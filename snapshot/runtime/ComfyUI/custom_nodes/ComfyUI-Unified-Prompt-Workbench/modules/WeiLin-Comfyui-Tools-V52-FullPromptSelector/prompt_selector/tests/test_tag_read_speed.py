"""Tag 读取加速（表达式索引 + 主题/收藏组派生表 + 单遍搜索）的行为测试。

不启动 ComfyUI、不 import 插件包、不碰生产数据：用临时目录里的小 tags 库，对比
“原 SQL（经 UW_DISABLE_TAG_READ_INDEX 强制回退）”和“索引路径”的 items/total/order，
并覆盖派生表迁移、触发器同步、版本重建、失败回退与 tag_api 预热缓存键。
"""

import contextlib
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = TESTS_DIR.parent


def _load_tag_library():
    spec = importlib.util.spec_from_file_location('tag_library_read_speed', PACKAGE_DIR / 'tag_library.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TAG_LIBRARY = _load_tag_library()

# --- tag 库夹具（一个区域里既有基础 Tag 子夹、也有整组被判定成「tags 串」的子夹） ---
SCOPE_VERSION = 'tags-v1:0'


def _execute(sql_path, statements):
    with contextlib.closing(sqlite3.connect(sql_path)) as conn, conn:
        for statement in statements:
            conn.execute(statement)


TAGS = [
    # (t_uuid, g_uuid, text, desc, create_time, id_index, metadata)
    ('t01', 'fa-base', 'alice', '', 10, 0, {}),
    ('t02', 'fa-base', 'alice,bob', '', 11, 1, {}),
    ('t03', 'fa-base', 'carol,dave,eve', '', 11, 2, {}),
    ('t04', 'fa-base', 'frank,grace,heidi,ivan', '', 12, 3, {}),
    ('t05', 'fa-base', 'a,b,c,d,e', '', 13, 4, {}),
    ('t06', 'fa-base', 'hair', '', 20, 5, {}),
    ('t07', 'fa-base', 'hair brush', '', 21, 6, {}),
    ('t08', 'fa-base', 'hair style', '', 21, 7, {}),
    ('t09', 'fa-base', 'long hair', '', 100, 8, {}),
    ('t10', 'fa-base', 'curly', 'hair care', 99, 9, {}),
    ('t11', 'fa-base', 'redhair', '', 101, 10, {}),
    ('t12', 'fa-base', 'favorite tag', '', 14, 11, {'favorite': True}),
    ('t13', 'fa-base', 'theme tag', '', 15, 12, {'themes': ['theme-x']}),
    ('t14', 'fa-base', 'collect tag', '', 16, 13, {'collection_ids': ['grp-a']}),
    ('t15', 'fa-base', 'default tag', '', 17, 14, {'collection_ids': ['default']}),
    ('t16', 'fa-base', 'extra folder', '', 18, 15, {'folder_ids': ['fb-base']}),
    ('t17', 'fa-base', 'under_score', '', 19, 16, {}),
    ('t18', 'fa-base', 'multi words a,b,c,d,e,f', '', 5, 17, {}),
    ('t20', 'fa-str1', 's1,a,b,c,d,e,f', '', 30, 18, {}),
    ('t21', 'fa-str1', 's2,a,b,c,d,e', '', 31, 19, {}),
    ('t22', 'fb-base', 'paint', '', 40, 20, {}),
    ('t23', 'fb-base', 'hair brush', '', 41, 21, {}),
    ('t24', 'fb-base', 'other', '', 42, 22, {'themes': ['theme-y']}),
    ('t25', 'fb-base', 'border', '', 43, 23, {'folder_ids': ['fa-base']}),
]

GROUPS = [('area-a', '区域 A', 0, 0), ('area-b', '区域 B', 0, 1)]
SUBGROUPS = [
    ('fa-base', 'area-a', '基础 A', 2, 0, 0),
    ('fa-str1', 'area-a', '串 A1', 3, 1, 0),
    ('fb-base', 'area-b', '基础 B', 2, 2, 1),
]


def _create_tag_database(path, with_read_index=False):
    statements = [
        'CREATE TABLE tag_groups (p_uuid TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT DEFAULT "", '
        'create_time INTEGER, id_index INTEGER)',
        "CREATE TABLE tag_subgroups (g_uuid TEXT PRIMARY KEY, p_uuid TEXT NOT NULL, name TEXT NOT NULL, "
        "color TEXT DEFAULT '', create_time INTEGER, id_index INTEGER, group_id INTEGER)",
        "CREATE TABLE tag_tags (t_uuid TEXT PRIMARY KEY, subgroup_id INTEGER, text TEXT NOT NULL, "
        "desc TEXT DEFAULT '', color TEXT DEFAULT '', create_time INTEGER, g_uuid TEXT, id_index INTEGER)",
        'CREATE TABLE workbench_tag_meta (tag_uuid TEXT PRIMARY KEY, data TEXT NOT NULL)',
    ]
    for p_uuid, name, create_time, id_index in GROUPS:
        statements.append(f"INSERT INTO tag_groups VALUES ('{p_uuid}', '{name}', '', {create_time}, {id_index})")
    for g_uuid, p_uuid, name, create_time, id_index, group_id in SUBGROUPS:
        statements.append(f"INSERT INTO tag_subgroups VALUES ('{g_uuid}', '{p_uuid}', '{name}', '', "
                          f'{create_time}, {id_index}, {group_id})')
    for t_uuid, g_uuid, text, desc, create_time, id_index, metadata in TAGS:
        statements.append(
            f"INSERT INTO tag_tags VALUES ('{t_uuid}', 0, '{text}', '{desc}', '', {create_time}, "
            f"'{g_uuid}', {id_index})")
        if metadata:
            payload = json.dumps(metadata, ensure_ascii=False).replace("'", "''")
            statements.append(f"INSERT INTO workbench_tag_meta VALUES ('{t_uuid}', '{payload}')")
    _execute(path, statements)
    library = TAG_LIBRARY.TagLibrary(path)
    if with_read_index:
        library.prepare_read_index()
    return library


class _TempDatabase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='tag-read-speed-')
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self._reset_module_state)
        self.path = Path(self.directory.name) / 'userdatas_zh_CN_tags.db'
        self.addCleanup(self._clear_caches)

    def _reset_module_state(self):
        TAG_LIBRARY._PAGE_CACHE.clear()
        TAG_LIBRARY._READ_INDEX_BUILDING.clear()
        TAG_LIBRARY._SEARCH_CACHE_FILE = None
        TAG_LIBRARY._SEARCH_ORDER.clear()
        TAG_LIBRARY._SEARCH_BUILDING.clear()
        TAG_LIBRARY.release_string_caches()

    def _clear_caches(self):
        TAG_LIBRARY._PAGE_CACHE.clear()

    def build(self):
        return _create_tag_database(self.path)

    def built(self):
        return _create_tag_database(self.path, with_read_index=True)

    @staticmethod
    def _legacy(library, **kwargs):
        with mock.patch.dict(os.environ, {'UW_DISABLE_TAG_READ_INDEX': '1'}):
            TAG_LIBRARY._PAGE_CACHE.clear()
            return library.page(**kwargs)

    @staticmethod
    def _indexed(library, **kwargs):
        TAG_LIBRARY._PAGE_CACHE.clear()
        return library.page(**kwargs)

    def assert_page_equal(self, library, **kwargs):
        legacy = self._legacy(library, **kwargs)
        indexed = self._indexed(library, **kwargs)
        self.assertEqual(legacy['total'], indexed['total'], kwargs)
        self.assertEqual([dict(item) for item in legacy['items']],
                         [dict(item) for item in indexed['items']], kwargs)
        return indexed


