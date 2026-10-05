"""第 32 轮：用「挖掉官方名字」的办法收严 角色›种族 / 道具›器物。

残留误判都是「作品名 / 角色名里含该轴的关键词」：
  角色›种族：dragon ball、rosario+vampire、monster musume
  道具›器物：sword art online、fake phone screenshot
做法同 v31：先从官方 character/copyright 表挑出**含该轴关键词**的名字，
在条目文本里整体挖空，再跑该轴正则；挖空后不再命中 → 撤除该轴。

用法： python fix_name_axis_v32.py [--apply]
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
TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402
from fix_boundary_v21 import widen_pattern  # noqa: E402

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
REPORT = HERE / "名字挖空收严_v32_20260919.md"
SAMPLE = 30

AXES = {
    "角色›种族": ["dragon", "elf", "demon", "angel", "catgirl", "fox girl", "beast",
               "monster", "robot", "mecha", "slime", "vampire", "dragonborn",
               "kemono", "dog girl", "animal ears"],
    "道具›器物": ["book", "cup", "glass", "bottle", "food", "cake", "fruit",
               "camera", "phone", "umbrella", "balloon", "plant", "knife", "gun",
               "sword", "staff", "box", "bag", "doll", "teddy bear"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    off_names = []
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["category"] in (3, 4):
            off_names.append(r["name"].lower().replace("_", " ").strip())
    off_names = sorted(set(off_names), key=len, reverse=True)
    print(f"官方名字：{len(off_names):,}")

    plans = {}
    for label, words in AXES.items():
        rx = re.compile(widen_pattern(r"\b(" + "|".join(words) + r")\b"), re.I)
        picked = [n for n in off_names if any(w in n for w in words)]
        res = [re.compile(r"(?<![a-z0-9])" + re.escape(n).replace(r"\ ", "[ _]+")
                          + r"(?![a-z0-9])") for n in picked]
        plans[label] = (rx, res)
        print(f"  {label}：含关键词的官方名字 {len(picked):,} 个")

    con = sqlite3.connect(str(DB))
    try:
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

        drops = {}
        samples = {}
        for label, (rx, res) in plans.items():
            drop, samp = [], []
            for u, s, text in rows:
                e = subs.get(s)
                area = gdb.get(e[0], "") if e else ""
                doc = meta.get(u)
                if COMBO.search(area) or doc is None:
                    continue
                if label not in (doc.get("themes") or []):
                    continue
                body = denoise(text)
                if not rx.search(body):
                    continue                  # 来自清单，别动
                cut = body
                for nre in res:
                    cut = nre.sub(" ", cut)
                if not rx.search(cut):
                    drop.append(u)
                    if len(samp) < SAMPLE * 3:
                        m = rx.search(body)
                        samp.append((body[:62], m.group(0) if m else "",
                                     md5(u.encode()).hexdigest()))
            drops[label] = drop
            samples[label] = samp
            print(f"{label}：要撤除 {len(drop):,}")
            for t, hit, _h in sorted(samp, key=lambda x: x[2])[:12]:
                print(f"   {t[:50]:<52} ← {hit}")

        L = ["# 名字挖空收严（v32）", ""]
        for label, drop in drops.items():
            L += [f"## {label}（撤除 {len(drop):,}）", "", "| 文本 | 命中词 |", "| --- | --- |"]
            for t, hit, _h in sorted(samples[label], key=lambda x: x[2])[:SAMPLE * 2]:
                L.append(f"| {t} | `{hit}` |")
            L.append("")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print(f"落盘：{REPORT.name}")

        if not args.apply:
            print("dry-run，未改动。加 --apply 执行。")
            return 0
        if not any(drops.values()):
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_name_axis_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)
        by_uuid = {}
        for label, drop in drops.items():
            for u in drop:
                by_uuid.setdefault(u, []).append(label)
        updates = []
        for u, labels in by_uuid.items():
            d = dict(meta.get(u) or {})
            d["themes"] = [x for x in (d.get("themes") or []) if x not in labels]
            updates.append((u, json.dumps(d, ensure_ascii=False)))
        con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) "
                        "values (?,?)", updates)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.commit()
        print(f"已处理 {len(updates):,} 条记录")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
