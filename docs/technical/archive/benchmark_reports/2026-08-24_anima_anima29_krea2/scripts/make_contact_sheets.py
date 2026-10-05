from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
RESULTS = ROOT / "raw" / "results.jsonl"
OUTPUT = ROOT / "contact_sheets"
MODEL_ORDER = ["anima_original", "anima_29b", "krea2"]
MODEL_LABELS = {
    "anima_original": "Anima original",
    "anima_29b": "Anima 2.9B preview v1 BF16",
    "krea2": "Krea2 Turbo",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def load_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if record.get("success"):
                records.append(record)
    return records


def first_image(record: dict[str, Any]) -> Path:
    metrics = record.get("image_metrics") or []
    if metrics:
        return Path(metrics[0]["path"])
    return Path(record["output_paths"][0])


def make_triptych(case_id: str, records: list[dict[str, Any]]) -> Path | None:
    by_model = {record["model"]: record for record in records}
    if not all(model in by_model for model in MODEL_ORDER):
        return None
    source_images = [Image.open(first_image(by_model[model])).convert("RGB") for model in MODEL_ORDER]
    landscape = sum(image.width > image.height for image in source_images) >= 2
    cell_width = 620 if landscape else 500
    cell_height = 430 if landscape else 700
    margin = 24
    header = 92
    footer = 84
    canvas = Image.new(
        "RGB",
        (margin * 2 + cell_width * 3, header + cell_height + footer + margin),
        "#15171a",
    )
    draw = ImageDraw.Draw(canvas)
    title_font = font(30, bold=True)
    label_font = font(22, bold=True)
    meta_font = font(17)
    phase = by_model[MODEL_ORDER[0]]["phase"]
    category = by_model[MODEL_ORDER[0]]["category"]
    draw.text((margin, 16), f"{phase.upper()} / {case_id}", fill="#f5f6f7", font=title_font)
    draw.text((margin, 54), category, fill="#aeb6bf", font=meta_font)
    for index, model in enumerate(MODEL_ORDER):
        record = by_model[model]
        image = source_images[index]
        fitted = ImageOps.contain(image, (cell_width - 18, cell_height - 18), Image.Resampling.LANCZOS)
        x0 = margin + index * cell_width
        image_x = x0 + (cell_width - fitted.width) // 2
        image_y = header + (cell_height - fitted.height) // 2
        canvas.paste(fitted, (image_x, image_y))
        draw.rectangle(
            [x0 + 6, header + 6, x0 + cell_width - 7, header + cell_height - 7],
            outline="#4f5964",
            width=2,
        )
        meta = record.get("telemetry_summary") or {}
        line1 = MODEL_LABELS[model]
        line2 = (
            f"{record.get('wall_time_s')}s | {meta.get('gpu_memory_mb_max')} MB | "
            f"{record.get('steps')} steps"
        )
        draw.text((x0 + 12, header + cell_height + 10), line1, fill="#ffffff", font=label_font)
        draw.text((x0 + 12, header + cell_height + 43), line2, fill="#b9c2cc", font=meta_font)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"{phase}_{case_id}.jpg"
    canvas.save(path, quality=92, subsampling=0)
    for image in source_images:
        image.close()
    return path


def make_phase_overview(phase: str, grouped: dict[str, list[dict[str, Any]]]) -> Path | None:
    case_ids = sorted(case_id for case_id, rows in grouped.items() if rows[0]["phase"] == phase)
    if not case_ids:
        return None
    thumb_width = 300
    thumb_height = 260
    label_height = 48
    margin = 20
    header = 76
    canvas = Image.new(
        "RGB",
        (
            margin * 2 + thumb_width * 3,
            header + len(case_ids) * (thumb_height + label_height) + margin,
        ),
        "#111315",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 16), f"{phase.upper()} OVERVIEW", fill="white", font=font(30, True))
    for col, model in enumerate(MODEL_ORDER):
        draw.text(
            (margin + col * thumb_width + 8, 52),
            MODEL_LABELS[model],
            fill="#bfc7cf",
            font=font(16, True),
        )
    for row, case_id in enumerate(case_ids):
        by_model = {record["model"]: record for record in grouped[case_id]}
        y0 = header + row * (thumb_height + label_height)
        for col, model in enumerate(MODEL_ORDER):
            if model not in by_model:
                continue
            with Image.open(first_image(by_model[model])) as source:
                fitted = ImageOps.contain(
                    source.convert("RGB"),
                    (thumb_width - 12, thumb_height - 12),
                    Image.Resampling.LANCZOS,
                )
            x0 = margin + col * thumb_width
            canvas.paste(
                fitted,
                (x0 + (thumb_width - fitted.width) // 2, y0 + (thumb_height - fitted.height) // 2),
            )
        draw.text(
            (margin + 8, y0 + thumb_height + 8),
            case_id,
            fill="#f1f2f3",
            font=font(17, True),
        )
        draw.line(
            (margin, y0 + thumb_height + label_height - 2, canvas.width - margin, y0 + thumb_height + label_height - 2),
            fill="#34393f",
            width=1,
        )
    path = OUTPUT / f"overview_{phase}.jpg"
    canvas.save(path, quality=90, subsampling=1)
    return path


def make_length_boundary_series(records: list[dict[str, Any]]) -> Path | None:
    rows = sorted(
        (record for record in records if record["phase"] == "length_boundary"),
        key=lambda record: record.get("qwen35_token_count", 0),
    )
    if not rows:
        return None
    columns = 4
    cell_width = 360
    cell_height = 526
    label_height = 78
    margin = 24
    header = 90
    row_count = (len(rows) + columns - 1) // columns
    canvas = Image.new(
        "RGB",
        (
            margin * 2 + columns * cell_width,
            header + row_count * (cell_height + label_height) + margin,
        ),
        "#111315",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 14), "ANIMA 3.8B QWEN3.5 CONTEXT BOUNDARY", fill="white", font=font(30, True))
    draw.text(
        (margin, 54),
        "Same seed, 832x1216, 40 steps; all models unloaded between runs",
        fill="#bfc7cf",
        font=font(17),
    )
    for index, record in enumerate(rows):
        col = index % columns
        row = index // columns
        x0 = margin + col * cell_width
        y0 = header + row * (cell_height + label_height)
        with Image.open(first_image(record)) as source:
            fitted = ImageOps.contain(
                source.convert("RGB"),
                (cell_width - 16, cell_height - 16),
                Image.Resampling.LANCZOS,
            )
        canvas.paste(
            fitted,
            (x0 + (cell_width - fitted.width) // 2, y0 + (cell_height - fitted.height) // 2),
        )
        metrics = record["image_metrics"][0]
        token_count = record.get("qwen35_token_count", "?")
        draw.text((x0 + 8, y0 + cell_height + 8), f"{token_count} tokens", fill="white", font=font(20, True))
        draw.text(
            (x0 + 8, y0 + cell_height + 39),
            f"Laplacian {metrics['laplacian_variance']:.1f} | color {metrics['colorfulness']:.1f}",
            fill="#bfc7cf",
            font=font(15),
        )
    path = OUTPUT / "length_boundary_anima38_series.jpg"
    canvas.save(path, quality=92, subsampling=0)
    return path


def make_length_boundary_control_series(records: list[dict[str, Any]]) -> Path | None:
    rows = sorted(
        (record for record in records if record["phase"] == "length_boundary_control"),
        key=lambda record: (record["qwen35_token_count"], record.get("boundary_control", "")),
    )
    if not rows:
        return None
    columns = 5
    cell_width = 330
    cell_height = 482
    label_height = 86
    margin = 24
    header = 92
    canvas = Image.new(
        "RGB",
        (margin * 2 + columns * cell_width, header + cell_height + label_height + margin),
        "#111315",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 14), "ANIMA 3.8B COMPLETE-SENTENCE CONTROLS", fill="white", font=font(30, True))
    draw.text(
        (margin, 54),
        "Same 448-token normal base; complete neutral suffixes; alternate wording at 479",
        fill="#bfc7cf",
        font=font(17),
    )
    for index, record in enumerate(rows):
        x0 = margin + index * cell_width
        with Image.open(first_image(record)) as source:
            fitted = ImageOps.contain(
                source.convert("RGB"),
                (cell_width - 14, cell_height - 14),
                Image.Resampling.LANCZOS,
            )
        canvas.paste(fitted, (x0 + (cell_width - fitted.width) // 2, header + (cell_height - fitted.height) // 2))
        metrics = record["image_metrics"][0]
        draw.text(
            (x0 + 7, header + cell_height + 8),
            f"{record['qwen35_token_count']} tokens",
            fill="white",
            font=font(19, True),
        )
        draw.text(
            (x0 + 7, header + cell_height + 37),
            record.get("boundary_control", ""),
            fill="#bfc7cf",
            font=font(14),
        )
        draw.text(
            (x0 + 7, header + cell_height + 60),
            f"Laplacian {metrics['laplacian_variance']:.1f} | color {metrics['colorfulness']:.1f}",
            fill="#bfc7cf",
            font=font(13),
        )
    path = OUTPUT / "length_boundary_anima38_controls.jpg"
    canvas.save(path, quality=92, subsampling=0)
    return path


def make_speed_series(records: list[dict[str, Any]]) -> Path | None:
    rows = [
        record
        for record in records
        if record["phase"] == "speed" and record["negative_mode"] == "common"
    ]
    if not rows:
        return None
    base_seed = min(record["seed"] for record in rows)
    rows = [record for record in rows if record["seed"] == base_seed]
    columns = max(sum(record["model"] == model for record in rows) for model in MODEL_ORDER)
    cell_width = 360
    cell_height = 360
    label_height = 74
    left_label = 210
    margin = 24
    header = 90
    canvas = Image.new(
        "RGB",
        (
            left_label + columns * cell_width + margin,
            header + len(MODEL_ORDER) * (cell_height + label_height) + margin,
        ),
        "#111315",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 14), "STEP / QUALITY AND TIME", fill="white", font=font(30, True))
    draw.text(
        (margin, 54),
        f"Same prompt and seed {base_seed}; cold model unload before and after every run",
        fill="#bfc7cf",
        font=font(17),
    )
    for row_index, model in enumerate(MODEL_ORDER):
        model_rows = sorted(
            (record for record in rows if record["model"] == model),
            key=lambda record: record["steps"],
        )
        y0 = header + row_index * (cell_height + label_height)
        draw.multiline_text(
            (margin, y0 + 18),
            MODEL_LABELS[model].replace(" ", "\n", 1),
            fill="white",
            font=font(20, True),
            spacing=6,
        )
        for col, record in enumerate(model_rows):
            x0 = left_label + col * cell_width
            with Image.open(first_image(record)) as source:
                fitted = ImageOps.contain(
                    source.convert("RGB"),
                    (cell_width - 16, cell_height - 16),
                    Image.Resampling.LANCZOS,
                )
            canvas.paste(
                fitted,
                (x0 + (cell_width - fitted.width) // 2, y0 + (cell_height - fitted.height) // 2),
            )
            draw.text(
                (x0 + 8, y0 + cell_height + 8),
                f"{record['steps']} steps | {record['wall_time_s']:.2f}s",
                fill="white",
                font=font(19, True),
            )
            draw.text(
                (x0 + 8, y0 + cell_height + 38),
                f"peak {record['telemetry_summary']['gpu_memory_mb_max']:.0f} MB",
                fill="#bfc7cf",
                font=font(15),
            )
    path = OUTPUT / "speed_step_quality_series.jpg"
    canvas.save(path, quality=92, subsampling=0)
    return path


def main() -> int:
    all_records = load_records()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in all_records:
        phase = record["phase"]
        if phase in {"speed", "length_boundary", "length_boundary_control"}:
            continue
        if phase == "reliability":
            group_key = f"{record['case_id']}_seed_{record['seed']}"
        elif record["negative_mode"] == "live":
            group_key = f"{record['case_id']}_live_negative"
        else:
            group_key = record["case_id"]
        grouped[group_key].append(record)
    created: list[Path] = []
    for case_id, case_records in grouped.items():
        path = make_triptych(case_id, case_records)
        if path:
            created.append(path)
    phases = sorted({rows[0]["phase"] for rows in grouped.values()})
    for phase in phases:
        path = make_phase_overview(phase, grouped)
        if path:
            created.append(path)
    path = make_length_boundary_series(all_records)
    if path:
        created.append(path)
    path = make_length_boundary_control_series(all_records)
    if path:
        created.append(path)
    path = make_speed_series(all_records)
    if path:
        created.append(path)
    print(f"Created {len(created)} contact sheets in {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
