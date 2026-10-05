"""精查：边界放宽（v21/v25）**新**匹配上的条目里，有没有靠错词进来的。

做法：每条规则跑两遍——旧边界 `\\b...\\b` 与放宽后 `(?<![a-z0-9])...(?!...)`，
只取「放宽后匹配、旧边界没匹配」的差集，那是这轮新增的全部来源；
按命中短语聚合，逐条看上下文。

输出：边界新增命中_精查_20260919.md
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
from rebuild_action_scene_v8 import DB, COMBO, denoise, load_wiki  # noqa: E402
import rebuild_action_scene_v12 as V12  # noqa: E402
from fix_review_v14 import PLAN as PLAN14  # noqa: E402
from fix_boundary_v21 import widen_pattern  # noqa: E402

REPORT = HERE / "边界新增命中_精查_20260919.md"
SAMPLE = 25


def main() -> int:
    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))}
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        raw[f"{theme}›{sub}"] = pattern
    raw.update(PLAN14)

    pairs = {}
    for label, p in raw.items():
        if r"\b" not in p:
            continue                      # 只看老式 \b 规则
        pairs[label] = (re.compile(p, re.I), re.compile(widen_pattern(p), re.I))
    print(f"参与对比的老式规则：{len(pairs)} 条")

    with sqlite3.connect(str(DB)) as con:
        rows = con.execute("select t_uuid, text from tag_tags").fetchall()

    added = Counter()
    by_phrase = defaultdict(Counter)
    samples = defaultdict(list)
    for u, text in rows:
        body = denoise(text)
        for label, (rx_old, rx_new) in pairs.items():
            if rx_old.search(body):
                continue                  # 旧边界本来就能命中
            m = rx_new.search(body)
            if not m:
                continue
            added[label] += 1
            by_phrase[label][m.group(0)] += 1
            if len(samples[label]) < SAMPLE * 3:
                s = max(0, m.start() - 30)
                samples[label].append(((("…" + body[s:m.end() + 22] + "…")), m.group(0),
                                       md5(u.encode()).hexdigest()))

    L = ["# 边界放宽新增命中 · 精查", "",
         f"- 参与对比的老式规则：{len(pairs)} 条", "",
         "| 轴 | 新增条目 | 新增里最常见的命中词 |", "| --- | --- | --- |"]
    for label, n in added.most_common():
        top = "、".join(f"`{p}`×{c}" for p, c in by_phrase[label].most_common(3))
        L.append(f"| {label} | {n:,} | {top} |")
    L += ["", "## 逐轴抽样（看命中上下文）", ""]
    for label, _n in added.most_common():
        L.append(f"**{label}**")
        L.append("")
        for ctx, hit, _h in sorted(samples[label], key=lambda x: x[2])[:SAMPLE]:
            L.append(f"- `{hit}` ← {ctx}")
        L.append("")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print("新增命中（按轴）：")
    for label, n in added.most_common(20):
        top = "、".join(f"{p}×{c}" for p, c in by_phrase[label].most_common(2))
        print(f"   {label:<12} +{n:>6,}   {top[:56]}")
    print(f"落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
