"""Document worker adaptation; the author's versioned document stays unchanged."""
import time

import numpy as np

from . import guide_solver, studio_models
from .vendor.document import Document as OriginalDocument, Solved, SOLVE_CACHE, iso_lines, wall_polylines, tr


class Document(OriginalDocument):
    default_device = "gpu"

    def __init__(self, *args, **kwargs):
        self.compute_device = self.default_device
        self.compute_revision = 0
        super().__init__(*args, **kwargs)

    @classmethod
    def configured(cls, preferred):
        class ConfiguredDocument(cls):
            default_device = studio_models.preference(preferred)
        return ConfiguredDocument

    def set_device(self, preferred):
        with self._cv:
            self.compute_device = studio_models.preference(preferred)
            self.compute_revision += 1
            self._solves.clear()
            self._cv.notify_all()

    def _work(self):
        # Same publication/cache contract as the pinned Document._work. Device
        # changes invalidate in-flight results without editing masks or history.
        while True:
            with self._cv:
                job = None
                while not self._closed and (job := self._next_job()) is None:
                    self._cv.wait()
                if self._closed:
                    return
                rid, inp = job
                revision, preferred = self.compute_revision, self.compute_device
                self._solving = (rid, inp.sig)
            self._emit(type="solving", region=rid)
            started = time.perf_counter()
            fields, error, courses, wales, unguided, cut, wall_lines = None, None, [], [], None, None, []
            info = {}
            try:
                res = guide_solver.solve_region(inp.mc, inp.alpha, inp.walls, info, preferred=preferred)
                if res is not None:
                    fields = tuple(f.astype(np.float32) for f in res)
                    bare = inp.mc & np.isnan(fields[0])
                    solved = inp.mc & ~bare
                    if not solved.any() or not all(np.isfinite(f[solved]).all() for f in fields):
                        fields, error = None, tr("求解失败（数值发散），试着调整走向线")
                    else:
                        fields = tuple(np.where(bare, np.float32(0), f) for f in fields)
                        unguided = bare if bare.any() else None
                        y0, _, x0, _ = inp.box
                        cut = info.get("cut")
                        lines_in = solved if cut is None else solved & ~cut
                        courses = iso_lines(fields[0], lines_in, self.course_step, x0, y0)
                        wales = iso_lines(fields[3], lines_in, self.course_step, x0, y0)
                        if inp.auto is not None:
                            wall_lines = wall_polylines(inp.auto, x0, y0)
            except Exception as exc:
                error = tr("求解出错：{error}", error=exc)
            seconds = time.perf_counter() - started
            with self._cv:
                self._solving = None
                if self._closed:
                    return
                if revision != self.compute_revision:
                    continue
                cache = self._solves.setdefault(rid, {})
                cache.pop(inp.sig, None)
                solved = Solved(inp.sig, inp, fields, error, seconds, courses, wales, next(self._versions),
                                unguided, cut, wall_lines)
                solved.inference = info.get("inference", {})
                cache[inp.sig] = solved
                while len(cache) > SOLVE_CACHE:
                    del cache[next(iter(cache))]
            self._emit(type="solved", region=rid, seconds=round(seconds, 2), error=error)

    def state(self):
        with self.lock:
            result = super().state()
            _, prep = self._prepare()
            for region in result["regions"]:
                solved = self._shown(region["id"], prep.get(region["id"]))
                region["inference"] = getattr(solved, "inference", {})
            return result
