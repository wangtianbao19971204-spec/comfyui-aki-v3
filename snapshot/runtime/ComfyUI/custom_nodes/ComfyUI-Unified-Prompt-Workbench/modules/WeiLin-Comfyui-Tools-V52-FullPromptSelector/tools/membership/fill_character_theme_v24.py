"""第 24 轮：把「是官方角色」的条目补齐 角色›原作（+ 缺失的 series）。

体检发现：42,113 条目本来就是官方角色，其中 3,294 条没挂 角色›原作。
判据仍是「逗号前那段归一化后 == 官方角色名」，只增不改。

用法： python fill_character_theme_v24.py [--write]
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
from rebuild_action_scene_v8 import DB, COMBO  # noqa: E402

TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
OUT = HERE / "全库_面与主题_v24_20260919.jsonl"
REPORT = HERE / "补角色原作_v24_20260919.md"
SAMPLE = 24
THEME = "角色›原作"


def norm(s: str) -> str:
    s = s.strip().lower().replace("\\(", "(").replace("\\)", ")")
    return re.sub(r"\s+", "_", s).strip("_")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    chars, copies = {}, {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        # 注意：只有 category 3 才是作品；1=画师、5=meta，别混进来
        if row["category"] == 4:
            chars[norm(row["name"])] = row["name"]
        elif row["category"] == 3:
            copies[norm(row["name"])] = row["name"]
    print(f"官方表：角色 {len(chars):,}｜作品 {len(copies):,}")

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

    changed = got_theme = got_series = 0
    by_src = Counter()
    samples = []
    out_lines = []
    for u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        doc = meta.get(u)
        if COMBO.search(area) or doc is None:
            continue
        t = (text or "").strip()
        themes = list(doc.get("themes", []))
        facets = list(doc.get("facets", []))
        series = doc.get("series") or ""
        if t:
            head = re.split(r"[,;]", t)[0].strip()
            tail = t[len(head):].strip(" ,;")
            canon = chars.get(norm(head))
            if canon:
                if THEME not in themes:
                    themes.append(THEME)
                    got_theme += 1
                if not series:
                    tv = copies.get(norm(tail))
                    if tv:
                        series = tv
                        by_src["条目尾巴对上官方作品"] += 1
                    else:
                        m = re.search(r"\(([^)]+)\)", canon)
                        if m:
                            series = m.group(1).replace("_", " ")
                            by_src["用官方角色名的括号"] += 1
                        else:
                            by_src["推不出作品"] += 1
                    if series:
                        got_series += 1
                if got_theme or got_series:
                    changed += 1
                    if len(samples) < SAMPLE * 4:
                        samples.append((t[:56], canon, series, md5(u.encode()).hexdigest()))
        out_lines.append(json.dumps(
            {"id": u, "source": area, "leaf": e[1] if e else "",
             "themes": themes, "facets": facets, "series": series, "text": t[:150]},
            ensure_ascii=False))

    if args.write:
        OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# 补「角色›原作」与 series（v24）", "",
         f"- 新增 角色›原作：{got_theme:,} 条", f"- 补上 series：{got_series:,} 条", "",
         "| series 来源 | 条数 |", "| --- | --- |"]
    for k, v in by_src.most_common():
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 抽样", "", "| 库里文本 | 官方角色名 | series |", "| --- | --- | --- |"]
    for t, c, ser, _h in sorted(samples, key=lambda x: x[3])[:SAMPLE * 2]:
        L.append(f"| {t} | `{c}` | {ser} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"新增 角色›原作 {got_theme:,}；补 series {got_series:,}")
    print("series 来源：", dict(by_src))
    for t, c, ser, _h in sorted(samples, key=lambda x: x[3])[:12]:
        print(f"   {t[:40]:<42} | {c:<26} | {ser}")
    print(f"落盘：{REPORT.name}{'；快照 ' + OUT.name if args.write else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
