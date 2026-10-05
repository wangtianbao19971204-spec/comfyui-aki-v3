"""第 34 轮：接上之前跳过的 locations 剩余章节 + attire 分类，补零归属。

零归属拆解显示：剩下 5,590 条短词里大头是**场景词**（cityscape/street/road/playground/
stadium/airport/restaurant/cafe/park…）和**服饰词**（furisode/dirndl/hanbok/tunic/tutu/
buruma/blazer/overalls/pajamas…）—— 正是 v19 时我跳过的 locations 剩余章节与 attire。

映射：
  场景›室内 ← locations 的 Buildings / Places of worship
  场景›室外 ← locations 的 Man-made / Other、以及 real_world_locations 全部
  服饰 5 类 ← attire 的对应章节
短语一律过 v12 的 prep()（弱词/单字母/歧义/物件后缀过滤），只补零归属条目。

用法： python fill_scene_attire_v34.py [--write]
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
from rebuild_action_scene_v11 import phrase_pattern  # noqa: E402
import rebuild_action_scene_v12 as V12  # noqa: E402

V11.MIN_SINGLE_TOKEN = 3
OUT = HERE / "全库_面与主题_v34_20260919.jsonl"
REPORT = HERE / "补场景服饰_v34_20260919.md"
SAMPLE = 16
FACETS = {"人物数量›在场人数", "外貌›面部", "外貌›发型", "外貌›身体",
          "成人›露出", "状态›半脱"}

SCENE = {
    "场景›室内": [("locations", ("building", "places of worship"))],
    "场景›室外": [("locations", ("man-made", "other")),
                ("real_world_locations", None)],
}
ATTIRE = {
    "服饰›配饰": ("headwear", "head and face", "neck and shoulders", "limbs", "torso"),
    "服饰›上装": ("shirts and topwear",),
    "服饰›下装": ("pants and bottomwear",),
    "服饰›鞋袜": ("legs and feet", "shoes and footwear"),
    "服饰›通用": ("uniforms and costumes", "swimsuits and bodysuits", "traditional clothing"),
}


def pick(wiki, slug, wants):
    out = []
    for sec in wiki[slug]["sections"]:
        name = sec["section"].lower()
        if wants and not any(w in name for w in wants):
            continue
        if wants is None and "see also" in name:
            continue
        for t in sec["tags"]:
            if not t.startswith(("tag_group:", "list_of_")):
                out.append(t)
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    wiki = json.loads(Path(BENCH / "danbooru_tag_groups" / "parsed.json").read_text(encoding="utf-8"))

    plans = {}
    for label, specs in SCENE.items():
        ph = []
        for slug, wants in specs:
            ph += pick(wiki, f"tag_group:{slug}", wants)
        plans[label] = phrase_pattern(V12.prep(sorted(set(ph))))
    for label, wants in ATTIRE.items():
        plans[label] = phrase_pattern(V12.prep(pick(wiki, "tag_group:attire", wants)))
    compiled = {k: re.compile(v, re.I) for k, v in plans.items()}

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
                 "series": doc.get("series"), "text": (text or "")[:150]},
                ensure_ascii=False))
            continue
        body = denoise(text)
        scene = V12.scene_body(body)
        themes, facets = [], []
        for label, rx in compiled.items():
            target = scene if label.startswith("场景›") else body
            m = rx.search(target)
            if not m:
                continue
            (facets if label in FACETS else themes).append(label)
            added[label] += 1
            if len(samples[label]) < SAMPLE:
                st = max(0, m.start() - 24)
                samples[label].append(("…" + target[st:m.end() + 18] + "…", m.group(0),
                                       md5(u.encode()).hexdigest()))
        if themes or facets:
            changed += 1
        out_lines.append(json.dumps(
            {"id": u, "source": area, "leaf": e[1] if e else "",
             "themes": themes, "facets": facets, "text": (text or "")[:150]},
            ensure_ascii=False))

    if args.write:
        OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# 补场景 / 服饰（v34）", "", f"- 补上的零归属：{changed:,}", "",
         "| 轴 | 补到 |", "| --- | --- |"]
    for k in compiled:
        L.append(f"| {k} | {added[k]:,} |")
    L += ["", "## 抽样", ""]
    for k in compiled:
        L.append(f"**{k}**")
        L.append("")
        for ctx, hit, _h in sorted(samples[k], key=lambda x: x[2])[:SAMPLE]:
            L.append(f"- `{hit}` ← {ctx}")
        L.append("")
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"补上 {changed:,} 条零归属")
    for k in compiled:
        print(f"   {k:<12} +{added[k]:,}")
    print(f"落盘：{REPORT.name}{'；快照 ' + OUT.name if args.write else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
