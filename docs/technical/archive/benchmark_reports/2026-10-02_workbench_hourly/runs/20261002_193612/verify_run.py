import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

import psutil


run = Path(__file__).resolve().parent
reports = run.parent.parent
baseline = json.loads((reports / "runs/20261002_153615/source_snapshot_final/manifest.json").read_text(encoding="utf-8-sig"))
selector_changes = json.loads((reports / "runs/20261002_155721/change_manifest.json").read_text(encoding="utf-8-sig"))
native_change = json.loads((reports / "runs/20261002_172434/change_manifest.json").read_text(encoding="utf-8-sig"))
change = json.loads((run / "change_manifest.json").read_text(encoding="utf-8"))
previous_guard = json.loads((reports / "runs/20261002_172434/final_live_guard.json").read_text(encoding="utf-8-sig"))
production = Path(baseline["production_root"])


def sha(data):
    if isinstance(data, Path):
        data = data.read_bytes()
    return hashlib.sha256(data).hexdigest()


def get(route):
    with urlopen("http://127.0.0.1:8188" + route, timeout=10) as response:
        return response.read()


expected = dict(baseline["expected_source_hashes"])
for selector_change in selector_changes["files"]:
    expected[selector_change["relative_path"]] = selector_change["after_sha"]
expected[native_change["relative_path"]] = native_change["after_sha"]
expected[change["relative_path"]] = change["after_sha"]
source_drift = [path for path, digest in expected.items() if sha(production / path) != digest]
formal_drift = [path for path, digest in baseline["formal_files"].items() if sha(Path(path)) != digest]
served = []
for path, route in {
    change["relative_path"]: "/extensions/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/quick_group_navigation/uap_daily_controls.js",
    native_change["relative_path"]: "/weilin/prompt_ui/file/javascript/main.entry.js",
    "modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/dist/javascript/zz_tb_shared_preset_manager.js": "/weilin/prompt_ui/file/javascript/zz_tb_shared_preset_manager.js",
    "modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/js_node/prompt_selector/native_library_browser.js": "/extensions/weilin-comfyui-tools/prompt_selector/native_library_browser.js",
    "web/workbench_shell.js": "/extensions/ComfyUI-Unified-Prompt-Workbench/workbench_shell.js",
}.items():
    served.append({"path": path, "disk_sha": sha(production / path), "served_sha": sha(get(route))})
listeners = []
for connection in psutil.net_connections(kind="tcp"):
    if connection.laddr and connection.laddr.port == 8188 and connection.status == "LISTEN":
        listeners.append({"pid": connection.pid, "exe": psutil.Process(connection.pid).exe()})
queue = json.loads(get("/queue"))
modules = json.loads(get("/unified-workbench/status"))["modules"]
row = json.loads(get("/prompt_selector/library/prompt?prompt_id=7e161c74-e474-56b8-ada0-93d53ab7d01c&selection=1"))["prompt"]
guard = {
    "verified_at": datetime.now().astimezone().isoformat(),
    "source_count": len(expected), "source_drift": source_drift,
    "formal_count": len(baseline["formal_files"]), "formal_drift": formal_drift,
    "served": served, "served_match": all(x["disk_sha"] == x["served_sha"] for x in served),
    "listeners": listeners,
    "queue_running": len(queue["queue_running"]), "queue_pending": len(queue["queue_pending"]),
    "modules_ready": sum(bool(module["ready"]) for module in modules), "modules_count": len(modules),
    "usage_count_before": previous_guard["production_usage_after"], "usage_count_after": row.get("usage_count"),
    "last_used_unchanged": row.get("last_used") == json.loads((reports / "runs/20261002_172434/fixture_provenance.json").read_text(encoding="utf-8"))["production_last_used_before"],
}
(run / "final_live_guard.json").write_text(json.dumps(guard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
assert len(expected) == 27 and not source_drift
assert len(baseline["formal_files"]) == 21 and not formal_drift
assert guard["served_match"] and len(served) == 5
assert len(listeners) == 1 and listeners[0]["pid"] == 24420
assert guard["queue_running"] == guard["queue_pending"] == 0
assert guard["modules_ready"] == guard["modules_count"] == 5
assert guard["usage_count_before"] == guard["usage_count_after"] == 26
assert guard["last_used_unchanged"]
print(json.dumps({key: guard[key] for key in ("source_count", "formal_count", "served_match", "listeners", "queue_running", "queue_pending", "modules_ready", "usage_count_after")}, ensure_ascii=False))