class ReadIndexMigrationTests(_TempDatabase):
    def test_build_is_idempotent_and_records_its_version(self):
        library = self.build()
        self.assertTrue(library.prepare_read_index())
        self.assertFalse(library.prepare_read_index())
        with library.connection() as conn:
            version = conn.execute('SELECT version FROM workbench_tag_read_meta WHERE id=1').fetchone()[0]
            self.assertEqual(version, TAG_LIBRARY.READ_INDEX_VERSION)
            self.assertEqual(conn.execute('SELECT count(*) FROM workbench_tag_themes').fetchone()[0],
                             sum(len(meta.get('themes', [])) for *_, meta in TAGS))
            self.assertEqual(conn.execute('SELECT count(*) FROM workbench_tag_collections').fetchone()[0],
                             sum(len(meta.get('collection_ids', [])) for *_, meta in TAGS))
            triggers = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'workbench_tag_%'")}
            for table in ('themes', 'collections'):
                for event in ('insert', 'update', 'delete'):
                    self.assertIn(f'workbench_tag_{table}_{event}', triggers)
            self.assertEqual(conn.execute('SELECT count(*) FROM tag_tags').fetchone()[0], len(TAGS))
        # 重建（版本不符）不会产生重复行，也不会改 tag 库 revision。
        with library.connection() as conn, conn:
            revision = conn.execute('SELECT value FROM workbench_tag_revision WHERE id=1').fetchone()[0]
            conn.execute('UPDATE workbench_tag_read_meta SET version=0 WHERE id=1')
        self.assertTrue(library.prepare_read_index())
        with library.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM workbench_tag_themes').fetchone()[0],
                             sum(len(meta.get('themes', [])) for *_, meta in TAGS))
            self.assertEqual(conn.execute('SELECT value FROM workbench_tag_revision WHERE id=1').fetchone()[0],
                             revision)

    def test_missing_or_failed_build_leaves_original_path_in_place(self):
        library = self.build()
        with library.connection() as conn:
            self.assertFalse(library.read_index_ready(conn))
        with mock.patch.object(TAG_LIBRARY.TagLibrary, '_schedule_read_index_build') as schedule:
            result = library.page(query='hair', scope='tags')
            self.assertEqual(result['total'], 7)
            schedule.assert_called_once()
            with mock.patch.object(TAG_LIBRARY.TagLibrary, 'prepare_read_index',
                                   side_effect=sqlite3.OperationalError('boom')):
                with self.assertLogs('weilin.prompt_selector', level='WARNING') as logs:
                    self.assertFalse(library.warm_read_index())
            self.assertIn('Tag 读取索引建立失败', '\n'.join(logs.output))
            self.assert_page_equal(library, query='hair', scope='tags')

    def test_disabled_environment_skips_the_build(self):
        library = self.build()
        with mock.patch.dict(os.environ, {'UW_DISABLE_TAG_READ_INDEX': '1'}), \
                mock.patch.object(TAG_LIBRARY.threading, 'Thread') as thread:
            self.assertFalse(library.warm_read_index())
            with library.connection() as conn:
                self.assertFalse(library.read_index_ready(conn))
            library.page(scope='tags')
        thread.assert_not_called()
        with library.connection() as conn:
            self.assertIsNone(library._read_index_meta(conn))


