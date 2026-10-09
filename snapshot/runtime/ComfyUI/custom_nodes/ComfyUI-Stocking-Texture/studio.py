"""Editor-owned document, rendering and restoration. HTTP and nodes share this owner."""
import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from . import studio_models as models
from . import studio_store as store
from .rendering import render_scene
from .vendor import export, look
from .vendor.document import Document


def base_params(doc):
    if doc.look is not None:
        return dict(doc.look)
    if doc.sparkle is not None:
        return {"sparkle_depth": 0., "sparkle_bright": 0., "sparkle_painted": 100.}
    return {}


def check_maps(doc, scene, params):
    faded, excluded = scene.check(params)
    painted = doc.region_map() > 0
    missing = [i for i, r in enumerate(doc.state()["regions"], 1) if r["status"] in ("nostroke", "error")]
    nostroke = np.isin(doc.region_map(), missing) if missing else np.zeros_like(painted)
    nostroke |= doc.unguided_map()
    return faded, excluded, nostroke, painted


def check_image(doc, scene, params, *, rect=None, size=None):
    maps = [m.astype(np.float32) for m in check_maps(doc, scene, params)[:3]]
    if rect is not None:
        x0, y0, x1, y1 = rect
        maps = [m[y0:y1, x0:x1] for m in maps]
    elif size is not None:
        maps = [cv2.resize(m, size, interpolation=cv2.INTER_AREA) for m in maps]
    rgba = np.zeros((*maps[0].shape, 4), np.float32)
    for k, colour in ((2, (40, 190, 255)), (1, (255, 150, 70)), (0, (60, 50, 255))):
        a = np.clip(maps[k] * 1.3, 0, 1) * .85
        rgba[..., :3] = rgba[..., :3] * (1 - a[..., None]) + np.array(colour, np.float32) * a[..., None]
        rgba[..., 3] = rgba[..., 3] * (1 - a) + a
    rgb = rgba[..., :3] / np.maximum(rgba[..., 3:], 1e-6)
    return np.dstack((rgb, rgba[..., 3] * 255)).clip(0, 255).astype(np.uint8)


