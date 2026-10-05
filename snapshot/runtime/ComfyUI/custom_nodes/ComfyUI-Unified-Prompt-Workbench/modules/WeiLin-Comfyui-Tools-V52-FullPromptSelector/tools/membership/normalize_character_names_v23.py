"""第 23 轮：把角色名统一成 danbooru 官方写法（只改逗号前那一段）。

只要「逗号前那一段」归一化后等于官方角色名、且写法与官方不同，就替换成官方写法：
    `25-ji miku`            → `25-ji_miku`
    `2b (nier:automata)`    → `2b_(nier:automata)`
    `hu tao (genshin impact),genshin impact` → `hu_tao_(genshin_impact),genshin impact`
逗号之后的内容（作品、权重等）原样保留。

顺带：能确定作品的条目补 series + 角色›原作（复用 v22 的判据）。

用法：
  python normalize_character_names_v23.py            # dry-run：打印统计 + 写映射表
  python normalize_character_names_v23.py --apply    # 真改（改前自动备份 DB）
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DB = ROOT / "userdatas_zh_CN_tags.db"
MAPPING = HERE / "角色名统一映射_20260919.tsv"
REPORT = HERE / "角色名统一_v23_20260919.md"
COMBO = re.compile(r"一键NSFW|一键模式")
THEME = "角色›原作"


def norm(s: str) -> str:
    s = s.strip().lower().replace("\\(", "(").replace("\\)", ")")
    return re.sub(r"\s+", "_", s).strip("_")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    chars, copies = {}, {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        (chars if row["category"] == 4 else copies)[norm(row["name"])] = row["name"]

    con = sqlite3.connect(str(DB))
    try:
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

        existing_texts = Counter(t for _u, _s, t in rows)
        plan = []
        collide = 0
        for u, s, text in rows:
            e = subs.get(s)
            area = gdb.get(e[0], "") if e else ""
            if COMBO.search(area):
                continue
            t = (text or "").strip()
            if not t:
                continue
            m = re.match(r"^([^,;]+)(.*)$", t)
            if not m:            # 以逗号开头（画师串那种）直接跳过
                continue
            head, tail = m.group(1).strip(), m.group(2)
            canon = chars.get(norm(head))
            if not canon or canon == head:
                continue
            new_text = canon + tail
            if existing_texts.get(new_text) and new_text != t:
                collide += 1
            series = ""
            tv = copies.get(norm(tail.strip(" ,;")))
            if not tv:
                mm = re.search(r"\(([^)]+)\)", canon)
                if mm:
                    tv = mm.group(1).replace("_", " ")
            series = tv or ""
            plan.append((u, t, new_text, series, bool(existing_texts.get(new_text) and new_text != t)))

        print(f"可统一命名的条目：{len(plan):,}（其中改名后会与已有条目重名：{collide:,}）")
        by_series = Counter(x[3] for x in plan if x[3])
        print("能同时确定作品的：", sum(by_series.values()))

        with MAPPING.open("w", encoding="utf-8") as fh:
            fh.write("uuid\t原文本\t统一后\tseries\t重名\n")
            for u, old, new, series, dup in plan:
                fh.write(f"{u}\t{old}\t{new}\t{series}\t{'Y' if dup else ''}\n")
        print("映射表：", MAPPING.name)

        L = ["# 角色名统一为 danbooru 官方写法（v23）", "",
             f"- 可统一：{len(plan):,} 条（改名后与已有条目重名的 {collide:,} 条）",
             f"- 同时补上 series：{sum(by_series.values()):,}", "",
             "## 样例", "", "| 原文本 | 统一后 | series |", "| --- | --- | --- |"]
        for u, old, new, series, dup in plan[:60]:
            L.append(f"| {old[:46]} | `{new[:46]}` | {series} |")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print("报告：", REPORT.name)
        for _u, old, new, _s, _d in plan[:12]:
            print(f"   {old[:44]:<46} → {new[:44]}")

        if not args.apply:
            print("dry-run，未改动库。加 --apply 执行。")
            return 0

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"rename_characters_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        shutil.copy2(MAPPING, safe / MAPPING.name)
        print("已备份：", safe)

        con.executemany("update tag_tags set text=? where t_uuid=?",
                        [(new, u) for u, _o, new, _s, _d in plan])
        meta_updates = []
        for u, _o, _n, series, _d in plan:
            d = dict(meta.get(u) or {})
            themes = list(d.get("themes", []))
            if THEME not in themes:
                themes.append(THEME)
            d["themes"] = themes
            if series and not d.get("series"):
                d["series"] = series
            meta_updates.append((u, json.dumps(d, ensure_ascii=False)))
        con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) "
                        "values (?,?)", meta_updates)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.execute("update workbench_tag_text_revision set value = value + 1 where id = 1")
        con.commit()
        print(f"已改名 {len(plan):,} 条，并补 {THEME}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
