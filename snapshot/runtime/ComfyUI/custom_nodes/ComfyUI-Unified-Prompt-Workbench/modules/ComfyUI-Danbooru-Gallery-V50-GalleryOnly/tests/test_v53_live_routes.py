from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "py" / "danbooru_gallery"))

import v53  # noqa: E402
import v53.live_providers as live_providers  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = dict(headers or {})
        self.text = "fixture response"

    def json(self):
        return self._payload


class InvalidJsonResponse(FakeResponse):
    def json(self):
        raise ValueError("invalid fixture JSON")


class _FakeNode:
    @staticmethod
    def get_post_by_id_internal(post_id, source):
        return ('[{"id":"%s","source":"%s"}]' % (post_id, source),)


class FakeLegacy:
    DanbooruGalleryNode = _FakeNode

    def __init__(self):
        self.calls = []
        self.empty = False
        self.civitai_status = 200
        self.civitai_search_auth = ("", {})

    def load_user_auth(self):
        return "", ""

    def load_gelbooru_auth(self):
        return "", ""

    def load_civitai_auth(self):
        return ""

    def load_civitai_search_headers(self):
        return self.civitai_search_auth

    def load_favorites(self):
        return []

    def load_civitai_favorites(self):
        return []

    def _with_danbooru_auth_params(self, params):
        return dict(params)

    def _load_gelbooru_auth_params(self):
        return {}

    def _danbooru_request(self, method, url, **kwargs):
        self.calls.append(("danbooru", method, url, kwargs))
        if url.endswith("/tags.json"):
            payload = [] if self.empty else [{"name": "hakurei_reimu", "post_count": 100}]
        else:
            payload = [] if self.empty else [{
                "id": 1,
                **({"source": "https://artist.example/original"} if "/popular" in url else {}),
                "preview_file_url": "https://cdn.donmai.us/preview.jpg",
                "file_url": "https://cdn.donmai.us/file.jpg",
                "tag_string": "hakurei_reimu",
            }]
        return FakeResponse(payload)

    def _gelbooru_request(self, method, url, **kwargs):
        self.calls.append(("gelbooru", method, url, kwargs))
        params = kwargs.get("params") or {}
        if params.get("s") == "tag":
            payload = {"@attributes": {"count": 0}, "tag": []} if self.empty else {
                "tag": [{"name": "blue_hair", "count": 80}]
            }
        else:
            payload = {"@attributes": {"count": 0}, "post": []} if self.empty else {
                "post": [{"id": 2, "file_url": "https://img.gelbooru.com/2.jpg", "tags": "blue_hair"}]
            }
        return FakeResponse(payload)

    def _gelbooru_post_to_danbooru_shape(self, item):
        return {
            **item,
            "source": "gelbooru",
            "source_site": "gelbooru",
            "preview_file_url": item.get("file_url", ""),
            "large_file_url": item.get("file_url", ""),
        }

    def _yandere_request(self, method, url, **kwargs):
        self.calls.append(("yandere", method, url, kwargs))
        if url.endswith("/tag.json"):
            payload = [] if self.empty else [{"name": "long_hair", "count": 60, "type": 0}]
        elif url.endswith("/tag/related.json"):
            payload = [] if self.empty else [["long_hair", 60]]
        else:
            payload = [] if self.empty else [{"id": 3, "file_url": "https://files.yande.re/3.jpg", "tags": "long_hair"}]
        return FakeResponse(payload)

    def _yandere_post_to_danbooru_shape(self, item):
        return {
            **item,
            "source": "yandere",
            "source_site": "yandere",
            "preview_file_url": item.get("file_url", ""),
            "large_file_url": item.get("file_url", ""),
        }

    def _civitai_request(self, method, url, **kwargs):
        self.calls.append(("civitai", method, url, kwargs))
        if self.civitai_status != 200:
            return FakeResponse({}, self.civitai_status, {"Retry-After": "2"})
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "images":
            payload = {"items": [], "metadata": {}} if self.empty else {
                "items": [{"id": 4, "url": "https://image.civitai.com/4.jpg", "width": 512, "height": 768}],
                "metadata": {"nextCursor": "native-cursor-2"},
            }
        elif endpoint == "creators":
            payload = {"items": [] if self.empty else [{"username": "creator", "modelCount": 7}], "metadata": {}}
        elif endpoint == "tags":
            payload = {"items": [] if self.empty else [{"id": 9, "name": "portrait", "modelCount": 5}], "metadata": {}}
        else:
            payload = {"items": [] if self.empty else [{"id": 8, "name": "Model", "stats": {"downloadCount": 20}}], "metadata": {}}
        return FakeResponse(payload)

    def _civitai_item_to_danbooru_shape(self, item):
        return {
            "id": item.get("id"),
            "source": "civitai",
            "source_site": "civitai",
            "file_url": item.get("url", ""),
            "large_file_url": item.get("url", ""),
            "preview_file_url": item.get("url", ""),
        }


class FakeWebResponse:
    def __init__(self, payload, status, headers):
        self.payload = payload
        self.status = status
        self.headers = headers


class FakeWeb:
    @staticmethod
    def json_response(payload, status=200, headers=None):
        return FakeWebResponse(payload, status, dict(headers or {}))


class FakeRequest:
    def __init__(self, query, scenario=None, remote="127.0.0.1"):
        self.query = query
        self.headers = {} if scenario is None else {"X-Gallery-Test-Scenario": scenario}
        self.remote = remote


class FakeRoutes:
    def __init__(self):
        self.handlers = {}

    def get(self, path):
        def register(handler):
            self.handlers[path] = handler
            return handler

        return register


