#!/usr/bin/env python3
"""Safely import the pinned, licensed Danbooru alias snapshot.

The source is verified before parsing, staged in a temporary SQLite database,
and joined against the live ``hot_tags`` table.  Only aliases whose canonical
tag already exists and is not category 1 (artist) are eligible.  This tool
never inserts, updates, or deletes a ``hot_tags`` row.
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
from typing import Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_TAG_BYTES = 256
MAX_REJECTION_EXAMPLES = 20
DEFAULT_MAX_REJECT_RATIO = 0.01

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AliasImportError(RuntimeError):
    code = "alias_import_error"


class AliasImportValidationError(AliasImportError):
    code = "validation_error"


class AliasTargetDatabaseError(AliasImportError):
    code = "target_database_error"


@dataclass(frozen=True)
class AliasSourceMetadata:
    source_name: str
    source_url: str
    license: str
    revision: str
    expected_sha256: str
    expected_size: int

    def validate(self) -> None:
        for field_name in ("source_name", "source_url", "license", "revision"):
            value = unicodedata.normalize(
                "NFKC", str(getattr(self, field_name) or "")
            ).strip()
            if not value or _CONTROL_RE.search(value):
                raise AliasImportValidationError(
                    "{} must be non-empty and contain no control characters".format(
                        field_name
                    )
                )
        parsed = urlparse(self.source_url.strip())
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise AliasImportValidationError(
                "source_url must be an absolute HTTPS URL"
            )
        if self.license.strip().casefold() in {
            "unknown", "unlicensed", "no license", "all rights reserved"
        }:
            raise AliasImportValidationError("a reusable license is required")
        if not _SHA256_RE.fullmatch(self.expected_sha256.strip().casefold()):
            raise AliasImportValidationError("expected_sha256 must be 64 hex digits")
        if self.expected_size <= 0 or self.expected_size > MAX_INPUT_BYTES:
            raise AliasImportValidationError("expected_size is outside safe bounds")

    def as_dict(self) -> Dict[str, object]:
        return {
            "source_name": self.source_name.strip(),
            "source_url": self.source_url.strip(),
            "license": self.license.strip(),
            "revision": self.revision.strip(),
            "expected_sha256": self.expected_sha256.strip().casefold(),
            "expected_size": int(self.expected_size),
        }


FIXED_SOURCE = AliasSourceMetadata(
    source_name="deepghs/site_tags",
    source_url=(
        "https://huggingface.co/datasets/deepghs/site_tags/resolve/"
        "2b4de8c3f79540b10387a6fa7f251274f0b224a8/"
        "danbooru.donmai.us/tag_aliases.csv"
    ),
    license="CC-BY-4.0",
    revision="2b4de8c3f79540b10387a6fa7f251274f0b224a8",
    expected_sha256=(
        "a3dad50f86f4b8d117096c64ba1bd332be02b16222c587a8d2cddddf86ed852a"
    ),
    expected_size=1_684_212,
)


def normalize_tag(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    normalized = _WHITESPACE_RE.sub("_", normalized).casefold()
    if not normalized:
        raise AliasImportValidationError("tag is empty")
    if _CONTROL_RE.search(normalized):
        raise AliasImportValidationError("tag contains control characters")
    if len(normalized.encode("utf-8")) > MAX_TAG_BYTES:
        raise AliasImportValidationError("tag exceeds the UTF-8 byte limit")
    return normalized


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
                raise AliasImportValidationError(
                    "{} and {} must be distinct files "
                    "(resolved path/hard-link collision)".format(left_name, right_name)
                )


def _verify_source(
    input_path: Path,
    verified_snapshot_path: Path,
    source_metadata: AliasSourceMetadata,
) -> Dict[str, object]:
    source_metadata.validate()
    if not input_path.is_file():
        raise AliasImportValidationError("input CSV does not exist")
    digest = hashlib.sha256()
    input_size = 0
    try:
        with input_path.open("rb") as source, verified_snapshot_path.open("xb") as copy:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                input_size += len(block)
                if input_size > MAX_INPUT_BYTES:
                    raise AliasImportValidationError(
                        "input CSV exceeds the safe size limit"
                    )
                digest.update(block)
                copy.write(block)
    except OSError as exc:
        raise AliasImportValidationError(
            "unable to snapshot input CSV: {}".format(exc)
        )
    if input_size != source_metadata.expected_size:
        raise AliasImportValidationError(
            "source size mismatch: expected {}, got {}".format(
                source_metadata.expected_size, input_size
            )
        )
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != source_metadata.expected_sha256.strip().casefold():
        raise AliasImportValidationError(
            "source SHA256 mismatch: expected {}, got {}".format(
                source_metadata.expected_sha256, actual_sha256
            )
        )
    return {
        **source_metadata.as_dict(),
        "actual_sha256": actual_sha256,
        "actual_size": input_size,
        "input_path": str(input_path),
    }


def _record_rejection(report: Dict[str, object], line: int, reason: str) -> None:
    report["rejected_rows"] = int(report["rejected_rows"]) + 1
    examples = report["rejection_examples"]
    if isinstance(examples, list) and len(examples) < MAX_REJECTION_EXAMPLES:
        examples.append({"line": line, "reason": reason})


def _stage_csv(
    input_path: Path,
    stage_db_path: Path,
    source_report: Mapping[str, object],
    *,
    max_reject_ratio: float,
) -> Dict[str, object]:
    report: Dict[str, object] = {
        "total_rows": 0,
        "candidate_rows": 0,
        "staged_rows": 0,
        "rejected_rows": 0,
        "duplicate_rows": 0,
        "duplicate_conflicts": 0,
        "skipped_self_alias": 0,
        "rejection_examples": [],
    }
    stage = sqlite3.connect(str(stage_db_path))
    try:
        stage.executescript(
            """
            CREATE TABLE staged_aliases (
                alias TEXT PRIMARY KEY COLLATE NOCASE,
                canonical_tag TEXT
            );
            CREATE INDEX idx_staged_aliases_canonical
                ON staged_aliases(canonical_tag);
            CREATE TABLE stage_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        try:
            with input_path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                raw_headers = list(reader.fieldnames or [])
                normalized_headers = {
                    unicodedata.normalize("NFKC", str(header or ""))
                    .strip()
                    .casefold(): header
                    for header in raw_headers
                }
                if (
                    len(raw_headers) != 2
                    or len(normalized_headers) != 2
                    or set(normalized_headers) != {"alias", "tag"}
                ):
                    raise AliasImportValidationError(
                        "CSV header must contain exactly alias,tag"
                    )
                alias_column = normalized_headers["alias"]
                tag_column = normalized_headers["tag"]

                for line_number, row in enumerate(reader, start=2):
                    report["total_rows"] = int(report["total_rows"]) + 1
                    if None in row:
                        _record_rejection(
                            report, line_number, "row has extra CSV fields"
                        )
                        continue
                    try:
                        alias = normalize_tag(row.get(alias_column, ""))
                        canonical_tag = normalize_tag(row.get(tag_column, ""))
                        if alias == canonical_tag:
                            report["skipped_self_alias"] = (
                                int(report["skipped_self_alias"]) + 1
                            )
                            continue
                        report["candidate_rows"] = int(report["candidate_rows"]) + 1
                        existing = stage.execute(
                            "SELECT canonical_tag FROM staged_aliases WHERE alias = ?",
                            (alias,),
                        ).fetchone()
                        if existing is None:
                            stage.execute(
                                "INSERT INTO staged_aliases(alias, canonical_tag) "
                                "VALUES (?, ?)",
                                (alias, canonical_tag),
                            )
                        elif existing[0] == canonical_tag:
                            report["duplicate_rows"] = (
                                int(report["duplicate_rows"]) + 1
                            )
                        else:
                            stage.execute(
                                "UPDATE staged_aliases SET canonical_tag = NULL "
                                "WHERE alias = ?",
                                (alias,),
                            )
                    except AliasImportValidationError as exc:
                        _record_rejection(report, line_number, str(exc))
        except (UnicodeError, csv.Error) as exc:
            raise AliasImportValidationError(
                "unable to parse alias CSV: {}".format(exc)
            )

        conflict_count = stage.execute(
            "SELECT COUNT(*) FROM staged_aliases WHERE canonical_tag IS NULL"
        ).fetchone()[0]
        report["duplicate_conflicts"] = int(conflict_count)
        stage.execute("DELETE FROM staged_aliases WHERE canonical_tag IS NULL")
        report["staged_rows"] = int(
            stage.execute("SELECT COUNT(*) FROM staged_aliases").fetchone()[0]
        )
        metadata = {
            "source": dict(source_report),
            "stage": report,
        }
        stage.execute(
            "INSERT INTO stage_metadata(key, value) VALUES (?, ?)",
            ("manifest", json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
        )
        stage.commit()
    finally:
        stage.close()

    total_rows = int(report["total_rows"])
    rejected_rows = int(report["rejected_rows"])
    if total_rows == 0:
        raise AliasImportValidationError("CSV has no data rows")
    if rejected_rows / total_rows > max_reject_ratio:
        raise AliasImportValidationError(
            "rejected row ratio {:.2%} exceeds configured {:.2%}".format(
                rejected_rows / total_rows, max_reject_ratio
            )
        )
    if int(report["staged_rows"]) == 0:
        raise AliasImportValidationError("no valid aliases were staged")
    return report


def _readonly_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_readonly_uri(path), uri=True, timeout=30.0)
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _integrity_result(connection: sqlite3.Connection) -> str:
    return "\n".join(
        str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()
    )


