"""Apply metadata/comparison fixes to a candidate, preserving generation inputs."""
import copy
import json
import re
import struct

from freeze import ROOT, RUN, read, save, sha

WORKFLOW = "ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json"
TEMPLATE = "production_tools/templates/UAP统一生产工作台_v2.json"


def model_contracts():
    records = read(RUN / "model_headers.json")
    models = {}
    for record in records:
        if record["class"] != "UNETLoader":
            continue
        path = ROOT / record["path"]
        with path.open("rb") as stream:
            size = struct.unpack("<Q", stream.read(8))[0]
            header = json.loads(stream.read(size))
        keys = list(header)
        if any("adaln_modulation_cross_attn.1.weight" in key for key in keys):
            assert record["blocks"] in (28, 40)
            family = "anima29" if record["blocks"] == 40 else "anima"
        elif any("blocks.0.attn.qknorm.knorm.scale" in key for key in keys) and record["blocks"] == 28:
            family = "krea2"
        else:
            raise ValueError("Unrecognized model architecture: " + record["name"])
        models[record["name"].replace("\\", "/")] = {"family": family, "blocks": record["blocks"]}
    return {"version": 1, "verified_at": "2026-10-05", "evidence": "Local safetensors tensor keys and block counts; current known encoder/VAE pairs. Not a LoRA or image-quality certification.",
            "models": models,
            "families": {
                "anima": {"label": "Anima 原版", "clip": ["anima_baseV10_txt.safetensors"], "clip_type": "stable_diffusion", "vae": ["qwen_image_vae.safetensors"]},
                "anima29": {"label": "Anima 2.9B", "clip": ["anima_baseV10_txt.safetensors"], "clip_type": "stable_diffusion", "vae": ["qwen_image_vae.safetensors"]},
                "krea2": {"label": "Krea2", "clip": ["qwen3-vl-4b-heretic.safetensors"], "clip_type": "krea2", "vae": ["krea2RealVae_v10.safetensors"]}}}


