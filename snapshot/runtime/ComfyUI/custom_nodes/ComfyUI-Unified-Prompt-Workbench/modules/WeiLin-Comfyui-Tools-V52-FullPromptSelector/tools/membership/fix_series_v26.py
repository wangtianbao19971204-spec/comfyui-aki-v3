"""第 26 轮：修正 series 取值（v22/v24 取错了括号）。

bug：官方角色名常有两层括号
    `okita_souji_(swimsuit_assassin)_(fate/grand_order)`
正确作品是**最后一个**括号 = fate/grand_order；
v22 取的是第一个括号，于是把「swimsuit assassin / third ascension」当成了作品。

修正规则（按优先级，每一步都要能对上官方作品表才算数）：
  1) 条目逗号后的尾巴 → 对上官方作品
  2) 官方角色名的**最后一个**括号 → 对上官方作品（允许把下划线换成空格再比）
  3) 倒数第二个括号（个别名字作品在前面）
  4) 都对不上 → 清空，不硬塞

用法： python fix_series_v26.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
TABLE = BENCH / "danbooru_tags_api" / "tagtable.jsonl"
ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DB = ROOT / "userdatas_zh_CN_tags.db"
REPORT = HERE / "series修正_v26_20260919.md"
COMBO = re.compile(r"一键NSFW|一键模式")
SAMPLE = 30

# 少数"是作品但没直接对上官方名"的手工映射（键 = norm_key 后的旧值）
MANUAL = {
    "fate": "fate_(series)",
    "nikke": "goddess_of_victory:_nikke",
    "neptunia": "hyperdimension_neptunia",
    "mega man": "mega_man_(series)",
}


def norm_key(s: str) -> str:
    """用于和官方作品表比对的键：小写、下划线/空格/连字符统一成空格。"""
    s = s.strip().lower().replace("\\(", "(").replace("\\)", ")")
    s = re.sub(r"[_\-–—/]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ,.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    copies = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["category"] == 3:
            copies[norm_key(row["name"])] = row["name"]

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

        changes = []
        by_src = Counter()
        samples = []
        for u, s, text in rows:
            e = subs.get(s)
            area = gdb.get(e[0], "") if e else ""
            doc = meta.get(u)
            if COMBO.search(area) or doc is None:
                continue
            old = (doc.get("series") or "").strip()
            t = (text or "").strip()
            if not t:
                continue
            head = re.split(r"[,;]", t)[0].strip()
            tail = t[len(head):].strip(" ,;")
            # 官方角色名（含括号）从 tagtable 里拿不到，就用条目里的头段直接找作品
            new, src = "", ""
            if old and norm_key(old) in MANUAL:
                new, src = MANUAL[norm_key(old)], "手工映射到官方作品"
            # 0) 旧值本身就是合法官方作品 → 只做拼写规范化，绝不乱清
            elif old and norm_key(old) in copies:
                canon_old = copies[norm_key(old)]
                if canon_old != old:
                    new, src = canon_old, "旧值合法，仅规范化拼写"
                else:
                    continue
            if not new and tail:
                v = copies.get(norm_key(tail))
                if v:
                    new, src = v, "去掉尾巴对上官方作品"
            if not new:
                # 从条目自身找作品：常见写法 `角色 (作品)` / `角色 (形态) (作品)`
                parens = re.findall(r"\(([^()]+)\)", head)
                for cand in reversed(parens):          # 先看最后一个括号
                    v = copies.get(norm_key(cand))
                    if v:
                        new, src = v, "角色名的最后一个括号"
                        break
                if not new and len(parens) >= 2:
                    v = copies.get(norm_key(parens[-2]))
                    if v:
                        new, src = v, "角色名的倒数第二个括号"
            if new == old:
                continue
            if new:
                by_src[src] += 1
            else:
                by_src["清空（推不出官方作品）"] += 1
            changes.append((u, old, new))
            if len(samples) < SAMPLE * 4:
                samples.append((t[:52], old, new, src, md5(u.encode()).hexdigest()))

        print(f"需要修正 series 的条目：{len(changes):,}")
        for k, v in by_src.most_common():
            print(f"   {k:<22} {v:>6,}")
        print()
        print("样例（原 series → 新 series）：")
        for t, old, new, src, _h in sorted(samples, key=lambda x: x[4])[:16]:
            print(f"   {t[:40]:<42} | {old[:20]:<22} → {new or '(清空)'}")

        L = ["# series 修正（v26）", "",
             f"- 修正 {len(changes):,} 条", "",
             "| 来源 | 条数 |", "| --- | --- |"]
        for k, v in by_src.most_common():
            L.append(f"| {k} | {v:,} |")
        L += ["", "## 样例", "", "| 文本 | 原 series | 新 series | 依据 |", "| --- | --- | --- | --- |"]
        for t, old, new, src, _h in sorted(samples, key=lambda x: x[4])[:SAMPLE * 2]:
            L.append(f"| {t} | {old} | {new or '（清空）'} | {src} |")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print(f"落盘：{REPORT.name}")

        if not args.apply:
            print("dry-run，未改动。加 --apply 执行。")
            return 0
        if not changes:
            return 0

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_series_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)

        updates = []
        for u, _old, new in changes:
            d = dict(meta.get(u) or {})
            if new:
                d["series"] = new
            else:
                d.pop("series", None)
            updates.append((u, json.dumps(d, ensure_ascii=False)))
        con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) "
                        "values (?,?)", updates)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.commit()
        print(f"已修正 {len(updates):,} 条")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