_ALIAS_COLUMNS = {
    "alias",
    "canonical_tag",
    "relation_type",
    "source_name",
    "source_url",
    "declared_license",
    "source_revision",
    "source_sha256",
    "imported_at",
}


def _validate_hot_tags_schema(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(hot_tags)").fetchall()
    }
    missing = {"tag", "category"} - columns
    if missing:
        raise AliasTargetDatabaseError(
            "hot_tags is missing required columns: {}".format(
                ", ".join(sorted(missing))
            )
        )


def _alias_table_exists(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tag_aliases'"
    ).fetchone() is not None


def _validate_alias_schema(connection: sqlite3.Connection) -> None:
    if not _alias_table_exists(connection):
        return
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(tag_aliases)").fetchall()
    }
    missing = _ALIAS_COLUMNS - columns
    if missing:
        raise AliasTargetDatabaseError(
            "tag_aliases is missing required columns: {}".format(
                ", ".join(sorted(missing))
            )
        )


def _create_alias_schema(connection: sqlite3.Connection) -> None:
    # Keep each DDL statement on the caller's transaction. ``executescript``
    # issues an implicit COMMIT in Python's sqlite3 wrapper and would break the
    # all-or-nothing import guarantee.
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
        """
        CREATE INDEX IF NOT EXISTS idx_tag_aliases_canonical
            ON tag_aliases(canonical_tag COLLATE NOCASE)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tag_aliases_source_revision
            ON tag_aliases(source_name, source_revision)
        """
    )
    _validate_alias_schema(connection)


