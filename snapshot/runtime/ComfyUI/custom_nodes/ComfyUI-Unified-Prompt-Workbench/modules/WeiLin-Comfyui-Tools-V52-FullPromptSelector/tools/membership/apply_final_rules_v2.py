"""第 7 轮：修空模式误伤 + 重建画风规则 + 状态词归位 + 命中率断言（≤30%）。"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from per_entry_theme import denoise  # noqa: E402

DB = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
          r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\userdatas_zh_CN_tags.db")
OUT_JSONL = HERE / "全库归属_v7_20260919.jsonl"
OUT_RULES = HERE / "最终规则_v2_20260919.json"
REPORT = HERE / "审计v7_20260919.md"
COMBO = re.compile(r"一键NSFW|一键模式")
MAX_RATE = 0.30           # 任一规则命中率不得超过 30%

QUALITY = r"\b(highres|absurdres|masterpiece|best quality|very aesthetic|perfect anatomy|" \
          r"official art|ultra detailed|8k|4k|high resolution)\b"
ARTIST = r"(?:artist\s*[:：]|<artist>|\b画师\b|\bartist\b)"
STATE = r"\b(unbuttoned|undressing|open clothes|opened|pulled down|pulled up|slipped|shrugged off|" \
        r"discarded|removed|half[- ]dressed|torn clothes|wet clothes|clothes off)\b"

RULES: list[tuple[str, str, str]] = [
    ("人物数量", "在场人数", r"\b(1girl|2girls|3girls|multiple girls|1boy|2boys|multiple boys|"
                              r"boy and girl|yuri|pair|group|duo|solo)\b|\b(girl|boy|woman|man|female|male)\b"),
    ("画风", "画质", QUALITY),
    ("画风", "画师", ARTIST),
    ("外貌", "面部", r"\b(face|eyes|eyelashes|hair between eyes|blush|smile|expression|looking at viewer|"
                     r"closed eyes|half closed|heterochromia|tears|eyebrows)\b"),
    ("外貌", "发型", r"\b(hair|ponytail|twintails|braid|braids|bangs|headband|ahoge|hair ornament)\b"),
    ("外貌", "身体", r"\b(huge breasts|large breasts|breasts|nipples|navel|skin|thighs|muscular|slim|"
                     r"skinny|belly|hips|butt|tall|short|petite|chubby|fat|abs|collarbone|shoulder|neck)\b"),
    ("服饰", "上装", r"\b(shirt|tank top|sweater|hoodie|jacket|coat|blouse|bra|bikini top|corset|vest)\b"),
    ("服饰", "下装", r"\b(skirt|pants|shorts|leggings|jeans|trousers|panties|thong)\b"),
    ("服饰", "鞋袜", r"\b(socks|stockings|thighhighs|pantyhose|boots|heels|shoes|sneakers)\b"),
    ("服饰", "配饰", r"\b(necklace|choker|collar|ribbon|bow|gloves|hat|cap|glasses|earrings|belt|bag|"
                     r"pendant|tiara|veil)\b"),
    ("服饰", "通用", r"\b(dress|gown|uniform|costume|outfit|clothing|clothes|lingerie|swimsuit|bikini|"
                     r"kimono|yukata|hanfu|qipao|armor|suit|apron|robe)\b"),
    ("状态", "半脱", STATE),
    ("动作", "姿态", r"\b(sitting|standing|lying|kneeling|crouching|squatting|on back|on stomach|"
                     r"upside down|handstand|bent over|leaning|spread legs|crossed legs|pose|plank|"
                     r"one leg|reaching|stretching|bending|turning|walking|running|jumping|flying|"
                     r"floating|dancing|kicking|punching|legs up|arms up|arms behind)\b"),
    ("动作", "手部", r"\b(holding|holds|hand on|hands on|arm|arms|fingers|finger|grabbing|grabbing hold|"
                     r"pinching|caressing|thumbs up|peace sign|hand up|hands up)\b"),
    ("动作", "腿部", r"\b(leg|legs|feet|foot|thigh|knee|knees|toes|armpits|barefoot)\b"),
    ("场景", "室内", r"\b(indoors|interior|bedroom|bathroom|kitchen|office|classroom|room|sofa|bed|"
                     r"chair|table|floor|ceiling|mirror)\b"),
    ("场景", "室外", r"\b(outdoors|street|forest|beach|pool|sky|cloud|clouds|city|bridge|road|temple|"
                     r"snow|field|mountain|river|lake|sea|tree|trees|grass|flower|flowers|moon|stars|"
                     r"sunset|sunrise|dusk|dawn)\b"),
    ("场景", "背景", r"\b(background|scenery|wall|window|distant|horizon)\b"),
    ("成人", "性交", r"\b(sex|vaginal|penetration|cowgirl position|mating press|from behind|missionary|"
                     r"straddling|spitroast)\b"),
    ("成人", "前戏", r"\b(footjob|fellatio|oral|paizuri|handjob|foreplay|cum|cumshot)\b"),
    ("成人", "露出", r"\b(nsfw|nude|naked|topless|bottomless|exposed|showing breasts|nipples visible)\b"),
    ("成人", "特殊", r"\b(rape|bondage|restrained|tentacle|tentacles|futanari|futa|bestiality|"
                      r"corruption|transformed)\b"),
    ("道具", "器物", r"\b(book|books|cup|glass|bottle|food|cake|fruit|camera|phone|umbrella|balloon|"
                      r"plant|knife|gun|sword|staff|box|bag|doll|teddy bear)\b"),
    ("角色", "原作", r"\b(arknights|genshin|blue archive|bluearchive|fate|touhou|honkai|azur lane|"
                     r"nikke|vocaloid|project moon|girls frontline|splatoon|hololive)\b"),
    ("角色", "种族", r"\b(dragon|elf|demon|angel|catgirl|fox girl|beast|monster|robot|mecha|slime|"
                     r"vampire|dragonborn|kemono|dog girl|animal ears)\b"),
    ("角色", "职业", r"\b(maid|nurse|idol|teacher|student|knight|ninja|witch|police|office lady|"
                     r"flight attendant|scientist)\b"),
]


def main() -> int:
    rules = [(theme, sub, re.compile(pattern, re.I)) for theme, sub, pattern in RULES]
    with sqlite3.connect(str(DB)) as con:
        groups = {row[0]: row[1] for row in con.execute("select id_index, name from tag_groups")}
        subs = {row[0]: (row[1], row[2]) for row in
                con.execute("select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
    stats: Counter = Counter()
    samples: dict[str, list[str]] = {}
    membership_stats: Counter = Counter()
    total = zero = 0
    with OUT_JSONL.open("w", encoding="utf-8") as handle:
        for uuid, subgroup_id, text in rows:
            entry = subs.get(subgroup_id)
            area = groups.get(entry[0], "") if entry else ""
            if COMBO.search(area):
                continue
            total += 1
            body = denoise(text or "")
            hits: list[str] = []
            for theme, sub, pattern in rules:
                match = pattern.search(body)
                if not match:
                    continue
                label = f"{theme}›{sub}"
                if label in hits:
                    continue
                hits.append(label)
                stats[label] += 1
                bucket = samples.setdefault(label, [])
                if len(bucket) < 3:
                    bucket.append(body[max(0, match.start() - 20):match.end() + 20].strip())
            membership_stats[len(hits)] += 1
            if not hits:
                zero += 1
            handle.write(json.dumps({"id": uuid, "source": area, "leaf": entry[1] if entry else "",
                                     "memberships": hits, "text": (text or "")[:150]},
                                    ensure_ascii=False) + "\n")
    violations = [(label, count) for label, count in stats.items() if count / total > MAX_RATE]
    lines = ["# 第 7 轮审计（修空模式 + 重建画风 + 状态归位）", "",
             f"- 参与 tag {total:,}；零归属 {zero:,}（{zero / total * 100:.1f}%）",
             f"- 平均归属 {sum(k * v for k, v in membership_stats.items()) / total:.2f} 个/条",
             f"- **命中率 >{MAX_RATE:.0%} 的规则（断言违规）：{len(violations)}**", "",
             "| 规则 | 命中 | 命中率 | 片段样例 |", "| --- | --- | --- | --- |"]
    for label, count in stats.most_common():
        lines.append(f"| {label} | {count:,} | {count / total * 100:.1f}% | "
                     f"{'；'.join(samples.get(label, []))} |")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    OUT_RULES.write_text(json.dumps([{"theme": t, "sub": s, "pattern": p} for t, s, p in RULES],
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"参与 {total:,}；零归属 {zero:,}（{zero / total * 100:.1f}%）；"
          f"平均归属 {sum(k * v for k, v in membership_stats.items()) / total:.2f}")
    print(f"违规规则（>{MAX_RATE:.0%}）：{violations}")
    for label, count in stats.most_common(8):
        print(f"   {label:<16} {count:>7,} ({count / total * 100:>5.1f}%)  例：{(samples.get(label) or [''])[0][:44]}")
    print(f"落盘：{OUT_JSONL.name} / {OUT_RULES.name} / {REPORT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
