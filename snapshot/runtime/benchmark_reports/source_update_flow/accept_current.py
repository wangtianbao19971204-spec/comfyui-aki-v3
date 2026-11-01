"""Read-only, exhaustive scoped acceptance of a staged source-data release."""
from __future__ import annotations

from contextlib import closing
import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote, urlencode

from audit_current import equal, read, safe_file


def tag_journal_state(stage, live, approved):
    """Permit only deletion of the exact, explicitly reviewed native upserts."""
    from publish_current import fingerprint, require
    a, b = fingerprint(stage), fingerprint(live)
    if not approved:
        require(a == b, "Live database differs from stage: tags.sqlite3")
        return {"approved_seq": [], "consumed_seq": [], "pending_approved_seq": []}
    fields = ("seq", "id_index", "operation", "tag_text", "tag_desc")
    require(len(approved) == 2 and all(set(row) == set(fields) for row in approved), "Exactly two complete Tag search upserts must be reviewed")
    require(all(type(row["seq"]) is int and row["seq"] > 0 and type(row["id_index"]) is int
                and row["operation"] == "upsert" and isinstance(row["tag_text"], str)
                and isinstance(row["tag_desc"], str) for row in approved), "Invalid reviewed Tag search upsert")
    reviewed = {row["seq"]: row for row in approved}
    require(len(reviewed) == len(approved) and len({row["id_index"] for row in approved}) == len(approved),
            "Duplicate reviewed Tag search sequence or identity")
    require(a.keys() == b.keys() and a["schema"] == b["schema"], "Tag schema or table set differs from stage")
    for table in a.keys() - {"schema", "workbench_tag_search_journal"}:
        require(a[table] == b[table], "Tag content differs outside reviewed search consumption: " + table)
    with closing(sqlite3.connect(stage.as_uri() + "?mode=ro", uri=True)) as source, \
            closing(sqlite3.connect(live.as_uri() + "?mode=ro", uri=True)) as current:
        before = [dict(zip(fields, row)) for row in source.execute("SELECT " + ",".join(fields) + " FROM workbench_tag_search_journal ORDER BY seq")]
        after = [dict(zip(fields, row)) for row in current.execute("SELECT " + ",".join(fields) + " FROM workbench_tag_search_journal ORDER BY seq")]
        require(all(source.execute("SELECT lower(text),lower(desc) FROM tag_tags WHERE id_index=?", (row["id_index"],)).fetchone()
                    == (row["tag_text"], row["tag_desc"]) for row in approved), "Reviewed Tag upsert is not the staged Tag row")
    old = {row["seq"]: row for row in before}
    require(all(equal(old.get(seq), row) for seq, row in reviewed.items()), "Approved Tag search row differs from stage")
    present = {row["seq"] for row in after}
    consumed = sorted(set(old) - present)
    require(set(consumed) <= reviewed.keys(), "Unapproved Tag search journal row was deleted")
    require(equal(after, [row for row in before if row["seq"] not in consumed]), "Tag search journal was added to or rewritten")
    return {"approved_seq": sorted(reviewed), "consumed_seq": consumed,
            "pending_approved_seq": sorted(reviewed.keys() - set(consumed))}


def verify_tag_search_cache(snapshot, approved, consumed):
    """Prove native contentless FTS postings, not nonexistent plaintext columns."""
    from publish_current import require
    with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as cache, \
            closing(sqlite3.connect(":memory:")) as expected:
        sql = cache.execute("SELECT sql FROM sqlite_master WHERE name='tag_search'").fetchone()
        require(sql and "fts5" in sql[0].lower() and "trigram case_sensitive 1" in sql[0].lower()
                and "contentless_delete=1" in sql[0].lower(), "Unexpected native Tag search cache format")
        require([row[1] for row in cache.execute("PRAGMA table_info(tag_search)")] == ["tag_text", "tag_desc"], "Unexpected Tag search cache columns")
        meta = cache.execute("SELECT format,applied_seq FROM search_meta WHERE id=1").fetchone()
        require(meta is not None and meta[0] == 1 and type(meta[1]) is int and meta[1] >= max(consumed), "Tag search cache has not applied consumed sequences")
        cache.execute("CREATE VIRTUAL TABLE temp.accept_vocab USING fts5vocab(main,tag_search,instance)")
        expected.execute("CREATE VIRTUAL TABLE tag_search USING fts5(tag_text,tag_desc,content='',contentless_delete=1,tokenize='trigram case_sensitive 1')")
        expected.execute("CREATE VIRTUAL TABLE temp.accept_vocab USING fts5vocab(main,tag_search,instance)")
        for row in approved:
            if row["seq"] not in consumed:
                continue
            pid = row["id_index"]
            require(cache.execute("SELECT rowid FROM tag_search WHERE rowid=?", (pid,)).fetchone() == (pid,), "Consumed Tag search row is missing from native cache")
            expected.execute("INSERT INTO tag_search(rowid,tag_text,tag_desc) VALUES (?,?,?)", (pid, row["tag_text"], row["tag_desc"]))
            # Native FTS5 is contentless. Exact per-term positions plus equal
            # per-column token counts prove all indexed content without scanning
            # every posting in the full production cache.
            require(cache.execute("SELECT sz FROM tag_search_docsize WHERE id=?", (pid,)).fetchone()
                    == expected.execute("SELECT sz FROM tag_search_docsize WHERE id=?", (pid,)).fetchone(), "Tag search cache token counts differ")
            terms = [r[0] for r in expected.execute("SELECT DISTINCT term FROM temp.accept_vocab WHERE doc=?", (pid,))]
            for term in terms:
                query = "SELECT col,offset FROM temp.accept_vocab WHERE term=? AND doc=? ORDER BY col,offset"
                require(cache.execute(query, (term, pid)).fetchall() == expected.execute(query, (term, pid)).fetchall(), "Tag search cache text or display postings differ")
    return {"verified": True, "proof": "native_fts5_full_positions_and_column_token_counts", "snapshot": str(snapshot)}


