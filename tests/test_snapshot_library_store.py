"""Snapshot capture/restore of the prompt-library SQLite authority.

The prompt library moved from one large ``data.json`` to ``library.sqlite3``. These
tests pin the maintenance contract without importing any runtime plugin code: a small
fixture database is built from the reviewed schema, captured as an ordinary logical
SQL dump plus the ``prompt_library_store_v1`` profile, and restored only when the
rebuilt database still matches the recorded row counts, order and revision.
"""
import contextlib
import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
SPEC = importlib.util.spec_from_file_location('snapshot', REPO / 'scripts/snapshot.py')
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)

LIBRARY_DDL = """
CREATE TABLE library_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    position INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE category_orders (
    category_id TEXT PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
    order_json TEXT NOT NULL
);
CREATE TABLE prompts (
    id TEXT PRIMARY KEY,
    category_id TEXT NOT NULL REFERENCES categories(id),
    payload TEXT NOT NULL
);
CREATE INDEX prompts_by_category ON prompts(category_id);
"""

PROMPT_FILES = ('data.json', 'default.json', 'semantic_projection.json',
                'shared_pairs.json', 'shared_sync_log.json', 'STORE_OWNER.txt')


def build_store(conn, schema_version='1'):
    conn.executescript(LIBRARY_DDL)
    meta = {
        '__schema_version__': json.dumps(schema_version),
        'last_modified': json.dumps('2026-10-25T00:00:00'),
        '__top_level_order__': json.dumps(['version', 'categories', 'settings', 'last_modified']),
        'version': json.dumps('1.6'),
        'settings': json.dumps({'language': 'zh-CN', 'separator': ', '}),
    }
    conn.executemany('INSERT INTO library_meta(key, value) VALUES(?, ?)', meta.items())
    categories = [('cat-a', 'Alpha', 0), ('cat-b', 'Beta', 1)]
    for category_id, name, position in categories:
        payload = {'id': category_id, 'name': name}
        conn.execute('INSERT INTO categories(id, name, position, payload) VALUES(?, ?, ?, ?)',
                     (category_id, name, position, json.dumps(payload, ensure_ascii=False)))
    prompts = [('p1', 'cat-a'), ('p2', 'cat-a'), ('p3', 'cat-b')]
    for prompt_id, category_id in prompts:
        payload = {'id': prompt_id, 'prompt': 'fixture ' + prompt_id}
        conn.execute('INSERT INTO prompts(id, category_id, payload) VALUES(?, ?, ?)',
                     (prompt_id, category_id, json.dumps(payload, ensure_ascii=False)))
    conn.execute('INSERT INTO category_orders(category_id, order_json) VALUES(?, ?)',
                 ('cat-a', json.dumps(['p2', 'p1'])))
    conn.execute('INSERT INTO category_orders(category_id, order_json) VALUES(?, ?)',
                 ('cat-b', json.dumps(['p3'])))
    conn.commit()
    return conn


def memory_store(schema_version='1'):
    conn = sqlite3.connect(':memory:')
    return build_store(conn, schema_version)


def file_store(path, schema_version='1'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(path)) as conn:
        build_store(conn, schema_version)
    return path


def runtime_root(temporary, *, with_store=True, with_data_json=True):
    """A minimal runtime root carrying only the prompt-library payload files."""
    root = Path(temporary) / 'runtime'
    store_dir = root / snapshot.LIBRARY_PROMPT_STORE
    store_dir.mkdir(parents=True)
    for name in PROMPT_FILES:
        if name == 'data.json' and not with_data_json:
            continue
        (store_dir / name).write_bytes(('{"file": "' + name + '"}\n').encode('utf-8'))
    if with_store:
        file_store(root / snapshot.LIBRARY_STORE)
    return root


def dump_lines(conn):
    return [line + '\n' for line in conn.iterdump()]


