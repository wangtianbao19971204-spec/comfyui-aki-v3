from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CAMPAIGN = Path(
    r"G:\ComfyUI-aki-v3\character_lora_forge\characters\alicia_bell\runs\20260818_20x200_campaign"
)
INPUT_MANIFEST = CAMPAIGN / "final_selection_staging" / "input_manifest.json"
FINAL_MANIFEST = CAMPAIGN / "final_training_200" / "final_manifest.json"
OUTPUT_ROOT = CAMPAIGN / "split_lora_selection"


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/msyh.ttc")):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def build_sheet(form: str, round_id: str, records: list[dict], core_hashes: set[str]) -> Path:
    columns = 5
    thumb = 300
    label_height = 58
    title_height = 64
    rows = 5
    canvas = Image.new(
        "RGB",
        (columns * thumb, title_height + rows * (thumb + label_height)),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (16, 14),
        f"Alicia split selection | {form} | {round_id} | choose 5 additional",
        fill="black",
        font=load_font(27),
    )
    label_font = load_font(17)
    for index, record in enumerate(records):
        row, column = divmod(index, columns)
        source_path = Path(record["source_path"])
        with Image.open(source_path) as source:
            image = source.convert("RGB")
            image.thumbnail((thumb - 8, thumb - 8), Image.Resampling.LANCZOS)
            x = column * thumb + (thumb - image.width) // 2
            y = title_height + row * (thumb + label_height) + (thumb - image.height) // 2
            canvas.paste(image, (x, y))
        is_core = record["sha256"] in core_hashes
        border = "#17823b" if is_core else "#b8b8b8"
        draw.rectangle(
            (
                column * thumb + 2,
                title_height + row * (thumb + label_height) + 2,
                (column + 1) * thumb - 3,
                title_height + row * (thumb + label_height) + thumb - 3,
            ),
            outline=border,
            width=5 if is_core else 2,
        )
        marker = "CORE " if is_core else ""
        label = f"{marker}{record['contact_label']}\n{record['source_name'][:38]}"
        draw.multiline_text(
            (column * thumb + 7, title_height + row * (thumb + label_height) + thumb + 5),
            label,
            fill="black",
            font=label_font,
            spacing=2,
        )
    destination = OUTPUT_ROOT / "contact_sheets" / form / f"{round_id}_{form}_25.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=94)
    return destination


def main() -> int:
    input_manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    final_manifest = json.loads(FINAL_MANIFEST.read_text(encoding="utf-8"))
    core_hashes = {record["sha256"] for record in final_manifest["records"]}
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in input_manifest["records"]:
        grouped[(record["form"], record["round_id"])].append(record)

    sheets = []
    for (form, round_id), records in sorted(grouped.items()):
        records.sort(key=lambda item: (item["batch_ordinal"], item["source_name"]))
        if len(records) != 25:
            raise RuntimeError(f"Expected 25 records for {form}/{round_id}, found {len(records)}")
        sheets.append(str(build_sheet(form, round_id, records, core_hashes)))

    review_manifest = {
        "schema_version": 1,
        "status": "split_selection_review_ready",
        "input_manifest_path": str(INPUT_MANIFEST.resolve()),
        "input_manifest_sha256": sha256_file(INPUT_MANIFEST),
        "existing_core_manifest_path": str(FINAL_MANIFEST.resolve()),
        "existing_core_manifest_sha256": sha256_file(FINAL_MANIFEST),
        "selection_rule": "retain 100 audited core records per form and select 5 additional records per round from the frozen 25-record pool",
        "triggers": {
            "ordinary": "alcbo7yo260822",
            "morning_star": "alcbm7yo260822",
        },
        "hosiery_policy": {
            "ordinary": "No sheer hosiery identity cue. Caption only what is visibly worn.",
            "morning_star": "When legs are visible, require sheer ivory pantyhose covering both legs and feet, with warm skin tone visible through the fabric; reject bare legs, opaque white leggings, dense stripes, and detached sock-like legwear.",
        },
        "contact_sheets": sheets,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT_ROOT / "review_manifest.json"
    destination.write_text(json.dumps(review_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)
    print(f"contact_sheets={len(sheets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
