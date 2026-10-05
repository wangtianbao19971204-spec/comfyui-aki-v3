"""Compact the current UAP file while preserving the user's graph and values."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from layout_uap_workbench import OUTPUT, ROOT, bounds, contains, overlaps, rect

REPORT = ROOT / "benchmark_reports/2026-09-06_plugin_optimization/widget_density"
PAD, HEADER, GAP = 16, 58, 24
SIZES = {
    "VAELoader": (360, 70), "UNETLoader": (360, 100), "CLIPLoader": (360, 100),
    "UpscaleModelLoader": (360, 70), "ModelSamplingAuraFlow": (280, 70),
    "PrimitiveBoolean": (320, 70), "PrimitiveFloat": (260, 70),
    "EmptyLatentImage": (300, 110), "EmptySD3LatentImage": (300, 110), "easy seed": (320, 100),
    "VAEDecode": (240, 48), "VAEEncode": (240, 64), "VAEEncodeForInpaint": (300, 100),
    "MaskToImage": (240, 48), "ImageUpscaleWithModel": (280, 64),
    "ImpactConditionalBranch": (300, 100), "ImageScaleBy": (280, 90),
    "ImageScaleToMaxDimension": (300, 90), "ResizeImagesByLongerEdge": (280, 70),
    "VRAMCleanup": (300, 100), "KSampler": (320, 290), "UltimateSDUpscale": (360, 610),
    "DazzleSwitch": (340, 170), "PreviewImage": (340, 280),
    "Image Comparer (rgthree)": (340, 300), "SimpleImageCompare": (360, 300),
    "SaveImage": (360, 80), "LoadImage": (320, 300),
    "CR Prompt Text": (360, 140), "ShowText|pysssss": (360, 120),
    "CLIPTextEncode": (360, 120), "WeiLinPromptUI": (480, 250),
    "PromptCleaningMaid": (340, 340),
    "Lora Stacker (LoraManager)": (400, 200), "Lora Loader (LoraManager)": (400, 220),
    "DanbooruGalleryNode": (760, 580), "PromptSelector": (520, 430),
    "AnimaPromptComposer": (440, 380), "GetImageSize": (260, 90),
    "SolidMask": (280, 110), "FeatherMask": (280, 130),
    "ImageCompositeMasked": (300, 130), "LoraLoaderModelOnly": (360, 90),
    "Krea2EditModelPatch": (300, 90), "Krea2EditGroundedEncode": (360, 220),
    "Krea2ControlImageEncode": (340, 180), "Krea2ControlLoRALoader": (360, 100),
    "Krea2ControlApply": (300, 80), "AIO_Preprocessor": (300, 100),
    "DepthAnythingV2Preprocessor": (300, 100), "AnimaMultiLoraLoader": (320, 70),
    "ImagePadForOutpaint": (300, 150), "BiRefNetRMBG": (300, 180),
    "AnimaLLLiteApply_sdscripts": (360, 200), "OlmCropInfoInterpreter": (300, 190),
    "VNCCS_PoseStudio": (800, 640), "OlmJoyCaption": (400, 350),
    "TB_Anima_Prompt_Judge_API_V16": (400, 560), "PixAITagger": (400, 300),
    "DanbooruBrowserImportV05": (540, 240),
}


def resize(node):
    kind = node["type"]
    node.setdefault("properties", {})["uap_compact_widgets"] = True
    if kind in SIZES:
        node["size"] = list(SIZES[kind])
    if kind == "MarkdownNote":
        text = node.get("widgets_values", [""])[0]
        node["size"] = [380, 110 if len(text) < 300 else 170]
    elif kind.startswith("Anima") and "TagSelector" in kind:
        node["size"] = [340, 150]
    if kind == "LoadImage" and node["id"] == 1206:
        node["size"] = [480, 300]
    if kind == "PreviewImage" and node.get("title", "").startswith("[00W"):
        node["size"] = [360, 320]
    if kind == "DazzleSwitch":
        visible_ports = sum(1 for p in node.get("inputs", []) if not p.get("widget"))
        node["size"][1] = max(170, visible_ports * 20 + 90)
    if kind == "AnimaPromptComposer":
        # This node owns a thumbnail panel that expands after execution.
        node["size"][1] = 660 if node["id"] != 1008 else 380
    if kind.startswith("Lora ") and "LoraManager" in kind:
        loras = next((v for v in node.get("widgets_values", []) if isinstance(v, list)), [])
        rows = sum(2 if v.get("expanded") else 1 for v in loras if isinstance(v, dict))
        if rows:
            node["size"][1] += min(164, 44 + rows * 40) - 32


def pack(group, nodes, width):
    lanes = []
    for n in sorted(nodes, key=lambda n: -n["size"][0]):
        w, h = n["size"]
        candidates = [l for l in lanes if l["w"] >= w]
        next_x = sum(l["w"] + GAP for l in lanes)
        if next_x + w <= width or not candidates:
            lane = {"x": next_x, "w": w, "y": 0}
            lanes.append(lane)
        else:
            lane = min(candidates, key=lambda l: l["y"])
        n["pos"] = [PAD + lane["x"], HEADER + lane["y"]]
        lane["y"] += h + 30 + GAP
    group["bounding"] = [0, 0, max(n["pos"][0] + n["size"][0] for n in nodes) + PAD,
                         max(n["pos"][1] + n["size"][1] for n in nodes) + PAD]


def move(group, members, x, y):
    dx, dy = x - group["bounding"][0], y - group["bounding"][1]
    group["bounding"][0:2] = [x, y]
    for n in members:
        n["pos"] = [n["pos"][0] + dx, n["pos"][1] + dy]


def compact(data, resize_nodes=True):
    result = copy.deepcopy(data)
    groups = {g["title"]: g for g in result["groups"]}
    branches = result["extra"]["uap_workbench"]["branches"]
    wrappers = {b["group"] for b in branches}
    members = {g["title"]: [n for n in result["nodes"] if contains(g, n)] for g in result["groups"] if g["title"] not in wrappers}
    assigned = [n["id"] for ns in members.values() for n in ns]
    assert len(assigned) == len(result["nodes"]) == len(set(assigned)), "Ambiguous group membership"
    old_positions = {n["id"]: n["pos"][:] for n in result["nodes"]}
    for g in result["groups"]:
        if g["title"] in wrappers: continue
        ns = members[g["title"]]
        ns.sort(key=lambda n: (round(old_positions[n["id"]][1] / 60), old_positions[n["id"]][0]))
        for n in ns:
            if resize_nodes: resize(n)
            n.setdefault("properties", {})["uap_layout_group"] = g["title"]
        width = min(1360, g["bounding"][2] - 32)
        if g["title"].startswith("01 提示词"): width = 880
        if g["title"].startswith("02 尺寸"): width = 684
        if g["title"].startswith("03 最终"): width = 360
        if g["title"].startswith("CORE-02B"): width = 824
        pack(g, ns, width)
        if g["title"].startswith("02 尺寸"):
            # Keep dimensions and seed beside sampling, with short utility nodes
            # sharing the same column instead of reserving an almost empty lane.
            left_types = ("EmptyLatentImage", "EmptySD3LatentImage", "easy seed", "MarkdownNote")
            left = sorted((n for n in ns if n["type"] in left_types), key=lambda n: left_types.index(n["type"]))
            right = [n for n in ns if n not in left]
            right.sort(key=lambda n: {"DazzleSwitch": 0, "KSampler": 1, "VAEDecode": 2}.get(n["type"], 3))
            for column, x in ((left, PAD), (right, PAD + 344)):
                y = HEADER
                for n in column:
                    if n["type"] == "MarkdownNote": n["size"][0] = 320
                    n["pos"] = [x, y]
                    y += n["size"][1] + 30 + GAP
            g["bounding"][2] = max(n["pos"][0]+n["size"][0] for n in ns) + PAD
            g["bounding"][3] = max(n["pos"][1]+n["size"][1] for n in ns) + PAD
        if g["title"].startswith("01 提示词"):
            y = HEADER
            prompt_width = next(n["size"][0] for n in ns if n["type"] == "WeiLinPromptUI")
            for n in sorted(ns, key=lambda n: (n["type"] == "PrimitiveBoolean", n["id"])):
                if n["type"] == "WeiLinPromptUI": n["pos"] = [PAD, HEADER]
                else:
                    n["pos"] = [PAD + prompt_width + GAP, y]
                    y += n["size"][1] + 30 + GAP
            g["bounding"][2] = max(n["pos"][0]+n["size"][0] for n in ns) + PAD
            g["bounding"][3] = max(n["pos"][1]+n["size"][1] for n in ns) + PAD

    cursor_y = 0
    for b in branches:
        stages = {s["id"]: s["groups"] for s in b["stages"]}
        if "daily" in stages:
            y = cursor_y
            for daily_row in b.get("dailyRows", [stages["daily"]]):
                x = 0
                for title in daily_row:
                    g = groups[title]; move(g, members[title], x, y); x += g["bounding"][2] + 32
                y += max(groups[t]["bounding"][3] for t in daily_row) + 48
            y += 48
            for row in (("input", "prompt", "model"), ("control", "refine", "compare")):
                x = 0; row_bottom = y
                for key in row:
                    titles = stages.get(key, []); sy = y
                    for title in titles:
                        g = groups[title]; move(g, members[title], x, sy); sy += g["bounding"][3] + 48
                    row_bottom = max(row_bottom, sy)
                    x += max((groups[t]["bounding"][2] for t in titles), default=0) + 96
                y = row_bottom + 48
        else:
            x = 0
            for s in b["stages"]:
                for title in s["groups"]:
                    g = groups[title]; move(g, members[title], x, cursor_y); x += g["bounding"][2] + 48
        titles = [t for s in b["stages"] for t in s["groups"]]
        g = groups[b["group"]]
        g["bounding"] = bounds([groups[t]["bounding"] for t in titles], 28)
        g["bounding"][1] -= 30; g["bounding"][3] += 30
        cursor_y = g["bounding"][1] + g["bounding"][3] + 200
    x = 0
    for title in ("[00] UAP统一工作台总控台", "[10] 显存释放与收尾"):
        g = groups[title]
        move(g, members[title], x, -g["bounding"][3] - 110)
        x += g["bounding"][2] + 48
    result["extra"]["uap_workbench"]["compactWidgets"] = True
    result["extra"]["codex_uap_integration"]["layout"] = "content_sized_widgets"
    result["revision"] = result.get("revision", 0) + 1
    return result


def audit(before, after):
    for key in ("links", "definitions"):
        assert before[key] == after[key], key
    after_nodes = {n["id"]: n for n in after["nodes"]}
    assert {n["id"] for n in before["nodes"]} == set(after_nodes), "Node IDs changed"
    for a in before["nodes"]:
        b = after_nodes[a["id"]]
        for key in ("id", "type", "mode", "inputs", "outputs", "widgets_values"):
            assert a.get(key) == b.get(key), (a["id"], key)
    for g in before["groups"]:
        other = next(o for o in after["groups"] if o["title"] == g["title"])
        assert {n["id"] for n in before["nodes"] if contains(g,n)} == {n["id"] for n in after["nodes"] if contains(other,n)}, g["title"]
    collisions = [(a["id"],b["id"]) for i,a in enumerate(after["nodes"]) for b in after["nodes"][i+1:] if overlaps(rect(a),rect(b))]
    assert not collisions, collisions
    old_area = sum(n["size"][0]*n["size"][1] for n in before["nodes"])
    new_area = sum(n["size"][0]*n["size"][1] for n in after["nodes"])
    return {"before_node_area": old_area, "after_node_area": new_area, "area_reduction_percent": round(100*(1-new_area/old_area),1),
            "node_title_overlaps": collisions,"graph_values_modes_and_group_members_preserved": True,"ui_verification":"pending"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--repack-measured", action="store_true")
    args = parser.parse_args()
    data = json.loads(OUTPUT.read_text(encoding="utf8"))
    result = compact(data, resize_nodes=not args.repack_measured)
    receipt = audit(data, result)
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / f"before_{datetime.now():%Y%m%d_%H%M%S}.json").write_bytes(OUTPUT.read_bytes())
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    receipt["workflow_sha256"] = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    (REPORT / "validation.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
