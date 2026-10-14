"""Build a reviewed, private-data-minimal Colab Anima trial; never run locally.

Only ``build`` reads a local dataset. The ``remote-*`` commands are Linux/Colab
execution entrypoints contained in the generated, hash-pinned payload.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
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


def build_training_args(workspace: Path, config: dict) -> list[str]:
    models = {entry["role"]: str(workspace / entry["path"]) for entry in config["models"]["files"] if entry["role"] != "tokenizer"}
    command = [
        "--pretrained_model_name_or_path", models["dit"], "--vae", models["vae"], "--qwen3", models["qwen3"],
        "--dataset_config", str(workspace / "dataset.toml"), "--output_dir", str(workspace / "output/weights"),
        "--output_name", config["run_id"], "--network_module", "networks.lora_anima", "--network_dim", "32",
        "--network_alpha", "16", "--learning_rate", "2e-5", "--optimizer_type", "AdamW",
        "--lr_scheduler", "constant", "--timestep_sampling", "sigmoid", "--discrete_flow_shift", "1.0",
        "--max_train_steps", str(config["steps"]), "--save_every_n_steps", "25", "--mixed_precision", "bf16",
        "--save_precision", "bf16", "--save_model_as", "safetensors", "--seed", str(config["seed"]),
        "--max_data_loader_n_workers", "0", "--cache_latents", "--cache_latents_to_disk",
        "--cache_text_encoder_outputs", "--cache_text_encoder_outputs_to_disk", "--gradient_checkpointing",
        "--network_train_unet_only", "--attn_mode", "torch",
        "--save_state", "--save_state_on_train_end", "--log_with", "tensorboard", "--logging_dir", str(workspace / "output/tensorboard"),
    ]
    if config["qwen_image_vae_2d"]:
        command.append("--qwen_image_vae_2d")
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


def make_notebook(run_id: str, payload_name: str, payload_digest: str) -> dict:
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
    prepare = '''
subprocess.run([str(PYTHON), str(ROOT / "colab_trial.py"), "remote-prepare", "--workspace", str(ROOT)], check=True)
print("底模、tokenizer 和 BF16 GPU 检查通过，可进行 50/75 步管线测试")
'''
    training = '''
print("开始短训：Rank 32 / Alpha 16 / BF16 / Batch 1；每 25 步保留权重和续训状态")
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
    raise RuntimeError("短训未通过，失败日志已保留并提供下载")
print("短训完成；这只能证明远端训练管线和速度，角色质量需要后续出图比较")
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
            cell("markdown", "# Anima 远端短训\n先在「运行时 → 更改运行时类型」选 A100（或 L4 / H100 等支持 BF16 的 GPU）。这是 50/75 步管线测试，不是成品 LoRA。GPU 连接、安装、缓存和训练都可能消耗 Colab 额度。运行会下载公开底模，上传所选图文数据；无需授权 Google Drive。连接断开时未下载的临时文件可能丢失。"),
            cell("markdown", "## 1 · 上传本次资料包并核对文件"), cell("code", bootstrap),
            cell("markdown", "## 2 · 安装独立训练环境（首次较慢）"), cell("code", installation),
            cell("markdown", "## 3 · 下载底模并检查 GPU"), cell("code", prepare),
            cell("markdown", "## 4 · 运行短训并下载证据\n训练与缓存耗时会分别记录。此次关闭训练预览，比较本地速度时应比较梯度更新段，不能把不同设置的总时长当成严格对照。请保留结果 ZIP；短训完成后及时断开并删除 Colab 运行时。"), cell("code", training),
        ],
    }


def build_package(dataset_dir: Path, trigger_token: str, output_dir: Path, run_id: str,
                  model_manifest: dict, steps: int = 50, source_root: Path = SOURCE_ROOT,
                  tokenizer_files: dict[str, Path] | None = None, seed: int = 42,
                  qwen_image_vae_2d: bool = False) -> dict:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,79}", run_id):
        raise ValueError("Use a portable, unique run ID")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,79}", trigger_token):
        raise ValueError("Trigger token must be portable ASCII")
    if steps not in {50, 75}:
        raise ValueError("Trial steps must be 50 or 75")
    models = validate_model_manifest(model_manifest)
    source_root = Path(source_root).resolve()
    sources = reviewed_source_files(source_root)
    dataset, records = dataset_files(dataset_dir, trigger_token)
    extra_tokenizers = []
    for relative, path in (tokenizer_files or {}).items():
        path = Path(path)
        if relative not in CONFIG_FILES or path.is_symlink() or not path.is_file():
            raise ValueError("Extra tokenizer must be a regular allowlisted pure file")
        if (source_root / relative) in sources:
            raise ValueError("Extra tokenizer would overwrite reviewed source")
        extra_tokenizers.append(("trainer/" + relative, path.read_bytes()))
    available = {"trainer/" + path.relative_to(source_root).as_posix() for path in sources}
    available |= {entry["path"] for entry in models["files"]}
    available |= {name for name, data in extra_tokenizers}
    if not {"trainer/" + name for name in CONFIG_FILES} <= available:
        raise ValueError("Required pure tokenizer/config files are missing from source and download manifest")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    config = {"run_id": run_id, "trigger_token": trigger_token, "steps": steps, "seed": seed,
              "qwen_image_vae_2d": qwen_image_vae_2d, "resolution": 1024, "batch_size": 1,
              "models": models, "dataset": records, "scope": "pipeline-trial-not-release"}
    content = [("trainer/" + path.relative_to(source_root).as_posix(), path.read_bytes()) for path in sources]
    content.extend(extra_tokenizers)
    content.extend(("dataset/" + path.name, path.read_bytes()) for path in dataset)
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
    notebook.write_text(json.dumps(make_notebook(run_id, payload.name, digest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "payload_manifest.json").write_bytes(manifest_bytes)
    receipt = {"run_id": run_id, "image_count": len(records), "steps": steps, "payload": payload.name,
               "payload_sha256": digest, "payload_bytes": payload.stat().st_size, "notebook": notebook.name,
               "notebook_sha256": sha256(notebook), "local_training_started": False, "network_upload_started": False}
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


def remote_prepare(workspace: Path) -> None:
    import urllib.request
    import torch
    workspace = require_colab(workspace)
    output = workspace / "output"
    output.mkdir(exist_ok=False)
    config = json.loads((workspace / "trial_config.json").read_text(encoding="utf-8"))
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
    write_json(output / "prepare_timing.json", {"model_download_and_preflight_seconds": time.perf_counter() - started, "anima_blocks": blocks})
    timing = workspace / "dependency_install_timing.json"
    if timing.exists():
        write_json(output / timing.name, json.loads(timing.read_text()))


def remote_entry(workspace: Path) -> None:
    import math
    import torch
    workspace = require_colab(workspace)
    sys.path.insert(0, str(workspace / "trainer"))
    import anima_train_network as entry
    from library import train_util
    config = json.loads((workspace / "trial_config.json").read_text(encoding="utf-8"))
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
    config = json.loads((workspace / "trial_config.json").read_text())
    completed_steps = max((event["step"] or 0 for event in steps), default=0)
    if result == 0 and (not weights or failures or completed_steps < config["steps"]):
        result = 2
    elapsed = time.perf_counter() - started
    caches = {name: sum(event["seconds"] for event in events if event["event"] == label)
              for name, label in (("latent_cache_seconds", "latent_cache"), ("text_cache_seconds", "text_cache"))}
    training_seconds = ending.get("training_seconds")
    gradient_updates = [event for event in events if event["event"] == "gradient_update"]
    gradient_seconds = sum(event["seconds"] for event in gradient_updates)
    receipt = {"run_id": config["run_id"], "return_code": result, "completed_steps": completed_steps,
               "trainer_process_seconds": elapsed, **caches, "training_loop_and_saves_seconds": training_seconds,
               "model_and_trainer_setup_seconds": None if training_seconds is None else max(0, elapsed - training_seconds - sum(caches.values())),
               "steps_per_second_including_saves": None if not training_seconds else completed_steps / training_seconds,
               "gradient_update_seconds": gradient_seconds, "optimizer_updates": len(gradient_updates),
               "gradient_update_steps_per_second": None if not gradient_seconds else len(gradient_updates) / gradient_seconds,
               "gradient_timing_scope": "process_batch forward/backward/AdamW; CUDA synchronized; excludes fetch, setup, cache and saves",
               "peak_allocated_vram_bytes": ending.get("peak_allocated_vram_bytes"), "checkpoint_count": len(weights),
               "checkpoints": weights, "checkpoint_errors": failures, "loss_observations": len(steps),
               "quality_status": "not-evaluated-pipeline-trial-only"}
    write_json(output / "training_receipt.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != "checkpoints"}, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    build = subparsers.add_parser("build")
    for name in ("dataset-dir", "trigger-token", "output-dir", "run-id", "model-manifest"):
        build.add_argument("--" + name, required=True)
    build.add_argument("--steps", type=int, choices=(50, 75), default=50)
    build.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    build.add_argument("--t5-spiece", type=Path, help="Optional reviewed pure T5 spiece.model outside Git")
    build.add_argument("--seed", type=int, default=42)
    build.add_argument("--qwen-image-vae-2d", action="store_true")
    for action in ("remote-prepare", "remote-run", "remote-entry"):
        subparsers.add_parser(action).add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "build":
        result = build_package(Path(args.dataset_dir), args.trigger_token, Path(args.output_dir), args.run_id,
                               json.loads(Path(args.model_manifest).read_text(encoding="utf-8-sig")), args.steps, args.source_root,
                               {"configs/t5_old/spiece.model": args.t5_spiece} if args.t5_spiece else None,
                               args.seed, args.qwen_image_vae_2d)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "remote-prepare":
        remote_prepare(args.workspace)
    elif args.action == "remote-entry":
        remote_entry(args.workspace)
    else:
        raise SystemExit(remote_run(args.workspace))


if __name__ == "__main__":
    main()
