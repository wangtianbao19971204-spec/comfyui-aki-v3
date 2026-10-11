"""Simplify the selected Anima branch's control subgraphs; never deploy or enqueue."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
FILES = ("UAP统一生产工作台_v2.json", "生产套件_02_Anima2.9B_动漫生产_v2.json")
BRANCH_FILES = {"a29": FILES,
                "a1": (FILES[0], "生产套件_01_Anima原版_LoRA生产_v2.json")}
CHOICES = {"细致线稿": "PyraCannyPreprocessor", "中细线稿": "HEDPreprocessor",
           "粗略线稿": "Manga2Anime_LineArt_Preprocessor", "灰度图": "DepthAnythingV2Preprocessor"}


def node(node_id, kind, title, widgets=(), inputs=(), outputs=(), pos=(0, 0)):
    return {"id": node_id, "type": kind, "title": title, "pos": list(pos), "size": [300, 150],
            "flags": {}, "order": 0, "mode": 0, "inputs": [{"name": n, "type": t, "link": None} for n, t in inputs],
            "outputs": [{"name": n, "type": t, "links": []} for n, t in outputs],
            "properties": {}, "widgets_values": list(widgets)}


def relink(graph, connections):
    nodes = {n["id"]: n for n in graph["nodes"]}
    for n in nodes.values():
        for p in n.get("inputs", []): p["link"] = None
        for p in n.get("outputs", []): p["links"] = []
    for p in graph["inputs"] + graph["outputs"]: p["linkIds"] = []
    links = []
    for link_id, (source, source_slot, target, target_slot, kind) in enumerate(connections, 1):
        links.append({"id": link_id, "origin_id": source, "origin_slot": source_slot,
                      "target_id": target, "target_slot": target_slot, "type": kind})
        if source == -10: graph["inputs"][source_slot]["linkIds"].append(link_id)
        else: nodes[source]["outputs"][source_slot]["links"].append(link_id)
        if target == -20: graph["outputs"][target_slot]["linkIds"].append(link_id)
        else: nodes[target]["inputs"][target_slot]["link"] = link_id
    graph["links"] = links
    graph["state"]["lastLinkId"] = len(links)
    graph["state"]["lastNodeId"] = max(nodes)


def native_apply(old, loader_id):
    weight, strength, start, end, *_ = old["widgets_values"]
    loader = node(loader_id, "AnimaLLLiteModelLoader", "控制权重", [weight],
                  outputs=[("MODEL_PATCH", "MODEL_PATCH")])
    apply = node(old["id"], "AnimaLLLiteApply", "应用姿态控制", [strength, start, end],
                 inputs=[("model", "MODEL"), ("model_patch", "MODEL_PATCH"), ("image", "IMAGE"), ("mask", "MASK")],
                 outputs=[("MODEL", "MODEL")])
    return loader, apply


def compact_pose(graph, next_id):
    n = {item["title"]: item for item in graph["nodes"]}
    pick = lambda title: n[title]
    reference = pick("[05A] 姿态参考图")
    resize = pick("[05A] 参考图缩放")
    size = pick("[05A] 读取参考图尺寸")
    latent = pick("[06A] 自动出图尺寸")
    choice = pick("[05B] 控制图选择")["widgets_values"][0]
    if choice not in CHOICES: raise ValueError("Resolve the current control selector before migration: " + str(choice))
    processors = [pick(title) for title in ("[05B1] Canny 线稿", "[05B2] HED 线稿", "[05B3] 漫画线稿", "[05B4] 深度图")]
    resolutions = {p["widgets_values"][-1] for p in processors}
    if (len(resolutions) != 1
            or [p["widgets_values"][0] for p in processors[:3]] != list(CHOICES.values())[:3]
            or processors[-1]["widgets_values"][0] != "depth_anything_v2_vitl.pth"):
        raise ValueError("Custom preprocessing settings require an explicit migration.")
    pre = node(pick("[05B] 控制图选择")["id"], "AIO_Preprocessor", "控制方式", [CHOICES[choice], resolutions.pop()],
               inputs=[("image", "IMAGE")], outputs=[("IMAGE", "IMAGE")])
    loader, apply = native_apply(pick("[05D] 应用 LLLite 控制"), next_id)
    preview = pick("[05C] 擦线结果预览")
    preview["title"] = "最终控制图"
    advanced_id = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["id"] + "/erase-export"))
    advanced = {"id": advanced_id, "version": 1, "revision": 0, "name": "高级 · 擦线与导出",
        "state": {"lastGroupId": 0, "lastNodeId": 0, "lastLinkId": 0, "lastRerouteId": 0},
        "config": {}, "inputNode": {"id": -10, "bounding": [-200, 80, 128, 48]},
        "outputNode": {"id": -20, "bounding": [1150, 80, 128, 48]},
        "inputs": [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, advanced_id + "/input")), "name": "image", "type": "IMAGE", "linkIds": []}],
        "outputs": [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, advanced_id + "/output")), "name": "IMAGE", "type": "IMAGE", "linkIds": []}],
        "widgets": [], "groups": [], "extra": {}, "nodes": [pick(title) for title in (
            "[05C] 擦线遮罩", "[05C] 遮罩转图", "[05C] 遮罩预览", "[05B] 保存临时线稿",
            "[05C] 读取线稿尺寸", "[05C] 纯黑遮罩底", "[05C] 黑色覆盖图", "[05C] 擦除白色区域")]}
    m, mi, mp, save, dims, solid, black, composite = [item["id"] for item in advanced["nodes"]]
    # Current core exposes value before width/height. Keep slot numbers aligned
    # when the frontend adds native widget inputs while loading the saved graph.
    solid_node = next(item for item in advanced["nodes"] if item["id"] == solid)
    solid_node["inputs"] = [{"name": name, "type": kind, "widget": {"name": name}, "link": None}
                            for name, kind in (("value", "FLOAT"), ("width", "INT"), ("height", "INT"))]
    relink(advanced, [(-10, 0, save, 0, "IMAGE"), (-10, 0, dims, 0, "IMAGE"),
        (-10, 0, composite, 0, "IMAGE"), (m, 1, mi, 0, "MASK"), (mi, 0, mp, 0, "IMAGE"),
        (dims, 0, solid, 1, "INT"), (dims, 1, solid, 2, "INT"), (solid, 0, black, 0, "MASK"),
        (black, 0, composite, 1, "IMAGE"), (m, 1, composite, 2, "MASK"), (composite, 0, -20, 0, "IMAGE")])
    for i, item in enumerate(advanced["nodes"]): item["pos"] = [int(i % 3) * 340, int(i // 3) * 330]
    advanced_node = node(next_id + 1, advanced_id, "高级 · 擦线与导出", inputs=[("image", "IMAGE")], outputs=[("IMAGE", "IMAGE")])
    advanced_node["properties"]["uap_anima_erase"] = True
    # Preserve the existing mask operation. Bypass is an explicit user choice.
    graph["nodes"] = [reference, resize, pre, size, latent, advanced_node, preview, loader, apply]
    for i, item in enumerate(graph["nodes"]):
        item["pos"] = [int(i % 3) * 360, int(i // 3) * 340]
        if item["type"] != "LoadImage": item["size"] = [300, 220]
    graph["inputNode"]["bounding"] = [-190, 60, 128, 48]
    graph["outputNode"]["bounding"] = [1130, 700, 128, 68]
    graph["extra"]["anima_control_compact"] = 1
    graph["extra"]["anima_control_roles"] = {"reference": reference["id"], "preprocessor": pre["id"],
        "advanced": advanced_node["id"], "preview": preview["id"], "apply": apply["id"], "loader": loader["id"]}
    r, z, p, s, l, a, v, w, c = [item["id"] for item in graph["nodes"]]
    relink(graph, [(r, 0, z, 0, "IMAGE"), (z, 0, p, 0, "IMAGE"), (z, 0, s, 0, "IMAGE"),
        (s, 0, l, 0, "INT"), (s, 1, l, 1, "INT"), (p, 0, a, 0, "IMAGE"),
        (a, 0, v, 0, "IMAGE"), (a, 0, c, 2, "IMAGE"), (w, 0, c, 1, "MODEL_PATCH"),
        (-10, 0, c, 0, "MODEL"), (c, 0, -20, 0, "MODEL"), (l, 0, -20, 1, "LATENT")])
    return advanced


def migrate(data, branch_id="a29"):
    if branch_id not in BRANCH_FILES:
        raise ValueError("Unsupported Anima branch: " + str(branch_id))
    result = copy.deepcopy(data)
    definitions = result["definitions"]["subgraphs"]
    lookup = {g["id"]: g for g in definitions}
    next_id = max(n["id"] for g in [result, *definitions] for n in g["nodes"]) + 1
    branches = result.get("extra", {}).get("uap_workbench", {}).get("branches")
    allowed = set(next(b["nodeIds"] for b in branches if b["id"] == branch_id)) if branches else {n["id"] for n in result["nodes"]}
    for owner in result["nodes"]:
        graph = lookup.get(owner["type"])
        if owner["id"] not in allowed or not graph or graph["name"] not in ("[05] 线稿与姿态控制", "[09] VNCCS 光影控制"):
            continue
        if owner.get("properties", {}).get("uap_native_lllite"): continue
        if graph["name"].startswith("[05]"):
            definitions.append(compact_pose(graph, next_id))
            next_id += 2
            owner["properties"]["uap_anima_control"] = 1
            owner["properties"]["anima_control_roles"] = graph["extra"]["anima_control_roles"]
            preview = graph["extra"]["anima_control_roles"]["preview"]
            owner["properties"].pop("proxyWidgets", None)
            owner["properties"].pop("proxyWidgetErrorQuarantine", None)
            owner["properties"]["previewExposures"] = [{"name": "$$canvas-image-preview", "sourceNodeId": str(preview), "sourcePreviewName": "$$canvas-image-preview"}]
        else:
            old = next(n for n in graph["nodes"] if n["type"] == "AnimaLLLiteApply_sdscripts")
            loader, apply = native_apply(old, next_id)
            next_id += 1
            apply["pos"], loader["pos"] = old["pos"], [old["pos"][0], old["pos"][1] - 260]
            apply["title"] = old["title"]
            graph["nodes"] = [apply if n is old else n for n in graph["nodes"]] + [loader]
            connections = [(l["origin_id"], l["origin_slot"], l["target_id"],
                2 if l["target_id"] == old["id"] and l["target_slot"] == 1 else l["target_slot"], l["type"]) for l in graph["links"]]
            connections.append((loader["id"], 0, apply["id"], 1, "MODEL_PATCH"))
            relink(graph, connections)
        owner["properties"].pop("uap_legacy_lllite", None)
        owner["properties"]["uap_native_lllite"] = True
    for item in result["nodes"]:
        if item["id"] in allowed and item["type"] in ("Note", "MarkdownNote"):
            for i, value in enumerate(item.get("widgets_values", [])):
                if branch_id == "a1" and isinstance(value, str):
                    item["widgets_values"][i] = value.replace(
                        "Anima 2.9B 不可启用原版 28 层 LLLite。",
                        "原版 Anima 使用原生 28 层 LLLite 控制，无需区块映射。")
                if isinstance(value, str) and "当前 any-v2 与 inpainting-v2 LLLite" in value:
                    item["widgets_values"][i] = "## 姿态与构图控制\n\n本流的线稿/深度和 VNCCS 控制使用原生 Anima LLLite 与自动区块映射。需要启用 ComfyUI-Anima-LoRA-ControlNet-Patch；旧 LoRA 补丁由统一补丁替代。\n\n控制分支仍默认关闭。线稿控制先选参考图和控制方式，再调强度；原擦线遮罩与导出设置保留在高级子图，可旁路。采样、LoRA 和提示词沿用原值。层映射正确不保证每张图的控制效果，须用实际参考图验收。"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", choices=BRANCH_FILES, default="a29",
                        help="Branch to simplify; defaults to the existing a29 migration.")
    parser.add_argument("--write-source", action="store_true")
    args = parser.parse_args()
    for directory in (ROOT / "ComfyUI/user/default/workflows", ROOT / "production_tools/templates"):
        for name in BRANCH_FILES[args.branch]:
            path = directory / name
            text = path.read_text(encoding="utf-8")
            indent = len(text.splitlines()[1]) - len(text.splitlines()[1].lstrip())
            before = json.loads(text)
            after = migrate(before, args.branch)
            print(json.dumps({"file": str(path.relative_to(ROOT)), "changed": before != after, "written": args.write_source}, ensure_ascii=False))
            if args.write_source and before != after:
                path.write_bytes((json.dumps(after, ensure_ascii=False, indent=indent) + "\n").encode("utf-8"))


if __name__ == "__main__": main()
