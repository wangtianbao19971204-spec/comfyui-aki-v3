from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(r"G:\ComfyUI-aki-v3")
CAMPAIGN = (
    ROOT
    / "character_lora_forge"
    / "characters"
    / "alicia_bell"
    / "runs"
    / "20260818_20x200_campaign"
    / "final_training_split_200"
)
SOURCE = CAMPAIGN / "morning_star_v7_bow_pilot"
OUTPUT = CAMPAIGN / "morning_star_v8_bow_bundle_pilot"
DATASET = OUTPUT / "dataset"
EXPLICIT_TAG = " small wine-red bow tie at throat,"


def main() -> int:
    manifest = json.loads((SOURCE / "selection_manifest.json").read_text(encoding="utf-8"))
    DATASET.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for record in manifest["records"]:
        image_source = Path(record["output_image_path"])
        image_output = DATASET / image_source.name
        caption_output = DATASET / f"{record['final_stem']}.txt"
        caption = record["caption"].replace(EXPLICIT_TAG, " ")
        if "bow tie" in caption.lower() or "collar knot" in caption.lower():
            raise RuntimeError(f"Explicit bow term survived in {record['final_stem']}")
        shutil.copy2(image_source, image_output)
        caption_output.write_text(caption.strip() + "\n", encoding="utf-8")
        records.append(
            {
                "final_stem": record["final_stem"],
                "image_path": str(image_output.resolve()),
                "caption_path": str(caption_output.resolve()),
                "caption": caption.strip(),
            }
        )
    if len(records) != 44:
        raise RuntimeError(f"Expected 44 bundle-learning records, found {len(records)}")
    result = {
        "schema_version": 1,
        "purpose": "Bundle a consistently visible bow into the character trigger",
        "source_manifest": str((SOURCE / "selection_manifest.json").resolve()),
        "pair_count": len(records),
        "explicit_bow_caption_count": 0,
        "records": records,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "selection_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"pair_count": len(records), "explicit_bow_caption_count": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
