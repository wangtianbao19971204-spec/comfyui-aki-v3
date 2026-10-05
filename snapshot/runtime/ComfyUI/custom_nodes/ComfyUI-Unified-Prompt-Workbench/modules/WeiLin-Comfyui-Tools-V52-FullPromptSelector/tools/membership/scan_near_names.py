"""近似名扫描：库里那些「挂在角色›原作下、但名字不是官方角色名」的条目，
用编辑距离找出近似候选，供人工确认是否属于命名不规范。

用法： python scan_near_names.py
输出：近似名候选_20260919.md
"""
from __future__ import annotations

import difflib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
DB = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
          r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\userdatas_zh_CN_tags.db")
REPORT = HERE / "近似名候选_20260919.md"
COMBO = re.compile(r"一键NSFW|一键模式")


def norm_key(s: str) -> str:
    s = s.strip().lower().replace("\\(", "(").replace("\\)", ")")
    return re.sub(r"\s+", "_", s).strip("_")


def main() -> int:
    chars = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["category"] == 4:
            chars[r["name"]] = r["post_count"]
    keys = list(chars)
    print(f"官方角色：{len(keys):,}")

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

    cands = []
    checked = 0
    for u, s, t in con.execute("select t_uuid, subgroup_id, text from tag_tags"):
        d = meta.get(u)
        if d is None or "角色›原作" not in (d.get("themes") or []):
            continue
        tx = (t or "").strip()
        if not tx:
            continue
        head = re.split(r"[,;]", tx)[0].strip()
        h = norm_key(head)
        if h in chars:
            continue                      # 已经是官方名
        checked += 1
        close = difflib.get_close_matches(h, keys, n=1, cutoff=0.88)
        if close:
            cands.append((tx[:56], head, close[0], chars[close[0]]))

    print(f"挂了 角色›原作 但头段不是官方名：{checked:,}")
    print(f"  其中有近似候选（相似度≥0.88）：{len(cands):,}")
    for tx, head, c, pc in cands[:20]:
        print(f"   {head[:34]:<36} ≈ {c:<28} (pc={pc})")

    L = ["# 近似名候选（挂在角色›原作下，但名字对不上官方表）", "",
         f"- 这类条目：{checked:,}", f"- 有近似候选：{len(cands):,}", "",
         "| 库里文本 | 头段 | 近似官方名 | 作品量 |", "| --- | --- | --- | --- |"]
    for tx, head, c, pc in cands[:400]:
        L.append(f"| {tx} | {head} | `{c}` | {pc:,} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"落盘：{REPORT.name}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
