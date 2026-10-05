"""Audit current local image bindings against the frozen 15 web datasets."""

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import orjson

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPDATE = HERE.with_name("2026-09-27_codex_update")
WEB = UPDATE / "sources/web"
PROD = ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector"
DATA = PROD / "user_data/prompt_selector/data.json"
DB = PROD / "user_data/userdatas_zh_CN_tags.db"
PREVIEW = DATA.parent / "preview"
SKIP = {"excluded", "no_prompt_content"}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return orjson.loads(path.read_bytes())


registry = {row["source"]: row for row in read(UPDATE / "source_registry.json")}
metas = read(WEB / "codexes.json")
source_rows = []
dataset_stats = []
missing_registry = []
for meta in metas:
    source_file = WEB / (meta["id"] + ".external.json")
    if not source_file.exists():
        source_file = WEB / (meta["id"] + ".json")
    entries = read(source_file)["entries"]
    stats = Counter()
    for entry in entries:
        key = meta["id"] + ":" + entry["id"]
        row = registry.get(key)
        if row is None:
            missing_registry.append(key)
            continue
        stats["rows"] += 1
        stats["disposition_" + row["disposition"]] += 1
        image = entry.get("image")
        images = entry.get("images") or []
        if not image:
            continue
        stats["image_rows"] += 1
        stats["image_refs"] += max(1, len(images))
        if row["disposition"] in SKIP:
            stats["image_rows_held_or_empty"] += 1
            continue
        stats["included_image_rows"] += 1
        stats["included_extra_image_refs"] += max(0, len(images) - 1)
        stats["included_multi_image_rows"] += int(len(images) > 1)
        source_rows.append((key, meta["id"], row["disposition"], row["target_id"], image, len(images)))
    dataset_stats.append({"dataset": meta["id"], **stats})

data = read(DATA)
prompts = {prompt["id"]: prompt for category in data["categories"] for prompt in category["prompts"]}
tag_ids = {target for _, _, disposition, target, _, _ in source_rows if disposition.startswith("tag")}
tag_meta = {}
with sqlite3.connect(DB) as connection:
    ids = list(tag_ids)
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        marks = ",".join("?" for _ in chunk)
        for uid, payload in connection.execute(
            f"select tag_uuid,data from workbench_tag_meta where tag_uuid in ({marks})", chunk
        ):
            tag_meta[uid] = orjson.loads(payload)

missing_targets = []
missing_links = []
missing_files = []
bound_names = set()
by_disposition = Counter()
by_dataset = defaultdict(Counter)
for source, dataset, disposition, target, website_image, image_count in source_rows:
    by_disposition[disposition] += 1
    by_dataset[dataset]["included_image_rows"] += 1
    if disposition.startswith("tag"):
        item = tag_meta.get(target)
        name = item.get("preview") if item else None
    else:
        item = prompts.get(target)
        name = item.get("image") if item else None
    if item is None:
        missing_targets.append(source)
    elif not name:
        missing_links.append(source)
    elif not (PREVIEW / name).is_file():
        missing_files.append((source, name))
    else:
        bound_names.add(name)
        by_dataset[dataset]["local_preview_present"] += 1

image_receipts = read(UPDATE / "image_receipts.json")
downloaded_missing = []
downloaded_hash_mismatch = []
for receipt in image_receipts:
    path = PREVIEW / receipt["filename"]
    if not path.is_file():
        downloaded_missing.append(receipt["filename"])
    elif sha(path) != receipt["sha256"]:
        downloaded_hash_mismatch.append(receipt["filename"])

summary = {
    "schema": "web-image-local-audit/v1",
    "created_at": datetime.now().astimezone().isoformat(),
    "catalog_dataset_count": len(metas),
    "catalog_entry_count": sum(row["rows"] for row in dataset_stats),
    "catalog_image_entry_count": sum(row["image_rows"] for row in dataset_stats),
    "catalog_image_reference_count": sum(row["image_refs"] for row in dataset_stats),
    "held_or_empty_image_entries": sum(row.get("image_rows_held_or_empty", 0) for row in dataset_stats),
    "included_image_entries": len(source_rows),
    "included_multi_image_entries": sum(row.get("included_multi_image_rows", 0) for row in dataset_stats),
    "included_extra_image_references": sum(row.get("included_extra_image_refs", 0) for row in dataset_stats),
    "included_by_disposition": dict(by_disposition),
    "unique_local_bound_previews": len(bound_names),
    "newly_installed_preview_receipts": len(image_receipts),
    "missing_registry_count": len(missing_registry),
    "missing_target_count": len(missing_targets),
    "missing_image_link_count": len(missing_links),
    "missing_preview_file_count": len(missing_files),
    "downloaded_preview_missing_count": len(downloaded_missing),
    "downloaded_preview_hash_mismatch_count": len(downloaded_hash_mismatch),
    "data_sha256": sha(DATA),
    "db_sha256": sha(DB),
    "source_registry_sha256": sha(UPDATE / "source_registry.json"),
    "datasets": [{**row, "local_preview_present": by_dataset[row["dataset"]]["local_preview_present"]}
                 for row in dataset_stats],
    "exceptions": {
        "missing_registry": missing_registry[:100],
        "missing_targets": missing_targets[:100],
        "missing_links": missing_links[:100],
        "missing_preview_files": missing_files[:100],
        "downloaded_missing": downloaded_missing[:100],
        "downloaded_hash_mismatch": downloaded_hash_mismatch[:100],
    },
}
summary["passed_for_included_single_previews"] = all(summary[key] == 0 for key in (
    "missing_registry_count", "missing_target_count", "missing_image_link_count",
    "missing_preview_file_count", "downloaded_preview_missing_count",
    "downloaded_preview_hash_mismatch_count"))
(HERE / "AUDIT.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: summary[key] for key in (
    "catalog_entry_count", "catalog_image_entry_count", "included_image_entries",
    "held_or_empty_image_entries", "included_extra_image_references",
    "missing_preview_file_count", "downloaded_preview_hash_mismatch_count",
    "passed_for_included_single_previews")}, ensure_ascii=False))
if not summary["passed_for_included_single_previews"]:
    raise SystemExit(1)
