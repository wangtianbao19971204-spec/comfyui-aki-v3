import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "anima_tag_semantic_pass.py"
SPEC = importlib.util.spec_from_file_location("anima_tag_semantic_pass", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AnimaTagSemanticPassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = MODULE.load_contract()

    def classify(self, alias, tags, category="待归类/Anima复核/混合全套"):
        return MODULE.choose_semantic_destination(
            {"alias": alias, "prompt": tags},
            category,
            category,
            self.contract,
        )

    def test_extract_tags_removes_novelai_weights_and_character_prefixes(self):
        self.assertEqual(
            MODULE.extract_tags("2::char1：school_uniform::, {{{doggystyle}}}, ||footjob|handjob||"),
            ["school uniform", "doggystyle", "footjob", "handjob"],
        )

    def test_explicit_action_beats_incidental_clothing(self):
        result = self.classify("另一版本", "school uniform, skirt, doggystyle, sex from behind")
        self.assertEqual(result["target"], "Anima/姿势/R18/体位/后入与背后位")

    def test_explicit_outfit_alias_keeps_outfit_as_primary_intent(self):
        result = self.classify("原版校服", "school uniform, skirt, sitting, indoors")
        self.assertEqual(result["target"], "Anima/服装/正常/制服与职业/校服")

    def test_food_without_people_routes_to_still_life_background(self):
        result = self.classify("一杯鸡尾酒", "no humans, still life, cocktail, ice, glass")
        self.assertEqual(result["target"], "Anima/背景/正常/食物与静物")

    def test_minor_adult_combination_routes_to_safety(self):
        result = self.classify("危险测试", "underage, nude, nsfw")
        self.assertEqual(result["target"], "待归类/Anima复核/年龄与安全风险")

    def test_generic_noise_does_not_decide_a_category(self):
        result = self.classify("另一版本", "1girl, solo, looking at viewer, best quality")
        self.assertEqual(result["target"], "")

    def test_forehead_exposure_is_not_adult_exhibition(self):
        result = self.classify("露出一些额头的发型", "forehead, hair over one eye, long hair")
        self.assertNotEqual(result["target"], "Anima/姿势/R18/单人表现/暴露")

    def test_location_word_does_not_override_subject_action(self):
        result = self.classify("打扫房间动作", "indoors, bedroom, cleaning, holding broom")
        self.assertEqual(result["target"], "Anima/姿势/正常/单人动作")

    def test_ambiguous_clothing_and_species_title_stays_in_review(self):
        result = self.classify("穿环内衣扶她", "lingerie, futanari, nipple piercing")
        self.assertEqual(result["target"], "")
        self.assertEqual(result["reason"], "cross_root_semantic_conflict")

    def test_complete_outfit_does_not_fall_into_components(self):
        result = self.classify(
            "另一版本",
            "dress, skirt, jacket, gloves, hat, thighhighs, necklace",
        )
        self.assertNotEqual(result["target"], "Anima/服装/正常/组件与配饰")

    def test_seductive_smile_alone_does_not_define_seduction(self):
        result = self.classify("做巨乳梦", "large breasts, sleeping, seductive smile")
        self.assertNotEqual(result["target"], "Anima/姿势/R18/单人表现/诱惑")

    def test_explicit_seduction_alias_can_define_seduction(self):
        result = self.classify("护士诱惑", "nurse, seductive smile, looking at viewer")
        self.assertEqual(result["target"], "Anima/姿势/R18/单人表现/诱惑")

    def test_sexual_food_metaphor_does_not_become_normal_action(self):
        result = self.classify("小穴吃热狗", "eating, food, hot dog, pussy")
        self.assertNotEqual(result["target"], "Anima/姿势/正常/单人动作")

    def test_nudity_absence_tags_do_not_define_clothing_modification(self):
        result = self.classify("裸体围裙手捧披萨", "apron, no bra, no panties, holding pizza")
        self.assertNotEqual(result["target"], "Anima/服装/R18/暴露与改造/日常改造")

    def test_explicit_clothing_title_prevents_incidental_sex_action_choice(self):
        result = self.classify("圣诞驯鹿服装涩涩", "christmas outfit, oral sex, handjob")
        self.assertNotEqual(result["target"], "Anima/姿势/R18/非插入互动/口交与颜射")

    def test_near_tied_sibling_actions_stay_for_review(self):
        result = self.classify("绑在床上", "bound ankles, handcuffs")
        self.assertEqual(result["target"], "")
        self.assertEqual(result["reason"], "same_root_semantic_conflict")

    def test_incidental_accessories_do_not_define_components(self):
        result = self.classify("双人背靠背站位", "hair ornament, hat, bracelet, choker")
        self.assertNotEqual(result["target"], "Anima/服装/正常/组件与配饰")

    def test_scene_title_blocks_single_incidental_pose_tag(self):
        result = self.classify("原版场景", "indoors, seductive pose, window")
        self.assertNotEqual(result["target"], "Anima/姿势/R18/单人表现/诱惑")

    def test_action_title_blocks_single_incidental_uniform_tag(self):
        result = self.classify("摇头拒绝", "school uniform, shaking head")
        self.assertNotEqual(result["target"], "Anima/服装/正常/制服与职业/校服")

    def test_incidental_job_tag_does_not_define_character_identity(self):
        result = self.classify("射在尾巴上", "office lady, tail, cum")
        self.assertNotEqual(result["target"], "Anima/角色/正常/身份与职业/常规职业")

    def test_explicit_job_alias_defines_character_identity(self):
        result = self.classify("漏内裤慌张护士", "nurse, embarrassed")
        self.assertEqual(result["target"], "Anima/角色/正常/身份与职业/常规职业")

    def test_meme_source_does_not_promote_one_incidental_action_tag(self):
        result = self.classify(
            "加入绝地潜兵！",
            "pointing at viewer, parody",
            "所长常规NovelAI个人法典/表情包／搞怪",
        )
        self.assertNotEqual(result["target"], "Anima/姿势/正常/单人动作")

    def test_roll_suffix_does_not_match_office_lady(self):
        result = self.classify("初版（须roll）", "kneeling, indoors")
        self.assertNotEqual(result["target"], "Anima/角色/正常/身份与职业/常规职业")

    def test_photography_is_not_a_normal_body_action(self):
        result = self.classify("延时摄影星空", "night sky, long exposure, scenery")
        self.assertNotEqual(result["target"], "Anima/姿势/正常/单人动作")

    def test_explicit_adult_run_does_not_become_normal_action(self):
        result = self.classify("跑步露出乳头", "running, nipples, flashing")
        self.assertNotEqual(result["target"], "Anima/姿势/正常/单人动作")

    def test_bare_chest_photography_routes_to_exposure(self):
        result = self.classify("胸部袒露摄影", "breasts, topless, camera")
        self.assertEqual(result["target"], "Anima/姿势/R18/单人表现/暴露")

    def test_generic_alias_gets_semantic_name_after_selection(self):
        prompt = {"alias": "原版服装__002", "prompt": "school uniform, serafuku"}
        decision = self.classify(prompt["alias"], prompt["prompt"])
        self.assertEqual(MODULE.proposed_alias(prompt, decision), "校服｜水手服")


if __name__ == "__main__":
    unittest.main()
