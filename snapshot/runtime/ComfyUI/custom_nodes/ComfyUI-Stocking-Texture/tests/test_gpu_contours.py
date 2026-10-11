"""Opt-in CUDA equivalence checks: STOCKING_TEST_CUDA=1, with optional deps installed."""
import importlib
import os
import unittest

import contourpy
import cv2
import numpy as np

from test_nodes import PLUGIN


def canonical(lines):
    result = []
    for line in lines:
        points = [tuple(p.round(9)) for p in line]
        if points[0] == points[-1]:
            points = points[:-1]
            smallest = min(points)
            rotations = [points[k:] + points[:k] for k in range(len(points)) if points[k] == smallest]
            points = min(rotations + [p[:1] + p[:0:-1] for p in rotations])
            reverse = points
        else:
            reverse = points[::-1]
        result.append(tuple(min(points, reverse)))
    return sorted(result)


@unittest.skipUnless(os.environ.get("STOCKING_TEST_CUDA") == "1", "explicit CUDA acceptance only")
class GPUContours(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cupy
        cls.cp = cupy
        cls.contours = importlib.import_module(PLUGIN.__name__ + ".gpu_contours").Contours
        cls.solver = importlib.import_module(PLUGIN.__name__ + ".guide_solver")

    def test_masked_corners_saddles_exact_vertices_and_closed_loops(self):
        cases = []
        for bits in range(16):
            z = np.array([[bits & 1, (bits >> 1) & 1], [(bits >> 3) & 1, (bits >> 2) & 1]], float)
            for masked in range(5):
                valid = np.ones((2, 2), bool)
                if masked:
                    valid.flat[masked - 1] = False
                cases.append((z, valid, np.array([0., .5, 1.])))
        rng = np.random.default_rng(171)
        for k in range(45):
            z = rng.normal(size=(17, 19)) if k < 30 else rng.integers(-2, 3, (17, 19)).astype(float)
            valid = rng.random(z.shape) > (.1 if k % 2 else 0)
            cases.append((z, valid, np.arange(-3., 3.1, .5)))
        y, x = np.mgrid[-30:31, -32:33]
        cases.append((x * x + y * y, np.ones(x.shape, bool), np.arange(1., 850., 50.)))
        for k, (z, valid, levels) in enumerate(cases):
            gpu = self.contours(z, valid, levels, self.cp)
            cpu = contourpy.contour_generator(z=np.ma.array(z, mask=~valid))
            for level in levels:
                with self.subTest(case=k, level=level):
                    self.assertEqual(canonical(cpu.lines(float(level))), canonical(gpu.lines(level)))

    def test_no_strokes_occlusion_wall_and_disconnected_domain_release_pool(self):
        y, x = np.mgrid[:192, :160]
        base = (x > 16) & (x < 143) & (y > 8) & (y < 184)
        for kind in ("empty", "plain", "hole", "split", "wall"):
            mask = base.copy()
            alpha = np.zeros(mask.shape, np.uint8)
            walls = None
            if kind != "empty":
                for row in (40, 140):
                    cv2.line(alpha, (22, row), (137, row + 10), 255, 3)
            if kind == "hole":
                mask[(x - 65) ** 2 + (y - 95) ** 2 < 18 ** 2] = False
            if kind == "split":
                mask[78:104] = False
            if kind == "wall":
                walls = np.zeros(mask.shape, np.uint8)
                cv2.line(walls, (80, 8), (80, 128), 1, 2)
                walls = walls.astype(bool)
            info = {}
            gpu = self.solver.solve_region(mask, alpha, walls, info)
            cpu = self.solver.original.solve_region(mask, alpha, walls)
            with self.subTest(kind=kind):
                self.assertTrue(info["inference"]["backend"].startswith("cuda"), info)
                self.assertEqual(info["inference"]["pool_used_bytes"], 0)
                self.assertEqual(info["inference"]["pool_retained_bytes"], 0)
                if cpu is None:
                    self.assertIsNone(gpu)
                else:
                    for index, (a, b) in enumerate(zip(cpu, gpu)):
                        np.testing.assert_array_equal(np.isnan(a), np.isnan(b))
                        self.assertLess(float(np.nanmax(np.abs(a - b))), .5 if index == 3 else 1e-5)


if __name__ == "__main__":
    unittest.main()