class FilterEquivalenceTests(_TempDatabase):
    def setUp(self):
        super().setUp()
        self.library = self.built()

    def test_shape_scope_and_default_views_match_original_sql(self):
        cases = [
            dict(query='', scope='tags'),
            dict(query='', shape='atomic', scope='tags'),
            dict(query='', shape='group', scope='tags'),
            dict(query='', shape='string', scope='tags'),
            dict(query='', shape='string', scope='strings'),
            dict(query='', shape='group'),
            dict(query='', scope='strings'),
            dict(query='', offset=5, limit=3, scope='tags'),
            dict(query='', offset=3000, limit=10, scope='tags'),
        ]
        totals = {}
        for kwargs in cases:
            page = self.assert_page_equal(self.library, **kwargs)
            totals[(kwargs.get('shape', ''), kwargs.get('scope', ''))] = page['total']
        self.assertEqual(totals[('', 'tags')], 22)
        self.assertEqual(totals[('string', 'tags')], 3)
        self.assertEqual(totals[('string', 'strings')], 2)

    def test_folder_theme_collection_and_favorite_filters_match_original_sql(self):
        cases = [
            dict(query='', group='area-a', scope='tags'),
            dict(query='', group='area-b', scope='tags'),
            dict(query='', group='area-a'),
            dict(query='', subgroup='fa-base', scope='tags'),
            dict(query='', subgroup='fb-base', scope='tags'),
            dict(query='', theme='theme-x', scope='tags'),
            dict(query='', theme='theme-y'),
            dict(query='', theme='missing-theme', scope='tags'),
            dict(query='', favorite=True, scope='tags'),
            dict(query='', favorite=True),
            dict(query='', collection='default', known_collections=('grp-a', 'grp-b'), scope='tags'),
            dict(query='', collection='grp-a', known_collections=('grp-a', 'grp-b')),
            dict(query='', collection='missing', known_collections=('grp-a',)),
        ]
        results = {tuple(sorted(kwargs.items())): self.assert_page_equal(self.library, **kwargs)['total']
                   for kwargs in cases}
        self.assertEqual(results[tuple(sorted(dict(query='', group='area-a', scope='tags').items()))], 19)
        self.assertEqual(results[tuple(sorted(dict(query='', theme='theme-x', scope='tags').items()))], 1)
        self.assertEqual(results[tuple(sorted(dict(query='', favorite=True).items()))], 1)
        default_total = results[tuple(sorted(dict(query='', collection='default', known_collections=('grp-a', 'grp-b'),
                                                     scope='tags').items()))]
        self.assertEqual(default_total, 21)
        collected = results[tuple(sorted(dict(query='', collection='grp-a', known_collections=('grp-a', 'grp-b')).items()))]
        self.assertEqual(collected, 1)

    def test_duplicate_metadata_values_do_not_break_writes(self):
        # 历史 SQL 写入可能留下重复的 themes/collection_ids：派生表按集合去重，且写入不能被
        # “同一条 INSERT ... SELECT 里重复行”的约束错误打断（upsert 的 UPDATE 触发器路径）。
        payload = json.dumps({'themes': ['theme-dup', 'theme-dup'],
                              'collection_ids': ['grp-a', 'grp-a']}, ensure_ascii=False)
        with self.library.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT INTO workbench_tag_meta VALUES (?,?)', ('t02', payload))
        with self.library.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT INTO workbench_tag_meta VALUES (?,?) '
                         'ON CONFLICT(tag_uuid) DO UPDATE SET data=excluded.data', ('t02', payload))
        with self.library.connection() as conn:
            self.assertEqual([row[0] for row in conn.execute(
                "SELECT theme FROM workbench_tag_themes WHERE tag_uuid='t02'")], ['theme-dup'])
            self.assertEqual([row[0] for row in conn.execute(
                "SELECT collection_id FROM workbench_tag_collections WHERE tag_uuid='t02'")], ['grp-a'])
        self.assertEqual(self.assert_page_equal(self.library, query='', theme='theme-dup')['total'], 1)

    def test_derived_tables_follow_metadata_writes(self):
        with self.library.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            self.library.apply(conn, {'entity': 'tag', 'operation': 'metadata', 'resource_id': 'tag:t01',
                                      'themes': ['theme-new'], 'collection_ids': ['grp-b'], 'favorite': True})
        page = self.assert_page_equal(self.library, query='', theme='theme-new', scope='tags')
        self.assertEqual(page['total'], 1)
        page = self.assert_page_equal(self.library, query='', collection='grp-b', known_collections=('grp-a', 'grp-b'))
        self.assertEqual(page['total'], 1)
        with self.library.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            self.library.apply(conn, {'entity': 'tag', 'operation': 'delete', 'resource_id': 'tag:t01'})
        with self.library.connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM workbench_tag_themes WHERE tag_uuid='t01'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM workbench_tag_collections WHERE tag_uuid='t01'").fetchone()[0], 0)
        page = self.assert_page_equal(self.library, query='', theme='theme-new', scope='tags')
        self.assertEqual(page['total'], 0)


