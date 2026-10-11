"""GPU kernels around the pinned guide algorithm, with a complete CPU fallback.

Sparse solves and multi-level contour extraction run on CUDA. Region topology,
polyline assembly and the author's OpenCV operations stay on the host. No model
is required. Each solve uses a private module namespace and GPU memory pool.
"""
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import types

import numpy as np

from . import studio_models as models
from .vendor import guide_fields as original
from .gpu_contours import Contours


@lru_cache(maxsize=1)
def _algorithm():
    return compile(Path(original.__file__).read_text(encoding="utf-8"), original.__file__, "exec")


def _cuda_module(cp, stats):
    from cupyx.scipy import sparse
    from cupy_backends.cuda.libs import cusolver
    from cupyx.scipy.spatial import KDTree

    module = types.ModuleType(__package__ + ".vendor._cuda_guide_fields")
    module.__package__ = original.__package__
    exec(_algorithm(), module.__dict__)

    def factorized(matrix):
        a = sparse.csr_matrix(matrix)
        a.sum_duplicates()
        a.sort_indices()

        def solve(rhs):
            b = cp.asarray(rhs, dtype=cp.float64)
            def column(vector):
                vector = cp.ascontiguousarray(vector)
                out = cp.empty_like(vector)
                singular = np.empty(1, np.int32)
                # All upstream normal equations are SPD (Laplacian + positive
                # ridge). GPU sparse Cholesky with nested dissection avoids the
                # large QR fill-in cost on long, narrow stocking regions.
                cusolver.dcsrlsvchol(cp.cuda.device.get_cusolver_sp_handle(), a.shape[0], a.nnz,
                    a._descr.descriptor, a.data.data.ptr, a.indptr.data.ptr, a.indices.data.ptr,
                    vector.data.ptr, 0., 3, out.data.ptr, singular.ctypes.data)
                if singular[0] >= 0:
                    raise ArithmeticError("CUDA guide matrix is singular")
                return out
            x = column(b) if b.ndim == 1 else cp.stack([column(b[:, i]) for i in range(b.shape[1])], axis=1)
            residual = cp.linalg.norm(a @ x - b) / cp.maximum(cp.linalg.norm(b), 1.)
            error = float(residual.get())
            if not np.isfinite(error) or error > 1e-7:
                raise ArithmeticError("CUDA guide residual exceeds tolerance")
            stats["sparse_solves"] = stats.get("sparse_solves", 0) + 1
            stats["max_residual"] = max(stats.get("max_residual", 0.), error)
            return x.get()
        return solve

    class Nearest:
        def __init__(self, points):
            self.points = points
            self.cpu_tree = None
            self.tree = KDTree(cp.asarray(points, dtype=cp.float64))

        def query(self, points, **kwargs):
            kwargs.pop("workers", None)
            k = kwargs.pop("k", 1)
            distances, indices = self.tree.query(cp.asarray(points, dtype=cp.float64), k=k + 1, **kwargs)
            distances, indices = distances.get(), indices.get()
            # An equally near sample can belong to a different course/island.
            # Preserve the author's SciPy tie selection for just those rows.
            # CUDA still finds neighbours for the whole image in one query.
            finite = np.isfinite(distances[:, 1:])
            adjacent = np.where(finite, distances[:, 1:], 0.)
            previous = np.where(finite, distances[:, :-1], 1.)
            ties = np.any(finite & (np.abs(adjacent - previous) <= 1e-8 * np.maximum(1., adjacent)), axis=1)
            distances, indices = distances[:, :k].copy(), indices[:, :k].copy()
            if k == 1:
                distances, indices = distances[:, 0], indices[:, 0]
            if ties.any():
                if self.cpu_tree is None:
                    self.cpu_tree = original.cKDTree(self.points)
                distances[ties], indices[ties] = self.cpu_tree.query(points[ties], k=k, **kwargs)
                stats["nearest_tie_rows"] = stats.get("nearest_tie_rows", 0) + int(ties.sum())
            stats["nearest_queries"] = stats.get("nearest_queries", 0) + 1
            return distances, indices

    module.spla = types.SimpleNamespace(factorized=factorized,
        spsolve=lambda matrix, rhs: factorized(matrix)(rhs))
    module.cKDTree = Nearest
    across = module.solve_across

    def solve_across(region, v, nx, ny, step=2., medial_sigma=12, post_sigma=2., cut=None):
        inner = region & np.isfinite(v)
        if cut is not None:
            inner &= ~cut
        levels = np.arange(np.percentile(v[inner], .5), np.percentile(v[inner], 99.5), step)
        contours = Contours(v, inner, levels, cp)
        stats["contour_levels"] = len(levels)
        module.contourpy = types.SimpleNamespace(contour_generator=lambda **kwargs: contours)
        return across(region, v, nx, ny, step, medial_sigma, post_sigma, cut)

    module.solve_across = solve_across
    return module


@contextmanager
def _cuda_job(device, stats):
    # Torch has already loaded its CUDA DLLs in a ComfyUI process. CuPy remains
    # optional; missing/incompatible installations fall back without an installer.
    import cupy as cp
    with cp.cuda.Device(device.index or 0):
        pool = cp.cuda.MemoryPool()
        stream = cp.cuda.Stream(non_blocking=True)
        module = None
        try:
            with cp.cuda.using_allocator(pool.malloc), stream:
                module = _cuda_module(cp, stats)
                yield module
        finally:
            stream.synchronize()
            if module is not None:
                module.__dict__.clear()
            stats["pool_peak_bytes"] = pool.total_bytes()
            pool.free_all_blocks()
            stats["pool_used_bytes"] = pool.used_bytes()
            stats["pool_retained_bytes"] = pool.total_bytes()


def solve_region(mask, alpha, walls=None, info=None, *, preferred="gpu"):
    info = {} if info is None else info
    stats = {"preferred": models.preference(preferred)}
    info["inference"] = stats
    # Conservative allowance for the grid, emitted contours and sparse factors.
    required = max(256 * 1024 ** 2, mask.size * 320)
    fallback = None
    with models._device_lease(required, preferred) as (device, reason):
        if device.type == "cuda":
            try:
                with _cuda_job(device, stats) as algorithm:
                    result = algorithm.solve_region(mask, alpha, walls, info)
                stats.update(backend=str(device), device=models._label(device), fallback=None)
                return result
            except (ImportError, OSError) as exc:
                fallback = "gpu_dependency"
                stats["detail"] = str(exc)[:240]
            except Exception as exc:
                fallback = "gpu_solver_failed"
                stats["detail"] = str(exc)[:240]
        else:
            fallback = reason or ("cuda_unavailable" if preferred == "gpu" else None)
    # Discard partial CUDA wall metadata and release the GPU/queue lease before
    # the original CPU algorithm runs, including numeric and allocation failures.
    info.pop("walls", None)
    info.pop("cut", None)
    result = original.solve_region(mask, alpha, walls, info)
    stats.update(backend="cpu", device="CPU", fallback=fallback)
    return result
