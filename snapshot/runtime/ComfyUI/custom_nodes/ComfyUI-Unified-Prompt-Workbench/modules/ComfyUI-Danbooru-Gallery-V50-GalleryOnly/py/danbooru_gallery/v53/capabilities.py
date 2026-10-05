from __future__ import annotations

from dataclasses import replace
from typing import Dict, Iterable, Mapping, Optional, Tuple

from .domain import (
    AvailabilityState,
    FacetCapability,
    FeatureCapability,
    FeatureState,
    Fidelity,
    PaginationCapability,
    PeriodSemantics,
    ProviderAuth,
    ProviderAvailability,
    ProviderCapabilities,
    ProviderFeatures,
    ProviderLimits,
    ProviderRuntime,
    RankingCapability,
    SafetyCapability,
    Source,
)


PERIODS = ("day", "week", "month", "year", "all_time")


def _view(
    name: str,
    state: FeatureState = FeatureState.SUPPORTED,
    reason: Optional[str] = None,
    *,
    scope: str = "public_api",
    requires_auth: bool = False,
) -> FeatureCapability:
    return FeatureCapability(name, state, reason, requires_auth, scope)


def _rank(
    metric: str,
    periods: Iterable[str],
    fidelity: Fidelity,
    basis: str,
    semantics: PeriodSemantics,
    supports_anchor: bool,
    state: FeatureState = FeatureState.SUPPORTED,
    reason: Optional[str] = None,
) -> RankingCapability:
    return RankingCapability(
        metric=metric,
        periods=tuple(periods),
        fidelity=fidelity,
        basis=basis,
        period_semantics=semantics,
        supports_anchor_date=supports_anchor,
        state=state,
        reason_code=reason,
    )


def _facet(
    kind: str,
    state: FeatureState = FeatureState.SUPPORTED,
    reason: Optional[str] = None,
    *,
    listable: bool = True,
    filterable: bool = True,
    taxonomy_kind: Optional[str] = None,
) -> FacetCapability:
    return FacetCapability(
        kind=kind,
        state=state,
        reason_code=reason,
        listable=listable,
        filterable=filterable,
        taxonomy_kind=taxonomy_kind,
    )


def _danbooru() -> ProviderCapabilities:
    return ProviderCapabilities(
        source=Source.DANBOORU,
        features=ProviderFeatures(
            views=(
                _view("latest"),
                _view("ranking"),
                _view("category"),
                _view("search"),
                _view("favorites", scope="local"),
                _view("favorite_stream"),
            ),
            ranking=(
                _rank(
                    "popular",
                    ("day", "week", "month"),
                    Fidelity.NATIVE,
                    "dedicated_popular_endpoint",
                    PeriodSemantics.CALENDAR_ANCHOR,
                    True,
                ),
                _rank(
                    "favorites",
                    ("all_time",),
                    Fidelity.SERVER_DERIVED,
                    "official_field_sort",
                    PeriodSemantics.NOT_APPLICABLE,
                    False,
                ),
                _rank(
                    "score",
                    ("all_time",),
                    Fidelity.SERVER_DERIVED,
                    "official_field_sort",
                    PeriodSemantics.NOT_APPLICABLE,
                    False,
                ),
            ),
            facets=tuple(
                _facet(name, taxonomy_kind="image_tag")
                for name in ("general", "artist", "copyright", "character", "meta")
            ),
            compatible_filters_by_view={
                "latest": ("query", "safetyProfile"),
                "search": ("query", "safetyProfile"),
                "ranking": ("anchorDate",),
                "category": ("query",),
                # Local favorite ids are resolved as stored. Query/safety are not
                # evaluated and therefore must not be advertised as compatible.
                "favorites": (),
                "favorite_stream": (),
            },
            pagination=PaginationCapability(
                upstream_modes=("posts_id_cursor", "numeric_page"),
            ),
            safety=SafetyCapability(
                "booru_rating",
                ("all", "general", "sensitive", "questionable", "explicit"),
            ),
        ),
        availability=ProviderAvailability(),
        auth=ProviderAuth(False, False, "query_or_basic", recommended=False),
        limits=ProviderLimits(
            max_page_size=200,
            published_rate="10 requests/second shared by account and IP",
            anonymous_tag_limit=2,
            notes=("page and search-tag limits vary by account level",),
        ),
    )


