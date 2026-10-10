"""Adapt pinned texture algorithms to validated workflow guides and float RGB images.

Pure CPU processing: no files, model loaders, network, or desktop document/session state.
"""
from __future__ import annotations

import json
import math

import cv2
import numpy as np

EMPTY_GUIDES = '{"schema":1,"width":0,"height":0,"regions":[],"dividers":[]}'
STYLES = ("细线", "针织", "线圈", "斜单线", "加濑风", "油光（试验）")
STYLE_IDS = dict(zip(STYLES, ("knit", "loops", "coil", "lines", "grain", "oily")))
MAX_POINTS = 50000


def parse_guides(value, width, height):
    """Bind an empty document, otherwise require matching pixel coordinates and schema."""
    if not isinstance(value, str) or len(value.encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError("引导数据必须是小于 4 MiB 的 JSON 文本")
    try:
        data = json.loads(value or EMPTY_GUIDES)
    except (ValueError, TypeError) as exc:
        raise ValueError("引导 JSON 无效") from exc
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
        raise ValueError("仅支持 schema=1 的丝袜引导")
    rw, rh = data.get("width"), data.get("height")
    if type(rw) is not int or type(rh) is not int:
        raise ValueError("引导 width/height 必须为整数")
    regions, dividers = data.get("regions"), data.get("dividers")
    if not isinstance(regions, list) or len(regions) > 32 or not isinstance(dividers, list):
        raise ValueError("引导需包含 regions/dividers 列表，最多 32 个部位")
    if (rw, rh) == (0, 0) and not regions and not dividers:
        rw, rh = width, height
    if (rw, rh) != (width, height):
        raise ValueError(f"引导尺寸 {rw}×{rh} 与输入 {width}×{height} 不同；请重新编辑引导")
    count = 0

    def lines(value, polygon=False):
        nonlocal count
        if not isinstance(value, list):
            raise ValueError("多边形和走向线必须为列表")
        out = []
        for line in value:
            if not isinstance(line, list) or len(line) < (3 if polygon else 2):
                raise ValueError("部位多边形至少 3 点，走向/隔开线至少 2 点")
            count += len(line)
            if count > MAX_POINTS:
                raise ValueError("引导点数量超过 50000")
            pts = []
            for point in line:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError("坐标需为 [x,y]")
                x, y = point
                if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in point):
                    raise ValueError("坐标必须为有限数值")
                if not (0 <= x <= width - 1 and 0 <= y <= height - 1):
                    raise ValueError("引导坐标在输入图像之外")
                pts.append([float(x), float(y)])
            out.append(pts)
        return out

    clean, ids = [], set()
    for region in regions:
        if not isinstance(region, dict):
            raise ValueError("部位必须为对象")
        rid, name = region.get("id"), region.get("name")
        if not isinstance(rid, str) or not 1 <= len(rid) <= 128 or rid in ids:
            raise ValueError("部位 id 必须为唯一的非空字符串")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("部位名称需为 1–80 字")
        ids.add(rid)
        clean.append({"id": rid, "name": name.strip(), "polygons": lines(region.get("polygons"), True),
                      "strokes": lines(region.get("strokes"))})
    return {"schema": 1, "width": width, "height": height, "regions": clean, "dividers": lines(dividers)}


def region_maps(data, base_mask=None):
    """Later regions own overlaps; an external soft MASK also limits painted polygons."""
    h, w = data["height"], data["width"]
    maps, union = [], np.zeros((h, w), np.float32)
    for region in data["regions"]:
        raster = np.zeros((h, w), np.uint8)
        if region["polygons"]:
            for polygon in region["polygons"]:
                cv2.fillPoly(raster, [np.round(polygon).astype(np.int32)], 1)
            mask = raster.astype(np.float32)
            if base_mask is not None:
                mask *= base_mask
        else:
            mask = base_mask.copy() if base_mask is not None else raster.astype(np.float32)
        maps.append(mask)
        union = np.maximum(union, mask)
    if not maps and base_mask is not None:
        union = base_mask.copy()  # first editor preview, before the user draws a region
    return maps, union


