#!/usr/bin/env python3
"""Safely import a licensed Chinese tag-translation CSV into tags_cache.db.

The importer intentionally lives outside the runtime code path.  It stages and
validates the complete CSV first and defaults to a read-only dry run.  Applying
a pack requires an explicit ``--apply``; applying to the plugin's live database
also requires ``--allow-live-db``.  Only tags already present in the target are
eligible, and existing non-empty translations are never replaced.

Supported input layouts:

* Generic: ``tag``/``name``, ``category``, ``count``/``post_count`` and one of
  ``translation_cn``, ``cn_name``, ``zh_cn``, ``chinese`` or ``translation``.
* newtextdoc1111/danbooru-tag-csv: ``tag,category,count,alias``.  The alias
  field is multilingual, so only a unique, conservatively identified Chinese
  candidate is promoted to the display translation.

Run ``python tools/import_tag_translations.py --help`` for CLI usage.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"

MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_CSV_FIELD_BYTES = 1024 * 1024
MAX_TAG_BYTES = 256
MAX_TRANSLATION_BYTES = 512
MAX_METADATA_BYTES = 2048
MAX_REJECTION_EXAMPLES = 20
DEFAULT_MAX_REJECT_RATIO = 0.25

TAG_COLUMNS = ("tag", "name")
CATEGORY_COLUMNS = ("category", "type")
COUNT_COLUMNS = ("count", "post_count")
TRANSLATION_COLUMNS = (
    "translation_cn",
    "cn_name",
    "zh_cn",
    "lang_zh",
    "chinese",
    "translation",
)

# Artist names are intentionally excluded from the plugin's translation layer.
# Keep this allow-list explicit so both staging and the target-database UPSERT
# fail closed if new Danbooru categories are introduced later.
ALLOWED_TRANSLATION_CATEGORIES = frozenset((0, 3, 4, 5))

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_ALL_HAN_24_RE = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{1,24}$")
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")

_UNLICENSED_MARKERS = {
    "",
    "unknown",
    "unspecified",
    "none",
    "n/a",
    "no license",
    "unlicensed",
    "all rights reserved",
}


class TranslationImportError(RuntimeError):
    """Base error with a stable machine-readable code."""

    code = "translation_import_error"


class ImportValidationError(TranslationImportError):
    code = "validation_error"


class TargetDatabaseError(TranslationImportError):
    code = "target_database_error"


@dataclass(frozen=True)
class SourceMetadata:
    """Declared provenance for one immutable source snapshot."""

    source_url: str
    license: str
    revision: str

    def validate(self) -> None:
        source_url = _clean_metadata(self.source_url, "source_url")
        declared_license = _clean_metadata(self.license, "license")
        _clean_metadata(self.revision, "revision")

        parsed = urlparse(source_url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ImportValidationError("source_url must be an absolute HTTPS URL")
        if declared_license.casefold() in _UNLICENSED_MARKERS:
            raise ImportValidationError(
                "a declared reusable license is required; unlicensed packs are rejected"
            )

    def as_dict(self) -> Dict[str, str]:
        return {
            "source_url": self.source_url.strip(),
            "license": self.license.strip(),
            "revision": self.revision.strip(),
        }


def _clean_metadata(value: str, field: str) -> str:
    cleaned = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not cleaned:
        raise ImportValidationError("{} must not be empty".format(field))
    if _CONTROL_RE.search(cleaned):
        raise ImportValidationError("{} contains control characters".format(field))
    if len(cleaned.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ImportValidationError("{} is too large".format(field))
    return cleaned


def normalize_tag(value: object) -> str:
    """Return the canonical cache key: NFKC + casefold + spaces to underscores."""

    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = _WHITESPACE_RE.sub("_", normalized.strip()).casefold()
    if not normalized:
        raise ImportValidationError("tag is empty")
    if _CONTROL_RE.search(normalized):
        raise ImportValidationError("tag contains control characters")
    if len(normalized.encode("utf-8")) > MAX_TAG_BYTES:
        raise ImportValidationError("tag exceeds {} UTF-8 bytes".format(MAX_TAG_BYTES))
    return normalized


def normalize_translation(value: object) -> str:
    """Normalize display text without changing its word separators or case."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    if not normalized:
        raise ImportValidationError("translation is empty")
    if _CONTROL_RE.search(normalized):
        raise ImportValidationError("translation contains control characters")
    if len(normalized.encode("utf-8")) > MAX_TRANSLATION_BYTES:
        raise ImportValidationError(
            "translation exceeds {} UTF-8 bytes".format(MAX_TRANSLATION_BYTES)
        )
    return normalized


