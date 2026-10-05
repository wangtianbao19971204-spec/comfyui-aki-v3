from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Sequence


FINGERPRINT_VERSION = "sqlite-logical-v1"


def _encode_value(value: Any) -> bytes:
    if value is None:
        payload = b""
        type_marker = b"n"
    elif isinstance(value, int):
        payload = str(value).encode("ascii")
        type_marker = b"i"
    elif isinstance(value, float):
        payload = value.hex().encode("ascii")
        type_marker = b"f"
    elif isinstance(value, str):
        payload = value.encode("utf-8")
        type_marker = b"s"
    elif isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        type_marker = b"b"
    else:  # pragma: no cover - sqlite3 only returns the types above by default.
        raise TypeError(f"unsupported SQLite value type: {type(value).__name__}")
    return type_marker + len(payload).to_bytes(8, "big") + payload


def _encode_row(row: Sequence[Any]) -> bytes:
    return len(row).to_bytes(8, "big") + b"".join(
        _encode_value(value) for value in row
    )


def _update_record(digest: Any, marker: bytes, payload: bytes) -> None:
    digest.update(marker)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def logical_fingerprint(connection: sqlite3.Connection) -> dict:
    """Hash schema and table contents without depending on SQLite page layout.

    Rows are encoded with their SQLite result types and sorted as byte strings, so
    VACUUM, WAL checkpoints, page allocation, and unordered scan order do not alter
    the fingerprint. Duplicate rows remain significant. SQLite's schema objects and
    user/application version pragmas are included as logical database state.
    """

    schema_rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        ORDER BY type, name, tbl_name, COALESCE(sql, '')
        """
    ).fetchall()
    schema_digest = hashlib.sha256()
    for row in schema_rows:
        _update_record(schema_digest, b"S", _encode_row(row))

    table_names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name"
        )
    ]
    table_fingerprints = []
    for table_name in table_names:
        quoted_name = '"' + table_name.replace('"', '""') + '"'
        encoded_rows = [
            _encode_row(row)
            for row in connection.execute(f"SELECT * FROM {quoted_name}")
        ]
        encoded_rows.sort()
        table_digest = hashlib.sha256()
        for encoded_row in encoded_rows:
            _update_record(table_digest, b"R", encoded_row)
        table_fingerprints.append(
            {
                "name": table_name,
                "rowCount": len(encoded_rows),
                "sha256": table_digest.hexdigest(),
            }
        )

    pragmas = {
        "applicationId": int(connection.execute("PRAGMA application_id").fetchone()[0]),
        "userVersion": int(connection.execute("PRAGMA user_version").fetchone()[0]),
    }
    database_digest = hashlib.sha256()
    _update_record(database_digest, b"V", FINGERPRINT_VERSION.encode("ascii"))
    _update_record(database_digest, b"S", schema_digest.digest())
    _update_record(
        database_digest,
        b"P",
        json.dumps(pragmas, sort_keys=True, separators=(",", ":")).encode("ascii"),
    )
    for table in table_fingerprints:
        _update_record(database_digest, b"T", table["name"].encode("utf-8"))
        _update_record(database_digest, b"C", str(table["rowCount"]).encode("ascii"))
        _update_record(database_digest, b"H", bytes.fromhex(table["sha256"]))

    return {
        "version": FINGERPRINT_VERSION,
        "algorithm": "sha256",
        "sha256": database_digest.hexdigest(),
        "schemaSha256": schema_digest.hexdigest(),
        "pragmas": pragmas,
        "tables": table_fingerprints,
    }


def create_snapshot(source_path: Path, destination_path: Path) -> dict:
    source = source_path.expanduser().resolve()
    destination = destination_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source SQLite database not found: {source}")
    if source == destination:
        raise ValueError("source and destination SQLite databases must differ")
    if destination.exists():
        raise FileExistsError(f"destination SQLite database already exists: {destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(
            f"destination directory does not exist: {destination.parent}"
        )

    source_uri = "file:" + source.as_posix() + "?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.execute("PRAGMA query_only = ON")
        source_connection.backup(destination_connection)
        quick_check_rows = destination_connection.execute("PRAGMA quick_check").fetchall()
        if quick_check_rows != [("ok",)]:
            raise RuntimeError(
                f"isolated tag database quick_check failed: {quick_check_rows!r}"
            )
        table_count = destination_connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
        fingerprint = logical_fingerprint(destination_connection)
        return {
            "status": "ok",
            "source": str(source),
            "destination": str(destination),
            "quickCheck": "ok",
            "tableCount": int(table_count),
            "logicalFingerprint": fingerprint,
        }
    finally:
        destination_connection.close()
        source_connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and quick-check an isolated SQLite backup snapshot."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = create_snapshot(args.source, args.destination)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
