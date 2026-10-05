from __future__ import annotations

import json
import shutil
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from .comfy import ComfyClient, ComfyError, output_images
from .config import (
    ensure_layout,
    load_json,
    public_config,
    save_json,
)
from .matrix import build_jobs, stable_seed
from .report import write_review_html
from .scoring import combined_score, hash_distance, technical_score
from .vlm import VLMError, score_candidate
from .workflow import build_prompt_graph


def make_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def run_dir(config: dict[str, Any], run_id: str) -> Path:
    return Path(config["_project_dir"]) / "runs" / run_id


def create_plan(
    config: dict[str, Any],
    run_id: str | None = None,
) -> tuple[str, Path, list[dict[str, Any]]]:
    ensure_layout(config)
    selected_run_id = run_id or make_run_id()
    destination = run_dir(config, selected_run_id)
    destination.mkdir(parents=True, exist_ok=True)
    jobs = build_jobs(config)
    save_json(
        destination / "plan.json",
        {
            "schema_version": 1,
            "run_id": selected_run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "character_id": config["character_id"],
            "config": public_config(config),
            "jobs": jobs,
        },
    )
    return selected_run_id, destination, jobs


def load_or_create_plan(
    config: dict[str, Any],
    run_id: str | None,
) -> tuple[str, Path, list[dict[str, Any]]]:
    if run_id:
        destination = run_dir(config, run_id)
        plan_path = destination / "plan.json"
        if plan_path.exists():
            return run_id, destination, load_json(plan_path)["jobs"]
    return create_plan(config, run_id)


def create_repair_plan(
    config: dict[str, Any],
    *,
    source_run_id: str,
    run_id: str | None = None,
) -> tuple[str, Path, list[dict[str, Any]]]:
    source = run_dir(config, source_run_id)
    source_plan = load_json(source / "plan.json")
    scores = load_json(source / "scores.json")
    score_map = {item["job_id"]: item for item in scores}
    selected_run_id = run_id or f"{make_run_id()}_repair"
    destination = run_dir(config, selected_run_id)
    destination.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, Any]] = []

    for original in source_plan["jobs"]:
        score = score_map.get(original["job_id"]) or {}
        vlm = score.get("vlm") or {}
        needs_repair = bool(
            not score.get("machine_gold")
            or original.get("style_tier") == "style_stress"
            or vlm.get("decision") == "repair"
        )
        if not needs_repair:
            continue

        problem_text = " ".join(
            str(item) for item in vlm.get("problems", [])
        )
        correction_parts = [
            "strict correction pass",
            "preserve the exact same character identity as the references",
            "obey the requested framing, outfit and equipment literally",
        ]
        negative_parts = [
            "identity drift",
            "unrequested outfit redesign",
        ]
        if any(word in problem_text for word in ("比例", "高挑", "娇小")):
            correction_parts.append(
                "strict compact 5 to 5.5 head adult body ratio, "
                "short limbs and narrow shoulders"
            )
            negative_parts.extend(
                ["tall body", "long legs", "fashion model proportions"]
            )
        if any(word in problem_text for word in ("服装", "领口", "蕾丝", "花纹")):
            correction_parts.append(
                "follow every expected garment layer and accessory exactly, "
                "with readable ivory lace and black ribbon construction"
            )
            negative_parts.extend(
                ["missing garment layer", "wrong neckline", "wrong motif"]
            )
        if any(word in problem_text for word in ("枪", "武器", "枪套")):
            correction_parts.append(
                "show exactly the requested weapon and holster count, "
                "never one more or one less"
            )
            negative_parts.extend(
                ["missing weapon", "extra weapon", "merged holster"]
            )
        if any(word in problem_text for word in ("发型", "头发", "蝴蝶结")):
            correction_parts.append(
                "one fluffy curled high side ponytail and exactly one large "
                "black hair ribbon"
            )
            negative_parts.extend(
                ["wrong hairstyle", "extra hair bow", "straight flat hair"]
            )
        if any(word in problem_text for word in ("幼", "年龄", "成年")):
            correction_parts.append(
                "clear 23-year-old adult facial maturity and demeanor"
            )
            negative_parts.extend(
                ["childlike face", "immature expression", "oversized infant eyes"]
            )

        repaired = deepcopy(original)
        repaired["job_id"] = f"{original['job_id']}__repair01"
        repaired["seed"] = stable_seed(
            int(config["generation"]["base_seed"]) + 1_000_003,
            repaired["job_id"],
        )
        repaired["positive"] = (
            f"{original['positive']}, {', '.join(correction_parts)}"
        )
        repaired["negative"] = (
            f"{original['negative']}, {', '.join(negative_parts)}"
        )
        repaired["reference_strength"] = min(
            0.72,
            max(0.58, float(original.get("reference_strength", 0)) + 0.1),
        )
        style = config["generation"]["styles"][repaired["style_id"]]
        repaired["expected"]["style"] = style.get("prompt", "")
        jobs.append(repaired)

    save_json(
        destination / "plan.json",
        {
            "schema_version": 1,
            "run_id": selected_run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "character_id": config["character_id"],
            "source_run_id": source_run_id,
            "config": public_config(config),
            "jobs": jobs,
        },
    )
    return selected_run_id, destination, jobs


