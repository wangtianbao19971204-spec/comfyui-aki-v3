"""CPU contract tests on synthetic fabric regions; no private pictures or models."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stocking_plugin_tests", ROOT / "__init__.py",
                                            submodule_search_locations=[str(ROOT)])
PLUGIN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PLUGIN
SPEC.loader.exec_module(PLUGIN)
NODES = sys.modules[SPEC.name + ".nodes"]
ENGINE = sys.modules[SPEC.name + ".engine"]


def fixture():
    h, w = 160, 128
    yy, xx = np.mgrid[:h, :w]
    rgb = np.stack((0.30 + xx / 1600, 0.27 + yy / 2000, 0.25 + xx / 2100), axis=2).astype(np.float32)
    image = torch.from_numpy(rgb[None].copy())
    mask = torch.zeros((1, h, w)); mask[:, 10:150, 15:113] = 1
    data = {"schema": 1, "width": w, "height": h, "regions": [
        {"id": "left", "name": "左腿", "polygons": [],
         "strokes": [[[20, 45], [50, 35], [80, 35], [106, 45]],
                     [[20, 115], [50, 105], [80, 105], [106, 115]]]}], "dividers": []}
    return image, mask, data


class TextureContracts(unittest.TestCase):
    def setUp(self):
        self.image, self.mask, self.data = fixture()
        self.text = json.dumps(self.data)

    def run_render(self, node=None, **kwargs):
        settings = dict(image=self.image, guides_json=self.text, mask=self.mask,
                        color_exclude=False, auto_strength=False, sparkle_bright=0)
        settings.update(kwargs)
        return (node or NODES.StockingTextureRender()).render(**settings)

    def test_all_styles_are_local_and_preserve_float_pixels_outside_mask(self):
        for style in ENGINE.STYLES:
            with self.subTest(style=style):
                out, layer, alpha, check, report = self.run_render(style=style)
                self.assertEqual(out.shape, self.image.shape)
                self.assertEqual(check.shape, self.image.shape)
                self.assertTrue(torch.isfinite(out).all())
                self.assertTrue(torch.equal(out[self.mask == 0], self.image[self.mask == 0]))
                self.assertTrue(torch.equal(alpha[self.mask == 0], torch.zeros_like(alpha[self.mask == 0])))
                self.assertGreater(json.loads(report)["images"][0]["changed_pixels"], 0)
                self.assertTrue(torch.equal(layer[..., 3], alpha))
                composite = self.image * (1 - alpha[..., None]) + layer[..., :3] * alpha[..., None]
                torch.testing.assert_close(composite, out, rtol=0, atol=1e-7)

    def test_empty_mask_no_guides_and_zero_strength_are_exact_passthrough(self):
        for kwargs in ({"mask": self.mask * 0}, {"guides_json": ENGINE.EMPTY_GUIDES}, {"strength": 0}):
            settings = dict(image=self.image, guides_json=self.text, mask=self.mask,
                            color_exclude=False, auto_strength=False, sparkle_bright=0)
            settings.update(kwargs)
            out = NODES.StockingTextureRender().render(**settings)[0]
            self.assertTrue(torch.equal(out, self.image))

    def test_fixed_seed_and_cache_are_deterministic_but_new_seed_changes_grain(self):
        node = NODES.StockingTextureRender()
        first = self.run_render(node, style="加濑风", seed=123)[0]
        with mock.patch.object(NODES, "solve_geometry", side_effect=AssertionError("unneeded solve")):
            again = self.run_render(node, style="加濑风", seed=123)[0]
            other = self.run_render(node, style="加濑风", seed=124)[0]
        self.assertTrue(torch.equal(first, again))
        self.assertFalse(torch.equal(first, other))
        with mock.patch.object(NODES, "solve_geometry", wraps=NODES.solve_geometry) as solve:
            self.image[0, 50, 50] *= 0.8
            self.run_render(node, style="加濑风")
            self.assertEqual(solve.call_count, 1)

    def test_batch_broadcasts_mask_and_preserves_rgba_alpha(self):
        rgba = torch.cat((self.image, torch.full_like(self.image[..., :1], 0.73)), dim=3)
        batch = torch.cat((rgba, rgba), dim=0)
        out, layer, alpha, _, report = NODES.StockingTextureRender().render(
            batch, self.text, mask=self.mask, color_exclude=False)
        self.assertEqual(layer.shape[-1], 4)
        self.assertEqual(alpha.shape[0], 2)
        self.assertTrue(torch.equal(out[..., 3], batch[..., 3]))
        self.assertTrue(torch.equal(out[0], out[1]))
        self.assertEqual(len(json.loads(report)["images"]), 2)

    def test_multi_region_ownership_and_unguided_region(self):
        self.data["regions"][0]["polygons"] = [[[15, 10], [90, 10], [90, 149], [15, 149]]]
        self.data["regions"].append({"id": "right", "name": "右腿", "polygons": [
            [[70, 10], [112, 10], [112, 149], [70, 149]]], "strokes": []})
        data = ENGINE.parse_guides(json.dumps(self.data), 128, 160)
        geom = ENGINE.solve_geometry(np.round(self.image[0].numpy() * 255).astype(np.uint8),
                                     data, self.mask[0].numpy(), False, None, False)
        self.assertEqual(geom["all_labels"][80, 80], 2)
        self.assertEqual(geom["labels"][80, 80], 0)
        self.assertTrue(any("右腿" in item for item in geom["messages"]))

    def test_soft_mask_layer_composites_and_node_instances_do_not_share_state(self):
        soft = self.mask * 0.4
        settings = dict(image=self.image, guides_json=self.text, mask=soft,
                        color_exclude=False, auto_strength=False, style="细线")
        node = NODES.StockingTextureRender()
        out, layer, alpha, _, _ = node.render(**settings)
        torch.testing.assert_close(self.image * (1 - alpha[..., None]) + layer[..., :3] * alpha[..., None], out,
                                   rtol=0, atol=1e-7)
        other = NODES.StockingTextureRender()
        other.render(self.image, ENGINE.EMPTY_GUIDES)
        self.assertTrue(torch.equal(out, node.render(**settings)[0]))

    def test_depth_is_optional_and_its_direction_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "需要接入深度"):
            self.run_render(sparkle_depth=100)
        depth = torch.linspace(0, 1, 128)[None, None, :, None].expand(1, 160, 128, 3)
        light = NODES.depth_array(depth, 1, 160, 128, "近处较亮")
        dark = NODES.depth_array(1 - depth, 1, 160, 128, "近处较暗")
        np.testing.assert_allclose(light, dark, atol=1e-7)
        result = self.run_render(depth=depth, auto_walls=True, sparkle_depth=30)
        self.assertTrue(json.loads(result[-1])["images"][0]["sparkles_ready"])

    def test_soft_mask_scales_sparkles_instead_of_turning_them_off(self):
        settings = dict(image=self.image, guides_json=self.text, color_exclude=False,
                        auto_strength=False, strength=0, sparkle_even=300, seed=123)
        full = NODES.StockingTextureRender().render(mask=self.mask, **settings)[0]
        soft = NODES.StockingTextureRender().render(mask=self.mask * 0.4, **settings)[0]
        self.assertTrue(torch.any(soft != self.image))
        torch.testing.assert_close(soft - self.image, (full - self.image) * 0.4, rtol=0, atol=6e-8)

    def test_wall_that_removes_all_guide_anchors_is_a_reported_passthrough(self):
        data = {"schema": 1, "width": 64, "height": 64, "regions": [
            {"id": "thin", "name": "窄部位", "polygons": [], "strokes": [[[31, 10], [31, 53]]]}],
            "dividers": [[[31, 8], [31, 55]]]}
        image = torch.full((1, 64, 64, 3), 0.4)
        mask = torch.zeros((1, 64, 64)); mask[:, 8:56, 30:38] = 1
        out, _, _, _, report = NODES.StockingTextureRender().render(
            image, json.dumps(data), mask=mask, color_exclude=False, auto_strength=False)
        self.assertTrue(torch.equal(out, image))
        self.assertTrue(any("走向约束" in item for item in json.loads(report)["images"][0]["messages"]))

    def test_manual_wall_reaches_solver(self):
        self.data["dividers"] = [[[64, 55], [64, 90]]]
        from stocking_plugin_tests.vendor import guide_fields
        with mock.patch.object(guide_fields, "solve_region", wraps=guide_fields.solve_region) as solve:
            NODES.StockingTextureRender().render(self.image, json.dumps(self.data), mask=self.mask)
            self.assertTrue(solve.call_args.kwargs["walls"].any())

    def test_editor_outputs_can_drive_render_and_preview_only_writes_temp(self):
        with tempfile.TemporaryDirectory(prefix="stocking-node-test-") as folder:
            paths = types.SimpleNamespace(get_temp_directory=lambda: folder)
            with mock.patch.dict(sys.modules, {"folder_paths": paths}):
                prepared = NODES.StockingTextureGuides().prepare(self.image, self.text, self.mask)
            self.assertIs(prepared["result"][0], self.image)
            self.assertEqual(len(list(Path(folder).glob("*.png"))), 2)
            meta = prepared["ui"]["stocking"][0]
            self.assertEqual((meta["width"], meta["height"]), (128, 160))
            rendered = NODES.StockingTextureRender().render(*prepared["result"][::2],
                                                          mask=prepared["result"][1])
            self.assertGreater(json.loads(rendered[-1])["images"][0]["changed_pixels"], 0)

    def test_rejects_drift_nonfinite_oversized_and_bad_contracts(self):
        cases = []
        bad = json.loads(self.text); bad["width"] = 64; cases.append(bad)
        bad = json.loads(self.text); bad["regions"][0]["strokes"][0][0] = [float("nan"), 1]; cases.append(bad)
        bad = json.loads(self.text); bad["regions"].append(bad["regions"][0]); cases.append(bad)
        for data in cases:
            with self.assertRaises(ValueError):
                ENGINE.parse_guides(json.dumps(data), 128, 160)
        with self.assertRaises(ValueError):
            ENGINE.parse_guides("x" * (4 * 1024 * 1024 + 1), 128, 160)
        with self.assertRaises(ValueError):
            self.run_render(mask=torch.zeros(1, 8, 8))
        with self.assertRaises(ValueError):
            self.run_render(density=float("nan"))
        image = self.image.clone(); image[0, 0, 0, 0] = float("inf")
        with self.assertRaises(ValueError):
            NODES.StockingTextureRender().render(image, self.text)

    def test_vendored_files_match_the_reviewed_upstream_commit(self):
        upstream = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))
        for item in upstream["files"]:
            self.assertEqual(hashlib.sha256((ROOT / "vendor" / item["file"]).read_bytes()).hexdigest(), item["sha256"])

    def test_near_black_weave_survives_8bit_without_sparkles(self):
        image = torch.full_like(self.image, 19 / 255)
        for style in ENGINE.STYLES[:3]:
            with self.subTest(style=style):
                before = self.run_render(image=image, style=style, dark_adapt=False, auto_strength=True)
                after = self.run_render(image=image, style=style, dark_adapt=True, auto_strength=True)
                a, b = [json.loads(x[-1])["images"][0] for x in (before, after)]
                self.assertEqual(a["changed_pixels_8bit"], 0)
                self.assertGreater(b["changed_pixels_8bit"], b["active_pixels"] * 0.1)
                self.assertLessEqual(b["max_delta_8bit"], 4.01)
                self.assertTrue(torch.equal(after[0][self.mask == 0], image[self.mask == 0]))
                layer, alpha = after[1:3]
                torch.testing.assert_close(image * (1 - alpha[..., None]) + layer[..., :3] * alpha[..., None],
                                           after[0], rtol=0, atol=1e-7)

    def test_shadow_adaptation_preserves_lit_colors_and_nonweave_styles(self):
        for color in ((100, 110, 120), (223, 216, 226), (0, 0, 0)):
            image = torch.tensor(color, dtype=torch.float32).div(255).expand_as(self.image).clone()
            for style in ENGINE.STYLES:
                a = self.run_render(image=image, style=style, dark_adapt=False, sparkle_bright=100)[0]
                b = self.run_render(image=image, style=style, dark_adapt=True, sparkle_bright=100)[0]
                self.assertTrue(torch.equal(a, b), (color, style))
        for style in ENGINE.STYLES[3:]:
            self.assertTrue(torch.equal(self.run_render(style=style, dark_adapt=False)[0],
                                        self.run_render(style=style, dark_adapt=True)[0]))

    def test_compatibility_mode_matches_upstream_scene_on_active_pixels(self):
        from stocking_plugin_tests.vendor import look
        image = torch.round(self.image * 255) / 255
        rgb8 = np.round(image[0].numpy() * 255).astype(np.uint8)
        data = ENGINE.parse_guides(self.text, 128, 160)
        g = ENGINE.solve_geometry(rgb8, data, self.mask[0].numpy(), False, None, False)
        scene = look.Scene(rgb8, g["labels"], g["v"], g["across"], g["stock"], g["alpha"], ["左腿"], cut=g["cut"])
        active = (g["labels"] > 0) & g["stock"] & (g["alpha"] > 0)
        for style in ENGINE.STYLES:
            for bright in (0, 100):
                q = dict(style=ENGINE.STYLE_IDS[style], strength_auto=False, sparkle_link=False,
                         sparkle_bright=bright, sparkle_depth=0)
                original = scene.render(q)[0][..., ::-1]
                adapted = self.run_render(image=image, style=style, dark_adapt=False,
                                          sparkle_bright=bright, seed=look.SEED)[0][0].numpy()
                np.testing.assert_array_equal(np.round(adapted * 255).astype(np.uint8)[active], original[active])
                # SaveImage truncates, rather than rounding. The public PNG must
                # match too: adding two float deltas used to lose one level.
                np.testing.assert_array_equal(np.clip(adapted * 255, 0, 255).astype(np.uint8)[active],
                                              original[active])

    def test_manual_strength_report_and_invisible_output_warning(self):
        image = torch.full_like(self.image, 19 / 255)
        out = self.run_render(image=image, dark_adapt=False, strength=250, auto_strength=True)
        report = json.loads(out[-1])["images"][0]
        self.assertEqual(report["effective_strength"], 100)
        self.assertEqual(report["changed_pixels_8bit"], 0)
        self.assertTrue(any("手动值未采用" in x for x in report["messages"]))
        self.assertTrue(any("没有可见变化" in x for x in report["messages"]))
        manual = self.run_render(image=image, strength=250)
        self.assertEqual(json.loads(manual[-1])["images"][0]["effective_strength"], 250)

    def test_png_save_truncation_preserves_upstream_levels_across_brightness(self):
        from stocking_plugin_tests.vendor import look
        ramp = np.round(np.linspace(0, 255, 128)).astype(np.uint8)
        rgb8 = np.broadcast_to(ramp[None, :, None], (160, 128, 3)).copy()
        image = torch.from_numpy(rgb8.astype(np.float32)[None] / 255)
        data = ENGINE.parse_guides(self.text, 128, 160)
        g = ENGINE.solve_geometry(rgb8, data, self.mask[0].numpy(), False, None, False)
        scene = look.Scene(rgb8, g["labels"], g["v"], g["across"], g["stock"], g["alpha"], ["左腿"], cut=g["cut"])
        active = (g["labels"] > 0) & g["stock"] & (g["alpha"] > 0)
        for style in ENGINE.STYLES:
            q = dict(style=ENGINE.STYLE_IDS[style], density=65, strength=160, strength_auto=False,
                     sparkle_link=False, sparkle_depth=0, sparkle_bright=100)
            original = scene.render(q)[0][..., ::-1]
            out = self.run_render(image=image, style=style, density=65, strength=160,
                                  dark_adapt=False, sparkle_bright=100, seed=look.SEED)[0][0].numpy()
            saved = np.clip(out * 255, 0, 255).astype(np.uint8)
            np.testing.assert_array_equal(saved[active], original[active], err_msg=style)

    def test_shadow_adaptation_keeps_frequency_suppression(self):
        from stocking_plugin_tests.vendor import look
        from stocking_plugin_tests.rendering import render_scene
        yy, xx = np.mgrid[:160, :128].astype(np.float32)
        rgb8 = np.full((160, 128, 3), 19, np.uint8)
        reg = np.ones((160, 128), np.int8)
        for freq in (1.0, 1.6):
            scene = look.Scene(rgb8, reg, yy * freq, xx, reg > 0, reg.astype(np.float32), ["左腿"])
            for style in ("knit", "loops", "lines"):
                out, _ = render_scene(scene, dict(style=style, tilt=0, sparkle_link=False,
                                                  sparkle_bright=0, sparkle_depth=0), True)
                changed = np.any(out[20:-20, 20:-20] != 19, axis=2).sum()
                self.assertGreater(changed, 0) if freq == 1.0 else self.assertEqual(changed, 0)

    def test_new_defaults_and_explicit_saved_sparkle_off(self):
        spec = NODES.StockingTextureRender.INPUT_TYPES()
        self.assertEqual(spec["required"]["sparkle_bright"][1]["default"], 100)
        self.assertEqual(spec["required"]["sparkle_depth"][1]["default"], 0)
        self.assertTrue(spec["optional"]["dark_adapt"][1]["default"])
        default = NODES.StockingTextureRender().render(self.image, self.text, mask=self.mask)[0]
        explicit = NODES.StockingTextureRender().render(self.image, self.text, mask=self.mask, sparkle_bright=100)[0]
        off = NODES.StockingTextureRender().render(self.image, self.text, mask=self.mask, sparkle_bright=0)[0]
        self.assertTrue(torch.equal(default, explicit))
        self.assertFalse(torch.equal(off, default))


if __name__ == "__main__":
    unittest.main()
