import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


# Load tag_api with stubs so we can exercise the route coroutine without a
# running ComfyUI server. Only the minimum surface used by the identity
# endpoint is stubbed; the rest of tag_api is left untouched.
def _load_tag_api():
    import sys
    spec = importlib.util.spec_from_file_location('weilin_pkg.prompt_selector.tag_api', Path(__file__).resolve().parents[1] / 'tag_api.py')
    module = importlib.util.module_from_spec(spec)
    module.__package__ = 'weilin_pkg.prompt_selector'
    sys.modules['weilin_pkg.prompt_selector.tag_api'] = module
    spec.loader.exec_module(module)
    return module


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


class _StubPromptServerInstance:
    def __init__(self):
        self.routes = _StubRoutes()


class _StubServer:
    instance = _StubPromptServerInstance()


class TagApiIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys, types
        fake_server = types.ModuleType('server')
        fake_server.PromptServer = _StubServer
        sys.modules['server'] = fake_server

        # Minimal stubs for the relative imports inside tag_api.
        pkg = types.ModuleType('weilin_pkg')
        pkg.__path__ = [str(Path(__file__).resolve().parents[1])]
        sys.modules['weilin_pkg'] = pkg
        pspkg = types.ModuleType('weilin_pkg.prompt_selector')
        pspkg.__path__ = [str(Path(__file__).resolve().parents[1])]
        sys.modules['weilin_pkg.prompt_selector'] = pspkg
        app = types.ModuleType('weilin_pkg.app')
        app.__path__ = []
        sys.modules['weilin_pkg.app'] = app
        daomod = types.ModuleType('weilin_pkg.app.server')
        daomod.__path__ = []
        sys.modules['weilin_pkg.app.server'] = daomod
        daosub = types.ModuleType('weilin_pkg.app.server.dao')
        daosub.dao = types.SimpleNamespace(tags_db_path='/dev/null/never-opened')
        sys.modules['weilin_pkg.app.server.dao'] = daosub

        taglib = types.ModuleType('weilin_pkg.tag_library')
        class TagConflict(Exception):
            revision = None
        taglib.TagConflict = TagConflict
        taglib.TagLibrary = object
        sys.modules['weilin_pkg.prompt_selector.tag_library'] = taglib

        plan = types.ModuleType('weilin_pkg.tag_import_plan')
        plan.preview_tag_import = lambda *a, **k: {}
        sys.modules['weilin_pkg.prompt_selector.tag_import_plan'] = plan

        batch = types.ModuleType('weilin_pkg.tag_batch_jobs')
        class _E(Exception):
            pass
        class _Jobs:
            def __init__(self, *args, **kwargs): pass
            def start(self, *args, **kwargs): return {}
            def status(self, *args, **kwargs): return {}
            def cancel(self, *args, **kwargs): return {}
            def export(self, *args, **kwargs): return {}
        batch.TagBatchJobs = _Jobs
        batch.BatchConflict = _E
        batch.BatchError = _E
        batch.QueueFull = _E
        batch.UnknownJob = _E
        sys.modules['weilin_pkg.prompt_selector.tag_batch_jobs'] = batch

        ps = types.ModuleType('weilin_pkg.prompt_selector')
        ps._read_prompt_data_cached = lambda: {}
        ps._revision = lambda data: 'rev'
        ps._PROMPT_FILE_LOCK = None
        sys.modules['weilin_pkg.prompt_selector.prompt_selector'] = ps

        sel = types.ModuleType('weilin_pkg.selector_library')
        sel.collection_groups = lambda data: []
        sys.modules['weilin_pkg.prompt_selector.selector_library'] = sel

        # The single-item service is loaded by tag_api at import time; the
        # identity route never calls it, so a placeholder keeps this test
        # focused while item_maintenance keeps its own hermetic suite.
        item = types.ModuleType('weilin_pkg.prompt_selector.item_maintenance')
        item.read_item = lambda resource_id: {}
        item.write_item = lambda resource_id, payload: {}
        sys.modules['weilin_pkg.prompt_selector.item_maintenance'] = item

        bridge = types.ModuleType('weilin_pkg.tag_identity_bridge')
        real_bridge = Path(__file__).resolve().parents[1] / 'tag_identity_bridge.py'
        bridge_spec = importlib.util.spec_from_file_location('weilin_pkg.tag_identity_bridge', real_bridge)
        bridge_mod = importlib.util.module_from_spec(bridge_spec)
        sys.modules['weilin_pkg.prompt_selector.tag_identity_bridge'] = bridge_mod
        bridge_spec.loader.exec_module(bridge_mod)
        bridge.TagIdentityBridge = bridge_mod.TagIdentityBridge

        cls.tag_api = _load_tag_api()

    def setUp(self):
        relative = Path('benchmark_reports') / '2026-09-11_shared_collections' / 'evidence' / 'tag_link_candidates.json'
        real = next((parent / relative for parent in Path(__file__).resolve().parents if (parent / relative).is_file()), None)
        self.assertIsNotNone(real)
        self.assertTrue(real.is_file(), real)
        self.real_path = real
        self._restore = None

    def tearDown(self):
        self.tag_api.set_candidate_path_for_tests(None)

    def _route(self):
        return self.tag_api.PromptServer.instance.routes.get_routes['/prompt_selector/tags/identity']

    class _Q(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    class _Req:
        def __init__(self, query):
            self.query = query

    def _call(self, query):
        import asyncio
        route = self._route()
        return asyncio.run(route(self._Req(self._Q(query))))

    def _body(self, resp):
        return json.loads(resp.body.decode('utf-8'))

    def test_missing_identity_is_400(self):
        self.tag_api.set_candidate_path_for_tests(self.real_path)
        for query in ({}, {'tag_uuid': '', 'resource_id': ''}, {'tag_uuid': 'a', 'resource_id': 'b'}):
            resp = self._call(query)
            self.assertEqual(resp.status, 400, query)

    def test_no_match_is_deterministic_empty_200(self):
        self.tag_api.set_candidate_path_for_tests(self.real_path)
        resp = self._call({'tag_uuid': 'definitely-not-a-tag-uuid'})
        self.assertEqual(resp.status, 200)
        body = self._body(resp)
        self.assertEqual(body['count'], 0)
        self.assertEqual(body['matches'], [])
        self.assertIs(body['writes_to_sources'], False)
        self.assertIs(body['candidate_only'], True)

    def test_both_directions_and_metadata(self):
        self.tag_api.set_candidate_path_for_tests(self.real_path)
        bridge = self.tag_api.identity_bridge()
        sample = bridge.links[0]
        tag_uuid = sample['tag_sources'][0]['tag_uuid']
        resource_id = sample['prompt_targets'][0]['resource_id']

        by_tag = self._body(self._call({'tag_uuid': tag_uuid}))
        by_resource = self._body(self._call({'resource_id': resource_id}))
        self.assertGreaterEqual(by_tag['count'], 1)
        self.assertGreaterEqual(by_resource['count'], 1)
        for body in (by_tag, by_resource):
            self.assertIs(body['writes_to_sources'], False)
            self.assertIs(body['candidate_only'], True)

    def test_multi_record_relation_preserved(self):
        payload = {
            'schema': 'weilin-legacy-tag-link-candidates-v1',
            'summary': {'concepts': 1},
            'links': [{
                'status': 'candidate_not_applied',
                'relation': 'multiple_records',
                'tag_sources': [{'tag_uuid': 'tag-b'}, {'tag_uuid': 'tag-c'}],
                'prompt_targets': [{'resource_id': 'resource-b'}],
            }],
        }
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'links.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            self.tag_api.set_candidate_path_for_tests(path)
            body = self._body(self._call({'resource_id': 'resource-b'}))
            self.assertEqual(body['count'], 1)
            self.assertEqual(len(body['matches'][0]['tag_sources']), 2)

    def test_sources_are_not_written(self):
        self.tag_api.set_candidate_path_for_tests(self.real_path)
        import hashlib

        def digest(path):
            h = hashlib.sha256()
            h.update(Path(path).read_bytes())
            return h.hexdigest()

        before = digest(self.real_path)
        self._call({'tag_uuid': 'no-such-tag'})
        self._call({'resource_id': 'no-such-resource'})
        after = digest(self.real_path)
        self.assertEqual(before, after)

        # And the tags DB path must never be touched by this endpoint.
        with mock.patch.object(self.tag_api, 'library', side_effect=AssertionError('library() must not be called')):
            self._call({'tag_uuid': 'no-such-tag'})


if __name__ == '__main__':
    unittest.main()
