"""第 28 轮：只修「名字对、分隔符不对」的角色条目（安全子集）。

样本：`amiya(arknights)` → `amiya_(arknights)`、`nian(arknights)` → `nian_(arknights)`
做法：在括号前补下划线后，结果必须**精确等于**官方角色名才改。
权重包裹（`{{furina_(genshin_impact)}}`）一律不动 —— 那是用户的权重语法。
difflib 猜出来的一律不用（实测会猜错，如 bronya → robin）。

用法： python fix_name_separator_v28.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from datetime import datetime
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DB = ROOT / "userdatas_zh_CN_tags.db"
REPORT = HERE / "分隔符修正_v28_20260919.md"
COMBO = re.compile(r"一键NSFW|一键模式")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    chars = set()
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["category"] == 4:
            chars.add(r["name"])

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

        plan = []
        for u, s, text in rows:
            e = subs.get(s)
            area = gdb.get(e[0], "") if e else ""
            doc = meta.get(u)
            if COMBO.search(area) or doc is None:
                continue
            if "角色›原作" not in (doc.get("themes") or []):
                continue
            t = (text or "").strip()
            if not t:
                continue
            m = re.match(r"^([^,;]+)(.*)$", t)
            if not m:
                continue
            head, tail = m.group(1).strip(), m.group(2)
            if head in chars:
                continue                       # 已经规范
            cand = head.lower()
            cand = re.sub(r"\s+", "_", cand)
            cand = re.sub(r"_?\(", "_(", cand)          # 括号前一律用下划线
            cand = re.sub(r"_+", "_", cand)
            if cand in chars and cand != head:
                plan.append((u, t, cand + tail))

        print(f"可安全修正的条目：{len(plan):,}")
        for _u, old, new in plan[:20]:
            print(f"   {old[:48]:<50} → {new[:48]}")
        L = ["# 角色名分隔符修正（v28）", "",
             f"- 修正 {len(plan):,} 条（只改「名字对、括号前缺下划线」这一类）", "",
             "| 原文 | 修正后 |", "| --- | --- |"]
        for _u, old, new in plan[:200]:
            L.append(f"| {old[:60]} | `{new[:60]}` |")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print(f"落盘：{REPORT.name}")

        if not args.apply or not plan:
            print("dry-run 或无需改动。")
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_separator_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)
        con.executemany("update tag_tags set text=? where t_uuid=?",
                        [(new, u) for u, _o, new in plan])
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.execute("update workbench_tag_text_revision set value = value + 1 where id = 1")
        con.commit()
        print(f"已修正 {len(plan):,} 条")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
