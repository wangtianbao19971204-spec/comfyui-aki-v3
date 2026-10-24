"""Interaction-path tests for editing and saving one prompt.

Covers the copy-on-write single-record writers, the throttled backup, the skipped
full compatibility pass, the skipped parse of the whole library, and the skipped
full-library warm-up after an incremental patch.

``prompt_selector.py`` is loaded from the real source file with a temporary
``__file__`` so every store path points inside the test directory: importing the
module never touches the production user_data directory and never starts
ComfyUI. ``server`` is stubbed to the minimum the route decorators need.
"""

import asyncio
import datetime
import importlib.util
import itertools
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

PROMPT_SELECTOR_DIR = Path(__file__).resolve().parents[1]
PROMPT_SELECTOR_FILE = PROMPT_SELECTOR_DIR / 'prompt_selector.py'
NOW = '2026-10-24T12:00:00'
_LOAD_SEQUENCE = itertools.count()


class _StubRoutes:
    def __init__(self):
        self.get_routes = {}
        self.post_routes = {}

    def get(self, path):
        def decorator(handler):
            self.get_routes[path] = handler
            return handler
        return decorator

    def post(self, path):
        def decorator(handler):
            self.post_routes[path] = handler
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


def _load_prompt_selector(store_root):
    """Import the real module with every data path redirected under ``store_root``."""
    _install_server_stub()
    package = 'wb_edit_save_test_%d' % next(_LOAD_SEQUENCE)
    package_name = package + '.prompt_selector'
    root = types.ModuleType(package)
    root.__path__ = [str(PROMPT_SELECTOR_DIR)]
    sys.modules[package] = root
    subpackage = types.ModuleType(package_name)
    subpackage.__path__ = [str(PROMPT_SELECTOR_DIR)]
    sys.modules[package_name] = subpackage
    spec = importlib.util.spec_from_file_location(package_name + '.prompt_selector', PROMPT_SELECTOR_FILE)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = package_name
    module.__file__ = str(Path(store_root) / 'plugin' / 'prompt_selector.py')
    sys.modules[package_name + '.prompt_selector'] = module
    with mock.patch.dict(os.environ, {'UW_SKIP_LIBRARY_WARMUP': '1'}):
        module.__dict__['_orjson'] = None
        spec.loader.exec_module(module)
    return module


class _FixedDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 24, 12, 0, 0)


class _Request:
    """The tiny aiohttp request surface the save routes use."""

    def __init__(self, payload, etag=None):
        self.payload = payload
        self.headers = {} if etag is None else {'If-Match': etag}
        self.query = {}

    async def json(self):
        return self.payload


def _prompt(identity, text):
    return {'id': identity, 'prompt': text, 'alias': text, 'description': '', 'tags': [],
            'favorite': False, 'template': False, 'image': '',
            'created_at': '2026-01-01T00:00:00', 'updated_at': '2026-01-01T00:00:00',
            'usage_count': 0, 'last_used': None}


def _category(name='fixture', identity='cat-1', prompts=None):
    return {'id': identity, 'name': name, 'created_at': '2026-01-01T00:00:00',
            'updated_at': '2026-01-01T00:00:00', 'prompts': list(prompts or [])}


class EditSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = tempfile.TemporaryDirectory(prefix='wb-edit-save-store-')
        cls.addClassCleanup(cls.store.cleanup)
        cls.module = _load_prompt_selector(cls.store.name)

    def setUp(self):
        environment = mock.patch.dict(os.environ, {})
        environment.start()
        self.addCleanup(environment.stop)
        os.environ['UW_SKIP_LIBRARY_WARMUP'] = '1'
        os.environ['UW_DISABLE_SEMANTIC_CACHE'] = '1'

        directory = tempfile.TemporaryDirectory(prefix='wb-edit-save-case-')
        self.addCleanup(directory.cleanup)
        self.store_dir = Path(directory.name) / 'user_data' / 'prompt_selector'
        self.store_dir.mkdir(parents=True)
        self.data_file = self.store_dir / 'data.json'
        self.projection_file = self.store_dir / 'semantic_projection.json'

        module = self.module
        module.derived_cache.flush()
        module.DATA_FILE = str(self.data_file)
        module.DEFAULT_DATA_FILE = str(self.store_dir / 'default.json')
        module.PROMPT_STORE_DIR = str(self.store_dir)
        module.PREVIEW_DIR = str(self.store_dir / 'preview')
        module.THUMBNAIL_DIR = str(self.store_dir / 'preview_thumbnails')
        module._PROMPT_DATA_CACHE = None
        module._PROMPT_DATA_CACHE_SIGNATURE = None
        module._DATA_UPGRADE_CHECKED = False
        module._DATA_COMPATIBLE = False
        module._ROUTE_BRANCH_LAST_BACKUP_AT = 0
        module._SEMANTIC_CACHE.update({'projection': (), 'warned': False})
        module._WARM_SCHEDULER.update({'thread': None, 'again': False})
        module._PACKED_LIBRARY_CACHE.update({'revision': None, 'packed': None})
        module._library_state_reset()
        fixed_clock = mock.patch.object(module, 'datetime', _FixedDatetime)
        fixed_clock.start()
        self.addCleanup(fixed_clock.stop)
        self.addCleanup(self._drain_warm_worker)

    # -- fixtures ---------------------------------------------------------

    def _drain_warm_worker(self):
        thread = self.module._WARM_SCHEDULER.get('thread')
        if thread is not None and thread.is_alive():
            thread.join(10.0)

    def _decision(self, category, prompt):
        return {'binding': self.module.semantic_binding(category, prompt),
                'disposition': 'classified', 'primary_class': 'appearance',
                'content_type': 'fragment', 'usage': 'positive', 'declared_usage': 'positive',
                'model_scope': 'unknown', 'manual_search_eligible': True,
                'random_pool_eligible': False, 'strict_model_pool_eligible': False,
                'themes': [], 'subcategories': ['其他'], 'alternative_classes': [],
                'count_markers': [], 'refinements': [], 'note': '',
                'taxonomy_version': '2026-09-20-v1',
                'subcategory_owners': {'其他': 'appearance'},
                'semantic_review_status': 'user_confirmed'}

    def _write_library(self, prompts, name='fixture', identity='cat-1'):
        category = _category(name, identity, prompts)
        return self._write_categories([category])

    def _write_categories(self, categories):
        data = {'version': '1.6', 'last_modified': '2026-01-01T00:00:00',
                'settings': {'language': 'zh-CN', 'separator': ', ', 'save_selection': True},
                'categories': categories}
        decisions = {}
        for category in categories:
            for prompt in category['prompts']:
                decisions[prompt['id']] = self._decision(category, prompt)
        projection = {'schema': 'S4-semantic-projection-v1', 'decisions': decisions,
                      'class_labels': {}}
        self.data_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.projection_file.write_text(json.dumps(projection, ensure_ascii=False), encoding='utf-8')
        return data

    def _read_saved(self):
        return json.loads(self.data_file.read_text(encoding='utf-8'))

    def _revision(self, data):
        return self.module._revision(data)

    def _classification(self):
        return {'primary_class': 'appearance', 'content_type': 'fragment',
                'usage': 'positive', 'subcategories': ['其他']}

    def _edit_payload(self, row, base_revision, **overrides):
        return {'mode': 'edit', 'target_category_id': 'cat-1',
                'prompt': {**row, **overrides}, 'base_revision': base_revision,
                'classification': self._classification()}

    def _prime(self, warm=False):
        """Parse + cache the library (and optionally build the derived read model)."""
        data = self.module._read_prompt_data_cached()
        if warm:
            self._warm_state()
        return data

    def _warm_state(self):
        module = self.module
        module._reviewed_library_data()
        module._library_index_payload()
        module._library_page_payload('', '', 0, 30)
        return module._LIBRARY_STATE

    def _wait_for(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    # -- whole-library parse must not run on single-record writes ---------

    def test_upsert_edit_reuses_the_cached_document(self):
        data = self._write_library([_prompt('p1', 'one'), _prompt('p2', 'two')])
        current = self._prime(warm=True)
        old_prompt = current['categories'][0]['prompts'][0]
        payload = self._edit_payload(old_prompt, data['last_modified'], description='new note')

        with mock.patch.object(self.module, '_json_load_path',
                               side_effect=AssertionError('single-record save parsed data.json')):
            result = self.module._apply_upsert_prompt(payload)

        saved = self._read_saved()
        self.assertEqual(saved['categories'][0]['prompts'][0]['description'], 'new note')
        self.assertEqual(saved['last_modified'], NOW)
        self.assertEqual(result['revision'], NOW)
        # The committed document becomes the new shared cache; the old shared object
        # is untouched because only copies were edited.
        self.assertIs(self.module._PROMPT_DATA_CACHE['categories'][0]['prompts'][0], result['prompt'])
        self.assertEqual(old_prompt['description'], '')
        # The derived view was patched in place, so the next read already sees the edit.
        view_prompt = self.module._LIBRARY_STATE['views'][False]['categories'][0]['prompts'][0]
        self.assertEqual(view_prompt['description'], 'new note')

    def test_upsert_create_and_category_move_use_the_cached_document(self):
        data = self._write_library([_prompt('p1', 'one'), _prompt('p2', 'two')],
                                   name='first')
        data['categories'].append(_category('second', 'cat-2'))
        self.data_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        current = self._prime(warm=True)
        old_prompt = current['categories'][0]['prompts'][0]
        base = self._revision(current)

        with mock.patch.object(self.module, '_json_load_path',
                               side_effect=AssertionError('category move parsed data.json')):
            moved = self.module._apply_upsert_prompt({
                'mode': 'edit', 'target_category_id': 'cat-2',
                'prompt': {**old_prompt, 'description': 'moved'},
                'base_revision': base, 'classification': self._classification()})
            created = self.module._apply_upsert_prompt({
                'mode': 'create', 'target_category_id': 'cat-2', 'draft_id': 'draft-1',
                'prompt': {**_prompt('', 'brand new'), 'alias': 'new'},
                'base_revision': moved['revision']})

        saved = self._read_saved()
        first, second = saved['categories']
        self.assertEqual([prompt['id'] for prompt in first['prompts']], ['p2'])
        self.assertEqual([prompt['id'] for prompt in second['prompts']][0], 'p1')
        self.assertEqual(second['prompts'][0]['description'], 'moved')
        self.assertEqual(created['category']['id'], 'cat-2')
        self.assertIn('brand new', [prompt['prompt'] for prompt in second['prompts']])
        # Failures later in the call must never leak into the shared document.
        self.assertEqual(current['categories'][0]['prompts'][0]['description'], '')

    # -- copy-on-write isolation ------------------------------------------

    def test_revision_conflict_leaves_cache_and_file_untouched(self):
        data = self._write_library([_prompt('p1', 'one')])
        current = self._prime()
        before_bytes = self.data_file.read_bytes()
        payload = self._edit_payload(current['categories'][0]['prompts'][0],
                                     'stale-revision', description='must not save')

        with self.assertRaises(self.module.RevisionConflict):
            self.module._apply_upsert_prompt(payload)

        self.assertIs(self.module._PROMPT_DATA_CACHE, current)
        self.assertEqual(current['categories'][0]['prompts'][0]['description'], '')
        self.assertEqual(self.data_file.read_bytes(), before_bytes)
        self.assertEqual(list(self.store_dir.glob('.tmp_*')), [])
        self.assertEqual(list(self.store_dir.glob('*.backup_*')), [])

    def test_invalid_edit_leaves_cache_and_file_untouched(self):
        data = self._write_library([_prompt('p1', 'one')])
        current = self._prime()
        before_bytes = self.data_file.read_bytes()
        broken = self._edit_payload(current['categories'][0]['prompts'][0], data['last_modified'],
                                    plan_sections={'positive': 'a', 'negative': 'b'})

        with self.assertRaises(ValueError):
            self.module._apply_upsert_prompt(broken)

        self.assertIs(self.module._PROMPT_DATA_CACHE, current)
        self.assertEqual(current['categories'][0]['prompts'][0]['description'], '')
        self.assertEqual(self.data_file.read_bytes(), before_bytes)
        self.assertEqual(list(self.store_dir.glob('.tmp_*')), [])

    def test_save_io_failure_keeps_the_shared_document(self):
        data = self._write_library([_prompt('p1', 'one')])
        current = self._prime()
        before_bytes = self.data_file.read_bytes()
        payload = self._edit_payload(current['categories'][0]['prompts'][0],
                                     data['last_modified'], description='not saved')

        with mock.patch.object(self.module.os, 'replace',
                               side_effect=OSError('disk went away')):
            with self.assertRaises(OSError):
                self.module._apply_upsert_prompt(payload)

        self.assertEqual(self.data_file.read_bytes(), before_bytes)
        self.assertEqual(list(self.store_dir.glob('.tmp_*')), [])
        # The copy made before the failed replace is a complete previous revision,
        # never a partially written file.
        for backup in self.store_dir.glob('*.backup_*'):
            self.assertEqual(backup.read_bytes(), before_bytes)
        self.assertEqual(current['categories'][0]['prompts'][0]['description'], '')

    def test_delete_only_touches_the_copied_category(self):
        data = self._write_library([_prompt('p1', 'one'), _prompt('p2', 'two')])
        current = self._prime(warm=True)
        old_ids = [prompt['id'] for prompt in current['categories'][0]['prompts']]

        with mock.patch.object(self.module, '_json_load_path',
                               side_effect=AssertionError('delete parsed data.json')):
            result = self.module._apply_delete_prompt('p1', data['last_modified'])

        self.assertEqual(result['revision'], NOW)
        self.assertEqual([prompt['id'] for prompt in self._read_saved()['categories'][0]['prompts']],
                         ['p2'])
        self.assertEqual([prompt['id'] for prompt in current['categories'][0]['prompts']], old_ids)

    # -- compatibility pass runs once -------------------------------------

    def test_compatibility_pass_runs_once(self):
        self._write_library([_prompt('p1', 'one')])
        current = self._prime()
        self.assertTrue(self.module._DATA_COMPATIBLE)
        self.module._DATA_COMPATIBLE = False
        calls = []
        real = self.module._ensure_data_compatibility

        def counted(data):
            calls.append(data)
            return real(data)

        with mock.patch.object(self.module, '_ensure_data_compatibility', side_effect=counted):
            self.module._apply_plan_flag({'prompt_id': 'p1', 'is_user_plan': True,
                                          'base_revision': self._revision(current)})
            self.assertEqual(len(calls), 1)
            current = self.module._read_prompt_data_cached()
            self.module._apply_delete_prompt('p1', self._revision(current))
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.module._DATA_COMPATIBLE)

    def test_first_parse_marks_the_document_compatible_once(self):
        self._write_library([_prompt('p1', 'one')])
        module = self.module
        module._PROMPT_DATA_CACHE = None
        module._PROMPT_DATA_CACHE_SIGNATURE = None
        module._DATA_UPGRADE_CHECKED = False
        module._DATA_COMPATIBLE = False
        with mock.patch.object(module, '_atomic_save_json',
                               wraps=module._atomic_save_json) as save:
            parsed = module._read_prompt_data_cached()
        self.assertTrue(module._DATA_COMPATIBLE)
        self.assertTrue(module._DATA_UPGRADE_CHECKED)
        self.assertEqual(save.call_count, 0)
        self.assertIs(module._read_prompt_data_cached(), parsed)

    def test_legacy_data_upgrades_once_and_marks_compatible(self):
        legacy = {'version': '1.6', 'categories': [
            {'id': 'cat-1', 'name': 'fixture', 'prompts': [{'id': 'p1', 'prompt': 'one'}]}],
            'settings': {'language': 'zh-CN', 'separator': ', '}}
        self.data_file.write_text(json.dumps(legacy), encoding='utf-8')
        module = self.module
        module._PROMPT_DATA_CACHE = None
        module._PROMPT_DATA_CACHE_SIGNATURE = None
        module._DATA_UPGRADE_CHECKED = False
        module._DATA_COMPATIBLE = False
        with mock.patch.object(module, '_atomic_save_json',
                               wraps=module._atomic_save_json) as save:
            module._read_prompt_data_cached()
        self.assertTrue(module._DATA_COMPATIBLE)
        self.assertEqual(save.call_count, 1)
        upgraded = json.loads(self.data_file.read_text(encoding='utf-8'))
        self.assertIn('last_modified', upgraded)
        self.assertIn('updated_at', upgraded['categories'][0]['prompts'][0])

    # -- backup throttling -------------------------------------------------

    def test_single_record_saves_throttle_the_backup(self):
        self._write_library([_prompt('p1', 'one')])
        current = self._prime()
        self.module._ROUTE_BRANCH_LAST_BACKUP_AT = 0
        with mock.patch.object(self.module, '_create_backup') as backup:
            self.module._apply_upsert_prompt(
                self._edit_payload(current['categories'][0]['prompts'][0],
                                   self._revision(current), description='first'))
            self.assertEqual(backup.call_count, 1)
            current = self.module._read_prompt_data_cached()
            self.module._apply_upsert_prompt(
                self._edit_payload(current['categories'][0]['prompts'][0],
                                   self._revision(current), description='second'))
            self.assertEqual(backup.call_count, 1)
            # >180 s later the copy is written again.
            self.module._ROUTE_BRANCH_LAST_BACKUP_AT = 0
            current = self.module._read_prompt_data_cached()
            self.module._apply_upsert_prompt(
                self._edit_payload(current['categories'][0]['prompts'][0],
                                   self._revision(current), description='third'))
            self.assertEqual(backup.call_count, 2)

    def test_every_single_record_writer_uses_the_throttle(self):
        self._write_library([_prompt('p1', 'one'), _prompt('p2', 'two')])
        module = self.module
        revision = self._revision(self._prime())
        operations = [
            lambda current: module._apply_plan_flag(
                {'prompt_id': 'p1', 'is_user_plan': True, 'base_revision': self._revision(current)}),
            lambda current: asyncio.run(module.toggle_favorite(_Request({
                'prompt_id': 'p1', 'category_id': 'cat-1',
                'base_revision': self._revision(current)}))),
            lambda current: asyncio.run(module.mark_prompt_used(_Request({
                'prompt_id': 'p1', 'category_id': 'cat-1',
                'base_revision': self._revision(current)}))),
            lambda current: asyncio.run(module.update_prompt_order(_Request({
                'category': 'fixture', 'ordered_ids': ['p2', 'p1'],
                'base_revision': self._revision(current)}))),
            lambda current: module._apply_delete_prompt('p2', self._revision(current)),
        ]
        module._ROUTE_BRANCH_LAST_BACKUP_AT = 0
        with mock.patch.object(module, '_create_backup') as backup:
            for operation in operations:
                module._ROUTE_BRANCH_LAST_BACKUP_AT = 0
                current = module._read_prompt_data_cached()
                before = backup.call_count
                operation(current)
                self.assertEqual(backup.call_count, before + 1)
        self.assertGreaterEqual(backup.call_count, len(operations))

    def test_batch_writes_keep_backing_up_every_time(self):
        self._write_library([_prompt('p1', 'one')])
        module = self.module
        revision = self._revision(self._prime())
        module._ROUTE_BRANCH_LAST_BACKUP_AT = time.time()
        with mock.patch.object(module, '_create_backup') as backup:
            module._rename_category_branch({'old_name': 'fixture', 'new_name': 'renamed',
                                            'base_revision': revision})
            revision = self._revision(module._read_prompt_data_cached())
            module._rename_category_branch({'old_name': 'renamed', 'new_name': 'fixture',
                                            'base_revision': revision})
        self.assertEqual(backup.call_count, 2)

    # -- warm-up behaviour -------------------------------------------------

    def test_patched_edit_skips_the_full_warm_and_first_read_is_correct(self):
        data = self._write_library([_prompt('p1', 'one'), _prompt('p2', 'two')])
        current = self._prime(warm=True)
        os.environ.pop('UW_SKIP_LIBRARY_WARMUP')
        warm_calls = []

        def fake_warm(**kwargs):
            warm_calls.append(kwargs)

        with mock.patch.object(self.module, '_warm_library_caches', side_effect=fake_warm):
            result = self.module._apply_upsert_prompt(
                self._edit_payload(current['categories'][0]['prompts'][0],
                                   data['last_modified'], description='after save'))
            time.sleep(0.2)
            self.assertEqual(warm_calls, [])
            self.assertIsNone(self.module._WARM_SCHEDULER['thread'])
            self.assertIsNotNone(self.module._LIBRARY_STATE['index'])

            # The first reads after the save are served from the patched model; the
            # kept index payload is byte-identical to a fresh recomputation.
            retained = self.module._library_index_payload()
            page = self.module._library_page_payload('', '', 0, 30)
            self.assertEqual(retained['last_modified'], result['revision'])
            self.module._LIBRARY_STATE['index'] = None
            self.assertEqual(retained, self.module._library_index_payload())
            self.assertEqual(page['last_modified'], result['revision'])
            edited = next(item for item in page['items'] if item['id'] == 'p1')
            self.assertEqual(edited['description'], 'after save')

            # A commit that cannot be patched still gets the background warm-up.
            self.module._apply_delete_prompt('p2', self._revision(self.module._read_prompt_data_cached()))
            self.assertTrue(self._wait_for(lambda: len(warm_calls) == 1))

            # An edit that arrives before any derived state exists rebuilds too.
            self.module._library_state_reset()
            revision = self._revision(self.module._read_prompt_data_cached())
            self.module._apply_upsert_prompt(
                self._edit_payload({'id': 'p1', 'prompt': 'one', 'alias': 'one',
                                    'description': '', 'tags': [], 'favorite': False,
                                    'template': False, 'image': '',
                                    'created_at': '2026-01-01T00:00:00',
                                    'updated_at': '2026-01-01T00:00:00',
                                    'usage_count': 0, 'last_used': None},
                                   revision, description='cold state'))
            self.assertTrue(self._wait_for(lambda: len(warm_calls) == 2))

    def test_semantic_change_drops_the_index_and_requests_the_warm(self):
        data = self._write_library([_prompt('p1', 'one')])
        current = self._prime(warm=True)
        os.environ.pop('UW_SKIP_LIBRARY_WARMUP')
        self.assertIsNotNone(self.module._LIBRARY_STATE['index'])

        with mock.patch.object(self.module, '_request_library_warm') as warm:
            self.module._apply_upsert_prompt(
                self._edit_payload(current['categories'][0]['prompts'][0],
                                   data['last_modified'], prompt='1girl'))
            self.assertEqual(warm.call_count, 1)
        self.assertIsNone(self.module._LIBRARY_STATE['index'])
        # The views stayed patched; only the index payload needs a rebuild.
        self.assertIsNotNone(self.module._LIBRARY_STATE['views'].get(False))
        page = self.module._library_page_payload('', '', 0, 30)
        edited = next(item for item in page['items'] if item['id'] == 'p1')
        self.assertEqual(edited['_semantic']['count_markers'], ['1girl'])

    def test_atomic_save_triggers_the_warm_only_by_default(self):
        data = self._write_library([_prompt('p1', 'one')])
        self._prime()
        os.environ.pop('UW_SKIP_LIBRARY_WARMUP')
        with mock.patch.object(self.module, '_request_library_warm') as warm:
            self.module._atomic_save_json(self.module.DATA_FILE, data, create_backup=False)
            self.assertEqual(warm.call_count, 1)
            self.module._atomic_save_json(self.module.DATA_FILE, data, create_backup=False,
                                          schedule_warm=False)
            self.assertEqual(warm.call_count, 1)

    # -- persisted result matches the historical document ----------------

    def test_edit_save_matches_the_reference_document(self):
        module = self.module
        self._write_library([_prompt('p1', 'one'), _prompt('p2', 'two')])
        current = self._prime()
        before = self._read_saved()
        old_prompt = current['categories'][0]['prompts'][0]
        payload = self._edit_payload(old_prompt, before['last_modified'],
                                     description='changed', tags=['alpha', 'beta'],
                                     favorite=True)

        with mock.patch.object(module, 'datetime', _FixedDatetime):
            module._apply_upsert_prompt(payload)

        expected_category = {key: value for key, value in before['categories'][0].items()
                             if key != 'prompts'}
        expected_prompt = dict(old_prompt)
        expected_prompt.update({
            'alias': old_prompt['alias'], 'prompt': old_prompt['prompt'],
            'description': 'changed', 'image': '', 'tags': ['alpha', 'beta'],
            'favorite': True, 'template': False,
            'usage_count': old_prompt['usage_count'], 'last_used': old_prompt['last_used'],
            'created_at': old_prompt['created_at'], 'updated_at': NOW,
        })
        projection = json.loads(self.projection_file.read_text(encoding='utf-8'))
        classification = module.confirm_classification(
            projection, expected_category, expected_prompt, payload['classification'],
            previous_category=expected_category, previous_prompt=old_prompt)
        classification['binding'] = module.semantic_binding(expected_category, expected_prompt)
        expected_prompt['_classification'] = classification
        expected_category['prompts'] = [expected_prompt, before['categories'][0]['prompts'][1]]
        expected_category['updated_at'] = NOW
        expected = {**before, 'categories': [expected_category], 'last_modified': NOW}

        self.assertEqual(self._read_saved(), expected)

    def test_create_save_matches_the_reference_document(self):
        module = self.module
        self._write_library([_prompt('p1', 'one')])
        self._prime()
        before = self._read_saved()
        new_prompt = {'alias': 'new', 'prompt': 'brand new body', 'description': '',
                      'image': '', 'tags': [], 'favorite': False, 'template': False}

        with mock.patch.object(module, 'datetime', _FixedDatetime), \
                mock.patch.object(module.uuid, 'uuid4', return_value='new-id'):
            module._apply_upsert_prompt({
                'mode': 'create', 'target_category_id': 'cat-1', 'draft_id': 'draft-x',
                'prompt': new_prompt, 'base_revision': before['last_modified']})

        expected_category = {key: value for key, value in before['categories'][0].items()
                             if key != 'prompts'}
        expected_prompt = {
            'id': 'new-id', 'alias': 'new', 'prompt': 'brand new body', 'description': '',
            'image': '', 'tags': [], 'favorite': False, 'template': False,
            'usage_count': 0, 'last_used': None, 'created_at': NOW, 'updated_at': NOW,
            '_draft_id': 'draft-x',
        }
        expected_category['prompts'] = [before['categories'][0]['prompts'][0], expected_prompt]
        expected_category['updated_at'] = NOW
        expected = {**before, 'categories': [expected_category], 'last_modified': NOW}

        self.assertEqual(self._read_saved(), expected)

    # -- order route -------------------------------------------------------

    def test_update_order_reorders_copies_without_parsing(self):
        data = self._write_library([_prompt('p1', 'one'), _prompt('p2', 'two')])
        current = self._prime()
        before_ids = [prompt['id'] for prompt in current['categories'][0]['prompts']]
        with mock.patch.object(self.module, '_json_load_path',
                               side_effect=AssertionError('order parsed data.json')):
            response = asyncio.run(self.module.update_prompt_order(_Request({
                'category': 'fixture', 'ordered_ids': ['p2', 'p1'],
                'base_revision': data['last_modified']})))
        self.assertEqual(response.status, 200)
        self.assertEqual([prompt['id'] for prompt in self._read_saved()['categories'][0]['prompts']],
                         ['p2', 'p1'])
        self.assertEqual([prompt['id'] for prompt in current['categories'][0]['prompts']],
                         before_ids)


if __name__ == '__main__':
    unittest.main()
