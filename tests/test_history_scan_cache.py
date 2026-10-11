"""History reuse must preserve the findings of an uncached publication scan."""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location('history_tests_' + name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load('security_guard')
storage = load('staged_scan_cache')


class HistoryCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Cache Tests')
        self.git('config', 'user.email', 'tests@local.invalid')
        self.write('README.md', b'Neutral documentation.\n')
        self.commit('Baseline', 'README.md')
        self.cache = self.repo / '.git' / storage.HistoryCache.name

    def git(self, *args, input_data=None):
        result = subprocess.run(['git', '-C', str(self.repo), *args], input=input_data, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result.stdout

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def commit(self, message, *paths):
        self.git('add', '--', *paths)
        self.git('commit', '-qm', message)

    def scan(self):
        return guard.run(self.repo, cache_history=True)

    @staticmethod
    def secret():
        return b'sk-' + b'A1b2C3d4E5f6G7h8' * 3

    def assert_equivalent(self, result):
        fresh = guard.run(self.repo)
        for key in ('pass', 'findings', 'scanned_objects', 'scanned_bytes',
                    'cross_part_boundaries', 'reviewed_fixtures', 'compressed_objects'):
            self.assertEqual(result[key], fresh[key], key)
        self.assertNotIn(self.secret().decode(), json.dumps(result))

    def test_cold_warm_and_new_commit_reuse_only_unchanged_objects(self):
        cold = self.scan()
        warm = self.scan()
        self.assertTrue(cold['pass'] and warm['pass'])
        self.assertEqual(warm['cache']['reused_objects'], cold['scanned_objects'])
        self.assertEqual(warm['cache']['content_scanned_bytes'], 0)
        self.assertTrue(warm['cache']['all_object_bytes_rehashed'])
        self.assert_equivalent(warm)
        self.write('new.txt', b'New reviewed content\n')
        self.commit('Add content', 'new.txt')
        incremental = self.scan()
        self.assertEqual(incremental['cache']['content_scanned_objects'], 2)
        self.assertEqual(incremental['cache']['reused_objects'], cold['scanned_objects'])
        self.assert_equivalent(incremental)
        raw = self.cache.read_bytes()
        for private in (b'Neutral documentation', b'README.md', b'Add content'):
            self.assertNotIn(private, raw)

    def test_deleted_historical_secret_is_checked_and_failure_does_not_save(self):
        self.scan()
        before = self.cache.read_bytes()
        self.write('old.txt', self.secret())
        self.commit('Historical fixture', 'old.txt')
        self.git('rm', 'old.txt')
        self.git('commit', '-qm', 'Remove fixture')
        self.assertTrue(guard.run(self.repo, staged=True)['pass'])
        result = self.scan()
        self.assertFalse(result['pass'])
        self.assertFalse(result['cache']['written'])
        self.assertEqual(before, self.cache.read_bytes())
        self.assert_equivalent(result)

    def test_cached_blob_new_forbidden_historical_alias_is_rejected(self):
        self.scan()
        self.git('mv', 'README.md', 'credentials.json')
        self.git('commit', '-qm', 'Rename fixture')
        self.git('mv', 'credentials.json', 'README.md')
        self.git('commit', '-qm', 'Restore name')
        result = self.scan()
        self.assertFalse(result['pass'])
        self.assertIn('private_credential_file', {f['rule'] for f in result['findings']})
        self.assert_equivalent(result)

    def test_new_commit_message_is_scanned(self):
        self.scan()
        self.git('commit', '--allow-empty', '-qm', self.secret().decode())
        result = self.scan()
        self.assertFalse(result['pass'])
        self.assert_equivalent(result)

    def test_new_tag_message_is_scanned(self):
        self.scan()
        self.git('tag', '-a', 'fixture', '-m', self.secret().decode())
        result = self.scan()
        self.assertFalse(result['pass'])
        self.assert_equivalent(result)

    def test_current_ref_names_are_checked_on_warm_cache(self):
        self.scan()
        self.git('branch', 'fixture-' + self.secret().decode())
        result = self.scan()
        self.assertFalse(result['pass'])
        self.assert_equivalent(result)

    def test_cached_parts_new_manifest_order_is_checked(self):
        token = self.secret()
        for name, data in [('c', token[:20]), ('a', token[20:]), ('b', b' unrelated separator ')]:
            self.write('snapshot/library/data/' + name + '.part', data)
        def manifest(order):
            return json.dumps({'files': [{'path': 'library/data', 'parts': [{'path': p + '.part'} for p in order]}]}).encode()
        self.write('snapshot/manifest.json', manifest('cba'))
        self.commit('Safe split order', 'snapshot')
        self.assertTrue(self.scan()['pass'])
        self.write('snapshot/manifest.json', manifest('cab'))
        self.commit('Change split order', 'snapshot/manifest.json')
        result = self.scan()
        self.assertFalse(result['pass'])
        self.assertGreaterEqual(result['cache']['reused_objects'], 3)
        self.assertIn('cross_part_openai_style_key', {f['rule'] for f in result['findings']})
        self.assert_equivalent(result)

    def test_compressed_and_reviewed_payloads_always_rescan(self):
        self.write('plain.txt.gz', gzip.compress(b'ordinary compressed text'))
        self.write('fixture.txt', self.secret())
        self.commit('Reviewed fixtures', 'plain.txt.gz', 'fixture.txt')
        sha = hashlib.sha256(self.secret()).hexdigest()
        with mock.patch.dict(guard.REVIEWED_FIXTURES, {sha: 'synthetic'}), \
                mock.patch.dict(guard.FIXTURE_ENDS, {sha: 'fixture.txt'}):
            self.assertTrue(self.scan()['pass'])
            warm = self.scan()
            self.assertTrue(warm['pass'])
            self.assertEqual(warm['cache']['content_scanned_objects'], 2)
            self.assertEqual(len(warm['reviewed_fixtures']), 1)
            self.assertEqual(len(warm['compressed_objects']), 1)
            self.assert_equivalent(warm)
        self.assertFalse(self.scan()['pass'])

    def test_policy_change_invalidates_all_cached_content(self):
        self.scan()
        with mock.patch.dict(guard.STRONG, {'new_rule': re.compile(b'Neutral')}), \
                mock.patch.dict(guard.RULE_NEEDLES, {'new_rule': (b'Neutral',)}):
            result = self.scan()
        self.assertFalse(result['pass'])
        self.assertEqual(result['cache']['state'], 'policy_changed')
        self.assertEqual(result['cache']['reused_objects'], 0)

    def test_historical_path_exception_is_not_cached(self):
        raw = b'Reviewed historical metadata only\n'
        sha = hashlib.sha256(raw).hexdigest()
        self.write('credentials.json', raw)
        self.commit('Historical path fixture', 'credentials.json')
        with mock.patch.dict(guard.REVIEWED_HISTORICAL_PATHS, {('credentials.json', sha): 'synthetic'}):
            self.assertTrue(self.scan()['pass'])
            warm = self.scan()
            self.assertTrue(warm['pass'])
            self.assertEqual(warm['cache']['content_scanned_objects'], 1)
            self.assertEqual(len(warm['reviewed_fixtures']), 1)

    def test_new_gitlink_is_rejected_after_cache_warmup(self):
        self.scan()
        oid = self.git('rev-parse', 'HEAD').decode().strip()
        self.git('update-index', '--add', '--cacheinfo', '160000', oid, 'nested')
        self.git('commit', '-qm', 'Gitlink fixture')
        result = self.scan()
        self.assertFalse(result['pass'])
        self.assertIn('nested_gitlink', {f['rule'] for f in result['findings']})
        self.assert_equivalent(result)

    def test_registry_uses_head_not_worktree_or_index(self):
        self.scan()
        self.write(guard.TRAINING_REVIEW_FILE, json.dumps({'schema': 1, 'review_type': guard.TRAINING_REVIEW_TYPE, 'entries': []}).encode())
        self.git('add', guard.TRAINING_REVIEW_FILE)
        self.assertEqual(self.scan()['cache']['state'], 'warm')
        self.git('commit', '-qm', 'Review registry')
        result = self.scan()
        self.assertTrue(result['pass'])
        self.assertEqual(result['cache']['state'], 'policy_changed')
        self.assertEqual(result['cache']['reused_objects'], 0)

    def test_corruption_and_digest_mismatch_fall_back_to_history_not_index(self):
        self.scan()
        self.cache.write_bytes(b'broken metadata')
        result = self.scan()
        self.assertTrue(result['pass'])
        self.assertEqual(result['cache']['state'], 'invalid_full_rescan')
        data = json.loads(self.cache.read_bytes())
        data['payload']['records'] = {key: '0' * 64 for key in data['payload']['records']}
        data['checksum'] = storage.digest(storage.canonical(data['payload']))
        self.cache.write_bytes(storage.canonical(data))
        self.write('old.txt', self.secret())
        self.commit('Historical fixture', 'old.txt')
        self.git('rm', 'old.txt')
        self.git('commit', '-qm', 'Remove fixture')
        result = self.scan()
        self.assertFalse(result['pass'])
        self.assertEqual(result['cache']['state'], 'digest_mismatch_full_rescan')
        self.assert_equivalent(result)

    def test_staged_and_foreign_repository_caches_cannot_seed_history(self):
        guard.run(self.repo, staged=True, use_cache=True)
        shutil.copyfile(self.repo / '.git' / storage.NAME, self.cache)
        result = self.scan()
        self.assertEqual(result['cache']['reused_objects'], 0)
        self.assertEqual(result['cache']['state'], 'policy_changed')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        clone = Path(temp.name) / 'clone'
        self.git('clone', '--no-hardlinks', str(self.repo), str(clone))
        shutil.copyfile(self.cache, clone / '.git' / storage.HistoryCache.name)
        foreign = guard.run(clone, cache_history=True)
        self.assertTrue(foreign['pass'])
        self.assertEqual(foreign['cache']['state'], 'policy_changed')
        self.assertEqual(foreign['cache']['reused_objects'], 0)

    def test_ref_and_policy_drift_prevent_save(self):
        original = guard.scan_objects
        for kind in ('refs', 'policy'):
            with self.subTest(kind=kind):
                self.scan()
                before = self.cache.read_bytes()
                def mutate(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if kind == 'refs':
                        self.git('branch', 'concurrent')
                    else:
                        guard.MAX_BLOB += 1
                    return result
                limit = guard.MAX_BLOB
                try:
                    with mock.patch.object(guard, 'scan_objects', mutate):
                        result = self.scan()
                finally:
                    guard.MAX_BLOB = limit
                self.assertFalse(result['pass'])
                self.assertFalse(result['cache']['written'])
                self.assertEqual(before, self.cache.read_bytes())

    def test_history_store_rejects_hardlinks_and_supports_repository_size(self):
        self.scan()
        linked = self.repo / 'saved-cache.json'
        os.link(self.cache, linked)
        before = linked.read_bytes()
        result = self.scan()
        self.assertTrue(result['pass'])
        self.assertFalse(result['cache']['written'])
        self.assertEqual(result['cache']['reused_objects'], 0)
        self.assertEqual(linked.read_bytes(), before)
        self.cache.unlink()
        cache = storage.HistoryCache(self.repo / '.git', 'a' * 64)
        cache.pending = {hashlib.sha256(str(i).encode()).hexdigest(): 'b' * 64 for i in range(70000)}
        cache.save()
        self.assertTrue(cache.written)
        self.assertGreater(self.cache.stat().st_size, storage.LIMIT)
        loaded = storage.HistoryCache(self.repo / '.git', 'a' * 64)
        self.assertEqual(len(loaded.records), 70000)

    def test_pre_push_cache_roots_and_uncached_default(self):
        oid = self.git('rev-parse', 'HEAD').decode().strip()
        record = f'refs/heads/main {oid} refs/heads/main ' + '0' * 40
        self.assertNotIn('cache', guard.run_pre_push(self.repo, record))
        self.assertFalse(self.cache.exists())
        cold = guard.run_pre_push(self.repo, record, cache_history=True)
        warm = guard.run_pre_push(self.repo, record, cache_history=True)
        self.assertTrue(cold['pass'] and warm['pass'])
        self.assertEqual(warm['mode'], 'pre-push')
        self.assertEqual(warm['cache']['reused_objects'], cold['scanned_objects'])
        orphan = self.git('hash-object', '-w', '--stdin', input_data=b'unreferenced').decode().strip()
        self.assertFalse(guard.run_pre_push(self.repo, record.replace(oid, orphan), cache_history=True)['pass'])
        deletion = guard.run_pre_push(self.repo, '(delete) ' + '0' * 40 + f' refs/heads/old {oid}', cache_history=True)
        self.assertTrue(deletion['pass'])
        self.assertNotIn('cache', deletion)

    def test_cli_refuses_partial_scan_cache_combinations(self):
        for flags in [('--staged',), ('--all-history', '--names-only'),
                      ('--all-history', '--audit-content-only'), ('--pre-push', '--cache-staged')]:
            with self.subTest(flags=flags):
                result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'security_guard.py'),
                                         '--repo', str(self.repo), '--cache-history', *flags], capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(json.loads(result.stdout)['pass'])


if __name__ == '__main__':
    unittest.main()
