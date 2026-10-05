from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PLUGIN_ROOT / "tests" / "run_delivery.ps1"
SNAPSHOT_HELPER = PLUGIN_ROOT / "tests" / "sqlite_snapshot.py"
DB_MANAGER = PLUGIN_ROOT / "py" / "shared" / "db" / "db_manager.py"


def test_delivery_runner_uses_isolated_databases_and_logically_protects_live_tag_db():
    source = RUNNER.read_text(encoding="utf-8")
    snapshot_source = SNAPSHOT_HELPER.read_text(encoding="utf-8")

    assert "DANBOORU_GALLERY_TAG_DB_PATH" in source
    assert "isolatedTagDatabase = $isolatedTagDb" in source
    assert "isolatedComfyDatabase = $runtimeComfyDb" in source
    assert "New-VerifiedSqliteSnapshot" in source
    assert "-Source $liveTagDb -Destination $liveTagDbBeforeSnapshot" in source
    assert "-Source $liveTagDb -Destination $liveTagDbAfterSnapshot" in source
    assert "-Source $liveTagDbBeforeSnapshot -Destination $isolatedTagDb" in source
    assert 'source_uri = "file:"' in snapshot_source
    assert "source_connection.backup(destination_connection)" in snapshot_source
    assert 'destination_connection.execute("PRAGMA quick_check")' in snapshot_source
    assert 'FINGERPRINT_VERSION = "sqlite-logical-v1"' in snapshot_source
    assert "encoded_rows.sort()" in snapshot_source
    protected_block = source.split("$protectedPaths = @(", 1)[1].split("\n)", 1)[0]
    assert "$liveTagDb" not in protected_block
    assert "protectedFileHashesBefore" in source
    assert "protectedFileHashesAfter" in source
    assert "liveTagDatabaseProtection" in source
    assert "$liveTagDbLogicalBefore.sha256 -ne $liveTagDbLogicalAfter.sha256" in source
    assert source.count("--database-url") >= 2
    unit_block = source.split("if (-not $SkipUnitTests) {", 1)[1].split(
        "Push-Location $comfy", 1
    )[0]
    assert "$env:DANBOORU_GALLERY_DELIVERY_TEST = $oldDeliveryTest" in unit_block
    assert "$env:DANBOORU_GALLERY_TEST_CONFIG = $oldTestConfig" in unit_block
    assert "$env:DANBOORU_GALLERY_TAG_DB_PATH = $oldTagDbPath" in unit_block
    assert "$env:DANBOORU_GALLERY_DELIVERY_TEST = '1'" in unit_block
    assert "$env:DANBOORU_GALLERY_TAG_DB_PATH = $isolatedTagDb" in unit_block


def test_sqlite_snapshot_helper_copies_consistently_without_writing_source(tmp_path):
    source_db = tmp_path / "source.db"
    destination_db = tmp_path / "runtime" / "copy.db"
    destination_db.parent.mkdir()
    with sqlite3.connect(source_db) as connection:
        connection.execute("CREATE TABLE hot_tags(tag TEXT PRIMARY KEY, category INTEGER)")
        connection.execute("INSERT INTO hot_tags VALUES ('character_tag', 4)")

    before = hashlib.sha256(source_db.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("sqlite_snapshot_test", SNAPSHOT_HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = module.create_snapshot(source_db, destination_db)
    after = hashlib.sha256(source_db.read_bytes()).hexdigest()

    assert before == after
    assert result["status"] == "ok"
    assert result["quickCheck"] == "ok"
    assert result["logicalFingerprint"]["version"] == "sqlite-logical-v1"
    assert len(result["logicalFingerprint"]["sha256"]) == 64
    assert result["logicalFingerprint"]["tables"] == [
        {
            "name": "hot_tags",
            "rowCount": 1,
            "sha256": result["logicalFingerprint"]["tables"][0]["sha256"],
        }
    ]
    with sqlite3.connect(f"file:{destination_db.as_posix()}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert connection.execute("SELECT * FROM hot_tags").fetchone() == (
            "character_tag",
            4,
        )
    with pytest.raises(FileExistsError, match="already exists"):
        module.create_snapshot(source_db, destination_db)


def test_sqlite_logical_fingerprint_sees_wal_data_but_ignores_checkpoint(tmp_path):
    source_db = tmp_path / "source-wal.db"
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    spec = importlib.util.spec_from_file_location("sqlite_snapshot_wal_test", SNAPSHOT_HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    with sqlite3.connect(source_db) as connection:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("CREATE TABLE hot_tags(tag TEXT PRIMARY KEY, category INTEGER)")
        connection.execute("INSERT INTO hot_tags VALUES ('first_tag', 4)")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        connection.execute("INSERT INTO hot_tags VALUES ('wal_only_tag', 0)")
        connection.commit()
        before_checkpoint = module.create_snapshot(
            source_db, snapshots / "before-checkpoint.db"
        )
        assert Path(f"{source_db}-wal").is_file()

        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        after_checkpoint = module.create_snapshot(
            source_db, snapshots / "after-checkpoint.db"
        )
        assert (
            before_checkpoint["logicalFingerprint"]["sha256"]
            == after_checkpoint["logicalFingerprint"]["sha256"]
        )

        main_file_after_checkpoint = hashlib.sha256(source_db.read_bytes()).hexdigest()
        connection.execute("INSERT INTO hot_tags VALUES ('second_wal_only_tag', 3)")
        connection.commit()
        assert hashlib.sha256(source_db.read_bytes()).hexdigest() == main_file_after_checkpoint
        after_logical_change = module.create_snapshot(
            source_db, snapshots / "after-logical-change.db"
        )
        assert (
            after_logical_change["logicalFingerprint"]["sha256"]
            != after_checkpoint["logicalFingerprint"]["sha256"]
        )
        hot_tags = next(
            table
            for table in after_logical_change["logicalFingerprint"]["tables"]
            if table["name"] == "hot_tags"
        )
        assert hot_tags["rowCount"] == 3


def test_tag_db_environment_override_is_delivery_only_and_fails_closed():
    source = DB_MANAGER.read_text(encoding="utf-8")

    assert '_DELIVERY_GUARD_ENV = "DANBOORU_GALLERY_DELIVERY_TEST"' in source
    assert '_TAG_DB_OVERRIDE_ENV = "DANBOORU_GALLERY_TAG_DB_PATH"' in source
    assert "if not _delivery_enabled():\n        return None" in source
    assert "delivery test config escaped tests/.runtime" in source
    assert "delivery tag database escaped its declared runtimeRoot" in source
    assert "delivery tag database does not exist" in source
