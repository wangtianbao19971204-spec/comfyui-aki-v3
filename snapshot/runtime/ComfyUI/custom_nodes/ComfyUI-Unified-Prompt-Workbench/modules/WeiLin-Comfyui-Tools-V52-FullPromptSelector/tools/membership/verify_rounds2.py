"""第七~十轮核实：新轴精度 / 全库随机完整归属 / 轴间冲突 / 归属数量分布。

用法： python verify_rounds2.py
输出：归属核实_第二轮_20260919.md
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
from fill_new_axes_v35 import PLAN as PLAN35  # noqa: E402

REPORT = HERE / "归属核实_第二轮_20260919.md"
SAMPLE = 40
NEW_AXES = ["动作›行为", "画面›构图", "画面›技法", "画面›打光", "画面›配色",
            "画面›氛围", "生物›动物", "生物›传说", "生物›植物", "画面›图案"]
CONFLICT = [("动作›姿态", "动作›行为"), ("画面›打光", "场景›背景"),
            ("生物›动物", "角色›种族"), ("画面›技法", "画风›画质"),
            ("成人›露出", "状态›半脱")]


def main() -> int:
    wiki = json.loads((BENCH / "danbooru_tag_groups" / "parsed.json").read_text(encoding="utf-8"))
    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))}
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        raw[f"{theme}›{sub}"] = pattern
    raw.update(PLAN14)
    # v35 新轴的规则
    for label, specs in PLAN35.items():
        from fill_new_axes_v35 import pick
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
    rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()

    # A. 新轴抽样
    by_axis = defaultdict(list)
    for u, _s, t in rows:
        d = meta.get(u)
        if d is None:
            continue
        body = denoise(t)
        for lab in NEW_AXES:
            if lab not in (d.get("themes") or []):
                continue
            rx = comp.get(lab)
            ctx, hit = "", ""
            if rx:
                for m in rx.finditer(body):
                    hit = m.group(0)
                    st = max(0, m.start() - 24)
                    ctx = "…" + body[st:m.end() + 18] + "…"
                    break
            by_axis[lab].append((ctx or (t or "")[:60], hit, md5(u.encode()).hexdigest()))
    random.seed(20260919)

    # B. 全库随机（跨轴，展示完整归属）
    all_rows = []
    for u, _s, t in rows:
        d = meta.get(u)
        if d is None:
            continue
        e = subs.get(_s)
        area = gdb.get(e[0], "") if e else ""
        if COMBO.search(area):
            continue
        all_rows.append((u, (t or "")[:72], d.get("themes", []), d.get("facets", []),
                         d.get("series") or ""))
    rand40 = random.sample(all_rows, SAMPLE)

    # C. 冲突组合
    conflicts = defaultdict(int)
    for u, _t, th, fa, _se in all_rows:
        labs = set(th) | set(fa)
        for a, b in CONFLICT:
            if a in labs and b in labs:
                conflicts[f"{a} + {b}"] += 1

    # D. 归属数量分布
    dist = Counter(len(th) + len(fa) for _u, _t, th, fa, _se in all_rows)

    L = ["# 归属核实（第二轮）", ""]
    L += ["## 一、新轴 40 条抽样（带命中上下文）", ""]
    for lab in NEW_AXES:
        L.append(f"**{lab}**（{len(by_axis[lab]):,}）")
        L.append("")
        for ctx, hit, _h in sorted(random.sample(by_axis[lab],
                                                 min(SAMPLE, len(by_axis[lab]))),
                                   key=lambda x: x[2]):
            L.append(f"- `{hit}` ← {ctx}")
        L.append("")
    L += ["## 二、全库随机 40 条的完整归属", "",
          "| 文本 | 主题 | 面 | series |", "| --- | --- | --- | --- |"]
    for _u, t, th, fa, se in rand40:
        L.append(f"| {t.replace('|','/')} | {' + '.join(th)} | {' + '.join(fa)} | {se} |")
    L += ["", "## 三、轴间冲突", "", "| 组合 | 条数 |", "| --- | --- |"]
    for k, v in sorted(conflicts.items(), key=lambda x: -x[1]):
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 四、归属数量分布", "", "| 归属个数 | 条目 |", "| --- | --- |"]
    for k in sorted(dist):
        L.append(f"| {k} | {dist[k]:,} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print("== 三、轴间冲突 ==")
    for k, v in sorted(conflicts.items(), key=lambda x: -x[1]):
        print(f"   {k}: {v:,}")
    print("== 四、归属数量分布 ==")
    for k in sorted(dist):
        print(f"   {k} 个: {dist[k]:,}")
    print(f"落盘：{REPORT.name}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
