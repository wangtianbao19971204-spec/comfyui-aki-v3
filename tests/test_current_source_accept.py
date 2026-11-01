"""Exercise real scoped acceptance with synthetic SQLite and loopback fixtures."""
from contextlib import ExitStack, closing
import importlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


FLOW = Path(__file__).resolve().parents[1] / "snapshot/runtime/benchmark_reports/source_update_flow"
sys.path.insert(0, str(FLOW))
try:
    accept = importlib.import_module("accept_current")
    publish = importlib.import_module("publish_current")
finally:
    sys.path.remove(str(FLOW))


class ScopedAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stage = self.root / "stage"
        self.runtime = self.root / "runtime"
        self.batch = self.root / "batch"
        for directory in (self.stage, self.runtime, self.batch):
            directory.mkdir()
        self.identity = {"pid": 123, "created": 1, "command": ["fixture"], "cwd": str(self.runtime)}
        self.checks = {"library_ids": [], "library_count": 1, "dictionary": [],
                       "new_resources": 0, "revision": "fixture-revision"}
        self.plan = {"runtime": str(self.runtime), "expected_live_owner": self.identity,
                     "baseline_index": {"total_prompts": 1}, "files": [],
                     "spec": {"port": 12345, "images": [], "verification": self.checks}}
        library = self.stage / "library.sqlite3"
        with closing(sqlite3.connect(library)) as connection, connection:
            connection.executescript("""
                create table library_meta(key text primary key,value text);
                create table categories(id text primary key,payload text);
                create table category_orders(id text primary key,value text);
                create table prompts(id text primary key,category_id text,payload text);
                create table library_journal(seq integer primary key autoincrement,payload text);
                insert into library_meta values ('__last_backup_at__','old');
                insert into library_meta values ('revision','fixture-revision');
                insert into categories values ('category','{}');
                insert into prompts values ('resource','category','{"id":"resource"}');
                insert into library_journal(payload) values ('retained history');
            """)
        self.install("library.sqlite3", library, "sqlite")
        for name in ("data.json", "shared_pairs.json"):
            source = self.stage / name
            source.write_text("{}", encoding="utf-8")
            self.install(name, source, "json")
        self.requests = []
        self.note_effect = lambda: None
        self.display_effect = lambda: None
        self.display_items = []
        self.connection = type("NoNetwork", (), {"close": lambda this: None})()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(publish, "owner", return_value=(None, self.identity)))
        stack.enter_context(patch.object(publish, "empty", return_value={}))
        stack.enter_context(patch.object(publish, "get", side_effect=self.get))
        stack.enter_context(patch.object(accept.http.client, "HTTPConnection", return_value=self.connection))

    def install(self, name, source, kind):
        relative = "ComfyUI/plugin/user_data/" + name
        target = self.runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        self.plan["files"].append({"stage_name": name, "stage_path": str(source),
                                   "runtime_relative": relative, "kind": kind,
                                   "stage_sha256": publish.sha(source)})
        return target

    def database(self, name, deploy=False):
        baseline = self.stage / name
        with closing(sqlite3.connect(baseline)) as connection, connection:
            connection.execute("create table data(id integer primary key,value text)")
            connection.execute("insert into data values (1,'personal value')")
        if deploy:
            return self.install(name, baseline, "sqlite")
        relative = "ComfyUI/plugin/user_data/" + name
        target = self.runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(baseline, target)
        self.checks.setdefault("readonly_databases", []).append(
            {"name": name, "runtime_relative": relative, "baseline_path": str(baseline)})
        return target

    def get(self, port, route):
        self.requests.append(route)
        if route.startswith("/prompt_selector/source-notes?"):
            self.note_effect()
            return {"source_notes": [{"title": "Book", "entry_title": "Entry", "note": "Source note"}]}
        if route.startswith("/prompt_selector/tags/page?"):
            self.display_effect()
            return {"items": self.display_items}
        self.assertEqual(route, "/prompt_selector/library/index")
        return {"total_prompts": 1, "last_modified": "fixture-revision"}

    def note_query(self):
        self.checks["source_note_queries"] = [{"resource_id": "resource",
            "expected_source_notes": [{"title": "Book", "entry_title": "Entry", "note": "Source note"}]}]

    @staticmethod
    def change(path):
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("update data set value='unexpected persistence' where id=1")

    def test_tag_and_dictionary_deployment_are_optional(self):
        result = accept.verify(self.plan, self.batch)
        self.assertTrue(result["passed"])
        self.assertFalse((self.batch / "live_snapshot/tags.sqlite3").exists())
        self.assertFalse((self.batch / "live_snapshot/dictionary.sqlite3").exists())

    def test_present_optional_databases_are_exhaustively_compared(self):
        self.database("tags.sqlite3", deploy=True)
        dictionary = self.database("dictionary.sqlite3", deploy=True)
        self.change(dictionary)
        with self.assertRaisesRegex(RuntimeError, "dictionary.sqlite3"):
            accept.verify(self.plan, self.batch)

    def test_present_tag_database_drift_fails(self):
        tags = self.database("tags.sqlite3", deploy=True)
        self.change(tags)
        with self.assertRaisesRegex(RuntimeError, "tags.sqlite3"):
            accept.verify(self.plan, self.batch)

    def test_undeployed_readonly_databases_are_snapshotted_and_verified(self):
        self.database("tags.sqlite3")
        self.database("dictionary.sqlite3")
        self.note_query()
        result = accept.verify(self.plan, self.batch)
        self.assertEqual(result["readonly_databases_verified"], 2)
        self.assertEqual(result["source_note_queries_verified"], 1)
        self.assertEqual(len(self.requests), 2)

    def test_source_note_get_persistence_to_undeployed_tag_is_detected(self):
        tags = self.database("tags.sqlite3")
        self.note_query()
        self.note_effect = lambda: self.change(tags)
        with self.assertRaisesRegex(RuntimeError, "Read-only database changed: tags.sqlite3"):
            accept.verify(self.plan, self.batch)
        self.assertTrue(self.requests[0].startswith("/prompt_selector/source-notes?"))

    def test_source_note_get_persistence_to_library_is_detected(self):
        self.note_query()
        target = self.runtime / self.plan["files"][0]["runtime_relative"]
        def write():
            with closing(sqlite3.connect(target)) as connection, connection:
                connection.execute("update prompts set payload='{}'")
        self.note_effect = write
        with self.assertRaisesRegex(RuntimeError, "prompts"):
            accept.verify(self.plan, self.batch)

    def test_sqlite_sequence_drift_fails_even_with_identical_journal_rows(self):
        target = self.runtime / self.plan["files"][0]["runtime_relative"]
        with closing(sqlite3.connect(target)) as connection, connection:
            connection.execute("update sqlite_sequence set seq=99 where name='library_journal'")
        with self.assertRaisesRegex(RuntimeError, "sqlite_sequence"):
            accept.verify(self.plan, self.batch)

    def test_only_operational_backup_timestamp_may_differ(self):
        target = self.runtime / self.plan["files"][0]["runtime_relative"]
        with closing(sqlite3.connect(target)) as connection, connection:
            connection.execute("update library_meta set value='new' where key='__last_backup_at__'")
        self.assertTrue(accept.verify(self.plan, self.batch)["passed"])

    def test_nonoperational_library_metadata_drift_fails(self):
        target = self.runtime / self.plan["files"][0]["runtime_relative"]
        with closing(sqlite3.connect(target)) as connection, connection:
            connection.execute("update library_meta set value='drift' where key='revision'")
        with self.assertRaisesRegex(RuntimeError, "metadata differs"):
            accept.verify(self.plan, self.batch)

    def test_source_and_stage_drifting_together_cannot_replace_reviewed_hash(self):
        source = self.stage / "source.js"
        source.write_text("reviewed source", encoding="utf-8")
        target = self.install("source.js", source, "source")
        source.write_text("unreviewed source", encoding="utf-8")
        target.write_text("unreviewed source", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "main Git seal"):
            accept.verify(self.plan, self.batch)

    def tag_search_fixture(self, consume=True):
        source = self.stage / "tags.sqlite3"
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.executescript("""
                create table tag_tags(id_index integer primary key,t_uuid text,text text,desc text);
                create table workbench_tag_revision(id integer primary key,value integer);
                create table workbench_tag_search_journal(seq integer primary key autoincrement,id_index integer,operation text,tag_text text,tag_desc text);
                insert into tag_tags values(10,'tag-one','artist body one','new display one');
                insert into tag_tags values(20,'tag-two','artist body two','new display two');
                insert into workbench_tag_revision values(1,123);
                insert into workbench_tag_search_journal values(1,999,'upsert','old retained text','old retained display');
                insert into workbench_tag_search_journal values(2,10,'upsert','artist body one','new display one');
                insert into workbench_tag_search_journal values(3,20,'upsert','artist body two','new display two');
            """)
        self.tag_target = self.install("tags.sqlite3", source, "sqlite")
        self.checks["tag_search_journal_consumption"] = [
            {"seq": 2, "id_index": 10, "operation": "upsert", "tag_text": "artist body one", "tag_desc": "new display one"},
            {"seq": 3, "id_index": 20, "operation": "upsert", "tag_text": "artist body two", "tag_desc": "new display two"}]
        self.checks["tag_display_queries"] = [
            {"tag_uuid": "tag-one", "desc": "new display one", "query": "new display one"},
            {"tag_uuid": "tag-two", "desc": "new display two", "query": "new display two"}]
        self.display_items = [{"t_uuid": row["tag_uuid"], "desc": row["desc"]} for row in self.checks["tag_display_queries"]]
        relative = "ComfyUI/plugin/user_data/cache/tag_search.v1.db"
        self.checks["tag_search_cache_runtime_relative"] = relative
        self.cache = self.runtime / relative
        self.cache.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.cache)) as connection, connection:
            connection.execute("CREATE VIRTUAL TABLE tag_search USING fts5(tag_text,tag_desc,content='',contentless_delete=1,tokenize='trigram case_sensitive 1')")
            connection.execute("CREATE TABLE search_meta(id integer primary key,format integer,applied_seq integer)")
            connection.execute("INSERT INTO search_meta VALUES(1,1,3)")
            for row in self.checks["tag_search_journal_consumption"]:
                connection.execute("INSERT INTO tag_search(rowid,tag_text,tag_desc) VALUES(?,?,?)",
                                   (row["id_index"], row["tag_text"], row["tag_desc"]))
        if consume:
            self.display_effect = self.consume_tag_search

    def consume_tag_search(self):
        with closing(sqlite3.connect(self.tag_target)) as connection, connection:
            connection.execute("DELETE FROM workbench_tag_search_journal WHERE seq IN(2,3)")

    def test_exact_native_tag_journal_consumption_requires_matching_fts_cache(self):
        self.tag_search_fixture()
        result = accept.verify(self.plan, self.batch)
        self.assertTrue(result["passed"])
        self.assertFalse(result["all_scoped_databases_equal_to_stage"])
        self.assertTrue(result["all_scoped_databases_match_reviewed_state"])
        state = result["tag_search_reviewed_state"]
        self.assertEqual(state["consumed_seq"], [2, 3])
        self.assertEqual(state["pending_approved_seq"], [])
        self.assertTrue(state["cache"]["verified"])
        self.assertEqual(result["tag_display_queries_verified"], 2)
        with closing(sqlite3.connect(self.batch / "live_snapshot/tags.sqlite3")) as connection:
            self.assertEqual(connection.execute("SELECT seq FROM workbench_tag_search_journal").fetchall(), [(1,)])

    def test_no_consumption_does_not_require_a_cache(self):
        self.tag_search_fixture(consume=False)
        self.cache.unlink()
        result = accept.verify(self.plan, self.batch)
        self.assertTrue(result["all_scoped_databases_equal_to_stage"])
        self.assertEqual(result["tag_search_reviewed_state"]["consumed_seq"], [])
        self.assertNotIn("cache", result["tag_search_reviewed_state"])

    def test_native_search_must_return_approved_tag_uuid_and_display(self):
        self.tag_search_fixture()
        self.display_items[0]["desc"] = "old display"
        with self.assertRaisesRegex(RuntimeError, "display/search"):
            accept.verify(self.plan, self.batch)
        self.assertFalse((self.batch / "live_snapshot").exists())

    def test_retained_approved_journal_row_cannot_be_rewritten(self):
        self.tag_search_fixture(consume=False)
        with closing(sqlite3.connect(self.tag_target)) as connection, connection:
            connection.execute("UPDATE workbench_tag_search_journal SET tag_desc='tampered' WHERE seq=2")
        with self.assertRaisesRegex(RuntimeError, "rewritten"):
            accept.verify(self.plan, self.batch)

    def test_unapproved_old_journal_row_must_not_be_deleted(self):
        self.tag_search_fixture()
        with closing(sqlite3.connect(self.tag_target)) as connection, connection:
            connection.execute("DELETE FROM workbench_tag_search_journal WHERE seq=1")
        with self.assertRaisesRegex(RuntimeError, "Unapproved.*deleted"):
            accept.verify(self.plan, self.batch)

    def test_consumption_does_not_allow_tag_or_personal_data_changes(self):
        self.tag_search_fixture()
        with closing(sqlite3.connect(self.tag_target)) as connection, connection:
            connection.execute("UPDATE tag_tags SET text='different maintained body' WHERE id_index=10")
        with self.assertRaisesRegex(RuntimeError, "outside reviewed.*tag_tags"):
            accept.verify(self.plan, self.batch)

    def test_cache_text_mismatch_rejects_consumed_rows(self):
        self.tag_search_fixture()
        with closing(sqlite3.connect(self.cache)) as connection, connection:
            connection.execute("DELETE FROM tag_search WHERE rowid=10")
            connection.execute("INSERT INTO tag_search(rowid,tag_text,tag_desc) VALUES(10,'wrong cached body','new display one')")
        with self.assertRaisesRegex(RuntimeError, "cache.*differ"):
            accept.verify(self.plan, self.batch)

    def test_cache_must_record_consumed_sequence_as_applied(self):
        self.tag_search_fixture()
        with closing(sqlite3.connect(self.cache)) as connection, connection:
            connection.execute("UPDATE search_meta SET applied_seq=1")
        with self.assertRaisesRegex(RuntimeError, "not applied"):
            accept.verify(self.plan, self.batch)

    def test_equal_token_counts_do_not_hide_wrong_cache_postings(self):
        self.tag_search_fixture()
        with closing(sqlite3.connect(self.cache)) as connection, connection:
            connection.execute("DELETE FROM tag_search WHERE rowid=10")
            connection.execute("INSERT INTO tag_search(rowid,tag_text,tag_desc) VALUES(10,'artist body six','new display one')")
        with self.assertRaisesRegex(RuntimeError, "postings differ"):
            accept.verify(self.plan, self.batch)

    def test_unapproved_retained_journal_payload_cannot_change(self):
        self.tag_search_fixture()
        with closing(sqlite3.connect(self.tag_target)) as connection, connection:
            connection.execute("UPDATE workbench_tag_search_journal SET tag_desc='rewritten old row' WHERE seq=1")
        with self.assertRaisesRegex(RuntimeError, "rewritten"):
            accept.verify(self.plan, self.batch)

    def test_consumption_approval_must_exactly_match_sealed_stage_rows(self):
        self.tag_search_fixture()
        self.checks["tag_search_journal_consumption"][0]["tag_text"] = "unreviewed value"
        with self.assertRaisesRegex(RuntimeError, "Approved.*differs from stage|not the staged Tag row"):
            accept.verify(self.plan, self.batch)


if __name__ == "__main__":
    unittest.main()