class TextSearchEquivalenceTests(_TempDatabase):
    def setUp(self):
        super().setUp()
        self.library = self.built()

    def test_search_tiers_and_offsets_match_original_sql(self):
        cases = [
            dict(query='hair', scope='tags'),
            dict(query='hair'),
            dict(query='HAIR', scope='tags'),
            dict(query='hair brush', scope='tags'),
            dict(query='hair_style', scope='tags'),
            dict(query='under_score', scope='tags'),
            dict(query='alice,bob', scope='tags'),
            dict(query='apple_zx', scope='tags'),
            dict(query='hair', offset=1, limit=2, scope='tags'),
            dict(query='hair', offset=4, limit=2, scope='tags'),
            dict(query='hair', offset=100, limit=5, scope='tags'),
            dict(query='hair', shape='group', scope='tags'),
            dict(query='hair', favorite=True),
            dict(query='hair', theme='missing-theme', scope='tags'),
        ]
        for kwargs in cases:
            self.assert_page_equal(self.library, **kwargs)

    def test_search_order_is_exact_then_prefix_then_time(self):
        page = self.library.page(query='hair', scope='tags', limit=100)
        ordered = [(item['text'], item.get('match_reason')) for item in page['items']]
        self.assertEqual(ordered, [
            ('hair', 'Tag 精确匹配'),
            ('hair brush', 'Tag 前缀匹配'),
            ('hair brush', 'Tag 前缀匹配'),
            ('hair style', 'Tag 前缀匹配'),
            ('redhair', 'Tag 文本命中'),
            ('long hair', 'Tag 文本命中'),
            ('curly', '说明命中'),
        ])
        self.assertEqual(page['total'], 7)
        # 分页跨层（offset 落在“前缀”和“其余”之间）时顺序仍一致。
        rest = self.library.page(query='hair', scope='tags', offset=3, limit=2)
        self.assertEqual([item['text'] for item in rest['items']], ['hair style', 'redhair'])

    def test_empty_search_result_and_totals(self):
        page = self.assert_page_equal(self.library, query='apple_zx', scope='tags')
        self.assertEqual((page['total'], page['items']), (0, []))


SEARCH_EXTRA_TAGS = [
    # (t_uuid, text, desc, create_time, id_index) —— 中文/组合/大小写查询覆盖
    ('ts01', '女仆装', '', 200, 500),
    ('ts02', '黑色过膝袜', '过膝长袜', 201, 501),
    ('ts03', 'Hair Accessory', '', 202, 502),
    ('ts04', 'zzz-placeholder', 'nothing here', 203, 503),
]


