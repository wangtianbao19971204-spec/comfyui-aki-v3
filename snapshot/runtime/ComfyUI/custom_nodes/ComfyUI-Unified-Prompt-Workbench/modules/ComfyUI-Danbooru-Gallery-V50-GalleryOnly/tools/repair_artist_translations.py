#!/usr/bin/env python3
"""Audit and remove artist translations from a gallery tag database.

The command is dry-run by default.  ``--apply`` is required for every database
write, and the plugin's live database additionally requires
``--allow-live-db``.  Apply mode creates and verifies an online SQLite backup
before opening the target for writing, then performs the history insert,
artist cleanup and FTS5 rebuild in one transaction.

Examples::

    python tools/repair_artist_translations.py --db path/to/tags_cache.db
    python tools/repair_artist_translations.py --db path/to/tags_cache.db \
        --apply --backup-dir path/to/backups
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE_DB = (
    PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"
).resolve()
ARTIST_CATEGORY = 1
CHANGE_TYPE = "clear_artist_translation"
CHANGE_REASON = "Artist translations are excluded from the gallery translation layer"


class RepairError(RuntimeError):
    """Raised when a database cannot be safely audited or repaired."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _readonly_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_readonly_uri(path), uri=True, timeout=30.0)
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _integrity_result(connection: sqlite3.Connection) -> str:
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    return "\n".join(str(row[0]) for row in rows)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone() is not None


def _validate_schema(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(hot_tags)").fetchall()
    }
    missing = sorted({"tag", "category", "translation_cn"} - columns)
    if missing:
        raise RepairError(
            "hot_tags is missing required columns: {}".format(", ".join(missing))
        )

    fts_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'hot_tags_fts'"
    ).fetchone()
    fts_sql = str(fts_row[0] or "") if fts_row else ""
    if "VIRTUAL TABLE" not in fts_sql.upper() or "FTS5" not in fts_sql.upper():
        raise RepairError("hot_tags_fts is missing or is not an FTS5 virtual table")
    if not _table_exists(connection, "hot_tags_fts_docsize"):
        raise RepairError(
            "hot_tags_fts has no docsize shadow table; actual indexed-row count "
            "cannot be audited safely"
        )

    if _table_exists(connection, "tag_translation_history"):
        history_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(tag_translation_history)"
            ).fetchall()
        }
        required_history = {
            "tag",
            "category",
            "old_translation_cn",
            "new_translation_cn",
            "change_type",
            "reason",
            "run_id",
            "changed_at_utc",
        }
        missing_history = sorted(required_history - history_columns)
        if missing_history:
            raise RepairError(
                "existing tag_translation_history has an incompatible schema: {}"
                .format(", ".join(missing_history))
            )


def _history_count(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection, "tag_translation_history"):
        return 0
    return int(
        connection.execute("SELECT COUNT(*) FROM tag_translation_history").fetchone()[0]
    )


def _artist_translation_fingerprint(connection: sqlite3.Connection) -> str:
    """Hash the exact artist values so a post-backup race is detectable."""
    digest = hashlib.sha256()
    cursor = connection.execute(
        """
        SELECT tag, translation_cn
        FROM hot_tags
        WHERE category = ? AND translation_cn IS NOT NULL
        ORDER BY tag
        """,
        (ARTIST_CATEGORY,),
    )
    for tag, translation in cursor:
        for value in (str(tag), str(translation)):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def _collect_metrics(connection: sqlite3.Connection) -> Dict[str, object]:
    total_tags = int(connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0])
    translated_tags = int(
        connection.execute(
            "SELECT COUNT(*) FROM hot_tags "
            "WHERE NULLIF(TRIM(translation_cn), '') IS NOT NULL"
        ).fetchone()[0]
    )
    artist_tags = int(
        connection.execute(
            "SELECT COUNT(*) FROM hot_tags WHERE category = ?", (ARTIST_CATEGORY,)
        ).fetchone()[0]
    )
    artist_translation_values = int(
        connection.execute(
            "SELECT COUNT(*) FROM hot_tags "
            "WHERE category = ? AND translation_cn IS NOT NULL",
            (ARTIST_CATEGORY,),
        ).fetchone()[0]
    )
    artist_translated_tags = int(
        connection.execute(
            "SELECT COUNT(*) FROM hot_tags "
            "WHERE category = ? "
            "AND NULLIF(TRIM(translation_cn), '') IS NOT NULL",
            (ARTIST_CATEGORY,),
        ).fetchone()[0]
    )
    # An external-content FTS5 table proxies a plain ``COUNT(*)`` to its
    # content table, even when the index is stale.  The docsize shadow table
    # records one row per actually indexed document and makes this audit real.
    fts_rows = int(
        connection.execute("SELECT COUNT(*) FROM hot_tags_fts_docsize").fetchone()[0]
    )
    return {
        "total_tags": total_tags,
        "translated_tags": translated_tags,
        "artist_tags": artist_tags,
        "artist_translation_values": artist_translation_values,
        "artist_translated_tags": artist_translated_tags,
        "artist_translation_values_sha256": _artist_translation_fingerprint(
            connection
        ),
        "history_rows": _history_count(connection),
        "fts_rows": fts_rows,
        "fts_count_source": "hot_tags_fts_docsize",
        "fts_matches_hot_tags": fts_rows == total_tags,
        "integrity_check": _integrity_result(connection),
    }


