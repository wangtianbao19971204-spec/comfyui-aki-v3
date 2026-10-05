from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ZH_CN = PLUGIN_ROOT / "py" / "danbooru_gallery" / "zh_cn"
CORRECTIONS = ZH_CN / "verified_character_corrections.csv"
REPAIR_TOOL = PLUGIN_ROOT / "tools" / "repair_polluted_tag_translations.py"

SPEC = importlib.util.spec_from_file_location("verified_character_repair", REPAIR_TOOL)
assert SPEC and SPEC.loader
repair = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = repair
SPEC.loader.exec_module(repair)


def _corrections() -> dict[str, str]:
    with CORRECTIONS.open("r", encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 34
    assert all(row["category"] == "4" for row in rows)
    assert all(int(row["post_count"]) > 0 for row in rows)
    assert all(row["evidence"] == "manual_cross_title_review_2026-07-19" for row in rows)
    result = {row["tag"]: row["translation_cn"] for row in rows}
    assert len(result) == len(rows)
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


def test_curated_pack_is_character_only_and_ambiguous_names_stay_untranslated():
    corrections = _corrections()

    assert "graf_eisen" not in corrections
    assert "wild_tiger" not in corrections
    assert corrections["xiao_(genshin_impact)"] == "魈（原神）"
    assert corrections["saint-louis_(azur_lane)"] == "路易九世（碧蓝航线）"


def test_static_character_source_matches_curated_pack_without_reintroducing_bad_rows():
    corrections = _corrections()
    wai = _wai_rows()

    for tag, translation in corrections.items():
        assert wai.get(tag) == translation
    assert "graf_eisen" not in wai
    assert "wild_tiger" not in wai


def test_json_and_danbooru_csv_overrides_match_curated_pack():
    corrections = _corrections()
    json_rows = json.loads((ZH_CN / "all_tags_cn.json").read_text(encoding="utf-8"))
    with (ZH_CN / "danbooru.csv").open("r", encoding="utf-8", newline="") as source:
        csv_rows = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}

    for tag in (
        "feater_(arknights)",
        "kazuha's_friend_(genshin_impact)",
        "saint-louis_(azur_lane)",
        "xiao_(genshin_impact)",
    ):
        assert json_rows[tag] == corrections[tag]
        assert csv_rows[tag] == corrections[tag]


def test_repair_allowlist_contains_every_reviewed_bad_character_value():
    expected = {
        ("chihaya_anon", "千早爱音（偶像大师）"),
        ("mococo_abyssgard", "莫可可深渊花园（命运方舟）"),
        ("mococo_abyssgard_(1st_costume)", "莫可可深渊花园（初始服装）（命运方舟）"),
        ("xiao_(genshin_impact)", "魈_(原神冲击)"),
        ("kaban_(kemono_friends)", "薮猫（兽娘动物园）"),
        ("serena_(pokemon)", "小遥（宝可梦）"),
        ("raora_panthera", "拉欧拉·潘特拉(（Arknights）"),
        ("rika_(pokemon)", "莉佳（宝可梦）"),
        ("lyra_(pokemon)", "莉拉（宝可梦）"),
        ("takasaki_yu", "高咲侑（偶像大师 Shiny Colors）"),
        ("momo_(nikki)", "莫莫（NIKKE: 胜利女神）"),
        ("tsukimura_temari", "月村手毬（魔法少女奈叶）"),
        ("jervis_(kancolle)", "杰维斯（拳皇）"),
        ("feater_(arknights)", "羽毛（方舟）"),
        ("daiba_nana", "大场奈奈（偶像大师 百万现场）"),
        ("todo_yurika", "藤堂百合香（偶像大师）"),
        ("toyama_kasumi", "户山香橙（偶像大师 闪耀色彩）"),
        ("cure_dream", "菱川六花（光之美少女）"),
        ("white_heart_(neptunia)", "白心（明日方舟）"),
        ("klaudia_valentz", "科洛蒂娅·巴兰茨（碧蓝航线）"),
        ("white_len_(tsukihime)", "白莲（明日方舟）"),
        ("mutsu-no-kami_yoshiyuki", "陆奥守吉行（碧蓝幻想）"),
        ("ne-class_heavy_cruiser", "NE级重巡洋舰（碧蓝航线）"),
        ("fujima_sakura", "藤间樱（偶像大师 闪耀色彩）"),
        ("shizuka_rin_(1st_costume)", "静香凛（第一套服装）（偶像大师 闪耀色彩）"),
        ("rukkhadevata_(genshin_impact)", "流浪者（原神）"),
        ("dendra_(pokemon)", "丹帝（宝可梦）"),
        ("lapis_lazuli_(houseki_no_kuni)", "磷叶石（宝石之国）"),
        ("kagamine_rin_(append)", "镜音连-Append（Vocaloid）"),
        ("maestrale_(kancolle)", "东北风（舰队Collection）"),
        ("miriam_(pokemon)", "迷布莉姆（宝可梦）"),
        ("kazuha's_friend_(genshin_impact)", "枫原万叶（原神）"),
        ("kokoro_(hakui_koyori)", "博衣小夜璃（Hololive）"),
        ("saint-louis_(azur_lane)", "圣路易斯"),
        ("graf_eisen", "维塔（魔法少女奈叶）"),
        ("wild_tiger", "白虎（兽娘动物园）"),
    }
    assert expected.issubset(repair._KNOWN_CROSS_TITLE_COLLISIONS)
    for tag, bad_translation in expected:
        assert repair._is_known_cross_title_collision(tag, bad_translation)
