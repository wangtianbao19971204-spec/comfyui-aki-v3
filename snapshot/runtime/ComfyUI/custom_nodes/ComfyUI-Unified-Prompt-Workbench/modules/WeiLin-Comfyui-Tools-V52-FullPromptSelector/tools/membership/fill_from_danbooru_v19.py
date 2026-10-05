"""第 19 轮：用 danbooru 分组补零归属（终版：全部过 v12 的过滤器）。

v17 分词查表 → 漏进 `steins;gate` 的 gate、`school` 等
v18 正则化 → 仍漏 `Studio Ghibli`（studio）、`saliva_pool`（pool）、`water_bottle`（water）
v19 → 场景**直接复用 v12 已抽检干净的室内/室外清单**；其余轴统一过
       v12 的 prep()（弱词表 + 单字母过滤 + 歧义词剔除 + 物件后缀断言）。

只补**零归属**条目。用法： python fill_from_danbooru_v19.py [--write]
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
import rebuild_action_scene_v11 as V11  # noqa: E402
from rebuild_action_scene_v11 import phrase_pattern, section_tags  # noqa: E402
import rebuild_action_scene_v12 as V12  # noqa: E402

V11.MIN_SINGLE_TOKEN = 3
V11.OBJECT_SUFFIX = V11.OBJECT_SUFFIX + ("sweatdrops", "sweatdrop", "tears",
                                         "teardrops", "sweat spray", "speed lines")

WIKI = BENCH / "danbooru_tag_groups" / "parsed.json"
OUT = HERE / "全库_面与主题_v19_20260919.jsonl"
REPORT = HERE / "danbooru补零归属_v19_20260919.md"
SAMPLE = 16
FACET_LABELS = {"人物数量›在场人数", "外貌›面部", "外貌›发型", "外貌›身体",
                "成人›露出", "状态›半脱"}

AXIS_GROUPS = {
    "服饰›配饰": ["headwear", "handwear", "eyewear", "accessories", "neck_and_neckwear"],
    "服饰›上装": ["sleeves"],
    "服饰›鞋袜": ["legwear"],
    "外貌›面部": ["face_tags", "eyes_tags", "makeup"],
    "外貌›发型": ["hair", "hair_color", "hair_styles"],
    "外貌›身体": ["body_parts", "breasts_tags", "ass", "shoulders", "skin_color",
                 "ears_tags", "pussy", "wings", "feet"],
    "角色›职业": ["jobs"],
}
# 这几个轴直接用 v12 已经抽检干净的规则，不再拼装
DIRECT = {
    "动作›姿态": ("动作", "姿态"),
    "动作›手部": ("动作", "手部"),
    "动作›腿部": ("动作", "腿部"),
    "场景›室内": ("场景", "室内"),
    "场景›室外": ("场景", "室外"),
}
COUNT_WORDS = ["1girl", "2girls", "3girls", "multiple girls", "1boy", "2boys",
               "multiple boys", "boy and girl", "pair", "duo", "group"]


def group_phrases(wiki, name):
    return [t for sec in wiki[f"tag_group:{name}"]["sections"] for t in sec["tags"]
            if not t.startswith(("tag_group:", "list_of_"))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    wiki = json.loads(WIKI.read_text(encoding="utf-8"))

    plans = {}
    for axis, groups in AXIS_GROUPS.items():
        raw = sorted({t for g in groups for t in group_phrases(wiki, g)})
        plans[axis] = phrase_pattern(V12.prep(raw))       # v12 的过滤器
    plans["人物数量›在场人数"] = phrase_pattern(COUNT_WORDS)
    v12_rules = {f"{t}›{s}": p for t, s, p, _n in V12.build_rules(load_wiki())}
    for label, (t, s) in DIRECT.items():
        plans[label] = v12_rules[f"{t}›{s}"]

    compiled = {k: re.compile(v or r"(?!x)x", re.I) for k, v in plans.items()}

    with sqlite3.connect(str(DB)) as con:
        gdb = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
        meta = {}
        for u, blob in con.execute("select tag_uuid, data from workbench_tag_meta"):
            try:
                meta[u] = json.loads(blob)
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
            if rx.search(target):
                (facets if label in FACET_LABELS else themes).append(label)
                added[label] += 1
                if len(samples[label]) < SAMPLE:
                    samples[label].append(((text or "")[:70], md5(u.encode()).hexdigest()))
        if themes or facets:
            changed += 1
        out_lines.append(json.dumps(
            {"id": u, "source": area, "leaf": e[1] if e else "",
             "themes": themes, "facets": facets, "text": (text or "")[:150]},
            ensure_ascii=False))

    if args.write:
        OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# danbooru 补零归属（v19 终版）", "", f"- 补上的零归属：{changed:,}", "",
         "| 轴 | 补到条目 |", "| --- | --- |"]
    for label in compiled:
        L.append(f"| {label} | {added[label]:,} |")
    L += ["", "## 抽样", ""]
    for label in compiled:
        L.append(f"**{label}**")
        L.append("")
        for t, _h in sorted(samples[label], key=lambda x: x[1])[:SAMPLE]:
            L.append(f"- {t}")
        L.append("")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"补上 {changed:,} 条零归属")
    for label in compiled:
        print(f"   {label:<12} +{added[label]:,}")
    print(f"落盘：{REPORT.name}{'；快照 ' + OUT.name if args.write else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
