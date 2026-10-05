import asyncio
import importlib.util
import json
import logging
from pathlib import Path
import sys
import types

import pytest
import requests


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PLUGIN_ROOT / "py" / "danbooru_gallery" / "danbooru_gallery.py"

# The plugin directory contains an __init__.py but its on-disk folder name is not a
# valid Python identifier. Pytest's default import mode otherwise imports that file as
# the top-level module "__init__" during Package.setup, before fixtures can install the
# isolated ComfyUI stubs below. Register a matching inert package module so collection
# stays focused on the backend file under test and does not initialize every custom node.
_plugin_init = types.ModuleType("__init__")
_plugin_init.__file__ = str(PLUGIN_ROOT / "__init__.py")
_plugin_init.__path__ = [str(PLUGIN_ROOT)]
_plugin_init.__package__ = "__init__"
sys.modules.setdefault("__init__", _plugin_init)


def _package(name, path):
    package = types.ModuleType(name)
    package.__package__ = name
    package.__path__ = [str(path)]
    sys.modules[name] = package
    return package


@pytest.fixture(scope="module")
def gallery_module():
    """Load the single backend module without starting a real ComfyUI server."""
    root_name = "_v53_gallery_test_plugin"
    _package(root_name, PLUGIN_ROOT)
    _package(f"{root_name}.py", PLUGIN_ROOT / "py")
    _package(f"{root_name}.py.danbooru_gallery", PLUGIN_ROOT / "py" / "danbooru_gallery")
    _package(f"{root_name}.py.utils", PLUGIN_ROOT / "py" / "utils")
    _package(f"{root_name}.py.shared", PLUGIN_ROOT / "py" / "shared")
    _package(f"{root_name}.py.shared.db", PLUGIN_ROOT / "py" / "shared" / "db")

    test_logger = logging.getLogger("v53.legacy.security")
    test_logger.handlers.clear()
    test_logger.filters.clear()
    test_logger.propagate = False
    test_logger.setLevel(logging.DEBUG)

    logger_module = types.ModuleType(f"{root_name}.py.utils.logger")
    logger_module.get_logger = lambda _name: test_logger
    sys.modules[logger_module.__name__] = logger_module

    db_module = types.ModuleType(f"{root_name}.py.shared.db.db_manager")
    db_module.get_db_manager = lambda: None
    sys.modules[db_module.__name__] = db_module

    folder_paths_module = types.ModuleType("folder_paths")
    sys.modules.setdefault("folder_paths", folder_paths_module)

    class Routes:
        @staticmethod
        def get(_path):
            return lambda function: function

        @staticmethod
        def post(_path):
            return lambda function: function

    server_module = types.ModuleType("server")
    server_module.PromptServer = type(
        "PromptServer", (), {"instance": types.SimpleNamespace(routes=Routes())}
    )
    sys.modules.setdefault("server", server_module)

    module_name = f"{root_name}.py.danbooru_gallery.danbooru_gallery"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_shared_redaction_covers_urls_headers_and_exception_text(gallery_module):
    mod = gallery_module
    secrets = {
        "url_key": "url-secret-123",
        "login": "private-user",
        "bearer": "bearer-secret-456",
        "cookie": "session-cookie-789",
        "meili": "meili-secret-012",
        "password": "proxy-password-345",
    }
    text = (
        "ProxyError GET "
        f"https://proxy-user:{secrets['password']}@example.test/posts?api_key={secrets['url_key']}"
        f"&login={secrets['login']}&safe=visible "
        f"headers={{'Authorization': 'Bearer {secrets['bearer']}', "
        f"'Cookie': '{secrets['cookie']}', 'X-Meili-API-Key': '{secrets['meili']}'}}"
    )

    safe = mod._sanitize_log_text(text, include_configured=False)

    for secret in secrets.values():
        assert secret not in safe
    assert "safe=visible" in safe
    assert "example.test/posts" in safe
    assert "<redacted>" in safe or "%3Credacted%3E" in safe
    assert mod._redact_headers({
        "Authorization": secrets["bearer"],
        "Cookie": secrets["cookie"],
        "X-Meili-API-Key": secrets["meili"],
        "Accept": "application/json",
    }) == {
        "Authorization": "<redacted>",
        "Cookie": "<redacted>",
        "X-Meili-API-Key": "<redacted>",
        "Accept": "application/json",
    }


