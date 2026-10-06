"""Historical layout algorithm; direct rebuilding of production is retired.

Export the current canonical template with merge_unified_workflow.py instead.
The functions below preserve the old algorithm for explicit historical review.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

from merge_unified_workflow import ROOT, SOURCES, WORKFLOW_DIR, merge, read_json, write_json, validate

OUTPUT = WORKFLOW_DIR / "UAP统一生产工作台_v2.json"
REPORT_DIR = ROOT / "benchmark_reports/2026-09-06_plugin_optimization"
PAD, HEADER, GAP = 24, 68, 40
COLORS = {"daily": "#426878", "input": "#48685B", "prompt": "#596882", "model": "#716247", "control": "#5D5875", "refine": "#73596B", "compare": "#486B70"}
LABELS = {"daily": "日常出图", "input": "参考与反推", "prompt": "提示词工具", "model": "模型与开关", "control": "控制与修复", "refine": "细化与二放", "compare": "阶段对比"}


def rect(node):
    x, y = node["pos"]
    w, h = node["size"]
    return [x, y - 30, w, h + 30]


def bounds(rectangles, margin=0):
    x = min(r[0] for r in rectangles) - margin
    y = min(r[1] for r in rectangles) - margin
    right = max(r[0] + r[2] for r in rectangles) + margin
    bottom = max(r[1] + r[3] for r in rectangles) + margin
    return [x, y, right - x, bottom - y]


def overlaps(a, b):
    return min(a[0] + a[2], b[0] + b[2]) > max(a[0], b[0]) and min(a[1] + a[3], b[1] + b[3]) > max(a[1], b[1])


def contains(g, n):
    x, y, w, h = g["bounding"]
    nx, ny = n["pos"]
    nw, nh = n["size"]
    return x <= nx + nw / 2 <= x + w and y <= ny + nh / 2 <= y + h


def resize(n):
    t = n["type"]
    w, h = n["size"]
    if t == "MarkdownNote":
        if isinstance(n.get("widgets_values"), str):
            n["widgets_values"] = [n["widgets_values"]]
        w, h = 520, 250
    elif t in {"VAELoader", "UpscaleModelLoader", "ModelSamplingAuraFlow", "PrimitiveBoolean", "PrimitiveFloat"}:
        w, h = 400, 70
    elif t in {"UNETLoader", "CLIPLoader", "EmptyLatentImage", "EmptySD3LatentImage", "easy seed"}:
        w, h = 400, 120
    elif t in {"VAEEncode", "VAEDecode", "MaskToImage", "ImageUpscaleWithModel"}:
        w, h = 400, 80
    elif t in {"ImpactConditionalBranch", "ImageScaleBy", "ImageScaleToMaxDimension", "ResizeImagesByLongerEdge", "VRAMCleanup"}:
        w, h = 400, 140
    elif t == "KSampler":
        w, h = 400, 340
    elif t == "UltimateSDUpscale":
        w, h = 400, 680
    elif t == "DazzleSwitch":
        w, h = 400, max(220, min(h, 300))
    elif t in {"PreviewImage", "Image Comparer (rgthree)", "SimpleImageCompare"}:
        w, h = 440, 440
    elif t == "SaveImage":
        w, h = 440, 130
    elif t == "LoadImage":
        w, h = (480 if n["id"] == 1206 else 400), 410
    elif t == "OlmDragCrop":
        w, h = 400, 920
    elif t in {"CR Prompt Text", "ShowText|pysssss"}:
        w, h = 400, 280
    elif t == "CLIPTextEncode":
        w, h = 400, 180
    elif t == "WeiLinPromptUI":
        w, h = 540, 400
    elif t == "PromptCleaningMaid":
        w, h = 400, 400
    elif t in {"Lora Stacker (LoraManager)", "Lora Loader (LoraManager)"}:
        w, h = 400, 350
    elif t == "DanbooruGalleryNode":
        w, h = 840, 920
    elif t == "PromptSelector":
        w, h = 520, 760
    elif t.startswith("Fast Groups"):
        w, h = 520, max(220, h)
    elif t.startswith("Anima") and "TagSelector" in t:
        w, h = 400, 210
    elif t == "AnimaPromptComposer":
        w, h = 440, 660
    elif re.fullmatch(r"[0-9a-f-]{36}", t):
        w, h = 400, max(100, h)
    else:
        w = max(400, math.ceil(w / 20) * 20)
    n["size"] = [w, h]
    n.setdefault("flags", {}).pop("pinned", None)
    n["flags"]["collapsed"] = False


def pack_nodes(nodes, width=1360):
    """Shelf pack with title clearance. Similar widgets share a vertical lane."""
    lanes = []
    for n in sorted(nodes, key=lambda n: -n["size"][0]):
        w, h = n["size"]
        candidates = [(i, l) for i, l in enumerate(lanes) if l["w"] >= w]
        if candidates and (sum(l["w"] + GAP for l in lanes) + w > width):
            i, lane = min(candidates, key=lambda p: p[1]["y"])
        else:
            lane = {"x": sum(l["w"] + GAP for l in lanes), "w": w, "y": 0}
            if lane["x"] + w > width and candidates:
                i, lane = min(candidates, key=lambda p: p[1]["y"])
            else:
                lanes.append(lane)
        n["pos"] = [PAD + lane["x"], HEADER + lane["y"]]
        lane["y"] += h + 30 + GAP
    return [max(n["pos"][0] + n["size"][0] for n in nodes) + PAD,
            max(n["pos"][1] + n["size"][1] for n in nodes) + PAD]


def move(group, nodes, x, y):
    dx, dy = x - group["bounding"][0], y - group["bounding"][1]
    group["bounding"][0:2] = [x, y]
    for n in nodes:
        n["pos"] = [n["pos"][0] + dx, n["pos"][1] + dy]


def stage_of(title):
    if title.startswith(("CORE-01", "SW-01")): return "input"
    if title.startswith(("SW-00B", "SW-03A", "CORE-03")): return "prompt"
    if title.startswith(("CORE-02G", "CORE-04", "CORE-05", "SW-05K", "SW-05 ", "SW-09", "CORE-06A")): return "control"
    if title.startswith(("CORE-02", "CORE-00W", "INFO-", "CTRL-")): return "model"
    if title.startswith(("FX-", "CORE-10", "CORE-11")): return "refine"
    if title.startswith(("SW-10", "SW-05V")): return "compare"
    return "daily"


def build():
    data = merge(None, compact=True)
    baseline = copy.deepcopy(data)
    nodes = {n["id"]: n for n in data["nodes"]}
    for n in data["nodes"]: resize(n)
    all_groups, branches = [], []
    next_gid = 1000

    def group(title, ns, stage, width=1360):
        nonlocal next_gid
        size = pack_nodes(ns, width)
        g = {"id": next_gid, "title": title, "bounding": [0, 0, *size], "color": COLORS[stage], "font_size": 24, "flags": {}}
        next_gid += 1
        all_groups.append(g)
        return (g, ns)

    node_cursor, branch_y = 1002, 0
    for index, (spec, stat) in enumerate(zip(SOURCES, data["extra"]["production_suite"]["source_stats"])):
        ns = data["nodes"][node_cursor - 1000: node_cursor - 1000 + stat["nodes"]]
        source = read_json(WORKFLOW_DIR / spec["file"])
        defaults = {str(n["id"]): s.get("mode", 0) for n, s in zip(ns, source["nodes"])}
        node_cursor += len(ns)
        stages = {key: [] for key in LABELS}
        if index < 3:
            old_groups = [g for g in baseline["groups"] if g["title"].endswith(spec["suffix"])]
            owners = {}
            for n in ns:
                old_n = next(o for o in baseline["nodes"] if o["id"] == n["id"])
                matches = [g for g in old_groups if contains(g, old_n)]
                owners[n["id"]] = min(matches, key=lambda g: g["bounding"][2] * g["bounding"][3])["id"] if matches else None
            daily = [n for n in ns if (n.get("title", "").startswith("[00W") and n["type"] != "AnimaMultiLoraLoader")]
            prompts = [n for n in daily if n["type"] not in {"SaveImage", "PreviewImage"}]
            prompts.sort(key=lambda n: (n["type"] != "WeiLinPromptUI", n["type"] == "PrimitiveBoolean", n["id"]))
            results = [n for n in daily if n["type"] in {"SaveImage", "PreviewImage"}]
            results.sort(key=lambda n: n["type"] != "SaveImage")
            cleanup = [n for n in ns if n["type"] == "VRAMCleanup"]
            results += cleanup
            sample_groups = [g for g in old_groups if g["title"].startswith("CORE-06 ") or (index < 2 and g["title"].startswith("CORE-06A"))]
            sampling = [n for n in ns if owners[n["id"]] in {g["id"] for g in sample_groups}]
            sampling.sort(key=lambda n: (n["type"] != "KSampler", n["type"] == "MarkdownNote", n["id"]))
            # Keep the sampler and size/seed controls in two compact lanes.
            for n in sampling:
                if n["type"] == "MarkdownNote": n["size"] = [400, 180]
                elif n["size"][0] > 400: n["size"][0] = 400
            stages["daily"] = [group("01 提示词与出图模式 " + spec["suffix"], prompts, "daily", 980),
                               group("02 尺寸、种子与采样 " + spec["suffix"], sampling, "daily", 840),
                               group("03 最终预览与保存 " + spec["suffix"], results, "daily", 480)]
            prompt_y = HEADER
            for n in prompts:
                if n["type"] == "WeiLinPromptUI":
                    n["pos"] = [PAD, HEADER]
                else:
                    n["pos"] = [PAD + 580, prompt_y]
                    prompt_y += n["size"][1] + 30 + GAP
            stages["daily"][0][0]["bounding"][3] = max(n["pos"][1] + n["size"][1] for n in prompts) + PAD
            taken = {n["id"] for n in daily + cleanup + sampling}
            for old_g in old_groups:
                members = [n for n in ns if owners[n["id"]] == old_g["id"] and n["id"] not in taken]
                if not members: continue
                title = old_g["title"]
                stage = stage_of(title)
                members.sort(key=lambda n: (n["type"] == "MarkdownNote", next(o for o in baseline["nodes"] if o["id"] == n["id"])["pos"][1], n["id"]))
                for n in members:
                    if n["type"].startswith("Fast Groups"):
                        prefix = "FX-" if "Bypasser" in n["type"] else "SW-"
                        n["properties"]["matchTitle"] = "^" + prefix + ".*" + re.escape(spec["suffix"]) + "$"
                        n["properties"]["showAllGraphs"] = False
                if title.startswith("CORE-02 "):
                    loaders = [n for n in members if n["type"] in {"UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingAuraFlow"}]
                    loras = [n for n in members if n not in loaders]
                    loaders.sort(key=lambda n: ["UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingAuraFlow"].index(n["type"]))
                    def lora_order(n):
                        title = n.get("title", "")
                        if n["type"] == "Lora Stacker (LoraManager)":
                            return 0 if "角色" in title else (1 if "基础" in title else 2)
                        return 3 if n["type"] == "Lora Loader (LoraManager)" else 4
                    loras.sort(key=lora_order)
                    stages[stage].append(group("CORE-02A 模型与编码器 " + spec["suffix"], loaders, stage, 840))
                    stages[stage].append(group("CORE-02B LoRA 组合与加载 " + spec["suffix"], loras, stage, 840))
                else:
                    width = 560 if title.startswith("CORE-01A") else (1440 if "图库" in title else 1320)
                    item = group(title, members, stage, width)
                    stages[stage].append(item)
                taken.update(n["id"] for n in members)
            leftovers = [n for n in ns if n["id"] not in taken]
            if leftovers: stages["model"].append(group("模型补充说明 " + spec["suffix"], leftovers, "model"))

            x = 0
            for g, members in stages["daily"]:
                move(g, members, x, branch_y)
                x += g["bounding"][2] + 64
            daily_height = max(g["bounding"][3] for g, _ in stages["daily"])
            row_y = branch_y + daily_height + 160
            # Three aligned columns; each stage is traversed top to bottom.
            for row in (("input", "prompt", "model"), ("control", "refine", "compare")):
                row_bottom = row_y
                for col, stage in enumerate(row):
                    cursor = row_y
                    for g, members in stages[stage]:
                        move(g, members, col * 1740, cursor)
                        cursor += g["bounding"][3] + 72
                    row_bottom = max(row_bottom, cursor)
                row_y = row_bottom + 100
        else:
            def ext_stage(n):
                t = n["type"]
                if t in {"SaveImage", "PreviewImage", "VRAMCleanup"}: return "compare"
                if t in {"UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingAuraFlow", "UpscaleModelLoader", "LoraLoaderModelOnly"}: return "model"
                if t in {"LoadImage", "MarkdownNote", "OlmDragCrop", "ImagePadForOutpaint"}: return "input"
                if t in {"CLIPTextEncode", "Krea2EditGroundedEncode"}: return "prompt"
                return "control"
            x = 0
            for stage in ("input", "prompt", "model", "control", "compare"):
                members = [n for n in ns if ext_stage(n) == stage]
                if not members: continue
                if stage == "input":
                    members.sort(key=lambda n: {"MarkdownNote": 0, "OlmDragCrop": 1, "ImagePadForOutpaint": 2, "LoadImage": 3}[n["type"]])
                if stage == "compare": members.sort(key=lambda n: {"SaveImage": 0, "PreviewImage": 1, "VRAMCleanup": 2}[n["type"]])
                label = {"input": "输入与选区", "prompt": "编辑提示词", "model": "模型加载", "control": "处理与采样", "compare": "预览与交付"}[stage]
                width = 1000 if stage == "input" else (840 if stage == "control" else 560)
                item = group(label + " " + spec["suffix"], members, stage, width)
                move(*item, x, branch_y)
                x += item[0]["bounding"][2] + 64
                stages[stage].append(item)

        items = [item for values in stages.values() for item in values]
        branch_bounds = bounds([g["bounding"] for g, _ in items], 40)
        branch_bounds[1] -= 32
        branch_bounds[3] += 32
        wrapper = {"id": next_gid, "title": spec["nav"], "bounding": branch_bounds, "color": "#343C46", "font_size": 28, "flags": {}}
        next_gid += 1
        all_groups.insert(0, wrapper)
        stage_meta = [{"id": k, "label": LABELS[k], "groups": [g["title"] for g, _ in stages[k]]} for k in LABELS if stages[k]]
        if index >= 3:
            stage_meta.sort(key=lambda s: ["input", "prompt", "model", "control", "compare"].index(s["id"]))
            for s in stage_meta:
                s["label"] = {"input": "输入与选区", "prompt": "编辑提示词", "model": "模型加载", "control": "处理与采样", "compare": "预览与交付"}[s["id"]]
        branches.append({"id": spec["key"], "label": spec["label"], "group": spec["nav"], "nodeIds": [n["id"] for n in ns], "modes": defaults, "stages": stage_meta})
        branch_y = branch_bounds[1] + branch_bounds[3] + 320

    nodes[1000]["widgets_values"] = ["# UAP 统一工作台\n\n顶部导航选择分支，再按阶段浏览。\n\n**日常出图**：提示词 → 尺寸与种子 → 采样 → 预览保存。\n\n高级工具位于下方，按阶段按钮和细分菜单直达。"]
    nodes[1001].update(type="MarkdownNote", title="分支切换说明", inputs=[], outputs=[], properties={"Node name for S&R": "MarkdownNote"}, size=[520, 250], widgets_values=["## 分支切换\n\n顶部选择分支后，点击 **启用此分支**。\n\n切换会保留各分支的可选工具和旁路状态。\n\n只浏览或跳转不会改变启用状态。\n\n**上一步 / 下一步** 按阶段和分组顺序浏览。"])
    console = group("[00] UAP统一工作台总控台", [nodes[1000], nodes[1001]], "daily", 1100)
    move(*console, 0, -480)
    release = nodes[max(nodes)]
    release["widgets_values"] = ["## 完成与释放\n\n检查最终预览和保存路径。\n\n连续出图时保留模型缓存；本轮完成后使用 ComfyUI 的卸载模型操作，或打开 `生产套件_99_释放模型显存_v2.json`。"]
    ending = group("[10] 显存释放与收尾", [release], "compare", 560)
    move(*ending, 1160, -480)
    data["groups"] = all_groups
    data["last_group_id"] = next_gid - 1
    data["revision"] = 3
    data["id"] = "uap-unified-production-workbench-visual-20260906"
    data["extra"]["uap_workbench"] = {"version": 1, "activeBranch": "a1", "viewBranch": "a1", "stage": "daily", "branches": branches}
    data["extra"]["codex_uap_integration"].update(layout="operation_stages_compact", navigation="UAP stage toolbar + exact group navigation", generated_by="production_tools/layout_uap_workbench.py")
    data["extra"]["workflow_display_name"] = "UAP统一生产工作台 · 视觉操作优化"
    data["extra"]["workflow_variant"] = "unified_visual_operation_layout"
    data["extra"]["qgn_navigation_groups"] = [{"id": "uap_home", "groupName": console[0]["title"], "shortcutKey": "1", "zoomScale": 95, "order": 0}] + [
        {"id": "uap_" + b["id"], "groupName": b["stages"][0]["groups"][0], "shortcutKey": str((i + 2) % 10), "zoomScale": 95, "order": i + 1} for i, b in enumerate(branches)]
    data["extra"]["qgn_navigation_groups"].append({"id": "uap_release", "groupName": ending[0]["title"], "shortcutKey": "L", "zoomScale": 95, "order": 10})
    data["extra"]["ds"] = {"scale": 0.65, "offset": [100, 240]}
    data["extra"]["production_suite"]["navigation_slots"] = 11
    return data, baseline


def audit(data, before):
    errors = validate(data)
    assert data["links"] == before["links"], "Execution links changed"
    assert data["definitions"] == before["definitions"], "Subgraphs changed"
    for old, new in zip(before["nodes"], data["nodes"]):
        if old["id"] in {1000, 1001, 1307}: continue
        for field in ("id", "type", "mode", "inputs", "outputs", "widgets_values"):
            a, b = old.get(field), new.get(field)
            if field == "widgets_values" and old["type"] == "MarkdownNote" and isinstance(a, str): a = [a]
            assert a == b, (old["id"], field)
    for old in before["groups"]:
        if not old["title"].startswith(("SW-", "FX-")): continue
        new = next(g for g in data["groups"] if g["title"] == old["title"])
        old_members = {n["id"] for n in before["nodes"] if contains(old, n)}
        new_members = {n["id"] for n in data["nodes"] if contains(new, n)}
        assert old_members == new_members, (old["title"], old_members ^ new_members)
    collisions = [(a["id"], b["id"]) for i, a in enumerate(data["nodes"]) for b in data["nodes"][i+1:] if overlaps(rect(a), rect(b))]
    if collisions: errors.append(f"node/title overlaps: {collisions}")
    inner = [g for g in data["groups"] if not re.match(r"^\[0[1-9]\]", g["title"])]
    group_collisions = [(a["title"], b["title"]) for i, a in enumerate(inner) for b in inner[i+1:] if overlaps(a["bounding"], b["bounding"])]
    if group_collisions: errors.append(f"group overlaps: {group_collisions}")
    old_inner = [g for g in before["groups"] if not re.match(r"^\[0[1-3]\]", g["title"])]
    branch_metrics = []
    for b in data["extra"]["uap_workbench"]["branches"]:
        ids = set(b["nodeIds"])
        old_rect = bounds([rect(n) for n in before["nodes"] if n["id"] in ids])
        new_rect = bounds([rect(n) for n in data["nodes"] if n["id"] in ids])
        branch_metrics.append({"branch": b["label"], "before": old_rect[2:], "after": new_rect[2:], "area_reduction_percent": round(100 * (1 - new_rect[2] * new_rect[3] / (old_rect[2] * old_rect[3])), 1)})
    return {"errors": errors, "execution_links_unchanged": True, "subgraphs_unchanged": True, "generation_widgets_and_modes_unchanged": True, "optional_group_membership_unchanged": True,
            "node_title_overlap_count": len(collisions), "inner_group_overlap_count": len(group_collisions),
            "before_group_area": sum(g["bounding"][2]*g["bounding"][3] for g in old_inner), "after_group_area": sum(g["bounding"][2]*g["bounding"][3] for g in inner),
            "before_node_area": sum(n["size"][0]*n["size"][1] for n in before["nodes"]), "after_node_area": sum(n["size"][0]*n["size"][1] for n in data["nodes"]),
            "branch_layout_metrics": branch_metrics,
            "nodes": len(data["nodes"]), "links": len(data["links"]), "subgraphs": len(data["definitions"]["subgraphs"]), "groups": len(data["groups"]),
            "ui_verification": "pending"}


if __name__ == "__main__":
    raise SystemExit(
        "Historical layout rebuild is retired: it restores old workflow receivers and parameters. "
        "Use merge_unified_workflow.py --output <NEW candidate.json> to export the canonical v2 template; "
        "review and deploy the candidate with guards. No files were changed."
    )
