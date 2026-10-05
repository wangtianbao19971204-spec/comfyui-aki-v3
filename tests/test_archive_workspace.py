import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/archive_workspace.ps1"


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell archive tool")
class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "runtime"
        self.archive = self.root / "external"
        self.workspace.mkdir()
        self.archive.mkdir()
        (self.workspace / "main").mkdir()
        (self.workspace / "old").mkdir()
        (self.workspace / "old/value.txt").write_text("recoverable", encoding="utf-8")
        self.plan = self.root / "plan.json"
        self.receipt = self.archive / "receipt.json"
        self.spec = {"workspace": str(self.workspace), "archive_root": str(self.archive),
                     "protected_paths": ["main"], "items": [{"source": "old", "target": "old", "reason": "fixture"}]}

    def run_tool(self, *args):
        self.plan.write_text(json.dumps(self.spec), encoding="utf-8")
        return subprocess.run(["pwsh", "-NoProfile", "-File", str(SCRIPT), "-Plan", str(self.plan),
                               "-Receipt", str(self.receipt), *args], capture_output=True, encoding="utf-8")

    def review(self):
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["review_sha256"]

    def test_plan_then_recoverable_move(self):
        sha = self.review()
        self.assertTrue((self.workspace / "old/value.txt").exists())
        result = self.run_tool("-Mode", "Apply", "-ReviewSha256", sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.archive / "old/value.txt").read_text(), "recoverable")
        self.assertFalse((self.workspace / "old").exists())
        self.assertTrue(Path(str(self.receipt) + ".applied.jsonl").exists())

    def test_drift_refuses_move(self):
        sha = self.review()
        (self.workspace / "old/value.txt").write_text("changed")
        result = self.run_tool("-Mode", "Apply", "-ReviewSha256", sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.workspace / "old/value.txt").exists())

    def test_protected_root_refused(self):
        self.spec["items"][0]["source"] = "main"
        self.assertNotEqual(self.run_tool().returncode, 0)

    def test_parent_escape_refused(self):
        self.spec["items"][0]["target"] = "../escaped"
        self.assertNotEqual(self.run_tool().returncode, 0)

    def test_protected_descendant_needs_exact_reviewed_exception(self):
        self.spec['protected_paths'] = ['old']
        self.spec['items'][0]['source'] = 'old/value.txt'
        self.assertNotEqual(self.run_tool().returncode, 0)
        self.spec['allowed_protected_sources'] = ['old/value.txt']
        self.assertEqual(self.run_tool().returncode, 0)

    def test_empty_and_windows_alias_paths_refused(self):
        for value in ['', 'old.', 'old ', 'old//value.txt', 'CON.txt']:
            with self.subTest(value=value):
                self.spec['items'][0]['source'] = value
                self.assertNotEqual(self.run_tool().returncode, 0)

    def test_active_lock_refused(self):
        (self.workspace / "old/run.lock").write_text("lock")
        self.assertNotEqual(self.run_tool().returncode, 0)

    def test_existing_target_refused(self):
        (self.archive / "old").mkdir()
        self.assertNotEqual(self.run_tool().returncode, 0)

    def test_overlapping_sources_refused(self):
        self.spec["items"].append({"source": "old/value.txt", "target": "copy", "reason": "duplicate"})
        self.assertNotEqual(self.run_tool().returncode, 0)

    def test_metadata_mode_is_explicit_and_bound_to_review(self):
        result = self.run_tool('-InventoryMode', 'Metadata')
        self.assertEqual(result.returncode, 0, result.stderr)
        sha = json.loads(result.stdout)['review_sha256']
        report = json.loads(self.receipt.read_text(encoding='utf-8-sig'))
        self.assertEqual(report['inventory_mode'], 'Metadata')
        self.assertNotIn('sha256', report['moves'][0]['files'][0])
        self.assertNotEqual(self.run_tool('-Mode', 'Apply', '-ReviewSha256', sha).returncode, 0)
        result = self.run_tool('-Mode', 'Apply', '-ReviewSha256', sha, '-InventoryMode', 'Metadata')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_link_preservation_does_not_traverse_loop_or_outside_target(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'preserved.txt').write_text('untouched')
        try:
            (self.workspace / 'old/loop').symlink_to(self.workspace / 'old', target_is_directory=True)
            (self.workspace / 'old/external').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation privilege unavailable')
        self.assertNotEqual(self.run_tool().returncode, 0)
        flags = ['-InventoryMode', 'Metadata', '-PreserveReparsePoints']
        result = self.run_tool(*flags)
        self.assertEqual(result.returncode, 0, result.stderr)
        sha = json.loads(result.stdout)['review_sha256']
        report = json.loads(self.receipt.read_text(encoding='utf-8-sig'))
        self.assertEqual(len(report['moves'][0]['files']), 3)
        result = self.run_tool('-Mode', 'Apply', '-ReviewSha256', sha, *flags)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.archive / 'old/loop').is_symlink())
        self.assertEqual((outside / 'preserved.txt').read_text(), 'untouched')


if __name__ == "__main__":
    unittest.main()