def _looks_chinese(value: str) -> bool:
    return bool(_HAN_RE.search(value)) and not _KANA_RE.search(value) and not _HANGUL_RE.search(value)


def select_newtextdoc_candidate(alias_value: object) -> Tuple[Optional[str], str]:
    """Select a conservative Chinese display candidate from multilingual aliases.

    Only an alias made entirely of 1--24 Han characters is eligible.  Exactly
    one eligible value must remain after de-duplication.  Multiple plausible
    aliases are reported as ambiguous instead of selecting one based on input
    order or trying to guess whether an all-Han term is Japanese or Chinese.
    """

    raw_alias = str(alias_value or "").strip()
    if not raw_alias or raw_alias.casefold() in {"null", "none", "nan"}:
        return None, "no_translation"
    if len(raw_alias.encode("utf-8")) > MAX_CSV_FIELD_BYTES:
        return None, "oversize_alias"

    candidates: List[str] = []
    seen = set()
    for raw_candidate in raw_alias.split(","):
        try:
            candidate = normalize_translation(raw_candidate)
        except ImportValidationError:
            continue
        if candidate in seen or not _ALL_HAN_24_RE.fullmatch(candidate):
            continue
        seen.add(candidate)
        candidates.append(candidate)

    if not candidates:
        return None, "no_translation"

    if len(candidates) == 1:
        return candidates[0], "selected_unique_han"
    return None, "ambiguous_translation"


def _normalized_header(value: object) -> str:
    header = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"[\s-]+", "_", header)


def _find_column(
    headers: Sequence[str], candidates: Iterable[str], explicit: Optional[str] = None
) -> Optional[str]:
    by_normalized = {_normalized_header(header): header for header in headers}
    if explicit:
        return by_normalized.get(_normalized_header(explicit))
    for candidate in candidates:
        if candidate in by_normalized:
            return by_normalized[candidate]
    return None


def _parse_integer(value: object, field: str, minimum: int, maximum: int) -> int:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if field == "post_count":
        text = text.replace(",", "").replace("_", "")
    try:
        parsed = int(text, 10)
    except (TypeError, ValueError):
        raise ImportValidationError("{} is not an integer".format(field))
    if parsed < minimum or parsed > maximum:
        raise ImportValidationError(
            "{} must be between {} and {}".format(field, minimum, maximum)
        )
    return parsed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _detect_delimiter(path: Path, encoding: str, explicit: Optional[str]) -> str:
    if explicit:
        delimiter = "\t" if explicit == r"\t" else explicit
        if len(delimiter) != 1:
            raise ImportValidationError("delimiter must be one character or \\t")
        return delimiter
    with path.open("r", encoding=encoding, newline="") as source:
        sample = source.read(64 * 1024)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except csv.Error:
        return ","


def _new_stage_report(input_path: Path, sha256: str, input_bytes: int) -> Dict[str, object]:
    return {
        "input_path": str(input_path),
        "input_bytes": input_bytes,
        "sha256": sha256,
        "format": None,
        "delimiter": None,
        "total_rows": 0,
        "candidate_rows": 0,
        "staged_rows": 0,
        "rejected_rows": 0,
        "skipped_disallowed_category": 0,
        "skipped_no_translation": 0,
        "skipped_ambiguous_translation": 0,
        "duplicate_conflicts": 0,
        "rejection_examples": [],
    }


def _record_rejection(report: Dict[str, object], line: int, reason: str) -> None:
    report["rejected_rows"] = int(report["rejected_rows"]) + 1
    examples = report["rejection_examples"]
    if isinstance(examples, list) and len(examples) < MAX_REJECTION_EXAMPLES:
        examples.append({"line": line, "reason": reason})


