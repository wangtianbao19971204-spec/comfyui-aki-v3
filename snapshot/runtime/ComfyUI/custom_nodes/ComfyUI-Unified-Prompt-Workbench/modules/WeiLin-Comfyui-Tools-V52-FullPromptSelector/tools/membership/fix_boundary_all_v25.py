"""第 25 轮：把「下划线边界修复」应用到全库（不只零归属）。

v21 只补了当时零归属的条目，于是像 `cat_girl`（已挂了「人物数量」面）这种
永远捞不到 `\\bcatgirl\\b` 那类规则。本轮对**所有条目**重跑加宽边界后的规则，
只做新增、不删不改。

用法： python fix_boundary_all_v25.py [--write]
"""
from __future__ import annotations

import argparse
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

OUT = HERE / "全库_面与主题_v25_20260919.jsonl"
REPORT = HERE / "下划线边界全库修复_v25_20260919.md"
SAMPLE = 20
FACETS = {"人物数量›在场人数", "外貌›面部", "外貌›发型", "外貌›身体",
          "成人›露出", "状态›半脱"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))}
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        raw[f"{theme}›{sub}"] = pattern
    raw.update(PLAN14)
    compiled = {k: re.compile(widen_pattern(v) if r"\b" in v else v, re.I)
                for k, v in raw.items()}

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
                meta[u] = {"themes": [], "facets": []}

    changed = 0
    added = Counter()
    samples = defaultdict(list)
    out_lines = []
    for u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        doc = meta.get(u)
        if COMBO.search(area) or doc is None:
            continue
        body = denoise(text)
        scene = V12.scene_body(body)
        themes = list(doc.get("themes", []))
        facets = list(doc.get("facets", []))
        touched = False
        for label, rx in compiled.items():
            if label in themes or label in facets:
                continue
            target = scene if label.startswith("场景›") else body
            m = rx.search(target)
            if not m:
                continue
            (facets if label in FACETS else themes).append(label)
            added[label] += 1
            touched = True
            if len(samples[label]) < SAMPLE:
                start = max(0, m.start() - 34)
                ctx = body[start:m.end() + 26].replace("\n", " ")
                samples[label].append((("…" + ctx + "…"), m.group(0),
                                       md5(u.encode()).hexdigest()))
        if touched:
            changed += 1
        out_lines.append(json.dumps(
            {"id": u, "source": area, "leaf": e[1] if e else "",
             "themes": themes, "facets": facets, "series": doc.get("series"),
             "text": (text or "")[:150]}, ensure_ascii=False))

    if args.write:
        OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# 下划线边界修复（全库版，v25）", "", f"- 受影响条目：{changed:,}", "",
         "| 新增的轴 | 条数 |", "| --- | --- |"]
    for k, v in added.most_common():
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 抽样（每轴最多 20 条，含命中片段）", ""]
    for k, _v in added.most_common(24):
        L.append(f"**{k}**")
        L.append("")
        for t, hit, _h in sorted(samples[k], key=lambda x: x[2])[:SAMPLE]:
            L.append(f"- {t}   ← `{hit}`")
        L.append("")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"受影响条目 {changed:,}")
    for k, v in added.most_common(20):
        print(f"   {k:<12} +{v:,}")
    print(f"落盘：{REPORT.name}{'；快照 ' + OUT.name if args.write else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
