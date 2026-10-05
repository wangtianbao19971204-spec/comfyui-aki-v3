"""第 20 轮：给零归属里的「作品角色」补 角色›原作（+ 缺失的 series）。

匹配 danbooru 的 194 个角色清单页（44,387 个角色短语 → 作品名）。
精度靠两道闸：
  闸1（强）：tag 已经有 series 时，只接受「匹配到的作品 == 已有 series」的结果，用现成元数据自校验；
  闸2（中）：没有 series 时，要求 tag 很短（≤3 个词）且匹配到的角色名 ≥2 个词。
量化结果：14,387 条零归属里 3,356 条能匹配上角色清单。

用法： python fill_character_series_v20.py [--write]
"""
from __future__ import annotations

import argparse
import json
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
from rebuild_action_scene_v8 import DB, COMBO  # noqa: E402
from explore_adopt_danbooru import TOKEN, MAXN, norm_phrase  # noqa: E402

WIKI = BENCH / "danbooru_tag_groups" / "parsed.json"
OUT = HERE / "全库_面与主题_v20_20260919.jsonl"
REPORT = HERE / "角色清单补零归属_v20_20260919.md"
SAMPLE = 24
THEME = "角色›原作"


def series_of(slug: str) -> str:
    s = slug.replace("list_of_", "")
    for suf in ("_characters", "_servants", "_units_and_subgroups", "_identities"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return re.sub(r"\s+", " ", s.replace("_", " ")).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    wiki = json.loads(WIKI.read_text(encoding="utf-8"))

    lookup = {}
    for slug, info in wiki.items():
        if not slug.startswith("list_of"):
            continue
        if not any(k in slug for k in ("characters", "servants", "pokemon", "digimon",
                                       "youkai", "pals", "monsters", "mascots",
                                       "warframes", "identities", "rocodex")):
            continue
        series = series_of(slug)
        for sec in info["sections"]:
            for t in sec["tags"]:
                if t.startswith(("tag_group:", "list_of_")):
                    continue
                p = norm_phrase(t)
                if p and len(p) >= 3:
                    lookup.setdefault(p, set()).add(series)

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

    changed = 0
    by_rule = Counter()
    by_series = Counter()
    got_series = 0
    samples = []
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

        toks = [t for t in TOKEN.split((text or "").lower()) if t]
        n = len(toks)
        matched = {}          # 短语 -> 作品集合
        for i in range(n):
            for k in range(1, MAXN + 1):
                if i + k > n:
                    break
                gram = " ".join(toks[i:i + k])
                g = lookup.get(gram)
                if g:
                    matched[gram] = g

        cur_series = (doc.get("series") or "").strip().lower()
        accept = set()
        rule = None
        if matched and cur_series:
            cand = {x for g in matched.values() for x in g}
            if cur_series in cand:
                accept = {cur_series}
                rule = "闸1 与已有 series 一致"
        if not accept and matched and not cur_series:
            multi = [g for p, g in matched.items() if len(p.split()) >= 2]
            if n <= 3 and multi:
                accept = set().union(*multi)
                rule = "闸2 短条目 + 多词角色名"

        if accept:
            themes = list(doc.get("themes", []))
            if THEME not in themes:
                themes.append(THEME)
            doc = dict(doc)
            doc["themes"] = themes
            doc["facets"] = list(doc.get("facets", []))
            if not doc.get("series"):
                doc["series"] = sorted(accept)[0]
                got_series += 1
            changed += 1
            by_rule[rule] += 1
            for x in accept:
                by_series[x] += 1
            if len(samples) < SAMPLE * 4:
                samples.append(((text or "")[:64], sorted(accept)[0], rule,
                                md5(u.encode()).hexdigest()))
            out_lines.append(json.dumps(
                {"id": u, "source": area, "leaf": e[1] if e else "",
                 "themes": themes, "facets": doc["facets"], "series": doc.get("series"),
                 "text": (text or "")[:150]}, ensure_ascii=False))
        else:
            out_lines.append(json.dumps(
                {"id": u, "source": area, "leaf": e[1] if e else "",
                 "themes": doc.get("themes", []), "facets": doc.get("facets", []),
                 "text": (text or "")[:150]}, ensure_ascii=False))

    if args.write:
        OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# 角色清单补零归属（v20）", "",
         f"- 补上 {THEME}：{changed:,} 条（其中顺带补 series {got_series:,} 条）", "",
         "| 判定闸门 | 条数 |", "| --- | --- |"]
    for k, v in by_rule.most_common():
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 命中作品 Top25", "", "| 作品 | 条目 |", "| --- | --- |"]
    for k, v in by_series.most_common(25):
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 抽样", ""]
    for t, ser, rule, _h in sorted(samples, key=lambda x: x[3])[:SAMPLE * 2]:
        L.append(f"- {t}   → `{ser}`（{rule}）")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"补上 {THEME} {changed:,} 条（顺带补 series {got_series:,}）")
    print("判定闸门：", dict(by_rule))
    print("抽样：")
    for t, ser, rule, _h in sorted(samples, key=lambda x: x[3])[:14]:
        print(f"   {t[:56]:<58} → {ser}  [{rule[:6]}]")
    print(f"落盘：{REPORT.name}{'；快照 ' + OUT.name if args.write else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
