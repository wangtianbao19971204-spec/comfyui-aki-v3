import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import import_workspace_sources as importer
import security_guard


class SourceImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        self.repo = self.root / 'repo'
        self.runtime.mkdir()
        self.repo.mkdir()

    def source(self, relative='scripts/example.py', data=b'answer = 42\n'):
        target = self.runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def target(self, relative='scripts/example.py', data=b'existing\n'):
        target = self.repo / 'snapshot' / importer.payload_relative(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def plan(self):
        return importer.plan(self.runtime, self.repo)

    def apply(self, review):
        return importer.apply_plan(review, review['review_sha256'], self.repo)

    def test_import_is_byte_identical_and_does_not_modify_runtime(self):
        source = self.source()
        original = source.read_bytes()
        review = self.plan()
        self.assertEqual(review['new_files'], 1)
        self.assertFalse((self.repo / 'snapshot').exists())
        receipt = self.apply(review)
        target = self.repo / review['records'][0]['destination']
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(receipt['files'], 1)
        self.assertFalse(receipt['existing_main_files_modified'])
        self.assertFalse(receipt['deployed'])

    def test_existing_identical_and_different_paths_never_overwrite(self):
        self.source('scripts/same.py')
        self.source('scripts/different.py')
        same = self.target('scripts/same.py', b'answer = 42\n')
        different = self.target('scripts/different.py', b'authoritative edit\n')
        review = self.plan()
        self.assertEqual({row['status'] for row in review['records']},
                         {'existing_identical_skip', 'existing_different_skip'})
        self.assertEqual(self.apply(review)['files'], 0)
        self.assertEqual(same.read_bytes(), b'answer = 42\n')
        self.assertEqual(different.read_bytes(), b'authoritative edit\n')

    def test_review_mutation_and_wrong_hash_are_refused(self):
        self.source()
        review = self.plan()
        with self.assertRaises(ValueError):
            importer.apply_plan(review, '0' * 64, self.repo)
        modified = copy.deepcopy(review)
        modified['new_files'] += 1
        with self.assertRaises(ValueError):
            self.apply(modified)
        self.assertFalse((self.repo / 'snapshot').exists())

    def test_source_drift_preflights_all_files_before_writing(self):
        self.source('scripts/a.py')
        changed = self.source('scripts/b.py')
        review = self.plan()
        changed.write_bytes(b'changed = True\n')
        with self.assertRaises(RuntimeError):
            self.apply(review)
        self.assertFalse((self.repo / 'snapshot').exists())

    def test_new_target_appearing_after_review_is_refused(self):
        self.source()
        review = self.plan()
        appeared = self.target(data=b'concurrent main edit\n')
        with self.assertRaises(FileExistsError):
            self.apply(review)
        self.assertEqual(appeared.read_bytes(), b'concurrent main edit\n')

    def test_key_is_quarantined_without_value_in_report(self):
        synthetic = 'sk-' + 'Z8' * 20
        self.source(data=('api_key = "' + synthetic + '"\n').encode())
        review = self.plan()
        self.assertEqual(review['records'][0]['status'], 'security_quarantine')
        self.assertIn('openai_style_key', review['records'][0]['rules'])
        self.assertNotIn(synthetic, json.dumps(review))
        self.assertEqual(self.apply(review)['files'], 0)

    def test_private_data_weights_and_training_runs_are_not_imported(self):
        for relative in ('scripts/providers.json', 'scripts/runtime.json', 'scripts/model.safetensors',
                         'character_lora_forge/characters/person/private.py',
                         'character_lora_forge/runs/round1/private.py',
                         'anima_lora_forge/datasets/person/private.py',
                         'qwen21_lab/site_packages/dependency.py',
                         'remote_llm_guard/autodl_power_on.py'):
            self.source(relative)
        review = self.plan()
        self.assertEqual(review['new_files'], 0)
        self.assertEqual(self.apply(review)['files'], 0)

    def test_current_trainer_and_model_implementation_sources_are_imported(self):
        relative = importer.TRAINER + '/vendor/sd-scripts/library/anima_utils.py'
        self.source(relative)
        self.source('ComfyUI/custom_nodes/example/models/implementation.py')
        self.source(importer.LAB_CORE + '/comfy/ldm/current.py')
        self.source(importer.TRAINER + '/config/presets/anima/public.toml')
        self.source(importer.LAB_CORE + '/comfy_api/input/__init__.py')
        self.source(importer.LAB_CORE + '/input/user_image.py')
        self.assertEqual(self.plan()['new_files'], 5)

    def test_binary_model_payload_cannot_use_tokenizer_exception(self):
        self.source(importer.LAB_CORE + '/comfy/text_encoders/t5_pile_tokenizer/tokenizer.model', b'vocabulary')
        self.source(importer.LAB_CORE + '/comfy/weights.model', b'not a tokenizer')
        review = self.plan()
        self.assertEqual(review['new_files'], 1)

    def test_gitattributes_uses_inert_upstream_name(self):
        self.source('scripts/.gitattributes', b'* text eol=crlf\n')
        review = self.plan()
        self.assertTrue(review['records'][0]['destination'].endswith('/.gitattributes.upstream'))
        self.apply(review)
        self.assertFalse((self.repo / 'snapshot/runtime/scripts/.gitattributes').exists())

    def test_handcrafted_review_cannot_expand_explicit_owner_scope(self):
        self.source()
        outside = self.source('other/private.py', b'not selected\n')
        review = self.plan()
        row = review['records'][0]
        row.update(source='other/private.py', destination='snapshot/runtime/other/private.py',
                   source_sha256=hashlib.sha256(outside.read_bytes()).hexdigest(), bytes=outside.stat().st_size)
        del review['review_sha256']
        review['review_sha256'] = importer.canonical_hash(review)
        with self.assertRaises(ValueError):
            self.apply(review)

    def test_exact_reviewed_literal_requires_same_path_and_hash(self):
        data = ('token = "' + 'SYNTHETIC-' + 'A2b3C4' * 3 + '"\n').encode()
        self.source(data=data)
        digest = hashlib.sha256(data).hexdigest()
        with patch.dict(security_guard.REVIEWED_FIXTURES, {digest: 'synthetic source fixture'}), \
                patch.dict(security_guard.FIXTURE_ENDS, {digest: 'snapshot/runtime/scripts/example.py'}):
            review = self.plan()
            self.assertEqual(review['new_files'], 1)
            self.assertIn('reviewed_content', review['records'][0])
            self.source('scripts/other.py', data)
            self.assertEqual(self.plan()['new_files'], 1)
            self.source(data=data + b'# changed\n')
            self.assertEqual(self.plan()['new_files'], 0)

    def test_symlink_and_linked_parent_are_never_followed(self):
        original = self.source('other/target.py')
        link = self.runtime / 'scripts/link.py'
        link.parent.mkdir()
        try:
            link.symlink_to(original)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        review = self.plan()
        self.assertEqual(review['new_files'], 0)
        self.assertEqual(review['records'][0]['reason'], 'linked_path_not_followed')
        with self.assertRaises(ValueError):
            importer.safe_unlinked(self.runtime, 'scripts/link.py')

    def test_reports_are_exclusive_and_contained(self):
        path = importer.report_path('fixture.json', self.repo)
        importer.save_new(path, {'pass': True})
        with self.assertRaises(FileExistsError):
            importer.save_new(path, {})
        with self.assertRaises(ValueError):
            importer.report_path('../escape.json', self.repo)

    def test_public_summary_excludes_machine_and_private_state(self):
        self.source()
        self.source('scripts/runtime.json', b'{"pid": 999}')
        review = self.plan()
        receipt = self.apply(review)
        summary = importer.public_summary(review, [receipt])
        serialized = json.dumps(summary)
        self.assertEqual(summary['file_count'], 1)
        self.assertNotIn(str(self.runtime), serialized)
        self.assertNotIn('runtime.json', serialized)
        self.assertNotIn('"pid"', serialized)
        self.assertEqual(summary['files'][0]['source'], 'scripts/example.py')
        with self.assertRaises(ValueError):
            importer.public_summary(review, [receipt, receipt])


if __name__ == '__main__':
    unittest.main()
