"""第 37 轮：`bow (weapon)` / `bow (music)` 不是「服饰›配饰」。

做法：对挂了 服饰›配饰 的条目，逐个看它的配饰命中点；
若命中点全都是「bow + (weapon)/(music)」，撤除该轴。
用法： python fix_bow_v37.py [--apply]
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402
from fix_boundary_v21 import widen_pattern  # noqa: E402

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
REPORT = HERE / "弓误判修复_v37_20260919.md"
LABEL = "服饰›配饰"
PATTERN = (r"\b(necklace|choker|collar|ribbon|bow|gloves|hat|cap|glasses|earrings|belt|"
           r"bag|pendant|tiara|veil)\b")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    rx = re.compile(widen_pattern(PATTERN), re.I)

    con = sqlite3.connect(str(DB))
    try:
        rows = con.execute("select t_uuid, text from tag_tags").fetchall()
        meta = {}
        for u, b in con.execute("select tag_uuid, data from workbench_tag_meta"):
            try:
                meta[u] = json.loads(b)
            except Exception:
                meta[u] = {}

        drop, samples = [], []
        for u, text in rows:
            d = meta.get(u)
            if d is None or LABEL not in (d.get("themes") or []):
                continue
            body = denoise(text)
            ms = list(rx.finditer(body))
            if not ms:
                continue
            ok = False
            for m in ms:
                after = body[m.end():m.end() + 18]
                if m.group(0).lower() == "bow" and re.match(
                        r"[ _]+[\(\[]?\s*(weapon|music)", after, re.I):
                    continue
                ok = True
                break
            if not ok:
                drop.append(u)
                if len(samples) < 40:
                    samples.append((body[:60], md5(u.encode()).hexdigest()))

        print(f"要撤除 {LABEL}：{len(drop):,}")
        for t, _h in sorted(samples, key=lambda x: x[1])[:14]:
            print("   ", t)
        L = ["# `bow (weapon)` 误判修复（v37）", "", f"- 撤除 {len(drop):,} 条", "",
             "## 样例", ""]
        for t, _h in sorted(samples, key=lambda x: x[1])[:30]:
            L.append(f"- {t}")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print(f"落盘：{REPORT.name}")

        if not args.apply or not drop:
            print("dry-run 或无需改动。")
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_bow_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)
        updates = []
        for u in drop:
            d = dict(meta.get(u) or {})
            d["themes"] = [x for x in (d.get("themes") or []) if x != LABEL]
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
