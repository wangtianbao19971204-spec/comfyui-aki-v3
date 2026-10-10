"""Replay saved UI bend-edit stages against an independently obtained upstream.

Caller-owned drafts and immutable image/depth assets remain private. This runner
checks that splitting preserves selection, guidance really changes direction,
and each rendered stage matches upstream at the same input and parameters.
It does not certify SAM accuracy or the artistic quality of arbitrary drawings.
"""
import argparse
import base64
import hashlib
import importlib
import io
import json
from pathlib import Path
import zlib

import numpy as np
from PIL import Image

from compare_upstream import package


def mask(value, width, height, bits=True):
    raw = np.frombuffer(zlib.decompress(base64.b64decode(value)), np.uint8)
    return (np.unpackbits(raw, count=width * height).astype(bool)
            if bits else raw).reshape(height, width)


def original_doc(project, assets, document):
    """Read the public schema independently of candidate restore/snapshot code."""
    w, h = project["width"], project["height"]
    data = (assets / (project["asset"] + ".png")).read_bytes()
    assert hashlib.sha256(data).hexdigest() == project["asset"]
    art = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
    assert art.shape == (h, w, 3)
    regions = [(r["name"], r["color"], mask(r["mask"], w, h))
               for r in project["regions"]]
    strokes = [(np.asarray(s["pts"]).reshape(-1, 2), s["region"])
               for s in project["strokes"]]
    dividers = [np.asarray(s).reshape(-1, 2) for s in project["dividers"]]
    sparkle = mask(project["sparkle"], w, h, False) if project.get("sparkle") else None
    doc = document.Document.from_snapshot(
        art, project["name"], None, regions, strokes, sparkle, project.get("look"),
        dividers, project.get("erased", []), project["color_exclude"], False)
    try:
        if project.get("depth_asset"):
            depth = (assets / (project["depth_asset"] + ".npy")).read_bytes()
            assert hashlib.sha256(depth).hexdigest() == project["depth_asset"]
            doc.disparity = np.load(io.BytesIO(depth), allow_pickle=False)
    except Exception:
        doc.close()
        raise
    return doc, art, regions


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    plugin = Path(__file__).resolve().parents[1]
    package("candidate", plugin)
    package("original", args.upstream / "stocking")
    studio = importlib.import_module("candidate.studio")
    store = importlib.import_module("candidate.studio_store")
    document = importlib.import_module("original.document")
    look = importlib.import_module("original.look")
    provenance = json.loads((plugin / "UPSTREAM.json").read_text(encoding="utf-8"))
    for row in provenance["files"]:
        assert hashlib.sha256((args.upstream / "stocking" / row["file"]).read_bytes()).hexdigest() == row["sha256"]
    stages, fields, unions = [], {}, {}
    for name, path in (("baseline", args.baseline), ("split", args.split), ("arc", args.arc)):
        saved = json.loads(path.read_text(encoding="utf-8"))
        project = saved.get("project", saved)
        assert project["dark_adapt"] is False
        doc, art, regions = original_doc(project, args.assets, document)
        own = None
        try:
            own = studio.Studio(args.assets, store.Preferences(args.out / "user"),
                                {"sam": Path("missing"), "depth": Path("missing")}, project)
            assert doc.wait_idle(120), "Upstream solver timed out"
            own.wait_ready()
            original_fields, candidate_fields = doc.fields(), own.doc.fields()
            for a, b in zip(original_fields, candidate_fields):
                np.testing.assert_array_equal(a, b)
            fields[name] = [a.copy() for a in candidate_fields]
            unions[name] = np.logical_or.reduce([r[2] for r in regions])
            reference = look.scene_from_doc(doc, disparity=lambda: doc.disparity)
            renders = []
            for style in look.STYLES:
                params = dict(look.DEFAULTS, style=style, density=65,
                              sparkle_depth=0, sparkle_bright=0, sparkle_even=0,
                              sparkle_painted=0)
                expected = reference.render(params)[0]
                actual = own.render(params)[0]
                np.testing.assert_array_equal(actual, expected)
                image = actual[..., ::-1]
                Image.fromarray(image).save(args.out / f"{name}-{style}.png")
                changed = np.any(image != art, axis=2)
                renders.append({"style": style, "upstream_pixels_equal": True,
                                "changed_pixels": int(changed.sum()),
                                "changed_outside_selection": int((changed & ~unions[name]).sum())})
            stages.append({"stage": name, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "regions": len(regions), "strokes": len(project["strokes"]),
                           "dividers": len(project["dividers"]), "fields_equal": True,
                           "renders": renders})
            Image.fromarray(art).save(args.out / "source.png")
            print(json.dumps({"stage": name, "six_styles_equal": True}), flush=True)
        finally:
            if own is not None:
                own.close()
            doc.close()
    for value in unions.values():
        np.testing.assert_array_equal(value, unions["baseline"])
    changes = {}
    for name in ("split", "arc"):
        a, b = fields["baseline"], fields[name]
        na, nb = np.hypot(a[2], a[3]), np.hypot(b[2], b[3])
        valid = (a[0] > 0) & (b[0] > 0) & (na > 1e-9) & (nb > 1e-9)
        dot = (a[2][valid] * b[2][valid] + a[3][valid] * b[3][valid]) / (na[valid] * nb[valid])
        degrees = np.degrees(np.arccos(np.clip(np.abs(dot), 0, 1)))
        count = int((degrees > 15).sum())
        assert count > 100, "Direction edit did not measurably change the solve"
        changes[name] = {"common_solved_pixels": int(valid.sum()), "pixels_rotated_over_15_degrees": count,
                         "p95_rotation_degrees": float(np.percentile(degrees, 95))}
    assert stages[1]["regions"] == stages[0]["regions"] + 1
    assert stages[2]["dividers"] >= 1 and stages[2]["strokes"] >= 3
    result = {"pass": True, "upstream_commit": provenance["commit"], "selection_union_preserved": True,
              "dark_adapt": False, "cases": 18, "stages": stages, "direction_changes": changes,
              "scope": "Caller-provided UI snapshots; exact parity does not prove every pose is aesthetically correct."}
    (args.out / "ACCEPTANCE.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("upstream", "assets", "baseline", "split", "arc", "out"):
        parser.add_argument("--" + key, type=Path, required=True)
    run(parser.parse_args())
