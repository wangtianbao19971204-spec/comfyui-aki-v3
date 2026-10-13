"""Repair standalone Krea2 control routing in source workflows, never deploy/enqueue."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from simplify_anima_control import node

ROOT = Path(__file__).resolve().parents[1]
FILENAME = "生产套件_03_Krea2_一体化生产_v2.json"
REVISION = 1
REQUIRED = {449: "DazzleSwitch", 501: "GetImageSize", 504: "ImageCompositeMasked",
            506: "LoadImage", 513: "VNCCS_PoseStudio", 433: "DepthAnythingV2Preprocessor",
            534: "Krea2ControlImageEncode", 535: "Krea2ControlLoRALoader", 536: "Krea2ControlApply"}


def slot(item, name):
    return next(i for i, port in enumerate(item["inputs"]) if port["name"] == name)


def origin(data, target, input_name):
    item = next(n for n in data["nodes"] if n["id"] == target)
    link_id = item["inputs"][slot(item, input_name)].get("link")
    link = next((link for link in data["links"] if link[0] == link_id), None)
    return tuple(link[1:3]) if link else None


class Wiring:
    def __init__(self, data):
        self.data = data
        self.nodes = {n["id"]: n for n in data["nodes"]}
        self.last_link = max(data.get("last_link_id", 0), *(link[0] for link in data["links"]))

    def connect(self, source, source_slot, target, input_name, kind="IMAGE"):
        target_slot = slot(self.nodes[target], input_name)
        target_port = self.nodes[target]["inputs"][target_slot]
        existing = next((link for link in self.data["links"] if link[0] == target_port.get("link")), None)
        if existing is None:
            self.last_link += 1
            existing = [self.last_link, source, source_slot, target, target_slot, kind]
            self.data["links"].append(existing)
            target_port["link"] = self.last_link
        else:
            old_output = self.nodes[existing[1]]["outputs"][existing[2]]
            old_output["links"] = [link for link in old_output.get("links") or [] if link != existing[0]]
            existing[1:] = [source, source_slot, target, target_slot, kind]
        output = self.nodes[source]["outputs"][source_slot]
        output["links"] = [*(output.get("links") or []), existing[0]]
        self.data["last_link_id"] = self.last_link


def image_switch(node_id, title, select, labels, pos):
    item = node(node_id, "DazzleSwitch", title, [select, "priority", 0],
                inputs=[("input_01", "*"), ("input_02", "*"), ("input_03", "*"),
                        ("select", "COMBO"), ("mode", "COMBO"), ("select_override", "INT")],
                outputs=[("output", "IMAGE"), ("selected_index", "INT")], pos=pos)
    item["size"] = [340, 180]
    for i, label in enumerate(labels):
        item["inputs"][i].update(label=label, shape=7)
    for port in item["inputs"][3:]:
        port["widget"] = {"name": port["name"]}
    item["properties"]["Node name for S&R"] = "DazzleSwitch"
    item["widgets_values_named"] = {"select": select, "mode": "priority", "select_override": 0}
    return item


def validate_routing(data):
    roles = data["extra"]["krea2_control_routing"]["roles"]
    expected = {
        (roles["source"], "input_01"): (449, 0),
        (roles["source"], "input_02"): (roles["pose_depth"], 0),
        (roles["pose_depth"], "image"): (513, 0),
        (501, "image"): (roles["source"], 0),
        (504, "destination"): (roles["source"], 0),
        (roles["erase"], "input_01"): (504, 0),
        (roles["erase"], "input_02"): (roles["source"], 0),
        (534, "control_image"): (roles["erase"], 0),
        (536, "control_latent"): (534, 0),
    }
    for (target, name), source in expected.items():
        if origin(data, target, name) != source:
            raise ValueError(f"Krea2 control routing is inconsistent at {target}.{name}; review before migration.")


def migrate(data):
    result = copy.deepcopy(data)
    nodes = {item["id"]: item for item in result["nodes"]}
    if any(nodes.get(key, {}).get("type") != kind for key, kind in REQUIRED.items()):
        raise ValueError("Expected the legacy standalone Krea2 production workflow; no data was changed.")
    previous = result.get("extra", {}).get("krea2_control_routing")
    if previous:
        if previous.get("revision") != REVISION:
            raise ValueError("Unsupported Krea2 routing revision; review before migration.")
        validate_routing(result)
        return result
    legacy = {(501, "image"): (449, 0), (504, "destination"): (449, 0),
              (534, "control_image"): (433, 0), (536, "control_latent"): (534, 0)}
    for (target, name), expected in legacy.items():
        if origin(result, target, name) != expected:
            raise ValueError(f"Custom legacy wiring at {target}.{name} requires explicit review.")

    first = max(result.get("last_node_id", 0), *nodes) + 1
    source_id, depth_id, erase_id, note_id = range(first, first + 4)
    source = image_switch(source_id, "[05R1] 控制来源：参考图 / VNCCS", "input_01",
                          ("参考图处理结果", "VNCCS 姿态深度"), (3600, 1910))
    erase = image_switch(erase_id, "[05R2] 使用擦线：启用 / 旁路", "input_02",
                         ("启用擦线（需要有效遮罩）", "旁路：保留控制图"), (3970, 1910))
    depth = copy.deepcopy(nodes[433])
    depth.update(id=depth_id, title="[09R] VNCCS 姿态深度", pos=[7080, 3320],
                 order=max(item.get("order", 0) for item in result["nodes"]) + 1,
                 mode=nodes[513].get("mode", 0))
    for port in depth["inputs"]:
        port["link"] = None
    for port in depth["outputs"]:
        port["links"] = []
    # The same native chain as UAP K2: rendered Studio image -> Depth -> source
    # selection -> optional black-mask composite -> Encode -> existing Apply.
    # Keep Studio's current mode, capture and reference; no hidden auto-enable.
    note = node(note_id, "MarkdownNote", "控制来源与擦线使用说明", [
        "## 控制来源与擦线\n\n"
        "先启用原有 Krea2 控制组，再在【控制来源】选择参考图或 VNCCS。"
        "参考图使用原【控制图选择】的线稿／深度设置；VNCCS 需先启用原 VNCCS 组，"
        "其姿态图会转成深度图后送入同一控制链。\n\n"
        "【使用擦线】默认旁路。需要擦除时，在原【擦线遮罩】节点打开蒙版编辑器，"
        "绘制并保存有效遮罩，再选择【启用擦线】。原图片与文件名不会被自动替换。"
        "普通 RGB 图片没有 alpha，输出为零遮罩，不能擦除；仅把 RGB 白色画黑并不会创建遮罩。"
        "在【遮罩预览】确认白色区域：白色 MASK 才是擦除区（保存图的透明处，MASK=1-alpha）。\n\n"
        "来源与擦线选择均进入控制编码；最后的编码预览显示实际送入模型的控制图。"
        "Turbo 底模、种子、采样、尺寸、提示词、LoRA、细化与二放设置沿用原值。"
    ], pos=(4370, 1650))
    note["size"] = [510, 520]
    result["nodes"].extend((source, depth, erase, note))
    result["last_node_id"] = note_id
    wiring = Wiring(result)
    wiring.connect(449, 0, source_id, "input_01")
    wiring.connect(513, 0, depth_id, "image")
    wiring.connect(depth_id, 0, source_id, "input_02")
    wiring.connect(source_id, 0, 501, "image")
    wiring.connect(source_id, 0, 504, "destination")
    wiring.connect(504, 0, erase_id, "input_01")
    wiring.connect(source_id, 0, erase_id, "input_02")
    wiring.connect(erase_id, 0, 534, "control_image")
    result.setdefault("extra", {})["krea2_control_routing"] = {
        "revision": REVISION,
        "roles": {"reference_selector": 449, "source": source_id, "pose": 513,
                  "pose_depth": depth_id, "erase": erase_id, "mask": 506,
                  "composite": 504, "encode": 534, "loader": 535, "apply": 536, "note": note_id},
        "mask_semantics": "MASK=1-alpha; RGB input produces zero MASK. Keep user filename; save a mask in the native editor.",
    }
    validate_routing(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-source", action="store_true", help="Write only this checkout's snapshot/runtime source files.")
    args = parser.parse_args()
    if args.write_source and not (ROOT.parent.name == "snapshot" and (ROOT.parents[1] / "AGENTS.md").is_file()):
        parser.error("Writing is restricted to maintained snapshot/runtime sources; runtime deployment is a separate action.")
    for directory in (ROOT / "ComfyUI/user/default/workflows", ROOT / "production_tools/templates"):
        path = directory / FILENAME
        text = path.read_text(encoding="utf-8")
        indent = len(text.splitlines()[1]) - len(text.splitlines()[1].lstrip())
        before = json.loads(text)
        after = migrate(before)
        print(json.dumps({"file": str(path.relative_to(ROOT)), "changed": before != after,
                          "written": bool(args.write_source and before != after)}, ensure_ascii=False))
        if args.write_source and before != after:
            path.write_bytes((json.dumps(after, ensure_ascii=False, indent=indent) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
