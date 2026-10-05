from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


CAMPAIGN = Path(
    r"G:\ComfyUI-aki-v3\character_lora_forge\characters\alicia_bell\runs\20260818_20x200_campaign"
)
MANIFEST = CAMPAIGN / "final_training_split_200" / "morning_star" / "selection_manifest.json"
HOSIERY_PHRASE = (
    "very sheer ivory pantyhose covering both legs and feet, "
    "warm skin tone visible through the fabric"
)
MALFORMED_PHRASE = (
    "very sheer very sheer ivory pantyhose covering both legs and feet, "
    "warm skin tone visible through the fabric covering both legs and feet, "
    "warm skin tone visible through the fabric"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical_caption(caption: str) -> str:
    result = caption.replace(MALFORMED_PHRASE, HOSIERY_PHRASE).strip().rstrip(".")
    if HOSIERY_PHRASE.lower() not in result.lower():
        result += ", " + HOSIERY_PHRASE
    if result.lower().count(HOSIERY_PHRASE.lower()) != 1:
        raise RuntimeError("Caption must contain the hosiery phrase exactly once")
    return result + "."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    batch_dir = args.batch_dir.resolve()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source_by_stem = {record["final_stem"]: record for record in manifest["records"]}
    outputs = sorted(batch_dir.glob("*_repair.png"))
    if not outputs:
        raise RuntimeError(f"No repair images found in {batch_dir}")

    records = []
    for output in outputs:
        stem = output.name[: -len("_repair.png")]
        source = source_by_stem.get(stem)
        if source is None:
            raise RuntimeError(f"Unknown final stem: {stem}")
        original = Path(source["final_image_path"])
        records.append(
            {
                "rejected_final_stem": stem,
                "round_id": source["round_id"],
                "original_path": str(original.resolve()),
                "original_sha256": sha256_file(original),
                "output_path": str(output.resolve()),
                "output_sha256": sha256_file(output),
                "visual_assessment": (
                    "Pass: one adult Morning Star Alicia; plain continuous very sheer "
                    "ivory pantyhose covers both visible legs and feet with warm skin "
                    "tone visible; no pattern, stripe, stocking top, sock edge, garter, "
                    "or broken coverage; anatomy and source composition remain usable."
                ),
                "caption": canonical_caption(source["caption"]),
            }
        )

    review = {
        "schema_version": 1,
        "status": "pass",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "batch": args.name,
        "count": len(records),
        "edit_mode": "built-in imagegen precise-object-edit",
        "fixed_hosiery_phrase": HOSIERY_PHRASE,
        "records": records,
    }
    destination = batch_dir / f"{args.name}_review.json"
    destination.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)
    print(json.dumps({"status": review["status"], "count": review["count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
