"""第 14 轮：按复审结论调整 4 处归属。

1) `animal ears` 从「角色›种族」**移出** —— 种族靠 dragon/elf/monster 等就够；
   它本身是耳朵，**移入「外貌›身体」（身体部件）**，但 `fake animal ears`（装扮）不算。
2) `cum` 从「成人›前戏」**挪到「成人›特殊」** —— 它是结果不是前戏。
3) `wet clothes` **留在「状态」**（服装状态本来就归这一支），不删。
4) `opened` 不再裸匹配 —— 只有 `opened shirt/clothes/coat/...` 这类服装语境才算，
   原来 opened door / opened eyes / mouth opened 一律不再命中。

所有删词都断言「不产生空分支」（历史两次误伤事故的根因）。
用法： python fix_review_v14.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rebuild_action_scene_v8 import DB, denoise  # noqa: E402
from fix_weak_words_v13 import FIXED_PATTERN as BODY_PATTERN  # noqa: E402

CUR = HERE / "全库_面与主题_v13_20260919.jsonl"
OUT = HERE / "全库_面与主题_v14_20260919.jsonl"
REPORT = HERE / "归属复审修复_v14_20260919.md"
RULES = HERE / "最终规则_v2_20260919.json"


def drop_alt(pattern: str, alt: str) -> str:
    """从 |a|b|c| 形式里删掉一个完整分支，并断言没有留下空分支。"""
    esc = re.escape(alt)
    for cand in (r"\|" + esc + r"(?=\|)",          # 中间分支
                 r"\|" + esc + r"(?=\))",          # 最后一个分支
                 esc + r"\|"):                     # 第一个分支
        new = re.sub(cand, "", pattern)
        if new != pattern:
            break
    for bad in ("||", "(|", "|)"):
        assert bad not in new, f"删 {alt} 后出现空分支（{bad}）：{new[:140]}"
    # 语义断言：删掉的分支必须真的不再独立命中（cumshot 里含 cum 不算）
    assert not re.search(r"(?<![a-z0-9])" + esc + r"(?![a-z0-9])", new, re.I), \
        f"删 {alt} 没生效"
    return new


def build_plan():
    """把 v14 的全部规则改动算出来（模块级可复用，便于别的脚本 import）。"""
    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads(RULES.read_text(encoding="utf-8"))}
    body = BODY_PATTERN + r"|(?:(?<!fake[ _])animal[ _]+ears(?![a-z0-9]))"
    race = drop_alt(raw["角色›种族"], "animal ears")
    fore = drop_alt(raw["成人›前戏"], "cum")
    special = raw["成人›特殊"] + r"|(?<![a-z0-9])(?:cum|cumdrip|cumshot)(?![a-z0-9])"
    # fake animal ears 是发箍类装扮，挂到配饰，免得它变成零归属
    acc = raw["服饰›配饰"] + r"|(?<![a-z0-9])fake[ _]+animal[ _]+ears(?![a-z0-9])"
    half = drop_alt(raw["状态›半脱"], "opened") + (
        r"|(?<![a-z0-9])opened[ _]+(?:shirt|clothes|clothing|coat|jacket|dress|blouse|"
        r"bra|pants|robe|bikini|cardigan|vest|uniform|panties)(?![a-z0-9])")

    return {
        "外貌›身体": body, "角色›种族": race, "成人›前戏": fore,
        "成人›特殊": special, "服饰›配饰": acc, "状态›半脱": half,
    }


PLAN = build_plan()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    FACETS = {"外貌›身体", "状态›半脱"}

    # 自检：改完之后每个开关都得按预期工作
    import re as _re
    PLAN = globals()["PLAN"]
    checks = [
        ("外貌›身体", "fake animal ears", False), ("外貌›身体", "animal ears", True),
        ("外貌›身体", "short hair", False), ("外貌›身体", "breasts", True),
        ("角色›种族", "animal ears", False), ("角色›种族", "dragon", True),
        ("成人›前戏", "cum", False), ("成人›前戏", "fellatio", True),
        ("成人›特殊", "cum", True), ("成人›特殊", "rape", True),
        ("服饰›配饰", "fake animal ears", True), ("服饰›配饰", "gloves", True),
        ("状态›半脱", "opened door", False), ("状态›半脱", "opened shirt", True),
        ("状态›半脱", "wet clothes", True), ("状态›半脱", "torn clothes", True),
        ("状态›半脱", "opened eyes", False),
    ]
    bad = []
    for label, text, want in checks:
        got = bool(re.search(PLAN[label], text, re.I))
        if got != want:
            bad.append(f"{label} / {text!r} 期望 {want} 实际 {got}")
    if bad:
        print("自检不过，未写任何文件：")
        for b in bad:
            print("  ", b)
        return 1
    print(f"自检 {len(checks)} 项全过")

    with sqlite3.connect(str(DB)) as con:
        full = {u: t for u, t in con.execute("select t_uuid, text from tag_tags")}
    snap = [json.loads(line) for line in CUR.read_text(encoding="utf-8").splitlines() if line.strip()]

    before = Counter()
    after = Counter()
    out_lines = []
    for row in snap:
        body_text = denoise(full.get(row["id"]) or row.get("text") or "")
        for label in PLAN:
            bucket = "facets" if label in FACETS else "themes"
            if label in row.get(bucket, []):
                before[label] += 1
            vals = [v for v in row.get(bucket, []) if v != label]
            if re.search(PLAN[label], body_text, re.I):
                vals.append(label)
                after[label] += 1
            row[bucket] = vals
        out_lines.append(json.dumps(row, ensure_ascii=False))

    OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# 归属复审修复（v14）", "", "| 位置 | 改动 | 前 | 后 |", "| --- | --- | --- | --- |"]
    note = {
        "外貌›身体": "新增 animal ears（排除 fake）",
        "角色›种族": "移出 animal ears",
        "成人›前戏": "移出 cum",
        "成人›特殊": "接收 cum",
        "服饰›配饰": "接收 fake animal ears（装扮）",
        "状态›半脱": "保留 wet clothes；opened 限定服装语境",
    }
    for label in PLAN:
        L.append(f"| {label} | {note[label]} | {before[label]:,} | {after[label]:,} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    for label in PLAN:
        print(f"  {label:<10} {before[label]:>7,} -> {after[label]:>7,}   ({note[label]})")
    print(f"落盘：{OUT.name}{'（已写）' if args.apply else '（dry-run）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
