"""Device routing and document invalidation, without a CUDA dependency."""
from contextlib import contextmanager
import importlib
import threading
import time
import types
import unittest
from unittest import mock

import numpy as np
import torch

from test_nodes import PLUGIN

solver = importlib.import_module(PLUGIN.__name__ + ".guide_solver")
models = importlib.import_module(PLUGIN.__name__ + ".studio_models")
document = importlib.import_module(PLUGIN.__name__ + ".studio_document")


class SolverRouting(unittest.TestCase):
    def test_manual_cpu_uses_original_algorithm_without_importing_gpu_backend(self):
        mask = np.ones((16, 16), bool)
        alpha = np.zeros((16, 16), np.uint8)
        with mock.patch.object(solver, "_cuda_job", side_effect=AssertionError("GPU accessed")), \
                mock.patch.object(models, "_device", side_effect=AssertionError("GPU queried")):
            info = {}
            self.assertIsNone(solver.solve_region(mask, alpha, info=info, preferred="cpu"))
        self.assertEqual(info["inference"]["backend"], "cpu")
        self.assertIsNone(info["inference"]["fallback"])

    def test_failed_cuda_releases_lease_before_original_cpu_retry(self):
        locked = []
        @contextmanager
        def lease(*args):
            locked.append(True)
            try:
                yield torch.device("cuda:0"), None
            finally:
                locked.clear()
        def cpu(*args):
            self.assertFalse(locked)
            return "original result"
        for failure, reason in [(ImportError("no cupy"), "gpu_dependency"),
                                (MemoryError("allocation failed"), "gpu_solver_failed")]:
            with self.subTest(reason=reason), mock.patch.object(models, "_device_lease", lease), \
                    mock.patch.object(solver, "_cuda_job", side_effect=failure), \
                    mock.patch.object(solver.original, "solve_region", side_effect=cpu):
                info = {}
                self.assertEqual(solver.solve_region(np.ones((16, 16), bool), None, info=info), "original result")
                self.assertEqual(info["inference"]["fallback"], reason)

    def test_device_change_discards_inflight_result_without_changing_guides(self):
        entered, finish = threading.Event(), threading.Event()
        calls = []
        def solve(mask, alpha, walls, info, *, preferred):
            calls.append(preferred)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(finish.wait(5))
            info["inference"] = {"backend": "cpu", "preferred": preferred}
            return None
        art = np.zeros((64, 64, 3), np.uint8)
        with mock.patch.object(solver, "solve_region", side_effect=solve):
            doc = document.Document.from_snapshot(art, "test.png", None,
                [("leg", "#123456", np.ones((64, 64), bool))],
                [(np.array([[8, 32], [54, 32]], float), 0)])
            try:
                self.assertTrue(entered.wait(5))
                before = doc.regions[0].mask.copy()
                edits = doc.edits
                doc.set_device("cpu")
                finish.set()
                self.assertTrue(doc.wait_idle(5))
                self.assertEqual(calls, ["gpu", "cpu"])
                self.assertEqual(doc.state()["regions"][0]["inference"]["preferred"], "cpu")
                np.testing.assert_array_equal(doc.regions[0].mask, before)
                self.assertEqual(doc.edits, edits)
            finally:
                finish.set()
                doc.close()
                doc._worker.join(5)


if __name__ == "__main__":
    unittest.main()
