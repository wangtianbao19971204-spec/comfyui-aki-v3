"""Add the VNCCS pose source to the Krea2 depth control in the UAP workbench.

The k2 branch already routes a depth map into the Krea2 depth ControlNet-LoRA:

    1190 reference -> 1153 resize -> 1191 DepthAnythingV2 -> 1159 Krea2ControlImageEncode
    -> 1161 Krea2ControlApply -> sampler

and the VNCCS pose studio output (1172) currently feeds previews only. This change adds
the same two pieces the line-art path already uses for its own source choice:

    [05B6] DazzleSwitch          (pose-depth source selection, same shape as 1157)
    [05B4P] DepthAnythingV2      (depth of the pose render)
    [05V4] PreviewImage          (pose depth preview, same shape as 05V* previews)

with input_01 = the existing reference depth (unchanged default) and input_02 = the pose
depth. Both new nodes are appended to the k2 branch node list and to the CORE-05 group
metadata, so branch activation and the workbench layout keep treating them as parts of
the Krea2 control chain.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("UAP统一生产工作台_v2.json",)
DIRECTORIES = ("ComfyUI/user/default/workflows", "production_tools/templates")

REFERENCE_DEPTH = 1191
CONTROL_ENCODE = 1159
POSE_STUDIO = 1172
GROUP = "CORE-05 参考预处理与控制图生成 · K2 Krea2"
BRANCH = "k2"
POSE_SWITCH_TITLE = "[05B6] Depth 来源选择（参考图 / VNCCS 姿势）"
POSE_DEPTH_TITLE = "[05B4P] VNCCS 姿势深度"
POSE_PREVIEW_TITLE = "[05V4] VNCCS 姿势深度预览"


def new_node(node_id, kind, title, widgets=(), inputs=(), outputs=(), size=(340, 150)):
    return {
        "id": node_id, "type": kind, "title": title, "pos": [0, 0], "size": list(size),
        "flags": {}, "order": 0, "mode": 0,
        "inputs": [{"name": name, "type": kind_, "link": None} for name, kind_ in inputs],
        "outputs": [{"name": name, "type": kind_, "links": []} for name, kind_ in outputs],
        "properties": {"uap_compact_widgets": True, "uap_layout_group": GROUP},
        "widgets_values": list(widgets),
    }


def link_id(link):
    """Subgraph definitions and the root graph use different link encodings."""
    return link[0] if isinstance(link, list) else link["id"]


def link_origin(link):
    return link[1] if isinstance(link, list) else link["origin_id"]


def link_origin_slot(link):
    return link[2] if isinstance(link, list) else link["origin_slot"]


def migrate(data):
    result = copy.deepcopy(data)
    nodes = result["nodes"]
    by_id = {node["id"]: node for node in nodes}
    for required in (REFERENCE_DEPTH, CONTROL_ENCODE, POSE_STUDIO):
        if required not in by_id:
            raise ValueError(f"root node {required} is missing; the Krea2 control chain moved")
    definitions = result["definitions"]["subgraphs"]
    next_node = max(node["id"] for graph in [result, *definitions] for node in graph["nodes"]) + 1
    next_link = max(link_id(link) for graph in [result, *definitions] for link in graph.get("links", [])) + 1

    def append(node):
        nodes.append(node)
        by_id[node["id"]] = node
        return node

    switch = append(new_node(next_node, "DazzleSwitch", POSE_SWITCH_TITLE,
                             widgets=["(none)", "priority", 0],
                             inputs=[("input_01", "*"), ("input_02", "*")],
                             outputs=[("output", "*"), ("selected_index", "INT")]))
    depth = append(new_node(next_node + 1, "DepthAnythingV2Preprocessor", POSE_DEPTH_TITLE,
                            widgets=["depth_anything_v2_vitl.pth", 1024],
                            inputs=[("image", "IMAGE")],
                            outputs=[("IMAGE", "IMAGE")]))
    preview = append(new_node(next_node + 2, "PreviewImage", POSE_PREVIEW_TITLE,
                              inputs=[("images", "IMAGE")], outputs=[]))

    links = []

    # The root graph stores links as [id, origin_id, origin_slot, target_id, target_slot, type];
    # a dict there is not deserialized by the frontend, so match whatever the file already uses.
    link_style = 'list' if any(isinstance(item, list) for item in result["links"]) else 'dict'

    def add_link(origin, origin_slot, target, target_slot, kind):
        nonlocal next_link
        if link_style == 'list':
            link = [next_link, origin, origin_slot, target, target_slot, kind]
        else:
            link = {"id": next_link, "origin_id": origin, "origin_slot": origin_slot,
                    "target_id": target, "target_slot": target_slot, "type": kind}
        links.append(link)
        result["links"].append(link)
        by_id[origin]["outputs"][origin_slot]["links"].append(next_link)
        by_id[target]["inputs"][target_slot]["link"] = next_link
        next_link += 1
        return link

    # pose studio -> pose depth -> switch input_02 and preview
    add_link(POSE_STUDIO, 0, depth["id"], 0, "IMAGE")
    add_link(depth["id"], 0, switch["id"], 1, "IMAGE")
    add_link(depth["id"], 0, preview["id"], 0, "IMAGE")
    # reference depth -> switch input_01
    add_link(REFERENCE_DEPTH, 0, switch["id"], 0, "IMAGE")

    # rewire the encoder's control image: reference depth -> switch output
    encode = by_id[CONTROL_ENCODE]
    port = next(item for item in encode["inputs"] if item["name"] == "control_image")
    previous = port["link"]
    old_link = next(item for item in result["links"] if link_id(item) == previous)
    origin_id, origin_slot = link_origin(old_link), link_origin_slot(old_link)
    origin_node = by_id[origin_id]
    origin_node["outputs"][origin_slot]["links"] = [
        link_id_ for link_id_ in origin_node["outputs"][origin_slot]["links"] if link_id_ != previous]
    result["links"] = [item for item in result["links"] if link_id(item) != previous]
    port["link"] = None
    add_link(switch["id"], 0, CONTROL_ENCODE, encode["inputs"].index(port), "IMAGE")

    # keep the encoder's own preview of the pose depth available
    if "state" in result:
        result["state"]["lastNodeId"] = max(node["id"] for node in nodes)
        result["state"]["lastLinkId"] = max(link_id(item) for item in result["links"])

    k2 = next(branch for branch in result["extra"]["uap_workbench"]["branches"] if branch["id"] == BRANCH)
    added = [switch["id"], depth["id"], preview["id"]]
    k2["nodeIds"] = sorted(set(k2["nodeIds"]) | set(added))

    audit = {
        "branch": BRANCH,
        "added_nodes": [{"id": node["id"], "type": node["type"], "title": node["title"]} for node in (switch, depth, preview)],
        "rewired": {"control_encode": CONTROL_ENCODE, "from": origin_id, "to": switch["id"]},
        "default_behaviour": "switch select=(none) + mode=priority resolves to input_01 = the reference depth, "
                             "so the rendered result is unchanged until the dropdown selects input_02",
        "pose_source": {"pose_studio": POSE_STUDIO, "depth_node": depth["id"]},
    }
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