def _create_provenance_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tag_alias_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            declared_license TEXT NOT NULL,
            revision TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            input_filename TEXT NOT NULL,
            imported_at_utc TEXT NOT NULL,
            input_rows INTEGER NOT NULL,
            staged_rows INTEGER NOT NULL,
            eligible_rows INTEGER NOT NULL,
            inserted_aliases INTEGER NOT NULL,
            updated_aliases INTEGER NOT NULL,
            preserved_aliases INTEGER NOT NULL,
            skipped_missing_canonical INTEGER NOT NULL,
            skipped_artist_canonical INTEGER NOT NULL,
            rejected_rows INTEGER NOT NULL,
            duplicate_rows INTEGER NOT NULL,
            conflict_rows INTEGER NOT NULL,
            UNIQUE(source_name, revision, sha256)
        )
        """
    )


def _alias_hygiene_counts(
    connection: sqlite3.Connection, source_metadata: AliasSourceMetadata
) -> Dict[str, int]:
    if not _alias_table_exists(connection):
        return {
            "existing_artist_aliases": 0,
            "existing_missing_canonical_aliases": 0,
            "source_artist_aliases": 0,
            "source_missing_canonical_aliases": 0,
        }
    source_name = source_metadata.source_name.strip()
    return {
        "existing_artist_aliases": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM tag_aliases a
                CROSS JOIN hot_tags h ON h.tag = a.canonical_tag
                WHERE h.category = 1
                """
            ).fetchone()[0]
        ),
        "existing_missing_canonical_aliases": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM tag_aliases a
                LEFT JOIN hot_tags h ON h.tag = a.canonical_tag
                WHERE h.tag IS NULL
                """
            ).fetchone()[0]
        ),
        "source_artist_aliases": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM tag_aliases a
                CROSS JOIN hot_tags h ON h.tag = a.canonical_tag
                WHERE h.category = 1 AND a.source_name = ?
                """,
                (source_name,),
            ).fetchone()[0]
        ),
        "source_missing_canonical_aliases": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM tag_aliases a
                LEFT JOIN hot_tags h ON h.tag = a.canonical_tag
                WHERE h.tag IS NULL AND a.source_name = ?
                """,
                (source_name,),
            ).fetchone()[0]
        ),
    }


def _reject_ineligible_source_aliases(hygiene: Mapping[str, int]) -> None:
    artists = int(hygiene["source_artist_aliases"])
    missing = int(hygiene["source_missing_canonical_aliases"])
    if artists or missing:
        raise AliasTargetDatabaseError(
            "existing aliases from the pinned source are ineligible "
            "(artist={}, missing_canonical={}); refusing to report success".format(
                artists, missing
            )
        )


def _has_prior_import(
    connection: sqlite3.Connection, source_metadata: AliasSourceMetadata
) -> bool:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='tag_alias_imports'"
    ).fetchone()
    if not exists:
        return False
    return connection.execute(
        """
        SELECT 1 FROM tag_alias_imports
        WHERE source_name = ? AND revision = ? AND sha256 = ?
        LIMIT 1
        """,
        (
            source_metadata.source_name.strip(),
            source_metadata.revision.strip(),
            source_metadata.expected_sha256.strip().casefold(),
        ),
    ).fetchone() is not None


def _target_counts(
    connection: sqlite3.Connection,
    source_metadata: AliasSourceMetadata,
    *,
    include_existing_aliases: bool,
) -> Dict[str, int]:
    staged = int(
        connection.execute(
            "SELECT COUNT(*) FROM stagepack.staged_aliases"
        ).fetchone()[0]
    )
    eligible = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM stagepack.staged_aliases s
            JOIN hot_tags h ON h.tag = s.canonical_tag
            WHERE h.category != 1
            """
        ).fetchone()[0]
    )
    missing = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM stagepack.staged_aliases s
            LEFT JOIN hot_tags h ON h.tag = s.canonical_tag
            WHERE h.tag IS NULL
            """
        ).fetchone()[0]
    )
    artists = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM stagepack.staged_aliases s
            JOIN hot_tags h ON h.tag = s.canonical_tag
            WHERE h.category = 1
            """
        ).fetchone()[0]
    )
    if not include_existing_aliases:
        return {
            "staged_aliases": staged,
            "eligible_aliases": eligible,
            "would_insert_aliases": eligible,
            "would_update_aliases": 0,
            "would_preserve_aliases": 0,
            "skipped_missing_canonical": missing,
            "skipped_artist_canonical": artists,
        }

    parameters = (
        source_metadata.source_name.strip(),
        source_metadata.source_url.strip(),
        source_metadata.license.strip(),
        source_metadata.revision.strip(),
        source_metadata.expected_sha256.strip().casefold(),
    )
    inserted = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM stagepack.staged_aliases s
            JOIN hot_tags h ON h.tag = s.canonical_tag AND h.category != 1
            LEFT JOIN tag_aliases a ON a.alias = s.alias
            WHERE a.alias IS NULL
            """
        ).fetchone()[0]
    )
    updated = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM stagepack.staged_aliases s
            JOIN hot_tags h ON h.tag = s.canonical_tag AND h.category != 1
            JOIN tag_aliases a ON a.alias = s.alias
            WHERE a.canonical_tag != s.canonical_tag
               OR a.relation_type != 'official_alias'
               OR a.source_name != ? OR a.source_url != ?
               OR a.declared_license != ? OR a.source_revision != ?
               OR a.source_sha256 != ?
            """,
            parameters,
        ).fetchone()[0]
    )
    preserved = eligible - inserted - updated
    return {
        "staged_aliases": staged,
        "eligible_aliases": eligible,
        "would_insert_aliases": inserted,
        "would_update_aliases": updated,
        "would_preserve_aliases": int(preserved),
        "skipped_missing_canonical": missing,
        "skipped_artist_canonical": artists,
    }