def _inspect_database(db_path: Path) -> Dict[str, object]:
    connection = _connect_readonly(db_path)
    try:
        _validate_schema(connection)
        metrics = _collect_metrics(connection)
        if metrics["integrity_check"] != "ok":
            raise RepairError(
                "target integrity_check failed: {}".format(metrics["integrity_check"])
            )
        return metrics
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_backup_path(db_path: Path, backup_dir: Optional[Path], run_id: str) -> Path:
    destination_dir = (backup_dir or db_path.parent).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = db_path.suffix or ".sqlite"
    stem = "{}.pre_artist_translation_repair_{}_{}".format(
        db_path.stem, timestamp, run_id[-8:]
    )
    candidate = destination_dir / (stem + suffix)
    counter = 1
    while candidate.exists():
        candidate = destination_dir / "{}_{}{}".format(stem, counter, suffix)
        counter += 1
    if candidate.resolve() == db_path.resolve():
        raise RepairError("backup path resolves to the target database")
    return candidate


def _create_verified_backup(db_path: Path, backup_path: Path) -> Dict[str, str]:
    source = _connect_readonly(db_path)
    try:
        destination = sqlite3.connect(str(backup_path), timeout=30.0)
        try:
            source.backup(destination)
            destination.commit()
            integrity = _integrity_result(destination)
            if integrity != "ok":
                raise RepairError("backup integrity_check failed: {}".format(integrity))
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
        "sha256": _sha256(backup_path),
        "integrity_check": "ok",
    }


def _create_history_table(connection: sqlite3.Connection) -> None:
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
        """
        CREATE INDEX IF NOT EXISTS idx_tag_translation_history_tag
        ON tag_translation_history(tag)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tag_translation_history_run
        ON tag_translation_history(run_id)
        """
    )


