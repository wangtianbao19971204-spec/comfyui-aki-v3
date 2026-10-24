"""Tag 预热延后 + 目录缓存的行为测试（不 import 插件包、不启动 ComfyUI）。

tag_api 沿用 tests/test_tag_api_identity.py 的 stub 惯例按文件加载；tag_library 也按
文件加载，并在临时目录里建一个最小的 tags 库来验证目录缓存的读写与失效。
"""

import asyncio
import importlib.util
import itertools
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = TESTS_DIR.parent


class _StubRoutes:
    def __init__(self):
        self.get_routes = {}

    def get(self, path):
        def decorator(fn):
            self.get_routes[path] = fn
            return fn
        return decorator

    def post(self, path):
        def decorator(fn):
            return fn
        return decorator


class _CountingTagLibrary:
    """Records every library() construction so import-time work is visible."""

    instances = []

    def __init__(self, path):
        self.path = path
        _CountingTagLibrary.instances.append(self)


class _TagConflict(Exception):
    revision = None


class _HookRecorder:
    def __init__(self):
        self.calls = []
        self.module = types.ModuleType('startup_hooks_stub')

        def register_after_start(callback, delay=0.0):
            self.calls.append((callback, delay))
            return True

        self.module.register_after_start = register_after_start


_LOAD_SEQUENCE = itertools.count()


def _server_module(routes, app=None):
    instance = types.SimpleNamespace(routes=routes)
    if app is not None:
        instance.app = app
    module = types.ModuleType('server')
    module.PromptServer = types.SimpleNamespace(instance=instance)
    return module


def _load_tag_api(hooks_module, skip_warmup, app=None):
    """Load tag_api.py with the minimum relative-import surface stubbed out."""
    base = 'warm_pkg_%d' % next(_LOAD_SEQUENCE)
    sys.modules['server'] = _server_module(_StubRoutes(), app)
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
    tag_library.TagConflict = _TagConflict
    tag_library.TagLibrary = _CountingTagLibrary
    tag_library.STRING_AREA_PREFIX = '__tag_strings_area__:'
    tag_library.STRING_GROUP_UUID = '__tag_strings__'
    tag_library.STRING_LOOSE_UUID = '__tag_strings_loose__'
    sys.modules[base + '.prompt_selector.tag_library'] = tag_library

    plan = types.ModuleType(base + '.prompt_selector.tag_import_plan')
    plan.preview_tag_import = lambda *args, **kwargs: {}
    sys.modules[base + '.prompt_selector.tag_import_plan'] = plan

    batch = types.ModuleType(base + '.prompt_selector.tag_batch_jobs')

    class _BatchError(Exception):
        pass

    class _Jobs:
        def __init__(self, *args, **kwargs):
            pass

        def start(self, *args, **kwargs):
            return {}

        def status(self, *args, **kwargs):
            return {}

        def cancel(self, *args, **kwargs):
            return {}

        def export(self, *args, **kwargs):
            return {}

    batch.TagBatchJobs = _Jobs
    batch.BatchConflict = _BatchError
    batch.BatchError = _BatchError
    batch.QueueFull = _BatchError
    batch.UnknownJob = _BatchError
    sys.modules[base + '.prompt_selector.tag_batch_jobs'] = batch

    prompt_store = types.ModuleType(base + '.prompt_selector.prompt_selector')
    prompt_store._read_prompt_data_cached = lambda: {}
    prompt_store._revision = lambda data: 'rev'
    prompt_store._PROMPT_FILE_LOCK = None
    prompt_store.PROMPT_STORE_DIR = str(PACKAGE_DIR / 'user_data' / 'prompt_selector')
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

    class _LinkError(Exception):
        pass

    tag_links.LinkError = _LinkError
    tag_links.LinkConflict = _LinkError
    tag_links.lookup = lambda **kwargs: {}
    tag_links.link = lambda **kwargs: {}
    tag_links.unlink = lambda **kwargs: {}
    sys.modules[base + '.prompt_selector.tag_links'] = tag_links

    sys.modules[base + '.prompt_selector.startup_hooks'] = hooks_module

    spec = importlib.util.spec_from_file_location(base + '.prompt_selector.tag_api', PACKAGE_DIR / 'tag_api.py')
    module = importlib.util.module_from_spec(spec)
    module.__package__ = base + '.prompt_selector'
    sys.modules[base + '.prompt_selector.tag_api'] = module
    environ = {'UW_SKIP_LIBRARY_WARMUP': '1'} if skip_warmup else {}
    with mock.patch.dict(os.environ, environ, clear=False):
        if not skip_warmup:
            os.environ.pop('UW_SKIP_LIBRARY_WARMUP', None)
        spec.loader.exec_module(module)
    return module


