"""Pinned multilayer rendering contracts on synthetic fields; no models or services.

Mixtures are checked against independently rendered single layers and explicit
weights, not against the adapter's layer selection or blend helper. Raw upstream
oracles use a fresh Scene for each parameter set because this pin's full-image
cache omits the first layer's amount.
"""
import copy
import importlib
import threading
import types
import unittest
from unittest import mock

import numpy as np

from test_nodes import PLUGIN

rendering = importlib.import_module(PLUGIN.__name__ + ".rendering")
look = importlib.import_module(PLUGIN.__name__ + ".vendor.look")
knit = importlib.import_module(PLUGIN.__name__ + ".vendor.knit")
studio = importlib.import_module(PLUGIN.__name__ + ".studio")


def make_scene(*, bright=False, depth=True, scene_type=look.Scene):
    h, w = 144, 176
    yy, xx = np.mgrid[:h, :w]
    base = 145 if bright else 22
    rgb = np.stack((base + xx / 18 + yy / 45,
                    base + 3 + yy / 20,
                    base + 5 + xx / 30), axis=-1).astype(np.uint8)
    reg = np.zeros((h, w), np.int8)
    reg[9:-9, 11:-11] = 1
    reg[55:67, 76:92] = 0                 # an occluder must stay outside coverage
    v = yy * .64 + xx * .07 + .7 * np.sin(xx / 23)
    across = xx * .81 + yy * .04
    disparity = np.exp(-((xx - w / 2) / 47) ** 2 - ((yy - h / 2) / 39) ** 2).astype(np.float32)
    return scene_type(rgb, reg, v, across, reg > 0, (reg > 0).astype(np.float32), ["左腿"],
                      disparity=(lambda: disparity) if depth else None)


def layer(style, *, weight=50, amount=None, strength=180, tilt=29, auto=False):
    return dict(style=style, density=65, tilt=tilt, strength=strength,
                strength_auto=auto, weight=weight, amount=amount)


def params(first=None, extras=(), *, locked=True, **effects):
    p = dict(sparkle_depth=0, sparkle_bright=0, sparkle_painted=0,
             sparkle_even=0, sparkle_link=False, moire_on=False,
             lock_total=locked, layers=copy.deepcopy(list(extras)))
    p.update(first or layer("knit"))
    p.update(effects)
    return look.clean_params(p)


def single_layer(scene, item, dark):
    return rendering.render_scene(scene, params(item), dark)[0]


def expected_mix(scene, items, shares, dark, *, unlocked=False):
    # Binary-exact shares keep the oracle independent of accumulation precision.
    images = [single_layer(scene, item, dark).astype(np.float64) for item in items]
    result = sum(image * share for image, share in zip(images, shares))
    if unlocked:
        result += scene.src.astype(np.float64) * (1 - sum(shares))
    return np.clip(np.round(result), 0, 255).astype(np.uint8)


def editor_renderer(scene, p, dark):
    """Exercise Studio's real render/cache/crop without opening a document worker."""
    owner = object.__new__(studio.Studio)
    owner.doc = types.SimpleNamespace(look=copy.deepcopy(p))
    owner.preferences = types.SimpleNamespace(read=lambda: {})
    owner.lock = threading.RLock()
    owner.dark_adapt = dark
    owner._scene = (("synthetic",), scene)
    owner._adapted = (None, None)
    owner.scene = lambda: scene
    return owner


