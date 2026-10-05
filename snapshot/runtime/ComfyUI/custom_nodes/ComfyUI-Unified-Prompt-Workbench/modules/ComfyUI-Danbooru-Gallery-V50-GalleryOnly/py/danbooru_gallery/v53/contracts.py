from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import date
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set, Tuple

from .capabilities import get_provider_capabilities
from .cursor import CursorCodecError, OpaqueCursorCodec
from .domain import (
    AvailabilityState,
    AutocompleteRequest,
    BrowseRequest,
    ContractValidationError,
    ErrorCode,
    FacetRequest,
    FeatureState,
    Fidelity,
    ProviderCapabilities,
    ProviderError,
    Source,
    View,
)


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PERIODS = {"day", "week", "month", "year", "all_time"}
_BROWSE_FIELDS = {
    "source",
    "client_request_id",
    "client_query_key",
    "view",
    "query",
    "metric",
    "period",
    "anchor_date",
    "facet_kind",
    "facet_id",
    "safety_profile",
    "page_size",
    "cursor",
    "allow_approx",
}
_FACET_FIELDS = {
    "source",
    "client_request_id",
    "client_query_key",
    "facet_kind",
    "query",
    "page_size",
    "cursor",
}
_AUTOCOMPLETE_FIELDS = {
    "source",
    "client_request_id",
    "client_query_key",
    "query",
    "facet_kind",
    "page_size",
}


def _fail(
    message: str,
    *,
    code: ErrorCode = ErrorCode.INVALID_REQUEST,
    http_status: int = 400,
    details: Optional[Mapping[str, Any]] = None,
) -> None:
    raise ContractValidationError(
        message,
        code=code,
        http_status=http_status,
        details=details,
    )


def _ensure_mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("request must be an object")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: Set[str]) -> None:
    unknown = sorted(str(key) for key in data.keys() if key not in allowed)
    if unknown:
        _fail("unknown request fields", details={"fields": unknown})


def _scalar(data: Mapping[str, Any], key: str, default: Any = None) -> Any:
    getall = getattr(data, "getall", None)
    if callable(getall):
        try:
            values = list(getall(key))
        except KeyError:
            values = []
        if len(values) > 1:
            _fail("%s must not be repeated" % key)
        if values:
            value = values[0]
            if isinstance(value, (list, tuple, set, dict)):
                _fail("%s must be a scalar" % key)
            return value
    value = data.get(key, default)
    if isinstance(value, (list, tuple, set, dict)):
        _fail("%s must be a scalar" % key)
    return value


def _required_text(data: Mapping[str, Any], key: str, max_length: int) -> str:
    value = _scalar(data, key)
    if not isinstance(value, str) or not value.strip():
        _fail("%s is required" % key)
    value = value.strip()
    if len(value) > max_length:
        _fail("%s is too long" % key)
    return value


