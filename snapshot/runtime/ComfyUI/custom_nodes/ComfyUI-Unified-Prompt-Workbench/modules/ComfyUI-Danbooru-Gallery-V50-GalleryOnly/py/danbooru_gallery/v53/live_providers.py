from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .capabilities import get_provider_capabilities
from .cursor import OpaqueCursorCodec
from .domain import (
    AutocompleteRequest,
    AvailabilityState,
    BrowseRequest,
    ErrorCode,
    FacetPage,
    FacetRequest,
    FeatureState,
    ProviderCapabilities,
    ProviderError,
    ProviderPage,
    ProviderPayloadError,
    ProviderRuntime,
    Source,
    View,
)
from .providers import GalleryProvider


CIVITAI_API_ROOT = "https://civitai.red/api/v1"
CIVITAI_API_FALLBACK_ROOT = "https://civitai.com/api/v1"
CIVITAI_API_ROOTS = (CIVITAI_API_ROOT, CIVITAI_API_FALLBACK_ROOT)

# Provider calls are blocking HTTP/normalization work. Keep them off asyncio's
# process-wide default executor and cap submitted work as well as worker count so a
# burst cannot build an unbounded queue shared with unrelated ComfyUI components.
_PROVIDER_EXECUTOR_MAX_WORKERS = 4
_PROVIDER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_PROVIDER_EXECUTOR_MAX_WORKERS,
    thread_name_prefix="danbooru-gallery-v53",
)
_PROVIDER_EXECUTOR_BUDGET = threading.BoundedSemaphore(_PROVIDER_EXECUTOR_MAX_WORKERS)
_PROVIDER_SUCCESS_CACHE_TTL_SECONDS = 2.0
_PROVIDER_SUCCESS_CACHE_MAX_ENTRIES = 64


class ProviderRequestError(RuntimeError):
    """A sanitized provider failure suitable for the V2 error envelope."""

    def __init__(self, error: ProviderError) -> None:
        super().__init__(error.message)
        self.error = error


def _provider_error(
    code: ErrorCode,
    status: int,
    message: str,
    *,
    retryable: bool = False,
    retry_after: Optional[float] = None,
    details: Optional[Mapping[str, Any]] = None,
) -> ProviderRequestError:
    return ProviderRequestError(
        ProviderError(
            code=code,
            http_status=status,
            retryable=retryable,
            retry_after_seconds=retry_after,
            message=message,
            details=details,
        )
    )


def _retry_after(response: Any) -> Optional[float]:
    try:
        value = response.headers.get("Retry-After")
        return None if value is None else max(0.0, float(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _response_failure(
    source: Source,
    response: Any,
    context: str,
    *,
    deep_cursor: bool = False,
) -> ProviderRequestError:
    status = int(getattr(response, "status_code", 0) or 0)
    retry_after = _retry_after(response)
    if status == 400:
        return _provider_error(ErrorCode.INVALID_REQUEST, 400, "%s rejected the request" % context)
    if status == 401:
        return _provider_error(ErrorCode.AUTH_INVALID, 401, "%s authentication failed" % context)
    if status == 403:
        challenge = False
        text = str(getattr(response, "text", "") or "").lower()
        if "cloudflare" in text or "cf-chl" in text or "just a moment" in text:
            challenge = True
        return _provider_error(
            ErrorCode.CHALLENGE if challenge else ErrorCode.FORBIDDEN,
            403,
            "%s was refused" % context,
        )
    if status in (421, 429):
        if source == Source.CIVITAI and deep_cursor:
            return _provider_error(
                ErrorCode.PAGINATION_LIMIT,
                429,
                "Civitai deep pagination limit reached; restart from the first page",
                retryable=False,
                retry_after=retry_after,
            )
        return _provider_error(
            ErrorCode.RATE_LIMITED,
            429,
            "%s is rate limited" % context,
            retryable=True,
            retry_after=retry_after,
        )
    if status in (408, 504):
        return _provider_error(
            ErrorCode.UPSTREAM_TIMEOUT,
            504,
            "%s timed out" % context,
            retryable=True,
        )
    if status == 503:
        return _provider_error(
            ErrorCode.UPSTREAM_BUSY,
            503,
            "%s is temporarily unavailable" % context,
            retryable=True,
            retry_after=retry_after,
        )
    return _provider_error(
        ErrorCode.BAD_GATEWAY,
        502,
        "%s returned an unexpected status" % context,
        retryable=status >= 500 or status == 0,
        details={"upstreamStatus": status or None},
    )


def normalize_provider_exception(source: Source, exc: BaseException, context: str) -> ProviderRequestError:
    if isinstance(exc, ProviderRequestError):
        return exc
    legacy_code = str(getattr(exc, "code", "") or "")
    if legacy_code:
        try:
            code = ErrorCode(legacy_code)
        except ValueError:
            code = ErrorCode.UPSTREAM_ERROR
        return _provider_error(
            code,
            int(getattr(exc, "http_status", 502) or 502),
            str(getattr(exc, "public_message", "") or (context + " failed")),
            retryable=bool(getattr(exc, "retryable", False)),
            retry_after=getattr(exc, "retry_after_seconds", None),
        )
    response = getattr(exc, "response", None)
    if response is not None:
        return _response_failure(source, response, context)
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return _provider_error(ErrorCode.UPSTREAM_TIMEOUT, 504, context + " timed out", retryable=True)
    if any(token in name for token in ("connection", "proxy", "ssl")):
        return _provider_error(
            ErrorCode.NETWORK_UNAVAILABLE,
            502,
            context + " network is unavailable",
            retryable=True,
        )
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return _provider_error(ErrorCode.SCHEMA_CHANGED, 502, context + " returned invalid JSON")
    return _provider_error(ErrorCode.UPSTREAM_ERROR, 502, context + " failed")


def _json(response: Any, source: Source, context: str, *, deep_cursor: bool = False) -> Any:
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        raise _response_failure(source, response, context, deep_cursor=deep_cursor)
    try:
        return response.json()
    except Exception as exc:
        raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, context + " returned invalid JSON") from exc


def _mapping_items(items: Iterable[Any], context: str) -> Tuple[Mapping[str, Any], ...]:
    result = []
    for item in items:
        if not isinstance(item, Mapping):
            raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, context + " returned a non-object item")
        result.append(dict(item))
    return tuple(result)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _page_number(state: Optional[Mapping[str, Any]], *, default: int = 1) -> int:
    if not state:
        return default
    page = _safe_int(state.get("page"), 0)
    if page < 1:
        raise _provider_error(ErrorCode.INVALID_REQUEST, 400, "cursor contains an invalid page")
    return page


def _offset(state: Optional[Mapping[str, Any]]) -> int:
    if not state:
        return 0
    value = _safe_int(state.get("offset"), -1)
    if value < 0:
        raise _provider_error(ErrorCode.INVALID_REQUEST, 400, "cursor contains an invalid offset")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _facet_item(
    item_id: Any,
    label: Any,
    kind: str,
    *,
    category: Optional[str] = None,
    count: Optional[int] = None,
    count_kind: Optional[str] = None,
) -> Mapping[str, Any]:
    return {
        "id": str(item_id),
        "label": str(label),
        "kind": kind,
        "category": category,
        "itemCount": count,
        "countKind": count_kind,
        "state": "supported",
    }


