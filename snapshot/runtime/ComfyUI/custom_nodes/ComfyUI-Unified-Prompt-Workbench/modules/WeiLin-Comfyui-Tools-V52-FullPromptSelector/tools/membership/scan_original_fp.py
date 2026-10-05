"""第五轮：查「原始规则」自己的误匹配（不是边界放宽引入的那批）。

典型：`witch hat` 被算成 角色›职业 —— 因为 `\\bwitch\\b` 在空格写法下本来就能命中。
做法：对每个挂了某轴的条目，看命中词**后面紧跟的词**是不是"否定后缀"
（如职业词后跟 hat/dress/office；种族词后跟 body feature 但主体不是种族等）。

用法： python scan_original_fp.py
输出：原始规则误匹配_20260919.md
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
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
from rebuild_action_scene_v8 import DB, COMBO, denoise, load_wiki  # noqa: E402
import rebuild_action_scene_v12 as V12  # noqa: E402
from fix_review_v14 import PLAN as PLAN14  # noqa: E402
from fix_boundary_v21 import widen_pattern  # noqa: E402

REPORT = HERE / "原始规则误匹配_20260919.md"
SAMPLE = 25

# 轴 → 命中词后面**不该跟**的词（跟了就说明它是在修饰别的东西）
REJECT_AFTER = {
    "角色›职业": ("hat", "cap", "dress", "outfit", "uniform", "costume", "clothes",
                "room", "office", "cafe", "shop", "gloves", "sleeves", "shoes",
                "boots", "headdress", "headband", "apron", "mask", "wings"),
    "角色›种族": ("hat", "dress", "outfit", "costume", "clothes", "print", "pattern",
                "costume", "slayer", "ears", "horns", "wings", "tail", "skin"),
    "道具›器物": ("face", "hair", "operator", "girl", "boy", "on", "in", "with"),
}
PAREN = re.compile(r"\([^()]*\)")


def main() -> int:
    raw = {f'{r["theme"]}›{r["sub"]}': r["pattern"] for r in
           json.loads((HERE / "最终规则_v2_20260919.json").read_text(encoding="utf-8"))}
    for theme, sub, pattern, _n in V12.build_rules(load_wiki()):
        raw[f"{theme}›{sub}"] = pattern
    raw.update(PLAN14)
    comp = {k: re.compile(widen_pattern(v) if r"\b" in v else v, re.I)
            for k, v in raw.items()}

    with sqlite3.connect(str(DB)) as con:
        gdb = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
        meta = {}
        for u, b in con.execute("select tag_uuid, data from workbench_tag_meta"):
            try:
                meta[u] = json.loads(b)
            except Exception:
                meta[u] = {}

    hits = defaultdict(list)
    per_label = Counter()
    for u, s, text in rows:
        d = meta.get(u)
        if d is None:
            continue
        body = denoise(text)
        nop = PAREN.sub(" ", body)
        for label, bads in REJECT_AFTER.items():
            if label not in (d.get("themes") or []):
                continue
            rx = comp.get(label)
            if not rx:
                continue
            for m in rx.finditer(nop):
                nxt = re.match(r"[ _]+([a-z0-9']+)", nop[m.end():m.end() + 24])
                if nxt and nxt.group(1) in bads:
                    per_label[label] += 1
                    if len(hits[label]) < 400:
                        hits[label].append((m.group(0), nxt.group(1), body[:70],
                                            md5(u.encode()).hexdigest()))
                    break

    L = ["# 原始规则误匹配扫描（第五轮）", "", "| 轴 | 可疑条数 |", "| --- | --- |"]
    for k, v in per_label.most_common():
        L.append(f"| {k} | {v:,} |")
    for label, items in hits.items():
        L += ["", f"## {label}（{per_label[label]} 条）", "",
              "| 命中词 | 后接词 | 文本 |", "| --- | --- | --- |"]
        for hit, nxt, t, _h in sorted(items, key=lambda x: x[3])[:SAMPLE]:
            L.append(f"| `{hit}` | `{nxt}` | {t.replace('|','/')} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print("可疑误匹配（原始规则）：")
    for k, v in per_label.most_common():
        print(f"   {k}: {v}")
    for label, items in hits.items():
        print(f"--- {label} 样例 ---")
        for hit, nxt, t, _h in sorted(items, key=lambda x: x[3])[:10]:
            print(f"   `{hit}` + `{nxt}`  ← {t[:54]}")
    print(f"落盘：{REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
