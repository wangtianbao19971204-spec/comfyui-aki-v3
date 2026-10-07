"""Synthetic prompt-assistant exports; never inspect live user documents."""
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
SPEC = importlib.util.spec_from_file_location('snapshot', Path(__file__).resolve().parents[1] / 'scripts/snapshot.py')
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


OWNER = 'ComfyUI/user/default/prompt-assistant'
DOCUMENTS = (
    'rules/system_prompts.json', 'rules/kontext_presets.json',
    'tags/默认标签.csv', 'config/active_prompts.json', 'config/tags_user.json',
)


def fixture_bytes(relative):
    if relative.endswith('.csv'):
        return b'\xef\xbb\xbf' + '标签,备注\r\n"角色","保留中文与逗号，"\r\n"场景","第二条合成标注"\r\n'.encode('utf-8')
    fixture = {'id': 'fixture-' + relative, 'content': '中文正文\r\n第二行',
               'personal': {'favorite': True, 'note': '原字段'}}
    return b'\xef\xbb\xbf' + (json.dumps(fixture, ensure_ascii=False, indent=2)
                              .replace('\n', '\r\n') + '\r\n').encode('utf-8')


class PromptAssistantExportTests(unittest.TestCase):
    def setUp(self):
        # Isolate source selection from the installed plugin catalogue.
        patcher = patch.object(snapshot, 'reviewed_plugin_sources', return_value=frozenset())
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_document(self, runtime, relative, data=None):
        source = runtime / OWNER / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(fixture_bytes(relative) if data is None else data)
        return source

    def chunk_snapshot(self, runtime, payload):
        payload.mkdir()
        entries = []
        with patch.object(snapshot, 'CHUNK', 32):
            for source, relative in snapshot.prompt_assistant_text_exports(runtime):
                parts = snapshot.split_file(source, payload / relative)
                entries.append({
                    'source': source.relative_to(runtime).as_posix(), 'path': relative,
                    'kind': 'chunks', 'sha256': snapshot.digest(source),
                    'bytes': source.stat().st_size, 'parts': parts,
                })
        snapshot.save(payload / 'manifest.json', {
            'source_root': str(runtime), 'files': entries,
        })
        return entries

    def test_only_exact_five_documents_selected_and_auth_neighbors_not_read(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / 'live'
            for relative in DOCUMENTS:
                self.write_document(runtime, relative)
            neighbors = [
                'config/config.json', 'config/providers.json', 'config/credentials.json',
                'rules/auth.json', 'rules/unreviewed.json', 'tags/private.csv',
            ]
            for relative in neighbors:
                self.write_document(runtime, relative, b'synthetic excluded neighbor')
            outside = runtime / 'ComfyUI/user/other/prompt-assistant/rules/system_prompts.json'
            outside.parent.mkdir(parents=True)
            outside.write_bytes(b'synthetic different user')
            expected = {(OWNER + '/' + name, 'library/prompt_assistant/' + name)
                        for name in DOCUMENTS}
            with patch.object(Path, 'open', side_effect=AssertionError('selector must not read document bodies')):
                actual = {(source.relative_to(runtime).as_posix(), target)
                          for source, target in snapshot.prompt_assistant_text_exports(runtime)}
            self.assertEqual(actual, expected)

    def test_missing_documents_do_not_create_files_or_default_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'live'
            runtime.mkdir()
            self.assertEqual(snapshot.prompt_assistant_text_exports(runtime), [])
            self.assertEqual(list(runtime.rglob('*')), [])
            self.write_document(runtime, 'config/active_prompts.json')
            entries = self.chunk_snapshot(runtime, root / 'candidate')
            snapshot.materialize(root / 'candidate', root / 'restored')
            self.assertEqual({row['source'] for row in entries}, {OWNER + '/config/active_prompts.json'})
            self.assertFalse((root / 'restored' / OWNER / 'rules').exists())
            self.assertFalse((runtime / OWNER / 'rules').exists())

    def test_chunk_restore_preserves_unicode_bom_crlf_ids_and_personal_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'live'
            expected = {}
            for relative in DOCUMENTS:
                expected[relative] = fixture_bytes(relative)
                self.write_document(runtime, relative, expected[relative])
            entries = self.chunk_snapshot(runtime, root / 'candidate')
            self.assertEqual({row['kind'] for row in entries}, {'chunks'})
            self.assertTrue(all(len(row['parts']) > 1 for row in entries))
            result = snapshot.materialize(root / 'candidate', root / 'restored')
            self.assertTrue(result['pass'])
            for relative, raw in expected.items():
                restored = root / 'restored' / OWNER / relative
                self.assertEqual(restored.read_bytes(), raw)
                if relative.endswith('.json'):
                    data = json.loads(restored.read_text(encoding='utf-8-sig'))
                    self.assertEqual(data['id'], 'fixture-' + relative)
                    self.assertEqual(data['content'], '中文正文\r\n第二行')
                    self.assertEqual(data['personal'], {'favorite': True, 'note': '原字段'})

    def test_registered_chunks_and_file_entries_cannot_reclassify_documents_as_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'live'
            for relative in DOCUMENTS:
                self.write_document(runtime, relative)
            profiles = runtime / 'production_tools/profiles.json'
            profiles.parent.mkdir()
            profiles.write_text('{"production": []}', encoding='utf-8')
            main = runtime / 'ComfyUI/main.py'
            main.write_bytes(b'# synthetic core source\n')
            self.write_document(runtime, 'config/config.json', b'{}')
            for kind, alias in [('chunks', False), ('file', False), ('file', True)]:
                with self.subTest(kind=kind, alias=alias):
                    entries = []
                    for relative in DOCUMENTS:
                        source = OWNER + '/' + relative
                        if alias:
                            source = source.swapcase()
                            # POSIX has distinct case paths; Windows aliases the same file.
                            file = runtime / source
                            file.parent.mkdir(parents=True, exist_ok=True)
                            file.write_bytes(fixture_bytes(relative))
                        entries.append({
                            'source': source,
                            'path': ('library/prompt_assistant/' + relative if kind == 'chunks'
                                     else 'runtime/' + source),
                            'kind': kind, 'sha256': hashlib.sha256(fixture_bytes(relative)).hexdigest(),
                            **({'parts': []} if kind == 'chunks' else {}),
                        })
                    manifest = root / 'registered.json'
                    manifest.write_text(json.dumps({'files': entries}, ensure_ascii=False), encoding='utf-8')
                    selected, _, _ = snapshot.selected_sources(runtime, manifest)
                    self.assertIn('ComfyUI/main.py', selected)
                    self.assertFalse({path.casefold() for path in selected} &
                                     {(OWNER + '/' + name).casefold() for name in DOCUMENTS})
                    self.assertNotIn(OWNER + '/config/config.json', selected)

    def test_file_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'live'
            source = runtime / OWNER / 'rules/system_prompts.json'
            source.parent.mkdir(parents=True)
            target = root / 'outside.json'
            target.write_bytes(b'{}')
            try:
                source.symlink_to(target)
            except OSError:
                self.skipTest('Symlink creation unavailable')
            with self.assertRaises(ValueError):
                snapshot.prompt_assistant_text_exports(runtime)

    def test_directory_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'live'
            source = runtime / OWNER / 'rules'
            source.parent.mkdir(parents=True)
            target = root / 'outside-rules'
            target.mkdir()
            (target / 'system_prompts.json').write_bytes(b'{}')
            try:
                source.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest('Symlink creation unavailable')
            with self.assertRaises(ValueError):
                snapshot.prompt_assistant_text_exports(runtime)

    def test_hardlinked_document_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'live'
            source = runtime / OWNER / 'config/tags_user.json'
            source.parent.mkdir(parents=True)
            target = root / 'outside.json'
            target.write_bytes(b'{}')
            os.link(target, source)
            with self.assertRaises(ValueError):
                snapshot.prompt_assistant_text_exports(runtime)

    def test_present_directory_is_not_silently_treated_as_missing_document(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / 'live'
            (runtime / OWNER / 'rules/system_prompts.json').mkdir(parents=True)
            with self.assertRaises(ValueError):
                snapshot.prompt_assistant_text_exports(runtime)


if __name__ == '__main__':
    unittest.main()
