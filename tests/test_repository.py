import contextlib
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
import snapshot


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
            repository.adopt(candidate)
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
            repository.adopt(candidate)
        self.assertTrue(candidate.exists())
        repository.run_git('add', 'uncommitted.txt')
        self.commit()
        foreign = self.make_snapshot(self.root/'comfyui-candidate-foreign', b'new', self.root/'other-runtime')
        with self.assertRaises(ValueError):
            repository.adopt(foreign)

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
        subprocess.run(['git', 'clone', str(output), str(restored)], check=True, capture_output=True)
        self.assertTrue(snapshot.verify(restored/'snapshot')['pass'])
        self.assertEqual((restored/'snapshot/source.txt').read_bytes(), b'original')
        with self.assertRaises(ValueError):
            repository.bundle(output)
        with self.assertRaises(ValueError):
            repository.bundle(self.repo/'inside.bundle')


if __name__ == '__main__':
    unittest.main()
