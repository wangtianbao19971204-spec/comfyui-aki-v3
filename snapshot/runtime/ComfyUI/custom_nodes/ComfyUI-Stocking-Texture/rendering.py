"""Local shadow adaptation around the pinned upstream shaders.

The dispatch and sparkle order follow upstream look.Scene.render at the commit in
UPSTREAM.json. Only the weave dark-fade interval changes: 0..0.12 instead of
0.03..0.30. Pure black stays black; midtones above 0.30, frequency filtering,
coverage, tint and seeded sparkle draws retain the upstream behavior. No vendor
globals are patched. Disable dark_adapt for the original rendering path.
"""
import numpy as np

from .vendor import knit, look


def render_scene(scene, params, dark_adapt):
    q = scene.resolve(look.clean_params(params))
    adapted = bool(dark_adapt and q["style"] in ("knit", "loops", "lines"))
    if not adapted:
        out, info = scene.render(q)
    else:
        info = look.geometry(q["density"], scene.w, scene.h)
        p, strength = info["period"], q["strength"] / 100.0
        common = dict(f_lo=info["f_lo"], f_hi=info["f_hi"], dark=(0.0, 0.12))
        if q["style"] in ("knit", "loops"):
            draw = knit.render_thread if q["style"] == "knit" else knit.render_loops
            out, _ = draw(scene.src, scene.R, scene.V / p + 0.37 * scene.R,
                          scene.A / (p * info["wale_ratio"]), scene.alpha, scene.wide_luma(),
                          amp=(0.10 if q["style"] == "knit" else 0.12) * strength, **common)
        else:
            theta = np.deg2rad(q["tilt"])
            phase = np.cos(theta) * scene.V / p + np.sin(theta * scene.side) * scene.A / p
            out, _ = knit.render_lines(scene.src, scene.R, phase, scene.alpha,
                                       amp=0.115 * strength, **common)
        moire_ready = True
        if look.moire_active(q):
            fringes = scene.moire_map(q["moire_area"] / 100.0)
            if fringes is None:
                moire_ready = False
            else:
                out = look.apply_moire(out, scene.src, fringes, q["moire"] / 100.0,
                                       scene.suggested_strength() / 100.0)
        weight, ready = scene.sparkle_weight(q, q["style"])
        if weight is not None:
            recipe = look.SPARKLE_RECIPES[q["style"]]
            draws = scene.randoms("lines") if recipe["draws"] == "lines" else scene.randoms("grain")[2:]
            out = knit.add_sparkles(out, weight, None, density=recipe["density"],
                                    r_lo=recipe["r_lo"], r_hi=recipe["r_hi"],
                                    tint=recipe["tint"], draws=draws)
        info = dict(info, style=q["style"], sparkles_ready=ready, moire_ready=moire_ready)
    return out, dict(info, effective_strength=float(q["strength"]),
                     automatic_strength=bool(q["strength_auto"]), dark_adapt=adapted)
