from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
V53_IMPORT_ROOT = PLUGIN_ROOT / "py" / "danbooru_gallery"
sys.path.insert(0, str(V53_IMPORT_ROOT))

import v53  # noqa: E402


def _browse(**overrides):
    raw = {
        "source": "civitai",
        "view": "ranking",
        "query": None,
        "metric": "reactions",
        "period": "week",
        "anchor_date": None,
        "facet_kind": None,
        "facet_id": None,
        "safety_profile": "general",
        "page_size": 20,
        "cursor": None,
        "allow_approx": False,
        "client_request_id": "browser-1",
    }
    raw.update(overrides)
    raw["client_query_key"] = v53.browse_client_query_key(raw)
    return raw


def _facet(**overrides):
    raw = {
        "source": "civitai",
        "facet_kind": "model_taxonomy",
        "query": None,
        "page_size": 20,
        "cursor": None,
        "client_request_id": "facet-1",
    }
    raw.update(overrides)
    raw["client_query_key"] = v53.facet_client_query_key(raw)
    return raw


def _autocomplete(**overrides):
    raw = {
        "source": "danbooru",
        "query": "hakurei",
        "facet_kind": "character",
        "page_size": 20,
        "client_request_id": "autocomplete-1",
    }
    raw.update(overrides)
    raw["client_query_key"] = v53.autocomplete_client_query_key(raw)
    return raw


def _error(raw, validator=v53.validate_browse_request, **kwargs):
    with pytest.raises(v53.ContractValidationError) as caught:
        validator(raw, **kwargs)
    return caught.value.error


def test_v53_can_be_imported_without_comfyui_modules():
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(V53_IMPORT_ROOT)!r}); "
        "import v53; "
        "assert v53.CONTRACT_VERSION == 1; "
        "assert 'server' not in sys.modules and 'folder_paths' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_four_provider_capability_contracts_are_versioned_and_serializable():
    capabilities = v53.all_provider_capabilities()
    assert [item.source.value for item in capabilities] == [
        "danbooru",
        "gelbooru",
        "yandere",
        "civitai",
    ]
    for item in capabilities:
        payload = item.to_dict()
        assert payload["schemaVersion"] == v53.CONTRACT_VERSION == 1
        assert payload["availability"] == {"state": "available", "reason": None}
        assert payload["features"]["pagination"]["kind"] == "opaque_cursor"
        assert payload["limits"]["maxPageSize"] > 0
        json.dumps(payload, ensure_ascii=False)


def test_capability_semantics_match_the_v53_public_api_plan():
    danbooru = v53.get_provider_capabilities("danbooru")
    popular = danbooru.ranking("popular", "week")
    assert popular.fidelity == v53.Fidelity.NATIVE
    assert popular.period_semantics == v53.PeriodSemantics.CALENDAR_ANCHOR
    assert popular.supports_anchor_date is True
    assert danbooru.ranking("popular", "year") is None
    assert danbooru.limits.max_page_size == 200
    assert danbooru.limits.anonymous_tag_limit == 2

    gelbooru = v53.get_provider_capabilities("gelbooru")
    assert gelbooru.ranking("score", "all_time").fidelity == v53.Fidelity.SERVER_DERIVED
    assert gelbooru.view("favorites").state == v53.FeatureState.UNSUPPORTED
    assert gelbooru.view("favorites").reason_code == "local_favorites_unavailable"
    approximate = gelbooru.ranking("score_approx", "month")
    assert approximate.state == v53.FeatureState.PROVISIONAL
    assert approximate.fidelity == v53.Fidelity.CLIENT_APPROX
    assert approximate.period_semantics == v53.PeriodSemantics.BOUNDED_SAMPLE

    yandere = v53.get_provider_capabilities("yandere")
    assert yandere.view("ranking").state == v53.FeatureState.PROVISIONAL
    assert yandere.view("favorites").state == v53.FeatureState.UNSUPPORTED
    assert yandere.view("favorites").reason_code == "local_favorites_unavailable"
    assert yandere.ranking("score_period", "year").period_semantics == v53.PeriodSemantics.EXPLICIT_RANGE
    assert yandere.limits.max_page_size == 100

    civitai = v53.get_provider_capabilities("civitai")
    assert civitai.view("search").state == v53.FeatureState.DEGRADED
    assert civitai.view("search").scope == "experimental_web"
    assert civitai.view("search").requires_auth is True
    assert civitai.view("favorites").scope == "local"
    assert civitai.ranking("reactions", "all_time").period_semantics == v53.PeriodSemantics.ROLLING_CURRENT
    assert civitai.ranking("collected", "week").state == v53.FeatureState.PROVISIONAL
    known_tag = civitai.facet("known_image_tag_id")
    assert known_tag.state == v53.FeatureState.DEGRADED
    assert known_tag.listable is False and known_tag.filterable is True
    model_taxonomy = civitai.facet("model_taxonomy")
    assert model_taxonomy.listable is True and model_taxonomy.filterable is False
    assert civitai.facet("media_type").state == v53.FeatureState.UNSUPPORTED
    assert "baseModel" in civitai.features.compatible_filters_by_view["latest"]
    assert "knownImageTagId" in civitai.features.compatible_filters_by_view["ranking"]
    assert civitai.features.compatible_filters_by_view["search"] == ("query",)
    assert danbooru.features.compatible_filters_by_view["favorites"] == ()
    assert civitai.features.compatible_filters_by_view["favorites"] == ()


