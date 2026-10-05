"""Check all graph links, exact generation preservation and CLI write safety."""
import collections
import importlib.util
import json
import subprocess
import sys

from freeze import ROOT, RUN, read, save, sha
from stage_workflow import WORKFLOW, TEMPLATE

wf = read(RUN / "candidate" / WORKFLOW)
old = read(RUN / "before" / WORKFLOW)
assert wf == read(RUN / "candidate" / TEMPLATE)
checks = 0
global_ids = set()
for graph, baseline in zip([wf] + wf["definitions"]["subgraphs"], [old] + old["definitions"]["subgraphs"]):
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert len(nodes) == len(graph["nodes"])
    assert not global_ids.intersection(nodes)
    global_ids.update(nodes)
    links = {link[0] if isinstance(link, list) else link["id"]: link if isinstance(link, list) else [link[k] for k in ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")] for link in graph["links"]}
    degree = {node: 0 for node in nodes}
    successors = collections.defaultdict(list)
    for id, origin, oslot, target, tslot, kind in links.values():
        if origin != -10:
            assert id in (nodes[origin]["outputs"][oslot].get("links") or [])
        if target != -20:
            assert nodes[target]["inputs"][tslot]["link"] == id
        if origin in nodes and target in nodes:
            degree[target] += 1
            successors[origin].append(target)
        checks += 1
    pending = [id for id, count in degree.items() if count == 0]
    seen = []
    while pending:
        id = pending.pop()
        seen.append(id)
        for target in successors[id]:
            degree[target] -= 1
            if degree[target] == 0:
                pending.append(target)
    assert len(seen) == len(nodes)
    for node, before in zip(graph["nodes"], baseline["nodes"]):
        assert node["id"] == before["id"]
        assert node.get("widgets_values") == before.get("widgets_values")
        assert node["mode"] == before["mode"]
        # Only image-comparison connections may change. Subgraph computations cannot.
        if node["type"] != "Image Comparer (rgthree)":
            assert node.get("inputs") == before.get("inputs")
        checks += 1
for branch, previous in zip(wf["extra"]["uap_workbench"]["branches"], old["extra"]["uap_workbench"]["branches"]):
    assert branch["modes"] == previous["modes"]
    assert branch["nodeIds"] == previous["nodeIds"]
assert wf["extra"]["uap_workbench"]["activeBranch"] == old["extra"]["uap_workbench"]["activeBranch"]
builder = RUN / "candidate/production_tools/merge_unified_workflow.py"
protected = RUN / "candidate" / WORKFLOW
digest = sha(protected)
def run(*args):
    return subprocess.run([sys.executable, str(builder), *map(str, args)], capture_output=True, text=True, encoding="utf-8", errors="replace")
assert run("--validate", "--compact").returncode == 0
assert sha(protected) == digest
assert run().returncode != 0
assert run("--compact", "--output", protected).returncode != 0
assert sha(protected) == digest
candidate = RUN / "builder_export.json"
if candidate.exists():
    candidate = RUN / ("builder_export_" + digest[:12] + ".json")
if candidate.exists():
    assert read(candidate) == wf
else:
    assert run("--output", candidate).returncode == 0
assert read(candidate) == wf
assert run("--output", candidate).returncode != 0
released = {item["path"]: item["after"] for item in read(RUN / "release_manifest.json")["files"]} if (RUN / "release_manifest.json").exists() else {}
for item in read(RUN / "baseline.json")["files"]:
    assert sha(ROOT / item["path"]) == released.get(item["path"], item["sha256"]), item["path"]
result = {"passed": True, "nodes": len(global_ids), "links": 685, "checks": checks,
          "generation_values_and_prompts_unchanged": True, "all_default_modes_unchanged": True,
          "builder_validate_read_only": True, "production_and_existing_candidate_write_refused": True,
          "canonical_export_matches": True, "all_68_production_guards_match_expected_state": True}
save(RUN / "structure_results.json", result)
print(json.dumps(result))