def test_logger_filter_redacts_network_records(gallery_module):
    mod = gallery_module
    secret = "must-never-reach-a-log"
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    mod.logger.addHandler(handler)
    try:
        mod.logger.error(
            "request failed url=%s headers=%s",
            f"https://example.test/?api_key={secret}",
            {"Authorization": f"Bearer {secret}", "Cookie": f"sid={secret}"},
        )
    finally:
        mod.logger.removeHandler(handler)

    assert records
    assert secret not in "\n".join(records)
    assert "<redacted>" in records[-1] or "%3Credacted%3E" in records[-1]


def test_gelbooru_html_headers_are_merged_once(gallery_module, monkeypatch):
    mod = gallery_module
    captured = {}

    def fake_request(method, url, headers, throttle=None, **kwargs):
        captured.update({"method": method, "url": url, "headers": headers, "kwargs": kwargs})
        return types.SimpleNamespace(status_code=200, headers={}, text="", content=b"")

    monkeypatch.setattr(mod, "_request_with_headers", fake_request)
    response = mod._gelbooru_request(
        "GET",
        "https://gelbooru.com/index.php",
        headers={"Accept": "text/html", "X-Test": "html-fallback"},
        params={"page": "post"},
    )

    assert response.status_code == 200
    assert captured["headers"]["Accept"] == "text/html"
    assert captured["headers"]["User-Agent"] == mod.GELBOORU_HEADERS["User-Agent"]
    assert captured["headers"]["X-Test"] == "html-fallback"
    assert "headers" not in captured["kwargs"]


def test_internal_posts_raises_structured_network_error(gallery_module, monkeypatch):
    mod = gallery_module
    secret = "proxy-query-secret"
    monkeypatch.setattr(mod, "load_settings", lambda: {"cache_enabled": False})
    mod.DanbooruGalleryNode._post_cache.clear()

    def fail(**_kwargs):
        raise requests.exceptions.ProxyError(
            f"proxy failed for https://example.test/posts?api_key={secret}"
        )

    monkeypatch.setattr(
        mod.DanbooruGalleryNode, "_get_danbooru_posts", staticmethod(fail)
    )

    with pytest.raises(mod.LegacyGalleryError) as raised:
        mod.DanbooruGalleryNode.get_posts_internal(
            tags="cat", limit=20, page=1, source="danbooru"
        )

    error = raised.value
    assert error.code == "network_unavailable"
    assert error.http_status == 502
    assert error.retryable is True
    assert secret not in error.public_message


def test_legacy_posts_route_returns_stable_non_2xx_envelope(gallery_module, monkeypatch):
    mod = gallery_module
    secret = "route-proxy-secret"

    def fail(**_kwargs):
        raise requests.exceptions.ProxyError(
            f"proxy failed https://example.test/?api_key={secret} "
            f"Authorization: Bearer {secret}"
        )

    monkeypatch.setattr(
        mod.DanbooruGalleryNode, "get_posts_internal", staticmethod(fail)
    )
    request = types.SimpleNamespace(query={
        "search[tags]": "cat",
        "limit": "20",
        "page": "1",
        "source": "danbooru",
    })

    response = asyncio.run(mod.get_posts_for_front(request))
    payload = json.loads(response.text)

    assert response.status == 502
    assert payload["items"] == []
    assert payload["error"] == {
        "code": "network_unavailable",
        "httpStatus": 502,
        "retryable": True,
        "message": "画廊列表请求网络不可用",
        "source": "danbooru",
    }
    assert secret not in response.text
    assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"


def test_legacy_posts_route_keeps_real_empty_result_as_bare_array(gallery_module, monkeypatch):
    mod = gallery_module
    monkeypatch.setattr(
        mod.DanbooruGalleryNode,
        "get_posts_internal",
        staticmethod(lambda **_kwargs: ("[]",)),
    )
    request = types.SimpleNamespace(query={
        "search[tags]": "no_such_tag",
        "limit": "20",
        "page": "1",
        "source": "danbooru",
    })

    response = asyncio.run(mod.get_posts_for_front(request))

    assert response.status == 200
    assert json.loads(response.text) == []


def test_yandere_non_200_is_not_an_empty_success(gallery_module, monkeypatch):
    mod = gallery_module
    response = types.SimpleNamespace(
        status_code=503,
        headers={"Retry-After": "3"},
        text="temporary upstream failure api_key=do-not-log",
    )
    monkeypatch.setattr(mod, "_yandere_request", lambda *_args, **_kwargs: response)

    with pytest.raises(mod.LegacyGalleryError) as raised:
        mod._get_yandere_posts("cat", limit=20, page=1)

    assert raised.value.code == "upstream_busy"
    assert raised.value.http_status == 503
    assert raised.value.retry_after_seconds == 3


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}])
def test_civitai_union_unwrap_preserves_superjson_values(gallery_module, value):
    document = {"result": {"data": {"json": value}}}

    assert gallery_module._civitai_unwrap_trpc_document(document, "fixture") == value


