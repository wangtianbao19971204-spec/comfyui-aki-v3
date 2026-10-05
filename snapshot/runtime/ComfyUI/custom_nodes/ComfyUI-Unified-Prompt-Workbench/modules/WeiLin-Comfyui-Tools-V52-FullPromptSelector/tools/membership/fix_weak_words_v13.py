"""第 13 轮：修「外貌›身体」的弱词误伤（只动这一条面规则）。

审计证据（probe_phrase.py 抽样）：
  short    → 13,819 条里绝大多数是 short hair / short skirt / short shorts / short sleeves
  neck     → 1,911 条里绝大多数是 neck ribbon / noose around neck / hands on another's neck
  shoulder → 3,092 条里绝大多数是 off shoulder / shoulder armor / bare shoulders / hair over shoulder
  butt     → 242 条里有 butt plug / butt crack

处理：从「外貌›身体」里删掉 short / neck / shoulder，并给 butt 加负向断言（butt plug 是道具）。
其余规则、其余主题/面一律保持快照原样（画风›画师/画质、角色›原作 是后处理过的，绝不能重算）。

用法： python fix_weak_words_v13.py [--apply]
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
from rebuild_action_scene_v8 import DB, COMBO, denoise, load_wiki  # noqa: E402
from rebuild_action_scene_v11 import keep_phrase, phrase_pattern  # noqa: E402
import rebuild_action_scene_v11 as _v11  # noqa: E402

# 4 字符下限是为了杀掉单字母 `v`；这条规则里没有那种词，放宽到 3 才能保住 fat / abs
_v11.MIN_SINGLE_TOKEN = 3

CUR = HERE / "全库_面与主题_v12_20260919.jsonl"
OUT = HERE / "全库_面与主题_v13_20260919.jsonl"
REPORT = HERE / "外貌身体弱词修复_v13_20260919.md"

LABEL = "外貌›身体"
DROP = ("short", "neck", "shoulder")


def _build_fixed_pattern() -> str:
    old = json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))
    pat_old = next(r["pattern"] for r in old if f'{r["theme"]}›{r["sub"]}' == LABEL)
    words = [w.strip() for w in re.findall(r"[a-z][a-z ]*", pat_old) if w.strip()]
    kept = [w for w in words if w not in DROP]
    return phrase_pattern(kept) + r"(?![ _]+plug\b)"


FIXED_PATTERN = _build_fixed_pattern()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    pat_new = FIXED_PATTERN
    rx_new = re.compile(pat_new, re.I)

    with sqlite3.connect(str(DB)) as con:
        groups = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
    full = {u: t for u, _s, t in rows}

    snap = [json.loads(line) for line in CUR.read_text(encoding="utf-8").splitlines() if line.strip()]

    before = after = 0
    lost, kept_tags = [], 0
    out_lines = []
    for row in snap:
        body = denoise(full.get(row["id"]) or row.get("text") or "")
        was = LABEL in row.get("facets", [])
        now = bool(rx_new.search(body))
        if was:
            before += 1
        if now:
            after += 1
        facets = [f for f in row.get("facets", []) if f != LABEL]
        if now:
            facets.append(LABEL)
            kept_tags += 1
        if was and not now:
            lost.append(body[:90])
        out = dict(row)
        out["facets"] = facets
        out_lines.append(json.dumps(out, ensure_ascii=False))

    OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = [f"# 外貌›身体 弱词修复（v13）", "",
         f"- 删除短语：{'、'.join('`%s`' % d for d in DROP)}",
         f"- 追加断言：`butt` 后面不是 `plug`（butt plug 是道具）",
         f"- 修复前：{before:,} → 修复后：{after:,}（净减 {before - after:,}）", "",
         "## 被移出的样例（原来靠 short/neck/shoulder 才进来的）", ""]
    for t in lost[:40]:
        L.append(f"- {t}")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"{LABEL}：修复前 {before:,} → 修复后 {after:,}（净减 {before - after:,}）")
    print(f"抽样看被移出的 10 条：")
    for t in lost[:10]:
        print("   ", t)
    print(f"落盘：{OUT.name}（{'已写' if args.apply else 'dry-run'}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
