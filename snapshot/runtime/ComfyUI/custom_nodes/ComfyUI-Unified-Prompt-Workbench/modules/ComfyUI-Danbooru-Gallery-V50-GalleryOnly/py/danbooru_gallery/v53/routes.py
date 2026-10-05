from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import secrets
import threading
import uuid
from typing import Any, Dict, Mapping, Optional

from .contracts import (
    error_envelope,
    success_envelope,
    validate_autocomplete_request,
    validate_browse_request,
    validate_facet_request,
)
from .cursor import OpaqueCursorCodec
from .domain import CONTRACT_VERSION, ContractValidationError, ErrorCode, ProviderError
from .live_providers import (
    LiveProviderRegistry,
    ProviderRequestError,
    build_live_provider_registry,
    normalize_provider_exception,
)
from .settings import FEATURE_API_PATH, V53FeatureFlags


V2_API_ROOT = "/danbooru_gallery/v2"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_CODEC: Optional[OpaqueCursorCodec] = None
_DEFAULT_CODEC_LOCK = threading.Lock()
_REGISTERED_ROUTE_TABLES = set()
_REGISTERED_FEATURE_ROUTE_TABLES = set()
_REGISTER_LOCK = threading.Lock()


def get_default_cursor_codec() -> OpaqueCursorCodec:
    global _DEFAULT_CODEC
    with _DEFAULT_CODEC_LOCK:
        if _DEFAULT_CODEC is None:
            configured = os.environ.get("DANBOORU_GALLERY_V2_CURSOR_SECRET", "")
            secret = configured.encode("utf-8") if len(configured.encode("utf-8")) >= 16 else secrets.token_bytes(32)
            _DEFAULT_CODEC = OpaqueCursorCodec(secret, ttl_seconds=3600)
        return _DEFAULT_CODEC


def _server_request_id() -> str:
    return uuid.uuid4().hex


def _identity(query: Mapping[str, Any]) -> Dict[str, str]:
    client_id = query.get("client_request_id", "")
    query_key = query.get("client_query_key", "")
    return {
        "client_request_id": client_id if isinstance(client_id, str) else "",
        "query_key": query_key if isinstance(query_key, str) and _HASH_RE.fullmatch(query_key) else "",
    }


def _response_headers(error: Optional[ProviderError] = None) -> Dict[str, str]:
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    if error is not None and error.retry_after_seconds is not None:
        value = error.retry_after_seconds
        headers["Retry-After"] = str(int(value) if float(value).is_integer() else value)
    return headers


def _web_json(web_module: Any, payload: Mapping[str, Any], *, status: int = 200, error: Optional[ProviderError] = None) -> Any:
    return web_module.json_response(
        dict(payload),
        status=status,
        headers=_response_headers(error),
    )


def _error_response(
    web_module: Any,
    query: Mapping[str, Any],
    error: ProviderError,
    *,
    request_id: Optional[str] = None,
) -> Any:
    identity = _identity(query)
    request_cursor = query.get("cursor")
    if not isinstance(request_cursor, str):
        request_cursor = None
    payload = error_envelope(
        request_id=request_id or _server_request_id(),
        client_request_id=identity["client_request_id"],
        query_key=identity["query_key"],
        request_cursor=request_cursor,
        error=error,
    )
    return _web_json(web_module, payload, status=error.http_status, error=error)


def _source_query_value(query: Mapping[str, Any]) -> Optional[str]:
    getall = getattr(query, "getall", None)
    if callable(getall):
        try:
            values = list(getall("source"))
        except KeyError:
            values = []
        if len(values) > 1:
            raise ContractValidationError("source must not be repeated")
        raw = values[0] if values else None
    else:
        raw = query.get("source")
    if raw in (None, ""):
        return None
    if not isinstance(raw, str) or raw.strip().lower() not in ("danbooru", "gelbooru", "yandere", "civitai"):
        raise ContractValidationError(
            "unsupported source",
            code=ErrorCode.UNSUPPORTED,
            http_status=422,
        )
    return raw.strip().lower()


