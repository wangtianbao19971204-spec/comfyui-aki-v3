"""Tests for the persistent derived-semantics cache and the deferred warm-up.

``prompt_selector.py`` is loaded from the real source file with a temporary
``__file__`` so every store path points inside the test directory: importing the
module never touches the production user_data directory and never starts
ComfyUI. ``server`` and ``startup_hooks`` are stubbed to the minimum the route
decorators and the registration call need.
"""

import importlib.util
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import msgpack
import zstandard

PROMPT_SELECTOR_DIR = Path(__file__).resolve().parents[1]
PROMPT_SELECTOR_FILE = PROMPT_SELECTOR_DIR / 'prompt_selector.py'
CACHE_FILENAME = 'semantic_cache.v1.msgpack.zst'


class _StubRoutes:
    def __init__(self):
        self.get_routes = {}

    def get(self, path):
        def decorator(handler):
            self.get_routes[path] = handler
            return handler
        return decorator

    def post(self, path):
        def decorator(handler):
            return handler
        return decorator


class _StubPromptServer:
    def __init__(self):
        self.routes = _StubRoutes()


def _install_server_stub():
    module = sys.modules.get('server')
    if module is None:
        module = types.ModuleType('server')
        module.PromptServer = types.SimpleNamespace(instance=_StubPromptServer())
        sys.modules['server'] = module
    return module


def _load_prompt_selector(name, store_root, hooks=None, skip_warmup=None):
    """Import the real module with every data path redirected under ``store_root``."""
    _install_server_stub()
    if skip_warmup is None:
        skip_warmup = hooks is None
    package = 'wb_semantic_test_' + name
    package_name = package + '.prompt_selector'
    root = types.ModuleType(package)
    root.__path__ = [str(PROMPT_SELECTOR_DIR)]
    sys.modules[package] = root
    subpackage = types.ModuleType(package_name)
    subpackage.__path__ = [str(PROMPT_SELECTOR_DIR)]
    sys.modules[package_name] = subpackage
    if hooks is not None:
        hooks_module = types.ModuleType(package_name + '.startup_hooks')
        hooks_module.register_after_start = hooks
        sys.modules[package_name + '.startup_hooks'] = hooks_module
    spec = importlib.util.spec_from_file_location(package_name + '.prompt_selector', PROMPT_SELECTOR_FILE)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = package_name
    # The module derives PROMPT_STORE_DIR from __file__; the temporary path keeps
    # the import-time existence check and fallback write inside the test directory.
    module.__file__ = str(Path(store_root) / 'plugin' / 'prompt_selector.py')
    sys.modules[package_name + '.prompt_selector'] = module
    with mock.patch.dict(os.environ, {}):
        if skip_warmup:
            os.environ['UW_SKIP_LIBRARY_WARMUP'] = '1'
        else:
            os.environ.pop('UW_SKIP_LIBRARY_WARMUP', None)
        spec.loader.exec_module(module)
    return module


def _prompt(identity, text):
    return {'id': identity, 'prompt': text, 'alias': text, 'description': '', 'tags': [],
            'favorite': False, 'image': '', 'created_at': '2026-01-01T00:00:00',
            'updated_at': '2026-01-01T00:00:00', 'usage_count': 0, 'last_used': None}


def _library(prompts):
    return {'version': '1.6', 'last_modified': '2026-01-01T00:00:00',
            'settings': {'language': 'zh-CN', 'separator': ', ', 'save_selection': True},
            'categories': [{'id': 'fixture-category', 'name': 'fixture',
                            'created_at': '2026-01-01T00:00:00', 'updated_at': '2026-01-01T00:00:00',
                            'prompts': prompts}]}


def _prompts(count):
    return [_prompt('p%d' % (index + 1), 'prompt text number %d' % (index + 1))
            for index in range(count)]


def _projection(**overrides):
    document = {'schema': 'S4-semantic-projection-v1', 'decisions': {}, 'class_labels': {}}
    document.update(overrides)
    return document


class SemanticCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = tempfile.TemporaryDirectory(prefix='wb-semantic-store-')
        cls.addClassCleanup(cls.store.cleanup)
        cls.module = _load_prompt_selector('cache', cls.store.name)

    def setUp(self):
        environment = mock.patch.dict(os.environ, {})
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('UW_DISABLE_SEMANTIC_CACHE', None)
        os.environ.pop('UW_SKIP_LIBRARY_WARMUP', None)

        directory = tempfile.TemporaryDirectory(prefix='wb-semantic-case-')
        self.addCleanup(directory.cleanup)
        self.store_dir = Path(directory.name) / 'user_data' / 'prompt_selector'
        self.store_dir.mkdir(parents=True)
        self.data_file = self.store_dir / 'data.json'
        self.projection_file = self.store_dir / 'semantic_projection.json'
        self.cache_file = self.store_dir / 'cache' / CACHE_FILENAME

        module = self.module
        module.derived_cache.flush()
        module.DATA_FILE = str(self.data_file)
        module.DEFAULT_DATA_FILE = str(self.store_dir / 'default.json')
        module.PROMPT_STORE_DIR = str(self.store_dir)
        module.PREVIEW_DIR = str(self.store_dir / 'preview')
        module.THUMBNAIL_DIR = str(self.store_dir / 'preview_thumbnails')
        module._PROMPT_DATA_CACHE = None
        module._PROMPT_DATA_CACHE_SIGNATURE = None
        module._SEMANTIC_CACHE.update({'projection': (), 'warned': False})
        module._library_state_reset()

    def tearDown(self):
        self.module.derived_cache.flush()

    def _write(self, prompts, projection=None):
        self.data_file.write_text(json.dumps(_library(prompts), ensure_ascii=False), encoding='utf-8')
        self.projection_file.write_text(
            json.dumps(projection if projection is not None else _projection(), ensure_ascii=False),
            encoding='utf-8')

    def _write_data(self, prompts):
        """Rewrite the library only; the projection file keeps its identity."""
        self.data_file.write_text(json.dumps(_library(prompts), ensure_ascii=False), encoding='utf-8')

    def _rebuild(self):
        with self.module._PROMPT_FILE_LOCK, self.module._PROMPT_CACHE_LOCK:
            self.module._library_rebuild_locked()
        return self.module._LIBRARY_STATE['entries']

    @staticmethod
    def _semantics(entries):
        return {identity: entry['_semantic'] for identity, entry in entries.items()}

    def _stored_payload(self):
        with open(self.cache_file, 'rb') as stream:
            return msgpack.unpackb(zstandard.ZstdDecompressor().decompress(stream.read()), raw=False)

    def _count_entries(self):
        real = self.module._library_entry
        calls = []

        def wrapper(*args, **kwargs):
            calls.append(args)
            return real(*args, **kwargs)

        return calls, mock.patch.object(self.module, '_library_entry', side_effect=wrapper)

    def test_cache_roundtrip_and_atomic_replace(self):
        prompts = _prompts(3)
        self._write(prompts)
        entries = self._rebuild()
        semantics = self._semantics(entries)

        with mock.patch.object(self.module.derived_cache.os, 'replace', wraps=os.replace) as replace:
            self.assertTrue(self.module.derived_cache.flush())
        replace.assert_called_once()
        temporary, target = replace.call_args.args
        self.assertEqual(target, str(self.cache_file))
        self.assertEqual(temporary, str(self.cache_file) + '.tmp')
        self.assertEqual([path.name for path in self.cache_file.parent.iterdir()], [CACHE_FILENAME])

        payload = self._stored_payload()
        self.assertEqual(payload['format'], 1)
        self.assertEqual(payload['refinement_version'], self.module.REFINEMENT_VERSION)
        signature = self.module._projection_signature()
        self.assertEqual(payload['projection'], [signature[2], signature[0]])
        self.assertEqual(sorted(payload['entries']), sorted(semantics))

        data = json.loads(self.data_file.read_text(encoding='utf-8'))
        category = data['categories'][0]
        for prompt in category['prompts']:
            binding, semantic = payload['entries'][prompt['id']]
            self.assertEqual(binding, self.module.semantic_binding(category, prompt))
            self.assertEqual(semantic, semantics[prompt['id']])

    def test_binding_hits_reuse_cached_semantics(self):
        prompts = _prompts(4)
        self._write(prompts)
        first = self._semantics(self._rebuild())
        self.assertTrue(self.module.derived_cache.flush())

        self.module._library_state_reset()
        calls, patched = self._count_entries()
        with patched:
            second = self._semantics(self._rebuild())
        self.assertEqual(calls, [])
        self.assertEqual(second, first)
        # A full hit changes nothing on disk, so no write is scheduled.
        self.assertFalse(self.module.derived_cache.flush())

    def test_binding_change_recomputes_only_that_row(self):
        self._write(_prompts(3))
        self._rebuild()
        self.assertTrue(self.module.derived_cache.flush())

        original = _prompts(3)
        changed = [_prompt('p1', original[0]['prompt']),
                   _prompt('p2', 'a much longer replacement prompt'),
                   _prompt('p3', original[2]['prompt'])]
        self._write_data(changed)
        self.module._library_state_reset()
        calls, patched = self._count_entries()
        with patched:
            self._rebuild()
        self.assertEqual(len(calls), 1)

        self.assertTrue(self.module.derived_cache.flush())
        payload = self._stored_payload()
        self.assertEqual(payload['entries']['p2'][1],
                         self.module._LIBRARY_STATE['entries']['p2']['_semantic'])

    def test_incremental_edit_updates_mapping_and_schedules_store(self):
        prompts = _prompts(3)
        self._write(prompts)
        before = self._semantics(self._rebuild())
        self.assertTrue(self.module.derived_cache.flush())

        self._write_data([_prompt('p1', prompts[0]['prompt']),
                          _prompt('p2', 'a much longer replacement prompt'),
                          _prompt('p3', prompts[2]['prompt'])])
        data = json.loads(self.data_file.read_text(encoding='utf-8'))
        category = data['categories'][0]
        calls, patched = self._count_entries()
        with patched:
            with self.module._PROMPT_FILE_LOCK, self.module._PROMPT_CACHE_LOCK:
                self.module._cache_prompt_data(data, ['p2'])
        self.assertEqual(len(calls), 1)
        binding, semantic = self.module._SEMANTIC_ENTRIES['p2']
        self.assertEqual(binding, self.module.semantic_binding(category, category['prompts'][1]))
        self.assertEqual(semantic, self.module._LIBRARY_STATE['entries']['p2']['_semantic'])
        self.assertEqual(self.module._LIBRARY_STATE['entries']['p1']['_semantic'], before['p1'])
        self.assertTrue(self.module.derived_cache.flush())
        self.assertEqual(self._stored_payload()['entries']['p2'][1], semantic)

    def test_projection_signature_change_ignores_cache(self):
        prompts = _prompts(3)
        self._write(prompts)
        self._rebuild()
        self.assertTrue(self.module.derived_cache.flush())

        self.projection_file.write_text(json.dumps(_projection(class_labels={'note': 'changed'}), indent=1),
                                        encoding='utf-8')
        self.module._library_state_reset()
        calls, patched = self._count_entries()
        with patched:
            self._rebuild()
        self.assertEqual(len(calls), len(prompts))

    def test_corrupt_cache_falls_back_and_rewrites(self):
        prompts = _prompts(3)
        self._write(prompts)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_bytes(b'not a zstd frame')
        calls, patched = self._count_entries()
        with patched:
            self._rebuild()
        self.assertEqual(len(calls), len(prompts))
        self.assertTrue(self.module.derived_cache.flush())
        self.assertEqual(sorted(self._stored_payload()['entries']), ['p1', 'p2', 'p3'])

    def test_cached_result_matches_full_recompute(self):
        self._write(_prompts(5))
        self._rebuild()
        self.assertTrue(self.module.derived_cache.flush())

        with mock.patch.dict(os.environ, {'UW_DISABLE_SEMANTIC_CACHE': '1'}):
            self.module._library_state_reset()
            uncached = self._semantics(self._rebuild())

        self.module._library_state_reset()
        calls, patched = self._count_entries()
        with patched:
            cached = self._semantics(self._rebuild())
        self.assertEqual(calls, [])
        self.assertEqual(cached, uncached)
        self.assertEqual(cached, self._semantics(self.module._LIBRARY_STATE['entries']))

    def test_disable_env_skips_cache_io(self):
        self._write(_prompts(3))
        self._rebuild()
        self.assertTrue(self.module.derived_cache.flush())
        before = self.cache_file.read_bytes()

        with mock.patch.dict(os.environ, {'UW_DISABLE_SEMANTIC_CACHE': '1'}):
            self.module._library_state_reset()
            with mock.patch.object(self.module.derived_cache, 'load',
                                   side_effect=AssertionError('load must not run')), \
                    mock.patch.object(self.module.derived_cache, 'store',
                                      side_effect=AssertionError('store must not run')):
                self._rebuild()
        self.assertEqual(self.cache_file.read_bytes(), before)


