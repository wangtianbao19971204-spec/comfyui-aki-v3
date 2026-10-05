from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


CONTRACT_VERSION = 1


class Source(str, Enum):
    DANBOORU = "danbooru"
    GELBOORU = "gelbooru"
    YANDERE = "yandere"
    CIVITAI = "civitai"


class View(str, Enum):
    LATEST = "latest"
    RANKING = "ranking"
    CATEGORY = "category"
    SEARCH = "search"
    FAVORITES = "favorites"
    FAVORITE_STREAM = "favorite_stream"


class FeatureState(str, Enum):
    SUPPORTED = "supported"
    PROVISIONAL = "provisional"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"


class Fidelity(str, Enum):
    NATIVE = "native"
    SERVER_DERIVED = "server_derived"
    CLIENT_APPROX = "client_approx"
    UNSUPPORTED = "unsupported"


class PeriodSemantics(str, Enum):
    CALENDAR_ANCHOR = "calendar_anchor"
    EXPLICIT_RANGE = "explicit_range"
    ROLLING_CURRENT = "rolling_current"
    BOUNDED_SAMPLE = "bounded_sample"
    NOT_APPLICABLE = "not_applicable"


class AvailabilityState(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED = "unsupported"
    AUTH_REQUIRED = "auth_required"
    AUTH_INVALID = "auth_invalid"
    RATE_LIMITED = "rate_limited"
    PAGINATION_LIMIT = "pagination_limit"
    UPSTREAM_BUSY = "upstream_busy"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    FORBIDDEN = "forbidden"
    UPSTREAM_ERROR = "upstream_error"
    BAD_GATEWAY = "bad_gateway"
    CHALLENGE = "challenge"
    SCHEMA_CHANGED = "schema_changed"
    NETWORK_UNAVAILABLE = "network_unavailable"
    CLIENT_CANCELLED = "client_cancelled"


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


@dataclass(frozen=True)
class FeatureCapability:
    id: str
    state: FeatureState
    reason_code: Optional[str] = None
    requires_auth: bool = False
    scope: str = "public_api"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state.value,
            "reasonCode": self.reason_code,
            "requiresAuth": self.requires_auth,
            "scope": self.scope,
        }


@dataclass(frozen=True)
class RankingCapability:
    metric: str
    periods: Tuple[str, ...]
    fidelity: Fidelity
    basis: str
    period_semantics: PeriodSemantics
    supports_anchor_date: bool
    state: FeatureState = FeatureState.SUPPORTED
    reason_code: Optional[str] = None
    requires_auth: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "state": self.state.value,
            "reasonCode": self.reason_code,
            "requiresAuth": self.requires_auth,
            "periods": list(self.periods),
            "fidelity": self.fidelity.value,
            "basis": self.basis,
            "periodSemantics": self.period_semantics.value,
            "supportsAnchorDate": self.supports_anchor_date,
        }


@dataclass(frozen=True)
class FacetCapability:
    kind: str
    state: FeatureState
    reason_code: Optional[str] = None
    requires_auth: bool = False
    listable: bool = True
    filterable: bool = True
    taxonomy_kind: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "state": self.state.value,
            "reasonCode": self.reason_code,
            "requiresAuth": self.requires_auth,
            "listable": self.listable,
            "filterable": self.filterable,
            "taxonomyKind": self.taxonomy_kind,
        }


@dataclass(frozen=True)
class PaginationCapability:
    kind: str = "opaque_cursor"
    upstream_modes: Tuple[str, ...] = ()
    prefer_cursor: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "upstreamModes": list(self.upstream_modes),
            "preferCursor": self.prefer_cursor,
        }


@dataclass(frozen=True)
class SafetyCapability:
    kind: str
    profiles: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "profiles": list(self.profiles)}


@dataclass(frozen=True)
class ProviderFeatures:
    views: Tuple[FeatureCapability, ...]
    ranking: Tuple[RankingCapability, ...]
    facets: Tuple[FacetCapability, ...]
    compatible_filters_by_view: Mapping[str, Tuple[str, ...]]
    pagination: PaginationCapability
    safety: SafetyCapability

    def to_dict(self) -> Dict[str, Any]:
        return {
            "views": [item.to_dict() for item in self.views],
            "ranking": [item.to_dict() for item in self.ranking],
            "facets": [item.to_dict() for item in self.facets],
            "compatibleFiltersByView": {
                key: list(value) for key, value in self.compatible_filters_by_view.items()
            },
            "pagination": self.pagination.to_dict(),
            "safety": self.safety.to_dict(),
        }