def _stage_csv(
    input_path: Path,
    stage_db_path: Path,
    *,
    pack_format: str,
    encoding: str,
    delimiter: Optional[str],
    translation_column: Optional[str],
    max_reject_ratio: float,
    sha256: str,
) -> Dict[str, object]:
    input_bytes = input_path.stat().st_size
    report = _new_stage_report(input_path, sha256, input_bytes)
    selected_delimiter = _detect_delimiter(input_path, encoding, delimiter)
    report["delimiter"] = "\\t" if selected_delimiter == "\t" else selected_delimiter

    stage = sqlite3.connect(str(stage_db_path))
    try:
        stage.execute(
            """
            CREATE TABLE staged (
                tag TEXT PRIMARY KEY,
                category INTEGER NOT NULL,
                post_count INTEGER NOT NULL,
                translation_cn TEXT
            )
            """
        )
        previous_field_limit = csv.field_size_limit()
        csv.field_size_limit(MAX_CSV_FIELD_BYTES)
        try:
            with input_path.open("r", encoding=encoding, newline="") as source:
                reader = csv.DictReader(source, delimiter=selected_delimiter)
                raw_headers = list(reader.fieldnames or [])
                if not raw_headers:
                    raise ImportValidationError("CSV has no header row")
                if len({_normalized_header(header) for header in raw_headers}) != len(raw_headers):
                    raise ImportValidationError("CSV contains duplicate normalized headers")

                tag_column = _find_column(raw_headers, TAG_COLUMNS)
                category_column = _find_column(raw_headers, CATEGORY_COLUMNS)
                count_column = _find_column(raw_headers, COUNT_COLUMNS)
                explicit_translation = _find_column(
                    raw_headers, TRANSLATION_COLUMNS, explicit=translation_column
                )
                alias_column = _find_column(raw_headers, ("alias", "aliases"))

                missing = []
                if not tag_column:
                    missing.append("tag/name")
                if not category_column:
                    missing.append("category/type")
                if not count_column:
                    missing.append("count/post_count")
                if missing:
                    raise ImportValidationError(
                        "CSV is missing required columns: {}".format(", ".join(missing))
                    )

                if translation_column and not explicit_translation:
                    raise ImportValidationError(
                        "requested translation column {!r} was not found".format(
                            translation_column
                        )
                    )

                detected_format = pack_format
                if pack_format == "auto":
                    detected_format = "generic" if explicit_translation else "newtextdoc"
                if detected_format == "generic" and not explicit_translation:
                    raise ImportValidationError(
                        "generic CSV needs a Chinese translation column ({})".format(
                            ", ".join(TRANSLATION_COLUMNS)
                        )
                    )
                if detected_format == "newtextdoc" and not alias_column:
                    raise ImportValidationError(
                        "newtextdoc format requires an alias/aliases column"
                    )
                report["format"] = detected_format

                for line_number, row in enumerate(reader, start=2):
                    report["total_rows"] = int(report["total_rows"]) + 1
                    if None in row:
                        _record_rejection(report, line_number, "row has extra CSV fields")
                        continue
                    try:
                        raw_tag = row.get(tag_column or "", "")
                        if len(str(raw_tag).encode("utf-8")) > MAX_TAG_BYTES * 2:
                            raise ImportValidationError("tag input is oversized")
                        tag = normalize_tag(raw_tag)
                        category = _parse_integer(
                            row.get(category_column or ""), "category", 0, 5
                        )
                        post_count = _parse_integer(
                            row.get(count_column or ""),
                            "post_count",
                            0,
                            9_223_372_036_854_775_807,
                        )

                        if category not in ALLOWED_TRANSLATION_CATEGORIES:
                            report["skipped_disallowed_category"] = (
                                int(report["skipped_disallowed_category"]) + 1
                            )
                            continue

                        if detected_format == "newtextdoc":
                            alias_value = row.get(alias_column or "", "")
                            translation, selection = select_newtextdoc_candidate(alias_value)
                            if translation is None:
                                if selection == "ambiguous_translation":
                                    report["skipped_ambiguous_translation"] = (
                                        int(report["skipped_ambiguous_translation"]) + 1
                                    )
                                elif selection == "oversize_alias":
                                    raise ImportValidationError("alias field is oversized")
                                else:
                                    report["skipped_no_translation"] = (
                                        int(report["skipped_no_translation"]) + 1
                                    )
                                continue
                        else:
                            raw_translation = row.get(explicit_translation or "", "")
                            if not str(raw_translation or "").strip():
                                report["skipped_no_translation"] = (
                                    int(report["skipped_no_translation"]) + 1
                                )
                                continue
                            translation = normalize_translation(raw_translation)
                            if not _looks_chinese(translation):
                                raise ImportValidationError(
                                    "translation is not a Chinese candidate"
                                )

                        report["candidate_rows"] = int(report["candidate_rows"]) + 1
                        stage.execute(
                            """
                            INSERT INTO staged(tag, category, post_count, translation_cn)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(tag) DO UPDATE SET
                                post_count = MAX(staged.post_count, excluded.post_count),
                                translation_cn = CASE
                                    WHEN staged.translation_cn = excluded.translation_cn
                                        THEN staged.translation_cn
                                    ELSE NULL
                                END
                            """,
                            (tag, category, post_count, translation),
                        )
                    except ImportValidationError as exc:
                        _record_rejection(report, line_number, str(exc))
        except (UnicodeError, csv.Error) as exc:
            raise ImportValidationError("unable to parse CSV: {}".format(exc))
        finally:
            csv.field_size_limit(previous_field_limit)

        ambiguous_duplicates = stage.execute(
            "SELECT COUNT(*) FROM staged WHERE translation_cn IS NULL"
        ).fetchone()[0]
        report["duplicate_conflicts"] = int(ambiguous_duplicates)
        stage.execute("DELETE FROM staged WHERE translation_cn IS NULL")
        report["staged_rows"] = stage.execute("SELECT COUNT(*) FROM staged").fetchone()[0]
        stage.commit()
    finally:
        stage.close()

    total_rows = int(report["total_rows"])
    rejected_rows = int(report["rejected_rows"])
    if total_rows == 0:
        raise ImportValidationError("CSV has no data rows")
    if rejected_rows / total_rows > max_reject_ratio:
        raise ImportValidationError(
            "rejected row ratio {:.2%} exceeds the configured {:.2%}".format(
                rejected_rows / total_rows, max_reject_ratio
            )
        )
    if int(report["staged_rows"]) == 0:
        raise ImportValidationError("no unambiguous Chinese translations were staged")
    return report


