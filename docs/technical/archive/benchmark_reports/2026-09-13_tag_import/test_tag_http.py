from contextlib import closing
import argparse
import copy
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


def _consume_package_argument():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--package', required=True)
    options, remaining = parser.parse_known_args(sys.argv[1:])
    sys.argv[:] = [sys.argv[0], *remaining]
    package = Path(options.package).resolve()
    if not package.is_dir():
        raise RuntimeError('--package must name the directory containing tag_api.py')
    for filename in ('tag_api.py', 'tag_library.py', 'tag_import_plan.py'):
        if not (package / filename).is_file():
            raise RuntimeError(f'--package is missing {filename}')
    return package


PACKAGE_DIR = _consume_package_argument()
ROOT_NAME = '_staged_tag_http_fixture'
TARGET_NAME = ROOT_NAME + '.feature'


def _package_module(name, path=None):
    module = types.ModuleType(name)
    module.__package__ = name
    module.__path__ = [] if path is None else [str(path)]
    sys.modules[name] = module
    return module


def _plain_module(name):
    module = types.ModuleType(name)
    module.__package__ = name.rpartition('.')[0]
    sys.modules[name] = module
    return module


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PACKAGE_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'could not load staged module {filename}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_package_module(ROOT_NAME)
_package_module(TARGET_NAME, PACKAGE_DIR)
_package_module(ROOT_NAME + '.app')
_package_module(ROOT_NAME + '.app.server')

dao_module = _plain_module(ROOT_NAME + '.app.server.dao')
dao_module.dao = types.SimpleNamespace(tags_db_path=None)

server_module = _plain_module('server')


class _PromptServer:
    instance = types.SimpleNamespace(routes=web.RouteTableDef())


server_module.PromptServer = _PromptServer

CATALOG_DATA = {
    'collections': [
        {'id': 'default', 'name': 'Default'},
        {'id': 'c1', 'name': 'Collection One'},
    ],
    'collection_revision': 'collections-v1:0',
}

prompt_selector_module = _plain_module(TARGET_NAME + '.prompt_selector')
prompt_selector_module._PROMPT_FILE_LOCK = threading.RLock()
prompt_selector_module._read_prompt_data_cached = lambda: CATALOG_DATA
prompt_selector_module._revision = lambda data: data['collection_revision']

selector_module = _plain_module(TARGET_NAME + '.selector_library')
selector_module.collection_groups = lambda data: copy.deepcopy(data['collections'])

tag_library_module = _load(TARGET_NAME + '.tag_library', 'tag_library.py')
tag_import_plan_module = _load(TARGET_NAME + '.tag_import_plan', 'tag_import_plan.py')
tag_api_module = _load(TARGET_NAME + '.tag_api', 'tag_api.py')

TagLibrary = tag_library_module.TagLibrary


SCHEMA = '''
CREATE TABLE tag_groups (
    id_index INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    color TEXT NOT NULL,
    create_time INTEGER NOT NULL,
    p_uuid TEXT NOT NULL UNIQUE
);
CREATE TABLE tag_subgroups (
    id_index INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    color TEXT NOT NULL,
    create_time INTEGER NOT NULL,
    g_uuid TEXT NOT NULL UNIQUE,
    p_uuid TEXT NOT NULL
);
CREATE TABLE tag_tags (
    id_index INTEGER PRIMARY KEY AUTOINCREMENT,
    subgroup_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    desc TEXT NOT NULL,
    color TEXT NOT NULL,
    create_time INTEGER NOT NULL,
    t_uuid TEXT NOT NULL UNIQUE,
    g_uuid TEXT NOT NULL
);
'''


class TagHttpIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / 'tags.sqlite3'
        self._create_database()
        dao_module.dao.tags_db_path = self.db_path
        CATALOG_DATA['collections'] = [
            {'id': 'default', 'name': 'Default'},
            {'id': 'c1', 'name': 'Collection One'},
        ]
        CATALOG_DATA['collection_revision'] = 'collections-v1:0'

        app = web.Application()
        app.add_routes(server_module.PromptServer.instance.routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

        response = await self.client.get('/prompt_selector/tags/revision')
        self.assertEqual(response.status, 200)
        self.initial_revision = (await response.json())['revision']
        self.assertEqual(self.initial_revision, 'tags-v1:0')

    async def asyncTearDown(self):
        await self.client.close()
        self.temporary.cleanup()

    def _create_database(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executescript(SCHEMA)
            conn.execute(
                'INSERT INTO tag_groups '
                '(id_index,name,color,create_time,p_uuid) VALUES (1,?,?,?,?)',
                ('Group One', '#111111', 1000, 'group-1'),
            )
            conn.execute(
                'INSERT INTO tag_subgroups '
                '(id_index,group_id,name,color,create_time,g_uuid,p_uuid) '
                'VALUES (1,1,?,?,?,?,?)',
                ('Subgroup One', '#222222', 1001, 'subgroup-1', 'group-1'),
            )
            conn.execute(
                'INSERT INTO tag_tags '
                '(id_index,subgroup_id,text,desc,color,create_time,t_uuid,g_uuid) '
                'VALUES (1,1,?,?,?,?,?,?)',
                ('old text', 'old description', '#333333', 1002, 'old-1', 'subgroup-1'),
            )

    async def _json(self, method, path, *, payload=None, headers=None):
        response = await self.client.request(method, path, json=payload, headers=headers)
        body = await response.json()
        return response, body

    async def _export_old_bundle(self):
        response, body = await self._json(
            'GET', '/prompt_selector/tags/export?ids=tag:old-1'
        )
        self.assertEqual(response.status, 200, body)
        self.assertEqual(body['format'], 'weilin-tags-v1')
        self.assertEqual([item['t_uuid'] for item in body['items']], ['old-1'])
        return body

    def _database_snapshot(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            tables = (
                'tag_groups',
                'tag_subgroups',
                'tag_tags',
                'workbench_tag_meta',
                'workbench_tag_revision',
            )
            rows = {}
            for table in tables:
                rows[table] = [
                    tuple(row)
                    for row in conn.execute(f'SELECT * FROM {table} ORDER BY rowid')
                ]
        return {'bytes': self.db_path.read_bytes(), 'rows': rows}

    def _logical_snapshot(self):
        snapshot = self._database_snapshot()
        return snapshot['rows']

    async def _preview(self, bundle, overwrite=True, collection_revision=None):
        payload = {
            'bundle': bundle,
            'overwrite': overwrite,
            'collection_revision': collection_revision
            if collection_revision is not None
            else CATALOG_DATA['collection_revision'],
        }
        return await self._json(
            'POST', '/prompt_selector/tags/pre_import', payload=payload
        )

    @staticmethod
    def _confirmed_payload(bundle, plan, overwrite=True):
        return {
            'operation': 'import',
            'bundle': bundle,
            'overwrite': overwrite,
            'collection_revision': plan['collection_revision'],
            'preflight_token': plan['preflight_token'],
            'confirmed': True,
        }

    def _assert_operation_shape(self, operation, status):
        expected_fields = {
            'contract',
            'operation_id',
            'status',
            'atomic',
            'committed',
            'uncommitted',
            'skipped',
            'before_revision',
            'after_revision',
            'collection_revision',
            'canonical_bundle_hash',
            'preflight_token',
            'counts',
            'items',
            'category_counts',
            'failure',
            'persistence',
            'recovery',
        }
        self.assertEqual(set(operation), expected_fields)
        self.assertEqual(operation['contract'], 'weilin-tag-import-operation-v1')
        self.assertEqual(operation['status'], status)
        self.assertTrue(operation['atomic'])
        self.assertEqual(operation['persistence'], 'response_export')
        self.assertIsInstance(operation['operation_id'], str)
        self.assertTrue(operation['operation_id'])

    async def test_preflight_is_read_only_and_reports_metadata_only_update(self):
        bundle = await self._export_old_bundle()
        bundle['items'][0].update(
            favorite=True,
            notes='metadata-only update',
            collection_ids=['default'],
        )
        before = self._database_snapshot()

        response, plan = await self._preview(bundle, overwrite=True)
        self.assertEqual(response.status, 200, plan)
        self.assertEqual(plan['contract'], 'tag-import-preflight-v1')
        self.assertEqual(plan['base_revision'], self.initial_revision)
        self.assertEqual(plan['collection_revision'], 'collections-v1:0')
        self.assertTrue(plan['preflight_token'])
        self.assertTrue(plan['canonical_bundle_hash'])
        self.assertEqual(
            plan['counts'],
            {
                'new': 0,
                'updated': 1,
                'suspected_duplicate': 0,
                'unsupported': 0,
                'version_conflicts': 0,
                'total_records': 1,
                'will_write': 1,
                'will_skip': 0,
            },
        )
        self.assertEqual(
            plan['items'],
            [
                {
                    'stable_id': 'old-1',
                    'source_index': 0,
                    'source_coordinate': 'items[0]',
                    'disposition': 'updated',
                    'changed_fields': ['favorite', 'notes', 'collection_ids'],
                    'ignored_field_names': [],
                }
            ],
        )
        for category in ('groups', 'subgroups'):
            counts = plan['category_counts'][category]
            self.assertEqual(counts['new'], 0)
            self.assertEqual(counts['updated'], 0)
            self.assertEqual(counts['suspected_duplicate'], 1)
            self.assertEqual(counts['will_write'], 0)
            self.assertEqual(counts['will_skip'], 1)
            self.assertEqual(len(counts['actions']), 1)
            self.assertEqual(counts['actions'][0]['disposition'], 'suspected_duplicate')

        after = self._database_snapshot()
        self.assertEqual(after['rows'], before['rows'])
        self.assertEqual(after['bytes'], before['bytes'])

    async def test_confirmed_matching_import_commits_once_with_exact_ids_and_counts(self):
        bundle = await self._export_old_bundle()
        bundle['items'][0].update(
            favorite=True,
            notes='metadata-only update',
            collection_ids=['default'],
        )
        response, plan = await self._preview(bundle)
        self.assertEqual(response.status, 200, plan)
        before = self._logical_snapshot()

        payload = self._confirmed_payload(bundle, plan)
        response, body = await self._json(
            'POST',
            '/prompt_selector/tags/update',
            payload=payload,
            headers={'If-Match': plan['base_revision']},
        )
        self.assertEqual(response.status, 200, body)
        self.assertTrue(body['success'])
        self.assertEqual(
            body['result'], {'created': 0, 'updated': 1, 'unchanged': 0}
        )
        self.assertEqual(response.headers['ETag'], '"' + body['revision'] + '"')

        operation = body['operation']
        self._assert_operation_shape(operation, 'committed')
        self.assertEqual(operation['committed'], 1)
        self.assertEqual(operation['uncommitted'], 0)
        self.assertEqual(operation['skipped'], 0)
        self.assertEqual(operation['before_revision'], plan['base_revision'])
        self.assertEqual(operation['after_revision'], body['revision'])
        self.assertEqual(operation['collection_revision'], plan['collection_revision'])
        self.assertEqual(operation['canonical_bundle_hash'], plan['canonical_bundle_hash'])
        self.assertEqual(operation['preflight_token'], plan['preflight_token'])
        self.assertEqual(operation['counts'], plan['counts'])
        self.assertEqual(operation['items'], plan['items'])
        self.assertEqual(operation['category_counts'], plan['category_counts'])
        self.assertIsNone(operation['failure'])
        self.assertEqual(operation['recovery'], {'mode': 'none', 'partial_batches': False})
        self.assertEqual(operation['items'][0]['stable_id'], 'old-1')
        self.assertEqual(operation['items'][0]['source_index'], 0)
        self.assertEqual(operation['items'][0]['source_coordinate'], 'items[0]')

        after = self._logical_snapshot()
        self.assertEqual(before['tag_groups'], after['tag_groups'])
        self.assertEqual(before['tag_subgroups'], after['tag_subgroups'])
        self.assertEqual(before['tag_tags'], after['tag_tags'])
        self.assertEqual(len(before['workbench_tag_meta']), 0)
        self.assertEqual(len(after['workbench_tag_meta']), 1)
        self.assertEqual(after['workbench_tag_meta'][0][0], 'old-1')
        metadata = json.loads(after['workbench_tag_meta'][0][1])
        self.assertEqual(
            metadata,
            {
                'favorite': True,
                'notes': 'metadata-only update',
                'collection_ids': ['default'],
            },
        )
        self.assertEqual(after['workbench_tag_revision'], [(1, 1)])

        item_response, item_body = await self._json(
            'GET', '/prompt_selector/tags/item?id=tag:old-1'
        )
        self.assertEqual(item_response.status, 200, item_body)
        self.assertEqual(item_body['item']['t_uuid'], 'old-1')
        self.assertEqual(item_body['item']['resource_id'], 'tag:old-1')
        self.assertTrue(item_body['item']['favorite'])
        self.assertEqual(item_body['item']['notes'], 'metadata-only update')
        self.assertEqual(item_body['item']['collection_ids'], ['default'])

    async def test_changed_confirmation_inputs_and_tampered_header_are_rejected_before_writes(self):
        bundle = await self._export_old_bundle()
        bundle['items'][0].update(
            favorite=True, notes='planned', collection_ids=['default']
        )
        response, plan = await self._preview(bundle)
        self.assertEqual(response.status, 200, plan)
        base_payload = self._confirmed_payload(bundle, plan)

        variants = []

        altered_bundle = copy.deepcopy(base_payload)
        altered_bundle['bundle']['items'][0]['notes'] = 'altered after preview'
        variants.append(('altered bundle', altered_bundle, plan['base_revision']))

        altered_overwrite = copy.deepcopy(base_payload)
        altered_overwrite['overwrite'] = False
        variants.append(('altered overwrite', altered_overwrite, plan['base_revision']))

        altered_token = copy.deepcopy(base_payload)
        altered_token['preflight_token'] = 'not-the-issued-token'
        variants.append(('altered token', altered_token, plan['base_revision']))

        unconfirmed = copy.deepcopy(base_payload)
        unconfirmed['confirmed'] = False
        variants.append(('unconfirmed', unconfirmed, plan['base_revision']))

        tampered_header = copy.deepcopy(base_payload)
        variants.append(('tampered If-Match', tampered_header, 'tags-v1:999999'))

        for label, payload, header in variants:
            with self.subTest(label=label):
                before = self._logical_snapshot()
                response, body = await self._json(
                    'POST',
                    '/prompt_selector/tags/update',
                    payload=payload,
                    headers={'If-Match': header},
                )
                self.assertEqual(response.status, 409, body)
                self.assertTrue(body['conflict'])
                self.assertEqual(body['committed'], 0)
                operation = body['operation']
                self._assert_operation_shape(operation, 'not_committed')
                self.assertEqual(operation['committed'], 0)
                # The failure record describes the server-recomputed request.
                # With overwrite disabled, metadata-only input preserves the
                # current metadata and therefore has zero proposed writes.
                self.assertEqual(operation['uncommitted'], 0 if label == 'altered overwrite' else 1)
                self.assertEqual(
                    operation['recovery'],
                    {'mode': 'repreview_original_bundle', 'partial_batches': False},
                )
                self.assertEqual(self._logical_snapshot(), before)

    async def test_stale_tag_and_collection_revisions_are_rejected_before_import_writes(self):
        bundle = await self._export_old_bundle()
        bundle['items'][0].update(
            favorite=True, notes='stale test', collection_ids=['default']
        )
        response, plan = await self._preview(bundle)
        self.assertEqual(response.status, 200, plan)
        payload = self._confirmed_payload(bundle, plan)

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE tag_tags SET color='#abcdef' WHERE t_uuid='old-1'"
            )
        after_external_tag_change = self._logical_snapshot()

        response, body = await self._json(
            'POST',
            '/prompt_selector/tags/update',
            payload=payload,
            headers={'If-Match': plan['base_revision']},
        )
        self.assertEqual(response.status, 409, body)
        self.assertTrue(body['conflict'])
        self.assertEqual(body['committed'], 0)
        self._assert_operation_shape(body['operation'], 'not_committed')
        self.assertEqual(self._logical_snapshot(), after_external_tag_change)

        fresh_bundle = await self._export_old_bundle()
        fresh_bundle['items'][0].update(
            favorite=True, notes='collection stale', collection_ids=['default']
        )
        response, fresh_plan = await self._preview(fresh_bundle)
        self.assertEqual(response.status, 200, fresh_plan)
        fresh_payload = self._confirmed_payload(fresh_bundle, fresh_plan)
        CATALOG_DATA['collection_revision'] = 'collections-v1:1'
        before_collection_rejection = self._logical_snapshot()

        response, body = await self._json(
            'POST',
            '/prompt_selector/tags/update',
            payload=fresh_payload,
            headers={'If-Match': fresh_plan['base_revision']},
        )
        self.assertEqual(response.status, 409, body)
        self.assertTrue(body['conflict'])
        self.assertEqual(body['committed'], 0)
        self._assert_operation_shape(body['operation'], 'not_committed')
        self.assertEqual(self._logical_snapshot(), before_collection_rejection)

    async def test_fault_after_first_real_apply_rolls_back_every_table_and_revision(self):
        bundle = {
            'format': 'weilin-tags-v1',
            'groups': [],
            'subgroups': [],
            'items': [
                {
                    't_uuid': 'new-fault-tag',
                    'resource_id': 'tag:new-fault-tag',
                    'kind': 'tag',
                    'text': 'new text',
                    'desc': 'new description',
                    'color': '#999999',
                    'create_time': 2000,
                    'g_uuid': 'subgroup-1',
                    'favorite': True,
                    'notes': 'must roll back',
                    'collection_ids': ['c1'],
                }
            ],
        }
        response, plan = await self._preview(bundle)
        self.assertEqual(response.status, 200, plan)
        self.assertEqual(plan['counts']['new'], 1)
        self.assertEqual(plan['counts']['will_write'], 1)
        payload = self._confirmed_payload(bundle, plan)
        before = self._logical_snapshot()

        original_apply = TagLibrary.apply
        calls = {'real': 0}

        def fail_after_first_real_apply(instance, conn, item):
            result = original_apply(instance, conn, item)
            if hasattr(instance, 'path'):
                calls['real'] += 1
                if calls['real'] == 1:
                    raise RuntimeError('injected failure after first apply')
            return result

        TagLibrary.apply = fail_after_first_real_apply
        try:
            response, body = await self._json(
                'POST',
                '/prompt_selector/tags/update',
                payload=payload,
                headers={'If-Match': plan['base_revision']},
            )
        finally:
            TagLibrary.apply = original_apply

        self.assertEqual(calls['real'], 1)
        self.assertEqual(response.status, 500, body)
        self.assertIn('injected failure after first apply', body['error'])
        self.assertEqual(body['committed'], 0)
        operation = body['operation']
        self._assert_operation_shape(operation, 'not_committed')
        self.assertEqual(operation['committed'], 0)
        self.assertEqual(operation['uncommitted'], 1)
        self.assertEqual(operation['skipped'], 0)
        self.assertEqual(operation['before_revision'], plan['base_revision'])
        self.assertIsNone(operation['after_revision'])
        self.assertEqual(operation['counts'], plan['counts'])
        self.assertEqual(operation['items'][0]['stable_id'], 'new-fault-tag')
        self.assertIn('injected failure after first apply', operation['failure'])
        self.assertEqual(
            operation['recovery'],
            {'mode': 'repreview_original_bundle', 'partial_batches': False},
        )

        after = self._logical_snapshot()
        self.assertEqual(after, before)
        self.assertEqual(after['tag_groups'], before['tag_groups'])
        self.assertEqual(after['tag_subgroups'], before['tag_subgroups'])
        self.assertEqual(after['tag_tags'], before['tag_tags'])
        self.assertEqual(after['workbench_tag_meta'], before['workbench_tag_meta'])
        self.assertEqual(
            after['workbench_tag_revision'], before['workbench_tag_revision']
        )
        self.assertFalse(
            any(row[6] == 'new-fault-tag' for row in after['tag_tags'])
        )

    async def test_legacy_import_without_token_remains_revision_protected(self):
        bundle = await self._export_old_bundle()
        bundle['items'][0].update(
            favorite=True, notes='legacy import', collection_ids=['default']
        )
        stale_revision = self.initial_revision
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE tag_tags SET color='#444444' WHERE t_uuid='old-1'"
            )
        before = self._logical_snapshot()

        legacy_payload = {
            'operation': 'import',
            'bundle': bundle,
            'overwrite': True,
            'collection_revision': CATALOG_DATA['collection_revision'],
        }
        response, body = await self._json(
            'POST',
            '/prompt_selector/tags/update',
            payload=legacy_payload,
            headers={'If-Match': stale_revision},
        )
        self.assertEqual(response.status, 409, body)
        self.assertTrue(body['conflict'])
        self.assertNotIn('operation', body)
        self.assertEqual(self._logical_snapshot(), before)

    async def test_policy_conflict_preview_cannot_be_force_confirmed(self):
        bundle = await self._export_old_bundle()
        bundle['items'][0]['text'] = 'policy conflict replacement'
        before = self._logical_snapshot()
        response, plan = await self._preview(bundle, overwrite=False)
        self.assertEqual(response.status, 200, plan)
        self.assertFalse(plan['committable'])
        self.assertGreaterEqual(plan['counts']['version_conflicts'], 1)
        self.assertEqual(self._logical_snapshot(), before)
        response, body = await self._json(
            'POST', '/prompt_selector/tags/update',
            payload=self._confirmed_payload(bundle, plan, overwrite=False),
            headers={'If-Match': plan['base_revision']},
        )
        self.assertEqual(response.status, 409, body)
        self.assertEqual(body['operation']['committed'], 0)
        self.assertEqual(self._logical_snapshot(), before)

    async def test_invalid_json_and_unknown_collection_are_http_errors_without_writes(self):
        before = self._logical_snapshot()
        response = await self.client.post(
            '/prompt_selector/tags/pre_import',
            data='{invalid',
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status, 400)
        body = await response.json()
        self.assertEqual(body['committed'], 0)
        self.assertIn('JSON', body['error'])
        self.assertEqual(self._logical_snapshot(), before)

        response = await self.client.post(
            '/prompt_selector/tags/update',
            data='{invalid',
            headers={
                'Content-Type': 'application/json',
                'If-Match': self.initial_revision,
            },
        )
        self.assertEqual(response.status, 400)
        body = await response.json()
        self.assertIn('JSON', body['error'])
        self.assertEqual(self._logical_snapshot(), before)

        bundle = await self._export_old_bundle()
        bundle['items'][0]['collection_ids'] = ['missing-collection']
        response, body = await self._preview(bundle)
        self.assertEqual(response.status, 400, body)
        self.assertIn('收藏组', body['error'])
        self.assertEqual(self._logical_snapshot(), before)

        response, body = await self._json(
            'GET', '/prompt_selector/tags/page?collection=missing-collection'
        )
        self.assertEqual(response.status, 400, body)
        self.assertIn('收藏组', body['error'])
        self.assertEqual(self._logical_snapshot(), before)


if __name__ == '__main__':
    unittest.main()

