"""Offline registration of deployed LoRAs: synthetic tree, no weights or network."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import register_present_loras as register


def meta(digest, *, family='Moss', purpose='画风与画师', official='748cm Style', version='v1.0',
         precision='BF16', model_id=100, version_id=200, file_id=300):
    civitai = {'id': version_id, 'modelId': model_id,
               'files': [{'id': file_id, 'name': 'upstream:name.safetensors',
                          'hashes': {'SHA256': digest.upper()}}]}
    return {'file_name': 'Moss__748cm__v1.0__BF16', 'model_name': '【Moss｜画风与画师】748cm Style · v1.0 · BF16',
            'sha256': digest, 'preview_url': '', 'metadata_source': 'moss-deploy-20261114',
            'civitai': civitai,
            'organization': {'family': family, 'purpose': purpose, 'official_name': official,
                             'version': version, 'precision': precision}}


class RegistrationTests(unittest.TestCase):
    def test_asset_uses_the_slot_directory_as_the_reviewed_placement(self):
        digest = 'b' * 64
        relative = 'ComfyUI/models/loras/moss/画风与画师/Moss__748cm Style__v1.0__BF16__cv200__f300.safetensors'
        asset = register.build_asset(relative, relative.replace('.safetensors', '.metadata.json'),
                                     digest, 1234, meta(digest), None)
        self.assertEqual(asset['family'], 'Moss')
        self.assertEqual(asset['current_path'], relative)
        self.assertEqual(asset['standardization']['family_slug'], 'moss')
        self.assertEqual(asset['standardization']['category'], '画风与画师')
        self.assertEqual(asset['standardization']['target_path'], relative)
        self.assertEqual(asset['standardization']['source_identity'], 'civitai:model=100,version=200,file=300')
        self.assertEqual(asset['bytes'], 1234)
        self.assertFalse(asset['captured_in_inventory'])
        self.assertEqual(asset['sources'][0]['declared_sha256'], digest)
        self.assertIsNone(asset['sources'][0]['filename'])

    def test_asset_without_civitai_identity_stays_unresolved(self):
        digest = 'c' * 64
        relative = 'ComfyUI/models/loras/moss/控制与编辑/Moss__edit__Rank64__BF16__sha__ABC.safetensors'
        payload = meta(digest)
        payload['civitai'] = {'id': None, 'modelId': None, 'files': []}
        asset = register.build_asset(relative, relative.replace('.safetensors', '.metadata.json'),
                                     digest, 1, payload, None)
        self.assertEqual(asset['source_status'], 'unresolved')
        self.assertEqual(asset['sources'], [])
        self.assertEqual(asset['standardization']['source_identity'], 'unresolved:sha256=' + digest)

    def test_asset_rejects_a_slot_outside_the_reviewed_families(self):
        digest = 'd' * 64
        relative = 'ComfyUI/models/loras/other/画风与画师/x.safetensors'
        with self.assertRaisesRegex(ValueError, 'unreviewed_family_or_purpose'):
            register.build_asset(relative, 'x.metadata.json', digest, 1, meta(digest), None)

    def test_readable_name_drops_names_outside_the_catalogue_path_contract(self):
        self.assertIsNone(register.readable_name('upstream:name.safetensors'))
        self.assertEqual(register.readable_name('plain name.safetensors'), 'plain name.safetensors')

    def test_display_name_prefers_the_reviewed_official_name(self):
        payload = meta('e' * 64)
        self.assertEqual(register.display_name(payload), '748cm Style')
        payload['organization']['official_name'] = ''
        self.assertEqual(register.display_name(payload), '748cm Style')
        payload['model_name'] = '【Moss｜画风与画师】Plain · v1'
        payload['organization']['official_name'] = ''
        self.assertEqual(register.display_name(payload), 'Plain')

    def test_collect_skips_recorded_sidecarless_and_mismatched_files(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            slot = runtime / 'ComfyUI/models/loras/moss/画风与画师'
            slot.mkdir(parents=True)
            kept = slot / 'Moss__kept.safetensors'
            kept.write_bytes(b'kept')
            mismatch = slot / 'Moss__mismatch.safetensors'
            mismatch.write_bytes(b'mismatch')
            bare = slot / 'Moss__bare.safetensors'
            bare.write_bytes(b'bare')
            fresh = slot / 'Moss__fresh.safetensors'
            fresh.write_bytes(b'fresh')
            for weight, digest in ((kept, hashlib.sha256(b'kept').hexdigest()),
                                   (mismatch, 'f' * 64),
                                   (fresh, hashlib.sha256(b'fresh').hexdigest())):
                payload = meta(digest)
                weight.with_suffix('.metadata.json').write_text(json.dumps(payload), encoding='utf-8')
            added, skipped = register.collect(runtime,
                                              {('ComfyUI/models/loras/moss/画风与画师/' + kept.name).casefold()},
                                              set(), set())
            self.assertEqual([Path(item['path']).name for item in added], ['Moss__fresh.safetensors'])
            reasons = {Path(item['path']).name: item['reason'] for item in skipped}
            self.assertEqual(reasons['Moss__mismatch.safetensors'], 'sidecar_sha256_mismatch')
            self.assertEqual(reasons['Moss__bare.safetensors'], 'sidecar_missing')


if __name__ == '__main__':
    unittest.main()