def _inspect_target(
    db_path: Path,
    stage_db_path: Path,
    source_metadata: AliasSourceMetadata,
) -> Dict[str, object]:
    if not db_path.is_file():
        raise AliasTargetDatabaseError("target database does not exist")
    connection = _connect_readonly(db_path)
    try:
        _validate_hot_tags_schema(connection)
        _validate_alias_schema(connection)
        integrity = _integrity_result(connection)
        if integrity != "ok":
            raise AliasTargetDatabaseError(
                "target integrity_check failed: {}".format(integrity)
            )
        has_alias_table = _alias_table_exists(connection)
        connection.execute(
            "ATTACH DATABASE ? AS stagepack", (_readonly_uri(stage_db_path),)
        )
        try:
            counts = _target_counts(
                connection,
                source_metadata,
                include_existing_aliases=has_alias_table,
            )
        finally:
            connection.execute("DETACH DATABASE stagepack")
        return {
            "integrity": integrity,
            "hot_tags": int(
                connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0]
            ),
            "tag_aliases": int(
                connection.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
            ) if has_alias_table else 0,
            "alias_table_exists": has_alias_table,
            "already_imported": _has_prior_import(connection, source_metadata),
            **_alias_hygiene_counts(connection, source_metadata),
            **counts,
        }
    finally:
        connection.close()