def test_civitai_union_unwrap_decodes_devalue_date_and_undefined(gallery_module):
    # Equivalent to a small devalue.stringify result. Container integers are
    # references into this flat table, not the final numeric values.
    flat = [
        {"items": 1, "nextCursor": 2, "omitted": -1},
        [3, 4, -1],
        123456789,
        {"id": 5, "createdAt": 6},
        {"id": 7},
        "image-1",
        ["Date", "2026-07-23T00:00:00.000Z"],
        "image-2",
    ]
    document = {"result": {"data": json.dumps(flat, separators=(",", ":"))}}

    decoded = gallery_module._civitai_unwrap_trpc_document(document, "image.getInfinite")

    assert decoded == {
        "items": [
            {"id": "image-1", "createdAt": "2026-07-23T00:00:00.000Z"},
            {"id": "image-2"},
            None,
        ],
        "nextCursor": 123456789,
    }


def test_civitai_union_unwrap_accepts_standalone_undefined(gallery_module):
    document = {"result": {"data": "-1"}}

    assert gallery_module._civitai_unwrap_trpc_document(document, "collection.saveItem") is None


def test_civitai_devalue_decoder_enforces_global_allocation_budget(gallery_module):
    max_items = gallery_module._CIVITAI_DEVALUE_MAX_ARRAY_ITEMS
    flat = [[1, 2], [-7, max_items], [-7, max_items]]

    with pytest.raises(RuntimeError, match="allocation is too large"):
        gallery_module._civitai_devalue_unflatten(json.dumps(flat))


@pytest.mark.parametrize("serialized", ["[NaN]", "[Infinity]", "[-Infinity]", "[1e309]"])
def test_civitai_devalue_decoder_rejects_non_finite_numbers(gallery_module, serialized):
    with pytest.raises(RuntimeError):
        gallery_module._civitai_devalue_unflatten(serialized)


def test_civitai_union_unwrap_rejects_any_error_envelope(gallery_module):
    document = {
        "error": {"json": {"message": "private upstream error"}},
        "result": {"data": {"json": {"items": []}}},
    }

    with pytest.raises(RuntimeError, match="error envelope"):
        gallery_module._civitai_unwrap_trpc_document(document, "fixture")


@pytest.mark.parametrize(
    "flat",
    [
        [{"items": 99}],
        [["UnknownCustomType", 1], "private-value"],
        [{"__proto__": 1}, "private-value"],
        [{"self": 0}],
    ],
)
def test_civitai_devalue_decoder_rejects_malformed_or_unsafe_graphs(gallery_module, flat):
    with pytest.raises(RuntimeError):
        gallery_module._civitai_devalue_unflatten(json.dumps(flat))


def test_civitai_remote_collection_buffers_upstream_batches_without_skips(
    gallery_module, monkeypatch
):
    mod = gallery_module
    mod._invalidate_civitai_remote_collection_cache()
    monkeypatch.setattr(
        mod,
        "_civitai_remote_resolve_collection",
        lambda _ref="": {"id": 77, "name": "fixture", "type": "Image", "isOwner": True},
    )
    upstream = [
        (list(range(1, 101)), 1000),
        (list(range(101, 201)), 2000),
        (list(range(201, 251)), None),
    ]
    calls = []

    class Response:
        status_code = 200
        text = "fixture"

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_trpc_get(procedure, payload, timeout=20, referer_image_id=None, meta_values=None):
        assert procedure == "image.getInfinite"
        batch_index = len(calls)
        ids, next_cursor = upstream[batch_index]
        calls.append({"cursor": payload.get("cursor"), "meta": meta_values})
        # Return the current devalue string shape end-to-end so the cursor used
        # for the next upstream request is the value restored by the decoder.
        flat = [{"items": 1, "nextCursor": 2}, [], next_cursor]
        for item_id in ids:
            item_ref = len(flat)
            id_ref = item_ref + 1
            url_ref = item_ref + 2
            flat[1].append(item_ref)
            flat.extend([
                {"id": id_ref, "url": url_ref},
                item_id,
                f"https://image.civitai.com/{item_id}.jpg",
            ])
        return Response({"result": {"data": json.dumps(flat, separators=(",", ":"))}})

    monkeypatch.setattr(mod, "_civitai_trpc_get", fake_trpc_get)
    visible = []
    upstream_call_counts = []
    page_calls = []
    for page in range(1, 8):
        buffered, call = mod._civitai_remote_get_collection_posts(
            "77", limit=40, page=page, force_refresh=(page == 1)
        )
        start = (page - 1) * 40
        visible.extend(int(post["id"]) for post in buffered[start : start + 40])
        upstream_call_counts.append(len(calls))
        page_calls.append(call)

    assert visible == list(range(1, 251))
    assert len(visible) == len(set(visible))
    assert upstream_call_counts == [1, 1, 2, 2, 2, 3, 3]
    assert [entry["cursor"] for entry in calls] == [None, 1000, 2000]
    assert calls[0]["meta"] == {"cursor": ["undefined"]}
    assert calls[1]["meta"] is None
    assert page_calls[4]["has_more"] is True
    assert page_calls[5]["has_more"] is False
    assert all(call["local_pagination"] is True for call in page_calls)