def create_subset_plan(
    config: dict[str, Any],
    *,
    batch_ids: list[str],
    run_id: str | None = None,
    variant: str | None = None,
    seed_offset: int = 0,
    reference_delta: float = 0,
) -> tuple[str, Path, list[dict[str, Any]]]:
    requested = set(batch_ids)
    jobs = [
        deepcopy(job)
        for job in build_jobs(config)
        if job["batch_id"] in requested
    ]
    found = {job["batch_id"] for job in jobs}
    missing = sorted(requested - found)
    if missing:
        raise KeyError(f"未知批次: {', '.join(missing)}")
    if variant:
        for job in jobs:
            job["job_id"] = f"{job['job_id']}__{variant}"
            job["seed"] = stable_seed(
                int(config["generation"]["base_seed"]) + int(seed_offset),
                job["job_id"],
            )
            job["reference_strength"] = round(
                min(
                    0.8,
                    max(
                        0,
                        float(job.get("reference_strength", 0))
                        + float(reference_delta),
                    ),
                ),
                3,
            )
    selected_run_id = run_id or f"{make_run_id()}_subset"
    destination = run_dir(config, selected_run_id)
    destination.mkdir(parents=True, exist_ok=True)
    save_json(
        destination / "plan.json",
        {
            "schema_version": 1,
            "run_id": selected_run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "character_id": config["character_id"],
            "batch_filter": sorted(requested),
            "variant": variant,
            "seed_offset": seed_offset,
            "reference_delta": reference_delta,
            "config": public_config(config),
            "jobs": jobs,
        },
    )
    return selected_run_id, destination, jobs


def create_campaign_plan(
    config: dict[str, Any],
    *,
    source_run_ids: list[str],
    run_id: str | None = None,
) -> tuple[str, Path, list[dict[str, Any]]]:
    selected_run_id = run_id or f"{make_run_id()}_campaign"
    destination = run_dir(config, selected_run_id)
    destination.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, Any]] = []
    state_jobs: dict[str, dict[str, Any]] = {}
    seen_job_ids: set[str] = set()

    for source_run_id in source_run_ids:
        source = run_dir(config, source_run_id)
        audit_path = source / "manual_audit.json"
        if config["selection"].get("require_manual_audit", False):
            if not audit_path.is_file():
                continue
            audit = load_json(audit_path)
            if audit.get("status") != "approved":
                continue
            excluded_job_ids = set(audit.get("excluded_job_ids") or [])
        else:
            excluded_job_ids = set()
        plan = load_json(source / "plan.json")
        state = load_json(source / "state.json")
        for job in plan["jobs"]:
            if job["job_id"] in excluded_job_ids:
                continue
            source_item = state.get("jobs", {}).get(job["job_id"], {})
            if (
                source_item.get("status") != "completed"
                or not source_item.get("candidate")
            ):
                continue
            job_id = job["job_id"]
            if job_id in seen_job_ids:
                job_id = f"{job_id}__from_{source_run_id}"
            seen_job_ids.add(job_id)
            campaign_job = deepcopy(job)
            campaign_job["job_id"] = job_id
            campaign_job["_manual_source_approved"] = True
            campaign_job["_source_run_id"] = source_run_id
            jobs.append(campaign_job)
            state_jobs[job_id] = {
                "status": "completed",
                "candidate": source_item["candidate"],
                "prompt_id": source_item.get("prompt_id"),
                "source_run_id": source_run_id,
                "source_job_id": job["job_id"],
                "job": campaign_job,
            }

    save_json(
        destination / "plan.json",
        {
            "schema_version": 1,
            "run_id": selected_run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "character_id": config["character_id"],
            "source_run_ids": source_run_ids,
            "config": public_config(config),
            "jobs": jobs,
        },
    )
    save_json(
        destination / "state.json",
        {
            "run_id": selected_run_id,
            "jobs": state_jobs,
        },
    )
    return selected_run_id, destination, jobs


