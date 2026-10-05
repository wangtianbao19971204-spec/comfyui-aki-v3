"""Read-only production audit; writes evidence only beside this script."""
import collections
import datetime
import hashlib
import json
from pathlib import Path
import urllib.request
import sys

ROOT = Path(r"G:\ComfyUI-aki-v3")
RUN = Path(__file__).resolve().parent
WF = ROOT / "ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json"
TEMPLATE = ROOT / "production_tools/templates/UAP统一生产工作台_v2.json"
if "--candidate" in sys.argv:
    WF = RUN / "candidate" / WF.name
    TEMPLATE = WF


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def get_api(path):
    with urllib.request.urlopen("http://127.0.0.1:8188/" + path, timeout=25) as response:
        return json.load(response)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value):
    if isinstance(value, str) and len(value) > 240:
        return {"text_length": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()}
    if isinstance(value, list):
        return [compact(v) for v in value]
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items()}
    return value


def widgets_for(node):
    values = node.get("widgets_values")
    if node["type"] in {"CLIPTextEncode", "WeiLinPromptUI", "CR Prompt Text", "OlmJoyCaption",
                         "TB_Multi_API_Caption_SmartRunner_V16", "TB_Anima_Prompt_Judge_API_V16", "VNCCS_PoseStudio"}:
        return {"redacted_text_widgets": True, "sha256": hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()}
    return compact(values)


