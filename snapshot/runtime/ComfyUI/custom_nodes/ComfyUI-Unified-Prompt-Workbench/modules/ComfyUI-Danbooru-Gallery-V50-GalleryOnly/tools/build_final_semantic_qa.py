#!/usr/bin/env python3
"""Build the final, read-only semantic QA result for the phase-2 safe core.

This tool deliberately does not open a Gallery database.  It takes the three
already-reviewed CSV packs, joins their evidence, applies the explicit final
human semantic decisions below, and writes a reproducible audit bundle.

Corrections are *suggestions only*.  A row with a proposed correction is still
removed from ``final_safe_core.csv`` so that this pass can never expand or
silently rewrite the reviewed safe set.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


IMPORT_FIELDS = ("tag", "category", "post_count", "translation_cn")


@dataclass(frozen=True)
class Removal:
    issue_types: str
    proposed_correction_cn: str
    reason: str
    evidence_url: str = ""


def R(issue_types: str, correction: str, reason: str, evidence_url: str = "") -> Removal:
    return Removal(issue_types, correction, reason, evidence_url)


# Explicit human decisions after reading all 875 rows.  The set is intentionally
# conservative: uncertainty alone is not a removal reason.  Each entry has a
# concrete identity, qualifier, localization, or Simplified-Chinese problem.
REMOVALS: Mapping[str, Removal] = {
    "acolyte_(ragnarok_online)": R("official_localization", "服事(仙境传说)", "现译是泛化职业名；该作品的中文职业名不是“侍僧”。"),
    "ako_(blue_archive)": R("wrong_official_name", "天雨亚子(蔚蓝档案)", "“阿子”不是该角色的通行中文名；本地 WAI 候选给出完整角色名。"),
    "alexandrina_sebastiane": R("wrong_official_name", "亚历山德丽娜·莎芭丝缇安", "Bangumi 中文名与现译在人名核心部分不一致。"),
    "allister_(pokemon)": R("wrong_official_name", "欧尼奥(宝可梦)", "现译按英文音译，和该角色官方中文名不一致。"),
    "amate_yuzuriha": R("wrong_official_name", "天手让叶", "Bangumi 精确角色证据表明现译读音和用字均错误。"),
    "ao_isami": R("wrong_name_order;wrong_official_name", "勇·碧", "现译把日文姓名误作普通汉字姓名；Bangumi 角色页给出简体中文名。", "https://bgm.tv/character/147924"),
    "arcane_jinx": R("variant_lost", "双城之战版金克丝", "现译丢失 source tag 中的 Arcane 版本限定，退化为基础角色。"),
    "asaba_harumasa": R("wrong_identity", "浅羽悠真", "“幻影”与 source tag 的角色身份无关；Bangumi 精确角色证据给出中文名。"),
    "ayase_momo": R("wrong_official_name", "绫濑桃", "现译擅自增加“子”，与 Bangumi 精确角色中文名不一致。"),
    "bardiche_(nanoha)": R("wrong_official_name", "雷光战斧(魔法少女奈叶)", "现译只做音译，和该魔导器的中文作品名不一致。"),
    "beatrice_(re:zero)": R("nickname_over_generalization", "碧翠丝(Re:从零开始的异世界生活)", "现译使用昵称“贝蒂”，不能稳定指向 source tag 的完整角色名。"),
    "boothill_(honkai:_star_rail)": R("wrong_official_name", "波提欧(崩坏:星穹铁道)", "现译按英文拼写音译，与游戏简体中文角色名不一致。", "https://honkai-star-rail.fandom.com/zh/wiki/%E6%B3%A2%E6%8F%90%E6%AC%A7?variant=zh-sg"),
    "camellya_(wuthering_waves)": R("wrong_official_name", "椿(鸣潮)", "现译按英文名音译，与游戏简体中文角色名“椿”不一致。", "https://wiki.biligame.com/wutheringwaves/%E5%85%B1%E9%B8%A3%E8%80%85/%E6%A4%BF"),
    "caelus_(honkai:_star_rail)": R("wrong_official_name", "穹(崩坏:星穹铁道)", "“凯洛斯”不是该男主角的简体中文名。", "https://anibase.net/ja/character/mR8xz/%E7%A9%B9"),
    "elegg_(nikke)": R("wrong_official_name", "伊莱格(胜利女神:NIKKE)", "Bangumi 精确角色证据与现译人名不一致。"),
    "endministrator_(arknights)": R("semantic_invention", "管理员(明日方舟:终末地)", "现译“终端管理员”是未受证据支持的拆词扩写，并遗漏终末地身份范围。"),
    "eous_(zenless_zone_zero)": R("wrong_identity", "伊埃斯(绝区零)", "“无系列名”不是角色名，属于字段占位文本误入翻译。", "https://donmai.moe/wiki_pages/eous_%28zenless_zone_zero%29"),
    "futatsuiwa_mamizou": R("wrong_official_name", "二岩猯藏", "Bangumi 精确角色证据与本地 WAI 候选都反证现译。"),
    "gekota": R("wrong_official_name", "呱太", "现译机械转写英文拼写，未对应作品中的中文角色/吉祥物名。"),
    "hatoba_tsugu": R("not_simplified_chinese", "鸠羽津", "现译含日文旧字“鳩”，不符合本轮简体中文规范。"),
    "hatsune_miku_(append)": R("duplicate_qualifier", "初音未来(Append)", "一个 source 限定被同时写成方括号与圆括号，重复扩写。"),
    "himemushi_momoyo": R("wrong_official_name", "姬虫百百世", "Bangumi 精确角色中文名反证现译“百代”。"),
    "hino_rei": R("wrong_official_name", "火野丽", "Bangumi 与本地 WAI 均反证现译末字。"),
    "hong_lu_(project_moon)": R("wrong_official_name", "鸿璐(Project Moon)", "Bangumi 精确角色中文名反证现译“红露”。"),
    "hoshizora_miyuki": R("wrong_official_name", "星空幸", "Bangumi 精确角色中文名与本地 WAI 均不支持“美雪”。"),
    "itsumi_erika": R("wrong_identity", "逸见艾丽卡", "现译是另一组中文姓名；Bangumi 与本地 WAI 一致反证。"),
    "jade_leech": R("literalized_person_name", "杰德·李奇", "现译把专名 Jade 误译为普通名词“翡翠”。"),
    "jeanne_d'arc_alter_(avenger)_(fate)": R("duplicate_qualifier;unnatural_translation", "贞德·Alter(Avenger)(Fate)", "现译同时在姓名和括号中重复“复仇者”，影响精确联想。"),
    "jiro_kyoka": R("name_component_lost", "耳郎响香", "source tag 含完整姓名，现译只剩名字并丢失姓氏。"),
    "kanna_kamui": R("wrong_official_name", "康娜卡姆依", "Bangumi 与本地 WAI 一致反证现译。"),
    "kazama_iroha": R("wrong_official_name", "风真伊吕波", "把姓氏“风真”误写成“风间”；Bangumi 精确角色证据反证。"),
    "kazama_iroha_(1st_costume)": R("wrong_official_name;duplicate_qualifier", "风真伊吕波(初始服装)", "姓氏误写，且同一个服装限定被方括号与圆括号重复表达。"),
    "kinich_(genshin_impact)": R("wrong_official_name", "基尼奇(原神)", "“金赤”不是游戏简体中文角色名。", "https://wiki.biligame.com/ys/Kinich"),
    "kino_makoto": R("wrong_identity", "木野真琴", "现译“木之本樱”是另一作品角色；Bangumi 与本地 WAI 一致反证。"),
    "kirishima_touka": R("wrong_official_name", "雾岛董香", "现译逐字误配该角色姓名，不能用于精确联想。"),
    "kiriya_aoi": R("wrong_official_name", "雾矢葵", "Bangumi 与本地 WAI 一致反证现译。"),
    "kise_yayoi": R("wrong_official_name", "黄濑弥生", "Bangumi 与本地 WAI 一致反证现译。"),
    "kishin_sagume": R("wrong_official_name", "稀神探女", "本地 WAI 候选反证现译；现译也未对应 source tag 的日文姓名。"),
    "kizuna_akari": R("wrong_identity", "绁星灯", "现译“绊爱”是另一位虚拟角色；Bangumi 与本地 WAI 一致反证。"),
    "kyonko": R("wrong_identity", "虚子", "该 tag 是阿虚的性转角色，现译“京子”错配常见姓名；本地 WAI 亦反证。"),
    "lacey_(pokemon)": R("wrong_official_name", "紫竽(宝可梦)", "Bangumi 精确角色中文名反证英文直译音。"),
    "lance_(pokemon)": R("wrong_official_name", "渡(宝可梦)", "现译按英文名音译，不是该宝可梦角色的中文名。"),
    "madotsuki": R("wrong_official_name", "附窗子", "Bangumi 与本地 WAI 一致反证现译“圆崎未梦”。"),
    "makinami_mari_illustrious": R("wrong_official_name", "真希波·玛丽·伊兰崔亚斯", "现译多个姓名分段误写；本地 WAI 候选反证。"),
    "male_rover_(wuthering_waves)": R("wrong_official_name", "男性漂泊者(鸣潮)", "游戏官方将 Rover 译为“漂泊者”，不是“漫游者”。", "https://wutheringwaves.kurogames.com/zh-tw/main/news/detail/2560"),
    "matsuno_karamatsu": R("wrong_official_name", "松野空松", "Bangumi 精确角色中文名反证现译“唐松”。"),
    "meursault_(project_moon)": R("wrong_official_name", "默尔索(Project Moon)", "Bangumi 精确角色中文名反证现译“梅尔索”。"),
    "miles_edgeworth": R("wrong_official_name", "御剑怜侍", "现译按英语名音译，Bangumi 与 Wikidata 中文名反证。"),
    "misumi_nagisa": R("wrong_official_name", "美墨渚", "Bangumi 与本地 WAI 一致反证现译“三隅渚”。"),
    "murosaki_miyo": R("wrong_official_name", "室崎美夜", "Bangumi 精确角色中文名反证现译末字。"),
    "nakamura_yuri": R("wrong_official_name", "仲村由理", "Bangumi 与本地 WAI 一致反证现译。"),
    "narancia_ghirga": R("wrong_official_name", "纳兰迦·吉尔卡", "Bangumi 精确角色中文名反证现译。"),
    "nikki_(nikki)": R("wrong_official_name", "暖暖(暖暖系列)", "“妮基”不是该系列主角的简体中文名，Bangumi 亦给出中文姓名反证。"),
    "nonna_(girls_und_panzer)": R("wrong_official_name", "农娜(少女与战车)", "本地 WAI 候选给出作品通行中文名，现译只作英文音译。"),
    "northern_white-faced_owl_(kemono_friends)": R("wrong_official_name", "白脸角鸮(兽娘动物园)", "Bangumi 精确角色中文名反证直译物种名。"),
    "orange_pekoe_(girls_und_panzer)": R("wrong_official_name", "橙黄白毫(少女与战车)", "Bangumi 与本地 WAI 一致反证现译“橙华”。"),
    "oribe_yasuna": R("wrong_official_name", "折部安奈", "Bangumi 与本地 WAI 一致反证姓氏用字。"),
    "otokura_yuuki": R("wrong_official_name", "乙仓悠贵", "现译末字与角色姓名不符。"),
    "otomachi_una": R("wrong_official_name", "音街鳗", "Bangumi 与本地 WAI 候选反证现译“音街音”。"),
    "pekomon_(usada_pekora)": R("wrong_identity", "佩克兽(兔田佩克拉)", "现译把 Pekomon 错配为兔田佩克拉本人，两个身份不可合并。"),
    "phrolova_(wuthering_waves)": R("wrong_official_name", "弗洛洛(鸣潮)", "游戏简体中文名反证现译“芙罗拉”。", "https://wiki.biligame.com/wutheringwaves/%E5%85%B1%E9%B8%A3%E8%80%85/%E5%BC%97%E6%B4%9B%E6%B4%9B"),
    "princess_king_boo": R("wrong_identity", "幽灵王姬", "该 tag 是 King Boo 的公主化同人角色；“布布王”未保留公主化身份。", "https://knowyourmeme.com/memes/princess-boo"),
    "raising_heart": R("wrong_official_name", "旭日之心", "Bangumi 精确角色证据反证“雷神之心”。"),
    "ranma-chan": R("variant_lost", "女乱马", "该 tag 专指女体形态，现译退化为不区分形态的基础角色名。"),
    "rensouhou-kun": R("not_simplified_chinese", "连装炮君", "现译使用日文旧字“連”“砲”，不符合本轮简体中文规范。"),
    "rosehip_(girls_und_panzer)": R("wrong_official_name", "蔷薇果(少女与战车)", "Bangumi 与本地 WAI 一致反证现译“玫瑰果”。"),
    "rover_(wuthering_waves)": R("wrong_official_name", "漂泊者(鸣潮)", "“罗浮”是错配专名；游戏官方称主角为“漂泊者”。", "https://wutheringwaves.kurogames.com/zh-tw/main/news/detail/1188"),
    "roxas": R("wrong_official_name", "洛克萨斯", "Bangumi 精确角色中文名反证现译首字。"),
    "rupa_(girls_band_cry)": R("wrong_official_name", "卢帕(Girls Band Cry)", "Bangumi 精确角色中文名反证现译“瑠波”。"),
    "saijo_juri": R("wrong_official_name", "西城树里", "Bangumi 精确角色中文名反证整段姓名。"),
    "sakuma_mayu": R("wrong_official_name", "佐久间麻由", "Bangumi 与本地 WAI 一致反证名字用字。"),
    "sessyoin_kiara": R("wrong_official_name", "杀生院祈荒", "现译是错误音译，未对应 source tag 的日文姓名。"),
    "shidare_hotaru": R("wrong_official_name", "枝垂萤", "Bangumi 与本地 WAI 一致反证姓氏字序。"),
    "skirk_(genshin_impact)": R("wrong_official_name", "丝柯克(原神)", "游戏简体中文角色名反证现译“斯柯尔”。", "https://wiki.biligame.com/ys/%E6%B2%99%E7%9B%92/%E8%A7%92%E8%89%B2%E4%B8%8A%E7%BA%BF%E6%97%B6%E9%97%B4"),
    "su-san": R("honorific_mistranslated;wrong_identity", "小苏", "tag 中 -san 是敬称，现译误把整体当作人名 Susan。"),
    "sunazuka_akira": R("not_simplified_chinese", "砂冢明", "现译使用日文/旧字“塚”，不符合本轮简体中文规范。"),
    "sylvain_jose_gautier": R("wrong_official_name", "希尔凡·乔泽·戈迪耶", "现译多个人名分段与作品简体中文名不一致。"),
    "takara_miyuki": R("wrong_identity", "高良美幸", "Bangumi 与本地 WAI 一致反证“宝田美雪”。"),
    "takeba_yukari": R("wrong_official_name", "岳羽由加莉", "本地 WAI 候选给出该角色通行中文姓名，现译逐字误配。"),
    "tamura_yuri": R("wrong_official_name", "田村百合", "Bangumi 精确角色中文名反证名字用字。"),
    "tanya_degurechaff": R("wrong_official_name", "谭雅·提古雷查夫", "Bangumi 精确角色中文名反证现译。"),
    "the_herta_(honkai:_star_rail)": R("variant_lost;wrong_official_name", "大黑塔(崩坏:星穹铁道)", "The Herta 是与黑塔人偶分开的本体版本，现译丢失该身份差异。", "https://zh.wikipedia.org/wiki/%E9%BB%91%E5%A1%94_%28%E5%B4%A9%E5%A3%9E%EF%BC%9A%E6%98%9F%E7%A9%B9%E9%90%B5%E9%81%93%29"),
    "till_(alien_stage)": R("wrong_official_name", "蒂尔(异星舞台)", "Bangumi 精确角色中文名反证现译首字。"),
    "timoris_(bang_dream!)": R("wrong_identity", "八幡海铃(BanG Dream!)", "现译“南小春”是错角色；Bangumi 精确角色证据反证。"),
    "tomoe_hotaru": R("wrong_identity", "土萌萤", "现译“巴麻美”是另一作品角色；Bangumi 与本地 WAI 一致反证。"),
    "trish_una": R("wrong_official_name", "特莉休·乌纳", "Bangumi 精确角色中文名反证名字用字。"),
    "tsukino_mito": R("wrong_official_name", "月之美兔", "现译误读姓氏；该 VTuber 的通行中文名是“月之美兔”。"),
    "tsukishiro_yanagi": R("wrong_official_name", "月城柳", "Bangumi 精确角色中文名反证现译姓氏。"),
    "tsurumaki_maki": R("wrong_official_name", "弦卷真纪", "本地 WAI 候选反证现译姓名用字。"),
    "vulpisfoglia_(arknights)": R("wrong_official_name", "忍冬(明日方舟)", "Bangumi 精确角色中文名反证按英文词义直译的“狐尾草”。"),
    "wakan_tanka": R("wrong_transliteration", "瓦坎·坦卡", "现译把专名 Tanka 误写为普通名词“坦克”；Wikidata 候选亦反证。"),
    "wakasagihime": R("wrong_official_name", "若鹭姬", "Bangumi 精确角色中文名反证现译“若狭姬”。"),
    "yanami_anna": R("wrong_identity", "八奈见杏菜", "现译“柳美奈”与 source tag 无对应；Bangumi 精确角色证据反证。"),
    "yotsuba_alice": R("wrong_official_name", "四叶有栖", "现译把日文人名 Arisu 直接音译，未使用作品中文姓名。"),
    "yuutenji_nyamu": R("wrong_official_name", "祐天寺若麦", "现译把 にゃむ 误作“喵”，Wikidata/Bangumi 角色证据反证。", "https://www.wikidata.org/wiki/Q121909754"),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_pack_row(row: Mapping[str, str], source_pack: str) -> dict[str, str]:
    result = {field: str(row.get(field, "")).strip() for field in IMPORT_FIELDS}
    result["source_pack"] = source_pack
    if not result["tag"] or not result["translation_cn"]:
        raise ValueError(f"empty tag/translation in {source_pack}: {row!r}")
    if result["category"] not in {"0", "4"}:
        raise ValueError(f"disallowed category {result['category']} for {result['tag']}")
    int(result["post_count"])
    return result


def evidence_index(path: Path | None, tag_field: str = "tag") -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    return {row[tag_field].strip(): row for row in read_csv(path) if row.get(tag_field, "").strip()}


def source_qualifier_count(tag: str) -> int:
    return len(re.findall(r"_\([^()]+\)", tag))


def target_qualifier_count(translation: str) -> int:
    normalized = translation.replace("（", "(").replace("）", ")")
    return len(re.findall(r"\([^()]+\)", normalized))


def translation_key(value: str) -> str:
    """Compare audited translations while ignoring Latin-only case drift."""
    return unicodedata.normalize("NFKC", value).casefold()


def build(args: argparse.Namespace) -> dict[str, object]:
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    packs = (
        ("general_high_anchor_448", args.general_high_anchor),
        ("general_weilin_delta_68", args.general_weilin_delta),
        ("weilin_character_v2_359", args.character_pack),
    )
    union_rows: list[dict[str, str]] = []
    for source_pack, path in packs:
        union_rows.extend(normalize_pack_row(row, source_pack) for row in read_csv(path))

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in union_rows:
        grouped[row["tag"]].append(row)
    duplicate_rows: list[dict[str, object]] = []
    for tag, rows in sorted(grouped.items()):
        if len(rows) > 1:
            duplicate_rows.append(
                {
                    "tag": tag,
                    "row_count": len(rows),
                    "translations": " | ".join(sorted({row["translation_cn"] for row in rows})),
                    "source_packs": " | ".join(sorted({row["source_pack"] for row in rows})),
                    "is_conflict": "yes" if len({row["translation_cn"] for row in rows}) > 1 else "no",
                }
            )
    if duplicate_rows:
        raise ValueError(f"input safe packs are not a unique union: {len(duplicate_rows)} duplicate tags")

    tags = set(grouped)
    unknown_removals = sorted(set(REMOVALS) - tags)
    if unknown_removals:
        raise ValueError(f"removal decisions refer to absent tags: {unknown_removals}")

    bangumi = evidence_index(args.bangumi_candidates)
    general_high_review = evidence_index(args.general_high_review)
    general_weilin_review = evidence_index(args.general_weilin_review)
    character_review = evidence_index(args.character_review)
    prior_proper = evidence_index(args.prior_proper_evidence)

    union_sorted = sorted(union_rows, key=lambda row: (-int(row["post_count"]), row["tag"]))
    union_path = output_dir / "unique_union_875.csv"
    write_csv(union_path, (*IMPORT_FIELDS, "source_pack"), union_sorted)

    dup_path = output_dir / "duplicate_conflicts.csv"
    write_csv(dup_path, ("tag", "row_count", "translations", "source_packs", "is_conflict"), duplicate_rows)

    decisions: list[dict[str, object]] = []
    final_rows: list[dict[str, str]] = []
    for row in union_sorted:
        tag = row["tag"]
        removal = REMOVALS.get(tag)
        bgm = bangumi.get(tag, {})
        reviewed = (
            general_high_review.get(tag)
            or general_weilin_review.get(tag)
            or character_review.get(tag)
            or {}
        )
        prior = prior_proper.get(tag, {})
        decision = "remove" if removal else "keep"
        if not removal:
            final_rows.append({field: row[field] for field in IMPORT_FIELDS})
        evidence_parts: list[str] = []
        if reviewed:
            evidence_parts.append("reviewed_csv")
        if bgm:
            evidence_parts.append(f"bangumi:{bgm.get('bangumi_url', '')}")
        if prior.get("existing_wai_candidates"):
            evidence_parts.append(f"existing_wai:{prior['existing_wai_candidates']}")
        if removal and removal.evidence_url:
            evidence_parts.append(removal.evidence_url)
        decisions.append(
            {
                **row,
                "decision": decision,
                "issue_types": removal.issue_types if removal else "",
                "reason": removal.reason if removal else "逐条终审未发现有证据支持的语义错误，保留原审核译文。",
                "proposed_correction_cn": removal.proposed_correction_cn if removal else "",
                "bangumi_translation_cn": bgm.get("translation_cn", ""),
                "bangumi_url": bgm.get("bangumi_url", ""),
                "prior_wai_candidates": prior.get("existing_wai_candidates", ""),
                "reviewed_status": reviewed.get("final_status", reviewed.get("status", "")),
                "evidence": " | ".join(evidence_parts),
            }
        )

    decision_fields = (
        *IMPORT_FIELDS,
        "source_pack",
        "decision",
        "issue_types",
        "reason",
        "proposed_correction_cn",
        "bangumi_translation_cn",
        "bangumi_url",
        "prior_wai_candidates",
        "reviewed_status",
        "evidence",
    )
    decisions_path = output_dir / "semantic_decisions_875.csv"
    write_csv(decisions_path, decision_fields, decisions)
    removed_path = output_dir / "suspicious_removed.csv"
    write_csv(removed_path, decision_fields, (row for row in decisions if row["decision"] == "remove"))
    final_path = output_dir / "final_safe_core.csv"
    write_csv(final_path, IMPORT_FIELDS, final_rows)

    bangumi_reconciliation_path = output_dir / "bangumi_safe_reconciliation.csv"
    bangumi_reconciliation: list[dict[str, object]] = []
    if args.bangumi_safe_import:
        old_by_tag = {row["tag"]: row for row in union_rows}
        final_by_tag = {row["tag"]: row for row in final_rows}
        for bgm_row in read_csv(args.bangumi_safe_import):
            tag = bgm_row["tag"].strip()
            old_row = old_by_tag.get(tag)
            final_row = final_by_tag.get(tag)
            if old_row is None:
                status = "bangumi_complement_new"
            elif translation_key(old_row["translation_cn"]) == translation_key(bgm_row["translation_cn"]) and final_row is not None:
                status = "overlap_same_kept"
            elif translation_key(old_row["translation_cn"]) == translation_key(bgm_row["translation_cn"]):
                status = "overlap_same_but_removed"
            elif final_row is not None:
                status = "conflict_with_kept_old"
            else:
                status = "bangumi_can_replace_removed_old"
            bangumi_reconciliation.append(
                {
                    "tag": tag,
                    "category": bgm_row.get("category", ""),
                    "post_count": bgm_row.get("post_count", ""),
                    "bangumi_translation_cn": bgm_row.get("translation_cn", ""),
                    "old_translation_cn": old_row["translation_cn"] if old_row else "",
                    "old_final_decision": "keep" if final_row else ("remove" if old_row else "not_in_old_safe"),
                    "reconciliation_status": status,
                    "recommendation": (
                        "作为独立 Bangumi 安全包的新增项合并"
                        if status == "bangumi_complement_new"
                        else "重复一致，只保留一份"
                        if status == "overlap_same_kept"
                        else "停止交付并人工复核"
                        if status in {"overlap_same_but_removed", "conflict_with_kept_old"}
                        else "用 Bangumi 安全译名替换被移除旧项，但不在本轮 final_safe_core 内自动扩容"
                    ),
                }
            )
    write_csv(
        bangumi_reconciliation_path,
        (
            "tag",
            "category",
            "post_count",
            "bangumi_translation_cn",
            "old_translation_cn",
            "old_final_decision",
            "reconciliation_status",
            "recommendation",
        ),
        bangumi_reconciliation,
    )

    issue_counts: Counter[str] = Counter()
    for removal in REMOVALS.values():
        issue_counts.update(part for part in removal.issue_types.split(";") if part)
    counts_by_source = Counter(row["source_pack"] for row in union_rows)
    kept_by_category = Counter(row["category"] for row in final_rows)
    removed_by_category = Counter(row["category"] for row in union_rows if row["tag"] in REMOVALS)
    source_qualifier_failures = [
        row["tag"]
        for row in final_rows
        if source_qualifier_count(row["tag"]) > target_qualifier_count(row["translation_cn"])
    ]
    long_tag_rows = [
        row["tag"] for row in union_rows if len(row["tag"].split("_")) > 6 or len(row["tag"]) > 64
    ]
    invariants = {
        "input_rows": len(union_rows),
        "unique_tags": len(grouped),
        "expected_input_rows": 875,
        "duplicate_tag_groups": len(duplicate_rows),
        "conflicting_translation_groups": sum(row["is_conflict"] == "yes" for row in duplicate_rows),
        "final_rows": len(final_rows),
        "removed_rows": len(REMOVALS),
        "set_equation_holds": len(final_rows) + len(REMOVALS) == len(union_rows),
        "artist_rows": sum(row["category"] == "1" for row in union_rows),
        "allowed_categories_only": all(row["category"] in {"0", "4"} for row in union_rows),
        "long_weilin_prompt_rows_processed": 0,
        "target_rows_over_short_tag_limit": long_tag_rows,
        "kept_source_qualifier_failures": source_qualifier_failures,
        "no_database_paths_or_connections": True,
    }
    if invariants != {
        **invariants,
        "input_rows": 875,
        "unique_tags": 875,
        "duplicate_tag_groups": 0,
        "conflicting_translation_groups": 0,
        "artist_rows": 0,
        "allowed_categories_only": True,
        "long_weilin_prompt_rows_processed": 0,
        "target_rows_over_short_tag_limit": [],
        "kept_source_qualifier_failures": [],
        "no_database_paths_or_connections": True,
        "set_equation_holds": True,
    }:
        raise AssertionError(f"semantic QA invariant failed: {invariants}")

    invariants_path = output_dir / "invariants.json"
    write_json(invariants_path, invariants)
    reconciliation_counts = Counter(str(row["reconciliation_status"]) for row in bangumi_reconciliation)
    report = {
        "scope": {
            "description": "Final semantic QA of the existing safe core; no database opened or modified",
            "input_packs": {name: str(path.resolve()) for name, path in packs},
            "artist_policy": "excluded",
            "long_weilin_prompt_policy": "out of scope and untouched",
            "correction_policy": "proposed corrections are audit-only; removed rows are not rewritten into final_safe_core",
        },
        "counts": {
            "input_rows": len(union_rows),
            "unique_tags": len(grouped),
            "kept": len(final_rows),
            "removed": len(REMOVALS),
            "proposed_corrections": sum(bool(item.proposed_correction_cn) for item in REMOVALS.values()),
            "by_source_pack": dict(sorted(counts_by_source.items())),
            "kept_by_category": dict(sorted(kept_by_category.items())),
            "removed_by_category": dict(sorted(removed_by_category.items())),
            "issue_types": dict(sorted(issue_counts.items())),
            "bangumi_safe_reconciliation": dict(sorted(reconciliation_counts.items())),
        },
        "evidence": {
            "bangumi_candidates": str(args.bangumi_candidates.resolve()) if args.bangumi_candidates else "",
            "bangumi_overlaps": sum(tag in bangumi for tag in tags),
            "bangumi_translation_differences": sum(
                tag in bangumi and bangumi[tag].get("translation_cn", "") != grouped[tag][0]["translation_cn"]
                for tag in tags
            ),
            "review_csvs": [
                str(path.resolve())
                for path in (
                    args.general_high_review,
                    args.general_weilin_review,
                    args.character_review,
                    args.prior_proper_evidence,
                )
                if path
            ],
        },
        "outputs": {
            path.name: {"path": str(path.resolve()), "sha256": sha256(path)}
            for path in (
                union_path,
                dup_path,
                decisions_path,
                removed_path,
                final_path,
                bangumi_reconciliation_path,
                invariants_path,
            )
        },
        "invariants": invariants,
    }
    report_path = output_dir / "report.json"
    write_json(report_path, report)
    report["outputs"][report_path.name] = {"path": str(report_path.resolve()), "sha256": sha256(report_path)}
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--general-high-anchor", type=Path, required=True)
    result.add_argument("--general-weilin-delta", type=Path, required=True)
    result.add_argument("--character-pack", type=Path, required=True)
    result.add_argument("--general-high-review", type=Path)
    result.add_argument("--general-weilin-review", type=Path)
    result.add_argument("--character-review", type=Path)
    result.add_argument("--prior-proper-evidence", type=Path)
    result.add_argument("--bangumi-candidates", type=Path)
    result.add_argument("--bangumi-safe-import", type=Path)
    result.add_argument("--output-dir", type=Path, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    report = build(args)
    print(json.dumps(report["counts"], ensure_ascii=False, sort_keys=True))
    print(report["outputs"]["final_safe_core.csv"]["sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
