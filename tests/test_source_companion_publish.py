"""Sealed source companions share data rollback without overwriting other work."""
import json
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

import test_current_source_publish as fixtures

publish = fixtures.publish


class SourceCompanionTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.CurrentPublishFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.main = self.flow.root / "main"
        self.snapshot = self.main / "snapshot"
        self.snapshot.mkdir(parents=True)
        self.manifest = {"files": []}
        self.module_file = self.snapshot / "runtime/benchmark_reports/source_update_flow/publish_current.py"
        self.patch_file = patch.object(publish, "__file__", str(self.module_file))
        self.patch_file.start()
        self.addCleanup(self.patch_file.stop)

    def companion(self, relative, existed=True):
        target = self.flow.runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            target.write_text("old source", encoding="utf-8")
        source = self.snapshot / "runtime" / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("new source", encoding="utf-8")
        self.manifest["files"].append({"source": relative, "path": "runtime/" + relative,
                                       "kind": "file", "sha256": publish.sha(source)})
        path = self.snapshot / "manifest.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        spec = self.flow.spec
        spec["source_manifest"] = str(path)
        spec["source_manifest_sha256"] = publish.sha(path)
        spec.setdefault("approved_sources", {})[relative] = {
            "before_sha256": publish.sha(target) if existed else None,
            "after_sha256": publish.sha(source)}
        spec["files"].append({"runtime_relative": relative, "stage_path": str(source), "kind": "source"})
        return target, source

    def native_cache(self, relative="ComfyUI/plugin/user_data/cache/tag_search.v1.db"):
        target = self.flow.runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(target)) as connection, connection:
            connection.execute("CREATE TABLE search_meta(applied_seq integer,built_revision integer)")
            connection.execute("INSERT INTO search_meta VALUES(5,10)")
            connection.execute("CREATE TABLE tag_search(id integer primary key,description text)")
            connection.execute("INSERT INTO tag_search VALUES(1,'old Tag description')")
        baseline = self.flow.stage / "baseline_tag_search.v1.db"
        shutil.copy2(target, baseline)
        row = {"runtime_relative": relative, "baseline_path": str(baseline)}
        self.flow.spec.setdefault("native_cache_rollback", []).append(row)
        return target, baseline

    @staticmethod
    def update_cache(target):
        with closing(sqlite3.connect(target)) as connection, connection:
            # Native incremental sync updates applied_seq, not built_revision.
            connection.execute("UPDATE search_meta SET applied_seq=7")
            connection.execute("UPDATE tag_search SET description='new Tag description'")

    def test_source_requires_seal_and_explicit_scope(self):
        target, _ = self.companion("ComfyUI/plugin/module.py")
        self.flow.spec.pop("approved_sources")
        with self.assertRaisesRegex(RuntimeError, "explicit approval"):
            self.flow.prepare()
        self.assertEqual(target.read_text(), "old source")
        self.assertTrue(self.flow.original.alive)

    def test_foreign_manifest_is_rejected(self):
        self.companion("ComfyUI/plugin/module.py")
        other = self.flow.root / "manifest.json"
        other.write_bytes((self.snapshot / "manifest.json").read_bytes())
        self.flow.spec.update(source_manifest=str(other), source_manifest_sha256=publish.sha(other))
        with self.assertRaisesRegex(RuntimeError, "main-Git maintenance checkout"):
            self.flow.prepare()

    def test_live_source_drift_is_not_overwritten(self):
        target, _ = self.companion("ComfyUI/plugin/module.py")
        target.write_text("other maintainer", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "live source drift"):
            self.flow.prepare()
        self.assertEqual(target.read_text(), "other maintainer")
        self.assertTrue(self.flow.original.alive)

    def test_new_source_path_must_not_already_be_a_directory(self):
        target, _ = self.companion("ComfyUI/plugin/new.js", False)
        target.mkdir()
        with self.assertRaisesRegex(RuntimeError, "live source drift"):
            self.flow.prepare()
        self.assertTrue(target.is_dir())
        self.assertTrue(self.flow.original.alive)

    def test_changed_sealed_source_fails_before_service_stop(self):
        _, source = self.companion("ComfyUI/plugin/module.py")
        reviewed = self.flow.prepare()
        source.write_text("unreviewed", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "sealed file"):
            publish.apply(self.flow.batch, reviewed)
        self.assertTrue(self.flow.original.alive)

    def test_acceptance_failure_restores_data_code_and_absence(self):
        data, _, _ = self.flow.add_file("data.json")
        old, _ = self.companion("ComfyUI/plugin/module.py")
        added, _ = self.companion("ComfyUI/plugin/new.js", False)
        reviewed = self.flow.prepare()
        self.flow.acceptance = lambda *args: {"passed": False}
        with self.assertRaisesRegex(RuntimeError, "did not pass"):
            publish.apply(self.flow.batch, reviewed)
        self.assertEqual(data.read_text(), "old data.json")
        self.assertEqual(old.read_text(), "old source")
        self.assertFalse(added.exists())
        self.assertEqual(publish.read(self.flow.batch / "release_receipt.json")["phase"], "rolled_back")

    def test_success_installs_exact_sealed_companions(self):
        data, _, _ = self.flow.add_file("data.json")
        old, source = self.companion("ComfyUI/plugin/module.py")
        added, new_source = self.companion("ComfyUI/plugin/new.js", False)
        reviewed = self.flow.prepare()
        publish.apply(self.flow.batch, reviewed)
        self.assertEqual(data.read_text(), "new data.json")
        self.assertEqual(publish.sha(old), publish.sha(source))
        self.assertEqual(publish.sha(added), publish.sha(new_source))
        self.assertTrue(publish.read(self.flow.batch / "release_receipt.json")["passed"])

    def test_native_cache_tag_and_source_are_restored_as_one_failed_group(self):
        tag, _, _ = self.flow.add_file("tags.sqlite3", "sqlite")
        old, _ = self.companion("ComfyUI/plugin/module.py")
        added, _ = self.companion("ComfyUI/plugin/new.js", False)
        cache, baseline = self.native_cache()
        expected = publish.fingerprint(baseline)
        reviewed = self.flow.prepare()
        def reject(plan, batch):
            self.update_cache(cache)
            raise RuntimeError("reject after native cache sync")
        self.flow.acceptance = reject
        with self.assertRaisesRegex(RuntimeError, "after native cache sync"):
            publish.apply(self.flow.batch, reviewed)
        self.assertEqual(publish.fingerprint(cache), expected)
        with closing(sqlite3.connect(cache)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM search_meta").fetchone(), (5, 10))
            self.assertEqual(connection.execute("SELECT description FROM tag_search").fetchone()[0], "old Tag description")
        with closing(sqlite3.connect(tag)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM data").fetchone()[0], "old")
        self.assertEqual(old.read_text(), "old source")
        self.assertFalse(added.exists())
        self.assertFalse(self.flow.new_processes[0].alive)
        self.assertTrue(self.flow.new_processes[1].alive)
        self.assertEqual(publish.read(self.flow.batch / "release_receipt.json")["phase"], "rolled_back")

    def test_success_keeps_native_updated_cache_without_installing_baseline(self):
        self.flow.add_file("data.json")
        cache, baseline = self.native_cache()
        reviewed = self.flow.prepare()
        def succeed(plan, batch):
            self.update_cache(cache)
            return {"passed": True}
        self.flow.acceptance = succeed
        publish.apply(self.flow.batch, reviewed)
        self.assertNotEqual(publish.fingerprint(cache), publish.fingerprint(baseline))
        self.assertTrue(publish.read(self.flow.batch / "release_receipt.json")["passed"])

    def test_native_cache_backup_drift_fails_before_stopping_original_service(self):
        cache, _ = self.native_cache()
        reviewed = self.flow.prepare()
        row = publish.read(self.flow.batch / "plan.json")["native_cache_rollback"][0]
        self.update_cache(Path(row["backup_path"]))
        with self.assertRaisesRegex(RuntimeError, "cache rollback backup changed"):
            publish.apply(self.flow.batch, reviewed)
        self.assertTrue(self.flow.original.alive)
        self.flow.popen.assert_not_called()
        with closing(sqlite3.connect(cache)) as connection:
            self.assertEqual(connection.execute("SELECT applied_seq FROM search_meta").fetchone()[0], 5)

    def test_native_cache_drift_after_prepare_is_preserved_without_install(self):
        live, _, _ = self.flow.add_file("data.json")
        cache, _ = self.native_cache()
        reviewed = self.flow.prepare()
        self.update_cache(cache)
        with self.assertRaisesRegex(RuntimeError, "Native cache drift"):
            publish.apply(self.flow.batch, reviewed)
        self.assertEqual(live.read_text(), "old data.json")
        with closing(sqlite3.connect(cache)) as connection:
            self.assertEqual(connection.execute("SELECT applied_seq FROM search_meta").fetchone()[0], 7)
        self.assertTrue(self.flow.new_processes[-1].alive)

    def test_native_cache_requires_reviewed_consistent_baseline(self):
        cache, _ = self.native_cache()
        self.update_cache(cache)
        with self.assertRaisesRegex(RuntimeError, "cache changed since"):
            self.flow.prepare()
        self.assertTrue(self.flow.original.alive)

    def test_native_cache_outside_native_cache_directory_is_refused(self):
        self.native_cache("ComfyUI/plugin/user_data/not_a_cache.db")
        with self.assertRaisesRegex(RuntimeError, "existing native user-data cache"):
            self.flow.prepare()
        self.assertTrue(self.flow.original.alive)

    def test_duplicate_native_cache_alias_is_refused(self):
        self.native_cache()
        duplicate = dict(self.flow.spec["native_cache_rollback"][0])
        duplicate["runtime_relative"] = duplicate["runtime_relative"].replace("/cache/", "/cache//")
        self.flow.spec["native_cache_rollback"].append(duplicate)
        with self.assertRaisesRegex(RuntimeError, "Duplicate or overlapping"):
            self.flow.prepare()

    def test_native_cache_cannot_also_be_a_file_install_target(self):
        cache, baseline = self.native_cache()
        self.flow.spec["files"].append({"runtime_relative": cache.relative_to(self.flow.runtime).as_posix(),
            "kind": "sqlite", "stage_path": str(baseline), "baseline_path": str(baseline)})
        with self.assertRaisesRegex(RuntimeError, "Duplicate or overlapping"):
            self.flow.prepare()

    def test_native_cache_live_path_cannot_be_its_own_review_baseline(self):
        cache, _ = self.native_cache()
        self.flow.spec["native_cache_rollback"][0]["baseline_path"] = str(cache)
        with self.assertRaisesRegex(RuntimeError, "isolated database"):
            self.flow.prepare()

    def test_drifted_new_source_is_preserved_before_complete_rollback(self):
        data, _, _ = self.flow.add_file("data.json")
        added, _ = self.companion("ComfyUI/plugin/new.js", False)
        old, _ = self.companion("ComfyUI/plugin/module.py")
        reviewed = self.flow.prepare()

        def fail(*args):
            added.write_text("unexpected new source edit", encoding="utf-8")
            old.write_text("unexpected existing source edit", encoding="utf-8")
            raise RuntimeError("acceptance source drift")

        self.flow.acceptance = fail
        with self.assertRaisesRegex(RuntimeError, "acceptance source drift"):
            publish.apply(self.flow.batch, reviewed)
        self.assertEqual(data.read_text(), "old data.json")
        self.assertFalse(added.exists())
        self.assertEqual(old.read_text(), "old source")
        drift = self.flow.batch / "rollback_source_drift"
        texts = {p.read_text() for p in drift.iterdir() if not p.name.endswith(".receipt.json")}
        self.assertEqual(texts, {"unexpected new source edit", "unexpected existing source edit"})
        self.assertEqual(publish.read(self.flow.batch / "release_receipt.json")["phase"], "rolled_back")


if __name__ == "__main__":
    unittest.main()
