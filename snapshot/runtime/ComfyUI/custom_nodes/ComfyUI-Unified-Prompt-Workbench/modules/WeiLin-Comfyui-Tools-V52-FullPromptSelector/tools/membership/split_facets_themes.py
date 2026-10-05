"""定稿：把规则分成「面（facet）」与「主题（theme）」两池，重跑全库 + 断言 + 抽样。"""
from __future__ import annotations

import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from per_entry_theme import denoise  # noqa: E402

DB = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
          r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\userdatas_zh_CN_tags.db")
RULES = HERE / "最终规则_v2_20260919.json"
OUT_JSONL = HERE / "全库_面与主题_20260919.jsonl"
REPORT = HERE / "面与主题_定稿统计_20260919.md"
SAMPLE = HERE / "面与主题_抽样验收_20260919.md"
COMBO = re.compile(r"一键NSFW|一键模式")
# 面规则：人人都有，只做筛选，不进主题
FACET_KEYS = {("人物数量", "在场人数"), ("外貌", "面部"), ("外貌", "发型"), ("外貌", "身体"),
              ("状态", "半脱"), ("成人", "露出")}
MAX_THEME_RATE = 0.30


def main() -> int:
    raw = json.loads(RULES.read_text(encoding="utf-8"))
    facets = [(r["theme"], r["sub"], re.compile(r["pattern"], re.I)) for r in raw
              if (r["theme"], r["sub"]) in FACET_KEYS]
    themes = [(r["theme"], r["sub"], re.compile(r["pattern"], re.I)) for r in raw
              if (r["theme"], r["sub"]) not in FACET_KEYS]
    empty = [f"{t}›{s}" for t, s, p in facets + themes if not p.pattern.strip("$^ ")]
    with sqlite3.connect(str(DB)) as con:
        groups = {row[0]: row[1] for row in con.execute("select id_index, name from tag_groups")}
        subs = {row[0]: (row[1], row[2]) for row in
                con.execute("select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
    theme_hits: Counter = Counter()
    facet_hits: Counter = Counter()
    per_tag: list[dict] = []
    total = 0
    for uuid, subgroup_id, text in rows:
        entry = subs.get(subgroup_id)
        area = groups.get(entry[0], "") if entry else ""
        if COMBO.search(area):
            continue
        total += 1
        body = denoise(text or "")
        tag_themes = [f"{t}›{s}" for t, s, p in themes if p.search(body)]
        tag_themes = list(dict.fromkeys(tag_themes))
        tag_facets = [f"{t}›{s}" for t, s, p in facets if p.search(body)]
        tag_facets = list(dict.fromkeys(tag_facets))
        for label in tag_themes:
            theme_hits[label] += 1
        for label in tag_facets:
            facet_hits[label] += 1
        per_tag.append({"id": uuid, "source": area, "leaf": entry[1] if entry else "",
                        "themes": tag_themes, "facets": tag_facets, "text": (text or "")[:150]})
    OUT_JSONL.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in per_tag),
                         encoding="utf-8")
    violations = [(label, count / total) for label, count in theme_hits.items()
                  if count / total > MAX_THEME_RATE]
    lines = ["# 面 / 主题 定稿统计", "",
             f"- 参与 tag {total:,}",
             f"- 面规则 {len(facets)} 条；主题规则 {len(themes)} 条；空模式 {len(empty)}",
             f"- 主题规则命中率超 {MAX_THEME_RATE:.0%} 的：{len(violations)}"
             f"{'（' + '；'.join(f'{n} {r:.0%}' for n, r in violations) + '）' if violations else ''}",
             f"- 平均每条：主题 {sum(len(r['themes']) for r in per_tag) / total:.2f} 个 / "
             f"面 {sum(len(r['facets']) for r in per_tag) / total:.2f} 个", "",
             "## 主题命中（分类浏览用）", "", "| 主题›小分类 | 条数 | 命中率 |", "| --- | --- | --- |"]
    for label, count in theme_hits.most_common():
        lines.append(f"| {label} | {count:,} | {count / total * 100:.1f}% |")
    lines += ["", "## 面命中（筛选用，不参与主题）", "", "| 面 | 条数 | 命中率 |", "| --- | --- | --- |"]
    for label, count in facet_hits.most_common():
        lines.append(f"| {label} | {count:,} | {count / total * 100:.1f}% |")
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    random.seed(20260919)
    sample_lines = ["# 面 / 主题 抽样验收", "", f"- 参与 {total:,} 条；每主题 20 条", ""]
    by_theme: dict[str, list[dict]] = defaultdict(list)
    for row in per_tag:
        for label in row["themes"]:
            by_theme[label.split("›")[0]].append(row)
    for theme, items in sorted(by_theme.items(), key=lambda kv: -len(kv[1])):
        sample_lines += [f"## {theme}（{len(items):,} 条）", "", "| 正文 | 主题 | 面 |", "| --- | --- | --- |"]
        for row in random.sample(items, min(20, len(items))):
            sample_lines.append(f"| {row['text'][:66]} | {' + '.join(row['themes'][:4])} | "
                                f"{' + '.join(row['facets'][:3])} |")
        sample_lines.append("")
    SAMPLE.write_text("\n".join(sample_lines), encoding="utf-8")
    print(f"参与 {total:,}；面规则 {len(facets)}／主题规则 {len(themes)}；空模式 {len(empty)}")
    print(f"主题规则超 30% 的：{violations}")
    print("主题 Top8：", dict(theme_hits.most_common(8)))
    print("面命中：", dict(facet_hits.most_common()))
    print(f"落盘：{OUT_JSONL.name} / {REPORT.name} / {SAMPLE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
