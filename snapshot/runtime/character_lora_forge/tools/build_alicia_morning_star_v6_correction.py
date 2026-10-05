from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CAMPAIGN = Path(
    r"G:\ComfyUI-aki-v3\character_lora_forge\characters\alicia_bell\runs\20260818_20x200_campaign"
)
SOURCE_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star_v5"
SOURCE_MANIFEST = SOURCE_ROOT / "selection_manifest.json"
OUTPUT_ROOT = CAMPAIGN / "final_training_split_200" / "morning_star_v6_correction"
DATASET = OUTPUT_ROOT / "dataset"
SHEETS = OUTPUT_ROOT / "audit_contact_sheets"
TRIGGER = "alcbm7yo260822"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def has(record: dict, pattern: str) -> bool:
    import re

    return re.search(pattern, record["caption"], flags=re.IGNORECASE) is not None


def choose(records: list[dict], selected: set[str], count: int) -> list[dict]:
    result = []
    round_use: Counter[str] = Counter()
    remaining = [item for item in records if item["final_stem"] not in selected]
    while remaining and len(result) < count:
        remaining.sort(
            key=lambda item: (
                round_use[item["round_id"]],
                item["round_id"],
                item["final_stem"],
            )
        )
        item = remaining.pop(0)
        result.append(item)
        selected.add(item["final_stem"])
        round_use[item["round_id"]] += 1
    if len(result) != count:
        raise RuntimeError(f"Needed {count} records, found {len(result)}")
    return result


def view_tag(caption: str) -> str:
    lower = caption.lower()
    tags = (
        "rear full-body view",
        "front full-body view",
        "three-quarter full-body view",
        "side full-body view",
        "seated full-body view",
        "full-body view",
        "full body",
        "kneeling pose",
        "seated pose",
        "rear three-quarter view",
        "three-quarter view",
        "side-profile upper-body view",
        "upper-body portrait",
        "head-and-torso portrait",
        "head-and-shoulders portrait",
        "identity close-up",
        "close-up",
        "portrait",
    )
    for tag in tags:
        if tag in lower:
            return tag
    return "character reference view"


def scene_tag(caption: str) -> str | None:
    lower = caption.lower()
    scenes = (
        "plain studio background",
        "plain neutral background",
        "stage background",
        "garden background",
        "park background",
        "cafe interior",
        "office interior",
        "corridor background",
        "doorway background",
        "night-city background",
        "autumn background",
    )
    for tag in scenes:
        keyword = tag.split()[0]
        if keyword in lower:
            return tag
    return None


def compact_caption(record: dict, category: str) -> str:
    parts = [
        TRIGGER,
        "adult Alicia Bell, Morning Star",
        "peach rose-gold twin tails",
        "wine-red ribbons",
        "gold five-point star clip",
        "champagne eyes",
    ]
    visible_outfit = has(
        record,
        r"dress|idol outfit|ivory top|upper dress|bodice|bell skirt|pantyhose",
    )
    if visible_outfit:
        parts.extend(
            [
                "ivory top and shoulder gauze",
                "wine-red corset",
            ]
        )
    if category == "full_hosiery_skirt" or has(record, r"ivory bell skirt"):
        parts.extend(["ivory bell skirt", "narrow wine-red hem"])
    if category in {"full_hosiery_skirt", "hosiery_correction"} or has(
        record, r"pantyhose"
    ):
        parts.append("ultra-sheer nude-ivory pantyhose, warm skin visible")
        parts.append("wine-red heels")
    parts.append(view_tag(record["caption"]))
    scene = scene_tag(record["caption"])
    if scene and scene != "plain studio background":
        parts.append(scene)
    return ", ".join(parts) + "."


def build_contact_sheets(records: list[dict]) -> list[str]:
    SHEETS.mkdir(parents=True, exist_ok=True)
    page_paths = []
    thumb_w, thumb_h, label_h = 300, 340, 52
    cols, rows = 4, 4
    font = ImageFont.load_default()
    for page_index in range(0, len(records), cols * rows):
        page = records[page_index : page_index + cols * rows]
        canvas = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h) + 34), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 8), f"Morning Star v6 correction audit | page {page_index // 16 + 1}", fill="black", font=font)
        for index, record in enumerate(page):
            row, col = divmod(index, cols)
            x, y = col * thumb_w, 34 + row * (thumb_h + label_h)
            with Image.open(record["output_image_path"]) as source:
                source = source.convert("RGB")
                source.thumbnail((thumb_w - 8, thumb_h - 8), Image.Resampling.LANCZOS)
                px = x + (thumb_w - source.width) // 2
                py = y + (thumb_h - source.height) // 2
                canvas.paste(source, (px, py))
            label = f"{record['final_stem']}\n{record['correction_category']}"
            draw.multiline_text((x + 4, y + thumb_h + 2), label, fill="black", font=font, spacing=2)
        path = SHEETS / f"morning_star_v6_correction_{page_index // 16 + 1:02d}.jpg"
        canvas.save(path, quality=90)
        page_paths.append(str(path.resolve()))
    return page_paths


