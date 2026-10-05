"""把 Ray 风格（Krea2 情绪版，3549 条）导入资源库：图片入库 + 新分类。"""
from __future__ import annotations

import json
import shutil
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DATA = ROOT / "prompt_selector" / "data.json"
PREVIEW = ROOT / "prompt_selector" / "preview"
BACKUP = ROOT / "prompt_selector_data_backups" / "20260919_krea2_mood"
CENTER = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
SRC = CENTER / "ray_styles_package.jsonl"
AREA = "Krea2 情绪版"
SOURCE_TAG = "Ray Style Switching Extension · 3549 moodboard (Civitai 2856809)"


def short_group(name: str) -> str:
    parts = name.split("_")
    return parts[-1] if len(parts) > 1 else name


def main() -> int:
    styles = [json.loads(line) for line in SRC.read_text(encoding="utf-8").splitlines() if line.strip()]
    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DATA, BACKUP / "data.json")
    document = json.loads(DATA.read_text(encoding="utf-8"))

    copied = missing = 0
    by_group: dict[str, list[dict]] = defaultdict(list)
    for index, style in enumerate(styles, 1):
        target = PREVIEW / f"ray_style_{index:05d}.webp"
        source = Path(style.get("image") or "")
        if source.is_file():
            if not target.exists():
                shutil.copy2(source, target)
            copied += 1
        else:
            missing += 1
        by_group[short_group(style["group"])].append({
            "id": f"krea2mood-{uuid.uuid4().hex[:16]}",
            "alias": style.get("name_cn") or style.get("name"),
            "prompt": style.get("prompt") or "",
            "description": f"{style.get('name')}｜negative: {style.get('negative_prompt') or '无'}",
            "image": target.name if source.is_file() else "",
            "tags": [AREA, style["group"]],
            "favorite": False, "template": False,
            "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
            "usage_count": 0, "last_used": None, "is_user_plan": False,
            "_classification": {"disposition": "classified", "primary_class": "style_quality",
                                "content_type": "fragment", "usage": "positive",
                                "model_scope": "krea2", "manual_search_eligible": True,
                                "random_pool_eligible": False, "semantic_review_status": "pending",
                                "note_kind": None, "note": SOURCE_TAG},
        })

    for group, entries in by_group.items():
        name = f"{AREA} / {group}"
        category = next((c for c in document["categories"] if c["name"] == name), None)
        if category is None:
            category = {"id": f"codex-{uuid.uuid4().hex[:12]}", "name": name,
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(), "prompts": []}
            document["categories"].append(category)
        existing = {e.get("prompt") for e in category["prompts"]}
        for entry in entries:
            if entry["prompt"] not in existing:
                category["prompts"].append(entry)
        category["updated_at"] = datetime.now().isoformat()
    document["last_modified"] = datetime.now().isoformat()
    DATA.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    total_entries = sum(len(v) for v in by_group.values())
    print(f"导入风格 {total_entries:,} 条；复制图片 {copied:,} 张，无图 {missing} 张")
    print(f"新建/更新分类 {len(by_group)} 个，全部在「{AREA}」下")
    for group, entries in sorted(by_group.items(), key=lambda item: -len(item[1]))[:8]:
        print(f"   {AREA} / {group}｜{len(entries):,} 条")
    print(f"备份：{BACKUP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
