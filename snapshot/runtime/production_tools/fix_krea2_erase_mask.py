"""Repair the line-art erase chain in the UAP workspace.

Two defects were measured on node 1164 ([05C2], the erase-mask loader):

1. the node is muted (mode 2), so its MASK output never reaches [05C7] ImageCompositeMasked;
2. its image widget points at ComfyUI_temp_oflff_00001_.png, an ordinary RGB render with no
   alpha channel, while its own properties.image still records the last mask-editor save
   (clipspace/clipspace-painted-masked-*.png), which is RGBA and really carries transparency.

This migration unmutes the node and restores the widget to the editor-saved mask, and only
touches that one node.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("UAP统一生产工作台_v2.json",)
DIRECTORIES = ("ComfyUI/user/default/workflows", "production_tools/templates")
MASK_NODE = 1164
EXPECTED_PROPERTY = 'clipspace/clipspace-painted-masked-1782566128506.png [input]'


def migrate(data):
    result = copy.deepcopy(data)
    nodes = {node["id"]: node for node in result["nodes"]}
    node = nodes.get(MASK_NODE)
    if node is None:
        raise ValueError(f"root node {MASK_NODE} is missing; the erase chain moved")
    properties = node.get("properties") or {}
    recorded = properties.get("image")
    if recorded != EXPECTED_PROPERTY:
        raise ValueError(f"node {MASK_NODE} no longer records the expected editor mask: {recorded!r}")
    changes = []
    if node.get("mode", 0) != 0:
        changes.append({"node": MASK_NODE, "field": "mode", "before": node.get("mode"), "after": 0})
        node["mode"] = 0
    widgets = node.get("widgets_values")
    if not widgets or widgets[0] != EXPECTED_PROPERTY.split(" ")[0]:
        changes.append({"node": MASK_NODE, "field": "widgets_values[0]",
                        "before": widgets[0] if widgets else None,
                        "after": EXPECTED_PROPERTY.split(" ")[0]})
        widgets[0] = EXPECTED_PROPERTY.split(" ")[0]
    audit = {"node": MASK_NODE, "title": node.get("title"), "changes": changes,
             "mask_semantics": "LoadImage derives MASK from alpha, so transparent areas become "
                               "mask=1 and are the areas the composite fills",
             "scope": "only node 1164: its muted state and its mask file reference"}
    return result, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-source", action="store_true")
    args = parser.parse_args()
    for directory in DIRECTORIES:
        for name in FILES:
            path = ROOT / directory / name
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