class UpstreamRenderingContracts(unittest.TestCase):
    def test_compatibility_mode_matches_fresh_upstream_for_all_six_styles(self):
        for style in look.STYLES:
            with self.subTest(style=style):
                p = params(layer(style))
                actual = rendering.render_scene(make_scene(), p, False)[0]
                expected = make_scene().render(p)[0]
                np.testing.assert_array_equal(actual, expected)
                self.assertGreater(np.count_nonzero(actual != make_scene().src), 0)

    def test_locked_two_and_four_layers_match_independent_weighted_renders(self):
        arrangements = [
            ([layer("knit", weight=25), layer("lines", weight=75, tilt=57)], [.25, .75]),
            ([layer("knit", weight=12.5), layer("loops", weight=12.5),
              layer("coil", weight=25), layer("grain", weight=50)], [.125, .125, .25, .5]),
        ]
        for dark in (False, True):
            for items, shares in arrangements:
                with self.subTest(dark=dark, count=len(items)):
                    scene = make_scene()
                    p = params(items[0], items[1:])
                    actual = rendering.render_scene(scene, p, dark)[0]
                    np.testing.assert_array_equal(actual, expected_mix(scene, items, shares, dark))
                    np.testing.assert_array_equal(actual[scene.R == 0], scene.src[scene.R == 0])

    def test_unlocked_amounts_below_above_100_and_default_50_match_independent_renders(self):
        arrangements = [
            ([layer("knit", amount=25), layer("lines", amount=12.5)], [.25, .125]),
            ([layer("knit", amount=75), layer("lines", amount=75)], [.75, .75]),
            ([layer("knit", amount=None), layer("loops", amount=25),
              layer("coil", amount=75), layer("grain", amount=50)], [.5, .25, .75, .5]),
        ]
        for dark in (False, True):
            for items, shares in arrangements:
                with self.subTest(dark=dark, shares=shares):
                    scene = make_scene()
                    actual = rendering.render_scene(scene, params(items[0], items[1:], locked=False), dark)[0]
                    np.testing.assert_array_equal(actual, expected_mix(scene, items, shares, dark, unlocked=True))

    def test_zero_weights_and_zero_unlocked_amounts_have_defined_fallbacks(self):
        for dark in (False, True):
            scene = make_scene()
            first, second = layer("knit", weight=0), layer("grain", weight=100)
            out, info = rendering.render_scene(scene, params(first, [second]), dark)
            np.testing.assert_array_equal(out, single_layer(scene, second, dark))
            self.assertFalse(info["dark_adapt"])       # the hidden weave contributes nothing
            zero = params(layer("knit", weight=0), [layer("lines", weight=0)])
            np.testing.assert_array_equal(rendering.render_scene(scene, zero, dark)[0],
                                          single_layer(scene, first, dark))
            empty = params(layer("knit", amount=0), [layer("lines", amount=0)], locked=False)
            out, info = rendering.render_scene(scene, empty, dark)
            np.testing.assert_array_equal(out, scene.src)
            self.assertFalse(info["dark_adapt"])

    def test_single_layer_ignores_weight_and_amount_even_when_zero(self):
        for dark in (False, True):
            scene = make_scene()
            expected = single_layer(scene, layer("knit"), dark)
            for locked in (False, True):
                p = params(layer("knit", weight=0, amount=0), locked=locked)
                np.testing.assert_array_equal(rendering.render_scene(scene, p, dark)[0], expected)

    def test_first_layer_amount_changes_on_same_scene_without_polluting_raw_cache(self):
        for dark in (False, True):
            with self.subTest(dark=dark):
                scene = make_scene()
                low = params(layer("knit", amount=25), [layer("lines", amount=50)], locked=False)
                high = copy.deepcopy(low)
                high["amount"] = 75
                scene.render(low)                        # deliberately populate the raw pin's incomplete cache
                raw_cache = scene._full
                before = copy.deepcopy(low)
                a = rendering.render_scene(scene, low, dark)[0]
                b = rendering.render_scene(scene, high, dark)[0]
                c = rendering.render_scene(scene, low, dark)[0]
                self.assertGreater(np.count_nonzero(a != b), 0)
                np.testing.assert_array_equal(a, c)
                np.testing.assert_array_equal(b, rendering.render_scene(make_scene(), high, dark)[0])
                self.assertIs(scene._full, raw_cache)
                self.assertEqual(low, before)
                owner = editor_renderer(scene, low, dark)
                np.testing.assert_array_equal(owner.render()[0], a)
                owner.doc.look = high
                np.testing.assert_array_equal(owner.render()[0], b)
                np.testing.assert_array_equal(owner.render(rect=(17, 23, 139, 121))[0], b[23:121, 17:139])
                owner.doc.look = low
                np.testing.assert_array_equal(owner.render()[0], a)

    def test_dark_adaptation_applies_to_eligible_extra_layers_and_preserves_bright_input(self):
        for weave in ("knit", "loops", "lines"):
            for first_is_weave in (False, True):
                with self.subTest(style=weave, first=first_is_weave):
                    items = [layer("grain", weight=25), layer(weave, weight=75)]
                    if first_is_weave:
                        items.reverse()
                    p = params(items[0], items[1:])
                    scene = make_scene()
                    plain = rendering.render_scene(scene, p, False)[0]
                    adapted, info = rendering.render_scene(scene, p, True)
                    self.assertTrue(info["dark_adapt"])
                    self.assertGreater(np.count_nonzero(plain != adapted), 0)
                    shares = [item["weight"] / 100 for item in items]
                    np.testing.assert_array_equal(adapted, expected_mix(scene, items, shares, True))
                    bright = make_scene(bright=True)
                    np.testing.assert_array_equal(rendering.render_scene(bright, p, True)[0],
                                                  rendering.render_scene(bright, p, False)[0])

    def test_facade_crop_and_editor_crop_equal_full_for_four_layers_and_effects(self):
        items = [layer("knit", weight=12.5, amount=25), layer("coil", weight=12.5, amount=25),
                 layer("lines", weight=25, amount=50), layer("grain", weight=50, amount=50)]
        for dark in (False, True):
            for locked in (False, True):
                with self.subTest(dark=dark, locked=locked):
                    scene = make_scene()
                    p = params(items[0], items[1:], locked=locked, sparkle_even=170,
                               moire_on=True, moire=60, moire_area=65)
                    full = rendering.render_scene(scene, p, dark)[0]
                    owner = editor_renderer(scene, p, dark)
                    for rect in ((0, 0, 63, 57), (31, 27, 145, 122), (140, 112, 176, 144)):
                        x0, y0, x1, y1 = rect
                        crop = look.Scene.render(rendering._Renderer(scene, dark), p, rect)[0]
                        np.testing.assert_array_equal(crop, full[y0:y1, x0:x1])
                        np.testing.assert_array_equal(owner.render(rect=rect)[0], full[y0:y1, x0:x1])

    def test_shared_effects_run_once_after_mix_using_first_visible_layers_recipe(self):
        for dark in (False, True):
            with self.subTest(dark=dark):
                scene = make_scene()
                p = params(layer("knit", weight=0),
                           [layer("lines", weight=25), layer("loops", weight=25), layer("grain", weight=50)],
                           sparkle_even=200, moire_on=True, moire=70, moire_area=60)
                events, outputs = [], {}
                blend, moire, sparkle = look.blend_layers, look.apply_moire, knit.add_sparkles

                def blend_once(*args, **kwargs):
                    events.append("blend")
                    outputs["blend"] = blend(*args, **kwargs)
                    return outputs["blend"]

                def moire_once(image, *args, **kwargs):
                    events.append("moire")
                    np.testing.assert_array_equal(image, outputs["blend"])
                    outputs["moire"] = moire(image, *args, **kwargs)
                    return outputs["moire"]

                def sparkle_once(image, *args, **kwargs):
                    events.append("sparkles")
                    np.testing.assert_array_equal(image, outputs["moire"])
                    for key in ("density", "r_lo", "r_hi", "tint"):
                        self.assertEqual(kwargs[key], look.SPARKLE_RECIPES["lines"][key])
                    return sparkle(image, *args, **kwargs)

                with mock.patch.object(look, "blend_layers", side_effect=blend_once), \
                        mock.patch.object(look, "apply_moire", side_effect=moire_once), \
                        mock.patch.object(knit, "add_sparkles", side_effect=sparkle_once):
                    _, info = rendering.render_scene(scene, p, dark)
                self.assertEqual(events, ["blend", "moire", "sparkles"])
                self.assertTrue(info["sparkles_ready"])
                self.assertTrue(info["moire_ready"])

    def test_extra_layer_auto_strength_is_resolved_without_mutating_inputs(self):
        p = params(layer("knit", strength=70), [layer("lines", strength=17, auto=True)])
        before = copy.deepcopy(p)
        for dark in (False, True):
            scene = make_scene()
            arrays = {key: getattr(scene, key).copy() for key in ("src", "R", "V", "A", "alpha")}
            with mock.patch.object(scene, "suggested_strength", return_value=137):
                actual = rendering.render_scene(scene, p, dark)[0]
            manual = copy.deepcopy(p)
            manual["layers"][0].update(strength=137, strength_auto=False)
            np.testing.assert_array_equal(actual, rendering.render_scene(make_scene(), manual, dark)[0])
            self.assertEqual(p, before)
            for key, value in arrays.items():
                np.testing.assert_array_equal(getattr(scene, key), value)

    def test_scene_subclass_seeded_randoms_survive_facade_forwarding(self):
        class SeededScene(look.Scene):
            def randoms(self, style):
                self.calls.append(style)
                if style not in self._randoms:
                    rng = np.random.default_rng(self.seed)
                    self._randoms[style] = (rng.random((self.h, self.w)), rng.random((self.h, self.w)))
                return self._randoms[style]

        p = params(layer("lines", strength=0), [layer("lines", strength=0)], sparkle_even=300)
        for dark in (False, True):
            results = []
            for seed in (17, 17, 19):
                scene = make_scene(scene_type=SeededScene)
                scene.seed, scene.calls = seed, []
                results.append(rendering.render_scene(scene, p, dark)[0])
                self.assertIn("lines", scene.calls)
            np.testing.assert_array_equal(results[0], results[1])
            self.assertGreater(np.count_nonzero(results[0] != results[2]), 0)

    def test_missing_depth_becoming_ready_on_same_scene_refreshes_image_and_status(self):
        for dark in (False, True):
            with self.subTest(dark=dark):
                scene = make_scene(depth=False)
                holder = {"depth": None}
                scene._disparity = lambda: holder["depth"]
                p = params(layer("knit"), [layer("lines")], sparkle_depth=150,
                           moire_on=True, moire=70, moire_area=80)
                pending, info = rendering.render_scene(scene, p, dark)
                self.assertFalse(info["sparkles_ready"])
                self.assertFalse(info["moire_ready"])
                yy, xx = np.mgrid[:scene.h, :scene.w]
                holder["depth"] = np.exp(-((xx - 80) / 45) ** 2 - ((yy - 70) / 39) ** 2).astype(np.float32)
                ready, info = rendering.render_scene(scene, p, dark)
                self.assertTrue(info["sparkles_ready"])
                self.assertTrue(info["moire_ready"])
                self.assertGreater(np.count_nonzero(pending != ready), 0)
                np.testing.assert_array_equal(ready, rendering.render_scene(scene, p, dark)[0])


if __name__ == "__main__":
    unittest.main()