class _FakeLibrary:
    def __init__(self):
        self.calls = []

    def categories(self):
        self.calls.append('categories')
        return {'groups': [], 'total': 0, 'revision': 'tags-v1:0'}

    def page(self, *args, **kwargs):
        self.calls.append('page')
        raise AssertionError('page() pre-warm must not run')


class TagWarmDeferralTests(unittest.TestCase):
    def setUp(self):
        _CountingTagLibrary.instances.clear()

    def _wait_for(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def test_import_registers_warmup_after_start_without_running_it(self):
        hooks = _HookRecorder()
        tag_api = _load_tag_api(hooks.module, skip_warmup=False)
        self.assertEqual(len(hooks.calls), 1)
        callback, delay = hooks.calls[0]
        self.assertIs(callback, tag_api._warm_tag_catalog)
        self.assertEqual(delay, 2.0)
        self.assertEqual(_CountingTagLibrary.instances, [])
        self.assertFalse(any(thread.name.startswith('uw-tag') for thread in threading.enumerate()))

    def test_skip_environment_variable_registers_nothing(self):
        hooks = _HookRecorder()
        _load_tag_api(hooks.module, skip_warmup=True)
        self.assertEqual(hooks.calls, [])
        self.assertEqual(_CountingTagLibrary.instances, [])

    def test_warmup_only_builds_the_folder_tree(self):
        hooks = _HookRecorder()
        tag_api = _load_tag_api(hooks.module, skip_warmup=False)
        fake = _FakeLibrary()
        with mock.patch.object(tag_api, 'library', return_value=fake):
            with self.assertLogs('weilin.prompt_selector', level='INFO') as logs:
                tag_api._warm_tag_catalog()
        self.assertEqual(fake.calls, ['categories'])
        self.assertIn('Tag catalog warmed in', '\n'.join(logs.output))

    def test_registered_work_starts_only_when_the_app_starts(self):
        spec = importlib.util.spec_from_file_location('startup_hooks_e2e', PACKAGE_DIR / 'startup_hooks.py')
        real_hooks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(real_hooks)
        real_hooks._REGISTERED.clear()
        self.addCleanup(real_hooks._REGISTERED.clear)

        class _App:
            def __init__(self):
                self.on_startup = []

        app = _App()
        tag_api = _load_tag_api(real_hooks, skip_warmup=False, app=app)
        # 已挂到 aiohttp 启动钩子上，但 import 期没有任何库调用或线程。
        self.assertEqual(len(app.on_startup), 1)
        self.assertEqual(_CountingTagLibrary.instances, [])

        fake = _FakeLibrary()
        with mock.patch.object(tag_api, 'library', return_value=fake):
            asyncio.run(app.on_startup[0](app))
            self.assertTrue(self._wait_for(lambda: fake.calls == ['categories']))
        self.assertEqual(fake.calls, ['categories'])


class StartupHooksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('startup_hooks_under_test', PACKAGE_DIR / 'startup_hooks.py')
        cls.hooks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.hooks)

    def setUp(self):
        self.hooks._REGISTERED.clear()

    def test_app_path_registers_startup_handler_and_runs_callback_in_a_thread(self):
        ran = []
        fired = threading.Event()

        def callback():
            ran.append(True)
            fired.set()

        class _App:
            def __init__(self):
                self.on_startup = []

        app = _App()
        server = types.ModuleType('server')
        server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(app=app))
        with mock.patch.dict(sys.modules, {'server': server}):
            self.assertTrue(self.hooks.register_after_start(callback, delay=0.0))
            self.assertEqual(ran, [])
            self.assertEqual(len(app.on_startup), 1)
            asyncio.run(app.on_startup[0](app))
            self.assertTrue(fired.wait(5.0))
        self.assertEqual(ran, [True])
        self.assertFalse(self.hooks.register_after_start(callback))

    def test_without_an_app_the_work_is_put_on_a_timer(self):
        timers = []

        class _FakeTimer:
            def __init__(self, interval, function, args=(), kwargs=None):
                self.interval = interval
                self.function = function
                self.args = args
                self.daemon = False
                self.started = False
                timers.append(self)

            def start(self):
                self.started = True

        ran = []
        server = types.ModuleType('server')
        server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace())
        with mock.patch.dict(sys.modules, {'server': server}), \
                mock.patch.object(self.hooks.threading, 'Timer', _FakeTimer):
            self.assertTrue(self.hooks.register_after_start(lambda: ran.append(True), delay=2.0))
        self.assertEqual(ran, [])
        self.assertEqual(len(timers), 1)
        self.assertEqual(timers[0].interval, 3.0)
        self.assertTrue(timers[0].started)
        self.assertTrue(timers[0].daemon)


