"""量：成员表按「folder_ids 为真源」清理时，会删多少、会不会把 tag 清空。

规则：
  * folder_ids 非空的 tag → 保留 folder_ids + 它们的区域祖先，其余删掉
  * folder_ids 为空的 tag → 原样保留（它们没有真源，只能靠 tag_tags 兜底）
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

DB = (r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
      r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\userdatas_zh_CN_tags.db")


def main() -> int:
    con = sqlite3.connect(DB)
    groups = {r[0]: (r[1], r[2]) for r in con.execute(
        "select id_index, name, p_uuid from tag_groups")}
    subs = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        "select id_index, group_id, name, g_uuid from tag_subgroups")}
    sub_to_group = {v[2]: v[0] for v in subs.values()}

    keep = set()
    nonempty = set()
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

    rows = list(con.execute("select tag_uuid, g_uuid from workbench_tag_folder_members"))
    drop = [(u, g) for u, g in rows if u in nonempty and (u, g) not in keep]
    fallback_tags = len({u for u, _g in rows if u not in nonempty})
    fallback_rows = sum(1 for u, _g in rows if u not in nonempty)

    print(f"成员表总行 {len(rows):,}")
    print(f"folder_ids 非空的 tag {len(nonempty):,}")
    print(f"  应保留 {len(keep):,}；应清理 {len(drop):,}")
    print(f"folder_ids 为空的 tag {fallback_tags:,}（{fallback_rows:,} 行）→ 原样保留")
    # 会不会把 tag 清空
    per = Counter(u for u, _g in drop)
    has = Counter(u for u, _g in rows if u in nonempty)
    gone = [u for u in per if per[u] == has[u]]
    print(f"  清理后一个归属都不剩的 tag：{len(gone)}")
    if gone[:5]:
        for u in gone[:5]:
            t = con.execute("select text from tag_tags where t_uuid=?", (u,)).fetchone()
            print("     ", (t[0] if t else "")[:50])
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
