"""量化：零归属里有多少是「作品角色」，能用 danbooru 角色清单补上 series + 角色›原作。"""
from __future__ import annotations

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

WIKI = BENCH / "danbooru_tag_groups" / "parsed.json"
REPORT = HERE / "角色清单补零归属_量化_20260919.md"
SAMPLE = 20


def series_of(slug: str) -> str:
    s = slug.replace("list_of_", "")
    for suf in ("_characters", "_servants", "_units_and_subgroups", "_identities"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    s = s.replace("_", " ").strip()
    return re.sub(r"\s+", " ", s)


def main() -> int:
    wiki = json.loads(WIKI.read_text(encoding="utf-8"))
    lookup = defaultdict(set)
    pages = 0
    for slug, info in wiki.items():
        if not slug.startswith("list_of"):
            continue
        if not any(k in slug for k in ("characters", "servants", "pokemon", "digimon",
                                       "youkai", "pals", "monsters", "mascots",
                                       "warframes", "identities", "rocodex")):
            continue
        pages += 1
        series = series_of(slug)
        for sec in info["sections"]:
            for t in sec["tags"]:
                if t.startswith(("tag_group:", "list_of_")):
                    continue
                p = norm_phrase(t)
                if p and len(p) >= 3:
                    lookup[p].add(series)
    print(f"角色清单页 {pages} 个；角色短语 {len(lookup):,}")

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
                meta[u] = {}

    zero = hits = 0
    series_cnt = Counter()
    samples = []
    no_series_before = 0
    for u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        doc = meta.get(u)
        if COMBO.search(area) or doc is None:
            continue
        if doc.get("themes") or doc.get("facets"):
            continue
        zero += 1
        toks = [t for t in TOKEN.split((text or "").lower()) if t]
        n = len(toks)
        found = set()
        for i in range(n):
            for k in range(1, MAXN + 1):
                if i + k > n:
                    break
                g = lookup.get(" ".join(toks[i:i + k]))
                if g:
                    found |= g
        if found:
            hits += 1
            for x in found:
                series_cnt[x] += 1
            if not doc.get("series"):
                no_series_before += 1
            if len(samples) < SAMPLE * 3:
                samples.append(((text or "")[:70], sorted(found)[:2], md5(u.encode()).hexdigest()))

    L = ["# 零归属里的作品角色（可用 danbooru 角色清单补）", "",
         f"- 零归属总数：{zero:,}",
         f"- 能匹配到角色清单的：{hits:,}（{hits / max(zero,1) * 100:.0f}%）",
         f"- 其中原本没有 series 字段的：{no_series_before:,}", "",
         "## 命中最多的作品 Top25", "", "| 作品 | 条目 |", "| --- | --- |"]
    for k, v in series_cnt.most_common(25):
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 抽样（按 id 哈希）", ""]
    for t, ser, _h in sorted(samples, key=lambda x: x[2])[:SAMPLE * 2]:
        L.append(f"- {t}   → `{'、'.join(ser)}`")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"零归属 {zero:,}；能匹配角色清单 {hits:,}（{hits / max(zero,1) * 100:.0f}%）")
    print("Top10 作品：", series_cnt.most_common(10))
    print("抽样：")
    for t, ser, _h in sorted(samples, key=lambda x: x[2])[:12]:
        print(f"   {t[:60]:<62} → {ser}")
    print(f"落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
