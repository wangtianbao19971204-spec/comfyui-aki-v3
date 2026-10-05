from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


MODULE_PATH = Path(__file__).parents[1] / "tools" / "build_final_semantic_qa.py"
SPEC = importlib.util.spec_from_file_location("build_final_semantic_qa", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_final_removal_policy_is_explicit_and_correction_is_audit_only() -> None:
    assert len(MODULE.REMOVALS) == 95
    assert all(decision.reason for decision in MODULE.REMOVALS.values())
    assert all(decision.issue_types for decision in MODULE.REMOVALS.values())
    assert all(decision.proposed_correction_cn for decision in MODULE.REMOVALS.values())
    assert MODULE.REMOVALS["eous_(zenless_zone_zero)"].proposed_correction_cn.startswith("伊埃斯")
    assert "wrong_identity" in MODULE.REMOVALS["kizuna_akari"].issue_types
    assert "variant_lost" in MODULE.REMOVALS["ranma-chan"].issue_types


def test_translation_comparison_ignores_latin_case_but_not_chinese_identity() -> None:
    assert MODULE.translation_key("重音Teto") == MODULE.translation_key("重音teto")
    assert MODULE.translation_key("POP子") == MODULE.translation_key("pop子")
    assert MODULE.translation_key("罗浮(鸣潮)") != MODULE.translation_key("漂泊者(鸣潮)")


def test_qualifier_counter_preserves_all_source_groups() -> None:
    assert MODULE.source_qualifier_count("name_(form)_(work)") == 2
    assert MODULE.target_qualifier_count("姓名(形态)(作品)") == 2
    assert MODULE.target_qualifier_count("姓名（形态）（作品）") == 2


def test_pack_normalization_rejects_artist_and_copyright_categories() -> None:
    base = {"tag": "example", "post_count": "12", "translation_cn": "示例"}
    with pytest.raises(ValueError, match="disallowed category"):
        MODULE.normalize_pack_row({**base, "category": "1"}, "artist")
    with pytest.raises(ValueError, match="disallowed category"):
        MODULE.normalize_pack_row({**base, "category": "3"}, "copyright")
    assert MODULE.normalize_pack_row({**base, "category": "4"}, "character")["category"] == "4"
