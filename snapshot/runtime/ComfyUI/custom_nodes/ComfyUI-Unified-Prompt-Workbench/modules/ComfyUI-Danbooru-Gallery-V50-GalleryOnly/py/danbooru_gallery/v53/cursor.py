from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from .domain import CONTRACT_VERSION


class CursorCodecError(ValueError):
    pass


@dataclass(frozen=True)
class CursorPayload:
    source: str
    request_kind: str
    query_key: str
    state: Mapping[str, Any]
    issued_at: int
    version: int = CONTRACT_VERSION


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    if not value or any(ch.isspace() for ch in value):
        raise CursorCodecError("invalid cursor encoding")
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except Exception as exc:
        raise CursorCodecError("invalid cursor encoding") from exc


class OpaqueCursorCodec:
    """Versioned, signed cursor token.

    The payload is intentionally a server contract, not a client API. It is signed
    against tampering but not encrypted; callers must never place secrets in state.
    """

    def __init__(
        self,
        secret: object,
        *,
        ttl_seconds: Optional[int] = None,
        max_token_length: int = 4096,
    ) -> None:
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if not isinstance(secret, bytes) or len(secret) < 16:
            raise ValueError("cursor secret must contain at least 16 bytes")
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("cursor ttl_seconds must be positive")
        self._secret = secret
        self._ttl_seconds = ttl_seconds
        self._max_token_length = max_token_length

    def encode(
        self,
        *,
        source: str,
        request_kind: str,
        query_key: str,
        state: Mapping[str, Any],
        issued_at: Optional[int] = None,
    ) -> str:
        if request_kind not in ("browse", "facet"):
            raise CursorCodecError("invalid cursor request kind")
        if not isinstance(state, Mapping):
            raise CursorCodecError("cursor state must be an object")
        payload: Dict[str, Any] = {
            "v": CONTRACT_VERSION,
            "source": str(source),
            "kind": request_kind,
            "queryKey": str(query_key),
            "state": dict(state),
            "iat": int(time.time() if issued_at is None else issued_at),
        }
        try:
            raw = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CursorCodecError("cursor state is not JSON serializable") from exc
        signature = hmac.new(self._secret, raw, hashlib.sha256).digest()
        token = "v%d.%s.%s" % (
            CONTRACT_VERSION,
            _b64_encode(raw),
            _b64_encode(signature),
        )
        if len(token) > self._max_token_length:
            raise CursorCodecError("cursor is too large")
        return token

    def decode(
        self,
        token: str,
        *,
        expected_source: Optional[str] = None,
        expected_kind: Optional[str] = None,
        expected_query_key: Optional[str] = None,
        now: Optional[int] = None,
    ) -> CursorPayload:
        if not isinstance(token, str) or not token or len(token) > self._max_token_length:
            raise CursorCodecError("invalid cursor")
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "v%d" % CONTRACT_VERSION:
            raise CursorCodecError("unsupported cursor version")
        raw = _b64_decode(parts[1])
        signature = _b64_decode(parts[2])
        expected_signature = hmac.new(self._secret, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise CursorCodecError("invalid cursor signature")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CursorCodecError("invalid cursor payload") from exc
        if not isinstance(data, dict) or data.get("v") != CONTRACT_VERSION:
            raise CursorCodecError("unsupported cursor payload")
        state = data.get("state")
        if not isinstance(state, dict):
            raise CursorCodecError("invalid cursor state")
        source = data.get("source")
        kind = data.get("kind")
        query_key = data.get("queryKey")
        issued_at = data.get("iat")
        if not isinstance(source, str) or not isinstance(kind, str):
            raise CursorCodecError("invalid cursor identity")
        if not isinstance(query_key, str) or not isinstance(issued_at, int):
            raise CursorCodecError("invalid cursor metadata")
        if expected_source is not None and source != expected_source:
            raise CursorCodecError("cursor belongs to a different provider")
        if expected_kind is not None and kind != expected_kind:
            raise CursorCodecError("cursor belongs to a different request kind")
        if expected_query_key is not None and query_key != expected_query_key:
            raise CursorCodecError("cursor belongs to a different query")
        current_time = int(time.time() if now is None else now)
        if issued_at > current_time + 300:
            raise CursorCodecError("cursor issue time is in the future")
        if self._ttl_seconds is not None and current_time - issued_at > self._ttl_seconds:
            raise CursorCodecError("cursor has expired")
        return CursorPayload(source, kind, query_key, state, issued_at)

