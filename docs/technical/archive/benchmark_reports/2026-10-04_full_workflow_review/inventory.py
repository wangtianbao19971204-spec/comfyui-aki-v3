"""Read-only inventory. Only writes redacted audit artifacts in this directory."""
import collections
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(r"G:\ComfyUI-aki-v3")
RUN = Path(__file__).resolve().parent
WF = ROOT / "ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json"
NATIVE_UI = {"MarkdownNote", "Fast Groups Muter (rgthree)", "Fast Groups Bypasser (rgthree)"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(name, value):
    (RUN / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def links(graph):
    keys = ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")
    return [v if isinstance(v, dict) else dict(zip(keys, v)) for v in graph.get("links", [])]


with urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=30) as response:
    info = json.load(response)
wf = read(WF)
branches = wf["extra"]["uap_workbench"]["branches"]
definitions = {d["id"]: d for d in wf["definitions"]["subgraphs"]}
audit = read(RUN / "audit_snapshot.json")
mapped = {(g["label"], n["id"]): n.get("mapped_widgets") for g in audit["graphs"] for n in g["nodes"]}
owned = {nid: b for b in branches for nid in b["nodeIds"]}
top_nodes = {n["id"]: n for n in wf["nodes"]}
parents = collections.defaultdict(list)
for node in wf["nodes"]:
    if node["type"] in definitions:
        parents[node["type"]].append(node["id"])
inventory = {"captured_at": datetime.datetime.now().astimezone().isoformat(), "workflow_sha256": sha(WF),
             "active_branch": wf["extra"]["uap_workbench"]["activeBranch"], "branches": [], "subgraphs": [],
             "nodes": [], "types": [], "groups": [], "mirror_mismatches": [], "unowned_top_nodes": [],
             "source_metadata_is_historical": wf["extra"].get("production_suite"), "guards": []}

for label, graph in [("TOP", wf)] + [(d["name"] + "/" + d["id"], d) for d in definitions.values()]:
    graph_links = links(graph)
    incoming = collections.defaultdict(list)
    outgoing = collections.defaultdict(list)
    by_id = {n["id"]: n for n in graph["nodes"]}
    for link in graph_links:
        incoming[link["target_id"]].append(link)
        outgoing[link["origin_id"]].append(link)
    for node in graph["nodes"]:
        branch = owned.get(node["id"]) if label == "TOP" else owned.get(parents.get(graph["id"], [None])[0])
        node_type = node["type"]
        schema = info.get(node_type, {})
        values = mapped.get((label, node["id"]))
        mismatch = []
        if values is not None and node.get("widgets_values_named"):
            mismatch = [k for k, v in values.items() if k in node["widgets_values_named"] and node["widgets_values_named"][k] != v]
        if mismatch:
            inventory["mirror_mismatches"].append({"graph": label, "id": node["id"], "type": node_type,
                                                   "fields": mismatch, "actual": {k: values[k] for k in mismatch},
                                                   "named": {k: node["widgets_values_named"][k] for k in mismatch}})
        model_values = node.get("widgets_values", []) if node_type in {"UNETLoader", "CLIPLoader", "VAELoader", "SAMLoader", "UltralyticsDetectorProvider", "UpscaleModelLoader", "LoraLoaderModelOnly", "AnimaLLLiteApply_sdscripts"} else None
        inventory["nodes"].append({"graph": label, "branch": branch["id"] if branch else None,
            "id": node["id"], "name": node.get("title", node_type), "class": node_type,
            "source": schema.get("python_module", "embedded subgraph" if node_type in definitions else "frontend-only"),
            "cnr_id": node.get("properties", {}).get("cnr_id"), "source_version": node.get("properties", {}).get("ver"),
            "current_mode": node.get("mode", 0), "saved_branch_mode": branch["modes"].get(str(node["id"])) if label == "TOP" and branch else None,
            "parent_instances": parents.get(graph.get("id"), []), "output_node": schema.get("output_node", False),
            "group": node.get("properties", {}).get("uap_layout_group"), "description": node.get("properties", {}).get("label"),
            "models": model_values, "parameters": values,
            "inputs": [{"name": node.get("inputs", [])[l["target_slot"]]["name"], "node": l["origin_id"], "slot": l["origin_slot"]} for l in incoming[node["id"]]],
            "consumers": [{"node": l["target_id"], "slot": l["target_slot"]} for l in outgoing[node["id"]]],
            "position": node.get("pos"), "size": node.get("size"), "input_count": len(node.get("inputs", [])),
            "output_count": len(node.get("outputs", []))})

for b in branches:
    branch_nodes = [n for n in inventory["nodes"] if n["graph"] == "TOP" and n["branch"] == b["id"]]
    inventory["branches"].append({"id": b["id"], "name": b["label"], "node_count": len(branch_nodes),
        "current_modes": dict(collections.Counter(n["current_mode"] for n in branch_nodes)),
        "saved_modes": dict(collections.Counter(n["saved_branch_mode"] for n in branch_nodes)),
        "stages": b["stages"], "subgraphs": [n["id"] for n in branch_nodes if n["class"] in definitions]})
inventory["unowned_top_nodes"] = [n["id"] for n in wf["nodes"] if n["id"] not in owned]
for d in definitions.values():
    inventory["subgraphs"].append({"id": d["id"], "name": d["name"], "node_count": len(d["nodes"]),
        "instances": parents[d["id"]], "inputs": [{"name": p["name"], "type": p["type"]} for p in d.get("inputs", [])],
        "outputs": [{"name": p["name"], "type": p["type"]} for p in d.get("outputs", [])],
        "proxyWidgets": d.get("proxyWidgets"), "instance_widgets": [top_nodes[n].get("widgets_values") for n in parents[d["id"]]]})
for group in wf["groups"]:
    inventory["groups"].append({"name": group["title"], "bounds": group.get("bounding"), "color": group.get("color"),
        "assigned_nodes": [n["id"] for n in inventory["nodes"] if n["graph"] == "TOP" and n["group"] == group["title"]],
        "navigation": [[b["id"], s["id"]] for b in branches for s in b["stages"] if group["title"] in s["groups"]]})
for typ in sorted({n["class"] for n in inventory["nodes"]}):
    ns = [n for n in inventory["nodes"] if n["class"] == typ]
    inventory["types"].append({"type": typ, "source": ns[0]["source"], "count": len(ns),
         "ids": [n["id"] for n in ns], "registered": typ in info, "frontend_only": typ in NATIVE_UI,
         "embedded_subgraph": typ in definitions, "category": info.get(typ, {}).get("category"),
         "description": info.get(typ, {}).get("description")})
related = []
for path in sorted((ROOT / "ComfyUI/user/default/workflows").glob("*.json")):
    if not path.name.startswith(("生产套件_", "生产扩展_", "检测模板_", "实验模板_", "UAP统一")):
        continue
    data = read(path)
    graphs = [data] + data.get("definitions", {}).get("subgraphs", [])
    types = {n["type"] for graph in graphs for n in graph.get("nodes", [])}
    sg_ids = {g["id"] for g in graphs[1:]}
    template = ROOT / "production_tools/templates" / path.name
    related.append({"name": path.name, "path": str(path), "sha256": sha(path),
        "top_nodes": len(data.get("nodes", [])), "subgraphs": len(graphs) - 1,
        "missing_types": sorted(types - set(info) - sg_ids - NATIVE_UI),
        "template_exists": template.is_file(), "template_matches": sha(path) == sha(template) if template.is_file() else None,
        "usdu": [{"id": n["id"], "title": n.get("title"), "values": n.get("widgets_values")} for g in graphs for n in g.get("nodes", []) if n["type"] == "UltimateSDUpscale"]})
    inventory["guards"].append({"path": str(path), "sha256": sha(path)})
inventory["related_workflows"] = related
for path in [ROOT / "production_tools/templates/UAP统一生产工作台_v2.json",
    ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/runtime_controls.js",
    ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/workbench_shell.js",
    ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/studio.css",
    ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js",
    ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_workbench.js",
    ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data/prompt_selector/data.json"]:
    if path.is_file():
        inventory["guards"].append({"path": str(path), "sha256": sha(path)})
save("inventory.json", inventory)
lines = []
for b in inventory["branches"]:
    lines.append(f"\n{b['id']} | {b['name']} | {b['node_count']} nodes | current {b['current_modes']} | saved {b['saved_modes']}")
    for n in inventory["nodes"]:
        if n["graph"] == "TOP" and n["branch"] == b["id"]:
            lines.append(f"{n['id']} | mode {n['current_mode']}/{n['saved_branch_mode']} | {n['name']} | {n['class']} | {n['source']} | {n['group']}")
for g in inventory["subgraphs"]:
    lines.append(f"\nSUBGRAPH {g['name']} | {g['id']} | parents {g['instances']}")
    for n in inventory["nodes"]:
        if n["graph"].endswith(g["id"]):
            lines.append(f"{n['id']} | mode {n['current_mode']} | {n['name']} | {n['class']} | {n['source']}")
            if n["models"] is not None:
                lines.append("  models " + json.dumps(n["models"], ensure_ascii=False))
            if n["parameters"] is not None:
                p = {k: v for k, v in n["parameters"].items() if k not in {"wildcard", "text", "prompt"}}
                lines.append("  parameters " + json.dumps(p, ensure_ascii=False))
(RUN / "COMPONENT_INDEX.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps({"branches": [{k: b[k] for k in ("id", "node_count", "current_modes", "saved_modes")} for b in inventory["branches"]],
    "total_nodes": len(inventory["nodes"]), "node_types": len(inventory["types"]),
    "related_workflows": len(related), "unowned_top_nodes": inventory["unowned_top_nodes"],
    "mirror_mismatches": inventory["mirror_mismatches"]}, ensure_ascii=False, indent=2))