def _gelbooru() -> ProviderCapabilities:
    return ProviderCapabilities(
        source=Source.GELBOORU,
        features=ProviderFeatures(
            views=(
                _view("latest"),
                _view("ranking"),
                _view("category"),
                _view("search"),
                _view(
                    "favorites",
                    FeatureState.UNSUPPORTED,
                    "local_favorites_unavailable",
                    scope="local",
                ),
            ),
            ranking=(
                _rank(
                    "score",
                    ("all_time",),
                    Fidelity.SERVER_DERIVED,
                    "official_field_sort",
                    PeriodSemantics.NOT_APPLICABLE,
                    False,
                ),
                _rank(
                    "score_approx",
                    ("day", "week", "month"),
                    Fidelity.CLIENT_APPROX,
                    "bounded_recent_id_sample",
                    PeriodSemantics.BOUNDED_SAMPLE,
                    True,
                    FeatureState.PROVISIONAL,
                    "approx_disabled_by_default",
                ),
            ),
            facets=(
                _facet("tag_cumulative", taxonomy_kind="image_tag"),
                _facet(
                    "tag_category_annotation",
                    FeatureState.DEGRADED,
                    "category_filter_not_documented",
                    listable=False,
                    filterable=False,
                    taxonomy_kind="image_tag",
                ),
            ),
            compatible_filters_by_view={
                "latest": ("query", "safetyProfile"),
                "search": ("query", "safetyProfile"),
                "ranking": ("query", "safetyProfile", "anchorDate"),
                "category": ("query",),
                "favorites": (),
            },
            pagination=PaginationCapability(
                upstream_modes=("dapi_pid_zero_based", "html_thumbnail_offset", "bounded_tag_scan"),
            ),
            safety=SafetyCapability(
                "booru_rating",
                ("all", "general", "sensitive", "questionable", "explicit"),
            ),
        ),
        availability=ProviderAvailability(),
        auth=ProviderAuth(False, False, "query", recommended=True),
        limits=ProviderLimits(
            max_page_size=100,
            published_rate=None,
            notes=("account-specific throttling; API credentials may be required",),
        ),
    )


def _yandere() -> ProviderCapabilities:
    return ProviderCapabilities(
        source=Source.YANDERE,
        features=ProviderFeatures(
            views=(
                _view("latest"),
                _view("ranking", FeatureState.PROVISIONAL, "contract_verification_required"),
                _view("category"),
                _view("search"),
                _view(
                    "favorites",
                    FeatureState.UNSUPPORTED,
                    "local_favorites_unavailable",
                    scope="local",
                ),
            ),
            ranking=(
                _rank(
                    "score_period",
                    ("day", "week", "month", "year"),
                    Fidelity.SERVER_DERIVED,
                    "official_date_range_score_sort",
                    PeriodSemantics.EXPLICIT_RANGE,
                    True,
                    FeatureState.PROVISIONAL,
                    "contract_verification_required",
                ),
            ),
            facets=(
                _facet("tag", taxonomy_kind="image_tag"),
                _facet("related_tag", taxonomy_kind="image_tag"),
                _facet(
                    "tag_type_annotation",
                    listable=False,
                    filterable=False,
                    taxonomy_kind="image_tag",
                ),
                _facet(
                    "category_listing",
                    FeatureState.UNSUPPORTED,
                    "category_filter_not_documented",
                    listable=False,
                    filterable=False,
                    taxonomy_kind="image_tag",
                ),
            ),
            compatible_filters_by_view={
                "latest": ("query", "safetyProfile"),
                "search": ("query", "safetyProfile"),
                "ranking": ("query", "safetyProfile", "anchorDate"),
                "category": ("query",),
                "favorites": (),
            },
            pagination=PaginationCapability(upstream_modes=("page_one_based",)),
            safety=SafetyCapability(
                "moebooru_rating",
                ("all", "safe", "questionable", "explicit"),
            ),
        ),
        availability=ProviderAvailability(),
        auth=ProviderAuth(False, False, "legacy_query", recommended=False),
        limits=ProviderLimits(
            max_page_size=100,
            published_rate=None,
            notes=("HTTP 421 means throttled; no numeric public rate is documented",),
        ),
    )