def _providers_query(query: Mapping[str, Any]) -> Optional[str]:
    unknown = [str(key) for key in query.keys() if key != "source"]
    if unknown:
        raise ContractValidationError("unknown request fields", details={"fields": sorted(unknown)})
    return _source_query_value(query)


def _required_source(query: Mapping[str, Any]) -> str:
    source = _source_query_value(query)
    if source is None:
        raise ContractValidationError("source is required")
    return source


def _disabled_provider_error(source: str) -> ContractValidationError:
    return ContractValidationError(
        "provider is disabled by rollout configuration",
        code=ErrorCode.UNSUPPORTED,
        http_status=422,
        details={"source": source, "reason": "provider_disabled"},
    )


def _capability_payload(provider: Any, flags: V53FeatureFlags) -> Dict[str, Any]:
    payload = dict(provider.capabilities().to_dict())
    source = str(payload.get("source") or "")
    if not flags.provider_enabled(source):
        payload["availability"] = {"state": "unavailable", "reason": "provider_disabled"}
        features = dict(payload.get("features") or {})
        for group in ("views", "ranking", "facets"):
            disabled = []
            for entry in features.get(group) or ():
                item = dict(entry)
                item["state"] = "unsupported"
                item["reasonCode"] = "provider_disabled"
                disabled.append(item)
            features[group] = disabled
        features["compatibleFiltersByView"] = {}
        payload["features"] = features
    return payload


