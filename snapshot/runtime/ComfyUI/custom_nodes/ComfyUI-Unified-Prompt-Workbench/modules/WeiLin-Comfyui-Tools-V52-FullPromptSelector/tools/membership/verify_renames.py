"""核实 v23 那批改名：抽样 + 可疑项筛查。

可疑定义：改后的官方名是**不带括号的短名字**（≤2 个词），这类最容易和普通词撞名
（rainy_days / violet / stockade 这种），要人工过一遍。
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
MAP = HERE / "角色名统一映射_20260919.tsv"
TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DB = ROOT / "userdatas_zh_CN_tags.db"
REPORT = HERE / "改名核实_20260919.md"


def main() -> int:
    rows = []
    for line in MAP.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 4:
            rows.append(parts)
    print(f"映射表：{len(rows):,} 条")

    chars = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["category"] == 4:
            chars[r["name"]] = r["post_count"]
    con = sqlite3.connect(str(DB))
    bad_new = 0
    still_old = 0
    missing = 0
    suspicious = []
    plain = 0
    for uuid, old, new, series, dup in rows:
        head = new.split(",")[0]
        if head not in chars:
            bad_new += 1
        cur = con.execute("select text from tag_tags where t_uuid=?", (uuid,)).fetchone()
        if not cur:
            missing += 1
            continue
        if cur[0] == old:
            still_old += 1
        # 可疑：官方名不带括号且 ≤2 个词
        if "(" not in head and len(head.split("_")) <= 2:
            plain += 1
            if len(suspicious) < 200:
                suspicious.append((old, new, series))

    print(f"  改成的新名不在官方角色表里的：{bad_new}")
    print(f"  库里还是旧文本的：{still_old}")
    print(f"  uuid 在库里找不到的：{missing}")
    print(f"  新名是「不带括号的短名」：{plain:,}（抽 40 条人工看）")

    random.seed(7)
    L = ["# 改名核实（v23 的 38,051 条）", "",
         f"- 映射条数：{len(rows):,}",
         f"- 新名不在官方角色表：{bad_new}",
         f"- 库里仍是旧文本：{still_old}",
         f"- 新名是「不带括号的短名」：{plain:,}", "",
         "## 一、随机抽 40 条（人工核对）", "", "| 原文 | 改成 | series |", "| --- | --- | --- |"]
    for uuid, old, new, series, _d in random.sample(rows, 40):
        L.append(f"| {old[:52]} | `{new[:52]}` | {series} |")
    L += ["", "## 二、可疑项抽样（不带括号的短名，最容易撞普通词）", "",
          "| 原文 | 改成 | series |", "| --- | --- | --- |"]
    for old, new, series in random.sample(suspicious, min(40, len(suspicious))):
        L.append(f"| {old[:52]} | `{new[:52]}` | {series} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"落盘：{REPORT.name}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
