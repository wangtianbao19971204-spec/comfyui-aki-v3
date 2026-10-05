from __future__ import annotations

import hashlib
from typing import Any


def _clean(parts: list[str]) -> str:
    return ", ".join(
        part.strip(" ,\n")
        for part in parts
        if isinstance(part, str) and part.strip(" ,\n")
    )


def stable_seed(base_seed: int, job_id: str) -> int:
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()
    offset = int.from_bytes(digest[:8], "big")
    return (int(base_seed) + offset) % 1_125_899_906_842_624


def build_jobs(config: dict[str, Any]) -> list[dict[str, Any]]:
    generation = config["generation"]
    styles = generation["styles"]
    identity = config["identity"]
    jobs: list[dict[str, Any]] = []

    for batch in generation["batches"]:
        style_ids = batch.get("styles") or [generation["default_style"]]
        count = int(batch.get("count", 1))
        for style_id in style_ids:
            style = styles[style_id]
            for index in range(1, count + 1):
                job_id = f"{batch['id']}__{style_id}__{index:03d}"
                positive = _clean(
                    [
                        generation.get("quality_prompt", ""),
                        identity.get("positive_prompt", ""),
                        batch.get("framing", ""),
                        batch.get("view", ""),
                        batch.get("pose", ""),
                        batch.get("expression", ""),
                        batch.get("outfit", ""),
                        batch.get("equipment", ""),
                        batch.get("background", ""),
                        batch.get("lighting", ""),
                        style.get("prompt", ""),
                        batch.get("extra_prompt", ""),
                    ]
                )
                negative = _clean(
                    [
                        generation.get("negative_prompt", ""),
                        identity.get("negative_prompt", ""),
                        style.get("negative_prompt", ""),
                        batch.get("negative_prompt", ""),
                    ]
                )
                width = int(batch.get("width", style.get("width", generation["width"])))
                height = int(batch.get("height", style.get("height", generation["height"])))
                jobs.append(
                    {
                        "job_id": job_id,
                        "batch_id": batch["id"],
                        "style_id": style_id,
                        "style_tier": style.get("tier", "anchor"),
                        "index": index,
                        "seed": stable_seed(generation["base_seed"], job_id),
                        "width": width,
                        "height": height,
                        "positive": positive,
                        "negative": negative,
                        "reference_id": batch.get(
                            "reference_id",
                            generation.get("default_reference_id"),
                        ),
                        "reference_strength": float(
                            batch.get(
                                "reference_strength",
                                style.get(
                                    "reference_strength",
                                    generation.get("reference_strength", 0),
                                ),
                            )
                        ),
                        "expected": {
                            "framing": batch.get("framing", ""),
                            "view": batch.get("view", ""),
                            "pose": batch.get("pose", ""),
                            "outfit": batch.get("outfit", ""),
                            "equipment": batch.get("equipment", ""),
                            "background": batch.get("background", ""),
                            "style": style.get("prompt", ""),
                        },
                    }
                )
    return jobs
