"""Source diffs must not erase small upstream revisions or identity boundaries."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "snapshot/runtime/benchmark_reports/source_update_flow/audit_current.py"
SPEC = importlib.util.spec_from_file_location("audit_current", SOURCE)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class SourceAuditTests(unittest.TestCase):
    def test_missing_null_and_json_types_remain_different(self):
        self.assertEqual(audit.differences({}, {"rating": None}), [
            {"path": "/rating", "old_present": False, "new_present": True, "new": None}])
        for a, b in [(False, 0), (True, 1), (1, 1.0), ("1", 1)]:
            with self.subTest(a=a, b=b):
                self.assertFalse(audit.equal(a, b))
                self.assertEqual(len(audit.differences({"v": a}, {"v": b})), 1)

    def test_arrays_and_all_prompt_fields_are_preserved(self):
        old = {"entries": [{"id": "a", "tags": "Blue_hair", "negative": "old",
                             "characterPrompts": [{"prompt": "A", "negative": "X"}],
                             "images": ["1", "2"], "params": {"seed": 1}}], "tree": ["a", "b"]}
        new = json.loads(json.dumps(old))
        entry = new["entries"][0]
        entry.update(tags="blue hair", negative="new", images=["2", "1"])
        entry["characterPrompts"][0]["negative"] = "Y"
        entry["params"]["seed"] = 1.0
        new["tree"].reverse()
        result = audit.document_delta(old, new)
        self.assertEqual(set(result["field_counts"]),
                         {"/tags", "/negative", "/images", "/characterPrompts", "/params/seed"})
        self.assertEqual(result["metadata"][0]["path"], "/tree")

    def test_same_id_is_scoped_by_dataset(self):
        old = {"entries": [{"id": "same", "tags": "A"}]}
        self.assertFalse(audit.document_delta(old, old)["changed"])
        self.assertEqual(audit.document_delta({"entries": []}, old)["added"], old["entries"])
        self.assertEqual(audit.document_delta(old, {"entries": []})["removed"], old["entries"])

    def test_duplicate_or_missing_ids_fail_closed(self):
        for entries in [[{"id": "a"}, {"id": "a"}], [{"id": ""}], [{"id": 1}]]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                audit.indexed(entries)

    def test_json_pointer_escaping(self):
        self.assertEqual(audit.differences({"a/b~c": 1}, {"a/b~c": 2})[0]["path"], "/a~1b~0c")

    def test_manifest_and_source_paths_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "a.json"
            data.write_text("{}", encoding="utf-8")
            manifest = {"files": {"a.json": {"size": 2, "sha256": audit.digest(data)}}}
            self.assertEqual(audit.verify_file(root, manifest, "a.json"), data)
            data.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                audit.verify_file(root, manifest, "a.json")
            for path in ("../a.json", "C:/a.json", "a\\b.json", "/a.json"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    audit.safe_file(root, path)


if __name__ == "__main__":
    unittest.main()