def test_runtime_capabilities_keep_static_features_and_apply_dynamic_state():
    runtime = v53.ProviderRuntime(
        availability=v53.AvailabilityState.UNAVAILABLE,
        reason="proxy_down",
        auth_configured=True,
        auth_required=True,
        feature_states={"ranking:collected": v53.FeatureState.SUPPORTED},
    )
    capability = v53.get_provider_capabilities("civitai", runtime)
    assert capability.availability.to_dict() == {"state": "unavailable", "reason": "proxy_down"}
    assert capability.auth.required is True and capability.auth.configured is True
    assert capability.ranking("collected", "week").state == v53.FeatureState.SUPPORTED
    assert capability.ranking("collected", "week").reason_code is None
    assert capability.ranking("reactions", "week").fidelity == v53.Fidelity.NATIVE


def test_canonical_query_keys_have_golden_hashes_and_ignore_ephemeral_fields():
    raw = {
        "source": "civitai",
        "view": "ranking",
        "query": None,
        "metric": "reactions",
        "period": "week",
        "anchor_date": None,
        "facet_kind": "model",
        "facet_id": "42",
        "safety_profile": "general",
        "page_size": "20",
        "allow_approx": "false",
    }
    expected = "5736adc97e7115d8e08edc8c4b284cf2e9cbe7133835b6250f952d5f6f11674f"
    assert v53.browse_client_query_key(raw) == expected
    reordered = dict(reversed(list(raw.items())))
    reordered.update(client_request_id="new-sequence", cursor="opaque", client_query_key=expected)
    assert v53.browse_client_query_key(reordered) == expected

    # This is the same 11-field vector asserted by the browser-side
    # query_contract.js test.
    browser_vector = dict(raw, query="portrait")
    assert v53.browse_client_query_key(browser_vector) == (
        "00394aa2212a1cbadaa55b1a6e1c9a381563a88358724a02a05c2c2a09d601eb"
    )

    facet_raw = {
        "source": "civitai",
        "facet_kind": "model_taxonomy",
        "query": "portrait",
        "page_size": 20,
    }
    assert v53.facet_client_query_key(facet_raw) == (
        "af293ed181baa698fcef415682db1b4bb9d96310be69849aa241042360286d05"
    )


def test_valid_native_browse_and_filter_contracts():
    request = v53.validate_browse_request(_browse(facet_kind="model", facet_id="42"))
    assert request.source == v53.Source.CIVITAI
    assert request.view == v53.View.RANKING
    assert request.metric == "reactions" and request.period == "week"

    latest = v53.validate_browse_request(
        _browse(
            view="latest",
            metric=None,
            period=None,
            facet_kind="base_model",
            facet_id="SDXL 1.0",
        )
    )
    assert latest.facet_kind == "base_model"

    degraded_filter = v53.validate_browse_request(
        _browse(facet_kind="known_image_tag_id", facet_id="1234")
    )
    assert degraded_filter.facet_id == "1234"


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda raw: raw.update(client_query_key="0" * 64), v53.ErrorCode.INVALID_REQUEST),
        (lambda raw: raw.update(extra_field="nope"), v53.ErrorCode.INVALID_REQUEST),
        (lambda raw: raw.update(page_size=201), v53.ErrorCode.INVALID_REQUEST),
        (lambda raw: raw.update(safety_profile="invented"), v53.ErrorCode.UNSUPPORTED),
    ],
)
def test_strict_browse_validation_rejects_bad_input(mutator, code):
    raw = _browse()
    mutator(raw)
    error = _error(raw)
    assert error.code == code


