"""Compare complete-editor output and preview overlays to an independent pinned upstream.

Reads existing fixtures and model acceptance depth; writes only a new evidence folder.
The original HTTP overlay function is compiled unchanged without starting its server.
"""
import argparse
import ast
import hashlib
import importlib
import json
from pathlib import Path
import types

import cv2
import numpy as np
from PIL import Image

from compare_upstream import package


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    plugin = Path(__file__).resolve().parents[1]
    package("candidate", plugin)
    package("original", args.upstream / "stocking")
    engine = importlib.import_module("candidate.engine")
    store = importlib.import_module("candidate.studio_store")
    studio = importlib.import_module("candidate.studio")
    document = importlib.import_module("original.document")
    look = importlib.import_module("original.look")
    provenance = json.loads((plugin / "UPSTREAM.json").read_text(encoding="utf-8"))
    for item in provenance["files"]:
        assert hashlib.sha256((args.upstream / "stocking" / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    source = args.upstream / "stocking/server.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("check_maps", "render_check"):
            node.decorator_list = []
            selected.append(node)
    assert len(selected) == 2
    namespace = {"np": np, "cv2": cv2, "Request": object, "CROP_MAX": 1024,
                 "CHECK_COLOURS": ((2, (40, 190, 255)), (1, (255, 150, 70)), (0, (60, 50, 255))),
                 "_png": lambda data: data}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    rows = []
    for fixture in json.loads(args.fixtures.read_text(encoding="utf-8")):
        name = fixture["id"]
        art = np.array(Image.open(fixture["image"]).convert("RGB"))
        h, w = art.shape[:2]
        guides = engine.parse_guides(Path(fixture["guides"]).read_text(encoding="utf-8"), w, h)
        masks, _ = engine.region_maps(guides)
        doc = document.Document.from_snapshot(art, name + ".png", None,
            [(r["name"], document.PALETTE[i % len(document.PALETTE)], mask > 0)
             for i, (r, mask) in enumerate(zip(guides["regions"], masks))],
            [(np.asarray(p), i) for i, r in enumerate(guides["regions"]) for p in r["strokes"]],
            dividers=[np.asarray(p) for p in guides["dividers"]], color_exclude=True)
        model_name = {"white-bent": "models-white", "black-crossed": "models-black", "nearblack-standing": "models-nearblack"}[name]
        doc.disparity = np.load(args.models / model_name / "depth.npy", allow_pickle=False)
        assets = args.out / "assets"
        saved = store.snapshot(doc, assets, depth_enabled=True, dark_adapt=False)
        own = studio.Studio(assets, store.Preferences(args.out / "user"), {"sam": Path("missing"), "depth": Path("missing")}, saved)
        try:
            assert doc.wait_idle(120)
            own.wait_ready()
            reference = look.scene_from_doc(doc, disparity=lambda: doc.disparity)
            namespace.update(doc_for=lambda _: doc, scene_for=lambda _: reference)
            active = doc.fields()[0] > 0
            yy, xx = np.where(active)
            x, y = int(np.median(xx)), int(np.median(yy))
            rect = (max(0, x - 96), max(0, y - 96), min(w, x + 96), min(h, y + 96))
            for style in look.STYLES:
                params = dict(look.DEFAULTS, style=style, density=65)
                expected = reference.render(params)[0]
                actual = own.render(params)[0]
                np.testing.assert_array_equal(actual, expected)
                crop = own.render(params, rect)[0]
                np.testing.assert_array_equal(crop, expected[rect[1]:rect[3], rect[0]:rect[2]])
                namespace["_params"] = lambda *a: params
                check = namespace["render_check"]("id", None, 351, 247)
                np.testing.assert_array_equal(studio.check_image(own.doc, own.scene(), params, size=(351, 247)), check)
                check_crop = namespace["render_check"]("id", None, rect[2]-rect[0], rect[3]-rect[1], rect[0], rect[1])
                np.testing.assert_array_equal(studio.check_image(own.doc, own.scene(), params, rect=rect), check_crop)
                Image.fromarray(actual[..., ::-1]).save(args.out / f"{name}-{style}.png")
                rows.append({"image": name, "style": style, "full_equal": True, "crop_equal": True,
                             "check_fit_equal": True, "check_crop_equal": True,
                             "changed_pixels": int(np.any(actual[..., ::-1] != art, axis=2).sum())})
            print(json.dumps({"image": name, "six_styles_full_and_preview_equal": True}), flush=True)
        finally:
            own.close(); doc.close()
    receipt = {"pass": True, "upstream": provenance["commit"], "server_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "dark_adapt": False, "actual_depth_enabled": True, "cases": rows}
    (args.out / "ACCEPTANCE.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("upstream", "fixtures", "models", "out"):
        parser.add_argument("--" + key, type=Path, required=True)
    run(parser.parse_args())
