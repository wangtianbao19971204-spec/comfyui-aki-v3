"""Check launch profiles against a captured registry and saved workflow closure."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIFIED = "ComfyUI-Unified-Prompt-Workbench"
FRONTEND_TYPES = {"MarkdownNote", "Note", "Reroute", "PrimitiveNode", "Fast Groups Muter (rgthree)", "Fast Groups Bypasser (rgthree)", "Label (rgthree)"}


def selected_workflows(profile, workflows):
    for workflow in workflows:
        name = Path(workflow["path"]).name
        selected = False
        if profile in {"production", "diagnostic", "legacy"}:
            selected = name.startswith(("生产套件_", "生产扩展_", "UAP统一", "Anima_推荐版_", "Krea2_"))
        elif profile == "anima":
            selected = name.startswith(("生产套件_01_", "生产套件_02_", "生产套件_99_"))
        elif profile == "krea":
            selected = name.startswith(("生产套件_03_", "生产套件_99_"))
        elif profile == "lean":
            # Lean only promises the six independent tools (04--09), not
            # later production extensions with a wider plugin dependency set.
            selected = name.startswith(tuple(f"生产扩展_{number:02d}_" for number in range(4, 10))) or name.startswith("生产套件_99_")
        if selected:
            yield workflow


def validate(inventory, profiles):
    merged = {item["directory"] for item in inventory["module_manifest"]["modules"]}
    results = {}
    errors = []
    for profile, names in profiles.items():
        failures = []
        missing_paths = [name for name in names if not (ROOT / "ComfyUI/custom_nodes" / name).is_dir()]
        if missing_paths:
            failures.append({"missing_plugin_directories": missing_paths})
        if len(names) != len(set(names)):
            failures.append({"duplicate_profile_entries": True})
        if set(names) & merged:
            failures.append({"empty_compatibility_entries": sorted(set(names) & merged)})
        if profile in {"production", "diagnostic", "anima", "krea", "legacy"} and UNIFIED not in names:
            failures.append({"unified_workbench_missing": True})
        covered = []
        for workflow in selected_workflows(profile, inventory["workflows"]):
            owners = {module.split(".", 1)[1].split(".", 1)[0] for module in workflow["modules"] if module.startswith("custom_nodes.")}
            if any(kind.endswith("(rgthree)") for kind in workflow["types"]):
                owners.add("rgthree-comfy")
            missing = sorted(owners - set(names))
            unknown = sorted(set(workflow["unregistered"]) - FRONTEND_TYPES)
            if missing or unknown:
                failures.append({"workflow": workflow["path"], "missing_plugins": missing, "unregistered_backend_types": unknown})
            covered.append({"workflow": workflow["path"], "required_plugins": sorted(owners), "missing_plugins": missing, "unregistered_backend_types": unknown})
        process = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "production_tools/launch.py"), profile, "--dry-run"], capture_output=True, text=True, encoding="utf-8", timeout=15)
        if process.returncode != 0:
            failures.append({"dry_run_failed": True})
        else:
            launch = json.loads(process.stdout)
            if "--disable-all-custom-nodes" not in launch["args"] or "--whitelist-custom-nodes" not in launch["args"]:
                failures.append({"whitelist_flags_missing": True})
            if any(name not in launch["args"] for name in names):
                failures.append({"dry_run_profile_entries_missing": True})
        results[profile] = {"plugins": len(names), "workflows": covered, "failures": failures, "dry_run_passed": process.returncode == 0}
        errors.extend({"profile": profile, **failure} for failure in failures)
    return {"checked_at": datetime.now().astimezone().isoformat(), "passed": not errors, "profiles": results, "failures": errors,
            "registry_captured_at": inventory["checked_at"], "limits": "Offline dependency/launch-command validation using the captured live registry, including nested subgraphs. No server or model was started; profile-specific plugin import/runtime acceptance remains separate."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(json.loads(args.inventory.read_text(encoding="utf-8")), json.loads((ROOT / "production_tools/profiles.json").read_text(encoding="utf-8")))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "profiles": {key: {"plugins": value["plugins"], "workflows": len(value["workflows"]), "failures": len(value["failures"])} for key, value in result["profiles"].items()}}, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