def test_unsupported_and_period_semantic_rules_fail_before_provider_io():
    search = _browse(view="search", query="cat", metric=None, period=None, safety_profile=None)
    assert _error(search).code == v53.ErrorCode.AUTH_REQUIRED

    with_anchor = _browse(anchor_date="2026-07-19")
    assert _error(with_anchor).code == v53.ErrorCode.INVALID_REQUEST

    danbooru = _browse(
        source="danbooru",
        metric="popular",
        period="week",
        anchor_date=None,
        safety_profile=None,
    )
    assert _error(danbooru).code == v53.ErrorCode.INVALID_REQUEST

    unsupported_year = _browse(
        source="danbooru",
        metric="popular",
        period="year",
        anchor_date="2026-07-19",
        safety_profile=None,
    )
    assert _error(unsupported_year).code == v53.ErrorCode.UNSUPPORTED


def test_provisional_rankings_require_explicit_runtime_enablement():
    yandere_raw = _browse(
        source="yandere",
        metric="score_period",
        period="month",
        anchor_date="2026-07-19",
        safety_profile="safe",
    )
    assert _error(yandere_raw).code == v53.ErrorCode.UNSUPPORTED
    runtime = v53.ProviderRuntime(
        feature_states={
            "view:ranking": v53.FeatureState.SUPPORTED,
            "ranking:score_period": v53.FeatureState.SUPPORTED,
        }
    )
    enabled = v53.get_provider_capabilities("yandere", runtime)
    assert v53.validate_browse_request(yandere_raw, capabilities=enabled).period == "month"

    gel_raw = _browse(
        source="gelbooru",
        metric="score_approx",
        period="week",
        anchor_date="2026-07-19",
        safety_profile="general",
        allow_approx=True,
    )
    assert _error(gel_raw).code == v53.ErrorCode.UNSUPPORTED
    gel_enabled = v53.get_provider_capabilities(
        "gelbooru",
        v53.ProviderRuntime(feature_states={"ranking:score_approx": v53.FeatureState.SUPPORTED}),
    )
    assert v53.validate_browse_request(gel_raw, capabilities=gel_enabled).allow_approx is True
    without_opt_in = _browse(**{**gel_raw, "allow_approx": False})
    assert _error(without_opt_in, capabilities=gel_enabled).code == v53.ErrorCode.UNSUPPORTED


def test_dynamic_unavailability_and_auth_are_enforced_except_for_local_view():
    unavailable = v53.get_provider_capabilities(
        "civitai",
        v53.ProviderRuntime(availability=v53.AvailabilityState.UNAVAILABLE, reason="offline"),
    )
    assert _error(_browse(), capabilities=unavailable).code == v53.ErrorCode.NETWORK_UNAVAILABLE

    favorite = _browse(
        view="favorites",
        metric=None,
        period=None,
        safety_profile=None,
    )
    assert v53.validate_browse_request(favorite, capabilities=unavailable).view == v53.View.FAVORITES

    for source in ("danbooru", "civitai"):
        capabilities = v53.get_provider_capabilities(source)
        filtered_favorite = _browse(
            source=source,
            view="favorites",
            query="cat",
            metric=None,
            period=None,
            safety_profile=None,
        )
        assert _error(filtered_favorite, capabilities=capabilities).code == v53.ErrorCode.UNSUPPORTED
        safe_favorite = _browse(
            source=source,
            view="favorites",
            query=None,
            metric=None,
            period=None,
            safety_profile="general",
        )
        assert _error(safe_favorite, capabilities=capabilities).code == v53.ErrorCode.UNSUPPORTED

    auth = v53.get_provider_capabilities(
        "danbooru",
        v53.ProviderRuntime(auth_required=True, auth_configured=False),
    )
    dan_latest = _browse(
        source="danbooru",
        view="latest",
        metric=None,
        period=None,
        safety_profile="general",
    )
    assert _error(dan_latest, capabilities=auth).code == v53.ErrorCode.AUTH_REQUIRED


def test_facet_request_contract_accepts_listable_and_rejects_non_listable_facets():
    request = v53.validate_facet_request(_facet())
    assert request.facet_kind == "model_taxonomy"

    taxonomy_category = _browse(
        view="category",
        metric=None,
        period=None,
        anchor_date=None,
        facet_kind="model_taxonomy",
        facet_id="character",
        allow_approx=False,
    )
    assert _error(taxonomy_category).code == v53.ErrorCode.UNSUPPORTED

    known_tag = _facet(facet_kind="known_image_tag_id")
    error = _error(known_tag, validator=v53.validate_facet_request)
    assert error.code == v53.ErrorCode.UNSUPPORTED


def test_autocomplete_uses_the_same_full_cross_language_query_contract():
    raw = _autocomplete()
    assert raw["client_query_key"] == (
        "5964b803486a5ef5ef68918bdaf0c180c8acdb8495151421f9274f3406a50251"
    )
    request = v53.validate_autocomplete_request(raw)
    assert request.query == "hakurei"
    assert request.facet_kind == "character"

    yandere_category = _facet(source="yandere", facet_kind="category_listing")
    error = _error(yandere_category, validator=v53.validate_facet_request)
    assert error.code == v53.ErrorCode.UNSUPPORTED


