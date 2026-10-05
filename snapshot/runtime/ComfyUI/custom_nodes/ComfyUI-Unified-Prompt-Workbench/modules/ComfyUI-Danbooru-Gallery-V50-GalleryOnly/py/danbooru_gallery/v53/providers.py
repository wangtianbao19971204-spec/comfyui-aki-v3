from __future__ import annotations

import asyncio
import functools
import inspect
import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from .capabilities import get_provider_capabilities
from .domain import (
    CONTRACT_VERSION,
    AutocompleteRequest,
    BrowseRequest,
    FacetPage,
    FacetRequest,
    ProviderCapabilities,
    ProviderPage,
    ProviderPayloadError,
    ProviderRuntime,
    Source,
)


class GalleryProvider(ABC):
    contract_version = CONTRACT_VERSION

    @property
    @abstractmethod
    def source(self) -> Source:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    @abstractmethod
    async def browse(self, request: BrowseRequest) -> ProviderPage:
        raise NotImplementedError

    @abstractmethod
    async def list_facets(self, request: FacetRequest) -> FacetPage:
        raise NotImplementedError

    @abstractmethod
    async def autocomplete(self, request: AutocompleteRequest) -> Tuple[Mapping[str, Any], ...]:
        raise NotImplementedError

    @abstractmethod
    async def get_post(self, post_id: str) -> Optional[Mapping[str, Any]]:
        raise NotImplementedError


def _legacy_items(value: Any, *, label: str) -> Tuple[Mapping[str, Any], ...]:
    if isinstance(value, tuple) and len(value) == 1:
        value = value[0]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProviderPayloadError("%s returned invalid JSON" % label) from exc
    if isinstance(value, Mapping) and isinstance(value.get("items"), list):
        value = value["items"]
    if not isinstance(value, list):
        raise ProviderPayloadError("%s must return an item list" % label)
    items = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ProviderPayloadError("%s returned a non-object item" % label)
        items.append(dict(item))
    return tuple(items)


def _legacy_post(value: Any) -> Optional[Mapping[str, Any]]:
    if isinstance(value, tuple) and len(value) == 1:
        value = value[0]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProviderPayloadError("legacy get_post returned invalid JSON") from exc
    if value is None:
        return None
    if isinstance(value, Mapping) and "items" not in value:
        return dict(value)
    items = _legacy_items(value, label="legacy get_post")
    return items[0] if items else None


class LegacyProviderAdapter(GalleryProvider):
    """Adapter boundary for the existing synchronous/JSON-string providers.

    It intentionally knows nothing about ComfyUI. Route integration supplies small
    callbacks that accept the validated V53 request objects.
    """

    def __init__(
        self,
        source: object,
        *,
        browse_handler: Callable[[BrowseRequest], Any],
        facet_handler: Optional[Callable[[FacetRequest], Any]] = None,
        autocomplete_handler: Optional[Callable[[AutocompleteRequest], Any]] = None,
        get_post_handler: Optional[Callable[[str], Any]] = None,
        runtime: Optional[ProviderRuntime] = None,
    ) -> None:
        self._source = source if isinstance(source, Source) else Source(str(source).lower())
        if not callable(browse_handler):
            raise TypeError("browse_handler must be callable")
        self._browse_handler = browse_handler
        self._facet_handler = facet_handler
        self._autocomplete_handler = autocomplete_handler
        self._get_post_handler = get_post_handler
        self._runtime = runtime or ProviderRuntime()

    @property
    def source(self) -> Source:
        return self._source

    def capabilities(self) -> ProviderCapabilities:
        return get_provider_capabilities(self._source, self._runtime)

    async def _invoke(self, handler: Callable[..., Any], *args: Any) -> Any:
        if inspect.iscoroutinefunction(handler):
            return await handler(*args)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, functools.partial(handler, *args))
        if inspect.isawaitable(result):
            return await result
        return result

    async def browse(self, request: BrowseRequest) -> ProviderPage:
        if request.source != self._source:
            raise ValueError("request source does not match adapter source")
        raw = await self._invoke(self._browse_handler, request)
        return ProviderPage(
            items=_legacy_items(raw, label="legacy browse"),
            provenance={"kind": "legacy_adapter", "endpoint": self._source.value},
        )

    async def list_facets(self, request: FacetRequest) -> FacetPage:
        if request.source != self._source:
            raise ValueError("request source does not match adapter source")
        if self._facet_handler is None:
            raise NotImplementedError("legacy facet handler is not configured")
        raw = await self._invoke(self._facet_handler, request)
        return FacetPage(items=_legacy_items(raw, label="legacy facets"))

    async def autocomplete(self, request: AutocompleteRequest) -> Tuple[Mapping[str, Any], ...]:
        if self._autocomplete_handler is None:
            raise NotImplementedError("legacy autocomplete handler is not configured")
        raw = await self._invoke(self._autocomplete_handler, request)
        return _legacy_items(raw, label="legacy autocomplete")

    async def get_post(self, post_id: str) -> Optional[Mapping[str, Any]]:
        if self._get_post_handler is None:
            raise NotImplementedError("legacy get_post handler is not configured")
        raw = await self._invoke(self._get_post_handler, str(post_id))
        return _legacy_post(raw)
