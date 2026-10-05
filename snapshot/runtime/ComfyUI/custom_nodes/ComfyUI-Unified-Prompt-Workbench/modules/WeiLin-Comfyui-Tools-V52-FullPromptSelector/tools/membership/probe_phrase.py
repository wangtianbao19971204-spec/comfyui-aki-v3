"""针对单个短语回查：这个短语到底命中了哪些 tag？

用法：python probe_phrase.py "short" "nsfw" "cum" ...
输出每个短语 12 条随机样例（含它在文本里的上下文），用来判断是否弱词误伤。
"""
from __future__ import annotations

import re
import sqlite3
import sys
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402

SAMPLE = 12


def main(argv) -> int:
    needles = argv[1:] or ["short", "nsfw"]
    with sqlite3.connect(str(DB)) as con:
        groups = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()

    for needle in needles:
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(needle.lower()).replace(r"\ ", r"[ _]+")
                         + r"(?![a-z0-9])", re.I)
        bucket = []
        count = 0
        for uuid, subgroup_id, text in rows:
            entry = subs.get(subgroup_id)
            area = groups.get(entry[0], "") if entry else ""
            if COMBO.search(area):
                continue
            body = denoise(text)
            m = pat.search(body)
            if not m:
                continue
            count += 1
            bucket.append((md5(uuid.encode()).hexdigest(), body, m.start(), m.end()))
            bucket.sort(key=lambda x: x[0])
            del bucket[SAMPLE:]
        print(f"=== 「{needle}」命中 {count:,} 条；抽样 {min(SAMPLE, len(bucket))} ===")
        for _k, body, s, e in bucket:
            ctx = body[max(0, s - 34):e + 34].replace("\n", " ")
            print(f"   …{ctx}…")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