@dataclass(frozen=True)
class ProviderAvailability:
    state: AvailabilityState = AvailabilityState.AVAILABLE
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"state": self.state.value, "reason": self.reason}


@dataclass(frozen=True)
class ProviderAuth:
    required: bool
    configured: bool
    mode: str
    recommended: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required": self.required,
            "configured": self.configured,
            "mode": self.mode,
            "recommended": self.recommended,
        }


@dataclass(frozen=True)
class ProviderLimits:
    max_page_size: int
    published_rate: Optional[str] = None
    max_offset_items: Optional[int] = None
    anonymous_tag_limit: Optional[int] = None
    notes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "maxPageSize": self.max_page_size,
            "publishedRate": self.published_rate,
            "maxOffsetItems": self.max_offset_items,
            "anonymousTagLimit": self.anonymous_tag_limit,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ProviderCapabilities:
    source: Source
    features: ProviderFeatures
    availability: ProviderAvailability
    auth: ProviderAuth
    limits: ProviderLimits
    schema_version: int = CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "source": self.source.value,
            "features": self.features.to_dict(),
            "availability": self.availability.to_dict(),
            "auth": self.auth.to_dict(),
            "limits": self.limits.to_dict(),
        }

    def view(self, view: str) -> Optional[FeatureCapability]:
        return next((item for item in self.features.views if item.id == view), None)

    def ranking(self, metric: str, period: str) -> Optional[RankingCapability]:
        return next(
            (
                item
                for item in self.features.ranking
                if item.metric == metric and period in item.periods
            ),
            None,
        )

    def facet(self, kind: str) -> Optional[FacetCapability]:
        return next((item for item in self.features.facets if item.kind == kind), None)


@dataclass(frozen=True)
class ProviderRuntime:
    availability: AvailabilityState = AvailabilityState.AVAILABLE
    reason: Optional[str] = None
    auth_configured: bool = False
    auth_required: Optional[bool] = None
    feature_states: Mapping[str, FeatureState] = field(default_factory=dict)
    feature_reasons: Mapping[str, Optional[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowseRequest:
    source: Source
    client_request_id: str
    client_query_key: str
    view: View
    query: Optional[str]
    metric: Optional[str]
    period: Optional[str]
    anchor_date: Optional[str]
    facet_kind: Optional[str]
    facet_id: Optional[str]
    safety_profile: Optional[str]
    page_size: int
    cursor: Optional[str]
    allow_approx: bool
    cursor_state: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class FacetRequest:
    source: Source
    client_request_id: str
    client_query_key: str
    facet_kind: str
    query: Optional[str]
    page_size: int
    cursor: Optional[str]
    cursor_state: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class AutocompleteRequest:
    source: Source
    client_request_id: str
    client_query_key: str
    query: str
    facet_kind: Optional[str]
    page_size: int


@dataclass(frozen=True)
class ProviderError:
    code: ErrorCode
    http_status: int
    retryable: bool
    message: str
    retry_after_seconds: Optional[float] = None
    details: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "code": self.code.value,
            "httpStatus": self.http_status,
            "retryable": self.retryable,
            "retryAfterSeconds": self.retry_after_seconds,
            "message": self.message,
        }
        if self.details:
            result["details"] = dict(self.details)
        return result


class ContractValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.INVALID_REQUEST,
        http_status: int = 400,
        retryable: bool = False,
        retry_after_seconds: Optional[float] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error = ProviderError(
            code=code,
            http_status=http_status,
            retryable=retryable,
            message=message,
            retry_after_seconds=retry_after_seconds,
            details=details,
        )


class ProviderPayloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderPage:
    items: Tuple[Mapping[str, Any], ...]
    next_cursor: Optional[str] = None
    ranking: Optional[Mapping[str, Any]] = None
    provenance: Optional[Mapping[str, Any]] = None
    applied: Mapping[str, Any] = field(default_factory=dict)
    warnings: Tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class FacetPage:
    items: Tuple[Mapping[str, Any], ...]
    next_cursor: Optional[str] = None
    warnings: Tuple[Mapping[str, Any], ...] = ()