class LibraryStoreSummaryTests(unittest.TestCase):
    def test_valid_store_summary_pins_rows_order_and_revision(self):
        with contextlib.closing(memory_store()) as conn:
            summary = snapshot.library_store_summary(conn)
        self.assertEqual(summary['profile'], snapshot.LIBRARY_STORE_PROFILE)
        self.assertEqual(summary['schema_version'], '1')
        self.assertEqual(summary['prompt_count'], 3)
        self.assertEqual(summary['category_count'], 2)
        self.assertEqual(summary['counts']['prompts'], 3)
        self.assertEqual(summary['counts']['categories'], 2)
        self.assertEqual(summary['last_modified'], '2026-10-25T00:00:00')
        self.assertEqual(summary['top_level_order'],
                         ['version', 'categories', 'settings', 'last_modified'])
        self.assertEqual(sorted(summary['columns']),
                         ['categories', 'category_orders', 'library_meta', 'prompts'])
        self.assertTrue(summary['order_covers_all_prompts'])
        self.assertEqual(summary['foreign_key_violations'], 0)

    def test_missing_table_or_column_is_rejected(self):
        with contextlib.closing(memory_store()) as conn:
            conn.execute('DROP TABLE prompts')
            conn.commit()
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)
        with contextlib.closing(memory_store()) as conn:
            conn.execute('ALTER TABLE categories RENAME TO categories_old')
            conn.execute('CREATE TABLE categories (id TEXT PRIMARY KEY, name TEXT, position INTEGER)')
            conn.commit()
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)

    def test_schema_version_mismatch_is_rejected(self):
        with contextlib.closing(memory_store(schema_version='2')) as conn:
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)
        with contextlib.closing(memory_store()) as conn:
            conn.execute("DELETE FROM library_meta WHERE key='__schema_version__'")
            conn.commit()
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)
        with contextlib.closing(memory_store()) as conn:
            conn.execute("UPDATE library_meta SET value='not json' WHERE key='__schema_version__'")
            conn.commit()
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)

    def test_missing_or_invalid_revision_is_rejected(self):
        with contextlib.closing(memory_store()) as conn:
            conn.execute("DELETE FROM library_meta WHERE key='last_modified'")
            conn.commit()
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)
        with contextlib.closing(memory_store()) as conn:
            conn.execute("UPDATE library_meta SET value='null' WHERE key='last_modified'")
            conn.commit()
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)

    def test_order_invariants_are_enforced(self):
        def build_change(statement, parameters=()):
            conn = memory_store()
            conn.execute(statement, parameters)
            conn.commit()
            return conn

        cases = [
            ("UPDATE category_orders SET order_json=? WHERE category_id='cat-a'",
             (json.dumps(['p1', 'p9']),)),                       # unknown prompt
            ("UPDATE category_orders SET order_json=? WHERE category_id='cat-a'",
             (json.dumps(['p1', 'p3']),)),                       # cross-category prompt
            ("UPDATE category_orders SET order_json=? WHERE category_id='cat-a'",
             (json.dumps(['p1', 'p2', 'p1']),)),                 # duplicate identity
            ("UPDATE category_orders SET order_json=? WHERE category_id='cat-a'",
             (json.dumps(['p1']),)),                             # p2 uncovered
            ("UPDATE category_orders SET order_json=? WHERE category_id='cat-a'",
             ('not a list',)),                                   # malformed order
            ("DELETE FROM category_orders WHERE category_id='cat-b'", ()),  # missing order row
        ]
        for statement, parameters in cases:
            with self.subTest(statement=statement), contextlib.closing(
                    build_change(statement, parameters)) as conn:
                with self.assertRaises(ValueError):
                    snapshot.library_store_summary(conn)
        with contextlib.closing(memory_store()) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO category_orders(category_id, order_json) VALUES('cat-a', '[]')")
            conn.rollback()

    def test_prompt_payload_and_category_references_are_checked(self):
        with contextlib.closing(memory_store()) as conn:
            conn.execute("UPDATE prompts SET payload='{\"id\": \"p-other\", \"prompt\": \"x\"}' WHERE id='p1'")
            conn.commit()
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)
        with contextlib.closing(memory_store()) as conn:
            conn.execute("INSERT INTO prompts(id, category_id, payload) VALUES('p4', 'ghost', '{\"id\": \"p4\"}')")
            conn.commit()
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)
        with contextlib.closing(memory_store()) as conn:
            conn.execute("UPDATE prompts SET payload='not json' WHERE id='p2'")
            conn.commit()
            with self.assertRaises(ValueError):
                snapshot.library_store_summary(conn)


