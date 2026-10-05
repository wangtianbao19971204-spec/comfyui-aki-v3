import json
import tempfile
import unittest
from pathlib import Path

import importlib.util
_PATH = Path(__file__).resolve().parents[1] / "tag_identity_bridge.py"
_SPEC = importlib.util.spec_from_file_location("tag_identity_bridge_under_test", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
TagIdentityBridge = _MODULE.TagIdentityBridge


class TagIdentityBridgeTests(unittest.TestCase):
    def test_real_candidate_summary_matches_audit(self):
        relative = Path("benchmark_reports") / "2026-09-11_shared_collections" / "evidence" / "tag_link_candidates.json"
        path = next((parent / relative for parent in Path(__file__).resolve().parents if (parent / relative).is_file()), None)
        self.assertIsNotNone(path, "repository evidence file not found above the plugin")
        self.assertTrue(path.is_file(), path)
        bridge = TagIdentityBridge(path)
        self.assertEqual(bridge.validate_summary(), {
            "concepts": 241,
            "tag_records": 258,
            "shared_records": 243,
            "relations": {"one_to_one_exact_body": 224, "multiple_records": 13, "one_to_one_normalized_body": 4},
        })

    def test_bidirectional_lookup_and_multi_record_retention(self):
        payload = {
            "schema": "weilin-legacy-tag-link-candidates-v1",
            "summary": {"concepts": 2},
            "links": [
                {"status": "candidate_not_applied", "relation": "one_to_one_exact_body", "tag_sources": [{"tag_uuid": "tag-a"}], "prompt_targets": [{"resource_id": "resource-a"}]},
                {"status": "candidate_not_applied", "relation": "multiple_records", "tag_sources": [{"tag_uuid": "tag-b"}, {"tag_uuid": "tag-c"}], "prompt_targets": [{"resource_id": "resource-b"}]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "links.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            bridge = TagIdentityBridge(path)
            self.assertEqual(bridge.by_tag_uuid("tag-a")[0]["prompt_targets"][0]["resource_id"], "resource-a")
            self.assertEqual(len(bridge.by_resource_id("resource-b")[0]["tag_sources"]), 2)
            self.assertEqual(bridge.relation(tag_uuid="tag-c")[0]["relation"], "multiple_records")

    def test_rejects_applied_or_invalid_schema(self):
        payload = {"schema": "weilin-legacy-tag-link-candidates-v1", "links": [{"status": "applied"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "links.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                TagIdentityBridge(path)


if __name__ == "__main__":
    unittest.main()
