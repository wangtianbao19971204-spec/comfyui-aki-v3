"""Offline release fault injection; never contact or control a real service."""
from contextlib import ExitStack, closing, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "snapshot/runtime/benchmark_reports/source_update_flow"
sys.path.insert(0, str(SOURCE))
try:
    SPEC = importlib.util.spec_from_file_location("publish_current_tested", SOURCE / "publish_current.py")
    publish = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(publish)
finally:
    sys.path.remove(str(SOURCE))


class PublishPrimitiveTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def database(self, name, rows=((1, b"a"), (2, b"b"))):
        path = self.root / name
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("create table entries(id integer primary key, value blob)")
            conn.executemany("insert into entries values (?,?)", rows)
        return path

    def test_backup_includes_committed_wal_and_does_not_mutate_source(self):
        source = self.database("live.db")
        with closing(sqlite3.connect(source)) as writer, writer:
            writer.execute("pragma journal_mode=WAL")
            writer.execute("insert into entries values (3,?)", (b"wal-only",))
            writer.commit()
            self.assertGreater(Path(str(source) + "-wal").stat().st_size, 0)
            before = publish.sha(source)
            target = self.root / "backup.db"
            publish.backup_sqlite(source, target)
            self.assertEqual(publish.sha(source), before)
            self.assertEqual(publish.fingerprint(source), publish.fingerprint(target))
            with closing(sqlite3.connect(target)) as backup:
                self.assertEqual(backup.execute("select value from entries where id=3").fetchone()[0], b"wal-only")
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                publish.backup_sqlite(source, target)

    def test_fingerprint_ignores_insertion_order_but_detects_content_and_schema(self):
        a = self.database("a.db")
        b = self.database("b.db", ((2, b"b"), (1, b"a")))
        self.assertEqual(publish.fingerprint(a), publish.fingerprint(b))
        with closing(sqlite3.connect(b)) as conn, conn:
            conn.execute("update entries set value=? where id=2", (b"changed",))
        self.assertNotEqual(publish.fingerprint(a), publish.fingerprint(b))
        with closing(sqlite3.connect(b)) as conn, conn:
            conn.execute("update entries set value=? where id=2", (b"b",))
            conn.execute("create index by_value on entries(value)")
        self.assertNotEqual(publish.fingerprint(a)["schema"], publish.fingerprint(b)["schema"])

    def test_busy_checkpoint_preserves_real_nonempty_wal_and_shm(self):
        source = self.database("busy.db")
        writer = sqlite3.connect(source)
        reader = sqlite3.connect(source)
        try:
            writer.execute("pragma journal_mode=WAL")
            reader.execute("begin")
            reader.execute("select * from entries").fetchall()
            writer.execute("insert into entries values (3,?)", (b"new",))
            writer.commit()
            wal = Path(str(source) + "-wal")
            shm = Path(str(source) + "-shm")
            before = wal.read_bytes()
            original_connect = sqlite3.connect
            with patch.object(publish.sqlite3, "connect", side_effect=lambda *a, **k: original_connect(*a, timeout=0, **k)):
                with self.assertRaisesRegex(RuntimeError, "busy"):
                    publish.checkpoint(source)
            self.assertEqual(wal.read_bytes(), before)
            self.assertTrue(shm.exists())
        finally:
            reader.close()
            writer.close()

    def test_checkpoint_refuses_residual_wal_even_after_success_result(self):
        source = self.root / "synthetic.db"
        source.write_bytes(b"main")
        wal = Path(str(source) + "-wal")
        shm = Path(str(source) + "-shm")
        wal.write_bytes(b"uncheckpointed-evidence")
        shm.write_bytes(b"shared-index")
        class Conn:
            def execute(self, query):
                return types.SimpleNamespace(fetchone=lambda: (0, 0, 0) if "wal_checkpoint" in query else ("ok",))
            def close(self):
                pass
        with patch.object(publish.sqlite3, "connect", return_value=Conn()):
            with self.assertRaisesRegex(RuntimeError, "Nonempty WAL"):
                publish.checkpoint(source)
        self.assertEqual(wal.read_bytes(), b"uncheckpointed-evidence")
        self.assertTrue(shm.exists())

    def test_checkpoint_missing_database_must_not_create_empty_replacement(self):
        missing = self.root / "externally_removed.db"
        with self.assertRaises((RuntimeError, FileNotFoundError, sqlite3.OperationalError)):
            publish.checkpoint(missing)
        self.assertFalse(missing.exists())

    def test_atomic_replace_failure_preserves_original_and_allows_restore_retry(self):
        source = self.root / "new.json"
        target = self.root / "live.json"
        source.write_bytes(b"new content")
        target.write_bytes(b"old content")
        with patch.object(publish.os, "replace", side_effect=OSError("injected rename fault")):
            with self.assertRaisesRegex(OSError, "rename fault"):
                publish.atomic_copy(source, target)
        self.assertEqual(target.read_bytes(), b"old content")
        self.assertEqual(list(self.root.glob("*.source-sync-*")), [])
        publish.atomic_copy(source, target)
        self.assertEqual(target.read_bytes(), b"new content")

    def test_partial_copy_failure_cleans_only_its_own_temporary_file(self):
        source = self.root / "source"
        target = self.root / "target"
        unrelated = self.root / "target.source-sync-unrelated.tmp"
        source.write_bytes(b"new")
        target.write_bytes(b"old")
        unrelated.write_bytes(b"retain")
        def broken_copy(inp, out, length):
            out.write(b"partial")
            raise OSError("injected copy fault")
        with patch.object(publish.shutil, "copyfileobj", side_effect=broken_copy):
            with self.assertRaisesRegex(OSError, "copy fault"):
                publish.atomic_copy(source, target)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(list(self.root.glob("*.source-sync-*")), [unrelated])


