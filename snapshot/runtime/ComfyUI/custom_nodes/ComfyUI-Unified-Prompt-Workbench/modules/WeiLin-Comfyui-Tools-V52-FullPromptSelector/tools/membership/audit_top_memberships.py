"""第十一轮：抽检「归属数量最多」的条目，看有没有系统性过标。

对每条，把每个归属的**命中片段**打出来，看这些归属是不是各有依据。
用法： python audit_top_memberships.py [--min 12] [--sample 12]
输出：过标抽检_20260919.md
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from collections import Counter
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
from fill_new_axes_v35 import PLAN as PLAN35, pick  # noqa: E402

REPORT = HERE / "过标抽检_20260919.md"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=12)
    ap.add_argument("--sample", type=int, default=12)
    args = ap.parse_args()

    wiki = json.loads((BENCH / "danbooru_tag_groups" / "parsed.json").read_text(encoding="utf-8"))
    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))}
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        raw[f"{theme}›{sub}"] = pattern
    raw.update(PLAN14)
    for label, specs in PLAN35.items():
        ph = []
        for slug, inc, exc in specs:
            key = f"tag_group:{slug}"
            if key in wiki:
                ph += pick(wiki, key, inc, exc)
        raw.setdefault(label, V12.phrase_pattern(V12.prep(sorted(set(ph)))))
    comp = {k: re.compile(widen_pattern(v) if r"\b" in v else v, re.I)
            for k, v in raw.items()}

    con = sqlite3.connect(str(DB))
    gdb = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
    subs = {r[0]: (r[1], r[2]) for r in con.execute(
        "select id_index, group_id, name from tag_subgroups")}
    meta = {}
    for u, b in con.execute("select tag_uuid, data from workbench_tag_meta"):
        try:
            meta[u] = json.loads(b)
        except Exception:
            meta[u] = {}

    heavy = []
    for u, s, t in con.execute("select t_uuid, subgroup_id, text from tag_tags"):
        d = meta.get(u)
        if d is None:
            continue
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        if COMBO.search(area):
            continue
        labels = list(d.get("themes", [])) + list(d.get("facets", []))
        if len(labels) >= args.min:
            heavy.append((u, (t or ""), labels))
    print(f"归属 ≥{args.min} 个的条目：{len(heavy):,}")
    dist = Counter(len(l) for _u, _t, l in heavy)
    for k in sorted(dist):
        print(f"   {k} 个: {dist[k]:,}")

    random.seed(20260919)
    pick_rows = random.sample(heavy, min(args.sample, len(heavy)))
    L = [f"# 归属数量最多条目抽检（≥{args.min} 个）", "",
         f"- 这批共 {len(heavy):,} 条", ""]
    for u, text, labels in pick_rows:
        body = denoise(text)
        scene = V12.scene_body(body)
        L += [f"## {len(labels)} 个归属 · {md5(u.encode()).hexdigest()[:8]}", "",
              f"```\n{text[:260]}\n```", "",
              "| 归属 | 命中片段 |", "| --- | --- |"]
        for lab in labels:
            rx = comp.get(lab)
            hit = "（清单/无正则）"
            if rx:
                target = scene if lab.startswith("场景›") else body
                m = rx.search(target)
                if m:
                    st = max(0, m.start() - 18)
                    hit = "…" + target[st:m.end() + 14] + "…"
            L.append(f"| {lab} | {hit} |")
        L.append("")
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"落盘：{REPORT.name}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
