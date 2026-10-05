"""Compare the current website release with the bound local release snapshot."""

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import orjson

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.with_name("2026-09-27_codex_update") / "sources/web"
CURRENT = HERE / "current_web"
DB = ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data/userdatas_zh_CN_tags.db"
PREVIEW = DB.parent / "prompt_selector/preview"


def read(path):
    return orjson.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value):
    value = unicodedata.normalize("NFKC", value or "").replace("_", " ").replace("\\", "")
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return re.sub(r"\s*([,:{}\[\]()])\s*", r"\1", value).strip(", ")


old_catalog = read(OLD / "codexes.json")
current_catalog = read(CURRENT / "codexes.json")
old_by_meta = {meta["id"]: meta for meta in old_catalog}
current_by_meta = {meta["id"]: meta for meta in current_catalog}
assert set(old_by_meta) == set(current_by_meta)
changed_datasets = []
for dataset in old_by_meta:
    old_file = OLD / (dataset + (".external.json" if (OLD / (dataset + ".external.json")).exists() else ".json"))
    new_file = CURRENT / (dataset + (".external.json" if (CURRENT / (dataset + ".external.json")).exists() else ".json"))
    if not new_file.exists():
        new_file = old_file
    old_entries = {row["id"]: row for row in read(old_file)["entries"]}
    new_entries = {row["id"]: row for row in read(new_file)["entries"]}
    added = [row for key, row in new_entries.items() if key not in old_entries]
    removed = [key for key in old_entries if key not in new_entries]
    changed = [key for key in new_entries if key in old_entries and new_entries[key] != old_entries[key]]
    changed_fields = Counter(field for key in changed for field in set(new_entries[key]) | set(old_entries[key])
                             if new_entries[key].get(field) != old_entries[key].get(field))
    if added or removed or changed:
        changed_datasets.append({"dataset": dataset, "old_entries": len(old_entries),
                                 "current_entries": len(new_entries), "added": len(added),
                                 "removed": len(removed), "changed": len(changed),
                                 "changed_fields": dict(changed_fields),
                                 "added_with_image": sum(bool(row.get("image")) for row in added)})
    if dataset == "raven_composition":
        raven_added = added

tags_by_body = defaultdict(list)
metadata = {}
with sqlite3.connect(DB) as db:
    for uid, body in db.execute("select t_uuid,text from tag_tags"):
        tags_by_body[norm(body)].append(uid)
    match_ids = {uid for row in raven_added for uid in tags_by_body.get(norm(row.get("tags", "")), [])}
    ids = list(match_ids)
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        marks = ",".join("?" for _ in chunk)
        for uid, payload in db.execute(f"select tag_uuid,data from workbench_tag_meta where tag_uuid in ({marks})", chunk):
            metadata[uid] = orjson.loads(payload)

rows = []
for entry in raven_added:
    matches = tags_by_body.get(norm(entry.get("tags", "")), [])
    target = min(matches) if matches else None
    meta = metadata.get(target, {}) if target else {}
    preview = meta.get("preview")
    rows.append({"source": "raven_composition:" + entry["id"],
                 "source_entry_sha256": hashlib.sha256(json.dumps(entry, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                 "rating": entry.get("rating"), "tag_text": entry.get("tags", ""),
                 "image": entry.get("image"), "asset_rev": entry.get("assetRev"),
                 "existing_same_body_tag_id": target,
                 "existing_preview": preview,
                 "existing_preview_file_present": bool(preview and (PREVIEW / preview).is_file()),
                 "website_image_not_in_prior_release": True})

summary = {
    "schema": "current-web-image-gap/v1",
    "created_at": datetime.now().astimezone().isoformat(),
    "old_release": read(OLD / "current.json")["release"],
    "current_release": read(CURRENT / "current.json")["release"],
    "current_published_at": read(CURRENT / "current.json").get("publishedAt"),
    "old_catalog_sha256": sha(OLD / "codexes.json"),
    "current_catalog_sha256": sha(CURRENT / "codexes.json"),
    "current_raven_sha256": sha(CURRENT / "raven_composition.json"),
    "current_external_sha256": sha(CURRENT / "mengshen_r18.external.json"),
    "changed_datasets": changed_datasets,
    "new_image_entries": len(rows),
    "new_entries_rating_safe": all(row["rating"] == "safe" for row in rows),
    "new_entries_with_same_body_tag": sum(bool(row["existing_same_body_tag_id"]) for row in rows),
    "new_entries_without_same_body_tag": sum(not row["existing_same_body_tag_id"] for row in rows),
    "same_body_tags_with_preview_file": sum(row["existing_preview_file_present"] for row in rows),
    "new_entry_image_count": sum(bool(row["image"]) for row in rows),
    "new_entry_multi_image_count": sum(len(entry.get("images") or []) > 1 for entry in raven_added),
    "rows_file": "CURRENT_GAP_ROWS.jsonl",
}
(HERE / "CURRENT_GAP.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
with (HERE / "CURRENT_GAP_ROWS.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
    for row in rows:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
print(json.dumps({key: summary[key] for key in (
    "old_release", "current_release", "new_image_entries",
    "new_entries_with_same_body_tag", "new_entries_without_same_body_tag",
    "same_body_tags_with_preview_file")}, ensure_ascii=False))
