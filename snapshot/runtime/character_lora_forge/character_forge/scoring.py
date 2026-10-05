from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat


def average_hash(path: Path, size: int = 16) -> str:
    with Image.open(path) as source:
        image = source.convert("L").resize(
            (size, size),
            Image.Resampling.LANCZOS,
        )
        values = list(image.getdata())
    mean = sum(values) / len(values)
    bits = "".join("1" if value >= mean else "0" for value in values)
    return f"{int(bits, 2):0{size * size // 4}x}"


def hash_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def technical_score(
    path: Path,
    expected_width: int,
    expected_height: int,
) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        gray = image.convert("L")
        luminance = ImageStat.Stat(gray)
        mean_luma = float(luminance.mean[0])
        variance = float(luminance.var[0])
        edges = gray.filter(ImageFilter.FIND_EDGES)
        sharpness = float(ImageStat.Stat(edges).var[0])

    expected_ratio = expected_width / max(expected_height, 1)
    actual_ratio = width / max(height, 1)
    ratio_error = abs(math.log(max(actual_ratio, 0.001) / expected_ratio))

    resolution_points = min(30.0, min(width, height) / 768 * 30)
    sharpness_points = min(25.0, sharpness / 220 * 25)
    exposure_points = 20.0 if 35 <= mean_luma <= 225 else 8.0
    aspect_points = max(0.0, 15.0 - ratio_error * 45)
    variance_points = min(10.0, variance / 1800 * 10)
    total = round(
        resolution_points
        + sharpness_points
        + exposure_points
        + aspect_points
        + variance_points,
        2,
    )
    return {
        "width": width,
        "height": height,
        "mean_luma": round(mean_luma, 2),
        "luma_variance": round(variance, 2),
        "edge_variance": round(sharpness, 2),
        "aspect_error": round(ratio_error, 4),
        "technical_total": total,
        "hash": average_hash(path),
        "hard_reject": min(width, height) < 640 or variance < 80,
    }


def combined_score(
    technical: dict[str, Any],
    vlm: dict[str, Any] | None,
) -> float:
    if vlm is None:
        return float(technical["technical_total"])
    return round(
        float(vlm.get("rubric_total", 0)) * 0.88
        + float(technical["technical_total"]) * 0.12,
        2,
    )
