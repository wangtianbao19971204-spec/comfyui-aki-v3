"""清掉 tag 库里的「单画师词典」/「画风组词典」区域。

背景：单画师改用 Anima 画师大区（带预览图），本地不再保留单画师条目。
实测：单画师词典 893 条（其中 391 条带预览图）；画风组词典 1622 条、0 张图。

补充（2026-09-19 复核）：画风组词典的文案在**资源库 data.json** 里也有，
而且那边带图（codex_artist_nai45_strings_*.jpg）；1,282 条里 1,280 条前缀精确匹配。
所以删 tag 库这份是纯去重，文案与图都不会丢。

删的是**库里的原始条目**（tag_tags + 它们的 meta / 成员行），不是归属标签。
预览图文件不动（删条目后它们只是变成孤儿文件，随时可单独清）。

用法： python delete_single_artist_area.py [--area 单画师词典] [--apply]
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
DEFAULT_AREA = "单画师词典"


def collect(con, area):
    gdb = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
    subs = {r[0]: (r[1], r[2]) for r in con.execute(
        "select id_index, group_id, name from tag_subgroups")}
    ids = [s for s, (g, _n) in subs.items() if gdb.get(g) == area]
    uuids = []
    for u, s in con.execute("select t_uuid, subgroup_id from tag_tags"):
        if s in ids:
            uuids.append(u)
    return ids, uuids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--area", default=DEFAULT_AREA,
                    help="要清理的区域名（默认 单画师词典）")
    args = ap.parse_args()
    area = args.area
    con = sqlite3.connect(str(DB))
    try:
        subgroup_ids, uuids = collect(con, area)
        print(f"区域「{area}」：叶子 {len(subgroup_ids)} 个，条目 {len(uuids):,}")
        if not args.apply:
            print("dry-run，未改动。加 --apply 执行。")
            return 0
        if not uuids:
            print("没有可删的条目。")
            return 0

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = ROOT / "prompt_selector_data_backups" / f"delete_single_artist_{stamp}"
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, backup / "userdatas_zh_CN_tags.db")
        print(f"已备份：{backup}")

        marks = ",".join("?" * len(uuids))
        # 先把要删的内容留档，便于回查
        dump = backup / "deleted_entries.txt"
        with open(dump, "w", encoding="utf-8") as fh:
            for u, t in con.execute(
                    f"select t_uuid, text from tag_tags where t_uuid in ({marks})", uuids):
                fh.write(f"{u}\t{t}\n")

        n_meta = con.execute(
            f"delete from workbench_tag_meta where tag_uuid in ({marks})", uuids).rowcount
        n_mem = con.execute(
            f"delete from workbench_tag_folder_members where tag_uuid in ({marks})",
            uuids).rowcount
        n_tag = con.execute(
            f"delete from tag_tags where t_uuid in ({marks})", uuids).rowcount
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.execute("update workbench_tag_text_revision set value = value + 1 where id = 1")
        con.execute("update tag_subgroups set p_uuid = p_uuid")   # 触发文本版本（可选）
        con.commit()

        left = con.execute(
            f"select count(*) from tag_tags where t_uuid in ({marks})", uuids).fetchone()[0]
        print(f"已删除：tag_tags {n_tag:,} 行 / meta {n_meta:,} 行 / 成员 {n_mem:,} 行；复查残留 {left}")
        print(f"删除清单留档：{dump}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
