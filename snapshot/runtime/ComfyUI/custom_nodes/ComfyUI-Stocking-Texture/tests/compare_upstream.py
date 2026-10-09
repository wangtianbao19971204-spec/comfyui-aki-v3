"""Offline fixed-input comparison with a separately obtained pinned upstream checkout.

No services, models or source images are modified. Evidence must be a new directory.
Upstream Document uses its real rasterizer, worker, coverage and export render path.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import types

import numpy as np
from PIL import Image, ImageDraw


def package(name, path):
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod


def run(upstream, image_path, guides_path, out):
    out.mkdir(parents=True, exist_ok=False)
    plugin = Path(__file__).resolve().parents[1]
    package("candidate", plugin)
    package("original", upstream / "stocking")
    engine = importlib.import_module("candidate.engine")
    look = importlib.import_module("original.look")
    document = importlib.import_module("original.document")
    provenance = json.loads((plugin / "UPSTREAM.json").read_text(encoding="utf-8"))
    for item in provenance["files"]:
        assert hashlib.sha256((upstream / "stocking" / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    rgb8 = np.array(Image.open(image_path).convert("RGB"))
    h, w = rgb8.shape[:2]
    rgb = rgb8.astype(np.float32) / 255
    data = engine.parse_guides(guides_path.read_text(encoding="utf-8"), w, h)
    geometry = engine.solve_geometry(rgb8, data, None, True, None, False)
    maps, _ = engine.region_maps(data)
    doc = document.Document(rgb8, "fixed-input-comparison")
    try:
        with doc.lock:
            for r, mask in zip(data["regions"], maps):
                region = doc._new_region(r["name"], mask > 0)
                for line in r["strokes"]:
                    doc.strokes.append(document.Stroke(next(doc._ids), line, region.id))
            doc.dividers = [document.Divider(next(doc._ids), line) for line in data["dividers"]]
            doc._touch()
        assert doc.wait_idle(60), "Original solver did not finish"
        scene = look.scene_from_doc(doc)
        reg, v, _, _, across = doc.fields()
        active = (geometry["labels"] > 0) & geometry["stock"] & (geometry["alpha"] > 0)
        parity = {
            "labels_equal": bool(np.array_equal(reg, geometry["labels"])),
            "coverage_equal": bool(np.array_equal(doc.coverage()[0], geometry["stock"])),
            "alpha_max_error": float(np.max(np.abs(doc.coverage()[1] - geometry["alpha"]))),
            "v_max_error": float(np.max(np.abs(v - geometry["v"]))),
            "across_max_error": float(np.max(np.abs(across - geometry["across"]))),
        }
        assert parity["labels_equal"] and parity["coverage_equal"]
        assert max(parity[k] for k in ("alpha_max_error", "v_max_error", "across_max_error")) < 1e-6, parity
        rows, images = [], []
        for style in look.STYLES:
            for bright in (0, 100):
                q = dict(style=style, density=100, strength=100, strength_auto=True, tilt=32,
                         sparkle_link=False, sparkle_depth=0, sparkle_bright=bright, sparkle_even=0)
                original = scene.render(q)[0][..., ::-1]
                legacy = engine.render_texture(rgb, data, geometry, None, q, look.SEED, False)
                legacy8 = np.round(legacy[0] * 255).astype(np.uint8)
                assert np.array_equal(original[active], legacy8[active]), (style, bright, "upstream parity")
                for adapt in (False, True):
                    result = engine.render_texture(rgb, data, geometry, None, q, look.SEED, adapt)
                    result8 = np.round(result[0] * 255).astype(np.uint8)
                    name = f"{style}-bright{bright}-adapt{int(adapt)}"
                    Image.fromarray(result8).save(out / (name + ".png"))
                    rows.append(dict(case=name, **result[-1]))
                    assert np.array_equal(result[0][~active], rgb[~active])
                    composite = rgb * (1 - result[2][..., None]) + result[1] * result[2][..., None]
                    assert float(np.abs(composite - result[0]).max()) < 1e-7
                    if style in ("knit", "loops", "lines") and bright == 0:
                        images.append((name, result8))
        # A second round exercises manual visibility, soft edges and deterministic recomputation.
        for style in ("knit", "loops", "lines"):
            for density, strength in ((65, 100), (65, 160), (40, 160), (40, 250), (100, 0)):
                q = dict(style=style, density=density, strength=strength, strength_auto=False,
                         sparkle_link=False, sparkle_depth=0, sparkle_bright=0, sparkle_even=0)
                result = engine.render_texture(rgb, data, geometry, None, q, look.SEED, True)
                repeat = engine.render_texture(rgb, data, geometry, None, q, look.SEED, True)
                assert np.array_equal(result[0], repeat[0])
                if strength == 0:
                    assert np.array_equal(result[0], rgb)
                name = f"{style}-density{density}-strength{strength}"
                Image.fromarray(np.round(result[0] * 255).astype(np.uint8)).save(out / (name + ".png"))
                rows.append(dict(case=name, **result[-1]))
                if (density, strength) == (65, 160):
                    images.append((name, np.round(result[0] * 255).astype(np.uint8)))
        ys, xs = np.where(active)
        # Use one region's bounding box, enlarged without contrast/brightness manipulation.
        ys, xs = np.where(geometry["all_labels"] == 1)
        box = (max(0, xs.min()-8), max(0, ys.min()-8), min(w, xs.max()+9), min(h, ys.max()+9))
        crops = [("source", rgb8)] + images
        cw, ch = (box[2]-box[0])*3, (box[3]-box[1])*3
        sheet = Image.new("RGB", (cw*5, (ch+28)*2), "#262832")
        draw = ImageDraw.Draw(sheet)
        for i, (label, arr) in enumerate(crops):
            x, y = i % 5 * cw, i // 5 * (ch+28)
            sheet.paste(Image.fromarray(arr).crop(box).resize((cw, ch), Image.Resampling.NEAREST), (x, y+28))
            draw.text((x+4, y+6), label, fill="white")
        sheet.save(out / "comparison.png")
        receipt = dict(schema=1, upstream_commit=provenance["commit"],
                       source_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
                       upstream_document_parity=parity, case_count=len(rows), cases=rows)
        (out / "COMPARISON.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(dict(parity=parity, case_count=len(rows),
                              weave=[{k:r[k] for k in ("case", "changed_pixels_8bit", "max_delta_8bit")} for r in rows[:12]])))
    finally:
        doc.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "image", "guides", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    a = parser.parse_args()
    run(a.upstream, a.image, a.guides, a.out)
