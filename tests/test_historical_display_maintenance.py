"""Synthetic native-store and Tag-trigger proofs for display/source maintenance."""
import argparse
import copy
from contextlib import closing
import importlib.util
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
        for path, rows in ((self.ledger, history), (self.plan, self.identities)):
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        paths = [self.library, self.tags, self.ledger, self.plan, self.registries,
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

    def test_changed_review_bound_input_is_rejected_before_output(self):
        self.ledger.write_text("unreviewed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "input drift"):
            D.stage(self.args)
        self.assertFalse(self.args.output.exists())


if __name__ == "__main__":
    unittest.main()
