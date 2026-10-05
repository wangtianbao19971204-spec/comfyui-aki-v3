"""Read-only 15-dataset coverage audit after the Raven increment."""
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CURRENT = ROOT / "benchmark_reports/2026-09-28_web_image_reaudit/current_web"
OLD = ROOT / "benchmark_reports/2026-09-27_codex_update"
PROD = ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector"
DATA = PROD / "user_data/prompt_selector/data.json"
DB = PROD / "user_data/userdatas_zh_CN_tags.db"
PREVIEW = DATA.parent / "preview"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


old_registry = {r["source"]: r for r in read(OLD / "source_registry.json")}
new_registry = {r["source"]: r for r in read(HERE / "source_registry.json")}
assert not set(old_registry) & set(new_registry)
catalog = read(CURRENT / "codexes.json")
manifest = read(CURRENT / "manifest.json")
pointer = read(CURRENT / "current.json")
assert len(catalog) == 15 and manifest["contentHash"] == pointer["contentHash"]
data = read(DATA)
prompts = {p["id"]: p for c in data["categories"] for p in c["prompts"]}
counts = Counter()
tag_ids = set()
source_rows = []
missing = []
for meta in catalog:
    name = meta["id"] + (".external.json" if (CURRENT / (meta["id"] + ".external.json")).exists() else ".json")
    path = CURRENT / name
    if not path.exists():
        path = OLD / "sources/web" / name
    assert path.exists(), name
    if name in manifest["files"]:
        assert sha(path) == manifest["files"][name]["sha256"]
    for entry in read(path)["entries"]:
        source = meta["id"] + ":" + entry["id"]
        row = new_registry.get(source) or old_registry.get(source)
        if row is None:
            missing.append(source)
            continue
        counts["site_rows"] += 1
        if source in new_registry:
            counts["increment_rows"] += 1
        if not entry.get("image"):
            continue
        counts["image_rows"] += 1
        if row["disposition"] in ("excluded", "no_prompt_content"):
            counts["held_or_empty_image_rows"] += 1
            continue
        counts["included_image_rows"] += 1
        counts["extra_image_refs"] += max(0, len(entry.get("images") or []) - 1)
        source_rows.append((source, row))
        if row["disposition"].startswith("tag"):
            tag_ids.add(row["target_id"])
assert not missing and counts["site_rows"] == 41202 and counts["increment_rows"] == 816
assert counts["image_rows"] == 39224 and counts["included_image_rows"] == 36885

tag_meta = {}
with sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True) as db:
    ids = list(tag_ids)
    for index in range(0, len(ids), 400):
        chunk = ids[index:index + 400]
        marks = ",".join("?" for _ in chunk)
        for uid, payload in db.execute("select tag_uuid,data from workbench_tag_meta where tag_uuid in (" + marks + ")", chunk):
            tag_meta[uid] = json.loads(payload)

missing_target = []
missing_preview = []
new_source_image_missing = []
new_source_image_not_primary = []
for source, row in source_rows:
    if row["disposition"].startswith("tag"):
        item = tag_meta.get(row["target_id"])
        preview = item.get("preview") if item else None
    else:
        item = prompts.get(row["target_id"])
        preview = item.get("image") if item else None
    if not item:
        missing_target.append(source)
    elif not preview or not (PREVIEW / preview).is_file():
        missing_preview.append(source)
    if source in new_registry:
        local = row["local_preview"]
        if not (PREVIEW / local).is_file() or sha(PREVIEW / local) != row["image_sha256"]:
            new_source_image_missing.append(source)
        if preview != local:
            new_source_image_not_primary.append(source)
        assert any(x.get("entry_id") == source.split(":", 1)[1] and x.get("local_preview") == local
                   for x in item.get("external_sources", [])), source

old_receipts = read(OLD / "image_receipts.json")
old_image_failures = [r["filename"] for r in old_receipts
                      if not (PREVIEW / r["filename"]).is_file() or sha(PREVIEW / r["filename"]) != r["sha256"]]
result = {"passed": not (missing or missing_target or missing_preview or new_source_image_missing or old_image_failures),
          "created_at": datetime.now().astimezone().isoformat(), "release": pointer["release"],
          **dict(counts), "missing_source_rows": len(missing), "missing_targets": len(missing_target),
          "missing_primary_preview_files": len(missing_preview),
          "new_source_images_missing_or_changed": len(new_source_image_missing),
          "new_source_images_not_primary_preview": len(new_source_image_not_primary),
          "old_installed_image_failures": len(old_image_failures),
          "data_sha256": sha(DATA), "db_sha256": sha(DB),
          "exceptions": {"missing_sources": missing[:20], "missing_targets": missing_target[:20],
                         "missing_primary_previews": missing_preview[:20],
                         "new_source_images_not_primary": new_source_image_not_primary,
                         "old_installed_image_failures": old_image_failures[:20]}}
(HERE / "current_site_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: result[key] for key in ("passed", "site_rows", "image_rows", "included_image_rows",
                                                "held_or_empty_image_rows", "extra_image_refs",
                                                "new_source_images_not_primary_preview", "old_installed_image_failures")}, ensure_ascii=False))
assert result["passed"]
