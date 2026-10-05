"""Validate the lean profile without loading a diffusion model or queuing work."""
from __future__ import annotations
import json
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmark_reports/2026-09-06_plugin_optimization/lean_profile_validation.json"
REQUIRED = [
    "AnimaLLLiteApply_sdscripts", "Krea2EditGroundedEncode", "Krea2EditModelPatch",
    "OlmDragCrop", "OlmCropInfoInterpreter", "BiRefNetRMBG", "VRAMCleanup",
]

def get(path: str):
    with urllib.request.urlopen("http://127.0.0.1:8189" + path, timeout=30) as response:
        return json.load(response)

def main() -> None:
    info = get("/object_info")
    stats = get("/system_stats")
    missing = [node for node in REQUIRED if node not in info]
    assert not missing, missing
    report = {
        "checked_at": datetime.now().astimezone().isoformat(),
        "profile": "lean", "port": 8189, "plugins": 5,
        "registered_nodes": len(info), "required_nodes_present": REQUIRED,
        "missing_required_nodes": missing, "system": stats.get("system", {}),
        "no_model_queued": True,
        "note": "Static/profile validation only; no model was loaded and no prompt was queued.",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"registered_nodes": len(info), "plugins": 5, "missing": len(missing)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
