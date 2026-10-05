from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/msyh.ttc")):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def build_pages(manifest_path: Path, form_filter: str | None = None) -> list[Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest["records"]
    if form_filter:
        records = [record for record in records if record.get("form") == form_filter]
    form = form_filter or manifest["form"]
    output_dir = manifest_path.parent / "audit_contact_sheets"
    output_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    columns = 5
    rows = 4
    thumb = 300
    label_height = 62
    title_height = 64
    page_size = columns * rows
    total_pages = (len(records) + page_size - 1) // page_size
    for page_index, start in enumerate(range(0, len(records), page_size), 1):
        page_records = records[start : start + page_size]
        canvas = Image.new(
            "RGB",
            (columns * thumb, title_height + rows * (thumb + label_height)),
            "white",
        )
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (16, 14),
            f"Alicia {form} dataset audit | page {page_index:02d}/{total_pages:02d}",
            fill="black",
            font=load_font(27),
        )
        label_font = load_font(16)
        for index, record in enumerate(page_records):
            row, column = divmod(index, columns)
            image_path = Path(record["final_image_path"])
            with Image.open(image_path) as source:
                image = source.convert("RGB")
                image.thumbnail((thumb - 8, thumb - 8), Image.Resampling.LANCZOS)
                x = column * thumb + (thumb - image.width) // 2
                y = title_height + row * (thumb + label_height) + (thumb - image.height) // 2
                canvas.paste(image, (x, y))
            label = f"{record['final_stem']}\n{record.get('source_kind', 'source')}"
            draw.multiline_text(
                (column * thumb + 7, title_height + row * (thumb + label_height) + thumb + 5),
                label,
                fill="black",
                font=label_font,
                spacing=2,
            )
        destination = output_dir / f"{form}_audit_{page_index:02d}.jpg"
        canvas.save(destination, quality=94)
        pages.append(destination)
    index_path = output_dir / "audit_sheet_manifest.json"
    index_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "form": form,
                "selection_manifest": str(manifest_path.resolve()),
                "record_count": len(records),
                "pages": [str(path.resolve()) for path in pages],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--form")
    args = parser.parse_args()
    pages = build_pages(args.manifest.resolve(), args.form)
    print(f"pages={len(pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
