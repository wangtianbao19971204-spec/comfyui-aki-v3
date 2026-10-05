"""Low-cost static inventory of nodes used by the maintained workflow set."""
from __future__ import annotations
import json
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "ComfyUI/user/default/workflows"
OUT = ROOT / "benchmark_reports/2026-09-06_plugin_optimization/workflow_node_inventory.json"

def main() -> None:
    with urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=30) as response:
        object_info = json.load(response)
    files = []
    all_types = Counter()
    module_counts = Counter()
    maintained = Counter()
    maintained_names = []
    for path in sorted(WORKFLOWS.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf8"))
        except Exception:
            continue
        nodes = data.get("nodes", [])
        types = Counter(n.get("type") for n in nodes if n.get("type"))
        all_types.update(types)
        is_maintained = path.name.startswith("生产套件_") or path.name.startswith("生产扩展_")
        if is_maintained:
            maintained_names.append(path.name)
        for node_type, count in types.items():
            info = object_info.get(node_type, {})
            module = info.get("python_module", "<unregistered>")
            module_counts[module] += count
            if is_maintained:
                maintained[module] += count
        file_modules = Counter()
        for node_type, count in types.items():
            file_modules[object_info.get(node_type, {}).get("python_module", "<unregistered>")] += count
        files.append({"file": path.name, "node_count": len(nodes), "unique_types": len(types), "nodes": dict(types), "python_modules": dict(file_modules.most_common())})
    known = set(object_info)
    report = {
        "server": "http://127.0.0.1:8188",
        "object_info_nodes": len(known),
        "workflow_files": len(files),
        "all_used_node_types": len(all_types),
        "missing_from_object_info": sorted(t for t in all_types if t not in known),
        "node_frequency": dict(all_types.most_common()),
        "python_module_node_frequency_all_workflows": dict(module_counts.most_common()),
        "python_module_node_frequency_maintained": dict(maintained.most_common()),
        "maintained_workflows": maintained_names,
        "files": files,
        "scope": "Static inventory only; plugin ownership is inferred in the accompanying review and no plugin is removed automatically.",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"workflow_files": len(files), "used_types": len(all_types), "missing": len(report["missing_from_object_info"])}, ensure_ascii=False))

if __name__ == "__main__":
    main()
