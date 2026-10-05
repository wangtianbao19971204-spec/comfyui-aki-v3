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
SOURCE_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star_v4"
SOURCE_MANIFEST = SOURCE_ROOT / "selection_manifest.json"
SOURCE_AUDIT = SOURCE_ROOT / "global_visual_audit.json"
GENERATED_IMAGE = Path(
    r"C:\Users\Administrator\.codex\generated_images\01a01c63-5be8-7e01-9e93-bcc55d101fde\exec-5abab50d-c1e9-4d3a-95ec-37fe21144985.png"
)
REPAIR_ROOT = CAMPAIGN / "split_lora_selection" / "repair_generation_v5"
REPAIR_IMAGE = REPAIR_ROOT / "alcbm7yo260822_morning_star_R08_04_repair.png"
REPAIR_REVIEW = REPAIR_ROOT / "v4_to_v5_repair_review.json"
OUTPUT_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star_v5"
TRIGGER = "alcbm7yo260822"
IMAGE_REPAIR_STEM = f"{TRIGGER}_morning_star_R08_04"
CAPTION_ONLY_STEM = f"{TRIGGER}_morning_star_R07_09"
CAPTION_ONLY_TEXT = (
    f"{TRIGGER}, adult Alicia Bell, Morning Star form, peach-gold tied hair with a wine "
    "ribbon and a gold five-point hair accessory, ivory and wine-red idol dress, cropped "
    "side conducting gesture beside a night-city light tower."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def normalize_caption(caption: str) -> str:
    result = caption.strip().rstrip(".")
    if not result.startswith(f"{TRIGGER},"):
        raise RuntimeError("Caption trigger mismatch")
    return result + "."


def main() -> int:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(SOURCE_AUDIT.read_text(encoding="utf-8"))
    hard_reject_stems = {item["final_stem"] for item in audit.get("hard_rejects", [])}
    correction_stems = {
        item["final_stem"] for item in audit.get("caption_corrections_needed", [])
    }
    if audit.get("status") != "fail" or hard_reject_stems != {IMAGE_REPAIR_STEM}:
        raise RuntimeError("Expected the single v4 R08_04 visual rejection")
    if correction_stems != {CAPTION_ONLY_STEM, IMAGE_REPAIR_STEM}:
        raise RuntimeError("Unexpected v4 caption-correction set")
    if len(manifest.get("records", [])) != 200 or not GENERATED_IMAGE.is_file():
        raise RuntimeError("Expected 200 source records and one generated repair image")

    old_records = {item["final_stem"]: item for item in manifest["records"]}
    old_hashes = {item["sha256"].upper() for item in manifest["records"]}
    generated_sha = sha256_file(GENERATED_IMAGE)
    if generated_sha in old_hashes:
        raise RuntimeError("The v5 repair must be a new image")

    REPAIR_ROOT.mkdir(parents=True, exist_ok=True)
    if REPAIR_IMAGE.exists():
        if sha256_file(REPAIR_IMAGE) != generated_sha:
            raise RuntimeError("Existing stable repair image has a different hash")
    else:
        shutil.copy2(GENERATED_IMAGE, REPAIR_IMAGE)
    repair_review = {
        "schema_version": 1,
        "status": "pass",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_failed_audit": str(SOURCE_AUDIT.resolve()),
        "items": [
            {
                "rejected_final_stem": IMAGE_REPAIR_STEM,
                "original_path": old_records[IMAGE_REPAIR_STEM]["final_image_path"],
                "original_sha256": old_records[IMAGE_REPAIR_STEM]["sha256"].upper(),
                "output_path": str(REPAIR_IMAGE.resolve()),
                "output_sha256": generated_sha,
                "visual_assessment": (
                    "Native-resolution review passes: continuous plain very sheer ivory "
                    "pantyhose with no stocking-top band; Morning Star identity and cafe "
                    "composition remain coherent."
                ),
            }
        ],
        "caption_only_corrections": [CAPTION_ONLY_STEM],
    }
    REPAIR_REVIEW.write_text(
        json.dumps(repair_review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    dataset = OUTPUT_ROOT / "dataset"
    if OUTPUT_ROOT.exists() and any(OUTPUT_ROOT.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty output: {OUTPUT_ROOT}")
    dataset.mkdir(parents=True, exist_ok=True)

    output_records = []
    for old in manifest["records"]:
        stem = old["final_stem"]
        source = Path(old["final_image_path"])
        caption = normalize_caption(old["caption"])
        record = dict(old)
        if stem == IMAGE_REPAIR_STEM:
            source = REPAIR_IMAGE
            record.update(
                {
                    "source_kind": "v5_hosiery_contract_repair",
                    "source_path": str(source.resolve()),
                    "source_name": source.name,
                    "sha256": generated_sha,
                    "replaced_sha256": old["sha256"].upper(),
                    "repair_review": str(REPAIR_REVIEW.resolve()),
                }
            )
        elif stem == CAPTION_ONLY_STEM:
            caption = CAPTION_ONLY_TEXT
            record.update(
                {
                    "previous_source_kind": old["source_kind"],
                    "caption_correction_version": "v5_visible-content-only",
                }
            )

        target_image = dataset / f"{stem}.png"
        target_caption = dataset / f"{stem}.txt"
        shutil.copy2(source, target_image)
        target_caption.write_text(caption + "\n", encoding="utf-8")
        actual_sha = sha256_file(target_image)
        if actual_sha != record["sha256"].upper():
            raise RuntimeError(f"Image hash mismatch after copy: {stem}")
        record.update(
            {
                "caption": caption,
                "final_image_path": str(target_image.resolve()),
                "final_caption_path": str(target_caption.resolve()),
            }
        )
        output_records.append(record)

    round_counts = Counter(item["round_id"] for item in output_records)
    output_hashes = [item["sha256"].upper() for item in output_records]
    if len(output_records) != 200 or len(set(output_hashes)) != 200:
        raise RuntimeError("v5 must contain 200 unique images")
    if set(round_counts.values()) != {10} or len(round_counts) != 20:
        raise RuntimeError("v5 must retain 10 images in each of 20 rounds")

    output_manifest = {
        "schema_version": 5,
        "status": "assembled_pending_global_audit",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "form": "morning_star",
        "trigger_token": TRIGGER,
        "source_failed_manifest": str(SOURCE_MANIFEST.resolve()),
        "source_failed_audit": str(SOURCE_AUDIT.resolve()),
        "repair_reviews": [str(REPAIR_REVIEW.resolve())],
        "audit_adjudication": manifest.get("audit_adjudication"),
        "counts": {
            "images": 200,
            "captions": 200,
            "v5_image_replacements": 1,
            "v5_caption_only_corrections": 1,
            "cumulative_image_replacements": 23,
            "unique_sha256": 200,
        },
        "per_round_counts": dict(sorted(round_counts.items())),
        "hosiery_caption_policy": manifest["hosiery_caption_policy"],
        "dataset_path": str(dataset.resolve()),
        "records": output_records,
    }
    output_path = OUTPUT_ROOT / "selection_manifest.json"
    output_path.write_text(
        json.dumps(output_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output_path)
    print(json.dumps(output_manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
