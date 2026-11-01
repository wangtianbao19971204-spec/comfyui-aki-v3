"""Synthetic native-store and Tag-trigger proofs for display/source maintenance."""
import argparse
import copy
from contextlib import closing
import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


FLOW = Path(__file__).resolve().parents[1] / "snapshot/runtime/benchmark_reports/source_update_flow"
sys.path.insert(0, str(FLOW))
try:
    SPEC = importlib.util.spec_from_file_location("display_maintenance_tested", FLOW / "stage_display_maintenance.py")
    D = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(D)
finally:
    sys.path.remove(str(FLOW))
C = D.C


class DisplayMaintenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.web = self.root / "web"
        self.web.mkdir()
        self.library, self.tags = self.root / "library.sqlite3", self.root / "tags.sqlite3"
        self.ledger, self.plan = self.root / "history.jsonl", self.root / "identities.jsonl"
        self.registries, self.approval = self.root / "registry.json", self.root / "review.json"
        self.old = {key: {"id": key, "title": "Old " + key, "tags": "source " + key,
                          "negative": "old exclusion", "characterPrompts": [], "path": ["old area"]}
                    for key in ("a", "m", "t")}
        self.current = {key: {**copy.deepcopy(value), "title": "New " + key,
                              "note": "Current source note", "path": ["new source area"]}
                        for key, value in self.old.items()}
        self.category = {"id": "cat", "name": "Maintained local semantic area"}
        self.payloads = {}
        for key in ("a", "m"):
            payload = {"id": "codex-" + key, "alias": "Old " + key, "prompt": "Maintained body " + key,
                       "description": "Personal description", "notes": "Personal note", "image": "personal.png",
                       "favorite": True, "usage_count": 7, "_collection": {"notes": "keep"},
                       "_external_sources": [{"historic": n} for n in range(11)],
                       "_classification": {"semantic_review_status": "codex_import", "primary_class": "appearance",
                                           "manual_search_eligible": True, "random_pool_eligible": False}}
            self.payloads[key] = payload
        self.payloads["a"]["_external_source"] = {"dataset": "book", "entry_id": "a", "custom": "keep"}
        self.payloads["m"]["_external_sources"].append(C.variant("book", self.current["m"], "r-current"))
        store = C.native("library_store").LibraryStore(self.library, create=True)
        try:
            store.initialize_from_document({"last_modified": "before", "_source_to_canonical": {},
                "categories": [{**self.category, "prompts": list(self.payloads.values()) +
                                [{"id": "other-owner", "prompt": "Unchanged other body", "alias": "Personal"}]}]})
        finally:
            store.close()
        with closing(C.connect(self.library)) as connection, connection:
            self.category = json.loads(connection.execute("SELECT payload FROM categories WHERE id='cat'").fetchone()[0])
            for payload in self.payloads.values():
                payload["_classification"]["binding"] = C.binding(self.category, payload)
                connection.execute("UPDATE prompts SET payload=? WHERE id=?", (C.packed(payload), payload["id"]))
        self.tag_metadata = {"notes": "Personal Tag note", "favorite": True, "themes": ["keep"],
                             "external_source": {"dataset": "book", "entry_id": "t", "custom": "keep"},
                             "external_sources": [{"historical": 1}]}
        with closing(C.connect(self.tags)) as connection, connection:
            connection.executescript("""
                create table tag_tags(id_index integer primary key autoincrement,text text,desc text,color text,t_uuid text unique,g_uuid text);
                create table workbench_tag_meta(tag_uuid text primary key,data text);
                create table workbench_tag_revision(id integer primary key,value integer not null);
                create table workbench_tag_text_revision(id integer primary key,value integer not null);
                create table workbench_tag_search_journal(seq integer primary key autoincrement,id_index integer,operation text,tag_text text,tag_desc text);
                insert into tag_tags(text,desc,color,t_uuid,g_uuid) values ('tag body','Old t','blue','tag-t','local-folder');
                insert into workbench_tag_revision values(1,10);
                insert into workbench_tag_text_revision values(1,20);
                insert into workbench_tag_search_journal(id_index,operation,tag_text,tag_desc) values(1,'upsert','tag body','old t');
                create trigger tag_revision after update on tag_tags begin
                  update workbench_tag_revision set value=value+1 where id=1;
                  update workbench_tag_text_revision set value=value+1 where id=1;
                  insert into workbench_tag_search_journal(id_index,operation,tag_text,tag_desc) values(new.id_index,'upsert',lower(new.text),lower(new.desc)); end;
                create trigger meta_revision after update on workbench_tag_meta begin
                  update workbench_tag_revision set value=value+1 where id=1; end;
            """)
            connection.execute("INSERT INTO workbench_tag_meta VALUES (?,?)", ("tag-t", C.packed(self.tag_metadata)))
        self.identities = [{"source": "book:" + key, "owner": {"store": "tags" if key == "t" else "library",
                            "target_id": "tag-t" if key == "t" else "codex-" + key}, "source_hold": False}
                           for key in self.old]
        self.review = {"schema": D.SCHEMA, "accepted_registries": [str(self.registries)],
                       "display_sources": [], "metadata_sources": [copy.deepcopy(self.identities[1])],
                       "expected": {"display_sources": 2, "metadata_sources": 1, "library_names": 1, "tag_names": 1}}
        for key, identity in (("a", self.identities[0]), ("t", self.identities[2])):
            self.review["display_sources"].append({**copy.deepcopy(identity), "old_source_title": "Old " + key,
                "new_source_title": "New " + key, "global_current_bindings": [{"source": "book:" + key, "raw_sha256": C.digest(self.current[key])}]})
        self.args = argparse.Namespace(review=self.approval, library=self.library, tags=self.tags,
            web=self.web, source_ledger=self.ledger, identity_plan=self.plan, output=self.root / "new-stage", review_sha256=None)
        self.origin_paths = []
        self.write_inputs()

    def write_inputs(self):
        C.save(self.registries, [])
        C.save(self.web / "book.json", {"entries": list(self.current.values())})
        C.save(self.web / "codexes.json", [{"id": "book", "title": "Synthetic Book"}])
        C.save(self.web / "current.json", {"release": "r-current"})
        C.save(self.web / "manifest.json", {"release": "r-current", "files": {
            name: {"bytes": (self.web / name).stat().st_size, "sha256": C.file_hash(self.web / name)}
            for name in ("book.json", "codexes.json")}})
        history = [{"source": "book:" + key, "dataset": "book", "entry_id": key,
                    "before_raw": self.old[key], "after_raw": value, "old_raw_sha256": C.digest(self.old[key]),
                    "new_raw_sha256": C.digest(value), "new_release": "r-current", "new_file_sha256": C.file_hash(self.web / "book.json")}
                   for key, value in self.current.items()]
        frozen = self.root / "origin-source/book.json"
        if frozen.exists():
            for row in history:
                row["old_file_sha256"] = C.file_hash(frozen)
        for path, rows in ((self.ledger, history), (self.plan, self.identities)):
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        paths = [self.library, self.tags, self.ledger, self.plan, self.registries, *self.origin_paths,
                 *(self.web / name for name in ("manifest.json", "codexes.json", "current.json"))]
        self.review["inputs"] = {str(path): C.file_hash(path) for path in paths}
        C.save(self.approval, self.review)

    def run_stage(self):
        self.write_inputs()
        return D.stage(self.args)

    def payload(self, database, key="a"):
        with closing(C.connect(database, True)) as connection:
            return json.loads(connection.execute("SELECT payload FROM prompts WHERE id=?", ("codex-" + key,)).fetchone()[0])

    def test_native_name_and_tag_desc_update_preserve_body_personal_fields_and_history(self):
        hashes = {str(path): C.file_hash(path) for path in (self.library, self.tags)}
        result = self.run_stage()
        self.assertEqual(result["library_names"], 1)
        self.assertEqual(result["tag_names"], 1)
        self.assertEqual(result["source_versions_appended"], 2)
        self.assertEqual(result["source_versions_already_current"], 1)
        self.assertEqual(result["updated_library"], 1)
        self.assertEqual(hashes, {str(path): C.file_hash(path) for path in (self.library, self.tags)})
        after = self.payload(self.args.output / "library.sqlite3")
        self.assertEqual(after["alias"], "New a")
        for field in ("prompt", "description", "notes", "image", "favorite", "usage_count", "_collection"):
            self.assertEqual(after[field], self.payloads["a"][field])
        self.assertEqual(after["_external_sources"][:11], self.payloads["a"]["_external_sources"])
        self.assertEqual(after["_external_source"]["custom"], "keep")
        decision = {k: v for k, v in after["_classification"].items() if k != "binding"}
        self.assertEqual(decision, {k: v for k, v in self.payloads["a"]["_classification"].items() if k != "binding"})
        with closing(C.connect(self.args.output / "tags.sqlite3", True)) as connection:
            self.assertEqual(connection.execute("SELECT text,desc,color,t_uuid,g_uuid FROM tag_tags").fetchone(),
                             ("tag body", "New t", "blue", "tag-t", "local-folder"))
            self.assertEqual(connection.execute("SELECT value FROM workbench_tag_revision").fetchone()[0], 12)
            self.assertEqual(connection.execute("SELECT value FROM workbench_tag_text_revision").fetchone()[0], 21)

    def test_different_personal_library_name_aborts_before_output(self):
        with closing(C.connect(self.library)) as connection, connection:
            payload = self.payload(self.library)
            payload["alias"] = "User chosen title"
            connection.execute("UPDATE prompts SET payload=? WHERE id='codex-a'", (C.packed(payload),))
        with self.assertRaisesRegex(ValueError, "exact old source title"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_different_personal_tag_display_name_aborts(self):
        with closing(C.connect(self.tags)) as connection, connection:
            connection.execute("UPDATE tag_tags SET desc='Personal Tag label'")
        with self.assertRaisesRegex(ValueError, "Tag display desc"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_intentional_source_hold_cannot_be_written(self):
        self.identities[0]["source_hold"] = True
        with self.assertRaisesRegex(ValueError, "held source"):
            self.run_stage()

    def test_native_alias_overrides_still_present_physical_source_row(self):
        with closing(C.connect(self.library)) as connection, connection:
            connection.execute("INSERT OR REPLACE INTO library_meta VALUES ('_source_to_canonical',?)",
                               (C.packed({"codex-a": {"canonical_id": "other-owner", "source_category_id": "cat"}}),))
        with self.assertRaisesRegex(ValueError, "actual owner changed"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_unlisted_current_source_bound_to_owner_is_rejected(self):
        self.old["b"] = {"id": "b", "title": "Other old title", "tags": "other"}
        self.current["b"] = {"id": "b", "title": "Conflicting current title", "tags": "other"}
        self.identities.append({"source": "book:b", "owner": {"store": "library", "target_id": "codex-a"}, "source_hold": False})
        with closing(C.connect(self.library)) as connection, connection:
            connection.execute("INSERT OR REPLACE INTO library_meta VALUES ('_source_to_canonical',?)",
                               (C.packed({"codex-b": {"canonical_id": "codex-a", "source_category_id": "cat"}}),))
        with self.assertRaisesRegex(ValueError, "binding set changed"):
            self.run_stage()

    def test_invalid_classification_binding_is_not_repaired(self):
        with closing(C.connect(self.library)) as connection, connection:
            payload = self.payload(self.library)
            payload["_classification"]["binding"] = "invalid original binding"
            connection.execute("UPDATE prompts SET payload=? WHERE id='codex-a'", (C.packed(payload),))
        self.run_stage()
        self.assertEqual(self.payload(self.args.output / "library.sqlite3")["_classification"]["binding"], "invalid original binding")

    def test_tag_search_journal_trigger_failure_is_detected(self):
        with closing(C.connect(self.tags)) as connection, connection:
            connection.execute("DROP TRIGGER tag_revision")
        with self.assertRaisesRegex(ValueError, "Tag revision|search journal|Tag sequence"):
            self.run_stage()

    def test_already_current_primary_does_not_duplicate_raw_history(self):
        with closing(C.connect(self.library)) as connection, connection:
            payload = self.payload(self.library)
            payload["_external_source"] = C.variant("book", self.current["a"], "r-current")
            payload["_classification"]["binding"] = C.binding(self.category, payload)
            connection.execute("UPDATE prompts SET payload=? WHERE id='codex-a'", (C.packed(payload),))
        result = self.run_stage()
        after = self.payload(self.args.output / "library.sqlite3")
        self.assertEqual(sum(v.get("raw_entry") == self.current["a"] for v in after["_external_sources"]), 0)
        self.assertEqual(result["source_versions_appended"], 1)
        self.assertEqual(after["alias"], "New a")

    def test_current_history_note_is_not_overridden_by_archived_old_primary(self):
        with closing(C.connect(self.library)) as connection, connection:
            payload = self.payload(self.library)
            payload["_external_source"] = C.variant("book", self.old["a"], "r-old")
            payload["_external_sources"].append(C.variant("book", self.current["a"], "r-current"))
            payload["_classification"]["binding"] = C.binding(self.category, payload)
            connection.execute("UPDATE prompts SET payload=? WHERE id='codex-a'", (C.packed(payload),))
            before_history = copy.deepcopy(payload["_external_sources"])
        self.run_stage()
        after = self.payload(self.args.output / "library.sqlite3")
        self.assertEqual(after["_external_sources"], before_history)
        self.assertEqual(after["_external_sources"][-1]["raw_entry"]["note"], "Current source note")
        self.assertEqual(after["_external_source"]["raw_entry"], self.old["a"])

    def test_native_alias_without_original_category_contract_is_rejected(self):
        with closing(C.connect(self.library)) as connection, connection:
            connection.execute("INSERT OR REPLACE INTO library_meta VALUES ('_source_to_canonical',?)",
                               (C.packed({"codex-a": {"canonical_id": "codex-a"}}),))
        with self.assertRaisesRegex(ValueError, "invalid baseline native source alias"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def original_name_authority(self, existing=False):
        self.old["b"] = {"id": "b", "title": "Other old source", "tags": "other body"}
        self.current["b"] = {"id": "b", "title": "Different current source title", "tags": "other body"}
        self.identities.append({"source": "book:b", "owner": {"store": "library", "target_id": "codex-a"}, "source_hold": False})
        item = self.review["display_sources"][0]
        item["global_current_bindings"].append({"source": "book:b", "raw_sha256": C.digest(self.current["b"])})
        with closing(C.connect(self.library)) as connection, connection:
            connection.execute("INSERT OR REPLACE INTO library_meta VALUES ('_source_to_canonical',?)",
                (C.packed({"codex-b": {"canonical_id": "codex-a", "source_category_id": "cat"}}),))
            before = self.payload(self.library)
            raw = C.packed(before)
            connection.execute("INSERT INTO library_journal(at,op,prompt_id,category_id,before,after) VALUES ('origin-checkpoint','update','codex-a','cat',?,?)", (raw, raw))
        folder = self.root / "origin-source"
        folder.mkdir()
        frozen, manifest = folder / "book.json", folder / "manifest.json"
        C.save(frozen, {"entries": list(self.old.values())})
        C.save(manifest, {"release": "r-old", "files": {"book.json": {"size": frozen.stat().st_size, "sha256": C.file_hash(frozen)}}})
        first, last, edge = self.root / "original-import.json", self.root / "checkpoint.sqlite3", self.root / "import-operations.json"
        C.save(first, {"categories": [{"prompts": [before]}]})
        C.backup(self.library, last)
        if existing:
            C.save(edge, [{"source": "book:a", "target_id": "codex-a", "disposition": "library_existing"}])
        else:
            C.save(edge, [{"source": "book:a", "id": "codex-a", "store": "library", "action": ["add"]}])
        item["origin_naming_authority"] = {"schema": "origin-naming-authority/v1", "origin_source": "book:a", "native_origin_id": "codex-a",
            "frozen_source": {"path": str(frozen), "manifest_path": str(manifest), "name": "book.json", "release": "r-old"},
            "old_source_entry_sha256": C.digest(self.old["a"]),
            "checkpoints": [{"path": str(first), "kind": "document", "payload_sha256": C.digest(before)},
                            {"path": str(last), "kind": "sqlite", "payload_sha256": C.digest(before)}],
            "import_edge": {"path": str(edge), "kind": "accepted_existing_import" if existing else "direct_add"},
            "journal_checkpoint": {"path": str(last), "rows": [{"seq": 1, "at": "origin-checkpoint", "op": "update",
                "before_alias": "Old a", "after_alias": "Old a", "before_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "after_sha256": hashlib.sha256(raw.encode()).hexdigest()}]}}
        self.origin_paths = [frozen, manifest, first, last, edge]
        self.review["expected"]["original_import_names"] = 1
        return item["origin_naming_authority"]

    def test_proven_original_import_name_can_update_despite_other_current_titles(self):
        self.original_name_authority()
        result = self.run_stage()
        self.assertEqual(result["verified_original_import_names"], 1)
        after = self.payload(self.args.output / "library.sqlite3")
        self.assertEqual(after["alias"], "New a")
        self.assertEqual(after["prompt"], self.payloads["a"]["prompt"])
        self.assertEqual(after["_external_source"], self.payloads["a"]["_external_source"])
        self.assertEqual(after["_external_sources"], self.payloads["a"]["_external_sources"])
        self.assertEqual(result["source_versions_appended"], 1)  # Ordinary Tag case only.

    def test_accepted_existing_import_has_separate_exact_name_proof(self):
        self.original_name_authority(existing=True)
        self.assertEqual(self.run_stage()["verified_original_import_names"], 1)

    def test_conflicting_titles_still_fail_without_original_import_authority(self):
        self.original_name_authority()
        self.review["display_sources"][0].pop("origin_naming_authority")
        self.review["expected"].pop("original_import_names")
        with self.assertRaisesRegex(ValueError, "current titles conflict"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_approval_boolean_is_not_original_naming_evidence(self):
        self.original_name_authority()
        self.review["display_sources"][0]["origin_naming_authority"] = {"approved": True}
        with self.assertRaisesRegex(ValueError, "explicit original naming evidence"):
            self.run_stage()

    def test_original_name_checkpoint_with_local_rename_is_rejected(self):
        authority = self.original_name_authority()
        first = Path(authority["checkpoints"][0]["path"])
        document = C.read(first)
        document["categories"][0]["prompts"][0]["alias"] = "A personal renamed title"
        C.save(first, document)
        with self.assertRaisesRegex(ValueError, "checkpoint is missing, renamed or changed"):
            self.run_stage()

    def test_retained_journal_rename_is_not_overruled_by_original_name_claim(self):
        authority = self.original_name_authority()
        with closing(C.connect(authority["journal_checkpoint"]["path"])) as connection, connection:
            payload = copy.deepcopy(self.payloads["a"])
            payload["alias"] = "A personal renamed title"
            connection.execute("UPDATE library_journal SET before=?", (C.packed(payload),))
        with self.assertRaisesRegex(ValueError, "local rename or deletion"):
            self.run_stage()

    def test_later_primary_cannot_replace_the_selected_original_source(self):
        authority = self.original_name_authority()
        authority["origin_source"] = "book:b"
        with self.assertRaisesRegex(ValueError, "direct canonical import"):
            self.run_stage()

    def test_original_import_operation_must_really_match_source_and_owner(self):
        authority = self.original_name_authority()
        C.save(Path(authority["import_edge"]["path"]), [{"source": "book:b", "id": "codex-a", "store": "library", "action": ["add"]}])
        with self.assertRaisesRegex(ValueError, "direct add does not establish"):
            self.run_stage()

    def test_origin_name_does_not_require_old_history_for_secondary_sources(self):
        self.original_name_authority()
        self.identities = [row for row in self.identities if row["source"] != "book:b"]
        self.assertEqual(self.run_stage()["verified_original_import_names"], 1)

    def test_later_primary_is_preserved_but_does_not_choose_canonical_name(self):
        self.original_name_authority()
        with closing(C.connect(self.library)) as connection, connection:
            before = self.payload(self.library)
            before["_external_source"] = C.variant("book", self.current["b"], "r-current")
            before["_classification"]["binding"] = C.binding(self.category, before)
            connection.execute("UPDATE prompts SET payload=? WHERE id='codex-a'", (C.packed(before),))
        self.run_stage()
        after = self.payload(self.args.output / "library.sqlite3")
        self.assertEqual(after["alias"], "New a")
        self.assertEqual(after["_external_source"], before["_external_source"])
        self.assertEqual(after["_external_sources"], before["_external_sources"])

    def test_changed_review_bound_input_is_rejected_before_output(self):
        self.ledger.write_text("unreviewed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "input drift"):
            D.stage(self.args)
        self.assertFalse(self.args.output.exists())


if __name__ == "__main__":
    unittest.main()
