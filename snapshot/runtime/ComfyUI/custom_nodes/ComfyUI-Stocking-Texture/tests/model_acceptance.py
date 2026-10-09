"""Compare actual local SAM/depth inference against an independent upstream checkout."""
import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import types

import cv2
import numpy as np
from PIL import Image


def package(name, root):
    spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(args):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    args.out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    package("stocking_model_candidate", root)
    package("stocking_model_reference", args.upstream / "stocking")
    models = importlib.import_module("stocking_model_candidate.studio_models")
    engine = importlib.import_module("stocking_model_candidate.engine")
    sam = importlib.import_module("stocking_model_reference.sam")
    depth = importlib.import_module("stocking_model_reference.depth")
    art = np.asarray(Image.open(args.image).convert("RGB"))
    guides = engine.parse_guides(args.guides.read_text(encoding="utf-8"), art.shape[1], art.shape[0])
    mask = engine.region_maps(guides)[0][0] > 0
    y, x = np.unravel_index(cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5).argmax(), mask.shape)
    paths = {"sam": args.sam, "depth": args.depth}
    t0 = time.perf_counter()
    masks, scores = models.segment(art, int(x), int(y), paths)
    sam_seconds = time.perf_counter() - t0
    print(json.dumps({"stage": "candidate_sam", "seconds": sam_seconds, "areas": [int(m.sum()) for m in masks]}), flush=True)
    sam.checkpoint_path = lambda: str(args.sam)
    sam.pick_device = lambda torch: ("cpu", "CPU")
    service = sam.SamService()
    service._load()
    doc = types.SimpleNamespace(art=art, w=art.shape[1], h=art.shape[0], id="parity",
                                sam_embedding=None, sam_state="waiting", disparity=None)
    expected_masks, _, expected_scores = service.candidates(doc, int(x), int(y))
    for actual, expected in zip(masks, expected_masks):
        np.testing.assert_array_equal(actual, expected)
    np.testing.assert_allclose(scores, expected_scores, atol=0, rtol=0)
    for i, m in enumerate(masks):
        Image.fromarray(m.astype(np.uint8) * 255).save(args.out / f"sam-{i}.png")
    service.forget(doc)
    del service
    t0 = time.perf_counter()
    disparity = models.estimate_depth(art, paths)
    depth_seconds = time.perf_counter() - t0
    print(json.dumps({"stage": "candidate_depth", "seconds": depth_seconds, "shape": list(disparity.shape)}), flush=True)
    depth.LOCAL = str(args.depth)
    reference = depth.DepthService()
    reference._load()
    expected_depth = reference.disparity(doc)
    np.testing.assert_allclose(disparity, expected_depth, atol=1e-5, rtol=1e-6)
    np.save(args.out / "depth.npy", disparity, allow_pickle=False)
    span = max(float(disparity.max() - disparity.min()), 1e-9)
    Image.fromarray(np.round((disparity - disparity.min()) / span * 255).astype(np.uint8)).save(args.out / "depth.png")
    receipt = {"pass": True, "image_sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
               "sam_checkpoint_sha256": hashlib.sha256(args.sam.read_bytes()).hexdigest(),
               "depth_checkpoint_sha256": hashlib.sha256((args.depth / "model.safetensors").read_bytes()).hexdigest(),
               "point": [int(x), int(y)], "sam_candidates_equal": 3,
               "sam_areas": [int(m.sum()) for m in masks], "sam_scores": scores,
               "depth_max_error": float(np.max(np.abs(disparity - expected_depth))),
               "sam_seconds": sam_seconds, "depth_seconds": depth_seconds, "device": "CPU"}
    (args.out / "ACCEPTANCE.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--guides", type=Path, required=True)
    parser.add_argument("--sam", type=Path, required=True)
    parser.add_argument("--depth", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args())