class FakeProcess:
    def __init__(self, pid, services, command, cwd, listening=True):
        self.pid = pid
        self.services = services
        self.command = command
        self.working = cwd
        self.alive = True
        self.listening = listening
        self.creation = float(pid)
        self.wait_error_once = False
    def create_time(self): return self.creation
    def cmdline(self): return self.command
    def cwd(self): return self.working
    def environ(self): return {"OFFLINE_FIXTURE": "yes"}
    def is_running(self): return self.alive
    def poll(self): return None if self.alive else 0
    def terminate(self): self.alive = False; self.listening = False
    def wait(self, timeout):
        if self.wait_error_once:
            self.wait_error_once = False
            raise TimeoutError("injected wait failure after exit")
        return 0


class CurrentPublishFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runtime = self.root / "runtime"
        self.data = self.runtime / "ComfyUI/plugin/user_data"
        self.data.mkdir(parents=True)
        self.stage = self.root / "stage"
        self.stage.mkdir()
        self.batch = self.root / "release"
        self.spec = {"port": 12345, "files": [], "images": [], "bound_receipts": {}, "source_pointers": []}
        command = [str(self.runtime / "python/python.exe"), "main.py", "--port", "12345"]
        self.processes = {}
        self.original = FakeProcess(101, self.processes, command, str(self.runtime / "ComfyUI"))
        self.processes[101] = self.original
        self.new_processes = []
        self.acceptance = lambda plan, batch: {"passed": True}
        class NoSuchProcess(Exception): pass
        self.no_process = NoSuchProcess
        def process(pid):
            p = self.processes.get(pid)
            if p is None or not p.alive: raise NoSuchProcess(pid)
            return p
        def owner(runtime, port, expected=None):
            candidates = [p for p in self.processes.values() if p.alive and p.listening]
            if len(candidates) != 1: raise RuntimeError("Expected exactly one service listener")
            p = candidates[0]
            record = {"pid": p.pid, "created": p.creation, "command": p.command, "cwd": p.working}
            if expected and expected != record: raise RuntimeError("Service ownership changed")
            return p, record
        def popen(command, **kwargs):
            p = FakeProcess(200 + len(self.new_processes), self.processes, command, kwargs["cwd"])
            self.processes[p.pid] = p
            self.new_processes.append(p)
            return p
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(publish, "owner", side_effect=owner))
        stack.enter_context(patch.object(publish, "empty", return_value={"queue_running": [], "queue_pending": []}))
        stack.enter_context(patch.object(publish, "check_sources"))
        stack.enter_context(patch.object(publish, "listeners", side_effect=lambda port: [p.pid for p in self.processes.values() if p.alive and p.listening]))
        stack.enter_context(patch.object(publish, "get", side_effect=lambda port, route: {"degraded": False, "modules": [{"ready": True}]} if route.endswith("status") else {"total": 1}))
        self.popen = stack.enter_context(patch.object(publish.subprocess, "Popen", side_effect=popen))
        stack.enter_context(patch.dict(sys.modules, {"psutil": types.SimpleNamespace(Process=process, NoSuchProcess=NoSuchProcess), "accept_current": types.SimpleNamespace(verify=lambda plan, batch: self.acceptance(plan, batch))}))
        stack.enter_context(redirect_stdout(io.StringIO()))

    def add_file(self, name, kind="json"):
        live = self.data / name
        base = self.stage / ("baseline_" + name)
        new = self.stage / ("new_" + name)
        if kind == "sqlite":
            for path, value in ((live, "old"), (base, "old"), (new, "new")):
                with closing(sqlite3.connect(path)) as con, con:
                    con.execute("create table data(value text)")
                    con.execute("insert into data values (?)", (value,))
        else:
            live.write_text("old " + name, encoding="utf-8")
            base.write_bytes(live.read_bytes())
            new.write_text("new " + name, encoding="utf-8")
        self.spec["files"].append({"runtime_relative": live.relative_to(self.runtime).as_posix(), "kind": kind, "stage_path": str(new), "baseline_path": str(base)})
        return live, base, new

    def prepare(self):
        publish.prepare(self.runtime, self.batch, self.spec)
        return publish.sha(self.batch / "plan.json")

    def test_prepare_rejects_database_drift_since_stage_baseline(self):
        live, _, _ = self.add_file("library.sqlite3", "sqlite")
        with closing(sqlite3.connect(live)) as con, con: con.execute("insert into data values ('user edit')")
        with self.assertRaisesRegex(RuntimeError, "changed since staging"):
            self.prepare()
        self.assertFalse((self.batch / "plan.json").exists())
        self.assertTrue(self.original.alive)

    def test_prepare_rejects_json_drift_since_stage_baseline(self):
        live, _, _ = self.add_file("data.json")
        live.write_bytes(b"new personal data since staging")
        with self.assertRaisesRegex(RuntimeError, "changed since staging"):
            self.prepare()
        self.assertEqual(live.read_bytes(), b"new personal data since staging")
        self.assertFalse((self.batch / "plan.json").exists())
        self.assertTrue(self.original.alive)

    def test_prepare_rejects_same_resolved_target_with_double_slash_alias(self):
        self.add_file("data.json")
        alias = dict(self.spec["files"][0])
        alias["runtime_relative"] = alias["runtime_relative"].replace("user_data/", "user_data//")
        self.spec["files"].append(alias)
        with self.assertRaisesRegex(RuntimeError, "Duplicate deployment target"):
            self.prepare()

    def test_prepare_rejects_target_traversal_without_mutating_original(self):
        live, _, _ = self.add_file("data.json")
        before = live.read_bytes()
        self.spec["files"][0]["runtime_relative"] = "ComfyUI/plugin/user_data/../../../outside.json"
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.prepare()
        self.assertEqual(live.read_bytes(), before)

    def test_changed_stage_is_rejected_before_stopping_service(self):
        live, _, new = self.add_file("data.json")
        reviewed = self.prepare()
        new.write_bytes(b"late stage modification")
        with self.assertRaisesRegex(RuntimeError, "Stage changed"):
            publish.apply(self.batch, reviewed)
        self.assertTrue(self.original.alive)
        self.assertEqual(live.read_text(encoding="utf-8"), "old data.json")
        self.assertFalse((self.batch / "release_receipt.json").exists())

    def test_live_database_drift_is_preserved_and_service_restarted(self):
        live, _, _ = self.add_file("library.sqlite3", "sqlite")
        reviewed = self.prepare()
        with closing(sqlite3.connect(live)) as con, con: con.execute("insert into data values ('late edit')")
        with self.assertRaisesRegex(RuntimeError, "Database drift"):
            publish.apply(self.batch, reviewed)
        with closing(sqlite3.connect(live)) as con:
            self.assertEqual(con.execute("select count(*) from data").fetchone()[0], 2)
        self.assertTrue(self.new_processes[-1].alive)
        receipt = publish.read(self.batch / "release_receipt.json")
        self.assertEqual(receipt["phase"], "rolled_back")
        self.assertFalse(receipt["applied"])

    def test_partial_install_failure_restores_entire_group(self):
        first, _, _ = self.add_file("data.json")
        second, _, failing_stage = self.add_file("pairs.json")
        reviewed = self.prepare()
        real_copy = publish.atomic_copy
        def fail_second(source, target):
            if source == failing_stage: raise OSError("injected second file failure")
            return real_copy(source, target)
        with patch.object(publish, "atomic_copy", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second file failure"):
                publish.apply(self.batch, reviewed)
        self.assertEqual(first.read_text(encoding="utf-8"), "old data.json")
        self.assertEqual(second.read_text(encoding="utf-8"), "old pairs.json")
        self.assertEqual(publish.read(self.batch / "release_receipt.json")["phase"], "rolled_back")
        self.assertTrue(self.new_processes[-1].alive)

    def test_wait_failure_after_exit_restarts_without_touching_data(self):
        live, _, _ = self.add_file("data.json")
        reviewed = self.prepare()
        self.original.wait_error_once = True
        with self.assertRaisesRegex(TimeoutError, "wait failure"):
            publish.apply(self.batch, reviewed)
        self.assertEqual(live.read_text(encoding="utf-8"), "old data.json")
        self.assertTrue(self.new_processes[-1].alive)
        self.assertEqual(publish.read(self.batch / "release_receipt.json")["phase"], "rolled_back")

    def test_acceptance_exception_stops_new_service_before_group_restore(self):
        live, _, _ = self.add_file("data.json")
        reviewed = self.prepare()
        def reject(plan, batch): raise RuntimeError("injected acceptance failure")
        self.acceptance = reject
        with self.assertRaisesRegex(RuntimeError, "acceptance failure"):
            publish.apply(self.batch, reviewed)
        self.assertEqual(live.read_text(encoding="utf-8"), "old data.json")
        self.assertFalse(self.new_processes[0].alive)
        self.assertTrue(self.new_processes[1].alive)
        self.assertEqual(publish.read(self.batch / "release_receipt.json")["phase"], "rolled_back")

    def test_failed_acceptance_result_cannot_be_marked_accepted(self):
        live, _, _ = self.add_file("data.json")
        reviewed = self.prepare()
        self.acceptance = lambda plan, batch: {"passed": False}
        with self.assertRaisesRegex(RuntimeError, "[Aa]cceptance"):
            publish.apply(self.batch, reviewed)
        self.assertEqual(live.read_text(encoding="utf-8"), "old data.json")
        self.assertEqual(publish.read(self.batch / "release_receipt.json")["phase"], "rolled_back")

    def test_unready_nonlistening_child_is_stopped_before_restore(self):
        live, _, _ = self.add_file("data.json")
        reviewed = self.prepare()
        make_process = self.popen.side_effect
        def start(command, **kwargs):
            child = make_process(command, **kwargs)
            if len(self.new_processes) == 1: child.listening = False
            return child
        self.popen.side_effect = start
        ticks = iter(range(0, 6000, 600))
        real_copy = publish.atomic_copy
        def checked_copy(source, target):
            if source.parent.name == "backup":
                self.assertFalse(self.new_processes[0].alive, "Unready child must exit before any restore write")
            return real_copy(source, target)
        with patch.object(publish.time, "monotonic", side_effect=lambda: next(ticks)), patch.object(publish.time, "sleep"), patch.object(publish, "atomic_copy", side_effect=checked_copy):
            with self.assertRaisesRegex(RuntimeError, "startup timed out"):
                publish.apply(self.batch, reviewed)
        self.assertEqual(live.read_text(encoding="utf-8"), "old data.json")
        self.assertFalse(self.new_processes[0].alive)
        self.assertTrue(self.new_processes[1].alive)
        self.assertEqual(publish.read(self.batch / "release_receipt.json")["phase"], "rolled_back")

    def test_original_still_alive_aborts_before_restore_or_restart(self):
        live, _, _ = self.add_file("data.json")
        reviewed = self.prepare()
        with patch.object(self.original, "terminate", side_effect=OSError("injected refusal")):
            with self.assertRaisesRegex(RuntimeError, "Original service remains alive"):
                publish.apply(self.batch, reviewed)
        self.assertTrue(self.original.alive)
        self.assertEqual(live.read_text(encoding="utf-8"), "old data.json")
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
