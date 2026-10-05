"""第 30 轮：修「角色›职业」的精度问题（抽样显示只有约 50-60%）。

误判全是一类：职业词后面紧跟服饰/物件名词，于是「某件衣服」被当成了「某职业」
    maid headdress / witch hat / nurse cap / idol posters / springfield_(classic_witch)

修法：要求**独立命中** —— 该职业词至少有一次后面不是服饰/物件名词，
或者它本来就是独立成词的。全部命中都被后接词否定 → 撤除该轴。
括号内的命中不算（那是角色名/服装名）。

用法： python fix_job_axis_v30.py [--apply]
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402
from fix_boundary_v21 import widen_pattern  # noqa: E402

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
REPORT = HERE / "职业轴修正_v30_20260919.md"
SAMPLE = 30
LABEL = "角色›职业"
PATTERN = (r"\b(maid|nurse|idol|teacher|student|knight|ninja|witch|police|"
           r"office lady|flight attendant|scientist)\b")
# 命中词后面跟这些 → 它是在修饰服饰/场所，不是在说职业
REJECT_AFTER = {
    "hat", "cap", "hats", "headdress", "headband", "headdress", "crown",
    "dress", "outfit", "uniform", "costume", "clothes", "clothing", "apron",
    "gloves", "sleeves", "shoes", "boots", "stockings", "thighhighs",
    "poster", "posters", "room", "office", "cafe", "shop", "mask", "wings",
    "ears", "tail", "horns", "print", "pattern", "style", "themed",
}
PAREN = re.compile(r"\([^()]*\)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

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
        kept_ok = 0
        for u, s, text in rows:
            e = subs.get(s)
            area = gdb.get(e[0], "") if e else ""
            doc = meta.get(u)
            if COMBO.search(area) or doc is None:
                continue
            if LABEL not in (doc.get("themes") or []):
                continue
            body = denoise(text)
            nop = PAREN.sub(" ", body)
            all_m = list(rx.finditer(body))
            out_m = list(rx.finditer(nop))
            if not all_m:
                continue                      # 来自 danbooru 清单，别动
            if not out_m:
                drop.append(u)                # 只在括号里命中
                if len(samples) < SAMPLE * 3:
                    samples.append((body[:60], "（括号内）", md5(u.encode()).hexdigest()))
                continue
            if all(
                (lambda nx: nx and nx.group(1) in REJECT_AFTER)(
                    re.match(r"[ _]+([a-z0-9']+)", nop[m.end():m.end() + 24]))
                for m in out_m
            ):
                drop.append(u)
                if len(samples) < SAMPLE * 3:
                    parts = []
                    for m in out_m[:2]:
                        nxt = re.match(r"[ _]+([a-z0-9()']+)", nop[m.end():m.end() + 20])
                        if nxt:
                            parts.append(m.group(0) + "+" + nxt.group(1))
                    samples.append((body[:60], "、".join(parts) or "?",
                                    md5(u.encode()).hexdigest()))
            else:
                kept_ok += 1

        print(f"要撤除：{len(drop):,}（保留 {kept_ok:,}）")
        for t, hit, _h in sorted(samples, key=lambda x: x[2])[:18]:
            print(f"   {t[:50]:<52} ← {hit}")
        L = ["# 职业轴修正（v30）", "", f"- 撤除 {len(drop):,} 条（保留 {kept_ok:,}）", "",
             "## 撤除样例", "", "| 文本 | 命中 |", "| --- | --- |"]
        for t, hit, _h in sorted(samples, key=lambda x: x[2])[:SAMPLE * 2]:
            L.append(f"| {t} | {hit} |")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print(f"落盘：{REPORT.name}")

        if not args.apply or not drop:
            print("dry-run 或无需改动。")
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_job_{stamp}"
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
    raise SystemExit(main())
