"""Compatibility contracts for the pinned highlight/fade update.

Synthetic pixels and temporary user storage only. These checks exercise actual
shaders, workflow snapshots and HTTP validation; they are not a visual or GPU
acceptance claim.
"""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import numpy as np

import test_studio as fixtures
from test_nodes import ENGINE
from test_upstream_rendering import editor_renderer, layer, make_scene, params, rendering

api, store, look = fixtures.api, fixtures.store, fixtures.look


def highlight_scene():
    """A long, shaded limb with a smooth painted highlight and an edge notch.

    The ordinary rendering fixture is almost flat and produces no highlight;
    this input makes a missing particle pass observable without faking maps.
    """
    h, w = 224, 144
    yy, xx = np.mgrid[:h, :w]
    reg = np.zeros((h, w), np.int8)
    reg[10:-10, 26:118] = 1
    reg[105:115, 26:55] = 0
    light = 23 + 80 * np.exp(-((xx - 77) / 23) ** 2)
    rgb = np.stack((light + 8, light + 3, light), axis=-1).astype(np.uint8)
    return look.Scene(rgb, reg, yy * .64, xx * .81, reg > 0,
                      (reg > 0).astype(np.float32), ["左腿"])


class HighlightParameterContracts(unittest.TestCase):
    def test_string_flags_keep_upstream_boolean_meaning(self):
        for raw in ("0", "false", "no", "off", ""):
            with self.subTest(raw=raw):
                actual = store.clean_look(dict(fade=raw, particle_on=raw))
                self.assertIs(actual["fade"], False)
                self.assertIs(actual["particle_on"], False)
        for raw in ("1", "true", "yes", " TRUE "):
            with self.subTest(raw=raw):
                actual = store.clean_look(dict(fade=raw, particle_on=raw))
                self.assertIs(actual["fade"], True)
                self.assertIs(actual["particle_on"], True)

    def test_particle_amount_is_bounded_and_nonfinite_input_is_rejected(self):
        for raw, expected in ((-7, 0), ("35.5", 35.5), (130, 100)):
            self.assertEqual(store.clean_look({"particle": raw})["particle"], expected)
        for raw in (float("nan"), float("inf"), -float("inf"), "nan", "inf", "-Infinity"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                store.clean_look({"particle": raw})


class HighlightRenderingContracts(unittest.TestCase):
    def test_legacy_float_renderer_particles_respect_seed_and_leave_disabled_result_unchanged(self):
        original = highlight_scene()
        rgb8 = original.src[..., ::-1]
        rgb = rgb8.astype(np.float32) / 255
        data = ENGINE.parse_guides(json.dumps({"schema": 1, "width": original.w, "height": original.h,
            "regions": [{"id": "left", "name": "左腿", "polygons": [],
                         "strokes": [[[30, y], [70, y], [114, y]] for y in (45, 100, 165)]}],
            "dividers": []}), original.w, original.h)
        geometry = ENGINE.solve_geometry(rgb8, data, (original.REG > 0).astype(np.float32),
                                         False, None, False)
        self.assertEqual(geometry["messages"], [])
        for dark in (False, True):
            with self.subTest(dark=dark):
                p = params(layer("lines"), particle_on=True, particle=80)
                results = [ENGINE.render_texture(rgb, data, geometry, None, p, seed, dark)
                           for seed in (17, 17, 19)]
                np.testing.assert_array_equal(results[0][0], results[1][0])
                self.assertGreater(np.count_nonzero(results[0][0] != results[2][0]), 0)
                legacy = dict(p)
                for key in ("fade", "particle_on", "particle"):
                    legacy.pop(key)
                baseline = ENGINE.render_texture(rgb, data, geometry, None, legacy, 17, dark)[0]
                self.assertGreater(np.count_nonzero(results[0][0] != baseline), 0)
                for changes in ({"particle_on": False}, {"particle": 0}):
                    np.testing.assert_array_equal(
                        ENGINE.render_texture(rgb, data, geometry, None, dict(p, **changes), 17, dark)[0],
                        baseline)
                actual, texture, alpha = results[0][:3]
                np.testing.assert_array_equal(actual[original.REG == 0], rgb[original.REG == 0])
                np.testing.assert_allclose(rgb * (1 - alpha[..., None]) + texture * alpha[..., None],
                                           actual, rtol=0, atol=1e-7)

    def test_fade_switch_changes_real_pixels_in_all_styles_and_both_local_modes(self):
        for dark in (False, True):
            for style in look.STYLES:
                with self.subTest(dark=dark, style=style):
                    scene = make_scene()
                    p = params(layer(style), density=130, fade=True)
                    faded = rendering.render_scene(scene, p, dark)[0]
                    unfaded = rendering.render_scene(scene, dict(p, fade=False), dark)[0]
                    self.assertGreater(np.count_nonzero(faded != unfaded), 0)
                    np.testing.assert_array_equal(rendering.render_scene(scene, p, dark)[0], faded)
                    np.testing.assert_array_equal(unfaded[scene.R == 0], scene.src[scene.R == 0])
                    self.assertFalse(scene.check(dict(p, fade=False))[0].any())
                    if not dark:
                        for value, expected in ((True, faded), (False, unfaded)):
                            np.testing.assert_array_equal(
                                make_scene().render(dict(p, fade=value))[0], expected)

    def test_dark_adapter_keeps_bright_upstream_pixels_with_both_fade_settings(self):
        for style in ("knit", "loops", "lines"):
            for fade in (False, True):
                with self.subTest(style=style, fade=fade):
                    p = params(layer(style), density=130, fade=fade)
                    actual = rendering.render_scene(make_scene(bright=True), p, True)[0]
                    np.testing.assert_array_equal(actual, make_scene(bright=True).render(p)[0])

    def test_particles_toggle_back_to_exact_pixels_in_every_style(self):
        for dark in (False, True):
            for style in look.STYLES:
                with self.subTest(dark=dark, style=style):
                    scene = highlight_scene()
                    p = params(layer(style), particle_on=False, particle=73)
                    owner = editor_renderer(scene, p, dark)
                    baseline = owner.render()[0].copy()
                    owner.doc.look = dict(p, particle_on=True)
                    active = owner.render()[0]
                    self.assertGreater(np.count_nonzero(active != baseline), 0)
                    np.testing.assert_array_equal(active[scene.R == 0], scene.src[scene.R == 0])
                    owner.doc.look = dict(p, particle_on=True, particle=0)
                    np.testing.assert_array_equal(owner.render()[0], baseline)
                    owner.doc.look = p
                    np.testing.assert_array_equal(owner.render()[0], baseline)
                    if not dark:
                        np.testing.assert_array_equal(
                            highlight_scene().render(dict(p, particle_on=True))[0], active)

    def test_multilayer_particles_match_one_pass_over_the_completed_mix(self):
        items = [layer("knit", weight=12.5), layer("loops", weight=12.5),
                 layer("lines", weight=25), layer("grain", weight=50)]
        for dark in (False, True):
            with self.subTest(dark=dark):
                scene = highlight_scene()
                p = params(items[0], items[1:], particle_on=True, particle=83)
                mixed = rendering.render_scene(scene, dict(p, particle_on=False), dark)[0]
                _, core, band, tail, _, centre, _ = scene.oily_maps()
                field, gate = scene.particle_maps()
                arguments = (scene.src, core, band, tail, centre, field, gate, .83)
                once = look.apply_particles(mixed, *arguments)
                twice = look.apply_particles(once, *arguments)
                self.assertGreater(np.count_nonzero(once != mixed), 0)
                self.assertGreater(np.count_nonzero(once != twice), 0)  # oracle catches duplicate application
                actual = rendering.render_scene(scene, p, dark)[0]
                np.testing.assert_array_equal(actual, once)
                owner = editor_renderer(scene, p, dark)
                for rect in ((0, 0, 70, 75), (48, 65, 120, 155), (92, 160, 144, 224)):
                    x0, y0, x1, y1 = rect
                    expected = once[y0:y1, x0:x1]
                    np.testing.assert_array_equal(owner.render(rect=rect)[0], expected)
                    np.testing.assert_array_equal(
                        look.Scene.render(rendering._Renderer(scene, dark), p, rect)[0], expected)


class HighlightStorageContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.preferences = store.Preferences(self.root / "user")
        self.preferences.update(compute_device="cpu")
        self.original = fixtures.document()
        self.original.add_divider([60, 50, 68, 110])
        self.project = store.snapshot(self.original, self.assets, depth_enabled=False, dark_adapt=False)
        self.owned = []

    def tearDown(self):
        for item in reversed(self.owned):
            item.close()
        self.original.close()
        self.temp.cleanup()

    def studio(self, project=None):
        item = fixtures.studio_module.Studio(self.assets, self.preferences,
            {"sam": self.root / "missing-sam", "depth": self.root / "missing-depth"},
            self.project if project is None else project)
        self.owned.append(item)
        return item

    def test_old_schema2_look_defaults_without_changing_the_original_project(self):
        legacy = copy.deepcopy(self.project)
        for key in ("fade", "particle_on", "particle"):
            legacy["look"].pop(key, None)
        before = store.dumps(legacy)
        old_look = copy.deepcopy(legacy["look"])
        opened = self.studio(legacy)
        actual = opened.params()
        self.assertIs(actual["fade"], True)
        self.assertIs(actual["particle_on"], False)
        self.assertEqual(actual["particle"], 100)
        for key, value in old_look.items():
            self.assertEqual(actual[key], value)
        self.assertEqual(store.dumps(legacy), before)
        self.assertEqual(opened.project_data()["schema"], 2)

    def test_new_flags_and_multilayer_parameters_survive_save_reopen_and_look_undo(self):
        first = self.studio()
        baseline = first.params()
        changed = store.clean_look(dict(baseline, fade=False, particle_on=True, particle=64,
            layers=[layer("lines", weight=35)], weight=65))
        first.doc.set_look(changed)
        first.wait_ready()
        saved = json.loads(store.dumps(first.project_data()))
        self.assertEqual(saved["look"], changed)
        second = self.studio(saved)
        second.wait_ready()
        self.assertEqual(second.params(), changed)
        np.testing.assert_array_equal(first.render()[0], second.render()[0])
        first.doc.undo(page="look")
        self.assertEqual(first.params(), baseline)
        first.doc.redo(page="look")
        self.assertEqual(first.params(), changed)
        np.testing.assert_array_equal(first.render()[0], second.render()[0])

    def test_preset_export_import_preserves_new_switches_amount_and_layers(self):
        chosen = store.clean_look(dict(self.project["look"], fade=False, particle_on=True, particle=39,
            layers=[layer("grain", weight=25)], weight=75, strength_auto=False))
        self.preferences.save_preset("高光验收", chosen)
        filename, text = self.preferences.export_preset("高光验收")
        other = store.Preferences(self.root / "other-user")
        other.import_preset(text, filename)
        self.assertEqual(other.presets()[0]["params"], chosen)
        self.assertEqual(json.loads(text)["params"], chosen)

    def test_unreadable_saved_look_recovers_picture_and_guides_without_touching_input(self):
        for bad_look in ({"style": "future-style"}, {"particle": "broken"}, 7):
            with self.subTest(look=bad_look):
                broken = copy.deepcopy(self.project)
                broken["look"] = bad_look
                before = store.dumps(broken)
                image_path = store.asset_path(self.assets, broken["asset"], "png")
                image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
                opened = self.studio(broken)
                opened.wait_ready()
                recovered = opened.doc
                self.assertIsNone(recovered.look)
                self.assertIs(opened.params()["fade"], True)
                self.assertIs(opened.params()["particle_on"], False)
                saved = store.snapshot(recovered, self.assets, depth_enabled=False, dark_adapt=False)
                for key in ("asset", "image_sha256", "name", "width", "height", "regions", "strokes",
                            "dividers", "erased", "sparkle", "color_exclude", "guides_saved"):
                    self.assertEqual(saved[key], self.project[key], key)
                self.assertEqual(store.dumps(broken), before)
                self.assertEqual(hashlib.sha256(image_path.read_bytes()).hexdigest(), image_hash)
                with self.assertRaises((ValueError, TypeError)):
                    store.clean_look(bad_look)


class HighlightHTTPContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original = fixtures.document()
        assets = self.root / "assets"
        project = store.snapshot(self.original, assets, depth_enabled=False, dark_adapt=False)
        users = types.SimpleNamespace(get_request_user_filepath=lambda request, file:
            str(self.root / "user" / file))
        store.Preferences(self.root / "user" / "stocking_texture").update(compute_device="cpu")
        self.manager = api.StudioServer(types.SimpleNamespace(user_manager=users), assets,
            {"sam": self.root / "missing-sam", "depth": self.root / "missing-depth"}, retention_days=0)
        app = web.Application(client_max_size=store.MAX_PROJECT_BYTES)
        app.router.add_post(api.PREFIX, self.manager.create)
        app.router.add_get(api.PREFIX + "/{sid}/", self.manager.handle)
        app.router.add_route("*", api.PREFIX + "/{sid}/{tail:.*}", self.manager.handle)
        app.on_shutdown.append(self.manager.shutdown)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        response = await self.client.post(api.PREFIX, json={"project": project})
        self.assertEqual(response.status, 200, await response.text())
        opened = await response.json()
        self.base = opened["url"].rstrip("/")
        self.studio = self.manager.sessions[opened["session"]].studio
        await asyncio.to_thread(self.studio.wait_ready)
        self.docbase = self.base + "/api/doc/" + self.studio.doc.id

    async def asyncTearDown(self):
        await self.client.close()
        self.original.close()
        self.temp.cleanup()

    async def test_query_flags_and_put_keep_new_settings_while_invalid_edits_remain_atomic(self):
        query = urlencode({"fade": "false", "particle_on": "true", "particle": "42"})
        response = await self.client.get(self.docbase + "/look?" + query)
        self.assertEqual(response.status, 200, await response.text())
        queried = (await response.json())["params"]
        self.assertEqual((queried["fade"], queried["particle_on"], queried["particle"]), (False, True, 42))
        self.assertIs(self.studio.params()["fade"], True)  # a preview query is read-only
        response = await self.client.put(self.docbase + "/look", json=queried)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(self.studio.params(), queried)
        before = store.dumps(self.studio.project_data())
        for bad in ({"particle": "Infinity"}, {"density": "broken"}, {"style": "future-style"}):
            with self.subTest(bad=bad):
                response = await self.client.put(self.docbase + "/look", json=dict(queried, **bad))
                self.assertEqual(response.status, 400, await response.text())
                self.assertEqual(store.dumps(self.studio.project_data()), before)
                text = json.dumps({"format": "stocking-look-preset", "version": 1,
                                   "name": "bad", "params": dict(queried, **bad)})
                response = await self.client.post(self.base + "/api/look/presets/import",
                    json={"text": text, "filename": "bad.json"})
                self.assertEqual(response.status, 400, await response.text())
                self.assertEqual(store.dumps(self.studio.project_data()), before)
                self.assertEqual(self.studio.preferences.presets(), [])


if __name__ == "__main__":
    unittest.main()
