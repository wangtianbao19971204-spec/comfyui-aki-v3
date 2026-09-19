"""逐条定主题（补英文 booru 词表）：叶层只留来源，条层带主题+面。"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from theme_finalize_v7 import denoise  # noqa: E402

DB = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
          r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\userdatas_zh_CN_tags.db")
OUT_JSONL = HERE / "来源批次_逐条主题_20260919.jsonl"
REPORT = HERE / "来源批次_逐条主题统计_20260919.md"
TARGET_AREAS = ["社区 · AI杂图", "第1卷", "第2卷", "第3卷", "第4卷", "一些个人未能整好的串"]

# 英文 booru 词表（按主题→小分类）
EN: list[tuple[str, str, str]] = [
    ("角色", "原作", r"\b(arknights|genshin|blue archive|fate|touhou|honkai|azur lane|nikke|vocaloid|"
                     r"project moon|bluearchive|girls frontline)\b"),
    ("角色", "种族", r"\b(dragon|elf|demon|angel|catgirl|fox|beast|monster|robot|mecha|slime|vampire|"
                     r"dragonborn|kemono)\b"),
    # 人物在场/数量：只做"面"，不参与主主题竞争（几乎每条都有，会盖掉动作/服饰）
    ("人物数量", "在场人数", r"\b(1girl|2girls|3girls|multiple girls|1boy|2boys|multiple boys|boy and girl|"
                              r"yuri|pair|group|duo|solo)\b|\b(girl|boy|woman|man|male|female)\b"),
    ("角色", "关系", r"\b(boy and girl|yuri|couple|pairing|two shot)\b"),
    ("动作", "姿态", r"\b(sitting|standing|lying|kneeling|crouching|squatting|on back|on stomach|"
                     r"upside down|handstand|bent over|leaning|spread legs|crossed legs|jojo pose|pose|"
                     r"plank|carry|bridal carry|one leg)\b"),
    ("动作", "手部", r"\b(holding|hand on|hands on|arm|arms|fingers|grabbing|pinching|caressing|"
                     r"thumbs up|peace sign)\b"),
    ("动作", "腿部", r"\b(leg|legs|feet|foot|thigh|knee|toes|armpits)\b"),
    ("外貌", "面部", r"\b(face|eyes|eyelashes|hair between eyes|blush|smile|expression|looking at viewer|"
                     r"closed eyes|half closed|heterochromia|tears)\b"),
    ("外貌", "发型", r"\b(hair|ponytail|twintails|braid|bangs|headband|ahoge)\b"),
    ("外貌", "身体", r"\b(huge breasts|large breasts|breasts|nipples|navel|skin|thighs|muscular|slim|"
                     r"skinny|belly|hips|butt)\b"),
    ("服饰", "上装", r"\b(shirt|tank top|sweater|jacket|coat|dress|uniform|hoodie|bra| bikini top)\b"),
    ("服饰", "下装", r"\b(skirt|pants|shorts|leggings|jeans)\b"),
    ("服饰", "鞋袜", r"\b(socks|stockings|thighhighs|boots|heels|shoes)\b"),
    ("服饰", "配饰", r"\b(necklace|choker|collar|ribbon|bow|gloves|hat|glasses|earrings|belt|bag)\b"),
    ("服饰", "通用", r"\b(costume|outfit|clothes|clothing|lingerie|swimsuit|bikini)\b"),
    ("场景", "室内", r"\b(indoors|bedroom|bathroom|kitchen|office|classroom|room)\b"),
    ("场景", "室外", r"\b(outdoors|street|forest|beach|pool|sky|city|temple|snow|field)\b"),
    ("场景", "背景", r"\b(background|scenery|wall|window|night|day|light|shadow|particles)\b"),
    ("成人", "性交", r"\b(sex|vaginal|penetration|cowgirl position|mating press|from behind|missionary)\b"),
    ("成人", "前戏", r"\b(footjob|fellatio|oral|paizuri|handjob|foreplay|cum)\b"),
    ("成人", "露出", r"\b(nsfw|uncensored|nude|naked|topless|exposed|showing)\b"),
    ("成人", "特殊", r"\b(rape|bondage|restrained|tentacle|futanari|futa|bestiality)\b"),
    ("画风", "画质", r"\b(perfect composition|perfect anatomy|amazing|detail|detailed|highres|best quality|"
                     r"masterpiece|absurdres|quality|resolution|no text|watermark|signature|"
                     r"official art|very aesthetic)\b"),
    ("画风", "画师", r"\b(artist|artstyle|style)\b|画师|画风"),
    ("场景", "室外", r"\b(sky|cloud|clouds|water|river|lake|sea|tree|trees|grass|flower|flowers|"
                      r"mountain|building|road|bridge|moon|star|stars|sunset|sunrise|dusk|dawn)\b"),
    ("场景", "室内", r"\b(interior|furniture|sofa|bed|chair|table|door|floor|ceiling|mirror|lamp)\b"),
    ("道具", "器物", r"\b(book|books|cup|glass|bottle|food|cake|fruit|camera|phone|mirror|umbrella|"
                      r"balloon|flower|plant|knife|gun|sword|staff|box|bag|hat)\b"),
    ("服饰", "通用", r"\b(armor|armour|kimono|yukata|hanfu|qipao|cheongsam|maid|nurse|school uniform|"
                      r"serafuku|sailor|suit|wedding dress|gothic|dress)\b"),
    ("外貌", "身体", r"\b(tall|short|petite|chubby|fat|thin|muscular|abs|collarbone|shoulder|neck|"
                      r"hand|hands|finger|fingers)\b"),
    ("动作", "姿态", r"\b(reaching|stretching|bending|turning|walking|running|jumping|flying|floating|"
                      r"dancing|kicking|punching|holding up|arms behind|legs up)\b"),
]
SOURCE_ONLY = re.compile(r"图包|收录|杂图|精选|整理|筛选|合集|画廊|第\d+卷|社区|个人")


def themes_of(text: str) -> tuple[str, list[str]]:
    body = denoise(text)
    hits: list[str] = []
    for theme, sub, pattern in EN:
        if re.search(pattern, body, re.I):
            label = f"{theme}›{sub}"
            if label not in hits:          # 同一 (主题›小分类) 只记一次
                hits.append(label)
    if hits:
        # 主主题优先级：信息量高的优先；"人物数量/画风画质"只作面，不当主主题
        order = {"成人": 0, "动作": 1, "服饰": 2, "外貌": 3, "场景": 4, "角色": 5, "人物数量": 8, "画风": 9}
        primary = [hit for hit in hits if hit.split("›")[0] not in ("人物数量", "画风")]
        pool = primary or hits
        pool.sort(key=lambda item: order.get(item.split("›")[0], 7))
        return pool[0].split("›")[0], hits
    return "来源包", []


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="跑全库（默认只看来源批次）")
    args = parser.parse_args()
    with sqlite3.connect(str(DB)) as con:
        groups = {row[0]: row[1] for row in con.execute("select id_index, name from tag_groups")}
        subs = {row[0]: (row[1], row[2]) for row in
                con.execute("select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
    per_leaf: dict[str, Counter] = defaultdict(Counter)
    facet_counter: Counter = Counter()
    out = OUT_JSONL.open("w", encoding="utf-8")
    total = 0
    for uuid, subgroup_id, text in rows:
        entry = subs.get(subgroup_id)
        area = groups.get(entry[0], "") if entry else ""
        if not args.all and area not in TARGET_AREAS:
            continue
        theme, hits = themes_of(text or "")
        total += 1
        per_leaf[f"{area} / {entry[1][:18]}"][theme] += 1
        for hit in hits:
            facet_counter[hit] += 1
        out.write(json.dumps({"id": uuid, "source": area, "leaf": entry[1], "theme": theme,
                              "memberships": hits, "text": (text or "")[:140]}, ensure_ascii=False) + "\n")
    out.close()
    lines = ["# 来源批次：逐条定主题（补英文词表）", "",
             f"- 参与条目 {total:,}（叶层只留来源，主题落在条上）", "",
             "| 来源 / 叶子 | 各主题条数 |", "| --- | --- |"]
    for leaf, counter in sorted(per_leaf.items(), key=lambda kv: -sum(kv[1].values())):
        detail = "、".join(f"{theme} {count:,}" for theme, count in counter.most_common())
        lines.append(f"| {leaf} | {detail} |")
    lines += ["", "## 条级归属（小分类）Top20", "", "| 小分类 | 条数 |", "| --- | --- |"]
    for name, count in facet_counter.most_common(20):
        lines.append(f"| {name} | {count:,} |")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"参与 {total:,} 条")
    for leaf, counter in sorted(per_leaf.items(), key=lambda kv: -sum(kv[1].values()))[:9]:
        print(f"   {leaf[:26]:<28} " + "、".join(f"{t} {c:,}" for t, c in counter.most_common(4)))
    print(f"落盘：{OUT_JSONL.name} / {REPORT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
