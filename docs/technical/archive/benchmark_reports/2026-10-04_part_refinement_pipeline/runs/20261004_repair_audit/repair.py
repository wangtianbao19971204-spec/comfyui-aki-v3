"""Stage the audited workflow repairs; publishing is explicit and hash guarded."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(r"G:\ComfyUI-aki-v3")
RUN = Path(__file__).resolve().parent
WF = Path("ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json")
TEMPLATE = Path("production_tools/templates/UAP统一生产工作台_v2.json")
EXT = Path("ComfyUI/user/default/workflows/生产扩展_10_部位细化_Anima.json")
NEUTRAL = "An adult traveler wearing a blue coat, standing in a peaceful garden, daylight, illustration"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_links(graph):
    keys = ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")
    return [dict(zip(keys, link)) if isinstance(link, list) else copy.deepcopy(link)
            for link in graph.get("links", [])]


class Graph:
    def __init__(self, data, sub=False):
        self.data, self.sub = data, sub
        self.nodes = {n["id"]: n for n in data["nodes"]}
        self.links = normalized_links(data)
        self.last = max([l["id"] for l in self.links] + [0])

    def slot(self, nid, name):
        return next(i for i, p in enumerate(self.nodes[nid]["inputs"]) if p["name"] == name)

    def connect(self, src, out, dest, port, kind):
        self.last += 1
        slot = port if isinstance(port, int) else self.slot(dest, port)
        self.links = [l for l in self.links if (l["target_id"], l["target_slot"]) != (dest, slot)]
        self.links.append(dict(id=self.last, origin_id=src, origin_slot=out,
                               target_id=dest, target_slot=slot, type=kind))

    def remove(self, ids):
        self.data["nodes"] = [n for n in self.data["nodes"] if n["id"] not in ids]
        self.links = [l for l in self.links if l["origin_id"] not in ids and l["target_id"] not in ids]
        self.nodes = {n["id"]: n for n in self.data["nodes"]}

    def finish(self):
        for n in self.nodes.values():
            for p in n.get("inputs", []):
                p["link"] = None
            for p in n.get("outputs", []):
                p["links"] = []
        if self.sub:
            for p in self.data["inputs"] + self.data["outputs"]:
                p["linkIds"] = []
        for l in self.links:
            if l["origin_id"] == -10:
                self.data["inputs"][l["origin_slot"]]["linkIds"].append(l["id"])
            else:
                self.nodes[l["origin_id"]]["outputs"][l["origin_slot"]]["links"].append(l["id"])
            if l["target_id"] == -20:
                self.data["outputs"][l["target_slot"]]["linkIds"].append(l["id"])
            else:
                self.nodes[l["target_id"]]["inputs"][l["target_slot"]]["link"] = l["id"]
        self.data["links"] = self.links if self.sub else [list(l.values()) for l in self.links]
        if self.sub:
            self.data["state"]["lastNodeId"] = max(self.nodes, default=0)
            self.data["state"]["lastLinkId"] = self.last
        else:
            self.data["last_node_id"] = max(self.nodes, default=0)
            self.data["last_link_id"] = self.last


def set_widget(node, name, value):
    values = node.get("widgets_values", [])
    keys = []
    for p in node.get("inputs", []):
        if "widget" in p:
            key = p["name"]
            keys.append(key)
            if key in {"seed", "noise_seed"} and not any(i["name"] == "control_after_generate" for i in node["inputs"]):
                keys.append("control_after_generate")
    assert name in keys, (node["id"], name, keys)
    assert len(keys) == len(values), (node["id"], len(keys), len(values))
    values[keys.index(name)] = value
    if "widgets_values_named" in node:
        node["widgets_values_named"][name] = value


def single_part(source, target, part, code, start):
    labels = {"hand": "手部", "foot": "脚部", "face": "脸部", "eye": "眼睛"}
    model_key = "hand" if part == "foot" else {"eye": "Eyeful"}.get(part, part)
    provider = next(n for n in source["nodes"] if n["type"] == "UltralyticsDetectorProvider"
                    and model_key in n["widgets_values"][0])
    links = normalized_links(source)
    detector_id = next(l["target_id"] for l in links if l["origin_id"] == provider["id"])
    detail_id = next(l["target_id"] for l in links if l["origin_id"] == detector_id)
    lookup = {n["id"]: n for n in source["nodes"]}
    sam = next(n for n in source["nodes"] if n["type"] == "SAMLoader")
    nodes = copy.deepcopy([provider, sam, lookup[detector_id], lookup[detail_id]])
    for i, n in enumerate(nodes):
        n["id"] = start + i
        n["mode"] = 0
        n["order"] = i
        n["pos"] = [[30, 30], [30, 160], [400, 30], [790, 30]][i]
        n["title"] = f"[{code}{i + 1}] {labels[part]} " + ["YOLO 定位", "SAM 蒙版", "检测与蒙版求交", "局部重绘回贴"][i]
    if part == "foot":
        set_widget(nodes[0], "model_name", "bbox/adetailerFootYolov8x_v20.pt")
        for k, v in {"bbox_threshold": .35, "crop_factor": 3., "drop_size": 16, "post_dilation": 8}.items():
            set_widget(nodes[2], k, v)
        set_widget(nodes[3], "wildcard", "")
    for k, v in {"steps": 16, "force_inpaint": True, "noise_mask_feather": 20}.items():
        set_widget(nodes[3], k, v)
    target["name"] = f"[{code}] {labels[part]}细化"
    target["nodes"], target["links"], target["groups"] = nodes, [], []
    target["extra"] = {"ue_links": [], "links_added_by_ue": [], "uap_refinement": part}
    target["inputNode"]["bounding"] = [-190, 30, 150, 180]
    target["outputNode"]["bounding"] = [1190, 30, 150, 80]
    g = Graph(target, sub=True)
    g.connect(start, 0, start + 2, "bbox_detector", "BBOX_DETECTOR")
    g.connect(start + 1, 0, start + 2, "sam_model_opt", "SAM_MODEL")
    g.connect(-10, 0, start + 2, "image", "IMAGE")
    g.connect(start + 2, 0, start + 3, "segs", "SEGS")
    for i, p in enumerate(target["inputs"]):
        g.connect(-10, i, start + 3, p["name"], p["type"])
    g.connect(start + 3, 0, -20, 0, "IMAGE")
    g.finish()


def main():
    wf = read(RUN / "before" / WF)
    original = copy.deepcopy(wf)
    g = Graph(wf)
    definitions = {s["id"]: s for s in wf["definitions"]["subgraphs"]}
    olddefs = copy.deepcopy(definitions)
    labels = {"A": "手部细化", "B": "脚部细化", "C": "脸部细化", "D": "NSFW 标准细化", "E": "NSFW 快速细化", "F": "眼睛细化"}
    created = []
    for kit, suffix, ids, eyeid, ctrl, base in [
        ("a1", "A1 原版", [1050, 1017, 1032, 1031, 1018], 1292, 1053, 130000),
        ("a29", "A29 2.9B", [1106, 1085, 1103, 1102, 1086], 1293, 1125, 130100),
    ]:
        eyeid = max(g.nodes) + 1
        branch = next(b for b in wf["extra"]["uap_workbench"]["branches"] if b["id"] == kit)
        source = olddefs[g.nodes[ids[0]]["type"]]
        eye = copy.deepcopy(source)
        eye["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "uap-repair-eye-" + kit))
        for p in eye["inputs"] + eye["outputs"]:
            p["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, eye["id"] + p["name"] + p["type"]))
        wf["definitions"]["subgraphs"].append(eye)
        definitions[eye["id"]] = eye
        instance = copy.deepcopy(g.nodes[ids[0]])
        instance.update(id=eyeid, type=eye["id"], pos=[1370, 5220 if kit == "a1" else 11530])
        wf["nodes"].append(instance)
        g.nodes[eyeid] = instance
        branch["nodeIds"].append(eyeid)
        ids.append(eyeid)
        for index, part, code in [(0, "hand", "A"), (1, "foot", "B"), (2, "face", "C"), (5, "eye", "F")]:
            n = g.nodes[ids[index]]
            sg = definitions[n["type"]]
            single_part(source, sg, part, "10" + code, base + index * 10)
        titles = {}
        for index, nid in enumerate(ids):
            code = "ABCDEF"[index]
            n = g.nodes[nid]
            title = f"FX-10{code} {labels[code]} · {suffix}"
            titles[code] = title
            n["title"] = f"[10{code}] {labels[code]}"
            n["properties"]["uap_layout_group"] = title
            n["properties"]["uap_refinement"] = {"A":"hand", "B":"foot", "C":"face", "D":"region_standard", "E":"region_fast", "F":"eye"}[code]
            if code in "DE":
                n["properties"]["uap_exclusive_refinement"] = "region"
            n["mode"] = 4 if kit == wf["extra"]["uap_workbench"]["activeBranch"] else 2
            branch["modes"][str(nid)] = 4
            if code != "F":
                group = next(x for x in wf["groups"] if x["title"].startswith("FX-10" + code + " ") and x["title"].endswith(suffix))
                group["title"] = title
            else:
                group = dict(id=max(x["id"] for x in wf["groups"]) + 1, title=title,
                             bounding=[n["pos"][0]-20, n["pos"][1]-60, 432, 254], color="#73596B", flags={})
                wf["groups"].append(group)
        # New independent eye component receives the same model/conditioning sources as the hand component.
        for l in list(g.links):
            if l["target_id"] == ids[0] and l["target_slot"] > 0:
                g.connect(l["origin_id"], l["origin_slot"], eyeid, l["target_slot"], l["type"])
        # Preserve incoming base image; route hands -> feet -> regional preset -> face -> eyes.
        chain = [ids[i] for i in [0, 1, 3, 4, 2, 5]]
        for left, right in zip(chain, chain[1:]):
            g.connect(left, 0, right, "image", "IMAGE")
        for l in g.links:
            if l["type"] == "IMAGE" and l["origin_id"] == ids[4] and l["target_id"] not in ids:
                l["origin_id"] = eyeid
        # Stage comparisons must compare the fully refined image, not the former multi-part 10A output.
        for l in g.links:
            if l["type"] == "IMAGE" and l["origin_id"] == ids[0] and l["target_id"] not in ids:
                l["origin_id"] = eyeid
        ordered = [titles[c] for c in "ABDECF"]
        g.nodes[ctrl]["properties"]["customSortAlphabet"] = ",".join(ordered)
        stage = next(s for s in branch["stages"] if s["id"] == "refine")
        stage["groups"] = ordered + [t for t in stage["groups"] if not t.startswith("FX-")]
        for nid in branch["nodeIds"]:
            n = g.nodes[nid]
            if n["type"] in definitions and definitions[n["type"]]["name"].startswith(("[05]", "[09]")):
                n["properties"]["uap_legacy_lllite"] = True
        created.append((branch, ids))
    g.remove({1230})
    for b in wf["extra"]["uap_workbench"]["branches"]:
        b["nodeIds"] = [i for i in b["nodeIds"] if i in g.nodes]
        b["modes"] = {k: v for k, v in b["modes"].items() if int(k) in b["nodeIds"]}
    for sg in wf["definitions"]["subgraphs"]:
        if any(n["id"] in {104002, 114002} for n in sg["nodes"]):
            sub = Graph(sg, sub=True)
            sub.remove({104002, 114002})
            sub.finish()
    for n in wf["nodes"]:
        if "title" in n:
            n["title"] = n["title"].replace("04A", "00W-1") if "复制" in n["title"] else n["title"]
        if n["type"] == "MarkdownNote" and isinstance(n.get("widgets_values"), list):
            n["widgets_values"] = [v.replace("04A", "00W-1") if isinstance(v, str) else v for v in n["widgets_values"]]
    for sg in wf["definitions"]["subgraphs"]:
        for n in sg["nodes"]:
            if "复制" in n.get("title", ""):
                n["title"] = n["title"].replace("04A", "00W-1")
    note = "# 生产路线与默认值\n基础采样 → 手 → 脚 → 区域细化（标准/快速二选一）→ 脸 → 眼 → 可选 1.5× 二次放大 → 保存。\n所有细化默认旁路，按需从工作台选择；不含人体、头发、四肢、服装或独立皮肤细化。\n反推结果是候选，请复制到 00W-1 正向框。主采样、各细化子图及二放参数独立，不自动同步；复现终稿须分别固定各阶段种子。\n细化启用时单任务 batch 必须为 1；多张请排队多个单张任务。Anima 2.9B 不可启用原版 28 层 LLLite。\n08/09 为独立 2×/4× 交付工具，不自动接主流程。"
    g.nodes[1040]["widgets_values"] = [note]
    g.nodes[1225]["widgets_values"] = ["# Krea2 从创意到终稿\n00W-1 正向 + 常用负向 → 模型/LoRA → 主采样 → 可选 1.5× 二次放大（含缝补）→ 保存。\n输入图关闭为文生图；打开为图生图；同时启用遮罩为遮罩修复。\nKrea2 未接入 Anima 的部位细化。04 指令编辑、08/09 交付超分均为独立分支。\n反推仅提供候选，不自动覆盖正向；主采样与二放参数、种子分别设置。"]
    # Replace the unsafe positive example without echoing it to logs or receipts.
    n = g.nodes[1233]
    values = n["widgets_values"]
    assert isinstance(values, list) and isinstance(values[0], str)
    values[0] = NEUTRAL
    if isinstance(n.get("widgets_values_named"), dict):
        for key in n["widgets_values_named"]:
            if isinstance(n["widgets_values_named"][key], str) and n["widgets_values_named"][key] == original["nodes"][[x["id"] for x in original["nodes"]].index(1233)]["widgets_values"][0]:
                n["widgets_values_named"][key] = NEUTRAL
    wf["extra"]["uap_workbench"]["refinement_revision"] = "independent-parts-20261004"
    g.finish()
    save(RUN / "candidate" / WF.name, wf)
    # Standalone extension uses exactly the same 2.9B subgraphs, with neutral input and independent bypass switches.
    ext = read(RUN / "before" / EXT)
    keep = {1, 2, 3, 4, 5, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 50, 51}
    eg = Graph(ext)
    eg.remove(set(eg.nodes) - keep)
    eg.nodes[1]["widgets_values"][0] = "optimization_reference.png"
    if "widgets_values_named" in eg.nodes[1]:
        eg.nodes[1]["widgets_values_named"]["image"] = "optimization_reference.png"
    eg.nodes[1]["title"] = "输入待修图（运行前选择自己的图片）"
    ext["definitions"] = {"subgraphs": []}
    branch, ids = created[1]
    part_order = [ids[i] for i in [0, 1, 3, 4, 2, 5]]
    prompt_pairs = [(20, 21), (22, 23), (28, 29), (28, 29), (24, 25), (26, 27)]
    ext["groups"] = []
    for i, (nid, (positive, negative)) in enumerate(zip(part_order, prompt_pairs)):
        n = copy.deepcopy(g.nodes[nid])
        n["id"], n["mode"], n["pos"] = 100 + i, 4, [700 + i * 480, 140]
        n["properties"]["uap_layout_group"] = f"FX-{i+1:02d} " + n["title"]
        if len(n["inputs"]) > 6:
            n["widgets_values"] = [True, False]
            n["widgets_values_named"] = dict(female_anime_detector=True, male_realistic_detector=False)
        ext["nodes"].append(n)
        eg.nodes[n["id"]] = n
        ext["definitions"]["subgraphs"].append(copy.deepcopy(definitions[n["type"]]))
        for name, src, kind in [("image", 1 if i == 0 else n["id"] - 1, "IMAGE"), ("model", 5, "MODEL"), ("clip", 3, "CLIP"), ("vae", 4, "VAE"), ("positive", positive, "CONDITIONING"), ("negative", negative, "CONDITIONING")]:
            eg.connect(src, 0, n["id"], name, kind)
        ext["groups"].append(dict(id=i + 1, title=n["properties"]["uap_layout_group"], bounding=[n["pos"][0]-20, 80, 440, 320], color="#73596B", flags={}))
    eg.connect(105, 0, 50, "images", "IMAGE")
    eg.connect(105, 0, 51, "images", "IMAGE")
    controller = copy.deepcopy(g.nodes[1125])
    controller.update(id=106, mode=0, pos=[180, 700], title="部位细化开关（默认关闭）")
    controller["properties"].update(matchTitle="^FX-", customSortAlphabet=",".join(x["title"] for x in ext["groups"]))
    controller["properties"].pop("uap_layout_group", None)
    ext["nodes"].append(controller)
    eg.nodes[106] = controller
    ext["extra"] = {"uap_refinement_workflow": True, "description": "与 UAP 2.9B 同源子图。单图输入；默认全部关闭；区域标准/快速二选一；无二放。"}
    for i, nid in enumerate([1, 2, 3, 4, 5]):
        eg.nodes[nid]["pos"] = [180, 20 + i * 125]
    for i, nid in enumerate(range(20, 30)):
        eg.nodes[nid]["pos"] = [700 + (i // 2) * 480, 500 + (i % 2) * 240]
    eg.nodes[50]["pos"], eg.nodes[51]["pos"] = [3630, 140], [3630, 500]
    eg.finish()
    save(RUN / "candidate" / EXT.name, ext)
    manifest = []
    for f in (WF, TEMPLATE, EXT):
        candidate = RUN / "candidate" / (EXT.name if f == EXT else WF.name)
        manifest.append(dict(path=str(f), before=digest(RUN / "before" / f), after=digest(candidate)))
    save(RUN / "workflow_manifest.json", manifest)
    print(json.dumps({"staged": True, "nodes": len(wf["nodes"]), "subgraphs": len(wf["definitions"]["subgraphs"]), "extension_nodes": len(ext["nodes"])}))
    if "--publish" in sys.argv:
        for row in manifest:
            assert digest(ROOT / row["path"]) == row["before"], "Production drift: " + row["path"]
        for row in manifest:
            src = RUN / "candidate" / (EXT.name if Path(row["path"]) == EXT else WF.name)
            shutil.copy2(src, ROOT / row["path"])
        print("Published three guarded workflow files.")


if __name__ == "__main__":
    main()
