"""第 17 轮：用 danbooru 分组清单补**零归属**条目（只增不减）。

背景：零归属 18,196 条（19.5%），逐条看下来大多是"具体 danbooru tag，但我们手写词表里没有"
（penny_loafers / deerstalker / kote / battoujutsu_stance …）。danbooru 的分组清单正好覆盖这类。

做法：读**库里的 meta**（权威），对**当前 themes/facets 全空**的条目，
按人工指定的 分组→我们的轴 映射补归属。已有归属的条目一律不碰
（先验证补出来的质量，再考虑要不要扩到全库）。

用法：
  python fill_from_danbooru_v17.py            # 只统计 + 出抽样，不写文件
  python fill_from_danbooru_v17.py --write    # 生成写库快照
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

from rebuild_action_scene_v8 import DB, COMBO  # noqa: E402
from explore_adopt_danbooru import TOKEN, MAXN, norm_phrase  # noqa: E402
from measure_gap_fill import GROUP_TO_AXIS  # noqa: E402

WIKI = BENCH / "danbooru_tag_groups" / "parsed.json"
OUT = HERE / "全库_面与主题_v17_20260919.jsonl"
REPORT = HERE / "danbooru补零归属_v17_20260919.md"

SAMPLE = 16
# 这些分组太泛或语义不对口，本轮先不接（避免给轴灌噪声）
SKIP_GROUPS = {
    "image_composition",     # 构图/镜头，不等于"背景"
    "lighting",              # 打光
    "verbs_and_gerunds",     # 动作太泛（bathing/begging），会把"姿态"冲淡
    "holding_tags",          # holding_x 是"拿着某物"，语义跨动作与道具
    "technology",            # 题材过宽
    "cards", "water", "fire", "flowers", "food_tags",
    # 抽样发现这几个分组是"相关词都要"，会把职业/体型词灌进来
    "attire",                # nun / priest / waitress / fingernails
    "sex_acts",              # loli / shota / pregnant / amputee
    "sexual_positions",
    "simulated_sex_acts",
    "sexual_attire",
    "nudity",                # sleeveless_shirt / off-shoulder_shirt
    "bdsm_and_torture",      # latex / bruise_on_face
    "sex_objects",           # sailor_collar
}
FACET_LABELS = {"人物数量›在场人数", "外貌›面部", "外貌›发型", "外貌›身体",
                "成人›露出", "状态›半脱"}

# 下划线不拆：kita_high_school_uniform 不能被"school"命中
TAG_TOKEN = re.compile(r"[^a-z0-9_']+")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    wiki = json.loads(WIKI.read_text(encoding="utf-8"))
    lookup = defaultdict(set)
    for slug, info in wiki.items():
        if not slug.startswith("tag_group:"):
            continue
        name = slug.split(":", 1)[1]
        if name not in GROUP_TO_AXIS or name in SKIP_GROUPS:
            continue
        for sec in info["sections"]:
            for t in sec["tags"]:
                if t.startswith(("tag_group:", "list_of_")):
                    continue
                p = norm_phrase(t)
                if p:
                    lookup[p].add(name)
                    lookup[p.replace(" ", "_")].add(name)   # 兼容 blue_eyes 这种写法
    print(f"启用 {len({g for g in GROUP_TO_AXIS if g not in SKIP_GROUPS})} 个分组，"
          f"短语 {len(lookup):,} 个")

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

    added = Counter()
    changed = 0
    was_zero = now_filled = 0
    samples = defaultdict(list)
    by_group = Counter()
    out_lines = []

    for u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        if COMBO.search(area):
            continue
        doc = meta.get(u)
        if doc is None:
            continue
        # 只处理零归属条目；已有归属的不动
        if doc.get("themes") or doc.get("facets"):
            row = {"id": u, "source": area, "leaf": e[1] if e else "",
                   "themes": doc.get("themes", []), "facets": doc.get("facets", []),
                   "text": (text or "")[:150]}
            out_lines.append(json.dumps(row, ensure_ascii=False))
            continue
        toks = [t for t in TAG_TOKEN.split((text or "").lower()) if t]
        n = len(toks)
        groups = set()
        for i in range(n):
            for k in range(1, MAXN + 1):
                if i + k > n:
                    break
                g = lookup.get(" ".join(toks[i:i + k]))
                if g:
                    groups |= g
        labels = {"›".join(GROUP_TO_AXIS[g]) for g in groups}
        for g in groups:
            by_group[g] += 1
        themes = list(doc.get("themes", []))
        facets = list(doc.get("facets", []))
        empty_before = not themes and not facets
        new_themes = [x for x in labels if x not in FACET_LABELS]
        new_facets = [x for x in labels if x in FACET_LABELS]
        for x in new_themes:
            if x not in themes:
                themes.append(x)
                added[x] += 1
                if len(samples[x]) < SAMPLE:
                    src = "、".join(sorted(g for g in groups if "›".join(GROUP_TO_AXIS[g]) == x))
                    samples[x].append(((text or "")[:70], md5(u.encode()).hexdigest(), src))
        for x in new_facets:
            if x not in facets:
                facets.append(x)
                added[x] += 1
                if len(samples[x]) < SAMPLE:
                    src = "、".join(sorted(g for g in groups if "›".join(GROUP_TO_AXIS[g]) == x))
                    samples[x].append(((text or "")[:70], md5(u.encode()).hexdigest(), src))
        if themes != doc.get("themes", []) or facets != doc.get("facets", []):
            changed += 1
        if empty_before and (themes or facets):
            now_filled += 1
        row = {"id": u, "source": area, "leaf": e[1] if e else "",
               "themes": themes, "facets": facets, "text": (text or "")[:150]}
        out_lines.append(json.dumps(row, ensure_ascii=False))

    if args.write:
        OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# 用 danbooru 分组补零归属（v17）", "",
         f"- 变更行：{changed:,}",
         f"- 原本零归属、现在有归属：{now_filled:,}",
         f"- 跳过未接的分组：{'、'.join(sorted(SKIP_GROUPS))}", "",
         "## 新增归属 Top", "", "| 轴 | 新增条目 |", "| --- | --- |"]
    for k, v in added.most_common(30):
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 抽样（每轴最多 16 条，按 id 哈希均匀取）", ""]
    for k, _v in added.most_common(30):
        L.append(f"**{k}**")
        L.append("")
        for t, _h, src in sorted(samples[k], key=lambda x: x[1])[:SAMPLE]:
            L.append(f"- {t}   ← `{src}`")
        L.append("")
    L += ["", "## 触发的 danbooru 分组（按补到的人数）", "", "| 分组 | 补到条目 |", "| --- | --- |"]
    for g, n in by_group.most_common():
        L.append(f"| `{g}` | {n:,} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"变更 {changed:,} 行；原零归属现在有归属 {now_filled:,}")
    for k, v in added.most_common(15):
        print(f"   {k:<12} +{v:,}")
    print(f"落盘：{REPORT.name}{'；快照 ' + OUT.name if args.write else '（未写快照）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
