#!/usr/bin/env python3
"""Safely apply a human-reviewed Phase 3 tag pack.

The command is deliberately conservative and is a dry run unless ``--apply``
is present.  Applying to the plugin's live ``tags_cache.db`` additionally
requires ``--allow-live-db``.  Apply mode takes a verified online SQLite backup
before the first database change, then performs all changes and verification in
one transaction.

Translation CSV
---------------

Required columns are ``tag``, ``category`` and ``translation_cn``.  The Phase 3
review format also carries ``post_count,evidence_url,evidence_kind,confidence,``
``review_note,expected_translation_cn``; these audit columns are optional to keep the importer useful
for small, hand-written repair packs.  When supplied, ``post_count`` must still
match the target database so a frozen review cannot be applied after data
drift.  Translations normally only fill NULL/blank values.  A non-blank
``expected_translation_cn`` enables a narrowly guarded correction: the current
database value must match it byte-for-byte.  Any other existing, different
non-blank value is a hard conflict, never an unconditional overwrite.

Alias operation CSV
-------------------

Required columns are ``action``, ``alias`` and ``canonical_tag``.  ``action``
is ``upsert`` or ``delete``.  Optional audit columns are ``source_url,``
``source_record_id,verified_at_utc,review_note``.  A delete uses
``canonical_tag`` as a compare-and-delete guard.  Every canonical introduced
by this pack must exist and must be a one-hop, non-alias target.  Historical
chains/cycles are reported and may remain, but the pack may not increase them.

An upsert may also set ``clear_identity_translation=true`` together with an
``expected_identity_translation``.  This is a narrowly guarded cleanup for an
obsolete identity row such as ``pokemon_sm``: the alias must itself still be a
``hot_tags`` row and its current translation must exactly equal the expected
value.  No approximate or unconditional clearing is possible.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE_DB = (
    PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"
).resolve()

TOOL_NAME = "apply_phase3_reviewed_tag_pack"
TOOL_VERSION = 1
ARTIST_CATEGORY = 1
ALLOWED_TRANSLATION_CATEGORIES = frozenset((0, 3, 4, 5))
TRANSLATION_REQUIRED_COLUMNS = frozenset(("tag", "category", "translation_cn"))
ALIAS_REQUIRED_COLUMNS = frozenset(("action", "alias", "canonical_tag"))
MAX_CSV_BYTES = 32 * 1024 * 1024
MAX_TAG_BYTES = 512
MAX_TRANSLATION_BYTES = 2048
MAX_METADATA_BYTES = 8192
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


class Phase3PackError(RuntimeError):
    """Base exception for stable CLI error handling."""

    code = "phase3_pack_error"


class PackValidationError(Phase3PackError):
    code = "pack_validation_error"


class TargetDatabaseError(Phase3PackError):
    code = "target_database_error"


@dataclass(frozen=True)
class TranslationEntry:
    tag: str
    category: int
    post_count: Optional[int]
    translation_cn: str
    expected_translation_cn: str
    evidence_url: str
    evidence_kind: str
    confidence: str
    review_note: str
    row_number: int


@dataclass(frozen=True)
class AliasOperation:
    action: str
    alias: str
    canonical_tag: str
    source_url: str
    source_record_id: str
    verified_at_utc: str
    review_note: str
    clear_identity_translation: bool
    expected_identity_translation: str
    row_number: int


@dataclass(frozen=True)
class ReviewedPack:
    translations: Tuple[TranslationEntry, ...]
    alias_operations: Tuple[AliasOperation, ...]
    translation_csv: Optional[Path]
    alias_csv: Optional[Path]
    translation_sha256: Optional[str]
    alias_sha256: Optional[str]
    pack_sha256: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _clean_text(value: object, field: str, *, maximum: int) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    if _CONTROL_RE.search(text):
        raise PackValidationError("{} contains control characters".format(field))
    if len(text.encode("utf-8")) > maximum:
        raise PackValidationError("{} exceeds the byte limit".format(field))
    return text


def _clean_tag(value: object, field: str) -> str:
    text = _clean_text(value, field, maximum=MAX_TAG_BYTES)
    if not text:
        raise PackValidationError("{} is required".format(field))
    if any(character.isspace() for character in text):
        raise PackValidationError("{} may not contain whitespace".format(field))
    return text


def _clean_translation(value: object, field: str) -> str:
    text = _clean_text(value, field, maximum=MAX_TRANSLATION_BYTES)
    if not text:
        raise PackValidationError("{} is required".format(field))
    if not _HAN_RE.search(text):
        raise PackValidationError(
            "{} must contain at least one Chinese character".format(field)
        )
    return text


def _clean_optional_url(value: object, field: str) -> str:
    text = _clean_text(value, field, maximum=MAX_METADATA_BYTES)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme.casefold() not in ("http", "https") or not parsed.netloc:
        raise PackValidationError("{} must be an absolute HTTP(S) URL".format(field))
    return text


def _parse_bool(value: object, field: str) -> bool:
    text = str(value or "").strip().casefold()
    if text in ("", "0", "false", "no", "n"):
        return False
    if text in ("1", "true", "yes", "y"):
        return True
    raise PackValidationError("{} must be true or false".format(field))


def _read_csv_bytes(path: Path) -> bytes:
    """Read one immutable, size-bounded snapshot for parsing and hashing."""
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise PackValidationError("CSV does not exist or is not a file: {}".format(resolved))
    try:
        with resolved.open("rb") as handle:
            data = handle.read(MAX_CSV_BYTES + 1)
    except OSError as exc:
        raise PackValidationError("could not read CSV: {}".format(resolved)) from exc
    if not data or len(data) > MAX_CSV_BYTES:
        raise PackValidationError("CSV size is outside the permitted range: {}".format(resolved))
    return data


def _read_csv(
    path: Path, immutable_bytes: bytes
) -> Tuple[List[Dict[str, str]], Tuple[str, ...]]:
    resolved = Path(path).resolve()
    try:
        decoded = immutable_bytes.decode("utf-8-sig")
        with io.StringIO(decoded, newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise PackValidationError("CSV has no header: {}".format(resolved))
            normalized = tuple(str(name or "").strip() for name in reader.fieldnames)
            if any(not name for name in normalized) or len(set(normalized)) != len(normalized):
                raise PackValidationError("CSV contains blank or duplicate column names")
            reader.fieldnames = list(normalized)
            rows: List[Dict[str, str]] = []
            for row in reader:
                if None in row:
                    raise PackValidationError(
                        "CSV row {} has more fields than the header".format(reader.line_num)
                    )
                normalized_row = {key: str(value or "") for key, value in row.items()}
                if not any(value.strip() for value in normalized_row.values()):
                    continue
                normalized_row["__row_number__"] = str(reader.line_num)
                rows.append(normalized_row)
    except UnicodeDecodeError as exc:
        raise PackValidationError("CSV must be UTF-8: {}".format(resolved)) from exc
    return rows, normalized


def _parse_translation_csv(
    path: Path, immutable_bytes: bytes
) -> Tuple[TranslationEntry, ...]:
    rows, columns = _read_csv(path, immutable_bytes)
    missing = sorted(TRANSLATION_REQUIRED_COLUMNS - set(columns))
    if missing:
        raise PackValidationError(
            "translation CSV is missing required columns: {}".format(", ".join(missing))
        )
    entries: Dict[str, TranslationEntry] = {}
    for raw in rows:
        row_number = int(raw["__row_number__"])
        prefix = "translation row {}".format(row_number)
        tag = _clean_tag(raw.get("tag"), prefix + " tag")
        try:
            category = int(str(raw.get("category", "")).strip())
        except ValueError as exc:
            raise PackValidationError(prefix + " category must be an integer") from exc
        if category == ARTIST_CATEGORY:
            raise PackValidationError(prefix + " targets artist category 1, which is forbidden")
        if category not in ALLOWED_TRANSLATION_CATEGORIES:
            raise PackValidationError(prefix + " uses an unsupported category")
        post_count_text = str(raw.get("post_count", "") or "").strip()
        post_count: Optional[int] = None
        if post_count_text:
            try:
                post_count = int(post_count_text)
            except ValueError as exc:
                raise PackValidationError(prefix + " post_count must be an integer") from exc
            if post_count < 0:
                raise PackValidationError(prefix + " post_count may not be negative")
        entry = TranslationEntry(
            tag=tag,
            category=category,
            post_count=post_count,
            translation_cn=_clean_translation(
                raw.get("translation_cn"), prefix + " translation_cn"
            ),
            expected_translation_cn=_clean_text(
                raw.get("expected_translation_cn"),
                prefix + " expected_translation_cn",
                maximum=MAX_TRANSLATION_BYTES,
            ),
            evidence_url=_clean_optional_url(
                raw.get("evidence_url"), prefix + " evidence_url"
            ),
            evidence_kind=_clean_text(
                raw.get("evidence_kind"), prefix + " evidence_kind", maximum=MAX_METADATA_BYTES
            ),
            confidence=_clean_text(
                raw.get("confidence"), prefix + " confidence", maximum=MAX_METADATA_BYTES
            ),
            review_note=_clean_text(
                raw.get("review_note"), prefix + " review_note", maximum=MAX_METADATA_BYTES
            ),
            row_number=row_number,
        )
        key = tag.casefold()
        previous = entries.get(key)
        if previous is not None:
            previous_semantics = (
                previous.tag,
                previous.category,
                previous.post_count,
                previous.translation_cn,
                previous.expected_translation_cn,
                previous.evidence_url,
                previous.evidence_kind,
                previous.confidence,
                previous.review_note,
            )
            entry_semantics = (
                entry.tag,
                entry.category,
                entry.post_count,
                entry.translation_cn,
                entry.expected_translation_cn,
                entry.evidence_url,
                entry.evidence_kind,
                entry.confidence,
                entry.review_note,
            )
            if previous_semantics != entry_semantics:
                raise PackValidationError(
                    "conflicting duplicate translation rows for tag {}".format(tag)
                )
            continue
        entries[key] = entry
    return tuple(sorted(entries.values(), key=lambda item: item.tag.casefold()))


def _parse_alias_csv(path: Path, immutable_bytes: bytes) -> Tuple[AliasOperation, ...]:
    rows, columns = _read_csv(path, immutable_bytes)
    missing = sorted(ALIAS_REQUIRED_COLUMNS - set(columns))
    if missing:
        raise PackValidationError(
            "alias CSV is missing required columns: {}".format(", ".join(missing))
        )
    operations: Dict[str, AliasOperation] = {}
    for raw in rows:
        row_number = int(raw["__row_number__"])
        prefix = "alias row {}".format(row_number)
        action = _clean_text(raw.get("action"), prefix + " action", maximum=32).casefold()
        if action not in ("upsert", "delete"):
            raise PackValidationError(prefix + " action must be upsert or delete")
        alias = _clean_tag(raw.get("alias"), prefix + " alias")
        canonical_tag = _clean_tag(raw.get("canonical_tag"), prefix + " canonical_tag")
        clear_identity = _parse_bool(
            raw.get("clear_identity_translation"),
            prefix + " clear_identity_translation",
        )
        expected = _clean_text(
            raw.get("expected_identity_translation"),
            prefix + " expected_identity_translation",
            maximum=MAX_TRANSLATION_BYTES,
        )
        if action != "upsert" and (clear_identity or expected):
            raise PackValidationError(
                prefix + " identity translation cleanup is only valid for upsert"
            )
        if clear_identity and not expected:
            raise PackValidationError(
                prefix + " clear_identity_translation requires expected_identity_translation"
            )
        if expected and not clear_identity:
            raise PackValidationError(
                prefix + " expected_identity_translation requires clear_identity_translation=true"
            )
        operation = AliasOperation(
            action=action,
            alias=alias,
            canonical_tag=canonical_tag,
            source_url=_clean_optional_url(raw.get("source_url"), prefix + " source_url"),
            source_record_id=_clean_text(
                raw.get("source_record_id"), prefix + " source_record_id", maximum=MAX_METADATA_BYTES
            ),
            verified_at_utc=_clean_text(
                raw.get("verified_at_utc"), prefix + " verified_at_utc", maximum=256
            ),
            review_note=_clean_text(
                raw.get("review_note"), prefix + " review_note", maximum=MAX_METADATA_BYTES
            ),
            clear_identity_translation=clear_identity,
            expected_identity_translation=expected,
            row_number=row_number,
        )
        key = alias.casefold()
        previous = operations.get(key)
        if previous is not None:
            if previous != operation:
                raise PackValidationError(
                    "conflicting duplicate alias operations for {}".format(alias)
                )
            continue
        operations[key] = operation
    return tuple(sorted(operations.values(), key=lambda item: item.alias.casefold()))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_reviewed_pack(
    translation_csv: Optional[Path] = None,
    alias_csv: Optional[Path] = None,
) -> ReviewedPack:
    """Load, validate and fingerprint one or both reviewed CSV files."""
    translation_path = Path(translation_csv).resolve() if translation_csv else None
    alias_path = Path(alias_csv).resolve() if alias_csv else None
    if translation_path is None and alias_path is None:
        raise PackValidationError("at least one translation or alias CSV is required")
    if translation_path is not None and alias_path is not None and translation_path == alias_path:
        raise PackValidationError("translation and alias CSV paths must be different")

    # Each component is read exactly once.  Parsing and every SHA256 below use
    # this same immutable snapshot, so a file replacement cannot make the
    # reviewed rows diverge from the reported/confirmed pack hash.
    translation_bytes = _read_csv_bytes(translation_path) if translation_path else b""
    alias_bytes = _read_csv_bytes(alias_path) if alias_path else b""
    translations = (
        _parse_translation_csv(translation_path, translation_bytes)
        if translation_path
        else ()
    )
    aliases = _parse_alias_csv(alias_path, alias_bytes) if alias_path else ()
    digest = hashlib.sha256()
    for label, present, data in (
        (b"translations", translation_path is not None, translation_bytes),
        (b"aliases", alias_path is not None, alias_bytes),
    ):
        digest.update(label)
        digest.update(b"\x01" if present else b"\x00")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return ReviewedPack(
        translations=tuple(translations),
        alias_operations=tuple(aliases),
        translation_csv=translation_path,
        alias_csv=alias_path,
        translation_sha256=_sha256_bytes(translation_bytes) if translation_path else None,
        alias_sha256=_sha256_bytes(alias_bytes) if alias_path else None,
        pack_sha256=digest.hexdigest(),
    )


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    ).fetchone() is not None


def _columns(connection: sqlite3.Connection, table: str) -> frozenset:
    return frozenset(str(row[1]) for row in connection.execute("PRAGMA table_info({})".format(table)))


def _integrity_result(connection: sqlite3.Connection) -> str:
    return "\n".join(str(row[0]) for row in connection.execute("PRAGMA integrity_check"))


def _quick_check_result(connection: sqlite3.Connection) -> str:
    return "\n".join(str(row[0]) for row in connection.execute("PRAGMA quick_check"))


def _validate_database_schema(connection: sqlite3.Connection) -> None:
    hot_required = {"tag", "category", "post_count", "translation_cn"}
    missing = sorted(hot_required - set(_columns(connection, "hot_tags")))
    if missing:
        raise TargetDatabaseError("hot_tags is missing required columns: {}".format(", ".join(missing)))
    fts_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='hot_tags_fts'"
    ).fetchone()
    fts_sql = str(fts_row[0] or "") if fts_row else ""
    if "VIRTUAL TABLE" not in fts_sql.upper() or "FTS5" not in fts_sql.upper():
        raise TargetDatabaseError("hot_tags_fts is missing or is not an FTS5 table")
    if not _table_exists(connection, "hot_tags_fts_docsize"):
        raise TargetDatabaseError("hot_tags_fts docsize table is required for reliable verification")
    if _table_exists(connection, "tag_aliases"):
        required_alias = {
            "alias", "canonical_tag", "relation_type", "source_name", "source_url",
            "declared_license", "source_revision", "source_sha256", "imported_at",
        }
        missing_alias = sorted(required_alias - set(_columns(connection, "tag_aliases")))
        if missing_alias:
            raise TargetDatabaseError(
                "tag_aliases is missing required columns: {}".format(", ".join(missing_alias))
            )
    if _table_exists(connection, "tag_translation_history"):
        required_history = {
            "tag", "category", "old_translation_cn", "new_translation_cn",
            "change_type", "reason", "run_id", "changed_at_utc",
        }
        missing_history = sorted(
            required_history - set(_columns(connection, "tag_translation_history"))
        )
        if missing_history:
            raise TargetDatabaseError(
                "tag_translation_history is missing required columns: {}".format(", ".join(missing_history))
            )


def _database_metrics(connection: sqlite3.Connection) -> Dict[str, object]:
    total = int(connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0])
    translated = int(
        connection.execute(
            "SELECT COUNT(*) FROM hot_tags WHERE NULLIF(TRIM(translation_cn),'') IS NOT NULL"
        ).fetchone()[0]
    )
    artist_values = int(
        connection.execute(
            "SELECT COUNT(*) FROM hot_tags WHERE category=? AND translation_cn IS NOT NULL",
            (ARTIST_CATEGORY,),
        ).fetchone()[0]
    )
    aliases = int(connection.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]) if _table_exists(connection, "tag_aliases") else 0
    history = int(connection.execute("SELECT COUNT(*) FROM tag_translation_history").fetchone()[0]) if _table_exists(connection, "tag_translation_history") else 0
    fts_rows = int(connection.execute("SELECT COUNT(*) FROM hot_tags_fts_docsize").fetchone()[0])
    return {
        "total_tags": total,
        "translated_tags": translated,
        "artist_translation_values": artist_values,
        "alias_rows": aliases,
        "history_rows": history,
        "fts_rows": fts_rows,
        "fts_matches_hot_tags": fts_rows == total,
        "quick_check": _quick_check_result(connection),
        "integrity_check": _integrity_result(connection),
    }


def _load_hot_tags(connection: sqlite3.Connection) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    for row in connection.execute(
        "SELECT tag, category, post_count, translation_cn FROM hot_tags"
    ):
        key = str(row["tag"]).casefold()
        if key in result:
            raise TargetDatabaseError("hot_tags contains case-insensitive duplicate identities")
        result[key] = {
            "tag": str(row["tag"]),
            "category": int(row["category"]),
            "post_count": int(row["post_count"]),
            "translation_cn": row["translation_cn"],
        }
    return result


def _load_aliases(connection: sqlite3.Connection) -> Dict[str, Dict[str, object]]:
    if not _table_exists(connection, "tag_aliases"):
        return {}
    result: Dict[str, Dict[str, object]] = {}
    for row in connection.execute("SELECT * FROM tag_aliases"):
        key = str(row["alias"]).casefold()
        if key in result:
            raise TargetDatabaseError("tag_aliases contains case-insensitive duplicates")
        result[key] = dict(row)
    return result


def _alias_graph_metrics(
    aliases: Mapping[str, Mapping[str, object]]
) -> Dict[str, int]:
    """Return global legacy-hygiene metrics for a functional alias graph."""
    alias_keys = set(aliases)
    next_alias: Dict[str, Optional[str]] = {}
    for key, relation in aliases.items():
        target = str(relation.get("canonical_tag", "")).casefold()
        next_alias[key] = target if target in alias_keys else None
    chain_edges = sum(1 for target in next_alias.values() if target is not None)
    visited = set()
    cycle_components = 0
    cycle_nodes = 0
    for start in sorted(alias_keys):
        if start in visited:
            continue
        path: List[str] = []
        local_positions: Dict[str, int] = {}
        current: Optional[str] = start
        while current is not None and current not in visited:
            if current in local_positions:
                cycle_components += 1
                cycle_nodes += len(path) - local_positions[current]
                break
            local_positions[current] = len(path)
            path.append(current)
            current = next_alias.get(current)
        visited.update(path)
    return {
        "alias_rows": len(aliases),
        "chain_edges": chain_edges,
        "cycle_components": cycle_components,
        "cycle_nodes": cycle_nodes,
    }


def _is_nonblank(value: object) -> bool:
    return value is not None and bool(str(value).strip())


def _review_reason(entry: TranslationEntry, pack_sha256: str) -> str:
    return json.dumps(
        {
            "source": "phase3_human_review",
            "pack_sha256": pack_sha256,
            "expected_translation_cn": entry.expected_translation_cn,
            "evidence_url": entry.evidence_url,
            "evidence_kind": entry.evidence_kind,
            "confidence": entry.confidence,
            "review_note": entry.review_note,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _identity_clear_reason(operation: AliasOperation, pack_sha256: str) -> str:
    return json.dumps(
        {
            "source": "phase3_alias_direction_repair",
            "pack_sha256": pack_sha256,
            "canonical_tag": operation.canonical_tag,
            "source_url": operation.source_url,
            "source_record_id": operation.source_record_id,
            "verified_at_utc": operation.verified_at_utc,
            "review_note": operation.review_note,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _analyze(connection: sqlite3.Connection, pack: ReviewedPack) -> Dict[str, object]:
    _validate_database_schema(connection)
    metrics = _database_metrics(connection)
    if metrics["integrity_check"] != "ok":
        raise TargetDatabaseError(
            "target integrity_check failed: {}".format(metrics["integrity_check"])
        )
    if metrics["quick_check"] != "ok":
        raise TargetDatabaseError(
            "target quick_check failed: {}".format(metrics["quick_check"])
        )
    hot_tags = _load_hot_tags(connection)
    aliases_before = _load_aliases(connection)
    metrics["alias_graph"] = _alias_graph_metrics(aliases_before)
    translation_fills: List[Dict[str, object]] = []
    translation_corrections: List[Dict[str, object]] = []
    translation_noops = 0

    for entry in pack.translations:
        target = hot_tags.get(entry.tag.casefold())
        if target is None or target["tag"] != entry.tag:
            raise PackValidationError("translation target does not exist exactly: {}".format(entry.tag))
        if int(target["category"]) == ARTIST_CATEGORY:
            raise PackValidationError("artist translation is forbidden: {}".format(entry.tag))
        if int(target["category"]) != entry.category:
            raise PackValidationError(
                "category conflict for {}: pack {}, database {}".format(
                    entry.tag, entry.category, target["category"]
                )
            )
        if entry.post_count is not None and int(target["post_count"]) != entry.post_count:
            raise PackValidationError(
                "post_count conflict for {}: pack {}, database {}".format(
                    entry.tag, entry.post_count, target["post_count"]
                )
            )
        current = target["translation_cn"]
        if _is_nonblank(current):
            if str(current) == entry.translation_cn:
                translation_noops += 1
                continue
            if not entry.expected_translation_cn:
                raise PackValidationError(
                    "refusing to overwrite existing translation for {}".format(entry.tag)
                )
            if str(current) != entry.expected_translation_cn:
                raise PackValidationError(
                    "expected translation conflict for {}: database value does not match pack guard".format(
                        entry.tag
                    )
                )
            translation_corrections.append(
                {
                    "tag": entry.tag,
                    "category": entry.category,
                    "old_translation_cn": current,
                    "new_translation_cn": entry.translation_cn,
                    "reason": _review_reason(entry, pack.pack_sha256),
                }
            )
            continue
        if entry.expected_translation_cn:
            raise PackValidationError(
                "guarded translation correction target is blank: {}".format(entry.tag)
            )
        translation_fills.append(
            {
                "tag": entry.tag,
                "category": entry.category,
                "old_translation_cn": current,
                "new_translation_cn": entry.translation_cn,
                "reason": _review_reason(entry, pack.pack_sha256),
            }
        )

    aliases_final = {key: dict(value) for key, value in aliases_before.items()}
    delete_plans: List[Dict[str, object]] = []
    upsert_plans: List[Dict[str, object]] = []
    identity_clears: List[Dict[str, object]] = []

    # Deletions are projected first so one pack can safely invert an old alias
    # direction (delete canonical->short, then upsert short->canonical).
    for operation in pack.alias_operations:
        if operation.action != "delete":
            continue
        key = operation.alias.casefold()
        existing = aliases_final.get(key)
        if existing is None:
            raise PackValidationError("alias delete target does not exist: {}".format(operation.alias))
        if str(existing["alias"]) != operation.alias:
            raise PackValidationError("alias delete target differs by case: {}".format(operation.alias))
        if str(existing["canonical_tag"]) != operation.canonical_tag:
            raise PackValidationError(
                "alias delete conflict for {}: expected {}, database {}".format(
                    operation.alias, operation.canonical_tag, existing["canonical_tag"]
                )
            )
        identity = hot_tags.get(operation.alias.casefold())
        canonical_identity = hot_tags.get(operation.canonical_tag.casefold())
        if canonical_identity is None or canonical_identity["tag"] != operation.canonical_tag:
            raise PackValidationError(
                "alias delete canonical tag does not exist exactly: {}".format(
                    operation.canonical_tag
                )
            )
        if identity is not None and int(identity["category"]) == ARTIST_CATEGORY:
            raise PackValidationError("artist alias identity is forbidden: {}".format(operation.alias))
        if canonical_identity is not None and int(canonical_identity["category"]) == ARTIST_CATEGORY:
            raise PackValidationError("artist alias canonical is forbidden: {}".format(operation.canonical_tag))
        delete_plans.append({"alias": operation.alias, "canonical_tag": operation.canonical_tag})
        del aliases_final[key]

    for operation in pack.alias_operations:
        if operation.action != "upsert":
            continue
        alias_key = operation.alias.casefold()
        canonical_key = operation.canonical_tag.casefold()
        if alias_key == canonical_key:
            raise PackValidationError("alias may not point to itself: {}".format(operation.alias))
        canonical = hot_tags.get(canonical_key)
        if canonical is None or canonical["tag"] != operation.canonical_tag:
            raise PackValidationError(
                "alias canonical tag does not exist exactly: {}".format(operation.canonical_tag)
            )
        if int(canonical["category"]) == ARTIST_CATEGORY:
            raise PackValidationError("artist alias canonical is forbidden: {}".format(operation.canonical_tag))
        alias_identity = hot_tags.get(alias_key)
        if alias_identity is not None and int(alias_identity["category"]) == ARTIST_CATEGORY:
            raise PackValidationError("artist alias identity is forbidden: {}".format(operation.alias))
        if operation.clear_identity_translation:
            if alias_identity is None or alias_identity["tag"] != operation.alias:
                raise PackValidationError(
                    "identity translation cleanup requires an exact hot_tags identity: {}".format(operation.alias)
                )
            current = alias_identity["translation_cn"]
            if current != operation.expected_identity_translation:
                raise PackValidationError(
                    "identity translation conflict for {}: expected value does not match database".format(operation.alias)
                )
            if not _is_nonblank(current):
                raise PackValidationError("identity translation is already blank: {}".format(operation.alias))
            identity_clears.append(
                {
                    "tag": operation.alias,
                    "category": int(alias_identity["category"]),
                    "old_translation_cn": current,
                    "new_translation_cn": None,
                    "reason": _identity_clear_reason(operation, pack.pack_sha256),
                }
            )
        existing = aliases_final.get(alias_key)
        upsert_plans.append(
            {
                "operation": operation,
                "kind": "insert" if existing is None else "update",
            }
        )
        aliases_final[alias_key] = {
            "alias": operation.alias,
            "canonical_tag": operation.canonical_tag,
        }

    clear_keys = {str(row["tag"]).casefold() for row in identity_clears}
    write_keys = {
        str(row["tag"]).casefold()
        for row in translation_fills + translation_corrections
    }
    if clear_keys & write_keys:
        raise PackValidationError("one pack may not fill and clear the same translation identity")

    alias_keys = set(aliases_final)
    # Old snapshots contain known chains and cycles.  They are not a reason to
    # block an unrelated reviewed pack.  New/updated aliases, however, must be
    # strict one-hop relations in the final graph.
    for row in upsert_plans:
        operation = row["operation"]
        if operation.canonical_tag.casefold() in alias_keys:
            raise PackValidationError(
                "reviewed upsert must point directly to a non-alias canonical: {} -> {}".format(
                    operation.alias, operation.canonical_tag
                )
            )
    graph_before = _alias_graph_metrics(aliases_before)
    graph_after = _alias_graph_metrics(aliases_final)
    for metric in ("chain_edges", "cycle_components", "cycle_nodes"):
        if graph_after[metric] > graph_before[metric]:
            raise PackValidationError(
                "reviewed pack would increase global alias {} from {} to {}".format(
                    metric, graph_before[metric], graph_after[metric]
                )
            )
    for entry in pack.translations:
        if entry.tag.casefold() in alias_keys:
            raise PackValidationError(
                "translation target is an alias rather than a canonical tag: {}".format(entry.tag)
            )

    projected = dict(metrics)
    projected["translated_tags"] = int(metrics["translated_tags"]) + len(translation_fills) - len(identity_clears)
    projected["alias_rows"] = int(metrics["alias_rows"]) + sum(
        1 for row in upsert_plans if row["kind"] == "insert"
    ) - len(delete_plans)
    projected["history_rows"] = (
        int(metrics["history_rows"])
        + len(translation_fills)
        + len(translation_corrections)
        + len(identity_clears)
    )
    projected["fts_rows"] = int(metrics["total_tags"])
    projected["fts_matches_hot_tags"] = True
    projected["alias_graph"] = graph_after
    projected["quick_check"] = "not_run_dry_run_projection"
    projected["integrity_check"] = "not_run_dry_run_projection"
    plan = {
        "before": metrics,
        "projected_after": projected,
        "translation_fills": translation_fills,
        "translation_corrections": translation_corrections,
        "translation_noops": translation_noops,
        "alias_deletes": delete_plans,
        "alias_upserts": upsert_plans,
        "identity_translation_clears": identity_clears,
    }
    fingerprint_payload = {
        "before": metrics,
        "translation_fills": translation_fills,
        "translation_corrections": translation_corrections,
        "translation_noops": translation_noops,
        "alias_deletes": delete_plans,
        "alias_upserts": [
            {
                "kind": row["kind"],
                "operation": row["operation"].__dict__,
            }
            for row in upsert_plans
        ],
        "identity_translation_clears": identity_clears,
    }
    plan["fingerprint"] = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return plan


def _create_history_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tag_translation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT NOT NULL,
            category INTEGER NOT NULL,
            old_translation_cn TEXT,
            new_translation_cn TEXT,
            change_type TEXT NOT NULL,
            reason TEXT NOT NULL,
            run_id TEXT NOT NULL,
            changed_at_utc TEXT NOT NULL,
            UNIQUE(run_id, tag, change_type)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tag_translation_history_tag ON tag_translation_history(tag)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tag_translation_history_run ON tag_translation_history(run_id)"
    )


def _create_alias_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tag_aliases (
            alias TEXT PRIMARY KEY COLLATE NOCASE,
            canonical_tag TEXT NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'official_alias',
            source_name TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            declared_license TEXT NOT NULL DEFAULT '',
            source_revision TEXT NOT NULL DEFAULT '',
            source_sha256 TEXT NOT NULL DEFAULT '',
            imported_at INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tag_aliases_canonical ON tag_aliases(canonical_tag COLLATE NOCASE)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tag_aliases_source_revision ON tag_aliases(source_name, source_revision)"
    )


def _unique_backup_path(
    db_path: Path,
    backup_dir: Optional[Path],
    pack_sha256: str,
    protected_paths: Sequence[Path],
) -> Path:
    directory = (Path(backup_dir) if backup_dir else db_path.parent).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = "{}.pre_phase3_{}_{}".format(db_path.name, timestamp, pack_sha256[:12])
    protected = {Path(path).resolve() for path in protected_paths}
    for suffix in range(10000):
        name = stem + ("" if suffix == 0 else "_{}".format(suffix)) + ".db"
        candidate = (directory / name).resolve()
        if candidate in protected:
            continue
        if not candidate.exists():
            return candidate
    raise TargetDatabaseError("could not reserve a unique backup path")


def _create_verified_backup(
    db_path: Path, backup_path: Path, expected_total_tags: int
) -> Dict[str, object]:
    source = _readonly_connection(db_path)
    try:
        destination = sqlite3.connect(str(backup_path), timeout=30.0)
        try:
            source.backup(destination)
            destination.commit()
            integrity = _integrity_result(destination)
            quick_check = _quick_check_result(destination)
            total = int(destination.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0])
            if integrity != "ok":
                raise TargetDatabaseError("backup integrity_check failed: {}".format(integrity))
            if quick_check != "ok":
                raise TargetDatabaseError("backup quick_check failed: {}".format(quick_check))
            if total != expected_total_tags:
                raise TargetDatabaseError("backup hot_tags row count does not match the source")
        finally:
            destination.close()
    except Exception:
        try:
            backup_path.unlink()
        except OSError:
            pass
        raise
    finally:
        source.close()
    return {
        "path": str(backup_path),
        "sha256": _sha256_file(backup_path),
        "integrity_check": "ok",
        "quick_check": "ok",
        "total_tags": expected_total_tags,
        "method": "sqlite_backup_api",
    }


def _apply_plan(
    connection: sqlite3.Connection,
    plan: Mapping[str, object],
    pack: ReviewedPack,
    run_id: str,
    changed_at_utc: str,
) -> Tuple[Dict[str, int], Dict[str, object]]:
    _create_history_schema(connection)
    _create_alias_schema(connection)
    epoch = int(datetime.now(timezone.utc).timestamp())
    hot_columns = _columns(connection, "hot_tags")
    fills = list(plan["translation_fills"])  # type: ignore[arg-type]
    corrections = list(plan["translation_corrections"])  # type: ignore[arg-type]
    clears = list(plan["identity_translation_clears"])  # type: ignore[arg-type]
    deletes = list(plan["alias_deletes"])  # type: ignore[arg-type]
    upserts = list(plan["alias_upserts"])  # type: ignore[arg-type]

    for row in fills:
        cursor = connection.execute(
            """
            INSERT INTO tag_translation_history(
                tag, category, old_translation_cn, new_translation_cn,
                change_type, reason, run_id, changed_at_utc
            ) VALUES (?, ?, ?, ?, 'phase3_translation_fill', ?, ?, ?)
            """,
            (
                row["tag"], row["category"], row["old_translation_cn"],
                row["new_translation_cn"], row["reason"], run_id, changed_at_utc,
            ),
        )
        if "last_updated" in hot_columns:
            cursor = connection.execute(
                """
                UPDATE hot_tags SET translation_cn=?, last_updated=?
                WHERE tag=? AND category=? AND NULLIF(TRIM(translation_cn),'') IS NULL
                """,
                (row["new_translation_cn"], epoch, row["tag"], row["category"]),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE hot_tags SET translation_cn=?
                WHERE tag=? AND category=? AND NULLIF(TRIM(translation_cn),'') IS NULL
                """,
                (row["new_translation_cn"], row["tag"], row["category"]),
            )
        if int(cursor.rowcount) != 1:
            raise TargetDatabaseError("guarded translation fill failed for {}".format(row["tag"]))

    for row in corrections:
        connection.execute(
            """
            INSERT INTO tag_translation_history(
                tag, category, old_translation_cn, new_translation_cn,
                change_type, reason, run_id, changed_at_utc
            ) VALUES (?, ?, ?, ?, 'phase3_translation_correction', ?, ?, ?)
            """,
            (
                row["tag"], row["category"], row["old_translation_cn"],
                row["new_translation_cn"], row["reason"], run_id, changed_at_utc,
            ),
        )
        if "last_updated" in hot_columns:
            cursor = connection.execute(
                """
                UPDATE hot_tags SET translation_cn=?, last_updated=?
                WHERE tag=? AND category=? AND translation_cn=?
                """,
                (
                    row["new_translation_cn"], epoch, row["tag"], row["category"],
                    row["old_translation_cn"],
                ),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE hot_tags SET translation_cn=?
                WHERE tag=? AND category=? AND translation_cn=?
                """,
                (
                    row["new_translation_cn"], row["tag"], row["category"],
                    row["old_translation_cn"],
                ),
            )
        if int(cursor.rowcount) != 1:
            raise TargetDatabaseError(
                "guarded translation correction failed for {}".format(row["tag"])
            )

    for row in clears:
        connection.execute(
            """
            INSERT INTO tag_translation_history(
                tag, category, old_translation_cn, new_translation_cn,
                change_type, reason, run_id, changed_at_utc
            ) VALUES (?, ?, ?, NULL, 'alias_identity_translation_cleared', ?, ?, ?)
            """,
            (
                row["tag"], row["category"], row["old_translation_cn"],
                row["reason"], run_id, changed_at_utc,
            ),
        )
        if "last_updated" in hot_columns:
            cursor = connection.execute(
                "UPDATE hot_tags SET translation_cn=NULL, last_updated=? WHERE tag=? AND translation_cn=?",
                (epoch, row["tag"], row["old_translation_cn"]),
            )
        else:
            cursor = connection.execute(
                "UPDATE hot_tags SET translation_cn=NULL WHERE tag=? AND translation_cn=?",
                (row["tag"], row["old_translation_cn"]),
            )
        if int(cursor.rowcount) != 1:
            raise TargetDatabaseError(
                "guarded identity translation clear failed for {}".format(row["tag"])
            )

    for row in deletes:
        cursor = connection.execute(
            "DELETE FROM tag_aliases WHERE alias=? AND canonical_tag=?",
            (row["alias"], row["canonical_tag"]),
        )
        if int(cursor.rowcount) != 1:
            raise TargetDatabaseError("guarded alias delete failed for {}".format(row["alias"]))

    for row in upserts:
        operation = row["operation"]
        revision = operation.source_record_id or "phase3:{}".format(pack.pack_sha256[:16])
        cursor = connection.execute(
            """
            INSERT INTO tag_aliases(
                alias, canonical_tag, relation_type, source_name, source_url,
                declared_license, source_revision, source_sha256, imported_at
            ) VALUES (?, ?, 'official_alias', 'phase3_reviewed_tag_pack', ?, 'MIT', ?, ?, ?)
            ON CONFLICT(alias) DO UPDATE SET
                canonical_tag=excluded.canonical_tag,
                relation_type=excluded.relation_type,
                source_name=excluded.source_name,
                source_url=excluded.source_url,
                declared_license=excluded.declared_license,
                source_revision=excluded.source_revision,
                source_sha256=excluded.source_sha256,
                imported_at=excluded.imported_at
            """,
            (
                operation.alias, operation.canonical_tag, operation.source_url,
                revision, pack.pack_sha256, epoch,
            ),
        )
        if int(cursor.rowcount) != 1:
            raise TargetDatabaseError(
                "alias upsert did not affect exactly one row: {}".format(operation.alias)
            )

    for row in fills + corrections:
        actual = connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag=?", (row["tag"],)
        ).fetchone()
        if actual is None or actual[0] != row["new_translation_cn"]:
            raise TargetDatabaseError(
                "translation verification failed for {}".format(row["tag"])
            )
    for row in clears:
        actual = connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag=?", (row["tag"],)
        ).fetchone()
        if actual is None or actual[0] is not None:
            raise TargetDatabaseError(
                "identity translation clear verification failed for {}".format(row["tag"])
            )
    for row in upserts:
        operation = row["operation"]
        actual = connection.execute(
            "SELECT canonical_tag FROM tag_aliases WHERE alias=?", (operation.alias,)
        ).fetchone()
        if actual is None or actual[0] != operation.canonical_tag:
            raise TargetDatabaseError(
                "alias direction verification failed for {}".format(operation.alias)
            )

    connection.execute("INSERT INTO hot_tags_fts(hot_tags_fts) VALUES('rebuild')")
    after = _database_metrics(connection)
    after["alias_graph"] = _alias_graph_metrics(_load_aliases(connection))
    before = plan["before"]
    expected = plan["projected_after"]
    if int(after["total_tags"]) != int(before["total_tags"]):
        raise TargetDatabaseError("hot_tags row count changed during migration")
    if int(after["translated_tags"]) != int(expected["translated_tags"]):
        raise TargetDatabaseError("translated tag row count invariant failed")
    if int(after["alias_rows"]) != int(expected["alias_rows"]):
        raise TargetDatabaseError("alias row count invariant failed")
    if after["alias_graph"] != expected["alias_graph"]:
        raise TargetDatabaseError("alias graph metrics do not match the reviewed projection")
    if int(after["history_rows"]) != int(expected["history_rows"]):
        raise TargetDatabaseError("translation history row count invariant failed")
    if int(after["artist_translation_values"]) != int(before["artist_translation_values"]):
        raise TargetDatabaseError("artist translations changed during migration")
    if not after["fts_matches_hot_tags"]:
        raise TargetDatabaseError("FTS row count does not match hot_tags after rebuild")
    if after["integrity_check"] != "ok":
        raise TargetDatabaseError(
            "post-migration integrity_check failed: {}".format(after["integrity_check"])
        )
    if after["quick_check"] != "ok":
        raise TargetDatabaseError(
            "post-migration quick_check failed: {}".format(after["quick_check"])
        )
    changes = {
        "translations_filled": len(fills),
        "translations_corrected": len(corrections),
        "translation_noops": int(plan["translation_noops"]),
        "identity_translations_cleared": len(clears),
        "history_rows_inserted": len(fills) + len(corrections) + len(clears),
        "aliases_inserted": sum(1 for row in upserts if row["kind"] == "insert"),
        "aliases_updated": sum(1 for row in upserts if row["kind"] == "update"),
        "aliases_deleted": len(deletes),
        "fts_rows_rebuilt": int(after["fts_rows"]),
    }
    return changes, after


def _public_plan_counts(plan: Mapping[str, object]) -> Dict[str, int]:
    upserts = list(plan["alias_upserts"])  # type: ignore[arg-type]
    return {
        "translations_to_fill": len(plan["translation_fills"]),  # type: ignore[arg-type]
        "translations_to_correct": len(plan["translation_corrections"]),  # type: ignore[arg-type]
        "translation_noops": int(plan["translation_noops"]),
        "identity_translations_to_clear": len(plan["identity_translation_clears"]),  # type: ignore[arg-type]
        "history_rows_to_insert": (
            len(plan["translation_fills"])
            + len(plan["translation_corrections"])
            + len(plan["identity_translation_clears"])
        ),  # type: ignore[arg-type]
        "aliases_to_insert": sum(1 for row in upserts if row["kind"] == "insert"),
        "aliases_to_update": sum(1 for row in upserts if row["kind"] == "update"),
        "aliases_to_delete": len(plan["alias_deletes"]),  # type: ignore[arg-type]
        "fts_rows_to_rebuild": int(plan["before"]["total_tags"]),  # type: ignore[index]
    }


def apply_reviewed_tag_pack(
    db_path: Path,
    *,
    translation_csv: Optional[Path] = None,
    alias_csv: Optional[Path] = None,
    apply: bool = False,
    allow_live_db: bool = False,
    backup_dir: Optional[Path] = None,
    expected_pack_sha256: Optional[str] = None,
) -> Dict[str, object]:
    """Audit or apply a reviewed pack and return a JSON-serializable report."""
    database = Path(db_path).resolve()
    if not database.is_file():
        raise TargetDatabaseError("database does not exist or is not a file: {}".format(database))
    if apply and database == DEFAULT_LIVE_DB and not allow_live_db:
        raise TargetDatabaseError(
            "refusing to apply to the plugin live database without allow_live_db=True"
        )
    pack = load_reviewed_pack(translation_csv, alias_csv)
    if expected_pack_sha256 is not None:
        expected_hash = str(expected_pack_sha256).strip().casefold()
        if not _SHA256_RE.fullmatch(expected_hash):
            raise PackValidationError("expected_pack_sha256 must be 64 hex digits")
        if expected_hash != pack.pack_sha256:
            raise PackValidationError(
                "pack SHA256 mismatch: expected {}, got {}".format(expected_hash, pack.pack_sha256)
            )

    started = _utc_now()
    run_id = "phase3-{}".format(uuid.uuid4().hex)
    readonly = _readonly_connection(database)
    try:
        plan = _analyze(readonly, pack)
    finally:
        readonly.close()
    report: Dict[str, object] = {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "success": True,
        "mode": "apply" if apply else "dry-run",
        "applied": False,
        "database_committed": False,
        "db_path": str(database),
        "is_plugin_live_db": database == DEFAULT_LIVE_DB,
        "live_apply_guard": True,
        "run_id": run_id,
        "started_at_utc": started,
        "pack": {
            "sha256": pack.pack_sha256,
            "translation_csv": str(pack.translation_csv) if pack.translation_csv else None,
            "translation_csv_sha256": pack.translation_sha256,
            "translation_rows": len(pack.translations),
            "alias_csv": str(pack.alias_csv) if pack.alias_csv else None,
            "alias_csv_sha256": pack.alias_sha256,
            "alias_rows": len(pack.alias_operations),
        },
        "before": plan["before"],
        "planned_changes": _public_plan_counts(plan),
        "backup": None,
    }
    if not apply:
        report["changes"] = {
            "translations_filled": 0,
            "translations_corrected": 0,
            "translation_noops": int(plan["translation_noops"]),
            "identity_translations_cleared": 0,
            "history_rows_inserted": 0,
            "aliases_inserted": 0,
            "aliases_updated": 0,
            "aliases_deleted": 0,
            "fts_rows_rebuilt": 0,
        }
        report["after"] = plan["projected_after"]
        report["after_is_projection"] = True
        report["integrity"] = {
            "before": plan["before"]["integrity_check"],  # type: ignore[index]
            "backup": None,
            "after": None,
        }
        report["quick_check"] = {
            "before": plan["before"]["quick_check"],  # type: ignore[index]
            "backup": None,
            "after": None,
        }
        report["completed_at_utc"] = _utc_now()
        return report

    protected = [database]
    if pack.translation_csv:
        protected.append(pack.translation_csv)
    if pack.alias_csv:
        protected.append(pack.alias_csv)
    backup_path = _unique_backup_path(database, backup_dir, pack.pack_sha256, protected)
    connection = sqlite3.connect(str(database), timeout=30.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    backup: Optional[Dict[str, object]] = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            locked_plan = _analyze(connection, pack)
            if locked_plan["fingerprint"] != plan["fingerprint"]:
                raise TargetDatabaseError(
                    "database or migration plan changed before the write lock; refusing to apply"
                )
            backup = _create_verified_backup(
                database, backup_path, int(plan["before"]["total_tags"])  # type: ignore[index]
            )
            changes, after = _apply_plan(
                connection, locked_plan, pack, run_id, started
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()

    # All critical after-state checks ran inside the transaction.  Reuse that
    # verified snapshot after COMMIT so an auxiliary post-commit read cannot
    # turn a successful migration into an ambiguous failure status.
    report["backup"] = backup
    report["changes"] = changes
    report["after"] = after
    report["after_is_projection"] = False
    report["integrity"] = {
        "before": plan["before"]["integrity_check"],  # type: ignore[index]
        "backup": backup["integrity_check"] if backup else None,
        "after": after["integrity_check"],
    }
    report["quick_check"] = {
        "before": plan["before"]["quick_check"],  # type: ignore[index]
        "backup": backup["quick_check"] if backup else None,
        "after": after["quick_check"],
    }
    report["applied"] = True
    report["database_committed"] = True
    report["completed_at_utc"] = _utc_now()
    return report


# A descriptive alias makes the API easy to discover without weakening the
# CLI's explicit --apply guard.
migrate_reviewed_pack = apply_reviewed_tag_pack


def _preflight_report_target(
    path: Path, protected_paths: Sequence[Path]
) -> Path:
    """Validate report safety and exercise same-directory write/replace first."""
    destination = Path(path).resolve()
    protected = {Path(item).resolve() for item in protected_paths if item is not None}
    if destination in protected:
        raise PackValidationError(
            "report path must differ from the database and input CSV files"
        )
    if destination.exists() and not destination.is_file():
        raise PackValidationError("report target exists and is not a file: {}".format(destination))
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PackValidationError(
            "could not create report directory: {}".format(destination.parent)
        ) from exc
    first_probe = destination.with_name(
        ".{}.preflight-{}".format(destination.name, uuid.uuid4().hex)
    )
    second_probe = destination.with_name(
        ".{}.replace-{}".format(destination.name, uuid.uuid4().hex)
    )
    try:
        with first_probe.open("x", encoding="utf-8") as handle:
            handle.write("phase3-report-preflight\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(first_probe), str(second_probe))
    except OSError as exc:
        raise PackValidationError(
            "report target failed preflight write/replace: {}".format(destination)
        ) from exc
    finally:
        for probe in (first_probe, second_probe):
            try:
                probe.unlink()
            except OSError:
                pass
    return destination


def _write_json_report(path: Path, report: Mapping[str, object]) -> None:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp-" + uuid.uuid4().hex)
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_LIVE_DB,
        help="target SQLite database (default: plugin live tags_cache.db; dry-run only without flags)",
    )
    parser.add_argument(
        "--translation-csv", "--translations-csv", "--translations",
        dest="translation_csv", type=Path, help="reviewed translation CSV",
    )
    parser.add_argument(
        "--alias-csv", "--aliases-csv", "--aliases",
        dest="alias_csv", type=Path, help="reviewed alias operation CSV",
    )
    parser.add_argument(
        "--expected-pack-sha256",
        help="optional 64-hex confirmation of the exact combined CSV pack",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="create a verified backup and apply in one transaction (default: dry-run)",
    )
    parser.add_argument(
        "--allow-live-db", action="store_true",
        help="second confirmation required when --apply targets the plugin live database",
    )
    parser.add_argument(
        "--backup-dir", type=Path,
        help="backup directory used only with --apply (default: target database directory)",
    )
    parser.add_argument("--report", type=Path, help="also write the JSON report to this path")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    report: Optional[Dict[str, object]] = None
    try:
        report_target = None
        if arguments.report:
            report_target = _preflight_report_target(
                arguments.report,
                [
                    Path(arguments.db),
                    Path(arguments.translation_csv) if arguments.translation_csv else None,
                    Path(arguments.alias_csv) if arguments.alias_csv else None,
                ],
            )
        report = apply_reviewed_tag_pack(
            arguments.db,
            translation_csv=arguments.translation_csv,
            alias_csv=arguments.alias_csv,
            apply=bool(arguments.apply),
            allow_live_db=bool(arguments.allow_live_db),
            backup_dir=arguments.backup_dir,
            expected_pack_sha256=arguments.expected_pack_sha256,
        )
        if report_target:
            report["report_output"] = {
                "path": str(report_target),
                "written": True,
            }
            try:
                _write_json_report(report_target, report)
            except Exception as exc:
                report["report_output"] = {
                    "path": str(report_target),
                    "written": False,
                    "error": str(exc),
                }
                warning = (
                    "database migration state is final, but the requested JSON "
                    "report could not be written"
                )
                report.setdefault("warnings", []).append(warning)
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                auxiliary_error = {
                    "tool": TOOL_NAME,
                    "success": True,
                    "error_code": "report_write_failed_after_migration",
                    "error": str(exc),
                    "applied": bool(report.get("applied")),
                    "database_committed": bool(report.get("database_committed")),
                    "report_written": False,
                }
                print(
                    json.dumps(auxiliary_error, ensure_ascii=False, indent=2, sort_keys=True),
                    file=sys.stderr,
                )
                return 3
    except Exception as exc:
        error = {
            "tool": TOOL_NAME,
            "success": False,
            "applied": False,
            "database_committed": False,
            "error_code": getattr(exc, "code", "unexpected_error"),
            "error": str(exc),
        }
        print(json.dumps(error, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