def links_of(graph):
    return [l if isinstance(l, dict) else dict(zip(
        ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type"), l))
        for l in graph.get("links", [])]


workflow = read_json(WF)
template = read_json(TEMPLATE)
info = get_api("object_info")
graphs = [("TOP", workflow)] + [(s["name"] + "/" + s["id"], s)
                                    for s in workflow["definitions"]["subgraphs"]]
subgraph_ids = {s["id"] for s in workflow["definitions"]["subgraphs"]}
frontend = {"MarkdownNote", "Fast Groups Muter (rgthree)", "Fast Groups Bypasser (rgthree)"}
report = {
    "captured_at": datetime.datetime.now().astimezone().isoformat(),
    "method": "Read-only JSON, object_info and queue; no inference submission or production writes",
    "production_sha256": digest(WF), "template_sha256": digest(TEMPLATE),
    "graphs": [], "missing_backend_types": {}, "integrity_errors": [],
    "subgraph_instance_errors": [], "unconnected_required_candidates": [],
    "same_file_node_diff": [], "load_images": [], "parameter_mapping_errors": [],
    "parameter_range_errors": [],
}
seen_ids = collections.defaultdict(list)
for label, graph in graphs:
    nodes = {n["id"]: n for n in graph["nodes"]}
    links = links_of(graph)
    by_link = {l["id"]: l for l in links}
    if len(nodes) != len(graph["nodes"]) or len(by_link) != len(links):
        report["integrity_errors"].append([label, "duplicate local node or link id"])
    record = {"label": label, "node_count": len(nodes), "link_count": len(links),
              "inputs": graph.get("inputs"), "outputs": graph.get("outputs"), "nodes": []}
    indegree = {nid: 0 for nid in nodes}
    followers = collections.defaultdict(list)
    for link in links:
        if link["origin_id"] in nodes and link["target_id"] in nodes:
            indegree[link["target_id"]] += 1
            followers[link["origin_id"]].append(link["target_id"])
    ready = collections.deque(nid for nid, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        nid = ready.popleft()
        visited += 1
        for target in followers[nid]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    record["acyclic"] = visited == len(nodes)
    for n in graph["nodes"]:
        seen_ids[n["id"]].append(label)
        typ = n["type"]
        schema = info.get(typ)
        if not schema and typ not in subgraph_ids and typ not in frontend:
            report["missing_backend_types"].setdefault(typ, []).append([label, n["id"]])
        connected = []
        for slot, inp in enumerate(n.get("inputs", [])):
            lid = inp.get("link")
            if lid is None:
                if schema and inp["name"] in schema.get("input", {}).get("required", {}) and not inp.get("widget"):
                    report["unconnected_required_candidates"].append([label, n["id"], typ, inp["name"]])
                continue
            link = by_link.get(lid)
            if not link or (link["target_id"], link["target_slot"]) != (n["id"], slot):
                report["integrity_errors"].append([label, n["id"], inp["name"], "input reciprocal mismatch", lid])
                continue
            origin = nodes.get(link["origin_id"], {})
            connected.append({"input": inp["name"], "source_id": link["origin_id"],
                              "source_slot": link["origin_slot"], "source_title": origin.get("title", origin.get("type", "boundary"))})
        for slot, out in enumerate(n.get("outputs", [])):
            for lid in out.get("links") or []:
                link = by_link.get(lid)
                if not link or (link["origin_id"], link["origin_slot"]) != (n["id"], slot):
                    report["integrity_errors"].append([label, n["id"], out["name"], "output reciprocal mismatch", lid])
        if typ == "LoadImage":
            values = n.get("widgets_values", [])
            name = values[0] if isinstance(values, list) and values else ""
            p = ROOT / "ComfyUI/input" / name
            report["load_images"].append({"graph": label, "id": n["id"], "mode": n.get("mode"),
                                           "image": name, "input_file_exists": p.is_file()})
        record["nodes"].append({"id": n["id"], "type": typ, "title": n.get("title"), "mode": n.get("mode"),
                               "inputs": connected, "outputs": n.get("outputs"),
                               "widgets": widgets_for(n), "properties": compact(n.get("properties"))})
        if typ in {"DetailerForEach", "DetailerForEachPipe", "ImpactSimpleDetectorSEGS", "SegmDetectorSEGS",
                   "KSampler", "UltimateSDUpscale"}:
            fields = []
            specs = {}
            for section in ("required", "optional"):
                for name in schema.get("input_order", {}).get(section, []):
                    spec = schema["input"][section][name]
                    options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                    if not options.get("forceInput") and (isinstance(spec[0], list) or spec[0] in {"INT", "FLOAT", "STRING", "BOOLEAN"}):
                        fields.append(name)
                        specs[name] = spec
                        if name == "seed":
                            fields.append("control_after_generate")
            values = n.get("widgets_values", [])
            if len(fields) != len(values):
                report["parameter_mapping_errors"].append([label, n["id"], len(fields), len(values)])
            else:
                mapped = dict(zip(fields, values))
                record["nodes"][-1]["mapped_widgets"] = mapped
                for name, spec in specs.items():
                    value = mapped[name]
                    if isinstance(spec[0], list) and value not in spec[0]:
                        report["parameter_range_errors"].append([label, n["id"], name, "enum value unavailable"])
                    elif spec[0] in ("INT", "FLOAT") and len(spec) > 1:
                        if "min" in spec[1] and value < spec[1]["min"] or "max" in spec[1] and value > spec[1]["max"]:
                            report["parameter_range_errors"].append([label, n["id"], name, value])
    for link in links:
        if link["origin_id"] != -10:
            node = nodes.get(link["origin_id"])
            if not node or link["origin_slot"] >= len(node.get("outputs", [])):
                report["integrity_errors"].append([label, "missing origin/slot", link])
            elif link["id"] not in (node["outputs"][link["origin_slot"]].get("links") or []):
                report["integrity_errors"].append([label, "link absent from origin output", link])
        if link["target_id"] != -20:
            node = nodes.get(link["target_id"])
            if not node or link["target_slot"] >= len(node.get("inputs", [])):
                report["integrity_errors"].append([label, "missing target/slot", link])
            elif node["inputs"][link["target_slot"]].get("link") != link["id"]:
                report["integrity_errors"].append([label, "link absent from target input", link])
    report["graphs"].append(record)

for sg in workflow["definitions"]["subgraphs"]:
    for n in workflow["nodes"]:
        if n["type"] != sg["id"]:
            continue
        for side in ("inputs", "outputs"):
            actual = [(v["name"], v["type"]) for v in n.get(side, [])]
            declared = [(v["name"], v["type"]) for v in sg.get(side, [])]
            if actual != declared:
                report["subgraph_instance_errors"].append([n["id"], sg["name"], side, actual, declared])

report["duplicate_global_node_ids"] = {k: v for k, v in seen_ids.items() if len(v) > 1}
report["total_nodes"] = sum(len(g["nodes"]) for _, g in graphs)
report["total_links"] = sum(len(links_of(g)) for _, g in graphs)
report["groups"] = workflow["groups"]
titles = {g["title"] for g in workflow["groups"]}
config = workflow["extra"]["uap_workbench"]
report["active_branch"] = config["activeBranch"]
report["branches"] = [{"id": b["id"], "label": b["label"], "node_count": len(b["nodeIds"]),
    "stages": [{"id": s["id"], "label": s["label"]} for s in b["stages"]]} for b in config["branches"]]
report["missing_navigation_groups"] = [[b["id"], s["id"], title] for b in config["branches"]
    for s in b["stages"] for title in s["groups"] if title not in titles]
report["missing_layout_group_references"] = [[n["id"], n["properties"]["uap_layout_group"]]
    for n in workflow["nodes"] if n.get("properties", {}).get("uap_layout_group")
    and n["properties"]["uap_layout_group"] not in titles]
report["missing_sort_group_references"] = [[n["id"], title] for n in workflow["nodes"]
    for title in n.get("properties", {}).get("customSortAlphabet", "").split(",") if title and title not in titles]
top_ids = {n["id"] for n in workflow["nodes"]}
report["missing_branch_node_ids"] = [[b["id"], nid] for b in config["branches"] for nid in b["nodeIds"] if nid not in top_ids]
report["saved_refinement_modes"] = [{"branch": b["id"], "nodes": [{"id": n["id"], "title": n.get("title"),
    "current_mode": n["mode"], "mode_when_activated": b["modes"].get(str(n["id"]))} for n in workflow["nodes"]
    if n["id"] in b["nodeIds"] and n["type"] in subgraph_ids and n.get("properties", {}).get("uap_layout_group", "").startswith("FX-")]}
    for b in config["branches"] if b["id"] in {"a1", "a29"}]
model_fields = {"UNETLoader": "unet_name", "CLIPLoader": "clip_name", "VAELoader": "vae_name",
    "CheckpointLoaderSimple": "ckpt_name", "UltralyticsDetectorProvider": "model_name", "SAMLoader": "model_name",
    "UpscaleModelLoader": "model_name", "LoraLoaderModelOnly": "lora_name", "AnimaLLLiteApply_sdscripts": "model_name"}
report["model_references"] = []
for label, graph in graphs:
    for n in graph["nodes"]:
        field = model_fields.get(n["type"])
        if not field:
            continue
        choices = info[n["type"]].get("input", {}).get("required", {}).get(field)
        value = n.get("widgets_values", [None])[0]
        if choices and isinstance(choices[0], list):
            report["model_references"].append({"graph": label, "node_id": n["id"], "type": n["type"],
                "value": value, "exact_registered_choice": value in choices[0]})
report["historical_inference"] = []
for prompt in ("a047c35c-7c80-42f3-af67-8acf1f4c23a3", "768449b0-62b0-491e-a45f-d6b8784460bf",
               "33cb3b5c-c88c-484c-9d68-90beb84c5aad", "7b874888-68b7-45d3-8c62-990fbafb3c8d"):
    history = get_api("history/" + prompt).get(prompt)
    report["historical_inference"].append({"prompt_id": prompt, "history_present": bool(history),
        "status": history.get("status", {}).get("status_str") if history else None,
        "completed": history.get("status", {}).get("completed") if history else None})
standalone = ROOT / "ComfyUI/user/default/workflows/生产扩展_10_部位细化_Anima.json"
extension = read_json(standalone)
report["standalone_extension"] = {"path": str(standalone), "sha256": digest(standalone),
    "nodes": len(extension["nodes"]), "links": len(extension["links"]),
    "inventory": [{"id": n["id"], "type": n["type"], "title": n.get("title"), "mode": n.get("mode"),
        "widgets": widgets_for(n)} for n in extension["nodes"]]}
old_nodes = {n["id"]: n for n in template["nodes"]}
for n in workflow["nodes"]:
    old = old_nodes.get(n["id"])
    fields = [k for k in set(n) | set(old or {}) if n.get(k) != (old or {}).get(k)]
    if fields:
        report["same_file_node_diff"].append({"id": n["id"], "title": n.get("title"), "fields": fields})
old_sg = {s["id"]: s for s in template["definitions"]["subgraphs"]}
report["changed_subgraphs_vs_template"] = [{"id": s["id"], "name": s["name"],
    "production_nodes": len(s["nodes"]), "template_nodes": len(old_sg.get(s["id"], {}).get("nodes", []))}
    for s in workflow["definitions"]["subgraphs"] if s != old_sg.get(s["id"])]
queue = get_api("queue")
report["queue"] = {"running": len(queue["queue_running"]), "pending": len(queue["queue_pending"])}
selected_types = {n["type"] for _, g in graphs for n in g["nodes"]}
report["schemas"] = {t: {k: v for k, v in info[t].items() if k in ("input", "input_order", "output", "output_name", "python_module")}
                     for t in sorted(selected_types) if t in info}
(RUN / "audit_snapshot.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: report[k] for k in ("captured_at", "production_sha256", "template_sha256", "total_nodes", "total_links",
    "integrity_errors", "duplicate_global_node_ids", "subgraph_instance_errors", "missing_backend_types",
    "unconnected_required_candidates", "queue", "missing_navigation_groups", "missing_sort_group_references",
    "parameter_mapping_errors", "parameter_range_errors")}, ensure_ascii=False, indent=2))
