"""拆解剩余零归属：中文 / 长串 / 画师串 / 身份体型词，各占多少。"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rebuild_action_scene_v8 import DB, COMBO  # noqa: E402

REPORT = HERE / "零归属拆解_20260919.md"


def main() -> int:
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

    rows = []
    for u, s, t in con.execute("select t_uuid, subgroup_id, text from tag_tags"):
        d = meta.get(u)
        if d is None or d.get("themes") or d.get("facets"):
            continue
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        if COMBO.search(area):
            continue
        rows.append(((t or "").strip(), area, e[1] if e else ""))

    cn = [r for r in rows if re.search(r"[\u4e00-\u9fff]", r[0])]
    long_ = [r for r in rows if len(r[0]) > 60 and r not in cn]
    artist = [r for r in rows if r[1] == "画风组词典" and r not in cn and r not in long_]
    short = [r for r in rows if r not in cn and r not in long_ and r not in artist]

    print(f"零归属合计 {len(rows):,}")
    print(f"  含中文        {len(cn):,}")
    print(f"  长串(>60)     {len(long_):,}")
    print(f"  画风组词典     {len(artist):,}")
    print(f"  其余短词       {len(short):,}")
    print()
    words = Counter(r[0].lower() for r in short)
    print("其余短词 Top60（按出现次数）：")
    for w, c in words.most_common(60):
        print(f"   {w[:40]:<42} {c}")
    print()
    print("按区域分布（其余短词）：")
    for a, c in Counter(r[1] for r in short).most_common(12):
        print(f"   {a:<22} {c}")

    L = ["# 零归属拆解", "",
         f"- 合计 {len(rows):,}",
         f"- 含中文 {len(cn):,}",
         f"- 长串(>60) {len(long_):,}",
         f"- 画风组词典(画师串) {len(artist):,}",
         f"- 其余短词 {len(short):,}", "",
         "## 其余短词（去重后按词频）", ""]
    for w, c in words.most_common(300):
        L.append(f"- {w}  ×{c}")
    L += ["", "## 含中文样例", ""]
    for t, a, leaf in cn[:20]:
        L.append(f"- {t[:70]}  ({a})")
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"落盘：{REPORT.name}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
