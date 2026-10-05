"""量：剩余零归属里，有多少能被当初跳过的那些 danbooru 分组接住。"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
from rebuild_action_scene_v8 import DB, COMBO  # noqa: E402
from explore_adopt_danbooru import TOKEN, MAXN, norm_phrase  # noqa: E402

GROUPS = ["verbs_and_gerunds", "sex_acts", "sexual_positions", "simulated_sex_acts",
          "bdsm_and_torture", "sex_objects", "nudity", "sexual_attire", "holding_tags",
          "image_composition", "lighting", "technology", "food_tags", "cards", "water",
          "fire", "flowers", "sports", "dances", "audio_tags", "patterns", "symbols",
          "text", "colors", "subjective", "theme", "phrases", "groups",
          "family_relationships", "holidays_and_celebrations", "history", "companies_and_brand_names",
          "real_world_locations", "animals", "birds", "cats", "dogs", "legendary_creatures"]


def main() -> int:
    wiki = json.loads((BENCH / "danbooru_tag_groups" / "parsed.json").read_text(encoding="utf-8"))
    lookup = defaultdict(set)
    for g in GROUPS:
        slug = f"tag_group:{g}"
        if slug not in wiki:
            continue
        for sec in wiki[slug]["sections"]:
            for t in sec["tags"]:
                if t.startswith(("tag_group:", "list_of_")):
                    continue
                p = norm_phrase(t)
                if p:
                    lookup[p].add(g)
    print(f"参与的分组 {len(GROUPS)}；短语 {len(lookup):,}")

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

    zero = 0
    hit = 0
    by_group = Counter()
    samples = defaultdict(list)
    for u, s, t in con.execute("select t_uuid, subgroup_id, text from tag_tags"):
        d = meta.get(u)
        if d is None or d.get("themes") or d.get("facets"):
            continue
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        if COMBO.search(area):
            continue
        zero += 1
        toks = [x for x in TOKEN.split((t or "").lower()) if x]
        found = set()
        n = len(toks)
        for i in range(n):
            for k in range(1, MAXN + 1):
                if i + k > n:
                    break
                g = lookup.get(" ".join(toks[i:i + k]))
                if g:
                    found |= g
        if found:
            hit += 1
            for g in found:
                by_group[g] += 1
                if len(samples[g]) < 6:
                    samples[g].append((t or "")[:50])

    print(f"剩余零归属 {zero:,}；能被这些分组接住的 {hit:,}（{hit / max(zero,1) * 100:.0f}%）")
    print("各分组可接住：")
    for g, c in by_group.most_common(20):
        print(f"   {g:<28} {c:>5}   例：{samples[g][0][:34]}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
