"""多轮核实：冲突组合 / 每主题随机抽样 / 单短语独占 / 零归属构成。

用法： python verify_rounds.py
输出：归属多轮核实_20260919.md
"""
from __future__ import annotations

import json
import random
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
from scan_rule_phrases import split_alternation, to_phrase  # noqa: E402

REPORT = HERE / "归属多轮核实_20260919.md"
SAMPLE = 40

# 不该同时出现的组合（互斥）
CONFLICT = [
    ("场景›室内", "场景›室外"),
    ("角色›原作", "一键"),
]


def main() -> int:
    with sqlite3.connect(str(DB)) as con:
        gdb = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
        meta = {}
        for u, b in con.execute("select tag_uuid, data from workbench_tag_meta"):
            try:
                meta[u] = json.loads(b)
            except Exception:
                meta[u] = {}

    # ---------- 第一轮：冲突组合 ----------
    conflict_hits = defaultdict(list)
    for u, s, text in rows:
        d = meta.get(u)
        if d is None:
            continue
        labs = set(d.get("themes", [])) | set(d.get("facets", []))
        for a, b in CONFLICT:
            if a in labs and b in labs:
                conflict_hits[f"{a} + {b}"].append((text or "")[:60])

    # 先把规则编好（第二轮也要用）
    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))}
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        raw[f"{theme}›{sub}"] = pattern
    raw.update(PLAN14)
    comp = {k: re.compile(widen_pattern(v) if r"\b" in v else v, re.I)
            for k, v in raw.items()}

    # ---------- 第二轮：每主题随机抽样（带命中上下文） ----------
    by_label = defaultdict(list)
    for u, s, text in rows:
        d = meta.get(u)
        if d is None:
            continue
        body = denoise(text)
        for lab in list(d.get("themes", [])) + list(d.get("facets", [])):
            rx = comp.get(lab)
            hit, ctx = "", ""
            if rx:
                m = rx.search(body)
                if m:
                    hit = m.group(0)
                    st = max(0, m.start() - 26)
                    ctx = "…" + body[st:m.end() + 20] + "…"
            by_label[lab].append((ctx or (text or "")[:70], hit,
                                  md5(u.encode()).hexdigest()))
    random.seed(20260919)
    samples = {k: random.sample(v, min(SAMPLE, len(v))) for k, v in by_label.items()}

    # ---------- 第三轮：单短语独占 ----------
    phrase_hits = defaultdict(Counter)
    rule_tot = Counter()
    for u, s, text in rows:
        d = meta.get(u)
        if d is None:
            continue
        body = denoise(text)
        for label, rx in comp.items():
            m = rx.search(body)
            if not m:
                continue
            rule_tot[label] += 1
            phrase_hits[label][m.group(0)] += 1
    dom = []
    for label, tot in rule_tot.items():
        if tot < 50:
            continue
        p, c = phrase_hits[label].most_common(1)[0]
        if c / tot > 0.5:
            dom.append((label, p, c, tot, c / tot))

    # ---------- 第四轮：零归属构成 ----------
    zero_by_area = Counter()
    zero_total = Counter()
    zero_samples = defaultdict(list)
    for u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        if COMBO.search(area):
            continue
        d = meta.get(u)
        if d is None:
            continue
        zero_total[area] += 1
        if not d.get("themes") and not d.get("facets"):
            zero_by_area[area] += 1
            if len(zero_samples[area]) < 3:
                zero_samples[area].append((text or "")[:60])

    L = ["# 归属多轮核实", ""]
    L += ["## 第一轮：互斥组合", ""]
    if not conflict_hits:
        L.append("没有发现互斥组合同时出现。")
    for k, v in conflict_hits.items():
        L.append(f"- **{k}**：{len(v)} 条，例：{'；'.join(x.replace('|','/') for x in v[:3])}")

    L += ["", "## 第二轮：每主题随机 20 条", ""]
    for lab in sorted(samples, key=lambda x: -len(by_label[x])):
        L.append(f"**{lab}**（{len(by_label[lab]):,}）")
        L.append("")
        for ctx, hit, _h in sorted(samples[lab], key=lambda x: x[2]):
            L.append(f"- `{hit}` ← {ctx}")
        L.append("")

    L += ["## 第三轮：单短语独占（某词占该轴 >50% 命中）", "",
          "| 轴 | 独占短语 | 占比 |", "| --- | --- | --- |"]
    if not dom:
        L.append("| （无） | | |")
    for label, p, c, tot, r in sorted(dom, key=lambda x: -x[4]):
        L.append(f"| {label} | `{p}` | {c:,}/{tot:,} = {r:.0%} |")

    L += ["", "## 第四轮：零归属构成", "", "| 区域 | 条目 | 零归属 | 占比 | 样例 |", "| --- | --- | --- | --- | --- |"]
    for area, z in zero_by_area.most_common(20):
        t = zero_total[area]
        L.append(f"| {area} | {t:,} | {z:,} | {z / t * 100:.0f}% | "
                 f"{'；'.join(x.replace('|','/') for x in zero_samples[area][:2])} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print("== 第一轮 互斥组合 ==")
    for k, v in conflict_hits.items():
        print(f"   {k}: {len(v)} 条")
    print("== 第三轮 单短语独占 ==")
    for label, p, c, tot, r in sorted(dom, key=lambda x: -x[4])[:12]:
        print(f"   {label:<12} `{p}` {c:,}/{tot:,} = {r:.0%}")
    print(f"== 第四轮 零归属 Top5 ==")
    for area, z in zero_by_area.most_common(5):
        print(f"   {area:<20} {z:,} / {zero_total[area]:,}")
    print(f"落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