def main() -> int:
    if OUTPUT_ROOT.exists() and any(OUTPUT_ROOT.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty output: {OUTPUT_ROOT}")
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    records = manifest["records"]
    if len(records) != 200:
        raise RuntimeError("Expected the audited 200-image v5 dataset")

    selected: set[str] = set()
    groups: list[tuple[str, list[dict]]] = []

    full_hosiery_skirt = sorted(
        [
            item
            for item in records
            if has(item, r"pantyhose")
            and has(item, r"ivory bell skirt")
            and has(item, r"full.body|head.to.toe")
        ],
        key=lambda item: (item["round_id"], item["final_stem"]),
    )
    if len(full_hosiery_skirt) != 40:
        raise RuntimeError(f"Expected 40 full hosiery/skirt anchors, found {len(full_hosiery_skirt)}")
    selected.update(item["final_stem"] for item in full_hosiery_skirt)
    groups.append(("full_hosiery_skirt", full_hosiery_skirt))

    hosiery_candidates = [
        item
        for item in records
        if "repair" in item["source_kind"] and has(item, r"pantyhose")
    ]
    groups.append(("hosiery_correction", choose(hosiery_candidates, selected, 12)))

    star_candidates = [
        item
        for item in records
        if has(item, r"five.point")
        and has(item, r"portrait|close.up|head.and.torso|upper.body")
    ]
    star_candidates.sort(
        key=lambda item: (
            0 if item["source_kind"] == "identity_contract_repair" else 1,
            item["round_id"],
            item["final_stem"],
        )
    )
    star_group = []
    for item in star_candidates:
        if item["final_stem"] in selected:
            continue
        star_group.append(item)
        selected.add(item["final_stem"])
        if len(star_group) == 12:
            break
    if len(star_group) != 12:
        raise RuntimeError("Could not select 12 star identity anchors")
    groups.append(("star_identity", star_group))

    scene_anchor_stems = {
        f"{TRIGGER}_morning_star_R02_07",
        f"{TRIGGER}_morning_star_R07_05",
        f"{TRIGGER}_morning_star_R09_05",
        f"{TRIGGER}_morning_star_R10_05",
        f"{TRIGGER}_morning_star_R19_09",
        f"{TRIGGER}_morning_star_R19_10",
        f"{TRIGGER}_morning_star_R20_07",
        f"{TRIGGER}_morning_star_R20_10",
    }
    scene_candidates = [
        item for item in records if item["final_stem"] in scene_anchor_stems
    ]
    if len(scene_candidates) != 8 or scene_anchor_stems.intersection(selected):
        raise RuntimeError("Scene anchor whitelist is incomplete or overlaps another category")
    selected.update(scene_anchor_stems)
    groups.append(("scene_anchor", sorted(scene_candidates, key=lambda item: item["final_stem"])))

    DATASET.mkdir(parents=True)
    output_records = []
    for category, items in groups:
        for source_record in items:
            source = Path(source_record["final_image_path"])
            target = DATASET / f"{source_record['final_stem']}.png"
            caption_path = DATASET / f"{source_record['final_stem']}.txt"
            shutil.copy2(source, target)
            caption = compact_caption(source_record, category)
            caption_path.write_text(caption + "\n", encoding="utf-8")
            output_records.append(
                {
                    "final_stem": source_record["final_stem"],
                    "round_id": source_record["round_id"],
                    "correction_category": category,
                    "source_kind": source_record["source_kind"],
                    "source_image_path": str(source.resolve()),
                    "source_sha256": source_record["sha256"].upper(),
                    "output_image_path": str(target.resolve()),
                    "output_caption_path": str(caption_path.resolve()),
                    "output_sha256": sha256_file(target),
                    "caption": caption,
                    "caption_length": len(caption),
                }
            )

    if len(output_records) != 72 or len({item["output_sha256"] for item in output_records}) != 72:
        raise RuntimeError("Correction set must contain 72 unique paired images")
    if any(not item["caption"].startswith(f"{TRIGGER},") for item in output_records):
        raise RuntimeError("Every caption must begin with the trigger")
    page_paths = build_contact_sheets(output_records)
    category_counts = Counter(item["correction_category"] for item in output_records)
    round_counts = Counter(item["round_id"] for item in output_records)
    lengths = [item["caption_length"] for item in output_records]
    output_manifest = {
        "schema_version": 1,
        "status": "assembled_pending_visual_audit",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "form": "morning_star",
        "trigger_token": TRIGGER,
        "purpose": "targeted continuation dataset for skirt, hosiery, and five-point star reinforcement",
        "source_manifest": str(SOURCE_MANIFEST.resolve()),
        "dataset_path": str(DATASET.resolve()),
        "counts": {
            "images": 72,
            "captions": 72,
            "unique_sha256": 72,
            "categories": dict(category_counts),
            "rounds": dict(sorted(round_counts.items())),
            "caption_length": {
                "min": min(lengths),
                "max": max(lengths),
                "average": round(sum(lengths) / len(lengths), 2),
            },
        },
        "audit_contact_sheets": page_paths,
        "records": output_records,
    }
    destination = OUTPUT_ROOT / "selection_manifest.json"
    destination.write_text(
        json.dumps(output_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(destination)
    print(json.dumps(output_manifest["counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
