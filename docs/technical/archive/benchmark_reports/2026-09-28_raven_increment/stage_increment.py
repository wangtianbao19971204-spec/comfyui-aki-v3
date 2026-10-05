"""Stage the pinned Raven increment without editing production."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import sqlite3
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

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
EXPECTED_DATA = "40490c2c8fded8efb85572292970016ea34462b64a216e454190cb73d9386af6"
EXPECTED_DB = "341d88e9538ee432750a4617ebccb0aebf4ff671c933104c5fbb114a0dc627c9"


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


def classify(e):
    """Broad Tag facets from the full positive tag; title/note are reviewed context."""
    top = (e.get("path") or [""])[0]
    tag = e["tags"].casefold()
    themes, facets = set(), set()
    reason = "完整 tag 与原注语义"
    if top in ("颈部配饰", "身体配饰"):
        themes.add("服饰›配饰")
    elif top == "日常行为":
        themes.add("动作›行为")
    elif top == "物体互动":
        themes.add("动作›手部" if tag.startswith("holding_") or tag in ("two-handed", "reaching_for", "picking_up", "putting_down", "passing", "offering") else "动作›行为")
        if tag.startswith("holding_"):
            themes.add("道具›器物")
    elif top == "视角构图":
        themes.add("画面›构图")
    elif top == "色彩光影":
        if any(x in tag for x in ("lamp", "lantern")):
            themes.add("道具›器物")
            themes.add("画面›打光")
        elif any(x in tag for x in ("light", "shadow", "refraction", "scattering", "darkness", "dawn")):
            themes.add("画面›打光")
        elif any(x in tag for x in ("filter", "aberration")):
            themes.add("画面›技法")
        else:
            themes.add("画面›配色")
    elif top == "招牌梗":
        if "against_fourth_wall" in tag:
            themes.update(("动作›手部", "画面›构图"))
        elif tag == "speakiposting_(meme)":
            themes.add("动作›姿态")
            reason = "原注明确四肢着地趴姿"
        elif tag == "yandere_trance":
            themes.add("动作›手部")
            facets.add("外貌›面部")
            reason = "原注明确双手捧脸及恍惚表情"
        elif any(x in tag for x in ("finger", "hand")):
            themes.add("动作›手部")
        else:
            themes.add("动作›姿态")
    elif top == "身体部位":
        if tag == "elbows_on_table":
            themes.add("动作›姿态")
        elif tag == "index_fingers_together":
            themes.add("动作›手部")
        elif tag in ("neck_ribbon", "waist_apron", "nail_polish"):
            themes.add("服饰›配饰")
        elif tag in ("hands_up", "crossed_ankles"):
            themes.add("动作›姿态")
        elif tag == "sleeves_past_wrists":
            themes.add("服饰›上装")
        else:
            facets.add("外貌›面部" if tag in ("eyebrows", "moustache", "beard", "sideburns") else "外貌›身体")
    else:
        reason = "没有足够正文证据；暂不加主题"
    return sorted(themes), sorted(facets), reason


assert sha(DATA) == EXPECTED_DATA and sha(DB) == EXPECTED_DB, "Production changed since gap audit"
gap = read(AUDIT / "CURRENT_GAP.json")
pointer = read(WEB / "current.json")
manifest = read(WEB / "manifest.json")
assert pointer["release"] == gap["current_release"] == "r-9a4bf4049f141be7d4d9"
assert manifest["contentHash"] == pointer["contentHash"]
assert sha(WEB / "raven_composition.json") == manifest["files"]["raven_composition.json"]["sha256"]
old_ids = {e["id"] for e in read(OLD_WEB / "raven_composition.json")["entries"]}
entries = [e for e in read(WEB / "raven_composition.json")["entries"] if e["id"] not in old_ids]
assert len(entries) == gap["new_image_entries"] == 816
plan = {r["source"]: r for r in read(HERE / "image_plan.json")}
receipts = {r["source"]: r for r in read(HERE / "image_receipts.json")}
assert len(plan) == len(receipts) == 816
for key, receipt in receipts.items():
    assert receipt["status"] == "ok" and sha(STAGE / "images" / receipt["filename"]) == receipt["sha256"], key

BACKUP.mkdir(exist_ok=True)
if not (BACKUP / "tags.db").exists():
    with sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True) as src, sqlite3.connect(BACKUP / "tags.db") as dst:
        src.backup(dst)
assert sha(DB) == EXPECTED_DB
shutil.copy2(BACKUP / "tags.db", STAGE / "tags.db")
shutil.copy2(DATA, BACKUP / "data.json")
stamp = datetime.now().astimezone().isoformat()

db = sqlite3.connect(STAGE / "tags.db")
db.row_factory = sqlite3.Row
tags = {r["t_uuid"]: dict(r) for r in db.execute("select * from tag_tags")}
metadata = {uid: json.loads(payload) for uid, payload in db.execute("select tag_uuid,data from workbench_tag_meta")}
by_body = defaultdict(list)
for uid, row in tags.items():
    by_body[norm(row["text"])].append(uid)
groups = {r["name"]: dict(r) for r in db.execute("select * from tag_groups")}
folders = {(r["p_uuid"], r["name"]): dict(r) for r in db.execute("select * from tag_subgroups")}
folder_name = {r["g_uuid"]: r["name"] for r in db.execute("select g_uuid,name from tag_subgroups")}
group_name = {r["p_uuid"]: r["name"] for r in db.execute("select p_uuid,name from tag_groups")}


def folder_for(e):
    parts = e.get("path") or ["渡鸦的构图鉴"]
    area = parts[0]
    name = " / ".join(parts[1:]) or "主目录"
    if area not in groups:
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, "quicktagcloud:area:" + area))
        cur = db.execute("insert into tag_groups(name,color,create_time,p_uuid) values (?,?,?,?)",
                         (area, "", int(datetime.now().timestamp()), uid))
        groups[area] = {"p_uuid": uid, "id_index": cur.lastrowid}
        group_name[uid] = area
    group = groups[area]
    key = (group["p_uuid"], name)
    if key not in folders:
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, "quicktagcloud:folder:" + area + "/" + name))
        cur = db.execute("insert into tag_subgroups(group_id,name,color,create_time,p_uuid,g_uuid) values (?,?,?,?,?,?)",
                         (group["id_index"], name, "", int(datetime.now().timestamp()), group["p_uuid"], uid))
        folders[key] = {"id_index": cur.lastrowid, "g_uuid": uid}
        folder_name[uid] = name
    return folders[key]


def choose(candidates, e, themes, facets):
    def score(uid):
        row = tags[uid]
        meta = metadata.get(uid, {})
        sources = [meta.get("external_source", {}), *(meta.get("external_sources") or [])]
        existing = set(meta.get("themes") or []) | set(meta.get("facets") or [])
        folder = folders.get((groups[e["path"][0]]["p_uuid"], " / ".join(e["path"][1:]) or "主目录"), {})
        return (any(s.get("dataset") == "raven_composition" for s in sources),
                bool(existing & (set(themes) | set(facets))),
                folder.get("g_uuid") in set(meta.get("folder_ids") or []) or row["g_uuid"] == folder.get("g_uuid"),
                row["text"] == e["tags"], bool(meta.get("preview")))
    return max(sorted(candidates, reverse=True), key=score)


operations = []
registry = []
review = []
selected = {}
created_ids = set()
for e in entries:
    assert e.get("rating") == "safe" and e.get("image") and len(e.get("images") or []) == 1
    source = "raven_composition:" + e["id"]
    body = e["tags"]
    key = norm(body)
    themes, facets, reason = classify(e)
    folder = folder_for(e)
    candidates = by_body.get(key, [])
    uid = selected.get(key) or (choose(candidates, e, themes, facets) if candidates else None)
    action = "existing" if uid else "added"
    before_text = tags[uid]["text"] if uid else None
    if not uid:
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, "quicktagcloud:body:" + key))
        assert uid not in tags
        db.execute("insert into tag_tags(subgroup_id,text,desc,color,create_time,t_uuid,g_uuid) values (?,?,?,?,?,?,?)",
                   (folder["id_index"], body, e.get("title", ""), "", int(datetime.now().timestamp()), uid, folder["g_uuid"]))
        tags[uid] = dict(db.execute("select * from tag_tags where t_uuid=?", (uid,)).fetchone())
        by_body[key].append(uid)
        created_ids.add(uid)
    elif tags[uid]["text"] != body:
        assert norm(tags[uid]["text"]) == key
        db.execute("update tag_tags set text=? where t_uuid=?", (body, uid))
        tags[uid]["text"] = body
    selected[key] = uid
    old_meta = copy.deepcopy(metadata.get(uid, {}))
    meta = copy.deepcopy(old_meta)
    previous = meta.get("external_source")
    source_url = "https://novelai.quicktagcloud.com/?c=raven_composition&id=" + quote(e["id"])
    provenance = {"dataset": "raven_composition", "entry_id": e["id"], "release": pointer["release"],
                  "version": "2026.9.27", "url": source_url, "rating": e["rating"],
                  "title": e.get("title"), "note": e.get("note", ""), "path": e.get("path", []),
                  "tags": body, "source_sha256": hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                  "image": e["image"], "asset_rev": e.get("assetRev"),
                  "local_preview": plan[source]["filename"], "image_sha256": receipts[source]["sha256"]}
    sources = meta.get("external_sources") or []
    if previous and previous.get("entry_id") not in {s.get("entry_id") for s in sources}:
        sources.append(previous)
    sources = [s for s in sources if not (s.get("dataset") == provenance["dataset"] and s.get("entry_id") == provenance["entry_id"])]
    sources.append(provenance)
    meta["external_sources"] = sources
    meta["external_source"] = provenance
    meta["preview"] = plan[source]["filename"]
    meta["folder_ids"] = sorted(set(meta.get("folder_ids") or []) | {folder["g_uuid"]})
    if uid in created_ids:
        meta["themes"] = sorted(set(meta.get("themes") or []) | set(themes))
        meta["facets"] = sorted(set(meta.get("facets") or []) | set(facets))
    if action == "added":
        meta["notes"] = "来源：渡鸦的构图鉴 2026.9.27\n" + source_url + ("\n原注：" + e["note"] if e.get("note") else "")
    db.execute("insert into workbench_tag_meta(tag_uuid,data) values (?,?) on conflict(tag_uuid) do update set data=excluded.data",
               (uid, json.dumps(meta, ensure_ascii=False)))
    metadata[uid] = meta
    operations.append({"source": source, "target_id": uid, "action": action, "before_text": before_text,
                       "old_preview": old_meta.get("preview"), "new_preview": meta["preview"],
                       "before_meta_sha256": hashlib.sha256(json.dumps(old_meta, ensure_ascii=False, sort_keys=True).encode()).hexdigest() if action == "existing" else None,
                       "source_sha256": provenance["source_sha256"]})
    registry.append({"source": source, "source_sha256": provenance["source_sha256"], "disposition": "tag_existing_updated" if action == "existing" else "tag_added",
                     "target_id": uid, "image_sha256": provenance["image_sha256"], "local_preview": provenance["local_preview"]})
    review.append({"source": source, "tag": body, "title": e.get("title"), "note": e.get("note"), "source_path": e.get("path"),
                   "target_id": uid, "existing_matches": len(candidates), "themes": meta.get("themes", []), "facets": meta.get("facets", []),
                   "classification_reason": reason, "source_image": e["image"]})

db.commit()
assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
assert not db.execute("pragma foreign_key_check").fetchall()
assert len(registry) == 816 and len({r["source"] for r in registry}) == 816
assert len(selected) == 811
db.close()
save(HERE / "operations.json", operations)
save(HERE / "source_registry.json", registry)
with (HERE / "classification_review.jsonl").open("w", encoding="utf-8", newline="\n") as out:
    for row in review:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
save(HERE / "stage_summary.json", {"created_at": stamp, "source_release": pointer["release"],
     "source_rows": len(registry), "unique_tag_bodies": len(selected),
     "tag_added": sum(x["action"] == "added" for x in operations),
     "tag_existing_source_rows": sum(x["action"] == "existing" for x in operations),
     "images_downloaded": len(receipts), "stage_db_sha256": sha(STAGE / "tags.db"),
     "production_data_sha256": sha(DATA), "baseline_db_sha256": sha(BACKUP / "tags.db")})
save(HERE / "EXECUTION_STATE.json", {"status": "staged_unreleased", "production_mutated": False,
     "updated_at": stamp, "summary": "stage_summary.json"})
print("STAGED", len(registry), "SOURCES", len(selected), "UNIQUE TAGS", flush=True)
