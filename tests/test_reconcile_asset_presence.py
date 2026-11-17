"""Offline presence reconciliation: synthetic runtime, no weights or network."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import reconcile_asset_presence as reconcile


def asset(path, *, kind='lora', present=True, family='Krea2'):
    return {
        'path': path, 'bytes': 100, 'kind': kind, 'captured_in_inventory': False,
        'observed_present': present, 'local_sha256': 'a' * 64 if present else None,
        'source_status': 'version_metadata', 'family': family,
        'sources': [], 'companions': [], 'workflows': [], 'derivation': None,
        'notes': ['fixture'],
    }


class PresenceTests(unittest.TestCase):
    def test_only_absent_files_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / 'ComfyUI/models/loras/krea2').mkdir(parents=True)
            (runtime / 'ComfyUI/models/loras/krea2/kept.safetensors').write_bytes(b'x')
            self.assertFalse(reconcile.missing(asset('ComfyUI/models/loras/krea2/kept.safetensors'), runtime))
            self.assertTrue(reconcile.missing(asset('ComfyUI/models/loras/krea2/gone.safetensors'), runtime))
            self.assertFalse(reconcile.missing(asset('ComfyUI/models/loras/krea2/gone.safetensors',
                                                     present=False), runtime))

    def test_current_path_decides_presence_after_standardization(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / 'ComfyUI/models/loras/krea2').mkdir(parents=True)
            (runtime / 'ComfyUI/models/loras/krea2/Krea2__kept__v1__BF16.safetensors').write_bytes(b'x')
            item = asset('ComfyUI/models/loras/original.safetensors')
            item['current_path'] = 'ComfyUI/models/loras/krea2/Krea2__kept__v1__BF16.safetensors'
            item['standardization'] = {'family_slug': 'krea2'}
            self.assertFalse(reconcile.missing(item, runtime))

    def test_marking_clears_placement_and_digest_but_keeps_history(self):
        item = asset('ComfyUI/models/loras/krea2/x.safetensors')
        item['current_path'] = 'ComfyUI/models/loras/krea2/Krea2__x__v1__BF16.safetensors'
        item['standardization'] = {'family_slug': 'krea2'}
        marked = reconcile.mark_missing(item)
        self.assertFalse(marked['observed_present'])
        self.assertIsNone(marked['local_sha256'])
        self.assertNotIn('current_path', marked)
        self.assertNotIn('standardization', marked)
        self.assertEqual(marked['path'], item['path'])
        self.assertEqual(marked['bytes'], item['bytes'])
        self.assertEqual(marked['notes'][0], 'fixture')
        self.assertIn('presence check', marked['notes'][-1])
        self.assertEqual(item['observed_present'], True)

    def test_authorized_purge_receipt_is_quoted_only_for_purged_roots(self):
        self.assertEqual(reconcile.reason_for('ComfyUI/models/loras/anima/画风与画师/a.safetensors'),
                         reconcile.PURGE_NOTE)
        self.assertEqual(reconcile.reason_for('ComfyUI/models/vae/qwen_image_vae.safetensors'),
                         reconcile.PURGE_NOTE)
        self.assertEqual(reconcile.reason_for('ComfyUI/models/loras/krea2/画风与画师/a.safetensors'),
                         reconcile.OTHER_NOTE)

    def test_apply_marks_records_and_writes_a_private_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / 'repo'
            (repo / 'snapshot/inventory').mkdir(parents=True)
            (repo / 'docs').mkdir()
            runtime = root / 'runtime'
            (runtime / 'ComfyUI/models/loras/krea2').mkdir(parents=True)
            (runtime / 'ComfyUI/models/loras/krea2/kept.safetensors').write_bytes(b'x')
            manifest = {'source_root': str(runtime),
                        'metadata_files': [{'path': 'inventory/model_sources.json',
                                            'sha256': '0' * 64, 'bytes': 0, 'role': 'model-sources'}]}
            (repo / 'snapshot/manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            catalogue = {'assets': [asset('ComfyUI/models/loras/krea2/kept.safetensors'),
                                    asset('ComfyUI/models/loras/krea2/gone.safetensors')],
                         'missing_workflow_references': []}
            with patch.object(reconcile, 'REPO', repo), \
                 patch.object(reconcile.catalogue, 'checked_catalogue',
                              return_value=(catalogue, None, None)), \
                 patch.object(reconcile.catalogue, 'validate_catalogue') as validate, \
                 patch.object(reconcile.catalogue, 'render') as render, \
                 patch.object(reconcile.catalogue, 'read_json', return_value=({}, '0' * 64)), \
                 patch.object(reconcile.catalogue, 'digest', return_value='1' * 64):
                reconcile.main(['--runtime', str(runtime), '--evidence-root', str(root / 'private'),
                                '--apply'])
            validate.assert_called_once()
            render.assert_called_once_with(repo)
            saved = json.loads((repo / reconcile.catalogue.CATALOGUE).read_text(encoding='utf-8'))
            presence = {item['path']: item['observed_present'] for item in saved['assets']}
            self.assertTrue(presence['ComfyUI/models/loras/krea2/kept.safetensors'])
            self.assertFalse(presence['ComfyUI/models/loras/krea2/gone.safetensors'])
            saved_manifest = json.loads((repo / 'snapshot/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(saved_manifest['metadata_files'][0]['sha256'], '1' * 64)
            receipts = list((root / 'private').glob('presence-*/missing.json'))
            self.assertEqual(len(receipts), 1)
            entries = json.loads(receipts[0].read_text(encoding='utf-8'))
            self.assertEqual([entry['path'] for entry in entries],
                             ['ComfyUI/models/loras/krea2/gone.safetensors'])


if __name__ == '__main__':
    unittest.main()
