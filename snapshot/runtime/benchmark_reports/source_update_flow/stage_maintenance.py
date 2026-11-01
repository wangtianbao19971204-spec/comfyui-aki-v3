"""Stage review-bound historical source metadata without changing maintained text.

Only a new output directory is written. Inputs must be private consistent SQLite
copies; production deployment, image installation and server control are separate.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path

from audit_current import equal, safe_file
import stage_current as common


SCHEMA = "historical-source-maintenance-review-candidate/v1"
GAP_STATES = {"source_provenance_missing_at_actual_owner", "stale_or_incomplete_source_variant"}
REASONS = {"source_note", "source_negative", "per_image_prompt_parameters"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def tables(conn):
    return [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def schema(conn):
    return conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()


def compare_review_baseline(audited, fresh):
    """A startup backup timestamp is the only allowed drift since the audit."""
    with closing(common.connect(audited, True)) as a, closing(common.connect(fresh, True)) as b:
        require(schema(a) == schema(b), "library schema changed since review")
        for table in tables(a):
            if table == "library_meta":
                old = dict(a.execute("SELECT key,value FROM library_meta"))
                new = dict(b.execute("SELECT key,value FROM library_meta"))
                require(old.keys() == new.keys(), "library metadata keys changed since review")
                old.pop("__last_backup_at__", None)
                new.pop("__last_backup_at__", None)
                require(old == new, "library metadata changed since review")
            else:
                require(common.table_hash(a, table) == common.table_hash(b, table), "library rows changed since review: " + table)


def verified_file(web, manifest, name):
    path = safe_file(web, name)
    record = manifest["files"].get(name)
    require(isinstance(record, dict), "manifest does not cover input: " + name)
    require(path.is_file() and path.stat().st_size == record.get("size", record.get("bytes"))
            and common.file_hash(path) == record["sha256"], "source manifest mismatch: " + name)
    return common.read(path), common.file_hash(path)


def load_web(web, review, selected):
    manifest = common.read(web / "manifest.json")
    pointer = common.read(web / "current.json")
    require(manifest.get("release", pointer["release"]) == pointer["release"], "website pointer/manifest release mismatch")
    catalog, catalog_hash = verified_file(web, manifest, "codexes.json")
    require(isinstance(catalog, list) and catalog, "invalid website catalog")
    books, receipts = {}, {"codexes.json": catalog_hash}
    bound = {str(Path(p).resolve()): digest for p, digest in review["inputs"].items()}
    for meta in catalog:
        dataset = meta.get("id")
        require(isinstance(dataset, str) and dataset and dataset not in books, "duplicate or invalid dataset identity")
        document, digest = verified_file(web, manifest, dataset + ".json")
        receipts[dataset + ".json"] = digest
        if dataset in selected and meta.get("dataUrl"):
            external = safe_file(web, dataset + ".external.json")
            require(str(external.resolve()) in bound and common.file_hash(external) == bound[str(external.resolve())],
                    "selected external dataset needs a review-bound actual response")
            document, digest = common.read(external), common.file_hash(external)
            receipts[external.name] = digest
        entries = document.get("entries")
        require(isinstance(entries, list), "invalid dataset entries")
        index = {}
        for entry in entries:
            require(isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"] and entry["id"] not in index,
                    "duplicate or invalid website entry identity")
            index[entry["id"]] = entry
        books[dataset] = {"meta": meta, "entries": index, "file_sha256": digest}
    require(selected <= books.keys(), "reviewed dataset is absent from current catalog")
    return pointer["release"], books, receipts


def source_refs(payload):
    primary = payload.get("_external_source")
    if isinstance(primary, dict):
        yield primary
    for item in payload.get("_external_sources") or []:
        if isinstance(item, dict):
            yield item
    for item in payload.get("_merge_sources") or []:
        if isinstance(item, dict) and isinstance(item.get("prompt"), dict):
            yield from source_refs(item["prompt"])


def same_source(variant, dataset, entry):
    return (variant.get("dataset"), variant.get("entry_id")) == (dataset, entry)


def verify_owner(conn, source_map, categories, item, history, payload):
    dataset, entry = item["dataset"], item["entry_id"]
    target = item["owner"]["target_id"]
    native_row = {"store": "library", "target_id": target, "match": "explicit"}
    common.require_native_owner(conn, source_map, categories, entry, native_row)
    source_id = "codex-" + entry
    if source_id in source_map or conn.execute("SELECT 1 FROM prompts WHERE id=?", (source_id,)).fetchone():
        return "native_one_hop_owner"
    # A provenance target that itself redirects cannot become a hidden write.
    require(target not in source_map, "explicit witness target is itself a native alias")
    method = item.get("owner_method")
    if method == "unique_actual_explicit_source_provenance":
        require(any(same_source(v, dataset, entry) for v in source_refs(payload)), "actual explicit provenance witness is missing")
        return "actual_explicit_provenance"
    require(method in {"accepted_source_registry_lineage", "accepted_1031_source_registry_lineage"}, "source has no approved identity witness")
    # The older ledger used a dated field name; new batches use the generic one.
    registry = history.get("accepted_source_registry") or history.get("oct31_registry") or {}
    require(registry.get("source") == item["source"] and registry.get("disposition") in ("library_existing", "library_added")
            and registry.get("target_id") == target, "accepted historical registry witness does not match target")
    return "bound_accepted_source_registry"


def append_variant(before, variant):
    """Preserve an exact history prefix and every old primary field."""
    result = common.add_history(before, [variant], preserve_primary=True)
    primary = before.get("_external_source")
    if isinstance(primary, dict) and same_source(primary, variant["dataset"], variant["entry_id"]):
        result["_external_source"] = {**copy.deepcopy(primary), **copy.deepcopy(variant)}
    return result


def check_review(review, args):
    require(review.get("schema") == SCHEMA, "unsupported historical maintenance review")
    require(isinstance(review.get("inputs"), dict) and review["inputs"], "review inputs are not bound")
    bound = {str(Path(p).resolve()): digest for p, digest in review["inputs"].items()}
    for path, expected in bound.items():
        require(common.file_hash(path) == expected, "review input drift")
    for path in (args.audited_library, args.tags, args.source_ledger):
        require(str(Path(path).resolve()) in bound, "required audit/ledger input is not bound by review")
    selected = review.get("priority_sources")
    require(isinstance(selected, list) and selected, "no reviewed maintenance sources")
    identities = set()
    for item in selected:
        require(item.get("source_hold") is False, "source hold cannot be staged")
        require(item.get("source_variant_status") in GAP_STATES, "already-current source must not be unnecessarily appended")
        require(item.get("owner", {}).get("store") == "library", "historical maintenance writes library only")
        source = item.get("source")
        require(isinstance(source, str) and source == item.get("dataset", "") + ":" + item.get("entry_id", "")
                and source not in identities, "duplicate or invalid reviewed source identity")
        identities.add(source)
        reasons = item.get("priority_reasons")
        require(isinstance(reasons, list) and reasons and set(reasons) <= REASONS, "unreviewed source maintenance reason")
    counts = review.get("counts") or {}
    require(len(selected) == counts.get("priority_union_sources")
            and len({r["owner"]["target_id"] for r in selected}) == counts.get("priority_unique_targets"), "review scope counts disagree")
    require(not identities.intersection(r["source"] for r in review.get("visibility_only_note_sources", [])), "UI-only note source entered data maintenance")
    return selected


def load_ledger(path, selected, release, books):
    wanted = {item["source"]: item for item in selected}
    found = {}
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            source = row.get("source")
            if source not in wanted:
                continue
            require(source not in found, "duplicate source in bound historical ledger")
            item = wanted[source]
            require((row.get("dataset"), row.get("entry_id")) == (item["dataset"], item["entry_id"]), "historical source identity mismatch")
            before, current = row["before_raw"], row["after_raw"]
            require(before.get("id") == item["entry_id"] and current.get("id") == item["entry_id"], "historical entry ID changed")
            require(common.digest(before) == row["old_raw_sha256"] and common.digest(current) == row["new_raw_sha256"]
                    == item["current_entry_sha256"], "historical raw source hash mismatch")
            book = books[item["dataset"]]
            require(row["new_release"] == release and row["new_file_sha256"] == book["file_sha256"], "historical ledger points to another current release/file")
            require(equal(current, book["entries"].get(item["entry_id"])), "current dataset differs from reviewed historical source")
            require(isinstance(row.get("old_file_sha256"), str) and len(row["old_file_sha256"]) == 64, "historical frozen file hash missing")
            changed = set(row["changed_fields"])
            require("source_note" not in item["priority_reasons"] or "note" in changed, "note repair has no historical note change")
            require("source_negative" not in item["priority_reasons"] or "negative" in changed, "negative repair has no historical negative change")
            require("per_image_prompt_parameters" not in item["priority_reasons"] or "images" in changed, "per-image repair has no historical image data change")
            found[source] = row
    require(found.keys() == wanted.keys(), "historical ledger does not cover all reviewed sources")
    return found


def verify_payload(before, after, category):
    allowed = {"_external_source", "_external_sources", "_classification"}
    require(equal({k: v for k, v in before.items() if k not in allowed}, {k: v for k, v in after.items() if k not in allowed}),
            "maintained body or personal fields changed")
    common.validate_history(before, after, True)
    require(("_classification" in before) == ("_classification" in after), "classification field presence changed")
    a, b = copy.deepcopy(before.get("_classification")), copy.deepcopy(after.get("_classification"))
    valid = isinstance(a, dict) and a.get("binding") == common.binding(category, before)
    if valid:
        require(b.get("binding") == common.binding(category, after), "valid classification binding was not preserved")
        a.pop("binding", None)
        b.pop("binding", None)
    require(equal(a, b), "classification decision changed or invalid review was repaired")
    old_primary, new_primary = before.get("_external_source"), after.get("_external_source")
    if old_primary is None:
        require(("_external_source" in before) == ("_external_source" in after) and new_primary is None, "metadata maintenance invented a primary source")
    else:
        require(isinstance(old_primary, dict) and isinstance(new_primary, dict)
                and same_source(new_primary, old_primary.get("dataset"), old_primary.get("entry_id")), "primary source identity changed")


def validate_database(fresh, staged, changes, registry, categories, revision):
    with closing(common.connect(fresh, True)) as before, closing(common.connect(staged, True)) as after:
        require(schema(before) == schema(after), "library schema changed")
        require(tables(before) == tables(after), "library table set changed")
        ids = set(changes)
        require(after.execute("SELECT value FROM library_meta WHERE key='last_modified'").fetchone() == (common.packed(revision),), "library revision does not match staged maintenance")
        old_journal_max = before.execute("SELECT coalesce(max(seq),0) FROM library_journal").fetchone()[0]
        for table in tables(before):
            if table == "prompts":
                require(common.table_hash(before, table, ids, "id") == common.table_hash(after, table, ids, "id"), "unreviewed prompt row changed")
                require(before.execute("SELECT count(*) FROM prompts").fetchone() == after.execute("SELECT count(*) FROM prompts").fetchone(), "resource identities added/deleted")
            elif table == "library_meta":
                require(common.table_hash(before, table, {"last_modified"}, "key") == common.table_hash(after, table, {"last_modified"}, "key"), "library metadata or original aliases changed")
            elif table == "library_journal":
                original = before.execute("SELECT * FROM library_journal ORDER BY seq").fetchall()
                require(original == after.execute("SELECT * FROM library_journal WHERE seq<=? ORDER BY seq", (old_journal_max,)).fetchall(), "prior journal changed")
                appended = after.execute("SELECT prompt_id,category_id,before,after,op FROM library_journal WHERE seq>? ORDER BY seq", (old_journal_max,)).fetchall()
                require(len(appended) == len(ids) and {r[0] for r in appended} == ids, "journal append scope mismatch")
                for pid, cid, raw_before, raw_after, op in appended:
                    change = changes[pid]
                    require(op == "update" and cid == change["category_id"] and raw_before == change["before_raw"]
                            and equal(json.loads(raw_after), change["after"]), "journal undo snapshot mismatch")
            elif table == "sqlite_sequence":
                a = dict(before.execute("SELECT name,seq FROM sqlite_sequence")); b = dict(after.execute("SELECT name,seq FROM sqlite_sequence"))
                expected = dict(a)
                expected["library_journal"] = max(a.get("library_journal", 0), old_journal_max) + len(ids)
                require(b == expected, "unrelated SQLite sequence changed")
            else:
                require(common.table_hash(before, table) == common.table_hash(after, table), "unaffected table changed: " + table)
        for pid, change in changes.items():
            row = after.execute("SELECT category_id,payload FROM prompts WHERE id=?", (pid,)).fetchone()
            require(row[0] == change["category_id"] and equal(json.loads(row[1]), change["after"]), "staged prompt differs from declared metadata update")
            verify_payload(change["before"], change["after"], categories[change["category_id"]])
        for item in registry:
            payload = changes[item["target_id"]]["after"]
            versions = [v for v in payload.get("_external_sources", []) if same_source(v, item["dataset"], item["entry_id"])]
            require(versions and equal(versions[-1].get("raw_entry"), item["current_raw"])
                    and versions[-1].get("source_sha256") == common.digest(item["current_raw"]), "current complete source snapshot is absent at owner")
        require(after.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite integrity failure")


def stage(args):
    output, web = Path(args.output).resolve(), Path(args.web).resolve()
    paths = [Path(getattr(args, name)).resolve() for name in ("review", "library", "audited_library", "tags", "source_ledger")]
    require(not output.exists() and all(output != p and output not in p.parents for p in [web, *paths]), "output must be a new isolated directory")
    if getattr(args, "review_sha256", None):
        require(common.file_hash(args.review) == args.review_sha256, "review hash changed")
    review = common.read(args.review)
    selected = check_review(review, args)
    release, books, website_receipts = load_web(web, review, {r["dataset"] for r in selected})
    ledger = load_ledger(args.source_ledger, selected, release, books)
    compare_review_baseline(args.audited_library, args.library)
    input_hashes = {str(p): common.file_hash(p) for p in paths}
    stamp = datetime.now(timezone.utc).isoformat()
    changes, registry = {}, []
    with closing(common.connect(args.library, True)) as conn:
        categories = {i: json.loads(p) for i, p in conn.execute("SELECT id,payload FROM categories")}
        row = conn.execute("SELECT value FROM library_meta WHERE key='_source_to_canonical'").fetchone()
        source_map = json.loads(row[0]) if row else {}
        for item in selected:
            target = item["owner"]["target_id"]
            if target not in changes:
                row = conn.execute("SELECT category_id,payload FROM prompts WHERE id=?", (target,)).fetchone()
                require(row is not None, "reviewed library owner is missing")
                changes[target] = {"category_id": row[0], "before_raw": row[1], "before": json.loads(row[1]), "after": json.loads(row[1])}
            change = changes[target]
            history = ledger[item["source"]]
            witness = verify_owner(conn, source_map, categories, item, history, change["before"])
            current = history["after_raw"]
            require(not any(same_source(v, item["dataset"], item["entry_id"]) and equal(v.get("raw_entry"), current)
                            for v in source_refs(change["before"])), "source snapshot is already current; review must be refreshed")
            addition = common.variant(item["dataset"], current, release)
            addition["dataset_title"] = books[item["dataset"]]["meta"].get("title") or "原站说明"
            change["after"] = append_variant(change["after"], addition)
            registry.append({"source": item["source"], "dataset": item["dataset"], "entry_id": item["entry_id"], "store": "library",
                             "target_id": target, "category_id": change["category_id"], "disposition": "source_metadata_updated", "witness": witness,
                             "priority_reasons": item["priority_reasons"], "old_source_sha256": history["old_raw_sha256"],
                             "source_sha256": common.digest(current), "current_raw": current})
        for change in changes.values():
            before = change["before"]; decision = before.get("_classification"); category = categories[change["category_id"]]
            if isinstance(decision, dict) and decision.get("binding") == common.binding(category, before):
                change["after"]["_classification"]["binding"] = common.binding(category, change["after"])
            verify_payload(before, change["after"], category)
    # No writable output exists before every source and identity check succeeds.
    output.mkdir(parents=True)
    common.backup(args.library, output / "library.sqlite3")
    with closing(common.connect(output / "library.sqlite3")) as conn:
        for pid, change in changes.items():
            conn.execute("UPDATE prompts SET payload=? WHERE id=?", (common.packed(change["after"]), pid))
            conn.execute("INSERT INTO library_journal(at,op,prompt_id,category_id,before,after) VALUES (?,?,?,?,?,?)",
                         (stamp, "update", pid, change["category_id"], change["before_raw"], common.packed(change["after"])))
        conn.execute("INSERT INTO library_meta(key,value) VALUES ('last_modified',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (common.packed(stamp),))
        conn.commit()
        common.export_document(conn, output / "data.json")
        sync = common.native("shared_sync")
        with closing(common.connect(args.tags, True)) as tags:
            pairs = sync.build_pairs(tags.execute("SELECT t_uuid,text FROM tag_tags"),
                                     ((pid, json.loads(raw).get("prompt")) for pid, raw in conn.execute("SELECT id,payload FROM prompts")))
        common.save(output / "shared_pairs.json", {"version": sync.PAIR_VERSION, "generated_at": stamp, "library_revision": stamp, **pairs})
    document = common.read(output / "data.json")
    store = common.native("library_store").LibraryStore(output / "library.sqlite3")
    try:
        equality = store.verify_document_equals(document)
        require(equality.get("equal", equality.get("ok", False)), "export differs from native library store")
    finally:
        store.close()
    del document
    validate_database(args.library, output / "library.sqlite3", changes, registry, categories, stamp)
    require(all(common.file_hash(p) == digest for p, digest in input_hashes.items()), "readonly input changed during staging")
    proof = {"passed": True, "source_release": release, "reviewed_sources": len(registry), "updated_library": len(changes),
             "new_resources": 0, "tag_writes": 0, "dictionary_writes": 0, "production_modified": False,
             "all_maintained_body_and_personal_fields_unchanged": True, "all_prior_history_and_aliases_preserved": True,
             "classification_decisions_and_eligibility_unchanged": True, "current_full_raw_sources_verified": len(registry),
             "native_export_equal": True, "inputs": input_hashes, "website_files": website_receipts,
             "startup_backup_timestamp_only_audit_drift_allowed": True, "revision": stamp}
    common.save(output / "stage_review.json", review)
    common.save(output / "source_registry.json", [{k: v for k, v in r.items() if k != "current_raw"} for r in registry])
    common.save(output / "stage_validation.json", proof)
    common.save(output / "stage_summary.json", {**proof, "outputs": {p.name: common.file_hash(p) for p in output.iterdir() if p.is_file() and not p.name.endswith(("-wal", "-shm"))}})
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("review", "web", "library", "audited-library", "tags", "source-ledger", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--review-sha256")
    args = parser.parse_args()
    result = stage(args)
    print(json.dumps({k: result[k] for k in ("passed", "reviewed_sources", "updated_library", "production_modified")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
