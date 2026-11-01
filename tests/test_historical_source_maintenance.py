"""Synthetic historical maintenance regressions; no real prompts or live service."""
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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "snapshot/runtime/benchmark_reports/source_update_flow"
sys.path.insert(0, str(SOURCE))
try:
    SPEC = importlib.util.spec_from_file_location("historical_maintenance_tested", SOURCE / "stage_maintenance.py")
    maintenance = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(maintenance)
finally:
    sys.path.remove(str(SOURCE))
C = maintenance.common


class HistoricalMaintenanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.web = self.root / "web"
        self.web.mkdir()
        self.library = self.root / "fresh.sqlite3"
        self.audited = self.root / "audited.sqlite3"
        self.tags = self.root / "readonly_tags.sqlite3"
        self.ledger = self.root / "history.jsonl"
        self.review_path = self.root / "review.json"
        self.old = [{"id": "item-" + str(i), "tags": "Source text " + str(i), "note": "old source note",
                     "images": [{"path": "v.png", "rawTag": "Old Case", "negative": "old exclusion"}]} for i in (1, 2)]
        self.current = copy.deepcopy(self.old)
        for entry in self.current:
            entry.update(note="new source note", perImagePrompts=True,
                         original={"seed": 0, "sampler": "original", "unknown": None})
            entry["images"][0].update(rawTag="1.2::New Case::", negative="new exclusion",
                characterPrompts=[{"label": "first", "prompt": "Keep WEIGHT 0::zero::"}, {"label": "second", "prompt": "Keep_Order"}])
        self.catalog = [{"id": "book", "title": "Synthetic Source Book"}, {"id": "unselected", "title": "Unrelated Book"}]
        C.save(self.web / "book.json", {"entries": self.current})
        C.save(self.web / "unselected.json", {"entries": [{"id": "other", "tags": "unrelated"}]})
        C.save(self.web / "codexes.json", self.catalog)
        C.save(self.web / "current.json", {"release": "r-current"})
        self.manifest()
        payload = {"id": "canonical", "alias": "My alias", "prompt": "My maintained BODY", "description": "My personal notes",
                   "image": "personal.png", "favorite": True, "usage_count": 41, "last_used": "kept", "template": False,
                   "_collection": {"notes": "personal collection note"},
                   "_external_source": {"dataset": "book", "entry_id": "item-1", "note": "old source note", "custom_preview": "retain.png"},
                   "_external_sources": [{"historical": i} for i in range(12)] + [{"dataset": "book", "entry_id": "item-2", "note": "old source note"}],
                   "_classification": {"disposition": "classified", "primary_class": "task_template", "manual_search_eligible": True,
                                       "random_pool_eligible": False, "strict_model_pool_eligible": False, "semantic_review_status": "user_confirmed"}}
        aliases = {"codex-item-" + str(i): {"canonical_id": "canonical", "source_category_id": "legacy-cat"} for i in (1, 2)}
        doc = {"last_modified": "base", "_source_to_canonical": aliases, "_merge_history": [{"at": "keep", "source_ids": ["old"]}],
               "settings": {"private_order": [2, 1]}, "categories": [
                   {"id": "cat", "name": "Personal category", "prompts": [payload, {"id": "unrelated", "prompt": "Unrelated text", "favorite": True}]},
                   {"id": "legacy-cat", "name": "Legacy category", "prompts": [{"id": "codex-item-1", "prompt": "legacy shadow must not change"}]}]}
        store = C.native("library_store").LibraryStore(self.library, create=True)
        try:
            store.initialize_from_document(doc)
        finally:
            store.close()
        with closing(sqlite3.connect(self.library)) as conn, conn:
            category = json.loads(conn.execute("SELECT payload FROM categories WHERE id='cat'").fetchone()[0])
            payload["_classification"]["binding"] = C.binding(category, payload)
            conn.execute("UPDATE prompts SET payload=? WHERE id='canonical'", (C.packed(payload),))
            conn.execute("INSERT OR REPLACE INTO library_meta VALUES ('__last_backup_at__','1.0')")
        self.original_payload = copy.deepcopy(payload)
        C.backup(self.library, self.audited)
        with closing(sqlite3.connect(self.tags)) as conn, conn:
            conn.execute("CREATE TABLE tag_tags(t_uuid TEXT PRIMARY KEY,text TEXT)")
            conn.execute("INSERT INTO tag_tags VALUES ('tag-1','My maintained BODY')")
        self.history = [{"source": "book:" + new["id"], "dataset": "book", "entry_id": new["id"], "before_raw": old, "after_raw": new,
                         "old_raw_sha256": C.digest(old), "new_raw_sha256": C.digest(new), "old_file_sha256": "0" * 64,
                         "new_file_sha256": C.file_hash(self.web / "book.json"), "old_release": "r-old", "new_release": "r-current",
                         "changed_fields": ["note", "images", "original", "perImagePrompts"],
                         "oct31_registry": {"source": "book:" + new["id"], "disposition": "library_existing", "target_id": "canonical"}}
                        for old, new in zip(self.old, self.current)]
        self.review = {"schema": maintenance.SCHEMA, "counts": {"priority_union_sources": 2, "priority_unique_targets": 1},
                       "priority_sources": [{"source": "book:" + entry["id"], "dataset": "book", "entry_id": entry["id"], "source_hold": False,
                                             "owner": {"store": "library", "target_id": "canonical"}, "owner_method": "native_one_hop_source_map",
                                             "source_variant_status": "stale_or_incomplete_source_variant", "current_entry_sha256": C.digest(entry),
                                             "priority_reasons": ["source_note", "per_image_prompt_parameters"]} for entry in self.current],
                       "visibility_only_note_sources": []}
        self.args = argparse.Namespace(review=self.review_path, web=self.web, library=self.library, audited_library=self.audited,
                                       tags=self.tags, source_ledger=self.ledger, output=self.root / "stage", review_sha256=None)
        self.write_review()

    def manifest(self):
        files = {name: {"size": (self.web / name).stat().st_size, "sha256": C.file_hash(self.web / name)}
                 for name in ("book.json", "unselected.json", "codexes.json")}
        C.save(self.web / "manifest.json", {"release": "r-current", "files": files})

    def write_review(self):
        self.ledger.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.history), encoding="utf-8")
        self.review["inputs"] = {str(p): C.file_hash(p) for p in (self.audited, self.tags, self.ledger)}
        C.save(self.review_path, self.review)

    def read_payload(self, path, identity="canonical"):
        with closing(C.connect(path, True)) as conn:
            return json.loads(conn.execute("SELECT payload FROM prompts WHERE id=?", (identity,)).fetchone()[0])

    def change_baseline(self, change):
        with closing(sqlite3.connect(self.library)) as conn, conn:
            change(conn)
        self.audited.unlink()
        C.backup(self.library, self.audited)
        self.write_review()

    def run_stage(self):
        self.write_review()
        return maintenance.stage(self.args)

    def test_preserves_all_user_fields_shared_owner_history_and_raw_variants(self):
        initial = {str(p): C.file_hash(p) for p in (self.library, self.audited, self.tags)}
        result = self.run_stage()
        self.assertEqual(result["reviewed_sources"], 2)
        self.assertEqual(result["updated_library"], 1)
        self.assertEqual(initial, {str(p): C.file_hash(p) for p in (self.library, self.audited, self.tags)})
        after = self.read_payload(self.args.output / "library.sqlite3")
        for name in ("prompt", "alias", "description", "image", "favorite", "usage_count", "last_used", "_collection", "template"):
            self.assertEqual(after[name], self.original_payload[name])
        n = len(self.original_payload["_external_sources"])
        self.assertEqual(after["_external_sources"][:n], self.original_payload["_external_sources"])
        self.assertIn(self.original_payload["_external_source"], after["_external_sources"])
        self.assertEqual(after["_external_source"]["entry_id"], "item-1")
        self.assertEqual(after["_external_source"]["custom_preview"], "retain.png")
        self.assertEqual(after["_external_source"]["note"], "new source note")
        self.assertEqual(after["_external_sources"][-1]["raw_entry"], self.current[1])
        self.assertEqual(after["_external_sources"][-1]["dataset_title"], "Synthetic Source Book")
        self.assertEqual(self.read_payload(self.args.output / "library.sqlite3", "codex-item-1"), self.read_payload(self.library, "codex-item-1"))
        self.assertFalse((self.args.output / "tags.sqlite3").exists())
        self.assertFalse((self.args.output / "dictionary.sqlite3").exists())
        with closing(C.connect(self.args.output / "library.sqlite3", True)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM library_journal").fetchone()[0], 1)
        data = C.read(self.args.output / "data.json")
        self.assertEqual(data["_source_to_canonical"], {"codex-item-" + str(i): {"canonical_id": "canonical", "source_category_id": "legacy-cat"} for i in (1, 2)})

    def test_existing_invalid_classification_is_not_repaired_or_approved(self):
        def invalidate(conn):
            payload = json.loads(conn.execute("SELECT payload FROM prompts WHERE id='canonical'").fetchone()[0])
            payload["_classification"]["binding"] = "stale-binding"
            conn.execute("UPDATE prompts SET payload=? WHERE id='canonical'", (C.packed(payload),))
        self.change_baseline(invalidate)
        self.run_stage()
        after = self.read_payload(self.args.output / "library.sqlite3")
        self.assertEqual(after["_classification"]["binding"], "stale-binding")
        decision = C.native("semantic_projection").decision_for({"decisions": {}}, {"id": "cat", "name": "Personal category"}, after)
        self.assertFalse(decision["manual_search_eligible"])

    def test_fresh_startup_timestamp_drift_allowed_but_preserved(self):
        with closing(sqlite3.connect(self.library)) as conn, conn:
            conn.execute("UPDATE library_meta SET value='2.0' WHERE key='__last_backup_at__'")
        self.run_stage()
        with closing(C.connect(self.args.output / "library.sqlite3", True)) as conn:
            self.assertEqual(conn.execute("SELECT value FROM library_meta WHERE key='__last_backup_at__'").fetchone()[0], "2.0")

    def test_user_edit_since_audit_fails_before_output_creation(self):
        with closing(sqlite3.connect(self.library)) as conn, conn:
            payload = self.read_payload(self.library)
            payload["description"] = "new user note after review"
            conn.execute("UPDATE prompts SET payload=? WHERE id='canonical'", (C.packed(payload),))
        with self.assertRaisesRegex(ValueError, "rows changed since review"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_unselected_dataset_manifest_is_still_verified(self):
        (self.web / "unselected.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_historical_raw_hash_must_match_bound_ledger_content(self):
        self.history[0]["before_raw"]["note"] = "tampered historical note"
        with self.assertRaisesRegex(ValueError, "historical raw source hash"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_native_canonical_owner_overrides_existing_legacy_physical_row(self):
        self.review["priority_sources"][0]["owner"]["target_id"] = "codex-item-1"
        self.review["counts"]["priority_unique_targets"] = 2
        with self.assertRaisesRegex(ValueError, "native canonical owner"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_native_ownership_is_exactly_one_hop_not_recursive(self):
        def add_second_hop(conn):
            mapping = json.loads(conn.execute("SELECT value FROM library_meta WHERE key='_source_to_canonical'").fetchone()[0])
            mapping['canonical'] = {'canonical_id': 'unrelated', 'source_category_id': 'cat'}
            conn.execute("UPDATE library_meta SET value=? WHERE key='_source_to_canonical'", (C.packed(mapping),))
        self.change_baseline(add_second_hop)
        self.run_stage()
        doc = C.read(self.args.output / "data.json")
        merge = C.native("prompt_merge")
        self.assertEqual(merge.merged_source(doc, 'codex-item-1')[1]['id'], 'canonical')
        self.assertEqual(merge.merged_source(doc, 'canonical')[1]['id'], 'unrelated')
        self.assertEqual(self.read_payload(self.args.output / "library.sqlite3", "unrelated"), self.read_payload(self.library, "unrelated"))

    def remove_native_aliases_and_shadow(self, conn):
        conn.execute("UPDATE library_meta SET value='{}' WHERE key='_source_to_canonical'")
        conn.execute("DELETE FROM prompts WHERE id='codex-item-1'")
        conn.execute("UPDATE category_orders SET order_json='[]' WHERE category_id='legacy-cat'")

    def test_explicit_and_bound_historical_registry_witnesses_work_without_aliases(self):
        self.change_baseline(self.remove_native_aliases_and_shadow)
        self.review["priority_sources"][0]["owner_method"] = "unique_actual_explicit_source_provenance"
        self.review["priority_sources"][1]["owner_method"] = "accepted_source_registry_lineage"
        self.history[1]["accepted_source_registry"] = self.history[1].pop("oct31_registry")
        self.run_stage()
        registry = C.read(self.args.output / "source_registry.json")
        self.assertEqual([r["witness"] for r in registry], ["actual_explicit_provenance", "bound_accepted_source_registry"])
        self.assertEqual(C.read(self.args.output / "data.json")["_source_to_canonical"], {})

    def test_historical_registry_target_cannot_be_forged(self):
        self.change_baseline(self.remove_native_aliases_and_shadow)
        for row in self.review["priority_sources"]:
            row["owner_method"] = "accepted_1031_source_registry_lineage"
        self.history[0]["oct31_registry"]["target_id"] = "unrelated"
        with self.assertRaisesRegex(ValueError, "registry witness"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_source_hold_and_ui_only_current_note_are_not_data_repairs(self):
        for field, value, message in (("source_hold", True, "source hold"), ("source_variant_status", "current_hash_partial_source_payload", "already-current")):
            with self.subTest(field=field):
                original = self.review["priority_sources"][0][field]
                self.review["priority_sources"][0][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    self.run_stage()
                self.review["priority_sources"][0][field] = original
        self.assertFalse(self.args.output.exists())

    def test_already_current_full_raw_snapshot_is_not_appended_again(self):
        def already_current(conn):
            payload = self.read_payload(self.library)
            payload["_external_sources"].append(C.variant("book", self.current[0], "r-current"))
            conn.execute("UPDATE prompts SET payload=? WHERE id='canonical'", (C.packed(payload),))
        self.change_baseline(already_current)
        with self.assertRaisesRegex(ValueError, "snapshot is already current"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_validator_rejects_unrelated_row_mutation(self):
        export = C.export_document
        def corrupt(conn, path):
            conn.execute("UPDATE prompts SET payload=? WHERE id='unrelated'", (C.packed({"id": "unrelated", "prompt": "bad rewrite"}),))
            conn.commit()
            return export(conn, path)
        with patch.object(C, "export_document", side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, "unreviewed prompt row"):
                self.run_stage()
        self.assertFalse((self.args.output / "stage_validation.json").exists())

    def test_validator_rejects_missing_revision_refresh(self):
        export = C.export_document
        def stale_revision(conn, path):
            conn.execute("UPDATE library_meta SET value=? WHERE key='last_modified'", (C.packed('base'),))
            conn.commit()
            return export(conn, path)
        with patch.object(C, "export_document", side_effect=stale_revision):
            with self.assertRaisesRegex(ValueError, "library revision"):
                self.run_stage()
        self.assertFalse((self.args.output / "stage_validation.json").exists())

    def test_duplicate_source_and_raw_tag_target_are_rejected(self):
        self.review["priority_sources"][1] = copy.deepcopy(self.review["priority_sources"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.run_stage()
        self.review["priority_sources"][1] = copy.deepcopy(self.review["priority_sources"][0])
        self.review["priority_sources"][1]["entry_id"] = "item-2"
        self.review["priority_sources"][1]["source"] = "book:item-2"
        self.review["priority_sources"][1]["owner"]["store"] = "tags"
        with self.assertRaisesRegex(ValueError, "library only"):
            self.run_stage()


if __name__ == "__main__":
    unittest.main()