def _execute_tag_sql(path, statements):
    with closing(sqlite3.connect(path)) as conn, conn:
        for statement in statements:
            conn.execute(statement)


def _create_tag_database(path):
    _execute_tag_sql(path, [
        '''CREATE TABLE tag_groups (p_uuid TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT DEFAULT '',
            create_time INTEGER, id_index INTEGER)''',
        '''CREATE TABLE tag_subgroups (g_uuid TEXT PRIMARY KEY, p_uuid TEXT NOT NULL, name TEXT NOT NULL,
            color TEXT DEFAULT '', create_time INTEGER, id_index INTEGER, group_id INTEGER)''',
        '''CREATE TABLE tag_tags (t_uuid TEXT PRIMARY KEY, subgroup_id INTEGER, text TEXT NOT NULL,
            desc TEXT DEFAULT '', color TEXT DEFAULT '', create_time INTEGER, g_uuid TEXT,
            id_index INTEGER)''',
        'CREATE TABLE workbench_tag_meta (tag_uuid TEXT PRIMARY KEY, data TEXT NOT NULL)',
        "INSERT INTO tag_groups VALUES ('area-a', '区域 A', '', 1, 0)",
        "INSERT INTO tag_subgroups VALUES ('folder-a', 'area-a', '子夹 A', '', 2, 0, 0)",
        "INSERT INTO tag_tags VALUES ('tag-a', 0, 'alice', '', '', 3, 'folder-a', 0)",
        "INSERT INTO workbench_tag_meta VALUES ('tag-a', '{\"favorite\": true}')",
    ])


class TagCategoryCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('tag_library_under_test', PACKAGE_DIR / 'tag_library.py')
        cls.tag_library = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tag_library)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='tag-category-cache-')
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self._reset_state)
        self.cache_path = Path(self.directory.name) / 'cache' / 'tag_categories.v1.json'
        self.tag_library._CATEGORY_CACHE_FILE = self.cache_path

    def _reset_state(self):
        self.tag_library._CATEGORY_CACHE.update({'revision': None, 'payload': None})
        self.tag_library._CATEGORY_CACHE_FILE = None
        self.tag_library._CATEGORY_CACHE_DISABLED_LOGGED = False
        self.tag_library.release_string_caches()

    def _clear_memory_cache(self):
        self.tag_library._CATEGORY_CACHE.update({'revision': None, 'payload': None})
        self.tag_library.release_string_caches()

    def _database(self):
        path = Path(self.directory.name) / 'userdatas_zh_CN_tags.db'
        _create_tag_database(path)
        return path

    def _cache_revision(self):
        try:
            return json.loads(self.cache_path.read_text(encoding='utf-8')).get('revision')
        except Exception:
            return None

    def _wait(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def _trace(self, library):
        statements = []
        original = library.connection

        @contextmanager
        def traced():
            with original() as conn:
                conn.set_trace_callback(statements.append)
                try:
                    yield conn
                finally:
                    conn.set_trace_callback(None)

        library.connection = traced
        return statements

    def test_roundtrip_serves_the_folder_tree_without_rescanning(self):
        path = self._database()
        computed = self.tag_library.TagLibrary(path).categories()
        self.assertTrue(self._wait(lambda: self._cache_revision() == computed['revision']))
        document = json.loads(self.cache_path.read_text(encoding='utf-8'))
        self.assertEqual(document['revision'], computed['revision'])
        self.assertEqual(document['payload'], computed)

        self._clear_memory_cache()
        second = self.tag_library.TagLibrary(path)
        statements = self._trace(second)
        second.string_layout = mock.Mock(side_effect=AssertionError('cold scan ran on a cache hit'))
        self.assertEqual(second.categories(), computed)
        joined = '\n'.join(statements)
        self.assertIn('workbench_tag_revision', joined)
        self.assertNotIn('GROUP BY', joined)
        self.assertNotIn('count(*)', joined)

    def test_revision_change_rebuilds_and_rewrites_the_cache(self):
        path = self._database()
        first = self.tag_library.TagLibrary(path)
        old_revision = first.categories()['revision']
        self.assertTrue(self._wait(lambda: self._cache_revision() == old_revision))
        _execute_tag_sql(path, ["UPDATE tag_tags SET text='alice,bob' WHERE t_uuid='tag-a'"])
        self._clear_memory_cache()
        second = self.tag_library.TagLibrary(path)
        statements = self._trace(second)
        rebuilt = second.categories()
        self.assertNotEqual(rebuilt['revision'], old_revision)
        self.assertIn('GROUP BY', '\n'.join(statements))
        self.assertTrue(self._wait(lambda: self._cache_revision() == rebuilt['revision']))

    def test_corrupt_cache_is_ignored_and_replaced(self):
        path = self._database()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text('{not json', encoding='utf-8')
        library = self.tag_library.TagLibrary(path)
        with self.assertLogs('weilin.prompt_selector', level='WARNING') as logs:
            payload = library.categories()
        self.assertEqual(payload['revision'], 'tags-v1:0')
        self.assertIn('缓存', '\n'.join(logs.output))
        self.assertTrue(self._wait(lambda: self._cache_revision() == payload['revision']))

    def test_disable_environment_variable_ignores_and_skips_the_cache(self):
        path = self._database()
        self.tag_library.TagLibrary(path).categories()
        self.assertTrue(self._wait(lambda: self._cache_revision() == 'tags-v1:0'))

        self._clear_memory_cache()
        second = self.tag_library.TagLibrary(path)
        with mock.patch.dict(os.environ, {'UW_DISABLE_TAG_CATEGORY_CACHE': '1'}):
            statements = self._trace(second)
            with self.assertLogs('weilin.prompt_selector', level='INFO') as logs:
                self.assertEqual(second.categories()['revision'], 'tags-v1:0')
        self.assertIn('已禁用', '\n'.join(logs.output))
        self.assertIn('GROUP BY', '\n'.join(statements))

        # 禁用期间即使重建也不再写盘，旧缓存文件保持原样。
        _execute_tag_sql(path, ['UPDATE workbench_tag_revision SET value=value+1 WHERE id=1'])
        self._clear_memory_cache()
        third = self.tag_library.TagLibrary(path)
        with mock.patch.dict(os.environ, {'UW_DISABLE_TAG_CATEGORY_CACHE': '1'}):
            self.assertNotEqual(third.categories()['revision'], 'tags-v1:0')
        self.assertEqual(self._cache_revision(), 'tags-v1:0')


if __name__ == '__main__':
    unittest.main()
