"""全库条级多归属：每个 tag 记录**全部** 主题›小分类 归属（不是单一主主题）。

输出：全库条级归属_20260919.jsonl + 归属分布统计
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
sys.path.insert(0, str(HERE))
from per_entry_theme import themes_of  # noqa: E402

DB = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
          r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\userdatas_zh_CN_tags.db")
OUT = HERE / "全库条级归属_20260919.jsonl"
REPORT = HERE / "全库条级归属统计_20260919.md"
COMBO = re.compile(r"一键NSFW|一键模式")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    with sqlite3.connect(str(DB)) as con:
        groups = {row[0]: row[1] for row in con.execute("select id_index, name from tag_groups")}
        subs = {row[0]: (row[1], row[2]) for row in
                con.execute("select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
    if args.limit:
        rows = rows[:args.limit]
    counts = Counter()
    sub_counter: Counter = Counter()
    theme_counter: Counter = Counter()
    examples: dict[int, list[str]] = defaultdict(list)
    total = combo = 0
    with OUT.open("w", encoding="utf-8") as handle:
        for uuid, subgroup_id, text in rows:
            entry = subs.get(subgroup_id)
            area = groups.get(entry[0], "") if entry else ""
            if COMBO.search(area):
                combo += 1
                continue
            total += 1
            _primary, hits = themes_of(text or "")
            counts[len(hits)] += 1
            for hit in hits:
                sub_counter[hit] += 1
                theme_counter[hit.split("›")[0]] += 1
            if len(hits) >= 4 and len(examples[len(hits)]) < 4:
                examples[len(hits)].append(f"{(text or '')[:70]} → {' + '.join(hits)}")
            handle.write(json.dumps({"id": uuid, "source": area, "leaf": entry[1] if entry else "",
                                     "memberships": hits, "text": (text or "")[:150]},
                                    ensure_ascii=False) + "\n")
    lines = ["# 全库条级多归属统计", "",
             f"- 参与 tag：{total:,}（排除一键组合 {combo:,}）",
             f"- **平均每条归属数：{sum(k * v for k, v in counts.items()) / max(1, total):.2f}**", "",
             "| 每条的归属数 | 条数 | 占比 |", "| --- | --- | --- |"]
    for number in sorted(counts):
        lines.append(f"| {number} | {counts[number]:,} | {counts[number] / total * 100:.1f}% |")
    lines += ["", "## 主题级计数（一条可计入多个主题）", "", "| 主题 | 条数 |", "| --- | --- |"]
    for theme, count in theme_counter.most_common():
        lines.append(f"| {theme} | {count:,} |")
    lines += ["", "## 小分类 Top25", "", "| 小分类 | 条数 |", "| --- | --- |"]
    for name, count in sub_counter.most_common(25):
        lines.append(f"| {name} | {count:,} |")
    lines += ["", "## 多归属示例（≥4 个归属）", ""]
    for number, items in sorted(examples.items(), reverse=True):
        lines.append(f"### {number} 个归属")
        lines += [f"- {item}" for item in items]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"参与 {total:,}（排除组合包 {combo:,}）")
    print(f"平均归属数 {sum(k * v for k, v in counts.items()) / max(1, total):.2f}")
    print("归属数分布：", dict(sorted(counts.items())))
    print("主题级计数：", dict(theme_counter.most_common()))
    print(f"落盘：{OUT.name} / {REPORT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
