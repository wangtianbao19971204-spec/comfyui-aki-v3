"""第 18 轮：用 danbooru 分组清单补零归属（v17 的修正版，改为正则+边界过滤）。

v17 用分词查表，漏进来一堆：`steins;gate` 里的 `gate`、`kita_high_school_uniform` 里的
`school`、`o-ring_bikini` 里的 `ring`、单字母 `v`。本轮改成复用 v11 的 phrase_pattern：
  * 边界安全（下划线/空格都认）
  * 弱词与单字母过滤（MIN_SINGLE_TOKEN=3）
  * 短语后面跟衣物/效果线名词时判否
并修正 locations 的映射：按 wiki 章节拆「室内 / 室外」，不再整页塞进室内。

只补**零归属**条目，已有归属的不动。

用法： python fill_from_danbooru_v18.py [--write]
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

from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402
import rebuild_action_scene_v11 as V11  # noqa: E402
from rebuild_action_scene_v11 import phrase_pattern  # noqa: E402
from rebuild_action_scene_v11 import section_tags  # noqa: E402
from rebuild_action_scene_v8 import load_wiki  # noqa: E402

V11.MIN_SINGLE_TOKEN = 3          # 只杀 1-2 字母，保住 hug / obi / tan 这类

WIKI = BENCH / "danbooru_tag_groups" / "parsed.json"
OUT = HERE / "全库_面与主题_v18_20260919.jsonl"
REPORT = HERE / "danbooru补零归属_v18_20260919.md"
SAMPLE = 16

FACET_LABELS = {"人物数量›在场人数", "外貌›面部", "外貌›发型", "外貌›身体",
                "成人›露出", "状态›半脱"}

# 轴 ← danbooru 分组（人工指定，只留语义词表干净的分组）
AXIS_GROUPS = {
    "服饰›配饰": ["accessories", "handwear", "headwear", "eyewear", "neck_and_neckwear"],
    "服饰›上装": ["sleeves"],
    "服饰›鞋袜": ["legwear"],
    "外貌›面部": ["face_tags", "eyes_tags", "makeup"],
    "外貌›发型": ["hair", "hair_color", "hair_styles"],
    "外貌›身体": ["body_parts", "breasts_tags", "ass", "shoulders", "skin_color",
                 "ears_tags", "pussy", "wings", "feet"],
    "人物数量›在场人数": ["character_count"],
    "动作›姿态": ["posture"],
    "动作›手部": ["hands", "gestures"],
    "角色›职业": ["jobs"],
    "道具›器物": ["doors_and_gates"],
}
# 场景单独处理：按 locations 的章节拆
SCENE_INDOOR = ("locations", "Indoors")
SCENE_OUTDOOR = ("locations", "Natural settings")


def group_phrases(wiki, name):
    out = []
    for sec in wiki[f"tag_group:{name}"]["sections"]:
        for t in sec["tags"]:
            if not t.startswith(("tag_group:", "list_of_")):
                out.append(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    wiki = json.loads(WIKI.read_text(encoding="utf-8"))

    plans = {}
    for axis, groups in AXIS_GROUPS.items():
        phrases = sorted({t for g in groups for t in group_phrases(wiki, g)})
        plans[axis] = phrase_pattern(phrases)
    plans["场景›室内"] = phrase_pattern(section_tags(wiki, "tag_group:locations", SCENE_INDOOR[1]))
    plans["场景›室外"] = phrase_pattern(
        section_tags(wiki, "tag_group:locations", SCENE_OUTDOOR[1]) + ["outdoors"])

    compiled = {k: re.compile(v, re.I) for k, v in plans.items()}
    for k, rx in compiled.items():
        if not rx.pattern or rx.pattern == r"(?!x)x":
            print("空规则：", k)

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
        themes, facets = [], []
        for label, rx in compiled.items():
            if rx.search(body):
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

    L = ["# danbooru 补零归属（v18，正则+边界过滤版）", "",
         f"- 补上的零归属条目：{changed:,}",
         f"- 使用的轴：{len(compiled)} 个", "",
         "| 轴 | 短语数 | 补到条目 |", "| --- | --- | --- |"]
    for label, _rx in compiled.items():
        L.append(f"| {label} | {len(plans[label].split('|'))} | {added[label]:,} |")
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
