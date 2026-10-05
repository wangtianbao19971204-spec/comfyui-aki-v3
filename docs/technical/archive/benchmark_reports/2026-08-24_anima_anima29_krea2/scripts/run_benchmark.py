from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import psutil
import requests
from PIL import Image


SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = BENCHMARK_ROOT / "benchmark_config.json"
RAW_DIR = BENCHMARK_ROOT / "raw"
RESULTS_PATH = RAW_DIR / "results.jsonl"
CSV_PATH = RAW_DIR / "results.csv"
PROMPT_DIR = RAW_DIR / "api_prompts"
HISTORY_DIR = RAW_DIR / "history"
TELEMETRY_DIR = RAW_DIR / "telemetry"
COMFY_ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI")
COMFY_OUTPUT = COMFY_ROOT / "output"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.")
    return cleaned[:180] or "job"


def find_comfy_process() -> psutil.Process | None:
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            command = " ".join(process.info.get("cmdline") or [])
            if "ComfyUI" in command and "main.py" in command:
                return process
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return None


def parse_number(value: str) -> float | None:
    value = value.strip()
    if not value or value.upper() in {"N/A", "[N/A]"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def query_resources(comfy_process: psutil.Process | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "timestamp": time.time(),
        "gpu_memory_mb": None,
        "gpu_util_percent": None,
        "gpu_power_w": None,
        "gpu_temp_c": None,
        "comfy_rss_mb": None,
        "system_available_mb": round(psutil.virtual_memory().available / 1024**2, 1),
    }
    try:
        command = [
            "nvidia-smi",
            "--query-gpu=memory.used,utilization.gpu,power.draw,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
            check=True,
        )
        values = [parse_number(part) for part in completed.stdout.strip().split(",")]
        if len(values) >= 4:
            result["gpu_memory_mb"] = values[0]
            result["gpu_util_percent"] = values[1]
            result["gpu_power_w"] = values[2]
            result["gpu_temp_c"] = values[3]
    except (OSError, subprocess.SubprocessError):
        pass
    if comfy_process is not None:
        try:
            result["comfy_rss_mb"] = round(
                comfy_process.memory_info().rss / 1024**2, 1
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
    return result


class ResourceMonitor:
    def __init__(self, interval: float = 0.5) -> None:
        self.interval = interval
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process = find_comfy_process()

    def start(self) -> None:
        self.samples = []
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples.append(query_resources(self._process))
            self._stop.wait(self.interval)

    def summary(self) -> dict[str, Any]:
        def available(key: str) -> list[float]:
            return [
                float(sample[key])
                for sample in self.samples
                if sample.get(key) is not None
            ]

        summary: dict[str, Any] = {"sample_count": len(self.samples)}
        for key in (
            "gpu_memory_mb",
            "gpu_util_percent",
            "gpu_power_w",
            "gpu_temp_c",
            "comfy_rss_mb",
            "system_available_mb",
        ):
            values = available(key)
            summary[f"{key}_min"] = min(values) if values else None
            summary[f"{key}_max"] = max(values) if values else None
            summary[f"{key}_mean"] = (
                round(sum(values) / len(values), 3) if values else None
            )
        return summary


class ComfyClient:
    def __init__(self, server: str, timeout: int = 900) -> None:
        self.server = server.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.client_id = f"codex-benchmark-{uuid.uuid4()}"
        self.comfy_process = find_comfy_process()

    def get_json(self, route: str) -> Any:
        response = self.session.get(f"{self.server}{route}", timeout=30)
        response.raise_for_status()
        return response.json()

    def post_json(self, route: str, payload: dict[str, Any]) -> Any:
        response = self.session.post(
            f"{self.server}{route}", json=payload, timeout=60
        )
        response.raise_for_status()
        if response.content:
            try:
                return response.json()
            except requests.JSONDecodeError:
                return {"text": response.text}
        return {}

    def wait_idle(self, timeout: int = 900) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            queue = self.get_json("/queue")
            running = queue.get("queue_running") or []
            pending = queue.get("queue_pending") or []
            if not running and not pending:
                return
            time.sleep(1)
        raise TimeoutError("ComfyUI queue did not become idle.")

    def unload_models(self) -> dict[str, Any]:
        self.wait_idle()
        before = query_resources(self.comfy_process)
        started = time.perf_counter()
        self.post_json("/free", {"unload_models": True, "free_memory": True})
        time.sleep(2)
        samples = [query_resources(self.comfy_process)]
        for _ in range(12):
            time.sleep(0.5)
            samples.append(query_resources(self.comfy_process))
            recent = [
                sample.get("gpu_memory_mb")
                for sample in samples[-3:]
                if sample.get("gpu_memory_mb") is not None
            ]
            if len(recent) == 3 and max(recent) - min(recent) <= 32:
                break
        after = samples[-1]
        return {
            "duration_s": round(time.perf_counter() - started, 3),
            "before": before,
            "after": after,
            "samples": samples,
        }

    def submit_and_wait(self, prompt: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        response = self.post_json(
            "/prompt", {"prompt": prompt, "client_id": self.client_id}
        )
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI rejected prompt: {response}")
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            history = self.get_json(f"/history/{prompt_id}")
            if prompt_id in history:
                return prompt_id, history[prompt_id]
            time.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for prompt {prompt_id}")


def build_prompt(
    model_key: str,
    model: dict[str, Any],
    case: dict[str, Any],
    output_prefix: str,
    negative: str,
    steps_override: int | None = None,
) -> dict[str, Any]:
    steps = int(steps_override or model["steps"])
    seed = int(case["seed"])
    width = int(case["width"])
    height = int(case["height"])
    positive = case["prompt"]
    latent_class = model["latent_class"]

    if model["builder"] == "anima_native":
        prompt = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": model["unet"],
                    "weight_dtype": "default",
                },
            },
            "2": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": model["clip"],
                    "type": model["clip_type"],
                    "device": "default",
                },
            },
            "3": {
                "class_type": "ModelSamplingAuraFlow",
                "inputs": {"model": ["1", 0], "shift": float(model["shift"])},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": positive},
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": negative},
            },
            "6": {
                "class_type": latent_class,
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "7": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["3", 0],
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "latent_image": ["6", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": float(model["cfg"]),
                    "sampler_name": model["sampler"],
                    "scheduler": model["scheduler"],
                    "denoise": 1.0,
                },
            },
        }
    elif model["builder"] == "anima_38b":
        prompt = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": model["unet"],
                    "weight_dtype": "default",
                },
            },
            "2": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": model["native_clip"],
                    "type": "stable_diffusion",
                    "device": "default",
                },
            },
            "3": {
                "class_type": "AnimaQwen35Loader",
                "inputs": {"qwen35_model": model["qwen35_clip"]},
            },
            "4": {
                "class_type": "AnimaQwen35UnifiedPrompt",
                "inputs": {
                    "model": ["1", 0],
                    "native_clip": ["2", 0],
                    "qwen35_clip": ["3", 0],
                    "adapter_name": model["adapter"],
                    "prompt": positive,
                    "adapter_strength": float(model["adapter_strength"]),
                },
            },
            "5": {
                "class_type": "AnimaQwen35UnifiedPrompt",
                "inputs": {
                    "model": ["1", 0],
                    "native_clip": ["2", 0],
                    "qwen35_clip": ["3", 0],
                    "adapter_name": model["adapter"],
                    "prompt": negative,
                    "adapter_strength": float(model["adapter_strength"]),
                },
            },
            "6": {
                "class_type": latent_class,
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "7": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "latent_image": ["6", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": float(model["cfg"]),
                    "sampler_name": model["sampler"],
                    "scheduler": model["scheduler"],
                    "denoise": 1.0,
                },
            },
        }
    elif model["builder"] == "krea2":
        prompt = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": model["unet"],
                    "weight_dtype": "default",
                },
            },
            "2": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": model["clip"],
                    "type": model["clip_type"],
                    "device": "default",
                },
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": positive},
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": negative},
            },
            "6": {
                "class_type": latent_class,
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "7": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "latent_image": ["6", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": float(model["cfg"]),
                    "sampler_name": model["sampler"],
                    "scheduler": model["scheduler"],
                    "denoise": 1.0,
                },
            },
        }
    else:
        raise ValueError(f"Unknown builder: {model['builder']}")

    prompt.update(
        {
            "8": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": model["vae"]},
            },
            "9": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["7", 0], "vae": ["8", 0]},
            },
            "10": {
                "class_type": "SaveImage",
                "inputs": {"images": ["9", 0], "filename_prefix": output_prefix},
            },
        }
    )
    return prompt


