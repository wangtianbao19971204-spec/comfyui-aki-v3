"""Controlled Tag DB release with exact process ownership and rollback."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from contextlib import closing
from datetime import datetime
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMFY = ROOT / "ComfyUI"
PYTHON = ROOT / "python/python.exe"
PROD = ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector"
DB = PROD / "user_data/userdatas_zh_CN_tags.db"
DATA = PROD / "user_data/prompt_selector/data.json"
PREVIEW = PROD / "user_data/prompt_selector/preview"
BACKUP = HERE / "backup/tags.db"
STAGE = HERE / "stage/tags.db"
sys.path.insert(0, str(ROOT / "benchmark_reports/2026-09-27_codex_update"))
from db_fingerprint import fingerprint


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def now():
    return datetime.now().astimezone().isoformat()


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8188" + path, timeout=90) as response:
        return json.load(response)


def listeners():
    return sorted({c.pid for c in psutil.net_connections(kind="tcp") if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == 8188})


def queue_empty():
    state = get("/queue")
    assert not state["queue_running"] and not state["queue_pending"]
    return state


def owner(proc, expected_create=None):
    assert Path(proc.exe()).resolve() == PYTHON.resolve()
    assert str(COMFY / "main.py") in proc.cmdline()
    if expected_create is not None:
        assert abs(proc.create_time() - expected_create) < 0.02


def stop(proc, created):
    owner(proc, created)
    assert listeners() == [proc.pid]
    proc.terminate()
    proc.wait(60)
    assert not listeners()


def sidecars():
    for suffix in ("-wal", "-shm"):
        path = DB.with_name(DB.name + suffix)
        if path.exists():
            if suffix == "-wal":
                assert path.stat().st_size == 0, "Nonempty WAL must never be discarded"
            path.unlink()


def replace(src):
    tmp = DB.with_name(DB.name + ".raven-increment-tmp")
    with src.open("rb") as inp, tmp.open("wb") as out:
        shutil.copyfileobj(inp, out, 1024 * 1024)
        out.flush()
        os.fsync(out.fileno())
    assert sha(src) == sha(tmp)
    os.replace(tmp, DB)
    assert sha(src) == sha(DB)


def start(label, cmd):
    assert not listeners()
    with (HERE / (label + ".out.log")).open("ab") as stdout, (HERE / (label + ".err.log")).open("ab") as stderr:
        child = subprocess.Popen(cmd, cwd=COMFY, stdout=stdout, stderr=stderr,
                                 creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                                 close_fds=True)
    process = psutil.Process(child.pid)
    owner(process)
    receipt[label] = {"pid": child.pid, "create_time": process.create_time(), "command": cmd}
    checkpoint(label + "_starting")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        assert child.poll() is None, "ComfyUI exited during startup"
        try:
            queue_empty()
            assert listeners() == [child.pid]
            workbench = get("/unified-workbench/status")
            assert workbench["nodes"] == 71 and not workbench["degraded"]
            return process
        except (OSError, ValueError, AssertionError):
            time.sleep(4)
    raise RuntimeError("ComfyUI startup timeout")


def checkpoint(phase, **fields):
    receipt.update(phase=phase, **fields)
    receipt["events"].append({"phase": phase, "at": now()})
    save(HERE / "release_receipt.json", receipt)
    save(HERE / "EXECUTION_STATE.json", {"status": phase, "production_mutated": receipt["applied"],
                                        "updated_at": now(), "receipt": "release_receipt.json"})
    print(phase, flush=True)


pre = read(HERE / "preflight.json")
assert pre["passed"] and pre["source_rows"] == 816
for relative, digest in pre["bound_files"].items():
    assert sha(ROOT / relative) == digest, relative
assert sha(STAGE) == pre["stage_db_sha256"] and sha(BACKUP) == pre["backup_db_sha256"]
assert sha(DB) == pre["production_db_sha256"] and sha(DATA) == pre["production_data_sha256"]
assert listeners() == [pre["owner"]["pid"]]
old = psutil.Process(pre["owner"]["pid"])
owner(old, pre["owner"]["create_time"])
queue_empty()
save(HERE / "baseline_index.json", get("/prompt_selector/library/index"))
receipt = {"created_at": now(), "phase": "job_0", "applied": False, "passed": False,
           "preflight_sha256": sha(HERE / "preflight.json"), "events": [], "installed_new": []}
checkpoint("job_0_passed")
child = None
try:
    for image in read(HERE / "image_receipts.json"):
        src = HERE / "stage/images" / image["filename"]
        dst = PREVIEW / image["filename"]
        assert dst.resolve().is_relative_to(PREVIEW.resolve())
        if not dst.exists():
            tmp = dst.with_name(dst.name + ".raven-increment-tmp")
            shutil.copy2(src, tmp)
            assert sha(tmp) == image["sha256"]
            os.replace(tmp, dst)
            receipt["installed_new"].append(image["filename"])
        assert sha(dst) == image["sha256"]
    checkpoint("previews_ready", previews_verified=816)
    queue_empty()
    assert sha(DB) == pre["production_db_sha256"]
    stop(old, pre["owner"]["create_time"])
    checkpoint("service_stopped")
    with closing(sqlite3.connect(DB)) as db:
        assert db.execute("pragma wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    sidecars()
    assert fingerprint(DB) == fingerprint(BACKUP), "Production Tag DB drifted after preflight"
    replace(STAGE)
    receipt["applied"] = True
    checkpoint("database_replaced")
    child = start("production", pre["owner"]["command"])
    checkpoint("live_acceptance")
    with (HERE / "live_acceptance.log").open("wb") as log:
        subprocess.run([str(PYTHON), "-X", "utf8", str(HERE / "live_acceptance.py")],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
    live = read(HERE / "live_acceptance.json")
    assert live["passed"] and live["tag_api_verified"] == 811 and live["image_http_verified"] == 816
    assert listeners() == [child.pid]
    assert queue_empty()
    checkpoint("accepted", passed=True, production_db_sha256=sha(DB), completed_at=now())
except BaseException as error:
    checkpoint("rollback_required", error=repr(error))
    if child is None and receipt.get("production") and psutil.pid_exists(receipt["production"]["pid"]):
        child = psutil.Process(receipt["production"]["pid"])
    if child is not None and child.is_running():
        owner(child, receipt["production"]["create_time"])
        if listeners() == [child.pid]:
            stop(child, receipt["production"]["create_time"])
        elif not listeners():
            child.terminate()
            child.wait(60)
        else:
            raise RuntimeError("Unknown service listener blocks restoration")
    old_still_running = listeners() == [old.pid] and old.is_running()
    assert old_still_running or not listeners(), "Unknown service listener blocks restoration"
    if receipt["applied"]:
        sidecars()
        replace(BACKUP)
    for name in receipt["installed_new"]:
        target = PREVIEW / name
        assert target.resolve().is_relative_to(PREVIEW.resolve())
        if target.exists():
            target.unlink()
    recovered = old if old_still_running else start("recovery", pre["owner"]["command"])
    assert fingerprint(DB) == fingerprint(BACKUP)
    assert get("/prompt_selector/library/index") == read(HERE / "baseline_index.json")
    assert listeners() == [recovered.pid] and queue_empty()
    receipt["applied"] = False
    checkpoint("rolled_back", rollback_verified=True)
    raise
