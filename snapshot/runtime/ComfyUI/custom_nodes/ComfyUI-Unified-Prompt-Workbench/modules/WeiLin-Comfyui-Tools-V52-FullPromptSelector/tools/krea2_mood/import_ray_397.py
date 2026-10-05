"""导入 397_styles 版到「Krea2 情绪版」（单独标版本）。"""
from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
ZIP = Path(r"C:\Users\Administrator\Downloads\rayStyleSwitching_397Styles_3123959.zip")
OUT = HERE / "ray_styles" / "styles397_local"
ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
DATA = ROOT / "prompt_selector" / "data.json"
PREVIEW = ROOT / "prompt_selector" / "preview"
BACKUP = ROOT / "prompt_selector_data_backups" / "20260919_krea2_mood397"
AREA = "Krea2 情绪版"
SOURCE = "Ray Style Switching Extension · 397 styles (Civitai 2856809)"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP) as archive:
        archive.extractall(OUT)
    images = {path.name: path for path in OUT.rglob("*.jpg")}
    styles: list[dict] = []
    for path in sorted(OUT.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in (data if isinstance(data, list) else [data]):
            styles.append({**item, "_file": path.stem})
    print(f"397 版风格条目 {len(styles):,}；包内 jpg {len(images)}")
    print("字段：", sorted({key for style in styles for key in style if not key.startswith('_')}))
    sample = styles[0]
    print("样例：", json.dumps(sample, ensure_ascii=False)[:300])
    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DATA, BACKUP / "data.json")
    document = json.loads(DATA.read_text(encoding="utf-8"))
    by_group: dict[str, list[dict]] = defaultdict(list)
    copied = missing = 0
    for index, style in enumerate(styles, 1):
        key = (style.get("thumbnail") or style.get("image") or style.get("name") or "")
        candidate = images.get(Path(str(key).replace("./", "").replace("\\", "/")).name or "")
        if candidate is None:                      # 退回按风格名找
            for name, path in images.items():
                if Path(name).stem.lower() == str(style.get("name", "")).lower():
                    candidate = path
                    break
        target = PREVIEW / f"ray_style_397_{index:04d}.jpg"
        if candidate and candidate.is_file():
            if not target.exists():
                shutil.copy2(candidate, target)
            copied += 1
            image_name = target.name
        else:
            missing += 1
            image_name = ""
        group = style["_file"].split("_")[-1]
        by_group[group].append({
            "id": f"krea2mood397-{uuid.uuid4().hex[:14]}",
            "alias": style.get("name") or f"风格 {index}",
            "prompt": style.get("prompt") or "",
            "description": f"397 styles｜{style.get('_file')}",
            "image": image_name,
            "tags": [AREA, "397风格", style["_file"]],
            "favorite": False, "template": False,
            "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
            "usage_count": 0, "last_used": None, "is_user_plan": False,
            "_classification": {"disposition": "classified", "primary_class": "style_quality",
                                "content_type": "fragment", "usage": "positive",
                                "model_scope": "krea2", "manual_search_eligible": True,
                                "random_pool_eligible": False, "semantic_review_status": "pending",
                                "note_kind": None, "note": SOURCE},
        })
    for group, entries in by_group.items():
        name = f"{AREA} / 397风格 · {group}"
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
    print(f"导入 {sum(len(v) for v in by_group.values()):,} 条；复制图片 {copied}，无图 {missing}")
    print(f"新分类 {len(by_group)} 个：" + "、".join(sorted(by_group)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
