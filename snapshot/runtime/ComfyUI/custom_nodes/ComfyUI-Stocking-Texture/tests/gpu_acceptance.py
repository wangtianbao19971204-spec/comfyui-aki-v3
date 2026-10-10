"""Real local CPU/CUDA latency, mask, depth and offload comparison. No downloads."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
from unittest import mock

import numpy as np
from PIL import Image
import torch


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(args):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if not torch.cuda.is_available():
        raise RuntimeError("This acceptance requires an available CUDA GPU")
    args.out.mkdir(parents=True, exist_ok=False)
    models = load("candidate_models", Path(__file__).resolve().parents[1] / "studio_models.py")
    baseline = load("baseline_models", args.baseline)
    art = np.asarray(Image.open(args.image).convert("RGB"))
    paths = {"sam": args.sam, "depth": args.depth}
    rows, references = [], []
    def measured(label, operation, info):
        torch.cuda.synchronize()
        before = torch.cuda.memory_allocated()
        torch.cuda.reset_peak_memory_stats()
        start = time.perf_counter()
        result = operation()
        torch.cuda.synchronize()
        row = dict(label=label, wall_seconds=time.perf_counter() - start, **info,
                   allocated_before=before, allocated_after=torch.cuda.memory_allocated(),
                   peak_allocated=torch.cuda.max_memory_allocated())
        rows.append(row)
        print(json.dumps(row), flush=True)
        for cache in (models._sam_cache, models._depth_cache):
            if "model" in cache:
                assert all(t.device.type == "cpu" for t in
                           list(cache["model"].parameters()) + list(cache["model"].buffers()))
        assert all(entry[0].device.type == "cpu" for entry in models._embeddings.values())
        return result

    for k, point in enumerate(args.point):
        refs = measured(f"baseline_cpu_{k}", lambda: baseline.segment(art, *point, paths), {})
        references.append(refs)
    for k, point in enumerate(args.point):
        info = {}
        with mock.patch.object(models, "_device", return_value=torch.device("cpu")):
            actual = measured(f"cached_cpu_{k}", lambda: models.segment(art, *point, paths, info=info), info)
        np.testing.assert_array_equal(actual[0], references[k][0])
        np.testing.assert_array_equal(actual[1], references[k][1])
    # Start a fresh model/feature cache so the first GPU click includes model loading.
    models._sam_cache.clear(); models._embeddings.clear()
    masks_comparison = []
    for k, point in enumerate(args.point * 2):
        info = {}
        actual = measured(f"gpu_{k}", lambda: models.segment(art, *point, paths, info=info), info)
        if not info["backend"].startswith("cuda"):
            raise AssertionError("GPU acceptance fell back to CPU")
        ref_masks, ref_scores = references[k % len(args.point)]
        for j, (mask, ref) in enumerate(zip(actual[0], ref_masks)):
            union = int(np.logical_or(mask, ref).sum())
            overlap = int(np.logical_and(mask, ref).sum())
            row = {"click": k, "candidate": j, "iou": overlap / max(union, 1),
                   "changed_pixels": int(np.count_nonzero(mask != ref)), "area": int(mask.sum()),
                   "cpu_area": int(ref.sum()), "score_error": abs(actual[1][j] - ref_scores[j])}
            masks_comparison.append(row)
            Image.fromarray(mask.astype(np.uint8) * 255).save(args.out / f"gpu-{k}-{j}.png")
        if k > 0:
            assert info["embedding_cached"] and info["model_cached"]
    # Another image must be encoded, and returning to the original must reuse its features.
    for name, image, expected in (("other_image", np.ascontiguousarray(art[:, ::-1]), False),
                                  ("return_image", art, True)):
        info = {}
        measured(name, lambda: models.segment(image, *args.point[0], paths, info=info), info)
        assert info["embedding_cached"] is expected
    baseline_depth = measured("baseline_depth", lambda: baseline.estimate_depth(art, paths), {})
    info = {}
    with mock.patch.object(models, "_device", return_value=torch.device("cpu")):
        cpu_depth = measured("cached_cpu_depth", lambda: models.estimate_depth(art, paths, info=info), info)
    np.testing.assert_array_equal(cpu_depth, baseline_depth)
    for k in range(2):
        info = {}
        gpu_depth = measured(f"gpu_depth_{k}", lambda: models.estimate_depth(art, paths, info=info), info)
        assert info["backend"].startswith("cuda")
    np.save(args.out / "cpu-depth.npy", baseline_depth, allow_pickle=False)
    np.save(args.out / "gpu-depth.npy", gpu_depth, allow_pickle=False)
    error = np.abs(gpu_depth - baseline_depth)
    span = max(float(np.ptp(baseline_depth)), 1e-9)
    min_iou = min(row["iou"] for row in masks_comparison)
    depth_error = {"max": float(error.max()), "mean": float(error.mean()),
                   "max_divided_by_range": float(error.max()) / span}
    # cuBLAS keeps a small per-thread workspace after tensors are offloaded.
    # Clear it ONLY in this isolated validation process to distinguish workspace
    # from leaked tensors. Production inference never purges global CUDA caches.
    workspace_bytes = torch.cuda.memory_allocated()
    torch._C._cuda_clearCublasWorkspaces()
    torch.cuda.synchronize()
    remaining_bytes = torch.cuda.memory_allocated()
    assert remaining_bytes == 0, "Live CUDA tensors remained after clearing isolated cuBLAS workspaces"
    receipt = {"pass": min_iou >= .995 and depth_error["max_divided_by_range"] <= .001,
               "thresholds": {"sam_min_iou": .995, "depth_max_error_divided_by_range": .001},
               "gpu": torch.cuda.get_device_name(), "torch": torch.__version__,
               "image_sha256": sha(args.image), "sam_sha256": sha(args.sam),
               "depth_sha256": sha(args.depth / "model.safetensors"),
               "baseline_source_sha256": sha(args.baseline),
               "candidate_source_sha256": sha(Path(models.__file__)),
               "cuda_workspace_bytes": workspace_bytes, "cuda_tensors_after_workspace_release": remaining_bytes,
               "points": args.point, "cpu_exact": True, "rows": rows,
               "sam": masks_comparison, "depth": depth_error}
    (args.out / "ACCEPTANCE.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": receipt["pass"], "sam_min_iou": min_iou, "depth": depth_error}), flush=True)
    assert receipt["pass"], "Inspect CPU/GPU differences before release"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("baseline", "image", "sam", "depth", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--point", nargs=2, type=int, action="append", required=True)
    run(parser.parse_args())