def _fixtures_enabled() -> bool:
    return str(os.environ.get("DANBOORU_GALLERY_TEST_FIXTURES", "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _fixture_scenario(request: Any) -> str:
    if not _fixtures_enabled():
        return ""
    remote = str(getattr(request, "remote", "") or "").strip().strip("[]")
    try:
        if not remote or not ipaddress.ip_address(remote.split("%", 1)[0]).is_loopback:
            return "remote_forbidden"
    except ValueError:
        return "remote_forbidden"
    headers = getattr(request, "headers", {}) or {}
    value = str(headers.get("X-Gallery-Test-Scenario", "success") or "success").strip().lower()
    allowed = {
        "success",
        "empty",
        "delay",
        "401",
        "403",
        "429",
        "500",
        "schema_drift",
        "cursor_expired",
        "remote_forbidden",
    }
    return value if value in allowed else "success"


def _fixture_error(scenario: str) -> Optional[ProviderError]:
    if scenario == "remote_forbidden":
        return ProviderError(ErrorCode.FORBIDDEN, 403, False, "fixture mode is loopback-only")
    if scenario == "401":
        return ProviderError(ErrorCode.AUTH_INVALID, 401, False, "fixture authentication failed")
    if scenario == "403":
        return ProviderError(ErrorCode.FORBIDDEN, 403, False, "fixture request forbidden")
    if scenario == "429":
        return ProviderError(ErrorCode.RATE_LIMITED, 429, True, "fixture rate limited", 2)
    if scenario == "500":
        return ProviderError(ErrorCode.UPSTREAM_ERROR, 502, True, "fixture upstream failure")
    if scenario == "schema_drift":
        return ProviderError(ErrorCode.SCHEMA_CHANGED, 502, False, "fixture schema changed")
    if scenario == "cursor_expired":
        return ProviderError(ErrorCode.INVALID_REQUEST, 400, False, "fixture cursor expired")
    return None


async def _fixture_delay(scenario: str) -> None:
    if scenario == "delay":
        await asyncio.sleep(0.15)


def _fixture_item(source: str, suffix: str = "1") -> Mapping[str, Any]:
    # Keep the delivery fixture aligned with the gallery's static-image policy.
    # GIF is intentionally filtered by the UI because it may be animated, so a
    # GIF pixel would make a successful fixture response render as zero cards.
    pixel = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
        "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    return {
        "id": "fixture-%s-%s" % (source, suffix),
        "source": source,
        "source_site": source,
        "rating": "general",
        "score": 100,
        "file_url": pixel,
        "large_file_url": pixel,
        "preview_file_url": pixel,
        "file_ext": "png",
        "image_width": 1024,
        "image_height": 1024,
        "tag_string": "fixture_tag",
        "tag_string_general": "fixture_tag",
    }


def _fixture_ranking(validated: Any, provider: Any) -> Optional[Mapping[str, Any]]:
    if getattr(validated, "view", None) is None or validated.view.value != "ranking":
        return None
    capability = provider.capabilities().ranking(validated.metric, validated.period)
    return {
        "requestedMetric": validated.metric,
        "effectiveMetric": validated.metric,
        "period": validated.period,
        "fidelity": capability.fidelity.value if capability else "server_derived",
        "label": "fixture ranking",
        "basis": capability.basis if capability else "fixture",
        "periodSemantics": capability.period_semantics.value if capability else "not_applicable",
        "coverage": None,
    }


def create_v2_handlers(
    registry: LiveProviderRegistry,
    cursor_codec: OpaqueCursorCodec,
    *,
    feature_flags: Optional[V53FeatureFlags] = None,
    web_module: Any = None,
    logger: Any = None,
) -> Mapping[str, Any]:
    if web_module is None:
        from aiohttp import web as web_module
    flags = (feature_flags or V53FeatureFlags()).validate()

    async def providers(request: Any) -> Any:
        try:
            source = _providers_query(request.query)
            if source is not None:
                payload = _capability_payload(registry.get(source), flags)
                payload["featureFlags"] = dict(flags.to_dict())
                return _web_json(web_module, payload)
            payload = {
                "schemaVersion": CONTRACT_VERSION,
                "featureFlags": dict(flags.to_dict()),
                "providers": [_capability_payload(provider, flags) for provider in registry.all()],
            }
            return _web_json(web_module, payload)
        except ContractValidationError as exc:
            payload = {
                "schemaVersion": CONTRACT_VERSION,
                "providers": [],
                "error": exc.error.to_dict(),
            }
            return _web_json(web_module, payload, status=exc.error.http_status, error=exc.error)

    async def browse(request: Any) -> Any:
        server_id = _server_request_id()
        try:
            raw = request.query
            source = _required_source(raw)
            if not flags.provider_enabled(source):
                raise _disabled_provider_error(source)
            provider = registry.get(source)
            validated = validate_browse_request(
                raw,
                capabilities=provider.capabilities(),
                cursor_codec=cursor_codec,
            )
            scenario = _fixture_scenario(request)
            await _fixture_delay(scenario)
            fixture_error = _fixture_error(scenario)
            if fixture_error is not None:
                return _error_response(web_module, request.query, fixture_error, request_id=server_id)
            if scenario:
                items = [] if scenario == "empty" else [_fixture_item(validated.source.value)]
                next_cursor = None
                if scenario != "empty" and validated.cursor is None:
                    next_cursor = cursor_codec.encode(
                        source=validated.source.value,
                        request_kind="browse",
                        query_key=validated.client_query_key,
                        state={"fixturePage": 2},
                    )
                payload = success_envelope(
                    request_id=server_id,
                    client_request_id=validated.client_request_id,
                    query_key=validated.client_query_key,
                    items=items,
                    request_cursor=validated.cursor,
                    next_cursor=next_cursor,
                    ranking=_fixture_ranking(validated, provider),
                    provenance={"kind": "fixture", "endpoint": validated.source.value},
                    applied={"requestTime": "2026-07-19T00:00:00Z", "safetyProfile": validated.safety_profile},
                )
                return _web_json(web_module, payload)
            page = await provider.browse(validated)
            payload = success_envelope(
                request_id=server_id,
                client_request_id=validated.client_request_id,
                query_key=validated.client_query_key,
                items=page.items,
                request_cursor=validated.cursor,
                next_cursor=page.next_cursor,
                ranking=page.ranking,
                provenance=page.provenance,
                applied=page.applied,
                warnings=page.warnings,
            )
            return _web_json(web_module, payload)
        except asyncio.CancelledError:
            raise
        except ContractValidationError as exc:
            return _error_response(web_module, request.query, exc.error, request_id=server_id)
        except ProviderRequestError as exc:
            return _error_response(web_module, request.query, exc.error, request_id=server_id)
        except (TypeError, ValueError) as exc:
            error = ProviderError(ErrorCode.INVALID_REQUEST, 400, False, "invalid provider request")
            return _error_response(web_module, request.query, error, request_id=server_id)
        except Exception as exc:
            if logger is not None:
                logger.warning("[GalleryV2] browse failed: %s", type(exc).__name__)
            source = request.query.get("source", "danbooru")
            try:
                provider = registry.get(source)
                normalized = normalize_provider_exception(provider.source, exc, "gallery browse")
                error = normalized.error
            except Exception:
                error = ProviderError(ErrorCode.UPSTREAM_ERROR, 502, False, "gallery browse failed")
            return _error_response(web_module, request.query, error, request_id=server_id)

    async def facets(request: Any) -> Any:
        server_id = _server_request_id()
        try:
            raw = request.query
            source = _required_source(raw)
            if not flags.provider_enabled(source):
                raise _disabled_provider_error(source)
            provider = registry.get(source)
            validated = validate_facet_request(
                raw,
                capabilities=provider.capabilities(),
                cursor_codec=cursor_codec,
            )
            scenario = _fixture_scenario(request)
            await _fixture_delay(scenario)
            fixture_error = _fixture_error(scenario)
            if fixture_error is not None:
                return _error_response(web_module, request.query, fixture_error, request_id=server_id)
            if scenario:
                items = [] if scenario == "empty" else [{
                    "id": "fixture-%s" % validated.facet_kind,
                    "label": "Fixture %s" % validated.facet_kind,
                    "kind": validated.facet_kind,
                    "category": None,
                    "itemCount": 42,
                    "countKind": "fixture_count",
                    "state": "supported",
                }]
                payload = success_envelope(
                    request_id=server_id,
                    client_request_id=validated.client_request_id,
                    query_key=validated.client_query_key,
                    items=items,
                    request_cursor=validated.cursor,
                    provenance={"kind": "fixture", "endpoint": validated.source.value + "/facets"},
                )
                return _web_json(web_module, payload)
            page = await provider.list_facets(validated)
            payload = success_envelope(
                request_id=server_id,
                client_request_id=validated.client_request_id,
                query_key=validated.client_query_key,
                items=page.items,
                request_cursor=validated.cursor,
                next_cursor=page.next_cursor,
                warnings=page.warnings,
            )
            return _web_json(web_module, payload)
        except asyncio.CancelledError:
            raise
        except ContractValidationError as exc:
            return _error_response(web_module, request.query, exc.error, request_id=server_id)
        except ProviderRequestError as exc:
            return _error_response(web_module, request.query, exc.error, request_id=server_id)
        except (TypeError, ValueError):
            error = ProviderError(ErrorCode.INVALID_REQUEST, 400, False, "invalid provider request")
            return _error_response(web_module, request.query, error, request_id=server_id)
        except Exception as exc:
            if logger is not None:
                logger.warning("[GalleryV2] facets failed: %s", type(exc).__name__)
            error = ProviderError(ErrorCode.UPSTREAM_ERROR, 502, False, "gallery facets failed")
            return _error_response(web_module, request.query, error, request_id=server_id)

    async def autocomplete(request: Any) -> Any:
        server_id = _server_request_id()
        try:
            raw = request.query
            source = _required_source(raw)
            if not flags.provider_enabled(source):
                raise _disabled_provider_error(source)
            provider = registry.get(source)
            validated = validate_autocomplete_request(raw, capabilities=provider.capabilities())
            scenario = _fixture_scenario(request)
            await _fixture_delay(scenario)
            fixture_error = _fixture_error(scenario)
            if fixture_error is not None:
                return _error_response(web_module, request.query, fixture_error, request_id=server_id)
            if scenario:
                items = [] if scenario == "empty" else [{
                    "id": "fixture-suggestion",
                    "label": validated.query + " fixture",
                    "kind": validated.facet_kind or "tag",
                    "category": None,
                    "itemCount": 1,
                    "countKind": "fixture_count",
                    "state": "supported",
                }]
            else:
                items = await provider.autocomplete(validated)
            payload = success_envelope(
                request_id=server_id,
                client_request_id=validated.client_request_id,
                query_key=validated.client_query_key,
                items=items,
            )
            return _web_json(web_module, payload)
        except asyncio.CancelledError:
            raise
        except ContractValidationError as exc:
            return _error_response(web_module, request.query, exc.error, request_id=server_id)
        except ProviderRequestError as exc:
            return _error_response(web_module, request.query, exc.error, request_id=server_id)
        except (TypeError, ValueError):
            error = ProviderError(ErrorCode.INVALID_REQUEST, 400, False, "invalid provider request")
            return _error_response(web_module, request.query, error, request_id=server_id)
        except Exception as exc:
            if logger is not None:
                logger.warning("[GalleryV2] autocomplete failed: %s", type(exc).__name__)
            error = ProviderError(ErrorCode.UPSTREAM_ERROR, 502, False, "gallery autocomplete failed")
            return _error_response(web_module, request.query, error, request_id=server_id)

    return {
        V2_API_ROOT + "/providers": providers,
        V2_API_ROOT + "/browse": browse,
        V2_API_ROOT + "/facets": facets,
        V2_API_ROOT + "/autocomplete": autocomplete,
    }


def create_feature_handler(
    feature_flags: V53FeatureFlags,
    *,
    web_module: Any = None,
) -> Any:
    if web_module is None:
        from aiohttp import web as web_module
    flags = feature_flags.validate()

    async def features(request: Any) -> Any:
        if list(getattr(request, "query", {}).keys()):
            error = ProviderError(ErrorCode.INVALID_REQUEST, 400, False, "feature endpoint accepts no query fields")
            return _web_json(
                web_module,
                {"schemaVersion": CONTRACT_VERSION, "featureFlags": {}, "error": error.to_dict()},
                status=error.http_status,
                error=error,
            )
        return _web_json(
            web_module,
            {
                "schemaVersion": CONTRACT_VERSION,
                "featureFlags": dict(flags.to_dict()),
                "error": None,
            },
        )

    return features


def register_feature_route(
    route_table: Any,
    feature_flags: V53FeatureFlags,
    *,
    web_module: Any = None,
) -> Any:
    handler = create_feature_handler(feature_flags, web_module=web_module)
    table_id = id(route_table)
    with _REGISTER_LOCK:
        if table_id not in _REGISTERED_FEATURE_ROUTE_TABLES:
            route_table.get(FEATURE_API_PATH)(handler)
            _REGISTERED_FEATURE_ROUTE_TABLES.add(table_id)
    return handler


def register_v2_routes(
    route_table: Any,
    legacy: Any,
    *,
    cursor_codec: Optional[OpaqueCursorCodec] = None,
    registry: Optional[LiveProviderRegistry] = None,
    feature_flags: Optional[V53FeatureFlags] = None,
    web_module: Any = None,
    logger: Any = None,
) -> Mapping[str, Any]:
    flags = (feature_flags or V53FeatureFlags()).validate()
    if not flags.v2_routes_enabled:
        return {}
    codec = cursor_codec or get_default_cursor_codec()
    provider_registry = registry or build_live_provider_registry(legacy, codec)
    handlers = create_v2_handlers(
        provider_registry,
        codec,
        feature_flags=flags,
        web_module=web_module,
        logger=logger,
    )
    table_id = id(route_table)
    with _REGISTER_LOCK:
        if table_id in _REGISTERED_ROUTE_TABLES:
            return handlers
        for path, handler in handlers.items():
            route_table.get(path)(handler)
        _REGISTERED_ROUTE_TABLES.add(table_id)
    return handlers


__all__ = [
    "FEATURE_API_PATH",
    "V2_API_ROOT",
    "create_feature_handler",
    "create_v2_handlers",
    "get_default_cursor_codec",
    "register_feature_route",
    "register_v2_routes",
]
