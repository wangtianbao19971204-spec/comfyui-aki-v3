#!/usr/bin/env python3
"""Build a conservative Chinese tag pack from Wikidata's CC0 API.

Only untranslated, short copyright/character tags already present in the local
database are queried.  A result is accepted only when an exact English
Wikipedia sitelink resolves to a matching Wikidata entity, its English
description matches the Danbooru category, a Simplified Chinese label exists,
and every parenthesized identity qualifier is preserved.  The API evidence is
checkpointed as JSONL; this tool never writes SQLite.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"
API_URL = "https://www.wikidata.org/w/api.php"
SOURCE_PAGE = "https://www.wikidata.org/wiki/Wikidata:Data_access"
SOURCE_LICENSE = "CC0-1.0"
USER_AGENT = "ComfyUI-Danbooru-Gallery-TagAudit/1.0"
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_API_RETRIES = 6
BASE_RETRY_SECONDS = 2.0
MAX_RETRY_DELAY_SECONDS = 300.0
RETRYABLE_HTTP_STATUS = frozenset((429, 503, 504))
ALLOWED_CATEGORIES = frozenset((3, 4))
CATEGORY_NAMES = {3: "copyright", 4: "character"}

_SPACE_RE = re.compile(r"\s+")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WORK_DESCRIPTION_RE = re.compile(
    r"\b(?:anime|brand|company|comic|film|franchise|game|manga|media|novel|"
    r"series|software|television|video game|visual novel|webcomic)\b",
    re.IGNORECASE,
)
_CHARACTER_DESCRIPTION_RE = re.compile(
    r"\b(?:character|mascot|protagonist|antagonist|pok[eé]mon species)\b",
    re.IGNORECASE,
)
_DISAMBIGUATION_RE = re.compile(r"referred to by the same term|disambiguation", re.IGNORECASE)
_TITLE_SMALL_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "but",
        "by",
        "for",
        "from",
        "in",
        "nor",
        "of",
        "on",
        "or",
        "per",
        "the",
        "to",
        "via",
        "vs",
        "with",
    }
)
_TITLE_WORD_RE = re.compile(r"^([^\w]*)([\w]+)([^\w]*)$", re.UNICODE)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    left = Path(left).expanduser().resolve()
    right = Path(right).expanduser().resolve()
    if str(left).casefold() == str(right).casefold():
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def _validate_distinct_paths(named_paths: Sequence[Tuple[str, Path]]) -> None:
    resolved = [(name, Path(path).expanduser().resolve()) for name, path in named_paths]
    for index, (left_name, left_path) in enumerate(resolved):
        for right_name, right_path in resolved[index + 1 :]:
            if _paths_refer_to_same_file(left_path, right_path):
                raise ValueError(
                    "{} and {} paths must be distinct files "
                    "(resolved path/hard-link collision)".format(left_name, right_name)
                )


def _recheck_artifact_path(
    artifact_name: str,
    artifact_path: Path,
    protected_paths: Sequence[Tuple[str, Path]],
) -> None:
    _validate_distinct_paths([(artifact_name, artifact_path), *protected_paths])


def normalize_title(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _SPACE_RE.sub(" ", value).casefold()


def tag_to_title(tag: str) -> str:
    value = unicodedata.normalize("NFKC", tag).replace(r"\(", "(").replace(r"\)", ")")
    return _SPACE_RE.sub(" ", value.replace("_", " ")).strip()


def title_lookup_variants(title: str) -> Tuple[str, ...]:
    """Return a small deterministic set of exact-title lookup candidates.

    Danbooru tags are normally lowercase while ``wbgetentities`` title lookup
    is case-sensitive enough that the lowercase spelling can be reported as
    missing.  These variants only alter casing; the returned entity must still
    pass the original-title sitelink equality check in :func:`fetch_entities`
    and :func:`validate_entity`.
    """

    original = _SPACE_RE.sub(
        " ", unicodedata.normalize("NFKC", str(title or "")).strip()
    )
    if not original:
        return ()
    title_cased = original.title()
    words = title_cased.split(" ")
    conservative_words: List[str] = []
    for index, word in enumerate(words):
        match = _TITLE_WORD_RE.fullmatch(word)
        if index and match and match.group(2).casefold() in _TITLE_SMALL_WORDS:
            word = "{}{}{}".format(
                match.group(1), match.group(2).casefold(), match.group(3)
            )
        conservative_words.append(word)
    conservative_title = " ".join(conservative_words)

    variants: List[str] = []
    for variant in (original, title_cased, conservative_title):
        if variant and variant not in variants:
            variants.append(variant)
    return tuple(variants)


def candidate_reason(tag: str, category: int, max_words: int, max_chars: int) -> str:
    if category not in ALLOWED_CATEGORIES:
        return "disallowed_category"
    if len(tag) > max_chars:
        return "tag_length"
    words = [part for part in re.split(r"[_\s-]+", tag) if part]
    if len(words) > max_words:
        return "word_count"
    return ""


def select_candidates(
    db_path: Path,
    max_words: int = 6,
    max_chars: int = 64,
    limit: Optional[int] = None,
) -> Tuple[List[Dict[str, object]], Counter]:
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    counts = Counter()
    uri = "file:{}?mode=ro".format(urllib.parse.quote(db_path.resolve().as_posix(), safe="/:"))
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        rows: List[Dict[str, object]] = []
        for row in connection.execute(
            """
            SELECT tag, category, post_count
            FROM hot_tags
            WHERE NULLIF(TRIM(translation_cn), '') IS NULL
            ORDER BY post_count DESC, tag ASC
            """
        ):
            tag = str(row["tag"])
            category = int(row["category"])
            reason = candidate_reason(tag, category, max_words, max_chars)
            if reason:
                counts["skipped_" + reason] += 1
                continue
            rows.append(
                {
                    "tag": tag,
                    "category": category,
                    "post_count": int(row["post_count"]),
                    "title": tag_to_title(tag),
                }
            )
        if limit is not None:
            counts["eligible_before_limit"] = len(rows)
            counts["skipped_limit"] = max(0, len(rows) - limit)
            rows = rows[:limit]
        counts["selected"] = len(rows)
        return rows, counts
    finally:
        connection.close()


def _safe_qualifier_translation(value: object) -> Optional[str]:
    translation = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not translation:
        return None
    if "(" in translation or ")" in translation:
        return None
    if _KANA_RE.search(translation) or _HANGUL_RE.search(translation):
        return None
    if _CONTROL_RE.search(translation):
        return None
    return translation


def load_qualifier_translations(db_path: Path) -> Dict[str, str]:
    """Load exact, existing non-artist qualifier translations read-only."""

    uri = "file:{}?mode=ro".format(
        urllib.parse.quote(db_path.resolve().as_posix(), safe="/:")
    )
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        output: Dict[str, str] = {}
        for row in connection.execute(
            """
            SELECT tag, translation_cn
            FROM hot_tags
            WHERE category <> 1
              AND NULLIF(TRIM(translation_cn), '') IS NOT NULL
            """
        ):
            tag = str(row["tag"])
            translation = _safe_qualifier_translation(row["translation_cn"])
            if translation is not None:
                output[tag] = translation
        return output
    finally:
        connection.close()


class WikidataAPIError(RuntimeError):
    """Raised for a non-retryable or exhausted Wikidata API error."""


def load_cache(
    path: Path,
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> Dict[str, Dict[str, object]]:
    output: Dict[str, Dict[str, object]] = {}
    if not path.exists():
        return output
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    valid_bytes = 0
    for index, encoded_line in enumerate(lines):
        if not encoded_line.strip():
            valid_bytes += len(encoded_line)
            continue
        try:
            row = json.loads(encoded_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            is_truncated_tail = (
                index == len(lines) - 1
                and not encoded_line.endswith((b"\n", b"\r"))
            )
            if not is_truncated_tail:
                raise
            # A process can be interrupted in the middle of the final append.
            # Remove only that incomplete tail; complete earlier batches remain
            # authoritative and the missing titles will be fetched on resume.
            _recheck_artifact_path("cache", path, protected_paths)
            with path.open("r+b") as handle:
                handle.truncate(valid_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            break
        if not isinstance(row, Mapping):
            raise ValueError("cache row must be a JSON object")
        title = normalize_title(row.get("requested_title"))
        if title:
            output[title] = dict(row)
        valid_bytes += len(encoded_line)
    return output


def append_cache(
    path: Path,
    rows: Iterable[Mapping[str, object]],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ).encode("utf-8")
    needs_separator = False
    if path.is_file() and path.stat().st_size:
        with path.open("rb") as existing:
            existing.seek(-1, os.SEEK_END)
            needs_separator = existing.read(1) not in (b"\n", b"\r")
    _recheck_artifact_path("cache", path, protected_paths)
    with path.open("ab") as handle:
        if needs_separator:
            handle.write(b"\n")
        if payload:
            # One append per successful API batch minimizes the chance of a
            # partially written checkpoint; load_cache repairs a truncated tail.
            handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _purge_cache_keys(
    path: Path,
    cache: Dict[str, Dict[str, object]],
    stale_keys: Sequence[str],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> int:
    if not stale_keys:
        return 0
    stale = set(stale_keys)
    retained = [row for key, row in cache.items() if key not in stale]
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            for row in retained:
                handle.write(
                    (
                        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                    ).encode("utf-8")
                )
            handle.flush()
            os.fsync(handle.fileno())
        _recheck_artifact_path("cache", path, protected_paths)
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    for key in stale_keys:
        cache.pop(key, None)
    return len(stale_keys)


def purge_unverified_null_cache_entries(
    path: Path,
    cache: Dict[str, Dict[str, object]],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> int:
    """Atomically remove legacy null results that lack verified lookup status."""

    stale_keys = [
        key
        for key, row in cache.items()
        if row.get("entity") is None and row.get("lookup_status") != "not_found"
    ]
    return _purge_cache_keys(
        path, cache, stale_keys, protected_paths=protected_paths
    )


def purge_null_cache_entries(
    path: Path,
    cache: Dict[str, Dict[str, object]],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> Tuple[int, int]:
    """Atomically remove every null lookup so improved variants can retry it.

    Returns ``(all_null_rows, verified_not_found_rows)``.  Keeping the second
    count makes an explicitly requested re-fetch auditable while distinguishing
    it from legacy ambiguous rows produced by older builder versions.
    """

    stale_keys = [key for key, row in cache.items() if row.get("entity") is None]
    verified_not_found = sum(
        1
        for key in stale_keys
        if cache[key].get("lookup_status") == "not_found"
    )
    return (
        _purge_cache_keys(
            path, cache, stale_keys, protected_paths=protected_paths
        ),
        verified_not_found,
    )


def _numeric_delay(value: object) -> Optional[float]:
    try:
        delay = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(delay) or delay < 0:
        return None
    return delay


def _retry_after_seconds(headers: object) -> Optional[float]:
    if headers is None or not hasattr(headers, "get"):
        return None
    raw_value = headers.get("Retry-After")
    numeric = _numeric_delay(raw_value)
    if numeric is not None:
        return numeric
    if not raw_value:
        return None
    try:
        retry_at = parsedate_to_datetime(str(raw_value))
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(
        0.0,
        (retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds(),
    )


def _maxlag_delay(error: Mapping[str, object], headers: object) -> Optional[float]:
    hints = [_retry_after_seconds(headers)]
    for key in ("retry-after", "lag"):
        hints.append(_numeric_delay(error.get(key)))
    data = error.get("data")
    if isinstance(data, Mapping):
        for key in ("retry-after", "lag"):
            hints.append(_numeric_delay(data.get(key)))
    usable = [hint for hint in hints if hint is not None]
    return max(usable) if usable else None


def _retry_delay(attempt: int, server_hint: Optional[float] = None) -> float:
    exponential = BASE_RETRY_SECONDS * (2**attempt)
    requested = max(exponential, server_hint or 0.0)
    return min(requested, MAX_RETRY_DELAY_SECONDS)


def _sleep_for_retry(
    attempt: int, retries: int, server_hint: Optional[float] = None
) -> None:
    if attempt + 1 >= retries:
        return
    time.sleep(_retry_delay(attempt, server_hint))


def _post_api(
    parameters: Mapping[str, str], retries: int = DEFAULT_API_RETRIES
) -> Mapping[str, object]:
    if retries < 1:
        raise ValueError("retries must be at least 1")
    body = urllib.parse.urlencode(parameters).encode("utf-8")
    for attempt in range(retries):
        # A fresh Request per attempt avoids carrying response-specific state
        # across retries in alternative urllib handlers.
        request = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                response_headers = getattr(response, "headers", None)
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code not in RETRYABLE_HTTP_STATUS or attempt + 1 >= retries:
                raise
            _sleep_for_retry(
                attempt, retries, _retry_after_seconds(getattr(error, "headers", None))
            )
            continue
        except (
            urllib.error.URLError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            if attempt + 1 >= retries:
                raise
            _sleep_for_retry(attempt, retries)
            continue
        if not isinstance(payload, Mapping):
            raise WikidataAPIError("Wikidata API returned a non-object response")
        api_error = payload.get("error")
        if isinstance(api_error, Mapping):
            code = str(api_error.get("code") or "unknown")
            info = str(api_error.get("info") or "")
            if code.casefold() == "maxlag":
                if attempt + 1 >= retries:
                    raise WikidataAPIError(
                        "Wikidata maxlag persisted after {} attempts: {}".format(
                            retries, info
                        )
                    )
                _sleep_for_retry(
                    attempt, retries, _maxlag_delay(api_error, response_headers)
                )
                continue
            raise WikidataAPIError(
                "Wikidata API error {}: {}".format(code, info).rstrip()
            )
        return payload
    raise RuntimeError("unreachable")


def _fetch_title_variant_batch(titles: Sequence[str]) -> Mapping[str, object]:
    return _post_api(
        {
            "action": "wbgetentities",
            "format": "json",
            "formatversion": "2",
            "sites": "enwiki",
            "titles": "|".join(titles),
            "props": "labels|descriptions|sitelinks|info",
            "languages": "en|zh-hans|zh-cn|zh",
            "sitefilter": "enwiki|zhwiki",
            "maxlag": "5",
        }
    )


def fetch_entities(titles: Sequence[str]) -> List[Dict[str, object]]:
    """Fetch exact enwiki entities using finite casing-only title variants.

    Each API request contains at most one variant per original title, so the
    caller's 50-title batch ceiling remains intact.  An entity returned for a
    redirect, fuzzy match, disambiguated title, or any other spelling change is
    discarded because its enwiki sitelink must normalize exactly to the
    *original* title, not merely to the lookup variant.
    """

    originals = [
        _SPACE_RE.sub(" ", unicodedata.normalize("NFKC", str(title)).strip())
        for title in titles
    ]
    variants_by_title = [title_lookup_variants(title) for title in originals]
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    resolved: Dict[int, Tuple[Mapping[str, object], str]] = {}
    tried: List[List[str]] = [[] for _title in originals]
    maximum_variants = max(
        (len(variants) for variants in variants_by_title), default=0
    )

    for variant_index in range(maximum_variants):
        lookup_titles: List[str] = []
        expected_by_key: Dict[str, List[int]] = {}
        for index, variants in enumerate(variants_by_title):
            if index in resolved or variant_index >= len(variants):
                continue
            variant = variants[variant_index]
            lookup_titles.append(variant)
            tried[index].append(variant)
            expected_by_key.setdefault(
                normalize_title(originals[index]), []
            ).append(index)
        if not lookup_titles:
            continue

        payload = _fetch_title_variant_batch(lookup_titles)
        entities = payload.get("entities") or {}
        if not isinstance(entities, Mapping):
            raise RuntimeError("Wikidata response did not contain an entity map")
        for entity in entities.values():
            if not isinstance(entity, Mapping):
                continue
            sitelinks = entity.get("sitelinks") or {}
            if not isinstance(sitelinks, Mapping):
                continue
            enwiki = sitelinks.get("enwiki") or {}
            if not isinstance(enwiki, Mapping):
                continue
            sitelink_key = normalize_title(enwiki.get("title"))
            for index in expected_by_key.get(sitelink_key, ()):
                # This comparison deliberately uses the original title.  The
                # variant is only a lookup aid and never widens acceptance.
                if sitelink_key == normalize_title(originals[index]):
                    resolved[index] = (entity, variants_by_title[index][variant_index])

    output: List[Dict[str, object]] = []
    for index, requested in enumerate(originals):
        match = resolved.get(index)
        entity = match[0] if match is not None else None
        output.append(
            {
                "requested_title": requested,
                "lookup_variant": match[1] if match is not None else None,
                "lookup_variants_tried": tried[index],
                "fetched_at_utc": fetched_at,
                "api_url": API_URL,
                "entity": entity,
                "lookup_status": "found" if entity is not None else "not_found",
            }
        )
    return output


def _localized_value(entity: Mapping[str, object], field: str, language: str) -> str:
    container = entity.get(field) or {}
    if not isinstance(container, Mapping):
        return ""
    value = container.get(language) or {}
    if not isinstance(value, Mapping):
        return ""
    return str(value.get("value") or "").strip()


def _parenthesis_groups(value: str) -> Optional[List[str]]:
    groups: List[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(value):
        if character == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif character == ")":
            if depth == 0:
                return None
            depth -= 1
            if depth == 0:
                groups.append(value[start:index])
    if depth:
        return None
    return groups


def _reconstruct_qualified_translation(
    base_translation: str,
    source_groups: Sequence[str],
    qualifier_translations: Optional[Mapping[str, str]],
) -> Optional[str]:
    if not qualifier_translations:
        return None
    rebuilt_groups: List[str] = []
    for source_group in source_groups:
        # Nested identity qualifiers cannot be reconstructed without changing
        # the original parenthesis structure, so they remain review-only.
        if "(" in source_group or ")" in source_group:
            return None
        translated_group = _safe_qualifier_translation(
            qualifier_translations.get(source_group)
        )
        if translated_group is None:
            return None
        rebuilt_groups.append(translated_group)
    return base_translation + "".join("({})".format(group) for group in rebuilt_groups)


def validate_entity(
    tag: str,
    category: int,
    evidence: Mapping[str, object],
    qualifier_translations: Optional[Mapping[str, str]] = None,
) -> Tuple[Optional[str], str, Optional[str]]:
    if category not in ALLOWED_CATEGORIES:
        return None, "disallowed_category", None
    entity = evidence.get("entity")
    if not isinstance(entity, Mapping):
        return None, "not_found", None
    entity_id = str(entity.get("id") or "") or None
    sitelinks = entity.get("sitelinks") or {}
    if not isinstance(sitelinks, Mapping):
        return None, "title_mismatch", entity_id
    enwiki = sitelinks.get("enwiki") or {}
    if not isinstance(enwiki, Mapping):
        return None, "title_mismatch", entity_id
    if normalize_title(enwiki.get("title")) != normalize_title(tag_to_title(tag)):
        return None, "title_mismatch", entity_id
    description = _localized_value(entity, "descriptions", "en")
    if not description or _DISAMBIGUATION_RE.search(description):
        return None, "description_rejected", entity_id
    category_pattern = _WORK_DESCRIPTION_RE if category == 3 else _CHARACTER_DESCRIPTION_RE
    if not category_pattern.search(description):
        return None, "category_mismatch", entity_id
    translation = _localized_value(entity, "labels", "zh-hans")
    if not translation:
        translation = _localized_value(entity, "labels", "zh-cn")
    translation = unicodedata.normalize("NFKC", translation).strip()
    if not translation:
        return None, "no_simplified_chinese", entity_id
    if not _HAN_RE.search(translation):
        return None, "no_han", entity_id
    if _KANA_RE.search(translation) or _HANGUL_RE.search(translation):
        return None, "contains_japanese_or_korean", entity_id
    normalized_tag = unicodedata.normalize("NFKC", tag)
    source_groups = _parenthesis_groups(normalized_tag)
    translation_groups = _parenthesis_groups(translation)
    if (
        source_groups is not None
        and translation_groups == []
        and source_groups
        and not any(not group.strip() for group in source_groups)
        and translation.count("(") == 0
        and translation.count(")") == 0
    ):
        reconstructed = _reconstruct_qualified_translation(
            translation, source_groups, qualifier_translations
        )
        if reconstructed is not None:
            if len(reconstructed) > 64:
                return None, "translation_length", entity_id
            return reconstructed, "accepted_reconstructed", entity_id
    if (
        source_groups is None
        or translation_groups is None
        or len(source_groups) != len(translation_groups)
        or any(not group.strip() for group in source_groups)
        or any(not group.strip() for group in translation_groups)
        or normalized_tag.count("(") != translation.count("(")
        or normalized_tag.count(")") != translation.count(")")
    ):
        return None, "qualifier_lost", entity_id
    if len(translation) > 64:
        return None, "translation_length", entity_id
    return translation, "accepted", entity_id


def validate_artifact_paths(
    db_path: Path, output_path: Path, cache_path: Path, report_path: Path
) -> None:
    artifacts = [
        ("output", output_path),
        ("cache", cache_path),
        ("report", report_path),
    ]
    for name, path in artifacts:
        if _paths_refer_to_same_file(db_path, path):
            raise ValueError("{} path must not overwrite the database".format(name))
    _validate_distinct_paths(artifacts)


def _atomic_write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    protected_paths: Sequence[Tuple[str, Path]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "tag", "category", "post_count", "translation_cn",
                    "confidence", "wikidata_id",
                ),
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        _recheck_artifact_path("output", path, protected_paths)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _atomic_write_json(
    path: Path,
    payload: Mapping[str, object],
    *,
    protected_paths: Sequence[Tuple[str, Path]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _recheck_artifact_path("report", path, protected_paths)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def build_pack(
    db_path: Path,
    output_path: Path,
    cache_path: Path,
    report_path: Path,
    batch_size: int = 40,
    max_words: int = 6,
    max_chars: int = 64,
    request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
    refetch_null_cache: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, object]:
    db_path = Path(db_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    cache_path = Path(cache_path).expanduser().resolve()
    report_path = Path(report_path).expanduser().resolve()
    if not db_path.is_file():
        raise ValueError("database not found: {}".format(db_path))
    if not 1 <= batch_size <= 50:
        raise ValueError("batch_size must be between 1 and 50")
    if not math.isfinite(request_interval_seconds) or request_interval_seconds < 0:
        raise ValueError("request_interval_seconds must be a non-negative number")
    validate_artifact_paths(db_path, output_path, cache_path, report_path)
    cache_protected = [
        ("database", db_path),
        ("output", output_path),
        ("report", report_path),
    ]
    candidates, selection = select_candidates(db_path, max_words, max_chars, limit)
    qualifier_translations = load_qualifier_translations(db_path)
    cache = load_cache(cache_path, protected_paths=cache_protected)
    purged_null_rows = 0
    purged_verified_not_found_rows = 0
    if refetch_null_cache:
        purged_null_rows, purged_verified_not_found_rows = purge_null_cache_entries(
            cache_path, cache, protected_paths=cache_protected
        )
    purged_unverified_null_rows = (
        purged_null_rows - purged_verified_not_found_rows
    )
    requested_titles = []
    all_title_keys = set()
    cached_titles_before = 0
    for row in candidates:
        title_key = normalize_title(row["title"])
        if title_key in all_title_keys:
            continue
        all_title_keys.add(title_key)
        if title_key in cache:
            cached_titles_before += 1
        else:
            requested_titles.append(str(row["title"]))
    requests_made = 0
    for offset in range(0, len(requested_titles), batch_size):
        fetched = fetch_entities(requested_titles[offset : offset + batch_size])
        # Persist every complete batch before sleeping or starting the next one.
        # If a later request fails, rerunning reads these rows and requests only
        # the still-missing titles.
        append_cache(cache_path, fetched, protected_paths=cache_protected)
        for row in fetched:
            cache[normalize_title(row["requested_title"])] = row
        requests_made += 1
        print(json.dumps({"wikidata_requests": requests_made, "titles_fetched": min(offset + batch_size, len(requested_titles))}), flush=True)
        if (
            request_interval_seconds > 0
            and offset + batch_size < len(requested_titles)
        ):
            time.sleep(request_interval_seconds)

    # Keep the report reproducible even when there were no candidates and thus
    # no API calls: the empty checkpoint itself is still a hashed snapshot.
    if not cache_path.exists():
        append_cache(cache_path, (), protected_paths=cache_protected)

    accepted: List[Dict[str, object]] = []
    rejected = Counter()
    reconstructed_rows = 0
    reconstructed_qualifiers = 0
    for row in candidates:
        evidence = cache.get(normalize_title(row["title"]), {})
        translation, reason, entity_id = validate_entity(
            str(row["tag"]),
            int(row["category"]),
            evidence,
            qualifier_translations,
        )
        if translation is None:
            rejected[reason] += 1
            continue
        if reason == "accepted_reconstructed":
            reconstructed_rows += 1
            reconstructed_qualifiers += len(
                _parenthesis_groups(unicodedata.normalize("NFKC", str(row["tag"])))
                or []
            )
        accepted.append(
            {
                "tag": row["tag"],
                "category": row["category"],
                "post_count": row["post_count"],
                "translation_cn": translation,
                "confidence": "H",
                "wikidata_id": entity_id,
            }
        )

    _atomic_write_csv(
        output_path,
        accepted,
        protected_paths=[
            ("database", db_path),
            ("cache", cache_path),
            ("report", report_path),
        ],
    )
    report = {
        "source": {
            "name": "Wikidata",
            "api_url": API_URL,
            "source_page": SOURCE_PAGE,
            "license": SOURCE_LICENSE,
            "snapshot_cache": str(cache_path.resolve()),
            "snapshot_cache_sha256": file_sha256(cache_path),
            "revision_policy": "per-entity lastrevid in checkpointed API payload",
        },
        "input": {"database": str(db_path.resolve()), "database_sha256": file_sha256(db_path)},
        "selection": dict(selection),
        "fetch": {
            "unique_titles": len(all_title_keys),
            "cached_titles_before": cached_titles_before,
            "new_titles": len(requested_titles),
            "requests_made": requests_made,
            "request_interval_seconds": request_interval_seconds,
            "purged_unverified_null_cache_rows": purged_unverified_null_rows,
            "purged_verified_not_found_cache_rows": (
                purged_verified_not_found_rows
            ),
        },
        "output": {
            "csv": str(output_path.resolve()),
            "rows": len(accepted),
            "by_category": dict(Counter(CATEGORY_NAMES[int(row["category"])] for row in accepted)),
            "reconstructed_rows": reconstructed_rows,
            "reconstructed_qualifiers": reconstructed_qualifiers,
            "qualifier_translation_entries": len(qualifier_translations),
            "sha256": file_sha256(output_path),
        },
        "rejected": dict(sorted(rejected.items())),
        "artist_allowed": False,
        "existing_translations_preserved": True,
    }
    _atomic_write_json(
        report_path,
        report,
        protected_paths=[
            ("database", db_path),
            ("cache", cache_path),
            ("output", output_path),
        ],
    )
    return report


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument(
        "--request-interval-seconds",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL_SECONDS,
        help="Minimum pause between successful API batches (default: %(default)s)",
    )
    parser.add_argument(
        "--refetch-null-cache",
        action="store_true",
        help=(
            "Atomically purge every entity=null cache row, including verified "
            "not_found rows, and fetch it again using the current exact-title "
            "lookup variants"
        ),
    )
    parser.add_argument("--max-words", type=int, default=6)
    parser.add_argument("--max-tag-chars", type=int, default=64)
    parser.add_argument(
        "--limit",
        type=int,
        help="query only the highest-post-count eligible tags (for bounded audits)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if not 1 <= args.batch_size <= 50:
        raise SystemExit("--batch-size must be between 1 and 50")
    if (
        not math.isfinite(args.request_interval_seconds)
        or args.request_interval_seconds < 0
    ):
        raise SystemExit("--request-interval-seconds must be non-negative")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    report = build_pack(
        args.db,
        args.output,
        args.cache,
        args.report,
        args.batch_size,
        args.max_words,
        args.max_tag_chars,
        args.request_interval_seconds,
        args.refetch_null_cache,
        args.limit,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