class Studio:
    def __init__(self, assets, preferences, model_paths, project=None, *, art=None, draft_id=None):
        self.assets, self.preferences, self.model_paths = Path(assets), preferences, model_paths
        self.project = store.parse_project(project or {})
        self.base_hash = store.project_digest(self.project)
        self.draft_id = draft_id
        if draft_id is not None and not store.DRAFT_ID.fullmatch(draft_id):
            raise ValueError("自动保存标识无效")
        self.doc = store.restore(self.project, self.assets, art) if self.project or art is not None else None
        self.depth_enabled = bool(self.project.get("depth_enabled", True))
        self.dark_adapt = bool(self.project.get("dark_adapt", True))
        self.depth_status, self.depth_error = "idle", None
        self.depth_revision = 0
        self.on_event = lambda event: None
        self.last_access = time.monotonic()
        self.closed = False
        self.lock = threading.RLock()
        self._scene = (None, None)
        self._adapted = (None, None)
        self._asset = self.project.get("asset") if art is None else None
        if self.doc:
            self._bind(self.doc)

    def _bind(self, doc):
        self.depth_revision += 1
        doc.on_event = self.publish
        doc.sam_state = "ready" if models.available(self.model_paths)["sam"] else "error"
        doc.sam_error = None if doc.sam_state == "ready" else "缺少 SAM ViT-B 模型"
        self.depth_status = "ready" if doc.disparity is not None else "idle"
        self.depth_error = None
        self._scene, self._adapted = (None, None), (None, None)

    def publish(self, event):
        if not self.closed:
            self.on_event(event)

    def replace(self, doc):
        with self.lock:
            if self.doc:
                self.doc.close()
            self.doc = doc
            self._asset = None
            self._bind(doc)
            self.save_draft()
        self.publish({"type": "opened", "doc": doc.id})
        self.start_depth()

    def open_bytes(self, data, filename):
        if len(data) > 128 * 1024 * 1024:
            raise ValueError("导入文件超过 128 MiB")
        doc = Document.open(data=data, filename=Path(filename).name)
        if doc.w * doc.h > store.MAX_PIXELS or min(doc.w, doc.h) < 8:
            doc.close()
            raise ValueError("图片须至少 8 像素且不超过 2400 万像素")
        self.replace(doc)
        return self.state()

    def state(self):
        if self.doc is None:
            return None
        result = self.doc.state()
        result["sam"]["device"] = "CPU"
        return result

    def scene(self):
        doc = self.doc
        key = (doc.render_key(), id(doc.disparity))
        with self.lock:
            if self._scene[0] != key:
                self._scene = (key, look.scene_from_doc(doc, disparity=lambda: doc.disparity))
                self._adapted = (None, None)
            return self._scene[1]

    def params(self, overrides=None):
        p = base_params(self.doc)
        if overrides:
            p.update({k: v for k, v in overrides.items() if k in look.DEFAULTS})
        return look.clean_params(p)

    def render(self, params=None, rect=None):
        q = self.params(params)
        scene = self.scene()
        if not self.dark_adapt:
            return scene.render(q, rect)
        key = (self._scene[0], tuple(sorted(q.items())))
        with self.lock:
            if self._adapted[0] != key:
                self._adapted = (key, render_scene(scene, q, True))
            out, info = self._adapted[1]
        if rect is not None:
            x0, y0, x1, y1 = rect
            out = out[y0:y1, x0:x1]
        return out, info

    def look_info(self, overrides=None):
        doc, scene = self.doc, self.scene()
        q = scene.resolve(self.params(overrides))
        g = look.geometry(q["density"], doc.w, doc.h)
        faded, excluded, nostroke, painted = check_maps(doc, scene, q)
        n = max(int(painted.sum()), 1)
        regions = doc.state()["regions"]
        untextured = [r["name"] for r in regions if r["status"] in ("nostroke", "error")]
        untextured += [r["name"] + "分开的一块" for r in regions if r["status"] == "ok" and r["unguided"]]
        return dict(g, params=q, strength_suggested=scene.suggested_strength(), densest=scene.densest(),
                    untextured=untextured, solving=[r["name"] for r in regions if r["status"] in ("pending", "solving")],
                    check={"faded": float(faded.sum() / n), "excluded": float(excluded.sum() / n),
                           "nostroke": float(nostroke.sum() / n)},
                    textured=int((scene.R > 0).sum()), has_sparkle_layer=doc.sparkle is not None,
                    depth=self.depth_status, depth_error=self.depth_error)

    def start_depth(self):
        with self.lock:
            doc = self.doc
            if self.closed or doc is None or not self.depth_enabled or doc.disparity is not None:
                return
            if self.depth_status == "working":
                return
            if not models.available(self.model_paths)["depth"]:
                self.depth_status, self.depth_error = "error", "缺少 Depth Anything V2 Small 模型"
                self.publish({"type": "depth"})
                return
            self.depth_status, self.depth_error = "working", None
            revision = self.depth_revision

        def run():
            try:
                disparity = models.estimate_depth(doc.art, self.model_paths)
                with self.lock:
                    if self.closed or self.doc is not doc or not self.depth_enabled or self.depth_revision != revision:
                        return
                    doc.disparity = disparity
                    self.depth_status = "ready"
                    self.save_draft()
            except Exception as exc:
                with self.lock:
                    if self.doc is doc and self.depth_revision == revision and not self.closed:
                        self.depth_status, self.depth_error = "error", str(exc)
            self.publish({"type": "depth"})
        threading.Thread(target=run, name="stocking-studio-depth", daemon=True).start()

    def segment(self, rid, x, y, subtract=False):
        doc = self.doc
        doc.region(rid)
        if not np.isfinite([x, y]).all() or not 0 <= x < doc.w or not 0 <= y < doc.h:
            raise ValueError("点选坐标在画面外")
        masks, _ = models.segment(doc.art, x, y, self.model_paths)
        if self.doc is not doc or self.closed:
            raise ValueError("图片已更换，请重新点选")
        doc.segment_click(rid, x, y, subtract, masks, 0)

    def project_data(self):
        if self.doc is None:
            return {}
        data = store.snapshot(self.doc, self.assets, depth_enabled=self.depth_enabled,
                              dark_adapt=self.dark_adapt, asset=self._asset)
        self._asset = data["asset"]
        return data

    def save_draft(self):
        if not self.draft_id or self.doc is None or self.closed:
            return
        path = self.preferences.path.parent / "drafts" / (self.draft_id + ".json")
        store.atomic_json(path, {"base_hash": self.base_hash, "project": self.project_data()})

    def restore_draft(self):
        if not self.draft_id:
            return False
        path = self.preferences.path.parent / "drafts" / (self.draft_id + ".json")
        if not path.is_file():
            return False
        record = json.loads(path.read_text(encoding="utf-8"))
        # An externally edited or older workflow is authoritative over an unrelated draft.
        if record["base_hash"] != self.base_hash:
            return False
        draft = store.parse_project(record["project"])
        doc = store.restore(draft, self.assets)
        if self.doc:
            self.doc.close()
        self.doc, self._asset = doc, draft.get("asset")
        self.depth_enabled, self.dark_adapt = draft.get("depth_enabled", True), draft.get("dark_adapt", True)
        self._bind(doc)
        return True

    def wait_ready(self, timeout=180):
        doc = self.doc
        self.start_depth()
        end = time.monotonic() + timeout
        while self.depth_enabled and self.depth_status == "working" and time.monotonic() < end:
            time.sleep(.05)
        if self.depth_enabled and self.depth_status != "ready":
            raise ValueError(self.depth_error or "深度计算超时，请重试")
        if not doc.wait_idle(max(1, end - time.monotonic())):
            raise ValueError("走向求解超时，请减少区域或分辨率后重试")
        failed = [r for r in doc.state()["regions"] if r["status"] == "error"]
        if failed:
            raise ValueError("走向求解失败：" + "; ".join(r["name"] + ": " + str(r["error"]) for r in failed))

    def outputs(self):
        self.wait_ready()
        out, info = self.render()
        rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        layer = export.stocking_layer(self.doc.art, rgb, self.doc.coverage()[1])
        check = check_image(self.doc, self.scene(), self.params())
        report = self.look_info()
        report.update(changed_pixels=int(np.any(rgb != self.doc.art, axis=2).sum()),
                      dark_adapt=self.dark_adapt, sparkles_ready=info["sparkles_ready"])
        return rgb, layer, cv2.cvtColor(check, cv2.COLOR_BGRA2RGBA), report

    def close(self):
        with self.lock:
            self.save_draft()
            self.closed = True
            if self.doc:
                self.doc.close()
            self._scene, self._adapted = (None, None), (None, None)
