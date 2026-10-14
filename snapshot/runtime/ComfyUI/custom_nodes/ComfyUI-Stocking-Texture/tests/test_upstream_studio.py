"""Actual adapter/storage behavior for the pinned upstream editor update.

Synthetic image fixtures and temporary user storage only; no browser or GPU claim.
"""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from urllib.parse import unquote, urlencode

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
import numpy as np

import test_studio as fixtures

api, store, look = fixtures.api, fixtures.store, fixtures.look


def multilayer_look():
    return dict(look.DEFAULTS, style="grain", density=67,
        strength_auto=False, strength=43, sparkle_depth=0, sparkle_bright=0,
        sparkle_even=0, sparkle_link=False, weight=35, amount=21, lock_total=False,
        layers=[dict(style="lines", density=83, tilt=12, strength=57,
                     strength_auto=False, weight=65, amount=39)])


class UpstreamStudioStorage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.preferences = store.Preferences(self.root / "user")
        self.preferences.update(compute_device="cpu")
        self.original = fixtures.document()
        self.project = store.snapshot(self.original, self.assets,
                                      depth_enabled=False, dark_adapt=False)
        self.owned = []

    def tearDown(self):
        for studio in reversed(self.owned):
            studio.close()
        self.original.close()
        self.temp.cleanup()

    def studio(self, project=None, draft_id=None):
        item = fixtures.studio_module.Studio(self.assets, self.preferences,
            {"sam": self.root / "missing-sam", "depth": self.root / "missing-depth"},
            self.project if project is None else project, draft_id=draft_id)
        self.owned.append(item)
        return item

    def test_schema2_multilayer_snapshot_preserves_parameters_and_pixels(self):
        first = self.studio()
        first.doc.set_look(multilayer_look())
        first.wait_ready()
        saved = json.loads(store.dumps(first.project_data()))
        self.assertEqual(saved["schema"], 2)
        self.assertEqual(saved["look"], multilayer_look())
        second = self.studio(saved)
        second.wait_ready()
        self.assertEqual(second.params(), first.params())
        np.testing.assert_array_equal(second.doc.art, first.doc.art)
        np.testing.assert_array_equal(second.doc.regions[0].mask, first.doc.regions[0].mask)
        np.testing.assert_array_equal(second.render()[0], first.render()[0])

    def test_multilayer_draft_restores_without_changing_workflow_baseline(self):
        draft_id = "c" * 32
        first = self.studio(draft_id=draft_id)
        baseline = first.base_hash
        first.doc.set_look(multilayer_look())
        first.doc.rename_region(first.doc.regions[0].id, "draft region")
        first.save_draft()
        path = self.preferences.path.parent / "drafts" / (draft_id + ".json")
        self.assertEqual(json.loads(path.read_text("utf-8"))["project"]["look"], multilayer_look())
        second = self.studio(draft_id=draft_id)
        self.assertTrue(second.restore_draft())
        self.assertEqual(second.base_hash, baseline)
        self.assertEqual(second.params(), multilayer_look())
        self.assertEqual(second.doc.regions[0].name, "draft region")
        self.assertEqual(second.project["look"], self.project["look"])
        changed = copy.deepcopy(self.project)
        changed["look"]["density"] = 91
        third = self.studio(changed, draft_id)
        self.assertFalse(third.restore_draft())
        self.assertEqual(third.params()["density"], 91)


