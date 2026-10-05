"""第 12 轮（写库版）：用 danbooru 精确清单替换「动作 / 场景」主题归属。

与 v11 试跑的差别（对齐库里的既有口径）：
  1. 动作/场景在库里属于 **themes**（不是 facets），子类名沿用「姿态 / 手部 / 腿部」与
     「室内 / 室外 / 背景」，不新建、不改名，避免 UI 里的分类凭空消失。
  2. 手部 = danbooru `tag_group:hands`（104 条手部位置）+ `tag_group:gestures`（130 条手势）。
  3. 场景›背景 保持原规则不动（当初没被判定为问题）。
输出：与现有库快照同结构的 jsonl（id/source/leaf/themes/facets/text），可直接喂
      writeback_memberships.py。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rebuild_action_scene_v11 import (  # noqa: E402
    AMBIGUOUS_PLACES, DB, denoise, keep_phrase, load_wiki, phrase_pattern, scene_body,
    section_tags,
)
import rebuild_action_scene_v11 as _v11  # noqa: E402

# 抽样里抓到的补丁：`flying sweatdrops` 这类「动作词修饰效果线」也判否
_v11.OBJECT_SUFFIX = _v11.OBJECT_SUFFIX + ("sweatdrops", "sweatdrop", "tears", "teardrops",
                                           "sweat spray", "speed lines")

BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
CUR = HERE / "全库_面与主题_20260919.jsonl"          # 当前库里的归属快照
OUT = HERE / "全库_面与主题_v12_20260919.jsonl"       # 写库用
REPORT = HERE / "动作场景重建_v12_写库版_20260919.md"
SAMPLES = HERE / "动作场景抽样_v12_每类32条_20260919.md"

OLD_ACTION_SCENE = ("动作›姿态", "动作›手部", "动作›腿部", "场景›室内", "场景›室外")
KEEP_BACKGROUND = "场景›背景"
MAX_RATE = 0.30
SAMPLE_PER_CLASS = 32
FACET_EXEMPT = ("人物数量", "外貌")

# danbooru 的 posture 页把「视线」也列进去了，但那不是姿态（会命中海量 looking at viewer）
EXTRA_WEAK = {"looking at viewer", "looking to the side", "looking afar"}


def keep2(p: str) -> bool:
    s = (p or "").strip().lower().replace("_", " ")
    if s in EXTRA_WEAK:
        return False
    if s.startswith("list of "):
        return False
    return keep_phrase(p)


def prep(lst):
    return [p for p in lst if keep2(p)]


def build_rules(wiki):
    posture = prep(wiki["tag_group:posture"]["tags"])
    gestures = prep(wiki["tag_group:gestures"]["tags"])
    hands = prep(wiki["tag_group:hands"]["tags"])

    legs = []
    for s in wiki["tag_group:posture"]["sections"]:
        if any(k in s["section"].lower()
               for k in ("leg location", "knee location", "foot position")):
            legs.extend(s["tags"])
    legs = prep(sorted(set(legs)))

    indoor = [t for t in section_tags(wiki, "tag_group:locations", "indoors")
              if t not in AMBIGUOUS_PLACES]
    outdoor = [t for t in section_tags(wiki, "tag_group:locations", "natural settings")
               if t not in AMBIGUOUS_PLACES]
    hand_all = prep(sorted({t for t in (hands + gestures)}))

    return [
        ("动作", "姿态", phrase_pattern(posture), len([p for p in posture if keep_phrase(p)])),
        ("动作", "手部", phrase_pattern(hand_all),
         len([p for p in hand_all if keep_phrase(p)])),
        ("动作", "腿部", phrase_pattern(legs), len([p for p in legs if keep_phrase(p)])),
        ("场景", "室内", phrase_pattern(indoor), len(indoor)),
        ("场景", "室外", phrase_pattern(outdoor, extra=r"outdoors"), len(outdoor) + 1),
    ]


def rank(uid: str) -> str:
    from hashlib import md5
    return md5(uid.encode("utf-8", "ignore")).hexdigest()


def main() -> int:
    wiki = load_wiki()
    new_rules = build_rules(wiki)
    compiled = [(t, s, re.compile(p, re.I), t == "场景") for t, s, p, _n in new_rules]
    labels = [f"{t}›{s}" for t, s, _p, _n in new_rules]

    rows = [json.loads(line) for line in CUR.read_text(encoding="utf-8").splitlines() if line.strip()]
    # 快照里的 text 被截断到 150 字，匹配必须用库里的全文
    with sqlite3.connect(str(DB)) as con:
        full_text = {u: t for u, t in con.execute("select t_uuid, text from tag_tags")}
    stats: Counter = Counter()
    samples: dict[str, list[dict]] = {}
    changed = added = removed = 0
    out_lines = []

    for row in rows:
        body = denoise(full_text.get(row["id"]) or row.get("text") or "")
        fbody = scene_body(body)
        hits = []
        for (theme, sub, pattern, uses_scene), label in zip(compiled, labels):
            m = pattern.search(fbody if uses_scene else body)
            if m:
                hits.append(label)
                stats[label] += 1
                bucket = samples.setdefault(label, [])
                bucket.append({"key": rank(row["id"]), "text": body[:120],
                               "hit": m.group(0), "leaf": row.get("leaf", ""),
                               "area": row.get("source", "")})
                bucket.sort(key=lambda x: x["key"])
                del bucket[SAMPLE_PER_CLASS:]

        old_themes = [t for t in row.get("themes", []) if t not in OLD_ACTION_SCENE]
        new_themes = old_themes + [h for h in hits if h not in old_themes]
        if new_themes != row.get("themes", []):
            changed += 1
        added += len([h for h in hits if h not in row.get("themes", [])])
        removed += len([t for t in row.get("themes", []) if t in OLD_ACTION_SCENE
                        and t not in hits])
        out = dict(row)
        out["themes"] = new_themes
        out_lines.append(json.dumps(out, ensure_ascii=False))

    OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    total = len(rows)
    final = Counter()
    for line in out_lines:
        for t in json.loads(line)["themes"]:
            final[t] += 1
    violations = [(l, c) for l, c in stats.items()
                  if c / total > MAX_RATE and not l.startswith(FACET_EXEMPT)]

    L = ["# 动作 / 场景 精确重建 · v12 写库版", "",
         f"- 参与 tag：{total:,}（沿用当前库快照）",
         f"- 变更行：{changed:,}；新增归属：{added:,}；移除旧归属：{removed:,}",
         f"- 改写规则：{'、'.join(OLD_ACTION_SCENE)}（{KEEP_BACKGROUND} 保持原样）",
         f"- 命中率断言（≤{MAX_RATE:.0%}）：{'通过' if not violations else '**违规** ' + str(violations)}",
         "", "## 新规则", "", "| 规则 | 短语数 | 命中 | 命中率 |", "| --- | --- | --- | --- |"]
    for t, s, _p, n in new_rules:
        lbl = f"{t}›{s}"
        L.append(f"| {lbl} | {n} | {stats[lbl]:,} | {stats[lbl] / total * 100:.2f}% |")
    L += ["", "## 写库后主题分布（前后对比）", "",
          "| 主题 | 写库前 | 写库后 |", "| --- | --- | --- |"]
    before = Counter()
    for row in rows:
        for t in row.get("themes", []):
            before[t] += 1
    for lbl in sorted(set(before) | set(final), key=lambda k: -final.get(k, 0)):
        b, a = before.get(lbl, 0), final.get(lbl, 0)
        mark = " **← 本次改写**" if lbl in labels else ""
        L.append(f"| {lbl}{mark} | {b:,} | {a:,} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    S = [f"# 动作 / 场景 抽样（每类 {SAMPLE_PER_CLASS} 条，按 id 哈希随机）", ""]
    for lbl in labels:
        S += [f"## {lbl}（命中 {stats[lbl]:,}）", "",
              "| # | 文本 | 命中短语 | 来源 | 叶子 |", "| --- | --- | --- | --- | --- |"]
        for i, x in enumerate(samples.get(lbl, []), 1):
            S.append(f"| {i} | {x['text'].replace('|', '/')} | `{x['hit']}` | "
                     f"{x['area']} | {x['leaf']} |")
        S.append("")
    SAMPLES.write_text("\n".join(S), encoding="utf-8")

    print(f"参与 {total:,}；变更 {changed:,} 行；新增 {added:,}；移除 {removed:,}")
    print(f"断言违规：{violations if violations else '无'}")
    for lbl in labels:
        print(f"  {lbl:<8} 命中 {stats[lbl]:>7,} ({stats[lbl] / total * 100:>5.2f}%)  "
              f"写库前 {before.get(lbl, 0):>7,} -> 写库后 {final.get(lbl, 0):>7,}")
    print(f"落盘：{OUT.name} / {REPORT.name} / {SAMPLES.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