class SearchIndexTests(_TempDatabase):
    """trigram FTS cache + tags 库变更日志：构建/回退/增量同步/语义等价。"""

    def setUp(self):
        super().setUp()
        self.search_cache = Path(self.directory.name) / 'cache' / 'tag_search.v1.db'
        TAG_LIBRARY._SEARCH_CACHE_FILE = self.search_cache
        self._schedule = mock.patch.object(TAG_LIBRARY.TagLibrary, '_schedule_search_index_sync')
        self.schedule = self._schedule.start()
        self.addCleanup(self._schedule.stop)
        self.library = self.built()
        with self.library.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            for t_uuid, text, desc, create_time, id_index in SEARCH_EXTRA_TAGS:
                conn.execute('INSERT INTO tag_tags (t_uuid, subgroup_id, text, desc, color, create_time, '
                             'g_uuid, id_index) VALUES (?,?,?,?,?,?,?,?)',
                             (t_uuid, 0, text, desc, '', create_time, 'fa-base', id_index))
        TAG_LIBRARY._PAGE_CACHE.clear()

    def warm(self):
        self.assertTrue(self.library.warm_search_index())
        return self.library

    @staticmethod
    def _old(library, **kwargs):
        with mock.patch.dict(os.environ, {'UW_DISABLE_TAG_SEARCH_INDEX': '1'}):
            TAG_LIBRARY._PAGE_CACHE.clear()
            return library.page(**kwargs)

    @staticmethod
    def _fast(library, **kwargs):
        TAG_LIBRARY._PAGE_CACHE.clear()
        return library.page(**kwargs)

    def assert_fast_equal(self, **kwargs):
        old = self._old(self.library, **kwargs)
        fast = self._fast(self.library, **kwargs)
        self.assertEqual(old['total'], fast['total'], kwargs)
        self.assertEqual([dict(item) for item in old['items']],
                         [dict(item) for item in fast['items']], kwargs)
        return fast

    def test_build_creates_cache_journal_and_versions(self):
        library = self.warm()
        self.assertTrue(self.search_cache.is_file())
        with library.connection() as conn:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'workbench_tag_search%'")}
            for name in TAG_LIBRARY.SEARCH_TRIGGERS:
                self.assertIn(name, names)
            self.assertIn(TAG_LIBRARY.SEARCH_JOURNAL_TABLE, names)
            self.assertIn(TAG_LIBRARY.SEARCH_SCHEMA_TABLE, names)
            self.assertEqual(library._search_schema_version(conn), TAG_LIBRARY.SEARCH_INDEX_VERSION)
            self.assertEqual(conn.execute('SELECT count(*) FROM workbench_tag_search_journal').fetchone()[0], 0)
        meta = library._search_cache_meta(self.search_cache)
        with contextlib.closing(sqlite3.connect(str(self.path))) as raw:
            self.assertEqual(meta['built_revision'],
                             raw.execute('SELECT value FROM workbench_tag_revision WHERE id=1').fetchone()[0])
        # 第二次 warm 不再重建 cache。
        with mock.patch.object(TAG_LIBRARY.TagLibrary, '_build_search_cache',
                               side_effect=AssertionError('cache rebuilt on a warm hit')):
            self.assertTrue(library.warm_search_index())

    def test_plain_search_matches_original_sql(self):
        library = self.warm()
        queries = ['hair', 'Hair', 'HAIR', 'hair brush', 'hair_brush', 'hair  brush', 'under_score',
                   '女仆装', '黑色过膝袜', 'zzz-placeholder', 'car', 'tag', '100%', 'a b c',
                   'apple_zx', 'ab', '紫', '的']
        for query in queries:
            for offset, limit in ((0, 100), (0, 20), (3, 5), (50, 5)):
                page = self.assert_fast_equal(query=query, offset=offset, limit=limit)
                self.assertEqual(page['offset'], offset)
        for page_kwargs in (dict(query='hair', offset=0, limit=1), dict(query='hair', offset=6, limit=10),
                            dict(query='', offset=0, limit=10)):
            self.assert_fast_equal(**page_kwargs)

    def test_search_tier_order_is_preserved_by_fast_path(self):
        library = self.warm()
        page = self._fast(library, query='hair', offset=0, limit=100)
        self.assertEqual([item['text'] for item in page['items']][:4],
                         ['hair', 'hair brush', 'hair brush', 'hair style'])
        self.assertEqual([item.get('match_reason') for item in page['items']][:4],
                         ['Tag 精确匹配', 'Tag 前缀匹配', 'Tag 前缀匹配', 'Tag 前缀匹配'])
        rest = self._fast(library, query='hair', offset=4, limit=2)
        self.assertEqual([item['text'] for item in rest['items']], ['Hair Accessory', 'redhair'])

    def _spy_fast_numbers(self):
        original = TAG_LIBRARY.TagLibrary._search_fast_numbers
        calls = []

        def spy(instance, conn, query, forms, offset, limit):
            calls.append((query, offset, limit))
            return original(instance, conn, query, forms, offset, limit)

        patcher = mock.patch.object(TAG_LIBRARY.TagLibrary, '_search_fast_numbers', spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_short_and_empty_queries_fall_back(self):
        self.warm()
        calls = self._spy_fast_numbers()
        for query in ('', 'a', 'ab', '紫', '的'):
            self.assert_fast_equal(query=query, offset=0, limit=10)
        self.assertGreater(len(calls), 0)

    def test_filters_keep_using_the_original_paths(self):
        self.warm()
        with mock.patch.object(TAG_LIBRARY.TagLibrary, '_search_fast_numbers',
                               side_effect=AssertionError('fast search used with filters')):
            self.assert_fast_equal(query='hair', scope='tags', offset=0, limit=100)
            self.assert_fast_equal(query='hair', shape='group', scope='tags', offset=0, limit=100)
            self.assert_fast_equal(query='hair', favorite=True, offset=0, limit=100)

    def test_journal_triggers_and_incremental_sync(self):
        library = self.warm()
        with library.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE tag_tags SET text='hair!', desc='' WHERE t_uuid='t06'")
        with library.connection() as conn:
            row = conn.execute('SELECT operation, tag_text, tag_desc FROM workbench_tag_search_journal').fetchone()
        self.assertEqual(tuple(row), ('upsert', 'hair!', ''))
        # 日志未回放时走旧 SQL（结果正确），并调度后台同步。
        self.assert_fast_equal(query='hair', offset=0, limit=100)
        self.schedule.assert_called()
        library._search_sync()
        with library.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM workbench_tag_search_journal').fetchone()[0], 0)
        self.assertTrue(library.warm_search_index())  # 重建内存顺序表
        page = self.assert_fast_equal(query='hair', offset=0, limit=100)
        self.assertIn('hair!', [item['text'] for item in page['items']])

    def test_delete_tag_is_journaled_and_synced(self):
        library = self.warm()
        with library.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("DELETE FROM tag_tags WHERE t_uuid='t06'")
        with library.connection() as conn:
            self.assertEqual(conn.execute('SELECT operation FROM workbench_tag_search_journal').fetchone()[0], 'delete')
        self.assert_fast_equal(query='hair', offset=0, limit=100)
        library._search_sync()
        self.assertTrue(library.warm_search_index())
        page = self.assert_fast_equal(query='hair', offset=0, limit=100)
        self.assertNotIn('hair', [item['text'] for item in page['items']])

    def test_missing_or_version_mismatched_cache_is_rebuilt(self):
        library = self.warm()
        self.search_cache.unlink()
        self.assertTrue(library.prepare_search_index())
        self.assertTrue(self.search_cache.is_file())
        cache = sqlite3.connect(str(self.search_cache))
        with cache:
            cache.execute('UPDATE search_meta SET format=999 WHERE id=1')
        cache.close()
        self.assertIsNone(library._search_cache_meta(self.search_cache))
        self.assertTrue(library.prepare_search_index())
        meta = library._search_cache_meta(self.search_cache)
        self.assertIsNotNone(meta)
        self.assert_fast_equal(query='hair', offset=0, limit=10)

    def test_disabled_environment_skips_everything(self):
        TAG_LIBRARY._SEARCH_ORDER.clear()
        with mock.patch.dict(os.environ, {'UW_DISABLE_TAG_SEARCH_INDEX': '1'}), \
                mock.patch.object(TAG_LIBRARY.threading, 'Thread') as thread:
            self.assertFalse(self.library.warm_search_index())
            self._fast(self.library, query='hair', offset=0, limit=10)
        thread.assert_not_called()
        self.assertFalse(self.search_cache.exists())
        with self.library.connection() as conn:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'workbench_tag_search%'")}
        self.assertEqual(names, set())

    def test_order_array_is_rebuilt_after_tag_writes(self):
        library = self.warm()
        key = str(library.path)
        self.assertIn(key, TAG_LIBRARY._SEARCH_ORDER)
        with library.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE tag_tags SET create_time=12345 WHERE t_uuid='t06'")
        with library.connection() as conn:
            self.assertIsNone(library._search_order(conn))
        self.assertTrue(library.warm_search_index())
        with library.connection() as conn:
            order = library._search_order(conn)
        self.assertIsNotNone(order)
        with contextlib.closing(sqlite3.connect(str(self.path))) as raw:
            self.assertEqual(len(order), raw.execute('SELECT count(*) FROM tag_tags').fetchone()[0])

    def test_too_many_pending_changes_rebuilds_instead_of_replaying(self):
        library = self.warm()
        with mock.patch.object(TAG_LIBRARY, 'SEARCH_REBUILD_PENDING', 2):
            with library.connection() as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                for index in range(3):
                    conn.execute('UPDATE tag_tags SET text=? WHERE t_uuid=?', (f'hair {index}', 't06'))
            with mock.patch.object(TAG_LIBRARY.TagLibrary, '_build_search_cache', wraps=library._build_search_cache) as build:
                library._search_sync()
            self.assertEqual(build.call_count, 1)
        with library.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM workbench_tag_search_journal').fetchone()[0], 0)
        self.assertTrue(library.warm_search_index())
        self.assert_fast_equal(query='hair', offset=0, limit=10)

    def test_restored_older_tags_db_invalidates_cache(self):
        library = self.warm()
        with contextlib.closing(sqlite3.connect(str(self.search_cache))) as cache, cache:
            cache.execute('UPDATE search_meta SET built_revision=built_revision+1 WHERE id=1')
        library._search_sync()
        meta = library._search_cache_meta(self.search_cache)
        with contextlib.closing(sqlite3.connect(str(self.path))) as raw:
            self.assertEqual(meta['built_revision'],
                             raw.execute('SELECT value FROM workbench_tag_revision WHERE id=1').fetchone()[0])
        self.assert_fast_equal(query='hair', offset=0, limit=10)

    def test_warm_failure_is_logged_and_does_not_raise(self):
        with mock.patch.object(TAG_LIBRARY.TagLibrary, '_build_search_cache',
                               side_effect=sqlite3.OperationalError('boom')):
            with self.assertLogs('weilin.prompt_selector', level='WARNING') as logs:
                self.assertFalse(self.library.warm_search_index())
        self.assertIn('Tag 搜索索引预热失败', '\n'.join(logs.output))
        self.assert_fast_equal(query='hair', offset=0, limit=10)


class _FakeWarmLibrary:
    def __init__(self):
        self.calls = []

    def categories(self):
        self.calls.append(('categories',))

    def warm_read_index(self):
        self.calls.append(('warm_read_index',))
        return True

    def page(self, *args, **kwargs):
        self.calls.append(('page', args, kwargs))
        return {'items': [], 'total': 0}


class _StubRoutes:
    def get(self, path):
        def decorator(fn):
            return fn
        return decorator

    def post(self, path):
        def decorator(fn):
            return fn
        return decorator


def _load_tag_api():
    base = 'read_speed_tag_api_pkg'
    sys.modules['server'] = types.ModuleType('server')
    sys.modules['server'].PromptServer = types.SimpleNamespace(
        instance=types.SimpleNamespace(routes=_StubRoutes()))
    package = types.ModuleType(base)
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules[base] = package
    selector_package = types.ModuleType(base + '.prompt_selector')
    selector_package.__path__ = [str(PACKAGE_DIR)]
    sys.modules[base + '.prompt_selector'] = selector_package
    app_package = types.ModuleType(base + '.app')
    app_package.__path__ = []
    sys.modules[base + '.app'] = app_package
    app_server = types.ModuleType(base + '.app.server')
    app_server.__path__ = []
    sys.modules[base + '.app.server'] = app_server
    dao_module = types.ModuleType(base + '.app.server.dao')
    dao_module.dao = types.SimpleNamespace(tags_db_path='never-opened.db')
    sys.modules[base + '.app.server.dao'] = dao_module
    tag_library = types.ModuleType(base + '.prompt_selector.tag_library')
    tag_library.TagConflict = type('TagConflict', (ValueError,), {})
    tag_library.TagLibrary = object
    tag_library.STRING_AREA_PREFIX = '__tag_strings_area__:'
    tag_library.STRING_GROUP_UUID = '__tag_strings__'
    tag_library.STRING_LOOSE_UUID = '__tag_strings_loose__'
    sys.modules[base + '.prompt_selector.tag_library'] = tag_library
    plan = types.ModuleType(base + '.prompt_selector.tag_import_plan')
    plan.preview_tag_import = lambda *args, **kwargs: {}
    sys.modules[base + '.prompt_selector.tag_import_plan'] = plan
    batch = types.ModuleType(base + '.prompt_selector.tag_batch_jobs')
    for name in ('TagBatchJobs', 'BatchConflict', 'BatchError', 'QueueFull', 'UnknownJob'):
        setattr(batch, name, type(name, (Exception,), {}))
    sys.modules[base + '.prompt_selector.tag_batch_jobs'] = batch
    prompt_store = types.ModuleType(base + '.prompt_selector.prompt_selector')
    prompt_store._read_prompt_data_cached = lambda: {}
    prompt_store._revision = lambda data: 'rev'
    prompt_store._PROMPT_FILE_LOCK = None
    prompt_store.PROMPT_STORE_DIR = str(PACKAGE_DIR / 'never-used')
    sys.modules[base + '.prompt_selector.prompt_selector'] = prompt_store
    selector_library = types.ModuleType(base + '.prompt_selector.selector_library')
    selector_library.collection_groups = lambda data: []
    sys.modules[base + '.prompt_selector.selector_library'] = selector_library
    bridge = types.ModuleType(base + '.prompt_selector.tag_identity_bridge')
    bridge.TagIdentityBridge = object
    sys.modules[base + '.prompt_selector.tag_identity_bridge'] = bridge
    item_maintenance = types.ModuleType(base + '.prompt_selector.item_maintenance')
    item_maintenance.read_item = lambda resource_id: {}
    item_maintenance.write_item = lambda resource_id, payload: {}
    sys.modules[base + '.prompt_selector.item_maintenance'] = item_maintenance
    item_batch = types.ModuleType(base + '.prompt_selector.item_batch')
    item_batch.apply_batch = lambda payload: {}
    sys.modules[base + '.prompt_selector.item_batch'] = item_batch
    tag_links = types.ModuleType(base + '.prompt_selector.tag_links')
    for name in ('LinkError', 'LinkConflict'):
        setattr(tag_links, name, type(name, (Exception,), {}))
    tag_links.lookup = lambda **kwargs: {}
    tag_links.link = lambda **kwargs: {}
    tag_links.unlink = lambda **kwargs: {}
    sys.modules[base + '.prompt_selector.tag_links'] = tag_links
    startup_hooks = types.ModuleType(base + '.prompt_selector.startup_hooks')
    startup_hooks.register_after_start = lambda callback, delay=0.0: True
    sys.modules[base + '.prompt_selector.startup_hooks'] = startup_hooks

    spec = importlib.util.spec_from_file_location(base + '.prompt_selector.tag_api', PACKAGE_DIR / 'tag_api.py')
    module = importlib.util.module_from_spec(spec)
    module.__package__ = base + '.prompt_selector'
    sys.modules[base + '.prompt_selector.tag_api'] = module
    with mock.patch.dict(os.environ, {'UW_SKIP_LIBRARY_WARMUP': '1'}):
        spec.loader.exec_module(module)
    return module


class WarmCacheKeyTests(_TempDatabase):
    def test_warm_default_views_only_build_ready_index(self):
        tag_api = _load_tag_api()
        fake = _FakeWarmLibrary()
        with mock.patch.object(tag_api, 'library', return_value=fake), \
                mock.patch.object(tag_api, 'catalog', return_value={'collections': [{'id': 'grp-a'}],
                                                                    'collection_revision': 'rev'}):
            with self.assertLogs('weilin.prompt_selector', level='INFO') as logs:
                tag_api._warm_tag_catalog()
        self.assertEqual(fake.calls[0], ('categories',))
        self.assertEqual(fake.calls[1], ('warm_read_index',))
        pages = [call for call in fake.calls if call[0] == 'page']
        self.assertEqual(len(pages), 16)
        self.assertEqual({call[1][4] for call in pages}, {100, 120})
        scopes = {(call[1][8], call[1][9]) for call in pages}
        self.assertEqual(scopes, {(shape, scope) for scope in ('tags', 'strings')
                                  for shape in ('', 'atomic', 'group', 'string')})
        self.assertTrue(all(call[1][7] == ('grp-a',) for call in pages))
        self.assertIn('Tag catalog warmed in', '\n'.join(logs.output))

    def test_warm_tag_catalog_builds_search_cache_with_real_library(self):
        tag_api = _load_tag_api()
        library = self.build()
        cache = Path(self.directory.name) / 'cache' / 'tag_search.v1.db'
        TAG_LIBRARY._SEARCH_CACHE_FILE = cache
        TAG_LIBRARY._CATEGORY_CACHE_FILE = Path(self.directory.name) / 'cache' / 'tag_categories.v1.json'
        with mock.patch.object(tag_api, 'library', return_value=library), \
                mock.patch.object(tag_api, 'catalog', return_value={'collections': [],
                                                                    'collection_revision': 'rev'}):
            with self.assertLogs('weilin.prompt_selector', level='INFO') as logs:
                tag_api._warm_tag_catalog()
        self.assertTrue(cache.is_file())
        self.assertIn(str(library.path), TAG_LIBRARY._SEARCH_ORDER)
        joined = '\n'.join(logs.output)
        self.assertIn('Tag 搜索索引已就绪', joined)
        self.assertIn('Tag catalog warmed in', joined)

    def test_prewarmed_default_view_is_served_from_cache(self):
        tag_api = _load_tag_api()
        library = self.built()
        with mock.patch.object(tag_api, 'catalog', return_value={'collections': [{'id': 'grp-a'}],
                                                                'collection_revision': 'rev'}):
            self.assertEqual(tag_api._warm_default_tag_views(library), 16)
        for shape in ('', 'atomic', 'group', 'string'):
            for scope in ('tags', 'strings'):
                key = (library.revision(), '', '', '', False, '', ('grp-a',), shape, scope, '')
                self.assertIn(key, TAG_LIBRARY._PAGE_CACHE, (shape, scope))
        statements = []
        original = library.connection

        @contextlib.contextmanager
        def traced():
            with original() as conn:
                conn.set_trace_callback(statements.append)
                try:
                    yield conn
                finally:
                    conn.set_trace_callback(None)

        library.connection = traced
        try:
            page = library.page('', '', '', 0, 100, False, '', ('grp-a',), 'group', 'tags')
        finally:
            library.connection = original
        self.assertEqual(len(page['items']), min(page['total'], 100))
        joined = '\n'.join(' '.join(statement.split()) for statement in statements)
        self.assertNotIn('SELECT count(*) FROM tag_tags', joined)
        self.assertNotIn('SELECT t.id_index', joined)
        self.assertIn('WHERE t.id_index IN (1,2)', joined)


if __name__ == '__main__':
    unittest.main()