def test_civitai_remote_collection_rejects_expired_pagination_session(
    gallery_module, monkeypatch
):
    mod = gallery_module
    mod._invalidate_civitai_remote_collection_cache()
    monkeypatch.setattr(
        mod,
        "_civitai_remote_resolve_collection",
        lambda _ref="": {"id": 78, "name": "session-fixture", "type": "Image"},
    )
    calls = []

    class Response:
        status_code = 200
        text = "fixture"

        def json(self):
            return {"result": {"data": {"json": {
                "items": [
                    {"id": item_id, "url": f"https://image.civitai.com/{item_id}.jpg"}
                    for item_id in range(40)
                ],
                "nextCursor": 1000,
            }}}}

    def fake_trpc_get(*_args, **_kwargs):
        calls.append(1)
        return Response()

    monkeypatch.setattr(mod, "_civitai_trpc_get", fake_trpc_get)
    _, first_call = mod._civitai_remote_get_collection_posts(
        "78", limit=40, page=1, force_refresh=True
    )
    session_id = first_call["session_id"]
    assert session_id
    assert len(calls) == 1

    mod._invalidate_civitai_remote_collection_cache("78")
    with pytest.raises(RuntimeError, match="session expired"):
        mod._civitai_remote_get_collection_posts(
            "78", limit=40, page=2, session_id=session_id
        )
    assert len(calls) == 1


def test_civitai_remote_collection_rejects_multi_cursor_cycles(
    gallery_module, monkeypatch
):
    mod = gallery_module
    mod._invalidate_civitai_remote_collection_cache()
    monkeypatch.setattr(
        mod,
        "_civitai_remote_resolve_collection",
        lambda _ref="": {"id": 79, "name": "cycle-fixture", "type": "Image"},
    )
    batches = [
        (range(1, 11), "A"),
        (range(11, 21), "B"),
        (range(21, 31), "A"),
    ]
    calls = []

    class Response:
        status_code = 200
        text = "fixture"

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_trpc_get(_procedure, payload, **_kwargs):
        ids, next_cursor = batches[len(calls)]
        calls.append(payload.get("cursor"))
        return Response({"result": {"data": {"json": {
            "items": [
                {"id": item_id, "url": f"https://image.civitai.com/{item_id}.jpg"}
                for item_id in ids
            ],
            "nextCursor": next_cursor,
        }}}})

    monkeypatch.setattr(mod, "_civitai_trpc_get", fake_trpc_get)
    with pytest.raises(RuntimeError, match="repeated or cyclic cursor"):
        mod._civitai_remote_get_collection_posts(
            "79", limit=100, page=1, force_refresh=True
        )
    assert calls == [None, "A", "B"]


def test_civitai_remote_collection_commits_seen_ids_atomically(
    gallery_module, monkeypatch
):
    mod = gallery_module
    mod._invalidate_civitai_remote_collection_cache()
    monkeypatch.setattr(
        mod,
        "_civitai_remote_resolve_collection",
        lambda _ref="": {"id": 80, "name": "atomic-fixture", "type": "Image"},
    )

    class Response:
        status_code = 200
        text = "fixture"

        def json(self):
            return {"result": {"data": {"json": {
                "items": [
                    {"id": 1, "url": "https://image.civitai.com/1.jpg"},
                    {"id": 2, "url": "https://image.civitai.com/2.jpg"},
                ],
                "nextCursor": None,
            }}}}

    monkeypatch.setattr(mod, "_civitai_trpc_get", lambda *_args, **_kwargs: Response())
    original_normalize = mod._civitai_item_to_danbooru_shape
    failed_once = {"value": False}

    def flaky_normalize(item):
        if item.get("id") == 2 and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("fixture conversion failure")
        return original_normalize(item)

    monkeypatch.setattr(mod, "_civitai_item_to_danbooru_shape", flaky_normalize)
    with pytest.raises(RuntimeError, match="fixture conversion failure"):
        mod._civitai_remote_get_collection_posts(
            "80", limit=2, page=1, force_refresh=True
        )

    posts, _ = mod._civitai_remote_get_collection_posts("80", limit=2, page=1)
    assert [int(post["id"]) for post in posts] == [1, 2]


