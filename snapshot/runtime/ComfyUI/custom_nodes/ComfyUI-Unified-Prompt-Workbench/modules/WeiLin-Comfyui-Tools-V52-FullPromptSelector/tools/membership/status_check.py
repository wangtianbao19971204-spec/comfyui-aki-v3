"""全局状态核查：tag 库 / 资源库 / 归属写回 / 预览图 / Anima 下载 / git。"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DB = ROOT / "userdatas_zh_CN_tags.db"
DATA = ROOT / "prompt_selector" / "data.json"
PREVIEW = ROOT / "prompt_selector" / "preview"
HERE = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")


def main() -> int:
    with sqlite3.connect(str(DB)) as con:
        total = con.execute("select count(*) from tag_tags").fetchone()[0]
        groups = con.execute("select count(*) from tag_groups").fetchone()[0]
        subs = con.execute("select count(*) from tag_subgroups").fetchone()[0]
        meta = con.execute("select count(*) from workbench_tag_meta").fetchone()[0]
        with_theme = con.execute("select count(*) from workbench_tag_meta where data like '%\"themes\"%'").fetchone()[0]
        members = con.execute("select count(*) from workbench_tag_folder_members").fetchone()[0]
        dup = con.execute("select count(*) - count(distinct tag_uuid || '|' || g_uuid) "
                          "from workbench_tag_folder_members").fetchone()[0]
        orphan_sub = con.execute(
            "select count(*) from tag_subgroups s left join tag_groups g on s.group_id = g.id_index "
            "where g.id_index is null").fetchone()[0]
        rev = list(con.execute("select value from workbench_tag_revision"))[0][0]
    print(f"== tag 库 ==")
    print(f"  tag {total:,} | 区域 {groups} | 叶子 {subs} | 断链叶子 {orphan_sub} | revision {rev}")
    print(f"  meta {meta:,}（含 themes {with_theme:,}）| 成员 {members:,} | 成员重复 {dup}")

    document = json.loads(DATA.read_text(encoding="utf-8"))
    categories = document["categories"]
    krea = [c for c in categories if c["name"].startswith("Krea2 情绪版")]
    krea_entries = sum(len(c["prompts"]) for c in krea)
    krea_img = sum(1 for c in krea for e in c["prompts"] if (e.get("image") or "").strip())
    print(f"== 资源库 ==")
    print(f"  分类 {len(categories)} | 条目 {sum(len(c['prompts']) for c in categories):,}")
    print(f"  Krea2 情绪版：{len(krea)} 个分类 / {krea_entries:,} 条 / 有图 {krea_img:,}")

    counts = Counter()
    for path in PREVIEW.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name.startswith("anima_artist_"):
            counts["anima 画师图"] += 1
        elif name.startswith("ray_style_"):
            counts["Krea2 情绪版图"] += 1
        else:
            counts["其它预览"] += 1
    print(f"== 预览目录 ==（{PREVIEW}）")
    for key, value in counts.most_common():
        print(f"  {key}: {value:,}")

    log = HERE / "anima_download.out.log"
    if log.exists():
        tail = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        print("== Anima 下载 ==")
        print("  " + (tail[-1] if tail else "无日志"))
    failed = HERE / "anima_download_failed.jsonl"
    if failed.exists():
        print(f"  失败清单：{sum(1 for _ in failed.open(encoding='utf-8')):,} 条")
    for name in ("面与主题_定稿统计_20260919.md", "归属抽样验收_20260919.md", "writeback_manifest_20260919.json"):
        path = HERE / name
        print(f"  {name}: {'有' if path.exists() else '缺'}（{path.stat().st_size if path.exists() else 0:,} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
