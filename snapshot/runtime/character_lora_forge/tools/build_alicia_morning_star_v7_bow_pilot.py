from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


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
SOURCE = CAMPAIGN / "morning_star_v6_correction"
OUTPUT = CAMPAIGN / "morning_star_v7_bow_pilot"
DATASET = OUTPUT / "dataset"
SHEETS = OUTPUT / "audit_contact_sheets"
BOW_PATTERN = re.compile(r"collar knot|collar bow|fabric bow|bow tie", re.IGNORECASE)
REAR_PATTERN = re.compile(r"rear|looking back", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def add_bow_tag(caption: str) -> str:
    marker = "champagne eyes,"
    if marker not in caption:
        raise ValueError(f"Caption has no stable insertion marker: {caption}")
    return caption.replace(marker, f"{marker} small wine-red bow tie at throat,", 1)


def font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def build_sheets(records: list[dict]) -> list[str]:
    SHEETS.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    thumb_w, thumb_h, label_h = 300, 340, 48
    cols, rows = 4, 4
    page_size = cols * rows
    for page_index, start in enumerate(range(0, len(records), page_size), start=1):
        page_records = records[start : start + page_size]
        canvas = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h) + 44), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 8), f"Morning Star v7 bow pilot | page {page_index}", fill="black", font=font(18))
        for index, record in enumerate(page_records):
            row, col = divmod(index, cols)
            x, y = col * thumb_w, 44 + row * (thumb_h + label_h)
            image = Image.open(record["output_image_path"]).convert("RGB")
            image.thumbnail((thumb_w - 8, thumb_h - 8), Image.Resampling.LANCZOS)
            canvas.paste(image, (x + (thumb_w - image.width) // 2, y + (thumb_h - image.height) // 2))
            draw.text((x + 5, y + thumb_h + 4), record["final_stem"], fill="black", font=font(12))
        path = SHEETS / f"morning_star_v7_bow_pilot_{page_index:02d}.jpg"
        canvas.save(path, quality=92)
        paths.append(str(path.resolve()))
    return paths


def main() -> int:
    manifest = json.loads((SOURCE / "selection_manifest.json").read_text(encoding="utf-8"))
    DATASET.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for record in manifest["records"]:
        source_image = Path(record["source_image_path"])
        original_caption_path = source_image.with_suffix(".txt")
        original_caption = original_caption_path.read_text(encoding="utf-8").strip()
        if not BOW_PATTERN.search(original_caption) or REAR_PATTERN.search(original_caption):
            continue
        output_image = DATASET / f"{record['final_stem']}.png"
        output_caption = DATASET / f"{record['final_stem']}.txt"
        shutil.copy2(record["output_image_path"], output_image)
        caption = add_bow_tag(record["caption"])
        output_caption.write_text(caption + "\n", encoding="utf-8")
        records.append(
            {
                "final_stem": record["final_stem"],
                "round_id": record["round_id"],
                "correction_category": record["correction_category"],
                "source_image_path": record["output_image_path"],
                "source_original_caption": original_caption,
                "output_image_path": str(output_image.resolve()),
                "output_caption_path": str(output_caption.resolve()),
                "sha256": sha256_file(output_image),
                "caption": caption,
            }
        )
    if len(records) != 44:
        raise RuntimeError(f"Expected 44 high-confidence bow records, found {len(records)}")
    if any("small wine-red bow tie at throat" not in item["caption"] for item in records):
        raise RuntimeError("Every pilot caption must contain the explicit bow tag")
    sheet_paths = build_sheets(records)
    output_manifest = {
        "schema_version": 1,
        "purpose": "High-confidence explicit bow-tie continuation pilot",
        "source_manifest": str((SOURCE / "selection_manifest.json").resolve()),
        "selection_rule": "Original v5 caption names a collar bow/knot and is not a rear view",
        "pair_count": len(records),
        "unique_images": len({item["sha256"] for item in records}),
        "explicit_bow_caption_count": sum(
            "small wine-red bow tie at throat" in item["caption"] for item in records
        ),
        "audit_contact_sheets": sheet_paths,
        "records": records,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "selection_manifest.json").write_text(
        json.dumps(output_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: output_manifest[key] for key in ("pair_count", "unique_images", "explicit_bow_caption_count")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