def image_paths_from_history(history: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for output in (history.get("outputs") or {}).values():
        for image in output.get("images") or []:
            if image.get("type") != "output":
                continue
            subfolder = image.get("subfolder") or ""
            paths.append(COMFY_OUTPUT / subfolder / image["filename"])
    return paths


def image_metrics(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
        width, height = image.size
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    histogram = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
    probabilities = histogram / max(float(histogram.sum()), 1.0)
    probabilities = probabilities[probabilities > 0]
    entropy = float(-(probabilities * np.log2(probabilities)).sum())
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edges = cv2.Canny(gray, 100, 200)
    edge_density = float((edges > 0).mean())
    rg = rgb[:, :, 0].astype(np.float32) - rgb[:, :, 1].astype(np.float32)
    yb = 0.5 * (
        rgb[:, :, 0].astype(np.float32) + rgb[:, :, 1].astype(np.float32)
    ) - rgb[:, :, 2].astype(np.float32)
    colorfulness = math.sqrt(float(rg.std()) ** 2 + float(yb.std()) ** 2)
    colorfulness += 0.3 * math.sqrt(float(rg.mean()) ** 2 + float(yb.mean()) ** 2)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "file_size_bytes": len(data),
        "width": width,
        "height": height,
        "brightness_mean": round(float(gray.mean()), 4),
        "brightness_std": round(float(gray.std()), 4),
        "saturation_mean": round(float(hsv[:, :, 1].mean()), 4),
        "gray_entropy": round(entropy, 5),
        "laplacian_variance": round(laplacian_variance, 4),
        "edge_density": round(edge_density, 6),
        "colorfulness": round(colorfulness, 4),
    }


def successful_job_keys() -> set[str]:
    keys: set[str] = set()
    if not RESULTS_PATH.exists():
        return keys
    for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("success"):
            keys.add(record["job_key"])
    return keys


def append_result(record: dict[str, Any]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    rebuild_csv()


def rebuild_csv() -> None:
    if not RESULTS_PATH.exists():
        return
    rows: list[dict[str, Any]] = []
    for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        telemetry = record.get("telemetry_summary") or {}
        metrics = (record.get("image_metrics") or [{}])[0]
        unload_after = ((record.get("unload_after") or {}).get("after") or {})
        rows.append(
            {
                "job_key": record.get("job_key"),
                "phase": record.get("phase"),
                "case_id": record.get("case_id"),
                "category": record.get("category"),
                "model": record.get("model"),
                "seed": record.get("seed"),
                "width": record.get("width"),
                "height": record.get("height"),
                "steps": record.get("steps"),
                "cfg": record.get("cfg"),
                "sampler": record.get("sampler"),
                "scheduler": record.get("scheduler"),
                "success": record.get("success"),
                "wall_time_s": record.get("wall_time_s"),
                "peak_vram_mb": telemetry.get("gpu_memory_mb_max"),
                "peak_gpu_util_percent": telemetry.get("gpu_util_percent_max"),
                "peak_power_w": telemetry.get("gpu_power_w_max"),
                "peak_temp_c": telemetry.get("gpu_temp_c_max"),
                "peak_comfy_rss_mb": telemetry.get("comfy_rss_mb_max"),
                "min_system_available_mb": telemetry.get(
                    "system_available_mb_min"
                ),
                "post_unload_vram_mb": unload_after.get("gpu_memory_mb"),
                "image_path": metrics.get("path"),
                "image_sha256": metrics.get("sha256"),
                "gray_entropy": metrics.get("gray_entropy"),
                "laplacian_variance": metrics.get("laplacian_variance"),
                "edge_density": metrics.get("edge_density"),
                "colorfulness": metrics.get("colorfulness"),
                "error": record.get("error"),
            }
        )
    if not rows:
        return
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_jobs(config: dict[str, Any], phases: set[str]) -> list[dict[str, Any]]:
    cases = config["cases"]
    by_id = {case["id"]: case for case in cases}
    jobs: list[dict[str, Any]] = []
    for phase in phases:
        if phase == "reliability":
            for case_id in config["reliability"]["case_ids"]:
                base = by_id[case_id]
                for seed in config["reliability"]["seeds"]:
                    case = dict(base)
                    case["phase"] = "reliability"
                    case["seed"] = seed
                    jobs.append({"case": case, "steps_override": None})
        elif phase == "speed":
            base = by_id["smoke_single_character"]
            case = dict(base)
            case["phase"] = "speed"
            jobs.append({"case": case, "steps_override": "per_model"})
        else:
            for case in cases:
                if case["phase"] == phase:
                    jobs.append({"case": dict(case), "steps_override": None})
    return jobs


def job_key(
    phase: str,
    case_id: str,
    model_key: str,
    seed: int,
    steps: int,
    negative_mode: str,
) -> str:
    return f"{phase}:{case_id}:{model_key}:s{seed}:n{steps}:{negative_mode}"


def run_one(
    client: ComfyClient,
    config: dict[str, Any],
    model_key: str,
    case: dict[str, Any],
    steps_override: int | None,
    negative_mode: str,
) -> dict[str, Any]:
    model = config["models"][model_key]
    steps = int(steps_override or model["steps"])
    phase = case["phase"]
    key = job_key(
        phase, case["id"], model_key, int(case["seed"]), steps, negative_mode
    )
    prefix = "/".join(
        [
            config["output_prefix"],
            phase,
            model_key,
            safe_name(f"{case['id']}_s{case['seed']}_n{steps}_{negative_mode}"),
        ]
    )
    if negative_mode == "live":
        negative = model.get("live_negative", "")
    else:
        negative = case.get("negative", config["common_negative"])
    prompt = build_prompt(
        model_key,
        model,
        case,
        prefix,
        negative,
        steps_override=steps_override,
    )
    prompt_path = PROMPT_DIR / f"{safe_name(key)}.json"
    write_json(prompt_path, prompt)
    record: dict[str, Any] = {
        "job_key": key,
        "phase": phase,
        "case_id": case["id"],
        "category": case["category"],
        "checks": case.get("checks") or [],
        "model": model_key,
        "model_label": model["label"],
        "seed": int(case["seed"]),
        "width": int(case["width"]),
        "height": int(case["height"]),
        "steps": steps,
        "cfg": float(model["cfg"]),
        "sampler": model["sampler"],
        "scheduler": model["scheduler"],
        "negative_mode": negative_mode,
        "prompt_text": case["prompt"],
        "negative_text": negative,
        "api_prompt_path": str(prompt_path),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "success": False,
    }
    monitor = ResourceMonitor(interval=0.5)
    try:
        record["unload_before"] = client.unload_models()
        monitor.start()
        started = time.perf_counter()
        prompt_id, history = client.submit_and_wait(prompt)
        record["wall_time_s"] = round(time.perf_counter() - started, 3)
        record["prompt_id"] = prompt_id
        history_path = HISTORY_DIR / f"{safe_name(key)}.json"
        write_json(history_path, history)
        record["history_path"] = str(history_path)
        status = history.get("status") or {}
        record["comfy_status"] = status
        image_paths = image_paths_from_history(history)
        record["output_paths"] = [str(path) for path in image_paths]
        record["success"] = bool(image_paths) and all(
            path.exists() for path in image_paths
        )
        if not record["success"]:
            record["error"] = "No output image was produced."
    except Exception as exc:  # noqa: BLE001 - every failure must be recorded
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()
    finally:
        monitor.stop()
        record["telemetry_summary"] = monitor.summary()
        telemetry_path = TELEMETRY_DIR / f"{safe_name(key)}.json"
        write_json(telemetry_path, monitor.samples)
        record["telemetry_path"] = str(telemetry_path)
        try:
            record["unload_after"] = client.unload_models()
        except Exception as unload_error:  # noqa: BLE001
            record["unload_after_error"] = (
                f"{type(unload_error).__name__}: {unload_error}"
            )
    record["image_metrics"] = []
    for output_path in record.get("output_paths") or []:
        path = Path(output_path)
        if path.exists():
            try:
                record["image_metrics"].append(image_metrics(path))
            except Exception as metric_error:  # noqa: BLE001
                record.setdefault("metric_errors", []).append(
                    f"{path}: {type(metric_error).__name__}: {metric_error}"
                )
    record["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a resumable ComfyUI benchmark for two Anima workflows and Krea2."
    )
    parser.add_argument(
        "--phases",
        default="smoke",
        help="Comma separated: smoke,core,advanced,length,aspect,reliability,speed,all",
    )
    parser.add_argument(
        "--models",
        default="all",
        help="Comma separated model keys or all",
    )
    parser.add_argument(
        "--negative-mode",
        choices=("common", "live"),
        default="common",
    )
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--seed-offset",
        type=int,
        default=0,
        help="Add an offset to every selected case seed for independent repeats.",
    )
    parser.add_argument(
        "--reverse-speed-steps",
        action="store_true",
        help="Run per-model speed steps in reverse order to expose ordering effects.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_json(CONFIG_PATH)
    all_phases = {"smoke", "core", "advanced", "length", "aspect", "reliability", "speed"}
    requested_phases = {part.strip() for part in args.phases.split(",") if part.strip()}
    phases = all_phases if "all" in requested_phases else requested_phases
    unknown_phases = phases - all_phases
    if unknown_phases:
        raise SystemExit(f"Unknown phases: {sorted(unknown_phases)}")
    if args.models == "all":
        model_keys = list(config["models"])
    else:
        model_keys = [part.strip() for part in args.models.split(",") if part.strip()]
    unknown_models = set(model_keys) - set(config["models"])
    if unknown_models:
        raise SystemExit(f"Unknown models: {sorted(unknown_models)}")

    base_jobs = build_jobs(config, phases)
    expanded_jobs: list[tuple[str, dict[str, Any], int | None]] = []
    for job in base_jobs:
        case = job["case"]
        case["seed"] = int(case["seed"]) + args.seed_offset
        for model_key in model_keys:
            if job["steps_override"] == "per_model":
                speed_steps = config["speed_steps"][model_key]
                if args.reverse_speed_steps:
                    speed_steps = reversed(speed_steps)
                for steps in speed_steps:
                    expanded_jobs.append((model_key, dict(case), int(steps)))
            else:
                expanded_jobs.append((model_key, dict(case), None))
    if args.limit > 0:
        expanded_jobs = expanded_jobs[: args.limit]

    completed = successful_job_keys()
    client = ComfyClient(config["server"], timeout=args.timeout)
    print(
        f"Benchmark root: {BENCHMARK_ROOT}\n"
        f"Jobs selected: {len(expanded_jobs)}; already successful: {len(completed)}",
        flush=True,
    )
    try:
        client.wait_idle()
        initial_unload = client.unload_models()
        write_json(RAW_DIR / "initial_unload.json", initial_unload)
        total = len(expanded_jobs)
        for index, (model_key, case, steps_override) in enumerate(expanded_jobs, start=1):
            model = config["models"][model_key]
            steps = int(steps_override or model["steps"])
            key = job_key(
                case["phase"],
                case["id"],
                model_key,
                int(case["seed"]),
                steps,
                args.negative_mode,
            )
            if key in completed and not args.force:
                print(f"[{index}/{total}] SKIP {key}", flush=True)
                continue
            print(f"[{index}/{total}] RUN  {key}", flush=True)
            record = run_one(
                client,
                config,
                model_key,
                case,
                steps_override,
                args.negative_mode,
            )
            append_result(record)
            state = "OK" if record.get("success") else "FAIL"
            peak = (record.get("telemetry_summary") or {}).get("gpu_memory_mb_max")
            print(
                f"[{index}/{total}] {state} {key} "
                f"time={record.get('wall_time_s')}s peak_vram={peak}MB",
                flush=True,
            )
    finally:
        try:
            final_unload = client.unload_models()
            write_json(RAW_DIR / "final_unload.json", final_unload)
        except Exception as exc:  # noqa: BLE001
            print(f"Final unload failed: {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
