"""Bind the staged Raven increment to current production and service owner."""
import hashlib
import json
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROD = ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector"
DATA = PROD / "user_data/prompt_selector/data.json"
DB = PROD / "user_data/userdatas_zh_CN_tags.db"
PREVIEW = PROD / "user_data/prompt_selector/preview"
WEB = ROOT / "benchmark_reports/2026-09-28_web_image_reaudit/current_web"
AUDIT = WEB.parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


validation = read(HERE / "stage_validation.json")
assert validation["passed"] and validation["rollback_drill_passed"]
assert sha(DATA) == validation["data_sha256"]
assert sha(DB) == "341d88e9538ee432750a4617ebccb0aebf4ff671c933104c5fbb114a0dc627c9"
assert sha(HERE / "stage/tags.db") == validation["stage_db_sha256"]
assert sha(HERE / "backup/tags.db") == validation["baseline_db_sha256"]
assert read(WEB / "current.json")["release"] == get("https://assets.quicktagcloud.com/data/current.json")["release"]
assert read(WEB / "current.json")["release"] == "r-9a4bf4049f141be7d4d9"
assert sha(WEB / "raven_composition.json") == read(WEB / "manifest.json")["files"]["raven_composition.json"]["sha256"]
assert len(read(HERE / "source_registry.json")) == len(read(HERE / "image_receipts.json")) == 816
for image in read(HERE / "image_receipts.json"):
    src = HERE / "stage/images" / image["filename"]
    dst = PREVIEW / image["filename"]
    assert image["status"] == "ok" and sha(src) == image["sha256"]
    if dst.exists():
        assert sha(dst) == image["sha256"], "Preview filename collision"

listeners = sorted({c.pid for c in psutil.net_connections(kind="tcp") if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == 8188})
assert len(listeners) == 1, listeners
proc = psutil.Process(listeners[0])
cmd = proc.cmdline()
assert Path(proc.exe()).resolve() == (ROOT / "python/python.exe").resolve()
assert str(ROOT / "ComfyUI/main.py") in cmd
queue = get("http://127.0.0.1:8188/queue")
assert not queue["queue_running"] and not queue["queue_pending"]
workbench = get("http://127.0.0.1:8188/unified-workbench/status")
assert workbench["nodes"] == 71 and not workbench["degraded"]
with sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True) as live, sqlite3.connect(HERE / "backup/tags.db") as baseline:
    assert live.execute("pragma integrity_check").fetchone()[0] == "ok"
    for table in ("tag_tags", "tag_groups", "tag_subgroups", "workbench_tag_meta"):
        assert live.execute("select count(*) from " + table).fetchone() == baseline.execute("select count(*) from " + table).fetchone()
    assert live.execute("select value from workbench_tag_revision where id=1").fetchone() == baseline.execute("select value from workbench_tag_revision where id=1").fetchone()

bound = [HERE / name for name in ("stage_increment.py", "validate_increment.py", "preflight.py", "release.py", "live_acceptance.py", "prepare_images.py", "fetch_images.py",
                                  "source_registry.json", "operations.json", "classification_review.jsonl", "image_plan.json", "image_receipts.json", "stage_validation.json")]
result = {"passed": True, "created_at": datetime.now().astimezone().isoformat(),
          "source_release": "r-9a4bf4049f141be7d4d9", "source_rows": 816,
          "production_data_sha256": sha(DATA), "production_db_sha256": sha(DB),
          "backup_db_sha256": sha(HERE / "backup/tags.db"), "stage_db_sha256": sha(HERE / "stage/tags.db"),
          "owner": {"pid": proc.pid, "create_time": proc.create_time(), "command": cmd},
          "queue": queue, "workbench": workbench,
          "bound_files": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in bound}}
(HERE / "preflight.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("PREFLIGHT_PASS", proc.pid, "IMAGES", 816, flush=True)
