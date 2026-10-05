import copy
import sys
import unittest
from pathlib import Path


PROMPT_SELECTOR_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROMPT_SELECTOR_DIR / "tools"
for module_path in (PROMPT_SELECTOR_DIR, TOOLS_DIR):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

import integrate_marked_anima_prompts as module  # noqa: E402


class IntegrateMarkedAnimaPromptsTests(unittest.TestCase):
    def test_alias_marker_is_idempotent(self):
        self.assertEqual(module.marked_alias("测试"), "正太萝莉-测试")
        self.assertEqual(
            module.marked_alias("正太萝莉-测试"),
            "正太萝莉-测试",
        )

    def test_manual_targets_are_existing_canonical_leaves(self):
        allowed = module.canonical_targets(module.load_contract())
        self.assertFalse(set(module.MANUAL_TARGETS.values()) - allowed)

    def test_integration_removes_source_and_preserves_prompt_payload(self):
        source_name = "Anima/正太萝莉/姿势/R18/体位/插入与体位"
        target_name = "Anima/姿势/R18/体位/站立位"
        prompt = {
            "id": "sample-prompt",
            "alias": "站立位测试",
            "prompt": "standing sex",
            "image": "sample.png",
            "tags": ["sample"],
        }
        source = {
            "categories": [
                {
                    "id": "source-category",
                    "name": source_name,
                    "prompts": [copy.deepcopy(prompt)],
                },
                {
                    "id": "target-category",
                    "name": target_name,
                    "prompts": [],
                },
            ],
        }

        audit = module.build_audit(source, "source-hash", 200)
        result = module.integrated_data(source, audit)
        module.validate_result(source, result, audit)

        self.assertEqual(audit["prompt_count"], 1)
        self.assertEqual(audit["low_confidence_count"], 0)
        self.assertEqual(audit["projected_over_capacity"], {})
        self.assertEqual([c["name"] for c in result["categories"]], [target_name])
        moved = result["categories"][0]["prompts"][0]
        self.assertEqual(moved["alias"], "正太萝莉-站立位测试")
        self.assertEqual(moved["prompt"], prompt["prompt"])
        self.assertEqual(moved["image"], prompt["image"])
        self.assertEqual(moved["tags"], prompt["tags"])


if __name__ == "__main__":
    unittest.main()