def _readonly_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_readonly_uri(path), uri=True, timeout=30.0)
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _validate_target_schema(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(hot_tags)").fetchall()
    }
    required = {
        "tag",
        "category",
        "post_count",
        "translation_cn",
        "last_updated",
        "aliases",
    }
    missing = sorted(required - columns)
    if missing:
        raise TargetDatabaseError(
            "hot_tags is missing required columns: {}".format(", ".join(missing))
        )
    fts_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'hot_tags_fts'"
    ).fetchone()
    if not fts_row or "VIRTUAL TABLE" not in str(fts_row[0] or "").upper():
        raise TargetDatabaseError("hot_tags_fts FTS5 table is missing")
    docsize_row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='hot_tags_fts_docsize'"
    ).fetchone()
    if not docsize_row:
        raise TargetDatabaseError(
            "hot_tags_fts_docsize is missing; real FTS document count cannot be verified"
        )


def _fts_document_count(connection: sqlite3.Connection) -> int:
    """Count real indexed documents, not external-content proxy rows."""

    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM hot_tags_fts_docsize"
            ).fetchone()[0]
        )
    except sqlite3.DatabaseError as exc:
        raise TargetDatabaseError(
            "unable to read hot_tags_fts_docsize: {}".format(exc)
        ) from exc


def _integrity_result(connection: sqlite3.Connection) -> str:
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    return "\n".join(str(row[0]) for row in rows)


def _has_prior_import(
    connection: sqlite3.Connection, metadata: SourceMetadata, sha256: str
) -> bool:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='tag_translation_imports'"
    ).fetchone()
    if not exists:
        return False
    row = connection.execute(
        """
        SELECT 1 FROM tag_translation_imports
        WHERE source_url = ? AND revision = ? AND sha256 = ?
        LIMIT 1
        """,
        (metadata.source_url.strip(), metadata.revision.strip(), sha256),
    ).fetchone()
    return row is not None


