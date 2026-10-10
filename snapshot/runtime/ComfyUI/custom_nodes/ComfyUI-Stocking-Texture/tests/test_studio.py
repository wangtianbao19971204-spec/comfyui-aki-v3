"""Full-editor contracts: real document edits, saved workflow data, PSD and HTTP previews."""
import asyncio
import base64
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
import zlib

from aiohttp import web, FormData
from aiohttp.test_utils import TestClient, TestServer
import cv2
import numpy as np
from PIL import Image
import torch

from test_nodes import PLUGIN, fixture

store = importlib.import_module(PLUGIN.__name__ + ".studio_store")
studio_module = importlib.import_module(PLUGIN.__name__ + ".studio")
api = importlib.import_module(PLUGIN.__name__ + ".studio_api")
assets_ui = importlib.import_module(PLUGIN.__name__ + ".studio_assets")
vendor = importlib.import_module(PLUGIN.__name__ + ".vendor.document")
psd = importlib.import_module(PLUGIN.__name__ + ".vendor.psd_io")
look = importlib.import_module(PLUGIN.__name__ + ".vendor.look")


def document():
    image, mask, guides = fixture()
    art = np.round(image[0].numpy() * 255).astype(np.uint8)
    params = dict(look.DEFAULTS, sparkle_depth=0, sparkle_bright=0, sparkle_even=0,
                  sparkle_link=False, strength_auto=False, density=65)
    return vendor.Document.from_snapshot(art, "验收.png", None,
        [("左腿", "#65a7fa", mask[0].numpy() > 0)],
        [(np.asarray(p), 0) for p in guides["regions"][0]["strokes"]],
        look=params, color_exclude=False)


class StudioContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / "input/stocking_studio/assets"
        self.models = {"sam": self.root / "missing.pth", "depth": self.root / "missing-depth"}
        self.doc = document()
        self.project = store.snapshot(self.doc, self.assets, depth_enabled=False, dark_adapt=False)
        self.owned = [self.doc]

    def tearDown(self):
        for item in self.owned:
            item.close()
        self.temp.cleanup()

    def studio(self, project=None, draft_id=None):
        s = studio_module.Studio(self.assets, store.Preferences(self.root / "user"), self.models,
                                self.project if project is None else project, draft_id=draft_id)
        self.owned.append(s)
        return s

    def test_six_styles_roundtrip_match_frozen_snapshot_and_crop(self):
        one, two = self.studio(), self.studio()
        one.wait_ready(); two.wait_ready()
        for style in look.STYLES:
            with self.subTest(style=style):
                a = one.render({"style": style})[0]
                b = two.render({"style": style})[0]
                np.testing.assert_array_equal(a, b)
                crop = one.render({"style": style}, (24, 32, 80, 104))[0]
                np.testing.assert_array_equal(crop, a[32:104, 24:80])
                self.assertGreater(np.any(a[..., ::-1] != one.doc.art, axis=2).sum(), 0)

    def test_pixel_brush_erase_and_undo_restore_exact_masks(self):
        d = self.studio().doc
        rid = d.regions[0].id
        original = d.region(rid).mask.copy()
        d.paint(rid, [64, 80, 70, 84], 12, True)
        erased = d.region(rid).mask.copy()
        self.assertLess(erased.sum(), original.sum())
        d.undo(); np.testing.assert_array_equal(d.region(rid).mask, original)
        d.redo(); np.testing.assert_array_equal(d.region(rid).mask, erased)
        d.paint(rid, [64, 80, 70, 84], 12, False)
        np.testing.assert_array_equal(d.region(rid).mask, original)

    def test_split_merge_and_mirror_preserve_region_data(self):
        d = self.studio().doc
        original = d.regions[0].mask.copy()
        left, right = d.split_region(d.regions[0].id, [[64, 0], [64, 159]])
        self.assertEqual(len(d.regions), 2)
        np.testing.assert_array_equal(d.region(left).mask | d.region(right).mask, original)
        d.merge_region(left, right)
        np.testing.assert_array_equal(d.region(right).mask, original)
        d.undo(); self.assertEqual(len(d.regions), 2)
        d.undo(); self.assertEqual(len(d.regions), 1)
        mask = np.zeros((160, 128), bool); mask[10:150, 15:58] = True
        mirror = np.fliplr(mask).copy()
        other = vendor.Document.from_snapshot(d.art, "mirror.png", None,
            [("左腿", "#65a7fa", mask), ("右腿", "#f2823b", mirror)],
            [(np.array([[20, 40], [36, 35], [53, 40]]), 0)], color_exclude=False)
        self.owned.append(other)
        made, _, rms = other.mirror_strokes(other.regions[0].id, other.regions[1].id)
        self.assertGreater(made, 0)
        self.assertLess(rms, 1)
        self.assertTrue(other.wait_idle())
        self.assertEqual([r["status"] for r in other.state()["regions"]], ["ok", "ok"])

    def test_psd_art_masks_strokes_painted_sparkles_and_dividers_roundtrip(self):
        d = self.doc
        sparkle = np.zeros((d.h, d.w), np.uint8); sparkle[45:55, 45:55] = 180
        d.sparkle = sparkle
        d.add_divider([65, 65, 70, 100])
        path = self.root / "guide.psd"
        psd.write_guides(str(path), d.art, {r.name: r.mask for r in d.regions}, d.stroke_alpha(),
                         {r.name: r.color for r in d.regions}, sparkle, d.divider_alpha())
        reopened = vendor.Document.open(str(path))
        self.owned.append(reopened)
        np.testing.assert_array_equal(reopened.art, d.art)
        np.testing.assert_array_equal(reopened.regions[0].mask, d.regions[0].mask)
        np.testing.assert_array_equal(reopened.sparkle, sparkle)
        self.assertGreater(len(reopened.strokes), 0)
        self.assertGreater(len(reopened.dividers), 0)

    def test_presets_are_independent_of_picture_and_keep_unreadable_records(self):
        p = store.Preferences(self.root / "user")
        params = dict(look.DEFAULTS, style="coil", density=65, strength_auto=True, strength=17,
                      moire_on=True, moire=60, moire_area=35)
        p.save_preset("常用白丝", params)
        fresh = store.Preferences(self.root / "user")
        self.assertEqual(fresh.presets()[0]["params"]["style"], "coil")
        self.assertEqual(fresh.presets()[0]["params"]["strength"], look.DEFAULTS["strength"])
        for key in ("moire_on", "moire", "moire_area"):
            self.assertEqual(fresh.presets()[0]["params"][key], params[key])
        fresh.save_preset("常用白丝", dict(params, density=80))
        self.assertEqual(len(p.presets()), 1)
        self.assertEqual(p.presets()[0]["params"]["density"], 80)
        data = p.read(); data["presets"]["future"] = {"style": "future-style"}
        store.atomic_json(p.path, data)
        raw = p.path.read_bytes()
        self.assertIsNone(p.presets()[1]["params"])
        self.assertEqual(raw, p.path.read_bytes())
        p.delete_preset("常用白丝")
        self.assertEqual(p.presets()[0]["name"], "future")

    def test_draft_restore_does_not_replace_a_changed_workflow(self):
        draft_id = "a" * 32
        first = self.studio(draft_id=draft_id)
        first.doc.rename_region(first.doc.regions[0].id, "恢复草稿")
        first.save_draft()
        second = self.studio(draft_id=draft_id)
        self.assertTrue(second.restore_draft())
        self.assertEqual(second.doc.regions[0].name, "恢复草稿")
        changed = json.loads(store.dumps(self.project)); changed["dark_adapt"] = True
        third = self.studio(changed, draft_id)
        self.assertFalse(third.restore_draft())
        self.assertEqual(third.doc.regions[0].name, "左腿")

    def test_browser_integer_normalization_and_key_order_preserve_draft(self):
        first = self.studio(draft_id="b" * 32)
        first.doc.rename_region(first.doc.regions[0].id, "浏览器往返草稿")
        first.save_draft()
        browser = json.loads(store.dumps(self.project),
            parse_float=lambda value: int(float(value)) if float(value).is_integer() else float(value))
        browser = dict(reversed(list(browser.items())))
        second = self.studio(browser, "b" * 32)
        self.assertTrue(second.restore_draft())
        self.assertEqual(second.doc.regions[0].name, "浏览器往返草稿")

    def test_rejects_path_traversal_bad_masks_nonfinite_and_shape_changes(self):
        with self.assertRaises(ValueError): store.asset_path(self.assets, "../secret", "png")
        with self.assertRaises(ValueError): store.unpack(base64.b64encode(zlib.compress(b"x" * 100_000)).decode(), 8, 8)
        with self.assertRaises(ValueError): store.points([0, 0, float("nan"), 3], 8, 8)
        with self.assertRaises(ValueError): store.restore(self.project, self.assets, np.zeros((20, 20, 3), np.uint8))
        broken = dict(self.project, asset="/etc/passwd")
        with self.assertRaises(ValueError): store.restore(broken, self.assets)

    def test_node_saved_project_runs_without_browser_and_layers_composite(self):
        fake = types.SimpleNamespace(models_dir=str(self.root / "models"), folder_names_and_paths={},
            get_input_directory=lambda: str(self.root / "input"),
            get_user_directory=lambda: str(self.root / "user"), get_temp_directory=lambda: str(self.root / "temp"))
        with mock.patch.dict(sys.modules, {"folder_paths": fake}):
            node = PLUGIN.NODE_CLASS_MAPPINGS["StockingTextureStudio"]()
            result = node.render(store.dumps(self.project))
        output, layer, alpha = [a[0].numpy() for a in result["result"][:3]]
        composite = self.doc.art.astype(np.float32) / 255 * (1 - alpha[..., None]) + layer[..., :3] * alpha[..., None]
        self.assertLessEqual(np.abs(composite - output).max() * 255, 1.1)
        np.testing.assert_array_equal((output * 255).astype(np.uint8), np.round(output * 255).astype(np.uint8))
        self.assertEqual(result["ui"]["stocking_studio"][0]["project"]["asset"], self.project["asset"])

    def test_first_connected_image_run_does_not_require_optional_models(self):
        fake = types.SimpleNamespace(models_dir=str(self.root / "models"), folder_names_and_paths={},
            get_input_directory=lambda: str(self.root / "input"),
            get_user_directory=lambda: str(self.root / "user"), get_temp_directory=lambda: str(self.root / "temp"))
        image = torch.from_numpy(self.doc.art[None].astype(np.float32) / 255)
        with mock.patch.dict(sys.modules, {"folder_paths": fake}):
            result = PLUGIN.NODE_CLASS_MAPPINGS["StockingTextureStudio"]().render("{}", image)
        np.testing.assert_array_equal(result["result"][0].numpy(), image.numpy())
        self.assertTrue(result["ui"]["stocking_studio"][0]["project"]["depth_enabled"])
        self.assertEqual(len(result["ui"]["stocking_studio"][0]["source_hash"]), 64)

    def test_snapshot_cannot_create_a_project_it_cannot_reopen(self):
        with mock.patch.object(store, "MAX_PROJECT_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "24 MiB"):
                store.snapshot(self.doc, self.assets)

    def test_depth_cache_survives_save_and_is_not_reused_for_another_picture(self):
        s = self.studio()
        s.doc.disparity = np.tile(np.linspace(0, 1, s.doc.w, dtype=np.float32), (s.doc.h, 1))
        project = s.project_data()
        d = store.restore(project, self.assets)
        self.owned.append(d)
        np.testing.assert_array_equal(d.disparity, s.doc.disparity)
        different = store.restore(project, self.assets, np.zeros_like(d.art))
        self.owned.append(different)
        self.assertIsNone(different.disparity)

    def test_moire_depth_readiness_and_saved_project_roundtrip(self):
        old = json.loads(store.dumps(self.project))
        for key in ("moire_on", "moire", "moire_area"):
            old["look"].pop(key, None)
        s = self.studio(old)
        self.assertFalse(s.params()["moire_on"])
        s.wait_ready()
        s.doc.set_look(dict(s.params(), moire_on=True, moire=60, moire_area=35))
        self.assertFalse(s.render()[1]["moire_ready"])
        self.assertEqual(s.look_info()["depth"], "error")
        with self.assertRaisesRegex(ValueError, "摩尔纹效果需要深度"):
            s.outputs()
        y, x = np.mgrid[:s.doc.h, :s.doc.w]
        s.doc.disparity = np.exp(-((x - 64) / 42) ** 2 - ((y - 80) / 55) ** 2).astype(np.float32)
        for dark in (False, True):
            s.dark_adapt = dark
            saved = s.project_data()
            restored = self.studio(saved)
            restored.wait_ready()
            for style in look.STYLES:
                whole, info = s.render({"style": style})
                self.assertTrue(info["moire_ready"])
                self.assertFalse(np.array_equal(whole, s.render({"style": style, "moire_on": False})[0]))
                np.testing.assert_array_equal(whole, restored.render({"style": style})[0])
                np.testing.assert_array_equal(s.render({"style": style}, (24, 32, 80, 104))[0], whole[32:104, 24:80])
            for key in ("moire_on", "moire", "moire_area"):
                self.assertEqual(restored.params()[key], s.params()[key])

    def test_static_adapter_uses_scoped_routes_and_preserves_all_upstream_tools(self):
        base = "/stocking_texture/studio/" + "f" * 32
        page = assets_ui.page(base)
        self.assertIn('id="stocking-apply"', page)
        for control in ("moire-on", "moire", "moire-area"):
            self.assertIn('id="' + control + '"', page)
        for name in ("app.js", "look.js", "i18n.js", "style.css", "i18n/en.json"):
            text, _ = assets_ui.static_asset(name, base)
            self.assertGreater(len(text), 100)
            if name in ("app.js", "look.js"):
                self.assertNotIn("fetch('/api/", text)
        app_js, _ = assets_ui.static_asset("app.js", base)
        self.assertNotIn("/open/dialog", app_js)
        self.assertNotIn("/export/ask", app_js)
        self.assertIn("/segment/select", app_js)
        self.assertIn("/mirror", app_js)
        with self.assertRaises(ValueError): assets_ui.static_asset("../../engine.py", base)


class StudioHTTP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.doc = document()
        self.project = store.snapshot(self.doc, self.assets, depth_enabled=False, dark_adapt=False)
        self.webapp = web.Application(client_max_size=store.MAX_PROJECT_BYTES)
        users = types.SimpleNamespace(get_request_user_filepath=lambda request, file:
            str(self.root / "users" / request.headers.get("comfy-user", "default") / file))
        server = types.SimpleNamespace(user_manager=users)
        self.manager = api.StudioServer(server, self.assets, {"sam": self.root / "missing", "depth": self.root / "depth"})
        self.webapp.router.add_post(api.PREFIX, self.manager.create)
        self.webapp.router.add_get(api.PREFIX + "/{sid}/", self.manager.handle)
        self.webapp.router.add_route("*", api.PREFIX + "/{sid}/{tail:.*}", self.manager.handle)
        self.webapp.on_shutdown.append(self.manager.shutdown)
        self.client = TestClient(TestServer(self.webapp))
        await self.client.start_server()
        response = await self.client.post(api.PREFIX, json={"project": self.project})
        self.assertEqual(response.status, 200, await response.text())
        self.opened = await response.json()
        self.base = self.opened["url"].rstrip("/")
        st = await (await self.client.get(self.base + "/api/doc")).json()
        self.docbase = self.base + "/api/doc/" + st["id"]
        self.rid = st["regions"][0]["id"]

    async def asyncTearDown(self):
        await self.client.close()
        self.doc.close()
        self.temp.cleanup()

    async def call(self, method, path, data=None):
        response = await self.client.request(method, self.base + path, json=data)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def test_live_crop_full_preview_and_apply_workflow_data(self):
        s = self.manager.sessions[self.opened["session"]].studio
        await asyncio.to_thread(s.wait_ready)
        params = "?w=128&h=160&style=coil"
        response = await self.client.get(self.docbase + "/render/fit" + params)
        self.assertEqual(response.status, 200)
        full = cv2.imdecode(np.frombuffer(await response.read(), np.uint8), cv2.IMREAD_UNCHANGED)
        response = await self.client.get(self.docbase + "/render/crop?w=56&h=72&x0=24&y0=32&style=coil")
        self.assertEqual(response.status, 200)
        crop = cv2.imdecode(np.frombuffer(await response.read(), np.uint8), cv2.IMREAD_UNCHANGED)
        np.testing.assert_array_equal(crop, full[32:104, 24:80])
        self.assertEqual(json.loads(response.headers["X-Look"])["x0"], 24)
        applied = await self.call("POST", "/api/apply")
        restored = store.restore(applied["project"], self.assets)
        try: np.testing.assert_array_equal(restored.regions[0].mask, self.doc.regions[0].mask)
        finally: restored.close()

    async def test_chunked_json_reads_all_chunks_and_bounds_body(self):
        async def chunks():
            for chunk in (b'{"project":', store.dumps(self.project).encode()[:80], store.dumps(self.project).encode()[80:], b'}'):
                yield chunk
                await asyncio.sleep(.01)
        response = await self.client.post(api.PREFIX, data=chunks(), headers={"Content-Type": "application/json"})
        self.assertEqual(response.status, 200, await response.text())
        with mock.patch.object(store, "MAX_PROJECT_BYTES", 100):
            response = await self.client.post(api.PREFIX, data=b' ' * 101)
        self.assertEqual(response.status, 400)

    async def test_moire_http_preview_export_and_apply_preserve_parameters(self):
        s = self.manager.sessions[self.opened["session"]].studio
        await asyncio.to_thread(s.wait_ready)
        params = dict(s.params(), style="oily", moire_on=True, moire=60, moire_area=35)
        response = await self.client.post(self.docbase + "/export", json={"kind": "png", "params": params})
        self.assertEqual(response.status, 400)
        self.assertIn("摩尔纹效果需要深度", await response.text())
        y, x = np.mgrid[:s.doc.h, :s.doc.w]
        s.doc.disparity = np.exp(-((x - 64) / 42) ** 2 - ((y - 80) / 55) ** 2).astype(np.float32)
        response = await self.client.put(self.docbase + "/look", json=params)
        self.assertEqual(response.status, 200, await response.text())
        response = await self.client.get(self.docbase + "/render/fit?w=128&h=160")
        self.assertTrue(json.loads(response.headers["X-Look"])["moire_ready"])
        full = cv2.imdecode(np.frombuffer(await response.read(), np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(full, s.render()[0])
        response = await self.client.post(self.docbase + "/export", json={"kind": "png"})
        self.assertEqual(response.status, 200, await response.text())
        result = await response.json()
        data = await (await self.client.get(result["url"])).read()
        np.testing.assert_array_equal(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR), full)
        applied = await self.call("POST", "/api/apply")
        for key in ("moire_on", "moire", "moire_area"):
            self.assertEqual(applied["project"]["look"][key], params[key])
        restored = studio_module.Studio(self.assets, s.preferences, s.model_paths, applied["project"])
        try:
            np.testing.assert_array_equal(restored.outputs()[0], full[..., ::-1])
        finally:
            restored.close()

    async def test_apply_only_acknowledges_a_successful_parent_write(self):
        s = self.manager.sessions[self.opened["session"]].studio
        original = s.base_hash
        s.doc.rename_region(s.doc.regions[0].id, "新草稿")
        prepared = await self.call("POST", "/api/apply")
        self.assertEqual(s.base_hash, original)
        response = await self.client.post(self.base + "/api/apply/ack", json={"ticket": "stale"})
        self.assertEqual(response.status, 400)
        self.assertEqual(s.base_hash, original)
        await self.call("POST", "/api/apply/ack", {"ticket": prepared["ticket"]})
        self.assertNotEqual(s.base_hash, original)

    async def test_concurrent_creates_respect_session_limit_and_user_ownership(self):
        responses = await asyncio.gather(*[self.client.post(api.PREFIX, json={"project": self.project}) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in responses), [200, 200, 200, 400, 400])
        self.assertEqual(len(self.manager.sessions), 4)
        response = await self.client.get(self.base + "/api/doc", headers={"comfy-user": "other"})
        self.assertEqual(response.status, 403)

    async def test_edit_mask_sam_candidate_cycle_and_undo(self):
        s = self.manager.sessions[self.opened["session"]].studio
        candidates = []
        for radius in (10, 20, 30):
            y, x = np.ogrid[:160, :128]
            candidates.append((x - 64)**2 + (y - 80)**2 < radius**2)
        # This verifies candidate application; model quality is tested separately with actual weights.
        with mock.patch.object(studio_module.models, "segment", return_value=(candidates, [.9, .8, .7])):
            response = await self.client.post(self.docbase + f"/regions/{self.rid}/segment", json={"x": 64, "y": 80, "subtract": True})
        self.assertEqual(response.status, 200, await response.text())
        after_small = s.doc.region(self.rid).mask.copy()
        response = await self.client.post(self.docbase + "/segment/select", json={"k": 2})
        self.assertEqual(response.status, 200)
        self.assertLess(s.doc.region(self.rid).mask.sum(), after_small.sum())
        response = await self.client.post(self.docbase + "/undo", json={})
        self.assertEqual(response.status, 200)
        np.testing.assert_array_equal(s.doc.region(self.rid).mask, self.doc.regions[0].mask)

    async def test_psd_export_browser_download_and_reopen(self):
        response = await self.client.post(self.docbase + "/export", json={"kind": "guides", "path": "../must-not-write.psd"})
        self.assertEqual(response.status, 200, await response.text())
        result = await response.json()
        response = await self.client.get(result["url"])
        self.assertEqual(response.status, 200)
        data = await response.read()
        self.assertEqual(data[:4], b"8BPS")
        upload = FormData(); upload.add_field("file", data, filename="roundtrip.psd", content_type="application/octet-stream")
        response = await self.client.post(self.base + "/api/open/upload", data=upload)
        self.assertEqual(response.status, 200, await response.text())
        s = self.manager.sessions[self.opened["session"]].studio
        np.testing.assert_array_equal(s.doc.art, self.doc.art)
        np.testing.assert_array_equal(s.doc.regions[0].mask, self.doc.regions[0].mask)
        self.assertFalse((self.root / "must-not-write.psd").exists())

    async def test_sessions_and_presets_are_isolated_and_unsafe_routes_absent(self):
        await self.call("PUT", "/api/look/presets", {"name": "检查", "params": dict(look.DEFAULTS, style="coil")})
        response = await self.client.post(api.PREFIX, json={"project": self.project}, headers={"comfy-user": "second"})
        other = (await response.json())["url"].rstrip("/")
        response = await self.client.get(other + "/api/look/presets", headers={"comfy-user": "second"})
        self.assertEqual((await response.json())["presets"], [])
        for endpoint in ("/api/shutdown", "/api/open/path", "/api/open/dialog"):
            response = await self.client.post(self.base + endpoint, json={"path": "C:/Windows/win.ini"})
            self.assertEqual(response.status, 404)
        response = await self.client.post(self.base + "/api/apply", json={}, headers={"Origin": "https://elsewhere.invalid"})
        self.assertEqual(response.status, 403)


if __name__ == "__main__":
    unittest.main()