def test_opaque_cursor_is_signed_bound_and_expiring():
    codec = v53.OpaqueCursorCodec(b"0123456789abcdef0123456789abcdef", ttl_seconds=10)
    query_key = _browse()["client_query_key"]
    token = codec.encode(
        source="civitai",
        request_kind="browse",
        query_key=query_key,
        state={"nextCursor": "upstream-secret-shape"},
        issued_at=100,
    )
    decoded = codec.decode(
        token,
        expected_source="civitai",
        expected_kind="browse",
        expected_query_key=query_key,
        now=105,
    )
    assert decoded.state == {"nextCursor": "upstream-secret-shape"}

    with pytest.raises(v53.CursorCodecError, match="different provider"):
        codec.decode(token, expected_source="danbooru", now=105)
    with pytest.raises(v53.CursorCodecError, match="different query"):
        codec.decode(token, expected_query_key="0" * 64, now=105)
    with pytest.raises(v53.CursorCodecError, match="expired"):
        codec.decode(token, now=111)

    version, payload, signature = token.split(".")
    signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(v53.CursorCodecError, match="signature"):
        codec.decode(".".join((version, payload, signature)), now=105)


def test_validated_cursor_returns_provider_state_without_exposing_its_shape():
    codec = v53.OpaqueCursorCodec("a sufficiently long cursor signing secret")
    first = _browse()
    token = codec.encode(
        source="civitai",
        request_kind="browse",
        query_key=first["client_query_key"],
        state={"cursor": "abc", "page": 2},
    )
    next_page = _browse(cursor=token)
    request = v53.validate_browse_request(next_page, cursor_codec=codec)
    assert request.cursor == token
    assert request.cursor_state == {"cursor": "abc", "page": 2}


def test_success_and_error_envelopes_have_stable_empty_result_semantics():
    query_key = "a" * 64
    success = v53.success_envelope(
        request_id="server-1",
        client_request_id="client-1",
        query_key=query_key,
        items=[],
    )
    assert success["items"] == [] and success["error"] is None
    assert success["pageInfo"]["hasNext"] is False
    assert len(success["pageInfo"]["pageKey"]) == 64

    failure = v53.error_envelope(
        request_id="server-2",
        client_request_id="client-2",
        query_key=query_key,
        request_cursor="opaque-attempt",
        error=v53.ProviderError(
            code=v53.ErrorCode.RATE_LIMITED,
            http_status=429,
            retryable=True,
            retry_after_seconds=2,
            message="upstream rate limited",
        ),
    )
    assert failure["items"] == []
    assert failure["pageInfo"]["requestCursor"] == "opaque-attempt"
    assert failure["pageInfo"]["nextCursor"] is None
    assert failure["pageInfo"]["hasNext"] is None
    assert failure["error"] == {
        "code": "rate_limited",
        "httpStatus": 429,
        "retryable": True,
        "retryAfterSeconds": 2,
        "message": "upstream rate limited",
    }


def test_legacy_provider_adapter_normalizes_sync_and_async_boundaries():
    browse_request = v53.validate_browse_request(_browse())
    facet_request = v53.validate_facet_request(_facet())

    async def autocomplete(_request):
        return [{"id": "tag", "label": "tag"}]

    adapter = v53.LegacyProviderAdapter(
        "civitai",
        browse_handler=lambda _request: (json.dumps([{"id": 1}, {"id": 2}]),),
        facet_handler=lambda _request: {"items": [{"id": "portrait"}]},
        autocomplete_handler=autocomplete,
        get_post_handler=lambda post_id: {"id": post_id, "url": "https://example.invalid"},
    )

    page = asyncio.run(adapter.browse(browse_request))
    facets = asyncio.run(adapter.list_facets(facet_request))
    suggestions = asyncio.run(adapter.autocomplete({"query": "ta"}))
    post = asyncio.run(adapter.get_post("9"))
    assert page.items == ({"id": 1}, {"id": 2})
    assert page.provenance["kind"] == "legacy_adapter"
    assert facets.items == ({"id": "portrait"},)
    assert suggestions == ({"id": "tag", "label": "tag"},)
    assert post == {"id": "9", "url": "https://example.invalid"}
    assert adapter.contract_version == v53.CONTRACT_VERSION


def test_legacy_provider_adapter_rejects_shape_drift():
    adapter = v53.LegacyProviderAdapter(
        "civitai",
        browse_handler=lambda _request: {"unexpected": []},
    )
    with pytest.raises(v53.ProviderPayloadError, match="item list"):
        asyncio.run(adapter.browse(v53.validate_browse_request(_browse())))
