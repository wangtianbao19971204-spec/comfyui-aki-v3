import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
SPEC = importlib.util.spec_from_file_location('cached_security_guard_tests', SCRIPTS / 'security_guard.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class StagedCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Cache Tests')
        self.git('config', 'user.email', 'tests@local.invalid')
        self.write('README.md', b'Neutral documentation.\n')
        self.git('add', 'README.md')
        self.git('commit', '-qm', 'Baseline')
        self.cache_path = self.repo / '.git/comfyui-staged-scan-v1.json'

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result.stdout

    def write(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def run_guard(self):
        return guard.run(self.repo, staged=True, use_cache=True)

    @staticmethod
    def secret():
        return b'sk-' + b'A1b2C3d4E5f6G7h8' * 3

    def test_cold_then_warm_keeps_byte_count_and_does_not_store_payload(self):
        cold = self.run_guard()
        warm = self.run_guard()
        self.assertTrue(cold['pass'] and warm['pass'])
        self.assertEqual(cold['cache']['reused_objects'], 0)
        self.assertEqual(warm['cache']['reused_objects'], 1)
        self.assertEqual(cold['scanned_bytes'], warm['scanned_bytes'])
        self.assertTrue(warm['cache']['all_object_bytes_rehashed'])
        self.assertNotIn(b'Neutral documentation', self.cache_path.read_bytes())
        self.assertNotIn(b'README.md', self.cache_path.read_bytes())

    def test_changed_staged_content_is_rescanned_not_worktree(self):
        self.run_guard()
        self.write('README.md', self.secret())
        self.git('add', 'README.md')
        self.write('README.md', b'Safe but not staged')
        report = self.run_guard()
        self.assertFalse(report['pass'])
        self.assertEqual(report['cache']['reused_objects'], 0)
        self.assertFalse(report['cache']['written'])
        self.assertNotIn(self.secret().decode(), json.dumps(report))

    def test_rename_invalidates_path_bound_hit(self):
        self.run_guard()
        self.git('mv', 'README.md', 'renamed.md')
        report = self.run_guard()
        self.assertTrue(report['pass'])
        self.assertEqual(report['cache']['reused_objects'], 0)

    def test_new_forbidden_alias_is_not_approved(self):
        self.run_guard()
        self.write('private/credentials.json', (self.repo / 'README.md').read_bytes())
        self.git('add', 'private')
        self.assertFalse(self.run_guard()['pass'])

    def test_policy_rule_change_invalidates_cache(self):
        self.run_guard()
        with mock.patch.dict(guard.STRONG, {'new_rule': re.compile(b'Neutral')}), mock.patch.dict(guard.RULE_NEEDLES, {'new_rule': (b'Neutral',)}):
            report = self.run_guard()
        self.assertFalse(report['pass'])
        self.assertEqual(report['cache']['state'], 'policy_changed')
        self.assertEqual(report['cache']['reused_objects'], 0)

    def test_exception_registry_is_index_bound(self):
        self.run_guard()
        raw = json.dumps({'schema': 1, 'review_type': guard.TRAINING_REVIEW_TYPE, 'entries': []}).encode()
        self.write(guard.TRAINING_REVIEW_FILE, raw)
        # Unstaged registry does not change the staged policy.
        self.assertEqual(self.run_guard()['cache']['reused_objects'], 1)
        self.git('add', guard.TRAINING_REVIEW_FILE)
        report = self.run_guard()
        self.assertTrue(report['pass'])
        self.assertEqual(report['cache']['state'], 'policy_changed')
        self.assertEqual(report['cache']['reused_objects'], 0)

    def test_manifest_order_is_checked_even_when_parts_hit_cache(self):
        token = self.secret()
        self.write('snapshot/library/data/c.part', token[:20])
        self.write('snapshot/library/data/a.part', token[20:])
        self.write('snapshot/library/data/b.part', b' unrelated separator ')
        def manifest(order):
            return json.dumps({'files': [{'path': 'library/data', 'parts': [{'path': p + '.part'} for p in order]}]}).encode()
        self.write('snapshot/manifest.json', manifest('cba'))
        self.git('add', 'snapshot')
        self.assertTrue(self.run_guard()['pass'])
        self.write('snapshot/manifest.json', manifest('cab'))
        self.git('add', 'snapshot/manifest.json')
        report = self.run_guard()
        self.assertFalse(report['pass'])
        self.assertGreaterEqual(report['cache']['reused_objects'], 3)
        self.assertIn('cross_part_openai_style_key', {f['rule'] for f in report['findings']})

    def test_compressed_payloads_always_rescan(self):
        self.write('plain.txt.gz', gzip.compress(b'ordinary compressed text'))
        self.git('add', 'plain.txt.gz')
        self.assertTrue(self.run_guard()['pass'])
        report = self.run_guard()
        self.assertTrue(report['pass'])
        self.assertEqual(report['cache']['reused_objects'], 1)
        self.assertEqual(len(report['compressed_objects']), 1)

    def test_reviewed_exception_is_not_cached(self):
        raw = self.secret()
        sha = hashlib.sha256(raw).hexdigest()
        self.write('fixture.txt', raw)
        self.git('add', 'fixture.txt')
        with mock.patch.dict(guard.REVIEWED_FIXTURES, {sha: 'synthetic'}), mock.patch.dict(guard.FIXTURE_ENDS, {sha: 'fixture.txt'}):
            self.assertTrue(self.run_guard()['pass'])
            warm = self.run_guard()
            self.assertEqual(warm['cache']['reused_objects'], 1)
            self.assertEqual(len(warm['reviewed_fixtures']), 1)
        self.assertFalse(self.run_guard()['pass'])

    def test_ref_names_rechecked_on_hit(self):
        self.run_guard()
        self.git('branch', 'fixture-' + self.secret().decode())
        report = self.run_guard()
        self.assertFalse(report['pass'])
        self.assertNotIn(self.secret().decode(), json.dumps(report))

    def test_corrupt_cache_falls_back_to_full_scan(self):
        self.run_guard()
        self.cache_path.write_bytes(b'not json')
        report = self.run_guard()
        self.assertTrue(report['pass'])
        self.assertEqual(report['cache']['state'], 'invalid_full_rescan')
        self.assertEqual(report['cache']['reused_objects'], 0)

    def test_checksum_corruption_falls_back(self):
        self.run_guard()
        data = json.loads(self.cache_path.read_bytes())
        data['checksum'] = '0' * 64
        self.cache_path.write_text(json.dumps(data))
        report = self.run_guard()
        self.assertTrue(report['pass'])
        self.assertEqual(report['cache']['state'], 'invalid_full_rescan')

    def test_object_digest_mismatch_falls_back_without_approval(self):
        self.run_guard()
        data = json.loads(self.cache_path.read_bytes())
        data['payload']['records'] = {key: '0' * 64 for key in data['payload']['records']}
        data['checksum'] = hashlib.sha256(json.dumps(data['payload'], sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        self.cache_path.write_text(json.dumps(data))
        report = self.run_guard()
        self.assertTrue(report['pass'])
        self.assertEqual(report['cache']['state'], 'digest_mismatch_full_rescan')
        self.assertEqual(report['cache']['reused_objects'], 0)

    def test_cache_does_not_follow_hardlinks(self):
        self.run_guard()
        other = self.repo / 'keep-copy.json'
        os.link(self.cache_path, other)
        before = other.read_bytes()
        report = self.run_guard()
        self.assertTrue(report['pass'])
        self.assertEqual(report['cache']['reused_objects'], 0)
        self.assertFalse(report['cache']['written'])
        self.assertEqual(other.read_bytes(), before)

    def test_cache_directory_is_not_removed(self):
        self.cache_path.mkdir()
        report = self.run_guard()
        self.assertTrue(report['pass'])
        self.assertFalse(report['cache']['written'])
        self.assertTrue(self.cache_path.is_dir())

    def test_alternate_index_is_checked(self):
        self.run_guard()
        alternate = self.repo / '.git/alternate-index'
        with mock.patch.dict(os.environ, {'GIT_INDEX_FILE': str(alternate)}):
            self.git('read-tree', 'HEAD')
            self.write('danger.txt', self.secret())
            self.git('add', 'danger.txt')
            self.assertFalse(self.run_guard()['pass'])
        self.assertTrue(self.run_guard()['pass'])

    def test_all_history_never_uses_staged_cache(self):
        self.run_guard()
        with self.assertRaises(ValueError):
            guard.run(self.repo, use_cache=True)
        with self.assertRaises(ValueError):
            guard.run(self.repo, staged=True, content_only=True, use_cache=True)
        self.write('old.txt', self.secret())
        self.git('add', 'old.txt')
        self.git('commit', '-qm', 'Historical fixture')
        self.git('rm', 'old.txt')
        self.git('commit', '-qm', 'Remove fixture')
        self.assertTrue(self.run_guard()['pass'])
        result = guard.run(self.repo)
        self.assertFalse(result['pass'])
        self.assertNotIn('cache', result)

    def test_policy_drift_prevents_cache_save(self):
        original = guard.StreamScanner.feed
        def changed(scanner, data):
            original(scanner, data)
            guard.MAX_BLOB += 1
        previous = guard.MAX_BLOB
        try:
            with mock.patch.object(guard.StreamScanner, 'feed', changed):
                report = self.run_guard()
        finally:
            guard.MAX_BLOB = previous
        self.assertFalse(report['pass'])
        self.assertFalse(report['cache']['written'])

    def test_index_drift_prevents_cache_save(self):
        original = guard.scan_objects
        def mutate(*args, **kwargs):
            report = original(*args, **kwargs)
            self.write('new.txt', b'concurrent staged edit')
            self.git('add', 'new.txt')
            return report
        with mock.patch.object(guard, 'scan_objects', mutate):
            report = self.run_guard()
        self.assertFalse(report['pass'])
        self.assertFalse(report['cache']['written'])

    def test_policy_code_fingerprint_changes(self):
        first = guard.staged_policy_fingerprint(None)
        with mock.patch.object(guard, 'OVERLAP', guard.OVERLAP + 1):
            self.assertNotEqual(first, guard.staged_policy_fingerprint(None))


if __name__ == '__main__':
    unittest.main()
