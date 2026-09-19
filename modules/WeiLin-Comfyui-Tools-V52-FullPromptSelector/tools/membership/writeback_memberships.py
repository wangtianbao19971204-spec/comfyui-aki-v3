"""写回库：① 条级 themes/facets 进 workbench_tag_meta；② 叶子+祖先归属进 members（闭合）。

先备份，再写；写完跑断言：闭合违规 0 / 无重复 / meta 可解析。
用法： python writeback_memberships.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DB = ROOT / "userdatas_zh_CN_tags.db"
DATA = ROOT / "prompt_selector" / "data.json"
BACKUP = ROOT / "prompt_selector_data_backups" / "20260919_membership_writeback"
HERE = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
SRC = HERE / "全库_面与主题_20260919.jsonl"
MANIFEST = HERE / "writeback_manifest_20260919.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        BACKUP.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, BACKUP / "userdatas_zh_CN_tags.db")
        shutil.copy2(DATA, BACKUP / "data.json")
        print(f"已备份：{BACKUP}")

    rows = [json.loads(line) for line in SRC.read_text(encoding="utf-8").splitlines() if line.strip()]
    con = sqlite3.connect(str(DB))
    try:
        groups = {row[0]: (row[1], row[2]) for row in
                  con.execute("select id_index, name, p_uuid from tag_groups")}
        subgroups = {row[0]: (row[1], row[2], row[3]) for row in
                     con.execute("select id_index, group_id, name, g_uuid from tag_subgroups")}
        tag_rows = {row[0]: (row[1], row[2]) for row in
                    con.execute("select t_uuid, subgroup_id, text from tag_tags")}
        meta = {row[0]: row[1] for row in con.execute("select tag_uuid, data from workbench_tag_meta")}
        existing = list(con.execute("select tag_uuid, g_uuid from workbench_tag_folder_members"))

        meta_rows = []
        member_rows = []
        for row in rows:
            uuid = row["id"]
            if uuid not in tag_rows:
                continue
            subgroup_id = tag_rows[uuid][0]
            entry = subgroups.get(subgroup_id)
            old = {}
            if uuid in meta:
                try:
                    old = json.loads(meta[uuid])
                except Exception:  # noqa: BLE001
                    old = {}
            old["themes"] = row["themes"]
            old["facets"] = row["facets"]
            meta_rows.append((uuid, json.dumps(old, ensure_ascii=False)))
            if entry:
                folder_uuids = [entry[2]]
                group = groups.get(entry[0])
                if group and group[1]:
                    folder_uuids.append(group[1])       # 祖先闭合：区域级
                for folder in folder_uuids:
                    member_rows.append((uuid, folder))
        print(f"将写入：meta {len(meta_rows):,} 行；成员 {len(member_rows):,} 行"
              f"（原成员 {len(existing):,} 行）")
        # 全局祖先闭合：任何"叶子级"成员都要补上它的区域级父 uuid
        subgroup_uuid_to_group = {value[2]: value[0] for value in subgroups.values()}
        have = {(uuid, folder) for uuid, folder in con.execute(
            "select tag_uuid, g_uuid from workbench_tag_folder_members")}
        closure_rows = []
        for uuid, folder in list(have):
            group_id = subgroup_uuid_to_group.get(folder)
            if group_id is None:
                continue
            parent_uuid = groups.get(group_id, (None, None))[1]
            if parent_uuid and (uuid, parent_uuid) not in have:
                closure_rows.append((uuid, parent_uuid))
                have.add((uuid, parent_uuid))
        print(f"补祖先归属（全局闭合）：{len(closure_rows):,} 行")
        if args.apply:
            con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) values (?,?)",
                            meta_rows)
            con.executemany("insert or ignore into workbench_tag_folder_members (tag_uuid, g_uuid) "
                            "values (?,?)", member_rows)
            if closure_rows:
                con.executemany("insert or ignore into workbench_tag_folder_members "
                                "(tag_uuid, g_uuid) values (?,?)", closure_rows)
            con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
            con.execute("update workbench_tag_text_revision set value = value + 1 where id = 1")
            con.commit()

        # 断言
        members: dict[str, set[str]] = defaultdict(set)
        for uuid, folder in con.execute("select tag_uuid, g_uuid from workbench_tag_folder_members"):
            members[uuid].add(folder)
        closure_violation = 0
        checked = 0
        for uuid, folders in members.items():
            for folder in folders:
                group_id = subgroup_uuid_to_group.get(folder)
                if group_id is None:
                    continue
                parent_uuid = groups.get(group_id, (None, None))[1]
                if parent_uuid:
                    checked += 1
                    if parent_uuid not in folders:
                        closure_violation += 1
        dup = con.execute("select count(*) - count(distinct tag_uuid || '|' || g_uuid) "
                          "from workbench_tag_folder_members").fetchone()[0]
        meta_ok = sum(1 for uuid, blob in con.execute("select tag_uuid, data from workbench_tag_meta")
                      if blob and blob.strip().startswith("{"))
        print(f"断言：闭合违规 {closure_violation}/{checked}；重复成员 {dup}；meta 可解析 {meta_ok:,}")
    finally:
        con.close()
    MANIFEST.write_text(json.dumps({"timestamp": datetime.now().isoformat(timespec="seconds"),
                                    "applied": args.apply, "tags": len(rows)},
                                   ensure_ascii=False), encoding="utf-8")
    print(f"{'已写回' if args.apply else 'DRY-RUN'}；manifest：{MANIFEST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
