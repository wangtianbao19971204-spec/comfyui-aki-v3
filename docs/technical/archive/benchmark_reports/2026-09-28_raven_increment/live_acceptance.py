"""Verify every Raven source image and every resulting Tag through live APIs."""
import hashlib
import json
import sqlite3
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROD = ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector"
DATA = PROD / "user_data/prompt_selector/data.json"
DB = PROD / "user_data/userdatas_zh_CN_tags.db"
STAGE_DB = HERE / "stage/tags.db"
PREVIEW = PROD / "user_data/prompt_selector/preview"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fetch(path):
    with urllib.request.urlopen("http://127.0.0.1:8188" + path, timeout=90) as response:
        return response.read()


def get(path):
    return json.loads(fetch(path))


pre = read(HERE / "preflight.json")
assert sha(DATA) == pre["production_data_sha256"]
assert get("/prompt_selector/library/index") == read(HERE / "baseline_index.json")
registry = read(HERE / "source_registry.json")
receipts = read(HERE / "image_receipts.json")
assert len(registry) == len(receipts) == 816

with sqlite3.connect(STAGE_DB) as staged:
    wanted = {}
    for uid in {row["target_id"] for row in registry}:
        text = staged.execute("select text from tag_tags where t_uuid=?", (uid,)).fetchone()[0]
        metadata = json.loads(staged.execute("select data from workbench_tag_meta where tag_uuid=?", (uid,)).fetchone()[0])
        wanted[uid] = (text, metadata["preview"])


def check_tag(pair):
    uid, (text, preview) = pair
    result = get("/prompt_selector/tags/item?" + urllib.parse.urlencode({"id": "tag:" + uid}))
    item = result["item"]
    assert item["text"] == text and item["preview"] == preview, uid
    return uid


def check_image(row):
    name = row["filename"]
    raw = fetch("/prompt_selector/preview/" + urllib.parse.quote(name))
    assert hashlib.sha256(raw).hexdigest() == row["sha256"] == sha(PREVIEW / name), name
    return name


with ThreadPoolExecutor(max_workers=8) as pool:
    verified_tags = list(pool.map(check_tag, wanted.items()))
with ThreadPoolExecutor(max_workers=8) as pool:
    verified_images = list(pool.map(check_image, receipts))

# A full logical fingerprint avoids relying on SQLite file bytes while WAL mode is active.
import sys
sys.path.insert(0, str(ROOT / "benchmark_reports/2026-09-27_codex_update"))
from db_fingerprint import fingerprint

assert fingerprint(DB) == fingerprint(STAGE_DB), "Live Tag DB differs from staged database"
queue = get("/queue")
assert not queue["queue_running"] and not queue["queue_pending"]
workbench = get("/unified-workbench/status")
assert workbench["nodes"] == 71 and not workbench["degraded"]
listeners = sorted({c.pid for c in psutil.net_connections(kind="tcp") if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == 8188})
assert len(listeners) == 1
result = {"passed": True, "created_at": datetime.now().astimezone().isoformat(),
          "source_release": pre["source_release"], "source_rows": 816,
          "tag_api_verified": len(verified_tags), "image_http_verified": len(verified_images),
          "db_fingerprint_equal_to_stage": True, "resource_index_unchanged": True,
          "data_sha256": sha(DATA), "production_owner_pid": listeners[0], "queue_empty": True,
          "workbench_nodes": workbench["nodes"], "degraded": workbench["degraded"]}
(HERE / "live_acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("LIVE_ACCEPTANCE_PASS", len(verified_tags), "TAGS", len(verified_images), "IMAGES", flush=True)