def raster_lines(lines, shape, width):
    out = np.zeros(shape, np.uint8)
    for line in lines:
        points = np.round(np.asarray(line) * 16).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(out, [points], False, 255, width, cv2.LINE_8, 4)
    return out


def solve_geometry(rgb8, data, base_mask, color_exclude, disparity, auto_walls):
    """Synchronously solve each region, including manual/depth walls and occlusion bridges."""
    from .vendor import coverage, guide_fields as gf, walls

    h, w = rgb8.shape[:2]
    maps, _ = region_maps(data, base_mask)
    labels = np.zeros((h, w), np.int8)
    input_alpha = np.zeros((h, w), np.float32)
    for index, mask in enumerate(maps, 1):
        inside = mask > 0
        labels[inside] = index
        input_alpha[inside] = mask[inside]
    stock, feather = coverage.stocking_coverage(coverage.lab_of(rgb8), labels, exclude=color_exclude)
    # Bound the upstream blur/sparkles to the chosen area, keeping zero-MASK pixels untouched.
    alpha = feather
    stock &= input_alpha > 0
    manual = raster_lines(data["dividers"], (h, w), 3) > 0
    scale = math.sqrt(w * h / (1280 * 1920))
    ridges = walls.ridges(disparity, scale) if auto_walls and disparity is not None else None
    solved = labels.copy()
    # Document stores solved fields as float32, then assembles float64 full-image
    # coordinates. Preserve both steps: phase arithmetic can otherwise round a
    # few bright pixels differently from the original export.
    v, across = np.zeros((h, w), np.float64), np.zeros((h, w), np.float64)
    cut = np.zeros((h, w), bool)
    fill = {}
    messages = []
    for index, region in enumerate(data["regions"], 1):
        mc_full = labels == index
        box = gf.region_box(mc_full)
        if box is None:
            messages.append(f'{region["name"]}：没有选中像素')
            continue
        y0, y1, x0, x1 = box
        sl = (slice(y0, y1), slice(x0, x1))
        mc = mc_full[sl]
        guides = raster_lines(region["strokes"], (h, w), 5)[sl]
        wall = manual[sl].copy()
        if ridges is not None:
            wall |= walls.find_walls(walls.crop(ridges, sl), stock[sl] & mc, scale)
        info = {}
        if min(mc.shape) < 8 or int(mc.sum()) < 16:
            fields = None
        else:
            try:
                fields = gf.solve_region(mc, guides, walls=wall if wall.any() else None, info=info)
            except ZeroDivisionError:
                # A wall can remove every sampled guide point; upstream's mean anchor is then undefined.
                fields = None
                messages.append(f'{region["name"]}：隔开线遮住走向约束，请调整走向或隔开线')
        if fields is None:
            solved[sl][mc] = 0
            messages.append(f'{region["name"]}：没有有效走向线，保持原图')
            continue
        valid = np.isfinite(fields[0]) & np.isfinite(fields[3])
        solved[sl][mc & ~valid] = 0
        if (mc & ~valid).any():
            messages.append(f'{region["name"]}：未引导的分离区域保持原图')
        for dst, field in ((v, fields[0]), (across, fields[3])):
            dst[sl][mc & valid] = field[mc & valid].astype(np.float32)
        if info.get("cut") is not None:
            cut[sl] |= info["cut"] & mc
        gap = gf.fill_occlusions(mc) & ~mc & (labels[sl] == 0)
        if info.get("cut") is not None:
            gap &= ~info["cut"]
        if gap.any():
            fill[index] = np.zeros((h, w), bool)
            fill[index][sl] = gap
    return dict(labels=solved, all_labels=labels, v=v, across=across, stock=stock,
                alpha=alpha, input_alpha=input_alpha, cut=cut, fill=fill, messages=messages)


