"""Small synthetic downloads; no production models, network, or cache writes."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import import_lora_downloads as importer


def weight(path, *, offsets=None, recent=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {'fixture.lora_A.weight': {'dtype': 'F32', 'shape': [2],
                                      'data_offsets': offsets or [0, 8]}}
    raw = json.dumps(header).encode('utf-8')
    path.write_bytes(struct.pack('<Q', len(raw)) + raw + b'12345678')
    if not recent:
        old = time.time() - 120
        os.utime(path, (old, old))
    return path


def version(sha, *, base='Anima', title='Synthetic style'):
    return {'id': 200, 'modelId': 100, 'name': 'v1', 'baseModel': base,
            'trainedWords': ['fixture'], 'model': {'name': title, 'type': 'LORA'},
            'files': [{'id': 300, 'name': 'upstream.safetensors',
                       'metadata': {'fp': 'bf16'}, 'hashes': {'SHA256': sha.upper()}}]}


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.row = {'original_name': 'download.safetensors', 'bytes': 200,
                    'sha256': 'a' * 64}
        self.version = version(self.row['sha256'])

    def test_exact_sha_file_chosen_among_multiple_variants(self):
        wrong = copy.deepcopy(self.version['files'][0])
        wrong.update(id=301, metadata={'fp': 'fp16'}, hashes={'SHA256': 'b' * 64})
        self.version['files'].insert(0, wrong)
        asset = importer.public_asset(self.row, self.version, '画风与画师')
        self.assertEqual(asset['sources'][0]['file_id'], 300)
        self.assertEqual(asset['standardization']['precision'], 'BF16')
        self.assertIn('__cv200__f300.safetensors', asset['current_path'])

    def test_short_hash_or_title_match_cannot_identify_source(self):
        for declared in ('a' * 10, 'b' * 64):
            with self.subTest(declared=declared):
                self.version['files'][0]['hashes']['SHA256'] = declared
                with self.assertRaisesRegex(ValueError, 'exact_source_file_not_found'):
                    importer.public_asset(self.row, self.version, '画风与画师')

    def test_ambiguous_hash_requires_review(self):
        self.version['files'].append(copy.deepcopy(self.version['files'][0]))
        with self.assertRaisesRegex(ValueError, 'exact_source_file_not_found'):
            importer.selected_version(self.version, self.row['sha256'])

    def test_non_lora_and_invalid_ids_cannot_be_imported(self):
        self.version['model']['type'] = 'Checkpoint'
        with self.assertRaisesRegex(ValueError, 'source_is_not_lora'):
            importer.selected_version(self.version, self.row['sha256'])
        self.version['model']['type'] = 'LORA'
        for field, value in (('id', True), ('modelId', 0)):
            candidate = copy.deepcopy(self.version)
            candidate[field] = value
            with self.assertRaisesRegex(ValueError, 'invalid_source_identity'):
                importer.selected_version(candidate, self.row['sha256'])

    def test_exact_version_base_beats_cross_family_title(self):
        self.version.update(baseModel='Krea2')
        self.version['model']['name'] = 'Anima 2.9B / Krea2 / Illustrious style'
        asset = importer.public_asset(self.row, self.version, '画风与画师')
        self.assertEqual(asset['family'], 'krea2')
        self.assertIn('/loras/krea2/画风与画师/', asset['current_path'])

    def test_unknown_family_or_category_are_not_guessed(self):
        with self.assertRaisesRegex(ValueError, 'unknown_category'):
            importer.public_asset(self.row, self.version, 'not-reviewed')
        self.version['baseModel'] = 'Unknown architecture'
        self.version['model']['name'] = 'Anima style'
        with self.assertRaisesRegex(ValueError, 'source_family_needs_review'):
            importer.public_asset(self.row, self.version, '画风与画师')

    def test_public_asset_does_not_copy_freeform_response_fields(self):
        marker = 'PRIVATE_SYNTHETIC_FIXTURE'
        self.version.update(description=marker, notes=marker,
                            images=[{'meta': {'prompt': marker}}])
        self.version['model']['description'] = marker
        before = copy.deepcopy(self.version)
        asset = importer.public_asset(self.row, self.version, '画风与画师')
        self.assertNotIn(marker, json.dumps(asset))
        self.assertEqual(self.version, before)
        self.assertEqual(asset['sources'][0]['declared_sha256'], self.row['sha256'])


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = weight(self.root / 'Downloads' / 'fixture.safetensors')

    def test_full_stream_hash_is_recorded(self):
        row = importer.inspect_weight(self.source)
        self.assertEqual(row['sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(row['bytes'], self.source.stat().st_size)

    def test_recent_download_waits_without_mutation(self):
        os.utime(self.source, None)
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'download_still_recent'):
            importer.inspect_weight(self.source)
        self.assertEqual(self.source.read_bytes(), before)

    def test_incomplete_tensor_payload_is_rejected(self):
        weight(self.source, offsets=[0, 1000])
        with self.assertRaisesRegex(ValueError, 'incomplete_safetensors'):
            importer.inspect_weight(self.source)

    def test_changed_download_during_hash_is_rejected(self):
        before = importer.fingerprint(self.source)
        with patch.object(importer, 'fingerprint', side_effect=[before, [0, 0, 0]]):
            with self.assertRaisesRegex(ValueError, 'download_changed'):
                importer.inspect_weight(self.source)

    def test_linked_file_or_parent_is_rejected(self):
        link = self.root / 'linked-downloads'
        try:
            link.symlink_to(self.source.parent, target_is_directory=True)
        except OSError as error:
            self.skipTest('Host does not allow symlink creation: ' + str(error))
        with self.assertRaisesRegex(ValueError, 'linked_path'):
            importer.inspect_weight(link / self.source.name)

    def test_exclusive_copy_never_overwrites_existing_weight(self):
        row = importer.inspect_weight(self.source)
        target = self.root / 'destination.safetensors'
        target.write_bytes(b'existing-user-weight')
        with self.assertRaises(FileExistsError):
            importer.copy_verified(self.source, target, row)
        self.assertEqual(target.read_bytes(), b'existing-user-weight')
        self.assertTrue(self.source.exists())

    def test_changed_source_since_plan_stays_in_downloads(self):
        row = importer.inspect_weight(self.source)
        self.source.write_bytes(b'changed-after-plan')
        target = self.root / 'destination.safetensors'
        with self.assertRaisesRegex(ValueError, 'source_changed_since_plan'):
            importer.copy_verified(self.source, target, row)
        self.assertFalse(target.exists())
        self.assertEqual(self.source.read_bytes(), b'changed-after-plan')

    def test_copy_digest_failure_retains_original(self):
        row = importer.inspect_weight(self.source)
        row['sha256'] = 'b' * 64
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'copied_weight_differs_original_retained'):
            importer.copy_verified(self.source, self.root / 'destination.safetensors', row)
        self.assertEqual(self.source.read_bytes(), before)

    def test_destination_verification_failure_retains_original(self):
        row = importer.inspect_weight(self.source)
        before = self.source.read_bytes()
        with patch.object(importer.hashlib, 'file_digest', return_value=hashlib.sha256(b'bad-copy')):
            with self.assertRaisesRegex(ValueError, 'destination_hash_mismatch_original_retained'):
                importer.copy_verified(self.source, self.root / 'destination.safetensors', row)
        self.assertEqual(self.source.read_bytes(), before)

    def test_cross_volume_copy_verified_before_any_source_removal(self):
        row = importer.inspect_weight(self.source)
        target = self.root / 'other-volume' / 'destination.safetensors'
        importer.copy_verified(self.source, target, row)
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertTrue(self.source.exists())


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.downloads = self.root / 'Downloads'
        self.runtime = self.root / 'runtime'
        self.evidence = self.root / 'private-receipt'
        self.evidence.mkdir()
        self.source = weight(self.downloads / 'new.safetensors')
        self.row = importer.inspect_weight(self.source)
        self.row['version'] = version(self.row['sha256'])
        self.row['asset'] = importer.public_asset(self.row, self.row['version'], '画风与画师')
        self.target = self.runtime / self.row['asset']['current_path']
        self.relative = self.target.relative_to(self.runtime / 'ComfyUI/models/loras').as_posix()
        self.requests = []

    def response(self, url, data=None):
        self.requests.append((url, data))
        if url.endswith('/queue'):
            return {'queue_running': [], 'queue_pending': []}
        if url.endswith('/object_info/LoraLoader'):
            return {'LoraLoader': {'input': {'required': {'lora_name': [[self.relative]]}}}}
        if url.endswith('/api/lm/loras/save-metadata'):
            return {'success': True}
        if '/api/lm/loras/list?' in url:
            metadata = json.loads(self.target.with_suffix('.metadata.json').read_text(encoding='utf-8'))
            return {'items': [metadata]}
        raise AssertionError('Unexpected request: ' + url)

    def run_apply(self, responder=None):
        with patch.object(importer, 'request', side_effect=responder or self.response), redirect_stdout(io.StringIO()):
            return importer.apply_rows([self.row], self.downloads, self.runtime,
                                       'http://127.0.0.1:8188', self.evidence)

    def test_registered_and_loader_visible_then_moves_original(self):
        before = self.source.read_bytes()
        assets = self.run_apply()
        self.assertEqual(assets, [self.row['asset']])
        self.assertFalse(self.source.exists())
        self.assertEqual(self.target.read_bytes(), before)
        self.assertTrue((self.evidence / 'completed-assets.json').exists())
        self.assertTrue(all('/scan' not in url and '/free' not in url for url, _ in self.requests))

    def test_existing_model_and_personal_fields_untouched(self):
        personal = self.runtime / 'ComfyUI/models/loras/anima/old.metadata.json'
        personal.parent.mkdir(parents=True)
        raw = b'{"favorite": true, "exclude": true, "notes": "user fixture"}'
        personal.write_bytes(raw)
        self.run_apply()
        self.assertEqual(personal.read_bytes(), raw)
        posted = [data for url, data in self.requests if url.endswith('/save-metadata')]
        self.assertEqual(len(posted), 1)
        self.assertEqual(set(posted[0]), {'file_path', 'model_name', 'organization'})
        self.assertEqual(posted[0]['file_path'], self.target.as_posix())

    def test_existing_target_sidecar_prevents_registration(self):
        self.target.parent.mkdir(parents=True)
        old = self.target.with_suffix('.metadata.json')
        raw = b'{"favorite": true, "exclude": true}'
        old.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'target_exists_no_overwrite'):
            self.run_apply()
        self.assertEqual(old.read_bytes(), raw)
        self.assertFalse(self.target.exists())
        self.assertTrue(self.source.exists())
        self.assertTrue(all(data is None for _, data in self.requests))

    def test_registration_failure_retains_original(self):
        def responder(url, data=None):
            if url.endswith('/save-metadata'):
                return {'success': False}
            return self.response(url, data)
        with self.assertRaisesRegex(ValueError, 'registration_failed_original_retained'):
            self.run_apply(responder)
        self.assertTrue(self.source.exists())
        self.assertFalse((self.evidence / 'completed-assets.json').exists())

    def test_card_mismatch_retains_original(self):
        def responder(url, data=None):
            if '/api/lm/loras/list?' in url:
                return {'items': [{'file_path': self.target.as_posix(), 'sha256': 'b' * 64}]}
            return self.response(url, data)
        with self.assertRaisesRegex(ValueError, 'card_or_loader_verification_failed_original_retained'):
            self.run_apply(responder)
        self.assertTrue(self.source.exists())

    def test_busy_queue_prevents_any_copy(self):
        with self.assertRaisesRegex(ValueError, 'queue_is_not_empty'):
            self.run_apply(lambda url, data=None: {'queue_running': [['job']], 'queue_pending': []})
        self.assertTrue(self.source.exists())
        self.assertFalse(self.target.exists())

    def test_outside_lora_root_target_is_rejected(self):
        self.row['asset']['current_path'] = 'ComfyUI/models/checkpoints/escaped.safetensors'
        with self.assertRaises(ValueError):
            self.run_apply()
        self.assertTrue(self.source.exists())
        self.assertFalse((self.runtime / self.row['asset']['current_path']).exists())

    def test_sidecar_selects_public_identity_fields(self):
        marker = 'PRIVATE_SYNTHETIC_FIXTURE'
        self.row['version'].update(notes=marker, description=marker, images=[{'prompt': marker}])
        self.row['version']['model']['description'] = marker
        self.run_apply()
        metadata = self.target.with_suffix('.metadata.json').read_text(encoding='utf-8')
        self.assertNotIn(marker, metadata)

    def test_preview_http_failure_does_not_block_registered_model(self):
        self.row['version']['images'] = [{'type': 'image', 'url': 'https://image.civitai.com/fixture.jpeg'}]
        failure = HTTPError('http://127.0.0.1:8188/api/lm/loras/set-preview-from-url',
                            502, 'synthetic upstream failure', {}, io.BytesIO(b''))
        self.addCleanup(failure.close)

        def responder(url, data=None):
            if url.endswith('/set-preview-from-url'):
                raise failure
            return self.response(url, data)

        companions = self.row['asset']['companions'][:]
        assets = self.run_apply(responder)
        self.assertEqual(assets, [self.row['asset']])
        self.assertFalse(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertEqual(self.row['asset']['companions'], companions)

    def test_video_http_and_lookalike_image_hosts_do_not_fetch(self):
        self.row['version']['images'] = [
            {'type': 'video', 'url': 'https://image.civitai.com/clip.mp4'},
            {'type': 'image', 'url': 'http://image.civitai.com/plain.jpeg'},
            {'type': 'image', 'url': 'https://image.civitai.com.example.test/fixture.jpeg'},
            {'type': 'image', 'url': 'https://example.test/fixture.jpeg'},
        ]
        with patch.object(importer, 'request') as request:
            importer.add_preview(self.row, self.target, self.runtime, 'http://127.0.0.1:8188')
            request.assert_not_called()

    def test_official_static_preview_registers_only_local_companion(self):
        self.row['version']['images'] = [
            {'type': 'image', 'url': 'https://image.civitai.com/second.jpeg', 'nsfwLevel': 8},
            {'type': 'image', 'url': 'https://image.civitai.com/first.jpeg', 'nsfwLevel': 1,
             'meta': {'prompt': 'PRIVATE_SYNTHETIC_FIXTURE'}},
        ]
        sent = []
        preview = self.target.with_suffix('.preview.jpeg')

        def responder(url, data=None):
            if url.endswith('/set-preview-from-url'):
                sent.append(data)
                preview.write_bytes(b'synthetic static thumbnail')
                sidecar = self.target.with_suffix('.metadata.json')
                metadata = json.loads(sidecar.read_text(encoding='utf-8'))
                metadata['preview_url'] = preview.as_posix()
                sidecar.write_text(json.dumps(metadata), encoding='utf-8')
                return {'success': True}
            return self.response(url, data)

        self.run_apply(responder)
        self.assertEqual(sent, [{'model_path': self.target.as_posix(),
                                'image_url': 'https://image.civitai.com/first.jpeg', 'nsfw_level': 1}])
        self.assertIn(preview.relative_to(self.runtime).as_posix(), self.row['asset']['companions'])
        self.assertTrue(self.target.exists())
        self.assertFalse(self.source.exists())


class MainBoundaryTests(unittest.TestCase):
    def test_apply_updates_only_source_metadata_manifest_and_accepts_runtime_ancestor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'runtime'
            # The live root normally contains maintenance/comfyui; this is valid.
            repo = runtime / 'maintenance/comfyui'
            (repo / 'snapshot/inventory').mkdir(parents=True)
            downloads = root / 'Downloads'
            source = weight(downloads / 'new.safetensors')
            measured = importer.inspect_weight(source)
            public_version = version(measured['sha256'])
            baseline = {'assets': [], 'missing_workflow_references': []}
            catalogue_path = repo / importer.catalogue.CATALOGUE
            catalogue_path.write_text(json.dumps(baseline), encoding='utf-8')
            inventory_path = repo / importer.catalogue.INVENTORY
            inventory_path.write_text('{}', encoding='utf-8')
            workflow_path = repo / importer.catalogue.WORKFLOW_SOURCE
            workflow_path.parent.mkdir(parents=True)
            workflow_path.write_text('{"nodes": []}', encoding='utf-8')
            original_metadata = [
                {'path': 'inventory/model_sources.json', 'sha256': 'a' * 64,
                 'bytes': 1, 'role': 'public-source-metadata'},
                {'path': 'inventory/models.json', 'sha256': 'b' * 64, 'bytes': 2},
            ]
            original_files = [
                {'path': 'ComfyUI/main.py', 'sha256': 'c' * 64, 'bytes': 3},
                {'path': 'inventory/model_sources.json', 'sha256': 'd' * 64, 'bytes': 4},
            ]
            manifest = {'source_root': str(runtime), 'files': copy.deepcopy(original_files),
                        'metadata_files': copy.deepcopy(original_metadata), 'schema': 1}
            manifest_path = repo / 'snapshot/manifest.json'
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            old_inventory = inventory_path.read_bytes()
            old_workflow = workflow_path.read_bytes()
            cache = root / 'private-cache.sqlite'
            connection = importer.sqlite3.connect(cache)
            try:
                connection.execute('CREATE TABLE personal (favorite INTEGER, excluded INTEGER)')
                connection.execute('INSERT INTO personal VALUES (1, 1)')
                connection.commit()
            finally:
                connection.close()

            def apply_mock(rows, actual_downloads, actual_runtime, api, evidence, previews=True):
                self.assertEqual(actual_downloads, downloads)
                self.assertEqual(actual_runtime, runtime)
                self.assertTrue(previews)
                self.assertTrue((evidence / 'cache-before.sqlite').exists())
                return [row['asset'] for row in rows]

            with patch.object(importer, 'REPO', repo), \
                 patch.object(importer.catalogue, 'checked_catalogue', return_value=(copy.deepcopy(baseline), None, None)), \
                 patch.object(importer.catalogue, 'validate_catalogue') as validate, \
                 patch.object(importer.catalogue, 'render') as render, \
                 patch.object(importer.subprocess, 'check_output', return_value='feat/import-fixture\n'), \
                 patch.object(importer, 'request', return_value=public_version), \
                 patch.object(importer, 'apply_rows', side_effect=apply_mock), \
                 redirect_stdout(io.StringIO()):
                importer.main(['--runtime', str(runtime), '--downloads', str(downloads),
                               '--cache-db', str(cache), '--evidence-root', str(root / 'private'), '--apply'])
                self.assertEqual(validate.call_count, 2)
                render.assert_called_once_with(repo)
            updated = json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertEqual(updated['files'], original_files)
            self.assertEqual(updated['metadata_files'][1:], original_metadata[1:])
            source_record = updated['metadata_files'][0]
            self.assertEqual(source_record['sha256'], hashlib.sha256(catalogue_path.read_bytes()).hexdigest())
            self.assertEqual(source_record['bytes'], catalogue_path.stat().st_size)
            self.assertEqual(source_record['role'], original_metadata[0]['role'])
            self.assertEqual(updated['source_root'], str(runtime))
            self.assertEqual(updated['schema'], manifest['schema'])
            self.assertEqual(inventory_path.read_bytes(), old_inventory)
            self.assertEqual(workflow_path.read_bytes(), old_workflow)
            saved_catalogue = json.loads(catalogue_path.read_text(encoding='utf-8'))
            self.assertEqual(len(saved_catalogue['assets']), 1)
            self.assertEqual(saved_catalogue['assets'][0]['local_sha256'], measured['sha256'])
            connection = importer.sqlite3.connect(cache)
            try:
                self.assertEqual(connection.execute('SELECT * FROM personal').fetchall(), [(1, 1)])
            finally:
                connection.close()

    def test_runtime_inside_repository_is_rejected_before_download_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / 'repo'
            (repo / 'snapshot').mkdir(parents=True)
            (repo / 'snapshot/manifest.json').write_text(json.dumps({'source_root': str(root / 'runtime')}))
            with patch.object(importer, 'REPO', repo), patch.object(importer.catalogue, 'checked_catalogue', return_value=({'assets': []}, None, None)):
                with self.assertRaisesRegex(ValueError, 'private_inputs_must_stay_outside_git'):
                    importer.main(['--runtime', str(repo / 'snapshot/runtime'),
                                   '--downloads', str(root / 'Downloads'),
                                   '--evidence-root', str(root / 'private')])


if __name__ == '__main__':
    unittest.main()
