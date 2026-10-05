import sys
import unittest
from pathlib import Path


PROMPT_SELECTOR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROMPT_SELECTOR_DIR))

from anima_tag_classifier import (  # noqa: E402
    SOURCE_ADULT_UPPER,
    SOURCE_REGULAR,
    classify_prompt,
)


class AnimaTagClassifierTests(unittest.TestCase):
    def classify(self, alias, prompt, source="", section="", current=""):
        return classify_prompt(
            {"alias": alias, "prompt": prompt},
            current_category=current,
            reference_source=source,
            reference_section=section,
        )

    def test_professional_uniform_is_clothing(self):
        result = self.classify(
            "护士制服",
            "nurse uniform,nurse cap,white thighhighs,gloves",
        )
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.target, "Anima/服装/正常/制服与职业/职业制服")

    def test_artificial_body_is_character(self):
        result = self.classify(
            "机械人偶",
            "android,robot joints,mechanical body,glowing eyes",
        )
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.root, "character")
        self.assertEqual(result.target, "Anima/角色/正常/种族与形态/人工造物")

    def test_explicit_position_is_pose(self):
        result = self.classify(
            "背后位",
            "1girl,1boy,sex from behind,bent over",
        )
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.target, "Anima/姿势/R18/体位/后入与背后位")

    def test_city_environment_is_background(self):
        result = self.classify(
            "雨夜城市街道",
            "city street,night,rain,neon lights,no humans,scenery",
        )
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.target, "Anima/背景/正常/城市与日常")

    def test_source_character_section_beats_incidental_clothes(self):
        result = self.classify(
            "某作品角色",
            "named character,red dress,boots",
            source=SOURCE_REGULAR,
            section="动漫角色",
        )
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.target, "Anima/角色/正常/作品角色/动漫角色")

    def test_source_clothing_section_corrects_legacy_character_root(self):
        result = self.classify(
            "冰系旅法师",
            "frilled shirt,pleated skirt,capelet,corset,brown boots",
            source=SOURCE_REGULAR,
            section="魔法特辑",
            current="Anima/角色/魔法特辑",
        )
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.target, "Anima/服装/正常/幻想与主题/魔法少女")

    def test_style_only_prompt_is_excluded(self):
        result = self.classify(
            "复古油画风格",
            "oil painting,artist:example,best quality,style",
            source=SOURCE_REGULAR,
            section="各种风格",
        )
        self.assertEqual(result.status, "excluded")
        self.assertEqual(result.target, "待归类/Anima复核/画风质量镜头")

    def test_minor_and_adult_markers_are_quarantined(self):
        result = self.classify("风险示例", "loli,nsfw,nude")
        self.assertEqual(result.status, "quarantine")
        self.assertEqual(result.target, "待归类/Anima复核/年龄与安全风险")

    def test_entire_age_risk_reference_section_is_quarantined(self):
        result = self.classify(
            "无明显年龄词的条目",
            "nsfw,nude",
            source=SOURCE_ADULT_UPPER,
            section="大车小孩特辑",
        )
        self.assertEqual(result.status, "quarantine")
        self.assertEqual(result.target, "待归类/Anima复核/年龄与安全风险")

    def test_body_writing_section_is_not_blanket_excluded(self):
        result = self.classify(
            "人体彩绘街道露出",
            "bodypaint,nude,outdoors,city street",
            source=SOURCE_ADULT_UPPER,
            section="Body Writing",
        )
        self.assertNotEqual(result.status, "excluded")

    def test_semantic_alias_with_style_tags_is_not_excluded(self):
        result = self.classify(
            "掐脖性爱昏迷",
            "choking,sex,unconscious,artist:example,best quality,style",
        )
        self.assertNotEqual(result.status, "excluded")


if __name__ == "__main__":
    unittest.main()
