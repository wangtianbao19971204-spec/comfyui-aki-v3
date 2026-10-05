"""第 16 轮：撤掉「画风›画师」这个归属标签。

背景：画师这一块改用 Anima 画师大区（单独一区 + 图），资料库归属里不再保留
「画风›画师」。之前只把它从 10,070 压到 4,363，并没有真正撤掉。

「画风›画质」按你的要求保留。

用法： python retire_artist_label_v16.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CUR = HERE / "全库_面与主题_v15_20260919.jsonl"
OUT = HERE / "全库_面与主题_v16_20260919.jsonl"
REPORT = HERE / "撤掉画风画师_v16_20260919.md"

RETIRE = "画风›画师"


def main() -> int:
    rows = [json.loads(line) for line in CUR.read_text(encoding="utf-8").splitlines() if line.strip()]
    removed = 0
    samples = []
    out = []
    for row in rows:
        themes = list(row.get("themes", []))
        if RETIRE in themes:
            removed += 1
            if len(samples) < 15:
                samples.append((row.get("text") or "")[:70])
            themes = [t for t in themes if t != RETIRE]
        row["themes"] = themes
        out.append(json.dumps(row, ensure_ascii=False))
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")

    # 断言：撤掉之后全库不该再有这个标签
    left = sum(1 for line in out if RETIRE in json.loads(line).get("themes", []))
    assert left == 0, f"还剩 {left} 条没撤干净"

    L = [f"# 撤掉「{RETIRE}」（v16）", "",
         f"- 从 {len(rows):,} 条里撤除 **{removed:,}** 条的这个归属",
         "- 画师功能改由 Anima 画师大区承担（单区 + 预览图）",
         "- 「画风›画质」按原决定保留",
         "", "## 被撤掉的样例", ""]
    for s in samples:
        L.append(f"- {s}")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"撤除 {removed:,} 条「{RETIRE}」；复查剩余 {left} 条")
    for s in samples[:8]:
        print("   ", s)
    print(f"落盘：{OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
