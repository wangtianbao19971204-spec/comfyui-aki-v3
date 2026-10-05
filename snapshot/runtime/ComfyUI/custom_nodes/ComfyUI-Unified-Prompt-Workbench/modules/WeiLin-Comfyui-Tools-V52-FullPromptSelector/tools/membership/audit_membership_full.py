"""全量归属审计：逐条规则统计命中，并反查「是哪个短语在撑这条规则」。

做法：把规则（旧规则里除动作/场景外的全部 + v12 定稿的动作/场景 5 条 + 场景›背景）
重新跑一遍全库全文，对每条规则记录：
  * 命中数 / 命中率
  * 各短语的实际命中次数（Top N）——用来发现"某个弱词撑起半条规则"
  * 16 条随机样本（按 id 哈希均匀抽，带命中片段）

输出：归属全面审计_20260919.md
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rebuild_action_scene_v8 import DB, COMBO, denoise, load_wiki  # noqa: E402
from rebuild_action_scene_v11 import scene_body  # noqa: E402
import rebuild_action_scene_v12 as V12  # noqa: E402
from fix_weak_words_v13 import FIXED_PATTERN as BODY_PATTERN  # noqa: E402

OLD_RULES = HERE / "最终规则_v2_20260919.json"
REPORT = HERE / "归属全面审计_20260919.md"
MAX_RATE = 0.30
FACET_EXEMPT = ("人物数量", "外貌")
SAMPLE_PER_CLASS = 16


def build_all_rules():
    old = json.loads(OLD_RULES.read_text(encoding="utf-8"))
    rules = []
    for r in old:
        if r["theme"] in ("动作", "场景") and r["sub"] != "背景":
            continue                      # 动作/场景（除背景）用 v12 定稿替换
        rules.append((r["theme"], r["sub"], r["pattern"]))
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        rules.append((theme, sub, pattern))
    # v13 修过「外貌›身体」的弱词，审计要跟着用新规则，否则数字对不上库
    rules = [(t, s, BODY_PATTERN if f"{t}›{s}" == "外貌›身体" else p) for t, s, p in rules]
    return rules


def main() -> int:
    rules = build_all_rules()
    # 只有 v12 的「室内/室外」用去括号正文；场景›背景 沿用旧口径（看原文）
    compiled = [(t, s, re.compile(p, re.I),
                 t == "场景" and s in ("室内", "室外")) for t, s, p in rules]

    with sqlite3.connect(str(DB)) as con:
        groups = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()

    total = 0
    hits = Counter()
    phrases = defaultdict(Counter)
    samples = defaultdict(list)
    per_tag = Counter()

    for uuid, subgroup_id, text in rows:
        entry = subs.get(subgroup_id)
        area = groups.get(entry[0], "") if entry else ""
        if COMBO.search(area):
            continue
        total += 1
        raw = denoise(text)
        scene = scene_body(raw)
        n = 0
        for theme, sub, pattern, uses_scene in compiled:
            m = pattern.search(scene if uses_scene else raw)
            if not m:
                continue
            label = f"{theme}›{sub}"
            hits[label] += 1
            phrases[label][m.group(0)] += 1
            n += 1
            if len(samples[label]) < SAMPLE_PER_CLASS:
                samples[label].append((raw[:110], m.group(0)))
        per_tag[n] += 1

    # 重新按 id 哈希抽样（上面的顺序抽样有偏差）
    key = {}
    for uuid, subgroup_id, text in rows:
        key[uuid] = md5(uuid.encode("utf-8", "ignore")).hexdigest()
    best = defaultdict(list)
    for uuid, subgroup_id, text in rows:
        entry = subs.get(subgroup_id)
        area = groups.get(entry[0], "") if entry else ""
        if COMBO.search(area):
            continue
        raw = denoise(text)
        scene = scene_body(raw)
        for theme, sub, pattern, uses_scene in compiled:
            m = pattern.search(scene if uses_scene else raw)
            if not m:
                continue
            label = f"{theme}›{sub}"
            bucket = best[label]
            bucket.append((key[uuid], raw[:110], m.group(0)))
            bucket.sort(key=lambda x: x[0])
            del bucket[SAMPLE_PER_CLASS:]

    L = ["# 归属全面审计（2026-09-19）", "",
         f"- 参与 tag：{total:,}（排除一键组合区）",
         f"- 规则数：{len(rules)}（{len({t for t, _s, _p in rules})} 个主题/面）",
         "- 抽样方式：按 id 哈希均匀随机，每类 16 条", "",
         "## 一、总账", "",
         "| 主题 / 面 | 命中 | 命中率 | 不同短语数 | 最靠前的撑起短语 |",
         "| --- | --- | --- | --- | --- |"]
    for label, cnt in hits.most_common():
        ph = phrases[label]
        top = "、".join(f"`{p}`×{c}" for p, c in ph.most_common(3))
        L.append(f"| {label} | {cnt:,} | {cnt / total * 100:.2f}% | {len(ph)} | {top} |")

    L += ["", "## 二、每条规则命中最多的短语（Top 8）——认一认有没有弱词撑场", ""]
    for label, _cnt in hits.most_common():
        L.append(f"**{label}**")
        L.append("")
        L.append("、".join(f"`{p}`×{c}" for p, c in phrases[label].most_common(8)))
        L.append("")

    L += ["## 三、每类 16 条抽样", ""]
    for label, _cnt in hits.most_common():
        L += [f"### {label}（命中 {hits[label]:,}）", "",
              "| # | 文本 | 命中短语 |", "| --- | --- | --- |"]
        for i, (_k, txt, ph) in enumerate(best.get(label, []), 1):
            L.append(f"| {i} | {txt.replace('|', '/')} | `{ph}` |")
        L.append("")

    L += ["## 四、每条的归属个数分布", "", "| 归属个数 | tag 数 |", "| --- | --- |"]
    for k in sorted(per_tag):
        L.append(f"| {k} | {per_tag[k]:,} |")

    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"参与 {total:,}；规则 {len(rules)} 条")
    print(f"{'规则':<18}{'命中':>9}{'命中率':>9}   撑起它的短语")
    for label, cnt in hits.most_common():
        top = "、".join(f"{p}×{c}" for p, c in phrases[label].most_common(2))
        flag = "  ← 超30%" if (cnt / total > MAX_RATE and not label.startswith(FACET_EXEMPT)) else ""
        print(f"{label:<18}{cnt:>9,}{cnt / total * 100:>8.2f}%   {top[:60]}{flag}")
    print(f"\n落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
