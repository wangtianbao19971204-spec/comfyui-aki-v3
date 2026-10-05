import hashlib
import json
import sys
import unittest
from collections import Counter
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from test_lora_performance_and_shared_prompts import (  # noqa: E402
    PLUGIN_DIR,
    load_shared_prompt_adapter,
)


SOURCE_PATH = (
    PLUGIN_DIR.parent
    / "WeiLin-Comfyui-Tools-V52-FullPromptSelector"
    / "user_data"
    / "prompt_selector"
    / "data.json"
)
TAXONOMY_PATH = PLUGIN_DIR / "data" / "weilin_category_taxonomy.json"
CONTRACT_PATH = PLUGIN_DIR / "data" / "weilin_anima_classification_contract.json"


ROOT_KIND = {
    "Anima/姿势": "pose",
    "Anima/角色": "character",
    "Anima/服装": "clothing",
    "Anima/背景": "background",
}


@unittest.skipUnless(SOURCE_PATH.is_file(), "WeiLin Prompt Selector is not installed")
class WeiLinTaxonomyManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_bytes = SOURCE_PATH.read_bytes()
        cls.source = json.loads(cls.source_bytes)
        cls.taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.categories = cls.source["categories"]
        cls.prompts = [
            prompt
            for category in cls.categories
            for prompt in category.get("prompts", [])
        ]

    def test_manifest_matches_semantic_source_snapshot(self):
        self.assertEqual(len(self.categories), 259)
        self.assertEqual(len(self.prompts), 16442)
        self.assertEqual(
            self.taxonomy["source_sha256"],
            hashlib.sha256(self.source_bytes).hexdigest(),
        )
        self.assertEqual(len({category["name"] for category in self.categories}), 259)
        self.assertEqual(len({category["id"] for category in self.categories}), 259)
        self.assertEqual(len({prompt["id"] for prompt in self.prompts}), 16442)
        self.assertEqual(self.taxonomy["mappings"], {})
        self.assertEqual(self.taxonomy["prompt_routes"], {})
        self.assertEqual(self.taxonomy["quarantined_prompts"], {})
        self.assertEqual(self.taxonomy["audit"]["anima_prompt_count"], 15951)
        self.assertEqual(self.taxonomy["audit"]["review_prompt_count"], 442)
        self.assertEqual(self.taxonomy["audit"]["leaf_max_prompt_count"], 200)
        self.assertEqual(self.taxonomy["audit"]["leaf_over_soft_limit_count"], 0)

    def test_all_anima_categories_obey_the_contract(self):
        canonical = {
            name
            for names in self.contract["canonical_categories"].values()
            for name in names
        }
        anima_names = {
            category["name"]
            for category in self.categories
            if category["name"].startswith("Anima/")
        }
        self.assertEqual(len(anima_names), 246)
        self.assertTrue(anima_names - set(ROOT_KIND) <= canonical)
        self.assertFalse({
            "Anima/角色/魔法特辑",
            "Anima/姿势/R18/口交（类口交颜射）",
            "Anima/姿势/R18/大车小孩特辑",
        } & anima_names)

        raw_counts = Counter()
        for category in self.categories:
            for root, kind in ROOT_KIND.items():
                if category["name"] == root or category["name"].startswith(root + "/"):
                    raw_counts[kind] += len(category.get("prompts", []))
                    break
        self.assertEqual(
            dict(raw_counts),
            {
                "pose": 9738,
                "character": 1430,
                "clothing": 3577,
                "background": 1206,
            },
        )

    def test_adapter_maps_anima_and_dedicated_style_quality_branch(self):
        adapter = load_shared_prompt_adapter()
        payloads = adapter["_build_shared_prompt_payloads"](
            str(SOURCE_PATH),
            SOURCE_PATH.stat().st_mtime_ns,
            summary_only=True,
        )
        self.assertEqual(
            payloads["pose"]["kind_counts"],
            {
                "pose": 9712,
                "background": 1206,
                "clothing": 3557,
                "character": 1427,
                "style_quality": 424,
            },
        )
        for kind, payload in payloads.items():
            self.assertTrue(payload["success"], kind)
            self.assertTrue(payload["taxonomy_source_matches"], kind)
            self.assertEqual(payload["pending_prompt_count"], 0, kind)
            self.assertEqual(payload["mapped_source_categories"], 253, kind)
            self.assertEqual(payload["unmapped_category_count"], 6, kind)

        review_prefix = "待归类/Anima复核/画风质量镜头/"
        self.assertEqual(payloads["style_quality"]["matched_source_categories"], 7)
        self.assertTrue(payloads["style_quality"]["items"])
        self.assertTrue(all(
            str(path.get("source_full") or "").startswith(review_prefix)
            for item in payloads["style_quality"]["items"]
            for path in item.get("shared_category_paths", [])
        ))
        for kind in ("pose", "background", "clothing", "character"):
            self.assertFalse(any(
                str(path.get("source_full") or "").startswith(
                    "待归类/Anima复核/"
                )
                for item in payloads[kind]["items"]
                for path in item.get("shared_category_paths", [])
            ))

    def test_review_buckets_are_explicit_and_non_overlapping(self):
        categories = {category["name"]: category for category in self.categories}
        expected = {
            "待归类/Anima复核/画风质量镜头/负面词与排除项": 16,
            "待归类/Anima复核/画风质量镜头/画师与作品风格": 81,
            "待归类/Anima复核/画风质量镜头/界面排版与画面特效": 43,
            "待归类/Anima复核/画风质量镜头/镜头构图与光影": 83,
            "待归类/Anima复核/画风质量镜头/媒介与渲染风格": 140,
            "待归类/Anima复核/画风质量镜头/质量与正向参数": 78,
            "待归类/Anima复核/画风质量镜头/综合画面控制": 1,
        }
        self.assertEqual(
            {name: len(categories[name]["prompts"]) for name in expected},
            expected,
        )
        self.assertEqual(
            {
                name
                for name in categories
                if name.startswith("待归类/Anima复核/")
            },
            set(expected),
        )

    def test_marked_prompts_are_distributed_without_a_dedicated_root(self):
        self.assertFalse(any(
            category["name"] == "Anima/正太萝莉"
            or category["name"].startswith("Anima/正太萝莉/")
            for category in self.categories
        ))
        marked = [
            (category["name"], prompt)
            for category in self.categories
            for prompt in category.get("prompts", [])
            if str(prompt.get("alias") or "").startswith("正太萝莉-")
        ]
        self.assertEqual(len(marked), 542)
        self.assertTrue(all(name.startswith("Anima/") for name, _prompt in marked))
        self.assertTrue(all(
            not str(prompt.get("alias") or "").startswith("正太萝莉-正太萝莉-")
            for _name, prompt in marked
        ))


if __name__ == "__main__":
    unittest.main()
