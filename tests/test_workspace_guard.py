import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workspace_guard as guard


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / "file.py"
        self.file.write_text("old")
        self.baseline = self.root / "baseline.json"
        self.before = guard.digest(self.file)
        self.baseline.write_text(json.dumps({"runtime": str(self.root), "health": {"pid": 1},
                                            "files": {"file.py": guard.file_state(self.file)}}))

    @patch.object(guard, "health", return_value={"pid": 1})
    def test_verified_unchanged(self, _):
        self.assertTrue(guard.verify(self.baseline)["pass"])

    @patch.object(guard, "health", return_value={"pid": 2})
    def test_service_drift(self, _):
        self.assertFalse(guard.verify(self.baseline)["pass"])

    @patch.object(guard, "health", return_value={"pid": 1})
    def test_approval_binds_before_and_after_bytes(self, _):
        self.file.write_text("safe")
        self.assertFalse(guard.verify(self.baseline)["pass"])
        spec = self.root / "allowed.json"
        spec.write_text(json.dumps({"files": [{"source": "file.py", "before_sha256": self.before,
                                              "after_sha256": guard.digest(self.file)}]}))
        result = guard.verify(self.baseline, approved_changes=spec)
        self.assertTrue(result["pass"])
        self.assertEqual(result["approved_changed_files"], ["file.py"])
        self.file.write_text("later unapproved drift")
        self.assertFalse(guard.verify(self.baseline, approved_changes=spec)["pass"])

    @patch.object(guard, "health", return_value={"pid": 1})
    def test_stale_approval_is_rejected(self, _):
        spec = self.root / "allowed.json"
        spec.write_text(json.dumps({"files": [{"source": "file.py", "before_sha256": "0" * 64,
                                              "after_sha256": guard.digest(self.file)}]}))
        with self.assertRaises(ValueError):
            guard.verify(self.baseline, approved_changes=spec)


if __name__ == "__main__":
    unittest.main()
