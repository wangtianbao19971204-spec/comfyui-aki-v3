#!/usr/bin/env python3
"""Fetch exact-match Chinese subject/character evidence from Bangumi's API.

The command reads a Gallery target CSV, hard-excludes every category except
copyright (3) and character (4), and never opens or modifies the Gallery DB.
Every successful API response is durably appended to a raw JSONL cache before
processing continues, so an interrupted run can resume without repeating
completed requests.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import os
import re
import socket
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple


API_BASE = "https://api.bgm.tv"
API_DOCS_URL = "https://bangumi.github.io/api/"
DEFAULT_USER_AGENT = (
    "ComfyUI-Danbooru-Gallery/5.3 "
    "(Bangumi translation evidence audit; local desktop user)"
)
DEFAULT_MIN_INTERVAL = 0.75
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 4
DEFAULT_PAGE_SIZE = 10
DEFAULT_MAX_RESULTS = 20
ELIGIBLE_CATEGORIES = frozenset((3, 4))

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_QUALIFIER_RE = re.compile(r"(?:_?\([^()]*\))+$")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")

CANDIDATE_COLUMNS = (
    "rank",
    "tag",
    "category",
    "category_name",
    "post_count",
    "translation_cn",
    "translation_scope",
    "requires_qualifier_reconstruction",
    "name_head",
    "source_qualifiers_json",
    "bangumi_entity_type",
    "bangumi_id",
    "bangumi_url",
    "query",
    "match_field",
    "match_value",
    "translation_field",
    "entity_name",
    "confidence",
    "review_status",
    "source_name",
    "source_url",
    "evidence_json",
)


class BangumiFetchError(RuntimeError):
    """Raised when input/API/cache/output safety prevents a complete build."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_exact_identity(value: object) -> str:
    """Conservative exact key: NFKC/casefold, retaining only letters/digits."""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def split_name_head(tag: object) -> Tuple[str, list[str]]:
    source = unicodedata.normalize("NFKC", str(tag or "")).strip()
    match = _TRAILING_QUALIFIER_RE.search(source)
    if not match:
        return source, []
    suffix = match.group(0)
    head = source[: match.start()].rstrip("_")
    qualifiers = [value.strip() for value in re.findall(r"\(([^()]*)\)", suffix)]
    return head or source, qualifiers


def query_from_name_head(name_head: str) -> str:
    query = unicodedata.normalize("NFKC", name_head).replace(r"\(", "(").replace(r"\)", ")")
    query = _WHITESPACE_RE.sub(" ", query.replace("_", " ")).strip()
    return query


def _valid_chinese(value: object) -> Optional[str]:
    translation = unicodedata.normalize("NFKC", str(value or "")).strip()
    translation = _WHITESPACE_RE.sub(" ", translation)
    if (
        not translation
        or _CONTROL_RE.search(translation)
        or not _HAN_RE.search(translation)
        or _KANA_RE.search(translation)
        or _HANGUL_RE.search(translation)
        or len(translation.encode("utf-8")) > 512
    ):
        return None
    return translation


