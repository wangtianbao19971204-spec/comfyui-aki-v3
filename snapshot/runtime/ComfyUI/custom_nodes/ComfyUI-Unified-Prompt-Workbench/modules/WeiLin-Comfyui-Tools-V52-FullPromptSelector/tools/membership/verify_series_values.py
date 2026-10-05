"""核实：库里写入的 series 值是不是 danbooru 官方作品名？不是的话给出近似候选。"""
from __future__ import annotations

import difflib
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
sys.path.insert(0, str(HERE))
from rebuild_action_scene_v8 import DB  # noqa: E402

TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
REPORT = HERE / "series值核实_20260919.md"


def norm(s: str) -> str:
    s = s.strip().lower().replace("\\(", "(").replace("\\)", ")")
    s = re.sub(r"[_\-–—]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,.")


def main() -> int:
    copies = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["category"] == 3:
            copies[norm(row["name"])] = row["name"]
    print(f"官方作品：{len(copies):,}")

    with sqlite3.connect(str(DB)) as con:
        vals = Counter()
        for (b,) in con.execute("select data from workbench_tag_meta"):
            try:
                v = (json.loads(b).get("series") or "").strip()
            except Exception:
                continue
            if v:
                vals[v.lower()] += 1
        total = sum(vals.values())
        ok = {k: v for k, v in vals.items() if norm(k) in copies}
        bad = {k: v for k, v in vals.items() if norm(k) not in copies}
        print(f"库里 series 取值：{len(vals):,} 种 / {total:,} 条")
        print(f"  标准作品名：{len(ok):,} 种 / {sum(ok.values()):,} 条")
        print(f"  非标准：{len(bad):,} 种 / {sum(bad.values()):,} 条")

        L = ["# series 值核实", "",
             f"- 库里 series 共 {len(vals):,} 种 / {total:,} 条",
             f"- **标准作品名**：{len(ok):,} 种 / {sum(ok.values()):,} 条",
             f"- **非标准**：{len(bad):,} 种 / {sum(bad.values()):,} 条", "",
             "## 非标准 series → 官方候选（按条数）", "",
             "| 库里 series | 条数 | 官方候选 | 相似度 |", "| --- | --- | --- | --- |"]
        keys = list(copies)
        fixed = 0
        for k, n in sorted(bad.items(), key=lambda x: -x[1])[:120]:
            cand = difflib.get_close_matches(norm(k), keys, n=1, cutoff=0.75)
            if cand:
                L.append(f"| {k} | {n} | `{copies[cand[0]]}` | "
                         f"{difflib.SequenceMatcher(None, norm(k), cand[0]).ratio():.2f} |")
                fixed += n
            else:
                L.append(f"| {k} | {n} | （无候选） | |")
        L += ["", f"（前 120 项覆盖 {fixed:,} 条）"]
        REPORT.write_text("\n".join(L), encoding="utf-8")

        print()
        print("非标准 series Top20 → 候选：")
        for k, n in sorted(bad.items(), key=lambda x: -x[1])[:20]:
            cand = difflib.get_close_matches(norm(k), keys, n=1, cutoff=0.75)
            print(f"   {k:<28} {n:>5}  →  {copies[cand[0]] if cand else '（无）'}")
        print(f"落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
