"""Point the Anima erase subgraph at the mask the mask editor actually saved.

The [05] 线稿与姿态控制 subgraph instances its own 高级 · 擦线与导出 copy, which is the erase
implementation the Anima branches use (the Krea2 branch keeps its own root-level chain, so the
two branches stay independent). That copy's mask loader still points at
ComfyUI_temp_oflff_00001_.png, an ordinary RGB render without an alpha channel, which makes the
composite an erasing no-op. Its properties.image already records the editor-saved RGBA mask.

This migration writes that correct file into the image widget of every mask loader inside the
erase subgraph definition, and does nothing else.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("UAP统一生产工作台_v2.json", "生产套件_01_Anima原版_LoRA生产_v2.json",
         "生产套件_02_Anima2.9B_动漫生产_v2.json")
DIRECTORIES = ("ComfyUI/user/default/workflows", "production_tools/templates")
ERASE_NAME = "高级 · 擦线与导出"
EDITOR_MASK = "clipspace/clipspace-painted-masked-1782566128506.png"


def migrate(data):
    result = copy.deepcopy(data)
    subgraphs = {item["id"]: item for item in result.get("definitions", {}).get("subgraphs") or []}
    erase_ids = {key for key, item in subgraphs.items() if item.get("name") == ERASE_NAME}
    changes = []
    for key in erase_ids:
        definition = subgraphs[key]
        for node in definition.get("nodes") or []:
            if node.get("type") != "LoadImage":
                continue
            widgets = node.get("widgets_values")
            if not widgets:
                continue
            before = widgets[0]
            if before == EDITOR_MASK:
                continue
            properties = node.setdefault("properties", {})
            recorded = properties.get("image")
            changes.append({"definition": key[:8], "node": node["id"], "before": before,
                            "after": EDITOR_MASK, "properties_image": recorded})
            widgets[0] = EDITOR_MASK
            properties["image"] = EDITOR_MASK
    return result, {"erase_subgraphs": sorted(key[:8] for key in erase_ids),
                    "editor_mask": EDITOR_MASK, "changes": changes,
                    "scope": "only the image widget of mask loaders inside 高级 · 擦线与导出"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-source", action="store_true")
    args = parser.parse_args()
    for directory in DIRECTORIES:
        for name in FILES:
            path = ROOT / directory / name
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8")
            indent = len(raw.splitlines()[1]) - len(raw.splitlines()[1].lstrip())
            before = json.loads(raw)
            after, audit = migrate(before)
            print(json.dumps({"file": str(path.relative_to(ROOT)), "changed": before != after,
                              "written": args.write_source, "audit": audit}, ensure_ascii=False))
            if args.write_source and before != after:
                payload = (json.dumps(after, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")
                if b"\r\n" in raw.encode("utf-8"):
                    payload = payload.replace(b"\n", b"\r\n")
                path.write_bytes(payload)


if __name__ == "__main__":
    main()
