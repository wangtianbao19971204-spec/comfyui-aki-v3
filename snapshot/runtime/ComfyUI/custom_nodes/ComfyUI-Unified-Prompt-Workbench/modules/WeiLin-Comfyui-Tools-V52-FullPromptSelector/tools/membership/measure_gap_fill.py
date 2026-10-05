"""量化：零归属的 15,597 条里，有多少能被 danbooru 分组清单补上？补到哪些分组？"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
BENCH_DIR = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
sys.path.insert(0, str(BENCH_DIR))
from rebuild_action_scene_v8 import DB, COMBO, load_wiki  # noqa: E402
from explore_adopt_danbooru import TOKEN, MAXN, norm_phrase  # noqa: E402
from scan_rule_phrases import split_alternation, to_phrase  # noqa: E402
import rebuild_action_scene_v12 as V12  # noqa: E402
from fix_review_v14 import PLAN as PLAN14  # noqa: E402

WIKI = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import"
            r"\danbooru_tag_groups\parsed.json")
REPORT = HERE / "零归属缺口量化_20260919.md"

# danbooru 分组 → 我们的轴（用于补缺口）
GROUP_TO_AXIS = {
    "legwear": ("服饰", "鞋袜"), "feet": ("外貌", "身体"),
    "headwear": ("服饰", "配饰"), "handwear": ("服饰", "配饰"),
    "accessories": ("服饰", "配饰"), "eyewear": ("服饰", "配饰"),
    "neck_and_neckwear": ("服饰", "配饰"),
    "attire": ("服饰", "通用"), "sleeves": ("服饰", "上装"),
    "covering": ("服饰", "通用"), "nudity": ("成人", "露出"),
    "posture": ("动作", "姿态"), "hands": ("动作", "手部"),
    "gestures": ("动作", "手部"), "holding_tags": ("道具", "器物"),
    "verbs_and_gerunds": ("动作", "姿态"),
    "locations": ("场景", "室内"), "real_world_locations": ("场景", "室外"),
    "backgrounds": ("场景", "背景"), "image_composition": ("场景", "背景"),
    "lighting": ("场景", "背景"),
    "face_tags": ("外貌", "面部"), "eyes_tags": ("外貌", "面部"),
    "makeup": ("外貌", "面部"), "hair": ("外貌", "发型"),
    "hair_color": ("外貌", "发型"), "hair_styles": ("外貌", "发型"),
    "body_parts": ("外貌", "身体"), "breasts_tags": ("外貌", "身体"),
    "ass": ("外貌", "身体"), "shoulders": ("外貌", "身体"),
    "skin_color": ("外貌", "身体"), "ears_tags": ("外貌", "身体"),
    "pussy": ("外貌", "身体"), "wings": ("外貌", "身体"),
    "sex_acts": ("成人", "性交"), "sexual_positions": ("成人", "性交"),
    "simulated_sex_acts": ("成人", "前戏"), "bdsm_and_torture": ("成人", "特殊"),
    "sex_objects": ("成人", "特殊"), "sexual_attire": ("服饰", "通用"),
    "jobs": ("角色", "职业"), "character_count": ("人物数量", "在场人数"),
    "food_tags": ("道具", "器物"), "technology": ("道具", "器物"),
    "cards": ("道具", "器物"), "doors_and_gates": ("道具", "器物"),
    "water": ("道具", "器物"), "fire": ("道具", "器物"),
    "flowers": ("道具", "器物"),
}


def main() -> int:
    wiki = json.loads(WIKI.read_text(encoding="utf-8"))
    lookup = defaultdict(set)
    for slug, info in wiki.items():
        if not slug.startswith("tag_group:"):
            continue
        name = slug.split(":", 1)[1]
        for sec in info["sections"]:
            for t in sec["tags"]:
                if t.startswith(("tag_group:", "list_of_")):
                    continue
                p = norm_phrase(t)
                if p and name in GROUP_TO_AXIS:      # 只看我们给它指定了轴的组
                    lookup[p].add(name)

    # 现有规则短语（用来判定"零归属"）
    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))}
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        raw[f"{theme}›{sub}"] = pattern
    raw.update(PLAN14)
    cur = defaultdict(set)
    for label, pattern in raw.items():
        for part in split_alternation(pattern):
            p = to_phrase(part)
            if p:
                cur[p].add(label)

    with sqlite3.connect(str(DB)) as con:
        gdb = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
        # 零归属以库里的 meta 为准（正则重建会漏）
        meta_zero = {}
        for u, blob in con.execute("select tag_uuid, data from workbench_tag_meta"):
            try:
                d = json.loads(blob)
            except Exception:
                continue
            meta_zero[u] = not (d.get("themes") or d.get("facets"))

    total = zero = filled = 0
    fill_by_axis = Counter()
    still = Counter()
    still_samples = defaultdict(list)
    fill_samples = defaultdict(list)

    for u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        if COMBO.search(area):
            continue
        total += 1
        if not meta_zero.get(u, False):
            continue
        zero += 1
        toks = [t for t in TOKEN.split((text or "").lower()) if t]
        n = len(toks)
        dgroups = set()
        for i in range(n):
            for k in range(1, MAXN + 1):
                if i + k > n:
                    break
                gram = " ".join(toks[i:i + k])
                g = lookup.get(gram)
                if g:
                    dgroups |= g
        if dgroups:
            filled += 1
            for g in dgroups:
                axis = "›".join(GROUP_TO_AXIS[g])
                fill_by_axis[axis] += 1
                if len(fill_samples[axis]) < 3:
                    fill_samples[axis].append((text or "")[:70])
        else:
            still[area] += 1
            if len(still_samples[area]) < 3:
                still_samples[area].append((text or "")[:70])

    L = ["# 零归属缺口量化：接 danbooru 分组能补多少", "",
         f"- 参与 {total:,}；零归属 {zero:,}（{zero / total * 100:.1f}%）",
         f"- 其中**能被 danbooru 分组补上**：{filled:,}（{filled / max(zero,1) * 100:.0f}%）",
         f"- 仍然补不上：{zero - filled:,}", "",
         "## 一、能补到哪些轴", "", "| 目标轴 | 可补条目 | 样例 |", "| --- | --- | --- |"]
    for axis, n in fill_by_axis.most_common():
        L.append(f"| {axis} | {n:,} | {'；'.join(x.replace('|','/') for x in fill_samples[axis])} |")
    L += ["", "## 二、仍补不上的（按区域）", "", "| 区域 | 条数 | 样例 |", "| --- | --- | --- |"]
    for area, n in still.most_common(20):
        L.append(f"| {area} | {n:,} | {'；'.join(x.replace('|','/') for x in still_samples[area])} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"参与 {total:,}；零归属 {zero:,}；能被 danbooru 补上 {filled:,}（{filled/max(zero,1)*100:.0f}%）")
    for axis, n in fill_by_axis.most_common(15):
        print(f"   {axis:<12} +{n:,}")
    print(f"   仍补不上 {zero - filled:,}")
    print(f"落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
