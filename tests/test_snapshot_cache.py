import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import project
import snapshot
import snapshot_cache


class SnapshotFingerprintTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / 'repo'
        self.root = self.repo / 'snapshot'
        self.root.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, capture_output=True)
        self.a = self.root / 'runtime/ComfyUI/a.py'
        self.b = self.root / 'runtime/ComfyUI/plugin/b.py'
        for file, data in ((self.a, b'alpha\n'), (self.b, b'bravo\n')):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        self.write_manifest()

    def write_manifest(self, extras=()):
        snapshot.save(self.root / 'manifest.json', {
            'source_root': str(self.repo.parent / 'production'),
            'files': project.source_entries(self.repo) + list(extras)})

    def cache(self):
        return snapshot_cache.SnapshotCache(self.root, self.repo / '.git')

    def verify(self):
        return snapshot.verify(self.root, cache=self.cache())

    def test_unchanged_files_and_directories_skip_hash_and_content_work(self):
        self.assertTrue(self.verify()['pass'])
        warm = self.verify()
        self.assertTrue(warm['pass'])
        self.assertEqual(warm['cache']['hashed_files'], 0)
        self.assertEqual(warm['cache']['content_scanned_files'], 0)
        self.assertEqual(warm['cache']['unchanged_directories'], warm['cache']['directory_count'])
        self.assertGreater(warm['cache']['directory_count'], 1)
        self.assertEqual(warm['failures'], snapshot.verify(self.root)['failures'])

    def test_one_changed_file_reads_only_it_and_new_manifest(self):
        self.verify()
        self.a.write_bytes(b'edited\n')
        self.write_manifest()
        result = self.verify()
        self.assertTrue(result['pass'])
        self.assertEqual(result['cache']['hashed_files'], 2)
        self.assertEqual(result['cache']['content_scanned_files'], 2)
        self.assertEqual(result['cache']['reused_content_scans'], 1)
        self.assertGreater(result['cache']['unchanged_directories'], 0)

    def test_same_size_edit_with_restored_mtime_is_detected(self):
        self.verify()
        before = self.a.stat()
        self.a.write_bytes(b'ALPHA\n')
        os.utime(self.a, ns=(before.st_atime_ns, before.st_mtime_ns))
        result = self.verify()
        self.assertFalse(result['pass'])
        self.assertIn('hash_mismatch', {f['reason'] for f in result['failures']})

    def test_rename_rechecks_path_and_deletion_is_detected(self):
        self.verify()
        self.a.rename(self.a.with_name('renamed.py'))
        result = self.verify()
        self.assertFalse(result['pass'])
        self.assertIn('unlisted_payload', {f['reason'] for f in result['failures']})
        self.write_manifest()
        self.assertTrue(self.verify()['pass'])
        self.b.unlink()
        self.assertFalse(self.verify()['pass'])

    def test_added_unlisted_file_is_not_hidden_by_directory_cache(self):
        self.verify()
        self.a.with_name('extra.py').write_bytes(b'new\n')
        self.assertIn('unlisted_payload', {f['reason'] for f in self.verify()['failures']})

    def test_renamed_private_path_is_rejected_even_with_same_content(self):
        self.verify()
        self.a.rename(self.a.with_name('providers.json'))
        result = self.verify()
        self.assertFalse(result['pass'])
        self.assertIn('private_config_payload', {f['reason'] for f in result['failures']})

    def test_changed_secret_is_scanned_and_failure_does_not_update_cache(self):
        self.verify()
        cache_file = self.cache().path
        before = cache_file.read_bytes()
        self.a.write_text('api_key = "' + 'sk-' + 'A9' * 24 + '"', encoding='utf-8')
        self.write_manifest()
        result = self.verify()
        self.assertFalse(result['pass'])
        self.assertFalse(result['cache']['written'])
        self.assertEqual(cache_file.read_bytes(), before)

    def test_corrupted_and_changed_policy_caches_fall_back(self):
        self.verify()
        self.cache().path.write_bytes(b'incomplete')
        result = self.verify()
        self.assertTrue(result['pass'])
        self.assertEqual(result['cache']['state'], 'invalid_full_rescan')
        self.assertGreater(result['cache']['hashed_files'], 0)
        with mock.patch.object(snapshot_cache, 'policy', return_value='f' * 64):
            changed = self.verify()
        self.assertEqual(changed['cache']['state'], 'policy_changed')
        self.assertEqual(changed['cache']['reused_content_scans'], 0)

    def test_copied_cache_from_another_checkout_cannot_reuse(self):
        self.verify()
        other = self.repo.parent / 'other'
        shutil.copytree(self.repo, other)
        cache = snapshot_cache.SnapshotCache(other / 'snapshot', other / '.git')
        self.assertEqual(cache.state, 'policy_changed')
        result = snapshot.verify(other / 'snapshot', cache=cache)
        self.assertTrue(result['pass'])
        self.assertEqual(result['cache']['reused_content_scans'], 0)

    def test_unreliable_metadata_always_reads_and_scans(self):
        self.verify()
        with mock.patch.object(snapshot_cache, 'signature', return_value=None):
            result = self.verify()
        self.assertTrue(result['pass'])
        self.assertEqual(result['cache']['reused_content_scans'], 0)
        self.assertGreater(result['cache']['hashed_files'], 0)

    def test_joined_chunks_reuse_but_reordering_does_not(self):
        folder = self.root / 'library/content'
        folder.mkdir(parents=True)
        parts = []
        for name, content in (('one.part', b'one\n'), ('two.part', b'two\n')):
            (folder / name).write_bytes(content)
            parts.append({'path': name, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
        entry = {'source': 'content.txt', 'path': 'library/content', 'kind': 'chunks',
                 'parts': parts, 'sha256': hashlib.sha256(b'one\ntwo\n').hexdigest()}
        self.write_manifest([entry])
        self.assertTrue(self.verify()['pass'])
        self.assertEqual(self.verify()['cache']['reused_joined_hashes'], 1)
        entry['parts'] = list(reversed(parts))
        self.write_manifest([entry])
        result = self.verify()
        self.assertFalse(result['pass'])
        self.assertIn('joined_hash_mismatch', {f['reason'] for f in result['failures']})

    def test_file_changes_during_scan_are_rejected(self):
        original = snapshot.scan
        def mutate(file):
            result = original(file)
            if file == self.a:
                file.write_bytes(b'replaced during scan\n')
            return result
        with mock.patch.object(snapshot, 'scan', side_effect=mutate):
            with self.assertRaises(RuntimeError):
                self.verify()
        self.assertFalse(self.cache().path.exists())

    def test_noop_seal_uses_cache_and_fresh_mode_remains_full(self):
        self.verify()
        result = project.seal('No source changes', self.repo)
        self.assertFalse(result['updated'])
        self.assertEqual(result['cache']['hashed_files'], 0)
        self.assertNotIn('cache', project.seal('Explicit full check', self.repo, fresh=True))

    def test_change_between_manifest_hash_and_later_scan_is_rejected(self):
        original = snapshot.scan
        def mutate_later(file):
            result = original(file)
            if file == self.a:
                self.b.write_bytes(b'changed after manifest check\n')
            return result
        with mock.patch.object(snapshot, 'scan', side_effect=mutate_later):
            with self.assertRaises(RuntimeError):
                self.verify()
        self.assertFalse(self.cache().path.exists())

    def test_manifest_change_after_parse_is_rejected(self):
        original = json.loads
        def mutate_manifest(data, *args, **kwargs):
            result = original(data, *args, **kwargs)
            if isinstance(result, dict) and 'source_root' in result:
                (self.root / 'manifest.json').write_text('{"files":[]}', encoding='utf-8')
            return result
        with mock.patch.object(snapshot.json, 'loads', side_effect=mutate_manifest):
            with self.assertRaises(RuntimeError):
                self.verify()
        self.assertFalse(self.cache().path.exists())

    def test_scoped_deploy_plan_excludes_unrelated_runtime_files(self):
        self.verify()
        runtime = self.repo.parent / 'production'
        plan = project.deploy_plan(runtime, self.repo, scopes=('ComfyUI/plugin',))
        self.assertEqual([r['source'] for r in plan['changes']], ['ComfyUI/plugin/b.py'])
        self.assertEqual(plan['cache']['hashed_files'], 0)
        for bad in ('../outside', '/absolute', 'ComfyUI/../outside'):
            with self.assertRaises(ValueError):
                project.deploy_plan(runtime, self.repo, scopes=(bad,))


if __name__ == '__main__':
    unittest.main()