class LiveProviderBase(GalleryProvider):
    def __init__(self, legacy: Any, cursor_codec: OpaqueCursorCodec) -> None:
        self.legacy = legacy
        self.cursor_codec = cursor_codec
        # One re-entrant lock makes the inflight -> success-cache transition atomic:
        # callers always observe either the live future or its cached result.
        self._singleflight_lock = threading.RLock()
        self._singleflight: Dict[
            Tuple[str, str, str, str], concurrent.futures.Future[Any]
        ] = {}
        self._success_cache_lock = self._singleflight_lock
        self._success_cache: OrderedDict[
            Tuple[str, str, str, str], Tuple[float, Any]
        ] = OrderedDict()

    def _runtime(self) -> ProviderRuntime:
        return ProviderRuntime()

    def capabilities(self) -> ProviderCapabilities:
        return get_provider_capabilities(self.source, self._runtime())

    def _success_cache_allowed(self) -> bool:
        try:
            return not bool(self._runtime().auth_configured)
        except Exception:
            # Unknown auth state is treated conservatively: single-flight remains
            # available, but no result survives beyond the active request.
            return False

    def _cached_success(
        self, key: Tuple[str, str, str, str],
    ) -> Optional[Any]:
        now = time.monotonic()
        with self._success_cache_lock:
            for cached_key, (expires_at, _value) in tuple(self._success_cache.items()):
                if expires_at <= now:
                    self._success_cache.pop(cached_key, None)
            entry = self._success_cache.get(key)
            if entry is None:
                return None
            self._success_cache.move_to_end(key)
            return entry[1]

    @staticmethod
    def _cacheable_success(key: Tuple[str, str, str, str], result: Any) -> bool:
        operation = key[0]
        if operation == "browse":
            return isinstance(result, ProviderPage)
        if operation == "facets":
            return isinstance(result, FacetPage)
        if operation == "autocomplete":
            return isinstance(result, tuple) and all(
                isinstance(item, Mapping) for item in result
            )
        return False

    def _remember_success(
        self, key: Tuple[str, str, str, str], result: Any,
    ) -> None:
        if not self._success_cache_allowed():
            with self._success_cache_lock:
                self._success_cache.clear()
            return
        ttl = max(0.0, float(_PROVIDER_SUCCESS_CACHE_TTL_SECONDS))
        limit = max(0, int(_PROVIDER_SUCCESS_CACHE_MAX_ENTRIES))
        if ttl <= 0 or limit <= 0 or not self._cacheable_success(key, result):
            return
        now = time.monotonic()
        with self._success_cache_lock:
            for cached_key, (expires_at, _value) in tuple(self._success_cache.items()):
                if expires_at <= now:
                    self._success_cache.pop(cached_key, None)
            self._success_cache[key] = (now + ttl, result)
            self._success_cache.move_to_end(key)
            while len(self._success_cache) > limit:
                self._success_cache.popitem(last=False)

    async def _thread(
        self,
        function: Any,
        *args: Any,
        singleflight_key: Optional[Tuple[str, str, str, str]] = None,
        cache_success: bool = False,
    ) -> Any:
        """Run one blocking call under the plugin budget, sharing identical work."""

        async def await_future(future: concurrent.futures.Future[Any]) -> Any:
            # One disconnected browser must not cancel a future shared by another
            # caller. The worker/budget are released only when the real future ends.
            return await asyncio.shield(asyncio.wrap_future(future))

        if cache_success and not self._success_cache_allowed():
            with self._success_cache_lock:
                self._success_cache.clear()
            cache_success = False

        if cache_success and singleflight_key is not None:
            cached = self._cached_success(singleflight_key)
            if cached is not None:
                return cached

        if singleflight_key is not None:
            with self._singleflight_lock:
                existing = self._singleflight.get(singleflight_key)
            if existing is not None:
                return await await_future(existing)

        budget = _PROVIDER_EXECUTOR_BUDGET
        if not budget.acquire(blocking=False):
            raise _provider_error(
                ErrorCode.UPSTREAM_BUSY,
                503,
                "gallery provider worker capacity is exhausted",
                retryable=True,
                retry_after=1.0,
            )

        try:
            if singleflight_key is not None:
                # Calls may arrive from more than one event-loop thread. Recheck and
                # reserve cache/inflight state atomically so exactly one future is
                # submitted even while a prior future is moving into the TTL cache.
                cached_after_budget = None
                with self._singleflight_lock:
                    if cache_success:
                        cached_after_budget = self._cached_success(singleflight_key)
                    existing = (
                        None
                        if cached_after_budget is not None
                        else self._singleflight.get(singleflight_key)
                    )
                    if cached_after_budget is None and existing is None:
                        future = _PROVIDER_EXECUTOR.submit(function, *args)
                        self._singleflight[singleflight_key] = future
                if cached_after_budget is not None:
                    budget.release()
                    return cached_after_budget
                if existing is not None:
                    budget.release()
                    return await await_future(existing)
            else:
                future = _PROVIDER_EXECUTOR.submit(function, *args)
        except Exception as exc:
            budget.release()
            raise _provider_error(
                ErrorCode.UPSTREAM_BUSY,
                503,
                "gallery provider worker capacity is unavailable",
                retryable=True,
                retry_after=1.0,
            ) from exc

        def release(done: concurrent.futures.Future[Any]) -> None:
            if singleflight_key is not None:
                with self._singleflight_lock:
                    if cache_success:
                        try:
                            result = done.result()
                        except BaseException:
                            pass
                        else:
                            self._remember_success(singleflight_key, result)
                    if self._singleflight.get(singleflight_key) is done:
                        self._singleflight.pop(singleflight_key, None)
            budget.release()

        future.add_done_callback(release)
        return await await_future(future)

    async def browse(self, request: BrowseRequest) -> ProviderPage:
        if request.source != self.source:
            raise ValueError("request source does not match provider source")
        try:
            return await self._thread(
                self._browse_sync,
                request,
                singleflight_key=(
                    "browse",
                    self.source.value,
                    request.client_query_key,
                    request.cursor or "",
                ),
                cache_success=True,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise normalize_provider_exception(self.source, exc, self.source.value + " browse") from exc

    async def list_facets(self, request: FacetRequest) -> FacetPage:
        if request.source != self.source:
            raise ValueError("request source does not match provider source")
        try:
            return await self._thread(
                self._facets_sync,
                request,
                singleflight_key=(
                    "facets",
                    self.source.value,
                    request.client_query_key,
                    request.cursor or "",
                ),
                cache_success=True,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise normalize_provider_exception(self.source, exc, self.source.value + " facets") from exc

    async def autocomplete(self, request: AutocompleteRequest) -> Tuple[Mapping[str, Any], ...]:
        if request.source != self.source:
            raise ValueError("request source does not match provider source")
        try:
            return await self._thread(
                self._autocomplete_sync,
                request,
                singleflight_key=(
                    "autocomplete",
                    self.source.value,
                    request.client_query_key,
                    "",
                ),
                cache_success=True,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise normalize_provider_exception(self.source, exc, self.source.value + " autocomplete") from exc

    async def get_post(self, post_id: str) -> Optional[Mapping[str, Any]]:
        def load() -> Optional[Mapping[str, Any]]:
            result = self.legacy.DanbooruGalleryNode.get_post_by_id_internal(post_id, self.source.value)
            if isinstance(result, tuple) and len(result) == 1:
                result = result[0]
            if isinstance(result, str):
                result = json.loads(result)
            if isinstance(result, list) and result and isinstance(result[0], Mapping):
                return dict(result[0])
            return None

        try:
            return await self._thread(
                load,
                singleflight_key=("get_post", self.source.value, str(post_id), ""),
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise normalize_provider_exception(self.source, exc, self.source.value + " get_post") from exc

    def _cursor(self, request_kind: str, query_key: str, state: Mapping[str, Any]) -> str:
        return self.cursor_codec.encode(
            source=self.source.value,
            request_kind=request_kind,
            query_key=query_key,
            state=state,
        )

    def _structured_favorites(self) -> Tuple[Mapping[str, Any], ...]:
        loader = getattr(self.legacy, "load_civitai_favorites", None)
        if not callable(loader):
            return ()
        result = []
        for item in loader() or ():
            if not isinstance(item, Mapping):
                continue
            source = str(item.get("source_site") or item.get("source") or "civitai").lower()
            if source == self.source.value:
                result.append(dict(item))
        return tuple(result)

    def _local_favorites_page(self, request: BrowseRequest) -> ProviderPage:
        items = self._structured_favorites()
        offset = _offset(request.cursor_state)
        page_items = items[offset : offset + request.page_size]
        next_offset = offset + len(page_items)
        next_cursor = None
        if next_offset < len(items):
            next_cursor = self._cursor("browse", request.client_query_key, {"offset": next_offset})
        return ProviderPage(
            items=page_items,
            next_cursor=next_cursor,
            provenance={"kind": "local", "endpoint": "local_favorites"},
            applied={"requestTime": _utc_now()},
        )

    def _browse_sync(self, request: BrowseRequest) -> ProviderPage:
        raise NotImplementedError

    def _facets_sync(self, request: FacetRequest) -> FacetPage:
        raise NotImplementedError

    def _autocomplete_sync(self, request: AutocompleteRequest) -> Tuple[Mapping[str, Any], ...]:
        raise NotImplementedError


class DanbooruLiveProvider(LiveProviderBase):
    source = Source.DANBOORU
    _TAG_CATEGORIES = {"general": 0, "artist": 1, "copyright": 3, "character": 4, "meta": 5}

    def _runtime(self) -> ProviderRuntime:
        configured = False
        try:
            username, api_key = self.legacy.load_user_auth()
            configured = bool(username and api_key)
        except Exception:
            pass
        return ProviderRuntime(auth_configured=configured)

    def _posts(self, request: BrowseRequest, tags: Sequence[str], endpoint: str = "/posts.json") -> ProviderPage:
        page = _page_number(request.cursor_state)
        params = {"tags": " ".join(item for item in tags if item), "limit": request.page_size, "page": page}
        auth = getattr(self.legacy, "_with_danbooru_auth_params", None)
        if callable(auth):
            params = auth(params)
        response = self.legacy._danbooru_request(
            "GET", "https://danbooru.donmai.us" + endpoint, params=params, timeout=30
        )
        data = _json(response, self.source, "Danbooru posts")
        if not isinstance(data, list):
            raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Danbooru posts response shape changed")
        items = []
        for raw in data:
            if not isinstance(raw, Mapping):
                raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Danbooru returned a non-object post")
            item = dict(raw)
            item.setdefault("source", "danbooru")
            item.setdefault("source_site", "danbooru")
            items.append(item)
        next_cursor = None
        if len(items) >= request.page_size:
            next_cursor = self._cursor("browse", request.client_query_key, {"page": page + 1})
        return ProviderPage(
            items=tuple(items),
            next_cursor=next_cursor,
            provenance={"kind": "official_public_api", "endpoint": "danbooru" + endpoint},
            applied={"requestTime": _utc_now(), "safetyProfile": request.safety_profile},
        )

    def _local_favorites_page(self, request: BrowseRequest) -> ProviderPage:
        provenance = {"kind": "local", "endpoint": "danbooru_favorites"}
        warnings = []
        loader = getattr(self.legacy, "load_favorites", None)
        ids = None
        fetcher = getattr(self.legacy, "_danbooru_bridge_fetch_favorite_ids", None)
        if callable(fetcher):
            try:
                ids, meta = fetcher(max_pages=5, limit=200)
                saver = getattr(self.legacy, "save_favorites", None)
                if callable(saver):
                    saver(ids)
                provenance = {
                    "kind": "browser_session",
                    "endpoint": "danbooru_favorites",
                    "pagesLoaded": int((meta or {}).get("pages_loaded") or 0),
                }
            except Exception as exc:
                warnings.append({
                    "code": "remote_favorites_fallback_local",
                    "message": "Danbooru browser-session favorites are unavailable; showing the local snapshot.",
                    "detail": str(exc)[:180],
                })
        if ids is None:
            ids = list(loader() or ()) if callable(loader) else []
        offset = _offset(request.cursor_state)
        page_ids = ids[offset : offset + request.page_size]
        items = []
        for post_id in page_ids:
            result = self.legacy.DanbooruGalleryNode.get_post_by_id_internal(str(post_id), "danbooru")
            if isinstance(result, tuple) and len(result) == 1:
                result = result[0]
            if isinstance(result, str):
                result = json.loads(result)
            if isinstance(result, list) and result and isinstance(result[0], Mapping):
                item = dict(result[0])
                item.setdefault("source", "danbooru")
                item.setdefault("source_site", "danbooru")
                items.append(item)
        next_offset = offset + len(page_ids)
        next_cursor = None
        if next_offset < len(ids):
            next_cursor = self._cursor("browse", request.client_query_key, {"offset": next_offset})
        return ProviderPage(
            items=tuple(items),
            next_cursor=next_cursor,
            provenance=provenance,
            applied={"requestTime": _utc_now()},
            warnings=tuple(warnings),
        )

    def _favorite_stream_page(self, request: BrowseRequest) -> ProviderPage:
        page = _page_number(request.cursor_state)
        params = {"limit": request.page_size, "page": page}
        fetcher = getattr(self.legacy, "_danbooru_bridge_fetch", None)
        if callable(fetcher):
            response = fetcher("/favorites.json", params=params, label="danbooru_favorite_stream")
        else:
            response = self.legacy._danbooru_request(
                "GET", "https://danbooru.donmai.us/favorites.json", params=params, timeout=30
            )
        data = _json(response, self.source, "Danbooru favorite stream")
        if not isinstance(data, list):
            raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Danbooru favorite stream response shape changed")

        post_ids = []
        seen = set()
        for raw in data:
            if not isinstance(raw, Mapping):
                continue
            post_id = raw.get("post_id")
            if post_id is None:
                continue
            post_id = str(post_id).strip()
            if post_id and post_id not in seen:
                seen.add(post_id)
                post_ids.append(post_id)

        if not post_ids:
            return ProviderPage(
                items=(),
                next_cursor=None,
                provenance={"kind": "official_public_api", "endpoint": "danbooru/favorites"},
                applied={"requestTime": _utc_now(), "sourceRecords": len(data)},
            )

        posts_response = self.legacy._danbooru_request(
            "GET",
            "https://danbooru.donmai.us/posts.json",
            params={"tags": "id:" + ",".join(post_ids), "limit": len(post_ids)},
            timeout=30,
        )
        posts_data = _json(posts_response, self.source, "Danbooru favorite stream posts")
        if not isinstance(posts_data, list):
            raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Danbooru posts response shape changed")
        by_id = {}
        for raw in posts_data:
            if isinstance(raw, Mapping) and raw.get("id") is not None:
                by_id[str(raw.get("id"))] = raw

        items = []
        for post_id in post_ids:
            raw = by_id.get(post_id)
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            item.setdefault("source", "danbooru")
            item.setdefault("source_site", "danbooru")
            items.append(item)

        next_cursor = None
        if len(data) >= request.page_size:
            next_cursor = self._cursor("browse", request.client_query_key, {"page": page + 1})
        return ProviderPage(
            items=tuple(items),
            next_cursor=next_cursor,
            provenance={"kind": "official_public_api", "endpoint": "danbooru/favorites"},
            applied={"requestTime": _utc_now(), "sourceRecords": len(data)},
        )

    def _browse_sync(self, request: BrowseRequest) -> ProviderPage:
        if request.view == View.FAVORITES:
            return self._local_favorites_page(request)
        if request.view == View.FAVORITE_STREAM:
            return self._favorite_stream_page(request)
        if request.view == View.RANKING and request.metric == "popular":
            page = _page_number(request.cursor_state)
            params = {
                "date": request.anchor_date,
                "scale": request.period,
                "limit": request.page_size,
                "page": page,
            }
            auth = getattr(self.legacy, "_with_danbooru_auth_params", None)
            if callable(auth):
                params = auth(params)
            response = self.legacy._danbooru_request(
                "GET",
                "https://danbooru.donmai.us/explore/posts/popular.json",
                params=params,
                timeout=30,
            )
            data = _json(response, self.source, "Danbooru popular")
            if not isinstance(data, list):
                raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Danbooru popular response shape changed")
            items = []
            for raw in _mapping_items(data, "Danbooru popular"):
                item = dict(raw)
                # Danbooru's raw `source` can be an artist/source URL. V53 items
                # reserve source/source_site for the provider identity.
                item["source"] = "danbooru"
                item["source_site"] = "danbooru"
                items.append(item)
            items = tuple(items)
            next_cursor = None
            if len(items) >= request.page_size:
                next_cursor = self._cursor("browse", request.client_query_key, {"page": page + 1})
            return ProviderPage(
                items=items,
                next_cursor=next_cursor,
                ranking={
                    "requestedMetric": "popular",
                    "effectiveMetric": "popular",
                    "period": request.period,
                    "fidelity": "native",
                    "label": "官方热门榜",
                    "basis": "dedicated_popular_endpoint",
                    "periodSemantics": "calendar_anchor",
                    "coverage": None,
                },
                provenance={"kind": "official_public_api", "endpoint": "danbooru/explore/posts/popular"},
                applied={
                    "anchorDate": request.anchor_date,
                    "timezone": "UTC",
                    "requestTime": _utc_now(),
                    "safetyProfile": request.safety_profile,
                },
            )

        tags = []
        if request.query:
            tags.append(request.query)
        if request.facet_id:
            tags.append(request.facet_id)
        if request.view == View.RANKING:
            tags.append("order:favcount" if request.metric == "favorites" else "order:score")
        if request.safety_profile and request.safety_profile != "all":
            tags.append("rating:" + request.safety_profile)
        page = self._posts(request, tags)
        if request.view == View.RANKING:
            metric = "favcount" if request.metric == "favorites" else "score"
            return ProviderPage(
                items=page.items,
                next_cursor=page.next_cursor,
                ranking={
                    "requestedMetric": request.metric,
                    "effectiveMetric": metric,
                    "period": "all_time",
                    "fidelity": "server_derived",
                    "label": "收藏总榜" if request.metric == "favorites" else "分数总榜",
                    "basis": "official_field_sort",
                    "periodSemantics": "not_applicable",
                    "coverage": None,
                },
                provenance=page.provenance,
                applied=page.applied,
            )
        return page

    def _tag_items(self, kind: str, query: Optional[str], limit: int, page: int) -> Tuple[Mapping[str, Any], ...]:
        params: Dict[str, Any] = {
            "search[category]": self._TAG_CATEGORIES[kind],
            "search[order]": "count",
            "limit": limit,
            "page": page,
        }
        if query:
            params["search[name_or_alias_matches]"] = query + "*"
        auth = getattr(self.legacy, "_with_danbooru_auth_params", None)
        if callable(auth):
            params = auth(params)
        response = self.legacy._danbooru_request(
            "GET", "https://danbooru.donmai.us/tags.json", params=params, timeout=20
        )
        data = _json(response, self.source, "Danbooru tags")
        if not isinstance(data, list):
            raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Danbooru tags response shape changed")
        output = []
        for item in data:
            if not isinstance(item, Mapping) or not item.get("name"):
                continue
            output.append(
                _facet_item(
                    item["name"],
                    item["name"],
                    kind,
                    category=kind,
                    count=_safe_int(item.get("post_count"), 0),
                    count_kind="post_count",
                )
            )
        return tuple(output)

    def _facets_sync(self, request: FacetRequest) -> FacetPage:
        page = _page_number(request.cursor_state)
        items = self._tag_items(request.facet_kind, request.query, request.page_size, page)
        next_cursor = None
        if len(items) >= request.page_size:
            next_cursor = self._cursor("facet", request.client_query_key, {"page": page + 1})
        return FacetPage(items=items, next_cursor=next_cursor)

    def _autocomplete_sync(self, request: AutocompleteRequest) -> Tuple[Mapping[str, Any], ...]:
        kind = request.facet_kind or "general"
        return self._tag_items(kind, request.query, request.page_size, 1)


class GelbooruLiveProvider(LiveProviderBase):
    source = Source.GELBOORU

    def _runtime(self) -> ProviderRuntime:
        configured = False
        try:
            user_id, api_key = self.legacy.load_gelbooru_auth()
            configured = bool(user_id and api_key)
        except Exception:
            pass
        return ProviderRuntime(auth_configured=configured)

    def _auth(self, params: Mapping[str, Any]) -> Dict[str, Any]:
        result = dict(params)
        loader = getattr(self.legacy, "_load_gelbooru_auth_params", None)
        if callable(loader):
            result.update(loader())
        return result

    def _post_data(self, response: Any) -> Sequence[Mapping[str, Any]]:
        data = _json(response, self.source, "Gelbooru DAPI")
        if isinstance(data, list):
            return data
        if isinstance(data, Mapping):
            if "post" in data or "posts" in data:
                posts = data.get("post") if "post" in data else data.get("posts")
                if posts is None:
                    return ()
                if isinstance(posts, Mapping):
                    return (posts,)
                if isinstance(posts, list):
                    return posts
            attributes = data.get("@attributes")
            if isinstance(attributes, Mapping) and _safe_int(attributes.get("count"), -1) == 0:
                return ()
        raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Gelbooru DAPI response shape changed")

    def _browse_sync(self, request: BrowseRequest) -> ProviderPage:
        if request.view == View.FAVORITES:
            raise _provider_error(
                ErrorCode.UNSUPPORTED,
                422,
                "Gelbooru favorites are not available",
            )
        page = _page_number(request.cursor_state)
        tags = []
        upstream_safety = None
        warnings = []
        if request.query:
            tags.append(request.query)
        if request.facet_id:
            tags.append(request.facet_id)
        if request.view == View.RANKING:
            tags.append("sort:score:desc")
        if request.safety_profile and request.safety_profile != "all":
            rating = "safe" if request.safety_profile in ("general", "sensitive") else request.safety_profile
            tags.append("rating:" + rating)
            upstream_safety = {"parameter": "rating", "value": rating}
            if request.safety_profile in ("general", "sensitive"):
                warnings.append(
                    {
                        "code": "safety_profile_degraded",
                        "message": (
                            "Gelbooru cannot distinguish general from sensitive; "
                            "both use upstream rating:safe"
                        ),
                        "details": {
                            "requestedSafetyProfile": request.safety_profile,
                            "effectiveUpstreamRating": "safe",
                        },
                    }
                )
        params = self._auth(
            {
                "page": "dapi",
                "s": "post",
                "q": "index",
                "json": "1",
                "tags": " ".join(tags),
                "limit": request.page_size,
                "pid": page - 1,
            }
        )
        response = self.legacy._gelbooru_request(
            "GET", "https://gelbooru.com/index.php", params=params, timeout=25
        )
        items = []
        normalizer = self.legacy._gelbooru_post_to_danbooru_shape
        for raw in self._post_data(response):
            item = normalizer(dict(raw))
            if isinstance(item, Mapping):
                items.append(dict(item))
        next_cursor = None
        if len(items) >= request.page_size:
            next_cursor = self._cursor("browse", request.client_query_key, {"page": page + 1})
        ranking = None
        if request.view == View.RANKING:
            ranking = {
                "requestedMetric": "score",
                "effectiveMetric": "score",
                "period": "all_time",
                "fidelity": "server_derived",
                "label": "总分榜",
                "basis": "official_field_sort",
                "periodSemantics": "not_applicable",
                "coverage": None,
            }
        return ProviderPage(
            items=tuple(items),
            next_cursor=next_cursor,
            ranking=ranking,
            provenance={"kind": "official_public_api", "endpoint": "gelbooru/dapi/post"},
            applied={
                "requestTime": _utc_now(),
                "safetyProfile": request.safety_profile,
                "upstreamSafety": upstream_safety,
            },
            warnings=tuple(warnings),
        )

    def _tag_items(self, query: Optional[str], limit: int, page: int) -> Tuple[Mapping[str, Any], ...]:
        params: Dict[str, Any] = {
            "page": "dapi",
            "s": "tag",
            "q": "index",
            "json": "1",
            "limit": limit,
            "pid": page - 1,
            "orderby": "count",
            "order": "DESC",
        }
        if query:
            params["name_pattern"] = query + "%"
        response = self.legacy._gelbooru_request(
            "GET", "https://gelbooru.com/index.php", params=self._auth(params), timeout=20
        )
        data = _json(response, self.source, "Gelbooru tag DAPI")
        raw_items: Any
        if isinstance(data, list):
            raw_items = data
        elif isinstance(data, Mapping) and "tag" in data:
            raw_items = data.get("tag") or []
            if isinstance(raw_items, Mapping):
                raw_items = [raw_items]
        elif isinstance(data, Mapping) and isinstance(data.get("@attributes"), Mapping) and _safe_int(data["@attributes"].get("count"), -1) == 0:
            raw_items = []
        else:
            raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Gelbooru tag DAPI response shape changed")
        output = []
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name") or item.get("tag")
            if name:
                output.append(
                    _facet_item(
                        name,
                        name,
                        "tag_cumulative",
                        count=_safe_int(item.get("count") or item.get("post_count"), 0),
                        count_kind="cumulative_post_count",
                    )
                )
        return tuple(output)

    def _facets_sync(self, request: FacetRequest) -> FacetPage:
        page = _page_number(request.cursor_state)
        items = self._tag_items(request.query, request.page_size, page)
        next_cursor = None
        if len(items) >= request.page_size:
            next_cursor = self._cursor("facet", request.client_query_key, {"page": page + 1})
        return FacetPage(items=items, next_cursor=next_cursor)

    def _autocomplete_sync(self, request: AutocompleteRequest) -> Tuple[Mapping[str, Any], ...]:
        return self._tag_items(request.query, request.page_size, 1)


class YandereLiveProvider(LiveProviderBase):
    source = Source.YANDERE
    _TYPE_NAMES = {0: "general", 1: "artist", 3: "copyright", 4: "character"}

    def _runtime(self) -> ProviderRuntime:
        return ProviderRuntime(
            feature_states={
                "view:ranking": FeatureState.SUPPORTED,
                "ranking:score_period": FeatureState.SUPPORTED,
            },
            feature_reasons={
                "view:ranking": None,
                "ranking:score_period": None,
            },
        )

    @staticmethod
    def _range(anchor: str, period: str) -> Tuple[str, str]:
        end = date.fromisoformat(anchor)
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[period]
        start = end - timedelta(days=days - 1)
        return start.isoformat(), end.isoformat()

    def _browse_sync(self, request: BrowseRequest) -> ProviderPage:
        if request.view == View.FAVORITES:
            raise _provider_error(
                ErrorCode.UNSUPPORTED,
                422,
                "Yande.re favorites are not available",
            )
        page = _page_number(request.cursor_state)
        tags = []
        start = end = None
        if request.query:
            tags.append(request.query)
        if request.facet_id:
            tags.append(request.facet_id)
        if request.view == View.RANKING:
            start, end = self._range(request.anchor_date, request.period)
            tags.extend(("date:%s..%s" % (start, end), "order:score"))
        if request.safety_profile and request.safety_profile != "all":
            rating = "safe" if request.safety_profile == "safe" else request.safety_profile
            tags.append("rating:" + rating)
        response = self.legacy._yandere_request(
            "GET",
            "https://yande.re/post.json",
            params={"tags": " ".join(tags), "limit": request.page_size, "page": page},
            timeout=25,
        )
        data = _json(response, self.source, "Yande.re posts")
        if not isinstance(data, list):
            raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Yande.re posts response shape changed")
        items = []
        for raw in data:
            if not isinstance(raw, Mapping):
                raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Yande.re returned a non-object post")
            item = self.legacy._yandere_post_to_danbooru_shape(dict(raw))
            if isinstance(item, Mapping):
                items.append(dict(item))
        next_cursor = None
        if len(items) >= request.page_size:
            next_cursor = self._cursor("browse", request.client_query_key, {"page": page + 1})
        ranking = None
        if request.view == View.RANKING:
            ranking = {
                "requestedMetric": "score_period",
                "effectiveMetric": "score",
                "period": request.period,
                "fidelity": "server_derived",
                "label": "区间分数榜（非站内 Popular）",
                "basis": "official_date_range_score_sort",
                "periodSemantics": "explicit_range",
                "coverage": None,
            }
        return ProviderPage(
            items=tuple(items),
            next_cursor=next_cursor,
            ranking=ranking,
            provenance={"kind": "official_public_api", "endpoint": "yande.re/post.json"},
            applied={
                "anchorDate": request.anchor_date,
                "timezone": "UTC",
                "windowStart": start,
                "windowEnd": end,
                "requestTime": _utc_now(),
                "safetyProfile": request.safety_profile,
            },
        )

    def _tag_items(self, query: Optional[str], limit: int, page: int) -> Tuple[Mapping[str, Any], ...]:
        params: Dict[str, Any] = {"order": "count", "limit": limit, "page": page}
        if query:
            params["name_pattern"] = query + "*"
        response = self.legacy._yandere_request(
            "GET", "https://yande.re/tag.json", params=params, timeout=20
        )
        data = _json(response, self.source, "Yande.re tags")
        if not isinstance(data, list):
            raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Yande.re tags response shape changed")
        output = []
        for item in data:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name") or item.get("tag")
            if name:
                tag_type = _safe_int(item.get("type") or item.get("tag_type"), 0)
                output.append(
                    _facet_item(
                        name,
                        name,
                        "tag",
                        category=self._TYPE_NAMES.get(tag_type, "general"),
                        count=_safe_int(item.get("count") or item.get("post_count"), 0),
                        count_kind="post_count",
                    )
                )
        return tuple(output)

    def _related_items(self, query: str, limit: int) -> Tuple[Mapping[str, Any], ...]:
        response = self.legacy._yandere_request(
            "GET",
            "https://yande.re/tag/related.json",
            params={"tags": query, "type": "json"},
            timeout=20,
        )
        data = _json(response, self.source, "Yande.re related tags")
        if isinstance(data, Mapping):
            data = data.get("tags") or data.get("related_tags") or []
        if not isinstance(data, list):
            raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Yande.re related tags response shape changed")
        output = []
        for item in data[:limit]:
            if isinstance(item, Mapping):
                name = item.get("name") or item.get("tag")
                count = _safe_int(item.get("count") or item.get("post_count"), 0)
            elif isinstance(item, (list, tuple)) and item:
                name = item[0]
                count = _safe_int(item[1] if len(item) > 1 else 0, 0)
            else:
                continue
            if name:
                output.append(_facet_item(name, name, "related_tag", count=count, count_kind="post_count"))
        return tuple(output)

    def _facets_sync(self, request: FacetRequest) -> FacetPage:
        if request.facet_kind == "related_tag":
            if not request.query:
                raise _provider_error(ErrorCode.INVALID_REQUEST, 400, "related_tag facet requires query")
            return FacetPage(items=self._related_items(request.query, request.page_size))
        page = _page_number(request.cursor_state)
        items = self._tag_items(request.query, request.page_size, page)
        next_cursor = None
        if len(items) >= request.page_size:
            next_cursor = self._cursor("facet", request.client_query_key, {"page": page + 1})
        return FacetPage(items=items, next_cursor=next_cursor)

    def _autocomplete_sync(self, request: AutocompleteRequest) -> Tuple[Mapping[str, Any], ...]:
        if request.facet_kind == "related_tag":
            return self._related_items(request.query, request.page_size)
        return self._tag_items(request.query, request.page_size, 1)


class CivitaiLiveProvider(LiveProviderBase):
    source = Source.CIVITAI
    _PERIODS = {"day": "Day", "week": "Week", "month": "Month", "year": "Year", "all_time": "AllTime"}
    _SORTS = {"reactions": "Most Reactions", "comments": "Most Comments"}
    _BASE_MODELS = (
        "SD 1.4",
        "SD 1.5",
        "SD 2.0",
        "SD 2.1",
        "SDXL 1.0",
        "Pony",
        "Flux.1 D",
        "Flux.1 S",
        "Illustrious",
        "SD 3.5",
    )

    def _runtime(self) -> ProviderRuntime:
        configured = False
        search_configured = False
        try:
            configured = bool(self.legacy.load_civitai_auth())
        except Exception:
            pass
        try:
            settings_loader = getattr(self.legacy, "load_civitai_remote_favorites_settings", None)
            if callable(settings_loader):
                settings = settings_loader()
                configured = configured or bool(
                    settings[1]
                    and isinstance(settings[3], Mapping)
                    and settings[3].get("Cookie")
                )
        except Exception:
            # Unknown remote-auth state disables neither the provider nor its
            # public views; it simply stays in the conservative unauthenticated state.
            pass
        try:
            search_loader = getattr(self.legacy, "load_civitai_search_headers", None)
            if callable(search_loader):
                search_raw, search_headers = search_loader()
                search_configured = bool(
                    search_raw
                    and isinstance(search_headers, Mapping)
                    and (
                        search_headers.get("Authorization")
                        or search_headers.get("X-Meili-API-Key")
                    )
                )
                configured = configured or search_configured
        except Exception:
            search_configured = False
        return ProviderRuntime(
            auth_configured=configured,
            feature_states={
                "view:search": (
                    FeatureState.SUPPORTED
                    if search_configured
                    else FeatureState.UNSUPPORTED
                ),
                "facet:model_version": FeatureState.UNSUPPORTED,
            },
            feature_reasons={
                "view:search": (
                    None if search_configured else "search_authorization_required"
                ),
                "facet:model_version": "public_list_endpoint_unavailable",
            },
        )

    @staticmethod
    def _public_api_endpoint(api_root: str, path: str) -> str:
        return api_root.split("://", 1)[-1].rstrip("/") + "/" + path.lstrip("/")

    @staticmethod
    def _public_api_origin(api_root: str) -> str:
        suffix = "/api/v1"
        return api_root[:-len(suffix)] if api_root.endswith(suffix) else api_root.rstrip("/")

    def _public_api_provenance(self, api_root: str, path: str) -> Mapping[str, Any]:
        provenance: Dict[str, Any] = {
            "kind": "official_public_api",
            "endpoint": self._public_api_endpoint(api_root, path),
        }
        if api_root == CIVITAI_API_FALLBACK_ROOT:
            provenance["fallbackFrom"] = self._public_api_endpoint(CIVITAI_API_ROOT, path)
        return provenance

    def _get(
        self,
        path: str,
        params: Mapping[str, Any],
        context: str,
        *,
        deep_cursor: bool = False,
    ) -> Tuple[Mapping[str, Any], str]:
        clean_path = path.lstrip("/")
        if not clean_path or "?" in clean_path or "#" in clean_path or ".." in clean_path.split("/"):
            raise _provider_error(ErrorCode.INVALID_REQUEST, 400, "invalid Civitai API path")

        last_error: Optional[Exception] = None
        for api_root in CIVITAI_API_ROOTS:
            url = api_root + "/" + clean_path
            if not url.startswith(api_root + "/"):
                raise _provider_error(ErrorCode.INVALID_REQUEST, 400, "invalid Civitai API path")
            try:
                response = self.legacy._civitai_request(
                    "GET", url, params=dict(params), timeout=25,
                )
                payload = _json(
                    response,
                    self.source,
                    context,
                    deep_cursor=deep_cursor,
                )
                # Every V53 public endpoint used here (images/models/creators/tags)
                # has the same top-level collection contract. Treat a 2xx body that
                # violates it as an upstream failure so the alternate public origin
                # gets a chance instead of returning a false schema error immediately.
                if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
                    raise _provider_error(
                        ErrorCode.SCHEMA_CHANGED,
                        502,
                        context + " response shape changed",
                    )
                return payload, api_root
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise _provider_error(ErrorCode.UPSTREAM_ERROR, 502, context + " failed")

    def _normalize_image(self, raw: Mapping[str, Any], api_root: str) -> Mapping[str, Any]:
        api_origin = self._public_api_origin(api_root)
        item = dict(raw)
        item["_civitai_api_base"] = api_origin
        normalizer = getattr(self.legacy, "_civitai_item_to_danbooru_shape", None)
        if callable(normalizer):
            normalized = normalizer(item)
            if isinstance(normalized, Mapping):
                result = dict(normalized)
                result["civitai_api_base"] = api_origin
                return result
        image_id = item.get("id")
        return {
            **item,
            "id": image_id,
            "source": "civitai",
            "source_site": "civitai",
            "file_url": item.get("url") or "",
            "large_file_url": item.get("url") or "",
            "preview_file_url": item.get("url") or "",
            "image_width": _safe_int(item.get("width"), 0),
            "image_height": _safe_int(item.get("height"), 0),
            "civitai_api_base": api_origin,
        }

    def _search_page(self, request: BrowseRequest) -> ProviderPage:
        """Search Civitai's authenticated image index without silent latest fallback."""
        plan_builder = getattr(self.legacy, "_civitai_extract_search_filters", None)
        search_loader = getattr(self.legacy, "_civitai_multisearch_images", None)
        if not callable(plan_builder) or not callable(search_loader):
            raise _provider_error(
                ErrorCode.UNSUPPORTED,
                422,
                "Civitai image search is unavailable in this plugin build",
            )

        page = _page_number(request.cursor_state)
        offset = (page - 1) * request.page_size
        max_offset = int(self.capabilities().limits.max_offset_items or 1000)
        if offset > max_offset:
            raise _provider_error(
                ErrorCode.PAGINATION_LIMIT,
                422,
                "Civitai search reached its safe offset limit",
            )

        plan = plan_builder(request.query or "", rating=None)
        if not isinstance(plan, Mapping) or plan.get("favorite_mode"):
            raise _provider_error(
                ErrorCode.INVALID_REQUEST,
                400,
                "Civitai search query is invalid",
            )
        result = search_loader(plan, request.page_size, page)
        if not isinstance(result, (tuple, list)) or len(result) != 2:
            raise _provider_error(
                ErrorCode.SCHEMA_CHANGED,
                502,
                "Civitai search returned an invalid result",
            )
        raw_items, call = result
        if not isinstance(raw_items, list) or not isinstance(call, Mapping):
            raise _provider_error(
                ErrorCode.SCHEMA_CHANGED,
                502,
                "Civitai search response shape changed",
            )
        items = []
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                raise _provider_error(
                    ErrorCode.SCHEMA_CHANGED,
                    502,
                    "Civitai search returned a non-object image",
                )
            item = dict(raw)
            item.setdefault("source", "civitai")
            item.setdefault("source_site", "civitai")
            items.append(item)

        raw_hits = _safe_int(call.get("raw_hits"), len(items))
        next_offset = offset + request.page_size
        estimated_total = call.get("estimated_total_hits")
        if isinstance(estimated_total, int) and not isinstance(estimated_total, bool):
            has_next = next_offset < estimated_total and next_offset <= max_offset
        else:
            has_next = raw_hits >= request.page_size and next_offset <= max_offset
        next_cursor = None
        if has_next:
            next_cursor = self._cursor(
                "browse",
                request.client_query_key,
                {"page": page + 1},
            )
        return ProviderPage(
            items=tuple(items),
            next_cursor=next_cursor,
            provenance={
                "kind": "authenticated_web_search",
                "endpoint": "search-new.civitai.com/multi-search",
            },
            applied={
                "requestTime": _utc_now(),
                "queryMode": "images_v6",
                "matchingStrategy": (
                    call.get("matching_strategy")
                    if call.get("matching_strategy") in ("all", "last")
                    else ("all" if bool(plan.get("strict_search")) else "last")
                ),
                "offset": offset,
                "safetyProfile": None,
            },
        )

    def _local_favorites_chain_page(
        self, request: BrowseRequest, *, remote_fallback: bool
    ) -> ProviderPage:
        """Keep every page in a local fallback chain on the same dataset."""
        local_page = self._local_favorites_page(request)
        offset = _offset(request.cursor_state)
        next_cursor = None
        if local_page.next_cursor:
            next_cursor = self._cursor(
                "browse",
                request.client_query_key,
                {
                    "offset": offset + len(local_page.items),
                    "favorites_source": "local",
                    "remote_fallback": bool(remote_fallback),
                },
            )
        provenance = {"kind": "local", "endpoint": "local_favorites"}
        warnings: Tuple[Mapping[str, Any], ...] = ()
        if remote_fallback:
            provenance["fallbackFrom"] = "civitai_remote_collection"
            warnings = ({
                "code": "remote_favorites_fallback_local",
                "message": "Civitai remote favorites are unavailable; showing the local snapshot.",
            },)
        return ProviderPage(
            items=local_page.items,
            next_cursor=next_cursor,
            provenance=provenance,
            applied=local_page.applied,
            warnings=warnings,
        )

    def _favorites_page(self, request: BrowseRequest) -> ProviderPage:
        """Prefer the configured remote Civitai collection, with a local snapshot fallback."""
        cursor_state = request.cursor_state if isinstance(request.cursor_state, Mapping) else {}
        offset = _offset(cursor_state)
        if cursor_state.get("favorites_source") == "local":
            return self._local_favorites_chain_page(
                request,
                remote_fallback=bool(cursor_state.get("remote_fallback")),
            )

        settings_loader = getattr(self.legacy, "load_civitai_remote_favorites_settings", None)
        remote_loader = getattr(self.legacy, "_civitai_remote_get_collection_posts", None)
        if not callable(settings_loader) or not callable(remote_loader):
            if offset > 0:
                raise ProviderPayloadError("Civitai favorites pagination source changed; refresh the first page")
            return self._local_favorites_chain_page(request, remote_fallback=False)

        try:
            settings = settings_loader()
            collection_headers = settings[1]
            default_collection_id = settings[2]
            parsed_headers = settings[3]
            remote_configured = bool(
                collection_headers
                and isinstance(parsed_headers, Mapping)
                and parsed_headers.get("Cookie")
            )
        except Exception:
            remote_configured = False
            default_collection_id = ""

        if not remote_configured:
            if offset > 0:
                raise ProviderPayloadError("Civitai favorites pagination source changed; refresh the first page")
            return self._local_favorites_chain_page(request, remote_fallback=False)

        page = (offset // request.page_size) + 1
        requested_session_id = str(cursor_state.get("session_id") or "").strip()
        if offset > 0 and not requested_session_id:
            raise ProviderPayloadError("Civitai favorites cursor expired; refresh the first page")
        collection_ref = str(
            cursor_state.get("collection_id") or default_collection_id or ""
        ).strip()
        try:
            result = remote_loader(
                collection_ref,
                request.page_size,
                page,
                force_refresh=(offset == 0),
                session_id=requested_session_id or None,
            )
            if not isinstance(result, (tuple, list)) or len(result) != 2:
                raise ProviderPayloadError("Civitai remote favorites returned an invalid result")
            remote_items, call = result
            if not isinstance(remote_items, list) or not isinstance(call, Mapping):
                raise ProviderPayloadError("Civitai remote favorites response shape changed")
        except Exception as exc:
            legacy_logger = getattr(self.legacy, "logger", None)
            safe_exception = getattr(self.legacy, "_safe_exception_text", None)
            if legacy_logger is not None and hasattr(legacy_logger, "warning"):
                safe_text = safe_exception(exc) if callable(safe_exception) else type(exc).__name__
                legacy_logger.warning(
                    "[CivitaiV53] remote favorites failed; %s: %s",
                    "keeping the remote pagination chain" if offset > 0 else "using local snapshot",
                    safe_text,
                )
            if offset > 0:
                raise
            local_items = self._structured_favorites()
            if not local_items:
                raise
            return self._local_favorites_chain_page(request, remote_fallback=True)

        if call.get("local_pagination"):
            page_items = remote_items[offset : offset + request.page_size]
            has_next = (
                offset + len(page_items) < len(remote_items)
                or bool(call.get("has_more"))
            )
        else:
            page_items = remote_items[: request.page_size]
            has_next = bool(call.get("next_cursor"))

        items = []
        for raw in page_items:
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            item.setdefault("source", "civitai")
            item.setdefault("source_site", "civitai")
            items.append(item)

        next_cursor = None
        if has_next:
            session_token = str(call.get("session_id") or "").strip()
            if call.get("local_pagination") and not session_token:
                raise ProviderPayloadError("Civitai remote favorites response is missing its pagination session")
            cursor_state_out = {"offset": offset + request.page_size}
            if session_token:
                cursor_state_out["session_id"] = session_token
            collection_id = call.get("collectionId")
            if collection_id not in (None, ""):
                cursor_state_out["collection_id"] = str(collection_id)
            next_cursor = self._cursor(
                "browse",
                request.client_query_key,
                cursor_state_out,
            )
        return ProviderPage(
            items=tuple(items),
            next_cursor=next_cursor,
            provenance={
                "kind": "authenticated_remote",
                "endpoint": "civitai.red/api/trpc/image.getInfinite",
            },
            applied={"requestTime": _utc_now()},
        )

    def _browse_sync(self, request: BrowseRequest) -> ProviderPage:
        if request.view == View.FAVORITES:
            return self._favorites_page(request)
        if request.view == View.SEARCH:
            return self._search_page(request)
        params: Dict[str, Any] = {"limit": request.page_size}
        upstream_cursor = None
        if request.cursor_state:
            upstream_cursor = request.cursor_state.get("cursor")
            if not isinstance(upstream_cursor, str) or not upstream_cursor:
                raise _provider_error(ErrorCode.INVALID_REQUEST, 400, "cursor contains invalid Civitai state")
            params["cursor"] = upstream_cursor
        if request.view == View.RANKING:
            params["sort"] = self._SORTS[request.metric]
            params["period"] = self._PERIODS[request.period]
        else:
            params["sort"] = "Newest"
        if request.facet_kind and request.facet_id:
            parameter = {
                "model": "modelId",
                "creator": "username",
                "base_model": "baseModels",
                "known_image_tag_id": "tags",
            }.get(request.facet_kind)
            if parameter:
                params[parameter] = request.facet_id
        if request.safety_profile:
            params["browsingLevel"] = {
                "general": 1,
                "sfw": 1,
                "nsfw": 31,
                "all": 31,
            }[request.safety_profile]
        data, api_root = self._get(
            "images", params, "Civitai images", deep_cursor=bool(upstream_cursor),
        )
        items = []
        for raw in data["items"]:
            if not isinstance(raw, Mapping):
                raise _provider_error(ErrorCode.SCHEMA_CHANGED, 502, "Civitai returned a non-object image")
            items.append(self._normalize_image(raw, api_root))
        metadata = data.get("metadata") if isinstance(data.get("metadata"), Mapping) else {}
        next_upstream = metadata.get("nextCursor")
        next_cursor = None
        if isinstance(next_upstream, str) and next_upstream:
            next_cursor = self._cursor("browse", request.client_query_key, {"cursor": next_upstream})
        ranking = None
        if request.view == View.RANKING:
            ranking = {
                "requestedMetric": request.metric,
                "effectiveMetric": self._SORTS[request.metric],
                "period": request.period,
                "fidelity": "native",
                "label": "互动榜" if request.metric == "reactions" else "评论榜",
                "basis": "official_metric_sort",
                "periodSemantics": "rolling_current",
                "coverage": None,
            }
        return ProviderPage(
            items=tuple(items),
            next_cursor=next_cursor,
            ranking=ranking,
            provenance=self._public_api_provenance(api_root, "images"),
            applied={
                "anchorDate": None,
                "timezone": None,
                "windowStart": None,
                "windowEnd": None,
                "requestTime": _utc_now(),
                "upstreamPeriod": params.get("period"),
                "safetyProfile": request.safety_profile,
                "upstreamSafety": (
                    {"parameter": "browsingLevel", "value": params["browsingLevel"]}
                    if "browsingLevel" in params
                    else None
                ),
            },
        )

    @staticmethod
    def _civitai_facet_item(raw: Mapping[str, Any], kind: str) -> Optional[Mapping[str, Any]]:
        if kind == "creator":
            item_id = raw.get("username") or raw.get("name") or raw.get("id")
            label = raw.get("username") or raw.get("name") or item_id
            count = raw.get("modelCount") or raw.get("count")
            count_kind = "model_count"
        else:
            item_id = raw.get("id") or raw.get("name")
            label = raw.get("name") or raw.get("label") or item_id
            stats = raw.get("stats") if isinstance(raw.get("stats"), Mapping) else {}
            count = raw.get("modelCount") or raw.get("count") or stats.get("downloadCount")
            count_kind = "model_count" if kind == "model_taxonomy" else "download_count"
        if item_id is None or label is None:
            return None
        return _facet_item(
            item_id,
            label,
            kind,
            count=None if count is None else _safe_int(count, 0),
            count_kind=count_kind,
        )

    def _facets_sync(self, request: FacetRequest) -> FacetPage:
        if request.facet_kind == "base_model":
            offset = _offset(request.cursor_state)
            values = self._BASE_MODELS[offset : offset + request.page_size]
            items = tuple(_facet_item(value, value, "base_model") for value in values)
            next_offset = offset + len(values)
            next_cursor = None
            if next_offset < len(self._BASE_MODELS):
                next_cursor = self._cursor("facet", request.client_query_key, {"offset": next_offset})
            return FacetPage(items=items, next_cursor=next_cursor)

        endpoint = {
            "model": "models",
            "creator": "creators",
            "model_taxonomy": "tags",
        }.get(request.facet_kind)
        if endpoint is None:
            raise _provider_error(ErrorCode.UNSUPPORTED, 422, "Civitai facet is not publicly listable")
        params: Dict[str, Any] = {"limit": request.page_size}
        page = 1
        if request.query:
            params["query"] = request.query
        if request.cursor_state:
            if isinstance(request.cursor_state.get("cursor"), str):
                params["cursor"] = request.cursor_state["cursor"]
            else:
                page = _page_number(request.cursor_state)
                params["page"] = page
        data, _api_root = self._get(
            endpoint,
            params,
            "Civitai " + endpoint,
            deep_cursor=bool(request.cursor_state),
        )
        items = []
        for raw in data["items"]:
            if isinstance(raw, Mapping):
                item = self._civitai_facet_item(raw, request.facet_kind)
                if item:
                    items.append(item)
        metadata = data.get("metadata") if isinstance(data.get("metadata"), Mapping) else {}
        next_cursor = None
        next_upstream = metadata.get("nextCursor")
        if isinstance(next_upstream, str) and next_upstream:
            next_cursor = self._cursor("facet", request.client_query_key, {"cursor": next_upstream})
        elif metadata.get("nextPage") is not None:
            next_cursor = self._cursor("facet", request.client_query_key, {"page": _safe_int(metadata["nextPage"], page + 1)})
        elif endpoint == "creators" and len(items) >= request.page_size:
            next_cursor = self._cursor("facet", request.client_query_key, {"page": page + 1})
        return FacetPage(items=tuple(items), next_cursor=next_cursor)

    def _autocomplete_sync(self, request: AutocompleteRequest) -> Tuple[Mapping[str, Any], ...]:
        kind = request.facet_kind or "model"
        endpoint = "creators" if kind == "creator" else ("tags" if kind == "model_taxonomy" else "models")
        data, _api_root = self._get(
            endpoint,
            {"query": request.query, "limit": request.page_size},
            "Civitai autocomplete",
        )
        output = []
        for raw in data["items"]:
            if isinstance(raw, Mapping):
                item = self._civitai_facet_item(raw, kind)
                if item:
                    output.append(item)
        return tuple(output)


class LiveProviderRegistry:
    def __init__(self, providers: Iterable[GalleryProvider]) -> None:
        self._providers = {provider.source: provider for provider in providers}
        missing = set(Source) - set(self._providers)
        if missing:
            raise ValueError("provider registry is missing: %s" % ", ".join(sorted(item.value for item in missing)))

    def get(self, source: Any) -> GalleryProvider:
        try:
            source_enum = source if isinstance(source, Source) else Source(str(source).lower())
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown provider source") from exc
        return self._providers[source_enum]

    def all(self) -> Tuple[GalleryProvider, ...]:
        return tuple(self._providers[source] for source in Source)


def build_live_provider_registry(legacy: Any, cursor_codec: OpaqueCursorCodec) -> LiveProviderRegistry:
    return LiveProviderRegistry(
        (
            DanbooruLiveProvider(legacy, cursor_codec),
            GelbooruLiveProvider(legacy, cursor_codec),
            YandereLiveProvider(legacy, cursor_codec),
            CivitaiLiveProvider(legacy, cursor_codec),
        )
    )


__all__ = [
    "CIVITAI_API_ROOT",
    "CIVITAI_API_FALLBACK_ROOT",
    "CIVITAI_API_ROOTS",
    "CivitaiLiveProvider",
    "DanbooruLiveProvider",
    "GelbooruLiveProvider",
    "LiveProviderRegistry",
    "ProviderRequestError",
    "YandereLiveProvider",
    "build_live_provider_registry",
    "normalize_provider_exception",
]