def stage():
    wf = read(RUN / "before" / WORKFLOW)
    before = copy.deepcopy(wf)
    nodes = {n["id"]: n for n in wf["nodes"]}
    links = {link[0]: link for link in wf["links"]}

    def source(node_id, name):
        port = next(p for p in nodes[node_id]["inputs"] if p["name"].lower() == name.lower())
        return links[port["link"]][1]

    def rewire(node_id, name, origin_id):
        port = next(p for p in nodes[node_id]["inputs"] if p["name"] == name)
        link = links[port["link"]]
        previous = nodes[link[1]]["outputs"][link[2]]["links"]
        previous.remove(link[0])
        link[1], link[2] = origin_id, 0
        output = nodes[origin_id]["outputs"][0]
        if output.get("links") is None:
            output["links"] = []
        output["links"].append(link[0])

    comparison_rows = []
    for branch, base, foot, face, eye, comparisons in (
        ("a1", 1016, 1017, 1032, 1308, (1033, 1034, 1035, 1036)),
        ("a29", 1084, 1085, 1103, 1309, (1107, 1108, 1109, 1110))):
        region = source(face, "image")
        stages = [(base, foot, "基础图 vs 手脚后"), (foot, region, "手脚后 vs 区域后"),
                  (region, face, "区域后 vs 脸后"), (face, eye, "脸后 vs 眼后")]
        for index, (node_id, (left, right, label)) in enumerate(zip(comparisons, stages), 1):
            rewire(node_id, "image_a", left)
            rewire(node_id, "image_b", right)
            nodes[node_id]["title"] = f"[10V-{index}] {label}"
            nodes[node_id].setdefault("properties", {})["label"] = "左图为前阶段，右图为后阶段；关闭的细化会原图透传。"
            comparison_rows.append({"branch": branch, "node": node_id, "a": left, "b": right, "label": label})

    snapshot = read(ROOT / "benchmark_reports/2026-10-04_full_workflow_review/audit_snapshot.json")
    mapped = {n["id"]: n["mapped_widgets"] for graph in snapshot["graphs"] for n in graph["nodes"] if n.get("mapped_widgets")}
    mirrors = []
    for graph in [wf] + wf["definitions"]["subgraphs"]:
        for node in graph["nodes"]:
            if node.get("widgets_values_named") and node["id"] in mapped:
                for key, value in mapped[node["id"]].items():
                    if key in node["widgets_values_named"] and node["widgets_values_named"][key] != value:
                        mirrors.append({"node": node["id"], "field": key})
                        node["widgets_values_named"][key] = value
    for node_id, model, cfg, sampler, scheduler in ((1051, "Anima 原版", 7, "res_multistep", "beta"), (1112, "Anima 2.9B", 3.5, "euler", "sgm_uniform")):
        nodes[node_id]["title"] = f"[11B] {model} 分块二放 · 1.5×"
        nodes[node_id]["properties"]["label"] = f"沿用 {model} 主线 LoRA，细化后进行 1.5× USDU；当前12步 / CFG {cfg} / {sampler} / {scheduler} / denoise 0.12。接缝 Half Tile + Intersections / 0.42；默认关闭，参数与主采样独立。"
    for node_id, text in ((1026, "当前预设：30步 / CFG 7 / res_multistep / beta。主种子由外置种子节点提供；不自动同步局部细化和二放。"),
                          (1096, "当前预设：28步 / CFG 3.5 / euler / sgm_uniform。主种子由外置种子节点提供；不自动同步局部细化和二放。")):
        nodes[node_id]["properties"]["label"] = text
    for node_id in (1037, 1111, 1158):
        nodes[node_id]["title"] = "[11A] OmniSR · USDU 像素预放大模型"
        nodes[node_id]["properties"]["label"] = "仅供本分支 USDU 使用。模型原生4×，最终输出按 USDU 的 upscale_by；当前为输入的1.5×。"
    nodes[1192]["title"] = "[11B] Krea2 分块二放 · 1.5×"
    for node in wf["nodes"]:
        if node["type"] == "PrimitiveBoolean" and "二放" in node.get("title", ""):
            prefix = re.match(r"^\[[^\]]+\]", node["title"]).group()
            family = "Krea2" if "Krea2" in node["title"] else "Anima"
            node["title"] = f"{prefix} 启用 {family} 分块二放（1.5×，可选）"
        if node["type"] == "easy seed":
            node["title"] = re.sub("随机种子", "主种子与模式", node.get("title", "主种子与模式"))
        if node["id"] in (1061, 1077, 1232):
            node["title"] = "提示词草稿 · 需采用到主输入"
            node.setdefault("properties", {})["label"] = "此字段没有连接采样条件，编辑后不会自动影响生成；请明确采用到当前分支主输入。"
        if node["id"] == 1287:
            node.setdefault("properties", {})["uap_legacy_lllite"] = True
    renamed_groups = {group["title"]: group["title"].replace("原生二放分级路由（由操作台开关）", "分块二放路由 · 1.5×（可选）") for group in wf["groups"] if "原生二放分级路由" in group["title"]}
    for group in wf["groups"]:
        group["title"] = renamed_groups.get(group["title"], group["title"])
    def rename_references(value):
        if isinstance(value, str):
            for old_name, new_name in renamed_groups.items():
                value = value.replace(old_name, new_name)
            return value
        if isinstance(value, list):
            return [rename_references(item) for item in value]
        if isinstance(value, dict):
            return {key: rename_references(item) for key, item in value.items()}
        return value
    wf["extra"] = rename_references(wf["extra"])
    for node in wf["nodes"]:
        node["properties"] = rename_references(node.get("properties", {}))
    for branch in wf["extra"]["uap_workbench"]["branches"]:
        family = {"a1": "anima", "a29": "anima29", "k2": "krea2", "ext04": "krea2", "ext05": "anima29", "ext07": "anima"}.get(branch["id"])
        if family:
            branch["modelFamily"] = family
        if branch["id"] == "ext05":
            branch["label"] = "Anima 2.9B 裁剪精修回贴"
        if branch["id"] == "ext07":
            branch["label"] = "Anima 原版四边扩图"
    wf["extra"]["uap_model_contracts"] = model_contracts()
    wf["extra"]["uap_release"] = {"version": "2026-10-05.product-repair", "canonical_source": TEMPLATE,
        "legacy_sources": "Independent production workflows are historical snapshots, not the current UAP build source.",
        "rule": "Read-only validation; export candidates from canonical template. Publish only with baseline and rollback guards."}
    # The dead size-read node is deliberately retained: no unrelated node removal.
    assert len(wf["nodes"]) == len(before["nodes"]) == 293
    for graph, original in zip([wf] + wf["definitions"]["subgraphs"], [before] + before["definitions"]["subgraphs"]):
        for node, old in zip(graph["nodes"], original["nodes"]):
            assert node["widgets_values"] == old["widgets_values"] if "widgets_values" in old else "widgets_values" not in node
            assert node["mode"] == old["mode"]
    assert len(wf["links"]) == len(before["links"])
    for name in (WORKFLOW, TEMPLATE):
        path = RUN / "candidate" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        save(path, wf)
    save(RUN / "workflow_changes.json", {"comparisons": comparison_rows, "mirrors": mirrors,
         "generation_widget_values_unchanged": True, "all_modes_unchanged": True,
         "candidate_sha256": sha(RUN / "candidate" / WORKFLOW)})
    print(json.dumps({"comparisons": len(comparison_rows), "mirror_fields": len(mirrors), "models": len(wf["extra"]["uap_model_contracts"]["models"]), "generation_values_preserved": True}))


if __name__ == "__main__":
    stage()
