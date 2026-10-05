"""Prove the Raven stage changes only declared Tag rows and source previews."""
import json
import hashlib
import re
import shutil
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AUDIT = ROOT / "benchmark_reports/2026-09-28_web_image_reaudit"
WEB = AUDIT / "current_web"
OLD_WEB = ROOT / "benchmark_reports/2026-09-27_codex_update/sources/web"
PROD = ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector"
DATA = PROD / "user_data/prompt_selector/data.json"
DB = PROD / "user_data/userdatas_zh_CN_tags.db"
BACKUP = HERE / "backup"
STAGE = HERE / "stage"


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


def norm(value):
    value = unicodedata.normalize("NFKC", value or "").replace("_", " ").replace("\\", "")
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return re.sub(r"\s*([,:{}\[\]()])\s*", r"\1", value).strip(", ")

ops = read(HERE / "operations.json")
registry = read(HERE / "source_registry.json")
receipts = read(HERE / "image_receipts.json")
old_ids = {e["id"] for e in read(OLD_WEB / "raven_composition.json")["entries"]}
entries = {e["id"]: e for e in read(WEB / "raven_composition.json")["entries"] if e["id"] not in old_ids}
assert len(ops) == len(registry) == len(receipts) == len(entries) == 816
assert sha(DATA) == sha(BACKUP / "data.json")
receipt_by_source = {r["source"]: r for r in receipts}
for item in receipts:
    path = STAGE / "images" / item["filename"]
    assert item["status"] == "ok" and sha(path) == item["sha256"]
    with Image.open(path) as image:
        image.verify()


def table(db, name, key):
    db.row_factory = sqlite3.Row
    return {r[key]: dict(r) for r in db.execute("select * from " + name)}


with sqlite3.connect(BACKUP / "tags.db") as old, sqlite3.connect(STAGE / "tags.db") as new:
    assert new.execute("pragma integrity_check").fetchone()[0] == "ok"
    assert not new.execute("pragma foreign_key_check").fetchall()
    before = table(old, "tag_tags", "t_uuid")
    after = table(new, "tag_tags", "t_uuid")
    old_meta = {uid: json.loads(data) for uid, data in old.execute("select tag_uuid,data from workbench_tag_meta")}
    new_meta = {uid: json.loads(data) for uid, data in new.execute("select tag_uuid,data from workbench_tag_meta")}
    touched = {r["target_id"] for r in registry}
    added = set(after) - set(before)
    assert len(added) == 445 and not (set(before) - set(after))
    assert len(after) == len(before) + 445
    assert len(touched) == 811 and added <= touched
    for uid, row in before.items():
        if uid not in touched:
            assert row == after[uid] and old_meta.get(uid) == new_meta.get(uid), uid
        else:
            assert {k: v for k, v in row.items() if k != "text"} == {k: v for k, v in after[uid].items() if k != "text"}, uid
            assert norm(row["text"]) == norm(after[uid]["text"]), uid
            before_m, after_m = old_meta.get(uid, {}), new_meta[uid]
            for key in set(before_m) | set(after_m):
                if key not in ("preview", "external_source", "external_sources", "folder_ids"):
                    assert before_m.get(key) == after_m.get(key), (uid, key)
    assert len(new_meta) - len(old_meta) == 445
    all_folders = {row[0] for row in new.execute("select g_uuid from tag_subgroups")}
    membership = {(uid, fid) for uid, fid in new.execute("select tag_uuid,g_uuid from workbench_tag_folder_members where tag_uuid in (" + ",".join("?" for _ in touched) + ")", tuple(touched))}
    for uid in touched:
        ids = new_meta[uid].get("folder_ids") or []
        assert set(ids) <= all_folders
        assert {(uid, fid) for fid in ids} == {p for p in membership if p[0] == uid}
    baseline_pairs = read(DATA.with_name("shared_pairs.json"))["pairs"]
    paired = touched & set(baseline_pairs.values())
    assert all(norm(before[uid]["text"]) == norm(after[uid]["text"]) for uid in paired)
    old_revision = old.execute("select value from workbench_tag_revision where id=1").fetchone()[0]
    new_revision = new.execute("select value from workbench_tag_revision where id=1").fetchone()[0]
    assert new_revision > old_revision

    assigned = defaultdict(list)
    for row in registry:
        source = row["source"]
        e = entries[source.split(":", 1)[1]]
        uid = row["target_id"]
        assert norm(after[uid]["text"]) == norm(e["tags"]), source
        assert row["source_sha256"] == receipt_by_source[source]["source_entry_sha256"]
        assert row["image_sha256"] == receipt_by_source[source]["sha256"]
        matches = [s for s in new_meta[uid]["external_sources"] if s.get("dataset") == "raven_composition" and s.get("entry_id") == e["id"]]
        assert len(matches) == 1 and matches[0]["image_sha256"] == row["image_sha256"]
        assert matches[0]["local_preview"] == row["local_preview"]
        assigned[uid].append(row)
    for uid, rows in assigned.items():
        assert new_meta[uid]["preview"] == rows[-1]["local_preview"]
    review = [json.loads(line) for line in (HERE / "classification_review.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(review) == 816
    assert all(new_meta[uid].get("themes") or new_meta[uid].get("facets") for uid in added), "New tags lack semantic classification"

# Test the binary replacement and recovery sequence away from production.
drill = HERE / "rollback_drill"
drill.mkdir(exist_ok=True)
target = drill / "tags.db"
shutil.copy2(STAGE / "tags.db", target)
assert sha(target) == sha(STAGE / "tags.db")
shutil.copy2(BACKUP / "tags.db", target)
assert sha(target) == sha(BACKUP / "tags.db")

result = {"passed": True, "source_rows": len(registry), "unique_targets": len(touched),
          "new_tags": len(added), "existing_targets_updated": len(touched - added),
          "images_verified": len(receipts), "source_images_not_primary_preview": len(registry) - len(touched),
          "data_sha256": sha(DATA), "baseline_db_sha256": sha(BACKUP / "tags.db"),
          "stage_db_sha256": sha(STAGE / "tags.db"), "tag_revision_before": old_revision,
          "tag_revision_after": new_revision, "paired_existing_tags_unchanged_semantically": len(paired),
          "rollback_drill_passed": True}
save(HERE / "stage_validation.json", result)
print("VALIDATION_PASS", json.dumps(result, ensure_ascii=False), flush=True)