def _browse(source, view="latest", **overrides):
    raw = {
        "source": source,
        "view": view,
        "query": None,
        "metric": None,
        "period": None,
        "anchor_date": None,
        "facet_kind": None,
        "facet_id": None,
        "safety_profile": {
            "danbooru": "general",
            "gelbooru": "general",
            "yandere": "safe",
            "civitai": "general",
        }[source],
        "page_size": 20,
        "cursor": None,
        "allow_approx": False,
        "client_request_id": "00000000-0000-4000-8000-000000000001",
    }
    raw.update(overrides)
    raw["client_query_key"] = v53.browse_client_query_key(raw)
    return raw


def _ranking(source):
    if source == "danbooru":
        return _browse(source, "ranking", metric="popular", period="week", anchor_date="2026-07-19", safety_profile=None)
    if source == "gelbooru":
        return _browse(source, "ranking", metric="score", period="all_time")
    if source == "yandere":
        return _browse(source, "ranking", metric="score_period", period="week", anchor_date="2026-07-19")
    return _browse(source, "ranking", metric="reactions", period="week")


def _facet(source):
    kind = {
        "danbooru": "character",
        "gelbooru": "tag_cumulative",
        "yandere": "tag",
        "civitai": "model",
    }[source]
    raw = {
        "source": source,
        "facet_kind": kind,
        "query": "test",
        "page_size": 20,
        "cursor": None,
        "client_request_id": "00000000-0000-4000-8000-000000000002",
    }
    raw["client_query_key"] = v53.facet_client_query_key(raw)
    return raw


def _category(source):
    facet = _facet(source)
    return _browse(
        source,
        "category",
        facet_kind=facet["facet_kind"],
        facet_id="42" if source in ("civitai",) else "test_tag",
        safety_profile="general" if source == "civitai" else None,
    )


def _registry():
    legacy = FakeLegacy()
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef")
    return legacy, codec, v53.build_live_provider_registry(legacy, codec)


def test_registry_exposes_verified_yandere_and_conservative_civitai_capabilities():
    _, _, registry = _registry()
    yandere = registry.get("yandere").capabilities()
    assert yandere.view("ranking").state == v53.FeatureState.SUPPORTED
    assert yandere.ranking("score_period", "year").state == v53.FeatureState.SUPPORTED
    civitai = registry.get("civitai").capabilities()
    assert civitai.ranking("collected", "week").state == v53.FeatureState.PROVISIONAL
    assert civitai.view("search").state == v53.FeatureState.UNSUPPORTED
    assert civitai.facet("model_version").state == v53.FeatureState.UNSUPPORTED
    assert "https://civitai.red/api/v1 primary" in civitai.limits.notes[0]
    assert "https://civitai.com/api/v1 fallback" in civitai.limits.notes[0]


@pytest.mark.parametrize("source", ["danbooru", "gelbooru", "yandere", "civitai"])
def test_four_live_providers_latest_are_normalized_without_legacy_bare_arrays(source):
    legacy, codec, registry = _registry()
    provider = registry.get(source)
    request = v53.validate_browse_request(_browse(source), capabilities=provider.capabilities(), cursor_codec=codec)
    page = asyncio.run(provider.browse(request))
    assert len(page.items) == 1
    assert page.items[0]["source"] == source
    assert page.provenance["kind"] == "official_public_api"
    if source == "civitai":
        assert legacy.calls[-1][2].startswith("https://civitai.red/api/v1/")
        assert all(token not in legacy.calls[-1][2] for token in ("multi-search", "trpc"))
        assert page.provenance["endpoint"] == "civitai.red/api/v1/images"
        assert page.items[0]["civitai_api_base"] == "https://civitai.red"


def test_native_ranking_requests_use_site_specific_public_contracts():
    legacy, codec, registry = _registry()
    pages = {}
    for source in ("danbooru", "gelbooru", "yandere", "civitai"):
        provider = registry.get(source)
        raw = _ranking(source)
        request = v53.validate_browse_request(raw, capabilities=provider.capabilities(), cursor_codec=codec)
        page = asyncio.run(provider.browse(request))
        assert page.ranking is not None
        pages[source] = page

    dan_call, gel_call, yan_call, civ_call = legacy.calls
    assert pages["danbooru"].items[0]["source"] == "danbooru"
    assert pages["danbooru"].items[0]["source_site"] == "danbooru"
    assert dan_call[2].endswith("/explore/posts/popular.json")
    assert dan_call[3]["params"]["scale"] == "week"
    assert "sort:score:desc" in gel_call[3]["params"]["tags"]
    assert "date:2026-07-13..2026-07-19" in yan_call[3]["params"]["tags"]
    assert "order:score" in yan_call[3]["params"]["tags"]
    assert civ_call[2] == "https://civitai.red/api/v1/images"
    assert civ_call[3]["params"]["sort"] == "Most Reactions"
    assert civ_call[3]["params"]["period"] == "Week"


@pytest.mark.parametrize("profile", ["general", "sensitive"])
def test_gelbooru_safe_mapping_reports_effective_upstream_safety_and_warning(profile):
    legacy, codec, registry = _registry()
    provider = registry.get("gelbooru")
    raw = _browse("gelbooru", safety_profile=profile)
    request = v53.validate_browse_request(
        raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )

    page = asyncio.run(provider.browse(request))

    assert "rating:safe" in legacy.calls[-1][3]["params"]["tags"]
    assert page.applied["safetyProfile"] == profile
    assert page.applied["upstreamSafety"] == {"parameter": "rating", "value": "safe"}
    assert len(page.warnings) == 1
    assert page.warnings[0]["code"] == "safety_profile_degraded"
    assert page.warnings[0]["details"] == {
        "requestedSafetyProfile": profile,
        "effectiveUpstreamRating": "safe",
    }
    assert "cannot distinguish general from sensitive" in page.warnings[0]["message"]


@pytest.mark.parametrize("source", ["gelbooru", "yandere"])
def test_unimplemented_favorites_are_rejected_before_provider_fetch(source):
    legacy, codec, registry = _registry()
    provider = registry.get(source)
    raw = _browse(
        source,
        "favorites",
        metric=None,
        period=None,
        anchor_date=None,
        safety_profile=None,
    )

    with pytest.raises(v53.ContractValidationError) as caught:
        v53.validate_browse_request(
            raw, capabilities=provider.capabilities(), cursor_codec=codec,
        )

    assert caught.value.error.code == v53.ErrorCode.UNSUPPORTED
    assert legacy.calls == []


