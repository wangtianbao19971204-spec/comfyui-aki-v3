import importlib.util
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_lora_api_module(user_dir: str):
    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_user_directory = lambda: user_dir
    folder_paths.get_folder_paths = lambda _name: []
    sys.modules.setdefault("folder_paths", folder_paths)

    module_name = "anima_lora_api_routing_test"
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN_DIR / "anima_lora_api.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeDownloadResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def read(self, size=-1):
        if self.offset >= len(self.payload):
            return b""
        if size is None or size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class CivitaiRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.api = load_lora_api_module(cls.temp_dir.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def make_public_result(self, model_id=1):
        return {
            "items": [{
                "id": model_id,
                "name": "Example",
                "type": "LORA",
                "creator": {"username": "tester"},
                "stats": {},
                "modelVersions": [{
                    "id": model_id * 10,
                    "name": "v1",
                    "baseModel": "Anima",
                    "files": [],
                    "images": [],
                }],
            }],
            "metadata": {"nextCursor": "next"},
        }

    def test_red_c_is_primary_and_cache_namespace_is_bumped(self):
        self.assertEqual(self.api.CIVITAI_API_BASE, "https://civitai.red/api/v1")
        self.assertEqual(self.api.CIVITAI_API_FALLBACK_BASE, "https://civitai.com/api/v1")
        self.assertIn("red-primary", self.api._CIVITAI_CACHE_VERSION)

    def test_preview_url_uses_civitai_source_width_route(self):
        source_url = (
            "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/"
            "2a9f6f60-468b-455e-9be6-017035903327/original=true/141100370.jpeg"
        )

        preview_url = self.api.get_civitai_preview_image_url(source_url, width=450)

        self.assertEqual(
            preview_url,
            source_url.replace("/original=true/", "/width=450/"),
        )
        self.assertNotIn("image-b2.civitai.com", preview_url)

    def test_preview_url_updates_existing_source_width(self):
        source_url = (
            "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/"
            "2a9f6f60-468b-455e-9be6-017035903327/width=320/141100370.jpeg"
        )

        preview_url = self.api.get_civitai_preview_image_url(source_url, width=512)

        self.assertIn("/width=512/", preview_url)
        self.assertNotIn("/width=320/", preview_url)

    def test_preview_url_expands_bare_search_index_uuid(self):
        image_uuid = "73d1564d-5f59-4be2-8dcb-89cf39a5c979"

        preview_url = self.api.get_civitai_preview_image_url(image_uuid, width=450)

        self.assertEqual(
            preview_url,
            f"https://image-b2.civitai.com/file/civitai-media-cache/{image_uuid}/original",
        )

    def test_preview_opener_uses_isolated_system_proxy(self):
        response = object()
        opener = mock.Mock()
        opener.open.return_value = response
        request = urllib.request.Request("https://image.civitai.com/example.jpg")

        with mock.patch.object(
            self.api,
            "load_config",
            return_value={"civitai_image_proxy": ""},
        ), mock.patch.object(
            self.api.urllib.request,
            "getproxies",
            return_value={"http": "http://127.0.0.1:10081", "ftp": "ignored"},
        ), mock.patch.object(
            self.api.urllib.request,
            "build_opener",
            return_value=opener,
        ) as build_opener:
            result = self.api.open_civitai_preview_url(request, timeout=17)

        self.assertIs(result, response)
        proxy_handler = build_opener.call_args.args[0]
        self.assertEqual(proxy_handler.proxies, {"http": "http://127.0.0.1:10081"})
        opener.open.assert_called_once_with(request, timeout=17)

    def test_preview_opener_prefers_lora_specific_proxy(self):
        opener = mock.Mock()
        request = urllib.request.Request("https://image.civitai.com/example.jpg")

        with mock.patch.object(
            self.api,
            "load_config",
            return_value={"civitai_image_proxy": "http://127.0.0.1:10081"},
        ), mock.patch.object(
            self.api.urllib.request,
            "getproxies",
        ) as getproxies, mock.patch.object(
            self.api.urllib.request,
            "build_opener",
            return_value=opener,
        ) as build_opener:
            self.api.open_civitai_preview_url(request)

        getproxies.assert_not_called()
        proxy_handler = build_opener.call_args.args[0]
        self.assertEqual(
            proxy_handler.proxies,
            {
                "http": "http://127.0.0.1:10081",
                "https": "http://127.0.0.1:10081",
            },
        )

    def test_category_search_transport_uses_lora_proxy_opener(self):
        payload = b'{"results":[{"hits":[],"estimatedTotalHits":0}]}'
        response = FakeDownloadResponse(payload)

        with mock.patch.object(
            self.api,
            "open_civitai_preview_url",
            return_value=response,
        ) as open_url:
            result = self.api._post_json_url(
                "https://search-new.civitai.com/multi-search",
                {"queries": []},
                api_key="public-search-key",
                timeout=19,
            )

        self.assertEqual(result["results"][0]["estimatedTotalHits"], 0)
        request = open_url.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.host, "search-new.civitai.com")
        open_url.assert_called_once_with(request, timeout=19)

    def test_public_search_uses_red_without_calling_blue_when_result_is_valid(self):
        calls = []

        def fake_read(url, **_kwargs):
            calls.append(url)
            return self.make_public_result(11)

        with mock.patch.object(self.api, "load_config", return_value={"civitai_api_key": ""}), \
             mock.patch.object(self.api, "_read_json_url", side_effect=fake_read):
            result = self.api._search_civitai_loras_uncached(base_model="Anima")

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("https://civitai.red/api/v1/models?"))
        self.assertEqual(result["metadata"]["source"], "public-api")
        self.assertEqual(result["metadata"]["sourceHost"], "civitai.red")
        self.assertEqual(result["metadata"]["sourceRole"], "primary")
        self.assertEqual(result["items"][0]["_search_host"], "civitai.red")

    def test_public_search_falls_back_to_blue_after_red_has_no_valid_items(self):
        calls = []
        responses = iter([{"items": [], "metadata": {}}, self.make_public_result(22)])

        def fake_read(url, **_kwargs):
            calls.append(url)
            return next(responses)

        with mock.patch.object(self.api, "load_config", return_value={"civitai_api_key": ""}), \
             mock.patch.object(self.api, "_read_json_url", side_effect=fake_read):
            result = self.api._search_civitai_loras_uncached(base_model="Anima")

        self.assertTrue(calls[0].startswith("https://civitai.red/api/v1/models?"))
        self.assertTrue(calls[1].startswith("https://civitai.com/api/v1/models?"))
        self.assertEqual(result["metadata"]["sourceHost"], "civitai.com")
        self.assertEqual(result["metadata"]["sourceRole"], "fallback")

    def test_model_detail_falls_back_to_blue_and_records_source(self):
        calls = []
        responses = iter([{"error": "not available"}, {"id": 123, "name": "Example", "modelVersions": []}])

        def fake_read(url, **_kwargs):
            calls.append(url)
            return next(responses)

        with mock.patch.object(self.api, "_load_civitai_cached_response", return_value=(None, 0)), \
             mock.patch.object(self.api, "_save_civitai_cached_response"), \
             mock.patch.object(self.api, "load_config", return_value={"civitai_api_key": ""}), \
             mock.patch.object(self.api, "_read_json_url", side_effect=fake_read):
            result = self.api.fetch_civitai_model(123, force_refresh=True)

        self.assertEqual(calls, [
            "https://civitai.red/api/v1/models/123",
            "https://civitai.com/api/v1/models/123",
        ])
        self.assertEqual(result["_anima_source"]["sourceHost"], "civitai.com")
        self.assertEqual(result["_anima_source"]["sourceRole"], "fallback")

    def test_shared_category_index_reports_its_actual_host(self):
        payload = {"results": [{"hits": [], "estimatedTotalHits": 0}]}
        with mock.patch.object(self.api, "_post_json_url", return_value=payload):
            result = self.api._search_civitai_loras_meili(
                "", "", "character", "models_v9", "", 40, "Anima"
            )

        self.assertEqual(result["metadata"]["source"], "meili")
        self.assertEqual(result["metadata"]["sourceHost"], "search-new.civitai.com")
        self.assertEqual(result["metadata"]["sourceRole"], "shared-search-index")

    def test_download_candidates_are_red_first_and_preserve_query(self):
        candidates = self.api._civitai_download_candidates(
            "https://www.civitai.com/api/download/models/123?foo=bar"
        )
        self.assertEqual(candidates, [
            "https://civitai.red/api/download/models/123?foo=bar",
            "https://civitai.com/api/download/models/123?foo=bar",
        ])

    def test_download_falls_back_to_blue_after_red_network_failure(self):
        task_id = "download-fallback-test"
        requested_hosts = []

        def fake_urlopen(request, timeout):
            self.assertEqual(timeout, 60)
            host = request.host
            requested_hosts.append(host)
            if host == "civitai.red":
                raise urllib.error.URLError("red unavailable")
            return FakeDownloadResponse(b"model")

        with tempfile.TemporaryDirectory() as tmp:
            save_path = str(Path(tmp) / "example.safetensors")
            self.api._DOWNLOAD_JOBS[task_id] = {
                "status": "pending",
                "progress": 0,
                "total": 0,
                "error": "",
                "save_path": save_path,
                "base_model": "Anima",
            }
            try:
                with mock.patch.object(self.api.urllib.request, "urlopen", side_effect=fake_urlopen):
                    self.api._download_thread(
                        task_id,
                        "https://civitai.com/api/download/models/123",
                        save_path,
                    )

                job = self.api._DOWNLOAD_JOBS[task_id]
                self.assertEqual(requested_hosts, ["civitai.red", "civitai.com"])
                self.assertEqual(job["status"], "completed")
                self.assertEqual(job["source_host"], "civitai.com")
                self.assertEqual(job["source_role"], "fallback")
                self.assertEqual(job["attempted_hosts"], ["civitai.red", "civitai.com"])
                self.assertEqual(Path(save_path).read_bytes(), b"model")
            finally:
                self.api._DOWNLOAD_JOBS.pop(task_id, None)


if __name__ == "__main__":
    unittest.main()
