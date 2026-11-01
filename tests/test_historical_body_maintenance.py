"""Synthetic exact-field, ownership and semantic regressions for body adoption."""
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
    SPEC = importlib.util.spec_from_file_location("body_maintenance_tested", SOURCE / "stage_body_maintenance.py")
    body = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(body)
finally:
    sys.path.remove(str(SOURCE))
C = body.C


class HistoricalBodyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.web = self.root / "web"; self.web.mkdir()
        self.library = self.root / "metadata_stage.sqlite3"
        self.tags = self.root / "tags.sqlite3"
        self.cohorts = self.root / "cohorts.jsonl"
        self.candidates = self.root / "candidates.jsonl"
        self.ledger = self.root / "historical.jsonl"
        self.manual_file = self.root / "manual.json"
        self.strip = self.root / "approved.mjs"
        # Deliberately synthetic parser fixture; production receives the real,
        # separately hash-bound site module, never this simplified function.
        self.strip.write_text("export function stripNaiDefaultTags(s){const tail=', very aesthetic, masterpiece, no text';return s.endsWith(tail)?s.slice(0,-tail.length):s;}", encoding="utf-8")
        self.before = {"safe": "1girl, red hair, best quality, very aesthetic, masterpiece, no text",
                       "quality": "1girl, red hair, very aesthetic, masterpiece, no text",
                       "encoding": "1girl, synthetic\ufffdtoken, best quality",
                       "manual": "1girl, red hair, very aesthetic, masterpiece, no text",
                       "space": "1girl, red hair, best quality"}
        self.after = {"safe": "1girl, red hair, best quality", "quality": "1girl, red hair",
                      "encoding": "1girl, synthetic\u00a0token, best quality", "manual": "1girl, red hair",
                      "space": "1girl,red hair,best quality"}
        self.old = {}; self.current = {}; self.payloads = {}; self.decisions = {}
        T = C.native("semantic_taxonomy")
        for key, text in self.before.items():
            self.old[key] = {"id": key, "tags": text, "negative": "source exclusion", "characterPrompts": [] if key == "space" else [{"label": "char1", "prompt": "separate character segment"}],
                             "images": [], "original": {"seed": 0, "custom": None}}
            self.current[key] = {**copy.deepcopy(self.old[key]), "tags": self.after[key], "note": "source current note"}
            primary = "quality_detail" if key == "manual" else "appearance" if key != "encoding" else "task_template"
            subs = ["质量与分辨率"] if key == "manual" else ["头发与发型"] if key != "encoding" else ["人物综合场景"]
            decision = {"disposition": "classified", "primary_class": primary, "content_type": "template", "usage": "positive", "declared_usage": "positive",
                        "model_scope": "unknown", "themes": [], "manual_search_eligible": True, "random_pool_eligible": False,
                        "strict_model_pool_eligible": False, "semantic_review_status": "not_semantically_reviewed" if key == "space" else "codex_import",
                        "alternative_classes": [], "classification_uncertain": False, "subcategories": subs,
                        "count_markers": T.original_count_markers(text), "note_kind": None, "note": "", "taxonomy_version": "synthetic"}
            self.decisions[key] = decision
            p = {"id": "codex-" + key, "prompt": text, "alias": "Personal " + key, "description": "User description",
                 "notes": "User note", "favorite": True, "usage_count": 13, "last_used": "keep", "image": "personal.png", "_collection": {"notes": "keep"},
                 "_external_source": {"dataset": "book", "entry_id": key, "custom_preview": "keep.png"},
                 "_external_sources": [{"historic": n} for n in range(3)], "_classification": decision}
            if key == "safe":
                p["_external_sources"].append(C.variant("book", self.current[key], "r-current"))
            self.payloads[key] = p
        store = C.native("library_store").LibraryStore(self.library, create=True)
        try:
            store.initialize_from_document({"last_modified": "metadata-revision", "_source_to_canonical": {}, "_merge_history": [{"keep": True}],
                "categories": [{"id": "cat", "name": "Personal", "prompts": list(self.payloads.values()) + [{"id": "held-owner", "prompt": "untouched held body", "favorite": True}]}]})
        finally:
            store.close()
        with closing(sqlite3.connect(self.library)) as conn, conn:
            self.category = json.loads(conn.execute("SELECT payload FROM categories WHERE id='cat'").fetchone()[0])
            for key, p in self.payloads.items():
                p["_classification"]["binding"] = C.binding(self.category, p)
                conn.execute("UPDATE prompts SET payload=? WHERE id=?", (C.packed(p), p["id"]))
        with closing(sqlite3.connect(self.tags)) as conn, conn:
            conn.execute("CREATE TABLE tag_tags(t_uuid TEXT PRIMARY KEY,text TEXT)")
            conn.execute("INSERT INTO tag_tags VALUES ('t','1girl, red hair')")
        self.proofs = []; self.cohort_rows = []; self.history = []
        for key in self.before:
            source = "book:" + key; owner = {"store": "library", "target_id": "codex-" + key}
            self.history.append({"source": source, "dataset": "book", "entry_id": key, "before_raw": self.old[key], "after_raw": self.current[key],
                                 "old_raw_sha256": C.digest(self.old[key]), "new_raw_sha256": C.digest(self.current[key]), "new_release": "r-current"})
            if key == "space":
                continue
            comp = {"source": source, "dataset": "book", "before": self.before[key], "after": self.after[key],
                    "old_raw_sha256": C.digest(self.old[key]), "current_raw_sha256": C.digest(self.current[key])}
            self.proofs.append({"owner": owner, "before_body": self.before[key], "after_candidate_body": self.after[key],
                                "before_body_sha256": body.text_hash(self.before[key]), "after_candidate_body_sha256": body.text_hash(self.after[key]),
                                "old_component_sources": [comp], "eligible_other_source_main_conflicts": [], "held_other_source_main_conflicts": [], "ambiguous_provenance_bindings": [],
                                "current_bound_sources": [{"source": source, "dataset": "book", "entry_id": key, "main_tags": self.after[key],
                                    "main_sha256": body.text_hash(self.after[key]), "source_raw_sha256": C.digest(self.current[key]), "held": False}]})
            cohort = body.SAFE if key == "safe" else body.QUALITY if key == "quality" else "requires_explicit_manual_review"
            self.cohort_rows.append({"owner": owner, "cohort": cohort, "before_body_sha256": body.text_hash(self.before[key]),
                                     "after_body_sha256": body.text_hash(self.after[key])})
        manual_rows = []
        for key in ("encoding", "manual"):
            proposed = copy.deepcopy(self.decisions[key]); proposed.pop("binding", None)
            if key == "manual":
                proposed.update(primary_class="appearance", subcategories=["头发与发型"])
            manual_rows.append({"owner": {"store": "library", "target_id": "codex-" + key},
                                "recommendation": body.MANUAL_CHANGE if key == "manual" else body.MANUAL_KEEP,
                                "before_body": self.before[key], "after_candidate_body": self.after[key],
                                "before_body_sha256": body.text_hash(self.before[key]), "after_body_sha256": body.text_hash(self.after[key]),
                                "classification_before": copy.deepcopy(self.decisions[key]), "proposed_classification_without_binding": proposed,
                                "native_signal_nodes_removed": ["quality.quality"] if key == "manual" else [],
                                "agent_fulltext_manual_review_performed": True, "human_user_confirmation": False})
        manual_rows.append({"owner": {"store": "library", "target_id": "held-owner"}, "recommendation": "hold_current_body_syntax_ambiguity"})
        self.manual_doc = {"rows": manual_rows, "input_files": {}}
        self.review = {"schema": body.SCHEMA, "approved": True, "approved_cohorts": {body.SAFE: 1, body.QUALITY: 1},
                       "approved_manual_owners": ["codex-encoding", "codex-manual"], "held_owners": ["held-owner"],
                       "additional_whitespace_sources": [{"source": "book:space", "owner": {"store": "library", "target_id": "codex-space"},
                                                          "expected_removed_spaces": 2, "owner_method": "native_physical_source_id", "review_status": "not_semantically_reviewed"}],
                       "expected": {"owners": 5, "quality_node_losses": 1, "manual_classification_updates": 1}}
        self.review_path = self.root / "approval.json"
        self.args = argparse.Namespace(review=self.review_path, library=self.library, tags=self.tags, web=self.web, cohorts=self.cohorts,
            candidates=self.candidates, source_ledger=self.ledger, manual_review=self.manual_file, strip_module=self.strip,
            output=self.root / "body-stage", node=None, review_sha256=None)
        self.write_inputs()

    def write_inputs(self):
        C.save(self.web / "book.json", {"entries": list(self.current.values())})
        C.save(self.web / "codexes.json", [{"id": "book", "title": "Synthetic Book"}])
        C.save(self.web / "current.json", {"release": "r-current"})
        C.save(self.web / "manifest.json", {"release": "r-current", "files": {n: {"size": (self.web / n).stat().st_size, "sha256": C.file_hash(self.web / n)} for n in ("book.json", "codexes.json")}})
        for path, rows in ((self.cohorts, self.cohort_rows), (self.candidates, self.proofs), (self.ledger, self.history)):
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        C.save(self.manual_file, self.manual_doc)
        self.review["inputs"] = {str(p): C.file_hash(p) for p in (self.library, self.tags, self.cohorts, self.candidates, self.ledger, self.manual_file, self.strip,
                                                                 self.web / "manifest.json", self.web / "codexes.json", self.web / "current.json")}
        C.save(self.review_path, self.review)

    def run_stage(self):
        self.write_inputs()
        return body.stage(self.args)

    def payload(self, path, key):
        with closing(C.connect(path, True)) as conn:
            return json.loads(conn.execute("SELECT payload FROM prompts WHERE id=?", (key,)).fetchone()[0])

    def test_exact_main_field_adoption_preserves_ids_personal_fields_and_context(self):
        hashes = {str(p): C.file_hash(p) for p in (self.library, self.tags)}
        result = self.run_stage()
        self.assertEqual(result["updated_library"], 5)
        self.assertEqual(result["declared_quality_loss_cohort"], 1)
        self.assertEqual(result["manual_classification_updates"], 1)
        self.assertEqual(result["additional_whitespace_owners"], 1)
        self.assertEqual(hashes, {str(p): C.file_hash(p) for p in (self.library, self.tags)})
        for key in self.before:
            after = self.payload(self.args.output / "library.sqlite3", "codex-" + key)
            self.assertEqual(after["prompt"], self.after[key])
            for field in ("alias", "description", "notes", "favorite", "usage_count", "last_used", "image", "_collection"):
                self.assertEqual(after[field], self.payloads[key][field])
            self.assertEqual(after["_external_sources"][:len(self.payloads[key]["_external_sources"])], self.payloads[key]["_external_sources"])
            self.assertTrue(any(v.get("raw_entry") == self.current[key] for v in after["_external_sources"]))
            self.assertEqual(after["_external_source"]["custom_preview"], "keep.png")
        self.assertEqual(self.payload(self.args.output / "library.sqlite3", "held-owner"), self.payload(self.library, "held-owner"))
        self.assertEqual(self.payload(self.args.output / "library.sqlite3", "codex-space")["_classification"]["semantic_review_status"], "not_semantically_reviewed")
        self.assertEqual(self.payload(self.args.output / "library.sqlite3", "codex-manual")["_classification"]["primary_class"], "appearance")
        self.assertEqual(result["source_snapshots_appended"], 4)  # metadata-stage current raw for safe was reused.
        with closing(C.connect(self.args.output / "library.sqlite3", True)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM library_journal").fetchone()[0], 5)
        self.assertFalse((self.args.output / "tags.sqlite3").exists())

    def test_actual_body_must_remain_exact_old_component(self):
        with closing(sqlite3.connect(self.library)) as conn, conn:
            p = self.payload(self.library, "codex-safe"); p["prompt"] += " user edit"
            conn.execute("UPDATE prompts SET payload=? WHERE id='codex-safe'", (C.packed(p),))
        with self.assertRaisesRegex(ValueError, "actual maintained body"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_current_body_cannot_concatenate_character_segments(self):
        self.proofs[0]["after_candidate_body"] += "\nchar1: separate character segment"
        with self.assertRaisesRegex(ValueError, "hashes disagree|same historical/current raw main"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_native_nonquality_and_count_guards_reject_semantic_changes(self):
        p = self.payloads["safe"]
        with self.assertRaisesRegex(ValueError, "non-quality|invariant"):
            body.classify_guard(self.category, p, "1girl, red hair, best quality, sword", body.SAFE)
        with self.assertRaisesRegex(ValueError, "person-count"):
            body.classify_guard(self.category, p, "2girls, red hair, best quality", body.SAFE)

    def test_quality_primary_cannot_use_nonquality_quality_loss_approval(self):
        p = self.payloads["manual"]
        with self.assertRaisesRegex(ValueError, "non-quality-primary"):
            body.classify_guard(self.category, p, self.after["manual"], body.QUALITY)

    def test_whitespace_status_must_be_explicit_and_must_not_promote_review(self):
        self.review["additional_whitespace_sources"][0]["review_status"] = "codex_import"
        with self.assertRaisesRegex(ValueError, "original review status"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_whitespace_preserves_both_explicit_non_codex_statuses(self):
        for status in ("source_import_with_current_rules", "not_semantically_reviewed"):
            with self.subTest(status=status):
                p = copy.deepcopy(self.payloads["space"])
                p["_classification"]["semantic_review_status"] = status
                decision, _ = body.classify_guard(self.category, p, self.after["space"], body.SPACE, additional_status=status)
                self.assertEqual(decision["semantic_review_status"], status)
                self.assertEqual(decision, p["_classification"])

    def test_manual_decision_cannot_invent_human_confirmation_or_pool_eligibility(self):
        self.manual_doc["rows"][1]["proposed_classification_without_binding"]["semantic_review_status"] = "user_confirmed"
        with self.assertRaisesRegex(ValueError, "promoted eligibility"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_unapproved_manual_and_held_owners_are_rejected(self):
        self.review["approved_manual_owners"].append("held-owner")
        with self.assertRaisesRegex(ValueError, "unique evidence|held manual"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_omitted_current_native_binding_is_detected_without_body_matching(self):
        extra = {"id": "other-source", "tags": self.after["safe"]}
        self.current["other-source"] = extra
        with closing(sqlite3.connect(self.library)) as conn, conn:
            conn.execute("UPDATE library_meta SET value=? WHERE key='_source_to_canonical'", (C.packed({"codex-other-source": {"canonical_id": "codex-safe", "source_category_id": "cat"}}),))
        with self.assertRaisesRegex(ValueError, "ownership evidence is incomplete"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_other_current_source_conflict_is_rejected(self):
        self.current["conflict"] = {"id": "conflict", "tags": "different B"}
        with closing(sqlite3.connect(self.library)) as conn, conn:
            conn.execute("UPDATE library_meta SET value=? WHERE key='_source_to_canonical'", (C.packed({"codex-conflict": {"canonical_id": "codex-safe", "source_category_id": "cat"}}),))
        with self.assertRaisesRegex(ValueError, "different main body"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_malformed_or_missing_native_alias_does_not_fall_back_to_physical(self):
        for mapping in ("bad-string", {"canonical_id": "missing", "source_category_id": "cat"}):
            with self.subTest(mapping_type=type(mapping).__name__):
                with closing(sqlite3.connect(self.library)) as conn, conn:
                    conn.execute("UPDATE library_meta SET value=? WHERE key='_source_to_canonical'", (C.packed({"codex-safe": mapping}),))
                with self.assertRaisesRegex(ValueError, "native canonical owner|invalid baseline native"):
                    self.run_stage()
                self.assertFalse(self.args.output.exists())

    def test_duplicate_owner_rows_cannot_be_silently_overwritten(self):
        for name in ("cohort_rows", "proofs"):
            with self.subTest(evidence=name):
                rows = getattr(self, name)
                rows.append(copy.deepcopy(rows[0]))
                with self.assertRaisesRegex(ValueError, "duplicate owner"):
                    self.run_stage()
                rows.pop()
                self.assertFalse(self.args.output.exists())

    def test_approved_strip_module_drift_is_rejected_before_execution(self):
        self.write_inputs()
        self.strip.write_text("throw new Error('changed');", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "input drift"):
            body.stage(self.args)
        self.assertFalse(self.args.output.exists())

    def test_validator_rejects_unapproved_personal_or_held_row_mutation(self):
        export = C.export_document
        def corrupt(conn, path):
            conn.execute("UPDATE prompts SET payload=? WHERE id='held-owner'", (C.packed({"id": "held-owner", "prompt": "bad"}),))
            conn.commit(); return export(conn, path)
        with patch.object(C, "export_document", side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, "unapproved body row"):
                self.run_stage()
        self.assertFalse((self.args.output / "stage_validation.json").exists())


if __name__ == "__main__":
    unittest.main()