class LazyInitializationTests(unittest.TestCase):
    def _store(self):
        directory = tempfile.TemporaryDirectory(prefix='wb-lazy-import-')
        self.addCleanup(directory.cleanup)
        store_dir = Path(directory.name) / 'user_data' / 'prompt_selector'
        store_dir.mkdir(parents=True)
        return Path(directory.name), store_dir

    def test_import_does_not_parse_or_upgrade_data(self):
        root, store_dir = self._store()
        data_file = store_dir / 'data.json'
        legacy = {'version': '1.6', 'categories': [
            {'id': 'c1', 'name': 'fixture', 'prompts': [{'id': 'p1', 'prompt': 'a cat'}]}],
            'settings': {'language': 'zh-CN', 'separator': ', '}}
        data_file.write_text(json.dumps(legacy), encoding='utf-8')
        before = data_file.read_bytes()

        module = _load_prompt_selector('lazy_upgrade', root)
        self.assertIsNone(module._PROMPT_DATA_CACHE)
        self.assertFalse(module._DATA_UPGRADE_CHECKED)
        self.assertEqual(data_file.read_bytes(), before)

        with mock.patch.object(module, '_atomic_save_json', wraps=module._atomic_save_json) as save:
            upgraded = module._read_prompt_data_cached()
        self.assertTrue(module._DATA_UPGRADE_CHECKED)
        self.assertEqual(save.call_count, 1)
        self.assertIn('last_modified', upgraded)
        saved = json.loads(data_file.read_text(encoding='utf-8'))
        self.assertIn('last_modified', saved)
        self.assertIn('updated_at', saved['categories'][0])
        self.assertIn('updated_at', saved['categories'][0]['prompts'][0])
        self.assertIn('last_modified', module._PROMPT_DATA_CACHE)

        with mock.patch.object(module, '_atomic_save_json', wraps=module._atomic_save_json) as again:
            self.assertIs(module._read_prompt_data_cached(), module._PROMPT_DATA_CACHE)
        self.assertEqual(again.call_count, 0)

    def test_import_leaves_unreadable_data_unparsed(self):
        root, store_dir = self._store()
        data_file = store_dir / 'data.json'
        data_file.write_bytes(b'{not valid json')
        module = _load_prompt_selector('lazy_invalid', root)
        self.assertIsNone(module._PROMPT_DATA_CACHE)
        self.assertEqual(data_file.read_bytes(), b'{not valid json')
        with self.assertRaises(json.JSONDecodeError):
            module._read_prompt_data_cached()


