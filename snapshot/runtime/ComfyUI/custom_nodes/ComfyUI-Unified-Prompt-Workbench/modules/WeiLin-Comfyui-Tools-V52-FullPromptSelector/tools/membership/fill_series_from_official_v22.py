"""第 22 轮：用 danbooru 官方标签表给「没有 series 的条目」补 series + 角色›原作。

数据：danbooru_tags_api/tagtable.jsonl（category 4 角色 401,596 条；category 3 作品 69,270 条）
判据（高精度）：条目的「逗号前那段名字」归一化后**精确等于**某个官方角色标签。

series 取值优先级：
  1) 条目逗号后的尾巴，归一化后能对上官方作品表 → 用官方作品名
  2) 官方角色名里的括号内容（kaga_(kancolle) → kancolle）
  3) 留空

用法： python fill_series_from_official_v22.py [--write]
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

TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
OUT = HERE / "全库_面与主题_v22_20260919.jsonl"
REPORT = HERE / "补series_v22_20260919.md"
SAMPLE = 30
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
        (chars if row["category"] == 4 else copies)[norm(row["name"])] = row
    copy_norm = {k: v["name"] for k, v in copies.items()}
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

    changed = 0
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
        if not t or doc.get("series"):
            out_lines.append(json.dumps(
                {"id": u, "source": area, "leaf": e[1] if e else "",
                 "themes": doc.get("themes", []), "facets": doc.get("facets", []),
                 "series": doc.get("series"), "text": t[:150]}, ensure_ascii=False))
            continue
        head = re.split(r"[,;]", t)[0].strip()
        tail = t[len(head):].strip(" ,;")
        canon = chars.get(norm(head))
        if not canon:
            out_lines.append(json.dumps(
                {"id": u, "source": area, "leaf": e[1] if e else "",
                 "themes": doc.get("themes", []), "facets": doc.get("facets", []),
                 "text": t[:150]}, ensure_ascii=False))
            continue

        series = ""
        if tail:
            tv = copy_norm.get(norm(tail))
            if tv:
                series = tv
                by_src["条目尾巴对上官方作品"] += 1
        if not series:
            m = re.search(r"\(([^)]+)\)", canon["name"])
            if m:
                series = m.group(1).replace("_", " ")
                by_src["用官方角色名的括号"] += 1
        if not series:
            # 只有角色名、推不出作品的不动：cyan / violet / cloudy 这类既是颜色也是角色名，风险太大
            by_src["跳过：推不出作品（颜色词等风险）"] += 1
            out_lines.append(json.dumps(
                {"id": u, "source": area, "leaf": e[1] if e else "",
                 "themes": doc.get("themes", []), "facets": doc.get("facets", []),
                 "text": t[:150]}, ensure_ascii=False))
            continue

        themes = list(doc.get("themes", []))
        if THEME not in themes:
            themes.append(THEME)
        changed += 1
        if len(samples) < SAMPLE * 4:
            samples.append((t[:56], canon["name"], series, md5(u.encode()).hexdigest()))
        out_lines.append(json.dumps(
            {"id": u, "source": area, "leaf": e[1] if e else "",
             "themes": themes, "facets": doc.get("facets", []),
             "series": series, "text": t[:150]}, ensure_ascii=False))

    if args.write:
        OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# 用 danbooru 官方表补 series + 角色›原作（v22）", "",
         f"- 补上的条目：{changed:,}", "",
         "| series 来源 | 条数 |", "| --- | --- |"]
    for k, v in by_src.most_common():
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 抽样", "", "| 库里原文 | 官方角色名 | series |", "| --- | --- | --- |"]
    for t, cname, series, _h in sorted(samples, key=lambda x: x[3])[:SAMPLE * 2]:
        L.append(f"| {t} | `{cname}` | {series} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"补上 {changed:,} 条")
    print("series 来源：", dict(by_src))
    for t, cname, series, _h in sorted(samples, key=lambda x: x[3])[:14]:
        print(f"   {t[:40]:<42} → {cname:<28} | {series}")
    print(f"落盘：{REPORT.name}{'；快照 ' + OUT.name if args.write else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
