import hashlib
import contextlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('snapshot', Path(__file__).resolve().parents[1] / 'scripts/snapshot.py')
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


class SnapshotTests(unittest.TestCase):
    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for relative in ['../elsewhere', '/absolute', '.']:
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


if __name__ == '__main__':
    unittest.main()