def _apply_repair(
    db_path: Path,
    run_id: str,
    changed_at_utc: str,
    expected_artist_values: int,
    expected_artist_fingerprint: str,
) -> Dict[str, int]:
    connection = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        _validate_schema(connection)
        if _integrity_result(connection) != "ok":
            raise RepairError("target integrity_check failed immediately before apply")

        connection.execute("BEGIN IMMEDIATE")
        try:
            current_artist_values = int(
                connection.execute(
                    "SELECT COUNT(*) FROM hot_tags "
                    "WHERE category = ? AND translation_cn IS NOT NULL",
                    (ARTIST_CATEGORY,),
                ).fetchone()[0]
            )
            if current_artist_values != expected_artist_values:
                raise RepairError(
                    "target changed after backup: expected {} artist translation values, found {}"
                    .format(expected_artist_values, current_artist_values)
                )
            current_artist_fingerprint = _artist_translation_fingerprint(connection)
            if current_artist_fingerprint != expected_artist_fingerprint:
                raise RepairError(
                    "target artist translations changed after backup; refusing to apply"
                )

            _create_history_table(connection)
            history_cursor = connection.execute(
                """
                INSERT INTO tag_translation_history(
                    tag, category, old_translation_cn, new_translation_cn,
                    change_type, reason, run_id, changed_at_utc
                )
                SELECT tag, category, translation_cn, NULL, ?, ?, ?, ?
                FROM hot_tags
                WHERE category = ? AND translation_cn IS NOT NULL
                """,
                (
                    CHANGE_TYPE,
                    CHANGE_REASON,
                    run_id,
                    changed_at_utc,
                    ARTIST_CATEGORY,
                ),
            )
            update_cursor = connection.execute(
                """
                UPDATE hot_tags
                SET translation_cn = NULL
                WHERE category = ? AND translation_cn IS NOT NULL
                """,
                (ARTIST_CATEGORY,),
            )

            # FTS5's external-content rebuild command is atomic with the data
            # cleanup and works whether or not legacy synchronization triggers
            # were present or previously missed updates.
            connection.execute(
                "INSERT INTO hot_tags_fts(hot_tags_fts) VALUES('rebuild')"
            )

            transaction_metrics = _collect_metrics(connection)
            if transaction_metrics["artist_translation_values"] != 0:
                raise RepairError("artist translations remain after cleanup")
            if not transaction_metrics["fts_matches_hot_tags"]:
                raise RepairError("FTS row count does not match hot_tags after rebuild")
            if transaction_metrics["integrity_check"] != "ok":
                raise RepairError(
                    "post-repair integrity_check failed: {}"
                    .format(transaction_metrics["integrity_check"])
                )

            history_inserted = int(history_cursor.rowcount)
            translations_cleared = int(update_cursor.rowcount)
            if history_inserted != translations_cleared:
                raise RepairError(
                    "history/update count mismatch: {} != {}"
                    .format(history_inserted, translations_cleared)
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()

    return {
        "history_rows_inserted": history_inserted,
        "artist_translation_values_cleared": translations_cleared,
        "fts_rows_rebuilt": int(transaction_metrics["fts_rows"]),
    }


def repair_database(
    db_path: Path,
    *,
    apply: bool = False,
    allow_live_db: bool = False,
    backup_dir: Optional[Path] = None,
) -> Dict[str, object]:
    """Audit or repair ``db_path`` and return a JSON-serializable report."""
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise RepairError("database does not exist or is not a file: {}".format(db_path))
    if apply and db_path == DEFAULT_LIVE_DB and not allow_live_db:
        raise RepairError(
            "refusing to apply to the plugin live database without "
            "allow_live_db=True"
        )

    started_at = _utc_now()
    run_id = "artist-repair-{}".format(uuid.uuid4().hex)
    before = _inspect_database(db_path)
    report: Dict[str, object] = {
        "tool": "repair_artist_translations",
        "mode": "apply" if apply else "dry-run",
        "applied": False,
        "db_path": str(db_path),
        "is_plugin_live_db": db_path == DEFAULT_LIVE_DB,
        "live_apply_guard": True,
        "run_id": run_id,
        "started_at_utc": started_at,
        "backup": None,
        "before": before,
        "planned_changes": {
            "history_rows_to_insert": before["artist_translation_values"],
            "artist_translation_values_to_clear": before[
                "artist_translation_values"
            ],
            "fts_rows_to_rebuild": before["total_tags"],
        },
    }

    if not apply:
        projected_after = dict(before)
        projected_after["translated_tags"] = int(before["translated_tags"]) - int(
            before["artist_translated_tags"]
        )
        projected_after["artist_translation_values"] = 0
        projected_after["artist_translated_tags"] = 0
        projected_after["artist_translation_values_sha256"] = hashlib.sha256(
            b""
        ).hexdigest()
        projected_after["history_rows"] = int(before["history_rows"]) + int(
            before["artist_translation_values"]
        )
        projected_after["fts_rows"] = before["total_tags"]
        projected_after["fts_matches_hot_tags"] = True
        projected_after["integrity_check"] = "not_run_dry_run_projection"
        report["changes"] = {
            "history_rows_inserted": 0,
            "artist_translation_values_cleared": 0,
            "fts_rows_rebuilt": 0,
        }
        report["after"] = projected_after
        report["after_is_projection"] = True
        report["integrity"] = {
            "before": before["integrity_check"],
            "backup": None,
            "after": None,
        }
        report["completed_at_utc"] = _utc_now()
        return report

    backup_path = _unique_backup_path(db_path, backup_dir, run_id)
    backup = _create_verified_backup(db_path, backup_path)
    report["backup"] = backup
    changes = _apply_repair(
        db_path,
        run_id,
        started_at,
        int(before["artist_translation_values"]),
        str(before["artist_translation_values_sha256"]),
    )
    after = _inspect_database(db_path)
    if after["artist_translation_values"] != 0:
        raise RepairError("verification failed: artist translations remain")
    if not after["fts_matches_hot_tags"]:
        raise RepairError("verification failed: FTS row count differs from hot_tags")

    report["applied"] = True
    report["changes"] = changes
    report["after"] = after
    report["after_is_projection"] = False
    report["integrity"] = {
        "before": before["integrity_check"],
        "backup": backup["integrity_check"],
        "after": after["integrity_check"],
    }
    report["completed_at_utc"] = _utc_now()
    return report


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="SQLite database to audit")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create a verified backup and apply the repair (default: dry-run)",
    )
    parser.add_argument(
        "--allow-live-db",
        action="store_true",
        help="second confirmation required only when applying to the plugin live database",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="backup directory used only with --apply (default: database directory)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        report = repair_database(
            args.db,
            apply=bool(args.apply),
            allow_live_db=bool(args.allow_live_db),
            backup_dir=args.backup_dir,
        )
    except Exception as exc:
        error = {
            "tool": "repair_artist_translations",
            "success": False,
            "error": str(exc),
        }
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