def _civitai() -> ProviderCapabilities:
    return ProviderCapabilities(
        source=Source.CIVITAI,
        features=ProviderFeatures(
            views=(
                _view("latest"),
                _view("ranking"),
                _view("category"),
                # Keep the view available while offline because a local snapshot
                # remains a valid fallback; runtime provenance reports remote use.
                _view("favorites", scope="local"),
                _view(
                    "search",
                    FeatureState.DEGRADED,
                    "search_authorization_required",
                    scope="experimental_web",
                    requires_auth=True,
                ),
            ),
            ranking=(
                _rank(
                    "reactions",
                    PERIODS,
                    Fidelity.NATIVE,
                    "official_metric_sort",
                    PeriodSemantics.ROLLING_CURRENT,
                    False,
                ),
                _rank(
                    "comments",
                    PERIODS,
                    Fidelity.NATIVE,
                    "official_metric_sort",
                    PeriodSemantics.ROLLING_CURRENT,
                    False,
                ),
                _rank(
                    "collected",
                    PERIODS,
                    Fidelity.NATIVE,
                    "official_metric_sort",
                    PeriodSemantics.ROLLING_CURRENT,
                    False,
                    FeatureState.PROVISIONAL,
                    "contract_and_live_verification_required",
                ),
            ),
            facets=(
                _facet("model", taxonomy_kind="model"),
                _facet("model_version", taxonomy_kind="model_version"),
                _facet("creator", taxonomy_kind="creator"),
                # /api/v1/tags currently lists names without the numeric image-tag
                # ids required by /api/v1/images?tags=. It is browseable as a
                # taxonomy, but cannot truthfully drive image category filtering.
                _facet("model_taxonomy", filterable=False, taxonomy_kind="model_tag"),
                _facet("base_model", taxonomy_kind="base_model"),
                _facet(
                    "known_image_tag_id",
                    FeatureState.DEGRADED,
                    "image_tag_discovery_unavailable",
                    listable=False,
                    filterable=True,
                    taxonomy_kind="image_tag_id",
                ),
                _facet(
                    "media_type",
                    FeatureState.UNSUPPORTED,
                    "media_fixed_to_image_in_v53",
                    listable=False,
                    filterable=False,
                    taxonomy_kind="media_type",
                ),
            ),
            compatible_filters_by_view={
                "latest": ("safetyProfile", "model", "creator", "baseModel", "modelVersion"),
                "ranking": (
                    "safetyProfile",
                    "model",
                    "creator",
                    "baseModel",
                    "modelVersion",
                    "knownImageTagId",
                ),
                "category": ("safetyProfile",),
                "search": ("query",),
                # The local snapshot is intentionally not post-filtered here.
                "favorites": (),
            },
            pagination=PaginationCapability(
                upstream_modes=("metadata_next_cursor",),
                prefer_cursor=True,
            ),
            safety=SafetyCapability(
                "civitai_browsing_level",
                ("all", "general", "sfw", "nsfw"),
            ),
        ),
        availability=ProviderAvailability(),
        auth=ProviderAuth(False, False, "bearer", recommended=False),
        limits=ProviderLimits(
            max_page_size=200,
            published_rate=None,
            max_offset_items=1000,
            notes=(
                "public API origin order is https://civitai.red/api/v1 primary, https://civitai.com/api/v1 fallback",
                "deep page offsets return pagination_limit; follow nextCursor",
                "HTTP 503 may include Retry-After: 2",
                "free-text image search uses the authenticated experimental web index",
            ),
        ),
    )


_BASE_CAPABILITIES: Mapping[Source, ProviderCapabilities] = {
    Source.DANBOORU: _danbooru(),
    Source.GELBOORU: _gelbooru(),
    Source.YANDERE: _yandere(),
    Source.CIVITAI: _civitai(),
}


def _state(value: object) -> FeatureState:
    if isinstance(value, FeatureState):
        return value
    return FeatureState(str(value))


def _override_reason(
    key: str,
    old_reason: Optional[str],
    new_state: FeatureState,
    runtime: ProviderRuntime,
) -> Optional[str]:
    if key in runtime.feature_reasons:
        return runtime.feature_reasons[key]
    if new_state == FeatureState.SUPPORTED:
        return None
    return old_reason or "runtime_override"


def _apply_runtime(
    base: ProviderCapabilities,
    runtime: ProviderRuntime,
) -> ProviderCapabilities:
    views = []
    for item in base.features.views:
        key = "view:%s" % item.id
        if key in runtime.feature_states:
            state = _state(runtime.feature_states[key])
            item = replace(
                item,
                state=state,
                reason_code=_override_reason(key, item.reason_code, state, runtime),
            )
        views.append(item)

    rankings = []
    for item in base.features.ranking:
        key = "ranking:%s" % item.metric
        if key in runtime.feature_states:
            state = _state(runtime.feature_states[key])
            item = replace(
                item,
                state=state,
                reason_code=_override_reason(key, item.reason_code, state, runtime),
            )
        rankings.append(item)

    facets = []
    for item in base.features.facets:
        key = "facet:%s" % item.kind
        if key in runtime.feature_states:
            state = _state(runtime.feature_states[key])
            item = replace(
                item,
                state=state,
                reason_code=_override_reason(key, item.reason_code, state, runtime),
            )
        facets.append(item)

    availability_reason = runtime.reason
    if runtime.availability != AvailabilityState.AVAILABLE and not availability_reason:
        availability_reason = "runtime_%s" % runtime.availability.value

    return replace(
        base,
        features=replace(
            base.features,
            views=tuple(views),
            ranking=tuple(rankings),
            facets=tuple(facets),
        ),
        availability=ProviderAvailability(runtime.availability, availability_reason),
        auth=replace(
            base.auth,
            required=(
                runtime.auth_required
                if runtime.auth_required is not None
                else base.auth.required
            ),
            configured=runtime.auth_configured,
        ),
    )


def get_provider_capabilities(
    source: object,
    runtime: Optional[ProviderRuntime] = None,
) -> ProviderCapabilities:
    try:
        source_enum = source if isinstance(source, Source) else Source(str(source).lower())
    except (TypeError, ValueError):
        raise ValueError("unknown provider source: %r" % (source,))
    base = _BASE_CAPABILITIES[source_enum]
    return _apply_runtime(base, runtime or ProviderRuntime())


def all_provider_capabilities(
    runtimes: Optional[Mapping[object, ProviderRuntime]] = None,
) -> Tuple[ProviderCapabilities, ...]:
    runtimes = runtimes or {}
    result = []
    for source in Source:
        runtime = runtimes.get(source) or runtimes.get(source.value)
        result.append(get_provider_capabilities(source, runtime))
    return tuple(result)
