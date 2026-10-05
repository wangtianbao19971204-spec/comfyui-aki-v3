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
SOURCE_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star"
SOURCE_MANIFEST = SOURCE_ROOT / "selection_manifest.json"
SOURCE_AUDIT = SOURCE_ROOT / "global_visual_audit.json"
REPLACEMENTS = (
    CAMPAIGN
    / "split_lora_selection"
    / "reviews"
    / "morning_star_replacements_51_final.json"
)
OUTPUT_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star_v2"
TRIGGER = "alcbm7yo260822"
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


def clean_caption(caption: str) -> str:
    caption = caption.strip().rstrip(".")
    if not caption.startswith(f"{TRIGGER},"):
        raise RuntimeError("Caption trigger mismatch")
    if "very sheer very sheer" in caption.lower():
        raise RuntimeError("Malformed duplicated hosiery wording")
    if caption.lower().count(HOSIERY_PHRASE.lower()) > 1:
        raise RuntimeError("Duplicated fixed hosiery phrase")
    return caption + ".\n"


def main() -> int:
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(SOURCE_AUDIT.read_text(encoding="utf-8"))
    replacement_review = json.loads(REPLACEMENTS.read_text(encoding="utf-8"))

    if audit.get("status") != "fail":
        raise RuntimeError("Expected a failed source visual audit")
    if replacement_review.get("status") != "pass":
        raise RuntimeError("Replacement review must have status=pass")

    rejects = {item["final_stem"]: item for item in audit["hard_rejects"]}
    corrections = {
        item["final_stem"]: item["replacement_caption"]
        for item in audit["caption_corrections_needed"]
    }
    replacements = {
        item["rejected_final_stem"]: item
        for item in replacement_review["replacements"]
    }
    if len(rejects) != 51 or set(replacements) != set(rejects):
        raise RuntimeError("Replacement set must map exactly to all 51 hard rejects")

    source_records = source_manifest["records"]
    current_hashes = {item["sha256"].upper() for item in source_records}
    replacement_hashes = [item["sha256"].upper() for item in replacements.values()]
    if len(set(replacement_hashes)) != 51:
        raise RuntimeError("Replacement SHA256 values must be unique")
    if current_hashes.intersection(replacement_hashes):
        raise RuntimeError("Replacement set overlaps the failed 200-image dataset")

    dataset = OUTPUT_ROOT / "dataset"
    if OUTPUT_ROOT.exists() and any(OUTPUT_ROOT.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty output: {OUTPUT_ROOT}")
    dataset.mkdir(parents=True, exist_ok=True)

    output_records = []
    for old in source_records:
        stem = old["final_stem"]
        record = dict(old)
        if stem in replacements:
            selected = replacements[stem]
            source = Path(selected["source_path"])
            if selected["round_id"] != old["round_id"]:
                raise RuntimeError(f"Round mismatch for {stem}")
            if sha256_file(source) != selected["sha256"].upper():
                raise RuntimeError(f"Replacement hash mismatch: {source}")
            record.update(
                {
                    "source_path": str(source.resolve()),
                    "source_name": source.name,
                    "sha256": selected["sha256"].upper(),
                    "caption": selected["caption"],
                    "source_kind": "hosiery_repair_replacement",
                    "selection_reason": selected["selection_reason"],
                    "replaced_sha256": old["sha256"].upper(),
                    "replacement_visual_assessment": selected["hosiery_visual_assessment"],
                }
            )
        else:
            source = Path(old["source_path"])
            if stem in corrections:
                record["caption"] = corrections[stem]

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
        raise RuntimeError("Repaired dataset must contain 200 unique records")
    if set(round_counts.values()) != {10}:
        raise RuntimeError(f"Expected 10 records per round: {dict(round_counts)}")

    manifest = {
        "schema_version": 2,
        "status": "assembled_pending_global_audit",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "form": "morning_star",
        "trigger_token": TRIGGER,
        "source_failed_manifest": str(SOURCE_MANIFEST.resolve()),
        "source_failed_audit": str(SOURCE_AUDIT.resolve()),
        "replacement_review": str(REPLACEMENTS.resolve()),
        "counts": {
            "images": len(list(dataset.glob("*.png"))),
            "captions": len(list(dataset.glob("*.txt"))),
            "replacements": len(replacements),
            "caption_corrections": len(corrections),
            "unique_sha256": len(set(hashes)),
        },
        "per_round_counts": dict(sorted(round_counts.items())),
        "hosiery_caption_policy": HOSIERY_PHRASE,
        "dataset_path": str(dataset.resolve()),
        "records": output_records,
    }
    manifest_path = OUTPUT_ROOT / "selection_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(manifest_path)
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
