"""Regression coverage for omitted build/default/runtime support dependencies."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import import_workspace_sources as importer
import project
import snapshot


TRAINER = importer.TRAINER
PUBLIC_CONFIGS = {
    TRAINER + '/vendor/sd-scripts/configs/qwen3_06b/config.json',
    TRAINER + '/vendor/sd-scripts/configs/t5_old/config.json',
}
VITE = snapshot.WB + '/modules/comfyui-lora-manager/vue-widgets/vite.config.mts'
DEFAULT = 'ComfyUI/custom_nodes/rgthree-comfy/rgthree_config.json.default'


class SourceSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runtime = self.base / 'runtime'
        self.repo = self.base / 'repo'
        self.runtime.mkdir()
        self.repo.mkdir()

    def source(self, relative, data=b'public support fixture\n'):
        path = self.runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_types_are_supported_consistently(self):
        paths = {VITE, 'scripts/example.cts', 'scripts/repair.patch',
                 'scripts/LICENSE-MIT', 'scripts/NOTICE-MHR',
                 'scripts/THIRD_PARTY_NOTICES'} | PUBLIC_CONFIGS | snapshot.REVIEWED_SUPPORT_FILES
        for relative in paths:
            with self.subTest(relative=relative):
                self.assertIsNone(importer.rejection(relative))
                self.assertTrue(snapshot.supported_source_payload(relative))
                self.assertFalse(snapshot.private_config(relative))

    def test_import_seal_and_registered_recapture_preserve_bytes(self):
        paths = {VITE, 'scripts/fix.patch', 'scripts/LICENSE-MIT'} | PUBLIC_CONFIGS | snapshot.REVIEWED_SUPPORT_FILES
        for relative in paths:
            self.source(relative, b'\x00asm\x01\x00\x00\x00' if relative.endswith('.wasm') else b'{}\n')
        review = importer.plan(self.runtime, self.repo)
        self.assertEqual(review['new_files'], len(paths))
        result = importer.apply_plan(review, review['review_sha256'], self.repo)
        self.assertEqual(result['files'], len(paths))
        entries = project.source_entries(self.repo)
        self.assertEqual({item['source'] for item in entries}, paths)
        for entry in entries:
            self.assertEqual(snapshot.digest(self.runtime / entry['source']), entry['sha256'])
        manifest = self.repo / 'registered.json'
        manifest.write_text(json.dumps({'files': entries}), encoding='utf-8')
        self.source('production_tools/profiles.json', b'{"production": []}')
        selected, omitted, _ = snapshot.selected_sources(self.runtime, manifest)
        self.assertTrue(paths <= selected.keys())
        self.assertEqual(omitted, [])

    def test_unregistered_production_support_is_discovered(self):
        self.source(DEFAULT, b'{}')
        self.source(VITE, b'export default {}\n')
        self.source('ComfyUI/custom_nodes/rgthree-comfy/web/lib/tree-sitter.wasm', b'\x00asm')
        self.source('production_tools/profiles.json', json.dumps({'production': [
            'rgthree-comfy', 'ComfyUI-Unified-Prompt-Workbench']}).encode())
        selected, _, _ = snapshot.selected_sources(self.runtime, self.repo / 'not-created.json')
        self.assertTrue({DEFAULT, VITE, 'ComfyUI/custom_nodes/rgthree-comfy/web/lib/tree-sitter.wasm'} <= selected.keys())

    def test_generic_defaults_wasm_and_version_markers_are_not_approved(self):
        for relative in ('scripts/config.json.default', 'scripts/custom.wasm',
                         'scripts/COMMIT_ID', 'scripts/UPDATER_VERSION',
                         DEFAULT.replace('rgthree-comfy', 'other'),
                         DEFAULT.upper()):
            with self.subTest(relative=relative):
                self.assertIsNotNone(importer.rejection(relative))
                self.assertFalse(snapshot.supported_source_payload(relative))

    def test_config_exception_is_exact_not_directory_wide(self):
        for relative in (TRAINER + '/vendor/sd-scripts/configs/other/config.json',
                         TRAINER + '/vendor/sd-scripts/configs/qwen3_06b/secrets.json',
                         TRAINER + '/vendor/sd-scripts/configs/qwen3_06b/CONFIG.JSON',
                         VITE.rsplit('/', 1)[0] + '/config.json'):
            with self.subTest(relative=relative):
                self.assertTrue(snapshot.private_config(relative))
                self.assertIsNotNone(importer.rejection(relative))

    def test_support_path_never_waives_credential_scan(self):
        synthetic = ('sk-' + 'R8' * 20).encode()
        for relative in (VITE, DEFAULT, *sorted(PUBLIC_CONFIGS),
                         'ComfyUI/custom_nodes/rgthree-comfy/web/lib/tree-sitter.wasm'):
            self.source(relative, b'public prefix ' + synthetic)
        review = importer.plan(self.runtime, self.repo)
        self.assertEqual(review['new_files'], 0)
        self.assertTrue(all(row['status'] == 'security_quarantine' for row in review['records']))
        self.assertNotIn(synthetic.decode(), json.dumps(review))
        self.assertEqual(importer.apply_plan(review, review['review_sha256'], self.repo)['files'], 0)

    def test_reviewed_config_drift_is_rejected_before_import(self):
        relative = sorted(PUBLIC_CONFIGS)[0]
        source = self.source(relative, b'{"model_type":"qwen3"}')
        review = importer.plan(self.runtime, self.repo)
        source.write_bytes(b'{"model_type":"changed"}')
        with self.assertRaises(RuntimeError):
            importer.apply_plan(review, review['review_sha256'], self.repo)
        self.assertFalse((self.repo / 'snapshot').exists())

    def test_reviewed_support_never_overwrites_main_source(self):
        self.source(VITE, b'installed build\n')
        target = self.repo / 'snapshot' / importer.payload_relative(VITE)
        target.parent.mkdir(parents=True)
        target.write_bytes(b'newer main build\n')
        review = importer.plan(self.runtime, self.repo)
        self.assertEqual(review['records'][0]['status'], 'existing_different_skip')
        self.assertEqual(importer.apply_plan(review, review['review_sha256'], self.repo)['files'], 0)
        self.assertEqual(target.read_bytes(), b'newer main build\n')

    def test_model_and_database_payloads_remain_outside(self):
        for relative in ('scripts/hand.task', 'scripts/body.torchscript',
                         'scripts/MANO_RIGHT.pkl', 'scripts/mesh.npy', 'scripts/mesh.npz',
                         'scripts/model.safetensors', 'scripts/tags_cache.db',
                         TRAINER + '/vendor/sd-scripts/configs/t5_old/spiece.model'):
            with self.subTest(relative=relative):
                self.assertIsNotNone(importer.rejection(relative))
                self.source(relative)
        self.assertEqual(importer.plan(self.runtime, self.repo)['new_files'], 0)

    def test_license_match_does_not_admit_disguised_binaries(self):
        for name in ('LICENSE-MIT', 'LICENSE-Pixart', 'NOTICE-MHR', 'LICENSE_1', 'THIRD_PARTY_NOTICES'):
            self.assertTrue(snapshot.source_license_name(name))
        for name in ('LICENSE.exe', 'LICENSE-MIT.dll', 'NOTICE-MHR.key', 'LICENSE-MIT.wasm'):
            self.assertFalse(snapshot.source_license_name(name))
            self.assertIsNotNone(importer.rejection('scripts/' + name))

    def test_support_symlink_is_not_followed(self):
        outside = self.source('other/real.mts')
        link = self.runtime / VITE
        link.parent.mkdir(parents=True)
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        review = importer.plan(self.runtime, self.repo)
        self.assertEqual(review['new_files'], 0)
        self.assertEqual(review['records'][0]['reason'], 'linked_path_not_followed')

    def test_forged_support_path_escape_is_rejected(self):
        self.source(VITE)
        review = importer.plan(self.runtime, self.repo)
        modified = copy.deepcopy(review)
        modified['records'][0]['source'] = '../outside.mts'
        modified.pop('review_sha256')
        modified['review_sha256'] = importer.canonical_hash(modified)
        with self.assertRaises(ValueError):
            importer.apply_plan(modified, modified['review_sha256'], self.repo)

    def test_registered_support_contract_is_complete_and_keeps_assets_external(self):
        repo = Path(__file__).resolve().parents[1]
        spec = json.loads((repo / 'governance/runtime-support.json').read_text(encoding='utf-8'))
        manifest = json.loads((repo / 'snapshot/manifest.json').read_text(encoding='utf-8'))
        sources = {entry['source']: entry for entry in manifest['files']}
        self.assertEqual(len(spec['public_sources']), 25)
        self.assertEqual(len(set(spec['public_sources'])), 25)
        for relative in spec['public_sources']:
            with self.subTest(relative=relative):
                self.assertIsNone(importer.rejection(relative))
                entry = sources[relative]
                self.assertEqual(entry['kind'], 'file')
                self.assertEqual(snapshot.digest(repo / 'snapshot' / entry['path']), entry['sha256'])
        self.assertEqual(len(spec['external_resources']), 11)
        for entry in spec['external_resources']:
            if entry['category'] == 'mutable_db':
                self.assertEqual(sources[entry['source']]['kind'], 'sqlite_sql')
                self.assertEqual(sources[entry['source']]['sql_format'], 'gallery_fts5_v1')
            else:
                self.assertNotIn(entry['source'], sources)
            self.assertIsNotNone(importer.rejection(entry['source']))
            self.assertFalse((repo / 'snapshot/runtime' / entry['source']).exists())


if __name__ == '__main__':
    unittest.main()