class DeferredWarmupTests(unittest.TestCase):
    def _root(self):
        directory = tempfile.TemporaryDirectory(prefix='wb-warm-register-')
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_import_registers_task_instead_of_warming(self):
        calls = []

        def register(callback, delay=0.0):
            calls.append((callback, delay))
            return True

        module = _load_prompt_selector('warm_register', self._root(), hooks=register)
        self.assertEqual(len(calls), 1)
        callback, delay = calls[0]
        self.assertIs(callback, module._start_heavy_startup_tasks)
        self.assertEqual(delay, 1.0)
        self.assertFalse(hasattr(module, '_schedule_library_warmup'))
        self.assertIsNone(module._LIBRARY_STATE['data'])
        self.assertFalse(any(thread.name == 'uw-library-warmup' and thread.is_alive()
                             for thread in threading.enumerate()))

        warmed = []
        with mock.patch.object(module, '_warm_library_caches', side_effect=lambda **kwargs: warmed.append(kwargs)):
            callback()
        self.assertEqual(warmed, [{'include_packed': False}])

    def test_skip_env_registers_nothing(self):
        calls = []
        module = _load_prompt_selector('warm_skip', self._root(),
                                       hooks=lambda callback, delay=0.0: calls.append(callback),
                                       skip_warmup=True)
        self.assertEqual(calls, [])
        self.assertIsNone(module._LIBRARY_STATE['data'])


if __name__ == '__main__':
    unittest.main()
