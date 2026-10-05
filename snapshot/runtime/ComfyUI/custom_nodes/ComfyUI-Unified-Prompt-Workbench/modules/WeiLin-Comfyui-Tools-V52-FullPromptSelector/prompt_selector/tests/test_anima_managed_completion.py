import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "anima_managed_completion.py"
SPEC = importlib.util.spec_from_file_location("anima_managed_completion", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AnimaManagedCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = MODULE.load_contract()
        cls.allowed = MODULE.canonical_targets(cls.contract)

    def test_all_managed_targets_are_in_contract(self):
        targets = set(MODULE.ROOT_DEFAULTS.values()) | set(MODULE.ADULT_POSE_DEFAULTS.values())
        targets.update(rule.target for rule in MODULE.MANAGED_RULES)
        targets.update(
            rule.target
            for rules in MODULE.CAPACITY_SPLITS.values()
            for rule in rules
        )
        self.assertFalse(targets - self.allowed)

    def test_adult_fallback_uses_participant_count(self):
        prompt = {"alias": "完整场景", "prompt": "1girl, 1boy, hetero, nude, sex"}
        self.assertEqual(
            MODULE._default_target(prompt, "pose", "所长色色NovelAI个人法典(上)/杂项"),
            "Anima/姿势/R18/情境/成人日常/双人",
        )

    def test_generic_pose_uses_body_arrangement(self):
        prompt = {"alias": "另一版本", "prompt": "1girl, solo, lying, on stomach, legs up"}
        score, target = MODULE._managed_rule_target(prompt, "pose")
        self.assertGreater(score, 0)
        self.assertEqual(target, "Anima/姿势/正常/基础姿态/躺卧与趴伏")

    def test_outfit_composition_requires_multiple_garment_tags(self):
        weak = {"alias": "挥手", "prompt": "1girl, waving, skirt"}
        strong = {"alias": "完整搭配", "prompt": "shirt, skirt, jacket, shoes, socks"}
        self.assertEqual(MODULE._managed_rule_target(weak, "clothing")[1], "")
        self.assertEqual(
            MODULE._managed_rule_target(strong, "clothing")[1],
            "Anima/服装/正常/日常与季节/完整穿搭",
        )

    def test_oral_capacity_split_prefers_cunnilingus(self):
        target, base = MODULE._capacity_target(
            "Anima/姿势/R18/非插入互动/口交与颜射",
            {"alias": "舔阴", "prompt": "cunnilingus, pussy licking"},
        )
        self.assertEqual(base, "Anima/姿势/R18/非插入互动/口交与颜射")
        self.assertEqual(target, "Anima/姿势/R18/非插入互动/口交与颜射/舔阴与女性口交")

    def test_existing_character_origin_is_not_overridden_by_incidental_clothes(self):
        semantic = {"deterministic": {"root": "clothing", "confidence": 0.7}, "candidates": []}
        model = {"root_model": {"label": "clothing", "margin": 0.6}, "leaf_model": {}}
        root, reason = MODULE._root_evidence(
            {"alias": "原版", "prompt": "dress, shoes"},
            "Anima/角色/正常/人物形象",
            semantic,
            model,
            self.allowed,
        )
        self.assertEqual(root, "character")
        self.assertEqual(reason, "broad_provenance_root")

    def test_primary_title_intent_can_correct_broad_origin(self):
        blank_semantic = {"deterministic": {}, "candidates": []}
        blank_model = {"root_model": {}, "leaf_model": {}}
        cases = (
            ("园丁的小憩", "pose"),
            ("衣衫不整星见雅", "clothing"),
            ("魔界战士", "character"),
        )
        for alias, expected in cases:
            with self.subTest(alias=alias):
                root, _reason = MODULE._root_evidence(
                    {"alias": alias, "prompt": ""},
                    "Anima/角色/正常/人物形象",
                    blank_semantic,
                    blank_model,
                    self.allowed,
                )
                self.assertEqual(root, expected)

    def test_action_title_outranks_incidental_clothing_words(self):
        semantic = {"deterministic": {}, "candidates": []}
        model = {"root_model": {}, "leaf_model": {}}
        for alias in (
            "弯腰脱裙",
            "比基尼女仆三人性爱系列",
            "购物弯腰偷拍裙底",
            "裸体围裙做饭时性爱",
        ):
            with self.subTest(alias=alias):
                root, reason = MODULE._root_evidence(
                    {"alias": alias, "prompt": ""},
                    "Anima/服装/正常/其他",
                    semantic,
                    model,
                    self.allowed,
                )
                self.assertEqual(root, "pose")
                self.assertEqual(reason, "managed_action_title")

    def test_explicit_action_tags_correct_ambiguous_broad_origin(self):
        root, reason = MODULE._root_evidence(
            {"alias": "原版", "prompt": "1girl, sex toy, vibrator, fingering"},
            "Anima/服装/正常/其他",
            {"deterministic": {}, "candidates": []},
            {"root_model": {}, "leaf_model": {}},
            self.allowed,
        )
        self.assertEqual(root, "pose")
        self.assertEqual(reason, "explicit_action_tags")

    def test_low_margin_leaf_model_falls_back_to_readable_meme_bucket(self):
        prompt = {
            "alias": "娃娃机抓小人",
            "prompt": "chibi, claw machine, grabbed by metal claw, tears",
        }
        semantic = {"deterministic": {}, "candidates": []}
        model = {
            "root_model": {"label": "pose", "margin": 0.9},
            "leaf_model": {
                "label": "Anima/姿势/R18/重口/异种互动/人形魔物",
                "margin": 0.08,
            },
        }
        target, _root_reason, reason, _confidence = MODULE.choose_managed_target(
            prompt,
            "所长常规NovelAI个人法典/表情包／搞怪",
            semantic,
            model,
            self.allowed,
            self.contract,
        )
        self.assertEqual(target, "Anima/姿势/正常/表情与情绪")
        self.assertEqual(reason, "readable_root_default")

    def test_explicit_style_only_preset_stays_outside_anima(self):
        target, _root_reason, reason, _confidence = MODULE.choose_managed_target(
            {"alias": "并收画风", "prompt": "artist:a, artist:b, year 2023"},
            "所长常规NovelAI个人法典/杂项内容",
            {"deterministic": {}, "candidates": []},
            {"root_model": {}, "leaf_model": {}},
            self.allowed,
            self.contract,
        )
        self.assertEqual(
            target,
            self.contract["non_anima_contracts"]["excluded_category"],
        )
        self.assertEqual(reason, "non_anima_style")

    def test_style_warning_note_does_not_hide_primary_content(self):
        self.assertFalse(
            MODULE._is_pure_style(
                {"alias": "胸口拔剑（画风受限）", "prompt": "pulling sword from chest"},
                "所长常规NovelAI个人法典/特殊画面",
            )
        )
        self.assertFalse(
            MODULE._is_pure_style(
                {"alias": "人物设定（n4，画风受限）", "prompt": "1girl, body type"},
                "所长常规NovelAI个人法典/特殊画面",
            )
        )

    def test_dense_garment_composition_beats_low_margin_model(self):
        root, reason = MODULE._root_evidence(
            {
                "alias": "原版",
                "prompt": "shirt, skirt, jacket, shoes, gloves, hat",
            },
            "所长常规NovelAI个人法典/群友处收录",
            {"deterministic": {}, "candidates": []},
            {"root_model": {"label": "pose", "margin": 0.1}, "leaf_model": {}},
            self.allowed,
        )
        self.assertEqual(root, "clothing")
        self.assertEqual(reason, "garment_composition")


if __name__ == "__main__":
    unittest.main()
