#!/usr/bin/env python3
"""Build and audit a no-clobber staging DB for a reviewed translation pack.

This tool is deliberately unable to target Gallery's live ``tags_cache.db``.
It copies a named baseline through SQLite's backup API into a newly-created,
versioned output directory, invokes the normal translation importer against
that copy, and then verifies the database and runtime autocomplete contracts.

It is intended for the last rehearsal before a separately-authorized live
import.  Running it never starts or stops ComfyUI.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LIVE_DB_PATH = (PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db").resolve()
IMPORTER_PATH = Path(__file__).resolve().with_name("import_tag_translations.py")
ALLOWED_CATEGORIES = frozenset((0, 3, 4, 5))
ARTIST_CATEGORY = 1
DEFAULT_EXPECTED_HOT_TAGS = 69_312
DEFAULT_EXPECTED_ARTIST_TRANSLATED = 0
SAMPLE_LIMIT = 5


class PreflightError(RuntimeError):
    """Raised when a staging-delivery invariant is not satisfied."""


@dataclass(frozen=True)
class PackRow:
    tag: str
    category: int
    post_count: int
    translation_cn: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _same_existing_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError, ValueError):
        return False


def _read_pack(path: Path) -> List[PackRow]:
    rows: List[PackRow] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"tag", "category", "post_count", "translation_cn"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise PreflightError(
                "translation pack is missing columns: {}".format(
                    ", ".join(sorted(missing))
                )
            )
        for line_number, raw in enumerate(reader, start=2):
            tag = str(raw.get("tag") or "").strip().casefold().replace(" ", "_")
            translation = str(raw.get("translation_cn") or "").strip()
            try:
                category = int(str(raw.get("category") or ""))
                post_count = int(str(raw.get("post_count") or ""))
            except ValueError as exc:
                raise PreflightError(
                    f"invalid category/post_count at CSV line {line_number}"
                ) from exc
            if not tag or not translation:
                raise PreflightError(f"blank tag/translation at CSV line {line_number}")
            if tag in seen:
                raise PreflightError(f"duplicate tag in translation pack: {tag}")
            if category not in ALLOWED_CATEGORIES:
                raise PreflightError(
                    f"disallowed category {category} for translation pack tag {tag}"
                )
            seen.add(tag)
            rows.append(PackRow(tag, category, post_count, translation))
    if not rows:
        raise PreflightError("translation pack has no data rows")
    return rows


def _readonly_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


@contextmanager
def _readonly_connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(_readonly_uri(path), uri=True, timeout=30.0)
    try:
        connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        connection.close()


def _scalar(connection: sqlite3.Connection, statement: str, params: Sequence[object] = ()) -> object:
    row = connection.execute(statement, params).fetchone()
    if row is None:
        raise PreflightError(f"query returned no row: {statement}")
    return row[0]


def _digest_rows(rows: Iterable[Sequence[object]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        rendered = json.dumps(
            list(row), ensure_ascii=False, separators=(",", ":"), sort_keys=False
        )
        digest.update(rendered.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _inspect_database(path: Path) -> Dict[str, object]:
    with _readonly_connection(path) as connection:
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        required = {"hot_tags", "hot_tags_fts", "hot_tags_fts_docsize"}
        missing = required.difference(table_names)
        if missing:
            raise PreflightError(
                "database is missing required tables: {}".format(
                    ", ".join(sorted(missing))
                )
            )
        integrity = str(_scalar(connection, "PRAGMA integrity_check"))
        quick_check = str(_scalar(connection, "PRAGMA quick_check"))
        hot_tags = int(_scalar(connection, "SELECT COUNT(*) FROM hot_tags"))
        translated = int(
            _scalar(
                connection,
                "SELECT COUNT(*) FROM hot_tags "
                "WHERE NULLIF(TRIM(translation_cn), '') IS NOT NULL",
            )
        )
        artist_translated = int(
            _scalar(
                connection,
                "SELECT COUNT(*) FROM hot_tags WHERE category = ? "
                "AND NULLIF(TRIM(translation_cn), '') IS NOT NULL",
                (ARTIST_CATEGORY,),
            )
        )
        fts_rows = int(_scalar(connection, "SELECT COUNT(*) FROM hot_tags_fts_docsize"))
        identity_digest = _digest_rows(
            connection.execute(
                "SELECT tag, category, post_count, COALESCE(aliases, '') "
                "FROM hot_tags ORDER BY tag"
            )
        )
        existing_translation_digest = _digest_rows(
            connection.execute(
                "SELECT tag, translation_cn FROM hot_tags "
                "WHERE NULLIF(TRIM(translation_cn), '') IS NOT NULL ORDER BY tag"
            )
        )
        return {
            "integrity_check": integrity,
            "quick_check": quick_check,
            "hot_tags": hot_tags,
            "translated": translated,
            "artist_translated": artist_translated,
            "fts_rows": fts_rows,
            "identity_sha256": identity_digest,
            "existing_translation_sha256": existing_translation_digest,
        }


def _pack_state(path: Path, pack: Sequence[PackRow]) -> Dict[str, object]:
    wanted = {row.tag: row for row in pack}
    found: Dict[str, Tuple[int, int, Optional[str]]] = {}
    with _readonly_connection(path) as connection:
        tags = list(wanted)
        for offset in range(0, len(tags), 500):
            batch = tags[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            statement = (
                "SELECT tag, category, post_count, translation_cn FROM hot_tags "
                f"WHERE tag IN ({placeholders})"
            )
            for tag, category, post_count, translation in connection.execute(
                statement, batch
            ):
                found[str(tag)] = (
                    int(category),
                    int(post_count),
                    None if translation is None else str(translation),
                )

    missing = sorted(set(wanted).difference(found))
    category_mismatches = []
    post_count_mismatches = []
    already_translated = []
    for tag, expected in wanted.items():
        actual = found.get(tag)
        if actual is None:
            continue
        if actual[0] != expected.category:
            category_mismatches.append(
                {"tag": tag, "expected": expected.category, "actual": actual[0]}
            )
        if actual[1] != expected.post_count:
            post_count_mismatches.append(
                {"tag": tag, "expected": expected.post_count, "actual": actual[1]}
            )
        if str(actual[2] or "").strip():
            already_translated.append({"tag": tag, "translation_cn": actual[2]})
    return {
        "pack_rows": len(pack),
        "found_rows": len(found),
        "missing": missing,
        "category_mismatches": category_mismatches,
        "post_count_mismatches": post_count_mismatches,
        "already_translated": already_translated,
    }


def _copy_sqlite_snapshot(source: Path, destination: Path) -> Dict[str, object]:
    if destination.exists():
        raise PreflightError(f"staging database already exists: {destination}")
    source_hash_before = _sha256_file(source)
    source_connection = sqlite3.connect(_readonly_uri(source), uri=True, timeout=30.0)
    destination_connection = sqlite3.connect(str(destination), timeout=30.0)
    try:
        source_connection.execute("PRAGMA query_only = ON")
        source_connection.backup(destination_connection)
        destination_connection.commit()
        quick_check = str(_scalar(destination_connection, "PRAGMA quick_check"))
        if quick_check != "ok":
            raise PreflightError(f"staging snapshot quick_check failed: {quick_check}")
    finally:
        destination_connection.close()
        source_connection.close()
    source_hash_after = _sha256_file(source)
    if source_hash_before != source_hash_after:
        raise PreflightError("baseline database bytes changed while making staging snapshot")
    return {
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "destination_sha256": _sha256_file(destination),
        "quick_check": quick_check,
    }


def _load_importer():
    spec = importlib.util.spec_from_file_location(
        "gallery_preflight_translation_importer", IMPORTER_PATH
    )
    if spec is None or spec.loader is None:
        raise PreflightError(f"could not load importer: {IMPORTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _temporary_environment(updates: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _runtime_autocomplete_checks(
    database: Path, samples: Sequence[PackRow], log_dir: Path
) -> List[Dict[str, object]]:
    log_dir.mkdir(parents=True, exist_ok=True)
    sample_payload = [
        {"tag": row.tag, "translation_cn": row.translation_cn} for row in samples
    ]
    child_source = r'''
import asyncio
import json
import sys
from py.shared.db.db_manager import TagDatabaseManager

async def main():
    database = sys.argv[1]
    samples = json.loads(sys.argv[2])
    manager = TagDatabaseManager(database)
    results = []
    try:
        for sample in samples:
            tag = sample["tag"]
            translation = sample["translation_cn"]
            english_rows = await manager.search_tags_by_prefix(tag, 10)
            chinese_rows = await manager.search_tags_optimized(
                translation, 10, search_type="chinese"
            )
            english_match = next(
                (row for row in english_rows if row.get("tag") == tag), None
            )
            chinese_match = next(
                (row for row in chinese_rows if row.get("tag") == tag), None
            )
            results.append({
                "tag": tag,
                "translation_cn": translation,
                "english_query": tag,
                "english_match": bool(
                    english_match and english_match.get("translation_cn") == translation
                ),
                "chinese_query": translation,
                "chinese_match": bool(
                    chinese_match and chinese_match.get("translation_cn") == translation
                ),
            })
    finally:
        await manager.close()
    print("__PREFLIGHT_JSON__" + json.dumps(results, ensure_ascii=False))

asyncio.run(main())
'''
    child_environment = os.environ.copy()
    child_environment["DANBOORU_GALLERY_LOG_DIR"] = str(log_dir)
    for key in (
        "DANBOORU_GALLERY_DELIVERY_TEST",
        "DANBOORU_GALLERY_TEST_CONFIG",
        "DANBOORU_GALLERY_TAG_DB_PATH",
    ):
        child_environment.pop(key, None)
    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-c",
            child_source,
            str(database),
            json.dumps(sample_payload, ensure_ascii=False),
        ],
        cwd=str(PLUGIN_ROOT),
        env=child_environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise PreflightError(
            "runtime autocomplete subprocess failed: {}".format(
                (completed.stderr or completed.stdout).strip()
            )
        )
    marker = "__PREFLIGHT_JSON__"
    rendered = next(
        (line[len(marker) :] for line in reversed(completed.stdout.splitlines()) if line.startswith(marker)),
        None,
    )
    if rendered is None:
        raise PreflightError("runtime autocomplete subprocess returned no JSON marker")
    try:
        parsed = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise PreflightError("runtime autocomplete subprocess returned invalid JSON") from exc
    if not isinstance(parsed, list):
        raise PreflightError("runtime autocomplete subprocess result is not a list")
    return parsed


def _fts_checks(database: Path, samples: Sequence[PackRow]) -> List[Dict[str, object]]:
    results: List[Dict[str, object]] = []
    with _readonly_connection(database) as connection:
        for sample in samples:
            phrase = '"{}"'.format(sample.translation_cn.replace('"', '""'))
            matches = int(
                _scalar(
                    connection,
                    "SELECT COUNT(*) FROM hot_tags_fts f "
                    "JOIN hot_tags h ON h.rowid = f.rowid "
                    "WHERE hot_tags_fts MATCH ? AND h.tag = ?",
                    (phrase, sample.tag),
                )
            )
            results.append(
                {
                    "tag": sample.tag,
                    "translation_cn": sample.translation_cn,
                    "fts_phrase": phrase,
                    "match": matches > 0,
                }
            )
    return results


def _verify_pack_values(database: Path, pack: Sequence[PackRow]) -> Dict[str, object]:
    expected = {row.tag: row.translation_cn for row in pack}
    actual: Dict[str, Optional[str]] = {}
    with _readonly_connection(database) as connection:
        tags = list(expected)
        for offset in range(0, len(tags), 500):
            batch = tags[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            for tag, translation in connection.execute(
                "SELECT tag, translation_cn FROM hot_tags "
                f"WHERE tag IN ({placeholders})",
                batch,
            ):
                actual[str(tag)] = None if translation is None else str(translation)
    mismatches = [
        {"tag": tag, "expected": translation, "actual": actual.get(tag)}
        for tag, translation in expected.items()
        if actual.get(tag) != translation
    ]
    return {
        "expected_rows": len(expected),
        "matched_rows": len(expected) - len(mismatches),
        "mismatches": mismatches,
    }


def _verify_existing_translations_unchanged(
    baseline: Path, staging: Path
) -> Dict[str, object]:
    with _readonly_connection(baseline) as connection:
        expected = {
            str(tag): str(translation)
            for tag, translation in connection.execute(
                "SELECT tag, translation_cn FROM hot_tags "
                "WHERE NULLIF(TRIM(translation_cn), '') IS NOT NULL"
            )
        }
    actual: Dict[str, Optional[str]] = {}
    tags = list(expected)
    with _readonly_connection(staging) as connection:
        for offset in range(0, len(tags), 500):
            batch = tags[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            for tag, translation in connection.execute(
                "SELECT tag, translation_cn FROM hot_tags "
                f"WHERE tag IN ({placeholders})",
                batch,
            ):
                actual[str(tag)] = None if translation is None else str(translation)
    mismatches = [
        {"tag": tag, "expected": translation, "actual": actual.get(tag)}
        for tag, translation in expected.items()
        if actual.get(tag) != translation
    ]
    return {
        "baseline_nonempty_rows": len(expected),
        "unchanged_rows": len(expected) - len(mismatches),
        "mismatches": mismatches,
    }


def _assert_database_metrics(
    metrics: Mapping[str, object], expected_hot_tags: int, expected_artist_translated: int
) -> None:
    failures = []
    if metrics.get("integrity_check") != "ok":
        failures.append(f"integrity_check={metrics.get('integrity_check')}")
    if metrics.get("quick_check") != "ok":
        failures.append(f"quick_check={metrics.get('quick_check')}")
    if int(metrics.get("hot_tags", -1)) != expected_hot_tags:
        failures.append(
            f"hot_tags={metrics.get('hot_tags')} expected={expected_hot_tags}"
        )
    if int(metrics.get("artist_translated", -1)) != expected_artist_translated:
        failures.append(
            "artist_translated={} expected={}".format(
                metrics.get("artist_translated"), expected_artist_translated
            )
        )
    if int(metrics.get("fts_rows", -1)) != expected_hot_tags:
        failures.append(f"fts_rows={metrics.get('fts_rows')} expected={expected_hot_tags}")
    if failures:
        raise PreflightError("database metric audit failed: " + "; ".join(failures))


def _write_json_no_clobber(path: Path, payload: Mapping[str, object]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered)
        stream.flush()
        os.fsync(stream.fileno())


def run_preflight(
    *,
    baseline_db: Path,
    input_csv: Path,
    output_dir: Path,
    source_url: str,
    declared_license: str,
    revision: str,
    expected_hot_tags: int = DEFAULT_EXPECTED_HOT_TAGS,
    expected_artist_translated: int = DEFAULT_EXPECTED_ARTIST_TRANSLATED,
) -> Dict[str, object]:
    baseline = baseline_db.expanduser().resolve()
    source_csv = input_csv.expanduser().resolve()
    destination_dir = output_dir.expanduser().resolve()
    if baseline == LIVE_DB_PATH or _same_existing_file(baseline, LIVE_DB_PATH):
        raise PreflightError("live Gallery database is forbidden as a preflight baseline")
    if not baseline.is_file():
        raise PreflightError(f"baseline database does not exist: {baseline}")
    if not source_csv.is_file():
        raise PreflightError(f"translation pack does not exist: {source_csv}")
    if expected_hot_tags <= 0 or expected_artist_translated < 0:
        raise PreflightError("expected database counts are invalid")

    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    destination_dir.mkdir(exist_ok=False)
    staging_db = (destination_dir / "tags_cache_preflight.sqlite").resolve()
    if staging_db == LIVE_DB_PATH:
        raise PreflightError("preflight staging path resolved to the live Gallery database")

    baseline_hash_before = _sha256_file(baseline)
    csv_hash_before = _sha256_file(source_csv)
    pack = _read_pack(source_csv)
    before = _inspect_database(baseline)
    _assert_database_metrics(before, expected_hot_tags, expected_artist_translated)
    pack_before = _pack_state(baseline, pack)
    if pack_before["missing"]:
        raise PreflightError(
            f"{len(pack_before['missing'])} translation-pack tags are absent from baseline"
        )
    if pack_before["category_mismatches"]:
        raise PreflightError("translation-pack category does not match baseline")
    if pack_before["post_count_mismatches"]:
        raise PreflightError("translation-pack post_count does not match baseline")
    if pack_before["already_translated"]:
        raise PreflightError(
            f"{len(pack_before['already_translated'])} pack rows already have translations"
        )

    snapshot = _copy_sqlite_snapshot(baseline, staging_db)
    importer = _load_importer()
    import_report = importer.import_translation_pack(
        source_csv,
        staging_db,
        importer.SourceMetadata(
            source_url=source_url,
            license=declared_license,
            revision=revision,
        ),
        apply=True,
        allow_live_db=False,
        pack_format="generic",
        max_reject_ratio=0.0,
        backup_dir=destination_dir / "importer-backups",
    )
    if import_report.get("status") != "imported":
        raise PreflightError(
            f"staging importer returned status {import_report.get('status')!r}"
        )

    after = _inspect_database(staging_db)
    _assert_database_metrics(after, expected_hot_tags, expected_artist_translated)
    expected_increase = len(pack)
    actual_increase = int(after["translated"]) - int(before["translated"])
    if actual_increase != expected_increase:
        raise PreflightError(
            f"translated-row increase {actual_increase} != pack rows {expected_increase}"
        )
    if before["identity_sha256"] != after["identity_sha256"]:
        raise PreflightError("hot_tags identity/category/count/aliases changed during import")

    counts = import_report.get("counts") or {}
    if int(counts.get("inserted_tags", -1)) != 0:
        raise PreflightError("importer reported inserted tags")
    if int(counts.get("filled_translations", -1)) != expected_increase:
        raise PreflightError("importer filled_translations does not equal pack rows")
    if int(counts.get("preserved_translations", -1)) != 0:
        raise PreflightError("importer unexpectedly preserved pre-existing pack translations")
    if int(import_report.get("skipped_missing_target_tags", -1)) != 0:
        raise PreflightError("importer skipped missing target tags")
    if int(import_report.get("skipped_disallowed_target_category", -1)) != 0:
        raise PreflightError("importer skipped disallowed target categories")

    values = _verify_pack_values(staging_db, pack)
    if values["mismatches"]:
        raise PreflightError("one or more imported translations do not match the CSV")
    preserved_values = _verify_existing_translations_unchanged(baseline, staging_db)
    if preserved_values["mismatches"]:
        raise PreflightError("one or more pre-existing translations were modified")
    samples = sorted(pack, key=lambda row: (-row.post_count, row.tag))[:SAMPLE_LIMIT]
    fts_checks = _fts_checks(staging_db, samples)
    if not all(bool(item["match"]) for item in fts_checks):
        raise PreflightError("one or more imported translations are absent from FTS")
    runtime_checks = _runtime_autocomplete_checks(
        staging_db, samples, destination_dir / "logs"
    )
    if not all(
        bool(item["english_match"]) and bool(item["chinese_match"])
        for item in runtime_checks
    ):
        raise PreflightError("runtime autocomplete failed an English or Chinese sample")

    if _sha256_file(baseline) != baseline_hash_before:
        raise PreflightError("baseline database bytes changed during preflight")
    if _sha256_file(source_csv) != csv_hash_before:
        raise PreflightError("translation CSV bytes changed during preflight")

    report: Dict[str, object] = {
        "schema_version": 1,
        "status": "PASS",
        "preflight_only": True,
        "live_database_touched": False,
        "comfyui_process_started_or_stopped": False,
        "inputs": {
            "baseline_db": str(baseline),
            "baseline_sha256": baseline_hash_before,
            "translation_csv": str(source_csv),
            "translation_csv_sha256": csv_hash_before,
            "translation_rows": len(pack),
        },
        "outputs": {
            "directory": str(destination_dir),
            "staging_db": str(staging_db),
            "staging_db_sha256": _sha256_file(staging_db),
        },
        "expected": {
            "hot_tags": expected_hot_tags,
            "artist_translated": expected_artist_translated,
            "translation_increase": expected_increase,
            "fts_rows": expected_hot_tags,
        },
        "baseline": before,
        "pack_baseline_state": pack_before,
        "snapshot": snapshot,
        "importer": import_report,
        "staging": after,
        "translation_increase": actual_increase,
        "translation_values": values,
        "pre_existing_translation_values": preserved_values,
        "fts_samples": fts_checks,
        "runtime_autocomplete_samples": runtime_checks,
        "delivery_runner_review": {
            "runner": str(PLUGIN_ROOT / "tests" / "run_delivery.ps1"),
            "starts_hidden_isolated_server": True,
            "checks_listener_owned_by_started_pid": True,
            "cleanup_stops_only_started_process_after_commandline_check": True,
            "checks_started_pid_released_listener": True,
            "guards_live_db_with_before_after_logical_snapshots": True,
        },
    }
    report_path = destination_dir / "preflight_report.json"
    report["outputs"]["report"] = str(report_path)
    _write_json_no_clobber(report_path, report)
    return report


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a no-clobber staging copy, import a reviewed translation CSV, "
            "and audit SQLite, FTS, and runtime autocomplete invariants."
        )
    )
    parser.add_argument("--baseline-db", type=Path, required=True)
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="must not already exist; use a version/timestamp in its name",
    )
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--license", required=True, dest="declared_license")
    parser.add_argument("--revision", required=True)
    parser.add_argument(
        "--expected-hot-tags", type=int, default=DEFAULT_EXPECTED_HOT_TAGS
    )
    parser.add_argument(
        "--expected-artist-translated",
        type=int,
        default=DEFAULT_EXPECTED_ARTIST_TRANSLATED,
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        report = run_preflight(
            baseline_db=arguments.baseline_db,
            input_csv=arguments.input_csv,
            output_dir=arguments.output_dir,
            source_url=arguments.source_url,
            declared_license=arguments.declared_license,
            revision=arguments.revision,
            expected_hot_tags=arguments.expected_hot_tags,
            expected_artist_translated=arguments.expected_artist_translated,
        )
    except (OSError, sqlite3.Error, PreflightError) as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
