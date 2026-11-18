"""Offline base-model import: synthetic containers, no weights, network or runtime writes."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import import_downloaded_model as importer


def weight(path, keys, *, recent=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {key: {'dtype': 'F32', 'shape': [1], 'data_offsets': [index * 4, index * 4 + 4]}
              for index, key in enumerate(keys)}
    raw = json.dumps(header).encode('utf-8')
    path.write_bytes(struct.pack('<Q', len(raw)) + raw + b'\0' * (4 * len(keys)))
    if not recent:
        old = time.time() - 120
        os.utime(path, (old, old))
    return path


def version(file_name='krea2_cat_tower_v2.0_raw_fp8.safetensors', *, sha='a' * 64, fp='fp8'):
    return {'id': 3338554, 'modelId': 2805913, 'name': 'v2.0 (Raw)', 'baseModel': 'Krea 2',
            'trainedWords': [], 'model': {'name': 'Krea2 Cat Tower', 'type': 'Checkpoint'},
            'files': [{'id': 3229901, 'name': file_name, 'metadata': {'format': 'SafeTensor', 'fp': fp},
                       'hashes': {'SHA256': sha.upper(), 'AutoV3': 'F3C476EE079E'}}]}


def asset(path='ComfyUI/models/diffusion_models/krea2CatTower_v20Raw_fp8.safetensors',
          kind='diffusion_model', sha='a' * 64):
    return {'path': path, 'bytes': 100, 'kind': kind, 'observed_present': True,
            'family': 'Krea2', 'local_sha256': sha, 'derivation': None,
            'sources': [{'provider': 'civitai', 'model_id': 2805913, 'version_id': 3338554,
                         'file_id': 3229901, 'revision': None,
                         'page_url': 'https://civitai.com/models/2805913'}],
            'standardization': {'family_slug': 'krea2', 'family_label': 'Krea2', 'category': '图像生成',
                                'display_name': 'Krea2 Cat Tower', 'version': 'v2.0 (Raw)',
                                'precision': 'FP8', 'source_identity': 'civitai:model=2805913,version=3338554,file=3229901',
                                'target_path': 'ComfyUI/models/diffusion_models/krea2/图像生成/Krea2__Krea2 Cat Tower'
                                               '__v2.0 (Raw)__FP8__cv3338554__f3229901.safetensors',
                                'evidence': ['snapshot/inventory/model_sources.json']}}


class ContainerTests(unittest.TestCase):
    def test_diffusion_only_container_uses_the_unet_root(self):
        with tempfile.TemporaryDirectory() as temp:
            path = weight(Path(temp) / 'krea2CatTower_v20Raw_fp8.safetensors',
                          ['blocks.0.attn.wq.weight', 'last.linear.weight'])
            row = importer.inspect_weight(path)
            self.assertEqual(row['kind'], 'diffusion_model')
            self.assertEqual(row['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_full_checkpoint_container_uses_the_checkpoint_root(self):
        with tempfile.TemporaryDirectory() as temp:
            path = weight(Path(temp) / 'full.safetensors',
                          ['model.diffusion_model.input_blocks.0.weight', 'first_stage_model.decoder.conv_in.weight'])
            self.assertEqual(importer.inspect_weight(path)['kind'], 'checkpoint')

    def test_recent_download_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = weight(Path(temp) / 'fresh.safetensors', ['blocks.0.weight'], recent=True)
            with self.assertRaisesRegex(ValueError, 'download_still_recent'):
                importer.inspect_weight(path)

    def test_truncated_container_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = weight(Path(temp) / 'cut.safetensors', ['blocks.0.weight'])
            path.write_bytes(path.read_bytes()[:-2])
            with self.assertRaises(ValueError):
                importer.inspect_weight(path)


class AssetTests(unittest.TestCase):
    def test_asset_is_named_under_its_family_and_purpose_root(self):
        row = {'original_name': 'krea2CatTower_v20Raw_fp8.safetensors', 'bytes': 14125465720,
               'sha256': 'a' * 64, 'kind': 'diffusion_model'}
        built = importer.build_asset(row, version(), 'diffusion_model')
        self.assertEqual(built['family'], 'Krea2')
        self.assertEqual(built['current_path'],
                         'ComfyUI/models/diffusion_models/krea2/图像生成/Krea2__Krea2 Cat Tower'
                         '__v2.0 (Raw)__FP8__cv3338554__f3229901.safetensors')
        self.assertEqual(built['standardization']['source_identity'],
                         'civitai:model=2805913,version=3338554,file=3229901')
        self.assertEqual(built['companions'],
                         [built['current_path'].replace('.safetensors', '.metadata.json')])
        self.assertFalse(built['captured_in_inventory'])

    def test_asset_requires_the_exact_public_file_hash(self):
        row = {'original_name': 'x.safetensors', 'bytes': 1, 'sha256': 'b' * 64, 'kind': 'diffusion_model'}
        with self.assertRaisesRegex(ValueError, 'exact_source_file_not_found'):
            importer.build_asset(row, version(), 'diffusion_model')

    def test_asset_requires_a_checkpoint_typed_source(self):
        published = version()
        published['model']['type'] = 'LORA'
        row = {'original_name': 'x.safetensors', 'bytes': 1, 'sha256': 'a' * 64, 'kind': 'diffusion_model'}
        with self.assertRaisesRegex(ValueError, 'source_is_not_checkpoint'):
            importer.build_asset(row, published, 'diffusion_model')

    def test_sidecar_keeps_reviewed_organization_and_public_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / Path(asset()['standardization']['target_path']).name
            target.write_bytes(b'x')
            metadata = importer.metadata_for({'sha256': 'a' * 64, 'bytes': 100}, asset(), version(), target)
        self.assertEqual(metadata['organization']['family'], 'Krea2')
        self.assertEqual(metadata['organization']['purpose'], '图像生成')
        self.assertEqual(metadata['organization']['kind'], '底模')
        self.assertEqual(metadata['organization']['binding_status'], 'hash_verified')
        self.assertEqual(metadata['organization']['civitai_version_id'], 3338554)
        self.assertEqual(metadata['base_model'], 'Krea 2')
        self.assertIn('【Krea2｜图像生成】Krea2 Cat Tower · v2.0 (Raw) · FP8', metadata['model_name'])
        self.assertIsNone(metadata['folder'])
        self.assertEqual(metadata['civitai']['files'][0]['hashes']['SHA256'], 'A' * 64)


class CardTests(unittest.TestCase):
    def database(self, root, rows):
        path = root / 'cache.sqlite'
        con = sqlite3.connect(path)
        try:
            con.execute('create table models (model_type text, file_path text, model_name text, sha256 text)')
            con.executemany('insert into models values (?, ?, ?, ?)', rows)
            con.commit()
        finally:
            con.close()
        return path

    def test_card_check_requires_path_label_and_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / Path(asset()['standardization']['target_path']).name
            target.write_text('', encoding='utf-8')
            label = '【Krea2｜图像生成】Krea2 Cat Tower · v2.0 (Raw) · FP8'
            database = self.database(root, [('checkpoint', target.as_posix(), label, 'a' * 64)])
            importer.verify_card(database, target, {'sha256': 'a' * 64}, label)
            with self.assertRaisesRegex(ValueError, 'card_verification_failed'):
                importer.verify_card(database, target, {'sha256': 'a' * 64}, label + ' ')


if __name__ == '__main__':
    unittest.main()
