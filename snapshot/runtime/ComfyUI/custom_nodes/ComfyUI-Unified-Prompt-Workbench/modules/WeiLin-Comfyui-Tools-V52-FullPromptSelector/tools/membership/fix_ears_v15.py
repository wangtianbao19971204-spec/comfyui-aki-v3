"""第 15 轮：把 danbooru `tag_group:ears_tags` 接进归属（耳朵属于身体部件）。

背景：`cat ears` / `fox ears` 之类原本是**零归属**。按复审结论「animal ears 应该是身体部件」，
用 ears_tags 三张清单补齐：
  * Animal ears / Other ears / Number of ears  -> 外貌›身体
  * Objects for the ears（耳环、耳机、耳钉）    -> 服饰›配饰
  * Misc（biting_ear / covering_own_ears ...）  -> 属于动作，本轮不接

用法： python fix_ears_v15.py
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
from rebuild_action_scene_v8 import DB, denoise, load_wiki  # noqa: E402
from rebuild_action_scene_v11 import phrase_pattern  # noqa: E402
import rebuild_action_scene_v11 as _v11  # noqa: E402
from fix_weak_words_v13 import FIXED_PATTERN as BODY_BASE  # noqa: E402
from fix_review_v14 import OUT as V14  # noqa: E402

_v11.MIN_SINGLE_TOKEN = 3

OUT = HERE / "全库_面与主题_v15_20260919.jsonl"

# 这些不是"耳朵本身"，而是装扮/道具
ACCESSORY_WORDS = {
    "fake_animal_ears", "animal_ear_headphones", "bear_ear_headphones",
    "cat_ear_headphones", "rabbit_ear_headphones",
    "ear_piercing", "ear_protection", "earrings", "single_earring",
    "headphones", "object_behind_ear",
}
BODY_SECTIONS = ("Animal ears", "Other ears", "Number of ears")


def main() -> int:
    wiki = load_wiki()
    body_ears, acc_ears = [], []
    for sec in wiki["tag_group:ears_tags"]["sections"]:
        is_body = sec["section"] in BODY_SECTIONS
        is_object = "objects for the ears" in sec["section"].lower()
        if not (is_body or is_object):
            continue
        for t in sec["tags"]:
            if t.startswith("tag_group:"):
                continue
            if is_object or t in ACCESSORY_WORDS:
                acc_ears.append(t)
            else:
                body_ears.append(t)
    body_ears = sorted(set(body_ears))
    acc_ears = sorted(set(acc_ears))

    # 只做「追加」：v14 快照里的既有归属一律保留，这里只补耳朵相关的新成员
    # `fake animal ears` 是发箍不是耳朵本身（v14 已排除过，这里保持一致）
    rx_body = re.compile(r"(?<!fake[ _])" + phrase_pattern(body_ears), re.I)
    rx_acc = re.compile(
        r"(?<![a-z0-9])" + phrase_pattern(acc_ears) + r"|"
        r"(?<![a-z0-9])fake[ _]+animal[ _]+ears(?![a-z0-9])", re.I)

    for label, rx, text, want in (
            ("外貌›身体", rx_body, "cat ears", True),
            ("外貌›身体", rx_body, "pointy ears", True),
            ("外貌›身体", rx_body, "extra ears", True),
            ("外貌›身体", rx_body, "short hair", False),
            ("外貌›身体", rx_body, "fake animal ears", False),
            ("服饰›配饰", rx_acc, "fake animal ears", True),
            ("服饰›配饰", rx_acc, "earrings", True),
            ("服饰›配饰", rx_acc, "headphones", True),
            ("服饰›配饰", rx_acc, "cat ears", False)):
        got = bool(rx.search(text))
        if got != want:
            print(f"自检失败：{label} / {text!r} 期望 {want} 实际 {got}")
            return 1
    print(f"耳朵清单：身体部件 {len(body_ears)} 条，配饰 {len(acc_ears)} 条；自检 8 项全过")

    with sqlite3.connect(str(DB)) as con:
        full = {u: t for u, t in con.execute("select t_uuid, text from tag_tags")}
    rows = [json.loads(line) for line in V14.read_text(encoding="utf-8").splitlines() if line.strip()]

    before, after = Counter(), Counter()
    gained_body = gained_acc = 0
    out = []
    for row in rows:
        body = denoise(full.get(row["id"]) or row.get("text") or "")
        for label, rx, bucket in (("外貌›身体", rx_body, "facets"),
                                  ("服饰›配饰", rx_acc, "themes")):
            vals = list(row.get(bucket, []))
            if label in vals:
                before[label] += 1
            if rx.search(body) and label not in vals:
                vals.append(label)
                if label == "外貌›身体":
                    gained_body += 1
                else:
                    gained_acc += 1
            if label in vals:
                after[label] += 1
            row[bucket] = vals
        out.append(json.dumps(row, ensure_ascii=False))

    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"  外貌›身体 {before['外貌›身体']:,} -> {after['外貌›身体']:,}（新增 {gained_body:,}）")
    print(f"  服饰›配饰 {before['服饰›配饰']:,} -> {after['服饰›配饰']:,}（新增 {gained_acc:,}）")
    print(f"落盘：{OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
