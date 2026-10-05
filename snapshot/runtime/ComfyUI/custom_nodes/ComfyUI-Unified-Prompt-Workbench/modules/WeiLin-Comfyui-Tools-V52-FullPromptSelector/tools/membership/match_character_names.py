"""拿 danbooru 官方 character/copyright 表核对库里的角色名，找出不规范命名并给出标准名。

输入：danbooru_tags_api/tagtable.jsonl（category 3/4）
输出：角色名核对_20260919.md（原文 → 标准名 → 作品 / 未匹配）

用法： python match_character_names.py [--sample 30]
"""
from __future__ import annotations

import argparse
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

TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
REPORT = HERE / "角色名核对_20260919.md"
SAMPLE = 30


def norm(s: str) -> str:
    s = s.strip().lower().replace("\\(", "(").replace("\\)", ")")
    s = re.sub(r"\s+", "_", s)
    return s.strip("_")


def base(s: str) -> str:
    return norm(re.sub(r"\s*\([^)]*\)\s*$", "", s))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=SAMPLE)
    ap.add_argument("--scope", choices=("zero", "noseries"), default="zero",
                    help="zero=零归属且无 series；noseries=所有没有 series 的条目")
    args = ap.parse_args()

    chars, copies = {}, {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        (chars if row["category"] == 4 else copies)[norm(row["name"])] = row
    print(f"danbooru 官方表：character {len(chars):,}｜copyright {len(copies):,}")

    by_base = defaultdict(list)
    for k, v in chars.items():
        by_base[base(k)].append(v)
    copy_names = {base(k) for k in copies} | set(copies)

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
    exact, fuzzy, unmatched = [], [], []
    for u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        doc = meta.get(u)
        if COMBO.search(area) or doc is None:
            continue
        if doc.get("series"):
            continue
        if args.scope == "zero" and (doc.get("themes") or doc.get("facets")):
            continue
        t = (text or "").strip()
        if not t:
            continue
        head = re.split(r"[,;]", t)[0].strip()
        tail = t[len(head):].strip(" ,;")
        h = norm(head)
        if h in chars:
            stat["精确命中官方名"] += 1
            exact.append((t, chars[h]["name"], chars[h]["post_count"], tail))
        else:
            b = base(head)
            cands = by_base.get(b, [])
            if cands:
                best = max(cands, key=lambda r: r["post_count"])
                stat["同名多作品（可补全括号）"] += 1
                fuzzy.append((t, best["name"], best["post_count"], tail))
            elif b in copy_names:
                stat["命中的是作品不是角色"] += 1
            else:
                stat["官方表里没有"] += 1
                if len(unmatched) < 400:
                    unmatched.append(t)

    L = [f"# 角色名与 danbooru 官方表核对（范围：{args.scope}）", "",
         f"- danbooru 官方：character {len(chars):,}｜copyright {len(copies):,}", "",
         "| 情况 | 条数 |", "| --- | --- |"]
    for k, v in stat.most_common():
        L.append(f"| {k} | {v:,} |")

    L += ["", "## 一、名字已经就是官方名（只差 series）", "", "| 库里原文 | 官方名 | 作品证据 |", "| --- | --- | --- |"]
    for t, cname, pc, tail in exact[:args.sample]:
        L.append(f"| {t[:52]} | `{cname}` | {tail[:30]} |")
    L += ["", "## 二、库里的写法不规范 → 可改成官方名", "",
          "| 库里原文 | 建议改成 | 作品证据 |", "| --- | --- | --- |"]
    for t, cname, pc, tail in fuzzy[:args.sample]:
        L.append(f"| {t[:52]} | `{cname}` | {tail[:30]} |")
    L += ["", "## 三、官方表里没有的（样例）", ""]
    for t in unmatched[:args.sample]:
        L.append(f"- {t[:70]}")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print("统计：", dict(stat))
    print("样例（可改名的）：")
    for t, cname, _pc, _tail in fuzzy[:12]:
        print(f"   {t[:44]:<46} → {cname}")
    print(f"落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
