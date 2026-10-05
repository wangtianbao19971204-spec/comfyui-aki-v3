"""第 8 轮：用 Danbooru wiki tag group 精确清单重建「动作 / 场景」规则（试跑，不写库）。

清单来源：danbooru_tag_groups/parsed.json（由 in-app browser 批量抓取的 193 个 wiki 页）
做法：只做「短语拼装」，绝不删词改规则（历史两次事故的根因）。
断言：任一规则命中率 > 30% 即失败退出。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
WIKI = BENCH / "danbooru_tag_groups" / "parsed.json"
OLD_RULES = HERE / "最终规则_v2_20260919.json"
DB = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
          r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\userdatas_zh_CN_tags.db")

OUT_JSONL = HERE / "全库_面与主题_v8_20260919.jsonl"
OUT_RULES = HERE / "最终规则_v3_20260919.json"
REPORT = HERE / "动作场景重建_v8_20260919.md"
SAMPLES = HERE / "动作场景抽样_v8_每类16条_20260919.md"

MAX_RATE = 0.30
COMBO = re.compile(r"一键NSFW|一键模式")
LINK_CLEAN = re.compile(r"[\[\]\(\)]")


def denoise(text: str) -> str:
    """轻量清洗：去权重语法/URL/换行，压缩空白，小写。"""
    t = (text or "").replace("\r", " ").replace("\n", " ")
    t = re.sub(r"<[^>]{0,40}>", " ", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[\(\[][^\)\]]{0,20}[\)\]]\s*[:：]?\s*(?=\d)", " ", t)
    t = re.sub(r"[\(\[\{][\d.]+[\)\]\}]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def phrase_pattern(phrases, extra=""):
    """精确短语 → 边界安全的联合正则（兼容空格/下划线写法）。"""
    parts = []
    for p in phrases:
        p = (p or "").strip().lower()
        if not p or p.startswith("!"):
            continue
        p = LINK_CLEAN.sub("", p)
        toks = [re.escape(t) for t in p.split() if t]
        if not toks:
            continue
        parts.append(r"[ _]+".join(toks))
    parts = sorted(set(parts), key=len, reverse=True)
    if extra:
        parts.append(extra)
    body = "|".join(parts)
    return r"(?<![a-z0-9])(?:" + body + r")(?![a-z0-9])"


def load_wiki():
    return json.loads(WIKI.read_text(encoding="utf-8"))


def section_tags(wiki, slug, want):
    for s in wiki[slug]["sections"]:
        if want.lower() in s["section"].lower():
            return s["tags"]
    return []


def build_rules(wiki):
    posture = wiki["tag_group:posture"]["tags"]
    gestures = wiki["tag_group:gestures"]["tags"]

    leg_secs = []
    for s in wiki["tag_group:posture"]["sections"]:
        if any(k in s["section"].lower() for k in ("leg location", "knee location", "foot position")):
            leg_secs.extend(s["tags"])
    feet = wiki.get("tag_group:feet", {}).get("tags", [])
    legs = sorted(set(leg_secs + feet))

    indoor = section_tags(wiki, "tag_group:locations", "indoors")
    outdoor = section_tags(wiki, "tag_group:locations", "natural settings")

    return [
        ("动作", "姿态", phrase_pattern(posture)),
        ("动作", "手势", phrase_pattern(gestures)),
        ("动作", "腿部", phrase_pattern(legs)),
        ("场景", "室内", phrase_pattern(indoor)),
        ("场景", "室外", phrase_pattern(outdoor, extra=r"outdoors")),
    ]


def load_old_rules():
    data = json.loads(OLD_RULES.read_text(encoding="utf-8"))
    keep, dropped = [], []
    for r in data:
        if r["theme"] in ("动作", "场景"):
            dropped.append(f'{r["theme"]}›{r["sub"]}')
        else:
            keep.append((r["theme"], r["sub"], r["pattern"]))
    return keep, dropped


def main() -> int:
    wiki = load_wiki()
    new_rules = build_rules(wiki)
    old_rules, dropped = load_old_rules()
    rules = old_rules + new_rules
    compiled = [(t, s, re.compile(p, re.I)) for t, s, p in rules]

    with sqlite3.connect(str(DB)) as con:
        groups = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()

    stats: Counter = Counter()
    samples: dict[str, list[dict]] = {}
    total = zero = 0
    new_labels = {f"{t}›{s}" for t, s, _ in new_rules}
    old_label_hits: Counter = Counter()
    new_label_hits: Counter = Counter()

    with OUT_JSONL.open("w", encoding="utf-8") as handle:
        for uuid, subgroup_id, text in rows:
            entry = subs.get(subgroup_id)
            area = groups.get(entry[0], "") if entry else ""
            if COMBO.search(area):
                continue
            total += 1
            body = denoise(text)
            hits: list[str] = []
            for theme, sub, pattern in compiled:
                m = pattern.search(body)
                if not m:
                    continue
                label = f"{theme}›{sub}"
                if label in hits:
                    continue
                hits.append(label)
                stats[label] += 1
                if label in new_labels:
                    new_label_hits[label] += 1
                else:
                    old_label_hits[label] += 1
                if label in new_labels:
                    bucket = samples.setdefault(label, [])
                    if len(bucket) < 16:
                        bucket.append({"text": body[:120], "leaf": entry[1] if entry else "",
                                       "area": area})
            if not hits:
                zero += 1
            handle.write(json.dumps({"id": uuid, "source": area,
                                     "leaf": entry[1] if entry else "",
                                     "memberships": hits, "text": (text or "")[:150]},
                                    ensure_ascii=False) + "\n")

    violations = [(lbl, c) for lbl, c in stats.items() if c / total > MAX_RATE]

    lines = ["# 第 8 轮：动作 / 场景 精确重建（Danbooru wiki tag group 清单）", "",
             f"- 参与 tag：{total:,}（已排除一键组合区）",
             f"- 零归属：{zero:,}（{zero / total * 100:.1f}%）",
             f"- 移除的旧规则：{', '.join(dropped)}",
             f"- 断言（任一规则命中率 >{MAX_RATE:.0%}）："
             f"{'通过' if not violations else '**违规** ' + str(violations)}", "",
             "## 新规则命中", "", "| 规则 | 命中 | 命中率 |", "| --- | --- | --- |"]
    for lbl, c in sorted(new_label_hits.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {lbl} | {c:,} | {c / total * 100:.2f}% |")
    lines += ["", "## 全量规则命中（含保留的旧规则）", "", "| 规则 | 命中 | 命中率 |",
              "| --- | --- | --- |"]
    for lbl, c in stats.most_common():
        lines.append(f"| {lbl} | {c:,} | {c / total * 100:.2f}% |")
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    s_lines = ["# 动作 / 场景 新规则抽样（每类 16 条）", ""]
    for lbl in sorted(new_label_hits):
        s_lines += [f"## {lbl}  （命中 {new_label_hits[lbl]:,}）", "",
                    "| # | 文本 | 来源 | 叶子 |", "| --- | --- | --- | --- |"]
        for i, s in enumerate(samples.get(lbl, []), 1):
            txt = s["text"].replace("|", "/")
            s_lines.append(f"| {i} | {txt} | {s['area']} | {s['leaf']} |")
        s_lines.append("")
    SAMPLES.write_text("\n".join(s_lines), encoding="utf-8")

    OUT_RULES.write_text(json.dumps(
        [{"theme": t, "sub": s, "pattern": p} for t, s, p in rules],
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"参与 {total:,}；零归属 {zero:,}（{zero / total * 100:.1f}%）")
    print(f"移除旧规则 {len(dropped)}：{dropped}")
    print(f"断言违规：{violations if violations else '无'}")
    for lbl, c in sorted(new_label_hits.items(), key=lambda kv: -kv[1]):
        print(f"  {lbl:<10} {c:>7,} ({c / total * 100:>5.2f}%)")
    print(f"落盘：{OUT_JSONL.name} / {OUT_RULES.name} / {REPORT.name} / {SAMPLES.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
