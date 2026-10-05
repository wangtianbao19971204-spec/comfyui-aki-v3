"""第 31 轮：职业轴再收严——把「作品名 / 角色名里含职业词」的情况挖掉再判。

残留误判：`pepo_(flower_knight_girl)`、`ng knight lamune & 40`、`scarlet_witch`
这些名字里自带 knight / witch，但那条目不是说职业。

做法：先从官方 character/copyright 表里挑出**含职业词**的名字，
在条目文本里把这些名字整体挖空，再跑职业正则；挖空后不再命中 → 撤除该轴。

用法： python fix_job_name_v31.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402
from fix_boundary_v21 import widen_pattern  # noqa: E402

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
REPORT = HERE / "职业轴再收严_v31_20260919.md"
SAMPLE = 30
LABEL = "角色›职业"
JOB_WORDS = ("maid", "nurse", "idol", "teacher", "student", "knight", "ninja",
             "witch", "police", "office lady", "flight attendant", "scientist")
PATTERN = r"\b(" + "|".join(JOB_WORDS) + r")\b"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    # 含职业词的官方名字（角色 + 作品）
    names = set()
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["category"] not in (3, 4):
            continue
        low = r["name"].lower()
        if any(w in low for w in JOB_WORDS):
            names.add(low.replace("_", " ").strip())
    print(f"含职业词的官方名字：{len(names):,}")
    name_res = [re.compile(r"(?<![a-z0-9])" + re.escape(n).replace(r"\ ", "[ _]+")
                           + r"(?![a-z0-9])") for n in sorted(names, key=len, reverse=True)]

    rx = re.compile(widen_pattern(PATTERN), re.I)
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

        drop = []
        samples = []
        for u, s, text in rows:
            e = subs.get(s)
            area = gdb.get(e[0], "") if e else ""
            doc = meta.get(u)
            if COMBO.search(area) or doc is None:
                continue
            if LABEL not in (doc.get("themes") or []):
                continue
            body = denoise(text)
            if not rx.search(body):
                continue                     # 来自清单，别动
            cut = body
            for nre in name_res:
                cut = nre.sub(" ", cut)
            if not rx.search(cut):
                drop.append(u)
                if len(samples) < SAMPLE * 3:
                    m = rx.search(body)
                    samples.append((body[:62], m.group(0) if m else "",
                                    md5(u.encode()).hexdigest()))

        print(f"要撤除：{len(drop):,}")
        for t, hit, _h in sorted(samples, key=lambda x: x[2])[:18]:
            print(f"   {t[:54]:<56} ← {hit}")
        L = ["# 职业轴再收严（v31）", "", f"- 撤除 {len(drop):,} 条", "",
             "## 撤除样例", "", "| 文本 | 命中词 |", "| --- | --- |"]
        for t, hit, _h in sorted(samples, key=lambda x: x[2])[:SAMPLE * 2]:
            L.append(f"| {t} | `{hit}` |")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print(f"落盘：{REPORT.name}")

        if not args.apply or not drop:
            print("dry-run 或无需改动。")
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_jobname_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)
        updates = []
        for u in drop:
            d = dict(meta.get(u) or {})
            d["themes"] = [x for x in (d.get("themes") or []) if x != LABEL]
            updates.append((u, json.dumps(d, ensure_ascii=False)))
        con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) "
                        "values (?,?)", updates)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.commit()
        print(f"已撤除 {len(updates):,} 条")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
