"""Validated workflow snapshots and immutable image assets for the full editor."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import threading
import uuid
import zlib

import numpy as np
from PIL import Image

from .vendor import look
from .vendor.document import Document, PALETTE

MAX_PIXELS = 24_000_000
MAX_PROJECT_BYTES = 24 * 1024 * 1024
ID = re.compile(r"[0-9a-f]{64}\Z")
DRAFT_ID = re.compile(r"[0-9a-f]{32}\Z")
_settings_lock = threading.RLock()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def project_digest(value):
    # JavaScript serializes 65.0 as 65 and may reorder object keys. Neither is
    # an edit, so draft ownership must survive the browser JSON round trip.
    def normalize(item):
        if isinstance(item, dict):
            return {key: normalize(value) for key, value in item.items()}
        if isinstance(item, list):
            return [normalize(value) for value in item]
        if isinstance(item, float) and item.is_integer():
            return int(item)
        return item
    data = json.dumps(normalize(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(dumps(value), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def image_digest(art):
    return hashlib.sha256(np.ascontiguousarray(art, dtype=np.uint8).tobytes()).hexdigest()


def put_asset(root, data, kind):
    if kind not in ("png", "npy"):
        raise ValueError("不支持的素材格式")
    digest = hashlib.sha256(data).hexdigest()
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{digest}.{kind}"
    if not path.exists():
        temp = root / (uuid.uuid4().hex + ".tmp")
        try:
            temp.write_bytes(data)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    return digest


def asset_path(root, digest, kind):
    if not isinstance(digest, str) or not ID.fullmatch(digest) or kind not in ("png", "npy"):
        raise ValueError("素材标识无效，请重新导入原图")
    root = Path(root).resolve()
    path = (root / f"{digest}.{kind}").resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("编辑素材不存在，请连接原图或重新导入")
    return path


def checked_asset(root, digest, kind):
    path = asset_path(root, digest, kind)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("编辑素材校验失败，请重新导入")
    return data


def pack(array, bits=True):
    data = np.packbits(array).tobytes() if bits else np.asarray(array, np.uint8).tobytes()
    return base64.b64encode(zlib.compress(data)).decode("ascii")


def unpack(value, width, height, bits=True):
    if not isinstance(value, str) or len(value) > MAX_PROJECT_BYTES:
        raise ValueError("蒙版数据无效或过大")
    size = (width * height + 7) // 8 if bits else width * height
    try:
        compressed = base64.b64decode(value, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, size + 1)
    except (ValueError, zlib.error) as exc:
        raise ValueError("蒙版数据损坏") from exc
    if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("蒙版尺寸或压缩格式不符")
    a = np.frombuffer(raw, np.uint8)
    return (np.unpackbits(a, count=width * height).astype(bool) if bits else a.copy()).reshape(height, width)


def points(value, width, height, minimum=2):
    if not isinstance(value, list) or len(value) < minimum * 2 or len(value) % 2 or len(value) > 100_000:
        raise ValueError("走向或笔画点数无效")
    a = np.asarray(value, np.float64).reshape(-1, 2)
    if not np.isfinite(a).all() or (a < 0).any() or (a[:, 0] >= width).any() or (a[:, 1] >= height).any():
        raise ValueError("笔画坐标超出图像")
    return a


def parse_project(value):
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_PROJECT_BYTES:
            raise ValueError("编辑数据超过 24 MiB")
        value = json.loads(value or "{}")
    if value == {}:
        return {}
    if not isinstance(value, dict) or value.get("schema") != 2:
        raise ValueError("不支持的完整编辑器文档格式")
    if len(dumps(value).encode("utf-8")) > MAX_PROJECT_BYTES:
        raise ValueError("编辑数据超过 24 MiB")
    w, h = value.get("width"), value.get("height")
    if type(w) is not int or type(h) is not int or min(w, h) < 8 or w * h > MAX_PIXELS:
        raise ValueError("图像尺寸须至少 8 像素且不超过 2400 万像素")
    if not isinstance(value.get("regions"), list) or len(value["regions"]) > 32:
        raise ValueError("部位最多 32 个")
    if not all(isinstance(r, dict) for r in value["regions"]):
        raise ValueError("部位数据无效")
    if not isinstance(value.get("strokes", []), list) or not isinstance(value.get("dividers", []), list):
        raise ValueError("走向与隔开线需为列表")
    if not all(isinstance(s, dict) and isinstance(s.get("pts"), list) for s in value.get("strokes", [])):
        raise ValueError("走向数据无效")
    if not all(isinstance(p, list) for p in value.get("dividers", [])):
        raise ValueError("隔开线数据无效")
    total = sum(len(s.get("pts", [])) for s in value.get("strokes", []))
    total += sum(len(p) for p in value.get("dividers", []))
    if total > 100_000:
        raise ValueError("文档笔画总点数超过 50000")
    return value


def snapshot(doc, assets, *, depth_enabled=True, dark_adapt=False, asset=None):
    snap = doc.snapshot()
    asset = asset or put_asset(assets, snap["art_png"], "png")
    result = {"schema": 2, "width": doc.w, "height": doc.h, "asset": asset,
              "image_sha256": image_digest(doc.art), "name": doc.name,
              "regions": [{"name": n, "color": c, "mask": pack(m)} for n, c, m in snap["regions"]],
              "strokes": [{"pts": p.ravel().tolist(), "region": k} for p, k in snap["strokes"]],
              "dividers": [p.ravel().tolist() for p in snap["dividers"]], "erased": snap["erased"],
              "color_exclude": snap["color_exclude"], "look": snap["look"],
              "guides_saved": snap["guides_saved"], "depth_enabled": bool(depth_enabled),
              "dark_adapt": bool(dark_adapt),
              "sparkle": pack(snap["sparkle"], False) if snap["sparkle"] is not None else None}
    if doc.disparity is not None:
        stream = io.BytesIO()
        np.save(stream, np.asarray(doc.disparity, np.float32), allow_pickle=False)
        result["depth_asset"] = put_asset(assets, stream.getvalue(), "npy")
    return parse_project(result)


def restore(value, assets, art=None):
    p = parse_project(value)
    if not p:
        if art is None:
            raise ValueError("请连接原图后运行，或在完整编辑器中导入图片/PSD")
        if art.ndim != 3 or art.shape[2] != 3 or min(art.shape[:2]) < 8 or art.shape[0] * art.shape[1] > MAX_PIXELS:
            raise ValueError("图片须至少 8 像素且不超过 2400 万像素")
        doc = Document(np.asarray(art, np.uint8), "ComfyUI.png")
        for name in ("左腿", "右腿"):
            doc.add_region(name)
        doc.look = dict(look.DEFAULTS)
        return doc
    if art is None:
        with Image.open(io.BytesIO(checked_asset(assets, p.get("asset"), "png"))) as im:
            if im.size != (p["width"], p["height"]):
                raise ValueError("原图素材与文档尺寸不符")
            art = np.asarray(im.convert("RGB")).copy()
    if tuple(art.shape) != (p["height"], p["width"], 3):
        raise ValueError("文档与输入图尺寸不同，请重新编辑")
    w, h = p["width"], p["height"]
    regions = []
    for i, r in enumerate(p["regions"]):
        name = str(r.get("name", "")).strip()
        if not name or len(name) > 40 or not name.isprintable():
            raise ValueError("部位名称需为 1–40 个可显示字符")
        color = r.get("color", PALETTE[i % len(PALETTE)])
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("部位颜色格式无效")
        regions.append((name, color, unpack(r.get("mask"), w, h)))
    strokes = []
    for s in p.get("strokes", []):
        k = s.get("region")
        if k is not None and (type(k) is not int or not 0 <= k < len(regions)):
            raise ValueError("走向的部位索引无效")
        strokes.append((points(s.get("pts"), w, h), k))
    dividers = [points(v, w, h) for v in p.get("dividers", [])]
    erased = p.get("erased", [])
    if erased:
        erased = points(np.asarray(erased).ravel().tolist(), w, h, 1).tolist()
    sparkle = unpack(p["sparkle"], w, h, False) if p.get("sparkle") is not None else None
    params = look.clean_params(p["look"]) if p.get("look") is not None else None
    doc = Document.from_snapshot(np.asarray(art, np.uint8), str(p.get("name", "ComfyUI.png"))[:180], None,
                                 regions, strokes, sparkle, params, dividers, erased,
                                 p.get("color_exclude", True), p.get("guides_saved", False))
    try:
        if p.get("depth_asset") and p.get("image_sha256") == image_digest(art):
            a = np.load(io.BytesIO(checked_asset(assets, p["depth_asset"], "npy")), allow_pickle=False)
            if a.dtype != np.float32 or a.shape != art.shape[:2] or not np.isfinite(a).all():
                raise ValueError("缓存深度图无效")
            doc.disparity = a
    except Exception:
        doc.close()
        raise
    return doc


class Preferences:
    def __init__(self, root):
        self.path = Path(root) / "preferences.json"

    def read(self):
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("预设文件损坏；请保留文件后修复")
        return value

    def update(self, **values):
        with _settings_lock:
            data = self.read()
            data.update(values)
            atomic_json(self.path, data)

    def presets(self):
        out = []
        for name, p in self.read().get("presets", {}).items():
            try:
                p = look.clean_params(p)
            except (ValueError, TypeError):
                p = None
            out.append({"name": name, "params": p})
        return out

    def save_preset(self, name, params):
        name = name.strip() if isinstance(name, str) else ""
        if not 1 <= len(name) <= 40 or not name.isprintable():
            raise ValueError("预设名称需为 1–40 个可显示字符")
        params = look.clean_params(params)
        if params["strength_auto"]:
            params["strength"] = look.DEFAULTS["strength"]
        with _settings_lock:
            data = self.read()
            presets = dict(data.get("presets", {}))
            if name not in presets and len(presets) >= 256:
                raise ValueError("预设最多 256 个")
            presets[name] = params
            data["presets"] = presets
            atomic_json(self.path, data)
        return self.presets()

    def delete_preset(self, name):
        with _settings_lock:
            data = self.read()
            presets = dict(data.get("presets", {}))
            if name not in presets:
                raise ValueError("找不到这个预设")
            del presets[name]
            data["presets"] = presets
            atomic_json(self.path, data)
        return self.presets()
