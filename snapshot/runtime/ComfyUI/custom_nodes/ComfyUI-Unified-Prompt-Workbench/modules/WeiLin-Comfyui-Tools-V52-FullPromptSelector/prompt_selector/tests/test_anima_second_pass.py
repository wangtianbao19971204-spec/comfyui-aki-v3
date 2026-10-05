import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "anima_second_pass.py"
SPEC = importlib.util.spec_from_file_location("anima_second_pass", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AnimaSecondPassTests(unittest.TestCase):
    def test_strong_title_root_prefers_explicit_component_intent(self):
        self.assertEqual(MODULE.strong_title_root("原版char1服装"), "clothing")
        self.assertEqual(MODULE.strong_title_root("原tag动作"), "pose")
        self.assertEqual(MODULE.strong_title_root("原版背景"), "background")
        self.assertEqual(MODULE.strong_title_root("原版角色设定"), "character")

    def test_generic_aliases_are_not_model_only_candidates(self):
        self.assertTrue(MODULE.is_generic_alias("原版"))
        self.assertTrue(MODULE.is_generic_alias("另一版本__002"))
        self.assertTrue(MODULE.is_generic_alias("2版"))
        self.assertFalse(MODULE.is_generic_alias("中式婚礼跪地奉茶"))

    def test_alias_root_evidence_rejects_incidental_source_bias(self):
        self.assertEqual(MODULE.alias_root_evidence("半撩水手服"), "clothing")
        self.assertEqual(MODULE.alias_root_evidence("床上压身侵犯受精"), "pose")
        self.assertEqual(MODULE.alias_root_evidence("白发巨乳御姐"), "")

    def test_strong_title_leaf_maps_unambiguous_actions(self):
        allowed = {target for target, _patterns in MODULE.STRONG_TITLE_LEAF_RULES}
        self.assertEqual(
            MODULE.strong_title_leaf("浴缸着衣乳交", allowed),
            "Anima/姿势/R18/非插入互动/乳交",
        )
        self.assertEqual(
            MODULE.strong_title_leaf("4p乱交", allowed),
            "Anima/姿势/R18/多人互动/双飞与多人",
        )
        self.assertEqual(
            MODULE.strong_title_leaf("原版泳装", allowed),
            "Anima/服装/R18/内衣与泳装/泳装",
        )
        self.assertEqual(
            MODULE.strong_title_leaf("扶她百合浴缸足交", allowed),
            "Anima/姿势/R18/非插入互动/足交",
        )
        self.assertEqual(
            MODULE.strong_title_leaf("被章鱼侵犯", allowed),
            "Anima/姿势/R18/重口/异种互动/触手",
        )

    def test_regular_live_room_is_not_implicitly_adult(self):
        prompt = {"alias": "直播间", "prompt": "streaming room, desk, monitor"}
        self.assertFalse(
            MODULE.has_adult_context(prompt, "所长常规NovelAI个人法典/特殊画面")
        )
        self.assertTrue(
            MODULE.has_adult_context(prompt, "所长色色NovelAI个人法典(上)/杂项")
        )

    def test_explicit_age_risk_is_preserved_for_manual_review(self):
        self.assertTrue(MODULE.has_safety_risk({"alias": "比基尼白丝幼女"}))
        self.assertTrue(MODULE.has_safety_risk({"prompt": "1girl, underage, swimsuit"}))
        self.assertFalse(MODULE.has_safety_risk({"alias": "成年女性泳装"}))

    def test_prior_applied_moves_are_loaded_as_training_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            report_dir = Path(temporary_dir)
            report = {
                "stage": "anima_second_pass_apply",
                "moves": [
                    {"prompt_id": "prompt-a"},
                    {"prompt_id": "prompt-b"},
                    {"prompt_id": ""},
                ],
            }
            (report_dir / "anima-second-pass-apply-20260823-000000.json").write_text(
                json.dumps(report),
                encoding="utf-8",
            )
            moved_ids, reports = MODULE.load_prior_applied_moves(report_dir)

        self.assertEqual(moved_ids, {"prompt-a", "prompt-b"})
        self.assertEqual(reports[0]["moved_prompt_ids"], 2)

    def test_excluded_and_safety_buckets_are_not_candidates(self):
        self.assertFalse(MODULE.is_candidate_category("待归类/Anima复核/画风质量镜头"))
        self.assertFalse(MODULE.is_candidate_category("待归类/Anima复核/年龄与安全风险"))
        self.assertTrue(MODULE.is_candidate_category("待归类/Anima复核/混合全套"))
        self.assertTrue(MODULE.is_candidate_category("所长常规NovelAI个人法典/美食有关"))

    def test_full_width_slash_stays_inside_reference_section(self):
        self.assertEqual(
            MODULE.source_context_from_category(
                "所长常规NovelAI个人法典/表情包／搞怪"
            ),
            ("所长常规NovelAI个人法典", "表情包/搞怪"),
        )
        self.assertEqual(
            MODULE.source_context_from_category(
                "所长色色NovelAI个人法典(上)/组件／杂项（女）"
            ),
            ("所长色色NovelAI个人法典(上)", "组件/杂项（女）"),
        )


if __name__ == "__main__":
    unittest.main()