def _flatten_infobox_value(value: object) -> list[Tuple[str, str]]:
    if isinstance(value, str):
        return [("", value)]
    output: list[Tuple[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                output.append(("", item))
            elif isinstance(item, Mapping):
                label = str(item.get("k") or "")
                candidate = item.get("v")
                if isinstance(candidate, str):
                    output.append((label, candidate))
    return output


def _infobox_items(entity: Mapping[str, object]) -> Iterable[Tuple[str, object]]:
    infobox = entity.get("infobox")
    if not isinstance(infobox, list):
        return ()
    output = []
    for item in infobox:
        if isinstance(item, Mapping):
            output.append((str(item.get("key") or ""), item.get("value")))
    return output


def entity_match_fields(entity: Mapping[str, object]) -> list[Tuple[str, str]]:
    fields: list[Tuple[str, str]] = []
    name = str(entity.get("name") or "").strip()
    if name:
        fields.append(("name", name))
    for key, value in _infobox_items(entity):
        normalized_key = normalize_exact_identity(key)
        is_alias = (
            "别名" in key
            or "alias" in key.casefold()
            or any(
                marker in normalized_key
                for marker in ("英文名", "罗马字", "羅馬字", "原名", "日文名")
            )
        )
        if not is_alias:
            continue
        for label, candidate in _flatten_infobox_value(value):
            candidate = candidate.strip()
            if candidate:
                field = "infobox:{}".format(key)
                if label:
                    field += "/{}".format(label)
                fields.append((field, candidate))
    deduplicated = []
    seen = set()
    for field, value in fields:
        key = (field, value)
        if key not in seen:
            seen.add(key)
            deduplicated.append((field, value))
    return deduplicated


def exact_entity_match(
    target_identity: str, entity: Mapping[str, object]
) -> Optional[Tuple[str, str]]:
    for field, value in entity_match_fields(entity):
        if normalize_exact_identity(value) == target_identity:
            return field, value
    return None


def simplified_character_names(entity: Mapping[str, object]) -> list[str]:
    candidates = []
    for key, value in _infobox_items(entity):
        if normalize_exact_identity(key) != normalize_exact_identity("简体中文名"):
            continue
        for _label, raw in _flatten_infobox_value(value):
            translation = _valid_chinese(raw)
            if translation and translation not in candidates:
                candidates.append(translation)
    return candidates


def _canonical_request_key(
    method: str,
    path: str,
    query: Mapping[str, object],
    body: Optional[Mapping[str, object]],
) -> str:
    canonical = json.dumps(
        {
            "method": method.upper(),
            "path": path,
            "query": dict(sorted((str(key), value) for key, value in query.items())),
            "body": body,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class HttpTransport:
    """Rate-limited stdlib HTTP transport with bounded retries."""

    def __init__(
        self,
        *,
        user_agent: str,
        access_token: Optional[str] = None,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not str(user_agent or "").strip() or _CONTROL_RE.search(user_agent):
            raise BangumiFetchError("a non-empty safe User-Agent is required")
        if min_interval < 0 or timeout <= 0 or max_retries < 0:
            raise BangumiFetchError("invalid HTTP timing/retry configuration")
        self.user_agent = user_agent.strip()
        self.access_token = str(access_token or "").strip() or None
        self.min_interval = float(min_interval)
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        delay = self.min_interval - elapsed
        if delay > 0:
            time.sleep(delay)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, object],
        body: Optional[Mapping[str, object]],
    ) -> Mapping[str, object]:
        encoded_query = urllib.parse.urlencode(query)
        url = API_BASE + path + ("?" + encoded_query if encoded_query else "")
        payload = None
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = "Bearer " + self.access_token
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        retryable_statuses = {429, 500, 502, 503, 504}
        for attempt in range(self.max_retries + 1):
            self._throttle()
            request = urllib.request.Request(
                url, data=payload, headers=headers, method=method.upper()
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    self._last_request = time.monotonic()
                    decoded = json.loads(raw.decode("utf-8"))
                    if not isinstance(decoded, Mapping):
                        raise BangumiFetchError("Bangumi returned a non-object JSON response")
                    return decoded
            except urllib.error.HTTPError as exc:
                self._last_request = time.monotonic()
                if exc.code not in retryable_statuses or attempt >= self.max_retries:
                    raise BangumiFetchError(
                        "Bangumi HTTP {} for {} {}".format(exc.code, method, path)
                    ) from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    delay = 2 ** attempt
                time.sleep(min(max(delay, self.min_interval), 60.0))
            except (
                urllib.error.URLError,
                socket.timeout,
                TimeoutError,
                ConnectionError,
                http.client.HTTPException,
            ) as exc:
                self._last_request = time.monotonic()
                if attempt >= self.max_retries:
                    raise BangumiFetchError(
                        "Bangumi network failure for {} {}: {}".format(method, path, exc)
                    ) from exc
                time.sleep(min(max(2 ** attempt, self.min_interval), 60.0))
        raise AssertionError("unreachable")


class CachedBangumiClient:
    """Request-level durable JSONL cache used as the resume checkpoint."""

    def __init__(self, transport, cache_path: Path | str) -> None:
        self.transport = transport
        self.cache_path = Path(cache_path).expanduser().resolve()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.responses: Dict[str, Mapping[str, object]] = {}
        self.cache_hits = 0
        self.network_requests = 0
        self.invalid_cache_lines = 0
        if self.cache_path.exists():
            with self.cache_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        self.invalid_cache_lines += 1
                        continue
                    if (
                        isinstance(record, Mapping)
                        and record.get("ok") is True
                        and isinstance(record.get("response"), Mapping)
                        and isinstance(record.get("request_key"), str)
                    ):
                        self.responses[str(record["request_key"])] = record["response"]

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, object]] = None,
        body: Optional[Mapping[str, object]] = None,
    ) -> Mapping[str, object]:
        query = dict(query or {})
        key = _canonical_request_key(method, path, query, body)
        cached = self.responses.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached
        response = self.transport.request_json(
            method, path, query=query, body=body
        )
        record = {
            "request_key": key,
            "retrieved_at": _utc_now(),
            "method": method.upper(),
            "path": path,
            "query": query,
            "body": body,
            "ok": True,
            "response": response,
        }
        with self.cache_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.responses[key] = response
        self.network_requests += 1
        return response


def _search(
    client: CachedBangumiClient,
    endpoint: str,
    keyword: str,
    *,
    page_size: int,
    max_results: int,
) -> list[Mapping[str, object]]:
    output: list[Mapping[str, object]] = []
    seen_ids = set()
    offset = 0
    while offset < max_results:
        limit = min(page_size, max_results - offset)
        payload = client.request(
            "POST",
            endpoint,
            query={"limit": limit, "offset": offset},
            body={"keyword": keyword},
        )
        data = payload.get("data")
        if not isinstance(data, list):
            raise BangumiFetchError("{} response is missing data[]".format(endpoint))
        for item in data:
            if not isinstance(item, Mapping):
                continue
            entity_id = item.get("id")
            if entity_id not in seen_ids:
                seen_ids.add(entity_id)
                output.append(item)
        try:
            total = int(payload.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        if len(data) < limit or offset + limit >= total:
            break
        offset += limit
    return output


def _load_targets(path: Path) -> list[Dict[str, str]]:
    if not path.is_file():
        raise BangumiFetchError("target CSV is missing: {}".format(path))
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"rank", "tag", "category", "post_count"}
        missing = sorted(required - set(reader.fieldnames or ()))
        if missing:
            raise BangumiFetchError("target CSV is missing columns: {}".format(", ".join(missing)))
        for raw in reader:
            row = {str(key): str(value or "") for key, value in raw.items()}
            try:
                int(row["rank"])
                int(row["category"])
                int(row["post_count"])
            except ValueError as exc:
                raise BangumiFetchError("target row has invalid numeric metadata") from exc
            rows.append(row)
    return rows


def _candidate_row(
    target: Mapping[str, str],
    *,
    name_head: str,
    qualifiers: Sequence[str],
    translation: str,
    entity_type: str,
    entity: Mapping[str, object],
    query: str,
    match: Tuple[str, str],
    translation_field: str,
) -> Dict[str, object]:
    entity_id = int(entity["id"])
    url = "https://bgm.tv/{}/{}".format(
        "subject" if entity_type == "subject" else "character", entity_id
    )
    evidence = {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "entity_name": str(entity.get("name") or ""),
        "match_field": match[0],
        "match_value": match[1],
        "translation_field": translation_field,
        "translation_value": translation,
        "normalization": "NFKC+whitespace_only; no_OpenCC",
        "target_identity": normalize_exact_identity(name_head),
        "source_qualifiers": list(qualifiers),
        "api_url": url,
    }
    return {
        "rank": target["rank"],
        "tag": target["tag"],
        "category": target["category"],
        "category_name": target.get("category_name", ""),
        "post_count": target["post_count"],
        "translation_cn": translation,
        "translation_scope": "name_head_only" if qualifiers else "full_tag",
        "requires_qualifier_reconstruction": "yes" if qualifiers else "no",
        "name_head": name_head,
        "source_qualifiers_json": json.dumps(list(qualifiers), ensure_ascii=False),
        "bangumi_entity_type": entity_type,
        "bangumi_id": entity_id,
        "bangumi_url": url,
        "query": query,
        "match_field": match[0],
        "match_value": match[1],
        "translation_field": translation_field,
        "entity_name": str(entity.get("name") or ""),
        "confidence": "H",
        "review_status": "verification_only_exact_api_evidence",
        "source_name": "Bangumi API",
        "source_url": url,
        "evidence_json": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
    }


def _evaluate_subject(
    client: CachedBangumiClient,
    target: Mapping[str, str],
    *,
    page_size: int,
    max_results: int,
) -> Tuple[Optional[Dict[str, object]], Dict[str, object]]:
    name_head, qualifiers = split_name_head(target["tag"])
    identity = normalize_exact_identity(name_head)
    query = query_from_name_head(name_head)
    results = _search(
        client, "/v0/search/subjects", query,
        page_size=page_size, max_results=max_results,
    )
    exact = []
    for entity in results:
        match = exact_entity_match(identity, entity)
        if match:
            exact.append((entity, match))
    evidence = {
        "tag": target["tag"], "category": 3, "query": query,
        "name_head": name_head, "qualifiers": qualifiers,
        "search_results": len(results),
        "exact_entity_ids": [item[0].get("id") for item in exact],
    }
    if not exact:
        evidence["decision"] = "no_exact_entity_match"
        return None, evidence
    if len(exact) != 1:
        evidence["decision"] = "ambiguous_exact_entity_match"
        return None, evidence
    entity, match = exact[0]
    translation = _valid_chinese(entity.get("name_cn"))
    if not translation:
        evidence["decision"] = "exact_entity_without_simplified_chinese"
        return None, evidence
    evidence["decision"] = "accepted"
    return _candidate_row(
        target, name_head=name_head, qualifiers=qualifiers,
        translation=translation, entity_type="subject", entity=entity,
        query=query, match=match, translation_field="name_cn",
    ), evidence


def _evaluate_character(
    client: CachedBangumiClient,
    target: Mapping[str, str],
    *,
    page_size: int,
    max_results: int,
) -> Tuple[Optional[Dict[str, object]], Dict[str, object]]:
    name_head, qualifiers = split_name_head(target["tag"])
    identity = normalize_exact_identity(name_head)
    query = query_from_name_head(name_head)
    results = _search(
        client, "/v0/search/characters", query,
        page_size=page_size, max_results=max_results,
    )
    details = []
    for search_entity in results:
        pre_match = exact_entity_match(identity, search_entity)
        infobox_present = isinstance(search_entity.get("infobox"), list) and bool(
            search_entity.get("infobox")
        )
        if pre_match is None and infobox_present:
            continue
        try:
            entity_id = int(search_entity.get("id"))
        except (TypeError, ValueError):
            continue
        detail = client.request(
            "GET", "/v0/characters/{}".format(entity_id), query={}, body=None
        )
        match = exact_entity_match(identity, detail)
        if match:
            details.append((detail, match))
    evidence = {
        "tag": target["tag"], "category": 4, "query": query,
        "name_head": name_head, "qualifiers": qualifiers,
        "search_results": len(results),
        "exact_entity_ids": [item[0].get("id") for item in details],
    }
    if not details:
        evidence["decision"] = "no_exact_entity_match"
        return None, evidence
    if len(details) != 1:
        evidence["decision"] = "ambiguous_exact_entity_match"
        return None, evidence
    detail, match = details[0]
    chinese_names = simplified_character_names(detail)
    if len(chinese_names) != 1:
        evidence["decision"] = (
            "exact_entity_without_simplified_chinese"
            if not chinese_names else "ambiguous_simplified_chinese_name"
        )
        evidence["simplified_chinese_names"] = chinese_names
        return None, evidence
    evidence["decision"] = "accepted"
    return _candidate_row(
        target, name_head=name_head, qualifiers=qualifiers,
        translation=chinese_names[0], entity_type="character", entity=detail,
        query=query, match=match, translation_field="infobox:简体中文名",
    ), evidence


def _validate_outputs(inputs: Sequence[Path], outputs: Sequence[Path]) -> None:
    resolved_inputs = [path.resolve() for path in inputs]
    resolved_outputs = [path.resolve() for path in outputs]
    if len({str(path).casefold() for path in resolved_outputs}) != len(resolved_outputs):
        raise BangumiFetchError("output paths must be distinct")
    for output in resolved_outputs:
        if os.path.lexists(str(output)):
            raise BangumiFetchError("refusing to overwrite existing artifact: {}".format(output))
        if any(str(output).casefold() == str(path).casefold() for path in resolved_inputs):
            raise BangumiFetchError("output path collides with an input")


def _temporary_text(path: Path, encoding: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding=encoding, newline="", dir=path.parent,
        prefix=path.name + ".", suffix=".tmp", delete=False,
    )
    return handle, Path(handle.name)


def _publish_bundle(artifacts: Sequence[Tuple[Path, Path]]) -> None:
    published = []
    try:
        for temporary, target in artifacts:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise BangumiFetchError("refusing to overwrite raced output: {}".format(target)) from exc
            published.append((temporary, target))
    except Exception:
        for temporary, target in reversed(published):
            try:
                if target.exists() and os.path.samefile(temporary, target):
                    target.unlink()
            except OSError:
                pass
        raise
    finally:
        for temporary, _target in artifacts:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def fetch_bangumi_candidates(
    *,
    targets_path: Path | str,
    candidates_output_path: Path | str,
    raw_cache_path: Path | str,
    report_path: Path | str,
    transport,
    expected_eligible_count: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> Dict[str, object]:
    targets_file = Path(targets_path).expanduser().resolve()
    candidates_output = Path(candidates_output_path).expanduser().resolve()
    raw_cache = Path(raw_cache_path).expanduser().resolve()
    report_output = Path(report_path).expanduser().resolve()
    if page_size < 1 or max_results < 1 or page_size > max_results:
        raise BangumiFetchError("invalid page_size/max_results")
    _validate_outputs((targets_file,), (candidates_output, report_output))
    if str(raw_cache).casefold() in {
        str(targets_file).casefold(), str(candidates_output).casefold(), str(report_output).casefold()
    }:
        raise BangumiFetchError("raw cache path must be distinct")
    targets_hash_before = file_sha256(targets_file)
    targets = _load_targets(targets_file)
    eligible = [row for row in targets if int(row["category"]) in ELIGIBLE_CATEGORIES]
    if expected_eligible_count and len(eligible) != expected_eligible_count:
        raise BangumiFetchError(
            "eligible target count is {}; expected {}".format(len(eligible), expected_eligible_count)
        )
    exclusion_counts = Counter()
    for row in targets:
        category = int(row["category"])
        if category not in ELIGIBLE_CATEGORIES:
            if category == 0:
                exclusion_counts["general_hard_excluded"] += 1
            elif category == 1:
                exclusion_counts["artist_hard_excluded"] += 1
            elif category == 5:
                exclusion_counts["meta_hard_excluded"] += 1
            else:
                exclusion_counts["unknown_category_hard_excluded"] += 1

    client = CachedBangumiClient(transport, raw_cache)
    candidates = []
    decisions = Counter()
    rejected = []
    for index, target in enumerate(eligible, start=1):
        if int(target["category"]) == 3:
            candidate, evidence = _evaluate_subject(
                client, target, page_size=page_size, max_results=max_results
            )
        else:
            candidate, evidence = _evaluate_character(
                client, target, page_size=page_size, max_results=max_results
            )
        decision = str(evidence["decision"])
        decisions[decision] += 1
        if candidate is not None:
            candidates.append(candidate)
        else:
            rejected.append(evidence)
        if index % 25 == 0 or index == len(eligible):
            print(
                "[Bangumi] processed {}/{}; accepted={}; cache_hits={}; network={}".format(
                    index,
                    len(eligible),
                    len(candidates),
                    client.cache_hits,
                    client.network_requests,
                ),
                flush=True,
            )

    if file_sha256(targets_file) != targets_hash_before:
        raise BangumiFetchError("target CSV changed during the API run")
    candidate_handle, candidate_temp = _temporary_text(candidates_output, "utf-8-sig")
    report_temp = None
    try:
        writer = csv.DictWriter(candidate_handle, fieldnames=CANDIDATE_COLUMNS)
        writer.writeheader()
        writer.writerows(candidates)
        candidate_handle.flush()
        os.fsync(candidate_handle.fileno())
        candidate_handle.close()
        report = {
            "schema_version": 1,
            "database_mutated": False,
            "source": {
                "name": "Bangumi API",
                "api_base": API_BASE,
                "documentation_url": API_DOCS_URL,
                "endpoints": [
                    "POST /v0/search/subjects",
                    "POST /v0/search/characters",
                    "GET /v0/characters/{id}",
                ],
            },
            "policy": {
                "eligible_categories": [3, 4],
                "general_allowed": False,
                "artist_allowed": False,
                "meta_allowed": False,
                "exact_normalized_identity_only": True,
                "ambiguous_entities_rejected": True,
                "character_requires_detail_simplified_chinese_name": True,
                "qualifiers_reconstructed": False,
                "verification_candidates_only": True,
                "direct_import_allowed": False,
                "opencc_applied": False,
                "page_size": page_size,
                "max_results_per_target": max_results,
            },
            "input": {
                "path": str(targets_file),
                "sha256": targets_hash_before,
                "rows": len(targets),
                "eligible_rows": len(eligible),
            },
            "cache": {
                "path": str(raw_cache),
                "sha256": file_sha256(raw_cache) if raw_cache.exists() else None,
                "cached_responses": len(client.responses),
                "cache_hits": client.cache_hits,
                "network_requests": client.network_requests,
                "invalid_cache_lines_ignored": client.invalid_cache_lines,
            },
            "results": {
                "candidate_rows": len(candidates),
                "decisions": dict(sorted(decisions.items())),
                "hard_exclusions": dict(sorted(exclusion_counts.items())),
                "rejected_rows": len(rejected),
            },
            "output": {
                "path": str(candidates_output),
                "sha256": file_sha256(candidate_temp),
                "rows": len(candidates),
                "columns": list(CANDIDATE_COLUMNS),
            },
            "rejections": rejected,
        }
        report_handle, report_temp = _temporary_text(report_output, "utf-8")
        json.dump(report, report_handle, ensure_ascii=False, indent=2, sort_keys=True)
        report_handle.write("\n")
        report_handle.flush()
        os.fsync(report_handle.fileno())
        report_handle.close()
        _validate_outputs((targets_file,), (candidates_output, report_output))
        _publish_bundle(((candidate_temp, candidates_output), (report_temp, report_output)))
        return report
    except Exception:
        if not candidate_handle.closed:
            candidate_handle.close()
        for temporary in (candidate_temp, report_temp):
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
        raise


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-cache", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-eligible-count", type=int, default=0)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument(
        "--token-env", default="BANGUMI_ACCESS_TOKEN",
        help="environment variable containing an optional Bangumi access token",
    )
    arguments = parser.parse_args(argv)
    token = os.environ.get(arguments.token_env) if arguments.token_env else None
    transport = HttpTransport(
        user_agent=arguments.user_agent,
        access_token=token,
        min_interval=arguments.min_interval,
        timeout=arguments.timeout,
        max_retries=arguments.max_retries,
    )
    report = fetch_bangumi_candidates(
        targets_path=arguments.targets,
        candidates_output_path=arguments.output,
        raw_cache_path=arguments.raw_cache,
        report_path=arguments.report,
        transport=transport,
        expected_eligible_count=arguments.expected_eligible_count,
        page_size=arguments.page_size,
        max_results=arguments.max_results,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
