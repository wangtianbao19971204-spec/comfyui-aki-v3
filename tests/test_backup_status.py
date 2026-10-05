import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import backup_status as backup


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class BackupStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.root = self.base / 'backup'
        self.companion = self.base / 'companion'
        self.index_path = self.base / 'index.json'
        self.commit = '1' * 40
        self.files = [self.payload(self.root, 'state/db.sqlite', b'synthetic database fixture', 'sqlite')]
        self.files[0]['target'] = 'db.sqlite'
        self.files[0]['database'] = {'integrity_check': 'ok', 'logical_sql_sha256': '2' * 64}
        self.files += [self.payload(self.root, 'state/settings.json', b'{"fixture": true}', 'file')]
        self.files[1]['target'] = 'settings.json'
        self.plan = {'schema': 1}
        plan_raw = self.write(self.root / 'plan.json', self.plan)
        self.state = {
            'pass': True, 'source_commit': self.commit, 'directory': 'state',
            'plan_sha256': digest(plan_raw), 'files': self.files, 'count': 2,
            'bytes': sum(row['bytes'] for row in self.files), 'checked_at': '2026-10-05T21:57:00+08:00',
        }
        source_file = self.payload(self.root, 'source.bundle', b'synthetic source bundle', 'file')
        companion_file = self.payload(self.companion, 'db.sqlite', b'synthetic companion', 'sqlite')
        companion_raw = self.write(self.companion / 'COMPANION_RECEIPT.json', {'pass': True})
        self.companion_report = {
            'pass': True, 'original_source_disk': 0, 'companion_disk': 2,
            'companion': str(self.companion), 'files': [companion_file],
            'count': 1, 'bytes': companion_file['bytes'],
        }
        self.source_copy = {'pass': True, 'source_commit': self.commit, 'files': [source_file]}
        self.final = {
            'schema': 1, 'pass': True, 'status': 'PASS_FOR_USER_APPROVED_CRITICAL_BACKUP_SCOPE',
            'batch_id': 'fixture', 'backup_root': str(self.root),
            'only_development_authority': str(self.repo), 'created_at': '2026-10-05T22:12:00+08:00',
            'source': {'commit': self.commit, 'version': '0.2.0', 'bundle': 'source.bundle',
                       'bundle_sha256': source_file['sha256'], 'bundle_bytes': source_file['bytes']},
            'accepted_current_state': {'receipt': 'state.json', 'plan': 'plan.json', 'directory': 'state',
                                      'payload_files': 2, 'payload_bytes': self.state['bytes'], 'sqlite_databases': 1},
            'validation': {'final_independent_recheck': 'recheck.json'},
            'privacy': {'ACL_receipt': 'acl.json'},
            'production_preservation': {'reviewed_guard': {'receipt': 'guard.json'}},
            'cross_physical_disk': {
                'main_and_g_sources_backed_up_to_D': True, 'drive_to_disk_number': {'G': 2, 'D': 0, 'C': 0},
                'c_drive_companion': {'receipt': 'companion.json', 'root': str(self.companion), 'files': 1,
                                     'companion_receipt_sha256': digest(companion_raw)},
            },
            'excluded': list(backup.EXCLUSIONS),
        }
        self.index = {
            'schema': 1, 'status': 'ACCEPTED_CRITICAL_SCOPE_BACKUP', 'main_git': str(self.repo),
            'batch_id': 'fixture', 'backup_root': str(self.root), 'final_receipt': str(self.root / 'final.json'),
        }
        self.extra_evidence = {}
        self.seal()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        return raw

    def payload(self, root, name, raw, kind):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {'target': name, 'bytes': len(raw), 'sha256': digest(raw), 'kind': kind}

    def seal(self):
        self.companion_report['parent_backup_receipt_sha256'] = digest(self.write(self.root / 'state.json', self.state))
        rows = {
            'state.json': self.state, 'plan.json': self.plan,
            'SOURCE_COPY_RECEIPT.json': self.source_copy,
            'SOURCE_CLONE_ACCEPTANCE.json': {'pass': True, 'commit': self.commit},
            'recheck.json': {'pass': True}, 'acl.json': {'pass': True}, 'guard.json': {'pass': True},
            'companion.json': self.companion_report,
            # A preserved failed attempt must not turn an accepted later snapshot into failure.
            'original-failed.json': {'pass': False}, **self.extra_evidence,
        }
        self.final['evidence'] = []
        for name, obj in rows.items():
            raw = self.write(self.root / name, obj)
            self.final['evidence'].append({'path': name, 'bytes': len(raw), 'sha256': digest(raw)})
        self.save_final()

    def save_final(self):
        self.index['final_receipt_sha256'] = digest(self.write(self.root / 'final.json', self.final))
        self.write(self.index_path, self.index)

    def query(self, **kwargs):
        return backup.inspect(self.repo, self.index_path, kwargs.get('head', self.commit), kwargs.get('clean', True))

    def test_valid_receipts_are_not_full_payload_or_runtime_acceptance(self):
        report = self.query()
        self.assertEqual(report['status'], 'accepted_receipt')
        self.assertTrue(report['current_checkout_covered'])
        self.assertTrue(report['receipt_chain_verified'])
        self.assertFalse(report['payload_sha256_rechecked'])
        self.assertFalse(report['physical_disks_rechecked'])
        self.assertFalse(report['live_data_freshness_checked'])
        self.assertFalse(report['automatic_actions'])
        self.assertEqual(report['payload_files'], 2)
        self.assertEqual(report['sqlite_databases'], 1)
        self.assertIn('未重算', '\n'.join(backup.lines(report)))

    def test_unconfigured_is_unknown_not_a_claim_that_no_backup_exists(self):
        report = backup.inspect(self.repo, None, self.commit, True)
        self.assertEqual(report['status'], 'not_configured')
        self.assertIn('无法判定', backup.lines(report)[0])

    def test_new_commit_or_dirty_tree_is_not_covered(self):
        for args in ({'head': '3' * 40}, {'clean': False}):
            with self.subTest(args=args):
                report = self.query(**args)
                self.assertTrue(report['recorded_acceptance'])
                self.assertFalse(report['current_checkout_covered'])
                self.assertIn('不覆盖当前', '\n'.join(backup.lines(report)))

    def test_no_private_config_or_database_payload_is_opened(self):
        original = Path.open
        forbidden = {self.root / 'state/db.sqlite', self.root / 'state/settings.json',
                     self.root / 'source.bundle', self.companion / 'db.sqlite'}
        def protected(path, *args, **kwargs):
            if path in forbidden:
                raise AssertionError('Payload opened by metadata query')
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'open', protected):
            self.assertEqual(self.query()['status'], 'accepted_receipt')

    def test_missing_index_receipt_payload_or_companion(self):
        for path in (self.index_path, self.root / 'final.json', self.root / 'state/db.sqlite',
                     self.companion / 'db.sqlite', self.companion / 'COMPANION_RECEIPT.json'):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.unlink()
                try:
                    self.assertEqual(self.query()['status'], 'unavailable')
                finally:
                    path.write_bytes(original)

    def test_bad_index_and_receipt_hashes(self):
        for path in (self.root / 'final.json', self.root / 'state.json', self.root / 'guard.json'):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                path.write_bytes(raw + b' ')
                try:
                    self.assertEqual(self.query()['status'], 'invalid')
                finally:
                    path.write_bytes(raw)

    def test_payload_size_change_is_detected_but_same_size_content_is_not_certified(self):
        path = self.root / 'state/settings.json'
        raw = path.read_bytes()
        path.write_bytes(b'x' * len(raw))
        report = self.query()
        self.assertEqual(report['status'], 'accepted_receipt')
        self.assertFalse(report['payload_sha256_rechecked'])
        path.write_bytes(raw + b' ')
        self.assertEqual(self.query()['status'], 'invalid')

    def test_wrong_repo_or_batch_is_rejected(self):
        self.index['main_git'] = str(self.base / 'another-repo')
        self.write(self.index_path, self.index)
        self.assertEqual(self.query()['status'], 'invalid')
        self.index['main_git'] = str(self.repo)
        self.index['batch_id'] = 'wrong'
        self.write(self.index_path, self.index)
        self.assertEqual(self.query()['status'], 'invalid')

    def test_false_final_or_database_integrity_fails(self):
        self.final['pass'] = False
        self.save_final()
        self.assertEqual(self.query()['status'], 'invalid')
        self.final['pass'] = True
        self.state['files'][0]['database']['integrity_check'] = 'error'
        self.seal()
        self.assertEqual(self.query()['status'], 'invalid')

    def test_inconsistent_commit_or_count_fails(self):
        self.state['source_commit'] = '4' * 40
        self.seal()
        self.assertEqual(self.query()['status'], 'invalid')
        self.state['source_commit'] = self.commit
        self.state['count'] = 9
        self.seal()
        self.assertEqual(self.query()['status'], 'invalid')

    def test_same_physical_disk_is_not_independent(self):
        self.final['cross_physical_disk']['drive_to_disk_number']['G'] = 0
        self.save_final()
        self.assertEqual(self.query()['status'], 'invalid')

    def test_metadata_is_read_only(self):
        before = {path: path.read_bytes() for path in self.base.rglob('*') if path.is_file()}
        self.query()
        self.assertEqual(before, {path: path.read_bytes() for path in self.base.rglob('*') if path.is_file()})

    def test_no_external_exception_or_unknown_exclusion_values_are_echoed(self):
        secret = 'private-fixture-value'
        with mock.patch.object(Path, 'open', side_effect=OSError(secret)):
            self.assertNotIn(secret, json.dumps(self.query()))
        self.final['excluded'] = [secret]
        self.save_final()
        self.assertNotIn(secret, json.dumps(self.query()))
        self.assertEqual(self.query()['status'], 'invalid')

    def test_duplicate_json_keys_fail(self):
        self.index_path.write_bytes(b'{"schema":1,"schema":1}')
        self.assertEqual(self.query()['status'], 'invalid')

    def test_oversized_metadata_fails(self):
        self.index_path.write_bytes(b' ' * (backup.MAX_FILE + 1))
        self.assertEqual(self.query()['status'], 'invalid')

    def test_network_relative_and_in_repo_indexes_are_rejected(self):
        for path in ('//server/share/index.json', '\\\\server\\share\\index.json', 'index.json', str(self.repo / 'index.json')):
            with self.subTest(path=path):
                self.assertEqual(backup.inspect(self.repo, path, self.commit, True)['status'], 'invalid')

    def test_unsafe_and_duplicate_evidence_paths_fail(self):
        first = dict(self.final['evidence'][0])
        for name in ('../escape.json', '/absolute.json', 'C:/drive.json', 'state.json:stream', 'a\\b.json', './state.json'):
            with self.subTest(name=name):
                self.final['evidence'][0] = {**first, 'path': name}
                self.save_final()
                self.assertEqual(self.query()['status'], 'invalid')
        self.final['evidence'][0] = first
        self.final['evidence'].append(dict(first))
        self.save_final()
        self.assertEqual(self.query()['status'], 'invalid')

    def test_hardlinked_metadata_is_rejected(self):
        link = self.base / 'hardlink.json'
        try:
            os.link(self.index_path, link)
        except OSError as exc:
            self.skipTest(type(exc).__name__)
        self.assertEqual(self.query()['status'], 'invalid')

    def test_symbolic_link_is_rejected(self):
        link = self.base / 'linked-index.json'
        try:
            os.symlink(self.index_path, link)
        except OSError as exc:
            self.skipTest(type(exc).__name__)
        self.assertEqual(backup.inspect(self.repo, link, self.commit, True)['status'], 'invalid')

    def test_aggregate_metadata_limit_is_enforced(self):
        with mock.patch.object(backup, 'MAX_METADATA', 10):
            self.assertEqual(self.query()['status'], 'invalid')

    def test_metadata_change_during_query_is_rejected(self):
        original = backup.payload_metadata
        def changing(*args, **kwargs):
            result = original(*args, **kwargs)
            self.index_path.write_bytes(self.index_path.read_bytes() + b' ')
            return result
        with mock.patch.object(backup, 'payload_metadata', side_effect=changing):
            self.assertEqual(self.query()['status'], 'invalid')


if __name__ == '__main__':
    unittest.main()
