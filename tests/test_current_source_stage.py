"""Offline staging safety checks using tiny native SQLite fixtures."""
import argparse
import copy
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stage_current", ROOT / "snapshot/runtime/benchmark_reports/source_update_flow/stage_current.py")
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


class CurrentStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = {"id": "enter-1", "tags": "A, B", "rating": "safe"}
        self.new = {**self.old, "rating": "nsfw"}
        self.added = {"id": "enter-2", "tags": "Exact Case", "characterPrompts": [{"label": "girl", "prompt": "Blue Eyes"}], "negative": "low quality", "original": "original.png"}
        for directory, release, entries in [("old", "old-r", [self.old]), ("web", "new-r", [self.new, self.added])]:
            path = self.root / directory; path.mkdir()
            stage.save(path / "enter_codex.json", {"entries": entries})
            stage.save(path / "manifest.json", {"files": {"enter_codex.json": {"size": (path / "enter_codex.json").stat().st_size, "sha256": stage.file_hash(path / "enter_codex.json")}}})
            stage.save(path / "current.json", {"release": release})
        original = {"id": "local", "prompt": "USER EDIT", "favorite": True, "usage_count": 41, "description": "personal", "_collection": {"notes": "mine"}, "_external_source": {"dataset": "different", "entry_id": "keep", "release": "old"}, "_external_sources": [{"historical": i} for i in range(12)]}
        store = stage.native("library_store").LibraryStore(self.root / "library.sqlite3", create=True)
        try: store.initialize_from_document({"last_modified": "base", "categories": [{"id": "cat", "name": "existing", "prompts": [original]}]})
        finally: store.close()
        with closing(sqlite3.connect(self.root / "tags.sqlite3")) as db:
            db.executescript("CREATE TABLE tag_tags(t_uuid TEXT PRIMARY KEY,text TEXT); CREATE TABLE workbench_tag_meta(tag_uuid TEXT PRIMARY KEY,data TEXT); INSERT INTO tag_tags VALUES ('t','A,B');")
            db.executescript("CREATE TABLE workbench_tag_revision(id INTEGER PRIMARY KEY,value INTEGER); INSERT INTO workbench_tag_revision VALUES(1,10); CREATE TRIGGER meta_revision AFTER UPDATE ON workbench_tag_meta BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;")
            db.commit()
        with closing(sqlite3.connect(self.root / "dictionary.sqlite3")) as db:
            db.executescript("CREATE TABLE danbooru_tag(id_index INTEGER PRIMARY KEY AUTOINCREMENT,tag TEXT,color_id INTEGER,translate TEXT,hot INTEGER,aliases INTEGER); INSERT INTO danbooru_tag VALUES (1,'preserve',3,'personal',88,4);")
            db.commit()
        self.review = {"schema": 1, "dataset": "enter_codex", "current_release": "new-r", "baseline_release": "old-r",
            "expected": {"added_sources": 1, "changed_sources": 1, "new_resources": 1},
            "existing": [{"entry_id": "enter-1", "disposition": "update", "store": "library", "target_id": "local", "match": "explicit"}],
            "new_groups": [{"entry_ids": ["enter-2"], "target_id": "codex-enter-2", "category_id": "cat"}],
            "dictionary_insertions": [{"tag": "new_word", "translation": "新词", "source": "a"}]}
        self.args = argparse.Namespace(web=self.root / "web", baseline_web=self.root / "old", library=self.root / "library.sqlite3", tags=self.root / "tags.sqlite3", dictionary=self.root / "dictionary.sqlite3", review=self.root / "review.json", output=self.root / "stage", image_receipts=None, image_dir=None)

    def run_stage(self):
        stage.save(self.args.review, self.review)
        return stage.stage(self.args)

    def test_stage_preserves_user_fields_history_and_input_bytes(self):
        inputs = [self.args.library, self.args.tags, self.args.dictionary]
        hashes = [stage.file_hash(p) for p in inputs]
        result = self.run_stage()
        self.assertTrue(result["passed"])
        self.assertEqual(hashes, [stage.file_hash(p) for p in inputs])
        data = stage.read(self.args.output / "data.json")
        prompts = {p["id"]: p for c in data["categories"] for p in c["prompts"]}
        local = prompts["local"]
        self.assertEqual(local["prompt"], "USER EDIT")
        self.assertTrue(local["favorite"])
        self.assertEqual(local["_collection"], {"notes": "mine"})
        self.assertEqual(local["_external_source"], {"dataset": "different", "entry_id": "keep", "release": "old"})
        self.assertEqual(local["_external_sources"][:12], [{"historical": i} for i in range(12)])
        self.assertEqual(len(local["_external_sources"]), 14)
        self.assertEqual(local["_external_sources"][-2]["raw_entry"], self.old)
        self.assertEqual(local["_external_sources"][-1]["raw_entry"], self.new)
        self.assertEqual(prompts["codex-enter-2"]["prompt"], "Exact Case\ngirl: Blue Eyes")
        self.assertFalse(prompts["codex-enter-2"]["_classification"]["random_pool_eligible"])

    def test_case_or_character_changes_cannot_share_new_resource(self):
        other = copy.deepcopy(self.added); other["id"] = "enter-3"; other["tags"] = "exact case"
        value = stage.read(self.args.web / "enter_codex.json"); value["entries"].append(other)
        stage.save(self.args.web / "enter_codex.json", value)
        path = self.args.web / "enter_codex.json"
        stage.save(self.args.web / "manifest.json", {"files": {"enter_codex.json": {"size": path.stat().st_size, "sha256": stage.file_hash(path)}}})
        self.review["expected"]["added_sources"] = 2
        self.review["new_groups"][0]["entry_ids"].append("enter-3")
        with self.assertRaisesRegex(ValueError, "different complete positive"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_modified_source_manifest_fails_before_output_creation(self):
        (self.args.web / "enter_codex.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            self.run_stage()
        self.assertFalse(self.args.output.exists())

    def test_source_edit_outside_reviewed_rating_is_rejected(self):
        value = stage.read(self.args.web / "enter_codex.json"); value["entries"][0]["tags"] = "new body"
        stage.save(self.args.web / "enter_codex.json", value); path = self.args.web / "enter_codex.json"
        stage.save(self.args.web / "manifest.json", {"files": {"enter_codex.json": {"size": path.stat().st_size, "sha256": stage.file_hash(path)}}})
        with self.assertRaisesRegex(ValueError, "outside metadata review"):
            self.run_stage()

    def test_existing_dictionary_cannot_be_overwritten(self):
        self.review["dictionary_insertions"][0]["tag"] = "preserve"
        with self.assertRaisesRegex(ValueError, "override existing tag"):
            self.run_stage()

    def test_native_tag_revision_trigger_and_personal_metadata_are_preserved(self):
        metadata = {"notes": "personal", "favorite": True, "external_source": {"dataset": "enter_codex", "entry_id": "enter-1", "release": "old-r"}}
        with closing(sqlite3.connect(self.args.tags)) as db:
            db.execute("INSERT INTO workbench_tag_meta VALUES (?,?)", ("t", stage.packed(metadata))); db.commit()
        self.review["existing"][0].update(store="tags", target_id="t")
        result = self.run_stage()
        self.assertEqual(result["updated_tags"], 1)
        with closing(sqlite3.connect(self.args.output / "tags.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT value FROM workbench_tag_revision").fetchone()[0], 11)
            after = json.loads(db.execute("SELECT data FROM workbench_tag_meta").fetchone()[0])
            self.assertEqual(after["notes"], "personal")
            self.assertTrue(after["favorite"])
            self.assertEqual(after["external_source"]["release"], "new-r")

    def test_ambiguous_metadata_hold_does_not_touch_existing_resource(self):
        self.review["existing"][0] = {"entry_id": "enter-1", "disposition": "hold", "reason": "ambiguous lineage"}
        result = self.run_stage()
        self.assertEqual(result["holds"], 1)
        self.assertEqual(result["updated_library"], 0)
        for name in ["library.sqlite3"]:
            with closing(sqlite3.connect(getattr(self.args, "library"))) as before, closing(sqlite3.connect(self.args.output / name)) as after:
                self.assertEqual(before.execute("SELECT payload FROM prompts WHERE id='local'").fetchone()[0], after.execute("SELECT payload FROM prompts WHERE id='local'").fetchone()[0])

    def test_all_four_source_aliases_resolve_through_native_merge_contract(self):
        value = stage.read(self.args.web / "enter_codex.json")
        for i in range(3, 7):
            entry = copy.deepcopy(self.added)
            entry.update(id="enter-" + str(i), original="variant-" + str(i) + ".png")
            value["entries"].append(entry)
            self.review["new_groups"][0]["entry_ids"].append(entry["id"])
        self.review["expected"]["added_sources"] = 5
        stage.save(self.args.web / "enter_codex.json", value)
        path = self.args.web / "enter_codex.json"
        stage.save(self.args.web / "manifest.json", {"files": {"enter_codex.json": {"size": path.stat().st_size, "sha256": stage.file_hash(path)}}})
        self.run_stage()
        document = stage.read(self.args.output / "data.json")
        merge = stage.native("prompt_merge")
        for i in range(3, 7):
            identity = "codex-enter-" + str(i)
            mapping = document["_source_to_canonical"][identity]
            self.assertEqual(mapping, {"canonical_id": "codex-enter-2", "source_category_id": "cat"})
            resolved = merge.merged_source(document, identity, "cat")
            self.assertEqual(resolved[1]["id"], "codex-enter-2")
            self.assertEqual(merge.merged_source(document, identity)[1]["id"], "codex-enter-2")
            self.assertIsNone(merge.merged_source(document, identity, "wrong-category"))

    def native_alias_fixture(self):
        store = stage.native("library_store").LibraryStore(self.args.library)
        try:
            document = store.load_document()
            source = document["categories"][0]["prompts"][0]
            source["id"] = "codex-enter-1"
            canonical = {"id": "canonical", "prompt": "kept merged text", "favorite": True, "description": "canonical notes"}
            document["categories"][0]["prompts"].append(canonical)
            document["_source_to_canonical"] = {"codex-enter-1": {"canonical_id": "canonical", "source_category_id": "cat"}}
            store.initialize_from_document(document)
        finally:
            store.close()

    def test_unchanged_primary_is_preserved_without_reordering_current_history(self):
        primary = {"dataset": "book", "entry_id": "one", "note": "old"}
        current = {**primary, "note": "current"}
        before = {"_external_source": primary, "_external_sources": [current]}
        after = stage.add_history(before, [{"dataset": "other", "entry_id": "two"}], preserve_primary=True)
        stage.validate_history(before, after, True)
        self.assertEqual(after["_external_source"], primary)
        self.assertEqual([v for v in after["_external_sources"] if v["dataset"] == "book"], [current])

    def test_changed_primary_requires_exact_prior_revision_to_be_archived(self):
        primary = {"dataset": "book", "entry_id": "one", "note": "old", "custom": "preserve"}
        before = {"_external_source": primary, "_external_sources": []}
        after = {"_external_source": {**primary, "note": "new"}, "_external_sources": []}
        with self.assertRaisesRegex(AssertionError, "prior primary source revision lost"):
            stage.validate_history(before, after, True)
        after["_external_sources"].append(copy.deepcopy(primary))
        stage.validate_history(before, after, True)

    def test_native_alias_rejects_review_that_updates_legacy_physical_row(self):
        self.native_alias_fixture()
        self.review["existing"][0].update(target_id="codex-enter-1", match="direct")
        with self.assertRaisesRegex(ValueError, "native canonical owner"):
            self.run_stage()

    def test_native_canonical_owner_updates_and_legacy_row_stays_exact(self):
        self.native_alias_fixture()
        with closing(sqlite3.connect(self.args.library)) as db:
            original = db.execute("SELECT category_id,payload FROM prompts WHERE id='codex-enter-1'").fetchone()
        self.review["existing"][0].update(target_id="canonical", match="canonical")
        result = self.run_stage()
        self.assertEqual(result["updated_library"], 1)
        with closing(sqlite3.connect(self.args.output / "library.sqlite3")) as db:
            legacy = db.execute("SELECT category_id,payload FROM prompts WHERE id='codex-enter-1'").fetchone()
            canonical = json.loads(db.execute("SELECT payload FROM prompts WHERE id='canonical'").fetchone()[0])
        self.assertEqual(original, legacy)
        self.assertEqual(canonical["prompt"], "kept merged text")
        self.assertEqual(canonical["description"], "canonical notes")
        self.assertEqual(canonical["_external_sources"][-1]["raw_entry"], self.new)


if __name__ == "__main__":
    unittest.main()
