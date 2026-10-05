import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import repository
import security_guard
import snapshot

TRAINING_TARGET = 'docs/technical/archive/anima_lora_forge/profiles/bundle_character.json'


def training_payload(strong=False):
    value = ('sk-' if strong else 'character') + 'A1b2C3d4E5f6G7h8' * 3
    return json.dumps({'trigger_token': value}).encode()


def training_registry(data):
    return {'schema': 1, 'review_type': security_guard.TRAINING_REVIEW_TYPE, 'entries': [{
        'target': TRAINING_TARGET, 'sha256': hashlib.sha256(data).hexdigest(),
        'allowed_rules': [security_guard.TRAINING_REVIEW_RULE], 'confirmed': True,
        'reason': security_guard.TRAINING_REVIEW_REASON}]}


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root/'comfyui'
        self.repo.mkdir()
        self.patch = patch.object(repository, 'REPO', self.repo)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.make_snapshot(self.repo/'snapshot', b'original')
        (self.repo/'.gitignore').write_text('/local/\n', encoding='utf-8')
        repository.run_git('init', '-b', 'main')
        repository.run_git('config', 'core.autocrlf', 'false')
        repository.run_git('add', '.')
        self.commit()

    def commit(self):
        repository.run_git('-c', 'user.name=Maintenance Test', '-c', 'user.email=test@local.invalid', 'commit', '-qm', 'Test baseline')

    def adopt(self, candidate):
        repository.adopt(candidate, purpose='recovery-migration', reviewed_sha256=repository.changes(candidate)['review_sha256'])

    def make_snapshot(self, destination, payload, runtime=None):
        destination.mkdir()
        (destination/'source.txt').write_bytes(payload)
        snapshot.save(destination/'manifest.json', {
            'created_at': '2026-10-05', 'source_root': str(runtime or self.root/'live'),
            'files': [{'source': 'ComfyUI/main.py', 'path': 'source.txt', 'kind': 'file', 'sha256': snapshot.digest(destination/'source.txt'), 'bytes': len(payload)}],
        })
        return destination

    def test_compare_adopt_preserves_previous_and_does_not_touch_runtime(self):
        candidate = self.make_snapshot(self.root/'comfyui-candidate-one', b'new version')
        diff = repository.changes(candidate)
        self.assertEqual(diff['changed'], ['ComfyUI/main.py'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.adopt(candidate)
        self.assertFalse(candidate.exists())
        self.assertFalse((self.root/'live').exists())
        self.assertEqual((self.repo/'snapshot/source.txt').read_bytes(), b'new version')
        backups = list((self.repo/'local/backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0]/'source.txt').read_bytes(), b'original')

    def test_adopt_rejects_dirty_or_different_runtime(self):
        candidate = self.make_snapshot(self.root/'comfyui-candidate-two', b'new')
        (self.repo/'uncommitted.txt').write_text('keep me')
        with self.assertRaises(RuntimeError):
            self.adopt(candidate)
        self.assertTrue(candidate.exists())
        repository.run_git('add', 'uncommitted.txt')
        self.commit()
        foreign = self.make_snapshot(self.root/'comfyui-candidate-foreign', b'new', self.root/'other-runtime')
        with self.assertRaises(ValueError):
            self.adopt(foreign)

    def test_adopt_requires_review_bound_to_both_manifests(self):
        candidate = self.make_snapshot(self.root/'comfyui-candidate-review', b'new')
        with self.assertRaises(ValueError):
            repository.adopt(candidate)
        with self.assertRaises(ValueError):
            repository.adopt(candidate, purpose='recovery-migration', reviewed_sha256='stale')
        self.assertTrue(candidate.exists())
        self.assertEqual((self.repo/'snapshot/source.txt').read_bytes(), b'original')

    def test_bundle_rejects_deleted_historical_secret(self):
        secret = self.repo/'leaked.txt'
        secret.write_text('api_key = "' + 'sk-' + 'A9' * 24 + '"')
        repository.run_git('add', 'leaked.txt')
        self.commit()
        repository.run_git('rm', 'leaked.txt')
        self.commit()
        with self.assertRaises(RuntimeError):
            repository.bundle(self.root/'unsafe.bundle')
        self.assertFalse((self.root/'unsafe.bundle').exists())

    def test_candidate_location_guard(self):
        wrong = self.make_snapshot(self.root/'wrong-name', b'new')
        with self.assertRaises(ValueError):
            repository.validate_candidate(wrong)

    def test_compare_includes_external_model_inventory_changes(self):
        candidate = self.make_snapshot(self.root/'comfyui-candidate-models', b'original')
        snapshot.save(candidate/'models.json', {'model_count': 1})
        manifest=json.loads((candidate/'manifest.json').read_text(encoding='utf-8'))
        manifest['metadata_files']=[{'path':'models.json','sha256':snapshot.digest(candidate/'models.json')}]
        snapshot.save(candidate/'manifest.json',manifest)
        diff=repository.changes(candidate)
        self.assertEqual(diff['changed'], [])
        self.assertEqual(diff['metadata_added'], ['models.json'])

    def test_missing_tracked_payload_rejected_despite_gitignore(self):
        (self.repo/'.gitignore').write_text('/local/\n/snapshot/source.txt\n', encoding='utf-8')
        repository.run_git('rm', '--cached', '--', 'snapshot/source.txt')
        repository.run_git('add', '.gitignore')
        self.commit()
        self.assertFalse(repository.run_git('status', '--porcelain'))
        with self.assertRaises(RuntimeError):
            repository.bundle(self.root/'incomplete.bundle')
        self.assertFalse((self.root/'incomplete.bundle').exists())

    def test_bundle_clone_and_overwrite_guards(self):
        output = self.root/'comfyui.bundle'
        with contextlib.redirect_stdout(io.StringIO()):
            repository.bundle(output)
        restored = self.root/'cloned'
        subprocess.run(['git', 'clone', '-c', 'core.longpaths=true', str(output), str(restored)], check=True, capture_output=True)
        self.assertTrue(snapshot.verify(restored/'snapshot')['pass'])
        self.assertEqual((restored/'snapshot/source.txt').read_bytes(), b'original')
        with self.assertRaises(ValueError):
            repository.bundle(output)
        with self.assertRaises(ValueError):
            repository.bundle(self.repo/'inside.bundle')

    def add_training_archive(self, data=None, *, reviewed_data=None):
        data = training_payload() if data is None else data
        path = self.repo/TRAINING_TARGET
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        snapshot.save(self.repo/security_guard.TRAINING_REVIEW_FILE,
                      training_registry(data if reviewed_data is None else reviewed_data))
        repository.run_git('add', '--', TRAINING_TARGET, security_guard.TRAINING_REVIEW_FILE)
        self.commit()
        return path

    def test_reviewed_training_archive_survives_real_bundle_and_clone(self):
        data = training_payload()
        self.assertEqual(security_guard.patterns(data), {'literal_credential_assignment'})
        self.add_training_archive(data)
        output = self.root/'training.bundle'
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            repository.bundle(output)
        self.assertTrue(json.loads(captured.getvalue())['credential_history_gate'])
        restored = self.root/'training-clone'
        subprocess.run(['git', 'clone', '-c', 'core.longpaths=true', str(output), str(restored)],
                       check=True, capture_output=True)
        self.assertEqual((restored/TRAINING_TARGET).read_bytes(), data)
        self.assertTrue(snapshot.verify(restored/'snapshot')['pass'])
        with patch.object(repository, 'REPO', restored):
            self.assertGreater(repository.check_tracked()['tracked_files'], 0)
        report = security_guard.run(restored)
        self.assertTrue(report['pass'], report['findings'])
        self.assertTrue(any(item['rule'] == security_guard.TRAINING_REVIEW_TYPE
                            for item in report['reviewed_fixtures']))

    def test_training_archive_changed_bytes_are_rejected_before_bundle(self):
        self.add_training_archive(training_payload() + b'\n', reviewed_data=training_payload())
        with self.assertRaisesRegex(RuntimeError, 'literal_credential_assignment'):
            repository.check_tracked()
        output = self.root/'changed-training.bundle'
        with self.assertRaises(RuntimeError):
            repository.bundle(output)
        self.assertFalse(output.exists())

    def test_training_review_never_hides_strong_key_in_real_bundle(self):
        data = training_payload(strong=True)
        self.add_training_archive(data)
        with self.assertRaises(RuntimeError) as error:
            repository.check_tracked()
        self.assertIn('openai_style_key', str(error.exception))
        self.assertNotIn(json.loads(data)['trigger_token'], str(error.exception))
        output = self.root/'strong-key.bundle'
        with self.assertRaises(RuntimeError):
            repository.bundle(output)
        self.assertFalse(output.exists())

    def test_uncommitted_and_index_only_reviews_never_authorize_bundle(self):
        data = training_payload()
        path = self.repo/TRAINING_TARGET
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        empty = {'schema': 1, 'review_type': security_guard.TRAINING_REVIEW_TYPE, 'entries': []}
        registry_path = self.repo/security_guard.TRAINING_REVIEW_FILE
        snapshot.save(registry_path, empty)
        repository.run_git('add', '--', TRAINING_TARGET, security_guard.TRAINING_REVIEW_FILE)
        self.commit()
        snapshot.save(registry_path, training_registry(data))
        for staged in (False, True):
            with self.subTest(staged=staged):
                if staged:
                    repository.run_git('add', '--', security_guard.TRAINING_REVIEW_FILE)
                with self.assertRaisesRegex(RuntimeError, 'literal_credential_assignment'):
                    repository.check_tracked()
                output = self.root/('uncommitted-' + str(staged) + '.bundle')
                with self.assertRaises(RuntimeError):
                    repository.bundle(output)
                self.assertFalse(output.exists())
        self.commit()
        with contextlib.redirect_stdout(io.StringIO()):
            repository.bundle(self.root/'committed-review.bundle')

    def test_reviewed_archive_does_not_skip_other_non_snapshot_content(self):
        self.add_training_archive()
        other = self.repo/'docs/unreviewed.json'
        other.write_bytes(training_payload())
        repository.run_git('add', '--', 'docs/unreviewed.json')
        self.commit()
        with self.assertRaisesRegex(RuntimeError, 'literal_credential_assignment'):
            repository.check_tracked()
        output = self.root/'unreviewed-alias.bundle'
        with self.assertRaises(RuntimeError):
            repository.bundle(output)
        self.assertFalse(output.exists())

    def test_reviewed_archive_keeps_name_and_resource_gates(self):
        self.add_training_archive()
        unsafe_name = 'docs/' + 'sk-' + 'A9' * 24 + '.txt'
        for relative in ('docs/extra.safetensors', 'docs/.env', unsafe_name):
            with self.subTest(kind=Path(relative).suffix):
                path = self.repo/relative
                path.write_text('ordinary text', encoding='utf-8')
                repository.run_git('add', '--', relative)
                with self.assertRaisesRegex(RuntimeError, 'Tracked path gate failed') as error:
                    repository.check_tracked()
                self.assertNotIn(Path(unsafe_name).name, str(error.exception))
                repository.run_git('rm', '--cached', '--', relative)
                path.unlink()


if __name__ == '__main__':
    unittest.main()
