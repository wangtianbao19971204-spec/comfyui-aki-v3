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


def verify(plan, batch):
    from publish_current import backup_sqlite, empty, fingerprint, get, now, owner, require
    spec, runtime = plan["spec"], Path(plan["runtime"])
    stage = {row["stage_name"]: Path(row["stage_path"]) for row in plan["files"]}
    targets = {row["stage_name"]: safe_file(runtime, row["runtime_relative"]) for row in plan["files"]}
    checks = spec["verification"]
    owner(runtime, spec["port"], plan["expected_live_owner"])
    snapshots = batch / "live_snapshot"
    snapshots.mkdir(exist_ok=False)
    live_databases = {}
    for name in ("library.sqlite3", "tags.sqlite3", "dictionary.sqlite3"):
        live_databases[name] = snapshots / name
        backup_sqlite(targets[name], live_databases[name])
    connection = http.client.HTTPConnection("127.0.0.1", spec["port"], timeout=90)

    def fetch(route):
        connection.request("GET", route)
        response = connection.getresponse()
        body = response.read()
        require(response.status == 200, "Acceptance HTTP failed: " + route)
        return body

    library = 0
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
        for table in ("categories", "category_orders", "prompts", "library_journal"):
            require(a[table] == b[table], "Live library content changed: " + table)
        for name in ("tags.sqlite3", "dictionary.sqlite3"):
            require(fingerprint(stage[name]) == fingerprint(live_databases[name]), "Live database differs from stage: " + name)
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
        empty(spec["port"])
        _, identity = owner(runtime, spec["port"], plan["expected_live_owner"])
        return {"passed": True, "at": now(), "library_http_verified": library,
                "source_aliases_verified": len(checks.get("aliases", {})),
                "existing_source_owner_queries_verified": len(checks.get("source_queries", [])),
                "new_selection_queries_verified": len(checks.get("new_ids", [])),
                "tag_http_verified": len(checks.get("tag_ids", [])),
                "images_http_verified": len(spec["images"]), "dictionary_http_verified": len(checks["dictionary"]),
                "library_count": checks["library_count"], "index_count": index["total_prompts"],
                "all_scoped_databases_equal_to_stage": True, "queue_empty": True, "service": identity}
    finally:
        connection.close()