@pytest.mark.parametrize("source", ["danbooru", "civitai"])
def test_supported_local_favorites_do_not_claim_query_or_safety_was_applied(source):
    legacy, codec, registry = _registry()
    provider = registry.get(source)
    raw = _browse(
        source,
        "favorites",
        query=None,
        metric=None,
        period=None,
        anchor_date=None,
        safety_profile=None,
    )
    request = v53.validate_browse_request(
        raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )

    page = asyncio.run(provider.browse(request))

    assert page.provenance["kind"] == "local"
    assert "query" not in page.applied
    assert "safetyProfile" not in page.applied
    assert legacy.calls == []


def test_civitai_favorites_prefer_the_configured_remote_collection_and_paginate():
    legacy, codec, registry = _registry()
    remote_items = [
        {
            "id": item_id,
            "source": "civitai",
            "source_site": "civitai",
            "file_url": f"https://image.civitai.com/{item_id}.jpg",
        }
        for item_id in range(45)
    ]

    legacy.load_civitai_remote_favorites_settings = lambda: (
        False, "configured", "collection-id", {"Cookie": "configured"},
    )

    def remote_favorites(
        collection_id, limit, page, force_refresh=False, session_id=None
    ):
        legacy.calls.append((
            "civitai_favorites", collection_id, limit, page, force_refresh, session_id,
        ))
        return remote_items, {
            "label": "remote_collection",
            "local_pagination": True,
            "next_cursor": False,
            "session_id": "session-1",
            "collectionId": collection_id,
        }

    legacy._civitai_remote_get_collection_posts = remote_favorites
    provider = registry.get("civitai")
    raw = _browse(
        "civitai", "favorites", page_size=20, query=None, metric=None,
        period=None, anchor_date=None, safety_profile=None,
    )
    request = v53.validate_browse_request(raw, capabilities=provider.capabilities(), cursor_codec=codec)

    first = asyncio.run(provider.browse(request))
    assert [item["id"] for item in first.items] == list(range(20))
    assert first.next_cursor
    assert first.provenance["kind"] == "authenticated_remote"

    second_raw = dict(raw, cursor=first.next_cursor)
    second_raw["client_request_id"] = "00000000-0000-4000-8000-000000000003"
    second = asyncio.run(provider.browse(v53.validate_browse_request(
        second_raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))
    assert [item["id"] for item in second.items] == list(range(20, 40))
    assert second.next_cursor

    third_raw = dict(raw, cursor=second.next_cursor)
    third_raw["client_request_id"] = "00000000-0000-4000-8000-000000000004"
    third = asyncio.run(provider.browse(v53.validate_browse_request(
        third_raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))
    assert [item["id"] for item in third.items] == list(range(40, 45))
    assert third.next_cursor is None
    assert legacy.calls == [
        ("civitai_favorites", "collection-id", 20, 1, True, None),
        ("civitai_favorites", "collection-id", 20, 2, False, "session-1"),
        ("civitai_favorites", "collection-id", 20, 3, False, "session-1"),
    ]


def test_civitai_local_window_keeps_next_page_at_exact_buffer_boundary():
    legacy, codec, registry = _registry()
    legacy.load_civitai_remote_favorites_settings = lambda: (
        True, "configured", "collection-id", {"Cookie": "configured"},
    )

    def buffered_remote(
        collection_id, limit, page, force_refresh=False, session_id=None
    ):
        buffered_count = 200 if page <= 5 else 250
        return [
            {"id": item_id, "source": "civitai", "source_site": "civitai"}
            for item_id in range(buffered_count)
        ], {
            "label": "remote_collection_buffer",
            "local_pagination": True,
            "next_cursor": page <= 5,
            "has_more": page <= 5,
            "session_id": "buffer-session",
            "collectionId": collection_id,
        }

    legacy._civitai_remote_get_collection_posts = buffered_remote
    provider = registry.get("civitai")
    raw = _browse(
        "civitai", "favorites", page_size=40, query=None, metric=None,
        period=None, anchor_date=None, safety_profile=None,
    )
    page = asyncio.run(provider.browse(v53.validate_browse_request(
        raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))
    delivered = list(page.items)
    for request_number in range(2, 8):
        assert page.next_cursor
        next_raw = dict(raw, cursor=page.next_cursor)
        next_raw["client_request_id"] = f"00000000-0000-4000-8000-{request_number:012d}"
        page = asyncio.run(provider.browse(v53.validate_browse_request(
            next_raw, capabilities=provider.capabilities(), cursor_codec=codec,
        )))
        delivered.extend(page.items)

    assert [item["id"] for item in delivered] == list(range(250))
    assert page.next_cursor is None


def test_civitai_successful_empty_remote_collection_does_not_restore_stale_local_items():
    legacy, codec, registry = _registry()
    legacy.load_civitai_favorites = lambda: [
        {"id": "stale-local", "source": "civitai", "source_site": "civitai"},
    ]
    legacy.load_civitai_remote_favorites_settings = lambda: (
        True, "configured", "collection-id", {"Cookie": "configured"},
    )
    legacy._civitai_remote_get_collection_posts = lambda *args, **kwargs: (
        [], {"label": "remote_collection", "local_pagination": True, "next_cursor": False},
    )
    provider = registry.get("civitai")
    raw = _browse(
        "civitai", "favorites", query=None, metric=None, period=None,
        anchor_date=None, safety_profile=None,
    )
    page = asyncio.run(provider.browse(v53.validate_browse_request(
        raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))

    assert page.items == ()
    assert page.provenance["kind"] == "authenticated_remote"


def test_civitai_remote_favorites_failure_falls_back_to_local_snapshot():
    legacy, codec, registry = _registry()
    local_items = [{
        "id": "local-1",
        "source": "civitai",
        "source_site": "civitai",
        "file_url": "https://image.civitai.com/local-1.jpg",
    }]
    legacy.load_civitai_favorites = lambda: local_items
    legacy.load_civitai_remote_favorites_settings = lambda: (
        True, "configured", "collection-id", {"Cookie": "configured"},
    )

    def unavailable_remote(*args, **kwargs):
        raise RuntimeError("remote unavailable")

    legacy._civitai_remote_get_collection_posts = unavailable_remote
    provider = registry.get("civitai")
    raw = _browse(
        "civitai", "favorites", query=None, metric=None, period=None,
        anchor_date=None, safety_profile=None,
    )
    request = v53.validate_browse_request(raw, capabilities=provider.capabilities(), cursor_codec=codec)

    page = asyncio.run(provider.browse(request))

    assert [item["id"] for item in page.items] == ["local-1"]
    assert page.provenance["kind"] == "local"
    assert page.provenance["fallbackFrom"] == "civitai_remote_collection"
    assert page.warnings[0]["code"] == "remote_favorites_fallback_local"


def test_civitai_local_fallback_chain_does_not_switch_back_to_remote():
    legacy, codec, registry = _registry()
    local_items = [
        {"id": f"local-{item_id}", "source": "civitai", "source_site": "civitai"}
        for item_id in range(45)
    ]
    legacy.load_civitai_favorites = lambda: local_items
    legacy.load_civitai_remote_favorites_settings = lambda: (
        True, "configured", "collection-id", {"Cookie": "configured"},
    )
    remote_calls = []

    def recovering_remote(*_args, **_kwargs):
        remote_calls.append(1)
        if len(remote_calls) == 1:
            raise RuntimeError("temporary remote failure")
        return ([
            {"id": f"remote-{item_id}", "source": "civitai", "source_site": "civitai"}
            for item_id in range(45)
        ], {
            "local_pagination": True,
            "has_more": False,
            "session_id": "should-not-be-used",
            "collectionId": "collection-id",
        })

    legacy._civitai_remote_get_collection_posts = recovering_remote
    provider = registry.get("civitai")
    raw = _browse(
        "civitai", "favorites", page_size=20, query=None, metric=None,
        period=None, anchor_date=None, safety_profile=None,
    )
    first = asyncio.run(provider.browse(v53.validate_browse_request(
        raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))
    assert [item["id"] for item in first.items] == [f"local-{i}" for i in range(20)]
    assert first.next_cursor

    second_raw = dict(raw, cursor=first.next_cursor)
    second_raw["client_request_id"] = "00000000-0000-4000-8000-000000000007"
    second = asyncio.run(provider.browse(v53.validate_browse_request(
        second_raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))

    assert [item["id"] for item in second.items] == [f"local-{i}" for i in range(20, 40)]
    assert second.provenance["kind"] == "local"
    assert second.provenance["fallbackFrom"] == "civitai_remote_collection"
    assert len(remote_calls) == 1


def test_civitai_cursor_backed_final_page_is_not_sliced_as_a_full_collection():
    legacy, codec, registry = _registry()
    legacy.load_civitai_remote_favorites_settings = lambda: (
        True, "configured", "collection-id", {"Cookie": "configured"},
    )

    def cursor_pages(
        collection_id, limit, page, force_refresh=False, session_id=None
    ):
        start = (page - 1) * limit
        count = limit if page == 1 else 5
        items = [
            {"id": item_id, "source": "civitai", "source_site": "civitai"}
            for item_id in range(start, start + count)
        ]
        return items, {
            "label": "remote_collection",
            "local_pagination": False,
            "next_cursor": page == 1,
            "session_id": "cursor-session",
            "collectionId": collection_id,
        }

    legacy._civitai_remote_get_collection_posts = cursor_pages
    provider = registry.get("civitai")
    raw = _browse(
        "civitai", "favorites", page_size=20, query=None, metric=None,
        period=None, anchor_date=None, safety_profile=None,
    )
    first = asyncio.run(provider.browse(v53.validate_browse_request(
        raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))
    second_raw = dict(raw, cursor=first.next_cursor)
    second_raw["client_request_id"] = "00000000-0000-4000-8000-000000000005"
    second = asyncio.run(provider.browse(v53.validate_browse_request(
        second_raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))

    assert [item["id"] for item in second.items] == list(range(20, 25))
    assert second.next_cursor is None


def test_civitai_second_page_remote_failure_does_not_mix_in_local_snapshot():
    legacy, codec, registry = _registry()
    local_items = [
        {"id": f"local-{item_id}", "source": "civitai", "source_site": "civitai"}
        for item_id in range(45)
    ]
    legacy.load_civitai_favorites = lambda: local_items
    legacy.load_civitai_remote_favorites_settings = lambda: (
        True, "configured", "collection-id", {"Cookie": "configured"},
    )

    def remote_then_fail(
        collection_id, limit, page, force_refresh=False, session_id=None
    ):
        if page > 1:
            raise RuntimeError("remote unavailable")
        return [
            {"id": item_id, "source": "civitai", "source_site": "civitai"}
            for item_id in range(limit)
        ], {
            "label": "remote_collection",
            "local_pagination": False,
            "next_cursor": True,
            "session_id": "failure-session",
            "collectionId": collection_id,
        }

    legacy._civitai_remote_get_collection_posts = remote_then_fail
    provider = registry.get("civitai")
    raw = _browse(
        "civitai", "favorites", page_size=20, query=None, metric=None,
        period=None, anchor_date=None, safety_profile=None,
    )
    first = asyncio.run(provider.browse(v53.validate_browse_request(
        raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))
    second_raw = dict(raw, cursor=first.next_cursor)
    second_raw["client_request_id"] = "00000000-0000-4000-8000-000000000006"
    with pytest.raises(RuntimeError, match="civitai browse failed"):
        asyncio.run(provider.browse(v53.validate_browse_request(
            second_raw, capabilities=provider.capabilities(), cursor_codec=codec,
        )))


@pytest.mark.parametrize("source", ["danbooru", "gelbooru", "yandere"])
def test_public_booru_search_views_forward_the_normalized_query(source):
    legacy, codec, registry = _registry()
    provider = registry.get(source)
    raw = _browse(source, "search", query="blue_hair")
    request = v53.validate_browse_request(raw, capabilities=provider.capabilities(), cursor_codec=codec)
    page = asyncio.run(provider.browse(request))
    assert page.items
    assert "blue_hair" in legacy.calls[-1][3]["params"]["tags"]


def test_civitai_free_text_search_requires_search_authorization():
    _, codec, registry = _registry()
    provider = registry.get("civitai")
    raw = _browse("civitai", "search", query="portrait")
    with pytest.raises(v53.ContractValidationError) as caught:
        v53.validate_browse_request(raw, capabilities=provider.capabilities(), cursor_codec=codec)
    assert caught.value.error.code == v53.ErrorCode.UNSUPPORTED


def test_civitai_authenticated_free_text_search_uses_web_index_and_paginates():
    legacy, codec, registry = _registry()
    legacy.civitai_search_auth = (
        "configured",
        {"Authorization": "Bearer fixture-search-token"},
    )
    search_calls = []

    def build_plan(query, rating=None):
        return {
            "query_terms": query.split(),
            "local_terms": query.split(),
            "strict_search": len(query.split()) > 1,
            "favorite_mode": False,
            "params": {"sort": "Newest"},
        }

    def search_images(plan, limit, page):
        search_calls.append((tuple(plan["query_terms"]), limit, page))
        start = (page - 1) * limit
        count = min(limit, max(0, 45 - start))
        return [
            {
                "id": start + index,
                "source": "civitai",
                "source_site": "civitai",
                "file_url": f"https://image.civitai.com/{start + index}.jpg",
            }
            for index in range(count)
        ], {
            "raw_hits": count,
            "estimated_total_hits": 45,
            "offset": start,
        }

    legacy._civitai_extract_search_filters = build_plan
    legacy._civitai_multisearch_images = search_images
    provider = registry.get("civitai")
    assert provider.capabilities().view("search").state == v53.FeatureState.SUPPORTED

    raw = _browse(
        "civitai", "search", page_size=20, query="blue hair", metric=None,
        period=None, anchor_date=None, safety_profile=None,
    )
    first = asyncio.run(provider.browse(v53.validate_browse_request(
        raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))
    assert [item["id"] for item in first.items] == list(range(20))
    assert first.next_cursor
    assert first.provenance == {
        "kind": "authenticated_web_search",
        "endpoint": "search-new.civitai.com/multi-search",
    }
    assert first.applied["matchingStrategy"] == "all"

    second_raw = dict(raw, cursor=first.next_cursor)
    second_raw["client_request_id"] = "00000000-0000-4000-8000-000000000008"
    second = asyncio.run(provider.browse(v53.validate_browse_request(
        second_raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))
    assert [item["id"] for item in second.items] == list(range(20, 40))
    assert second.next_cursor
    assert search_calls == [(('blue', 'hair'), 20, 1), (('blue', 'hair'), 20, 2)]


def test_civitai_search_honors_declared_200_item_page_size_without_data_loss():
    legacy, codec, registry = _registry()
    legacy.civitai_search_auth = (
        "configured",
        {"Authorization": "Bearer fixture-search-token"},
    )
    search_calls = []

    legacy._civitai_extract_search_filters = lambda query, rating=None: {
        "query_terms": query.split(),
        "local_terms": query.split(),
        "strict_search": False,
        "favorite_mode": False,
        "params": {"sort": "Newest"},
    }

    def search_images(_plan, limit, page):
        search_calls.append((limit, page))
        start = (page - 1) * limit
        count = min(limit, max(0, 250 - start))
        return [
            {
                "id": start + index,
                "source": "civitai",
                "source_site": "civitai",
                "file_url": f"https://image.civitai.com/{start + index}.jpg",
            }
            for index in range(count)
        ], {
            "raw_hits": count,
            "estimated_total_hits": 250,
            "offset": start,
        }

    legacy._civitai_multisearch_images = search_images
    provider = registry.get("civitai")
    raw = _browse(
        "civitai", "search", page_size=200, query="portrait", metric=None,
        period=None, anchor_date=None, safety_profile=None,
    )
    first = asyncio.run(provider.browse(v53.validate_browse_request(
        raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))
    second_raw = dict(raw, cursor=first.next_cursor)
    second_raw["client_request_id"] = "00000000-0000-4000-8000-000000000009"
    second = asyncio.run(provider.browse(v53.validate_browse_request(
        second_raw, capabilities=provider.capabilities(), cursor_codec=codec,
    )))

    assert [item["id"] for item in first.items] == list(range(200))
    assert [item["id"] for item in second.items] == list(range(200, 250))
    assert second.next_cursor is None
    assert search_calls == [(200, 1), (200, 2)]


@pytest.mark.parametrize("source", ["danbooru", "gelbooru", "yandere", "civitai"])
def test_four_provider_facets_use_public_endpoints(source):
    legacy, codec, registry = _registry()
    provider = registry.get(source)
    request = v53.validate_facet_request(_facet(source), capabilities=provider.capabilities(), cursor_codec=codec)
    page = asyncio.run(provider.list_facets(request))
    assert page.items and page.items[0]["kind"] == request.facet_kind
    url = legacy.calls[-1][2]
    assert {
        "danbooru": "/tags.json",
        "gelbooru": "/index.php",
        "yandere": "/tag.json",
        "civitai": "/api/v1/models",
    }[source] in url


@pytest.mark.parametrize("failure_mode", ["network", "http", "invalid_json", "invalid_shape"])
def test_civitai_public_api_falls_back_to_blue_origin_and_reports_actual_endpoint(failure_mode):
    class RedFailureLegacy(FakeLegacy):
        def _civitai_request(self, method, url, **kwargs):
            if url.startswith("https://civitai.red/"):
                self.calls.append(("civitai", method, url, kwargs))
                if failure_mode == "network":
                    raise ConnectionError("red fixture unavailable")
                if failure_mode == "http":
                    return FakeResponse({}, status=503, headers={"Retry-After": "2"})
                if failure_mode == "invalid_json":
                    return InvalidJsonResponse(None)
                return FakeResponse({"unexpected": []})
            return super()._civitai_request(method, url, **kwargs)

    legacy = RedFailureLegacy()
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef")
    provider = v53.CivitaiLiveProvider(legacy, codec)
    request = v53.validate_browse_request(
        _browse("civitai"), capabilities=provider.capabilities(), cursor_codec=codec,
    )

    page = asyncio.run(provider.browse(request))

    assert [call[2] for call in legacy.calls] == [
        "https://civitai.red/api/v1/images",
        "https://civitai.com/api/v1/images",
    ]
    assert page.provenance == {
        "kind": "official_public_api",
        "endpoint": "civitai.com/api/v1/images",
        "fallbackFrom": "civitai.red/api/v1/images",
    }
    assert page.items[0]["civitai_api_base"] == "https://civitai.com"


def test_civitai_public_origin_is_request_local_under_concurrency():
    class ConcurrentOriginsLegacy(FakeLegacy):
        def _civitai_request(self, method, url, **kwargs):
            params = kwargs.get("params") or {}
            model_id = str(params.get("modelId") or "")
            self.calls.append(("civitai", method, url, kwargs))
            if model_id == "blue" and url.startswith("https://civitai.red/"):
                return FakeResponse({}, status=503)
            origin = "red" if url.startswith("https://civitai.red/") else "blue"
            return FakeResponse({
                "items": [{
                    "id": f"{model_id}-{origin}",
                    "url": f"https://image.civitai.com/{model_id}-{origin}.jpg",
                    "width": 512,
                    "height": 768,
                }],
                "metadata": {},
            })

    legacy = ConcurrentOriginsLegacy()
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef")
    provider = v53.CivitaiLiveProvider(legacy, codec)

    def category_request(model_id, request_id):
        raw = _browse(
            "civitai",
            "category",
            facet_kind="model",
            facet_id=model_id,
            safety_profile="general",
            client_request_id=request_id,
        )
        raw["client_query_key"] = v53.browse_client_query_key(raw)
        return v53.validate_browse_request(
            raw, capabilities=provider.capabilities(), cursor_codec=codec,
        )

    async def run_both():
        return await asyncio.gather(
            provider.browse(category_request("red", "00000000-0000-4000-8000-000000000010")),
            provider.browse(category_request("blue", "00000000-0000-4000-8000-000000000011")),
        )

    red_page, blue_page = asyncio.run(run_both())

    assert red_page.provenance["endpoint"] == "civitai.red/api/v1/images"
    assert red_page.items[0]["civitai_api_base"] == "https://civitai.red"
    assert blue_page.provenance["endpoint"] == "civitai.com/api/v1/images"
    assert blue_page.provenance["fallbackFrom"] == "civitai.red/api/v1/images"
    assert blue_page.items[0]["civitai_api_base"] == "https://civitai.com"


def test_civitai_follows_native_next_cursor_and_maps_deep_429():
    legacy, codec, registry = _registry()
    provider = registry.get("civitai")
    first_raw = _ranking("civitai")
    first = v53.validate_browse_request(first_raw, capabilities=provider.capabilities(), cursor_codec=codec)
    first_page = asyncio.run(provider.browse(first))
    assert first_page.next_cursor
    second_raw = dict(first_raw, cursor=first_page.next_cursor)
    second = v53.validate_browse_request(second_raw, capabilities=provider.capabilities(), cursor_codec=codec)
    legacy.civitai_status = 429
    with pytest.raises(v53.ProviderRequestError) as caught:
        asyncio.run(provider.browse(second))
    assert caught.value.error.code == v53.ErrorCode.PAGINATION_LIMIT
    assert caught.value.error.retryable is False


def test_real_empty_upstream_is_a_successful_empty_provider_page():
    legacy, codec, registry = _registry()
    legacy.empty = True
    for source in ("danbooru", "gelbooru", "yandere", "civitai"):
        provider = registry.get(source)
        request = v53.validate_browse_request(_browse(source), capabilities=provider.capabilities(), cursor_codec=codec)
        page = asyncio.run(provider.browse(request))
        assert page.items == ()


def test_fixture_routes_cover_all_sites_and_modes_without_network(monkeypatch):
    monkeypatch.setenv("DANBOORU_GALLERY_TEST_FIXTURES", "1")
    legacy, codec, registry = _registry()
    handlers = v53.create_v2_handlers(registry, codec, web_module=FakeWeb)
    for source in ("danbooru", "gelbooru", "yandere", "civitai"):
        for raw in (_browse(source), _ranking(source), _category(source)):
            response = asyncio.run(handlers[v53.V2_API_ROOT + "/browse"](FakeRequest(raw, "success")))
            assert response.status == 200
            assert response.payload["error"] is None
            assert response.payload["items"]
            fixture_item = response.payload["items"][0]
            assert fixture_item["file_ext"] == "png"
            assert fixture_item["preview_file_url"].startswith("data:image/png;base64,")
        response = asyncio.run(handlers[v53.V2_API_ROOT + "/facets"](FakeRequest(_facet(source), "success")))
        assert response.status == 200
        assert response.payload["error"] is None
        assert response.payload["items"]
    assert legacy.calls == []


def test_fixture_error_envelope_and_retry_after_are_stable(monkeypatch):
    monkeypatch.setenv("DANBOORU_GALLERY_TEST_FIXTURES", "true")
    _, codec, registry = _registry()
    handlers = v53.create_v2_handlers(registry, codec, web_module=FakeWeb)
    response = asyncio.run(
        handlers[v53.V2_API_ROOT + "/browse"](FakeRequest(_browse("civitai"), "429"))
    )
    assert response.status == 429
    assert response.headers["Retry-After"] == "2"
    assert response.payload["items"] == []
    assert response.payload["pageInfo"]["hasNext"] is None
    assert response.payload["error"]["code"] == "rate_limited"


def test_fixture_mode_fails_closed_for_non_loopback_clients(monkeypatch):
    monkeypatch.setenv("DANBOORU_GALLERY_TEST_FIXTURES", "1")
    legacy, codec, registry = _registry()
    handlers = v53.create_v2_handlers(registry, codec, web_module=FakeWeb)
    response = asyncio.run(
        handlers[v53.V2_API_ROOT + "/browse"](
            FakeRequest(_browse("danbooru"), "success", remote="192.0.2.10")
        )
    )
    assert response.status == 403
    assert response.payload["error"]["code"] == "forbidden"
    assert legacy.calls == []


def test_fixture_autocomplete_is_successful_without_network(monkeypatch):
    monkeypatch.setenv("DANBOORU_GALLERY_TEST_FIXTURES", "1")
    legacy, codec, registry = _registry()
    handlers = v53.create_v2_handlers(registry, codec, web_module=FakeWeb)
    raw = {
        "source": "danbooru",
        "query": "haku",
        "facet_kind": "character",
        "page_size": 20,
        "client_request_id": "00000000-0000-4000-8000-000000000003",
    }
    raw["client_query_key"] = v53.autocomplete_client_query_key(raw)
    response = asyncio.run(
        handlers[v53.V2_API_ROOT + "/autocomplete"](FakeRequest(raw, "success"))
    )
    assert response.status == 200
    assert response.payload["items"]
    assert response.payload["error"] is None
    assert legacy.calls == []


def test_non_fixture_route_preserves_successful_empty_result(monkeypatch):
    monkeypatch.delenv("DANBOORU_GALLERY_TEST_FIXTURES", raising=False)
    legacy, codec, registry = _registry()
    legacy.empty = True
    handlers = v53.create_v2_handlers(registry, codec, web_module=FakeWeb)
    response = asyncio.run(
        handlers[v53.V2_API_ROOT + "/browse"](FakeRequest(_browse("civitai")))
    )
    assert response.status == 200
    assert response.payload["items"] == []
    assert response.payload["error"] is None
    assert legacy.calls and legacy.calls[-1][2] == "https://civitai.red/api/v1/images"


class BlockingDanbooruLegacy(FakeLegacy):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.thread_names = []

    def _danbooru_request(self, method, url, **kwargs):
        self.calls.append(("danbooru", method, url, kwargs))
        self.thread_names.append(threading.current_thread().name)
        self.started.set()
        if not self.release.wait(timeout=3):
            raise TimeoutError("test worker was not released")
        return FakeResponse([{
            "id": 1,
            "preview_file_url": "https://cdn.donmai.us/preview.jpg",
            "file_url": "https://cdn.donmai.us/file.jpg",
            "tag_string": "hakurei_reimu",
        }])


async def _wait_until_started(event):
    for _ in range(200):
        if event.is_set():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("provider worker did not start")


def test_identical_browse_requests_share_one_dedicated_worker(monkeypatch):
    legacy = BlockingDanbooruLegacy()
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef")
    provider = v53.DanbooruLiveProvider(legacy, codec)
    request = v53.validate_browse_request(
        _browse("danbooru"), capabilities=provider.capabilities(), cursor_codec=codec,
    )
    monkeypatch.setattr(
        live_providers, "_PROVIDER_EXECUTOR_BUDGET", threading.BoundedSemaphore(1),
    )

    async def scenario():
        first = asyncio.create_task(provider.browse(request))
        try:
            await _wait_until_started(legacy.started)
            second = asyncio.create_task(provider.browse(request))
            await asyncio.sleep(0.02)
            legacy.release.set()
            return await asyncio.gather(first, second)
        finally:
            legacy.release.set()

    first_page, second_page = asyncio.run(scenario())

    assert len(legacy.calls) == 1
    assert first_page is second_page
    assert legacy.thread_names[0].startswith("danbooru-gallery-v53")


def test_successful_browse_result_has_short_ttl_cache(monkeypatch):
    legacy, codec, registry = _registry()
    provider = registry.get("danbooru")
    request = v53.validate_browse_request(
        _browse("danbooru"), capabilities=provider.capabilities(), cursor_codec=codec,
    )
    monkeypatch.setattr(live_providers, "_PROVIDER_SUCCESS_CACHE_TTL_SECONDS", 0.02)

    first = asyncio.run(provider.browse(request))
    second = asyncio.run(provider.browse(request))
    assert first is second
    assert len(legacy.calls) == 1

    time.sleep(0.04)
    third = asyncio.run(provider.browse(request))
    assert third is not first
    assert len(legacy.calls) == 2


def test_facet_and_autocomplete_successes_use_separate_cache_keys():
    legacy, codec, registry = _registry()
    provider = registry.get("danbooru")
    facet_request = v53.validate_facet_request(
        _facet("danbooru"), capabilities=provider.capabilities(), cursor_codec=codec,
    )
    autocomplete_raw = {
        "source": "danbooru",
        "query": "haku",
        "facet_kind": "character",
        "page_size": 20,
        "client_request_id": "00000000-0000-4000-8000-000000000004",
    }
    autocomplete_raw["client_query_key"] = v53.autocomplete_client_query_key(
        autocomplete_raw
    )
    autocomplete_request = v53.validate_autocomplete_request(
        autocomplete_raw, capabilities=provider.capabilities(),
    )

    first_facets = asyncio.run(provider.list_facets(facet_request))
    second_facets = asyncio.run(provider.list_facets(facet_request))
    first_suggestions = asyncio.run(provider.autocomplete(autocomplete_request))
    second_suggestions = asyncio.run(provider.autocomplete(autocomplete_request))

    assert first_facets is second_facets
    assert first_suggestions is second_suggestions
    assert len(legacy.calls) == 2
    assert {key[0] for key in provider._success_cache} == {"facets", "autocomplete"}


def test_success_cache_is_lru_bounded(monkeypatch):
    legacy, codec, registry = _registry()
    provider = registry.get("danbooru")
    monkeypatch.setattr(live_providers, "_PROVIDER_SUCCESS_CACHE_TTL_SECONDS", 60.0)
    monkeypatch.setattr(live_providers, "_PROVIDER_SUCCESS_CACHE_MAX_ENTRIES", 2)
    requests = [
        v53.validate_browse_request(
            _browse("danbooru", query=query),
            capabilities=provider.capabilities(),
            cursor_codec=codec,
        )
        for query in ("one", "two", "three")
    ]

    for request in requests:
        asyncio.run(provider.browse(request))
    assert len(provider._success_cache) == 2
    assert len(legacy.calls) == 3

    # "one" is the least-recently-used entry and was evicted; "three" remains.
    asyncio.run(provider.browse(requests[0]))
    asyncio.run(provider.browse(requests[2]))
    assert len(provider._success_cache) == 2
    assert len(legacy.calls) == 4


def test_failed_request_is_not_cached_but_following_success_is():
    class FailOnceLegacy(FakeLegacy):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def _danbooru_request(self, method, url, **kwargs):
            self.attempts += 1
            self.calls.append(("danbooru", method, url, kwargs))
            if self.attempts == 1:
                raise ConnectionError("fixture connection failure")
            return FakeResponse([{"id": 1}])

    legacy = FailOnceLegacy()
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef")
    provider = v53.DanbooruLiveProvider(legacy, codec)
    request = v53.validate_browse_request(
        _browse("danbooru"), capabilities=provider.capabilities(), cursor_codec=codec,
    )

    with pytest.raises(v53.ProviderRequestError) as caught:
        asyncio.run(provider.browse(request))
    assert caught.value.error.code == v53.ErrorCode.NETWORK_UNAVAILABLE

    success = asyncio.run(provider.browse(request))
    cached = asyncio.run(provider.browse(request))
    assert success is cached
    assert legacy.attempts == 2


def test_authenticated_provider_disables_ttl_cache():
    class AuthenticatedLegacy(FakeLegacy):
        def load_user_auth(self):
            return "configured-user", "configured-api-key"

    legacy = AuthenticatedLegacy()
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef")
    provider = v53.DanbooruLiveProvider(legacy, codec)
    request = v53.validate_browse_request(
        _browse("danbooru"), capabilities=provider.capabilities(), cursor_codec=codec,
    )

    first = asyncio.run(provider.browse(request))
    second = asyncio.run(provider.browse(request))

    assert first is not second
    assert len(legacy.calls) == 2
    assert provider._success_cache == {}


def test_distinct_request_is_rejected_immediately_when_worker_budget_is_full(monkeypatch):
    legacy = BlockingDanbooruLegacy()
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef")
    provider = v53.DanbooruLiveProvider(legacy, codec)
    first_request = v53.validate_browse_request(
        _browse("danbooru", query="first"),
        capabilities=provider.capabilities(),
        cursor_codec=codec,
    )
    second_request = v53.validate_browse_request(
        _browse("danbooru", query="second"),
        capabilities=provider.capabilities(),
        cursor_codec=codec,
    )
    monkeypatch.setattr(
        live_providers, "_PROVIDER_EXECUTOR_BUDGET", threading.BoundedSemaphore(1),
    )

    async def scenario():
        first = asyncio.create_task(provider.browse(first_request))
        try:
            await _wait_until_started(legacy.started)
            with pytest.raises(v53.ProviderRequestError) as caught:
                await asyncio.wait_for(provider.browse(second_request), timeout=0.2)
            assert caught.value.error.code == v53.ErrorCode.UPSTREAM_BUSY
            assert caught.value.error.http_status == 503
            assert caught.value.error.retryable is True
            assert caught.value.error.retry_after_seconds == 1.0
        finally:
            legacy.release.set()
            await first

    asyncio.run(scenario())

    assert len(legacy.calls) == 1


def test_providers_route_and_registration_expose_all_four_get_paths(monkeypatch):
    monkeypatch.setenv("DANBOORU_GALLERY_TEST_FIXTURES", "1")
    legacy, codec, registry = _registry()
    handlers = v53.create_v2_handlers(registry, codec, web_module=FakeWeb)
    all_response = asyncio.run(handlers[v53.V2_API_ROOT + "/providers"](FakeRequest({})))
    assert all_response.status == 200
    assert [item["source"] for item in all_response.payload["providers"]] == [
        "danbooru",
        "gelbooru",
        "yandere",
        "civitai",
    ]
    one_response = asyncio.run(
        handlers[v53.V2_API_ROOT + "/providers"](FakeRequest({"source": "yandere"}))
    )
    assert one_response.payload["source"] == "yandere"
    ranking = next(item for item in one_response.payload["features"]["ranking"] if item["metric"] == "score_period")
    assert ranking["state"] == "supported"

    routes = FakeRoutes()
    v53.register_v2_routes(
        routes,
        legacy,
        cursor_codec=codec,
        registry=registry,
        web_module=FakeWeb,
    )
    assert set(routes.handlers) == {
        v53.V2_API_ROOT + "/providers",
        v53.V2_API_ROOT + "/browse",
        v53.V2_API_ROOT + "/facets",
        v53.V2_API_ROOT + "/autocomplete",
    }