def test_civitai_filtered_remote_collection_scans_until_page_is_filled(
    gallery_module, monkeypatch
):
    mod = gallery_module
    monkeypatch.setattr(mod, "_civitai_extract_search_filters", lambda *_args, **_kwargs: {
        "favorite_mode": True,
        "remote_collection": "81",
        "local_terms": ["match"],
        "local_nsfw_filter": None,
        "strict_search": True,
    })
    monkeypatch.setattr(
        mod,
        "load_civitai_remote_favorites_settings",
        lambda: (True, "configured", "81", {"Cookie": "configured"}),
    )
    requested_pages = []
    all_posts = [
        {
            "id": item_id,
            "file_url": f"https://image.civitai.com/{item_id}.jpg",
            "tag_string": "match" if item_id % 2 == 0 else "other",
            "tag_string_general": "match" if item_id % 2 == 0 else "other",
            "rating": "general",
        }
        for item_id in range(200)
    ]

    def buffered_loader(_collection, _limit, page, force_refresh=False):
        requested_pages.append(page)
        count = 100 if page <= 2 else 200
        return all_posts[:count], {
            "local_pagination": True,
            "has_more": count < len(all_posts),
            "next_cursor": count < len(all_posts),
            "collectionId": 81,
        }

    monkeypatch.setattr(mod, "_civitai_remote_get_collection_posts", buffered_loader)
    page = json.loads(mod._get_civitai_images("fixture", limit=40, page=2))

    assert requested_pages == [2, 3]
    assert [item["id"] for item in page] == list(range(80, 160, 2))
    assert len(page) == 40


@pytest.mark.parametrize(
    ("strict_search", "expected_strategy"),
    [(True, "all"), (False, "last")],
)
def test_civitai_multisearch_maps_strict_and_loose_to_meilisearch_strategy(
    gallery_module, monkeypatch, strict_search, expected_strategy
):
    mod = gallery_module
    captured = {}

    class Response:
        status_code = 200
        text = "fixture"

        @staticmethod
        def json():
            return {"results": [{"hits": [], "estimatedTotalHits": 41}]}

    def fake_request(method, url, headers, throttle=None, **kwargs):
        captured.update({
            "method": method,
            "url": url,
            "headers": headers,
            "json": kwargs.get("json"),
        })
        return Response()

    monkeypatch.setattr(mod, "_civitai_multisearch_headers", lambda _query: {
        "Authorization": "Bearer configured",
    })
    monkeypatch.setattr(mod, "_request_with_headers", fake_request)

    posts, call = mod._civitai_multisearch_images(
        {
            "query_terms": ["red", "dress"],
            "local_terms": ["red", "dress"],
            "strict_search": strict_search,
            "params": {"sort": "Newest"},
        },
        limit=200,
        page=2,
    )

    query = captured["json"]["queries"][0]
    assert posts == []
    assert captured["method"] == "POST"
    assert captured["url"] == mod.CIVITAI_SEARCH_URL
    assert query["matchingStrategy"] == expected_strategy
    assert query["offset"] == 200
    assert query["limit"] == 200
    assert call["matching_strategy"] == expected_strategy
    assert call["estimated_total_hits"] == 41


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": []},
        {"results": [None]},
        {"results": [{}]},
        {"results": [{"hits": {}}]},
    ],
)
def test_civitai_multisearch_rejects_changed_response_shapes(
    gallery_module, monkeypatch, payload
):
    mod = gallery_module

    class Response:
        status_code = 200
        text = "fixture"

        def json(self):
            return payload

    monkeypatch.setattr(mod, "_civitai_multisearch_headers", lambda _query: {
        "Authorization": "Bearer configured",
    })
    monkeypatch.setattr(
        mod,
        "_request_with_headers",
        lambda *_args, **_kwargs: Response(),
    )

    with pytest.raises(mod.LegacyGalleryError) as raised:
        mod._civitai_multisearch_images(
            {
                "query_terms": ["portrait"],
                "strict_search": False,
                "params": {},
            },
            limit=20,
            page=1,
        )
    assert raised.value.code == "schema_changed"