def _client(config: dict[str, Any]) -> ComfyClient:
    comfy = config["comfyui"]
    return ComfyClient(
        comfy["base_url"],
        comfy.get("root"),
        timeout=int(comfy.get("http_timeout", 30)),
    )


def _reference_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in config.get("references", [])}


def doctor(config: dict[str, Any]) -> dict[str, Any]:
    ensure_layout(config)
    client = _client(config)
    stats = client.system_stats()
    template = load_json(Path(config["comfyui"]["workflow_template"]))
    graph = template["graph"]
    available = client.object_info()
    required = sorted(
        {
            node["class_type"]
            for node in graph.values()
        }
        | {"SaveImage"}
    )
    if any(
        float(item.get("reference_strength", 0)) > 0
        for item in config["generation"]["styles"].values()
    ):
        required.extend(
            [
                "LoadImage",
                "ImageScaleToMaxDimension",
                "AnimaLLLiteApply",
            ]
        )
    missing = sorted({name for name in required if name not in available})

    llm = config["selection"]["llm"]
    provider_status: dict[str, Any] = {"enabled": bool(llm.get("enabled"))}
    if llm.get("enabled"):
        provider_path = Path(llm["provider_config"])
        provider_status["config_exists"] = provider_path.is_file()
        provider_status["provider"] = llm.get("provider")
        provider_status["model"] = llm.get("model")
        provider_status["configured"] = False
        if provider_path.is_file():
            providers = load_json(provider_path).get("providers", [])
            provider = next(
                (
                    item
                    for item in providers
                    if item.get("name") == llm.get("provider")
                ),
                None,
            )
            if provider:
                provider_status["configured"] = (
                    llm.get("model") in (provider.get("models") or [])
                    and provider.get("supports_vision") is not False
                )
                provider_status["key_source"] = (
                    "env"
                    if str(provider.get("api_key") or "").lower().startswith("env:")
                    else "stored"
                    if provider.get("api_key")
                    else "none"
                )

    system = stats.get("system", {})
    devices = stats.get("devices", [])
    return {
        "ok": not missing and (
            not llm.get("enabled") or provider_status.get("configured")
        ),
        "comfyui_version": system.get("comfyui_version"),
        "python_version": system.get("python_version"),
        "devices": [
            {
                "name": item.get("name"),
                "vram_total_gb": round(
                    float(item.get("vram_total", 0)) / (1024**3),
                    2,
                ),
                "vram_free_gb": round(
                    float(item.get("vram_free", 0)) / (1024**3),
                    2,
                ),
            }
            for item in devices
        ],
        "workflow_nodes": len(graph),
        "missing_nodes": missing,
        "llm": provider_status,
    }


