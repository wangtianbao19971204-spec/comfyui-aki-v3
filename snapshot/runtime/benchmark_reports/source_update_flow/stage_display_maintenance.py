"""Offline, review-bound source display names and complete source snapshots.

Only a new isolated batch is written. Native bodies, personal fields, identities,
categories, image choices and classification decisions remain unchanged.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from audit_current import equal
import stage_current as C
import stage_maintenance as M


SCHEMA = "historical-display-maintenance-review/v1"
require = M.require


def lines(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def identity(row):
    return row["owner"]["store"], row["owner"]["target_id"]


def tag_refs(payload):
    primary = payload.get("external_source")
    if isinstance(primary, dict):
        yield primary
    for item in payload.get("external_sources") or []:
        if isinstance(item, dict):
            yield item


def source_key(variant):
    dataset, entry = variant.get("dataset"), variant.get("entry_id")
    return dataset + ":" + entry if isinstance(dataset, str) and isinstance(entry, str) else None


def resolve_all(lib, tags, books, registries):
    """Native one-hop identity wins over physical rows and explicit lineage."""
    entries = {dataset + ":" + eid: entry for dataset, book in books.items()
               for eid, entry in book["entries"].items()}
    physical = {pid for pid, in lib.execute("SELECT id FROM prompts")}
    tag_ids = {pid for pid, in tags.execute("SELECT t_uuid FROM tag_tags")}
    row = lib.execute("SELECT value FROM library_meta WHERE key='_source_to_canonical'").fetchone()
    mapping = json.loads(row[0]) if row else {}
    provenance = defaultdict(set)
    for pid, raw in lib.execute("SELECT id,payload FROM prompts WHERE instr(payload,'external_source')>0 OR instr(payload,'_merge_sources')>0"):
        for variant in M.source_refs(json.loads(raw)):
            key = source_key(variant)
            if key:
                provenance[key].add(("library", pid))
    for pid, raw in tags.execute("SELECT tag_uuid,data FROM workbench_tag_meta WHERE instr(data,'external_source')>0"):
        for variant in tag_refs(json.loads(raw)):
            key = source_key(variant)
            if key:
                provenance[key].add(("tags", pid))
    resolved, ambiguous = {}, {}
    for source, entry in entries.items():
        alias = "codex-" + entry["id"]
        record = mapping.get(alias)
        if record is not None:
            require(isinstance(record, dict) and record.get("canonical_id") in physical,
                    "invalid native source map")
            resolved[source] = ("library", record["canonical_id"])
        elif alias in physical:
            resolved[source] = ("library", alias)
        else:
            choices = {owner for owner in provenance[source]
                       if (owner[0] == "library" and owner[1] in physical and owner[1] not in mapping)
                       or (owner[0] == "tags" and owner[1] in tag_ids)}
            if len(choices) == 1:
                resolved[source] = next(iter(choices))
            elif choices:
                ambiguous[source] = choices
            else:
                prior = registries.get(source, {})
                pid = prior.get("target_id")
                store = prior.get("store") or ("tags" if prior.get("disposition", "").startswith("tag_") else "library")
                if (store == "library" and pid in physical and pid not in mapping) or (store == "tags" and pid in tag_ids):
                    resolved[source] = (store, pid)
    return entries, resolved, ambiguous, mapping


def append_current(before, variant, underscore=True):
    refs = M.source_refs(before) if underscore else tag_refs(before)
    if any(M.same_source(v, variant["dataset"], variant["entry_id"])
           and equal(v.get("raw_entry"), variant["raw_entry"]) for v in refs):
        # The unchanged primary is already retained in place. Appending an old
        # primary behind a current history item would falsely make it latest.
        return copy.deepcopy(before), False
    after = C.add_history(before, [variant], underscore, preserve_primary=True)
    key = "_external_source" if underscore else "external_source"
    primary = before.get(key)
    if isinstance(primary, dict) and M.same_source(primary, variant["dataset"], variant["entry_id"]):
        after[key] = {**copy.deepcopy(primary), **copy.deepcopy(variant)}
    return after, True


def verify_payload(before, after, category=None, renamed=False, tag=False):
    keys = {"external_source", "external_sources"} if tag else {"_external_source", "_external_sources", "_classification"}
    if renamed:
        keys.add("alias")
    require(equal({k: v for k, v in before.items() if k not in keys},
                  {k: v for k, v in after.items() if k not in keys}), "body or personal fields changed")
    C.validate_history(before, after, not tag)
    if tag:
        return
    a, b = copy.deepcopy(before.get("_classification")), copy.deepcopy(after.get("_classification"))
    require(("_classification" in before) == ("_classification" in after), "classification presence changed")
    if isinstance(a, dict) and a.get("binding") == C.binding(category, before):
        require(isinstance(b, dict) and b.get("binding") == C.binding(category, after), "valid classification was not rebound")
        a.pop("binding", None)
        b.pop("binding", None)
    require(equal(a, b), "classification decision or eligibility changed")


def prove_origin_name(item, historical, bound, cache, wanted):
    """An original import name can be maintained independently of later primaries.

    This exception needs exact frozen upstream text, native checkpoints, an
    actual direct-import/accepted-registry edge and the retained journal. A
    boolean approval, current primary or similar spelling is never evidence.
    """
    authority = item.get("origin_naming_authority")
    require(isinstance(authority, dict) and authority.get("schema") == "origin-naming-authority/v1",
            "missing explicit original naming evidence")
    source, owner = item["source"], identity(item)
    dataset, eid = source.split(":", 1)
    old_title = historical["before_raw"].get("title")
    require(owner[0] == "library" and owner[1] == "codex-" + eid
            and authority.get("origin_source") == source and authority.get("native_origin_id") == owner[1],
            "original naming identity is not the direct canonical import")

    def path(value):
        resolved = Path(value).resolve()
        require(str(resolved) in bound, "original naming evidence is not review-bound")
        return resolved

    upstream = authority["frozen_source"]
    frozen = path(upstream["path"])
    manifest_path = path(upstream["manifest_path"])
    manifest = C.read(manifest_path)
    require(manifest.get("release") == upstream["release"], "original upstream release differs")
    require(frozen.name == upstream["name"] and C.file_hash(frozen) == historical["old_file_sha256"],
            "original naming source differs from historical source bytes")
    key = (str(frozen), "upstream")
    if key not in cache:
        document, _ = M.verified_file(frozen.parent, manifest, upstream["name"])
        cache[key] = {entry["id"]: entry for entry in document["entries"]}
    original = cache[key].get(eid)
    require(equal(original, historical["before_raw"]) and C.digest(original) == authority["old_source_entry_sha256"]
            and original.get("title") == old_title == item["old_source_title"], "original upstream title evidence differs")
    checkpoints = authority["checkpoints"]
    require(len(checkpoints) >= 2 and len({str(Path(r["path"]).resolve()) for r in checkpoints}) == len(checkpoints),
            "original name needs independent native continuity checkpoints")
    actual = []
    for record in checkpoints:
        checkpoint = path(record["path"])
        key = (str(checkpoint), record["kind"])
        if key not in cache:
            if record["kind"] == "document":
                document = C.read(checkpoint)
                cache[key] = {p["id"]: p for category in document["categories"]
                              for p in category["prompts"] if p.get("id") in wanted}
                del document
            else:
                require(record["kind"] == "sqlite", "unsupported original naming checkpoint")
                with closing(C.connect(checkpoint, True)) as connection:
                    marks = ",".join("?" for _ in wanted)
                    cache[key] = {pid: json.loads(raw) for pid, raw in connection.execute(
                        "SELECT id,payload FROM prompts WHERE id IN (" + marks + ")", sorted(wanted))}
        payload = cache[key].get(owner[1])
        require(isinstance(payload, dict) and payload.get("id") == owner[1] and payload.get("alias") == old_title
                and C.digest(payload) == record["payload_sha256"], "native naming checkpoint is missing, renamed or changed")
        actual.append(payload)
    edge = authority["import_edge"]
    edge_path = path(edge["path"])
    key = (str(edge_path), "import-edge")
    if key not in cache:
        cache[key] = C.read(edge_path)
    if edge["kind"] == "direct_add":
        matching = [row for row in cache[key] if row.get("store") == "library" and row.get("id") == owner[1]
                    and row.get("source") == source and row.get("action") == ["add"]]
        primary = actual[0].get("_external_source") or {}
        require(len(matching) == 1 and source_key(primary) == source, "direct add does not establish the original naming source")
    else:
        require(edge["kind"] == "accepted_existing_import", "unsupported original naming import edge")
        matching = [row for row in cache[key] if row.get("target_id") == owner[1]
                    and row.get("source") == source and row.get("disposition") == "library_existing"]
        require(len(matching) == 1, "accepted existing import does not establish naming identity")
    journal = authority["journal_checkpoint"]
    journal_path = path(journal["path"])
    observed = []
    with closing(C.connect(journal_path, True)) as connection:
        for seq, at, op, before, after in connection.execute(
                "SELECT seq,at,op,before,after FROM library_journal WHERE prompt_id=? ORDER BY seq", (owner[1],)):
            a, b = json.loads(before) if before else None, json.loads(after) if after else None
            alias_a = a.get("alias") if isinstance(a, dict) else None
            alias_b = b.get("alias") if isinstance(b, dict) else None
            require(alias_b == old_title and (a is None or alias_a == old_title), "retained journal contains a local rename or deletion")
            observed.append({"seq": seq, "at": at, "op": op, "before_alias": alias_a, "after_alias": alias_b,
                             "before_sha256": hashlib.sha256(before.encode()).hexdigest() if before else None,
                             "after_sha256": hashlib.sha256(after.encode()).hexdigest() if after else None})
    require(observed and equal(observed, journal["rows"]), "retained naming journal evidence changed")
    require(any(Path(record["path"]).resolve() == journal_path for record in checkpoints),
            "latest journal evidence has no native alias checkpoint")
    return "verified_original_import_name"


def validate_library(base, staged, changes, categories, stamp):
    with closing(C.connect(base, True)) as a, closing(C.connect(staged, True)) as b:
        require(M.schema(a) == M.schema(b) and M.tables(a) == M.tables(b), "library schema changed")
        ids = set(changes)
        maximum = a.execute("SELECT coalesce(max(seq),0) FROM library_journal").fetchone()[0]
        for table in M.tables(a):
            if table == "prompts":
                require(C.table_hash(a, table, ids, "id") == C.table_hash(b, table, ids, "id"), "unreviewed library row changed")
                require(a.execute("SELECT count(*) FROM prompts").fetchone() == b.execute("SELECT count(*) FROM prompts").fetchone(), "resource identities changed")
            elif table == "library_meta":
                require(C.table_hash(a, table, {"last_modified"}, "key") == C.table_hash(b, table, {"last_modified"}, "key"), "source aliases or library metadata changed")
                require(b.execute("SELECT value FROM library_meta WHERE key='last_modified'").fetchone() == (C.packed(stamp),), "library revision differs")
            elif table == "library_journal":
                require(a.execute("SELECT * FROM library_journal ORDER BY seq").fetchall() == b.execute("SELECT * FROM library_journal WHERE seq<=? ORDER BY seq", (maximum,)).fetchall(), "old journal changed")
                new = b.execute("SELECT prompt_id,category_id,before,after,op FROM library_journal WHERE seq>?", (maximum,)).fetchall()
                require(len(new) == len(ids) and {r[0] for r in new} == ids, "journal scope differs")
                for pid, cid, old, after, op in new:
                    require(op == "update" and cid == changes[pid]["category_id"] and old == changes[pid]["before_raw"]
                            and equal(json.loads(after), changes[pid]["after"]), "journal undo snapshots differ")
            elif table == "sqlite_sequence":
                expected = dict(a.execute("SELECT name,seq FROM sqlite_sequence"))
                expected["library_journal"] = max(expected.get("library_journal", 0), maximum) + len(ids)
                require(expected == dict(b.execute("SELECT name,seq FROM sqlite_sequence")), "unrelated library sequence changed")
            else:
                require(C.table_hash(a, table) == C.table_hash(b, table), "unaffected library table changed: " + table)
        for pid, change in changes.items():
            cid, raw = b.execute("SELECT category_id,payload FROM prompts WHERE id=?", (pid,)).fetchone()
            require(cid == change["category_id"] and equal(json.loads(raw), change["after"]), "declared library update differs")
            verify_payload(change["before"], change["after"], categories[cid], change["renamed"])
        require(b.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "library integrity failed")


def validate_tags(base, staged, changes):
    with closing(C.connect(base, True)) as a, closing(C.connect(staged, True)) as b:
        require(M.schema(a) == M.schema(b) and M.tables(a) == M.tables(b), "Tag schema changed")
        ids = set(changes)
        writes = sum(c["meta_changed"] for c in changes.values())
        maximum = a.execute("SELECT coalesce(max(seq),0) FROM workbench_tag_search_journal").fetchone()[0]
        for table in M.tables(a):
            if table in {"tag_tags", "workbench_tag_meta"}:
                key = "t_uuid" if table == "tag_tags" else "tag_uuid"
                require(C.table_hash(a, table, ids, key) == C.table_hash(b, table, ids, key), "unreviewed Tag row changed")
                require(a.execute("SELECT count(*) FROM " + table).fetchone() == b.execute("SELECT count(*) FROM " + table).fetchone(), "Tag identities changed")
            elif table in {"workbench_tag_revision", "workbench_tag_text_revision"}:
                count = len(ids) + writes if table == "workbench_tag_revision" else len(ids)
                old = a.execute("SELECT id,value FROM " + table + " ORDER BY id").fetchall()
                require([(i, v + count if i == 1 else v) for i, v in old] == b.execute("SELECT id,value FROM " + table + " ORDER BY id").fetchall(), "native Tag revision differs")
            elif table == "workbench_tag_search_journal":
                require(a.execute("SELECT * FROM workbench_tag_search_journal ORDER BY seq").fetchall() == b.execute("SELECT * FROM workbench_tag_search_journal WHERE seq<=? ORDER BY seq", (maximum,)).fetchall(), "old Tag search journal changed")
                actual = b.execute("SELECT id_index,operation,tag_text,tag_desc FROM workbench_tag_search_journal WHERE seq>?", (maximum,)).fetchall()
                expected = [(c["row_before"]["id_index"], "upsert", c["row_before"]["text"].lower(), c["new_title"].lower()) for c in changes.values()]
                require(sorted(actual) == sorted(expected), "native Tag search journal differs")
            elif table == "sqlite_sequence":
                expected = dict(a.execute("SELECT name,seq FROM sqlite_sequence"))
                expected["workbench_tag_search_journal"] = max(expected.get("workbench_tag_search_journal", 0), maximum) + len(ids)
                require(expected == dict(b.execute("SELECT name,seq FROM sqlite_sequence")), "unrelated Tag sequence changed")
            else:
                require(C.table_hash(a, table) == C.table_hash(b, table), "personal or derived Tag table changed: " + table)
        for pid, change in changes.items():
            columns = [r[1] for r in b.execute("PRAGMA table_info(tag_tags)")]
            after = dict(zip(columns, b.execute("SELECT * FROM tag_tags WHERE t_uuid=?", (pid,)).fetchone()))
            expected = {**change["row_before"], "desc": change["new_title"]}
            require(equal(after, expected), "Tag text, UUID, color, group or personal field changed")
            raw = b.execute("SELECT data FROM workbench_tag_meta WHERE tag_uuid=?", (pid,)).fetchone()[0]
            require(equal(json.loads(raw), change["after"]), "Tag source metadata differs")
            verify_payload(change["before"], change["after"], tag=True)
        require(b.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Tag integrity failed")


def stage(args):
    output, web = Path(args.output).resolve(), Path(args.web).resolve()
    require(not output.exists(), "output must be a new isolated directory")
    review = C.read(args.review)
    require(review.get("schema") == SCHEMA, "unsupported display review")
    if getattr(args, "review_sha256", None):
        require(C.file_hash(args.review) == args.review_sha256, "review hash changed")
    bound = {str(Path(p).resolve()): digest for p, digest in review["inputs"].items()}
    for path, digest in bound.items():
        require(C.file_hash(path) == digest, "review input drift")
    for name in ("library", "tags", "source_ledger", "identity_plan"):
        path = Path(getattr(args, name)).resolve()
        require(str(path) in bound and output != path and output not in path.parents, "required staging input is not review-bound or output overlaps input")
    require(output != web and output not in web.parents, "output overlaps website inputs")
    require(all(str((web / name).resolve()) in bound for name in ("manifest.json", "current.json", "codexes.json")),
            "website manifest, pointer and catalog must be review-bound")
    display = review["display_sources"]
    metadata = review["metadata_sources"]
    require(display or metadata, "empty display maintenance scope")
    require(len({r["source"] for r in display}) == len(display)
            and len({r["source"] for r in metadata}) == len(metadata), "duplicate reviewed source")
    expected = review["expected"]
    require(len(display) == expected["display_sources"] and len(metadata) == expected["metadata_sources"], "review counts differ")
    require(len({identity(r) for r in display}) == len(display), "multiple display changes target one owner")
    historical = {r["source"]: r for r in lines(args.source_ledger)}
    plan = {r["source"]: r for r in lines(args.identity_plan)}
    registries = {}
    for file in review["accepted_registries"]:
        require(str(Path(file).resolve()) in bound, "accepted registry is not bound")
        for row in C.read(file):
            source = row.get("source") or ("enter_codex:" + row["entry_id"])
            registries[source] = row
    catalog = C.read(web / "codexes.json")
    release, books, web_receipts = M.load_web(web, review, {r["id"] for r in catalog})
    stamp = datetime.now(timezone.utc).isoformat()
    changes, tag_changes, registry = {}, {}, []
    origin_cache = {}
    origin_owners = {r["owner"]["target_id"] for r in display if r.get("origin_naming_authority")}
    origin_names = 0
    with closing(C.connect(args.library, True)) as lib, closing(C.connect(args.tags, True)) as tags:
        entries, owners, ambiguous, source_map = resolve_all(lib, tags, books, registries)
        categories = {cid: json.loads(raw) for cid, raw in lib.execute("SELECT id,payload FROM categories")}
        current_bindings = defaultdict(set)
        for source, owner in owners.items():
            current_bindings[owner].add(source)
        target_ambiguity = set().union(*ambiguous.values()) if ambiguous else set()

        def proof(item):
            source = item["source"]
            require(source in historical and source in entries and source in plan, "source is absent from bound evidence")
            h, p, e = historical[source], plan[source], entries[source]
            dataset, eid = source.split(":", 1)
            require(p["source_hold"] is False and identity(p) == identity(item) == owners.get(source), "held source or actual owner changed")
            C.require_native_owner(lib, source_map, categories, eid,
                                   {"store": identity(item)[0], "target_id": identity(item)[1], "match": "explicit"})
            require((h["dataset"], h["entry_id"]) == (dataset, eid) and e["id"] == eid, "source identity mismatch")
            require(C.digest(h["before_raw"]) == h["old_raw_sha256"] and C.digest(h["after_raw"]) == h["new_raw_sha256"]
                    and equal(h["after_raw"], e) and h["new_release"] == release
                    and h["new_file_sha256"] == books[dataset]["file_sha256"], "historical/current source seal differs")
            return source, dataset, eid, h, e

        for item in display:
            source, dataset, eid, h, e = proof(item)
            owner = identity(item)
            require(owner not in target_ambiguity, "ambiguous source affects display owner")
            bindings = current_bindings[owner]
            require(bindings == {r["source"] for r in item["global_current_bindings"]}, "all-current-source display binding set changed")
            require(all(C.digest(entries[r["source"]]) == r["raw_sha256"] for r in item["global_current_bindings"]),
                    "reviewed current source binding content changed")
            require(bindings and source in bindings and all(not plan.get(s, {}).get("source_hold", False)
                    and registries.get(s, {}).get("disposition") not in {"hold", "excluded", "no_prompt_content"}
                    for s in bindings), "bound source is held or naming source is absent")
            if item.get("origin_naming_authority"):
                prove_origin_name(item, h, bound, origin_cache, origin_owners)
                origin_names += 1
            else:
                require(all(entries[s].get("title") == e.get("title") for s in bindings), "current titles conflict")
            require(isinstance(e.get("title"), str) and e["title"].strip()
                    and h["before_raw"].get("title") == item["old_source_title"]
                    and e["title"] == item["new_source_title"] != item["old_source_title"], "reviewed literal title revision differs")
            if owner[0] == "library":
                cid, raw = lib.execute("SELECT category_id,payload FROM prompts WHERE id=?", (owner[1],)).fetchone()
                before = json.loads(raw)
                require(before.get("alias") == item["old_source_title"], "local name is not the exact old source title")
                changes[owner[1]] = {"category_id": cid, "before_raw": raw, "before": before,
                                     "after": {**copy.deepcopy(before), "alias": e["title"]}, "renamed": True}
                if item.get("origin_naming_authority"):
                    registry.append({"source": source, "dataset": dataset, "entry_id": eid, "store": "library",
                                     "target_id": owner[1], "disposition": "origin_display_name_updated",
                                     "old_alias": before["alias"], "new_alias": e["title"],
                                     "current_raw_sha256": C.digest(e)})
            else:
                require(owner[0] == "tags", "unsupported display owner store")
                columns = [r[1] for r in tags.execute("PRAGMA table_info(tag_tags)")]
                row = tags.execute("SELECT * FROM tag_tags WHERE t_uuid=?", (owner[1],)).fetchone()
                require(row is not None, "Tag owner is missing")
                record = dict(zip(columns, row))
                require(record["desc"] == item["old_source_title"], "Tag display desc is not the exact old source title")
                before = json.loads(tags.execute("SELECT data FROM workbench_tag_meta WHERE tag_uuid=?", (owner[1],)).fetchone()[0])
                tag_changes[owner[1]] = {"row_before": record, "before": before, "after": copy.deepcopy(before),
                                          "new_title": e["title"], "meta_changed": False}

        scope = {r["source"]: r for r in metadata}
        for item in metadata:
            proof(item)
            require(identity(item)[0] == "library", "metadata-only scope must be library")
        for item in display:
            if item.get("origin_naming_authority"):
                # Naming authority does not adopt, merge or reorder any source
                # variants. Other bindings may be later entries with no old
                # changed-entry ledger at all; their titles remain independent.
                continue
            for source in current_bindings[identity(item)]:
                require(source in plan and not plan[source]["source_hold"], "display binding has no reviewed nonheld source identity")
                scope.setdefault(source, {"source": source, "owner": item["owner"]})
        for source, item in scope.items():
            _, dataset, eid, h, e = proof(item)
            owner = identity(item)
            variant = C.variant(dataset, e, release)
            variant["dataset_title"] = books[dataset]["meta"].get("title") or "Original source"
            if owner[0] == "library":
                if owner[1] not in changes:
                    cid, raw = lib.execute("SELECT category_id,payload FROM prompts WHERE id=?", (owner[1],)).fetchone()
                    before = json.loads(raw)
                    changes[owner[1]] = {"category_id": cid, "before_raw": raw, "before": before, "after": copy.deepcopy(before), "renamed": False}
                change = changes[owner[1]]
                change["after"], appended = append_current(change["after"], variant)
            else:
                change = tag_changes[owner[1]]
                previous = change["after"]
                change["after"], appended = append_current(previous, variant, False)
                change["meta_changed"] |= not equal(previous, change["after"])
            registry.append({"source": source, "dataset": dataset, "entry_id": eid, "store": owner[0], "target_id": owner[1],
                             "disposition": "current_source_appended" if appended else "current_source_already_present",
                             "current_raw_sha256": C.digest(e)})
        for pid in list(changes):
            change = changes[pid]
            if equal(change["before"], change["after"]):
                del changes[pid]
                continue
            decision = change["after"].get("_classification")
            category = categories[change["category_id"]]
            if isinstance(decision, dict) and decision.get("binding") == C.binding(category, change["before"]):
                decision["binding"] = C.binding(category, change["after"])
            verify_payload(change["before"], change["after"], category, change["renamed"])
        require(sum(c["renamed"] for c in changes.values()) == expected["library_names"]
                and len(tag_changes) == expected["tag_names"]
                and origin_names == expected.get("original_import_names", 0), "display owner counts differ")
    # No writable output is opened until source, owner and old-name guards pass.
    output.mkdir(parents=True)
    C.backup(args.library, output / "library.sqlite3")
    C.backup(args.tags, output / "tags.sqlite3")
    with closing(C.connect(output / "library.sqlite3")) as lib, closing(C.connect(output / "tags.sqlite3")) as tags:
        for pid, change in changes.items():
            lib.execute("UPDATE prompts SET payload=? WHERE id=?", (C.packed(change["after"]), pid))
            lib.execute("INSERT INTO library_journal(at,op,prompt_id,category_id,before,after) VALUES (?,?,?,?,?,?)",
                        (stamp, "update", pid, change["category_id"], change["before_raw"], C.packed(change["after"])))
        lib.execute("INSERT INTO library_meta(key,value) VALUES ('last_modified',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (C.packed(stamp),))
        for pid, change in tag_changes.items():
            tags.execute("UPDATE tag_tags SET desc=? WHERE t_uuid=?", (change["new_title"], pid))
            if change["meta_changed"]:
                tags.execute("UPDATE workbench_tag_meta SET data=? WHERE tag_uuid=?", (C.packed(change["after"]), pid))
        lib.commit()
        tags.commit()
        C.export_document(lib, output / "data.json")
        sync = C.native("shared_sync")
        pairs = sync.build_pairs(tags.execute("SELECT t_uuid,text FROM tag_tags"),
                                 ((pid, json.loads(raw).get("prompt")) for pid, raw in lib.execute("SELECT id,payload FROM prompts")))
        C.save(output / "shared_pairs.json", {"version": sync.PAIR_VERSION, "generated_at": stamp, "library_revision": stamp, **pairs})
    store = C.native("library_store").LibraryStore(output / "library.sqlite3")
    try:
        require(store.verify_document_equals(C.read(output / "data.json")).get("equal") is True, "native export differs")
    finally:
        store.close()
    validate_library(args.library, output / "library.sqlite3", changes, categories, stamp)
    validate_tags(args.tags, output / "tags.sqlite3", tag_changes)
    require(all(C.file_hash(path) == digest for path, digest in bound.items()), "read-only input changed while staging")
    result = {"passed": True, "revision": stamp, "source_release": release, "updated_library": len(changes),
              "library_names": sum(c["renamed"] for c in changes.values()), "tag_names": len(tag_changes),
              "verified_original_import_names": origin_names,
              "explicit_metadata_scope": len(metadata), "source_versions_appended": sum(r["disposition"] == "current_source_appended" for r in registry),
              "source_versions_already_current": sum(r["disposition"] == "current_source_already_present" for r in registry),
              "classification_decisions_unchanged": True, "body_personal_fields_categories_images_unchanged": True,
              "prior_history_and_native_aliases_preserved": True, "native_export_equal": True,
              "native_tag_revision_search_side_effects_verified": True, "production_modified": False,
              "inputs": bound, "website_files": web_receipts}
    C.save(output / "stage_review.json", review)
    C.save(output / "source_registry.json", registry)
    C.save(output / "stage_validation.json", result)
    C.save(output / "stage_summary.json", {**result, "outputs": {p.name: C.file_hash(p) for p in output.iterdir() if p.is_file() and not p.name.endswith(("-wal", "-shm"))}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("review", "web", "library", "tags", "source-ledger", "identity-plan", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--review-sha256")
    args = parser.parse_args()
    result = stage(args)
    print(json.dumps({k: result[k] for k in ("passed", "updated_library", "library_names", "tag_names", "production_modified")}))


if __name__ == "__main__":
    main()
