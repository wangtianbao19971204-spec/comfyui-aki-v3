"""Local shadow adaptation around the pinned upstream shaders.

The dispatch and sparkle order follow upstream look.Scene.render at the commit in
UPSTREAM.json. Only the weave dark-fade interval changes: 0..0.12 instead of
0.03..0.30. Pure black stays black; midtones above 0.30, frequency filtering,
coverage, tint and seeded sparkle draws retain the upstream behavior. No vendor
globals are patched. Disable dark_adapt for the original rendering path.
"""
import numpy as np

from .vendor import knit, look


class _Renderer:
    """Keep upstream blending/effect order, adapting only each weave shader.

    The per-call full cache also avoids the pinned version's missing top-level
    amount cache key. Studio supplies its own complete-parameter cache.
    """
    def __init__(self, scene, dark_adapt):
        self.scene, self.dark_adapt = scene, dark_adapt
        self._full = (None, None)

    def __getattr__(self, name):
        return getattr(self.scene, name)

    def _draw_layer(self, layer, sl, src, R, V, A, alpha):
        if not self.dark_adapt or layer["style"] not in ("knit", "loops", "lines"):
            return self.scene._draw_layer(layer, sl, src, R, V, A, alpha)
        g = look.geometry(layer["density"], self.w, self.h)
        p, strength = g["period"], layer["strength"] / 100.0
        common = dict(f_lo=g["f_lo"], f_hi=g["f_hi"], dark=(0.0, 0.12))
        if layer["style"] in ("knit", "loops"):
            draw = knit.render_thread if layer["style"] == "knit" else knit.render_loops
            out, _ = draw(src, R, V / p + 0.37 * R, A / (p * g["wale_ratio"]), alpha,
                          self.region_tone()[sl], amp=(0.10 if layer["style"] == "knit" else 0.12) * strength,
                          **common)
        else:
            theta = np.deg2rad(layer["tilt"])
            phase = np.cos(theta) * V / p + np.sin(theta * self.side[sl]) * A / p
            out, _ = knit.render_lines(src, R, phase, alpha, amp=0.115 * strength, **common)
        return out


def render_scene(scene, params, dark_adapt):
    q = scene.resolve(look.clean_params(params))
    adapted = bool(dark_adapt and any(layer["style"] in ("knit", "loops", "lines")
                                     for layer, _ in look.drawn_layers(q)))
    out, info = look.Scene.render(_Renderer(scene, dark_adapt), q)
    return out, dict(info, effective_strength=float(q["strength"]),
                     automatic_strength=bool(q["strength_auto"]), dark_adapt=adapted)
