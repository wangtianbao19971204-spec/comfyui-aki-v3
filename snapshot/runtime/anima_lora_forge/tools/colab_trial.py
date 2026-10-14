"""Build a reviewed Colab Anima trial or calibration; never run locally.

Only ``build`` reads a local dataset. The ``remote-*`` commands are Linux/Colab
execution entrypoints contained in the generated, hash-pinned payload.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
from urllib.parse import urlparse, parse_qs
import zipfile

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "vendor/sd-trainer/SD-Trainer/vendor/sd-scripts"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
CONFIG_FILES = {
    "configs/qwen3_06b/config.json", "configs/qwen3_06b/tokenizer.json",
    "configs/qwen3_06b/tokenizer_config.json", "configs/qwen3_06b/vocab.json",
    "configs/qwen3_06b/merges.txt", "configs/t5_old/config.json",
    "configs/t5_old/tokenizer.json", "configs/t5_old/spiece.model",
}
# Trainer constraints come from the reviewed upstream requirements.txt. AdamW
# does not need the optional third-party optimizers or bitsandbytes.
DEPENDENCIES = [
    "torch==2.6.0", "torchvision==0.21.0", "accelerate==1.6.0",
    "transformers==4.54.1", "diffusers==0.32.1", "ftfy==6.3.1",
    "opencv-python==4.10.0.84", "einops==0.7.0", "tensorboard==2.19.0",
    "safetensors==0.4.5", "toml==0.10.2", "voluptuous==0.15.2",
    "huggingface-hub==0.34.3", "imagesize==1.4.1", "numpy==1.26.4",
    "rich==14.1.0", "sentencepiece==0.2.1", "Pillow==11.1.0",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract_payload(archive, destination, expected_sha256):
    """Verify the *entire* ZIP before extracting any member into a new tree."""
    import hashlib
    import json
    from pathlib import Path, PurePosixPath
    import stat
    import zipfile

    archive, destination = Path(archive), Path(destination)
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise ValueError("Payload ZIP SHA-256 mismatch")
    if destination.exists():
        raise ValueError("Extraction destination must be new")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 4000 or sum(item.file_size for item in members) > 2 * 1024**3:
            raise ValueError("Payload exceeds extraction limits")
        names = []
        for item in members:
            name = item.filename
            parts = PurePosixPath(name).parts
            if (not name or name.startswith("/") or "\\" in name or ":" in name
                    or "\x00" in name or ".." in parts or "." in name.split("/")
                    or "" in name.split("/") or item.is_dir()
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("Unsafe ZIP member")
            names.append(name)
        if len(set(name.casefold() for name in names)) != len(names):
            raise ValueError("Duplicate ZIP member")
        if names.count("payload_manifest.json") != 1:
            raise ValueError("Missing payload manifest")
        manifest = json.loads(bundle.read("payload_manifest.json"))
        entries = manifest["files"]
        if (len({entry["path"] for entry in entries}) != len(entries)
                or set(names) != {entry["path"] for entry in entries} | {"payload_manifest.json"}):
            raise ValueError("ZIP does not exactly match manifest")
        for entry in entries:
            info = bundle.getinfo(entry["path"])
            if info.file_size != entry["bytes"]:
                raise ValueError("Payload size mismatch")
            digest = hashlib.sha256()
            with bundle.open(info) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError("Payload file SHA-256 mismatch")
        # Exclusive file creation, no extractall and no pre-existing links.
        destination.mkdir(parents=True, exist_ok=False)
        for name in names:
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(name) as source, target.open("xb") as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(chunk)
    return manifest


def validate_model_manifest(raw: dict) -> dict:
    """Accept public, hash-pinned addresses, never local model paths/credentials."""
    if (not isinstance(raw, dict) or set(raw) != {"files", "expected_num_blocks"}
            or not isinstance(raw["files"], list) or raw["expected_num_blocks"] not in {28, 40}):
        raise ValueError("Model manifest requires files and expected_num_blocks (28 or 40)")
    result, roles, paths = [], [], set()
    for entry in raw["files"]:
        if set(entry) - {"role", "path", "url", "sha256", "bytes"}:
            raise ValueError("Unexpected model manifest fields")
        role, path, url, digest = (entry.get(key, "") for key in ("role", "path", "url", "sha256"))
        parsed = urlparse(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or any(key != "download" or values != ["true"]
                                          for key, values in parse_qs(parsed.query).items())):
            raise ValueError("Models require public HTTPS URLs without credentials")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise ValueError("Every remote file needs an exact SHA-256")
        if (not path or "\\" in path or ":" in path or path.startswith("/")
                or any(part in {"", ".", ".."} for part in path.split("/"))):
            raise ValueError("Model target must be a safe relative path")
        if role in {"dit", "vae", "qwen3"}:
            if len(PurePosixPath(path).parts) != 2 or not path.startswith("models/") or not path.endswith(".safetensors"):
                raise ValueError("Weights must target models/<name>.safetensors")
            roles.append(role)
        elif role == "tokenizer":
            if path not in {"trainer/" + name for name in CONFIG_FILES}:
                raise ValueError("Tokenizer targets must be explicitly allowed")
        else:
            raise ValueError("Unknown model role")
        if path.casefold() in paths:
            raise ValueError("Duplicate model target")
        paths.add(path.casefold())
        cleaned = {"role": role, "path": path, "url": url, "sha256": digest.lower()}
        if "bytes" in entry:
            if not isinstance(entry["bytes"], int) or entry["bytes"] <= 0:
                raise ValueError("Invalid remote file size")
            cleaned["bytes"] = entry["bytes"]
        result.append(cleaned)
    if sorted(roles) != ["dit", "qwen3", "vae"]:
        raise ValueError("Need exactly one DiT, VAE and Qwen3 weight")
    return {"expected_num_blocks": raw["expected_num_blocks"], "files": result}


def reviewed_source_files(source_root: Path) -> list[Path]:
    """Allowlist executable source families and exact pure tokenizer files."""
    source_root = source_root.resolve()
    result = []
    for path in sorted(source_root.rglob("*")):
        relative = path.relative_to(source_root)
        if path.is_symlink():
            raise ValueError("Source symlinks are not allowed")
        if not path.is_file():
            continue
        parts = relative.parts
        allowed_python = path.suffix == ".py" and (len(parts) == 1 or parts[0] in {"library", "networks", "pytorch_lightning"})
        if allowed_python and not any(part.startswith(".") or part in {"__pycache__", "cache", "env", "venv", "tests"} for part in parts):
            result.append(path)
        elif relative.as_posix() in CONFIG_FILES or relative.as_posix() == "LICENSE.md":
            result.append(path)
    for required in ("anima_train_network.py", "train_network.py", "library/anima_utils.py", "LICENSE.md"):
        if source_root / required not in result:
            raise ValueError("Reviewed trainer source is incomplete: " + required)
    if "infer_anima_num_blocks" not in (source_root / "library/anima_utils.py").read_text(encoding="utf-8"):
        raise ValueError("Trainer is missing the reviewed dynamic Anima block detector")
    return result


def dataset_files(dataset_dir: Path, trigger_token: str) -> tuple[list[Path], list[dict]]:
    from PIL import Image

    dataset_dir = dataset_dir.resolve()
    images = sorted(path for path in dataset_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    if not images:
        raise ValueError("Dataset has no images")
    stems, hashes, files, records = set(), set(), [], []
    for image in images:
        caption = image.with_suffix(".txt")
        if image.is_symlink() or caption.is_symlink() or not caption.is_file():
            raise ValueError("Every image requires a regular same-stem caption")
        if image.stem.casefold() in stems:
            raise ValueError("Ambiguous image stems")
        stems.add(image.stem.casefold())
        text = caption.read_text(encoding="utf-8-sig").strip()
        if not text or not re.match(re.escape(trigger_token) + r"(?:\s|,|$)", text):
            raise ValueError("Caption must start with the selected trigger token")
        digest = sha256(image)
        if digest in hashes:
            raise ValueError("Duplicate image bytes")
        hashes.add(digest)
        with Image.open(image) as opened:
            dimensions = list(opened.size)
            opened.verify()
        files.extend((image, caption))
        records.append({"image": image.name, "caption": caption.name, "size": dimensions, "image_sha256": digest, "caption_sha256": sha256(caption)})
    return files, records


def training_policy(mode: str, steps: int) -> dict:
    if mode == "trial" and steps in {50, 75}:
        return {"mode": mode, "steps": steps, "save_every_n_steps": 25, "scope": "pipeline-trial-not-release"}
    if mode == "calibration" and steps == 400:
        return {"mode": mode, "steps": steps, "save_every_n_steps": 100, "scope": "calibration-not-release"}
    if mode == "continuation" and steps in {600, 800, 1000}:
        return {"mode": mode, "steps": steps, "save_every_n_steps": 200, "scope": "continued-calibration-not-release"}
    raise ValueError("Trial requires 50/75 steps; calibration400; explicit continuation600/800/1000 with verified state")


RESUME_STATE_FILES = {"model.safetensors", "optimizer.bin", "scheduler.bin", "random_states_0.pkl", "train_state.json"}


def validate_resume_config(config: dict, workspace: Path | None = None) -> int:
    resume = config.get("resume")
    if config.get("mode") != "continuation":
        if resume is not None:
            raise ValueError("Resume requires explicit continuation mode")
        return 0
    if not isinstance(resume, dict) or set(resume) != {
        "source_run_id", "starting_step", "state_dir", "source_payload_sha256",
        "source_results_sha256", "parent_checkpoint_sha256", "state_files",
    }:
        raise ValueError("Continuation requires a complete immutable resume identity")
    start, source = resume["starting_step"], resume["source_run_id"]
    if (type(start) is not int or start not in {400, 600, 800} or start >= config["steps"]
            or not isinstance(source, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,79}", source)
            or source == config["run_id"]):
        raise ValueError("Invalid cumulative resume step or source run")
    expected_dir = f"resume/{source}-step{start:08d}-state"
    if resume["state_dir"] != expected_dir:
        raise ValueError("Resume state path must match its source and step")
    for name in ("source_payload_sha256", "source_results_sha256", "parent_checkpoint_sha256"):
        if not isinstance(resume[name], str) or not re.fullmatch(r"[a-f0-9]{64}", resume[name]):
            raise ValueError("Resume source requires exact archive/checkpoint hashes")
    entries = resume["state_files"]
    if (not isinstance(entries, list) or len(entries) != len(RESUME_STATE_FILES)
            or {entry.get("name") for entry in entries} != RESUME_STATE_FILES):
        raise ValueError("Resume must contain model, AdamW, scheduler, RNG and step state")
    for entry in entries:
        if (set(entry) != {"name", "bytes", "sha256"} or type(entry["bytes"]) is not int or entry["bytes"] <= 0
                or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])):
            raise ValueError("Invalid resume member identity")
        if workspace is not None:
            path = workspace / expected_dir / entry["name"]
            if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
                raise ValueError("Frozen resume state changed: " + entry["name"])
    if workspace is not None:
        state = json.loads((workspace / expected_dir / "train_state.json").read_text(encoding="utf-8"))
        if type(state.get("current_step")) is not int or state["current_step"] != start:
            raise ValueError("Saved state cumulative step disagrees with continuation")
    return start


def regular_zip_members(bundle: zipfile.ZipFile) -> dict:
    result = {}
    folded = set()
    import stat
    for item in bundle.infolist():
        name = item.filename
        if (not name or name.startswith("/") or "\\" in name or ":" in name or "\x00" in name
                or any(part in {"", ".", ".."} for part in name.split("/")) or item.is_dir()
                or stat.S_ISLNK(item.external_attr >> 16) or name.casefold() in folded):
            raise ValueError("Unsafe or duplicate resume source ZIP member")
        folded.add(name.casefold())
        result[name] = item
    if len(result) > 4000 or sum(item.file_size for item in result.values()) > 8 * 1024**3:
        raise ValueError("Resume source exceeds limits")
    return result


def collect_resume_inputs(payload: Path, payload_digest: str, results: Path, results_digest: str, step: int) -> tuple:
    """Read only hash-approved archives; never deserialize optimizer/RNG pickle locally."""
    for path, digest in ((payload, payload_digest), (results, results_digest)):
        if (path.is_symlink() or not path.is_file() or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or sha256(path) != digest):
            raise ValueError("Resume archive identity mismatch")
    with zipfile.ZipFile(payload) as bundle:
        members = regular_zip_members(bundle)
        manifest = json.loads(bundle.read("payload_manifest.json"))
        entries = manifest["files"]
        if (manifest.get("schema") != 1 or len({entry["path"] for entry in entries}) != len(entries)
                or set(members) != {entry["path"] for entry in entries} | {"payload_manifest.json"}):
            raise ValueError("Parent payload manifest mismatch")
        for entry in entries:
            data = bundle.read(entry["path"])
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("Parent frozen input changed")
        old_config = json.loads(bundle.read("trial_config.json"))
        if old_config["run_id"] != manifest["run_id"]:
            raise ValueError("Parent payload run mismatch")
        validate_training_policy(old_config)
        validate_resume_config(old_config)
    if old_config.get("mode") not in {"calibration", "continuation"} or step != old_config["steps"]:
        raise ValueError("Resume only a completed calibration endpoint")
    source = old_config["run_id"]
    prefix = f"weights/{source}-step{step:08d}-state/"
    with zipfile.ZipFile(results) as bundle:
        members = regular_zip_members(bundle)
        receipt = json.loads(bundle.read("training_receipt.json"))
        result_config = json.loads(bundle.read("trial_config.json"))
        if result_config != old_config:
            raise ValueError("Parent result configuration differs from its payload")
        parent_start = validate_resume_config(old_config)
        expected_updates = step - parent_start
        if (receipt.get("run_id") != source or receipt.get("return_code") != 0
                or receipt.get("completed_steps") != step or receipt.get("optimizer_updates") != expected_updates
                or receipt.get("loss_observations") != expected_updates
                or receipt.get("checkpoint_errors") or receipt.get("missing_checkpoints")):
            raise ValueError("Parent training did not pass completion gates")
        if old_config["mode"] == "continuation" and (
                receipt.get("resume_verified") is not True or receipt.get("step_sequence_valid") is not True):
            raise ValueError("Parent continuation lacks positive restore/step sequence evidence")
        names = {name[len(prefix):] for name in members if name.startswith(prefix)}
        if names != RESUME_STATE_FILES:
            raise ValueError("Selected state members are incomplete or unexpected")
        state_data = {name: bundle.read(prefix + name) for name in sorted(names)}
        saved = json.loads(state_data["train_state.json"])
        if type(saved.get("current_step")) is not int or saved["current_step"] != step:
            raise ValueError("Selected state has wrong cumulative step")
        checkpoint_name = f"weights/{source}-step{step:08d}.safetensors"
        checkpoint_data = bundle.read(checkpoint_name)
        checkpoint_digest = hashlib.sha256(checkpoint_data).hexdigest()
        matches = [entry for entry in receipt["checkpoints"] if entry["path"] == checkpoint_name]
        if (len(matches) != 1 or matches[0]["sha256"] != checkpoint_digest
                or matches[0]["bytes"] != len(checkpoint_data)
                or matches[0]["metadata"].get("ss_steps") != str(step)):
            raise ValueError("Parent checkpoint identity/step mismatch")
    state_dir = f"resume/{source}-step{step:08d}-state"
    resume = {"source_run_id": source, "starting_step": step, "state_dir": state_dir,
              "source_payload_sha256": payload_digest, "source_results_sha256": results_digest,
              "parent_checkpoint_sha256": checkpoint_digest,
              "state_files": [{"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                              for name, data in state_data.items()]}
    content = [(state_dir + "/" + name, data) for name, data in state_data.items()]
    provenance = {"source_config": old_config, "source_training_receipt": receipt,
                  "source_payload_manifest": manifest, "resume_identity": resume,
                  "pickle_deserialized_locally": False, "exact_uninterrupted_trajectory_claimed": False}
    content.append(("resume_provenance.json", (json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode()))
    return old_config, manifest, resume, content


def validate_training_policy(config: dict) -> dict:
    policy = training_policy(config.get("mode", "trial"), config["steps"])
    for name in ("save_every_n_steps", "scope"):
        if config.get(name, policy[name]) != policy[name] or (policy["mode"] == "calibration" and name not in config):
            raise ValueError("Frozen training mode/save/scope mismatch")
    return policy


def load_frozen_config(workspace: Path) -> dict:
    """Recheck approved package inputs; generated caches/output are separate."""
    workspace = workspace.resolve()
    manifest_path = workspace / "payload_manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Payload manifest must be a regular file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise ValueError("Unsupported payload manifest schema")
    entries = manifest["files"]
    names = [entry["path"] for entry in entries]
    if (len(entries) > 4000 or len(set(name.casefold() for name in names)) != len(names)
            or names.count("trial_config.json") != 1):
        raise ValueError("Invalid frozen input manifest")
    for entry in entries:
        relative = entry["path"]
        if (relative.startswith("/") or "\\" in relative or ":" in relative
                or any(part in {"", ".", ".."} for part in relative.split("/"))):
            raise ValueError("Unsafe frozen input path")
        path = workspace.joinpath(*PurePosixPath(relative).parts)
        if (not path.resolve().is_relative_to(workspace) or path.is_symlink()
                or any(parent.is_symlink() for parent in path.parents if parent != workspace and parent.is_relative_to(workspace))
                or not path.is_file() or path.stat().st_size != entry["bytes"]
                or sha256(path) != entry["sha256"]):
            raise ValueError("Frozen payload input changed: " + relative)
    config = json.loads((workspace / "trial_config.json").read_text(encoding="utf-8"))
    if config["run_id"] != manifest["run_id"] or config["run_id"] != workspace.name:
        raise ValueError("Workspace/config/manifest run IDs differ")
    validate_training_policy(config)
    validate_model_manifest(config["models"])
    validate_resume_config(config, workspace)
    return config


def build_training_args(workspace: Path, config: dict) -> list[str]:
    policy = validate_training_policy(config)
    models = {entry["role"]: str(workspace / entry["path"]) for entry in config["models"]["files"] if entry["role"] != "tokenizer"}
    command = [
        "--pretrained_model_name_or_path", models["dit"], "--vae", models["vae"], "--qwen3", models["qwen3"],
        "--dataset_config", str(workspace / "dataset.toml"), "--output_dir", str(workspace / "output/weights"),
        "--output_name", config["run_id"], "--network_module", "networks.lora_anima", "--network_dim", "32",
        "--network_alpha", "16", "--learning_rate", "2e-5", "--optimizer_type", "AdamW",
        "--lr_scheduler", "constant", "--timestep_sampling", "sigmoid", "--discrete_flow_shift", "1.0",
        "--max_train_steps", str(policy["steps"]), "--save_every_n_steps", str(policy["save_every_n_steps"]), "--mixed_precision", "bf16",
        "--save_precision", "bf16", "--save_model_as", "safetensors", "--seed", str(config["seed"]),
        "--max_data_loader_n_workers", "0", "--cache_latents", "--cache_latents_to_disk",
        "--cache_text_encoder_outputs", "--cache_text_encoder_outputs_to_disk", "--gradient_checkpointing",
        "--network_train_unet_only", "--attn_mode", "torch",
        "--save_state", "--save_state_on_train_end", "--log_with", "tensorboard", "--logging_dir", str(workspace / "output/tensorboard"),
    ]
    if config["qwen_image_vae_2d"]:
        command.append("--qwen_image_vae_2d")
    if validate_resume_config(config):
        command.extend(("--resume", str(workspace / config["resume"]["state_dir"]), "--skip_until_initial_step"))
    return command


def create_colab_venv(host_python, venv):
    """Bootstrap an isolated venv even when Colab omits working ensurepip."""
    from pathlib import Path
    import subprocess

    host_python, venv = str(host_python), Path(venv)
    python = venv / "bin/python"
    used_host_pip = False
    try:
        subprocess.run([host_python, "-m", "venv", str(venv)], check=True)
    except subprocess.CalledProcessError:
        # Reuse only the just-created venv tree; no delete, global installation
        # or system-site-packages fallback. Host pip targets the venv explicitly.
        subprocess.run([host_python, "-m", "venv", "--without-pip", str(venv)], check=True)
        pip_command = [host_python, "-m", "pip", "--isolated", "--python", str(python)]
        used_host_pip = True
    else:
        pip_command = [str(python), "-m", "pip", "--isolated"]
    subprocess.run(pip_command + ["install", "--index-url", "https://pypi.org/simple",
                                  "pip==25.0.1", "setuptools==75.8.0", "wheel==0.45.1"], check=True)
    return python, used_host_pip


def make_notebook(run_id: str, payload_name: str, payload_digest: str, mode: str = "trial", steps: int = 50,
                  starting_step: int = 0) -> dict:
    policy = training_policy(mode, steps)
    run_label = (f"从{starting_step}续至{steps}步校准" if mode == "continuation" else
                 "400 步校准" if mode == "calibration" else str(steps) + " 步短训")
    saved_steps = list(range(starting_step + policy["save_every_n_steps"], steps + 1, policy["save_every_n_steps"]))
    purpose = ("完成后须比较 " + "/".join(map(str, saved_steps)) + " 步检查点的角色质量"
               if mode in {"calibration", "continuation"} else "只验证训练管线和速度")
    start_message = f"开始{run_label}：Rank 32 / Alpha 16 / BF16 / Batch 1；每 {policy['save_every_n_steps']} 步保留权重和续训状态"
    finish_message = f"{run_label}完成；{purpose}，此时还不是通过质量验收的成品 LoRA"
    verifier = inspect.getsource(safe_extract_payload)
    bootstrap = "import sys, subprocess, time\nfrom pathlib import Path\nfrom google.colab import files\n" + verifier + f'''
if not (3, 10) <= sys.version_info[:2] <= (3, 12):
    raise RuntimeError("本训练依赖支持 Python 3.10–3.12，请切换受支持的 Colab 运行时")
print("请选择 {payload_name}，只上传本次批准的数据和训练源码")
uploaded = files.upload()
if set(uploaded) != {{{payload_name!r}}}:
    raise ValueError("请只上传本次对应的 payload ZIP")
PAYLOAD = Path({payload_name!r})
ROOT = Path("/content/anima_trial") / {run_id!r}
safe_extract_payload(PAYLOAD, ROOT, {payload_digest!r})
print("全部文件哈希核对通过；数据集保存在当前临时运行时")
'''
    installation = inspect.getsource(create_colab_venv) + '''
import json
started = time.perf_counter()
VENV = ROOT / "venv"
PYTHON, USED_HOST_PIP = create_colab_venv(sys.executable, VENV)
subprocess.run([str(PYTHON), "-m", "pip", "--isolated", "install", "--index-url", "https://pypi.org/simple", "-r", str(ROOT / "requirements-colab.txt")], check=True)
(ROOT / "dependency_install_timing.json").write_text(json.dumps({"dependency_install_seconds": time.perf_counter() - started, "used_host_pip_for_venv_bootstrap": USED_HOST_PIP}), encoding="utf-8")
print("独立训练环境已安装，下一步下载经过 SHA-256 固定的公开底模")
'''
    prepare = f'''
subprocess.run([str(PYTHON), str(ROOT / "colab_trial.py"), "remote-prepare", "--workspace", str(ROOT)], check=True)
print({("底模、tokenizer 和 BF16 GPU 检查通过，可进行" + run_label)!r})
'''
    training = f'''
print({start_message!r})
result = subprocess.run([str(PYTHON), "-u", str(ROOT / "colab_trial.py"), "remote-run", "--workspace", str(ROOT)])
OUTPUT = ROOT / "output"
RESULT_ZIP = ROOT.parent / (ROOT.name + "_results.zip")
with __import__("zipfile").ZipFile(RESULT_ZIP, "w", compression=__import__("zipfile").ZIP_DEFLATED) as bundle:
    for path in sorted(OUTPUT.rglob("*")):
        if path.is_file() and not path.is_symlink():
            bundle.write(path, path.relative_to(OUTPUT).as_posix())
print("结果包含日志、耗时、GPU 证据、检查点哈希及续训状态，请保存到自己的电脑")
files.download(str(RESULT_ZIP))
if result.returncode:
    raise RuntimeError({(run_label + "未通过，失败日志已保留并提供下载")!r})
print({finish_message!r})
'''
    def cell(kind, text):
        result = {"cell_type": kind, "metadata": {}, "source": text.strip().splitlines(keepends=True)}
        if kind == "code":
            result.update(execution_count=None, outputs=[])
        return result
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"colab": {"name": run_id + ".ipynb", "provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}, "accelerator": "GPU"},
        "cells": [
            cell("markdown", f"# Anima 远端{run_label}\n先在「运行时 → 更改运行时类型」选 A100（或 L4 / H100 等支持 BF16 的 GPU）。本次{purpose}，不是成品 LoRA。GPU 连接、安装、缓存和训练都可能消耗 Colab 额度。运行会下载公开底模，上传所选图文数据；无需授权 Google Drive。连接断开时未下载的临时文件可能丢失。"),
            cell("markdown", "## 1 · 上传本次资料包并核对文件"), cell("code", bootstrap),
            cell("markdown", "## 2 · 安装独立训练环境（首次较慢）"), cell("code", installation),
            cell("markdown", "## 3 · 下载底模并检查 GPU"), cell("code", prepare),
            cell("markdown", f"## 4 · 运行{run_label}并下载证据\n训练与缓存耗时会分别记录。此次关闭训练预览，比较本地速度时应比较梯度更新段，不能把不同设置的总时长当成严格对照。请保留结果 ZIP；{run_label}完成后及时断开并删除 Colab 运行时。"), cell("code", training),
        ],
    }


def build_package(dataset_dir: Path, trigger_token: str, output_dir: Path, run_id: str,
                  model_manifest: dict, steps: int = 50, source_root: Path = SOURCE_ROOT,
                  tokenizer_files: dict[str, Path] | None = None, seed: int = 42,
                  qwen_image_vae_2d: bool = False, mode: str = "trial",
                  resume_inputs: dict | None = None) -> dict:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,79}", run_id):
        raise ValueError("Use a portable, unique run ID")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,79}", trigger_token):
        raise ValueError("Trigger token must be portable ASCII")
    policy = training_policy(mode, steps)
    models = validate_model_manifest(model_manifest)
    source_root = Path(source_root).resolve()
    sources = reviewed_source_files(source_root)
    dataset, records = dataset_files(dataset_dir, trigger_token)
    resume, resume_content = None, []
    if mode == "continuation":
        if not resume_inputs:
            raise ValueError("Explicit continuation requires approved parent payload/results")
        old_config, old_manifest, resume, resume_content = collect_resume_inputs(**resume_inputs)
        if (old_config["run_id"] == run_id or old_config["dataset"] != records
                or old_config["models"] != models or old_config["seed"] != seed
                or old_config["trigger_token"] != trigger_token or old_config["qwen_image_vae_2d"] != qwen_image_vae_2d
                or old_config["resolution"] != 1024 or old_config["batch_size"] != 1):
            raise ValueError("Continuation must preserve source data, model, seed and training contract")
        validate_resume_config({"run_id": run_id, **policy, "resume": resume})
        prior_sources = {entry["path"]: entry["sha256"] for entry in old_manifest["files"] if entry["path"].startswith("trainer/")}
        current_sources = {"trainer/" + path.relative_to(source_root).as_posix(): sha256(path) for path in sources}
        # The reviewed counter fix is the only trainer-source change permitted.
        for name, digest in prior_sources.items():
            if name == "trainer/train_network.py" or name not in current_sources and name.startswith("trainer/configs/"):
                continue
            if current_sources.get(name) != digest:
                raise ValueError("Unreviewed trainer difference for continuation: " + name)
    elif resume_inputs is not None:
        raise ValueError("Resume sources require explicit continuation mode")
    extra_tokenizers = []
    for relative, path in (tokenizer_files or {}).items():
        path = Path(path)
        if relative not in CONFIG_FILES or path.is_symlink() or not path.is_file():
            raise ValueError("Extra tokenizer must be a regular allowlisted pure file")
        if (source_root / relative) in sources:
            raise ValueError("Extra tokenizer would overwrite reviewed source")
        extra_tokenizers.append(("trainer/" + relative, path.read_bytes()))
    if resume is not None:
        current_sources.update({name: hashlib.sha256(data).hexdigest() for name, data in extra_tokenizers})
        if set(prior_sources) != set(current_sources) or any(
            current_sources[name] != digest for name, digest in prior_sources.items() if name != "trainer/train_network.py"
        ):
            raise ValueError("Continuation trainer/tokenizer files differ beyond the reviewed counter fix")
    available = {"trainer/" + path.relative_to(source_root).as_posix() for path in sources}
    available |= {entry["path"] for entry in models["files"]}
    available |= {name for name, data in extra_tokenizers}
    if not {"trainer/" + name for name in CONFIG_FILES} <= available:
        raise ValueError("Required pure tokenizer/config files are missing from source and download manifest")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    config = {"run_id": run_id, "trigger_token": trigger_token, **policy, "seed": seed,
              "qwen_image_vae_2d": qwen_image_vae_2d, "resolution": 1024, "batch_size": 1,
              "models": models, "dataset": records}
    if resume is not None:
        config["resume"] = resume
    content = [("trainer/" + path.relative_to(source_root).as_posix(), path.read_bytes()) for path in sources]
    content.extend(extra_tokenizers)
    content.extend(("dataset/" + path.name, path.read_bytes()) for path in dataset)
    content.extend(resume_content)
    content.extend([
        ("colab_trial.py", Path(__file__).read_bytes()),
        ("trial_config.json", (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")),
        ("requirements-colab.txt", ("\n".join(DEPENDENCIES) + "\n").encode("utf-8")),
    ])
    manifest = {"schema": 1, "run_id": run_id, "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in content]}
    if len({entry["path"].casefold() for entry in manifest["files"]}) != len(content):
        raise ValueError("Payload paths collide")
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    payload = output_dir / (run_id + "_payload.zip")
    with zipfile.ZipFile(payload, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in content:
            bundle.writestr(name, data)
        bundle.writestr("payload_manifest.json", manifest_bytes)
    digest = sha256(payload)
    notebook = output_dir / (run_id + ".ipynb")
    notebook.write_text(json.dumps(make_notebook(run_id, payload.name, digest, mode, steps,
                                               resume["starting_step"] if resume else 0), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "payload_manifest.json").write_bytes(manifest_bytes)
    receipt = {"run_id": run_id, "image_count": len(records), **policy, "payload": payload.name,
               "payload_sha256": digest, "payload_bytes": payload.stat().st_size, "notebook": notebook.name,
               "notebook_sha256": sha256(notebook), "local_training_started": False, "network_upload_started": False}
    if resume is not None:
        receipt.update(starting_step=resume["starting_step"], expected_new_updates=steps - resume["starting_step"],
                       source_run_id=resume["source_run_id"], source_results_sha256=resume["source_results_sha256"])
    (output_dir / "package_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def require_colab(workspace: Path) -> Path:
    if sys.platform != "linux" or not Path("/content").is_dir():
        raise RuntimeError("Remote commands execute only in a Colab Linux runtime")
    workspace = workspace.resolve()
    if not workspace.is_relative_to(Path("/content/anima_trial")):
        raise ValueError("Workspace must be inside the isolated Colab trial tree")
    return workspace


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def restore_training_state(accelerator, args, loader, starting_step, torch_api, expected_parameters):
    """Require real AdamW/scheduler/RNG restoration before any new update."""
    import logging
    rng_evidence = []
    class RNGGuard(logging.Handler):
        def emit(self, event):
            message = event.getMessage()
            if "Could not load random states" in message:
                raise RuntimeError("Random state restoration failed; continuation stopped")
            if "All random states loaded successfully" in message:
                rng_evidence.append(message)
    logger = logging.getLogger("accelerate.checkpointing")
    guard, prior_level = RNGGuard(), logger.level
    logger.addHandler(guard)
    logger.setLevel(logging.INFO)
    try:
        loader(accelerator, args)
    finally:
        logger.removeHandler(guard)
        logger.setLevel(prior_level)
    if len(rng_evidence) != 1:
        raise RuntimeError("Random state restoration was not positively verified")
    optimizer_steps, rates = [], []
    for optimizer in accelerator._optimizers:
        rates.extend(float(group["lr"]) for group in optimizer.param_groups)
        for parameter, state in optimizer.state.items():
            if "step" not in state:
                raise RuntimeError("Restored optimizer parameter lacks step state")
            value = state["step"]
            optimizer_steps.append(float(value.item() if hasattr(value, "item") else value))
            for name in ("exp_avg", "exp_avg_sq"):
                if (name not in state or state[name].shape != parameter.shape
                        or not bool(torch_api.isfinite(state[name]).all())):
                    raise RuntimeError("Restored AdamW momentum is missing, nonfinite or has wrong shape")
    if (len(optimizer_steps) != expected_parameters or any(value != starting_step for value in optimizer_steps)
            or not rates or any(not math.isfinite(rate) or abs(rate - 2e-5) > 1e-12 for rate in rates)):
        raise RuntimeError("Restored AdamW count/step/LR does not match the approved continuation")
    scheduler_epochs = [getattr(scheduler.scheduler, "last_epoch", None) for scheduler in accelerator._schedulers]
    if len(scheduler_epochs) != 1 or scheduler_epochs[0] != starting_step:
        raise RuntimeError("Restored scheduler epoch does not match the source step")
    return {"starting_step": starting_step, "optimizer_state_count": len(optimizer_steps),
            "optimizer_step_min": min(optimizer_steps), "optimizer_step_max": max(optimizer_steps),
            "learning_rates": rates, "scheduler_last_epochs": scheduler_epochs,
            "rng_restore_verified": True, "adamw_momentum_finite": True}


def remote_prepare(workspace: Path) -> None:
    workspace = require_colab(workspace)
    config = load_frozen_config(workspace)
    import urllib.request
    import torch
    output = workspace / "output"
    output.mkdir(exist_ok=False)
    models = validate_model_manifest(config["models"])
    started = time.perf_counter()
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("Need a BF16 CUDA GPU, e.g. A100/L4/H100; T4 is unsupported")
    gpu = torch.cuda.get_device_properties(0)
    environment = {"python": sys.version, "torch": torch.__version__, "torch_cuda": torch.version.cuda,
                   "gpu": gpu.name, "gpu_vram_bytes": gpu.total_memory, "compute_capability": list(torch.cuda.get_device_capability()),
                   "bf16_supported": True, "dependencies": subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True).splitlines()}
    write_json(output / "environment.json", environment)
    print(f"GPU: {gpu.name}, VRAM {gpu.total_memory / 1024**3:.1f} GiB, BF16 supported", flush=True)
    downloads = []
    for entry in models["files"]:
        target = workspace / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        file_started = time.perf_counter()
        if target.exists() and sha256(target) == entry["sha256"]:
            pass
        else:
            partial = target.with_suffix(target.suffix + ".part")
            request = urllib.request.Request(entry["url"], headers={"User-Agent": "Anima-Colab-Trial/1.0"})
            print("Downloading " + entry["path"], flush=True)
            digest, count = hashlib.sha256(), 0
            with urllib.request.urlopen(request, timeout=120) as source, partial.open("wb") as dest:
                for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
                    dest.write(chunk)
                    digest.update(chunk)
                    count += len(chunk)
            if digest.hexdigest() != entry["sha256"] or ("bytes" in entry and count != entry["bytes"]):
                raise RuntimeError("Downloaded model/tokenizer checksum mismatch: " + entry["path"])
            partial.replace(target)
        downloads.append({"path": entry["path"], "sha256": sha256(target), "bytes": target.stat().st_size, "seconds": time.perf_counter() - file_started})
    write_json(output / "model_downloads.json", downloads)
    # Verify the manifest-defined model depth before loading tensor weights.
    sys.path.insert(0, str(workspace / "trainer"))
    from library.anima_utils import infer_anima_num_blocks
    dit = next(workspace / entry["path"] for entry in models["files"] if entry["role"] == "dit")
    blocks = infer_anima_num_blocks(str(dit))
    if blocks != models["expected_num_blocks"]:
        raise RuntimeError(f"Anima block mismatch: expected {models['expected_num_blocks']}, detected {blocks}")
    dataset_config = f'''[general]
caption_extension = ".txt"
shuffle_caption = false
keep_tokens = 1

[[datasets]]
resolution = 1024
batch_size = 1
enable_bucket = true
bucket_no_upscale = true
min_bucket_reso = 512
max_bucket_reso = 1536
bucket_reso_steps = 64

[[datasets.subsets]]
image_dir = {json.dumps(str(workspace / "dataset"))}
num_repeats = 1
'''
    (workspace / "dataset.toml").write_text(dataset_config, encoding="utf-8")
    (output / "dataset.toml").write_text(dataset_config, encoding="utf-8")
    write_json(output / "trial_config.json", config)
    write_json(output / "prepare_timing.json", {"model_download_and_preflight_seconds": time.perf_counter() - started,
                                               "anima_blocks": blocks, "dataset_config_sha256": sha256(workspace / "dataset.toml")})
    timing = workspace / "dependency_install_timing.json"
    if timing.exists():
        write_json(output / timing.name, json.loads(timing.read_text()))


def remote_entry(workspace: Path) -> None:
    workspace = require_colab(workspace)
    config = load_frozen_config(workspace)
    import math
    import torch
    sys.path.insert(0, str(workspace / "trainer"))
    import anima_train_network as entry
    from library import train_util
    telemetry = workspace / "output/telemetry.jsonl"
    started, first_step, batch_started = time.perf_counter(), None, None
    torch.set_num_threads(2)

    def record(event, **data):
        with telemetry.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": event, "elapsed_seconds": time.perf_counter() - started, **data}, allow_nan=False) + "\n")
    def timed_method(owner, name, event):
        original = getattr(owner, name)
        def wrapped(*args, **kwargs):
            begin = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                record(event, seconds=time.perf_counter() - begin)
        setattr(owner, name, wrapped)
    starting_step = validate_resume_config(config, workspace)
    if starting_step:
        original_resume = train_util.resume_from_local_or_hf_if_specified
        def verified_resume(accelerator, args):
            if accelerator.num_processes != 1 or args.gradient_accumulation_steps != 1:
                raise RuntimeError("Continuation requires the verified single-GPU batch1 contract")
            record("resume_start", source_run_id=config["resume"]["source_run_id"], starting_step=starting_step,
                   state_dir=config["resume"]["state_dir"])
            evidence = restore_training_state(accelerator, args, original_resume, starting_step, torch,
                                              config["models"]["expected_num_blocks"] * 20)
            record("resume_loaded", **evidence)
        train_util.resume_from_local_or_hf_if_specified = verified_resume
    timed_method(train_util.DatasetGroup, "new_cache_latents", "latent_cache")
    timed_method(entry.AnimaNetworkTrainer, "cache_text_encoder_outputs_if_needed", "text_cache")
    original_process = entry.AnimaNetworkTrainer.process_batch
    def process(self, *args, **kwargs):
        nonlocal first_step, batch_started
        if first_step is None:
            first_step = time.perf_counter()
            torch.cuda.reset_peak_memory_stats()
            record("training_start")
        batch_started = time.perf_counter()
        loss = original_process(self, *args, **kwargs)
        if not bool(torch.isfinite(loss).all()):
            raise RuntimeError("Non-finite training loss; trial stopped")
        return loss
    entry.AnimaNetworkTrainer.process_batch = process
    original_optimizer_step = torch.optim.AdamW.step
    def optimizer_step(self, *args, **kwargs):
        value = original_optimizer_step(self, *args, **kwargs)
        # This measurement covers forward/backward/AdamW and excludes checkpoint
        # saves and caching. Synchronization makes asynchronous CUDA time honest.
        torch.cuda.synchronize()
        record("gradient_update", seconds=time.perf_counter() - batch_started)
        return value
    torch.optim.AdamW.step = optimizer_step
    original_log = entry.AnimaNetworkTrainer.step_logging
    def log(self, accelerator, values, global_step, epoch):
        if "loss/current" in values:
            loss = float(values["loss/current"])
            if not math.isfinite(loss):
                raise RuntimeError("Non-finite training loss")
            elapsed = time.perf_counter() - first_step
            record("step", step=global_step, loss=loss, average_loss=float(values["loss/average"]),
                   train_elapsed_seconds=elapsed, peak_allocated_vram_bytes=torch.cuda.max_memory_allocated(),
                   allocated_vram_bytes=torch.cuda.memory_allocated())
        return original_log(self, accelerator, values, global_step, epoch)
    entry.AnimaNetworkTrainer.step_logging = log
    parser = entry.setup_parser()
    args = parser.parse_args(build_training_args(workspace, config))
    train_util.verify_command_line_training_args(args)
    args = train_util.read_config_from_file(args, parser)
    record("entry_start", arguments=build_training_args(workspace, config))
    try:
        entry.AnimaNetworkTrainer().train(args)
    finally:
        record("entry_end", training_seconds=None if first_step is None else time.perf_counter() - first_step,
               peak_allocated_vram_bytes=torch.cuda.max_memory_allocated())


def checkpoint_record(path: Path, output: Path) -> dict:
    import struct
    with path.open("rb") as handle:
        size_bytes = handle.read(8)
        if len(size_bytes) != 8:
            raise ValueError("Truncated safetensors header")
        header_size = struct.unpack("<Q", size_bytes)[0]
        if header_size > 64 * 1024**2 or header_size + 8 > path.stat().st_size:
            raise ValueError("Invalid safetensors header length")
        header = json.loads(handle.read(header_size))
    tensors = {name: value for name, value in header.items() if name != "__metadata__"}
    if not tensors:
        raise ValueError("Checkpoint has no tensors")
    return {"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path),
            "tensor_count": len(tensors), "dtypes": sorted({value["dtype"] for value in tensors.values()}),
            "metadata": header.get("__metadata__", {})}


def remote_run(workspace: Path) -> int:
    workspace = require_colab(workspace)
    output = workspace / "output"
    if not (output / "prepare_timing.json").is_file():
        raise RuntimeError("Complete remote-prepare before training")
    if (output / "training_receipt.json").exists():
        raise RuntimeError("Use a new run ID instead of overwriting trial evidence")
    config = load_frozen_config(workspace)
    prepared_config = json.loads((output / "trial_config.json").read_text(encoding="utf-8"))
    if prepared_config != config:
        raise ValueError("Prepared config differs from frozen payload; use a new run ID")
    preparation = json.loads((output / "prepare_timing.json").read_text(encoding="utf-8"))
    dataset_config = workspace / "dataset.toml"
    if (dataset_config.is_symlink() or sha256(dataset_config) != preparation.get("dataset_config_sha256")
            or dataset_config.read_bytes() != (output / "dataset.toml").read_bytes()):
        raise ValueError("Prepared dataset configuration changed; use a new run ID")
    started = time.perf_counter()
    command = [sys.executable, "-u", str(workspace / "colab_trial.py"), "remote-entry", "--workspace", str(workspace)]
    env = os.environ.copy()
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false"})
    # No shell, credentials, Drive mount, local trainer or mutable GUI config.
    with (output / "training.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=workspace / "trainer", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        result = process.wait()
    events = []
    if (output / "telemetry.jsonl").exists():
        events = [json.loads(line) for line in (output / "telemetry.jsonl").read_text().splitlines() if line]
    steps = [event for event in events if event["event"] == "step"]
    ending = next((event for event in reversed(events) if event["event"] == "entry_end"), {})
    weights, failures = [], []
    for path in sorted((output / "weights").glob("*.safetensors")):
        try:
            weights.append(checkpoint_record(path, output))
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            failures.append({"path": path.name, "error": str(error)})
    starting_step = validate_resume_config(config, workspace)
    expected_updates = config["steps"] - starting_step
    completed_steps = max((event["step"] or 0 for event in steps), default=starting_step)
    policy = validate_training_policy(config)
    required_weights = {f"{config['run_id']}-step{step:08d}.safetensors"
                        for step in range(starting_step + policy["save_every_n_steps"], config["steps"] + 1, policy["save_every_n_steps"])}
    required_weights.add(config["run_id"] + ".safetensors")
    missing_weights = sorted(required_weights - {Path(weight["path"]).name for weight in weights})
    gradient_updates = [event for event in events if event["event"] == "gradient_update"]
    actual_step_sequence = [event["step"] for event in steps]
    sequence_valid = actual_step_sequence == list(range(starting_step + 1, config["steps"] + 1))
    resume_events = [event for event in events if event["event"] == "resume_loaded"]
    resume_verified = not starting_step or (len(resume_events) == 1 and resume_events[0].get("starting_step") == starting_step
                                            and resume_events[0].get("optimizer_step_min") == starting_step
                                            and resume_events[0].get("optimizer_step_max") == starting_step
                                            and resume_events[0].get("rng_restore_verified") is True
                                            and resume_events[0].get("adamw_momentum_finite") is True
                                            and resume_events[0].get("optimizer_state_count") == config["models"]["expected_num_blocks"] * 20
                                            and resume_events[0].get("scheduler_last_epochs") == [starting_step])
    if result == 0 and (failures or missing_weights or completed_steps != config["steps"]
                        or len(steps) != expected_updates or len(gradient_updates) != expected_updates
                        or not sequence_valid or not resume_verified):
        result = 2
    elapsed = time.perf_counter() - started
    caches = {name: sum(event["seconds"] for event in events if event["event"] == label)
              for name, label in (("latent_cache_seconds", "latent_cache"), ("text_cache_seconds", "text_cache"))}
    training_seconds = ending.get("training_seconds")
    gradient_seconds = sum(event["seconds"] for event in gradient_updates)
    receipt = {"run_id": config["run_id"], **validate_training_policy(config), "return_code": result, "completed_steps": completed_steps,
               "starting_step": starting_step, "expected_new_updates": expected_updates,
               "step_sequence_valid": sequence_valid, "resume_verified": resume_verified,
               "trainer_process_seconds": elapsed, **caches, "training_loop_and_saves_seconds": training_seconds,
               "model_and_trainer_setup_seconds": None if training_seconds is None else max(0, elapsed - training_seconds - sum(caches.values())),
               "steps_per_second_including_saves": None if not training_seconds else len(gradient_updates) / training_seconds,
               "gradient_update_seconds": gradient_seconds, "optimizer_updates": len(gradient_updates),
               "gradient_update_steps_per_second": None if not gradient_seconds else len(gradient_updates) / gradient_seconds,
               "gradient_timing_scope": "process_batch forward/backward/AdamW; CUDA synchronized; excludes fetch, setup, cache and saves",
               "peak_allocated_vram_bytes": ending.get("peak_allocated_vram_bytes"), "checkpoint_count": len(weights),
               "checkpoints": weights, "checkpoint_errors": failures, "loss_observations": len(steps),
               "missing_checkpoints": missing_weights,
               "quality_status": "not-evaluated-calibration-only" if config.get("mode") in {"calibration", "continuation"} else "not-evaluated-pipeline-trial-only"}
    if starting_step:
        receipt["resume_identity"] = config["resume"]
        receipt["resume_load_evidence"] = resume_events
    write_json(output / "training_receipt.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != "checkpoints"}, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    build = subparsers.add_parser("build")
    for name in ("dataset-dir", "trigger-token", "output-dir", "run-id", "model-manifest"):
        build.add_argument("--" + name, required=True)
    build.add_argument("--mode", choices=("trial", "calibration", "continuation"), default="trial")
    build.add_argument("--steps", type=int, choices=(50, 75, 400, 600, 800, 1000), default=50,
                       help="Trial50/75; calibration400/save100; verified continuation600/800/1000/save200")
    build.add_argument("--resume-payload", type=Path)
    build.add_argument("--resume-payload-sha256")
    build.add_argument("--resume-results", type=Path)
    build.add_argument("--resume-results-sha256")
    build.add_argument("--resume-step", type=int)
    build.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    build.add_argument("--t5-spiece", type=Path, help="Optional reviewed pure T5 spiece.model outside Git")
    build.add_argument("--seed", type=int, default=42)
    build.add_argument("--qwen-image-vae-2d", action="store_true")
    for action in ("remote-prepare", "remote-run", "remote-entry"):
        subparsers.add_parser(action).add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "build":
        resume_values = (args.resume_payload, args.resume_payload_sha256, args.resume_results, args.resume_results_sha256, args.resume_step)
        resume_inputs = None
        if any(value is not None for value in resume_values):
            if not all(value is not None for value in resume_values):
                parser.error("All five --resume-* identity arguments are required together")
            resume_inputs = dict(payload=args.resume_payload, payload_digest=args.resume_payload_sha256,
                                 results=args.resume_results, results_digest=args.resume_results_sha256, step=args.resume_step)
        result = build_package(Path(args.dataset_dir), args.trigger_token, Path(args.output_dir), args.run_id,
                               json.loads(Path(args.model_manifest).read_text(encoding="utf-8-sig")), args.steps, args.source_root,
                               {"configs/t5_old/spiece.model": args.t5_spiece} if args.t5_spiece else None,
                               args.seed, args.qwen_image_vae_2d, args.mode, resume_inputs)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "remote-prepare":
        remote_prepare(args.workspace)
    elif args.action == "remote-entry":
        remote_entry(args.workspace)
    else:
        raise SystemExit(remote_run(args.workspace))


if __name__ == "__main__":
    main()
