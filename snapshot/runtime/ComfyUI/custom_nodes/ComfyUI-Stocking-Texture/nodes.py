"""ComfyUI IMAGE/MASK adapters and editor previews for the stocking texture engine.

Only editor previews write to ComfyUI's temp directory; rendering stays in memory.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from .engine import (EMPTY_GUIDES, STYLES, STYLE_IDS, parse_guides, region_maps,
                     render_texture, solve_geometry)


def image_array(image):
    if not isinstance(image, torch.Tensor) or image.ndim != 4 or image.shape[-1] not in (3, 4):
        raise ValueError("IMAGE 必须为 [B,H,W,3/4] 张量")
    if image.shape[0] < 1 or min(image.shape[1:3]) < 8:
        raise ValueError("输入图像不能为空，宽高至少 8 像素")
    array = image.detach().cpu().float().numpy()
    if not np.isfinite(array).all() or (array < 0).any() or (array > 1).any():
        raise ValueError("IMAGE 必须为有限的 0–1 像素")
    return array


def mask_array(mask, batch, height, width):
    if mask is None:
        return None
    if not isinstance(mask, torch.Tensor):
        raise ValueError("MASK 必须为张量")
    a = mask.detach().cpu().float().numpy()
    if a.ndim == 2:
        a = a[None]
    if a.ndim != 3 or a.shape[1:] != (height, width) or a.shape[0] not in (1, batch):
        raise ValueError("MASK 需与图像等大，批次数为 1 或与 IMAGE 相同")
    if not np.isfinite(a).all() or (a < 0).any() or (a > 1).any():
        raise ValueError("MASK 必须为有限的 0–1，1 表示应用纹理")
    return np.broadcast_to(a, (batch, height, width))


def depth_array(depth, batch, height, width, mode):
    if depth is None:
        return None
    a = image_array(depth)
    if a.shape[1:3] != (height, width) or a.shape[0] not in (1, batch):
        raise ValueError("深度图需与原图等大，批次数为 1 或与 IMAGE 相同")
    a = a[..., :3].mean(axis=3)
    a = (1 - a) if mode == "近处较暗" else a
    return np.broadcast_to(a, (batch, height, width)).astype(np.float32)


class StockingTextureGuides:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",),
                             "guides_json": ("STRING", {"default": EMPTY_GUIDES, "multiline": True})},
                "optional": {"mask": ("MASK",)}}

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("原图", "部位蒙版", "引导数据")
    FUNCTION = "prepare"
    CATEGORY = "image/丝袜纹理"
    OUTPUT_NODE = True
    DESCRIPTION = "接图后运行一次，点击编辑丝袜引导，圈选部位并画走向线。外接 MASK 的白色为应用区域。"

    def prepare(self, image, guides_json=EMPTY_GUIDES, mask=None):
        a = image_array(image)
        b, h, w = a.shape[:3]
        data = parse_guides(guides_json, w, h)
        masks = mask_array(mask, b, h, w)
        union = np.stack([region_maps(data, masks[i] if masks is not None else None)[1] for i in range(b)])
        import folder_paths
        temp = Path(folder_paths.get_temp_directory())
        temp.mkdir(parents=True, exist_ok=True)
        key = uuid.uuid4().hex
        art_name, mask_name = f"stocking_{key}.png", f"stocking_{key}_mask.png"
        Image.fromarray(np.round(a[0, ..., :3] * 255).astype(np.uint8)).save(temp / art_name)
        # The editor shows the external constraint, not the union of its own painted polygons.
        preview_mask = masks[0] if masks is not None else np.zeros((h, w), np.float32)
        Image.fromarray(np.round(preview_mask * 255).astype(np.uint8)).save(temp / mask_name)
        descriptor = lambda name: {"filename": name, "subfolder": "", "type": "temp"}
        meta = {"width": w, "height": h, "has_mask": masks is not None, "mask": descriptor(mask_name)}
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return {"ui": {"images": [descriptor(art_name)], "stocking": [meta]},
                "result": (image, torch.from_numpy(union.copy()), text)}


class StockingTextureRender:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",), "guides_json": ("STRING", {"default": EMPTY_GUIDES, "multiline": True}),
            "style": (list(STYLES),),
            "density": ("FLOAT", {"default": 100, "min": 40, "max": 200, "step": 1}),
            "strength": ("FLOAT", {"default": 100, "min": 0, "max": 250, "step": 1}),
            "auto_strength": ("BOOLEAN", {"default": True}),
            "tilt": ("FLOAT", {"default": 32, "min": 0, "max": 75, "step": 1}),
            "sparkle_bright": ("FLOAT", {"default": 100, "min": 0, "max": 300, "step": 1}),
            "sparkle_even": ("FLOAT", {"default": 0, "min": 0, "max": 300, "step": 1}),
            "sparkle_depth": ("FLOAT", {"default": 0, "min": 0, "max": 300, "step": 1}),
            "color_exclude": ("BOOLEAN", {"default": True}),
            "auto_walls": ("BOOLEAN", {"default": False}),
            "depth_mode": (["近处较亮", "近处较暗"],),
            "seed": ("INT", {"default": 20261005, "min": 0, "max": 0xffffffffffffffff})},
            "optional": {"mask": ("MASK",), "depth": ("IMAGE",),
                         "dark_adapt": ("BOOLEAN", {"default": True})}}

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", "IMAGE", "STRING")
    RETURN_NAMES = ("成品", "透明纹理图层", "图层透明度", "问题标记", "处理说明")
    FUNCTION = "render"
    CATEGORY = "image/丝袜纹理"
    DESCRIPTION = "成图后处理。红=高频减弱，蓝=颜色排除，黄=缺走向。透明纹理图层可直接接 SaveImage；图层透明度 1 为不透明。"

    def __init__(self):
        self._cache_key = None
        self._geometry = None
        self._lock = threading.Lock()

    def render(self, image, guides_json=EMPTY_GUIDES, style="细线", density=100, strength=100,
               auto_strength=True, tilt=32, sparkle_bright=100, sparkle_even=0, sparkle_depth=0,
               color_exclude=True, auto_walls=False, depth_mode="近处较亮", seed=20261005,
               mask=None, depth=None, dark_adapt=True):
        a = image_array(image)
        b, h, w = a.shape[:3]
        data = parse_guides(guides_json, w, h)
        if style not in STYLE_IDS or depth_mode not in ("近处较亮", "近处较暗"):
            raise ValueError("未知纹理样式或深度方向")
        if type(seed) is not int or not 0 <= seed <= 0xffffffffffffffff:
            raise ValueError("seed 必须为无符号 64 位整数")
        values = {"density": (density, 40, 200), "strength": (strength, 0, 250), "tilt": (tilt, 0, 75),
                  "sparkle_bright": (sparkle_bright, 0, 300), "sparkle_even": (sparkle_even, 0, 300),
                  "sparkle_depth": (sparkle_depth, 0, 300)}
        for name, (value, low, high) in values.items():
            if not isinstance(value, (int, float)) or not np.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} 必须为 {low}–{high} 的有限数值")
        masks, depths = mask_array(mask, b, h, w), depth_array(depth, b, h, w, depth_mode)
        if depths is None and (auto_walls or sparkle_depth > 0):
            raise ValueError("按深度亮点或自动隔开线需要接入深度 IMAGE；也可关闭这两项")
        params = {"style": STYLE_IDS[style], "density": density, "strength": strength,
                  "strength_auto": bool(auto_strength), "tilt": tilt, "sparkle_link": False,
                  "sparkle_bright": sparkle_bright, "sparkle_even": sparkle_even,
                  "sparkle_depth": sparkle_depth, "sparkle_painted": 0}
        results, layers, alphas, checks, reports = [], [], [], [], []
        canonical = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        for i in range(b):
            rgb = a[i, ..., :3]
            base = masks[i] if masks is not None else None
            disp = depths[i] if depths is not None else None
            rgb8 = np.round(rgb * 255).astype(np.uint8)
            digest = hashlib.sha256(canonical)
            digest.update(rgb8.tobytes())
            digest.update(bytes((bool(color_exclude), bool(auto_walls))))
            for arr in (base, disp):
                digest.update(b"none" if arr is None else arr.tobytes())
            key = (w, h, digest.digest())
            with self._lock:
                geometry = self._geometry if self._cache_key == key else None
            if geometry is None:
                geometry = solve_geometry(rgb8, data, base, color_exclude, disp, auto_walls)
                with self._lock:
                    self._cache_key, self._geometry = key, geometry  # one bounded cache per node
            result, layer, alpha, check, report = render_texture(rgb, data, geometry, disp, params, seed, dark_adapt)
            if a.shape[-1] == 4:
                result = np.concatenate((result, a[i, ..., 3:]), axis=2)
                report["messages"] = [*report["messages"], "透明纹理图层用于 RGB 底图复合；透明底图复合后须恢复原图 alpha"]
            report["batch_index"] = i
            results.append(result); layers.append(np.dstack((layer, alpha))); alphas.append(alpha); checks.append(check); reports.append(report)
        to_tensor = lambda arrays: torch.from_numpy(np.stack(arrays))
        return (to_tensor(results), to_tensor(layers), to_tensor(alphas), to_tensor(checks),
                json.dumps({"schema": 1, "images": reports}, ensure_ascii=False, allow_nan=False))


NODE_CLASS_MAPPINGS = {"StockingTextureGuides": StockingTextureGuides, "StockingTextureRender": StockingTextureRender}
NODE_DISPLAY_NAME_MAPPINGS = {"StockingTextureGuides": "丝袜纹理 · 引导编辑", "StockingTextureRender": "丝袜纹理 · 渲染"}
