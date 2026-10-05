"""全规则 × 全短语的命中扫描：自动把「泛词」找出来。

做法：把每条规则拆成一个个短语，用分词 n-gram 查表统计每个短语命中多少条，
凡是命中率过高的短语就是"撑起整条规则的泛词"，逐条列出来审查。

输出：短语命中扫描_20260919.md
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rebuild_action_scene_v8 import DB, COMBO, load_wiki  # noqa: E402
import rebuild_action_scene_v12 as V12  # noqa: E402
from fix_review_v14 import (  # noqa: E402
    BODY_PATTERN, PLAN as PLAN14,
)

REPORT = HERE / "短语命中扫描_20260919.md"
TOKEN = re.compile(r"[^a-z0-9']+")
MAXN = 5
FLAG_RATE = 0.03          # 单个短语命中率超过 3% 就要人工看一眼


def split_alternation(pattern: str):
    """把 a|b|c 形式的正则拆成短语列表（只处理最外层那一组括号）。"""
    # 找第一个"非环视"的括号：跳过 (?<...)、(?=...)、(?!...)
    start = -1
    pos = 0
    while True:
        i = pattern.find("(", pos)
        if i < 0:
            break
        tail = pattern[i:i + 3]
        if tail in ("(?<", "(?=", "(?!", "(?i", "(?m"):
            pos = i + 1
            continue
        start = i
        break
    if start < 0:
        return [pattern]
    depth = 0
    end = None
    for i in range(start, len(pattern)):
        c = pattern[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return [pattern]
    inner = pattern[start + 1:end].lstrip("?:")
    parts, depth, cur = [], 0, []
    for c in inner:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur))
    return parts


def to_phrase(part: str):
    """把一条正则片段还原成可查表的短语；还原不了就返回 None。"""
    s = part.strip()
    if not s or len(s) > 40:
        return None
    s = s.replace(r"\b", " ").replace(r"\-", "-").replace(r"\.", ".")
    s = s.replace(r"\(", "(").replace(r"\)", ")")
    s = re.sub(r"\[\-\s\]", " ", s)
    s = re.sub(r"\[\s\]", " ", s)
    s = re.sub(r"\\(.)", r"\1", s)
    s = s.strip("^$()?:*=+ ")
    s = s.replace("_", " ").replace("-", " ").replace(".", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if not s or len(s) < 2 or re.search(r"[\[\]\\|{}*+?]", s):
        return None
    if not re.fullmatch(r"[a-z0-9' ]+", s):
        return None
    return s


def main() -> int:
    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))}
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        raw[f"{theme}›{sub}"] = pattern
    raw.update(PLAN14)                       # v14 定稿的 6 条覆盖旧版

    rules = {}
    for label, pattern in raw.items():
        phrases = [p for p in (to_phrase(x) for x in split_alternation(pattern)) if p]
        if phrases:
            rules[label] = sorted(set(phrases))

    lookup = defaultdict(set)
    for label, phrases in rules.items():
        for p in phrases:
            lookup[p].add(label)

    with sqlite3.connect(str(DB)) as con:
        gdb = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()

    total = 0
    phrase_hits = Counter()
    rule_hits = Counter()
    rule_phrases = defaultdict(Counter)
    zero_by_area = Counter()
    zero_total_by_area = Counter()
    zero_samples = defaultdict(list)

    for _u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        if COMBO.search(area):
            continue
        total += 1
        zero_total_by_area[area] += 1
        toks = [t for t in TOKEN.split((text or "").lower()) if t]
        found = set()
        hit_phrases = set()          # 同一条 tag 里同一个短语只算一次
        n = len(toks)
        for i in range(n):
            for k in range(1, MAXN + 1):
                if i + k > n:
                    break
                gram = " ".join(toks[i:i + k])
                g = lookup.get(gram)
                if g:
                    found |= g
                    hit_phrases.add(gram)
        for gram in hit_phrases:
            phrase_hits[gram] += 1
        for label in found:
            rule_hits[label] += 1
        if not found:
            zero_by_area[area] += 1
            if len(zero_samples[area]) < 3 and text:
                zero_samples[area].append(text[:80])

    generic = [(p, c) for p, c in phrase_hits.most_common() if c / total > FLAG_RATE]

    L = ["# 短语命中扫描（全规则 × 全短语）", "",
         f"- 参与 tag：{total:,}；规则 {len(rules)} 条；短语 {len(lookup):,} 个",
         f"- 单短语命中率超过 {FLAG_RATE:.0%} 的「泛词」：**{len(generic)} 个**", "",
         "## 一、泛词清单（这些是撑起整条规则的宽词，逐个审）", "",
         "| 短语 | 命中 | 命中率 | 挂在哪些规则 |", "| --- | --- | --- | --- |"]
    for p, c in generic:
        L.append(f"| `{p}` | {c:,} | {c / total * 100:.1f}% | "
                 f"{'、'.join(sorted(lookup[p]))} |")

    L += ["", "## 二、每条规则 Top12 短语", ""]
    for label, cnt in rule_hits.most_common():
        ph = [(p, phrase_hits[p]) for p in rules[label] if phrase_hits[p]]
        ph.sort(key=lambda x: -x[1])
        L.append(f"**{label}**（命中 {cnt:,}，短语 {len(rules[label])} 个）")
        L.append("")
        L.append("、".join(f"`{p}`×{c:,}" for p, c in ph[:12]) or "（无命中）")
        L.append("")

    L += ["## 三、零归属条目（按区域）", "",
          f"合计 {sum(zero_by_area.values()):,} 条（{sum(zero_by_area.values()) / total * 100:.1f}%）", "",
          "| 区域 | 条目 | 零归属 | 占比 | 样例 |", "| --- | --- | --- | --- | --- |"]
    for area, z in zero_by_area.most_common(25):
        t = zero_total_by_area[area]
        L.append(f"| {area} | {t:,} | {z:,} | {z / t * 100:.0f}% | "
                 f"{'；'.join(x.replace('|', '/') for x in zero_samples[area][:2])} |")

    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"参与 {total:,}；规则 {len(rules)}；短语 {len(lookup):,}")
    print(f"泛词（>{FLAG_RATE:.0%}）：{len(generic)} 个")
    for p, c in generic[:30]:
        print(f"   {p:<22} {c:>7,} ({c / total * 100:>5.1f}%)  {'、'.join(sorted(lookup[p]))[:60]}")
    print(f"零归属 {sum(zero_by_area.values()):,}（{sum(zero_by_area.values()) / total * 100:.1f}%）")
    print(f"落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
