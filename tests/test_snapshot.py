import hashlib
import contextlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
SPEC = importlib.util.spec_from_file_location('snapshot', Path(__file__).resolve().parents[1] / 'scripts/snapshot.py')
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


class SnapshotTests(unittest.TestCase):
    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for relative in ['../elsewhere', '/absolute', '.', r'ComfyUI\main.py', 'C:/absolute', 'C:relative',
                             'a/../b', 'a//b', 'a/./b', 'a/', 'a./b', 'a /b', 'NUL.txt', 'a:stream', '']:
                with self.assertRaises(ValueError):
                    snapshot.safe_path(Path(temp), relative)

    def test_upstream_attributes_are_archived_without_applying_to_snapshot(self):
        self.assertEqual(snapshot.payload_relative('ComfyUI/.gitattributes'), 'runtime/ComfyUI/.gitattributes.upstream')
        self.assertEqual(snapshot.payload_relative('ComfyUI/main.py'), 'runtime/ComfyUI/main.py')

    def test_credentials_detected_without_returning_values(self):
        secret = 'sk-' + 'aB3dE5fG7hI9jK1mN3pQ5rS7uV9xY1zA3'
        result = snapshot.suspects('key=' + secret)
        self.assertTrue(result)
        self.assertNotIn(secret, str(result))
        self.assertFalse(snapshot.suspects('api_key = "your_example_api_key"'))

    def test_private_config_selection(self):
        for name in ['providers.json', 'settings.json', 'config.json', '.env', 'credentials.yaml']:
            self.assertTrue(snapshot.PRIVATE_NAME.fullmatch(name))
        self.assertFalse(snapshot.PRIVATE_NAME.fullmatch('settings.json.example'))
        self.assertTrue(snapshot.private_config(snapshot.WB + '/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/init.json'))
        self.assertFalse(snapshot.private_config('ComfyUI/comfy/text_encoders/byt5_tokenizer/added_tokens.json'))
        self.assertFalse(snapshot.private_config('ComfyUI/custom_nodes/comfyui-easy-use/locales/zh/settings.json'))

    def test_wal_guard_detects_write_without_main_change(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp)/'live.db'
            with contextlib.closing(sqlite3.connect(file)) as conn:
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('CREATE TABLE items(value TEXT)')
                conn.commit()
                before = snapshot.database_state(file)
                conn.execute('INSERT INTO items VALUES(?)', ('new value',))
                conn.commit()
                after = snapshot.database_state(file)
                self.assertEqual(before['source_main_sha256'], after['source_main_sha256'])
                self.assertNotEqual(before['source_wal_sha256'], after['source_wal_sha256'])

    def test_unlisted_file_and_private_config_fail_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot.save(root/'manifest.json', {'source_root': str(root/'live'), 'files': []})
            self.assertTrue(snapshot.verify(root)['pass'])
            (root/'.env').write_text('secret config', encoding='utf-8')
            reasons = {entry['reason'] for entry in snapshot.verify(root)['failures']}
            self.assertIn('unlisted_payload', reasons)
            self.assertIn('private_config_payload', reasons)

    def test_split_roundtrip_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = b'first\r\n' + '中文'.encode() * 800 + b'\nlast\x00'
            source = root/'input'; source.write_bytes(data)
            previous = snapshot.CHUNK; snapshot.CHUNK = 64
            try:
                parts = snapshot.split_file(source, root/'parts')
            finally:
                snapshot.CHUNK = previous
            self.assertEqual(b''.join((root/'parts'/p['path']).read_bytes() for p in parts), data)

    def test_top_level_asset_exclusions_preserve_nested_source_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in ['models/weight.txt', 'input/private.txt', 'comfy/ldm/models/autoencoder.py', 'comfy_api/input/basic_types.py']:
                path=root/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('test', encoding='utf-8')
            files={path.relative_to(root).as_posix() for path in snapshot.walk(root, snapshot.SKIP_DIRS-{'input','output','temp'}, {'models','input','output','temp'})}
            self.assertEqual(files, {'comfy/ldm/models/autoencoder.py','comfy_api/input/basic_types.py'})

    def test_sql_restore_and_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); payload=root/'snapshot'; payload.mkdir()
            source=root/'source.db'
            with contextlib.closing(sqlite3.connect(source)) as conn:
                conn.executescript('CREATE TABLE items(id INTEGER PRIMARY KEY, text TEXT, blob BLOB); CREATE INDEX text_idx ON items(text);')
                conn.execute('INSERT INTO items VALUES(?,?,?)', (1,"quoted ' text\r\nwith semicolon;\rand 中文",b'\x00\xff'))
                conn.commit()
                dump='\n'.join(conn.iterdump())+'\n'
            sql=root/'dump.sql';sql.write_text(dump,encoding='utf-8',newline='\n')
            parts=snapshot.split_file(sql,payload/'sql')
            entry={'source':'ComfyUI/user/test.db','path':'sql','kind':'sqlite_sql','sql_sha256':hashlib.sha256(dump.encode()).hexdigest(),'parts':parts,'tables':{'items':1}}
            snapshot.save(payload/'manifest.json',{'source_root':str(root/'live'),'files':[entry]})
            self.assertTrue(snapshot.verify(payload)['pass'])
            destination=root/'restored'
            snapshot.materialize(payload,destination)
            with contextlib.closing(sqlite3.connect(destination/'ComfyUI/user/test.db')) as conn:
                self.assertEqual(conn.execute('SELECT blob FROM items').fetchone()[0],b'\x00\xff')
                self.assertEqual(conn.execute('SELECT text FROM items').fetchone()[0],"quoted ' text\r\nwith semicolon;\rand 中文")
            with self.assertRaises(FileExistsError):snapshot.materialize(payload,destination)
            (payload/'sql'/parts[0]['path']).write_bytes(b'broken')
            self.assertFalse(snapshot.verify(payload)['pass'])

    def test_gallery_format_is_bound_to_reviewed_source(self):
        entry = {'source': snapshot.GALLERY_DATABASE, 'path': 'library/sql/gallery',
                 'kind': 'sqlite_sql', 'sql_format': snapshot.GALLERY_FTS5,
                 'sql_sha256': hashlib.sha256(b'fixture').hexdigest(), 'tables': {}, 'parts': []}
        self.assertEqual(snapshot.manifest_path_failures({'files': [entry]}), [])
        for fmt, source in (([], snapshot.GALLERY_DATABASE), ('unknown', snapshot.GALLERY_DATABASE),
                            (snapshot.GALLERY_FTS5, 'ComfyUI/user/other.db')):
            with self.subTest(fmt=fmt, source=source):
                failures = snapshot.manifest_path_failures({'files': [{**entry, 'sql_format': fmt, 'source': source}]})
                self.assertIn('unreviewed_sql_format', {row['reason'] for row in failures})

    def test_duplicate_sources_are_rejected_before_restore_directory_creation(self):
        for duplicate in ['ComfyUI/main.py', 'comfyui/MAIN.PY']:
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                payload = root / 'snapshot'
                payload.mkdir()
                entries = []
                for name, source in [('a.txt', 'ComfyUI/main.py'), ('b.txt', duplicate)]:
                    file = payload / name
                    file.write_text(name, encoding='utf-8')
                    entries.append({'source': source, 'path': name, 'kind': 'file', 'sha256': snapshot.digest(file)})
                snapshot.save(payload / 'manifest.json', {'source_root': str(root / 'live'), 'files': entries})
                result = snapshot.verify(payload)
                self.assertFalse(result['pass'])
                self.assertIn('duplicate_source_path', {item['reason'] for item in result['failures']})
                with self.assertRaises(RuntimeError):
                    snapshot.materialize(payload, root / 'restored')
                self.assertFalse((root / 'restored').exists())

    def test_payload_metadata_and_part_ownership_cannot_be_reused(self):
        sha = hashlib.sha256(b'fixture').hexdigest()
        def file(source, path):
            return {'source': source, 'path': path, 'kind': 'file', 'sha256': sha}
        chunk = {'source': 'ComfyUI/library.json', 'path': 'library/parts', 'kind': 'chunks', 'sha256': sha,
                 'parts': [{'path': '00000.part', 'sha256': sha}]}
        cases = [
            {'files': [file('ComfyUI/a.py', 'payload.txt'), file('ComfyUI/b.py', 'PAYLOAD.TXT')]},
            {'files': [file('ComfyUI/a.py', 'payload.txt')], 'metadata_files': [{'path': 'payload.txt', 'sha256': sha}]},
            {'files': [chunk], 'metadata_files': [{'path': 'library/parts/00000.part', 'sha256': sha}]},
            {'files': [chunk, {**chunk, 'source': 'ComfyUI/other.json'}]},
            {'files': [{**chunk, 'parts': chunk['parts'] * 2}]},
            {'files': [file('ComfyUI/a.py', 'manifest.json')]},
            {'files': [], 'metadata_files': [{'path': 'verification.json', 'sha256': sha}]},
        ]
        for manifest in cases:
            with self.subTest(manifest=manifest):
                self.assertIn('duplicate_payload_path', {item['reason'] for item in snapshot.manifest_path_failures(manifest)})

    def test_source_and_payload_file_directory_conflicts_fail(self):
        sha = hashlib.sha256(b'fixture').hexdigest()
        for entries, expected in [
            ([{'source': 'ComfyUI/a', 'path': 'first.txt', 'kind': 'file', 'sha256': sha},
              {'source': 'ComfyUI/a/b.py', 'path': 'second.txt', 'kind': 'file', 'sha256': sha}], 'source_path_conflict'),
            ([{'source': 'ComfyUI/a.py', 'path': 'payload', 'kind': 'file', 'sha256': sha},
              {'source': 'ComfyUI/b.py', 'path': 'payload/child.txt', 'kind': 'file', 'sha256': sha}], 'payload_path_conflict'),
            ([{'source': 'ComfyUI/a.py', 'path': 'payload/child.txt', 'kind': 'file', 'sha256': sha},
              {'source': 'ComfyUI/b.py', 'path': 'payload', 'kind': 'file', 'sha256': sha}], 'payload_path_conflict'),
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, {item['reason'] for item in snapshot.manifest_path_failures({'files': entries})})

    def test_restore_sql_sidecar_and_receipt_are_reserved_targets(self):
        sha = hashlib.sha256(b'fixture').hexdigest()
        sql = {'source': 'ComfyUI/user/test.db', 'path': 'sql', 'kind': 'sqlite_sql', 'sql_sha256': sha,
               'parts': [{'path': '00000.part', 'sha256': sha}], 'tables': {}}
        for source in ['ComfyUI/user/test.db.restore.sql', 'restore_receipt.JSON']:
            entry = {'source': source, 'path': 'other.txt', 'kind': 'file', 'sha256': sha}
            with self.subTest(source=source):
                self.assertIn('duplicate_source_path', {item['reason'] for item in snapshot.manifest_path_failures({'files': [sql, entry]})})

    def test_manifest_rejects_unknown_kinds_and_nonportable_paths(self):
        sha = hashlib.sha256(b'fixture').hexdigest()
        normal = {'source': 'ComfyUI/a.py', 'path': 'payload.txt', 'kind': 'file', 'sha256': sha}
        for kind in ['unknown', None, [], {}]:
            with self.subTest(kind=kind):
                self.assertIn('invalid_entry_kind', {item['reason'] for item in snapshot.manifest_path_failures({'files': [{**normal, 'kind': kind}]})})
        for value in [r'ComfyUI\escape', '../escape', 'C:/escape', '/escape', 'a/../b', 'a//b']:
            for field in ['source', 'path']:
                with self.subTest(value=value, field=field):
                    self.assertTrue(snapshot.manifest_path_failures({'files': [{**normal, field: value}]}))
            chunk = {**normal, 'kind': 'chunks', 'parts': [{'path': value, 'sha256': sha}]}
            self.assertIn('invalid_part_path', {item['reason'] for item in snapshot.manifest_path_failures({'files': [chunk]})})

    def test_materialize_exclusive_create_does_not_overwrite_newly_appearing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root / 'snapshot'
            payload.mkdir()
            (payload / 'source.txt').write_bytes(b'new content')
            snapshot.save(payload / 'manifest.json', {'source_root': str(root / 'live'), 'files': [
                {'source': 'ComfyUI/main.py', 'path': 'source.txt', 'kind': 'file', 'sha256': snapshot.digest(payload / 'source.txt')}
            ]})
            destination = root / 'restored'
            original_safe_path = snapshot.safe_path
            def competing_file(target_root, relative):
                target = original_safe_path(target_root, relative)
                if target_root == destination and relative == 'ComfyUI/main.py':
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b'keep competing content')
                return target
            with patch.object(snapshot, 'safe_path', side_effect=competing_file), self.assertRaises(FileExistsError):
                snapshot.materialize(payload, destination)
            self.assertEqual((destination / 'ComfyUI/main.py').read_bytes(), b'keep competing content')
            self.assertFalse((destination / 'RESTORE_RECEIPT.json').exists())


if __name__ == '__main__':
    unittest.main()
