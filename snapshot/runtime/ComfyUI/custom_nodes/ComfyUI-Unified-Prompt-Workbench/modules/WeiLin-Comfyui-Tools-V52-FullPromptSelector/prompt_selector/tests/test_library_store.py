"""Tests for the round-3 SQLite library authority, journal and auto-maintenance.

Pure ``library_store`` tests use temp directories only.  The prompt_selector
integration tests load the real module with a stub ``server`` and a temporary
``__file__`` (same convention as tests/test_semantic_cache.py), so no ComfyUI
server is started and the production user_data directory is never touched.
"""

import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock

PROMPT_SELECTOR_DIR = Path(__file__).resolve().parents[1]
LIBRARY_STORE_FILE = PROMPT_SELECTOR_DIR / 'library_store.py'
MIGRATE_SCRIPT = PROMPT_SELECTOR_DIR.parents[7] / 'scripts' / 'migrate_library_store.py'
WORKTREE_ROOT = PROMPT_SELECTOR_DIR.parents[7]
PYTHON = sys.executable


def _load_store_module():
    spec = importlib.util.spec_from_file_location('wb_library_store_test', LIBRARY_STORE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prompt(identity, text, **extra):
    value = {'id': identity, 'alias': text, 'prompt': text, 'description': '', 'image': '',
             'tags': [], 'favorite': False, 'template': False,
             'created_at': '2026-01-01T00:00:00', 'updated_at': '2026-01-01T00:00:00',
             'usage_count': 0, 'last_used': None, 'unicode': '中文·测试'}
    value.update(extra)
    return value


def _document():
    return {
        'version': '1.6',
        'settings': {'language': 'zh-CN', 'separator': ', '},
        'last_modified': '2026-10-25T07:00:00.000+08:00',
        'selector_library': {'kinds': ['tag'], 'unresolved': {}},
        '_source_to_canonical': {'old': {'canonical_id': 'p2'}},
        '_merge_history': [{'source_ids': ['old'], 'canonical_id': 'p2'}],
        'categories': [
            {'id': 'cat-a', 'name': 'A', 'created_at': 'x', 'updated_at': 'x',
             'prompts': [_prompt('p1', 'a cat'), _prompt('p2', 'a dog')]},
            {'id': 'cat-b', 'name': 'B', 'created_at': 'x', 'updated_at': 'x',
             'prompts': [_prompt('p3', 'a fox')]},
            {'id': 'cat-c', 'name': 'C', 'created_at': 'x', 'updated_at': 'x', 'prompts': []},
        ],
    }


def _close_module(module):
    maintenance = module._LIBRARY_STORE_STATE.get('maintenance')
    if maintenance is not None:
        try:
            maintenance.shutdown()
        except Exception:
            pass
    instance = module._LIBRARY_STORE_STATE.get('instance')
    if instance is not None:
        try:
            instance.close()
        except Exception:
            pass
    module._LIBRARY_STORE_STATE['instance'] = None
    module._LIBRARY_STORE_STATE['active'] = False
    module._LIBRARY_STORE_STATE['dirty'] = False


def _wait_for(predicate, timeout=8.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class _StubRoutes:
    def get(self, path):
        def decorator(handler):
            return handler
        return decorator

    def post(self, path):
        def decorator(handler):
            return handler
        return decorator


def _load_prompt_selector(name, store_root, environment):
    module_spec = importlib.util.spec_from_file_location(
        'wb_libstore_%s.prompt_selector.prompt_selector' % name,
        PROMPT_SELECTOR_DIR / 'prompt_selector.py')
    package = types.ModuleType('wb_libstore_%s' % name)
    package.__path__ = [str(PROMPT_SELECTOR_DIR)]
    sys.modules[package.__name__] = package
    package_name = package.__name__ + '.prompt_selector'
    subpackage = types.ModuleType(package_name)
    subpackage.__path__ = [str(PROMPT_SELECTOR_DIR)]
    sys.modules[package_name] = subpackage
    server = types.ModuleType('server')
    server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=_StubRoutes()))
    sys.modules['server'] = server
    module = importlib.util.module_from_spec(module_spec)
    module.__package__ = package_name
    module.__file__ = str(Path(store_root) / 'plugin' / 'prompt_selector.py')
    sys.modules[package_name + '.prompt_selector'] = module
    with mock.patch.dict(os.environ, environment):
        module_spec.loader.exec_module(module)
    return module


def _store_dir(root):
    directory = Path(root) / 'user_data' / 'prompt_selector'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _projection_file(store_dir):
    (store_dir / 'semantic_projection.json').write_text(json.dumps({
        'schema': 'S4-semantic-projection-v1', 'decisions': {}, 'class_labels': {}}),
        encoding='utf-8')


DISABLE_MAINTENANCE = {'UW_DISABLE_LIBRARY_AUTOEXPORT': '1', 'UW_DISABLE_LIBRARY_AUTOBACKUP': '1'}


class LibraryStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ls = _load_store_module()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wb-library-store-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / 'library.sqlite3'
        self.store = self.ls.open_store(self.db, create=True)
        self.addCleanup(self.store.close)
        self.document = _document()
        self.store.initialize_from_document(self.document)

    def _load(self):
        return self.store.load_document()

    def test_roundtrip_and_schema(self):
        loaded = self._load()
        self.assertEqual(loaded, self.document)
        self.assertEqual(self.store.verify_document_equals(self.document)['equal'], True)
        self.assertEqual(self.store.table_counts()['prompts'], 3)
        self.assertEqual(self.store.table_counts()['categories'], 3)
        self.assertEqual(self.store.integrity_check(), ['ok'])
        self.assertEqual(self.store.revision(), self.document['last_modified'])

    def test_single_prompt_edit_is_small_transaction(self):
        changed = copy.deepcopy(self.document)
        changed['last_modified'] = '2026-10-25T07:01:00+08:00'
        changed['categories'][0]['prompts'][0]['description'] = 'edited'
        changes = self.ls.ChangeSet(
            upsert_prompts=[('cat-a', changed['categories'][0]['prompts'][0])],
            write_categories=[changed['categories'][0]], meta_keys=['last_modified'])
        started = time.perf_counter()
        self.store.commit_document(changed, changes, expected_revision=self.document['last_modified'])
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.5)
        self.assertEqual(self._load(), changed)
        self.assertEqual(self._load()['categories'][0]['prompts'][1],
                         self.document['categories'][0]['prompts'][1])

    def test_cas_conflict_leaves_store_untouched(self):
        with self.assertRaises(self.ls.StoreRevisionConflict) as caught:
            self.store.commit_document(self.document, self.ls.ChangeSet(meta_keys=['last_modified']),
                                       expected_revision='stale-revision')
        self.assertEqual(caught.exception.expected, 'stale-revision')
        self.assertEqual(self._load(), self.document)

    def test_transaction_rolls_back_on_mid_commit_error(self):
        changed = copy.deepcopy(self.document)
        changed['last_modified'] = '2026-10-25T07:02:00+08:00'
        changes = self.ls.ChangeSet(upsert_prompts=[('cat-a', changed['categories'][0]['prompts'][0])],
                                    meta_keys=['last_modified'])
        original = self.store._write_meta

        def failing(*args, **kwargs):
            raise RuntimeError('injected failure')

        self.store._write_meta = failing
        try:
            with self.assertRaises(RuntimeError):
                self.store.commit_document(changed, changes)
        finally:
            self.store._write_meta = original
        self.assertEqual(self._load(), self.document)

    def test_insert_move_delete_prompt_keeps_orders(self):
        document = copy.deepcopy(self.document)
        document['last_modified'] = '2026-10-25T07:03:00+08:00'
        new_prompt = _prompt('p4', 'a bird')
        document['categories'][0]['prompts'].append(new_prompt)
        self.store.commit_document(document, self.ls.ChangeSet(
            upsert_prompts=[('cat-a', new_prompt)], write_categories=[document['categories'][0]],
            meta_keys=['last_modified']))
        self.assertEqual(self._load(), document)

        moved = copy.deepcopy(document)
        moved['last_modified'] = '2026-10-25T07:04:00+08:00'
        moved['categories'][0]['prompts'] = [item for item in moved['categories'][0]['prompts']
                                             if item['id'] != 'p3']
        moved['categories'][1]['prompts'].append(_prompt('p3', 'a fox'))
        self.store.commit_document(moved, self.ls.ChangeSet(
            upsert_prompts=[('cat-b', moved['categories'][1]['prompts'][0])],
            write_categories=[moved['categories'][0], moved['categories'][1]],
            meta_keys=['last_modified']))
        self.assertEqual(self._load(), moved)

        deleted = copy.deepcopy(moved)
        deleted['last_modified'] = '2026-10-25T07:05:00+08:00'
        deleted['categories'][1]['prompts'] = []
        self.store.commit_document(deleted, self.ls.ChangeSet(
            delete_prompt_ids=['p3'], write_categories=[deleted['categories'][1]],
            meta_keys=['last_modified']))
        self.assertEqual(self._load(), deleted)

    def test_category_create_delete_updates_positions(self):
        created = copy.deepcopy(self.document)
        created['last_modified'] = '2026-10-25T07:06:00+08:00'
        created['categories'].append({'id': 'cat-new', 'name': 'New', 'prompts': []})
        self.store.commit_document(created, self.ls.ChangeSet(
            write_categories=[created['categories'][-1]], meta_keys=['last_modified']))
        self.assertEqual([c['id'] for c in self._load()['categories']],
                         ['cat-a', 'cat-b', 'cat-c', 'cat-new'])

        removed = copy.deepcopy(created)
        removed['last_modified'] = '2026-10-25T07:07:00+08:00'
        removed['categories'] = [c for c in removed['categories'] if c['id'] != 'cat-b']
        self.store.commit_document(removed, self.ls.ChangeSet(
            delete_category_ids=['cat-b'], update_positions=True, meta_keys=['last_modified']))
        self.assertEqual(self._load(), removed)
        self.assertTrue(self.store.verify_document_equals(removed)['equal'])

    def test_full_replace_with_backup_and_retention(self):
        backup_dir = self.root / 'backups'
        replacement = _document()
        replacement['last_modified'] = '2026-10-25T07:08:00+08:00'
        replacement['categories'] = replacement['categories'][:1]
        self.store.commit_document(replacement, self.ls.ChangeSet(full=True, backup=True))
        self.assertEqual(self._load(), replacement)
        backups = list((self.root / 'library_backups').glob('library_*.sqlite3'))
        self.assertEqual(len(backups), 1)
        backup_store = self.ls.open_store(backups[0])
        try:
            self.assertEqual(backup_store.load_document(), self.document)
        finally:
            backup_store.close()
        self.assertGreater(self.store.last_backup_at, 0)
        self.assertEqual(self.store.meta_value('__last_backup_at__'), self.store.last_backup_at)

    def test_export_json_roundtrip_and_atomicity(self):
        target = self.root / 'data.json'
        info = self.store.export_json(target)
        self.assertGreater(info['bytes'], 0)
        self.assertEqual(self.ls.read_json_document(target), self.document)
        self.assertEqual([path.name for path in self.root.glob('*.tmp')], [])
        self.assertEqual(info['sha256'], _sha256(target))

    def test_journal_records_edit_and_restore(self):
        changed = copy.deepcopy(self.document)
        changed['last_modified'] = '2026-10-25T07:09:00+08:00'
        changed['categories'][0]['prompts'][0]['prompt'] = 'a changed cat'
        self.store.commit_document(changed, self.ls.ChangeSet(
            upsert_prompts=[('cat-a', changed['categories'][0]['prompts'][0])],
            meta_keys=['last_modified']))
        entries = self.store.journal_entries(limit=5)
        self.assertEqual(entries[0]['op'], 'update')
        self.assertEqual(entries[0]['before']['prompt'], 'a cat')
        self.assertEqual(entries[0]['after']['prompt'], 'a changed cat')
        restored = self.store.restore_journal(entries[0]['seq'])
        self.assertTrue(restored['restored'])
        self.assertEqual(self._load()['categories'][0]['prompts'][0]['prompt'], 'a cat')
        restore_entries = self.store.journal_entries(limit=2)
        self.assertEqual(restore_entries[0]['op'], 'restore')

    def test_journal_delete_and_batch_entries(self):
        deleted = copy.deepcopy(self.document)
        deleted['last_modified'] = '2026-10-25T07:10:00+08:00'
        deleted['categories'][0]['prompts'] = deleted['categories'][0]['prompts'][:1]
        self.store.commit_document(deleted, self.ls.ChangeSet(
            delete_prompt_ids=['p2'], write_categories=[deleted['categories'][0]],
            meta_keys=['last_modified']))
        entry = self.store.journal_entries(limit=1)[0]
        self.assertEqual(entry['op'], 'delete')
        self.assertEqual(entry['before']['id'], 'p2')
        self.store.restore_journal(entry['seq'])
        self.assertEqual(self._load()['categories'], self.document['categories'])

        batch = copy.deepcopy(self.document)
        batch['last_modified'] = '2026-10-25T07:11:00+08:00'
        self.store.commit_document(batch, self.ls.ChangeSet(full=True))
        summary = self.store.journal_entries(limit=1)[0]
        self.assertEqual(summary['op'], 'replace')
        with self.assertRaises(ValueError):
            self.store.restore_journal(summary['seq'])

    def test_journal_prune(self):
        for index in range(30):
            changed = copy.deepcopy(self.document)
            changed['last_modified'] = '2026-10-25T07:%02d:00+08:00' % (12 + index % 40)
            changed['categories'][0]['prompts'][0]['description'] = 'edit %d' % index
            self.store.commit_document(changed, self.ls.ChangeSet(
                upsert_prompts=[('cat-a', changed['categories'][0]['prompts'][0])],
                meta_keys=['last_modified']))
        self.assertGreater(self.store.journal_counts()['entries'], 10)
        self.store.prune_journal(days=7, max_entries=5)
        self.assertEqual(self.store.journal_counts()['entries'], 5)


class MigrationToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ls = _load_store_module()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wb-migrate-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data_json = self.root / 'data.json'
        self.db = self.root / 'library.sqlite3'
        document = _document()
        self.data_json.write_text(json.dumps(document, ensure_ascii=False, separators=(',', ':')),
                                  encoding='utf-8')
        self.document_sha = _sha256(self.data_json)

    def _run(self, *arguments):
        command = [PYTHON, '-X', 'utf8', '-B', str(MIGRATE_SCRIPT),
                   '--data-json', str(self.data_json), '--db', str(self.db), *arguments]
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                   errors='replace', timeout=180)
        receipt = None
        if completed.stdout.strip():
            try:
                receipt = json.loads(completed.stdout)
            except ValueError:
                receipt = None
        return completed, receipt

    def test_dry_run_does_not_write(self):
        completed, receipt = self._run('--dry-run')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(receipt['ok'])
        self.assertFalse(self.db.exists())
        self.assertEqual(receipt['source_sha256'], self.document_sha)

    def test_apply_verify_idempotent_export(self):
        completed, receipt = self._run('--apply')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(receipt['ok'])
        self.assertTrue(self.db.is_file())
        self.assertEqual(receipt['final_verify']['equal'], True)
        self.assertEqual(_sha256(self.data_json), self.document_sha)
        store = self.ls.open_store(self.db)
        try:
            self.assertEqual(store.load_document(), self.ls.read_json_document(self.data_json))
            self.assertEqual(store.meta_value('__migration_receipt__')['source_sha256'],
                             self.document_sha)
        finally:
            store.close()
        completed, receipt = self._run('--apply')
        self.assertEqual(completed.returncode, 0)
        self.assertFalse(receipt.get('migrated', True))
        export = self.root / 'export.json'
        completed, receipt = self._run('--export-json', str(export))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.ls.read_json_document(export), self.ls.read_json_document(self.data_json))


class JournalAndMaintenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ls = _load_store_module()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wb-maintenance-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / 'library.sqlite3'
        self.store = self.ls.open_store(self.db, create=True)
        self.addCleanup(self.store.close)
        self.document = _document()
        self.store.initialize_from_document(self.document)
        self.export_path = self.root / 'data.json'
        self.maintenance = None

    def tearDown(self):
        if self.maintenance is not None:
            self.maintenance.shutdown()
            self.maintenance = None

    def _start(self, **overrides):
        options = dict(store=self.store, export_path=self.export_path,
                       document_provider=self.store.load_document,
                       backup_dir=self.root / 'backups', enable_backup=False,
                       export_debounce_s=0.2, export_interval_s=0.2)
        options.update(overrides)
        self.maintenance = self.ls.AutoMaintenance(**options)
        self.maintenance.start()
        return self.maintenance

    def _edit(self, revision):
        changed = copy.deepcopy(self.document)
        changed['last_modified'] = revision
        changed['categories'][0]['prompts'][0]['description'] = 'auto edit'
        self.store.commit_document(changed, self.ls.ChangeSet(
            upsert_prompts=[('cat-a', changed['categories'][0]['prompts'][0])],
            meta_keys=['last_modified']))
        self.maintenance.notify_write()
        return changed

    def test_auto_export_after_debounce(self):
        self._start()
        changed = self._edit('2026-10-25T08:01:00+08:00')
        self.assertTrue(_wait_for(lambda: self.export_path.is_file()), 'auto export file appeared')
        self.assertEqual(self.ls.read_json_document(self.export_path), changed)
        status = self.maintenance.status()
        self.assertFalse(status['export']['dirty'])
        self.assertGreater(status['export']['last_success_at'], 0)
        self.assertIsNone(status['export']['error'])

    def test_auto_export_failure_is_reported_and_not_fatal(self):
        self._start()
        blocker = self.root / 'blocker'
        blocker.write_text('not a directory', encoding='utf-8')
        self.maintenance.export_path = str(blocker / 'data.json')
        self._edit('2026-10-25T08:02:00+08:00')
        self.assertTrue(_wait_for(lambda: self.maintenance.last_export_error is not None
                                  or not self.maintenance.dirty), 'export attempted')
        if self.maintenance.last_export_error is not None:
            self.assertIn('Error', self.maintenance.last_export_error)
        self.assertIsNone(self.maintenance.last_backup_error)

    def test_auto_backup_interval_and_retention(self):
        self._start(enable_backup=True, backup_interval_s=0.2, backup_retain=2,
                    startup_backup_age_s=0, startup_delay_s=0)
        self.assertTrue(_wait_for(lambda: len(list((self.root / 'backups').glob('library_*.sqlite3'))) >= 1),
                        'startup backup appeared')
        self.assertTrue(_wait_for(lambda: self.store.last_backup_at > 0), 'backup timestamp persisted')
        self.assertGreater(self.store.last_backup_at, 0)
        self.assertGreater(self.maintenance.status()['backup']['last_success_at'], 0)
        self.assertIsNone(self.maintenance.status()['backup']['error'])
        files = list((self.root / 'backups').glob('library_*.sqlite3'))
        self.assertLessEqual(len(files), 2)

    def test_recent_backup_is_not_repeated_on_startup(self):
        self.store.backup(self.root / 'backups', retain=5)
        last_backup = self.store.last_backup_at
        self._start(enable_backup=True, backup_interval_s=3600,
                    startup_backup_age_s=24 * 3600, startup_delay_s=0)
        time.sleep(1.0)
        self.assertEqual(len(list((self.root / 'backups').glob('library_*.sqlite3'))), 1)
        self.assertEqual(self.maintenance.last_backup_success_at, last_backup)
        self.assertFalse(self.maintenance.status()['backup']['overdue'])

    def test_auto_backup_write_threshold(self):
        self._start(enable_backup=True, backup_interval_s=3600, backup_writes=2,
                    startup_backup_age_s=0, startup_delay_s=3600)
        self._edit('2026-10-25T08:03:00+08:00')
        self._edit('2026-10-25T08:04:00+08:00')
        self.assertTrue(_wait_for(lambda: len(list((self.root / 'backups').glob('library_*.sqlite3'))) >= 1),
                        'write-count backup appeared')

    def test_disable_flags(self):
        self._start(enable_export=False, enable_backup=False)
        self._edit('2026-10-25T08:05:00+08:00')
        time.sleep(0.5)
        self.assertFalse(self.export_path.exists())
        self.assertFalse((self.root / 'backups').exists())
        self.maintenance.shutdown()
        self.maintenance = None
        self.assertFalse(self.export_path.exists())

    def test_status_reports_counts_and_intervals(self):
        self._start()
        status = self.maintenance.status()
        self.assertTrue(status['active'])
        self.assertEqual(status['export']['interval_s'], 0.2)
        self.assertEqual(status['journal']['entries'], 0)
        self.assertIn('db', status)
        self.assertGreaterEqual(status['db']['bytes'], 1)

    def test_env_names_configure_defaults(self):
        environment = {
            'UW_LIBRARY_EXPORT_DEBOUNCE_S': '3.5',
            'UW_LIBRARY_EXPORT_INTERVAL_S': '123',
            'UW_LIBRARY_BACKUP_INTERVAL_S': '456',
            'UW_LIBRARY_BACKUP_RETAIN': '7',
        }
        with mock.patch.dict(os.environ, environment):
            maintenance = self.ls.AutoMaintenance(
                self.store, export_path=self.export_path,
                document_provider=self.store.load_document, enable_backup=False)
        self.assertEqual(maintenance.export_debounce_s, 3.5)
        self.assertEqual(maintenance.export_interval_s, 123.0)
        self.assertEqual(maintenance.backup_interval_s, 456.0)
        self.assertEqual(maintenance.backup_retain, 7)
        with mock.patch.dict(os.environ, {'UW_DISABLE_LIBRARY_AUTOBACKUP': '1'}):
            disabled = self.ls.AutoMaintenance(self.store, export_path=self.export_path)
        self.assertFalse(disabled.enable_backup)

    def test_wal_recovery_after_hard_kill(self):
        child = r'''
import importlib.util, os, sys
path = sys.argv[1]
spec = importlib.util.spec_from_file_location('ls', path)
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
store = ls.open_store(sys.argv[2])
document = store.load_document()
document['last_modified'] = '2026-10-25T09:30:00+08:00'
store.commit_document(document, ls.ChangeSet(meta_keys=['last_modified']))
os._exit(0)
'''
        completed = subprocess.run([PYTHON, '-X', 'utf8', '-c', child,
                                    str(LIBRARY_STORE_FILE), str(self.db)],
                                   capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        reopened = self.ls.open_store(self.db)
        try:
            self.assertEqual(reopened.load_document()['last_modified'], '2026-10-25T09:30:00+08:00')
            self.assertTrue(reopened.verify_document_equals(reopened.load_document())['equal'])
        finally:
            reopened.close()

    def test_uncommitted_wal_transaction_is_discarded(self):
        child = r'''
import importlib.util, os, sys
path = sys.argv[1]
spec = importlib.util.spec_from_file_location('ls', path)
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
store = ls.open_store(sys.argv[2])
store.connection.execute("BEGIN IMMEDIATE")
store.connection.execute("UPDATE library_meta SET value=? WHERE key='last_modified'", ('"broken"',))
os._exit(0)
'''
        completed = subprocess.run([PYTHON, '-X', 'utf8', '-c', child,
                                    str(LIBRARY_STORE_FILE), str(self.db)],
                                   capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        reopened = self.ls.open_store(self.db)
        try:
            self.assertEqual(reopened.load_document()['last_modified'],
                             self.document['last_modified'])
        finally:
            reopened.close()


class PromptSelectorStoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ls = _load_store_module()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wb-selector-store-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store_dir = _store_dir(self.root)
        self.db = self.store_dir / 'library.sqlite3'
        self.document = _document()
        store = self.ls.open_store(self.db, create=True)
        try:
            store.initialize_from_document(self.document,
                                           receipt={'source_sha256': 'fixture'})
        finally:
            store.close()
        _projection_file(self.store_dir)
        self.environment = {
            'UW_LIBRARY_STORE': 'sqlite', 'UW_SKIP_LIBRARY_WARMUP': '1',
            'UW_DISABLE_SEMANTIC_CACHE': '1', **DISABLE_MAINTENANCE,
        }

    def _module(self, environment=None):
        module = _load_prompt_selector(uuid.uuid4().hex[:8], self.root, environment or self.environment)
        self.addCleanup(_close_module, module)
        return module

    def _stored_document(self):
        store = self.ls.open_store(self.db)
        try:
            return store.load_document()
        finally:
            store.close()

    def test_read_path_uses_store_without_data_json(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment):
            self.assertTrue(module._library_store_active())
            self.assertEqual(module._read_prompt_data_cached(), self.document)
            self.assertFalse((self.store_dir / 'data.json').exists())
            status = module._library_store_status()
            self.assertTrue(status['active'])
            self.assertEqual(status['mode'], 'sqlite')
            self.assertEqual(status['journal']['entries'], 0)

    def test_single_edit_writes_one_row_and_journal(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment):
            data = module._read_prompt_data_cached()
            result = module._apply_upsert_prompt({
                'mode': 'edit', 'base_revision': data['last_modified'],
                'target_category_id': 'cat-a',
                'prompt': {'id': 'p1', 'alias': 'a cat v2', 'prompt': 'a cat v2',
                           'description': 'edited', 'image': '', 'tags': [],
                           'favorite': True},
            })
            self.assertTrue(result['success'])
            written = self._stored_document()
            self.assertEqual(written['categories'][0]['prompts'][0]['description'], 'edited')
            self.assertEqual(written['categories'][0]['prompts'][1],
                             self.document['categories'][0]['prompts'][1])
            self.assertFalse((self.store_dir / 'data.json').exists())
            self.assertEqual(module._read_prompt_data_cached(), written)
            store = self.ls.open_store(self.db)
            try:
                journal = store.journal_entries(limit=5)
            finally:
                store.close()
            self.assertEqual(journal[0]['op'], 'update')
            self.assertEqual(journal[0]['before']['description'], '')

    def test_journal_restore_endpoint_helper(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment):
            data = module._read_prompt_data_cached()
            module._apply_upsert_prompt({
                'mode': 'edit', 'base_revision': data['last_modified'],
                'target_category_id': 'cat-a',
                'prompt': {'id': 'p1', 'alias': 'cat', 'prompt': 'changed body',
                           'description': '', 'image': '', 'tags': []},
            })
            store = self.ls.open_store(self.db)
            try:
                journal = store.journal_entries(limit=1)
            finally:
                store.close()
            restored = module._restore_library_journal_entry({
                'seq': journal[0]['seq'],
                'base_revision': self._stored_document()['last_modified'],
            })
            self.assertTrue(restored['success'])
            self.assertEqual(module._read_prompt_data_cached()['categories'][0]['prompts'],
                             self.document['categories'][0]['prompts'])

    def test_missing_database_falls_back_to_data_json(self):
        self.db.unlink()
        (self.store_dir / 'data.json').write_text(
            json.dumps(self.document, ensure_ascii=False), encoding='utf-8')
        module = self._module()
        with mock.patch.dict(os.environ, self.environment):
            self.assertFalse(module._library_store_active())
            self.assertEqual(module._read_prompt_data_cached(), self.document)

    def test_json_mode_is_unchanged(self):
        module = self._module({'UW_LIBRARY_STORE': 'json', 'UW_SKIP_LIBRARY_WARMUP': '1'})
        (self.store_dir / 'data.json').write_text(
            json.dumps(self.document, ensure_ascii=False), encoding='utf-8')
        with mock.patch.dict(os.environ, {'UW_LIBRARY_STORE': 'json'}):
            self.assertFalse(module._library_store_active())
            self.assertEqual(module._read_prompt_data_cached(), self.document)

    def test_auto_export_integration(self):
        environment = {
            'UW_LIBRARY_STORE': 'sqlite', 'UW_SKIP_LIBRARY_WARMUP': '1',
            'UW_DISABLE_SEMANTIC_CACHE': '1',
            'UW_DISABLE_LIBRARY_AUTOBACKUP': '1',
            'UW_LIBRARY_EXPORT_DEBOUNCE_S': '0.1',
            'UW_LIBRARY_EXPORT_INTERVAL_S': '0.1',
        }
        module = self._load_with_maintenance(environment)
        with mock.patch.dict(os.environ, environment):
            data = module._read_prompt_data_cached()
            result = module._apply_upsert_prompt({
                'mode': 'edit', 'base_revision': data['last_modified'],
                'target_category_id': 'cat-a',
                'prompt': {'id': 'p1', 'alias': 'auto', 'prompt': 'auto export',
                           'description': '', 'image': '', 'tags': []},
            })
            self.assertTrue(result['success'])
            self.assertTrue(_wait_for(lambda: (self.store_dir / 'data.json').is_file()),
                            'auto export wrote data.json')
            exported = json.loads((self.store_dir / 'data.json').read_text(encoding='utf-8'))
            self.assertEqual(exported, module._read_prompt_data_cached())
            module._library_store_shutdown()

    def _load_with_maintenance(self, environment):
        module = _load_prompt_selector(uuid.uuid4().hex[:8], self.root, environment)
        self.addCleanup(_close_module, module)
        return module


class _FakeJsonRequest:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}

    async def json(self):
        return dict(self._payload)


class EditPatchO1Tests(unittest.TestCase):
    """The O(1) location map and single-row patch path (real writer functions)."""

    @classmethod
    def setUpClass(cls):
        cls.ls = _load_store_module()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wb-edit-patch-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store_dir = _store_dir(self.root)
        self.db = self.store_dir / 'library.sqlite3'
        self.document = _document()
        store = self.ls.open_store(self.db, create=True)
        try:
            store.initialize_from_document(self.document, receipt={'source_sha256': 'fixture'})
        finally:
            store.close()
        _projection_file(self.store_dir)
        self.environment = {
            'UW_LIBRARY_STORE': 'sqlite', 'UW_SKIP_LIBRARY_WARMUP': '1',
            'UW_DISABLE_SEMANTIC_CACHE': '1', **DISABLE_MAINTENANCE,
        }

    def _module(self, environment=None):
        environment = environment or self.environment
        module = _load_prompt_selector(uuid.uuid4().hex[:8], self.root, environment)
        self.addCleanup(_close_module, module)
        with mock.patch.dict(os.environ, environment):
            module._warm_library_caches(include_packed=False)
        return module

    def _revision(self, module):
        return module._revision(module._read_prompt_data_cached())

    def _scan_locations(self, module):
        data = module._read_prompt_data_cached()
        scanned = {}
        for category_position, category in enumerate(data.get('categories') or []):
            for prompt_index, prompt in enumerate(category.get('prompts') or []):
                scanned[prompt['id']] = (category_position, prompt_index)
        return scanned, data

    def _stored_document(self):
        store = self.ls.open_store(self.db)
        try:
            return store.load_document()
        finally:
            store.close()

    def test_location_map_matches_document(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment):
            state = module._LIBRARY_STATE
            scanned, _ = self._scan_locations(module)
            self.assertEqual(state['locations'], scanned)
            self.assertEqual(state['total_prompts'], 3)

    def test_body_edit_patches_one_row_without_full_scan(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment):
            calls = {'entry': 0}
            original_entry = module._library_entry

            def counted_entry(*args, **kwargs):
                calls['entry'] += 1
                return original_entry(*args, **kwargs)

            with mock.patch.object(module, '_library_entry', counted_entry), \
                    mock.patch.object(module, '_data_row_location',
                                      side_effect=AssertionError('full document scan used')), \
                    mock.patch.object(module, '_scan_prompt_location',
                                      side_effect=AssertionError('scan used for an unchanged row')):
                result = module._apply_upsert_prompt({
                    'mode': 'edit', 'base_revision': self._revision(module),
                    'target_category_id': 'cat-a',
                    'prompt': {'id': 'p1', 'alias': 'a cat v2', 'prompt': 'a cat v2',
                               'description': 'o1 patch', 'image': '', 'tags': []},
                })
            self.assertTrue(result['success'])
            self.assertEqual(calls['entry'], 1)
            scanned, data = self._scan_locations(module)
            self.assertEqual(module._LIBRARY_STATE['locations'], scanned)
            self.assertEqual(module._LIBRARY_STATE['total_prompts'], 3)
            self.assertEqual(self._stored_document()['categories'][0]['prompts'][0]['description'],
                             'o1 patch')
            self.assertFalse((self.store_dir / 'data.json').exists())

    def test_create_and_delete_maintain_the_map_without_scans(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment), \
                mock.patch.object(module, '_scan_prompt_location',
                                  side_effect=AssertionError('scan used for hinted ids')):
            created = module._apply_upsert_prompt({
                'mode': 'create', 'base_revision': self._revision(module),
                'target_category_id': 'cat-a',
                'prompt': {'alias': 'created', 'prompt': 'created body',
                           'description': '', 'image': '', 'tags': []},
            })
            self.assertTrue(created['success'])
            created_id = created['prompt']['id']
            scanned, _ = self._scan_locations(module)
            self.assertEqual(module._LIBRARY_STATE['locations'], scanned)
            self.assertEqual(module._LIBRARY_STATE['total_prompts'], 4)
            module._apply_delete_prompt(created_id, self._revision(module))
            scanned, _ = self._scan_locations(module)
            self.assertEqual(module._LIBRARY_STATE['locations'], scanned)
            self.assertEqual(module._LIBRARY_STATE['total_prompts'], 3)
            module._apply_delete_prompt('p3', self._revision(module))
            scanned, _ = self._scan_locations(module)
            self.assertEqual(module._LIBRARY_STATE['locations'], scanned)
            self.assertEqual(module._LIBRARY_STATE['total_prompts'], 2)
            self.assertNotIn('p3', self._stored_document_flat())

    def _stored_document_flat(self):
        return {prompt['id'] for category in self._stored_document()['categories']
                for prompt in category['prompts']}

    def test_move_keeps_both_categories_locations_correct(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment):
            result = module._apply_upsert_prompt({
                'mode': 'edit', 'base_revision': self._revision(module),
                'target_category_id': 'cat-b',
                'prompt': {'id': 'p2', 'alias': 'a dog', 'prompt': 'a dog',
                           'description': 'moved', 'image': '', 'tags': []},
            })
            self.assertTrue(result['success'])
            scanned, data = self._scan_locations(module)
            self.assertEqual(module._LIBRARY_STATE['locations'], scanned)
            self.assertEqual(module._LIBRARY_STATE['total_prompts'], 3)
            category = data['categories'][1]
            self.assertEqual(category['id'], 'cat-b')
            self.assertEqual(category['prompts'][-1]['id'], 'p2')
            self.assertNotIn('p2', [prompt['id'] for prompt in data['categories'][0]['prompts']])

    def test_plan_and_favorite_use_the_location_map(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment), \
                mock.patch.object(module, '_scan_prompt_location',
                                  side_effect=AssertionError('scan used for a known row')):
            plan = module._apply_plan_flag({'prompt_id': 'p2', 'is_user_plan': False,
                                            'base_revision': self._revision(module)})
            self.assertTrue(plan['success'])
            response = asyncio.run(module.toggle_favorite(_FakeJsonRequest({
                'prompt_id': 'p1', 'category_id': 'cat-a', 'favorite': True,
                'base_revision': self._revision(module),
            })))
            self.assertEqual(response.status, 200)
        stored = self._stored_document()['categories']
        self.assertTrue(stored[0]['prompts'][0]['favorite'])
        self.assertFalse(stored[0]['prompts'][1]['is_user_plan'])
        # The rows did not move: the journal/row order must be untouched.
        self.assertEqual([prompt['id'] for prompt in stored[0]['prompts']], ['p1', 'p2'])
        self.assertEqual([prompt['id'] for prompt in stored[1]['prompts']], ['p3'])

    def test_map_falls_back_to_one_scan_when_missing(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment):
            module._LIBRARY_STATE['locations'].clear()
            result = module._apply_upsert_prompt({
                'mode': 'edit', 'base_revision': self._revision(module),
                'target_category_id': 'cat-a',
                'prompt': {'id': 'p1', 'alias': 'fallback', 'prompt': 'fallback',
                           'description': 'fallback path', 'image': '', 'tags': []},
            })
            self.assertTrue(result['success'])
            scanned, _ = self._scan_locations(module)
            self.assertEqual(module._LIBRARY_STATE['locations'], scanned)
            self.assertEqual(module._LIBRARY_STATE['total_prompts'], 3)
            self.assertEqual(self._stored_document()['categories'][0]['prompts'][0]['description'],
                             'fallback path')

    def test_batch_removed_hint_avoids_scan(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment), \
                mock.patch.object(module, '_scan_prompt_location',
                                  side_effect=AssertionError('scan used for removed ids')):
            file_data = module._library_document_for_batch_write()
            file_data['categories'][0]['prompts'] = [
                prompt for prompt in file_data['categories'][0]['prompts'] if prompt['id'] == 'p1']
            file_data['categories'][1]['prompts'] = []
            result = module._cache_prompt_data(file_data, ['p2', 'p3'],
                                               removed_hint={'p2', 'p3'})
            self.assertFalse(result)
            scanned, _ = self._scan_locations(module)
            self.assertEqual(module._LIBRARY_STATE['locations'], scanned)
            self.assertEqual(module._LIBRARY_STATE['total_prompts'], 1)

    def test_patched_model_matches_full_rebuild(self):
        module = self._module()
        with mock.patch.dict(os.environ, self.environment):
            module._apply_upsert_prompt({
                'mode': 'edit', 'base_revision': self._revision(module),
                'target_category_id': 'cat-a',
                'prompt': {'id': 'p1', 'alias': 'patched', 'prompt': 'patched',
                           'description': 'patched', 'image': '', 'tags': ['x']},
            })
            module._apply_plan_flag({'prompt_id': 'p1', 'is_user_plan': False,
                                     'base_revision': self._revision(module)})
            module._apply_upsert_prompt({
                'mode': 'edit', 'base_revision': self._revision(module),
                'target_category_id': 'cat-b',
                'prompt': {'id': 'p2', 'alias': 'moved', 'prompt': 'moved',
                           'description': '', 'image': '', 'tags': []},
            })
            created = module._apply_upsert_prompt({
                'mode': 'create', 'base_revision': self._revision(module),
                'target_category_id': 'cat-a',
                'prompt': {'alias': 'temp', 'prompt': 'temp', 'description': '',
                           'image': '', 'tags': []},
            })
            module._apply_delete_prompt(created['prompt']['id'], self._revision(module))
            view_false = copy.deepcopy(module._reviewed_library_data(False))
            view_true = copy.deepcopy(module._reviewed_library_data(True))
            index_payload = copy.deepcopy(module._library_index_payload())
            page = copy.deepcopy(module._library_page_payload('', '', 0, 30))
            entries = copy.deepcopy(module._LIBRARY_STATE['entries'])
            module._library_state_reset()
            module._library_rebuild_locked()
            self.assertEqual(module._library_state_locked()['entries'], entries)
            self.assertEqual(module._reviewed_library_data(False), view_false)
            self.assertEqual(module._reviewed_library_data(True), view_true)
            self.assertEqual(module._library_index_payload(), index_payload)
            self.assertEqual(module._library_page_payload('', '', 0, 30), page)

    def test_semantic_store_waits_for_idle_and_resets_timer(self):
        module = self._module({key: value for key, value in self.environment.items()
                              if key != 'UW_DISABLE_SEMANTIC_CACHE'})
        calls = []
        original_flush = module._flush_semantic_cache_snapshot

        def counted_flush(*args, **kwargs):
            calls.append(time.monotonic())
            return original_flush(*args, **kwargs)

        timers = []
        cache_environment = {key: value for key, value in self.environment.items()
                             if key != 'UW_DISABLE_SEMANTIC_CACHE'}
        environment = {**cache_environment, 'UW_LIBRARY_SEMANTIC_STORE_IDLE_S': '0.4'}
        with mock.patch.dict(os.environ, environment), \
                mock.patch.object(module, '_SEMANTIC_STORE_SNAPSHOT_LIMIT', 0), \
                mock.patch.object(module, '_flush_semantic_cache_snapshot', counted_flush):
            for index in range(3):
                module._apply_upsert_prompt({
                    'mode': 'edit', 'base_revision': self._revision(module),
                    'target_category_id': 'cat-a',
                    'prompt': {'id': 'p1', 'alias': 'idle', 'prompt': 'idle body',
                               'description': 'idle %d' % index, 'image': '', 'tags': []},
                })
                timers.append(module._SEMANTIC_CACHE_STORE['timer'])
                time.sleep(0.1)
            self.assertIsNotNone(timers[0])
            self.assertIsNot(timers[0], timers[1])
            self.assertIsNot(timers[1], timers[2])
            time.sleep(0.15)
            self.assertEqual(calls, [], 'the idle timer must not fire after an edit')
            self.assertTrue(_wait_for(lambda: len(calls) >= 1, timeout=5.0),
                            'snapshot runs once the library has been idle long enough')
            self.assertEqual(len(calls), 1)
            self.assertIsNone(module._SEMANTIC_CACHE_STORE['timer'])

    def test_shutdown_forces_pending_semantic_store(self):
        module = self._module({key: value for key, value in self.environment.items()
                              if key != 'UW_DISABLE_SEMANTIC_CACHE'})
        calls = []
        original_flush = module._flush_semantic_cache_snapshot

        def counted_flush(*args, **kwargs):
            calls.append(kwargs.get('force'))
            return original_flush(*args, **kwargs)

        cache_environment = {key: value for key, value in self.environment.items()
                             if key != 'UW_DISABLE_SEMANTIC_CACHE'}
        environment = {**cache_environment, 'UW_LIBRARY_SEMANTIC_STORE_IDLE_S': '60'}
        with mock.patch.dict(os.environ, environment), \
                mock.patch.object(module, '_SEMANTIC_STORE_SNAPSHOT_LIMIT', 0), \
                mock.patch.object(module, '_flush_semantic_cache_snapshot', counted_flush):
            module._apply_upsert_prompt({
                'mode': 'edit', 'base_revision': self._revision(module),
                'target_category_id': 'cat-a',
                'prompt': {'id': 'p1', 'alias': 'shutdown', 'prompt': 'shutdown body',
                           'description': 'shutdown', 'image': '', 'tags': []},
            })
            self.assertIsNotNone(module._SEMANTIC_CACHE_STORE['timer'])
            module._library_store_shutdown()
            self.assertIn(True, calls, 'shutdown forces the pending snapshot')

    def test_edit_patch_matches_rebuild_without_row_index(self):
        module = self._module()
        categories_seen = []
        original_shift = module._shift_view_index

        def counted_shift(view, view_index, category_position, from_item, delta):
            categories_seen.append(category_position)
            return original_shift(view, view_index, category_position, from_item, delta)

        with mock.patch.dict(os.environ, self.environment), \
                mock.patch.object(module, '_shift_view_index', counted_shift):
            module._apply_upsert_prompt({
                'mode': 'edit', 'base_revision': self._revision(module),
                'target_category_id': 'cat-a',
                'prompt': {'id': 'p1', 'alias': 'a cat', 'prompt': 'a completely different body',
                           'description': '', 'image': '', 'tags': []},
            })
            snapshot = {
                'view': copy.deepcopy(module._LIBRARY_STATE['views'].get(False)),
                'rows': copy.deepcopy(module._LIBRARY_STATE['rows'].get(False)),
                'view_index': dict(module._LIBRARY_STATE['view_index'].get(False) or {}),
            }
            module._library_state_reset()
            module._library_rebuild_locked()
            module._reviewed_library_data(False)
            module._library_page_payload('', '', 0, 30)
        self.assertEqual(module._LIBRARY_STATE['views'].get(False), snapshot['view'])
        self.assertEqual(module._LIBRARY_STATE['rows'].get(False), snapshot['rows'])
        self.assertEqual(module._LIBRARY_STATE['view_index'].get(False), snapshot['view_index'])


if __name__ == '__main__':
    unittest.main()