def _inspect_target(
    db_path: Path,
    stage_db_path: Path,
    metadata: SourceMetadata,
    sha256: str,
) -> Dict[str, object]:
    target = _connect_readonly(db_path)
    try:
        _validate_target_schema(target)
        integrity = _integrity_result(target)
        if integrity != "ok":
            raise TargetDatabaseError("target integrity_check failed: {}".format(integrity))
        target.execute(
            "ATTACH DATABASE ? AS stagepack", (_readonly_uri(stage_db_path),)
        )
        try:
            total_tags = target.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0]
            translated_tags = target.execute(
                "SELECT COUNT(*) FROM hot_tags "
                "WHERE NULLIF(TRIM(translation_cn), '') IS NOT NULL"
            ).fetchone()[0]
            fts_rows = _fts_document_count(target)
            would_reject_missing = target.execute(
                """
                SELECT COUNT(*)
                FROM stagepack.staged s
                LEFT JOIN hot_tags h ON h.tag = s.tag
                WHERE h.tag IS NULL
                """
            ).fetchone()[0]
            would_fill = target.execute(
                """
                SELECT COUNT(*)
                FROM stagepack.staged s
                JOIN hot_tags h ON h.tag = s.tag
                WHERE NULLIF(TRIM(h.translation_cn), '') IS NULL
                  AND h.category IN (0, 3, 4, 5)
                """
            ).fetchone()[0]
            would_preserve = target.execute(
                """
                SELECT COUNT(*)
                FROM stagepack.staged s
                JOIN hot_tags h ON h.tag = s.tag
                WHERE NULLIF(TRIM(h.translation_cn), '') IS NOT NULL
                  AND h.category IN (0, 3, 4, 5)
                """
            ).fetchone()[0]
            would_skip_disallowed_target = target.execute(
                """
                SELECT COUNT(*)
                FROM stagepack.staged s
                JOIN hot_tags h ON h.tag = s.tag
                WHERE h.category NOT IN (0, 3, 4, 5)
                """
            ).fetchone()[0]
        finally:
            target.execute("DETACH DATABASE stagepack")
        return {
            "integrity": integrity,
            "total_tags": total_tags,
            "translated_tags": translated_tags,
            "fts_rows": fts_rows,
            "fts_matches_hot_tags": fts_rows == total_tags,
            # Kept for report-schema compatibility. Imports never create tags.
            "would_insert_tags": 0,
            "would_reject_missing_target_tags": would_reject_missing,
            "would_fill_translations": would_fill,
            "would_preserve_translations": would_preserve,
            "would_skip_disallowed_target_category": would_skip_disallowed_target,
            "already_imported": _has_prior_import(target, metadata, sha256),
        }
    finally:
        target.close()


def _unique_backup_path(db_path: Path, backup_dir: Optional[Path], sha256: str) -> Path:
    destination_dir = (backup_dir or db_path.parent).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = db_path.suffix or ".db"
    base = "{}.pre_tag_translation_{}_{}{}".format(
        db_path.stem, timestamp, sha256[:12], suffix
    )
    candidate = destination_dir / base
    counter = 1
    while candidate.exists():
        candidate = destination_dir / "{}.pre_tag_translation_{}_{}_{}{}".format(
            db_path.stem, timestamp, sha256[:12], counter, suffix
        )
        counter += 1
    return candidate


def _online_backup(db_path: Path, backup_path: Path) -> None:
    source = _connect_readonly(db_path)
    destination = sqlite3.connect(str(backup_path))
    try:
        source.backup(destination)
        destination.commit()
        integrity = _integrity_result(destination)
        if integrity != "ok":
            raise TargetDatabaseError(
                "backup integrity_check failed: {}".format(integrity)
            )
    finally:
        destination.close()
        source.close()


