from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


CAMPAIGN = Path(
    r"G:\ComfyUI-aki-v3\character_lora_forge\characters\alicia_bell\runs\20260818_20x200_campaign"
)
BASE_REVIEW = CAMPAIGN / "split_lora_selection" / "reviews" / "morning_star_replacements_51.json"
CURRENT_MANIFEST = CAMPAIGN / "final_training_split_200" / "morning_star" / "selection_manifest.json"
FAILED_AUDIT = CAMPAIGN / "final_training_split_200" / "morning_star" / "global_visual_audit.json"
REPAIR_ROOT = CAMPAIGN / "split_lora_selection" / "repair_generation"
BATCH_REVIEWS = (
    REPAIR_ROOT / "batch_main" / "batch_main_review.json",
    REPAIR_ROOT / "batch_a" / "batch_a_review.json",
    REPAIR_ROOT / "batch_b" / "batch_b_review.json",
)
OUTPUT = CAMPAIGN / "split_lora_selection" / "reviews" / "morning_star_replacements_51_final.json"
HOSIERY_PHRASE = (
    "very sheer ivory pantyhose covering both legs and feet, "
    "warm skin tone visible through the fabric"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    base = json.loads(BASE_REVIEW.read_text(encoding="utf-8"))
    current = json.loads(CURRENT_MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(FAILED_AUDIT.read_text(encoding="utf-8"))
    rejected = {item["final_stem"]: item for item in audit["hard_rejects"]}
    current_hashes = {item["sha256"].upper() for item in current["records"]}

    replacements = list(base["replacements"])
    if len(replacements) != 30:
        raise RuntimeError(f"Expected 30 frozen-pool replacements, found {len(replacements)}")

    for review_path in BATCH_REVIEWS:
        review = json.loads(review_path.read_text(encoding="utf-8"))
        batch_records = review.get("records") or review.get("items") or []
        passed_count = review.get(
            "count",
            review.get("reviewed_count", review.get("counts", {}).get("passed")),
        )
        if review.get("status") != "pass" or passed_count != 7 or len(batch_records) != 7:
            raise RuntimeError(f"Repair batch must pass with 7 records: {review_path}")
        for item in batch_records:
            source = Path(item["output_path"])
            if sha256_file(source) != item["output_sha256"].upper():
                raise RuntimeError(f"Generated repair hash mismatch: {source}")
            if item["caption"].lower().count(HOSIERY_PHRASE.lower()) != 1:
                raise RuntimeError(f"Invalid hosiery caption: {item['rejected_final_stem']}")
            replacements.append(
                {
                    "rejected_final_stem": item["rejected_final_stem"],
                    "round_id": item.get("round_id")
                    or next(
                        part
                        for part in item["rejected_final_stem"].split("_")
                        if part.startswith("R") and len(part) == 3
                    ),
                    "source_path": str(source.resolve()),
                    "source_name": source.name,
                    "sha256": item["output_sha256"].upper(),
                    "contact_label": "imagegen_hosiery_repair",
                    "selection_reason": (
                        "Identity-preserving edit repairs the failed legwear while retaining "
                        "the source pose, scene, and rendering style."
                    ),
                    "leg_visibility": "both legs and feet visible",
                    "hosiery_visual_assessment": item["visual_assessment"],
                    "caption": item["caption"],
                    "source_kind": "imagegen_hosiery_repair",
                    "original_path": item["original_path"],
                    "original_sha256": item["original_sha256"].upper(),
                }
            )

    stems = [item["rejected_final_stem"] for item in replacements]
    hashes = [item["sha256"].upper() for item in replacements]
    if len(replacements) != 51 or set(stems) != set(rejected):
        raise RuntimeError("Merged replacements must map exactly to all 51 hard rejects")
    if len(set(stems)) != 51 or len(set(hashes)) != 51:
        raise RuntimeError("Merged replacements must have unique stems and hashes")
    if current_hashes.intersection(hashes):
        raise RuntimeError("Merged replacements overlap the failed 200-image dataset")
    for item in replacements:
        if item["round_id"] not in item["rejected_final_stem"]:
            raise RuntimeError(f"Round mismatch: {item['rejected_final_stem']}")

    replacements.sort(key=lambda item: item["rejected_final_stem"])
    round_counts = Counter(item["round_id"] for item in replacements)
    output = {
        "schema_version": 2,
        "status": "pass",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "form": "morning_star",
        "trigger_token": "alcbm7yo260822",
        "fixed_hosiery_phrase": HOSIERY_PHRASE,
        "counts": {
            "total": len(replacements),
            "frozen_pool": 30,
            "imagegen_repairs": 21,
            "unique_sha256": len(set(hashes)),
        },
        "per_round_counts": dict(sorted(round_counts.items())),
        "source_reviews": [str(BASE_REVIEW.resolve())]
        + [str(path.resolve()) for path in BATCH_REVIEWS],
        "replacements": replacements,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
    print(json.dumps(output["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