def _optional_text(
    data: Mapping[str, Any],
    key: str,
    max_length: int,
    *,
    lowercase: bool = False,
) -> Optional[str]:
    value = _scalar(data, key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        _fail("%s must be a string" % key)
    value = value.strip()
    if not value:
        return None
    if len(value) > max_length:
        _fail("%s is too long" % key)
    return value.lower() if lowercase else value


def _integer(data: Mapping[str, Any], key: str, default: int) -> int:
    value = _scalar(data, key, default)
    if isinstance(value, bool):
        _fail("%s must be an integer" % key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        return int(value.strip())
    _fail("%s must be an integer" % key)
    raise AssertionError("unreachable")


def _boolean(data: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = _scalar(data, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true"):
            return True
        if normalized in ("0", "false"):
            return False
    _fail("%s must be true or false" % key)
    raise AssertionError("unreachable")


def _source(data: Mapping[str, Any]) -> Source:
    raw = _required_text(data, "source", 32).lower()
    try:
        return Source(raw)
    except ValueError:
        _fail("unsupported source", code=ErrorCode.UNSUPPORTED, http_status=422)
    raise AssertionError("unreachable")


def _view(data: Mapping[str, Any]) -> View:
    raw = _required_text(data, "view", 32).lower()
    try:
        return View(raw)
    except ValueError:
        _fail("unsupported view", code=ErrorCode.UNSUPPORTED, http_status=422)
    raise AssertionError("unreachable")


def _name(data: Mapping[str, Any], key: str) -> Optional[str]:
    value = _optional_text(data, key, 64, lowercase=True)
    if value is not None and not _NAME_RE.fullmatch(value):
        _fail("%s has an invalid format" % key)
    return value


def _anchor_date(data: Mapping[str, Any]) -> Optional[str]:
    value = _optional_text(data, "anchor_date", 10)
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail("anchor_date must use YYYY-MM-DD")
    if parsed.isoformat() != value:
        _fail("anchor_date must use canonical YYYY-MM-DD")
    return value


def _request_id(data: Mapping[str, Any]) -> str:
    value = _required_text(data, "client_request_id", 128)
    if not _REQUEST_ID_RE.fullmatch(value):
        _fail("client_request_id has an invalid format")
    return value


def _declared_query_key(data: Mapping[str, Any]) -> str:
    value = _required_text(data, "client_query_key", 64)
    if not _HASH_RE.fullmatch(value):
        _fail("client_query_key must be a lowercase SHA-256 hex digest")
    return value


def _cursor(data: Mapping[str, Any]) -> Optional[str]:
    value = _optional_text(data, "cursor", 4096)
    return value


def _browse_values(data: Mapping[str, Any]) -> Dict[str, Any]:
    data = _ensure_mapping(data)
    _reject_unknown(data, _BROWSE_FIELDS)
    source = _source(data)
    view = _view(data)
    query = _optional_text(data, "query", 1000)
    metric = _name(data, "metric")
    period = _optional_text(data, "period", 16, lowercase=True)
    if period is not None and period not in _PERIODS:
        _fail("unsupported period", code=ErrorCode.UNSUPPORTED, http_status=422)
    anchor = _anchor_date(data)
    facet_kind = _name(data, "facet_kind")
    facet_id = _optional_text(data, "facet_id", 256)
    safety = _name(data, "safety_profile")
    page_size = _integer(data, "page_size", 20)
    allow_approx = _boolean(data, "allow_approx", False)

    if (facet_kind is None) != (facet_id is None):
        _fail("facet_kind and facet_id must be provided together")
    if view == View.RANKING:
        if metric is None or period is None:
            _fail("ranking view requires metric and period")
    elif metric is not None or period is not None or anchor is not None or allow_approx:
        _fail("ranking fields are only valid for ranking view")
    if view == View.CATEGORY and facet_kind is None:
        _fail("category view requires facet_kind and facet_id")
    if view == View.SEARCH and not query:
        _fail("search view requires query")

    return {
        "source": source,
        "view": view,
        "query": query,
        "metric": metric,
        "period": period,
        "anchor_date": anchor,
        "facet_kind": facet_kind,
        "facet_id": facet_id,
        "safety_profile": safety,
        "page_size": page_size,
        "allow_approx": allow_approx,
        "cursor": _cursor(data),
    }


def _facet_values(data: Mapping[str, Any]) -> Dict[str, Any]:
    data = _ensure_mapping(data)
    _reject_unknown(data, _FACET_FIELDS)
    return {
        "source": _source(data),
        "facet_kind": _name(data, "facet_kind"),
        "query": _optional_text(data, "query", 256),
        "page_size": _integer(data, "page_size", 20),
        "cursor": _cursor(data),
    }


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def browse_client_query_key(data: Mapping[str, Any]) -> str:
    values = _browse_values(data)
    return _hash_payload(
        {
            "allowApprox": values["allow_approx"],
            "anchorDate": values["anchor_date"],
            "facetId": values["facet_id"],
            "facetKind": values["facet_kind"],
            "metric": values["metric"],
            "pageSize": values["page_size"],
            "period": values["period"],
            "query": values["query"],
            "safetyProfile": values["safety_profile"],
            "source": values["source"].value,
            "view": values["view"].value,
        }
    )


def facet_client_query_key(data: Mapping[str, Any]) -> str:
    values = _facet_values(data)
    if values["facet_kind"] is None:
        _fail("facet_kind is required")
    return _hash_payload(
        {
            "allowApprox": False,
            "anchorDate": None,
            "facetId": None,
            "facetKind": values["facet_kind"],
            "metric": None,
            "pageSize": values["page_size"],
            "period": None,
            "query": values["query"],
            "safetyProfile": None,
            "source": values["source"].value,
            "view": "category",
        }
    )


def _autocomplete_values(data: Mapping[str, Any]) -> Dict[str, Any]:
    data = _ensure_mapping(data)
    _reject_unknown(data, _AUTOCOMPLETE_FIELDS)
    return {
        "source": _source(data),
        "query": _required_text(data, "query", 256),
        "facet_kind": _name(data, "facet_kind"),
        "page_size": _integer(data, "page_size", 20),
    }


def autocomplete_client_query_key(data: Mapping[str, Any]) -> str:
    values = _autocomplete_values(data)
    return _hash_payload(
        {
            "allowApprox": False,
            "anchorDate": None,
            "facetId": None,
            "facetKind": values["facet_kind"],
            "metric": None,
            "pageSize": values["page_size"],
            "period": None,
            "query": values["query"],
            "safetyProfile": None,
            "source": values["source"].value,
            "view": "search",
        }
    )


def _feature_usable(state: FeatureState) -> bool:
    return state in (FeatureState.SUPPORTED, FeatureState.DEGRADED)


def _check_provider_available(
    capabilities: ProviderCapabilities,
    *,
    local_scope: bool,
) -> None:
    if local_scope:
        return
    if capabilities.auth.required and not capabilities.auth.configured:
        _fail("provider authentication is required", code=ErrorCode.AUTH_REQUIRED, http_status=401)
    if capabilities.availability.state == AvailabilityState.UNAVAILABLE:
        _fail(
            "provider is unavailable",
            code=ErrorCode.NETWORK_UNAVAILABLE,
            http_status=503,
            details={"reason": capabilities.availability.reason},
        )


def validate_browse_request(
    data: Mapping[str, Any],
    *,
    capabilities: Optional[ProviderCapabilities] = None,
    cursor_codec: Optional[OpaqueCursorCodec] = None,
) -> BrowseRequest:
    values = _browse_values(data)
    source = values["source"]
    capabilities = capabilities or get_provider_capabilities(source)
    if capabilities.source != source:
        _fail("capabilities do not match request source")

    view_capability = capabilities.view(values["view"].value)
    if view_capability is None or not _feature_usable(view_capability.state):
        _fail(
            "view is not supported",
            code=ErrorCode.UNSUPPORTED,
            http_status=422,
            details={"reason": None if view_capability is None else view_capability.reason_code},
        )
    _check_provider_available(capabilities, local_scope=view_capability.scope == "local")
    if view_capability.requires_auth and not capabilities.auth.configured:
        _fail("view requires authentication", code=ErrorCode.AUTH_REQUIRED, http_status=401)

    if values["page_size"] < 1 or values["page_size"] > capabilities.limits.max_page_size:
        _fail(
            "page_size is outside provider limits",
            details={"maxPageSize": capabilities.limits.max_page_size},
        )
    if values["safety_profile"] is not None:
        if values["safety_profile"] not in capabilities.features.safety.profiles:
            _fail("unsupported safety_profile", code=ErrorCode.UNSUPPORTED, http_status=422)

    compatible = set(
        capabilities.features.compatible_filters_by_view.get(values["view"].value, ())
    )
    if values["query"] and "query" not in compatible:
        _fail("query is not compatible with this view", code=ErrorCode.UNSUPPORTED, http_status=422)
    if values["safety_profile"] and "safetyProfile" not in compatible:
        _fail(
            "safety_profile is not compatible with this view",
            code=ErrorCode.UNSUPPORTED,
            http_status=422,
        )

    if values["facet_kind"] is not None:
        facet = capabilities.facet(values["facet_kind"])
        if facet is None or not _feature_usable(facet.state) or not facet.filterable:
            _fail("facet is not filterable", code=ErrorCode.UNSUPPORTED, http_status=422)
        if facet.requires_auth and not capabilities.auth.configured:
            _fail("facet requires authentication", code=ErrorCode.AUTH_REQUIRED, http_status=401)
        filter_key = {
            "base_model": "baseModel",
            "model_version": "modelVersion",
            "known_image_tag_id": "knownImageTagId",
        }.get(values["facet_kind"], values["facet_kind"])
        if values["view"] != View.CATEGORY and filter_key not in compatible:
            _fail("facet is not compatible with this view", code=ErrorCode.UNSUPPORTED, http_status=422)

    if values["view"] == View.RANKING:
        ranking = capabilities.ranking(values["metric"], values["period"])
        if ranking is None or not _feature_usable(ranking.state):
            _fail(
                "ranking metric or period is not supported",
                code=ErrorCode.UNSUPPORTED,
                http_status=422,
                details={"metric": values["metric"], "period": values["period"]},
            )
        if ranking.requires_auth and not capabilities.auth.configured:
            _fail("ranking requires authentication", code=ErrorCode.AUTH_REQUIRED, http_status=401)
        if ranking.supports_anchor_date:
            if values["period"] != "all_time" and values["anchor_date"] is None:
                _fail("this ranking requires anchor_date")
        elif values["anchor_date"] is not None:
            _fail("anchor_date is not supported by this ranking")
        if ranking.fidelity == Fidelity.CLIENT_APPROX and not values["allow_approx"]:
            _fail(
                "approximate ranking requires allow_approx=true",
                code=ErrorCode.UNSUPPORTED,
                http_status=422,
            )
        if ranking.fidelity != Fidelity.CLIENT_APPROX and values["allow_approx"]:
            _fail("allow_approx is only valid for approximate ranking")

    expected_key = browse_client_query_key(data)
    declared_key = _declared_query_key(data)
    if not hmac.compare_digest(declared_key, expected_key):
        _fail("client_query_key does not match canonical request")

    cursor_state = None
    if values["cursor"] is not None:
        if cursor_codec is None:
            _fail("cursor codec is required when cursor is present")
        try:
            decoded = cursor_codec.decode(
                values["cursor"],
                expected_source=source.value,
                expected_kind="browse",
                expected_query_key=expected_key,
            )
        except CursorCodecError as exc:
            _fail(str(exc))
        cursor_state = decoded.state

    return BrowseRequest(
        source=source,
        client_request_id=_request_id(data),
        client_query_key=expected_key,
        view=values["view"],
        query=values["query"],
        metric=values["metric"],
        period=values["period"],
        anchor_date=values["anchor_date"],
        facet_kind=values["facet_kind"],
        facet_id=values["facet_id"],
        safety_profile=values["safety_profile"],
        page_size=values["page_size"],
        cursor=values["cursor"],
        allow_approx=values["allow_approx"],
        cursor_state=cursor_state,
    )


def validate_facet_request(
    data: Mapping[str, Any],
    *,
    capabilities: Optional[ProviderCapabilities] = None,
    cursor_codec: Optional[OpaqueCursorCodec] = None,
) -> FacetRequest:
    values = _facet_values(data)
    if values["facet_kind"] is None:
        _fail("facet_kind is required")
    capabilities = capabilities or get_provider_capabilities(values["source"])
    if capabilities.source != values["source"]:
        _fail("capabilities do not match request source")
    category_view = capabilities.view("category")
    if category_view is None or not _feature_usable(category_view.state):
        _fail("category view is not supported", code=ErrorCode.UNSUPPORTED, http_status=422)
    _check_provider_available(capabilities, local_scope=False)
    facet = capabilities.facet(values["facet_kind"])
    if facet is None or not _feature_usable(facet.state) or not facet.listable:
        _fail("facet is not listable", code=ErrorCode.UNSUPPORTED, http_status=422)
    if facet.requires_auth and not capabilities.auth.configured:
        _fail("facet requires authentication", code=ErrorCode.AUTH_REQUIRED, http_status=401)
    if values["page_size"] < 1 or values["page_size"] > capabilities.limits.max_page_size:
        _fail(
            "page_size is outside provider limits",
            details={"maxPageSize": capabilities.limits.max_page_size},
        )

    expected_key = facet_client_query_key(data)
    declared_key = _declared_query_key(data)
    if declared_key != expected_key:
        _fail("client_query_key does not match canonical request")

    cursor_state = None
    if values["cursor"] is not None:
        if cursor_codec is None:
            _fail("cursor codec is required when cursor is present")
        try:
            decoded = cursor_codec.decode(
                values["cursor"],
                expected_source=values["source"].value,
                expected_kind="facet",
                expected_query_key=expected_key,
            )
        except CursorCodecError as exc:
            _fail(str(exc))
        cursor_state = decoded.state

    return FacetRequest(
        source=values["source"],
        client_request_id=_request_id(data),
        client_query_key=expected_key,
        facet_kind=values["facet_kind"],
        query=values["query"],
        page_size=values["page_size"],
        cursor=values["cursor"],
        cursor_state=cursor_state,
    )


def validate_autocomplete_request(
    data: Mapping[str, Any],
    *,
    capabilities: Optional[ProviderCapabilities] = None,
) -> AutocompleteRequest:
    values = _autocomplete_values(data)
    capabilities = capabilities or get_provider_capabilities(values["source"])
    if capabilities.source != values["source"]:
        _fail("capabilities do not match request source")
    _check_provider_available(capabilities, local_scope=False)
    if values["page_size"] < 1 or values["page_size"] > capabilities.limits.max_page_size:
        _fail(
            "page_size is outside provider limits",
            details={"maxPageSize": capabilities.limits.max_page_size},
        )
    if values["facet_kind"] is not None:
        facet = capabilities.facet(values["facet_kind"])
        if facet is None or not _feature_usable(facet.state):
            _fail("facet is not supported", code=ErrorCode.UNSUPPORTED, http_status=422)
        if facet.requires_auth and not capabilities.auth.configured:
            _fail("facet requires authentication", code=ErrorCode.AUTH_REQUIRED, http_status=401)

    expected_key = autocomplete_client_query_key(data)
    declared_key = _declared_query_key(data)
    if not hmac.compare_digest(declared_key, expected_key):
        _fail("client_query_key does not match canonical request")
    return AutocompleteRequest(
        source=values["source"],
        client_request_id=_request_id(data),
        client_query_key=expected_key,
        query=values["query"],
        facet_kind=values["facet_kind"],
        page_size=values["page_size"],
    )


def page_key(query_key: str, request_cursor: Optional[str]) -> str:
    return _hash_payload({"queryKey": query_key, "requestCursor": request_cursor})


def success_envelope(
    *,
    request_id: str,
    client_request_id: str,
    query_key: str,
    items: Sequence[Mapping[str, Any]],
    request_cursor: Optional[str] = None,
    next_cursor: Optional[str] = None,
    ranking: Optional[Mapping[str, Any]] = None,
    provenance: Optional[Mapping[str, Any]] = None,
    applied: Optional[Mapping[str, Any]] = None,
    warnings: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    return {
        "requestId": request_id,
        "clientRequestId": client_request_id,
        "queryKey": query_key,
        "items": [dict(item) for item in items],
        "pageInfo": {
            "nextCursor": next_cursor,
            "pageKey": page_key(query_key, request_cursor),
            "hasNext": next_cursor is not None,
        },
        "ranking": None if ranking is None else dict(ranking),
        "provenance": None if provenance is None else dict(provenance),
        "applied": dict(applied or {}),
        "warnings": [dict(item) for item in warnings],
        "error": None,
    }


def error_envelope(
    *,
    request_id: str,
    client_request_id: str,
    query_key: str,
    error: ProviderError,
    request_cursor: Optional[str] = None,
    warnings: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    return {
        "requestId": request_id,
        "clientRequestId": client_request_id,
        "queryKey": query_key,
        "items": [],
        "pageInfo": {
            "requestCursor": request_cursor,
            "nextCursor": None,
            "pageKey": page_key(query_key, request_cursor),
            "hasNext": None,
        },
        "warnings": [dict(item) for item in warnings],
        "error": error.to_dict(),
    }
