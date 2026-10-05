"""Private state contracts use isolated fixtures; never production credentials."""
import contextlib
import copy
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import external_state as state


class ExternalStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'public'
        self.runtime = self.root / 'runtime'
        (self.repo / 'snapshot').mkdir(parents=True)
        self.runtime.mkdir()
        self.manifest_file = self.repo / 'snapshot/manifest.json'
        self.manifest_file.write_text(json.dumps({'files': []}), encoding='utf-8')
        self.config = self.runtime / 'config.json'
        self.secret = 'fixture-sensitive-value-' + 'never-display'
        self.config.write_text(json.dumps({'api_key': self.secret}), encoding='utf-8')

    def plan(self, **changes):
        entry = {'id': 'plugin-config', 'root': 'runtime', 'source': 'config.json',
                 'target': 'ComfyUI/custom_nodes/example/config.json', 'category': 'private_config', 'action': 'copy'}
        entry.update(changes)
        return {'schema': 1, 'roots': {'runtime': str(self.runtime)}, 'entries': [entry]}

    def claim(self, path, kind='file'):
        item = {'kind': kind, 'source': path, 'path': 'runtime/' + path, 'sha256': '0' * 64}
        if kind == 'sqlite_sql':
            item.update(path='library/example', parts=[], tables={}, sql_sha256='0' * 64)
        self.manifest_file.write_text(json.dumps({'files': [item]}), encoding='utf-8')

    def test_inventory_and_copy_never_report_secret_values(self):
        manifest = state.inventory(self.plan(), self.repo)
        self.assertNotIn(self.secret, json.dumps(manifest))
        dest = self.root / 'overlay'
        self.assertTrue(state.verify_dry_run(manifest, dest, self.repo)['pass'])
        self.assertFalse(dest.exists())
        receipt = state.materialize(manifest, dest, self.repo)
        self.assertEqual((dest / self.plan()['entries'][0]['target']).read_bytes(), self.config.read_bytes())
        self.assertNotIn(self.secret, json.dumps(receipt))
        self.assertFalse(receipt['complete_runtime_restored'])
        self.assertFalse(receipt['service_started'])

    def test_exact_qwen_configs_validate_as_private_references_only(self):
        plan = self.plan()
        plan['entries'] = []
        for index, relative in enumerate(sorted(state.REFERENCE_ONLY_PRIVATE_CONFIG_PATHS)):
            source = self.runtime / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(json.dumps({'local_fixture': self.secret}), encoding='utf-8')
            plan['entries'].append({
                'id': f'qwen-config-{index}', 'root': 'runtime',
                'source': relative, 'target': relative,
                'category': 'private_config', 'action': 'reference',
            })
        with patch.object(state, 'source_fingerprint', side_effect=AssertionError('no inventory')):
            roots, entries, manifest_hash = state.validate_plan(plan, self.repo)
        self.assertEqual(len(entries), 3)
        self.assertEqual(set(roots), {'runtime'})
        self.assertEqual(len(manifest_hash), 64)
        self.assertTrue(all(entry['action'] == 'reference' for entry, _ in entries))
        self.assertNotIn(self.secret, json.dumps(plan))

    def test_exact_qwen_configs_reject_copy_or_reclassification(self):
        targets = list(state.REFERENCE_ONLY_PRIVATE_CONFIG_PATHS)
        targets += [target.upper() for target in targets]
        for target in targets:
            for category, action in [('private_config', 'copy'), ('mutable_cache', 'copy'),
                                     ('mutable_cache', 'reference'), ('external_asset', 'reference')]:
                with self.subTest(target=target, category=category, action=action):
                    with self.assertRaisesRegex(state.ContractError, 'private_config_reference_only'):
                        state.validate_plan(self.plan(target=target, category=category, action=action), self.repo)

    def test_qwen_config_allowlist_does_not_accept_path_aliases(self):
        for target in ['other/qwen21_lab/runtime.json', 'qwen21_lab/runtime-backup.json',
                       'QWEN21_lab/runtime.json', 'qwen21_lab/runtime.json/child.json',
                       'qwen21_lab/other_model_paths.yaml']:
            with self.subTest(target=target):
                with self.assertRaisesRegex(state.ContractError, 'private_config_(target_not_recognized|reference_only)'):
                    state.validate_plan(self.plan(target=target, action='reference'), self.repo)

    def test_exact_qwen_config_cannot_shadow_public_payload(self):
        for target in state.REFERENCE_ONLY_PRIVATE_CONFIG_PATHS:
            with self.subTest(target=target):
                self.claim(target)
                with self.assertRaisesRegex(state.ContractError, 'overlay_would_shadow_public_payload'):
                    state.validate_plan(self.plan(target=target, action='reference'), self.repo)

    def test_path_traversal_aliases_ads_unicode_and_git_rejected(self):
        for target in ['../config.json', 'a\\config.json', '/config.json', 'a:stream', 'NUL.json',
                       '.git/config.json', 'a/../config.json', 'a./config.json', 'ｃonfig.json', 'a//config.json']:
            with self.subTest(target=target), self.assertRaises(state.ContractError):
                state.inventory(self.plan(target=target), self.repo)

    def test_malformed_plan_types_are_fixed_code_failures(self):
        for key in state.ENTRY_KEYS:
            with self.subTest(key=key), self.assertRaises(state.ContractError):
                state.inventory(self.plan(**{key: []}), self.repo)
        plan = self.plan(); plan['entries'][0]['unexpected'] = 'must not be logged'
        with self.assertRaises(state.ContractError):
            state.inventory(plan, self.repo)

    def test_public_source_file_and_ancestor_shadow_rejected(self):
        for claim, target in [('a/config.json', 'a/config.json'), ('a.py', 'a.py/config.json'),
                              ('folder/config.json/child.py', 'folder/config.json')]:
            with self.subTest(claim=claim):
                self.claim(claim)
                with self.assertRaises(state.ContractError):
                    state.inventory(self.plan(target=target), self.repo)

    def test_directory_cannot_shadow_public_tree(self):
        (self.runtime / 'assets').mkdir()
        self.claim('ComfyUI/custom_nodes/source.py')
        with self.assertRaises(state.ContractError):
            state.inventory(self.plan(source='assets', target='ComfyUI', category='external_asset', action='reference'), self.repo)

    def test_executable_private_overlays_and_directory_copies_rejected(self):
        for target, category in [('remote.py', 'mutable_cache'), ('config.exe', 'private_config')]:
            with self.assertRaises(state.ContractError):
                state.inventory(self.plan(target=target, category=category), self.repo)
        (self.runtime / 'cache').mkdir()
        with self.assertRaises(state.ContractError):
            state.inventory(self.plan(source='cache', target='cache', category='mutable_cache'), self.repo)

    def test_case_duplicate_and_parent_targets_rejected(self):
        other = self.runtime / 'other.json'; other.write_text('{}', encoding='utf-8')
        for target in ['ComfyUI/custom_nodes/example/CONFIG.JSON', 'ComfyUI/custom_nodes/example/config.json/child.json']:
            plan = self.plan()
            plan['entries'].append({**plan['entries'][0], 'id': 'second', 'source': 'other.json', 'target': target})
            with self.assertRaises(state.ContractError):
                state.inventory(plan, self.repo)

    def test_hardlink_and_symlink_sources_rejected(self):
        hard = self.runtime / 'hard.json'; os.link(self.config, hard)
        with self.assertRaises(state.ContractError):
            state.inventory(self.plan(source='hard.json'), self.repo)
        hard.unlink()
        link = self.runtime / 'link.json'
        try:
            link.symlink_to(self.config)
        except OSError:
            self.skipTest('OS does not grant creation of symbolic links')
        with self.assertRaises(state.ContractError):
            state.inventory(self.plan(source='link.json'), self.repo)

    def test_source_drift_requires_reinventory(self):
        manifest = state.inventory(self.plan(), self.repo)
        self.config.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(state.ContractError, 'external_state_changed'):
            state.verify_dry_run(manifest, repo=self.repo)

    def test_public_manifest_drift_requires_reinventory(self):
        manifest = state.inventory(self.plan(), self.repo)
        self.claim('new.py')
        with self.assertRaisesRegex(state.ContractError, 'public_manifest_changed'):
            state.verify_dry_run(manifest, repo=self.repo)

    def test_destinations_cannot_overwrite_or_overlap(self):
        manifest = state.inventory(self.plan(), self.repo)
        for dest in [self.repo / 'new', self.runtime / 'new', self.config, self.root]:
            with self.subTest(dest=dest), self.assertRaises(state.ContractError):
                state.materialize(manifest, dest, self.repo)
        self.assertEqual(json.loads(self.config.read_text())['api_key'], self.secret)

    def test_assets_are_reference_only_with_honest_verification(self):
        assets = self.runtime / 'models'; assets.mkdir()
        (assets / 'weights.safetensors').write_bytes(b'not an actual model')
        plan = self.plan(source='models', target='ComfyUI/models', category='external_asset', action='reference')
        manifest = state.inventory(plan, self.repo)
        self.assertEqual(manifest['entries'][0]['state']['verification'], 'directory_reference_only')
        self.assertIsNone(manifest['entries'][0]['state']['sha256'])
        receipt = state.materialize(manifest, self.root / 'refs', self.repo)
        self.assertEqual(receipt['written'], [])
        self.assertEqual(receipt['unresolved_external_references'], 1)
        self.assertFalse((self.root / 'refs/ComfyUI/models').exists())
        with self.assertRaises(state.ContractError):
            state.inventory(self.plan(source='models/weights.safetensors', category='external_asset'), self.repo)

    def make_db(self):
        db = self.runtime / 'state.db'
        conn = sqlite3.connect(db)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE items(value TEXT)'); conn.commit()
        conn.execute('INSERT INTO items VALUES(?)', ('local fixture',)); conn.commit()
        return db, conn

    def test_sqlite_backup_includes_wal_and_allows_explicit_public_baseline(self):
        db, conn = self.make_db()
        with contextlib.closing(conn):
            target = 'ComfyUI/user/library.db'
            self.claim(target, 'sqlite_sql')
            plan = self.plan(source='state.db', target=target, category='mutable_db', action='sqlite_backup')
            manifest = state.inventory(plan, self.repo)
            self.assertIsNotNone(manifest['entries'][0]['state']['wal'])
            dest = self.root / 'backup'
            state.materialize(manifest, dest, self.repo)
            with contextlib.closing(sqlite3.connect(dest / target)) as restored:
                self.assertEqual(restored.execute('SELECT value FROM items').fetchall(), [('local fixture',)])
            self.assertEqual(conn.execute('SELECT count(*) FROM items').fetchone()[0], 1)

    def test_database_wal_drift_fails_guard(self):
        db, conn = self.make_db()
        with contextlib.closing(conn):
            plan = self.plan(source='state.db', target='state.db', category='mutable_db', action='reference')
            manifest = state.inventory(plan, self.repo)
            conn.execute('INSERT INTO items VALUES(?)', ('changed',)); conn.commit()
            with self.assertRaises(state.ContractError):
                state.verify_dry_run(manifest, repo=self.repo)

    def test_copy_limits_and_invalid_database_rejected(self):
        with patch.object(state, 'MAX_CONFIG_BYTES', 1), self.assertRaises(state.ContractError):
            state.inventory(self.plan(), self.repo)
        with self.assertRaises(state.ContractError):
            state.inventory(self.plan(target='state.db', category='mutable_db', action='copy'), self.repo)
        with self.assertRaises(state.ContractError):
            state.inventory(self.plan(target='state.db', category='mutable_db', action='reference'), self.repo)

    def test_private_json_reports_must_be_external_and_exclusive(self):
        for dest in [self.repo / 'private.json', self.config]:
            with self.assertRaises(state.ContractError):
                state.write_external_json(dest, {}, self.repo)
        dest = self.root / 'external/manifest.json'
        state.write_external_json(dest, {'schema': 1}, self.repo)
        self.assertEqual(state.read_external_json(dest, self.repo), {'schema': 1})
        with self.assertRaises(state.ContractError):
            state.write_external_json(dest, {}, self.repo)

    def test_tampered_manifest_assertions_and_state_rejected(self):
        manifest = state.inventory(self.plan(), self.repo)
        for key, value in [('contains_secret_values', True), ('entries', {}), ('public_manifest_sha256', 'bad')]:
            broken = copy.deepcopy(manifest); broken[key] = value
            with self.assertRaises(state.ContractError):
                state.verify_dry_run(broken, repo=self.repo)
        manifest['entries'][0]['state']['sha256'] = '0' * 64
        with self.assertRaises(state.ContractError):
            state.verify_dry_run(manifest, repo=self.repo)


if __name__ == '__main__':
    unittest.main()
