import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import project
import snapshot


class SourceAuthorityTests(unittest.TestCase):
    def make_repo(self, root):
        repo = root / 'repo'
        file = repo / 'snapshot/runtime/ComfyUI/main.py'
        file.parent.mkdir(parents=True)
        file.write_bytes(b'original\n')
        snapshot.save(repo / 'snapshot/manifest.json', {
            'source_root': str(root / 'production'), 'created_at': 'before',
            'files': project.source_entries(repo), 'runtime_before': {'old': True}, 'runtime_after': {'old': True},
        })
        return repo, file

    def test_source_edit_can_be_sealed_without_touching_production(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, file = self.make_repo(root)
            file.write_bytes(b'edited\n')
            self.assertEqual(project.status(repo)['changed'], ['ComfyUI/main.py'])
            result = project.seal('Isolated source edit', repo)
            self.assertTrue(result['updated'])
            self.assertFalse((root / 'production').exists())
            manifest = json.loads((repo / 'snapshot/manifest.json').read_text())
            self.assertIsNone(manifest['runtime_after'])
            self.assertFalse(manifest['development_revision']['live_deployed'])
            self.assertTrue(snapshot.verify(repo / 'snapshot')['pass'])

    def test_new_private_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo, file = self.make_repo(Path(temp))
            (file.parent / 'providers.json').write_text('{}')
            with self.assertRaises(ValueError):
                project.seal('No private config', repo)

    def test_failed_seal_preserves_old_manifest_and_working_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            repo, file = self.make_repo(Path(temp))
            original = (repo / 'snapshot/manifest.json').read_bytes()
            # Constructed fixture is never a live credential.
            file.write_text('api_key = "' + 'sk-' + 'A9' * 24 + '"')
            with self.assertRaises(RuntimeError):
                project.seal('Reject unsafe revision', repo)
            self.assertEqual((repo / 'snapshot/manifest.json').read_bytes(), original)
            self.assertIn('api_key', file.read_text())

    def test_plan_is_read_only_and_cannot_target_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, file = self.make_repo(root)
            result = project.deploy_plan(root / 'production', repo)
            self.assertEqual(result['mode'], 'READ_ONLY_PLAN')
            self.assertEqual(len(result['changes']), 1)
            self.assertFalse((root / 'production').exists())
            with self.assertRaises(ValueError):
                project.deploy_plan(repo, repo)

    def test_plan_rejects_unsealed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, file = self.make_repo(root)
            file.write_bytes(b'new unsealed source')
            with self.assertRaises(RuntimeError):
                project.deploy_plan(root/'production', repo)

    def test_removed_source_remains_in_plan_across_seals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, file = self.make_repo(root)
            live = root/'production/ComfyUI/main.py'
            live.parent.mkdir(parents=True)
            live.write_bytes(file.read_bytes())
            file.unlink()
            project.seal('Remove old source', repo)
            (file.parent/'new.py').write_text('new source')
            project.seal('Additional source', repo)
            result = project.deploy_plan(root/'production', repo)
            removed = [row for row in result['changes'] if row['operation'] == 'delete_requires_review']
            self.assertEqual(removed[0]['source'], 'ComfyUI/main.py')
            self.assertEqual(live.read_bytes(), b'original\n')


if __name__ == '__main__':
    unittest.main()
