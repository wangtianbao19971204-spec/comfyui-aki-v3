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
    manifest_path = root / "selection_manifest.json"
    dataset_audit_path = root / "dataset_audit.json"
    sheet_index_path = root / "audit_contact_sheets" / "audit_sheet_manifest.json"
    output_path = root / "global_review_preflight.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_audit = json.loads(dataset_audit_path.read_text(encoding="utf-8"))
    sheet_index = json.loads(sheet_index_path.read_text(encoding="utf-8"))
    if not dataset_audit.get("passed"):
        raise RuntimeError("Dataset audit must pass before global review")
    if len(manifest["records"]) != 200 or len(sheet_index["pages"]) != 10:
        raise RuntimeError("Expected 200 records and 10 contact sheets")

    records = []
    for index, record in enumerate(manifest["records"], 1):
        image = Path(record["final_image_path"])
        caption = Path(record["final_caption_path"])
        records.append(
            {
                "global_index": index,
                "final_stem": record["final_stem"],
                "round_id": record["round_id"],
                "source_kind": record["source_kind"],
                "image_path": str(image.resolve()),
                "image_sha256": sha256_file(image),
                "caption_path": str(caption.resolve()),
                "caption_sha256": sha256_file(caption),
                "caption": record["caption"],
            }
        )

    sheets = []
    for page, value in enumerate(sheet_index["pages"], 1):
        path = Path(value)
        sheets.append({"page": page, "path": str(path.resolve()), "sha256": sha256_file(path)})

    output = {
        "schema_version": 1,
        "status": "ready_for_sharded_global_review",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "form": "morning_star",
        "dataset_count": 200,
        "selection_manifest": str(manifest_path),
        "selection_manifest_sha256": sha256_file(manifest_path),
        "dataset_audit": str(dataset_audit_path),
        "dataset_audit_sha256": sha256_file(dataset_audit_path),
        "contact_sheets": sheets,
        "assignments": {
            "shard_a": {"indexes": list(range(1, 101)), "pages": list(range(1, 6))},
            "shard_b": {"indexes": list(range(101, 201)), "pages": list(range(6, 11))},
        },
        "hard_gates": {
            "identity": "adult Morning Star Alicia, no ordinary-form leakage",
            "hair_accessory": "exactly one small gold five-point star when hair area is visible",
            "hosiery": "visible legs and feet have plain continuous very sheer ivory pantyhose with warm skin visible",
            "caption": "visible content only; exact hosiery phrase once when legs are clearly visible",
            "quality": "solo, normal anatomy, opaque main clothing, no text or watermark",
        },
        "records": records,
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    print(json.dumps({"records": len(records), "sheets": len(sheets)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
