"""第 36 轮：收严 v35 新轴的三处误判。

1) 生物›传说：legendary_creatures 的「Miscellaneous」段是相关词（extra_arms / giantess /
   monster_girl），不是传说生物 → 去掉该段
2) 画面›氛围：subjective 里的 `color` / `thick` 这类弱词会命中「color contact lenses」
   「thick outline」→ 剔除弱词
3) 生物轴：补 `dildo` 到修饰对象判否（dragon_dildo）

做法：按收严后的规则重算这三类，与现有归属比对，只删不再命中的。
用法： python fix_new_axes_v36.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402
from rebuild_action_scene_v11 import phrase_pattern  # noqa: E402
import rebuild_action_scene_v11 as V11  # noqa: E402
import rebuild_action_scene_v12 as V12  # noqa: E402
from fill_new_axes_v35 import pick, OBJECTY  # noqa: E402

V11.MIN_SINGLE_TOKEN = 3
ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
REPORT = HERE / "新轴收严_v36_20260919.md"
SAMPLE = 25
WEAK_SUBJECTIVE = ("color", "colored", "colorful", "thick", "thin", "simple", "complex",
                   "detailed", "unique", "weird", "strange", "awesome", "cool",
                   "wild", "extreme", "heavy", "light", "sharp", "soft")
GUARD = tuple(sorted(set(OBJECTY) | {"dildo", "print", "pattern", "texture"}))


def strict_pattern(wiki, label):
    if label == "生物›传说":
        ph = pick(wiki, "tag_group:legendary_creatures",
                  ("type", "culture-specific"), ())
    elif label == "画面›氛围":
        ph = [t for t in pick(wiki, "tag_group:subjective", None, ("exceptions",))
              if t not in WEAK_SUBJECTIVE]
    else:
        ph = []
    return phrase_pattern(V12.prep(sorted(set(ph))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    wiki = json.loads((BENCH / "danbooru_tag_groups" / "parsed.json").read_text(encoding="utf-8"))

    targets = {}
    for label in ("生物›传说", "画面›氛围"):
        targets[label] = re.compile(strict_pattern(wiki, label), re.I)
    # 生物三轴统一加 dildo 判否
    bio = {}
    for label, specs in (("生物›动物", [("cats", ("main", "misc", "breeds", "colors",
                                                "markings", "feline relatives", "cats do"), ()),
                                      ("dogs", ("main", "misc", "breeds", "colors",
                                                "markings", "dogs do"), ()),
                                      ("birds", ("main", "misc", "breeds", "colors",
                                                 "birds do"), ())]),
                         ("生物›植物", [("flowers", None, ("see also",))]),
                         ("生物›传说", [("legendary_creatures", ("type", "culture-specific"), ())])):
        ph = []
        for slug, inc, exc in specs:
            key = f"tag_group:{slug}"
            if key in wiki:
                ph += pick(wiki, key, inc, exc)
        bio[label] = re.compile(phrase_pattern(V12.prep(sorted(set(ph)))), re.I)

    con = sqlite3.connect(str(DB))
    try:
        rows = con.execute("select t_uuid, text from tag_tags").fetchall()
        meta = {}
        for u, b in con.execute("select tag_uuid, data from workbench_tag_meta"):
            try:
                meta[u] = json.loads(b)
            except Exception:
                meta[u] = {}

        drop = []
        samples = []
        for u, text in rows:
            d = meta.get(u)
            if d is None:
                continue
            th = d.get("themes") or []
            body = denoise(text)
            bad = []
            for label, rx in targets.items():
                if label in th and not rx.search(body):
                    bad.append(label)
            for label, rx in bio.items():
                if label not in th:
                    continue
                ok = False
                for m in rx.finditer(body):
                    nxt = re.match(r"[ _]+([a-z0-9']+)", body[m.end():m.end() + 20])
                    prev = re.search(r"([a-z0-9']+)[ _]+$", body[max(0, m.start() - 24):m.start()])
                    if nxt and nxt.group(1) in GUARD:
                        continue
                    if prev and prev.group(1) in ("holding", "stuffed", "plush", "toy", "fake"):
                        continue
                    ok = True
                    break
                if not ok:
                    bad.append(label)
            if bad:
                drop.append((u, bad))
                if len(samples) < SAMPLE * 3:
                    samples.append((body[:58], "、".join(bad), md5(u.encode()).hexdigest()))

        cnt = {}
        for _u, bad in drop:
            for b in bad:
                cnt[b] = cnt.get(b, 0) + 1
        print(f"要撤除：{len(drop):,} 条记录")
        for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
            print(f"   {k}: {v}")
        for t, b, _h in sorted(samples, key=lambda x: x[2])[:12]:
            print(f"   [{b}] {t}")

        L = ["# 新轴收严（v36）", "", f"- 撤除 {len(drop):,} 条记录", ""]
        for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
            L.append(f"- {k}: {v}")
        L += ["", "## 样例", "", "| 文本 | 撤除的轴 |", "| --- | --- |"]
        for t, b, _h in sorted(samples, key=lambda x: x[2])[:SAMPLE]:
            L.append(f"| {t} | {b} |")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print(f"落盘：{REPORT.name}")

        if not args.apply or not drop:
            print("dry-run 或无需改动。")
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_newaxes_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)
        updates = []
        for u, bad in drop:
            d = dict(meta.get(u) or {})
            d["themes"] = [x for x in (d.get("themes") or []) if x not in bad]
            updates.append((u, json.dumps(d, ensure_ascii=False)))
        con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) "
                        "values (?,?)", updates)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.commit()
        print(f"已处理 {len(updates):,} 条")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