def render_texture(rgb, data, geometry, disparity, params, seed, dark_adapt=True):
    """Return float RGB result/layer, compositing alpha, diagnostic RGB, and actual metrics."""
    from .vendor import knit, look
    from .rendering import render_scene

    class SeededScene(look.Scene):
        def randoms(self, style):
            with self._lock:
                if style not in self._randoms:
                    rng = np.random.default_rng(seed)
                    grain = knit.grain_noise(rng, self.h, self.w) if style == "grain" else ()
                    self._randoms[style] = (*grain, rng.random((self.h, self.w)), rng.random((self.h, self.w)))
                return self._randoms[style]

    rgb8 = np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    g = geometry
    scene = SeededScene(rgb8, g["labels"], g["v"], g["across"], g["stock"], g["alpha"],
                        [r["name"] for r in data["regions"]],
                        disparity=(lambda: disparity) if disparity is not None else None,
                        cut=g["cut"], fill=g["fill"])
    out8, metrics = render_scene(scene, params, dark_adapt)
    active = (g["labels"] > 0) & g["stock"] & (g["alpha"] > 0)
    # Keep the exact uint8/255 representation at full coverage. Adding a
    # separately divided integer delta can land just below that value, and
    # ComfyUI SaveImage truncation then loses a colour level. Preserve the
    # source's sub-8-bit residual for float inputs and blend soft masks once.
    target = out8[..., ::-1].astype(np.float32) / 255 + (rgb - rgb8.astype(np.float32) / 255)
    weight = (active * g["input_alpha"])[..., None]
    result = np.where(weight == 1, target, rgb + (target - rgb) * weight)
    result = np.clip(result, 0, 1).astype(np.float32)
    diff = result - rgb
    # Solve a straight-alpha layer in float space; it composites exactly, including soft edges.
    need = np.where(diff > 0, diff / np.maximum(1 - rgb, 1e-9),
                    np.where(diff < 0, -diff / np.maximum(rgb, 1e-9), 0)).max(axis=2)
    layer_alpha = np.clip(np.maximum(g["alpha"] * g["input_alpha"] * active, need), 0, 1).astype(np.float32)
    layer = np.where(layer_alpha[..., None] > 0,
                     rgb + diff / np.maximum(layer_alpha[..., None], 1e-9), 0)
    layer = np.clip(layer, 0, 1).astype(np.float32)
    faded, excluded = scene.check(params)
    diagnostic = rgb * 0.4
    diagnostic[excluded & (g["all_labels"] > 0)] = (0.12, 0.4, 1)
    diagnostic[(g["all_labels"] > 0) & (g["labels"] == 0)] = (1, 0.8, 0.08)
    diagnostic[faded & active] = (1, 0.12, 0.1)
    # Count rounded 8-bit changes, not just nonzero floats (SaveImage truncation may differ).
    quantized = np.round(result * 255).astype(np.uint8)
    changed8 = np.any(quantized != rgb8, axis=2)
    messages = list(g["messages"])
    if active.any() and not changed8.any():
        messages.append("有效区域已求解，但 8 位成品没有可见变化；检查纯黑像素、强度、密度和亮点设置")
    if params["strength_auto"] and params["strength"] != metrics["effective_strength"]:
        messages.append(f'自动强度实际为 {metrics["effective_strength"]:g}%；手动值未采用，调节强度时请关闭自动')
    metrics.update(changed_pixels=int(np.any(diff != 0, axis=2).sum()),
                   changed_pixels_8bit=int(changed8.sum()),
                   max_delta_8bit=float(np.abs(diff).max() * 255),
                   active_pixels=int(active.sum()), excluded_pixels=int((excluded & (g["all_labels"] > 0)).sum()),
                   faded_pixels=int((faded & active).sum()),
                   selected_pixels=int((g["all_labels"] > 0).sum()),
                   solved_pixels=int((g["labels"] > 0).sum()), messages=messages, seed=int(seed))
    return result, layer, layer_alpha, diagnostic.astype(np.float32), metrics
