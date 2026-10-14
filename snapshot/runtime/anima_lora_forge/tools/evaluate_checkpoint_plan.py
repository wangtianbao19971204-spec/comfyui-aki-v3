"""Auditable, serial ComfyUI evaluation. Preparation never submits a GPU job.

Inputs, weights and generated evidence belong outside this source repository.
Only explicitly recorded temporary hard links are created in the model directory.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import struct
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}\Z")
HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
TEMPLATE = Path(__file__).resolve().parents[2] / "character_lora_forge/templates/anima_current_api.json"
CLASSES = ("UNETLoader", "CLIPLoader", "VAELoader", "LoraLoaderModelOnly",
           "ModelSamplingAuraFlow", "CLIPTextEncode", "EmptyLatentImage",
           "KSampler", "VAEDecode", "SaveImage")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def absolute(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return path.resolve()


def identifier(value: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe identifier: {value!r}")
    return value


def finite(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Invalid {label}")
    if not minimum <= value <= maximum:
        raise ValueError(f"Out-of-range {label}")
    return float(value)


def api(base: str, endpoint: str, value: Any = None, timeout: int = 90) -> Any:
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("Only a local unauthenticated ComfyUI HTTP endpoint is supported")
    body = None if value is None else json.dumps(value).encode("utf-8")
    request = urllib.request.Request(base.rstrip("/") + endpoint, data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def empty_queue(base: str) -> dict[str, Any]:
    queue = api(base, "/queue")
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI queue is not empty; no job was submitted or removed")
    if not isinstance(queue.get("queue_running"), list) or not isinstance(queue.get("queue_pending"), list):
        raise RuntimeError("Unrecognized ComfyUI queue response")
    return queue


def model_identity(spec: dict[str, Any], comfy: Path, role: str) -> dict[str, Any]:
    path = absolute(spec["path"], role)
    expected = spec["sha256"].lower()
    if not HASH.fullmatch(expected) or not path.is_file():
        raise ValueError(f"Missing model or invalid SHA: {role}")
    name = spec["name"]
    name_path = Path(name.replace("\\", "/"))
    if name_path.is_absolute() or ".." in name_path.parts:
        raise ValueError(f"Unsafe loader name: {role}")
    directories = {"dit": ("diffusion_models", "unet"),
                   "text_encoder": ("text_encoders", "clip"), "vae": ("vae",)}[role]
    if not any((comfy / "models" / directory / name_path).resolve() == path for directory in directories):
        raise ValueError(f"Loader name and audited path differ: {role}; external model roots are unsupported")
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"Model SHA mismatch: {role}")
    return {"path": str(path), "name": name, "sha256": actual, "bytes": path.stat().st_size}


def safetensors_identity(spec: dict[str, Any]) -> dict[str, Any]:
    path = absolute(spec["path"], "checkpoint")
    expected = spec["sha256"].lower()
    if not path.is_file() or path.suffix.lower() != ".safetensors" or not HASH.fullmatch(expected):
        raise ValueError("Missing checkpoint or invalid checkpoint SHA")
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"Checkpoint SHA mismatch: {spec['id']}")
    size = path.stat().st_size
    with path.open("rb") as stream:
        header_size = struct.unpack("<Q", stream.read(8))[0]
        if not 2 <= header_size <= min(16 * 1024 * 1024, size - 8):
            raise ValueError("Invalid safetensors header size")
        header = json.loads(stream.read(header_size))
    tensors = {key: val for key, val in header.items() if key != "__metadata__"}
    if not tensors:
        raise ValueError("Empty safetensors checkpoint")
    for tensor in tensors.values():
        offsets = tensor.get("data_offsets", [])
        if (len(offsets) != 2 or not all(type(x) is int for x in offsets)
                or not 0 <= offsets[0] <= offsets[1] <= size - 8 - header_size):
            raise ValueError("Invalid safetensors data offsets")
    return {"id": identifier(spec["id"]), "step": int(spec["step"]), "path": str(path),
            "sha256": actual, "bytes": size, "tensor_count": len(tensors)}


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema_version") != 1:
        raise ValueError("Unsupported plan schema")
    identifier(plan["run_id"])
    checkpoint_ids = [identifier(item["id"]) for item in plan["checkpoints"]]
    if not checkpoint_ids or len(set(checkpoint_ids)) != len(checkpoint_ids):
        raise ValueError("Checkpoint ids must be nonempty and unique")
    for key, prompt in plan["prompts"].items():
        identifier(key)
        if not isinstance(prompt.get("positive"), str) or not prompt["positive"].strip():
            raise ValueError("Missing positive prompt")
        negative = prompt.get("negative", plan.get("negative"))
        if not isinstance(negative, str):
            raise ValueError("Missing negative prompt")
    job_keys: set[str] = set()
    if not plan["jobs"]:
        raise ValueError("No evaluation jobs")
    for job in plan["jobs"]:
        key = identifier(job["job_key"])
        if key in job_keys or job["checkpoint_id"] not in checkpoint_ids or job["prompt_id"] not in plan["prompts"]:
            raise ValueError("Duplicate job or unknown checkpoint/prompt")
        job_keys.add(key)
        finite(job["strength"], "LoRA strength", 0, 2)
        if type(job["seed"]) is not int or not 0 <= job["seed"] < 2 ** 64:
            raise ValueError("Invalid seed")
    sample = plan["sampling"]
    for name in ("width", "height"):
        if type(sample[name]) is not int or sample[name] % 8 or not 64 <= sample[name] <= 4096:
            raise ValueError(f"Invalid {name}")
    if type(sample["steps"]) is not int or not 1 <= sample["steps"] <= 200:
        raise ValueError("Invalid sampling steps")
    finite(sample["cfg"], "cfg", 0, 30)
    finite(sample["shift"], "shift", 0.01, 100)


def build_graph(plan: dict[str, Any], checkpoints: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    original = read_json(TEMPLATE)["graph"]
    graph = {key: copy.deepcopy(original[key]) for key in ("2", "6", "10", "12", "13", "134", "165", "166", "167", "519")}
    graph["2"]["inputs"]["unet_name"] = plan["models"]["dit"]["name"]
    graph["165"]["inputs"]["clip_name"] = plan["models"]["text_encoder"]["name"]
    graph["166"]["inputs"]["vae_name"] = plan["models"]["vae"]["name"]
    prompt = plan["prompts"][job["prompt_id"]]
    graph["134"]["inputs"].update(text=prompt["positive"], clip=["165", 0])
    graph["6"]["inputs"].update(text=prompt.get("negative", plan.get("negative")), clip=["165", 0])
    graph["900010"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
        "model": ["2", 0], "lora_name": checkpoints[job["checkpoint_id"]]["loader_name"],
        "strength_model": job["strength"]}, "_meta": {"title": "Temporary audited evaluation LoRA"}}
    sample = plan["sampling"]
    graph["167"]["inputs"].update(model=["900010", 0], shift=sample["shift"])
    graph["519"]["inputs"].update(width=sample["width"], height=sample["height"], batch_size=1)
    graph["10"]["inputs"].update(seed=job["seed"], steps=sample["steps"], cfg=sample["cfg"],
                                  sampler_name=sample["sampler"], scheduler=sample["scheduler"],
                                  denoise=1.0, model=["167", 0], latent_image=["519", 0])
    graph["13"] = {"class_type": "SaveImage", "inputs": {"images": ["12", 0],
        "filename_prefix": f"temporary_anima_eval/{plan['run_id']}/{job['job_key']}"}}
    return graph


def object_info(base: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in CLASSES:
        info = api(base, "/object_info/" + urllib.parse.quote(name))
        if name not in info:
            raise RuntimeError(f"Required node unavailable: {name}")
        result.update(info)
    return result


def enum_check(info: dict[str, Any], node: str, field: str, value: Any) -> None:
    definition = info[node]["input"]["required"][field][0]
    if isinstance(definition, list) and value not in definition:
        raise ValueError(f"Loader/enum unavailable: {node}.{field}={value}")


def protected_source_roots() -> set[Path]:
    script = Path(__file__).resolve()
    runtime = script.parents[2]
    roots = {runtime}
    # Keep the managed source tree protected even in a copy without .git.
    if runtime.name.lower() == "runtime" and runtime.parent.name.lower() == "snapshot":
        roots.add(runtime.parent.parent)
    for ancestor in script.parents:
        if (ancestor / ".git").exists():
            roots.add(ancestor)
            break
    return roots


def prepare(plan_path: Path) -> Path:
    plan = read_json(plan_path)
    validate_plan(plan)
    comfy = absolute(plan["comfy_root"], "comfy_root")
    output = absolute(plan["output_root"], "output_root")
    protected = protected_source_roots() | {comfy}
    if any(output == root or root in output.parents for root in protected):
        raise ValueError("Evaluation output must be outside ComfyUI and the entire source repository/runtime")
    if output.exists():
        raise ValueError("output_root already exists; use a new immutable run id/output")
    base = plan.get("base_url", "http://127.0.0.1:8188")
    queue = empty_queue(base)
    info = object_info(base)
    models = {role: model_identity(plan["models"][role], comfy, role)
              for role in ("dit", "text_encoder", "vae")}
    for role, node, field in (("dit", "UNETLoader", "unet_name"),
                              ("text_encoder", "CLIPLoader", "clip_name"), ("vae", "VAELoader", "vae_name")):
        enum_check(info, node, field, models[role]["name"])
    enum_check(info, "KSampler", "sampler_name", plan["sampling"]["sampler"])
    enum_check(info, "KSampler", "scheduler", plan["sampling"]["scheduler"])
    checkpoint_list = [safetensors_identity(item) for item in plan["checkpoints"]]
    link_dir = comfy / "models/loras/_temporary_anima_eval" / plan["run_id"]
    if link_dir.exists():
        raise ValueError("Temporary LoRA directory already exists")
    output.mkdir(parents=True)
    write_json(output / "plan.json", plan)
    receipt: dict[str, Any] = {"schema_version": 1, "run_id": plan["run_id"], "prepared_at": timestamp(),
        "plan_source": str(plan_path), "plan_source_sha256": sha256(plan_path),
        "frozen_plan_sha256": sha256(output / "plan.json"), "runner_path": str(Path(__file__).resolve()),
        "runner_sha256": sha256(Path(__file__).resolve()), "template_path": str(TEMPLATE),
        "template_sha256": sha256(TEMPLATE), "models": models, "checkpoints": checkpoint_list,
        "link_directory": str(link_dir), "temporary_links": [], "gpu_submissions": 0,
        "purpose": "temporary-evaluation-input-not-installation", "status": "preparing"}
    write_json(output / "prepare_receipt.json", receipt)
    write_json(output / "object_info_prepare.json", info)
    write_json(output / "queue_prepare.json", queue)
    link_dir.mkdir(parents=True)
    for checkpoint in checkpoint_list:
        source = Path(checkpoint["path"])
        link = link_dir / (checkpoint["id"] + ".safetensors")
        os.link(source, link)
        entry = {"source_path": str(source), "link_path": str(link), "sha256": checkpoint["sha256"],
                 "bytes": checkpoint["bytes"], "same_file": os.path.samefile(source, link)}
        receipt["temporary_links"].append(entry)
        checkpoint["loader_name"] = str(link.relative_to(comfy / "models/loras"))
        write_json(output / "prepare_receipt.json", receipt)
    info = object_info(base)
    for checkpoint in checkpoint_list:
        enum_check(info, "LoraLoaderModelOnly", "lora_name", checkpoint["loader_name"])
    write_json(output / "object_info_linked.json", info)
    checkpoints = {item["id"]: item for item in checkpoint_list}
    graph_hashes = {}
    for job in plan["jobs"]:
        graph_path = output / "graphs" / (job["job_key"] + ".json")
        write_json(graph_path, build_graph(plan, checkpoints, job))
        graph_hashes[job["job_key"]] = sha256(graph_path)
    receipt.update(status="prepared", graph_sha256=graph_hashes, job_count=len(plan["jobs"]))
    write_json(output / "prepare_receipt.json", receipt)
    return output


def verify_frozen(output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = read_json(output / "prepare_receipt.json")
    if receipt["status"] != "prepared" or sha256(output / "plan.json") != receipt["frozen_plan_sha256"]:
        raise ValueError("Preparation incomplete or frozen plan changed")
    if sha256(Path(__file__).resolve()) != receipt["runner_sha256"] or sha256(TEMPLATE) != receipt["template_sha256"]:
        raise ValueError("Runner/template changed after preparation")
    plan = read_json(output / "plan.json")
    validate_plan(plan)
    if absolute(plan["output_root"], "output_root") != output:
        raise ValueError("Evaluation root was moved or changed")
    for model in receipt["models"].values():
        if sha256(Path(model["path"])) != model["sha256"]:
            raise ValueError("Base model identity changed after preparation")
    for entry in receipt["temporary_links"]:
        source, link = Path(entry["source_path"]), Path(entry["link_path"])
        if link.is_symlink() or not os.path.samefile(source, link) or sha256(link) != entry["sha256"]:
            raise ValueError("Temporary checkpoint identity changed")
    for job in plan["jobs"]:
        if sha256(output / "graphs" / (job["job_key"] + ".json")) != receipt["graph_sha256"][job["job_key"]]:
            raise ValueError("Prepared graph changed")
    return plan, receipt


def wait_for_history(base: str, prompt_id: str, path: Path, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = api(base, "/history/" + urllib.parse.quote(prompt_id))
        record = response.get(prompt_id)
        if record:
            write_json(path, record)
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI job failed: {prompt_id}; history preserved")
            if status.get("completed"):
                if status.get("status_str") != "success":
                    raise RuntimeError(f"ComfyUI job did not succeed: {prompt_id}")
                return record
        time.sleep(1.5)
    raise TimeoutError(f"Job timed out: {prompt_id}; user queue was not interrupted")


def retain_image(plan: dict[str, Any], job: dict[str, Any], record: dict[str, Any], destination: Path) -> dict[str, Any]:
    images = record.get("outputs", {}).get("13", {}).get("images", [])
    if len(images) != 1 or images[0].get("type") != "output":
        raise RuntimeError("Expected exactly one saved output image")
    image = images[0]
    expected_dir = f"temporary_anima_eval/{plan['run_id']}"
    if image.get("subfolder", "").replace("\\", "/") != expected_dir or not image["filename"].startswith(job["job_key"] + "_"):
        raise RuntimeError("Output image identity does not match the submitted job")
    root = absolute(plan["comfy_root"], "comfy_root") / "output"
    source = (root / image["subfolder"] / image["filename"]).resolve()
    if root.resolve() not in source.parents or source.suffix.lower() != ".png":
        raise ValueError("Unsafe output image path")
    with source.open("rb") as stream:
        header = stream.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise RuntimeError("Output is not a valid PNG header")
    dimensions = struct.unpack(">II", header[16:24])
    if dimensions != (plan["sampling"]["width"], plan["sampling"]["height"]):
        raise RuntimeError("Output dimensions differ from evaluation plan")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    image_hash = sha256(source)
    if sha256(destination) != image_hash:
        raise RuntimeError("Image copy hash mismatch")
    return {"runtime_output": str(source), "output_path": str(destination), "output_sha256": image_hash,
            "output_bytes": destination.stat().st_size, "width": dimensions[0], "height": dimensions[1]}


def execute(output: Path, limit: int | None, timeout: int) -> None:
    lock = output / ".execution.lock"
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    os.write(descriptor, f"pid={os.getpid()} utc={timestamp()}\n".encode())
    os.close(descriptor)
    try:
        plan, receipt = verify_frozen(output)
        base = plan.get("base_url", "http://127.0.0.1:8188")
        checkpoints = {item["id"]: item for item in receipt["checkpoints"]}
        manifest_path = output / "manifest.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else {
            "schema_version": 1, "run_id": plan["run_id"], "scope": "candidate-evaluation-not-release",
            "records": [], "status": "executing"}
        done = {entry["job_key"]: entry for entry in manifest["records"]}
        remaining = 0
        for job in plan["jobs"]:
            key = job["job_key"]
            if key in done:
                if sha256(Path(done[key]["output_path"])) != done[key]["output_sha256"]:
                    raise RuntimeError("Previously retained output changed")
                continue
            if limit is not None and remaining >= limit:
                break
            job_dir = output / "jobs" / key
            job_dir.mkdir(parents=True, exist_ok=True)
            submission_path = job_dir / "submission.json"
            submission = read_json(submission_path) if submission_path.exists() else None
            if submission and submission.get("state") == "post_started_unknown_result":
                raise RuntimeError(f"Ambiguous prior submission for {key}; inspect history before resubmitting")
            if submission is None:
                queue = empty_queue(base)
                write_json(job_dir / "queue_before.json", queue)
                write_json(job_dir / "system_stats_before.json", api(base, "/system_stats"))
                graph = read_json(output / "graphs" / (key + ".json"))
                request = {"prompt": graph, "client_id": str(uuid.uuid4())}
                write_json(job_dir / "request.json", request)
                submission = {"state": "post_started_unknown_result", "started_at": timestamp(),
                              "request_sha256": sha256(job_dir / "request.json")}
                write_json(submission_path, submission)
                response = api(base, "/prompt", request)
                write_json(job_dir / "response.json", response)
                if response.get("node_errors") or not response.get("prompt_id"):
                    submission.update(state="rejected", response=response)
                    write_json(submission_path, submission)
                    raise RuntimeError(f"ComfyUI rejected {key}; response preserved")
                submission.update(state="accepted", prompt_id=response["prompt_id"], accepted_at=timestamp())
                write_json(submission_path, submission)
            if submission.get("state") != "accepted":
                raise RuntimeError(f"Prior submission not resumable: {key}")
            prompt_id = submission["prompt_id"]
            history_path = job_dir / "history.json"
            record = wait_for_history(base, prompt_id, history_path, timeout)
            retained = retain_image(plan, job, record, output / "images" / (key + ".png"))
            entry = dict(job, **retained, comfy_prompt_id=prompt_id, completed_at=timestamp(),
                         checkpoint_sha256=checkpoints[job["checkpoint_id"]]["sha256"],
                         graph_sha256=receipt["graph_sha256"][key], history_sha256=sha256(history_path))
            manifest["records"].append(entry)
            manifest.update(status="executing", completed_count=len(manifest["records"]))
            write_json(manifest_path, manifest)
            write_json(job_dir / "system_stats_after.json", api(base, "/system_stats"))
            print(f"completed {len(manifest['records'])}/{len(plan['jobs'])} {key}", flush=True)
            remaining += 1
        manifest.update(status="completed" if len(manifest["records"]) == len(plan["jobs"]) else "partial",
                        stopped_at=timestamp())
        write_json(manifest_path, manifest)
    except Exception as error:
        write_json(output / "execution_error.json", {"time": timestamp(), "error_type": type(error).__name__,
            "message": str(error), "queue_interrupted": False, "automatic_resubmit": False})
        raise
    finally:
        lock.unlink()


def cleanup(output: Path) -> None:
    receipt = read_json(output / "prepare_receipt.json")
    plan = read_json(output / "plan.json")
    if (output / ".execution.lock").exists():
        raise RuntimeError("Execution is active; temporary inputs retained")
    empty_queue(plan.get("base_url", "http://127.0.0.1:8188"))
    comfy = absolute(plan["comfy_root"], "comfy_root")
    expected = (comfy / "models/loras/_temporary_anima_eval" / identifier(plan["run_id"])).resolve()
    if Path(receipt["link_directory"]).resolve() != expected:
        raise ValueError("Temporary directory identity mismatch")
    entries = receipt["temporary_links"]
    if expected.exists() and set(expected.iterdir()) != {Path(entry["link_path"]) for entry in entries}:
        raise ValueError("Unexpected temporary model directory contents; nothing removed")
    for entry in entries:
        link = Path(entry["link_path"])
        if link.parent.resolve() != expected or link.is_symlink() or not os.path.samefile(link, entry["source_path"]) or sha256(link) != entry["sha256"]:
            raise ValueError("Temporary link changed; nothing removed")
    for entry in entries:
        Path(entry["link_path"]).unlink()
    expected.rmdir()
    write_json(output / "temporary_inputs_cleanup_receipt.json", {"time": timestamp(), "removed_links": entries,
        "original_weights_retained": True, "images_retained": True, "models_not_installed": True})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    preparation = sub.add_parser("prepare", help="CPU/API preflight; create recorded temporary hard links")
    preparation.add_argument("--plan", type=Path, required=True)
    execution = sub.add_parser("execute", help="Explicit GPU submission; serial evaluation")
    execution.add_argument("--evaluation-root", type=Path, required=True)
    execution.add_argument("--limit", type=int, help="At most this many new jobs")
    execution.add_argument("--timeout", type=int, default=1200)
    removal = sub.add_parser("cleanup", help="Remove only recorded, unchanged temporary hard links")
    removal.add_argument("--evaluation-root", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        print(prepare(args.plan.resolve()))
    elif args.action == "execute":
        if args.limit is not None and args.limit <= 0 or args.timeout <= 0:
            parser.error("limit/timeout must be positive")
        execute(args.evaluation_root.resolve(), args.limit, args.timeout)
    else:
        cleanup(args.evaluation_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
