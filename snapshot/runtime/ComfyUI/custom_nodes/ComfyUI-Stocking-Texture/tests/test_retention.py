"""Age-based cleanup cannot remove active drafts/downloads or workflow assets."""
import os
from pathlib import Path
import tempfile
import time
import unittest

import test_studio as baseline

store = baseline.store


def file_at(path, age_days):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"retention fixture")
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


class RetentionContracts(unittest.TestCase):
    def test_only_expired_unreferenced_owned_transients_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = [file_at(root/"drafts"/("a"*32+".json"), 10), file_at(root/"exports"/("a"*32+"-old.png"), 10)]
            active = [file_at(root/"drafts"/("b"*32+".json"), 10), file_at(root/"exports"/("b"*32+"-open.psd"), 10)]
            keep = [file_at(root/"drafts"/("c"*32+".json"), 1), file_at(root/"exports"/("c"*32+"-new.png"), 1),
                    file_at(root/"assets"/("d"*64+".png"), 100), file_at(root/"preferences.json", 100),
                    file_at(root/"drafts"/"unknown.json", 100), file_at(root/"exports/nested"/("a"*32+"-old.png"), 100)]
            result = store.cleanup_transient(root, active, days=7)
            self.assertEqual(len(result["removed"]), 2)
            self.assertEqual(result["errors"], [])
            self.assertTrue(all(not p.exists() for p in old))
            self.assertTrue(all(p.exists() for p in active + keep))

    def test_zero_disables_cleanup_and_invalid_configuration_never_deletes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = file_at(root/"drafts"/("a"*32+".json"), 100)
            self.assertEqual(store.cleanup_transient(root, days=0)["removed"], [])
            for value in (-1, float("nan"), float("inf"), True, "bad"):
                with self.assertRaises(ValueError): store.cleanup_transient(root, days=value)
            self.assertTrue(path.exists())


class RetentionHTTP(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.StudioHTTP.asyncSetUp
    asyncTearDown = baseline.StudioHTTP.asyncTearDown

    async def test_create_cleans_expired_files_but_preserves_open_session_and_assets(self):
        entry = self.manager.sessions[self.opened["session"]]
        studio = entry.studio
        studio.save_draft()
        root = studio.preferences.path.parent
        draft = root/"drafts"/(studio.draft_id+".json")
        old_stamp = time.time() - 10 * 86400
        os.utime(draft, (old_stamp, old_stamp))
        download = file_at(root/"exports"/("a"*32+"-active.png"), 10)
        entry.downloads["a"*32] = download
        unused = file_at(root/"exports"/("b"*32+"-unused.png"), 10)
        orphan = file_at(root/"drafts"/("b"*32+".json"), 10)
        asset = next(self.assets.glob("*.png"))
        original_asset = asset.read_bytes()
        os.utime(asset, (old_stamp, old_stamp))
        response = await self.client.post(baseline.api.PREFIX, json={"project": self.project})
        self.assertEqual(response.status, 200, await response.text())
        self.assertTrue(draft.exists() and download.exists())
        self.assertFalse(unused.exists() or orphan.exists())
        self.assertEqual(asset.read_bytes(), original_asset)

    async def test_reopening_expired_draft_protects_it_before_cleanup(self):
        old_id = "f" * 32
        entry = self.manager.sessions[self.opened["session"]]
        root = entry.studio.preferences.path.parent
        path = root/"drafts"/(old_id+".json")
        store.atomic_json(path, {"base_hash": store.project_digest(self.project), "project": self.project})
        stamp = time.time() - 10 * 86400
        os.utime(path, (stamp, stamp))
        response = await self.client.post(baseline.api.PREFIX, json={"project": self.project, "draft_id": old_id})
        self.assertEqual(response.status, 200, await response.text())
        self.assertTrue((await response.json())["restored"])
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
