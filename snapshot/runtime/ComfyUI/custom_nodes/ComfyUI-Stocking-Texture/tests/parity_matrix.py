"""Compare the real upstream Document/Scene with the port across colours and poses.

All images and evidence stay in a new private output directory. Synthetic shapes
are algorithm controls, not human-pose quality certification. Optional real
fixtures use a JSON list with id/image/guides/description, and are never edited.
No server, model, network, installation or production mutation is performed.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import types

import cv2
import numpy as np
from PIL import Image


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def region(name, polygons, strokes):
    return dict(id=name, name=name, polygons=polygons, strokes=strokes)


def synthetic():
    """Independent geometry and colour factors; no retouching of real pictures."""
    layouts = {
        "straight": ([region("left", [[[60, 24], [145, 24], [145, 355], [60, 355]]],
                             [[[68, 60], [103, 50], [138, 60]],
                              [[68, 180], [103, 170], [138, 180]],
                              [[68, 310], [103, 300], [138, 310]]])], []),
        "bent": ([region("left", [[[60, 24], [138, 24], [140, 162], [224, 270],
                                    [166, 320], [84, 219], [60, 165]]],
                         [[[67, 65], [100, 57], [131, 65]],
                          [[66, 152], [96, 142], [134, 152]],
                          [[140, 262], [166, 239], [189, 231]]])],
                 [[[100, 187], [120, 173], [140, 162]]]),
        "crossed": ([
            region("left", [[[38, 25], [96, 25], [222, 351], [162, 351]]],
                   [[[54, 76], [93, 59]], [[145, 305], [191, 285]]]),
            region("right", [[[174, 25], [230, 25], [99, 351], [42, 351]]],
                   [[[181, 62], [218, 77]], [[69, 286], [111, 303]]])], []),
        "occluded": ([region("left", [
            [[60, 24], [145, 24], [145, 154], [60, 154]],
            [[60, 181], [145, 181], [145, 355], [60, 355]]],
            [[[68, 60], [103, 50], [138, 60]],
             [[68, 310], [103, 300], [138, 310]]])], []),
    }
    colours = {"white": (238, 234, 230), "gray": (135, 135, 135), "black": (55, 50, 58),
               "near_black": (19, 19, 19), "red": (160, 46, 55), "blue": (44, 82, 166),
               "purple": (130, 60, 150), "pure_black": (0, 0, 0)}
    yy, xx = np.mgrid[:384, :256]
    shade = (0.72 + 0.28 * np.exp(-((xx - 105) / 42) ** 2)) * (0.95 + 0.05 * np.cos(yy / 70))
    for pose, (regions, dividers) in layouts.items():
        data = dict(schema=1, width=256, height=384, regions=regions, dividers=dividers)
        for colour, base in colours.items():
            rgb = np.round(np.asarray(base)[None, None] * shade[..., None]).astype(np.uint8)
            yield dict(id=f"{colour}-{pose}", kind="synthetic", description=f"{colour}; {pose}",
                       rgb=rgb, data=data, depth=None, exclude=True, walls=False)
    data = dict(schema=1, width=256, height=384, regions=layouts["straight"][0], dividers=[])
    rgb = np.round(np.array((215, 212, 208))[None, None] * shade[..., None]).astype(np.uint8)
    rgb[220:255, 82:119] = (25, 70, 165)
    for exclude in (True, False):
        yield dict(id=f"colour-exclusion-{int(exclude)}", kind="synthetic", description="contrasting patch",
                   rgb=rgb, data=data, depth=None, exclude=exclude, walls=False)
    # Identical explicitly supplied disparity, not a test of a depth estimator.
    depth = (0.3 + 0.1 * np.cos(xx / 40) + 0.4 * (yy > 215)).astype(np.float32)
    for walls in (False, True):
        yield dict(id=f"supplied-depth-walls-{int(walls)}", kind="synthetic", description="depth step",
                   rgb=rgb, data=data, depth=depth, exclude=False, walls=walls)
    # The small fixture above detects no wall. Also exercise a positive depth
    # step that ends at a knee; this tests supplied depth, not a model.
    yy, xx = np.mgrid[:400, :300].astype(np.float32)
    depth = (0.6*np.sqrt(np.clip(1-((xx-150)/195)**2, 0, 1))
             + 0.2*(xx < 150)/(1+np.exp((yy-250)/30))).astype(np.float32)
    data = dict(schema=1, width=300, height=400, dividers=[], regions=[region("fold", [
        [[46, 21], [254, 21], [254, 379], [46, 379]]], [
        [[55, 75], [90, 65], [135, 75]], [[165, 65], [207, 75], [245, 90]],
        [[56, 325], [144, 310], [244, 329]]])])
    rgb = np.round((0.75+0.2*np.cos((xx-150)/150))[..., None]*np.array((90, 83, 96))).astype(np.uint8)
    for walls in (False, True):
        yield dict(id=f"fold-depth-walls-{int(walls)}", kind="synthetic", description="positive fold depth step",
                   rgb=rgb, data=data, depth=depth, exclude=False, walls=walls, expect_walls=walls)


def real_fixtures(path):
    if path is None:
        return
    for item in json.loads(path.read_text(encoding="utf-8")):
        source, guides = Path(item["image"]), Path(item["guides"])
        yield dict(id=item["id"], kind="real", description=item["description"],
                   rgb=np.array(Image.open(source).convert("RGB")),
                   data=json.loads(guides.read_text(encoding="utf-8")), depth=None,
                   exclude=item.get("color_exclude", True), walls=False,
                   source_sha256=sha(source), guides_sha256=sha(guides))


def test_fixture(f, out, engine, look, document):
    out.mkdir()
    rgb8, data, depth = f["rgb"], f["data"], f["depth"]
    h, w = rgb8.shape[:2]
    data = engine.parse_guides(json.dumps(data), w, h)
    Image.fromarray(rgb8).save(out / "source.png")
    (out / "guides.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if depth is not None:
        np.save(out / "depth.npy", depth)
    rgb = rgb8.astype(np.float32) / 255
    g = engine.solve_geometry(rgb8, data, None, f["exclude"], depth, f["walls"])
    doc = document.Document(rgb8, f["id"])
    try:
        with doc.lock:
            maps, _ = engine.region_maps(data)
            for spec, mask in zip(data["regions"], maps):
                r = doc._new_region(spec["name"], mask > 0)
                for pts in spec["strokes"]:
                    doc.strokes.append(document.Stroke(next(doc._ids), pts, r.id))
            doc.dividers = [document.Divider(next(doc._ids), pts) for pts in data["dividers"]]
            doc.set_color_exclude(f["exclude"])
            if f["walls"]:
                doc.disparity = depth
            doc._touch()
        assert doc.wait_idle(180), f["id"]
        errors = [s.error for cache in doc._solves.values() for s in cache.values() if s.error]
        assert not errors, errors
        scene = look.scene_from_doc(doc, disparity=(lambda: depth) if depth is not None else None)
        reg, v, _, _, across = doc.fields()
        stock, alpha = doc.coverage()[:2]
        geometry = dict(labels_equal=bool(np.array_equal(reg, g["labels"])),
                        coverage_equal=bool(np.array_equal(stock, g["stock"])),
                        cut_equal=bool(np.array_equal(doc.cut_map(), g["cut"])),
                        v_error=float(np.abs(v-g["v"]).max()),
                        across_error=float(np.abs(across-g["across"]).max()),
                        alpha_error=float(np.abs(alpha-g["alpha"]).max()))
        assert all(geometry[k] for k in ("labels_equal", "coverage_equal", "cut_equal")), geometry
        assert max(geometry[k] for k in ("v_error", "across_error", "alpha_error")) < 1e-6, geometry
        auto = [inp.auto for inp in doc._prepare()[1].values() if inp is not None and inp.auto is not None]
        geometry["automatic_wall_pixels"] = sum(int(x.sum()) for x in auto)
        geometry["cut_pixels"] = int(g["cut"].sum())
        if f.get("expect_walls"):
            assert geometry["automatic_wall_pixels"] > 0 and geometry["cut_pixels"] > 0, geometry
        selected = g["all_labels"] > 0
        active = (g["labels"] > 0) & g["stock"] & (g["alpha"] > 0)
        rows = []
        for style in look.STYLES:
            for bright in (0, 100):
                q = dict(style=style, density=65, strength=100, strength_auto=True, tilt=32,
                         sparkle_link=False, sparkle_depth=100 if depth is not None else 0,
                         sparkle_bright=bright, sparkle_even=0, sparkle_painted=0)
                original = scene.render(q)[0][..., ::-1]
                for adapt in (False, True):
                    result, layer, a, check, metrics = engine.render_texture(rgb, data, g, depth, q, look.SEED, adapt)
                    saved = np.clip(result*255, 0, 255).astype(np.uint8)  # real SaveImage conversion
                    diff = np.any(saved != original, axis=2)
                    maximum = int(np.abs(saved.astype(np.int16)-original.astype(np.int16)).max())
                    composite_error = float(np.abs(rgb*(1-a[..., None])+layer*a[..., None]-result).max())
                    assert not np.any(saved[~selected] != rgb8[~selected])
                    assert composite_error < 1e-7, composite_error
                    if not adapt:
                        assert not diff[active].any(), (f["id"], style, bright, int(diff[active].sum()), maximum)
                    repeat = engine.render_texture(rgb, data, g, depth, q, look.SEED, adapt)[0]
                    assert np.array_equal(repeat, result), "repeat mismatch"
                    name = f"{style}-bright{bright}-adapt{int(adapt)}"
                    if f["kind"] == "real" or (bright == 0 and style == "knit"):
                        Image.fromarray(saved).save(out / (name + ".png"))
                        Image.fromarray(np.round(check*255).astype(np.uint8)).save(out / (name + "-problems.png"))
                    if not adapt and f["kind"] == "real":
                        Image.fromarray(original).save(out / f"{style}-bright{bright}-original.png")
                    rows.append(dict(case=name, **metrics, active_parity_pixels=int(diff[active].sum()),
                                     full_difference_pixels=int(diff.sum()), max_upstream_delta=maximum,
                                     difference_outside_selection=int(diff[~selected].sum()),
                                     difference_inactive_selection=int(diff[selected & ~active].sum()),
                                     outside_changed_pixels=0, composite_error=composite_error, repeat_equal=True))
        report = dict(id=f["id"], kind=f["kind"], description=f["description"], geometry=geometry,
                      selected_pixels=int(selected.sum()), active_pixels=int(active.sum()),
                      source_sha256=f.get("source_sha256", sha(out/"source.png")),
                      canonical_pixel_sha256=hashlib.sha256(rgb8.tobytes()).hexdigest(),
                      guides_sha256=sha(out/"guides.json"), shape=list(rgb8.shape), cases=rows)
        (out / "RESULT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(dict(id=f["id"], geometry=geometry, cases=len(rows),
                              base=[dict(case=r["case"], changed=r["changed_pixels_8bit"],
                                         strength=r["effective_strength"], faded=r["faded_pixels"])
                                    for r in rows if r["case"].startswith("knit-bright0")]), ensure_ascii=False), flush=True)
        return report
    finally:
        doc.close()


def run(a):
    a.out.mkdir(parents=True, exist_ok=False)
    plugin = Path(__file__).resolve().parents[1]
    package("candidate", plugin)
    package("original", a.upstream / "stocking")
    engine = importlib.import_module("candidate.engine")
    look, document = [importlib.import_module("original."+name) for name in ("look", "document")]
    provenance = json.loads((plugin/"UPSTREAM.json").read_text(encoding="utf-8"))
    for item in provenance["files"]:
        assert sha(a.upstream/"stocking"/item["file"]) == item["sha256"]
    fixtures = ([] if a.real_only else list(synthetic())) + list(real_fixtures(a.fixtures))
    if a.only:
        fixtures = [f for f in fixtures if f["id"] in a.only]
        assert len(fixtures) == len(a.only), "Unknown or duplicate fixture id"
    results = []
    for fixture in fixtures:
        results.append(test_fixture(fixture, a.out/fixture["id"], engine, look, document))
    report = dict(schema=1, upstream_commit=provenance["commit"],
                  synthetic_fixtures=sum(x["kind"] == "synthetic" for x in results),
                  real_fixtures=sum(x["kind"] == "real" for x in results),
                  render_cases=sum(len(x["cases"]) for x in results),
                  matched_active_cases=sum("adapt0" in r["case"] for x in results for r in x["cases"]),
                  boundary="Exact compatibility is asserted within active coverage; excluded/unselected pixels stay unchanged.",
                  pass_all=True, results=results)
    (a.out/"MATRIX.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "results"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--real-only", action="store_true")
    parser.add_argument("--only", action="append")
    run(parser.parse_args())
