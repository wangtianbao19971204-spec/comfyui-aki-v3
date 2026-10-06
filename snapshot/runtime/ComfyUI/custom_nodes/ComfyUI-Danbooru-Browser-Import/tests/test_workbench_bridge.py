"""Isolated browser-to-workbench HTTP contract; no production cache or server."""
import importlib.util
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


MODULE_PATH = Path(__file__).resolve().parents[1] / "danbooru_browser_import.py"


class WorkbenchBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="workbench-browser-test-")
        self.environment = patch.dict(os.environ, {"COMFYUI_EXTERNAL_ROOT": self.directory.name})
        self.environment.start()
        self.events = []
        self.notify_error = None

        def send_sync(event, payload):
            if self.notify_error:
                raise self.notify_error
            self.events.append((event, payload))

        self.server = types.SimpleNamespace(routes=web.RouteTableDef(), send_sync=send_sync)
        server_module = types.ModuleType("server")
        server_module.PromptServer = types.SimpleNamespace(instance=self.server)
        spec = importlib.util.spec_from_file_location("isolated_workbench_bridge_" + uuid.uuid4().hex, MODULE_PATH)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"server": server_module}):
            spec.loader.exec_module(self.module)
        self.data_file = Path(self.directory.name) / "latest.json"
        self.module.DATA_FILE = str(self.data_file)
        self.module.LATEST = {}
        app = web.Application()
        app.add_routes(self.server.routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.environment.stop()
        self.directory.cleanup()

    def payload(self, **changes):
        value = {"positive": "1girl, blue eyes", "source_url": "https://danbooru.donmai.us/posts/123"}
        value.update(changes)
        return value

    async def post(self, payload):
        response = await self.client.post(self.module.WORKBENCH_ROUTE, json=payload)
        return response, await response.json()

    async def latest(self):
        response = await self.client.get(self.module.WORKBENCH_ROUTE)
        return response, await response.json()

    async def lease(self, action, import_id, receiver_id, claim_token=None, **changes):
        data = {"import_id": import_id, "receiver_id": receiver_id}
        if claim_token is not None:
            data["claim_token"] = claim_token
        data.update(changes)
        response = await self.client.post(self.module.WORKBENCH_ROUTE + "/" + action, json=data)
        return response, await response.json()

    def assert_private_response_headers(self, response):
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        for header in ("Access-Control-Allow-Origin", "Access-Control-Allow-Methods",
                       "Access-Control-Allow-Headers", "Access-Control-Allow-Credentials"):
            self.assertNotIn(header, response.headers)

    async def test_danbooru_normalization_persistence_event_and_recovery(self):
        response, result = await self.post(self.payload(
            positive="\n1girl, blue eyes \n", negative=" low quality ", title=" Source post ", post_id=123,
            source_url="https://danbooru.donmai.us:443/posts/123?ignored=value#discarded",
            image_url="https://cdn.donmai.us/original/example.jpg?ignored=value#discarded",
        ))
        self.assertEqual(response.status, 200)
        self.assertEqual(result["delivery"], "stored")
        self.assertTrue(result["realtime_notified"])
        self.assert_private_response_headers(response)
        payload = result["payload"]
        self.assertEqual(set(payload), {"import_id", "positive", "negative", "source_url", "title", "post_id", "image_url", "destination"})
        self.assertEqual(uuid.UUID(payload["import_id"]).version, 4)
        self.assertEqual(payload["positive"], "1girl, blue eyes")
        self.assertEqual(payload["negative"], "low quality")
        self.assertEqual(payload["source_url"], "https://danbooru.donmai.us/posts/123")
        self.assertEqual(payload["image_url"], "https://cdn.donmai.us/original/example.jpg")
        self.assertEqual(payload["title"], "Source post")
        self.assertEqual(payload["post_id"], "123")
        self.assertEqual(payload["destination"], "workbench")
        self.assertEqual(self.events, [(self.module.WORKBENCH_EVENT, payload)])
        self.assertFalse(self.data_file.exists(), "new imports must not write the Git latest JSON")
        stored = self.module._load_latest(force=True)
        self.assertEqual(stored["merged_tags"], payload["positive"])
        self.assertEqual(stored["prompt"], payload["positive"])
        self.assertEqual(stored["negative_prompt"], payload["negative"])
        self.assertEqual(stored["_route"], self.module.WORKBENCH_ROUTE)
        self.assertNotIn("discarded", json.dumps(stored))
        self.module.LATEST = {}
        recovered_response, recovered = await self.latest()
        self.assertEqual(recovered_response.status, 200)
        self.assert_private_response_headers(recovered_response)
        self.assertEqual(recovered["latest"], payload)
        self.assertEqual(recovered["items"], [payload])
        self.assertEqual(len(self.events), 1, "GET recovery must not rebroadcast")
        node_values = self.module.DanbooruBrowserImportV05().read_latest()
        self.assertEqual(len(node_values), 10)
        self.assertEqual(node_values[0], payload["positive"])
        self.assertEqual(node_values[6:9], (payload["source_url"], payload["image_url"], "123"))

    async def test_civitai_image_model_and_post_public_pages(self):
        ids = []
        for path in ("images/321", "models/321/example-model", "posts/321"):
            with self.subTest(path=path):
                response, result = await self.post(self.payload(
                    source_url="https://civitai.com/" + path + "?modelVersionId=42#discarded",
                    image_url="https://image.civitai.com/example/id/width=450/image.jpeg?ignored=value",
                ))
                self.assertEqual(response.status, 200)
                self.assertEqual(result["payload"]["source_url"], "https://civitai.com/" + path)
                self.assertEqual(result["payload"]["negative"], "")
                ids.append(result["payload"]["import_id"])
        self.assertEqual(len(set(ids)), 3)

    async def test_legacy_endpoint_node_and_cache_remain_compatible(self):
        legacy = {
            "merged_tags": ["1girl", "blue eyes"], "artist_tags": ["example artist"],
            "character_tags": ["example character"], "copyright_tags": "example series",
            "general_tags": "solo", "meta_tags": "highres", "source_url": "legacy source",
            "image_url": "legacy image", "post_id": "987", "legacy_extra": True,
        }
        response = await self.client.post(self.module.ROUTE, json=legacy)
        result = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(result["post_id"], "987")
        self.assertEqual(result["route"], "/danbooru_browser_import_v05")
        self.assertIn("legacy_extra", result["received_keys"])
        node = self.module.DanbooruBrowserImportV05()
        values = node.read_latest()
        self.assertEqual(values[:9], ("1girl, blue eyes", "example artist", "example character", "example series", "solo", "highres", "legacy source", "legacy image", "987"))
        self.assertEqual(len(values), 10)
        self.assertEqual(self.module.NODE_CLASS_MAPPINGS, {"DanbooruBrowserImportV05": self.module.DanbooruBrowserImportV05})
        self.assertEqual(self.module.DanbooruBrowserImportV05.RETURN_NAMES[0], "merged_tags")
        self.assertTrue(self.module.DanbooruBrowserImportV05.IS_CHANGED(7).startswith("7:"))
        _, new_result = await self.latest()
        self.assertIsNone(new_result["latest"])
        self.assertEqual(self.events, [])
        old_get = await self.client.get(self.module.ROUTE)
        self.assertEqual((await old_get.json())["latest"]["legacy_extra"], True)
        self.assertEqual(old_get.headers["Access-Control-Allow-Origin"], "*")

    async def test_first_get_has_no_latest_and_does_not_create_cache(self):
        response, result = await self.latest()
        self.assertEqual(response.status, 200)
        self.assertIsNone(result["latest"])
        self.assertEqual(result["items"], [])
        self.assertFalse(self.data_file.exists())
        self.assertFalse(self.module._inbox_path().exists())
        self.assertEqual(self.events, [])

    async def test_non_loopback_rejected_before_reading_or_persisting(self):
        request = types.SimpleNamespace(remote="198.51.100.5", headers={"X-Forwarded-For": "127.0.0.1"})
        for handler in (self.module.unified_workbench_browser_import_post,
                        self.module.unified_workbench_browser_import_get,
                        self.module.unified_workbench_browser_import_options):
            response = await handler(request)
            self.assertEqual(response.status, 403)
            self.assertEqual(json.loads(response.body), {"ok": False, "error": "loopback_required"})
            self.assert_private_response_headers(response)
        self.assertFalse(self.data_file.exists())
        self.assertEqual(self.events, [])
        for remote in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            self.assertTrue(self.module._is_loopback(types.SimpleNamespace(remote=remote)))
        for remote in (None, "not-an-ip", "192.168.1.2"):
            self.assertFalse(self.module._is_loopback(types.SimpleNamespace(remote=remote)))

    async def test_invalid_fields_text_and_urls_never_persist_or_echo(self):
        invalid = [
            [], {"positive": "only positive"}, self.payload(positive=" \t\n"),
            self.payload(positive=["private-value"]), self.payload(negative=None),
            self.payload(title="private-value\n"), self.payload(positive="x\0private-value"),
            self.payload(post_id=True), self.payload(post_id="private-value"),
            self.payload(extra="private-value"), self.payload(source_url="http://danbooru.donmai.us/posts/123"),
            self.payload(source_url="https://" + "discarded:discarded@" + "danbooru.donmai.us/posts/123"),
            self.payload(source_url="https://danbooru.donmai.us.evil.example/posts/123?private-value"),
            self.payload(source_url="https://civitai.com/login?private-value"),
            self.payload(source_url="https://civitai.com:8443/images/123"),
            self.payload(source_url="https://civitai.com/images/../login"),
            self.payload(image_url="https://external.example/private-value.jpg"),
            self.payload(image_url="https://civitai.com/api/private-value"),
        ]
        for value in invalid:
            with self.subTest(value_type=type(value).__name__):
                response, result = await self.post(value)
                self.assertEqual(response.status, 400)
                self.assertFalse(result["ok"])
                self.assertNotIn("private-value", json.dumps(result))
        self.assertFalse(self.data_file.exists())
        self.assertEqual(self.events, [])

    async def test_json_content_type_malformed_duplicate_and_bounded_body(self):
        response = await self.client.post(self.module.WORKBENCH_ROUTE, data="plain private-value")
        self.assertEqual(response.status, 415)
        self.assertEqual((await response.json())["error"], "json_required")
        for body in (b"not-json private-value", b"\xff", b'{"positive":"first","positive":"private-value"}'):
            response = await self.client.post(self.module.WORKBENCH_ROUTE, data=body, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status, 400)
            self.assertNotIn("private-value", await response.text())
        response, _ = await self.post(self.payload(positive="x" * (self.module.MAX_REQUEST_BYTES + 1)))
        self.assertEqual(response.status, 413)
        self.assertFalse(self.data_file.exists())
        self.assertEqual(self.events, [])

    async def test_individual_text_and_url_limits(self):
        for key, limit in self.module.TEXT_LIMITS.items():
            response, _ = await self.post(self.payload(**{key: "x" * (limit + 1)}))
            self.assertEqual(response.status, 400)
        response, _ = await self.post(self.payload(source_url="https://civitai.com/images/123?" + "x" * 2048))
        self.assertEqual(response.status, 400)
        self.assertFalse(self.data_file.exists())

    async def test_chunked_body_is_bounded_without_content_length(self):
        async def chunks():
            yield b'{"positive":"'
            for _ in range(33):
                yield b"x" * 8192
            yield b'","source_url":"https://civitai.com/images/123"}'
        response = await self.client.post(self.module.WORKBENCH_ROUTE, data=chunks(), headers={"Content-Type": "application/json"})
        self.assertEqual(response.status, 413)
        self.assertFalse(self.data_file.exists())
        self.assertEqual(self.events, [])

    async def test_atomic_storage_failure_preserves_old_cache_and_no_notification(self):
        original = {"merged_tags": "old tags", "source_url": "legacy source"}
        self.module._save_latest(original)
        original_bytes = self.data_file.read_bytes()
        with patch.object(self.module.sqlite3, "connect", side_effect=OSError("private-value")):
            response, result = await self.post(self.payload())
        self.assertEqual(response.status, 500)
        self.assert_private_response_headers(response)
        self.assertEqual(result, {"ok": False, "delivery": "failed", "error": "storage_write_failed"})
        self.assertEqual(self.data_file.read_bytes(), original_bytes)
        self.assertEqual(self.module.LATEST, original)
        self.assertEqual(self.events, [])

    async def test_realtime_failure_returns_stored_receipt_and_get_recovers(self):
        self.notify_error = RuntimeError("private-value")
        response, result = await self.post(self.payload())
        self.assertEqual(response.status, 202)
        self.assert_private_response_headers(response)
        self.assertTrue(result["ok"])
        self.assertEqual(result["delivery"], "stored")
        self.assertFalse(result["realtime_notified"])
        self.assertEqual(result["realtime_error"], "notification_failed")
        self.assertNotIn("private-value", json.dumps(result))
        self.assertFalse(self.data_file.exists())
        self.assertTrue(self.module._inbox_path().exists())
        self.assertEqual(self.events, [])
        recovered_response, recovered = await self.latest()
        self.assertEqual(recovered_response.status, 200)
        self.assertEqual(recovered["latest"], result["payload"])

    async def test_corrupt_or_oversized_storage_fails_without_echo(self):
        path = self.module._inbox_path()
        path.parent.mkdir(parents=True)
        for data in (b"private-value", b"x" * (self.module.MAX_STORED_BYTES + 1)):
            path.write_bytes(data)
            response, result = await self.latest()
            self.assertEqual(response.status, 500)
            self.assertEqual(result, {"ok": False, "error": "storage_read_failed"})
        self.assertEqual(self.events, [])
        path.unlink()
        await self.post(self.payload())
        for raw in ("private-value", "x" * (self.module.MAX_STORED_BYTES + 1),
                    json.dumps({"destination": "workbench", "import_id": "private-value", "positive": "text"})):
            with self.module._inbox_connection(write=True) as connection:
                connection.execute("UPDATE state SET payload_json=?", (raw,))
            response, result = await self.latest()
            self.assertEqual(response.status, 500)
            self.assertEqual(result, {"ok": False, "error": "storage_read_failed"})

    async def test_workbench_options_does_not_grant_cross_origin_preflight(self):
        response = await self.client.options(self.module.WORKBENCH_ROUTE, headers={
            "Origin": "https://arbitrary.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        })
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json()), {"ok": False, "error": "origin_not_allowed"})
        self.assert_private_response_headers(response)
        self.assertFalse(self.data_file.exists())

    async def test_cross_origin_workbench_responses_have_no_read_permission_or_cache(self):
        origin = {"Origin": "https://arbitrary.example"}
        response = await self.client.post(self.module.WORKBENCH_ROUTE, json=self.payload(), headers=origin)
        self.assertEqual(response.status, 403)
        self.assert_private_response_headers(response)
        self.assertEqual((await response.json())["error"], "origin_not_allowed")
        self.assertFalse(self.data_file.exists())
        response = await self.client.get(self.module.WORKBENCH_ROUTE, headers=origin)
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json())["error"], "origin_not_allowed")
        self.assert_private_response_headers(response)
        # An ordinary cross-origin simple POST cannot bypass the JSON-only
        # contract; a real browser's JSON preflight receives no CORS grant.
        response = await self.client.post(self.module.WORKBENCH_ROUTE, data="plain text", headers=origin)
        self.assertEqual(response.status, 403)
        self.assert_private_response_headers(response)
        self.assertEqual(len(self.events), 0)


    async def test_anonymous_gm_and_exact_same_origin_workbench_are_accepted(self):
        response, anonymous = await self.post(self.payload())
        self.assertEqual(response.status, 200)
        origin = {"Origin": str(self.client.make_url("/").origin())}
        response = await self.client.post(self.module.WORKBENCH_ROUTE, json=self.payload(), headers=origin)
        self.assertEqual(response.status, 200)
        same_origin = (await response.json())["payload"]
        self.assertNotEqual(same_origin["import_id"], anonymous["payload"]["import_id"])
        response = await self.client.get(self.module.WORKBENCH_ROUTE, headers=origin)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["latest"], same_origin)
        response = await self.client.options(self.module.WORKBENCH_ROUTE, headers=origin)
        self.assertEqual(response.status, 200)
        self.assert_private_response_headers(response)

    async def test_invalid_hosts_and_origins_are_rejected_without_dns_resolution(self):
        host_headers = ("arbitrary.example", "localhost.evil.example", "127.0.0.1.evil.example",
                        "user@127.0.0.1", "127.0.0.1:0", "127.0.0.1:invalid")
        for host in host_headers:
            response = await self.client.post(self.module.WORKBENCH_ROUTE, json=self.payload(), headers={"Host": host})
            self.assertEqual(response.status, 403)
            self.assertEqual((await response.json())["error"], "loopback_host_required")
        local = str(self.client.make_url("/").origin())
        origins = ("null", "https://arbitrary.example", local + "/path", local + "?query=value",
                   local + "#fragment", local.replace("http://", "https://"),
                   "http://127.0.0.1:1", "http://user@" + local.split("//", 1)[1])
        for origin in origins:
            response = await self.client.post(self.module.WORKBENCH_ROUTE, json=self.payload(), headers={"Origin": origin})
            self.assertEqual(response.status, 403)
            self.assertEqual((await response.json())["error"], "origin_not_allowed")
        self.assertFalse(self.data_file.exists())
        self.assertEqual(self.events, [])
        self.assertEqual(self.module._loopback_authority("localhost:8188"), ("localhost", 8188))
        self.assertEqual(self.module._loopback_authority("[::1]:8188"), ("::1", 8188))

    async def test_legacy_get_does_not_expose_workbench_payload_to_other_origins(self):
        _, stored = await self.post(self.payload(negative="example negative"))
        for headers in ({"Origin": "https://arbitrary.example"}, {"Host": "arbitrary.example"}):
            response = await self.client.get(self.module.ROUTE, headers=headers)
            self.assertEqual(response.status, 403)
            body = await response.json()
            self.assertNotIn("latest", body)
            self.assertNotIn("example negative", json.dumps(body))
            self.assert_private_response_headers(response)
        for headers in ({}, {"Origin": str(self.client.make_url("/").origin())}):
            response = await self.client.get(self.module.ROUTE, headers=headers)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["latest"]["import_id"], stored["payload"]["import_id"])
            self.assert_private_response_headers(response)

    async def test_legacy_post_cannot_forge_new_route_provenance(self):
        response = await self.client.post(self.module.ROUTE, json={
            **self.payload(), "destination": "workbench", "import_id": str(uuid.uuid4()),
            "_route": self.module.WORKBENCH_ROUTE,
        })
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8"))["_route"], self.module.ROUTE)
        response, result = await self.latest()
        self.assertEqual(response.status, 200)
        self.assertIsNone(result["latest"])
        self.assertEqual(self.events, [])

    async def test_only_active_workbench_cache_protects_legacy_post_from_cross_origin(self):
        response = await self.client.post(self.module.ROUTE, json={"merged_tags": "old tags"},
                                          headers={"Origin": "https://arbitrary.example"})
        self.assertEqual(response.status, 200, "existing legacy data retains its original protocol")
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        await self.post(self.payload())
        before = self.data_file.read_bytes()
        for headers in ({"Origin": "https://arbitrary.example"}, {"Host": "arbitrary.example"}):
            response = await self.client.post(self.module.ROUTE, data="overwrite attempt", headers=headers)
            self.assertEqual(response.status, 403)
            self.assert_private_response_headers(response)
            self.assertEqual(self.data_file.read_bytes(), before)
        response = await self.client.post(self.module.ROUTE, json={"merged_tags": "trusted legacy replacement"})
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8"))["merged_tags"], "trusted legacy replacement")
        _, result = await self.latest()
        self.assertIsNone(result["latest"])

    async def test_global_wildcard_cors_cannot_bypass_read_write_origin_guards(self):
        @web.middleware
        async def globally_permissive_cors(request, handler):
            # Mirrors ComfyUI's optional global CORS middleware, including its
            # OPTIONS short circuit. Route security must not depend on it.
            response = web.Response() if request.method == "OPTIONS" else await handler(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            return response

        app = web.Application(middlewares=[globally_permissive_cors])
        app.add_routes(self.server.routes)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            origin = {"Origin": "https://arbitrary.example"}
            preflight = await client.options(self.module.WORKBENCH_ROUTE, headers=origin)
            self.assertEqual(preflight.status, 200)
            self.assertEqual(preflight.headers["Access-Control-Allow-Origin"], "*")
            response = await client.post(self.module.WORKBENCH_ROUTE, json=self.payload(), headers=origin)
            self.assertEqual(response.status, 403)
            self.assertFalse(self.data_file.exists())
            stored_response = await client.post(self.module.WORKBENCH_ROUTE, json=self.payload())
            self.assertEqual(stored_response.status, 200)
            before = self.module._inbox_path().read_bytes()
            for route in (self.module.WORKBENCH_ROUTE, self.module.ROUTE):
                response = await client.get(route, headers=origin)
                self.assertEqual(response.status, 403)
                self.assertNotIn("latest", await response.json())
            response = await client.post(self.module.ROUTE, data="overwrite attempt", headers=origin)
            self.assertEqual(response.status, 403)
            self.assertEqual(self.module._inbox_path().read_bytes(), before)
            self.assertEqual(len(self.events), 1)
        finally:
            await client.close()

    async def test_five_sites_have_canonical_public_sources_and_explicit_media_hosts(self):
        pairs = [
            ("https://civitai.red/images/123?ignored=value", "https://civitai.red/images/123", "https://image.civitai.com/example.jpg"),
            ("https://www.pixai.art/zh-CN/artwork/123/?ignored=value#discarded", "https://pixai.art/artwork/123", "https://images-ng.pixai.art/gi/orig/example.jpg"),
            ("https://pixai.art/artwork/456", "https://pixai.art/artwork/456", "https://imagedelivery.net/example/image/public"),
            ("https://www.yande.re/post/show/123?ignored=value", "https://yande.re/post/show/123", "https://files.yande.re/image/example.jpg"),
            ("https://www.gelbooru.com/index.php?id=123&ignored=value&s=view&page=post#discarded", "https://gelbooru.com/index.php?page=post&s=view&id=123", "https://img3.gelbooru.com/images/example.jpg"),
        ]
        for source, canonical, image in pairs:
            response, result = await self.post(self.payload(source_url=source, image_url=image + "?ignored=value"))
            self.assertEqual(response.status, 200)
            self.assertEqual(result["payload"]["source_url"], canonical)
            self.assertEqual(result["payload"]["image_url"], image)
        for source in ("https://gelbooru.com/index.php?page=post&s=view&id=1&id=2",
                       "https://gelbooru.com/index.php?page=post&page=post&s=view&id=1",
                       "https://gelbooru.com/index.php?page=account&s=view&id=1",
                       "https://gelbooru.com/index.php?page=post&s=view&id=private-value",
                       "https://gelbooru.com/other.php?page=post&s=view&id=1",
                       "https://pixai.art/private/artwork/123",
                       "https://civitai.red.evil.example/images/123"):
            response, result = await self.post(self.payload(source_url=source))
            self.assertEqual(response.status, 400)
            self.assertNotIn("private-value", json.dumps(result))

    async def test_userinfo_is_rejected_in_both_source_and_media(self):
        for changes in ({"source_url": "https://" + "discarded@" + "civitai.com/images/123"},
                        {"image_url": "https://" + "discarded:discarded@" + "image.civitai.com/example.jpg"}):
            response, result = await self.post(self.payload(**changes))
            self.assertEqual(response.status, 400)
            self.assertEqual(result["error"], "invalid_url")
        self.assertFalse(self.module._inbox_path().exists())

    async def test_inbox_preserves_three_bursts_and_durable_reload_without_touching_legacy_json(self):
        self.module._save_latest({"merged_tags": "original legacy tags"})
        original = self.data_file.read_bytes()
        previous_token = self.module.DanbooruBrowserImportV05.IS_CHANGED(7)
        accepted = []
        for index in range(3):
            response, result = await self.post(self.payload(positive="burst " + str(index)))
            self.assertEqual(response.status, 200)
            accepted.append(result["payload"])
            token = self.module.DanbooruBrowserImportV05.IS_CHANGED(7)
            self.assertNotEqual(token, previous_token)
            self.assertEqual(self.module.DanbooruBrowserImportV05().read_latest()[0], "burst " + str(index))
            previous_token = token
        self.module.LATEST = {}
        self.assertEqual(self.data_file.read_bytes(), original)
        _, result = await self.latest()
        self.assertEqual(result["items"], accepted)
        self.assertEqual(result["latest"], accepted[-1])
        with self.module._inbox_connection() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(self.module.DanbooruBrowserImportV05().read_latest()[0], "burst 2")

    async def test_full_inbox_rejects_before_mutating_latest_or_notifying(self):
        for index in range(self.module.INBOX_LIMIT):
            response, result = await self.post(self.payload(positive="pending " + str(index)))
            self.assertEqual(response.status, 200)
        last = result["payload"]
        response, result = await self.post(self.payload(positive="overflow"))
        self.assertEqual(response.status, 409)
        self.assertEqual(result, {"ok": False, "delivery": "failed", "error": "inbox_full"})
        _, result = await self.latest()
        self.assertEqual(len(result["items"]), self.module.INBOX_LIMIT)
        self.assertEqual(result["latest"], last)
        self.assertEqual(len(self.events), self.module.INBOX_LIMIT)

    async def test_transaction_failure_rolls_back_inbox_and_latest_together(self):
        _, first = await self.post(self.payload(positive="original"))
        with self.module._inbox_connection(write=True) as connection:
            connection.execute("CREATE TRIGGER reject_state BEFORE INSERT ON state "
                               "BEGIN SELECT RAISE(ABORT, 'private-value'); END")
        response, result = await self.post(self.payload(positive="rejected"))
        self.assertEqual(response.status, 500)
        self.assertEqual(result["error"], "storage_write_failed")
        self.assertNotIn("private-value", json.dumps(result))
        _, result = await self.latest()
        self.assertEqual(result["items"], [first["payload"]])
        self.assertEqual(result["latest"], first["payload"])
        self.assertEqual(len(self.events), 1)

    async def test_two_receivers_only_one_claims_and_ack_is_idempotent_without_payload(self):
        _, stored = await self.post(self.payload())
        import_id = stored["payload"]["import_id"]
        receivers = [str(uuid.uuid4()), str(uuid.uuid4())]
        results = await asyncio.gather(*(self.lease("claim", import_id, receiver) for receiver in receivers))
        winner = next(index for index, (response, _) in enumerate(results) if response.status == 200)
        loser = 1 - winner
        self.assertEqual(results[loser][0].status, 409)
        self.assertEqual(results[loser][1]["error"], "already_claimed")
        self.assertGreater(results[loser][1]["retry_after_ms"], 0)
        claim = results[winner][1]
        self.assert_private_response_headers(results[winner][0])
        response, repeated = await self.lease("claim", import_id, receivers[winner])
        self.assertEqual(repeated["claim_token"], claim["claim_token"])
        self.assertEqual(repeated["claim_expires_at"], claim["claim_expires_at"])
        _, listing = await self.latest()
        self.assertEqual(listing["items"], [stored["payload"]], "GET includes all unacknowledged items")
        for _ in range(2):
            response, result = await self.lease("ack", import_id, receivers[winner], claim["claim_token"])
            self.assertEqual(response.status, 200)
            self.assertEqual(result, {"ok": True, "delivery": "accepted", "import_id": import_id})
        _, listing = await self.latest()
        self.assertEqual(listing["items"], [])
        self.assertEqual(listing["latest"], stored["payload"])
        response, result = await self.lease("claim", import_id, receivers[loser])
        self.assertEqual(result, {"ok": True, "delivery": "accepted", "import_id": import_id})
        response, result = await self.lease("ack", import_id, receivers[loser], claim["claim_token"])
        self.assertEqual(response.status, 409)
        self.assertEqual(result["error"], "claim_mismatch")

    async def test_expired_and_released_claim_tokens_cannot_ack_new_lease(self):
        _, stored = await self.post(self.payload())
        import_id, receiver = stored["payload"]["import_id"], str(uuid.uuid4())
        _, first = await self.lease("claim", import_id, receiver)
        with patch.object(self.module.time, "time", return_value=first["claim_expires_at"] + 1):
            response, expired = await self.lease("ack", import_id, receiver, first["claim_token"])
            self.assertEqual(response.status, 409)
            self.assertEqual(expired["error"], "claim_expired")
            _, second = await self.lease("claim", import_id, receiver)
        self.assertNotEqual(first["claim_token"], second["claim_token"])
        for action in ("ack", "release"):
            response, result = await self.lease(action, import_id, receiver, first["claim_token"])
            self.assertEqual(response.status, 409)
            self.assertEqual(result["error"], "claim_mismatch")
        response, result = await self.lease("release", import_id, receiver, second["claim_token"])
        self.assertEqual(result["delivery"], "released")
        _, third = await self.lease("claim", import_id, receiver)
        self.assertNotEqual(second["claim_token"], third["claim_token"])
        response, result = await self.lease("ack", import_id, receiver, second["claim_token"])
        self.assertEqual(response.status, 409)
        self.assertEqual(result["error"], "claim_mismatch")
        _, listing = await self.latest()
        self.assertEqual(listing["items"], [stored["payload"]])

    async def test_claim_json_uuid_fields_unknown_ids_and_all_route_origin_guards(self):
        unknown, receiver = str(uuid.uuid4()), str(uuid.uuid4())
        for action in ("claim", "ack", "release"):
            token = str(uuid.uuid4()) if action != "claim" else None
            response, result = await self.lease(action, unknown, receiver, token)
            self.assertEqual(response.status, 404)
            self.assertEqual(result["error"], "import_not_found")
            response, result = await self.lease(action, "private-value", receiver, token)
            self.assertEqual(response.status, 400)
            self.assertEqual(result["error"], "invalid_id")
            response, result = await self.lease(action, unknown, receiver, token, extra="private-value")
            self.assertEqual(response.status, 400)
            self.assertNotIn("private-value", json.dumps(result))
            route = self.module.WORKBENCH_ROUTE + "/" + action
            for method in ("post", "options"):
                response = await getattr(self.client, method)(route, headers={"Origin": "https://arbitrary.example"})
                self.assertEqual(response.status, 403)
                self.assert_private_response_headers(response)

    async def test_accepted_ledger_is_bounded_and_contains_no_prompt_bodies(self):
        receiver = str(uuid.uuid4())
        for index in range(self.module.ACCEPTED_LIMIT + 1):
            _, stored = await self.post(self.payload(positive="ledger prompt " + str(index)))
            import_id = stored["payload"]["import_id"]
            _, claim = await self.lease("claim", import_id, receiver)
            response, _ = await self.lease("ack", import_id, receiver, claim["claim_token"])
            self.assertEqual(response.status, 200)
        with self.module._inbox_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM accepted").fetchone()[0], self.module.ACCEPTED_LIMIT)
            self.assertEqual(connection.execute("SELECT count(*) FROM inbox").fetchone()[0], 0)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(accepted)")}
            self.assertEqual(columns, {"import_id", "receiver_id", "claim_token", "accepted_at"})

    async def test_unknown_schema_is_rejected_without_replacing_or_dropping_tables(self):
        path = self.module._inbox_path()
        path.parent.mkdir(parents=True)
        for version in (0, 2):
            if path.exists():
                path.unlink()
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE unrelated (value TEXT)")
                connection.execute("INSERT INTO unrelated VALUES ('private-value')")
                connection.execute("PRAGMA user_version=" + str(version))
                connection.commit()
            finally:
                connection.close()
            before = path.read_bytes()
            response, result = await self.post(self.payload())
            self.assertEqual(response.status, 500)
            self.assertEqual(result["error"], "storage_write_failed")
            self.assertEqual(path.read_bytes(), before)
            response, result = await self.latest()
            self.assertEqual(response.status, 500)
            self.assertNotIn("private-value", json.dumps(result))
        self.assertEqual(self.events, [])

    async def test_external_root_rejects_checkout_traversal_relative_and_link_paths(self):
        for root in (str(MODULE_PATH.parent), "relative-private", str(Path(self.directory.name) / ".." / "escape"),
                     str(Path(self.directory.name) / ".git" / "private")):
            with patch.dict(os.environ, {"COMFYUI_EXTERNAL_ROOT": root}):
                response, result = await self.post(self.payload())
                self.assertEqual(response.status, 500)
                self.assertEqual(result["error"], "storage_write_failed")
        external = Path(self.directory.name) / "linked-private"
        target = Path(self.directory.name) / "target"
        target.mkdir()
        try:
            external.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("local symlink creation is unavailable")
        with patch.dict(os.environ, {"COMFYUI_EXTERNAL_ROOT": str(external)}):
            response, result = await self.post(self.payload())
            self.assertEqual(response.status, 500)
        self.assertFalse((target / "mutable-data").exists())


if __name__ == "__main__":
    unittest.main()