class LibraryExportPlanTests(unittest.TestCase):
    def test_json_only_runtime_keeps_data_json_as_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = snapshot.library_export_plan(runtime_root(temp, with_store=False))
        self.assertFalse(plan['has_store'])
        self.assertEqual(plan['authority'], 'json')
        data = next(item for item in plan['files'] if item['payload_path'] == 'library/json/data.json')
        self.assertEqual(data['role'], 'authority')
        self.assertEqual(len(plan['files']), len(PROMPT_FILES))

    def test_sqlite_runtime_makes_data_json_an_optional_compatibility_export(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = snapshot.library_export_plan(runtime_root(temp))
        self.assertTrue(plan['has_store'])
        self.assertEqual(plan['authority'], 'sqlite')
        data = next(item for item in plan['files'] if item['payload_path'] == 'library/json/data.json')
        self.assertEqual(data['role'], 'compatibility_export')
        with tempfile.TemporaryDirectory() as temp:
            plan = snapshot.library_export_plan(runtime_root(temp, with_data_json=False))
        self.assertTrue(plan['has_store'])
        self.assertFalse(any(item['payload_path'].endswith('/data.json') for item in plan['files']))

    def test_missing_required_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = runtime_root(temp, with_store=False, with_data_json=False)
            with self.assertRaises(FileNotFoundError):
                snapshot.library_export_plan(root)
        with tempfile.TemporaryDirectory() as temp:
            root = runtime_root(temp)
            (root / snapshot.LIBRARY_PROMPT_STORE / 'semantic_projection.json').unlink()
            with self.assertRaises(FileNotFoundError):
                snapshot.library_export_plan(root)

    def test_reviewed_store_path_is_inside_prompt_store(self):
        self.assertEqual(snapshot.LIBRARY_STORE,
                         snapshot.LIBRARY_PROMPT_STORE + '/library.sqlite3')
        self.assertTrue(snapshot.LIBRARY_STORE.startswith(snapshot.LIBRARY + '/prompt_selector/'))


class SnapshotLibraryCaptureTests(unittest.TestCase):
    def _capture(self, root, out):
        return snapshot.sqlite_export(out, root, snapshot.LIBRARY_STORE,
                                      'library/sql/library.sqlite3', snapshot.ITERDUMP,
                                      snapshot.LIBRARY_STORE_PROFILE)

    def test_sqlite_export_records_profile_and_verifies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = runtime_root(temp)
            snapshot_path = Path(temp) / 'snapshot'
            snapshot_path.mkdir()
            entry = self._capture(root, snapshot_path)
            self.assertEqual(entry['kind'], 'sqlite_sql')
            self.assertEqual(entry['source'], snapshot.LIBRARY_STORE)
            self.assertEqual(entry['library_profile'], snapshot.LIBRARY_STORE_PROFILE)
            with contextlib.closing(sqlite3.connect(root / snapshot.LIBRARY_STORE)) as conn:
                expected = snapshot.library_store_summary(conn)
            self.assertEqual(entry['library_store'], expected)
            self.assertEqual(entry['tables']['prompts'], 3)
            self.assertEqual(len(entry['parts']), 1)
            self.assertEqual(entry['sql_sha256'],
                             hashlib.sha256((snapshot_path / 'library/sql/library.sqlite3'
                                             / entry['parts'][0]['path']).read_bytes()).hexdigest())
            snapshot.save(snapshot_path / 'manifest.json', {
                'source_root': str(Path(temp) / 'live'), 'files': [entry]})
            result = snapshot.verify(snapshot_path)
            self.assertTrue(result['pass'], result['failures'])
            self.assertEqual(snapshot.manifest_path_failures({'files': [entry]}), [])

    def test_manifest_rejects_unreviewed_profiles_and_bad_summaries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = runtime_root(temp)
            entry = self._capture(root, Path(temp) / 'payload')
            other = {**entry, 'source': 'ComfyUI/custom_nodes/other.db',
                     'path': 'library/sql/other', 'parts': []}
            failures = snapshot.manifest_path_failures({'files': [other]})
            self.assertIn('unreviewed_library_profile', {row['reason'] for row in failures})
            for change, reason in [
                ({'library_profile': 'future_profile_v2'}, 'unreviewed_library_profile'),
                ({'sql_format': snapshot.GALLERY_FTS5}, 'unreviewed_library_profile'),
                ({'library_store': {**entry['library_store'], 'schema_version': '2'}},
                 'invalid_library_store_summary'),
                ({'library_store': {**entry['library_store'], 'prompt_count': 4}},
                 'invalid_library_store_summary'),
                ({'library_store': {**entry['library_store'], 'order_covers_all_prompts': False}},
                 'invalid_library_store_summary'),
            ]:
                with self.subTest(change=change):
                    tampered = {**entry, **change}
                    reasons = {row['reason'] for row in
                               snapshot.manifest_path_failures({'files': [tampered]})}
                    self.assertIn(reason, reasons)

    def test_export_rejects_unknown_or_misplaced_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = runtime_root(temp)
            with self.assertRaises(ValueError):
                snapshot.sqlite_export(Path(temp) / 'payload', root, snapshot.LIBRARY_STORE,
                                       'library/sql/library.sqlite3', snapshot.ITERDUMP,
                                       'future_profile_v2')
            with self.assertRaises(ValueError):
                snapshot.sqlite_export(Path(temp) / 'payload', root, snapshot.LIBRARY_STORE,
                                       'library/sql/library.sqlite3', snapshot.GALLERY_FTS5,
                                       snapshot.LIBRARY_STORE_PROFILE)


class SnapshotLibraryRestoreTests(unittest.TestCase):
    def _snapshot(self, temp, *, with_json=True, tamper=None, corrupt=False):
        root = runtime_root(temp)
        out = Path(temp) / 'snapshot'
        out.mkdir()
        entries = [
            snapshot.sqlite_export(out, root, snapshot.LIBRARY_STORE,
                                   'library/sql/library.sqlite3', snapshot.ITERDUMP,
                                   snapshot.LIBRARY_STORE_PROFILE),
        ]
        if with_json:
            source = root / snapshot.LIBRARY_PROMPT_STORE / 'data.json'
            parts = snapshot.split_file(source, out / 'library/json/data.json')
            entries.append({'source': snapshot.LIBRARY_PROMPT_STORE + '/data.json',
                            'path': 'library/json/data.json', 'kind': 'chunks',
                            'sha256': snapshot.digest(source), 'bytes': source.stat().st_size,
                            'parts': parts, 'role': 'compatibility_export'})
        if corrupt:
            entry = entries[0]
            part = out / entry['path'] / entry['parts'][0]['path']
            broken = part.read_bytes()[:40]
            part.write_bytes(broken)
            entry['parts'][0]['sha256'] = hashlib.sha256(broken).hexdigest()
            entry['sql_sha256'] = hashlib.sha256(broken).hexdigest()
        if tamper is not None:
            tamper(entries[0])
        snapshot.save(out / 'manifest.json', {
            'source_root': str(Path(temp) / 'live'), 'files': entries,
            'library_authority': 'sqlite', 'library_json_export': 'compatibility_export'})
        return out, root

    def test_materialize_rebuilds_the_database_and_checks_the_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            payload, root = self._snapshot(temp)
            destination = Path(temp) / 'restored'
            receipt = snapshot.materialize(payload, destination)
            restored = destination / snapshot.LIBRARY_STORE
            self.assertTrue(restored.is_file())
            self.assertTrue(restored.with_suffix(restored.suffix + '.restore.sql').is_file())
            with contextlib.closing(sqlite3.connect(restored)) as conn:
                summary = snapshot.library_store_summary(conn)
                self.assertEqual(conn.execute('SELECT id, category_id FROM prompts ORDER BY id').fetchall(),
                                 [('p1', 'cat-a'), ('p2', 'cat-a'), ('p3', 'cat-b')])
            expected = snapshot.sqlite_export(Path(temp) / 'again', root, snapshot.LIBRARY_STORE,
                                              'library/sql/library.sqlite3', snapshot.ITERDUMP,
                                              snapshot.LIBRARY_STORE_PROFILE)['library_store']
            self.assertEqual(summary, expected)
            self.assertEqual((destination / snapshot.LIBRARY_PROMPT_STORE / 'data.json').read_bytes(),
                             (root / snapshot.LIBRARY_PROMPT_STORE / 'data.json').read_bytes())
            by_path = {check['path']: check for check in receipt['checks']}
            self.assertTrue(by_path[snapshot.LIBRARY_STORE]['library_store_match'])
            self.assertEqual(by_path[snapshot.LIBRARY_STORE]['library_profile'],
                             snapshot.LIBRARY_STORE_PROFILE)
            self.assertEqual(receipt['snapshot_verification']['pass'], True)

    def test_materialize_rejects_a_mismatched_profile_or_corrupt_dump(self):
        def bump(entry):
            store = entry['library_store']
            store['prompt_count'] += 1
            store['counts']['prompts'] += 1

        for tamper, corrupt in ((bump, False), (None, True)):
            with self.subTest(tamper=tamper, corrupt=corrupt), tempfile.TemporaryDirectory() as temp:
                payload, _root = self._snapshot(temp, tamper=tamper, corrupt=corrupt)
                destination = Path(temp) / 'restored'
                with self.assertRaises((RuntimeError, ValueError, sqlite3.DatabaseError)):
                    snapshot.materialize(payload, destination)
                self.assertFalse((destination / 'RESTORE_RECEIPT.json').exists())

    def test_manifest_tampering_fails_verification_before_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            payload, _root = self._snapshot(temp, with_json=False)
            manifest = json.loads((payload / 'manifest.json').read_text(encoding='utf-8'))
            manifest['library_authority'] = 'remote'
            snapshot.save(payload / 'manifest.json', manifest)
            self.assertIn('invalid_library_authority',
                          {row['reason'] for row in snapshot.verify(payload)['failures']})
            destination = Path(temp) / 'restored'
            with self.assertRaises(RuntimeError):
                snapshot.materialize(payload, destination)
            self.assertFalse((destination / 'RESTORE_RECEIPT.json').exists())


if __name__ == '__main__':
    unittest.main()