def generate(
    config: dict[str, Any],
    *,
    run_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    selected_run_id, destination, jobs = load_or_create_plan(config, run_id)
    client = _client(config)
    client.system_stats()
    references = _reference_map(config)
    state_path = destination / "state.json"
    state = load_json(state_path) if state_path.exists() else {
        "run_id": selected_run_id,
        "jobs": {},
    }
    candidate_dir = destination / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)

    pending = [
        job
        for job in jobs
        if state["jobs"].get(job["job_id"], {}).get("status") != "completed"
    ]
    if limit is not None:
        pending = pending[: max(0, int(limit))]

    for index, job in enumerate(pending, 1):
        job_id = job["job_id"]
        print(f"[{index}/{len(pending)}] 生成 {job_id}", flush=True)
        state["jobs"][job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "job": job,
        }
        save_json(state_path, state)

        reference_filename = None
        reference_id = job.get("reference_id")
        if reference_id and job.get("reference_strength", 0) > 0:
            reference = references.get(reference_id)
            if not reference:
                raise KeyError(f"未知 reference_id: {reference_id}")
            reference_path = Path(reference["path"])
            suffix = reference_path.suffix.lower() or ".png"
            relative = (
                f"character_lora_forge/{config['character_id']}/"
                f"{reference_id}{suffix}"
            )
            reference_filename = client.copy_to_input(
                reference_path,
                relative,
            )

        prefix = (
            f"character_lora_forge/{config['character_id']}/"
            f"{selected_run_id}/{job_id}"
        )
        graph = build_prompt_graph(
            config["comfyui"]["workflow_template"],
            config,
            job,
            filename_prefix=prefix,
            reference_filename=reference_filename,
        )
        try:
            prompt_id = client.queue_prompt(graph)
            state["jobs"][job_id]["prompt_id"] = prompt_id
            save_json(state_path, state)
            record = client.wait_for_prompt(
                prompt_id,
                timeout_seconds=int(
                    config["comfyui"].get("generation_timeout", 1800)
                ),
            )
            images = output_images(record)
            if not images:
                raise ComfyError("任务完成但没有图像输出")
            image = images[-1]
            suffix = Path(str(image.get("filename") or "candidate.png")).suffix
            suffix = suffix if suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
            candidate_path = candidate_dir / f"{job_id}{suffix}"
            client.copy_output_image(image, candidate_path)
            metadata = {
                "job": job,
                "prompt_id": prompt_id,
                "comfy_output": image,
                "candidate": str(candidate_path),
                "completed_at": datetime.now().isoformat(timespec="seconds"),
            }
            save_json(candidate_path.with_suffix(".json"), metadata)
            state["jobs"][job_id].update(
                {
                    "status": "completed",
                    "candidate": str(candidate_path),
                    "completed_at": metadata["completed_at"],
                }
            )
        except Exception as exc:
            state["jobs"][job_id].update(
                {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "failed_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            save_json(state_path, state)
            raise
        save_json(state_path, state)

    completed = [
        item
        for item in state["jobs"].values()
        if item.get("status") == "completed"
    ]
    return {
        "run_id": selected_run_id,
        "run_dir": str(destination),
        "completed": len(completed),
        "remaining": len(jobs) - len(completed),
    }


def _load_visual_spec(config: dict[str, Any]) -> dict[str, Any]:
    path = config.get("visual_spec")
    if path:
        spec_path = Path(path)
        if not spec_path.is_absolute():
            spec_path = Path(config["_project_dir"]) / spec_path
        return load_json(spec_path.resolve())
    return config["identity"]


def score(
    config: dict[str, Any],
    *,
    run_id: str,
    use_llm: bool = True,
    limit: int | None = None,
    auto_promote: bool = False,
) -> dict[str, Any]:
    destination = run_dir(config, run_id)
    state = load_json(destination / "state.json")
    plan = load_json(destination / "plan.json")
    job_map = {job["job_id"]: job for job in plan["jobs"]}
    completed = [
        (job_id, item)
        for job_id, item in state["jobs"].items()
        if item.get("status") == "completed" and item.get("candidate")
    ]
    if limit is not None:
        completed = completed[: max(0, int(limit))]

    references = [
        Path(item["path"])
        for item in config.get("references", [])
        if item.get("use_for_scoring", True)
    ]
    visual_spec = _load_visual_spec(config)
    llm_config = config["selection"]["llm"]
    llm_enabled = bool(use_llm and llm_config.get("enabled"))
    duplicate_distance = int(
        config["selection"].get("duplicate_hash_distance", 3)
    )

    results: list[dict[str, Any]] = []
    prior_hashes: list[tuple[str, str]] = []
    for index, (job_id, item) in enumerate(completed, 1):
        print(f"[{index}/{len(completed)}] 技术检查 {job_id}", flush=True)
        job = job_map[job_id]
        candidate = Path(item["candidate"])
        technical = technical_score(
            candidate,
            job["width"],
            job["height"],
        )
        duplicate_of = None
        for other_job, other_hash in prior_hashes:
            if hash_distance(technical["hash"], other_hash) <= duplicate_distance:
                duplicate_of = other_job
                break
        prior_hashes.append((job_id, technical["hash"]))

        hard_reject = bool(
            technical["hard_reject"]
            or duplicate_of
        )
        results.append(
            {
                "job_id": job_id,
                "batch_id": job["batch_id"],
                "style_id": job["style_id"],
                "candidate": str(candidate),
                "technical": technical,
                "vlm": None,
                "vlm_error": None,
                "duplicate_of": duplicate_of,
                "hard_reject": hard_reject,
                "manual_source_approved": bool(
                    job.get("_manual_source_approved", False)
                ),
                "final_score": combined_score(technical, None),
            }
        )

    if llm_enabled:
        eligible = [
            index
            for index, item in enumerate(results)
            if not item["hard_reject"]
        ]
        workers = max(1, int(llm_config.get("max_workers", 1)))

        def request_score(result_index: int) -> dict[str, Any]:
            item = results[result_index]
            job = job_map[item["job_id"]]
            attempts = max(1, int(llm_config.get("retry_attempts", 3)))
            last_error: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return score_candidate(
                        llm_config,
                        candidate=Path(item["candidate"]),
                        references=references,
                        visual_spec=visual_spec,
                        expected=job["expected"],
                        trigger_token=config["trigger_token"],
                    )
                except (VLMError, OSError, ValueError) as exc:
                    last_error = exc
                    if attempt < attempts:
                        time.sleep(min(8, 2 ** attempt))
            assert last_error is not None
            raise last_error

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(request_score, result_index): result_index
                for result_index in eligible
            }
            for completed_count, future in enumerate(
                as_completed(futures),
                1,
            ):
                result_index = futures[future]
                item = results[result_index]
                print(
                    f"[{completed_count}/{len(futures)}] LLM 筛选 "
                    f"{item['job_id']}",
                    flush=True,
                )
                try:
                    item["vlm"] = future.result()
                except (VLMError, OSError, ValueError) as exc:
                    item["vlm_error"] = f"{type(exc).__name__}: {exc}"
                if not item.get("manual_source_approved"):
                    item["hard_reject"] = bool(
                        item["hard_reject"]
                        or (
                            item["vlm"]
                            and item["vlm"].get("hard_reject")
                        )
                    )
                item["final_score"] = combined_score(
                    item["technical"],
                    item["vlm"],
                )

    selection = config["selection"]
    threshold = float(selection.get("gold_threshold", 82))
    target = int(selection.get("target_gold", 10))
    max_per_style = selection.get("max_per_style") or {}
    min_per_style = selection.get("min_per_style") or {}
    min_per_batch = selection.get("min_per_batch") or {}
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    style_counts: dict[str, int] = {}
    batch_counts: dict[str, int] = {}
    ranked = sorted(
        results,
        key=lambda row: float(row["final_score"]),
        reverse=True,
    )

    def select_item(item: dict[str, Any]) -> bool:
        if len(selected) >= target or item["job_id"] in selected_ids:
            return False
        manual_approved = bool(item.get("manual_source_approved"))
        if llm_enabled and item.get("vlm") is None and not manual_approved:
            return False
        if item["hard_reject"]:
            return False
        if not manual_approved and float(item["final_score"]) < threshold:
            return False
        if (
            not manual_approved
            and (item.get("vlm") or {}).get("decision") == "reject"
        ):
            return False
        style_id = item["style_id"]
        cap = int(max_per_style.get(style_id, target))
        if style_counts.get(style_id, 0) >= cap:
            return False
        selected.append(item)
        selected_ids.add(item["job_id"])
        style_counts[style_id] = style_counts.get(style_id, 0) + 1
        batch_id = item["batch_id"]
        batch_counts[batch_id] = batch_counts.get(batch_id, 0) + 1
        return True

    for style_id, minimum in min_per_style.items():
        for item in ranked:
            if style_counts.get(style_id, 0) >= int(minimum):
                break
            if item["style_id"] == style_id:
                select_item(item)

    for batch_id, minimum in min_per_batch.items():
        for item in ranked:
            if batch_counts.get(batch_id, 0) >= int(minimum):
                break
            if item["batch_id"] == batch_id:
                select_item(item)

    for item in ranked:
        if len(selected) >= target:
            break
        select_item(item)

    for item in results:
        item["machine_gold"] = item["job_id"] in selected_ids

    save_json(destination / "scores.json", results)
    machine_gold_dir = destination / "machine_gold"
    machine_gold_dir.mkdir(parents=True, exist_ok=True)
    job_ids = {item["job_id"] for item in results}
    for existing in machine_gold_dir.iterdir():
        if existing.is_file() and any(
            existing.name.startswith(f"{job_id}.")
            for job_id in job_ids
        ):
            existing.unlink()
    for item in selected:
        source = Path(item["candidate"])
        copied = machine_gold_dir / source.name
        shutil.copy2(source, copied)
        vlm_result = item.get("vlm") or {}
        caption = str(vlm_result.get("caption") or "").strip()
        if caption:
            copied.with_suffix(".txt").write_text(caption, encoding="utf-8")
        save_json(copied.with_suffix(".score.json"), item)

    review = write_review_html(
        destination,
        results,
        config["display_name"],
    )
    promoted = []
    if auto_promote:
        promoted = promote(config, run_id=run_id)
    return {
        "run_id": run_id,
        "scored": len(results),
        "machine_gold": len(selected),
        "review": str(review),
        "manual_audit_required": bool(
            config["selection"].get("require_manual_audit", False)
        ),
        "promoted": promoted,
    }


def record_manual_audit(
    config: dict[str, Any],
    *,
    run_id: str,
    status: str,
    notes: str,
    sampled_job_ids: list[str] | None = None,
    excluded_job_ids: list[str] | None = None,
) -> dict[str, Any]:
    allowed = {"approved", "rejected", "needs_revision"}
    if status not in allowed:
        raise ValueError(
            f"manual audit status 必须是: {', '.join(sorted(allowed))}"
        )
    destination = run_dir(config, run_id)
    if not (destination / "plan.json").is_file():
        raise FileNotFoundError(f"run 不存在: {run_id}")
    record = {
        "run_id": run_id,
        "status": status,
        "reviewer": "codex_visual_review",
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "sampled_job_ids": sampled_job_ids or [],
        "excluded_job_ids": excluded_job_ids or [],
        "notes": notes,
    }
    save_json(destination / "manual_audit.json", record)
    return record


def promote(config: dict[str, Any], *, run_id: str) -> list[str]:
    destination = run_dir(config, run_id)
    if config["selection"].get("require_manual_audit", False):
        audit_path = destination / "manual_audit.json"
        if not audit_path.is_file():
            raise RuntimeError(
                "缺少 manual_audit.json；必须先由 Codex 完成视觉抽检"
            )
        audit = load_json(audit_path)
        if audit.get("status") != "approved":
            raise RuntimeError(
                f"manual audit 未批准，当前状态: {audit.get('status')}"
            )
    scores = load_json(destination / "scores.json")
    project_dir = Path(config["_project_dir"])
    promotion_dir = project_dir / config["selection"].get(
        "promotion_dir",
        "03_seed_v0",
    )
    promotion_dir.mkdir(parents=True, exist_ok=True)
    promoted: list[str] = []
    for item in scores:
        if not item.get("machine_gold"):
            continue
        source = Path(item["candidate"])
        target = promotion_dir / source.name
        shutil.copy2(source, target)
        vlm = item.get("vlm") or {}
        caption = str(vlm.get("caption") or "").strip()
        if caption:
            target.with_suffix(".txt").write_text(caption, encoding="utf-8")
        save_json(target.with_suffix(".score.json"), item)
        promoted.append(str(target))
    return promoted
