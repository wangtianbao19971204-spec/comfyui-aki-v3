"""Freeze the authorized repair's files and live service state before editing."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

import psutil

ROOT = Path(r"G:\ComfyUI-aki-v3")
RUN = Path(__file__).resolve().parent
SCOPE = RUN.parent.parent
WEB = ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web"
NAV = WEB.parent / "modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def api(path):
    with urllib.request.urlopen("http://127.0.0.1:8188/" + path, timeout=20) as response:
        return json.load(response)


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def freeze():
    assert not (RUN / "baseline.json").exists(), "Baseline already exists; do not overwrite"
    assert not (SCOPE / "run.lock").exists(), "Another scope owner must be checked first"
    queue = api("queue")
    assert not queue["queue_running"] and not queue["queue_pending"], "Queue must be idle before repair"
    inventory = read(ROOT / "benchmark_reports/2026-10-04_full_workflow_review/inventory.json")
    paths = {Path(item["path"]) for item in inventory["guards"]}
    paths.update(WEB.glob("*.js"))
    paths.update(WEB.glob("*.css"))
    paths.update(NAV.glob("*.js"))
    paths.update(NAV.glob("*.css"))
    paths.add(ROOT / "production_tools/merge_unified_workflow.py")
    for item in inventory["related_workflows"]:
        template = ROOT / "production_tools/templates" / item["name"]
        if template.is_file():
            paths.add(template)
    files = []
    for path in sorted(paths):
        relative = path.relative_to(ROOT)
        backup = RUN / "before" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        files.append({"path": str(relative), "sha256": sha(path)})
    listeners = sorted({c.pid for c in psutil.net_connections(kind="tcp")
                        if c.status == psutil.CONN_LISTEN and c.laddr.port == 8188})
    assert listeners == [53232], listeners
    save(RUN / "baseline.json", {"time": datetime.datetime.now().astimezone().isoformat(),
         "files": files, "listeners": listeners, "queue": {"running": 0, "pending": 0},
         "workflow_sha256": inventory["workflow_sha256"], "qwen_pid": 51312})
    save(RUN / "object_info.json", api("object_info"))
    state = {"owner_thread": "01a1061f-c0b3-7f40-8168-1bc0ca82582c", "active_run": str(RUN),
             "phase": "baseline_frozen", "status": "in_progress", "production_published": False,
             "scope": "Audit findings: comparison correctness, build safety, task/target/model guards, focused controls and layout",
             "preserve": "Formal prompts, LoRAs, existing sampler/detector values, all default-off states, nine branches, libraries, queue",
             "plan": ["Workflow semantics and safe rebuilding", "Task, target and model contract guards",
                      "Focused refinement controls and responsive UI", "Unit/static and isolated browser acceptance", "Guarded publication and rollback verification"]}
    save(RUN / "STATE.json", state)
    with (SCOPE / "run.lock").open("x", encoding="utf-8") as stream:
        json.dump({"owner_thread": state["owner_thread"], "run": str(RUN), "started_at": datetime.datetime.now().astimezone().isoformat()}, stream)
    print(json.dumps({"guarded_files": len(files), "listeners": listeners, "phase": state["phase"]}))


if __name__ == "__main__":
    freeze()