def _reserve_unique_backup_path(
    db_path: Path,
    backup_dir: Optional[Path],
    sha256: str,
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> Path:
    destination_dir = (backup_dir or db_path.parent).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = db_path.suffix or ".db"
    counter = 0
    while True:
        if counter:
            filename = "{}.pre_tag_aliases_{}_{}_{}{}".format(
                db_path.stem, timestamp, sha256[:12], counter, suffix
            )
        else:
            filename = "{}.pre_tag_aliases_{}_{}{}".format(
                db_path.stem, timestamp, sha256[:12], suffix
            )
        candidate = destination_dir / filename
        if any(
            _paths_refer_to_same_file(candidate, protected)
            for _name, protected in protected_paths
        ):
            counter += 1
            continue
        try:
            descriptor = os.open(
                str(candidate),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.close(descriptor)
            try:
                _validate_distinct_paths(
                    [("backup", candidate), *protected_paths]
                )
            except Exception:
                candidate.unlink(missing_ok=True)
                raise
            return candidate
        except FileExistsError:
            counter += 1


def _online_backup(db_path: Path, backup_path: Path) -> None:
    source = None
    destination = None
    completed = False
    try:
        source = _connect_readonly(db_path)
        destination = sqlite3.connect(str(backup_path))
        source.backup(destination)
        destination.commit()
        integrity = _integrity_result(destination)
        if integrity != "ok":
            raise AliasTargetDatabaseError(
                "backup integrity_check failed: {}".format(integrity)
            )
        completed = True
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        if not completed:
            try:
                backup_path.unlink()
            except FileNotFoundError:
                pass


def _copy_stage(
    stage_db_path: Path,
    destination: Path,
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    destination = destination.resolve()
    _validate_distinct_paths([("staging", destination), *protected_paths])
    if destination.exists():
        raise AliasImportValidationError(
            "staging destination already exists; refusing to overwrite it"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(stage_db_path))
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
        target.commit()
        if _integrity_result(target) != "ok":
            raise AliasTargetDatabaseError("staging database integrity check failed")
    finally:
        target.close()
        source.close()


def _hot_tags_difference_count(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT * FROM (
                    SELECT * FROM hot_tags
                    EXCEPT
                    SELECT * FROM hot_tags_before_alias_import
                )
                UNION ALL
                SELECT * FROM (
                    SELECT * FROM hot_tags_before_alias_import
                    EXCEPT
                    SELECT * FROM hot_tags
                )
            )
            """
        ).fetchone()[0]
    )


def _apply_import(
    db_path: Path,
    stage_db_path: Path,
    input_path: Path,
    backup_dir: Optional[Path],
    source_metadata: AliasSourceMetadata,
    stage_report: Mapping[str, object],
    *,
    force: bool,
    protected_artifact_paths: Sequence[Tuple[str, Path]] = (),
) -> Dict[str, object]:
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    imported_epoch = int(datetime.now(timezone.utc).timestamp())
    connection = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("ATTACH DATABASE ? AS stagepack", (str(stage_db_path),))
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            _validate_hot_tags_schema(connection)
            _validate_alias_schema(connection)
            _reject_ineligible_source_aliases(
                _alias_hygiene_counts(connection, source_metadata)
            )
            if not force and _has_prior_import(connection, source_metadata):
                connection.execute("ROLLBACK")
                return {"already_imported": True}

            # The RESERVED write lock is held from before this online backup
            # until COMMIT/ROLLBACK. A separate read connection can still
            # create the backup, while no competing writer can enter the gap.
            backup_path = _reserve_unique_backup_path(
                db_path,
                backup_dir,
                source_metadata.expected_sha256.strip().casefold(),
                protected_paths=[
                    ("database", db_path),
                    ("input", input_path),
                    ("internal_stage", stage_db_path),
                    *protected_artifact_paths,
                ],
            )
            _online_backup(db_path, backup_path)
            _create_alias_schema(connection)
            _create_provenance_schema(connection)

            connection.execute(
                "CREATE TEMP TABLE hot_tags_before_alias_import AS "
                "SELECT * FROM hot_tags"
            )
            hot_count_before = int(
                connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0]
            )
            alias_count_before = int(
                connection.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
            )
            counts = _target_counts(
                connection, source_metadata, include_existing_aliases=True
            )

            connection.execute(
                """
                INSERT INTO tag_aliases(
                    alias, canonical_tag, relation_type, source_name, source_url,
                    declared_license, source_revision, source_sha256, imported_at
                )
                SELECT s.alias, s.canonical_tag, 'official_alias', ?, ?, ?, ?, ?, ?
                FROM stagepack.staged_aliases s
                JOIN hot_tags h ON h.tag = s.canonical_tag
                WHERE h.category != 1
                ON CONFLICT(alias) DO UPDATE SET
                    canonical_tag = excluded.canonical_tag,
                    relation_type = excluded.relation_type,
                    source_name = excluded.source_name,
                    source_url = excluded.source_url,
                    declared_license = excluded.declared_license,
                    source_revision = excluded.source_revision,
                    source_sha256 = excluded.source_sha256,
                    imported_at = excluded.imported_at
                WHERE tag_aliases.canonical_tag != excluded.canonical_tag
                   OR tag_aliases.relation_type != excluded.relation_type
                   OR tag_aliases.source_name != excluded.source_name
                   OR tag_aliases.source_url != excluded.source_url
                   OR tag_aliases.declared_license != excluded.declared_license
                   OR tag_aliases.source_revision != excluded.source_revision
                   OR tag_aliases.source_sha256 != excluded.source_sha256
                """,
                (
                    source_metadata.source_name.strip(),
                    source_metadata.source_url.strip(),
                    source_metadata.license.strip(),
                    source_metadata.revision.strip(),
                    source_metadata.expected_sha256.strip().casefold(),
                    imported_epoch,
                ),
            )

            hot_count_after = int(
                connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0]
            )
            hot_differences = _hot_tags_difference_count(connection)
            if hot_count_after != hot_count_before or hot_differences != 0:
                raise AliasTargetDatabaseError(
                    "hot_tags changed during alias import; transaction rolled back"
                )
            alias_count_after = int(
                connection.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
            )
            hygiene_after = _alias_hygiene_counts(connection, source_metadata)
            _reject_ineligible_source_aliases(hygiene_after)
            expected_aliases = alias_count_before + int(
                counts["would_insert_aliases"]
            )
            if alias_count_after != expected_aliases:
                raise AliasTargetDatabaseError(
                    "alias row count invariant failed: expected {}, got {}".format(
                        expected_aliases, alias_count_after
                    )
                )

            integrity = _integrity_result(connection)
            if integrity != "ok":
                raise AliasTargetDatabaseError(
                    "post-import integrity_check failed: {}".format(integrity)
                )

            connection.execute(
                """
                INSERT INTO tag_alias_imports(
                    source_name, source_url, declared_license, revision, sha256,
                    input_filename, imported_at_utc, input_rows, staged_rows,
                    eligible_rows, inserted_aliases, updated_aliases,
                    preserved_aliases, skipped_missing_canonical,
                    skipped_artist_canonical, rejected_rows, duplicate_rows,
                    conflict_rows
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_name, revision, sha256) DO UPDATE SET
                    source_url = excluded.source_url,
                    declared_license = excluded.declared_license,
                    input_filename = excluded.input_filename,
                    imported_at_utc = excluded.imported_at_utc,
                    input_rows = excluded.input_rows,
                    staged_rows = excluded.staged_rows,
                    eligible_rows = excluded.eligible_rows,
                    inserted_aliases = excluded.inserted_aliases,
                    updated_aliases = excluded.updated_aliases,
                    preserved_aliases = excluded.preserved_aliases,
                    skipped_missing_canonical = excluded.skipped_missing_canonical,
                    skipped_artist_canonical = excluded.skipped_artist_canonical,
                    rejected_rows = excluded.rejected_rows,
                    duplicate_rows = excluded.duplicate_rows,
                    conflict_rows = excluded.conflict_rows
                """,
                (
                    source_metadata.source_name.strip(),
                    source_metadata.source_url.strip(),
                    source_metadata.license.strip(),
                    source_metadata.revision.strip(),
                    source_metadata.expected_sha256.strip().casefold(),
                    input_path.name,
                    imported_at,
                    int(stage_report["total_rows"]),
                    int(stage_report["staged_rows"]),
                    int(counts["eligible_aliases"]),
                    int(counts["would_insert_aliases"]),
                    int(counts["would_update_aliases"]),
                    int(counts["would_preserve_aliases"]),
                    int(counts["skipped_missing_canonical"]),
                    int(counts["skipped_artist_canonical"]),
                    int(stage_report["rejected_rows"]),
                    int(stage_report["duplicate_rows"]),
                    int(stage_report["duplicate_conflicts"]),
                ),
            )
            connection.execute("COMMIT")
            applied_counts = {
                "eligible_aliases": int(counts["eligible_aliases"]),
                "inserted_aliases": int(counts["would_insert_aliases"]),
                "updated_aliases": int(counts["would_update_aliases"]),
                "preserved_aliases": int(counts["would_preserve_aliases"]),
                "skipped_missing_canonical": int(
                    counts["skipped_missing_canonical"]
                ),
                "skipped_artist_canonical": int(
                    counts["skipped_artist_canonical"]
                ),
            }
            return {
                "already_imported": False,
                "backup_path": str(backup_path),
                "counts": applied_counts,
                "target_after": {
                    "integrity": integrity,
                    "hot_tags": hot_count_after,
                    "hot_tags_changed": False,
                    "tag_aliases": alias_count_after,
                    **hygiene_after,
                },
                "imported_at_utc": imported_at,
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


def import_alias_pack(
    input_path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    mode: str = "dry-run",
    staging_db: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    force: bool = False,
    max_reject_ratio: float = DEFAULT_MAX_REJECT_RATIO,
    allow_live_db: bool = False,
    protected_artifact_paths: Sequence[Path] = (),
) -> Dict[str, object]:
    """Verify, stage, inspect, and optionally apply the pinned alias snapshot."""
    if mode not in {"dry-run", "stage", "apply"}:
        raise AliasImportValidationError("mode must be dry-run, stage, or apply")
    if not 0.0 <= max_reject_ratio <= 1.0:
        raise AliasImportValidationError("max_reject_ratio must be between 0 and 1")
    if mode == "stage" and staging_db is None:
        raise AliasImportValidationError("stage mode requires a staging_db path")

    resolved_input = Path(input_path).resolve()
    resolved_db = Path(db_path).resolve()
    if mode == "apply" and resolved_db == DEFAULT_DB_PATH.resolve() and not allow_live_db:
        raise AliasImportValidationError(
            "refusing to apply to the plugin live database without allow_live_db=True"
        )
    named_protected_artifacts = [
        ("protected_artifact_{}".format(index), Path(path).resolve())
        for index, path in enumerate(protected_artifact_paths)
    ]
    named_paths = [
        ("input", resolved_input),
        ("database", resolved_db),
        *named_protected_artifacts,
    ]
    if mode == "stage" and staging_db is not None:
        named_paths.append(("staging", Path(staging_db).resolve()))
    _validate_distinct_paths(named_paths)
    # Deliberately not a caller argument: production callers cannot substitute
    # a different URL, license, revision, size, or hash from the command line
    # or Python API.
    source_metadata = FIXED_SOURCE
    with tempfile.TemporaryDirectory(prefix="tag-alias-stage-") as temp_dir:
        verified_source_path = Path(temp_dir) / "verified-source.csv"
        source_report = _verify_source(
            resolved_input, verified_source_path, source_metadata
        )
        stage_path = Path(temp_dir) / "aliases.stage.sqlite"
        stage_report = _stage_csv(
            verified_source_path,
            stage_path,
            source_report,
            max_reject_ratio=max_reject_ratio,
        )
        report: Dict[str, object] = {
            "status": mode,
            "source": source_report,
            "stage": stage_report,
            "staging_path": None,
            "target_before": None,
            "backup_path": None,
        }

        if mode == "stage":
            destination = Path(staging_db).resolve()
            _copy_stage(
                stage_path,
                destination,
                protected_paths=[
                    ("input", resolved_input),
                    ("database", resolved_db),
                    *named_protected_artifacts,
                ],
            )
            report["status"] = "staged"
            report["staging_path"] = str(destination)
            return report

        target_before = _inspect_target(
            resolved_db, stage_path, source_metadata
        )
        report["target_before"] = target_before
        if mode == "dry-run":
            report["status"] = "dry_run"
            return report
        if bool(target_before["already_imported"]) and not force:
            _reject_ineligible_source_aliases(target_before)
            report["status"] = "already_imported"
            return report

        apply_report = _apply_import(
            resolved_db,
            stage_path,
            resolved_input,
            Path(backup_dir).resolve() if backup_dir else None,
            source_metadata,
            stage_report,
            force=force,
            protected_artifact_paths=named_protected_artifacts,
        )
        if bool(apply_report.get("already_imported")):
            report["status"] = "already_imported"
        else:
            report["status"] = "imported"
            report["backup_path"] = apply_report["backup_path"]
            report.update(
                {
                    "counts": apply_report["counts"],
                    "target_after": apply_report["target_after"],
                    "imported_at_utc": apply_report["imported_at_utc"],
                }
            )
        return report


def _validate_report_destination(
    output: Path, protected_paths: Sequence[Optional[Path]]
) -> Path:
    destination = Path(output).resolve()
    protected = {
        Path(path).resolve()
        for path in protected_paths
        if path is not None
    }
    if destination in protected:
        raise AliasImportValidationError(
            "json_report must not be the input, target, staging, or backup file"
        )
    for protected_path in protected:
        if _paths_refer_to_same_file(destination, protected_path):
            raise AliasImportValidationError(
                "json_report must not be a hard link to the input, target, "
                "staging, or backup file"
            )
    if destination.exists():
        raise AliasImportValidationError(
            "json_report already exists; refusing to overwrite it"
        )
    return destination


def _write_report(
    report: Mapping[str, object],
    output: Optional[Path],
    *,
    protected_paths: Sequence[Optional[Path]] = (),
) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        destination = _validate_report_destination(output, protected_paths)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                str(destination),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            raise AliasImportValidationError(
                "json_report appeared concurrently; refusing to overwrite it"
            )
    print(rendered)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and import the pinned licensed Danbooru alias snapshot"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--mode", choices=("dry-run", "stage", "apply"), default="dry-run"
    )
    parser.add_argument("--staging-db", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument(
        "--allow-live-db",
        action="store_true",
        help="second confirmation required when --mode apply targets the plugin live database",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--max-reject-ratio", type=float, default=DEFAULT_MAX_REJECT_RATIO
    )
    parser.add_argument("--json-report", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    initial_protected = [arguments.input, arguments.db, arguments.staging_db]
    try:
        if arguments.json_report:
            _validate_report_destination(
                arguments.json_report, initial_protected
            )
        report = import_alias_pack(
            arguments.input,
            arguments.db,
            mode=arguments.mode,
            staging_db=arguments.staging_db,
            backup_dir=arguments.backup_dir,
            force=arguments.force,
            max_reject_ratio=arguments.max_reject_ratio,
            allow_live_db=arguments.allow_live_db,
            protected_artifact_paths=(
                [arguments.json_report] if arguments.json_report else []
            ),
        )
        dynamic_protected = initial_protected + [
            Path(report["backup_path"])
            if report.get("backup_path")
            else None,
            Path(report["staging_path"])
            if report.get("staging_path")
            else None,
        ]
        _write_report(
            report,
            arguments.json_report,
            protected_paths=dynamic_protected,
        )
        return 0
    except AliasImportError as exc:
        _write_report(
            {"status": "error", "error": exc.code, "message": str(exc)},
            None,
        )
        return 2
    except Exception as exc:
        _write_report(
            {"status": "error", "error": "unexpected_error", "message": str(exc)},
            None,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
