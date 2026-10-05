from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def font(size: int) -> ImageFont.ImageFont:
    for candidate in (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/msyh.ttc")):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = sorted(manifest["records"], key=lambda item: (item["prompt_id"], item["lora_strength"], item["checkpoint_step"]))
    columns, thumb, label_height, title_height = 4, 360, 58, 64
    rows = (len(records) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * thumb, title_height + rows * (thumb + label_height)), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 15), f"Alicia {manifest['form']} | {manifest['phase']}", fill="black", font=font(28))
    label_font = font(17)
    for index, record in enumerate(records):
        row, column = divmod(index, columns)
        with Image.open(record["output_path"]) as source:
            image = source.convert("RGB")
            image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
        x = column * thumb + (thumb - image.width) // 2
        y = title_height + row * (thumb + label_height) + (thumb - image.height) // 2
        canvas.paste(image, (x, y))
        label = f"step {record['checkpoint_step']} | {record['prompt_id']} | s {record['lora_strength']:.1f}"
        draw.text((column * thumb + 8, title_height + row * (thumb + label_height) + thumb + 9), label, fill="black", font=label_font)
    destination = args.manifest.parent / "contact_sheet.jpg"
    canvas.save(destination, quality=94)
    print(destination.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
