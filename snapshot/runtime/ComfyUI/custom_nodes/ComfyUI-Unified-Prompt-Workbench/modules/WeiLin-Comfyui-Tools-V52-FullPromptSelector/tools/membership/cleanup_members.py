"""清理成员表的「原生位置」冗余行：以 meta.folder_ids 为唯一真源。

依据（prompt_selector/tag_library.py）：folder_ids 是唯一真源，成员表是它的派生索引，
目录筛选查的就是成员表；UI 每次改标签归属都会把该 tag 的成员行删掉、按 folder_ids 重建。
所以「原生位置行」本来就是会被冲掉的临时状态，留着只会让 tag 在搬走后仍出现在旧目录里。

规则：
  * folder_ids 非空 → 保留 folder_ids + 其区域祖先，其余删掉
  * folder_ids 为空 → 原样保留（没有真源，只能靠 tag_tags 兜底）

用法： python cleanup_members.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DB = ROOT / "userdatas_zh_CN_tags.db"


def plan(con):
    groups = {r[0]: (r[1], r[2]) for r in con.execute(
        "select id_index, name, p_uuid from tag_groups")}
    subs = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        "select id_index, group_id, name, g_uuid from tag_subgroups")}
    sub_to_group = {v[2]: v[0] for v in subs.values()}
    keep, nonempty = set(), set()
    for uuid, blob in con.execute("select tag_uuid, data from workbench_tag_meta"):
        try:
            fids = json.loads(blob).get("folder_ids") or []
        except Exception:
            fids = []
        if not fids:
            continue
        nonempty.add(uuid)
        for fid in fids:
            keep.add((uuid, fid))
            gid = sub_to_group.get(fid)
            if gid is None:
                continue
            parent = groups.get(gid, (None, None))[1]
            if parent:
                keep.add((uuid, parent))
    drop = [(u, g) for u, g in con.execute(
        "select tag_uuid, g_uuid from workbench_tag_folder_members")
        if u in nonempty and (u, g) not in keep]
    return nonempty, keep, drop


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB))
    try:
        nonempty, keep, drop = plan(con)
        total = con.execute("select count(*) from workbench_tag_folder_members").fetchone()[0]
        print(f"成员表 {total:,}；folder_ids 非空 {len(nonempty):,}")
        print(f"  保留 {len(keep):,}；清理 {len(drop):,}")
        if not args.apply:
            print("dry-run，未改动。加 --apply 执行。")
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"cleanup_members_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)
        con.executemany("delete from workbench_tag_folder_members "
                        "where tag_uuid=? and g_uuid=?", drop)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.commit()
        after = con.execute("select count(*) from workbench_tag_folder_members").fetchone()[0]
        dup = con.execute("select count(*) - count(distinct tag_uuid || '|' || g_uuid) "
                          "from workbench_tag_folder_members").fetchone()[0]
        print(f"清理后 {after:,}；重复 {dup}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
