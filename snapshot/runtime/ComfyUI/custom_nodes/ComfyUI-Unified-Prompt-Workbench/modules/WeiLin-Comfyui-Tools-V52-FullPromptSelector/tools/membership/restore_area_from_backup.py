"""从删除前的备份库里，把某个区域的条目原样恢复回线上库。

恢复内容：tag_tags 行 + 对应的 workbench_tag_meta 行。
meta 插入会触发 workbench_tag_meta 的触发器（按 folder_ids 重建成员行），
所以目录归属会自动跟着回来。

用法：
  python restore_area_from_backup.py --area 画风组词典 \
      --backup <backup_dir>/userdatas_zh_CN_tags.db [--apply]
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DB = ROOT / "userdatas_zh_CN_tags.db"


def pick_rows(bcon, area):
    gdb = {r[0]: r[1] for r in bcon.execute("select id_index, name from tag_groups")}
    subs = {r[0]: (r[1], r[2]) for r in bcon.execute(
        "select id_index, group_id, name from tag_subgroups")}
    ids = [s for s, (g, _n) in subs.items() if gdb.get(g) == area]
    marks = ",".join("?" * len(ids))
    tags = bcon.execute(
        f"select id_index, subgroup_id, text, desc, color, create_time, t_uuid, g_uuid "
        f"from tag_tags where subgroup_id in ({marks})", ids).fetchall()
    uuids = [r[6] for r in tags]
    umarks = ",".join("?" * len(uuids))
    metas = bcon.execute(
        f"select tag_uuid, data from workbench_tag_meta where tag_uuid in ({umarks})",
        uuids).fetchall()
    return ids, tags, metas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", required=True)
    ap.add_argument("--backup", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    backup = Path(args.backup)
    if not backup.exists():
        print("备份库不存在：", backup)
        return 1

    bcon = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        ids, tags, metas = pick_rows(bcon, args.area)
    finally:
        bcon.close()
    print(f"备份里「{args.area}」：叶子 {len(ids)} 个，条目 {len(tags):,}，带 meta {len(metas):,}")
    if not tags:
        return 1
    if not args.apply:
        print("dry-run，未改动。加 --apply 执行。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = ROOT / "prompt_selector_data_backups" / f"restore_{stamp}"
    safe.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
    print(f"写前已备份：{safe}")

    con = sqlite3.connect(str(DB))
    try:
        con.executemany(
            "insert or replace into tag_tags "
            "(id_index, subgroup_id, text, desc, color, create_time, t_uuid, g_uuid) "
            "values (?,?,?,?,?,?,?,?)", tags)
        con.executemany(
            "insert or replace into workbench_tag_meta (tag_uuid, data) values (?,?)", metas)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.execute("update workbench_tag_text_revision set value = value + 1 where id = 1")
        con.commit()
        got = con.execute(
            "select count(*) from tag_tags where subgroup_id in (%s)"
            % ",".join("?" * len(ids)), ids).fetchone()[0]
        gm = con.execute(
            "select count(*) from workbench_tag_meta where tag_uuid in (%s)"
            % ",".join("?" * len([r[6] for r in tags])), [r[6] for r in tags]).fetchone()[0]
        total = con.execute("select count(*) from tag_tags").fetchone()[0]
        print(f"恢复后：该区域 {got:,} 条；带 meta {gm:,}；全库 tag {total:,}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
