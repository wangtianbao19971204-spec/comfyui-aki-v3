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
SOURCE_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star_v3"
SOURCE_MANIFEST = SOURCE_ROOT / "selection_manifest.json"
SOURCE_AUDIT = SOURCE_ROOT / "global_visual_audit.json"
REPAIR_ROOT = CAMPAIGN / "split_lora_selection" / "repair_generation_v4"
BATCH_REVIEWS = (
    REPAIR_ROOT / "mixed_batch" / "mixed_batch_review.json",
    REPAIR_ROOT / "hosiery_batch_a" / "hosiery_batch_a_review.json",
    REPAIR_ROOT / "hosiery_batch_b" / "hosiery_batch_b_review.json",
)
OUTPUT_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star_v4"
TRIGGER = "alcbm7yo260822"
HOSIERY_PHRASE = (
    "very sheer ivory pantyhose covering both legs and feet, "
    "warm skin tone visible through the fabric"
)
ADJUDICATED_PASS = {
    "alcbm7yo260822_morning_star_R16_05": (
        "Native-resolution coordinator review finds uniform uninterrupted sheer coverage; "
        "no distinct welt or stocking-top boundary is visible. The preceding independent "
        "v2 global audit also accepted this exact repaired image."
    ),
    "alcbm7yo260822_morning_star_R16_08": (
        "Native-resolution coordinator review finds uniform uninterrupted sheer coverage; "
        "the tonal transition is lighting, not a stocking-top edge. The preceding independent "
        "v2 global audit also accepted this exact repaired image."
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def review_count(review: dict) -> int | None:
    explicit = review.get(
        "count",
        review.get(
            "reviewed_count",
            review.get(
                "passed",
                review.get("passed_count", review.get("counts", {}).get("passed")),
            ),
        ),
    )
    if explicit is not None:
        return explicit
    items = review.get("items") or review.get("records")
    if review.get("status") == "pass" and isinstance(items, list):
        return len(items)
    return None


def clean_caption(caption: str) -> str:
    result = caption.strip().rstrip(".")
    if not result.startswith(f"{TRIGGER},"):
        raise RuntimeError("Caption trigger mismatch")
    if "very sheer very sheer" in result.lower():
        raise RuntimeError("Malformed hosiery caption")
    if result.lower().count(HOSIERY_PHRASE.lower()) > 1:
        raise RuntimeError("Duplicated hosiery caption phrase")
    return result + ".\n"


def main() -> int:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(SOURCE_AUDIT.read_text(encoding="utf-8"))
    if audit.get("status") != "fail":
        raise RuntimeError("Expected failed v3 global audit")
    rejects = {
        item.get("final_stem") or item.get("stem"): item
        for item in audit["hard_rejects"]
    }
    if len(rejects) != 24:
        raise RuntimeError(f"Expected 24 v3 hard rejects, found {len(rejects)}")

    repairs = {}
    for path in BATCH_REVIEWS:
        review = json.loads(path.read_text(encoding="utf-8"))
        items = review.get("items") or review.get("records") or []
        expected = 8 if "mixed_batch" in path.name else 7
        if review.get("status") != "pass" or review_count(review) != expected or len(items) != expected:
            raise RuntimeError(f"Repair batch must pass with {expected} records: {path}")
        for item in items:
            stem = item["rejected_final_stem"]
            output = Path(item["output_path"])
            if stem in repairs or sha256_file(output) != item["output_sha256"].upper():
                raise RuntimeError(f"Duplicate stem or hash mismatch: {stem}")
            repairs[stem] = item
    if set(repairs).intersection(ADJUDICATED_PASS):
        raise RuntimeError("A repaired stem cannot also be manually adjudicated")
    if set(repairs).union(ADJUDICATED_PASS) != set(rejects):
        raise RuntimeError("Repairs plus adjudications must cover all v3 hard rejects")

    old_hashes = {item["sha256"].upper() for item in manifest["records"]}
    repair_hashes = [item["output_sha256"].upper() for item in repairs.values()]
    if len(set(repair_hashes)) != 22 or old_hashes.intersection(repair_hashes):
        raise RuntimeError("v4 repair outputs must be 22 unique new images")

    dataset = OUTPUT_ROOT / "dataset"
    if OUTPUT_ROOT.exists() and any(OUTPUT_ROOT.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty output: {OUTPUT_ROOT}")
    dataset.mkdir(parents=True, exist_ok=True)

    output_records = []
    for old in manifest["records"]:
        stem = old["final_stem"]
        source = Path(old["final_image_path"])
        record = dict(old)
        if stem in repairs:
            repair = repairs[stem]
            source = Path(repair["output_path"])
            record.update(
                {
                    "source_path": str(source.resolve()),
                    "source_name": source.name,
                    "sha256": repair["output_sha256"].upper(),
                    "caption": repair["caption"],
                    "source_kind": "v4_contract_repair",
                    "replaced_sha256": old["sha256"].upper(),
                    "replacement_visual_assessment": repair["visual_assessment"],
                }
            )
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
    if len(output_records) != 200 or len(set(hashes)) != 200 or set(round_counts.values()) != {10}:
        raise RuntimeError("v4 must retain 200 unique records and 10 per round")

    adjudication = {
        "schema_version": 1,
        "status": "pass",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_audit": str(SOURCE_AUDIT.resolve()),
        "source_audit_sha256": sha256_file(SOURCE_AUDIT),
        "records": [
            {
                "final_stem": stem,
                "image_path": next(item["final_image_path"] for item in output_records if item["final_stem"] == stem),
                "image_sha256": next(item["sha256"] for item in output_records if item["final_stem"] == stem),
                "disposition": "pass_after_native_coordinator_review",
                "evidence": evidence,
            }
            for stem, evidence in ADJUDICATED_PASS.items()
        ],
    }
    adjudication_path = OUTPUT_ROOT / "v3_audit_adjudication.json"
    adjudication_path.write_text(json.dumps(adjudication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    output = {
        "schema_version": 4,
        "status": "assembled_pending_global_audit",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "form": "morning_star",
        "trigger_token": TRIGGER,
        "source_failed_manifest": str(SOURCE_MANIFEST.resolve()),
        "source_failed_audit": str(SOURCE_AUDIT.resolve()),
        "repair_reviews": [str(path.resolve()) for path in BATCH_REVIEWS],
        "audit_adjudication": str(adjudication_path.resolve()),
        "counts": {
            "images": len(list(dataset.glob("*.png"))),
            "captions": len(list(dataset.glob("*.txt"))),
            "image_replacements": len(repairs),
            "adjudicated_unchanged": len(ADJUDICATED_PASS),
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
