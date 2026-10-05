"""第 21 轮：修「下划线复合词」的系统性漏抓。

老规则写的是 `\\b(girl|boy)\\b`，而 Python 的 `\\b` 把下划线当单词字符：
  `little_girl` 里 `girl` 前面是 `_`，**没有词边界 → 匹配失败**。
于是 `aqua_background` / `little_girl` / `cross_eyed` / `american_flag_dress`
这类条目全部落进零归属。

修法：把所有规则的 `\\b(...)\\b` 换成下划线感知的边界
      `(?<![a-z0-9])(?:...)(?![a-z0-9])`（下划线算分隔符）。
只对**零归属**条目生效地补，已有归属不动。

用法： python fix_boundary_v21.py [--write]
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

OUT = HERE / "全库_面与主题_v21_20260919.jsonl"
REPORT = HERE / "下划线边界修复_v21_20260919.md"
SAMPLE = 20
FACETS = {"人物数量›在场人数", "外貌›面部", "外貌›发型", "外貌›身体",
          "成人›露出", "状态›半脱"}


def widen_pattern(pattern: str) -> str:
    """\\bX\\b → (?<![a-z0-9])X(?![a-z0-9])，让下划线也算分隔符。"""
    out = pattern.replace(r"\b", "")
    out = re.sub(r"\(\?<!", "(?<!", out)
    # 前后补上边界断言
    return "(?<![a-z0-9])(?:" + out + r")(?![a-z0-9])"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))}
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        raw[f"{theme}›{sub}"] = pattern
    raw.update(PLAN14)
    # v14/v12 的规则已经是短语拼装（自带 (?<![a-z0-9]) 边界），只处理老式 \b 规则
    widened = {}
    for label, p in raw.items():
        widened[label] = widen_pattern(p) if r"\b" in p else p
    compiled = {k: re.compile(v, re.I) for k, v in widened.items()}

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
        if doc.get("themes") or doc.get("facets"):
            out_lines.append(json.dumps(
                {"id": u, "source": area, "leaf": e[1] if e else "",
                 "themes": doc.get("themes", []), "facets": doc.get("facets", []),
                 "text": (text or "")[:150]}, ensure_ascii=False))
            continue
        body = denoise(text)
        scene = V12.scene_body(body)
        themes, facets = [], []
        for label, rx in compiled.items():
            target = scene if label.startswith("场景›") else body
            m = rx.search(target)
            if m:
                (facets if label in FACETS else themes).append(label)
                added[label] += 1
                if len(samples[label]) < SAMPLE:
                    samples[label].append(
                        ((text or "")[:64], m.group(0), md5(u.encode()).hexdigest()))
        if themes or facets:
            changed += 1
        out_lines.append(json.dumps(
            {"id": u, "source": area, "leaf": e[1] if e else "",
             "themes": themes, "facets": facets, "text": (text or "")[:150]},
            ensure_ascii=False))

    if args.write:
        OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# 下划线边界修复（v21）", "",
         f"- 补上的零归属：{changed:,}", "",
         "| 轴 | 补到 |", "| --- | --- |"]
    for k, v in added.most_common():
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 抽样（补上后命中的片段也列出来）", ""]
    for k, _v in added.most_common(20):
        L.append(f"**{k}**")
        L.append("")
        for t, hit, _h in sorted(samples[k], key=lambda x: x[2])[:SAMPLE]:
            L.append(f"- {t}   ← `{hit}`")
        L.append("")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"补上 {changed:,} 条零归属")
    for k, v in added.most_common(14):
        print(f"   {k:<12} +{v:,}")
    print(f"落盘：{REPORT.name}{'；快照 ' + OUT.name if args.write else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
