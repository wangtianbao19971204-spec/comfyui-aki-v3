"""Original-site annotation contracts; all source/body data here is fictional."""
import ast
import asyncio
from contextlib import closing
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector"
PACKAGE = "_source_notes_fixture_native"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE); package.__path__ = [str(NATIVE)]
    sys.modules[PACKAGE] = package
notes = importlib.import_module(PACKAGE + ".source_notes")


def source(entry="entry-a", note="原站说明", **extra):
    return {"dataset": "suozhang", "entry_id": entry, "title": "示例条目",
            "note": note, "url": "https://novelai.quicktagcloud.com/?c=suozhang&id=" + entry, **extra}


class SourceNoteProjectionTests(unittest.TestCase):
    def test_raw_note_is_authoritative_over_legacy_field(self):
        value = {"_external_source": source(note="旧说明", raw_entry={"note": "新说明\n第二行"})}
        self.assertEqual(notes.project_source_notes(value)[0]["note"], "新说明\n第二行")

    def test_latest_empty_note_suppresses_history_and_old_primary(self):
        old = source(note="旧说明")
        value = {"_external_sources": [old, source(raw_entry={"note": ""})], "_external_source": old}
        self.assertEqual(notes.project_source_notes(value), [])

    def test_absent_raw_note_does_not_revive_legacy_note(self):
        self.assertEqual(notes.project_source_notes({"external_source": source(raw_entry={"title": "示例"})}), [])

    def test_distinct_source_identities_keep_equal_notes_separate(self):
        value = {"external_sources": [source("a"), source("b"), source("a", note="更新说明")]}
        result = notes.project_source_notes(value)
        self.assertEqual([r["note"] for r in result], ["更新说明", "原站说明"])

    def test_no_internal_data_or_personal_fields_in_projection(self):
        value = {"description": "个人描述", "notes": "个人备注", "external_source": source(release="private-release", source_sha256="private-hash", raw_entry={"note": "说明", "tags": "not UI data"})}
        before = copy.deepcopy(value)
        result = notes.project_source_notes(value)
        self.assertEqual(set(result[0]), {"title", "entry_title", "note", "url"})
        text = json.dumps(result, ensure_ascii=False)
        for hidden in ["private-release", "private-hash", "个人描述", "个人备注", "not UI data"]:
            self.assertNotIn(hidden, text)
        self.assertEqual(value, before)

    def test_malformed_sources_are_ignored_and_internal_titles_are_hidden(self):
        self.assertEqual(notes.project_source_notes({"external_sources": [None, 4, {}, {"dataset": "suozhang", "note": "孤立说明"}]}), [])
        result = notes.project_source_notes({"external_source": source(title="entry-a", dataset_title="suozhang")})
        self.assertEqual(result[0]["entry_title"], "")
        self.assertEqual(result[0]["title"], "所长常规法典")

    def test_original_link_allows_only_known_public_https_without_credentials(self):
        valid = "https://novelai.quicktagcloud.com/?c=suozhang&id=sample"
        self.assertEqual(notes.public_source_url(valid), valid)
        fixture_userinfo = "fixture-user:fixture-password" + "@"
        for url in ["javascript:alert(1)", "http://novelai.quicktagcloud.com/", "https://" + fixture_userinfo + "novelai.quicktagcloud.com/", "https://127.0.0.1/", "https://novelai.quicktagcloud.com.evil.test/", "https://novelai.quicktagcloud.com/\nfoo", "https://novelai.quicktagcloud.com:8443/"]:
            self.assertEqual(notes.public_source_url(url), "")


class SourceNoteReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tags.db"
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("CREATE TABLE tag_tags(t_uuid TEXT PRIMARY KEY); CREATE TABLE workbench_tag_meta(tag_uuid TEXT PRIMARY KEY,data TEXT); CREATE TABLE workbench_tag_revision(id INTEGER PRIMARY KEY,value INTEGER); INSERT INTO workbench_tag_revision VALUES(1,21); INSERT INTO tag_tags VALUES('shared');")
            db.execute("INSERT INTO workbench_tag_meta VALUES(?,?)", ("shared", json.dumps({"notes": "个人 Tag 备注", "external_source": source(note="Tag 的原站说明")}, ensure_ascii=False)))
            db.commit()
        self.document = {"last_modified": "revision-a", "_source_to_canonical": {"legacy": {"canonical_id": "shared", "source_category_id": "old"}}, "categories": [
            {"id": "old", "prompts": [{"id": "legacy", "_external_source": source(note="旧物理行说明")}]},
            {"id": "active", "prompts": [{"id": "shared", "description": "个人资源说明", "favorite": True, "_external_source": source(note="资源的原站说明")}]}]}

    def test_resource_uses_native_canonical_owner_despite_legacy_physical_row(self):
        before = copy.deepcopy(self.document)
        result = notes.read_source_notes("legacy", lambda: self.document, self.path)
        self.assertEqual(result["source_notes"][0]["note"], "资源的原站说明")
        self.assertEqual(result["revision"], "revision-a")
        self.assertEqual(before, self.document)

    def test_tag_uuid_namespace_is_separate_and_read_does_not_modify_db(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        tag = notes.read_source_notes("tag:shared", lambda: self.document, self.path)
        resource = notes.read_source_notes("shared", lambda: self.document, self.path)
        self.assertEqual(tag["source_notes"][0]["note"], "Tag 的原站说明")
        self.assertEqual(resource["source_notes"][0]["note"], "资源的原站说明")
        self.assertEqual(tag["revision"], "tags-v1:21")
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_unknown_identity_is_not_guessed_from_similar_body(self):
        for identity in ["missing", "tag:shared' OR 1=1--"]:
            with self.assertRaises(KeyError):
                notes.read_source_notes(identity, lambda: self.document, self.path)
        for identity in [None, "", "tag:"]:
            with self.assertRaises(ValueError):
                notes.read_source_notes(identity, lambda: self.document, self.path)

    def route(self, reader=None):
        tree = ast.parse((NATIVE / "tag_api.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "source_notes_get")
        function.decorator_list = []
        stub = lambda payload, status=200, headers=None: {"payload": payload, "status": status, "headers": headers or {"Cache-Control": "no-store"}}
        namespace = {"asyncio": asyncio, "read_source_notes": reader or notes.read_source_notes,
                     "prompt_store": types.SimpleNamespace(_read_prompt_data_cached=lambda: self.document),
                     "dao": types.SimpleNamespace(tags_db_path=self.path), "web": types.SimpleNamespace(json_response=stub), "response": stub}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "source_notes_route", "exec"), namespace)
        return namespace["source_notes_get"]

    def test_native_route_is_no_store_and_returns_annotation_projection(self):
        result = asyncio.run(self.route()(types.SimpleNamespace(query={"resource_id": "legacy"})))
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["headers"]["Cache-Control"], "no-store")
        self.assertEqual(result["payload"]["source_notes"][0]["note"], "资源的原站说明")

    def test_route_errors_do_not_expose_internal_exception_details(self):
        invalid = asyncio.run(self.route()(types.SimpleNamespace(query={})))
        missing = asyncio.run(self.route()(types.SimpleNamespace(query={"resource_id": "missing"})))
        def broken(*args): raise OSError("private path and SQL internals")
        failure = asyncio.run(self.route(broken)(types.SimpleNamespace(query={"resource_id": "shared"})))
        self.assertEqual([invalid["status"], missing["status"], failure["status"]], [400, 404, 503])
        self.assertNotIn("private path", str(failure))


if __name__ == "__main__":
    unittest.main()