def verify(plan, batch):
    from publish_current import backup_sqlite, empty, fingerprint, get, now, owner, require
    spec, runtime = plan["spec"], Path(plan["runtime"])
    stage = {row["stage_name"]: Path(row["stage_path"]) for row in plan["files"]}
    targets = {row["stage_name"]: safe_file(runtime, row["runtime_relative"]) for row in plan["files"]}
    checks = spec["verification"]
    owner(runtime, spec["port"], plan["expected_live_owner"])
    # New read-only API calls precede the consistency copies, so any accidental
    # persistence change is included in the subsequent full database checks.
    for query in checks.get("source_note_queries", []):
        returned = get(spec["port"], "/prompt_selector/source-notes?" + urlencode({"resource_id": query["resource_id"]}))
        require(equal(returned["source_notes"], query["expected_source_notes"]), "Original-site note projection mismatch")
    for query in checks.get("tag_display_queries", []):
        returned = get(spec["port"], "/prompt_selector/tags/page?" + urlencode({"q": query["query"], "limit": 100}))
        require(any(row.get("t_uuid") == query["tag_uuid"] and row.get("desc") == query["desc"]
                    for row in returned.get("items", [])), "Native Tag display/search result differs")
    snapshots = batch / "live_snapshot"
    snapshots.mkdir(exist_ok=False)
    live_databases = {}
    database_names = [row["stage_name"] for row in plan["files"] if row["kind"] == "sqlite"]
    for name in database_names:
        live_databases[name] = snapshots / name
        backup_sqlite(targets[name], live_databases[name])
    for database in checks.get("readonly_databases", []):
        name = database["name"]
        require(name not in live_databases and Path(name).name == name, "Duplicate or unsafe read-only snapshot name")
        target = safe_file(runtime, database["runtime_relative"])
        snapshot = snapshots / name
        backup_sqlite(target, snapshot)
        require(fingerprint(Path(database["baseline_path"])) == fingerprint(snapshot),
                "Read-only database changed: " + name)
    connection = http.client.HTTPConnection("127.0.0.1", spec["port"], timeout=90)

    def fetch(route):
        connection.request("GET", route)
        response = connection.getresponse()
        body = response.read()
        require(response.status == 200, "Acceptance HTTP failed: " + route)
        return body

    library = 0
    tag_search = {"approved_seq": [], "consumed_seq": [], "pending_approved_seq": []}
    try:
        with closing(sqlite3.connect(stage["library.sqlite3"].as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(live_databases["library.sqlite3"].as_uri() + "?mode=ro", uri=True)) as live:
                for pid in checks["library_ids"]:
                    before = source.execute("select category_id,payload from prompts where id=?", (pid,)).fetchone()
                    after = live.execute("select category_id,payload from prompts where id=?", (pid,)).fetchone()
                    require(before == after and before is not None, "Live resource differs from stage: " + pid)
                    payload = json.loads(before[1])
                    returned = json.loads(fetch("/prompt_selector/library/prompt?" + urlencode({"prompt_id": pid})))
                    require(equal(returned["prompt"], payload), "HTTP resource differs from stage: " + pid)
                    library += 1
                require(live.execute("select count(*) from prompts").fetchone()[0] == checks["library_count"], "Library count mismatch")
                for source_id, target_id in checks.get("aliases", {}).items():
                    returned = json.loads(fetch("/prompt_selector/library/prompt?" + urlencode({"prompt_id": source_id})))
                    require(returned["prompt"]["id"] == target_id, "Source alias did not resolve")
                for query in checks.get("source_queries", []):
                    requested = query["request_prompt_id"]
                    returned = json.loads(fetch("/prompt_selector/library/prompt?" + urlencode({"prompt_id": requested})))
                    expected = source.execute("select payload from prompts where id=?", (query["expected_target_id"],)).fetchone()
                    require(returned["requested_id"] == requested
                            and returned["redirected"] == (requested != query["expected_target_id"])
                            and returned["category"]["id"] == query["expected_category_id"]
                            and equal(returned["prompt"], json.loads(expected[0])), "Native source owner query mismatch")
                for pid in checks.get("new_ids", []):
                    selected = json.loads(fetch("/prompt_selector/library/prompt?" + urlencode({"prompt_id": pid, "selection": 1})))
                    semantic = selected["prompt"]["_semantic"]
                    require(semantic["primary_class"] == checks["new_primary_classes"][pid]
                            and semantic["manual_search_eligible"], "New resource is not available for selection")
                source_meta = {key: value for key, value in source.execute("select key,value from library_meta")
                               if key != "__last_backup_at__"}
                live_meta = {key: value for key, value in live.execute("select key,value from library_meta")
                             if key != "__last_backup_at__"}
                require(source_meta == live_meta, "Live library metadata differs from stage")
        # Startup may update only library backup timestamps. All content and
        # user rows must still match the validated stage exactly.
        a, b = fingerprint(stage["library.sqlite3"]), fingerprint(live_databases["library.sqlite3"])
        require(a["schema"] == b["schema"], "Live library schema differs from stage")
        require(a.keys() == b.keys(), "Live library tables differ from stage")
        for table in a.keys() - {"schema", "library_meta"}:
            require(a[table] == b[table], "Live library content changed: " + table)
        for name in ("tags.sqlite3", "dictionary.sqlite3"):
            if name in live_databases:
                if name == "tags.sqlite3":
                    tag_search = tag_journal_state(stage[name], live_databases[name], checks.get("tag_search_journal_consumption", []))
                else:
                    require(fingerprint(stage[name]) == fingerprint(live_databases[name]), "Live database differs from stage: " + name)
        require(not checks.get("tag_search_journal_consumption") or "tags.sqlite3" in live_databases,
                "Reviewed Tag search consumption requires a scoped Tag database")
        if tag_search["consumed_seq"]:
            require(checks.get("tag_search_cache_runtime_relative"), "Consumed Tag search rows require native cache evidence")
            cache = snapshots / "tag_search.v1.sqlite3"
            backup_sqlite(safe_file(runtime, checks["tag_search_cache_runtime_relative"]), cache)
            tag_search["cache"] = verify_tag_search_cache(cache, checks["tag_search_journal_consumption"], tag_search["consumed_seq"])
        for tag_id in checks.get("tag_ids", []):
            returned = json.loads(fetch("/prompt_selector/tags/item?" + urlencode({"id": "tag:" + tag_id})))
            require(returned["item"]["t_uuid"] == tag_id, "Tag HTTP identity mismatch")
        for row in checks["dictionary"]:
            records = json.loads(fetch("/weilin_prompt_selector/autocomplete_with_translation?" + urlencode({"query": row["tag"], "limit": 100})))
            require(any(item.get("tag") == row["tag"] and item.get("translation") == row["translation"] for item in records),
                    "Native autocomplete translation missing: " + row["tag"])
        for image in spec["images"]:
            filename = Path(image["runtime_relative"]).name
            require(hashlib.sha256(fetch("/prompt_selector/preview/" + quote(filename))).hexdigest() == image["sha256"],
                    "Preview HTTP bytes mismatch")
        index = get(spec["port"], "/prompt_selector/library/index")
        require(index["total_prompts"] == plan["baseline_index"]["total_prompts"] + checks["new_resources"], "Native index total mismatch")
        require(index["last_modified"] == checks["revision"], "Native index revision mismatch")
        for name in ("data.json", "shared_pairs.json"):
            require(hashlib.sha256(stage[name].read_bytes()).digest() == hashlib.sha256(targets[name].read_bytes()).digest(), "Derived file changed: " + name)
        for row in plan["files"]:
            if row["kind"] == "source":
                require(hashlib.sha256(Path(row["stage_path"]).read_bytes()).hexdigest() == row["stage_sha256"]
                        == hashlib.sha256(safe_file(runtime, row["runtime_relative"]).read_bytes()).hexdigest(),
                        "Deployed source differs from main Git seal")
        empty(spec["port"])
        _, identity = owner(runtime, spec["port"], plan["expected_live_owner"])
        return {"passed": True, "at": now(), "library_http_verified": library,
                "source_aliases_verified": len(checks.get("aliases", {})),
                "existing_source_owner_queries_verified": len(checks.get("source_queries", [])),
                "source_note_queries_verified": len(checks.get("source_note_queries", [])),
                "readonly_databases_verified": len(checks.get("readonly_databases", [])),
                "sealed_source_files_verified": sum(row["kind"] == "source" for row in plan["files"]),
                "new_selection_queries_verified": len(checks.get("new_ids", [])),
                "tag_http_verified": len(checks.get("tag_ids", [])),
                "tag_display_queries_verified": len(checks.get("tag_display_queries", [])),
                "tag_search_reviewed_state": {**tag_search, "passed": True},
                "images_http_verified": len(spec["images"]), "dictionary_http_verified": len(checks["dictionary"]),
                "library_count": checks["library_count"], "index_count": index["total_prompts"],
                "all_scoped_databases_equal_to_stage": not tag_search["consumed_seq"],
                "all_scoped_databases_match_reviewed_state": True, "queue_empty": True, "service": identity}
    finally:
        connection.close()
