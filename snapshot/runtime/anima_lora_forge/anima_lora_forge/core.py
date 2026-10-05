from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_path(value: str | os.PathLike[str], root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def load_profile(profile_path: str | os.PathLike[str]) -> dict[str, Any]:
    root = project_root()
    path = _resolve_path(profile_path, root)
    with path.open("r", encoding="utf-8-sig") as handle:
        profile = json.load(handle)
    if profile.get("schema_version") != 1:
        raise ValueError("Unsupported profile schema_version; expected 1")
    required = ("project_id", "character_id", "trigger_token", "dataset_dir")
    missing = [key for key in required if not profile.get(key)]
    if missing:
        raise ValueError(f"Profile is missing required fields: {', '.join(missing)}")
    profile["_profile_path"] = str(path)
    profile["_project_root"] = str(root)
    return profile


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size
    except Exception:
        return (-1, -1)


def scan_dataset(dataset_dir: Path, trigger_token: str) -> dict[str, Any]:
    images = sorted(
        path
        for path in dataset_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ) if dataset_dir.is_dir() else []
    captions = sorted(dataset_dir.glob("*.txt")) if dataset_dir.is_dir() else []
    image_by_stem = {path.stem: path for path in images}
    caption_by_stem = {path.stem: path for path in captions}
    missing_captions = sorted(set(image_by_stem) - set(caption_by_stem))
    orphan_captions = sorted(set(caption_by_stem) - set(image_by_stem))

    trigger_missing: list[str] = []
    trigger_not_first: list[str] = []
    caption_lengths: list[int] = []
    for stem, caption_path in caption_by_stem.items():
        text = caption_path.read_text(encoding="utf-8-sig").strip()
        caption_lengths.append(len(text))
        if trigger_token.lower() not in text.lower():
            trigger_missing.append(stem)
        if not text.lower().startswith(trigger_token.lower()):
            trigger_not_first.append(stem)

    hashes: dict[str, list[str]] = defaultdict(list)
    unreadable_images: list[str] = []
    dimensions: dict[str, list[int]] = {}
    for image_path in images:
        hashes[_sha256(image_path)].append(image_path.name)
        size = _image_dimensions(image_path)
        if size == (-1, -1):
            unreadable_images.append(image_path.name)
        elif size is not None:
            dimensions[image_path.name] = [size[0], size[1]]
    duplicate_groups = [names for names in hashes.values() if len(names) > 1]
    width_values = [value[0] for value in dimensions.values()]
    height_values = [value[1] for value in dimensions.values()]

    return {
        "dataset_dir": str(dataset_dir),
        "image_count": len(images),
        "caption_count": len(captions),
        "paired_count": len(set(image_by_stem) & set(caption_by_stem)),
        "missing_captions": missing_captions,
        "orphan_captions": orphan_captions,
        "trigger_missing": sorted(trigger_missing),
        "trigger_not_first": sorted(trigger_not_first),
        "exact_duplicate_groups": duplicate_groups,
        "unreadable_images": sorted(unreadable_images),
        "caption_length": {
            "min": min(caption_lengths) if caption_lengths else 0,
            "max": max(caption_lengths) if caption_lengths else 0,
            "average": (
                round(sum(caption_lengths) / len(caption_lengths), 1)
                if caption_lengths
                else 0
            ),
        },
        "dimensions": {
            "inspected": len(dimensions),
            "min_width": min(width_values) if width_values else None,
            "max_width": max(width_values) if width_values else None,
            "min_height": min(height_values) if height_values else None,
            "max_height": max(height_values) if height_values else None,
            "unique_sizes": sorted(
                {f"{value[0]}x{value[1]}" for value in dimensions.values()}
            ),
        },
    }


def _check(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    detail: str,
) -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def preflight(profile: dict[str, Any], verify_model_hash: bool = False) -> dict[str, Any]:
    root = Path(profile["_project_root"])
    checks: list[dict[str, Any]] = []
    dataset_dir = _resolve_path(profile["dataset_dir"], root)
    dataset = scan_dataset(dataset_dir, profile["trigger_token"])

    if not dataset_dir.is_dir():
        _check(checks, "dataset", "error", f"Dataset directory not found: {dataset_dir}")
    elif dataset["image_count"] == 0:
        _check(checks, "dataset", "error", "Dataset contains no supported images")
    else:
        _check(
            checks,
            "dataset",
            "ok",
            f'{dataset["image_count"]} images and {dataset["caption_count"]} captions',
        )

    pair_errors = (
        dataset["missing_captions"]
        or dataset["orphan_captions"]
        or dataset["trigger_missing"]
        or dataset["trigger_not_first"]
        or dataset["unreadable_images"]
    )
    _check(
        checks,
        "dataset_pairs",
        "error" if pair_errors else "ok",
        "Image/caption pairing, trigger placement, and readability",
    )
    _check(
        checks,
        "exact_duplicates",
        "error" if dataset["exact_duplicate_groups"] else "ok",
        (
            f'{len(dataset["exact_duplicate_groups"])} duplicate groups'
            if dataset["exact_duplicate_groups"]
            else "No exact image duplicates"
        ),
    )

    model_report: dict[str, Any] = {}
    for key in ("dit", "text_encoder", "vae"):
        configured = profile.get("models", {}).get(key)
        path = _resolve_path(configured, root) if configured else None
        exists = bool(path and path.is_file())
        record: dict[str, Any] = {
            "path": str(path) if path else None,
            "exists": exists,
        }
        expected_hash = profile.get("models", {}).get(f"expected_{key}_sha256")
        if exists:
            record["size_bytes"] = path.stat().st_size
        if exists and verify_model_hash and expected_hash:
            actual_hash = _sha256(path)
            record["sha256"] = actual_hash
            record["hash_matches"] = actual_hash.lower() == expected_hash.lower()
        model_report[key] = record
        hash_failed = verify_model_hash and expected_hash and not record.get("hash_matches")
        _check(
            checks,
            f"model_{key}",
            "error" if not exists or hash_failed else "ok",
            (
                f"{path}"
                if exists and not hash_failed
                else f"Missing or hash mismatch: {path}"
            ),
        )

    trainer = profile.get("trainer", {})
    trainer_root = _resolve_path(trainer.get("root", "vendor/sd-scripts"), root)
    trainer_script = trainer_root / trainer.get("script", "anima_train_network.py")
    accelerate = _resolve_path(
        trainer.get("accelerate", ".venv/Scripts/accelerate.exe"),
        root,
    )
    trainer_ready = trainer_script.is_file() and accelerate.is_file()
    _check(
        checks,
        "trainer",
        "ok" if trainer_ready else "warning",
        (
            "Anima trainer is installed"
            if trainer_ready
            else "Trainer is intentionally not installed yet; prepare remains available"
        ),
    )

    gpu: dict[str, Any] = {"torch_available": False}
    try:
        import torch

        gpu["torch_available"] = True
        gpu["torch_version"] = torch.__version__
        gpu["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            gpu["name"] = torch.cuda.get_device_name(0)
            gpu["bf16_supported"] = torch.cuda.is_bf16_supported()
            total = torch.cuda.get_device_properties(0).total_memory
            gpu["vram_gib"] = round(total / (1024**3), 1)
    except Exception as exc:
        gpu["detail"] = str(exc)
    _check(
        checks,
        "gpu",
        "ok" if gpu.get("cuda_available") and gpu.get("bf16_supported") else "warning",
        gpu.get("name", "CUDA/BF16 availability could not be confirmed"),
    )

    hard_errors = [item for item in checks if item["status"] == "error"]
    allow_execute = bool(trainer.get("allow_execute", False))
    return {
        "ok": not hard_errors,
        "ready_to_train": not hard_errors and trainer_ready and allow_execute,
        "execution_locked": not allow_execute,
        "profile": profile["_profile_path"],
        "project_id": profile["project_id"],
        "character_id": profile["character_id"],
        "trigger_token": profile["trigger_token"],
        "checks": checks,
        "dataset": dataset,
        "models": model_report,
        "trainer": {
            "root": str(trainer_root),
            "script": str(trainer_script),
            "accelerate": str(accelerate),
            "installed": trainer_ready,
            "allow_execute": allow_execute,
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "gpu": gpu,
        },
    }


def _toml_string(value: str | os.PathLike[str]) -> str:
    return str(value).replace("\\", "/").replace('"', '\\"')


def render_dataset_config(
    profile: dict[str, Any],
    dataset_dir_override: Path | None = None,
) -> str:
    root = Path(profile["_project_root"])
    training = profile["training"]
    dataset_dir = (
        dataset_dir_override.resolve()
        if dataset_dir_override is not None
        else _resolve_path(profile["dataset_dir"], root)
    )
    return "\n".join(
        [
            "[general]",
            'caption_extension = ".txt"',
            f'shuffle_caption = {str(bool(training.get("shuffle_caption", False))).lower()}',
            f'keep_tokens = {int(training.get("keep_tokens", 1))}',
            "",
            "[[datasets]]",
            f'resolution = {int(training.get("resolution", 1024))}',
            f'batch_size = {int(training.get("batch_size", 1))}',
            f'enable_bucket = {str(bool(training.get("enable_bucket", True))).lower()}',
            f'bucket_no_upscale = {str(bool(training.get("bucket_no_upscale", True))).lower()}',
            f'min_bucket_reso = {int(training.get("min_bucket_reso", 512))}',
            f'max_bucket_reso = {int(training.get("max_bucket_reso", 1536))}',
            f'bucket_reso_steps = {int(training.get("bucket_reso_steps", 64))}',
            "",
            "[[datasets.subsets]]",
            f'image_dir = "{_toml_string(dataset_dir)}"',
            f'num_repeats = {int(training.get("num_repeats", 1))}',
            "",
        ]
    )


def build_training_command(
    profile: dict[str, Any],
    dataset_config: Path,
    output_dir: Path,
    logs_dir: Path | None = None,
    sample_prompts: Path | None = None,
) -> list[str]:
    root = Path(profile["_project_root"])
    models = profile["models"]
    trainer = profile["trainer"]
    training = profile["training"]
    trainer_root = _resolve_path(trainer.get("root", "vendor/sd-scripts"), root)
    script = trainer_root / trainer.get("script", "anima_train_network.py")
    accelerate = _resolve_path(
        trainer.get("accelerate", ".venv/Scripts/accelerate.exe"),
        root,
    )
    command = [
        str(accelerate),
        "launch",
        "--num_cpu_threads_per_process",
        str(int(training.get("num_cpu_threads_per_process", 1))),
        str(script),
        "--pretrained_model_name_or_path",
        str(_resolve_path(models["dit"], root)),
        "--vae",
        str(_resolve_path(models["vae"], root)),
        "--qwen3",
        str(_resolve_path(models["text_encoder"], root)),
        "--dataset_config",
        str(dataset_config),
        "--output_dir",
        str(output_dir),
        "--output_name",
        training.get("output_name", profile["project_id"]),
        "--network_module",
        training.get("network_module", "networks.lora_anima"),
        "--network_dim",
        str(int(training.get("network_dim", 32))),
        "--network_alpha",
        str(int(training.get("network_alpha", 16))),
        "--learning_rate",
        str(training.get("learning_rate", "2e-5")),
        "--optimizer_type",
        training.get("optimizer_type", "AdamW"),
        "--lr_scheduler",
        training.get("lr_scheduler", "constant"),
        "--timestep_sampling",
        training.get("timestep_sampling", "sigmoid"),
        "--discrete_flow_shift",
        str(training.get("discrete_flow_shift", 1.0)),
        "--max_train_steps",
        str(int(training.get("max_train_steps", 1000))),
        "--save_every_n_steps",
        str(int(training.get("save_every_n_steps", 200))),
        "--mixed_precision",
        training.get("mixed_precision", "bf16"),
        "--save_precision",
        training.get("save_precision", "bf16"),
        "--save_model_as",
        "safetensors",
        "--seed",
        str(int(training.get("seed", 42))),
        "--max_data_loader_n_workers",
        str(int(training.get("max_data_loader_n_workers", 0))),
    ]
    boolean_flags = {
        "cache_text_encoder_outputs": "--cache_text_encoder_outputs",
        "cache_latents": "--cache_latents",
        "gradient_checkpointing": "--gradient_checkpointing",
        "network_train_unet_only": "--network_train_unet_only",
        "qwen_image_vae_2d": "--qwen_image_vae_2d",
    }
    for key, flag in boolean_flags.items():
        if training.get(key, True):
            command.append(flag)
    if logs_dir is not None:
        command.extend(
            [
                "--log_with",
                "tensorboard",
                "--logging_dir",
                str(logs_dir),
            ]
        )
    if sample_prompts is not None:
        evaluation = profile.get("evaluation", {})
        command.extend(
            [
                "--sample_prompts",
                str(sample_prompts),
                "--sample_every_n_steps",
                str(
                    int(
                        evaluation.get(
                            "sample_every_n_steps",
                            training.get("save_every_n_steps", 200),
                        )
                    )
                ),
                "--sample_at_first",
            ]
        )
    for extra in training.get("extra_args", []):
        command.append(str(extra))
    return command


def stage_dataset(
    profile: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    """Create a trainer-safe dataset tree without letting a GUI move gold files."""
    root = Path(profile["_project_root"])
    source = _resolve_path(profile["dataset_dir"], root)
    repeats = int(profile["training"].get("num_repeats", 1))
    subset_name = f"{repeats}_{profile['trigger_token']}"
    staging_root = run_dir / "dataset"
    subset_dir = staging_root / subset_name
    subset_dir.mkdir(parents=True, exist_ok=True)
    linked = 0
    copied = 0
    reused = 0
    source_files = sorted(
        path
        for path in source.iterdir()
        if path.is_file()
        and (path.suffix.lower() in IMAGE_EXTENSIONS or path.suffix.lower() == ".txt")
    )
    for source_path in source_files:
        destination = subset_dir / source_path.name
        if destination.exists():
            if destination.stat().st_size != source_path.stat().st_size:
                raise RuntimeError(f"Staged file differs from source: {destination}")
            reused += 1
            continue
        try:
            os.link(source_path, destination)
            linked += 1
        except OSError:
            shutil.copy2(source_path, destination)
            copied += 1
    return {
        "source_dir": str(source),
        "staging_root": str(staging_root),
        "subset_dir": str(subset_dir),
        "subset_name": subset_name,
        "file_count": len(source_files),
        "hardlinked": linked,
        "copied": copied,
        "reused": reused,
    }


def render_sd_trainer_job(
    profile: dict[str, Any],
    staging_root: Path,
    weights_dir: Path,
    logs_dir: Path,
) -> dict[str, Any]:
    root = Path(profile["_project_root"])
    training = profile["training"]
    evaluation = profile.get("evaluation", {})
    preview_enabled = bool(evaluation.get("enable_preview", True))
    job = {
        "model_train_type": "anima-lora",
        "lora_type": "lora",
        "pretrained_model_name_or_path": str(
            _resolve_path(profile["models"]["dit"], root)
        ),
        "vae": str(_resolve_path(profile["models"]["vae"], root)),
        "qwen3": str(_resolve_path(profile["models"]["text_encoder"], root)),
        "train_data_dir": str(staging_root),
        "output_dir": str(weights_dir),
        "output_name": training.get("output_name", profile["project_id"]),
        "logging_dir": str(logs_dir),
        "log_with": "tensorboard",
        "save_model_as": "safetensors",
        "save_precision": training.get("save_precision", "bf16"),
        "mixed_precision": training.get("mixed_precision", "bf16"),
        "resolution": f'{int(training.get("resolution", 1024))},{int(training.get("resolution", 1024))}',
        "enable_bucket": bool(training.get("enable_bucket", True)),
        "bucket_no_upscale": bool(training.get("bucket_no_upscale", True)),
        "min_bucket_reso": int(training.get("min_bucket_reso", 512)),
        "max_bucket_reso": int(training.get("max_bucket_reso", 1536)),
        "bucket_reso_steps": int(training.get("bucket_reso_steps", 64)),
        "train_batch_size": int(training.get("batch_size", 1)),
        "max_train_steps": int(training.get("max_train_steps", 1000)),
        "save_every_n_steps": int(training.get("save_every_n_steps", 200)),
        "network_module": training.get("network_module", "networks.lora_anima"),
        "network_dim": int(training.get("network_dim", 32)),
        "network_alpha": int(training.get("network_alpha", 16)),
        # SD-Trainer serializes this value into TOML and passes it directly to
        # torch.optim. Numeric-looking JSON strings would otherwise remain
        # strings and fail before step 0.
        "learning_rate": float(training.get("learning_rate", 2e-5)),
        "optimizer_type": training.get("optimizer_type", "AdamW"),
        "lr_scheduler": training.get("lr_scheduler", "constant"),
        "timestep_sampling": training.get("timestep_sampling", "sigmoid"),
        "discrete_flow_shift": float(training.get("discrete_flow_shift", 1.0)),
        "gradient_checkpointing": bool(training.get("gradient_checkpointing", True)),
        "network_train_unet_only": bool(
            training.get("network_train_unet_only", True)
        ),
        "cache_text_encoder_outputs": bool(
            training.get("cache_text_encoder_outputs", True)
        ),
        "cache_text_encoder_outputs_to_disk": True,
        "cache_latents": bool(training.get("cache_latents", True)),
        "cache_latents_to_disk": True,
        "qwen_image_vae_2d": bool(training.get("qwen_image_vae_2d", True)),
        "shuffle_caption": bool(training.get("shuffle_caption", False)),
        "caption_extension": ".txt",
        "keep_tokens": int(training.get("keep_tokens", 1)),
        "seed": int(training.get("seed", 42)),
        "max_data_loader_n_workers": 0,
        "persistent_data_loader_workers": False,
        "enable_preview": preview_enabled,
    }
    if preview_enabled:
        job.update(
            {
                "positive_prompts": evaluation.get(
                    "preview_prompt",
                    (
                        f"{profile['trigger_token']}, masterpiece, best quality, safe, "
                        "solo, fully clothed, modest opaque outfit, full body, "
                        "neutral standing pose, simple background"
                    ),
                ),
                "negative_prompts": evaluation.get(
                    "preview_negative",
                    (
                        "nsfw, explicit, sexual content, nude, naked, topless, "
                        "bottomless, nipples, areola, genitals, cleavage, underwear, "
                        "lingerie, bikini, swimsuit, transparent clothes, erotic, "
                        "suggestive, lewd, worst quality, low quality, score_1, "
                        "score_2, score_3, artist name, multiple people, cropped "
                        "feet, bad anatomy"
                    ),
                ),
                "sample_width": int(evaluation.get("sample_width", 1024)),
                "sample_height": int(evaluation.get("sample_height", 1024)),
                "sample_cfg": float(evaluation.get("sample_cfg", 4.5)),
                "sample_seed": int(evaluation.get("sample_seed", 42)),
                "sample_steps": int(evaluation.get("sample_steps", 40)),
                "sample_sampler": evaluation.get("sample_sampler", "euler"),
                "sample_at_first": True,
                "sample_every_n_steps": int(
                    evaluation.get(
                        "sample_every_n_steps",
                        training.get("save_every_n_steps", 200),
                    )
                ),
            }
        )
    return job


def sd_trainer_dashboard_status(profile: dict[str, Any]) -> dict[str, Any]:
    dashboard = profile.get("dashboard", {})
    ui_url = dashboard.get("ui_url", "http://127.0.0.1:28000")
    result: dict[str, Any] = {
        "ui_url": ui_url,
        "monitor_url": dashboard.get(
            "monitor_url", f"{ui_url.rstrip('/')}/train-monitor"
        ),
        "tensorboard_url": dashboard.get(
            "tensorboard_url", f"{ui_url.rstrip('/')}/tensorboard.html"
        ),
        "online": False,
    }
    try:
        with urllib.request.urlopen(ui_url, timeout=2) as response:
            result["online"] = 200 <= response.status < 500
            result["http_status"] = response.status
    except (OSError, urllib.error.URLError) as exc:
        result["detail"] = str(exc)
    return result


def submit_sd_trainer_job(
    profile: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    if not profile.get("trainer", {}).get("allow_execute", False):
        raise RuntimeError(
            "Training submission remains locked. Set trainer.allow_execute=true "
            "only after the smoke-test review."
        )
    root = Path(profile["_project_root"])
    output_root = _resolve_path(profile.get("output_root", "runs"), root)
    run_dir = output_root / run_id
    job_path = run_dir / "config" / "sd_trainer_job.json"
    if not job_path.is_file():
        raise FileNotFoundError(f"SD-Trainer job is not prepared: {job_path}")
    status = sd_trainer_dashboard_status(profile)
    if not status["online"]:
        raise RuntimeError("SD-Trainer dashboard is not running")
    payload = job_path.read_bytes()
    api_url = profile.get("dashboard", {}).get(
        "run_api", f'{status["ui_url"].rstrip("/")}/api/run'
    )
    request = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return {"api_url": api_url, "response": data}


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_sample_prompt(profile: dict[str, Any]) -> str:
    evaluation = profile.get("evaluation", {})
    positive = " ".join(
        str(
            evaluation.get(
                "preview_prompt",
                (
                    f"{profile['trigger_token']}, masterpiece, best quality, safe, "
                    "solo, fully clothed, modest opaque outfit, full body, "
                    "neutral standing pose, simple background"
                ),
            )
        ).split()
    )
    negative = " ".join(
        str(
            evaluation.get(
                "preview_negative",
                (
                    "nsfw, explicit, sexual content, nude, naked, topless, "
                    "bottomless, nipples, areola, genitals, cleavage, underwear, "
                    "lingerie, bikini, swimsuit, transparent clothes, erotic, "
                    "suggestive, lewd, worst quality, low quality, score_1, "
                    "score_2, score_3, artist name, multiple people, cropped "
                    "feet, bad anatomy"
                ),
            )
        ).split()
    )
    width = int(evaluation.get("sample_width", 1024))
    height = int(evaluation.get("sample_height", 1024))
    cfg = float(evaluation.get("sample_cfg", 4.5))
    steps = int(evaluation.get("sample_steps", 40))
    seed = int(evaluation.get("sample_seed", 42))
    sampler = evaluation.get("sample_sampler", "euler")
    return (
        f"{positive} --n {negative} --w {width} --h {height} "
        f"--l {cfg} --s {steps} --d {seed} --ss {sampler}\n"
    )


def prepare_run(
    profile: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    report = preflight(profile)
    if not report["ok"]:
        raise RuntimeError("Preflight contains hard errors; run doctor for details")
    root = Path(profile["_project_root"])
    output_root = _resolve_path(profile.get("output_root", "runs"), root)
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / run_id
    config_dir = run_dir / "config"
    weights_dir = run_dir / "weights"
    logs_dir = run_dir / "logs"
    samples_dir = run_dir / "samples"
    for directory in (config_dir, weights_dir, logs_dir, samples_dir):
        directory.mkdir(parents=True, exist_ok=True)

    staging = stage_dataset(profile, run_dir)
    dataset_config = config_dir / "dataset.toml"
    dataset_config.write_text(
        render_dataset_config(
            profile,
            dataset_dir_override=Path(staging["subset_dir"]),
        ),
        encoding="utf-8",
    )
    sample_prompts = config_dir / "sample_prompts.txt"
    sample_prompts.write_text(render_sample_prompt(profile), encoding="utf-8")
    preview_enabled = bool(profile.get("evaluation", {}).get("enable_preview", True))
    command = build_training_command(
        profile,
        dataset_config,
        weights_dir,
        logs_dir=logs_dir,
        sample_prompts=sample_prompts if preview_enabled else None,
    )
    command_file = config_dir / "train_command.ps1"
    command_file.write_text(
        "& " + " ".join(_powershell_quote(part) for part in command) + "\n",
        encoding="utf-8-sig",
    )
    profile_snapshot = config_dir / "profile.snapshot.json"
    snapshot = {
        key: value
        for key, value in profile.items()
        if not key.startswith("_")
    }
    profile_snapshot.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    sd_trainer_job_path = config_dir / "sd_trainer_job.json"
    sd_trainer_job_path.write_text(
        json.dumps(
            render_sd_trainer_job(
                profile,
                staging_root=Path(staging["staging_root"]),
                weights_dir=weights_dir,
                logs_dir=logs_dir,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "run_id": run_id,
        "status": "prepared",
        "execution_locked": report["execution_locked"],
        "profile": profile["_profile_path"],
        "dataset": report["dataset"],
        "models": report["models"],
        "staging": staging,
        "command": command,
        "paths": {
            "run_dir": str(run_dir),
            "dataset_config": str(dataset_config),
            "command_file": str(command_file),
            "sd_trainer_job": str(sd_trainer_job_path),
            "sample_prompts": str(sample_prompts),
            "weights_dir": str(weights_dir),
            "logs_dir": str(logs_dir),
            "samples_dir": str(samples_dir),
        },
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def execute_run(profile: dict[str, Any], run_id: str) -> int:
    root = Path(profile["_project_root"])
    output_root = _resolve_path(profile.get("output_root", "runs"), root)
    manifest_path = output_root / run_id / "run_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Run is not prepared: {manifest_path}")
    report = preflight(profile)
    if not report["ready_to_train"]:
        raise RuntimeError(
            "Training is not ready or remains locked. Install the trainer and set "
            "trainer.allow_execute=true only after the smoke-test review."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    logs_dir = Path(manifest["paths"]["logs_dir"])
    stdout_path = logs_dir / "train.stdout.log"
    stderr_path = logs_dir / "train.stderr.log"
    manifest["status"] = "running"
    manifest["started_at"] = datetime.now().astimezone().isoformat()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr:
        result = subprocess.run(
            manifest["command"],
            cwd=report["trainer"]["root"],
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
    manifest["status"] = "completed" if result.returncode == 0 else "failed"
    manifest["returncode"] = result.returncode
    manifest["finished_at"] = datetime.now().astimezone().isoformat()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result.returncode


def list_runs(profile: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(profile["_project_root"])
    output_root = _resolve_path(profile.get("output_root", "runs"), root)
    results: list[dict[str, Any]] = []
    if not output_root.is_dir():
        return results
    for manifest_path in sorted(output_root.glob("*/run_manifest.json"), reverse=True):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        weights_dir = Path(manifest["paths"]["weights_dir"])
        weights = (
            sorted(path.name for path in weights_dir.glob("*.safetensors"))
            if weights_dir.is_dir()
            else []
        )
        results.append(
            {
                "run_id": manifest.get("run_id"),
                "status": manifest.get("status"),
                "created_at": manifest.get("created_at"),
                "weights": weights,
                "run_dir": manifest["paths"]["run_dir"],
            }
        )
    return results
