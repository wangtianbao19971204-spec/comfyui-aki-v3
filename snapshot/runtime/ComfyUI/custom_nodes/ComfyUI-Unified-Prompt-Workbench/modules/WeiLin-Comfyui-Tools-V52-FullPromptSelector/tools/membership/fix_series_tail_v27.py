"""第 27 轮：给「有 角色›原作 但没 series」的条目补作品名。

v22/v23 用的是「整个逗号后尾巴」去比官方作品表，于是
    `dynasty ahri,league of legends,1girl,...`
这种尾巴是「作品, tag, tag…」的写法永远比不中。本轮改成**逐段试**：
逗号后的第 1 段、第 2 段各试一次，对上官方作品表就写入。

用法： python fix_series_tail_v27.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DB = ROOT / "userdatas_zh_CN_tags.db"
REPORT = HERE / "补series补漏_v27_20260919.md"
COMBO = re.compile(r"一键NSFW|一键模式")
SAMPLE = 30


def norm_key(s: str) -> str:
    s = s.strip().lower().replace("\\(", "(").replace("\\)", ")")
    s = re.sub(r"[_\-–—/]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ,.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    copies = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["category"] == 3:
            copies[norm_key(row["name"])] = row["name"]

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

        changes = []
        samples = []
        for u, s, text in rows:
            e = subs.get(s)
            area = gdb.get(e[0], "") if e else ""
            doc = meta.get(u)
            if COMBO.search(area) or doc is None:
                continue
            if (doc.get("series") or "").strip():
                continue
            if "角色›原作" not in (doc.get("themes") or []):
                continue
            t = (text or "").strip()
            segs = [x.strip() for x in re.split(r"[,;]", t)]
            hit = ""
            for seg in segs[1:3]:          # 只看逗号后的第 1、2 段
                if not seg:
                    continue
                seg = re.sub(r"^\d+(\.\d+)?\s*::\s*|\s*::$", "", seg).strip()
                v = copies.get(norm_key(seg))
                if v:
                    hit = v
                    break
            if not hit:
                continue
            changes.append((u, hit))
            if len(samples) < SAMPLE * 3:
                samples.append((t[:60], hit, md5(u.encode()).hexdigest()))

        print(f"可补 series 的条目：{len(changes):,}")
        for t, v, _h in sorted(samples, key=lambda x: x[2])[:16]:
            print(f"   {t[:52]:<54} → {v}")

        L = ["# 补 series 补漏（v27）", "", f"- 补上 {len(changes):,} 条", "",
             "## 样例", "", "| 文本 | 补上的作品 |", "| --- | --- |"]
        for t, v, _h in sorted(samples, key=lambda x: x[2])[:SAMPLE * 2]:
            L.append(f"| {t} | `{v}` |")
        REPORT.write_text("\n".join(L), encoding="utf-8")

        if not args.apply or not changes:
            print("dry-run 或无需改动。")
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_series_tail_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)
        updates = []
        for u, v in changes:
            d = dict(meta.get(u) or {})
            d["series"] = v
            updates.append((u, json.dumps(d, ensure_ascii=False)))
        con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) "
                        "values (?,?)", updates)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.commit()
        print(f"已补 {len(updates):,} 条")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
