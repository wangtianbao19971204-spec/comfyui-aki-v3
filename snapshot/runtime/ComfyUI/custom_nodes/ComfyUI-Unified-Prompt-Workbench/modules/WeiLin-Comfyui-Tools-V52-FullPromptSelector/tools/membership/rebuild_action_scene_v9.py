"""第 9 轮：动作 / 场景 精确重建（v8 假阳性修复后定稿候选）。

v8 抽样发现的问题与修法：
1. 单字符短语（`v`）命中一切 v 开头词        -> 短语长度断言（单词短语 >= 4 字符）
2. 弱动词（folded / split / yoga / floating）误伤服饰 -> 显式弱词表剔除
3. tag_group:feet 里全是袜子/鞋子/足交        -> 腿部只用 posture 的腿/膝/脚段落
4. `floating_scarf` `sleeves_folded_up` 这类   -> 短语后接衣物/杂物名词时判否（负向断言）
5. `office lady` / `studio ghibli` 误伤        -> 单字地点歧义词剔除（office / studio / water / plain / stream / nature / park）
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rebuild_action_scene_v8 import (  # noqa: E402
    DB, COMBO, denoise, load_wiki, load_old_rules, section_tags,
)

OUT_JSONL = HERE / "全库_面与主题_v9_20260919.jsonl"
OUT_RULES = HERE / "最终规则_v3_20260919.json"
REPORT = HERE / "动作场景重建_v9_20260919.md"
SAMPLES = HERE / "动作场景抽样_v9_每类32条_20260919.md"

MAX_RATE = 0.30
SAMPLE_PER_CLASS = 32

# 规则 1：短语长度/弱词断言
WEAK_PHRASES = {
    "v", "w", "x", "s",
    "folded", "split", "yoga", "floating", "pose", "poses",
    "eye contact", "natural", "object", "alone",
}
MIN_SINGLE_TOKEN = 4

# 规则 2：地点单字歧义词（会命中 office lady / studio ghibli / water drop / plain ...）
AMBIGUOUS_PLACES = {
    "office", "studio", "water", "plain", "stream", "nature", "park",
    "field", "hall", "court", "bar", "club", "ring", "stage",
}

# 规则 3：短语后面紧跟这些名词时，说明它修饰的是物件/环境而不是人
OBJECT_SUFFIX = (
    "scarf", "hair", "hair_strand", "strand", "strands", "cloth", "clothes", "clothing",
    "skirt", "dress", "sleeve", "sleeves", "ribbon", "petal", "petals", "leaf", "leaves",
    "paper", "light", "spark", "sparks", "sparkle", "sparkles", "feather", "feathers",
    "fabric", "bubble", "bubbles", "smoke", "cloud", "clouds", "snow", "dust", "sand",
    "ash", "flame", "flames", "particle", "particles", "string", "strings", "rope",
)


def keep_phrase(p: str) -> bool:
    p = (p or "").strip().lower()
    if not p or p.startswith("!") or p.startswith("tag_group:"):
        return False
    if p in WEAK_PHRASES:
        return False
    toks = [t for t in re.split(r"[ _]+", p) if t]
    if not toks:
        return False
    if len(toks) == 1 and len(toks[0]) < MIN_SINGLE_TOKEN:
        return False
    return True


def phrase_pattern(phrases, extra=""):
    parts = []
    for p in phrases:
        if not keep_phrase(p):
            continue
        toks = [re.escape(t) for t in re.split(r"[ _]+", p.strip().lower()) if t]
        parts.append(r"[ _]+".join(toks))
    if extra:
        parts.append(extra)
    parts = sorted(set(parts), key=len, reverse=True)
    if not parts:
        return r"(?!x)x"
    body = "|".join(parts)
    guard = r"(?![ _]+(?:" + "|".join(OBJECT_SUFFIX) + r")(?![a-z0-9]))"
    return r"(?<![a-z0-9])(?:" + body + r")(?![a-z0-9])" + guard


def build_rules(wiki):
    posture = wiki["tag_group:posture"]["tags"]
    gestures = wiki["tag_group:gestures"]["tags"]

    legs = []
    for s in wiki["tag_group:posture"]["sections"]:
        if any(k in s["section"].lower()
               for k in ("leg location", "knee location", "foot position")):
            legs.extend(s["tags"])

    indoor = [t for t in section_tags(wiki, "tag_group:locations", "indoors")
              if t not in AMBIGUOUS_PLACES]
    outdoor = [t for t in section_tags(wiki, "tag_group:locations", "natural settings")
               if t not in AMBIGUOUS_PLACES]

    return [
        ("动作", "姿态", phrase_pattern(posture), len([p for p in posture if keep_phrase(p)])),
        ("动作", "手势", phrase_pattern(gestures), len([p for p in gestures if keep_phrase(p)])),
        ("动作", "腿部", phrase_pattern(sorted(set(legs))),
         len([p for p in set(legs) if keep_phrase(p)])),
        ("场景", "室内", phrase_pattern(indoor), len(indoor)),
        ("场景", "室外", phrase_pattern(outdoor, extra=r"outdoors"), len(outdoor) + 1),
    ]


def main() -> int:
    wiki = load_wiki()
    new_rules = build_rules(wiki)
    old_rules, dropped = load_old_rules()
    rules = old_rules + [(t, s, p) for t, s, p, _n in new_rules]
    compiled = [(t, s, re.compile(p, re.I)) for t, s, p in rules]

    with sqlite3.connect(str(DB)) as con:
        groups = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()

    stats: Counter = Counter()
    samples: dict[str, list[dict]] = {}
    total = zero = 0
    new_labels = {f"{t}›{s}" for t, s, _p, _n in new_rules}

    with OUT_JSONL.open("w", encoding="utf-8") as handle:
        for uuid, subgroup_id, text in rows:
            entry = subs.get(subgroup_id)
            area = groups.get(entry[0], "") if entry else ""
            if COMBO.search(area):
                continue
            total += 1
            body = denoise(text)
            hits: list[str] = []
            for theme, sub, pattern in compiled:
                m = pattern.search(body)
                if not m:
                    continue
                label = f"{theme}›{sub}"
                if label in hits:
                    continue
                hits.append(label)
                stats[label] += 1
                if label in new_labels and len(samples.setdefault(label, [])) < SAMPLE_PER_CLASS:
                    samples[label].append({
                        "text": body[:120],
                        "hit": m.group(0),
                        "leaf": entry[1] if entry else "",
                        "area": area,
                    })
            if not hits:
                zero += 1
            handle.write(json.dumps({"id": uuid, "source": area,
                                     "leaf": entry[1] if entry else "",
                                     "memberships": hits, "text": (text or "")[:150]},
                                    ensure_ascii=False) + "\n")

    FACET_EXEMPT = ("人物数量", "外貌")   # 面类天然高命中（人物数量/外貌）
    violations = [(lbl, c) for lbl, c in stats.items()
                  if c / total > MAX_RATE and not lbl.startswith(FACET_EXEMPT)]

    lines = ["# 第 9 轮：动作 / 场景 精确重建（定稿候选）", "",
             f"- 参与 tag：{total:,}（已排除一键组合区）",
             f"- 零归属：{zero:,}（{zero / total * 100:.1f}%）",
             f"- 移除旧规则：{', '.join(dropped)}",
             f"- 主题规则命中率断言（≤{MAX_RATE:.0%}，除外天然高命中的面类）："
             f"{'通过' if not violations else '**违规** ' + str(violations)}", "",
             "## 新规则短语数 / 命中", "",
             "| 规则 | 短语数 | 命中 | 命中率 |", "| --- | --- | --- | --- |"]
    for t, s, _p, n in new_rules:
        lbl = f"{t}›{s}"
        c = stats[lbl]
        lines.append(f"| {lbl} | {n} | {c:,} | {c / total * 100:.2f}% |")
    lines += ["", "## 全量规则命中", "", "| 规则 | 命中 | 命中率 |", "| --- | --- | --- |"]
    for lbl, c in stats.most_common():
        lines.append(f"| {lbl} | {c:,} | {c / total * 100:.2f}% |")
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    s_lines = [f"# 动作 / 场景 抽样（每类 {SAMPLE_PER_CLASS} 条）", ""]
    for t, s, _p, _n in new_rules:
        lbl = f"{t}›{s}"
        s_lines += [f"## {lbl}  （命中 {stats[lbl]:,}）", "",
                    "| # | 文本 | 命中短语 | 来源 | 叶子 |", "| --- | --- | --- | --- | --- |"]
        for i, x in enumerate(samples.get(lbl, []), 1):
            s_lines.append(f"| {i} | {x['text'].replace('|', '/')} | `{x['hit']}` | "
                           f"{x['area']} | {x['leaf']} |")
        s_lines.append("")
    SAMPLES.write_text("\n".join(s_lines), encoding="utf-8")

    OUT_RULES.write_text(json.dumps(
        [{"theme": t, "sub": s, "pattern": p} for t, s, p in rules],
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"参与 {total:,}；零归属 {zero:,}（{zero / total * 100:.1f}%）")
    print(f"断言违规：{violations if violations else '无'}")
    for t, s, _p, n in new_rules:
        lbl = f"{t}›{s}"
        print(f"  {lbl:<10} 短语{n:>4}  命中 {stats[lbl]:>7,} ({stats[lbl] / total * 100:>5.2f}%)")
    print(f"落盘：{OUT_JSONL.name} / {OUT_RULES.name} / {REPORT.name} / {SAMPLES.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
