from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "py" / "danbooru_gallery"))

import v53  # noqa: E402


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
    def __init__(self, query=None):
        self.query = query or {}
        self.headers = {}
        self.remote = "127.0.0.1"


class FakeRoutes:
    def __init__(self):
        self.handlers = {}

    def get(self, path):
        def register(handler):
            self.handlers[path] = handler
            return handler

        return register


class _Legacy:
    def load_user_auth(self):
        return "", ""

    def load_gelbooru_auth(self):
        return "", ""

    def load_civitai_auth(self):
        return ""

    def _load_gelbooru_auth_params(self):
        return {}


def _runtime_plugin(tmp_path: Path) -> Path:
    root = tmp_path / "plugin"
    (root / "tests" / ".runtime" / "case").mkdir(parents=True)
    return root


def test_feature_flag_defaults_are_stable_and_experimental_paths_are_closed(tmp_path):
    root = _runtime_plugin(tmp_path)
    flags = v53.load_v53_feature_flags(plugin_root=root, environ={})
    assert flags.v2_routes_enabled is True
    assert flags.gallery_new_ui_enabled is True
    assert flags.provider_enabled("danbooru") is True
    assert flags.gelbooru_approx_rank_enabled is False
    assert flags.civitai_experimental_web is False


def test_invalid_rollout_combinations_fail_closed():
    with pytest.raises(v53.FeatureFlagConfigurationError, match="gallery_new_ui"):
        v53.V53FeatureFlags(
            v2_routes_enabled=False,
            gallery_new_ui_enabled=True,
            provider_danbooru_v2=False,
            provider_gelbooru_v2=False,
            provider_yandere_v2=False,
            provider_civitai_v2=False,
        ).validate()
    with pytest.raises(v53.FeatureFlagConfigurationError, match="gelbooru_approx"):
        v53.V53FeatureFlags(
            provider_gelbooru_v2=False,
            gelbooru_approx_rank_enabled=True,
        ).validate()


def test_delivery_config_requires_guard_and_is_confined_to_runtime(tmp_path):
    root = _runtime_plugin(tmp_path)
    config_path = root / "tests" / ".runtime" / "case" / "test-config.json"
    config_path.write_text(json.dumps({
        "schemaVersion": 1,
        "featureFlags": {
            "gallery_new_ui_enabled": False,
            "provider_gelbooru_v2": False,
        },
    }), encoding="utf-8")

    ignored = v53.load_v53_feature_flags(
        plugin_root=root,
        environ={"DANBOORU_GALLERY_TEST_CONFIG": str(config_path)},
    )
    assert ignored.gallery_new_ui_enabled is True

    loaded = v53.load_v53_feature_flags(
        plugin_root=root,
        environ={
            "DANBOORU_GALLERY_DELIVERY_TEST": "1",
            "DANBOORU_GALLERY_TEST_CONFIG": str(config_path),
        },
    )
    assert loaded.gallery_new_ui_enabled is False
    assert loaded.provider_gelbooru_v2 is False

    outside = tmp_path / "outside.json"
    outside.write_text('{"schemaVersion":1,"featureFlags":{}}', encoding="utf-8")
    with pytest.raises(v53.FeatureFlagConfigurationError, match="tests/.runtime"):
        v53.load_v53_feature_flags(
            plugin_root=root,
            environ={
                "DANBOORU_GALLERY_DELIVERY_TEST": "true",
                "DANBOORU_GALLERY_TEST_CONFIG": str(outside),
            },
        )


def test_feature_endpoint_is_always_available_while_v2_can_be_unregistered():
    flags = v53.V53FeatureFlags(
        v2_routes_enabled=False,
        gallery_new_ui_enabled=False,
        provider_danbooru_v2=False,
        provider_gelbooru_v2=False,
        provider_yandere_v2=False,
        provider_civitai_v2=False,
    ).validate()
    routes = FakeRoutes()
    v53.register_feature_route(routes, flags, web_module=FakeWeb)
    assert set(routes.handlers) == {v53.FEATURE_API_PATH}
    payload = asyncio.run(routes.handlers[v53.FEATURE_API_PATH](FakeRequest())).payload
    assert payload["featureFlags"]["gallery_new_ui_enabled"] is False

    assert v53.register_v2_routes(
        routes,
        _Legacy(),
        feature_flags=flags,
        web_module=FakeWeb,
    ) == {}
    assert all(not path.startswith(v53.V2_API_ROOT) for path in routes.handlers)


def test_disabled_provider_is_visible_but_cannot_make_requests():
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef")
    registry = v53.build_live_provider_registry(_Legacy(), codec)
    flags = v53.V53FeatureFlags(provider_gelbooru_v2=False)
    handlers = v53.create_v2_handlers(
        registry,
        codec,
        feature_flags=flags,
        web_module=FakeWeb,
    )

    capability = asyncio.run(
        handlers[v53.V2_API_ROOT + "/providers"](FakeRequest({"source": "gelbooru"}))
    )
    assert capability.status == 200
    assert capability.payload["availability"] == {
        "state": "unavailable",
        "reason": "provider_disabled",
    }
    assert all(
        item["state"] == "unsupported" and item["reasonCode"] == "provider_disabled"
        for item in capability.payload["features"]["views"]
    )

    blocked = asyncio.run(
        handlers[v53.V2_API_ROOT + "/browse"](FakeRequest({"source": "gelbooru"}))
    )
    assert blocked.status == 422
    assert blocked.payload["error"]["code"] == "unsupported"


@pytest.mark.parametrize("route", ["browse", "facets", "autocomplete"])
def test_unknown_provider_source_is_consistently_unsupported(route):
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef")
    registry = v53.build_live_provider_registry(_Legacy(), codec)
    handlers = v53.create_v2_handlers(registry, codec, web_module=FakeWeb)
    response = asyncio.run(
        handlers[v53.V2_API_ROOT + "/" + route](FakeRequest({"source": "unknown"}))
    )
    assert response.status == 422
    assert response.payload["error"]["code"] == "unsupported"
