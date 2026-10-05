"""体检：库里有多少条目其实是「官方角色 / 官方作品」，但没挂对应归属。

判据：条目逗号前那一段（或整条）归一化后，能否对上官方 character / copyright 表。
输出：角色作品覆盖体检_20260919.md
"""
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
from rebuild_action_scene_v8 import DB, COMBO  # noqa: E402

TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
REPORT = HERE / "角色作品覆盖体检_20260919.md"
SAMPLE = 20
THEME_CHAR = "角色›原作"


def norm(s: str) -> str:
    s = s.strip().lower().replace("\\(", "(").replace("\\)", ")")
    return re.sub(r"\s+", "_", s).strip("_")


def main() -> int:
    chars, copies = {}, {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        (chars if row["category"] == 4 else copies)[norm(row["name"])] = row
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

    stat = Counter()
    miss_char = []      # 是角色，但没挂 角色›原作
    miss_series = []    # 是角色，有 角色›原作 但没 series
    miss_copy = []      # 是作品，但没 series
    for u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        doc = meta.get(u)
        if COMBO.search(area) or doc is None:
            continue
        t = (text or "").strip()
        if not t:
            continue
        head = re.split(r"[,;]", t)[0].strip()
        h = norm(head)
        themes = doc.get("themes", []) or []
        series = doc.get("series") or ""
        is_char = h in chars
        is_copy = h in copies
        if is_char:
            stat["是官方角色"] += 1
            if THEME_CHAR not in themes:
                stat["  ↳ 缺 角色›原作"] += 1
                if len(miss_char) < 300:
                    miss_char.append((t[:60], chars[h]["name"], md5(u.encode()).hexdigest()))
            if not series:
                stat["  ↳ 缺 series"] += 1
                if len(miss_series) < 300:
                    miss_series.append((t[:60], chars[h]["name"]))
        if is_copy:
            stat["是官方作品"] += 1
            if not series:
                stat["  ↳ 缺 series"] += 1
                if len(miss_copy) < 300:
                    miss_copy.append((t[:60], copies[h]["name"]))

    L = ["# 角色 / 作品 归属覆盖体检", "",
         f"- 官方表：角色 {len(chars):,}｜作品 {len(copies):,}", "",
         "| 项目 | 条数 |", "| --- | --- |"]
    for k, v in stat.most_common():
        L.append(f"| {k} | {v:,} |")
    L += ["", "## 一、是角色但缺「角色›原作」（样例）", "",
          "| 库里文本 | 官方名 |", "| --- | --- |"]
    for t, c, _h in sorted(miss_char, key=lambda x: x[2])[:SAMPLE]:
        L.append(f"| {t} | `{c}` |")
    L += ["", "## 二、是角色但缺 series（样例）", "", "| 库里文本 | 官方名 |", "| --- | --- |"]
    for t, c in miss_series[:SAMPLE]:
        L.append(f"| {t} | `{c}` |")
    L += ["", "## 三、是作品但缺 series（样例）", "", "| 库里文本 | 官方名 |", "| --- | --- |"]
    for t, c in miss_copy[:SAMPLE]:
        L.append(f"| {t} | `{c}` |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print("统计：", dict(stat))
    print("缺 角色›原作 的样例：")
    for t, c, _h in sorted(miss_char, key=lambda x: x[2])[:10]:
        print(f"   {t[:44]:<46} | {c}")
    print(f"落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
