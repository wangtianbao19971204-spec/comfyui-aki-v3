"""Issue 3: real HTTP fields must preserve upstream segmentation and snapping."""
import unittest
import json
from unittest import mock

import cv2
import numpy as np

import test_studio as baseline


def seam_document(size=100):
    art = np.full((size, size, 3), 150, np.uint8)
    left = np.zeros((size, size), bool); left[20:80, 10:40] = True
    right = np.zeros_like(left); right[20:80, 43:80] = True
    doc = baseline.vendor.Document(art, "seam.png")
    rid = doc.add_region("fabric")
    doc.segment_click(rid, 20, 50, False, [left] * 3, 0)
    return doc, rid, right


class NewFieldHTTP(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.StudioHTTP.asyncSetUp
    asyncTearDown = baseline.StudioHTTP.asyncTearDown

    async def test_ping_version_tracks_the_pinned_dependency(self):
        response = await self.client.get(self.base + "/api/ping")
        self.assertEqual(response.status, 200)
        result = await response.json()
        pin = json.loads((baseline.assets_ui.SOURCE_ROOT.parents[1] / "UPSTREAM.json").read_text(encoding="utf-8"))["commit"]
        self.assertEqual(result["upstream_commit"], pin)
        self.assertEqual(result["version"], "comfy-studio-" + pin[:12])

    def install(self, doc):
        studio = self.manager.sessions[self.opened["session"]].studio
        studio.replace(doc)
        self.docbase = self.base + "/api/doc/" + doc.id
        return studio

    async def post(self, suffix, data):
        response = await self.client.post(self.docbase + suffix, json=data)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def test_segment_seams_matches_direct_upstream_pixel_for_pixel(self):
        results = []
        for fields, enabled in (({}, False), ({"seams": False}, False), ({"seams": True}, True)):
            doc, rid, right = seam_document()
            reference, ref_rid, ref_right = seam_document()
            self.install(doc)
            try:
                with mock.patch.object(baseline.studio_module.models, "segment", return_value=([right] * 3, [1.] * 3)):
                    await self.post(f"/regions/{rid}/segment", {"x": 60, "y": 50, **fields})
                reference.segment_click(ref_rid, 60, 50, False, [ref_right] * 3, 0, seams=enabled)
                np.testing.assert_array_equal(doc.region(rid).mask, reference.region(ref_rid).mask)
                results.append(doc.region(rid).mask.copy())
            finally:
                reference.close()
        np.testing.assert_array_equal(results[0], results[1])
        self.assertFalse(np.array_equal(results[1], results[2]))
        self.assertEqual(int((results[2] & ~results[1]).sum()), 180)

    async def test_select_seams_toggle_and_omission_match_direct_upstream(self):
        doc, rid, right = seam_document()
        reference, ref_rid, ref_right = seam_document()
        self.install(doc)
        try:
            doc.segment_click(rid, 60, 50, False, [right] * 3, 0)
            reference.segment_click(ref_rid, 60, 50, False, [ref_right] * 3, 0)
            unfilled = doc.region(rid).mask.copy()
            for fields, seams in (({"seams": True}, True), ({}, None), ({"seams": None}, None), ({"seams": False}, False)):
                await self.post("/segment/select", {"k": 0, **fields})
                reference.select_segment(0, seams=seams)
                np.testing.assert_array_equal(doc.region(rid).mask, reference.region(ref_rid).mask)
                self.assertEqual(bool(doc.region(rid).mask[50, 41]), seams is not False)
            np.testing.assert_array_equal(doc.region(rid).mask, unfilled)
        finally:
            reference.close()

    async def test_divider_snap_matches_upstream_pixels_and_differs_from_zero(self):
        art = np.full((200, 200, 3), 150, np.uint8)
        cv2.line(art, (103, 0), (103, 199), (25, 25, 25), 2)
        ys = np.arange(40, 160, 2.)
        pts = np.stack([96 + np.random.default_rng(0).normal(0, 2.5, len(ys)), ys], 1).ravel().tolist()
        results = []
        for fields, radius in (({}, 0), ({"snap": 0}, 0), ({"snap": 14}, 14)):
            doc = baseline.vendor.Document(art.copy(), "snap.png")
            reference = baseline.vendor.Document(art.copy(), "snap.png")
            self.install(doc)
            try:
                await self.post("/dividers", {"pts": pts, **fields})
                reference.add_divider(pts, snap_radius=radius)
                np.testing.assert_array_equal(doc.dividers[0].pts, reference.dividers[0].pts)
                np.testing.assert_array_equal(doc.divider_alpha(), reference.divider_alpha())
                results.append(doc.divider_alpha().copy())
            finally:
                reference.close()
        np.testing.assert_array_equal(results[0], results[1])
        self.assertFalse(np.array_equal(results[1], results[2]))

    async def test_invalid_seams_returns_400_without_mutating_masks(self):
        doc, rid, right = seam_document()
        self.install(doc)
        doc.segment_click(rid, 60, 50, False, [right] * 3, 0)
        before = doc.region(rid).mask.copy()
        with mock.patch.object(baseline.studio_module.models, "segment", side_effect=AssertionError("invalid input reached inference")):
            for path, body in ((f"/regions/{rid}/segment", {"x": 60, "y": 50}), ("/segment/select", {"k": 0})):
                for value in (0, 1, "true", [], {}):
                    with self.subTest(path=path, value=value):
                        response = await self.client.post(self.docbase + path, json={**body, "seams": value})
                        self.assertEqual(response.status, 400, await response.text())
                        np.testing.assert_array_equal(doc.region(rid).mask, before)
            response = await self.client.post(self.docbase + f"/regions/{rid}/segment", json={"x": 60, "y": 50, "seams": None})
            self.assertEqual(response.status, 400)

    async def test_invalid_snap_returns_400_without_adding_dividers(self):
        doc = self.manager.sessions[self.opened["session"]].studio.doc
        before = len(doc.dividers)
        for value in (-1, max(doc.w, doc.h) + 1, float("nan"), float("inf"), True, None, [], {}, "12"):
            with self.subTest(value=value):
                response = await self.client.post(self.docbase + "/dividers", json={"pts": [30, 30, 40, 60], "snap": value})
                self.assertEqual(response.status, 400, await response.text())
                self.assertEqual(len(doc.dividers), before)


if __name__ == "__main__":
    unittest.main()