def _create_provenance_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tag_translation_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT NOT NULL,
            declared_license TEXT NOT NULL,
            revision TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            input_filename TEXT NOT NULL,
            imported_at_utc TEXT NOT NULL,
            input_rows INTEGER NOT NULL,
            staged_rows INTEGER NOT NULL,
            inserted_tags INTEGER NOT NULL,
            filled_translations INTEGER NOT NULL,
            preserved_translations INTEGER NOT NULL,
            rejected_rows INTEGER NOT NULL,
            skipped_rows INTEGER NOT NULL,
            UNIQUE(source_url, revision, sha256)
        )
        """
    )


def _counts_inside_transaction(connection: sqlite3.Connection) -> Dict[str, int]:
    filled = connection.execute(
        """
        SELECT COUNT(*)
        FROM stagepack.staged s
        JOIN hot_tags h ON h.tag = s.tag
        WHERE NULLIF(TRIM(h.translation_cn), '') IS NULL
          AND h.category IN (0, 3, 4, 5)
        """
    ).fetchone()[0]
    preserved = connection.execute(
        """
        SELECT COUNT(*)
        FROM stagepack.staged s
        JOIN hot_tags h ON h.tag = s.tag
        WHERE NULLIF(TRIM(h.translation_cn), '') IS NOT NULL
          AND h.category IN (0, 3, 4, 5)
        """
    ).fetchone()[0]
    return {
        "inserted_tags": 0,
        "filled_translations": int(filled),
        "preserved_translations": int(preserved),
    }


def _apply_import(
    db_path: Path,
    stage_db_path: Path,
    input_path: Path,
    metadata: SourceMetadata,
    stage_report: Mapping[str, object],
    *,
    force: bool,
) -> Dict[str, object]:
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("ATTACH DATABASE ? AS stagepack", (str(stage_db_path),))
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            _validate_target_schema(connection)
            _create_provenance_table(connection)
            sha256 = str(stage_report["sha256"])
            if not force and _has_prior_import(connection, metadata, sha256):
                connection.execute("ROLLBACK")
                return {"already_imported": True}

            counts = _counts_inside_transaction(connection)
            skipped_disallowed_target = connection.execute(
                """
                SELECT COUNT(*)
                FROM stagepack.staged s
                JOIN hot_tags h ON h.tag = s.tag
                WHERE h.category NOT IN (0, 3, 4, 5)
                """
            ).fetchone()[0]
            skipped_missing_target = connection.execute(
                """
                SELECT COUNT(*)
                FROM stagepack.staged s
                LEFT JOIN hot_tags h ON h.tag = s.tag
                WHERE h.tag IS NULL
                """
            ).fetchone()[0]
            now_epoch = int(datetime.now(timezone.utc).timestamp())
            connection.execute(
                """
                UPDATE hot_tags
                SET translation_cn = (
                        SELECT s.translation_cn
                        FROM stagepack.staged s
                        WHERE s.tag = hot_tags.tag
                    ),
                    last_updated = ?
                WHERE hot_tags.category IN (0, 3, 4, 5)
                  AND NULLIF(TRIM(hot_tags.translation_cn), '') IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM stagepack.staged s
                      WHERE s.tag = hot_tags.tag
                        AND s.translation_cn IS NOT NULL
                  )
                """,
                (now_epoch,),
            )

            # FTS5's external-content rebuild command is atomic with the import.
            connection.execute(
                "INSERT INTO hot_tags_fts(hot_tags_fts) VALUES ('rebuild')"
            )
            total_after = connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0]
            translated_after = connection.execute(
                "SELECT COUNT(*) FROM hot_tags "
                "WHERE NULLIF(TRIM(translation_cn), '') IS NOT NULL"
            ).fetchone()[0]
            fts_after = _fts_document_count(connection)
            if fts_after != total_after:
                raise TargetDatabaseError(
                    "FTS row count {} does not match hot_tags {}".format(
                        fts_after, total_after
                    )
                )
            integrity = _integrity_result(connection)
            if integrity != "ok":
                raise TargetDatabaseError(
                    "post-import integrity_check failed: {}".format(integrity)
                )

            skipped_rows = (
                int(stage_report["skipped_disallowed_category"])
                + int(stage_report["skipped_no_translation"])
                + int(stage_report["skipped_ambiguous_translation"])
                + int(stage_report["duplicate_conflicts"])
                + int(skipped_disallowed_target)
                + int(skipped_missing_target)
            )
            connection.execute(
                """
                INSERT INTO tag_translation_imports(
                    source_url, declared_license, revision, sha256,
                    input_filename, imported_at_utc, input_rows, staged_rows,
                    inserted_tags, filled_translations, preserved_translations,
                    rejected_rows, skipped_rows
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_url, revision, sha256) DO UPDATE SET
                    declared_license = excluded.declared_license,
                    input_filename = excluded.input_filename,
                    imported_at_utc = excluded.imported_at_utc,
                    input_rows = excluded.input_rows,
                    staged_rows = excluded.staged_rows,
                    inserted_tags = excluded.inserted_tags,
                    filled_translations = excluded.filled_translations,
                    preserved_translations = excluded.preserved_translations,
                    rejected_rows = excluded.rejected_rows,
                    skipped_rows = excluded.skipped_rows
                """,
                (
                    metadata.source_url.strip(),
                    metadata.license.strip(),
                    metadata.revision.strip(),
                    sha256,
                    input_path.name,
                    imported_at,
                    int(stage_report["total_rows"]),
                    int(stage_report["staged_rows"]),
                    counts["inserted_tags"],
                    counts["filled_translations"],
                    counts["preserved_translations"],
                    int(stage_report["rejected_rows"]),
                    skipped_rows,
                ),
            )
            connection.execute("COMMIT")
            return {
                "already_imported": False,
                "counts": counts,
                "target_after": {
                    "total_tags": int(total_after),
                    "translated_tags": int(translated_after),
                    "fts_rows": int(fts_after),
                    "fts_matches_hot_tags": True,
                    "integrity": integrity,
                },
                "imported_at_utc": imported_at,
                "skipped_disallowed_target_category": int(
                    skipped_disallowed_target
                ),
                "skipped_missing_target_tags": int(skipped_missing_target),
            }
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
    finally:
        try:
            connection.execute("DETACH DATABASE stagepack")
        finally:
            connection.close()


def import_translation_pack(
    input_path: Path,
    db_path: Path,
    metadata: SourceMetadata,
    *,
    apply: bool = False,
    dry_run: bool = False,
    allow_live_db: bool = False,
    pack_format: str = "auto",
    encoding: str = "utf-8-sig",
    delimiter: Optional[str] = None,
    translation_column: Optional[str] = None,
    max_reject_ratio: float = DEFAULT_MAX_REJECT_RATIO,
    max_input_bytes: int = MAX_INPUT_BYTES,
    backup_dir: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, object]:
    """Validate a pack and, only with ``apply=True``, update existing tags."""

    metadata.validate()
    if apply and dry_run:
        raise ImportValidationError("apply and dry_run are mutually exclusive")
    if pack_format not in {"auto", "generic", "newtextdoc"}:
        raise ImportValidationError("unsupported pack format: {}".format(pack_format))
    if not 0.0 <= max_reject_ratio <= 1.0:
        raise ImportValidationError("max_reject_ratio must be between 0 and 1")

    source_path = Path(input_path).expanduser().resolve()
    target_path = Path(db_path).expanduser().resolve()
    if not source_path.is_file():
        raise ImportValidationError("input CSV does not exist: {}".format(source_path))
    input_bytes = source_path.stat().st_size
    if input_bytes <= 0:
        raise ImportValidationError("input CSV is empty")
    if input_bytes > max_input_bytes:
        raise ImportValidationError(
            "input CSV exceeds the {} byte safety limit".format(max_input_bytes)
        )
    if not target_path.is_file():
        raise TargetDatabaseError("target database does not exist: {}".format(target_path))
    if apply and target_path == DEFAULT_DB_PATH.resolve() and not allow_live_db:
        raise TargetDatabaseError(
            "applying to the plugin live tags_cache.db requires --allow-live-db"
        )

    sha256 = _sha256_file(source_path)
    with tempfile.TemporaryDirectory(prefix="tag_translation_stage_") as temp_dir:
        stage_path = Path(temp_dir) / "staged.sqlite3"
        stage_report = _stage_csv(
            source_path,
            stage_path,
            pack_format=pack_format,
            encoding=encoding,
            delimiter=delimiter,
            translation_column=translation_column,
            max_reject_ratio=max_reject_ratio,
            sha256=sha256,
        )
        target_before = _inspect_target(target_path, stage_path, metadata, sha256)
        report: Dict[str, object] = {
            "schema_version": 1,
            "status": "pending" if apply else "dry_run",
            "dry_run": not apply,
            "source": metadata.as_dict(),
            "pack": stage_report,
            "target_db": str(target_path),
            "target_before": target_before,
            "backup_path": None,
        }
        if not apply:
            return report
        if bool(target_before["already_imported"]) and not force:
            report["status"] = "already_imported"
            return report

        backup_path = _unique_backup_path(
            target_path, Path(backup_dir).resolve() if backup_dir else None, sha256
        )
        _online_backup(target_path, backup_path)
        report["backup_path"] = str(backup_path)
        apply_report = _apply_import(
            target_path,
            stage_path,
            source_path,
            metadata,
            stage_report,
            force=force,
        )
        if bool(apply_report.get("already_imported")):
            report["status"] = "already_imported"
        else:
            report["status"] = "imported"
            report.update(
                {
                    "counts": apply_report["counts"],
                    "target_after": apply_report["target_after"],
                    "imported_at_utc": apply_report["imported_at_utc"],
                    "skipped_disallowed_target_category": apply_report[
                        "skipped_disallowed_target_category"
                    ],
                    "skipped_missing_target_tags": apply_report[
                        "skipped_missing_target_tags"
                    ],
                }
            )
        return report


def _same_existing_file(left: Path, right: Path) -> bool:
    """Return whether two existing paths name the same filesystem object."""

    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError, ValueError):
        return False


def _validate_json_report_destination(
    output: Path,
    protected_paths: Sequence[Optional[Path]],
) -> Path:
    """Fail closed before a JSON report can overwrite an input or database."""

    destination = Path(output).expanduser().resolve()
    for protected_path in protected_paths:
        if protected_path is None:
            continue
        protected = Path(protected_path).expanduser().resolve()
        if destination == protected or _same_existing_file(destination, protected):
            raise ImportValidationError(
                "json_report must not be the input, target, staging, or backup file"
            )
    if destination.exists():
        raise ImportValidationError(
            "json_report already exists; refusing to overwrite it"
        )
    return destination


def _write_json_report(
    report: Mapping[str, object],
    output: Optional[Path],
    *,
    protected_paths: Sequence[Optional[Path]] = (),
) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        # Revalidate immediately before the create to close the gap between the
        # CLI preflight and the potentially long staging/import operation.
        destination = _validate_json_report_destination(output, protected_paths)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".{}.".format(destination.name),
                suffix=".tmp",
                dir=str(destination.parent),
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered + "\n")
                stream.flush()
                os.fsync(stream.fileno())

            # Publish a fully written inode with a no-clobber hard link.  This
            # gives readers atomic visibility while retaining O_EXCL semantics:
            # os.link fails if another process created the destination.
            _validate_json_report_destination(output, protected_paths)
            os.link(temporary_path, destination)
        except FileExistsError as exc:
            raise ImportValidationError(
                "json_report appeared concurrently; refusing to overwrite it"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
    print(rendered)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stage, validate and import licensed Chinese tag translations without "
            "overwriting existing translations."
        )
    )
    parser.add_argument("input_csv", type=Path, help="local CSV snapshot to import")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--source-url", required=True, help="public HTTPS source page")
    parser.add_argument("--license", required=True, dest="declared_license")
    parser.add_argument("--revision", required=True, help="immutable commit/revision ID")
    parser.add_argument(
        "--format",
        choices=("auto", "generic", "newtextdoc"),
        default="auto",
        dest="pack_format",
    )
    parser.add_argument("--translation-column")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--delimiter", help="one character; use \\t for TSV")
    parser.add_argument(
        "--max-reject-ratio", type=float, default=DEFAULT_MAX_REJECT_RATIO
    )
    parser.add_argument("--max-input-bytes", type=int, default=MAX_INPUT_BYTES)
    parser.add_argument("--backup-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="apply translations to existing target tags (default: dry-run)",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="compatibility spelling for the default read-only mode",
    )
    parser.add_argument(
        "--allow-live-db",
        action="store_true",
        help=(
            "second explicit confirmation required with --apply when --db resolves "
            "to the plugin's live tags_cache.db"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-apply an already recorded snapshot (still never overwrites translations)",
    )
    parser.add_argument("--json-report", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    initial_protected = [arguments.input_csv, arguments.db]
    try:
        if arguments.json_report:
            _validate_json_report_destination(
                arguments.json_report,
                initial_protected,
            )
        report = import_translation_pack(
            arguments.input_csv,
            arguments.db,
            SourceMetadata(
                source_url=arguments.source_url,
                license=arguments.declared_license,
                revision=arguments.revision,
            ),
            apply=arguments.apply,
            dry_run=arguments.dry_run,
            allow_live_db=arguments.allow_live_db,
            pack_format=arguments.pack_format,
            encoding=arguments.encoding,
            delimiter=arguments.delimiter,
            translation_column=arguments.translation_column,
            max_reject_ratio=arguments.max_reject_ratio,
            max_input_bytes=arguments.max_input_bytes,
            backup_dir=arguments.backup_dir,
            force=arguments.force,
        )
        dynamic_protected = initial_protected + [
            Path(report["backup_path"])
            if report.get("backup_path")
            else None,
        ]
        _write_json_report(
            report,
            arguments.json_report,
            protected_paths=dynamic_protected,
        )
        return 0
    except TranslationImportError as exc:
        error_report = {
            "schema_version": 1,
            "status": "error",
            "error": {"code": exc.code, "message": str(exc)},
        }
        # The validation error may itself mean that json_report points at a
        # protected file, so error paths are deliberately stdout-only.
        _write_json_report(error_report, None)
        return 2
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        error_report = {
            "schema_version": 1,
            "status": "error",
            "error": {"code": "unexpected_error", "message": str(exc)},
        }
        _write_json_report(error_report, None)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
