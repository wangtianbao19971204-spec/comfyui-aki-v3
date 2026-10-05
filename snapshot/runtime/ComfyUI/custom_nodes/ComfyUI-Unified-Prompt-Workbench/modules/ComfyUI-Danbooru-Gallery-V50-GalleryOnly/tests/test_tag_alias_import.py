from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
IMPORTER_PATH = PLUGIN_ROOT / "tools" / "import_tag_aliases.py"
ATTRIBUTION_PATH = PLUGIN_ROOT / "docs" / "TAG_ALIAS_ATTRIBUTION.md"
SPEC = importlib.util.spec_from_file_location("tag_alias_importer", IMPORTER_PATH)
assert SPEC and SPEC.loader
importer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = importer
SPEC.loader.exec_module(importer)


def _make_database(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(
            """
            CREATE TABLE hot_tags (
                tag TEXT PRIMARY KEY,
                category INTEGER NOT NULL,
                post_count INTEGER NOT NULL,
                translation_cn TEXT,
                last_updated INTEGER NOT NULL,
                aliases TEXT
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO hot_tags(
                tag, category, post_count, translation_cn, last_updated, aliases
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("general_tag", 0, 100, "通用标签", 1, '["local alias"]'),
                ("artist_tag", 1, 90, "遗留艺术家译名", 2, None),
                ("character_tag", 4, 80, "角色标签", 3, None),
            ],
        )
        connection.commit()
    finally:
        connection.close()

def _write_source(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=("alias", "tag"))
        writer.writeheader()
        writer.writerows(
            [
                {"alias": "general alias", "tag": "general tag"},
                {"alias": "artist_alias", "tag": "artist_tag"},
                {"alias": "character_alias", "tag": "character_tag"},
                {"alias": "missing_alias", "tag": "missing_tag"},
                {"alias": "general alias", "tag": "general tag"},
                {"alias": "conflict_alias", "tag": "general_tag"},
                {"alias": "conflict_alias", "tag": "character_tag"},
                {"alias": "general_tag", "tag": "general_tag"},
            ]
        )


def _metadata(path: Path, revision: str = "fixture-revision"):
    payload = path.read_bytes()
    return importer.AliasSourceMetadata(
        source_name="fixture/licensed_aliases",
        source_url="https://example.test/licensed/tag_aliases.csv",
        license="CC-BY-4.0",
        revision=revision,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_size=len(payload),
    )


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def test_pinned_source_metadata_and_attribution_are_exact():
    source = importer.FIXED_SOURCE
    assert source.source_name == "deepghs/site_tags"
    assert source.revision == "2b4de8c3f79540b10387a6fa7f251274f0b224a8"
    assert source.expected_size == 1_684_212
    assert source.expected_sha256 == (
        "a3dad50f86f4b8d117096c64ba1bd332be02b16222c587a8d2cddddf86ed852a"
    )
    assert source.license == "CC-BY-4.0"
    source.validate()

    attribution = ATTRIBUTION_PATH.read_text(encoding="utf-8")
    assert source.revision in attribution
    assert source.expected_sha256 in attribution
    assert source.source_url in attribution
    assert "CC BY 4.0" in attribution
    assert "artist" in attribution


def test_sha_mismatch_is_rejected_before_staging(tmp_path: Path, monkeypatch):
    database = tmp_path / "tags.db"
    source_path = tmp_path / "aliases.csv"
    _make_database(database)
    _write_source(source_path)
    metadata = _metadata(source_path)
    bad_metadata = importer.AliasSourceMetadata(
        source_name=metadata.source_name,
        source_url=metadata.source_url,
        license=metadata.license,
        revision=metadata.revision,
        expected_sha256="0" * 64,
        expected_size=metadata.expected_size,
    )
    monkeypatch.setattr(importer, "FIXED_SOURCE", bad_metadata)

    with pytest.raises(importer.AliasImportValidationError, match="SHA256 mismatch"):
        importer.import_alias_pack(
            source_path,
            database,
            mode="dry-run",
        )

    connection = sqlite3.connect(str(database))
    try:
        assert not _table_exists(connection, "tag_aliases")
    finally:
        connection.close()


def test_verified_snapshot_prevents_source_swap_after_hash_check(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    source_path = tmp_path / "aliases.csv"
    _make_database(database)
    _write_source(source_path)
    metadata = _metadata(source_path)
    monkeypatch.setattr(importer, "FIXED_SOURCE", metadata)
    original_stage = importer._stage_csv

    def swap_original_then_stage(verified_snapshot, *args, **kwargs):
        source_path.write_text(
            "alias,tag\nattacker_alias,artist_tag\n", encoding="utf-8"
        )
        assert Path(verified_snapshot) != source_path
        return original_stage(verified_snapshot, *args, **kwargs)

    monkeypatch.setattr(importer, "_stage_csv", swap_original_then_stage)
    report = importer.import_alias_pack(source_path, database, mode="dry-run")
    assert report["source"]["actual_sha256"] == metadata.expected_sha256
    assert report["stage"]["total_rows"] == 8
    assert report["target_before"]["eligible_aliases"] == 2


def test_json_report_cannot_overwrite_target_database(tmp_path: Path, monkeypatch):
    database = tmp_path / "tags.db"
    source_path = tmp_path / "aliases.csv"
    _make_database(database)
    _write_source(source_path)
    monkeypatch.setattr(importer, "FIXED_SOURCE", _metadata(source_path))
    before = database.read_bytes()

    exit_code = importer.main([
        "--input", str(source_path),
        "--db", str(database),
        "--mode", "dry-run",
        "--json-report", str(database),
    ])
    assert exit_code == 2
    assert database.read_bytes() == before
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_dry_run_and_explicit_staging_do_not_mutate_target(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    source_path = tmp_path / "aliases.csv"
    staging_path = tmp_path / "review" / "aliases.stage.sqlite"
    _make_database(database)
    _write_source(source_path)
    metadata = _metadata(source_path)
    monkeypatch.setattr(importer, "FIXED_SOURCE", metadata)

    dry_report = importer.import_alias_pack(
        source_path,
        database,
        mode="dry-run",
    )
    assert dry_report["status"] == "dry_run"
    assert dry_report["backup_path"] is None
    assert dry_report["stage"] == {
        "total_rows": 8,
        "candidate_rows": 7,
        "staged_rows": 4,
        "rejected_rows": 0,
        "duplicate_rows": 1,
        "duplicate_conflicts": 1,
        "skipped_self_alias": 1,
        "rejection_examples": [],
    }
    assert dry_report["target_before"]["eligible_aliases"] == 2
    assert dry_report["target_before"]["would_insert_aliases"] == 2
    assert dry_report["target_before"]["skipped_artist_canonical"] == 1
    assert dry_report["target_before"]["skipped_missing_canonical"] == 1

    stage_report = importer.import_alias_pack(
        source_path,
        database,
        mode="stage",
        staging_db=staging_path,
    )
    assert stage_report["status"] == "staged"
    assert stage_report["staging_path"] == str(staging_path.resolve())
    staged = sqlite3.connect(str(staging_path))
    try:
        assert staged.execute(
            "SELECT COUNT(*) FROM staged_aliases"
        ).fetchone()[0] == 4
        manifest = json.loads(
            staged.execute(
                "SELECT value FROM stage_metadata WHERE key='manifest'"
            ).fetchone()[0]
        )
        assert manifest["source"]["actual_sha256"] == metadata.expected_sha256
        assert manifest["stage"]["duplicate_conflicts"] == 1
    finally:
        staged.close()

    connection = sqlite3.connect(str(database))
    try:
        assert not _table_exists(connection, "tag_aliases")
        assert connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0] == 3
    finally:
        connection.close()

    with pytest.raises(
        importer.AliasImportValidationError, match="refusing to overwrite"
    ):
        importer.import_alias_pack(
            source_path,
            database,
            mode="stage",
            staging_db=staging_path,
        )


def test_apply_filters_artist_and_missing_targets_preserves_hot_tags(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    source_path = tmp_path / "aliases.csv"
    backup_dir = tmp_path / "backups"
    _make_database(database)
    _write_source(source_path)
    metadata = _metadata(source_path)
    monkeypatch.setattr(importer, "FIXED_SOURCE", metadata)
    original_backup = importer._online_backup
    lock_was_held = []

    def assert_writer_lock_then_backup(db_path, backup_path):
        competitor = sqlite3.connect(str(db_path), timeout=0.05, isolation_level=None)
        competitor.execute("PRAGMA busy_timeout = 50")
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competitor.execute("BEGIN IMMEDIATE")
            lock_was_held.append(True)
        finally:
            competitor.close()
        original_backup(db_path, backup_path)

    monkeypatch.setattr(importer, "_online_backup", assert_writer_lock_then_backup)

    before = sqlite3.connect(str(database)).execute(
        "SELECT * FROM hot_tags ORDER BY tag"
    ).fetchall()
    report = importer.import_alias_pack(
        source_path,
        database,
        mode="apply",
        backup_dir=backup_dir,
    )
    assert report["status"] == "imported"
    assert Path(report["backup_path"]).is_file()
    assert report["counts"]["eligible_aliases"] == 2
    assert report["counts"]["inserted_aliases"] == 2
    assert report["counts"]["skipped_artist_canonical"] == 1
    assert report["counts"]["skipped_missing_canonical"] == 1
    assert report["target_after"]["hot_tags_changed"] is False
    assert lock_was_held == [True]

    connection = sqlite3.connect(str(database))
    connection.row_factory = sqlite3.Row
    try:
        after = connection.execute("SELECT * FROM hot_tags ORDER BY tag").fetchall()
        assert [tuple(row) for row in after] == before
        aliases = {
            row["alias"]: row
            for row in connection.execute(
                "SELECT * FROM tag_aliases ORDER BY alias"
            ).fetchall()
        }
        assert set(aliases) == {"general_alias", "character_alias"}
        assert aliases["general_alias"]["canonical_tag"] == "general_tag"
        assert aliases["general_alias"]["declared_license"] == "CC-BY-4.0"
        assert aliases["general_alias"]["source_sha256"] == metadata.expected_sha256
        assert "artist_alias" not in aliases
        assert "missing_alias" not in aliases

        provenance = connection.execute(
            "SELECT * FROM tag_alias_imports"
        ).fetchone()
        assert provenance["eligible_rows"] == 2
        assert provenance["inserted_aliases"] == 2
        assert provenance["skipped_artist_canonical"] == 1
        assert provenance["skipped_missing_canonical"] == 1
        assert provenance["conflict_rows"] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()

    second = importer.import_alias_pack(
        source_path,
        database,
        mode="apply",
        backup_dir=backup_dir,
    )
    assert second["status"] == "already_imported"
    assert second["backup_path"] is None
    assert len(list(backup_dir.glob("*.db"))) == 1


def test_existing_ineligible_rows_from_same_source_block_apply(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    source_path = tmp_path / "aliases.csv"
    backup_dir = tmp_path / "backups"
    _make_database(database)
    _write_source(source_path)
    metadata = _metadata(source_path)
    monkeypatch.setattr(importer, "FIXED_SOURCE", metadata)

    connection = sqlite3.connect(str(database))
    try:
        importer._create_alias_schema(connection)
        connection.execute(
            """
            INSERT INTO tag_aliases(
                alias, canonical_tag, relation_type, source_name, source_url,
                declared_license, source_revision, source_sha256, imported_at
            ) VALUES (?, ?, 'official_alias', ?, ?, ?, ?, ?, 1)
            """,
            (
                "dirty_artist_alias",
                "artist_tag",
                metadata.source_name,
                metadata.source_url,
                metadata.license,
                metadata.revision,
                metadata.expected_sha256,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    dry_report = importer.import_alias_pack(source_path, database, mode="dry-run")
    assert dry_report["target_before"]["existing_artist_aliases"] == 1
    assert dry_report["target_before"]["source_artist_aliases"] == 1

    with pytest.raises(
        importer.AliasTargetDatabaseError,
        match="existing aliases from the pinned source are ineligible",
    ):
        importer.import_alias_pack(
            source_path,
            database,
            mode="apply",
            backup_dir=backup_dir,
        )
    assert not backup_dir.exists()
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0] == 1
    finally:
        connection.close()


def test_apply_to_live_database_requires_second_confirmation(tmp_path: Path, monkeypatch):
    database = tmp_path / "tags.db"
    source_path = tmp_path / "aliases.csv"
    _make_database(database)
    _write_source(source_path)
    monkeypatch.setattr(importer, "FIXED_SOURCE", _metadata(source_path))
    monkeypatch.setattr(importer, "DEFAULT_DB_PATH", database.resolve())
    before = database.read_bytes()

    with pytest.raises(importer.AliasImportValidationError, match="allow_live_db"):
        importer.import_alias_pack(source_path, database, mode="apply")
    assert database.read_bytes() == before

    parsed = importer.build_argument_parser().parse_args(
        [
            "--input", str(source_path),
            "--db", str(database),
            "--mode", "apply",
            "--allow-live-db",
        ]
    )
    assert parsed.allow_live_db is True

    allowed = importer.import_alias_pack(
        source_path,
        database,
        mode="apply",
        backup_dir=tmp_path / "backups",
        allow_live_db=True,
    )
    assert allowed["status"] == "imported"
    assert Path(allowed["backup_path"]).is_file()


def test_json_report_hardlink_cannot_overwrite_target_database(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    database_alias = tmp_path / "report.json"
    source_path = tmp_path / "aliases.csv"
    _make_database(database)
    _write_source(source_path)
    monkeypatch.setattr(importer, "FIXED_SOURCE", _metadata(source_path))
    before = database.read_bytes()
    os.link(database, database_alias)

    assert importer.main([
        "--input", str(source_path),
        "--db", str(database),
        "--mode", "dry-run",
        "--json-report", str(database_alias),
    ]) == 2
    assert database.read_bytes() == before

    source_before = source_path.read_bytes()
    source_alias = tmp_path / "source-report.json"
    os.link(source_path, source_alias)
    assert importer.main([
        "--input", str(source_path),
        "--db", str(database),
        "--mode", "dry-run",
        "--json-report", str(source_alias),
    ]) == 2
    assert source_path.read_bytes() == source_before