class UpstreamStudioHTTP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.original = fixtures.document()
        self.project = store.snapshot(self.original, self.assets,
                                      depth_enabled=False, dark_adapt=False)
        users = types.SimpleNamespace(get_request_user_filepath=lambda request, file:
            str(self.root / "users" / request.headers.get("comfy-user", "default") / file))
        self.manager = api.StudioServer(types.SimpleNamespace(user_manager=users), self.assets,
            {"sam": self.root / "missing-sam", "depth": self.root / "missing-depth"}, retention_days=0)
        for user in ("default", "second"):
            store.Preferences(self.root / "users" / user / "stocking_texture").update(compute_device="cpu")
        app = web.Application(client_max_size=store.MAX_PROJECT_BYTES)
        app.router.add_post(api.PREFIX, self.manager.create)
        app.router.add_get(api.PREFIX + "/{sid}/", self.manager.handle)
        app.router.add_route("*", api.PREFIX + "/{sid}/{tail:.*}", self.manager.handle)
        app.on_shutdown.append(self.manager.shutdown)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        response = await self.client.post(api.PREFIX, json={"project": self.project})
        self.assertEqual(response.status, 200, await response.text())
        self.opened = await response.json()
        self.base = self.opened["url"].rstrip("/")
        self.entry = self.manager.sessions[self.opened["session"]]
        self.studio = self.entry.studio
        await asyncio.to_thread(self.studio.wait_ready)
        self.update_docbase()

    async def asyncTearDown(self):
        await self.client.close()
        self.original.close()
        self.temp.cleanup()

    def update_docbase(self):
        self.docbase = self.base + "/api/doc/" + self.studio.doc.id
        self.rid = self.studio.doc.regions[0].id

    async def request(self, method, path, body=None, *, status=200, headers=None):
        response = await self.client.request(method, path, json=body, headers=headers)
        self.assertEqual(response.status, status, (await response.text())[:500])
        return await response.json()

    async def preset(self, name="test preset", params=None):
        return await self.request("PUT", self.base + "/api/look/presets",
            {"name": name, "params": multilayer_look() if params is None else params})

    def fingerprint(self):
        state = self.studio.doc.state()
        history = {name: state[name] for name in
                   ("can_undo", "can_redo", "can_undo_look", "can_redo_look", "look_rev")}
        return (store.dumps(self.studio.project_data()), self.studio.doc.edits,
                history, self.studio.preferences.path.read_bytes())

    def preset_text(self, **changes):
        data = {"format": "stocking-look-preset", "version": 1,
                "name": "imported preset", "params": multilayer_look()}
        data.update(changes)
        return json.dumps(data, ensure_ascii=False)

    async def test_page_histories_are_independent_and_slider_merge_is_one_step(self):
        original = self.studio.params()
        for density, merge in ((72, "false"), (89, "true")):
            await self.request("PUT", self.docbase + "/look?merge=" + merge,
                               dict(original, density=density))
        await self.request("PATCH", self.docbase + f"/regions/{self.rid}", {"name": "guides edit"})
        await self.request("POST", self.docbase + "/undo?page=look", {})
        self.assertEqual(self.studio.params()["density"], original["density"])
        self.assertEqual(self.studio.doc.regions[0].name, "guides edit")
        state = self.studio.doc.state()
        self.assertFalse(state["can_undo_look"])
        self.assertTrue(state["can_redo_look"])
        revision = state["look_rev"]
        await self.request("POST", self.docbase + "/undo", {})
        self.assertEqual(self.studio.doc.regions[0].name, self.original.regions[0].name)
        self.assertEqual(self.studio.params()["density"], original["density"])
        self.assertEqual(self.studio.doc.state()["look_rev"], revision)
        await self.request("POST", self.docbase + "/redo?page=look", {})
        self.assertEqual(self.studio.params()["density"], 89)
        self.assertEqual(self.studio.doc.regions[0].name, self.original.regions[0].name)
        await self.request("POST", self.docbase + "/redo?page=guides", {})
        self.assertEqual(self.studio.doc.regions[0].name, "guides edit")

    async def test_color_exclusion_uses_look_history_and_keeps_guide_edits(self):
        await self.request("PATCH", self.docbase + f"/regions/{self.rid}", {"name": "kept guide"})
        await self.request("PUT", self.docbase + "/coverage/exclude", {"on": True})
        self.assertTrue(self.studio.doc.color_exclude)
        await self.request("POST", self.docbase + "/undo?page=look", {})
        self.assertFalse(self.studio.doc.color_exclude)
        self.assertEqual(self.studio.doc.regions[0].name, "kept guide")
        await self.request("POST", self.docbase + "/redo?page=look", {})
        self.assertTrue(self.studio.doc.color_exclude)

    async def test_merged_return_to_initial_look_removes_the_history_step(self):
        original = self.studio.params()
        await self.request("PUT", self.docbase + "/look?merge=off", dict(original, density=79))
        await self.request("PUT", self.docbase + "/look?merge=yes", original)
        state = self.studio.doc.state()
        self.assertEqual(self.studio.params(), original)
        self.assertFalse(state["can_undo_look"])
        self.assertFalse(state["can_redo_look"])

    async def test_invalid_page_and_merge_queries_cannot_modify_document_or_storage(self):
        await self.request("PUT", self.docbase + "/look", dict(self.studio.params(), density=77))
        await self.request("PATCH", self.docbase + f"/regions/{self.rid}", {"name": "protected"})
        await asyncio.to_thread(self.studio.wait_ready)
        before = self.fingerprint()
        cases = [("POST", "/undo?page=unknown", {}), ("POST", "/redo?page=unknown", {}),
                 ("POST", "/undo?page=", {}), ("POST", "/redo?page=LOOK", {})]
        cases += [("PUT", "/look?merge=" + value, dict(self.studio.params(), density=93))
                  for value in ("", "garbage", "2", "True", "null")]
        for method, path, body in cases:
            with self.subTest(path=path):
                await self.request(method, self.docbase + path, body, status=400)
                self.assertEqual(self.fingerprint(), before)

    async def test_look_query_layers_compatibility_and_nonfinite_values_are_read_only(self):
        before = self.fingerprint()
        for layers in ("", " \t\r\n ", "[]", "null"):
            with self.subTest(layers=layers):
                result = await self.request("GET", self.docbase + "/look?" + urlencode({"layers": layers}))
                self.assertEqual(result["params"]["layers"], [])
                self.assertEqual(result["params"]["density"], self.project["look"]["density"])
                self.assertEqual(self.fingerprint(), before)
        queries = [{"density": "Infinity"}]
        for value in (float("inf"), "inf"):
            layer = dict(multilayer_look()["layers"][0], density=value)
            queries.append({"layers": json.dumps([layer])})
        for query in queries:
            with self.subTest(query=query):
                await self.request("GET", self.docbase + "/look?" + urlencode(query), status=400)
                self.assertEqual(self.fingerprint(), before)

    async def test_auto100_affects_new_images_and_preserves_saved_looks(self):
        self.assertTrue(self.studio.params()["lock_total"])
        await self.request("PUT", self.base + "/api/look/blend-auto", {"on": False})
        self.assertTrue(self.studio.params()["lock_total"])

        async def open_new():
            form = FormData()
            form.add_field("file", self.original.art_png(), filename="new-image.png", content_type="image/png")
            response = await self.client.post(self.base + "/api/open/upload", data=form)
            self.assertEqual(response.status, 200, await response.text())
            self.update_docbase()
            self.assertIsNone(self.studio.doc.look)
            return await self.request("GET", self.docbase + "/look")

        self.assertFalse((await open_new())["params"]["lock_total"])
        initial_new_look = self.studio.params()
        saved = dict(initial_new_look, density=81, lock_total=False)
        await self.request("PUT", self.docbase + "/look", saved)
        await self.request("POST", self.docbase + "/undo?page=look", {})
        self.assertEqual(self.studio.params(), initial_new_look)
        await self.request("POST", self.docbase + "/redo?page=look", {})
        self.assertEqual(self.studio.params(), saved)
        await self.request("PUT", self.base + "/api/look/blend-auto", {"on": True})
        self.assertFalse((await self.request("GET", self.docbase + "/look"))["params"]["lock_total"])
        self.assertTrue((await open_new())["params"]["lock_total"])
        self.assertTrue(self.studio.preferences.read()["blend_auto"])

    async def test_invalid_auto100_value_keeps_preferences_and_document(self):
        before = self.fingerprint()
        for value in (None, 0, 1, "false", []):
            with self.subTest(value=value):
                await self.request("PUT", self.base + "/api/look/blend-auto", {"on": value}, status=400)
                self.assertEqual(self.fingerprint(), before)

    async def test_preset_export_and_duplicate_import_preserve_original_and_layers(self):
        name = "preset/示例"
        await self.preset(name)
        exported = await self.request("POST", self.base + "/api/look/presets/export", {"name": name})
        self.assertEqual(exported["file"], "preset_示例.json")
        self.assertTrue(exported["url"].startswith(self.base + "/api/download/"))
        response = await self.client.get(exported["url"])
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "application/json")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn(exported["file"], unquote(response.headers["Content-Disposition"]))
        data = json.loads(await response.read())
        self.assertEqual((data["format"], data["version"], data["name"]), ("stocking-look-preset", 1, name))
        self.assertEqual(data["params"], multilayer_look())
        data["params"]["density"] = 99
        result = await self.request("POST", self.base + "/api/look/presets/import",
            {"text": "\ufeff" + json.dumps(data, ensure_ascii=False), "filename": exported["file"]})
        self.assertTrue(result["renamed"])
        self.assertEqual(result["imported"], name + " (2)")
        records = {p["name"]: p["params"] for p in result["presets"]}
        self.assertEqual(records[name], multilayer_look())
        self.assertEqual(records[name + " (2)"]["density"], 99)
        self.assertEqual(records[name + " (2)"]["layers"], multilayer_look()["layers"])

    async def test_preset_file_name_fallback_does_not_write_a_client_path(self):
        result = await self.request("POST", self.base + "/api/look/presets/import",
            {"text": self.preset_text(name=""), "filename": "C:\\client\\client-name.json"})
        self.assertEqual(result["imported"], "client-name")
        self.assertFalse(result["renamed"])
        self.assertEqual(list(self.studio.preferences.path.parent.glob("*.json")), [self.studio.preferences.path])

    async def test_malformed_preset_files_are_atomic(self):
        await self.preset()
        before = self.fingerprint()
        cases = ["{", "[]", self.preset_text(format="not-a-preset"), self.preset_text(params=[])]
        for text in cases:
            with self.subTest(text=text[:80]):
                await self.request("POST", self.base + "/api/look/presets/import",
                    {"text": text, "filename": "bad.json"}, status=400)
                self.assertEqual(self.fingerprint(), before)

    async def test_preset_byte_limit_accepts_boundary_and_rejects_oversize(self):
        text = self.preset_text()
        boundary = text + " " * (256 * 1024 - len(text.encode("utf-8")))
        result = await self.request("POST", self.base + "/api/look/presets/import",
            {"text": boundary, "filename": "boundary.json"})
        self.assertEqual(result["imported"], "imported preset")
        before = self.fingerprint()
        for oversized in (boundary + " ", "汉" * (256 * 1024 // 3 + 1)):
            with self.subTest(byte_count=len(oversized.encode("utf-8"))):
                await self.request("POST", self.base + "/api/look/presets/import",
                    {"text": oversized, "filename": "large.json"}, status=400)
                self.assertEqual(self.fingerprint(), before)

    async def test_invalid_preset_versions_are_atomic(self):
        await self.preset()
        before = self.fingerprint()
        for version in (0, -1, True, "1", 99999):
            with self.subTest(version=version):
                await self.request("POST", self.base + "/api/look/presets/import",
                    {"text": self.preset_text(version=version), "filename": "version.json"}, status=400)
                self.assertEqual(self.fingerprint(), before)

    async def test_nonfinite_preset_numbers_including_nested_layers_are_atomic(self):
        await self.preset()
        before = self.fingerprint()
        for number in (float("nan"), float("inf"), -float("inf")):
            for nested in (False, True):
                with self.subTest(number=number, nested=nested):
                    params = multilayer_look()
                    target = params["layers"][0] if nested else params
                    target["density"] = number
                    await self.request("POST", self.base + "/api/look/presets/import",
                        {"text": self.preset_text(params=params), "filename": "number.json"}, status=400)
                    self.assertEqual(self.fingerprint(), before)

    async def test_preset_users_and_session_downloads_are_isolated(self):
        await self.preset("shared name")
        exported = await self.request("POST", self.base + "/api/look/presets/export", {"name": "shared name"})
        headers = {"comfy-user": "second"}
        opened = await self.request("POST", api.PREFIX, {"project": self.project}, headers=headers)
        other = opened["url"].rstrip("/")
        listed = await self.request("GET", other + "/api/look/presets", headers=headers)
        self.assertEqual(listed["presets"], [])
        result = await self.request("POST", other + "/api/look/presets/import",
            {"text": self.preset_text(name="shared name"), "filename": "shared.json"}, headers=headers)
        self.assertFalse(result["renamed"])
        self.assertEqual(len(self.studio.preferences.presets()), 1)
        response = await self.client.get(exported["url"], headers=headers)
        self.assertEqual(response.status, 403)
        foreign = other + "/api/download/" + exported["url"].rsplit("/", 1)[1]
        response = await self.client.get(foreign, headers=headers)
        self.assertEqual(response.status, 404)
        before = self.fingerprint()
        response = await self.client.post(self.base + "/api/look/presets/import",
            json={"text": self.preset_text(), "filename": "foreign.json"},
            headers={"Origin": "https://elsewhere.invalid"})
        self.assertEqual(response.status, 403)
        self.assertEqual(self.fingerprint(), before)

    async def test_preset_download_cache_keeps_only_sixteen_and_writes_no_export_files(self):
        await self.preset()
        before_preferences = self.studio.preferences.path.read_bytes()
        before_files = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_file())
        downloads = [await self.request("POST", self.base + "/api/look/presets/export", {"name": "test preset"})
                     for _ in range(17)]
        self.assertEqual(len({item["url"] for item in downloads}), 17)
        self.assertEqual(len(self.entry.preset_downloads), 16)
        response = await self.client.get(downloads[0]["url"])
        self.assertEqual(response.status, 404)
        for item in downloads[1:]:
            response = await self.client.get(item["url"])
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["params"], multilayer_look())
        self.assertEqual(self.entry.downloads, {})
        self.assertFalse((self.studio.preferences.path.parent / "exports").exists())
        self.assertEqual(self.studio.preferences.path.read_bytes(), before_preferences)
        after_files = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_file())
        self.assertEqual(after_files, before_files)


if __name__ == "__main__":
    unittest.main()
