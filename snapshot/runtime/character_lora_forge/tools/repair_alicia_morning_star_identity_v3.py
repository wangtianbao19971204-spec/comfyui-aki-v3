from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path


CAMPAIGN = Path(
    r"G:\ComfyUI-aki-v3\character_lora_forge\characters\alicia_bell\runs\20260818_20x200_campaign"
)
SOURCE_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star_v2"
SOURCE_MANIFEST = SOURCE_ROOT / "selection_manifest.json"
SOURCE_AUDIT = SOURCE_ROOT / "global_visual_audit.json"
REPAIR_ROOT = CAMPAIGN / "split_lora_selection" / "repair_generation_v3"
BATCH_REVIEWS = (
    REPAIR_ROOT / "star_batch" / "star_batch_review.json",
    REPAIR_ROOT / "outfit_batch" / "outfit_batch_review.json",
)
OUTPUT_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star_v3"
TRIGGER = "alcbm7yo260822"
HOSIERY_PHRASE = (
    "very sheer ivory pantyhose covering both legs and feet, "
    "warm skin tone visible through the fabric"
)
CAPTION_ONLY = {
    "alcbm7yo260822_morning_star_R08_04": "append_hosiery",
    "alcbm7yo260822_morning_star_R10_02": "append_hosiery",
    "alcbm7yo260822_morning_star_R20_06": "repair_framing_and_hosiery",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def clean_caption(caption: str) -> str:
    result = caption.strip().rstrip(".")
    if not result.startswith(f"{TRIGGER},"):
        raise RuntimeError("Caption trigger mismatch")
    if "very sheer very sheer" in result.lower():
        raise RuntimeError("Malformed hosiery wording")
    if result.lower().count(HOSIERY_PHRASE.lower()) > 1:
        raise RuntimeError("Duplicated hosiery phrase")
    return result + ".\n"


def corrected_caption(stem: str, caption: str) -> str:
    action = CAPTION_ONLY.get(stem)
    if not action:
        return caption
    result = caption.strip().rstrip(".")
    if action == "repair_framing_and_hosiery":
        result = result.replace("upper-body pose", "full-body doorway pose")
    if HOSIERY_PHRASE.lower() not in result.lower():
        result += ", " + HOSIERY_PHRASE
    return result + "."


def main() -> int:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(SOURCE_AUDIT.read_text(encoding="utf-8"))
    if audit.get("status") != "fail":
        raise RuntimeError("Expected failed v2 global visual audit")
    rejects = {item["final_stem"]: item for item in audit["hard_reject_details"]}
    if len(rejects) != 12:
        raise RuntimeError(f"Expected 12 v2 hard rejects, found {len(rejects)}")

    repairs = {}
    for review_path in BATCH_REVIEWS:
        review = json.loads(review_path.read_text(encoding="utf-8"))
        items = review.get("items") or review.get("records") or []
        passed = review.get(
            "count",
            review.get(
                "reviewed_count",
                review.get(
                    "passed",
                    review.get("passed_count", review.get("counts", {}).get("passed")),
                ),
            ),
        )
        if review.get("status") != "pass" or passed != 6 or len(items) != 6:
            raise RuntimeError(f"Repair batch must pass with 6 records: {review_path}")
        for item in items:
            stem = item["rejected_final_stem"]
            source = Path(item["output_path"])
            if stem in repairs:
                raise RuntimeError(f"Duplicate repair stem: {stem}")
            if sha256_file(source) != item["output_sha256"].upper():
                raise RuntimeError(f"Repair hash mismatch: {source}")
            repairs[stem] = item
    if set(repairs) != set(rejects):
        raise RuntimeError("Identity repairs must map exactly to all 12 v2 hard rejects")

    old_hashes = {item["sha256"].upper() for item in manifest["records"]}
    new_hashes = [item["output_sha256"].upper() for item in repairs.values()]
    if len(set(new_hashes)) != 12 or old_hashes.intersection(new_hashes):
        raise RuntimeError("Identity repair outputs must be unique and new")

    dataset = OUTPUT_ROOT / "dataset"
    if OUTPUT_ROOT.exists() and any(OUTPUT_ROOT.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty output: {OUTPUT_ROOT}")
    dataset.mkdir(parents=True, exist_ok=True)

    output_records = []
    for old in manifest["records"]:
        stem = old["final_stem"]
        record = dict(old)
        source = Path(old["final_image_path"])
        if stem in repairs:
            repair = repairs[stem]
            source = Path(repair["output_path"])
            record.update(
                {
                    "source_path": str(source.resolve()),
                    "source_name": source.name,
                    "sha256": repair["output_sha256"].upper(),
                    "caption": repair["caption"],
                    "source_kind": "identity_contract_repair",
                    "replaced_sha256": old["sha256"].upper(),
                    "replacement_visual_assessment": repair["visual_assessment"],
                }
            )
        else:
            record["caption"] = corrected_caption(stem, old["caption"])

        destination = dataset / f"{stem}{source.suffix.lower()}"
        caption_path = dataset / f"{stem}.txt"
        shutil.copy2(source, destination)
        caption = clean_caption(record["caption"])
        caption_path.write_text(caption, encoding="utf-8")
        record.update(
            {
                "final_image_path": str(destination.resolve()),
                "final_caption_path": str(caption_path.resolve()),
                "caption": caption.strip(),
            }
        )
        output_records.append(record)

    hashes = [item["sha256"].upper() for item in output_records]
    round_counts = Counter(item["round_id"] for item in output_records)
    if len(output_records) != 200 or len(set(hashes)) != 200:
        raise RuntimeError("v3 dataset must contain 200 unique records")
    if set(round_counts.values()) != {10}:
        raise RuntimeError("v3 dataset must retain 10 records per round")

    output = {
        "schema_version": 3,
        "status": "assembled_pending_global_audit",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "form": "morning_star",
        "trigger_token": TRIGGER,
        "source_failed_manifest": str(SOURCE_MANIFEST.resolve()),
        "source_failed_audit": str(SOURCE_AUDIT.resolve()),
        "repair_reviews": [str(path.resolve()) for path in BATCH_REVIEWS],
        "counts": {
            "images": len(list(dataset.glob("*.png"))),
            "captions": len(list(dataset.glob("*.txt"))),
            "identity_replacements": len(repairs),
            "caption_only_corrections": len(CAPTION_ONLY),
            "unique_sha256": len(set(hashes)),
        },
        "per_round_counts": dict(sorted(round_counts.items())),
        "hosiery_caption_policy": HOSIERY_PHRASE,
        "dataset_path": str(dataset.resolve()),
        "records": output_records,
    }
    destination = OUTPUT_ROOT / "selection_manifest.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)
    print(json.dumps(output["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
