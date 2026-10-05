from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ZH_CN = PLUGIN_ROOT / "py" / "danbooru_gallery" / "zh_cn"
CORRECTIONS = ZH_CN / "verified_residual_character_corrections.csv"
REPAIR_TOOL = PLUGIN_ROOT / "tools" / "repair_polluted_tag_translations.py"

SPEC = importlib.util.spec_from_file_location("verified_residual_character_repair", REPAIR_TOOL)
assert SPEC and SPEC.loader
repair = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = repair
SPEC.loader.exec_module(repair)


EXPECTED_BAD_VALUES = {
    "august_von_parseval_(azur_lane)": "八月冯帕斯瓦尔（蔚蓝车道）",
    "august_von_parseval_(the_conquered_unhulde)_(azur_lane)": (
        "august_von_parseval（被征服的_unhulde）（蔚蓝车道）"
    ),
    "friedrich_der_grosse_(azur_lane)": "Friedrich_der_Grosse_(蔚蓝海岸)",
    "honolulu_(summer_accident?!)_(azur_lane)": "檀香山（夏季事故？！）（蔚蓝车道）",
    "le_malin_(sleepy_sunday)_(azur_lane)": "le_malin（沉睡的星期天）（蔚蓝车道）",
    "le_temeraire_(azur_lane)": "le_temeraire_(蔚蓝海岸)",
    "new_jersey_(exhilarating_steps!)_(azur_lane)": "新泽西（令人振奋的步伐！）（蔚蓝泳道）",
    "prinz_eugen_(final_lap)_(azur_lane)": "欧根亲王（最后一圈）（蔚蓝车道）",
    "ulrich_von_hutten_(azur_lane)": "ulrich_von_hutten（蔚蓝海岸）",
    "vittorio_veneto_(azur_lane)": "维托里奥·威尼托（蔚蓝海岸）",
    "utage_(arknights)": "使用_(arknights)",
    "swire_(arknights)": "太古_(arknights)",
    "hung_(arknights)": "挂（方舟）",
    "dusk_(arknights)": "黄昏（方舟）",
    "dusk_(everything_is_a_miracle)_(arknights)": "黄昏（一切都是奇迹）（明日方舟）",
    "blue_poison_(arknights)": "蓝色毒药（方舟）",
    "blue_poison_(shoal_beat)_(arknights)": "蓝色毒药_(shoal_beat)_(arknights)",
}


def _corrections() -> dict[str, str]:
    with CORRECTIONS.open("r", encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 17
    assert all(row["category"] == "4" for row in rows)
    assert all(int(row["post_count"]) > 0 for row in rows)
    assert all(
        row["evidence"] == "manual_residual_character_review_2026-07-19"
        for row in rows
    )
    result = {row["tag"]: row["translation_cn"] for row in rows}
    assert len(result) == len(rows)
    assert set(result) == set(EXPECTED_BAD_VALUES)
    return result


def _wai_rows() -> dict[str, str]:
    result: dict[str, str] = {}
    with (ZH_CN / "wai_characters.csv").open("r", encoding="utf-8", newline="") as source:
        for row in csv.reader(source):
            if len(row) < 2:
                continue
            normalized_tag = "_".join(row[1].strip().casefold().split())
            result[normalized_tag] = row[0].strip()
    return result


def test_residual_pack_is_exactly_the_reviewed_character_set():
    corrections = _corrections()

    assert corrections["swire_(arknights)"] == "诗怀雅（明日方舟）"
    assert corrections["dusk_(everything_is_a_miracle)_(arknights)"] == "夕·染尘烟（明日方舟）"
    assert corrections["blue_poison_(shoal_beat)_(arknights)"] == "蓝毒·浅滩律动（明日方舟）"


def test_static_sources_match_every_residual_correction():
    corrections = _corrections()
    json_rows = json.loads((ZH_CN / "all_tags_cn.json").read_text(encoding="utf-8"))
    with (ZH_CN / "danbooru.csv").open("r", encoding="utf-8", newline="") as source:
        csv_rows = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}

    for tag, translation in corrections.items():
        assert json_rows[tag] == translation
        assert csv_rows[tag] == translation


def test_wai_character_rows_use_reviewed_values_without_trailing_spaces():
    corrections = _corrections()
    wai = _wai_rows()

    for tag in (
        "blue_poison_(shoal_beat)_(arknights)",
        "dusk_(everything_is_a_miracle)_(arknights)",
        "friedrich_der_grosse_(azur_lane)",
        "swire_(arknights)",
    ):
        assert wai[tag] == corrections[tag]

    raw_wai = (ZH_CN / "wai_characters.csv").read_text(encoding="utf-8")
    assert "腓特烈大帝（碧蓝航线）  ,friedrich der grosse (azur lane)" not in raw_wai


def test_repair_allowlist_contains_each_exact_old_value_only():
    for tag, bad_translation in EXPECTED_BAD_VALUES.items():
        assert (tag, bad_translation) in repair._KNOWN_CROSS_TITLE_COLLISIONS
        assert repair._is_known_cross_title_collision(tag, bad_translation)

    for tag, corrected_translation in _corrections().items():
        assert not repair._is_known_cross_title_collision(tag, corrected_translation)
