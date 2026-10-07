"""Prevent another loss of audited plugin dependencies across import and capture."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import import_workspace_sources as importer
import project
import snapshot


class PluginSupportTests(unittest.TestCase):
    def test_registered_support_roundtrip_and_unknown_neighbors(self):
        paths = snapshot.reviewed_plugin_sources()
        self.assertTrue(paths)
        for relative in paths:
            self.assertTrue(snapshot.supported_source_payload(relative), relative)
            self.assertFalse(snapshot.private_config(relative), relative)
            self.assertIsNone(importer.rejection(relative), relative)
        for relative in ('ComfyUI/custom_nodes/vnccs-utils/other/body.target',
                         'ComfyUI/custom_nodes/example/tokenizer.model',
                         'ComfyUI/custom_nodes/example/config.json',
                         'ComfyUI/custom_nodes/websocket_other.py.exe'):
            self.assertIsNotNone(importer.rejection(relative), relative)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'runtime'
            repo = root / 'repo'
            runtime.mkdir(); repo.mkdir()
            examples = ('ComfyUI/custom_nodes/websocket_image_save.py',
                        'ComfyUI/custom_nodes/ComfyUI-LTXVideo/gemma_configs/tokenizer.model',
                        'ComfyUI/custom_nodes/ComfyUI_Mira/json/wai_characters.csv')
            for relative in examples:
                source = runtime / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b'public fixture\n')
            review = importer.plan(runtime, repo)
            self.assertEqual(review['new_files'], len(examples))
            importer.apply_plan(review, review['review_sha256'], repo)
            entries = project.source_entries(repo)
            manifest = repo / 'registered.json'
            manifest.write_text(json.dumps({'files': entries}), encoding='utf-8')
            profile = runtime / 'production_tools/profiles.json'
            profile.parent.mkdir(); profile.write_text('{"production":[]}')
            selected, _, _ = snapshot.selected_sources(runtime, manifest)
            self.assertTrue(set(examples) <= selected.keys())

    def test_exact_review_never_waives_byte_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / 'runtime'; runtime.mkdir()
            repo = Path(temp) / 'repo'; repo.mkdir()
            relative = 'ComfyUI/custom_nodes/ComfyUI-LTXVideo/gemma_configs/tokenizer.model'
            file = runtime / relative; file.parent.mkdir(parents=True)
            synthetic = ('sk-' + 'R8' * 20).encode()
            file.write_bytes(b'public prefix ' + synthetic)
            review = importer.plan(runtime, repo)
            self.assertEqual(review['new_files'], 0)
            self.assertEqual(review['records'][0]['status'], 'security_quarantine')
            self.assertNotIn(synthetic.decode(), json.dumps(review))

    def test_contract_has_unique_portable_exact_paths(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(snapshot, 'REPO', Path(temp)):
            contract = Path(temp) / 'governance/plugin-support-20261007.json'
            contract.parent.mkdir()
            for paths in (['../private/config.json'], ['scripts/private.json'],
                          ['ComfyUI/custom_nodes/one.txt'] * 2):
                contract.write_text(json.dumps({'public_sources': paths}))
                with self.assertRaises(ValueError):
                    snapshot.reviewed_plugin_sources()

    def test_capture_rejects_reviewed_file_and_parent_links(self):
        for directory_link in (False, True):
            with self.subTest(directory_link=directory_link), tempfile.TemporaryDirectory() as temp:
                runtime = Path(temp)
                profile = runtime / 'production_tools/profiles.json'
                profile.parent.mkdir(); profile.write_text('{"production":[]}')
                (runtime / 'ComfyUI/custom_nodes').mkdir(parents=True)
                relative = 'ComfyUI/custom_nodes/fixture/data.txt'
                outside = runtime / 'outside'; outside.mkdir()
                (outside / 'data.txt').write_text('unreviewed fixture')
                link = runtime / ('ComfyUI/custom_nodes/fixture' if directory_link else relative)
                link.parent.mkdir(parents=True, exist_ok=True)
                try:
                    link.symlink_to(outside if directory_link else outside / 'data.txt', target_is_directory=directory_link)
                except OSError:
                    self.skipTest('Symlink creation unavailable')
                with patch.object(snapshot, 'reviewed_plugin_sources', return_value={relative}):
                    with self.assertRaises(ValueError):
                        snapshot.selected_sources(runtime, runtime / 'missing-manifest.json')


if __name__ == '__main__':
    unittest.main()
