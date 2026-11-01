"""Build and exhaustively check an offline, review-bound website update.

Never imports the production server, opens a writable input, or deploys files.
Source identity decisions belong in the supplied review, not fuzzy matching.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import importlib
import json
import sqlite3
import shutil
import sys
import types
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(packed(value).encode("utf-8")).hexdigest()


def file_hash(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def connect(path, readonly=False):
    return sqlite3.connect(Path(path).resolve().as_uri() + ("?mode=ro" if readonly else ""), uri=True)


def backup(source, target):
    with closing(connect(source, True)) as origin, closing(connect(target)) as destination:
        origin.backup(destination)


def complete_body(entry):
    """Exact positive text plus ordered character segments; no case folding."""
    text = entry.get("tags", "")
    if not isinstance(text, str):
        raise ValueError("positive text must be a string")
    for part in entry.get("characterPrompts", []):
        body = part.get("prompt", "")
        if not isinstance(body, str):
            raise ValueError("character text must be a string")
        if body:
            text += "\n" + str(part.get("label") or "character") + ": " + body
    return text.strip()


def body_identity(entry):
    # Structured key avoids delimiter collisions in the rendered body.
    return packed([entry.get("tags", ""), entry.get("characterPrompts", [])])


def verified_web(web, name):
    manifest = read(web / "manifest.json")
    spec = manifest["files"][name]
    path = web / name
    if path.stat().st_size != spec["size"] or file_hash(path) != spec["sha256"]:
        raise ValueError("source manifest mismatch: " + name)
    return read(path)


def variant(dataset, entry, release):
    return {"dataset": dataset, "entry_id": entry["id"], "release": release,
            "url": "https://novelai.quicktagcloud.com/?c=" + quote(dataset) + "&id=" + quote(entry["id"]),
            "source_sha256": digest(entry), "body_sha256": hashlib.sha256(complete_body(entry).encode()).hexdigest(),
            "raw_entry": copy.deepcopy(entry), "tags": entry.get("tags", ""),
            "character_prompts": copy.deepcopy(entry.get("characterPrompts", [])),
            "negative": entry.get("negative", ""), "rating": entry.get("rating"),
            "image": entry.get("image"), "images": copy.deepcopy(entry.get("images", [])),
            "asset_rev": entry.get("assetRev"), "path": copy.deepcopy(entry.get("path", [])),
            "title": entry.get("title", ""), "note": entry.get("note", "")}


def add_history(payload, variants, underscore=True, preserve_primary=False):
    result = copy.deepcopy(payload)
    prefix = "_" if underscore else ""
    key, current = prefix + "external_sources", prefix + "external_source"
    history = list(result.get(key) or [])
    prior = result.get(current)
    matching_primary = [v for v in variants if isinstance(prior, dict)
                        and (v.get("dataset"), v.get("entry_id")) == (prior.get("dataset"), prior.get("entry_id"))]
    replaces_primary = not preserve_primary or bool(matching_primary and packed(matching_primary[-1]) != packed(prior))
    if prior and replaces_primary and packed(prior) not in {packed(x) for x in history}:
        history.append(copy.deepcopy(result[current]))
    seen = {packed(x) for x in history}
    for item in variants:
        if packed(item) not in seen:
            history.append(copy.deepcopy(item))
            seen.add(packed(item))
    result[key] = history  # Deliberately unbounded: never discard prior provenance.
    previous = result.get(current)
    if preserve_primary and isinstance(previous, dict):
        identity = (previous.get("dataset"), previous.get("entry_id"))
        matching = [v for v in variants if (v.get("dataset"), v.get("entry_id")) == identity]
        result[current] = copy.deepcopy(matching[-1] if matching else previous)
    elif preserve_primary:
        # A metadata-only revision must not invent a primary source.
        pass
    else:
        result[current] = copy.deepcopy(variants[-1])
    return result


def require_native_owner(conn, source_map, categories, entry_id, row):
    """A declared native alias governs ownership even while its old row exists."""
    source_id = "codex-" + entry_id
    mapping = source_map.get(source_id)
    physical = conn.execute("SELECT 1 FROM prompts WHERE id=?", (source_id,)).fetchone()
    if mapping is not None:
        if not isinstance(mapping, dict) or not all(isinstance(mapping.get(k), str) and mapping[k] for k in ("canonical_id", "source_category_id")):
            raise ValueError("invalid baseline native source alias")
        if row["store"] != "library" or row["target_id"] != mapping["canonical_id"]:
            raise ValueError("review target disagrees with native canonical owner: " + source_id)
        target = conn.execute("SELECT category_id,payload FROM prompts WHERE id=?", (mapping["canonical_id"],)).fetchone()
        if target is None:
            raise ValueError("native canonical owner missing")
        document = {"_source_to_canonical": source_map,
                    "categories": [{**categories[target[0]], "prompts": [json.loads(target[1])]}]}
        for category_id in ("", mapping["source_category_id"]):
            resolved = native("prompt_merge").merged_source(document, source_id, category_id)
            if resolved is None or resolved[1]["id"] != row["target_id"]:
                raise ValueError("native source owner did not resolve")
    elif physical is not None:
        if row["store"] != "library" or row["target_id"] != source_id:
            raise ValueError("review target disagrees with physical source owner")
    elif row.get("match") != "explicit":
        raise ValueError("source without native identity requires explicit provenance")


def native(name):
    module_path = Path(__file__).resolve().parents[2] / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector" / (name + ".py")
    package_name = "_offline_source_native"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(module_path.parent)]
        sys.modules[package_name] = package
    return importlib.import_module(package_name + "." + name)


def binding(category, prompt):
    # Same native binding contract, without importing the server package.
    personal = {"is_user_plan", "favorite", "usage_count", "last_used", "created_at", "updated_at", "image", "_classification", "_selector_favorites", "_collection"}
    return digest([{k: v for k, v in category.items() if k != "prompts" and k not in personal},
                   {k: v for k, v in prompt.items() if k not in personal}])


def all_tables(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def table_hash(conn, table, exclude_ids=(), identity=None):
    columns = [r[1] for r in conn.execute('PRAGMA table_info("' + table + '")')]
    excluded = set(exclude_ids)
    index = columns.index(identity) if identity else None
    hasher = hashlib.sha256()
    order = ",".join('"' + c + '"' for c in columns)
    count = 0
    for row in conn.execute('SELECT * FROM "' + table + '" ORDER BY ' + order):
        if index is not None and row[index] in excluded:
            continue
        hasher.update(packed(list(row)).encode()); hasher.update(b"\n")
        count += 1
    return {"rows": count, "sha256": hasher.hexdigest()}


def export_document(conn, path):
    """Stream the native store shape, preserving top-level/category/prompt order."""
    store = native("library_store")
    meta = {k: json.loads(v) for k, v in conn.execute("SELECT key,value FROM library_meta")}
    order = meta.pop(store.META_TOP_LEVEL_ORDER, [])
    meta = {k: v for k, v in meta.items() if k not in store.INTERNAL_META_KEYS}
    keys = [k for k in order if k == "categories" or k in meta]
    keys += [k for k in meta if k not in keys]
    if "categories" not in keys:
        keys.append("categories")
    with Path(path).open("w", encoding="utf-8", newline="") as output:
        output.write("{")
        for key_index, key in enumerate(keys):
            output.write(("," if key_index else "") + json.dumps(key) + ":")
            if key != "categories":
                output.write(packed(meta[key])); continue
            output.write("[")
            for ci, (cid, name, raw) in enumerate(conn.execute("SELECT id,name,payload FROM categories ORDER BY position,id")):
                category = json.loads(raw); category.setdefault("id", cid); category.setdefault("name", name)
                category.pop("prompts", None)
                output.write(("," if ci else "") + packed(category)[:-1] + ',"prompts":[')
                row = conn.execute("SELECT order_json FROM category_orders WHERE category_id=?", (cid,)).fetchone()
                ids = json.loads(row[0]) if row else []
                rows = dict(conn.execute("SELECT id,payload FROM prompts WHERE category_id=?", (cid,)))
                if len(ids) != len(set(ids)) or set(ids) != set(rows):
                    raise ValueError("category/order mismatch: " + cid)
                for pi, pid in enumerate(ids):
                    output.write(("," if pi else "") + rows[pid])
                output.write("]}")
            output.write("]")
        output.write("}")


def stage(args):
    web, baseline = Path(args.web).resolve(), Path(args.baseline_web).resolve()
    output = Path(args.output).resolve()
    inputs = [Path(args.library).resolve(), Path(args.tags).resolve(), Path(args.review).resolve()]
    if args.dictionary:
        inputs.append(Path(args.dictionary).resolve())
    if output.exists() or any(output == p or output in p.parents for p in [web, baseline, *inputs]):
        raise ValueError("output must be a new isolated directory")
    review = read(args.review)
    if review.get("schema") != 1:
        raise ValueError("unsupported stage review schema")
    for path, expected_hash in review.get("inputs", {}).items():
        if file_hash(path) != expected_hash:
            raise ValueError("review input drift: " + path)
    if review.get("inputs"):
        approved_hashes = set(review["inputs"].values())
        for path in inputs:
            if path != Path(args.review).resolve() and file_hash(path) not in approved_hashes:
                raise ValueError("database input is not bound by the review")
    dataset = review["dataset"]
    current = verified_web(web, dataset + ".json")
    prior = verified_web(baseline, dataset + ".json")
    new_release, old_release = read(web / "current.json")["release"], read(baseline / "current.json")["release"]
    if (review["current_release"], review["baseline_release"]) != (new_release, old_release):
        raise ValueError("review release mismatch")
    entries, old_entries = ({e["id"]: e for e in value["entries"]} for value in [current, prior])
    if len(entries) != len(current["entries"]) or len(old_entries) != len(prior["entries"]):
        raise ValueError("duplicate source IDs")
    if set(old_entries) - set(entries):
        raise ValueError("source deletions require a separate review")
    added = set(entries) - set(old_entries)
    changed = {i for i in entries.keys() & old_entries.keys() if packed(entries[i]) != packed(old_entries[i])}
    updates = review["existing"]
    if len({r["entry_id"] for r in updates}) != len(updates) or {r["entry_id"] for r in updates} != changed:
        raise ValueError("review must cover every changed source once")
    groups = review["new_groups"]
    reviewed_added = [i for group in groups for i in group["entry_ids"]]
    if len(reviewed_added) != len(set(reviewed_added)) or set(reviewed_added) != added:
        raise ValueError("new groups must cover every added source once")
    expected = review["expected"]
    if (len(added), len(changed), len(groups)) != (expected["added_sources"], expected["changed_sources"], expected["new_resources"]):
        raise ValueError("review count mismatch")
    for i in changed:
        fields = {k for k in entries[i].keys() | old_entries[i].keys() if packed(entries[i].get(k)) != packed(old_entries[i].get(k)) or (k in entries[i]) != (k in old_entries[i])}
        if not fields <= {"rating", "isNew"}:
            raise ValueError("existing source changed outside metadata review")
    for group in groups:
        if len({body_identity(entries[i]) for i in group["entry_ids"]}) != 1:
            raise ValueError("new group contains different complete positive bodies")
    images = {}
    image_receipts = getattr(args, "image_receipts", None)
    image_dir = getattr(args, "image_dir", None)
    if bool(image_receipts) != bool(image_dir):
        raise ValueError("image receipts and directory must be supplied together")
    if image_receipts:
        for receipt in read(image_receipts):
            if receipt.get("dataset") != dataset:
                continue
            eid = receipt["entry_id"]
            name = receipt["filename"]
            if Path(name).name != name or eid in images or eid not in added:
                raise ValueError("invalid or duplicate image receipt")
            entry = entries[eid]
            media = verified_web(web, "media.json")
            expected_url = media["baseUrl"].rstrip("/") + "/" + media.get("imagePrefix", "images") + "/" + quote(entry.get("assetCodexId") or dataset) + "/" + quote(entry["image"])
            if entry.get("assetRev"):
                expected_url += "?v=" + quote(entry["assetRev"])
            if receipt["url"] != expected_url or not receipt.get("decoded") or (receipt["width"], receipt["height"]) != (entry["imageWidth"], entry["imageHeight"]):
                raise ValueError("image receipt source identity mismatch")
            path = Path(image_dir) / name
            if file_hash(path) != receipt["sha256"] or path.stat().st_size != receipt["bytes"]:
                raise ValueError("image receipt mismatch")
            images[eid] = receipt
        if set(images) != added:
            raise ValueError("image receipts must cover all new sources")
    output.mkdir(parents=True)
    for source, name in [(args.library, "library.sqlite3"), (args.tags, "tags.sqlite3")]:
        backup(source, output / name)
    if args.dictionary:
        backup(args.dictionary, output / "dictionary.sqlite3")
    if images:
        (output / "images").mkdir()
        for receipt in images.values():
            shutil.copyfile(Path(image_dir) / receipt["filename"], output / "images" / receipt["filename"])
        save(output / "image_receipts.json", list(images.values()))
    stamp = datetime.now(timezone.utc).isoformat()
    registry, library_changed, tag_changed, created = [], {}, {}, {}
    with closing(connect(output / "library.sqlite3")) as lib, closing(connect(output / "tags.sqlite3")) as tags:
        categories = {i: json.loads(p) for i, p in lib.execute("SELECT id,payload FROM categories")}
        row = lib.execute("SELECT value FROM library_meta WHERE key='_source_to_canonical'").fetchone()
        source_map = json.loads(row[0]) if row else {}
        original_source_map = copy.deepcopy(source_map)
        target_sources = {}
        for row in updates:
            eid = row["entry_id"]
            if row["disposition"] in {"hold", "excluded"}:
                if not row.get("reason"):
                    raise ValueError("held/excluded source requires a reason")
                registry.append({**row, "old": variant(dataset, old_entries[eid], old_release), "new": variant(dataset, entries[eid], new_release)})
                continue
            if row["disposition"] != "update" or row.get("match") not in {"direct", "explicit", "canonical"}:
                raise ValueError("unreviewed lineage mapping")
            require_native_owner(lib, original_source_map, categories, eid, row)
            store, pid = row["store"], row["target_id"]
            key = (store, pid)
            if key in target_sources and not row.get("allow_shared_target"):
                raise ValueError("multiple sources target one record without explicit review")
            target_sources.setdefault(key, []).append(eid)
            sources = [variant(dataset, old_entries[eid], old_release), variant(dataset, entries[eid], new_release)]
            if store == "library":
                stored = lib.execute("SELECT category_id,payload FROM prompts WHERE id=?", (pid,)).fetchone()
                if stored is None:
                    raise ValueError("reviewed library target missing")
                cid, raw = stored
                before = json.loads(raw)
                after = add_history(before, sources, preserve_primary=True)
                classification = after.get("_classification")
                if isinstance(classification, dict) and classification.get("binding") == binding(categories[cid], before):
                    classification["binding"] = binding(categories[cid], after)
                lib.execute("UPDATE prompts SET payload=? WHERE id=?", (packed(after), pid))
                library_changed.setdefault(pid, {"category_id": cid, "before": before, "before_raw": raw})["after"] = after
            elif store == "tags":
                stored = tags.execute("SELECT data FROM workbench_tag_meta WHERE tag_uuid=?", (pid,)).fetchone()
                if stored is None:
                    raise ValueError("reviewed tag metadata target missing")
                before = json.loads(stored[0]); after = add_history(before, sources, False, preserve_primary=True)
                tags.execute("UPDATE workbench_tag_meta SET data=? WHERE tag_uuid=?", (packed(after), pid))
                tag_changed.setdefault(pid, {"before": before})["after"] = after
            else:
                raise ValueError("unknown reviewed store")
            registry.append({**row, "old_source_sha256": digest(old_entries[eid]), "source_sha256": digest(entries[eid])})
        dedicated = "source-enter-review-" + hashlib.sha256(dataset.encode()).hexdigest()[:16]
        new_category_ids = set()
        orders = {}
        for group in groups:
            ids = group["entry_ids"]; eid = ids[0]; entry = entries[eid]; pid = group["target_id"]
            if pid in created or lib.execute("SELECT 1 FROM prompts WHERE id=?", (pid,)).fetchone():
                raise ValueError("new resource ID collision")
            cid = group.get("category_id") or dedicated
            if cid not in categories:
                name = group.get("category_name") or "网站来源 / " + dataset + " / 待复核"
                if cid != dedicated and cid != "web-cat-" + hashlib.sha1(name.encode()).hexdigest()[:16]:
                    raise ValueError("review category missing")
                new_category = {"id": cid, "name": name, "created_at": stamp, "updated_at": stamp}
                pos = lib.execute("SELECT coalesce(max(position),-1)+1 FROM categories").fetchone()[0]
                lib.execute("INSERT INTO categories VALUES (?,?,?,?)", (cid, new_category["name"], pos, packed(new_category)))
                categories[cid] = new_category
                new_category_ids.add(cid)
                lib.execute("INSERT INTO category_orders VALUES (?,?)", (cid, "[]"))
            if cid not in orders:
                orders[cid] = json.loads(lib.execute("SELECT order_json FROM category_orders WHERE category_id=?", (cid,)).fetchone()[0])
            payload = {"id": pid, "alias": entry.get("title", ""), "prompt": complete_body(entry),
                       "description": "来源：" + dataset + "；完整参数与负面提示词保存在来源修订中。", "image": "",
                       "tags": [], "favorite": False, "template": False, "usage_count": 0,
                       "created_at": stamp, "updated_at": stamp}
            variants = [variant(dataset, entries[i], new_release) for i in ids]
            for source_variant in variants:
                receipt = images.get(source_variant["entry_id"])
                if receipt:
                    source_variant.update(local_preview=receipt["filename"], image_sha256=receipt["sha256"], image_url=receipt["url"])
            payload = add_history(payload, variants)
            if images:
                payload["image"] = images[ids[-1]]["filename"]
            payload["description"] = "\n\n".join(
                str(entries[i].get("title") or i) + "\nhttps://novelai.quicktagcloud.com/?c=" + quote(dataset) + "&id=" + quote(i)
                + ("\n预览：" + images[i]["filename"] if i in images else "")
                + ("\n负面提示词：\n" + entries[i]["negative"] if entries[i].get("negative") else "") for i in ids)
            for i in ids:
                alias = "codex-" + i
                if alias != pid:
                    mapping = {"canonical_id": pid, "source_category_id": cid}
                    if alias in source_map and source_map[alias] != mapping:
                        raise ValueError("source canonical mapping collision")
                    source_map[alias] = mapping
            decision = copy.deepcopy(group.get("classification") or {"disposition": "pending", "reason": "source_import_needs_review",
                "manual_search_eligible": False, "random_pool_eligible": False, "strict_model_pool_eligible": False,
                "usage": "positive", "model_scope": "unknown", "content_type": "resource", "primary_class": None})
            if decision.get("semantic_review_status") == "user_confirmed":
                raise ValueError("offline import must not claim user confirmation")
            payload["template"] = decision.get("content_type") == "template"
            decision["binding"] = binding(categories[cid], payload)
            payload["_classification"] = decision
            lib.execute("INSERT INTO prompts VALUES (?,?,?)", (pid, cid, packed(payload)))
            orders[cid].append(pid); created[pid] = {"category_id": cid, "after": payload}
            for i in ids:
                registry.append({"entry_id": i, "disposition": "added", "store": "library", "target_id": pid, "source_sha256": digest(entries[i])})
        for cid, order in orders.items():
            lib.execute("UPDATE category_orders SET order_json=? WHERE category_id=?", (packed(order), cid))
        lib.execute("INSERT INTO library_meta(key,value) VALUES ('last_modified',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (packed(stamp),))
        if source_map != original_source_map:
            lib.execute("INSERT INTO library_meta(key,value) VALUES ('_source_to_canonical',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (packed(source_map),))
        for pid, change in {**library_changed, **created}.items():
            lib.execute("INSERT INTO library_journal(at,op,prompt_id,category_id,before,after) VALUES (?,?,?,?,?,?)",
                        (stamp, "update" if pid in library_changed else "create", pid, change["category_id"],
                         change.get("before_raw"), packed(change["after"])))
        lib.commit(); tags.commit()
        export_document(lib, output / "data.json")
        sync = native("shared_sync")
        pairs = sync.build_pairs(tags.execute("SELECT t_uuid,text FROM tag_tags"),
                                 ((pid, json.loads(raw).get("prompt")) for pid, raw in lib.execute("SELECT id,payload FROM prompts")))
        save(output / "shared_pairs.json", {"version": sync.PAIR_VERSION, "generated_at": stamp, "library_revision": stamp, **pairs})
    dictionary_changes = []
    if review.get("dictionary_insertions"):
        if not args.dictionary:
            raise ValueError("dictionary review requires --dictionary")
        with closing(connect(output / "dictionary.sqlite3")) as db:
            for item in review["dictionary_insertions"]:
                if db.execute("SELECT 1 FROM danbooru_tag WHERE lower(replace(tag,'_',' '))=?", (item["tag"].lower().replace("_", " "),)).fetchone():
                    raise ValueError("dictionary insertion would override existing tag")
                db.execute("INSERT INTO danbooru_tag(tag,color_id,translate,hot,aliases) VALUES (?,?,?,?,?)", (item["tag"], 0, item["translation"], 0, 0))
                dictionary_changes.append(item)
            db.commit()
    validation = validate(output, args, library_changed, tag_changed, created, orders, new_category_ids, registry, entries, changed | added, dictionary_changes)
    validation["images_verified"] = bool(images)
    save(output / "source_registry.json", registry)
    save(output / "dictionary_ledger.json", dictionary_changes)
    save(output / "stage_review.json", review)
    save(output / "stage_validation.json", validation)
    save(output / "stage_summary.json", {"source_release": new_release, "baseline_release": old_release,
         "added_sources": len(added), "changed_sources": len(changed), "new_resources": len(created),
         "library_updated": len(library_changed), "tag_metadata_updated": len(tag_changed),
         "dictionary_inserted": len(dictionary_changes), "production_modified": False,
         "classification_fully_reviewed": all(g.get("classification", {}).get("disposition") in {"reviewed", "classified"} for g in groups),
         "images_pending": not bool(images), "inputs": {str(p): file_hash(p) for p in inputs},
         "outputs": {p.name: file_hash(p) for p in output.iterdir() if p.is_file() and not p.name.endswith(("-wal", "-shm"))}})
    return validation


def validate(output, args, updated, tag_updated, created, orders, new_category_ids, registry, entries, covered, dictionary_changes):
    """Check every base row, including all unrelated tables and personal fields."""
    checks = {}
    with closing(connect(args.library, True)) as before, closing(connect(output / "library.sqlite3", True)) as after:
        if all_tables(before) != all_tables(after):
            raise AssertionError("library schema changed")
        ids = set(updated) | set(created)
        allowed = {"prompts": (ids, "id"), "category_orders": (set(orders), "category_id"),
                   "categories": (new_category_ids, "id"), "library_meta": ({"last_modified", "_source_to_canonical"}, "key")}
        for table in all_tables(before):
            if table == "library_journal":
                max_seq = before.execute("SELECT coalesce(max(seq),0) FROM library_journal").fetchone()[0]
                if list(before.execute("SELECT * FROM library_journal ORDER BY seq")) != list(after.execute("SELECT * FROM library_journal WHERE seq<=? ORDER BY seq", (max_seq,))):
                    raise AssertionError("prior journal changed")
                if after.execute("SELECT count(*) FROM library_journal WHERE seq>?", (max_seq,)).fetchone()[0] != len(ids):
                    raise AssertionError("journal append count mismatch")
                continue
            exclusion, key = allowed.get(table, ((), None))
            if table_hash(before, table, exclusion, key) != table_hash(after, table, exclusion, key):
                raise AssertionError("unrelated library rows changed: " + table)
        for pid, change in updated.items():
            old, new = change["before"], change["after"]
            ignored = {"_external_source", "_external_sources", "_classification"}
            if {k: v for k, v in old.items() if k not in ignored} != {k: v for k, v in new.items() if k not in ignored}:
                raise AssertionError("non-provenance fields changed")
            oc, nc = copy.deepcopy(old.get("_classification")), copy.deepcopy(new.get("_classification"))
            for c in [oc, nc]:
                if isinstance(c, dict): c.pop("binding", None)
            if packed(oc) != packed(nc): raise AssertionError("semantic decision changed")
            validate_history(old, new, True)
        for pid, change in created.items():
            payload = change["after"]
            row = after.execute("SELECT payload FROM categories WHERE id=?", (change["category_id"],)).fetchone()
            if payload["_classification"]["binding"] != binding(json.loads(row[0]), payload):
                raise AssertionError("new classification binding mismatch")
        for cid, order in orders.items():
            row = before.execute("SELECT order_json FROM category_orders WHERE category_id=?", (cid,)).fetchone()
            old_order = json.loads(row[0]) if row else []
            if order[:len(old_order)] != old_order or set(order[len(old_order):]) != {i for i, v in created.items() if v["category_id"] == cid}:
                raise AssertionError("existing order changed")
        if after.execute("SELECT count(*) FROM prompts").fetchone()[0] != before.execute("SELECT count(*) FROM prompts").fetchone()[0] + len(created):
            raise AssertionError("prompt count mismatch")
        maps = []
        for db in [before, after]:
            row = db.execute("SELECT value FROM library_meta WHERE key='_source_to_canonical'").fetchone()
            maps.append(json.loads(row[0]) if row else {})
        if any(maps[1].get(k) != v for k, v in maps[0].items()):
            raise AssertionError("prior canonical mapping changed")
        expected_aliases = {"codex-" + r["entry_id"]: {"canonical_id": r["target_id"], "source_category_id": created[r["target_id"]]["category_id"]} for r in registry if r["disposition"] == "added" and "codex-" + r["entry_id"] != r["target_id"]}
        if {k: v for k, v in maps[1].items() if k not in maps[0]} != expected_aliases:
            raise AssertionError("canonical additions mismatch")
        doc = read(output / "data.json")
        for alias, mapping in expected_aliases.items():
            for category_id in ["", mapping["source_category_id"]]:
                resolved = native("prompt_merge").merged_source(doc, alias, category_id)
                if resolved is None or resolved[1]["id"] != mapping["canonical_id"]:
                    raise AssertionError("native canonical source lookup failed")
        native_store = native("library_store")
        store = native_store.LibraryStore(str(output / "library.sqlite3"))
        try:
            equality = store.verify_document_equals(doc)
            if not equality.get("equal", equality.get("ok", False)):
                raise AssertionError("native export mismatch: " + str(equality))
        finally: store.close()
        del doc
        checks["export_equals_native_store"] = True
    with closing(connect(args.tags, True)) as before, closing(connect(output / "tags.sqlite3", True)) as after:
        for table in all_tables(before):
            if table == "workbench_tag_revision":
                old_revision = before.execute("SELECT id,value FROM workbench_tag_revision ORDER BY id").fetchall()
                new_revision = after.execute("SELECT id,value FROM workbench_tag_revision ORDER BY id").fetchall()
                writes = sum(r.get("store") == "tags" and r["disposition"] == "update" for r in registry)
                expected_revision = [(identity, value + writes if identity == 1 else value) for identity, value in old_revision]
                if new_revision != expected_revision:
                    raise AssertionError("Tag revision differs from declared metadata writes")
                continue
            exclusions, key = (set(tag_updated), "tag_uuid") if table == "workbench_tag_meta" else ((), None)
            if table_hash(before, table, exclusions, key) != table_hash(after, table, exclusions, key):
                raise AssertionError("unrelated Tag rows changed: " + table)
        for change in tag_updated.values():
            if packed({k: v for k, v in change["before"].items() if k not in {"external_source", "external_sources"}}) != packed({k: v for k, v in change["after"].items() if k not in {"external_source", "external_sources"}}):
                raise AssertionError("Tag personal fields changed")
            validate_history(change["before"], change["after"], False)
    if len(registry) != len(covered) or {r["entry_id"] for r in registry} != covered:
        raise AssertionError("source coverage mismatch")
    for row in registry:
        if row["disposition"] in {"hold", "excluded"}: continue
        change = ({**updated, **created}[row["target_id"]] if row["store"] == "library" else tag_updated[row["target_id"]])
        history = change["after"]["_external_sources" if row["store"] == "library" else "external_sources"]
        if not any(v.get("entry_id") == row["entry_id"] and packed(v.get("raw_entry")) == packed(entries[row["entry_id"]]) for v in history):
            raise AssertionError("source variant not preserved")
    for name in ["library.sqlite3", "tags.sqlite3"] + (["dictionary.sqlite3"] if args.dictionary else []):
        with closing(connect(output / name, True)) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
                raise AssertionError("SQL integrity failed: " + name)
    if args.dictionary:
        with closing(connect(args.dictionary, True)) as before, closing(connect(output / "dictionary.sqlite3", True)) as after:
            for table in all_tables(before):
                if table != "danbooru_tag":
                    if table_hash(before, table) != table_hash(after, table): raise AssertionError("dictionary unrelated table changed")
                    continue
                max_id = before.execute("SELECT coalesce(max(id_index),0) FROM danbooru_tag").fetchone()[0]
                if list(before.execute("SELECT * FROM danbooru_tag ORDER BY id_index")) != list(after.execute("SELECT * FROM danbooru_tag WHERE id_index<=? ORDER BY id_index", (max_id,))):
                    raise AssertionError("existing dictionary rows changed")
                if after.execute("SELECT count(*) FROM danbooru_tag WHERE id_index>?", (max_id,)).fetchone()[0] != len(dictionary_changes):
                    raise AssertionError("dictionary additions mismatch")
    return {"passed": True, "checks": checks, "covered_sources": len(covered), "new_resources": len(created),
            "updated_library": len(updated), "updated_tags": len(tag_updated), "holds": sum(r["disposition"] == "hold" for r in registry),
            "excluded": sum(r["disposition"] == "excluded" for r in registry), "all_unrelated_rows_preserved": True,
            "source_variants_preserved": True, "images_verified": False, "online_acceptance": False}


def validate_history(before, after, underscore):
    prefix = "_" if underscore else ""
    key, primary = prefix + "external_sources", prefix + "external_source"
    previous = before.get(key) or []
    history = after.get(key) or []
    if packed(history[:len(previous)]) != packed(previous):
        raise AssertionError("prior source history changed or truncated")
    prior_main = before.get(primary)
    if prior_main:
        # An unchanged primary is still retained in place. Archiving it at the
        # history tail merely to satisfy this guard could make an older source
        # appear newer than an already-current historical revision.
        if packed(prior_main) != packed(after.get(primary)) and packed(prior_main) not in {packed(v) for v in history}:
            raise AssertionError("prior primary source revision lost")
        if (after[primary].get("dataset"), after[primary].get("entry_id")) != (prior_main.get("dataset"), prior_main.get("entry_id")):
            raise AssertionError("metadata update changed primary source identity")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["web", "baseline-web", "library", "tags", "review", "output"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--dictionary")
    parser.add_argument("--image-receipts")
    parser.add_argument("--image-dir")
    args = parser.parse_args()
    print(json.dumps(stage(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
