import contextlib
import importlib.util
import sqlite3
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('library_sql', REPO/'scripts/library_sql.py')
library_sql = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(library_sql)


class LibrarySqlTests(unittest.TestCase):
    def connection(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        return conn

    def gallery(self):
        conn = self.connection()
        conn.executescript("""CREATE TABLE hot_tags(tag TEXT PRIMARY KEY,translation_cn TEXT);
        CREATE TABLE history(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT,data BLOB);
        CREATE INDEX hot_tag_translation ON hot_tags(translation_cn);
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT) WITHOUT ROWID;
        """)
        conn.execute('INSERT INTO hot_tags(rowid,tag,translation_cn) VALUES(?,?,?)',
                     (17, 'fixture_blue_sky', '虚构蓝天'))
        conn.execute('INSERT INTO hot_tags(rowid,tag,translation_cn) VALUES(?,?,?)',
                     (104, 'fixture_red_flower', '虚构红花'))
        conn.execute('INSERT INTO history(id,value,data) VALUES(?,?,?)',
                     (9, "fixture O'Brien\0text writable_schema INSERT INTO sqlite_master", b'\x00\xff'))
        conn.execute("INSERT INTO history(id,value) VALUES(23,'deleted fixture')")
        conn.execute('DELETE FROM history WHERE id=23')
        conn.execute("INSERT INTO metadata VALUES('fixture','value')")
        conn.execute(library_sql.GALLERY_FTS_DDL)
        conn.execute("INSERT INTO hot_tags_fts(hot_tags_fts) VALUES('rebuild')")
        conn.executescript("""CREATE TRIGGER hot_tags_ai AFTER INSERT ON hot_tags BEGIN
        INSERT INTO hot_tags_fts(rowid,tag,translation_cn)
        VALUES(NEW.rowid,NEW.tag,NEW.translation_cn); END;""")
        return conn

    def test_reviewed_fts_roundtrip_preserves_ids_values_ddl_and_search(self):
        src = self.gallery()
        before = library_sql.summary(src, library_sql.GALLERY_FTS5)
        lines = [statement+'\n' for statement in library_sql.iter_sql(src, library_sql.GALLERY_FTS5)]
        self.assertNotIn('writable_schema', ''.join(lines))
        self.assertNotIn('INSERT INTO "hot_tags_fts_data"', ''.join(lines))
        dst = self.connection()
        after = library_sql.restore_sql(dst, lines, library_sql.GALLERY_FTS5)
        self.assertEqual(before, after)
        self.assertEqual(src.execute('SELECT rowid,* FROM hot_tags ORDER BY rowid').fetchall(),
                         dst.execute('SELECT rowid,* FROM hot_tags ORDER BY rowid').fetchall())
        self.assertEqual(src.execute('SELECT * FROM history').fetchall(), dst.execute('SELECT * FROM history').fetchall())
        self.assertEqual(dst.execute("SELECT rowid FROM hot_tags_fts WHERE hot_tags_fts MATCH 'fixture_blue_sky'").fetchall(), [(17,)])
        self.assertEqual(dst.execute('SELECT seq FROM sqlite_sequence WHERE name=\'history\'').fetchone(), (23,))
        dst.execute("INSERT INTO hot_tags VALUES('fixture_green_tree','虚构绿树')")
        self.assertTrue(dst.execute("SELECT rowid FROM hot_tags_fts WHERE hot_tags_fts MATCH 'fixture_green_tree'").fetchone())

    def test_ordinary_dump_bytes_remain_iterdump(self):
        src = self.connection()
        src.executescript("CREATE TABLE example(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT);INSERT INTO example VALUES(4,'fixture writable_schema INSERT INTO sqlite_master');INSERT INTO example VALUES(12,'deleted fixture');DELETE FROM example WHERE id=12;")
        self.assertEqual(list(library_sql.iter_sql(src)), list(src.iterdump()))
        dst = self.connection()
        after = library_sql.restore_sql(dst, (line+'\n' for line in src.iterdump()))
        self.assertEqual(library_sql.summary(src), after)

    def test_rejects_unknown_virtual_module_and_changed_schema(self):
        conn = self.connection()
        conn.execute('CREATE VIRTUAL TABLE unknown USING fts5(value)')
        for fmt in (library_sql.ITERDUMP, library_sql.GALLERY_FTS5):
            with self.subTest(fmt=fmt), self.assertRaises(ValueError):
                list(library_sql.iter_sql(conn, fmt))
        conn = self.connection()
        conn.execute('CREATE TABLE hot_tags(tag,translation_cn)')
        conn.execute("CREATE VIRTUAL TABLE hot_tags_fts USING fts5(tag,translation_cn,content='hot_tags',content_rowid='rowid',tokenize='porter')")
        with self.assertRaises(ValueError):
            list(library_sql.iter_sql(conn, library_sql.GALLERY_FTS5))

    def test_restore_rejects_schema_writes_unknown_virtual_and_existing_target(self):
        for sql in ('PRAGMA writable_schema=ON;\n', 'CREATE VIRTUAL TABLE unknown USING fts5(value);\n', "ATTACH DATABASE ':memory:' AS outside;\n"):
            with self.subTest(sql=sql), self.assertRaises((ValueError, sqlite3.DatabaseError)):
                library_sql.restore_sql(self.connection(), [sql], library_sql.GALLERY_FTS5)
        conn = self.connection()
        conn.execute('CREATE TABLE existing(value)')
        with self.assertRaises(ValueError):
            library_sql.restore_sql(conn, ['BEGIN TRANSACTION;\n'])

    def test_restore_rejects_incomplete_dump_and_unknown_format(self):
        with self.assertRaises(ValueError):
            library_sql.restore_sql(self.connection(), ['CREATE TABLE unfinished('])
        with self.assertRaises(ValueError):
            list(library_sql.iter_sql(self.connection(), 'unknown'))

    def test_desc_integer_primary_key_keeps_distinct_hidden_rowid(self):
        src = self.gallery()
        src.execute('CREATE TABLE descending(id INTEGER PRIMARY KEY DESC,value TEXT)')
        src.execute("INSERT INTO descending(rowid,id,value) VALUES(42,7,'fixture')")
        src.commit()
        dst = self.connection()
        library_sql.restore_sql(dst, (s+'\n' for s in library_sql.iter_sql(src, library_sql.GALLERY_FTS5)), library_sql.GALLERY_FTS5)
        self.assertEqual(dst.execute('SELECT rowid,id FROM descending').fetchall(), [(42,7)])

    def test_source_stale_fts_fails_instead_of_silently_rebuilding(self):
        src = self.gallery()
        src.execute("UPDATE hot_tags SET translation_cn='changed fixture' WHERE rowid=17")
        src.commit()
        with self.assertRaises(ValueError):
            list(library_sql.iter_sql(src, library_sql.GALLERY_FTS5))

    def test_explicit_stale_index_policy_preserves_business_data_and_records_change(self):
        src = self.gallery()
        src.execute("UPDATE hot_tags SET translation_cn='changed fixture' WHERE rowid=17")
        src.commit()
        before = library_sql.summary(src, library_sql.GALLERY_FTS5, allow_stale_fts=True)
        self.assertFalse(before['fts_source_consistent'])
        dst = self.connection()
        after = library_sql.restore_sql(dst, (s+'\n' for s in library_sql.iter_sql(src, library_sql.GALLERY_FTS5, allow_stale_fts=True)), library_sql.GALLERY_FTS5)
        self.assertTrue(after['fts_source_consistent'])
        for key in ('sql_sha256', 'sql_bytes', 'tables'):
            self.assertEqual(before[key], after[key])
        self.assertEqual(src.execute('SELECT rowid,* FROM hot_tags ORDER BY rowid').fetchall(), dst.execute('SELECT rowid,* FROM hot_tags ORDER BY rowid').fetchall())
        self.assertEqual(src.execute("SELECT rowid FROM hot_tags_fts WHERE hot_tags_fts MATCH 'changed'").fetchall(), [])
        self.assertEqual(dst.execute("SELECT rowid FROM hot_tags_fts WHERE hot_tags_fts MATCH 'changed'").fetchall(), [(17,)])

    def test_literal_whitespace_does_not_change_reviewed_fts_tokenizer(self):
        conn = self.connection()
        conn.execute('CREATE TABLE hot_tags(tag,translation_cn)')
        conn.execute("CREATE VIRTUAL TABLE hot_tags_fts USING fts5(tag,translation_cn,content='hot_tags',content_rowid='rowid',tokenize='unicode61 ')")
        with self.assertRaises(ValueError):
            list(library_sql.iter_sql(conn, library_sql.GALLERY_FTS5))

    def test_all_hidden_rowid_aliases_shadowed_are_rejected(self):
        src = self.gallery()
        src.execute('CREATE TABLE hidden_names(rowid TEXT,_rowid_ TEXT,oid TEXT)')
        src.commit()
        with self.assertRaises(ValueError):
            list(library_sql.iter_sql(src, library_sql.GALLERY_FTS5))

    def test_restoration_denies_external_functions_and_nonexport_pragmas(self):
        for statement in ("PRAGMA temp_store_directory='/outside';\n", "CREATE TABLE example(value);\nINSERT INTO example VALUES(load_extension('outside'));\n"):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.DatabaseError):
                library_sql.restore_sql(self.connection(), statement.splitlines(keepends=True))


if __name__ == '__main__':
    unittest.main()
