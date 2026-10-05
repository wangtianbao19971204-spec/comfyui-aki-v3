import sys
import unittest
from pathlib import Path


PROMPT_SELECTOR_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROMPT_SELECTOR_DIR / "tools"
for module_path in (PROMPT_SELECTOR_DIR, TOOLS_DIR):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

import anima_review_refinement as module  # noqa: E402
from anima_second_pass import canonical_targets  # noqa: E402
from anima_tag_classifier import load_contract  # noqa: E402


class AnimaReviewRefinementTests(unittest.TestCase):
    def test_child_word_is_detected(self):
        signals = module.safety_signals({
            "alias": "boundary sample",
            "prompt": "child,nude",
        })
        self.assertTrue(signals["hard_age"])
        self.assertTrue(signals["adult_signal"])

    def test_child_bearing_is_not_an_age_signal(self):
        signals = module.safety_signals({
            "alias": "adult body description",
            "prompt": "adult woman,child-bearing hips,evening gown",
        })
        self.assertFalse(signals["age_signal"])

    def test_minor_sensitive_description_is_quarantinable(self):
        signals = module.safety_signals({
            "alias": "boundary sample",
            "prompt": "loli,see-through outfit",
        })
        self.assertTrue(signals["age_signal"])
        self.assertTrue(signals["minor_sexualization"])
        self.assertTrue(signals["adult_signal"])

    def test_transparent_accessory_alone_is_not_adult_content(self):
        signals = module.safety_signals({
            "alias": "period fashion",
            "prompt": "adult woman,see-through gloves,steam train",
        })
        self.assertFalse(signals["age_signal"])
        self.assertFalse(signals["minor_sexualization"])
        self.assertFalse(signals["adult_signal"])

    def test_tags_restore_source_provenance(self):
        provenance = module._provenance_from_tags({
            "tags": ["2026.7.15新增", "色色法典（上）", "各种涩涩", "协作侍奉"],
        })
        self.assertEqual(
            provenance,
            "所长色色NovelAI个人法典(上)/协作侍奉",
        )

    def test_manual_targets_exist_in_contract(self):
        allowed = canonical_targets(load_contract())
        self.assertFalse(set(module.MANUAL_RELEASE_TARGETS.values()) - allowed)

if __name__ == "__main__":
    unittest.main()
