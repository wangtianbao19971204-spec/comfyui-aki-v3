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
HERE = Path(__file__).resolve().parent
DEFAULT_SRC = HERE / "全库_面与主题_v12_20260919.jsonl"
MANIFEST = HERE / "writeback_manifest_20260919.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--src", default=str(DEFAULT_SRC),
                        help="要写回的归属快照 jsonl（默认 v12 动作/场景定稿）")
    parser.add_argument("--backup-name", default="20260919_action_scene_v12",
                        help="备份子目录名")
    args = parser.parse_args()
    src = Path(args.src)
    backup_dir = ROOT / "prompt_selector_data_backups" / args.backup_name
    if args.apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, backup_dir / "userdatas_zh_CN_tags.db")
        shutil.copy2(DATA, backup_dir / "data.json")
        print(f"已备份：{backup_dir}")

    print(f"来源快照：{src}")
    rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
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
            if row.get("series"):
                old["series"] = row["series"]      # 角色›原作 顺带补的作品名
            meta_rows.append((uuid, json.dumps(old, ensure_ascii=False)))
            # folder_ids 是成员表的唯一真源；它有值时**不要再补原生位置行**，
            # 否则 tag 搬走后仍会出现在旧目录里（而且下次 UI 一改就被冲掉）。
            if entry and not (old.get("folder_ids") or []):
                folder_uuids = [entry[2]]
                group = groups.get(entry[0])
                if group and group[1]:
                    folder_uuids.append(group[1])       # 祖先闭合：区域级
                for folder in folder_uuids:
                    member_rows.append((uuid, folder))
        print(f"将写入：meta {len(meta_rows):,} 行；成员 {len(member_rows):,} 行"
              f"（原成员 {len(existing):,} 行）")
        # 全局祖先闭合：任何"叶子级"成员都要补上它的区域级父 uuid。
        # 注意：meta 上有触发器（DELETE + 按 folder_ids 重建），所以闭合**必须在写完之后
        # 再算一次**，否则算的是写之前的旧状态，等于白算。
        subgroup_uuid_to_group = {value[2]: value[0] for value in subgroups.values()}

        def compute_closure():
            have = {(u, f) for u, f in con.execute(
                "select tag_uuid, g_uuid from workbench_tag_folder_members")}
            rows_out = []
            for uuid, folder in list(have):
                group_id = subgroup_uuid_to_group.get(folder)
                if group_id is None:
                    continue
                parent_uuid = groups.get(group_id, (None, None))[1]
                if parent_uuid and (uuid, parent_uuid) not in have:
                    rows_out.append((uuid, parent_uuid))
                    have.add((uuid, parent_uuid))
            return rows_out

        if args.apply:
            con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) values (?,?)",
                            meta_rows)
            con.executemany("insert or ignore into workbench_tag_folder_members (tag_uuid, g_uuid) "
                            "values (?,?)", member_rows)
            closure_rows = compute_closure()          # ← 写完 meta 之后再算
            if closure_rows:
                con.executemany("insert or ignore into workbench_tag_folder_members "
                                "(tag_uuid, g_uuid) values (?,?)", closure_rows)
            print(f"补祖先归属（写后重算）：{len(closure_rows):,} 行")
            con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
            con.execute("update workbench_tag_text_revision set value = value + 1 where id = 1")
            con.commit()
        else:
            print(f"补祖先归属（dry-run 预演）：{len(compute_closure()):,} 行")

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
