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


GROUPS = {
    "all": None,
    "anchors": {"ordinary_anchor", "morning_star_anchor"},
    "wardrobe": {
        "ordinary_modern_casual",
        "ordinary_formal",
        "morning_star_adventure",
        "morning_star_fantasy_role",
    },
    "accessories": {"accessory_absent", "accessory_replaced"},
    "styles": {"style_watercolor", "style_3d", "style_graphic_novel"},
    "strengths": {"ordinary_anchor", "morning_star_anchor"},
}


def build_sheet(manifest_path: Path, group: str) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest["records"]
    prompt_ids = GROUPS[group]
    if prompt_ids is not None:
        records = [record for record in records if record["prompt_id"] in prompt_ids]
    if group == "anchors":
        records = [record for record in records if record["lora_strength"] == 0.8]
    if group not in ("all", "strengths"):
        records = [record for record in records if record["lora_strength"] == 0.8]
    records = sorted(
        records,
        key=lambda item: (item["prompt_id"], item["lora_strength"], item["checkpoint_step"]),
    )
    columns = 4
    thumb = 360
    label_height = 52
    title_height = 64
    rows = (len(records) + columns - 1) // columns
    canvas = Image.new(
        "RGB",
        (columns * thumb, title_height + rows * (thumb + label_height)),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (18, 15),
        f"Alicia Bell LoRA - {manifest['phase']} - {group}",
        fill="black",
        font=load_font(28),
    )
    label_font = load_font(18)
    for index, record in enumerate(records):
        row, column = divmod(index, columns)
        path = Path(record["output_path"])
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
            x = column * thumb + (thumb - image.width) // 2
            y = title_height + row * (thumb + label_height) + (thumb - image.height) // 2
            canvas.paste(image, (x, y))
        label = (
            f"step {record['checkpoint_step']} | {record['prompt_id']} | "
            f"strength {record['lora_strength']:.1f}"
        )
        draw.text(
            (column * thumb + 10, title_height + row * (thumb + label_height) + thumb + 10),
            label,
            fill="black",
            font=label_font,
        )
    suffix = "" if group == "all" else f"_{group}"
    destination = manifest_path.parent / f"contact_sheet{suffix}.jpg"
    canvas.save(destination, quality=94)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--group", choices=tuple(GROUPS), default="all")
    args = parser.parse_args()
    print(build_sheet(args.manifest.resolve(), args.group))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
