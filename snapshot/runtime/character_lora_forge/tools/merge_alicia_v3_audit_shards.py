from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_ROOT = Path(
    r"G:\ComfyUI-aki-v3\character_lora_forge\characters\alicia_bell\runs\20260818_20x200_campaign\final_training_split_200\morning_star_v3"
)
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_ROOT
    preflight_path = root / "global_review_preflight.json"
    shards = (root / "audit_shards" / "shard_a.json", root / "audit_shards" / "shard_b.json")
    output_path = root / "global_visual_audit.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight_sha = sha256_file(preflight_path)
    all_indexes = []
    hard_rejects = []
    caption_corrections = []
    native_checks = []
    shard_summaries = []
    for path in shards:
        shard = json.loads(path.read_text(encoding="utf-8"))
        if shard.get("global_review_preflight_sha256", "").upper() != preflight_sha:
            raise RuntimeError(f"Stale shard preflight hash: {path}")
        indexes = shard.get("assigned_indexes", [])
        if len(indexes) != len(set(indexes)):
            raise RuntimeError(f"Duplicate indexes inside shard: {path}")
        if shard.get("inspected_count") != len(indexes):
            raise RuntimeError(f"Shard inspected_count mismatch: {path}")
        all_indexes.extend(indexes)
        hard_rejects.extend(shard.get("hard_rejects", []))
        caption_corrections.extend(shard.get("caption_corrections_needed", []))
        native_checks.extend(shard.get("full_resolution_spot_checks", []))
        shard_summaries.append(
            {
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
                "status": shard.get("status"),
                "inspected_count": shard.get("inspected_count"),
            }
        )
    if sorted(all_indexes) != list(range(1, 201)) or len(all_indexes) != 200:
        raise RuntimeError("Audit shard union must cover indexes 1..200 exactly once")

    status = "pass" if not hard_rejects and not caption_corrections and all(
        item["status"] == "pass" for item in shard_summaries
    ) else "fail"
    output = {
        "schema_version": 1,
        "status": status,
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "form": "morning_star",
        "dataset_count": 200,
        "global_review_preflight": str(preflight_path),
        "global_review_preflight_sha256": preflight_sha,
        "selection_manifest_sha256": preflight["selection_manifest_sha256"],
        "dataset_audit_sha256": preflight["dataset_audit_sha256"],
        "pages_reviewed": 10,
        "inspected_count": len(all_indexes),
        "full_resolution_spot_checks": native_checks,
        "hard_rejects": hard_rejects,
        "caption_corrections_needed": caption_corrections,
        "shards": shard_summaries,
        "hosiery_summary": {
            "result": "pass" if not any(item.get("category") == "hosiery" for item in hard_rejects) else "fail",
            "fixed_phrase": "very sheer ivory pantyhose covering both legs and feet, warm skin tone visible through the fabric",
        },
        "reviewer_summary": (
            "Two non-overlapping visual-review shards covered all 200 records and all 10 pages."
        ),
        "next_action": "train" if status == "pass" else "repair findings and repeat full audit",
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    print(json.dumps({"status": status, "hard_rejects": len(hard_rejects), "caption_corrections": len(caption_corrections)}, indent=2))
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
