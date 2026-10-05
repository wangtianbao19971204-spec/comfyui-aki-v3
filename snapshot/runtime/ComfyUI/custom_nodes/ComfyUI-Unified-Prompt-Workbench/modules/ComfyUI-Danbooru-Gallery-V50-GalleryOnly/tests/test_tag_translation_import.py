from __future__ import annotations

import csv
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
IMPORTER_PATH = PLUGIN_ROOT / "tools" / "import_tag_translations.py"
SPEC = importlib.util.spec_from_file_location("tag_translation_importer", IMPORTER_PATH)
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
            CREATE TABLE sync_metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at INTEGER
            );
            CREATE VIRTUAL TABLE hot_tags_fts USING fts5(
                tag,
                translation_cn,
                content='hot_tags',
                content_rowid='rowid',
                tokenize='unicode61'
            );
            CREATE TRIGGER hot_tags_ai AFTER INSERT ON hot_tags BEGIN
                INSERT INTO hot_tags_fts(rowid, tag, translation_cn)
                VALUES (NEW.rowid, NEW.tag, NEW.translation_cn);
            END;
            CREATE TRIGGER hot_tags_au AFTER UPDATE ON hot_tags BEGIN
                UPDATE hot_tags_fts
                SET tag = NEW.tag, translation_cn = NEW.translation_cn
                WHERE rowid = NEW.rowid;
            END;
            CREATE TRIGGER hot_tags_ad AFTER DELETE ON hot_tags BEGIN
                DELETE FROM hot_tags_fts WHERE rowid = OLD.rowid;
            END;
            """
        )
        connection.executemany(
            """
            INSERT INTO hot_tags(
                tag, category, post_count, translation_cn, last_updated, aliases
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("blue_eyes", 0, 100, "现有蓝眼", 10, None),
                ("long_hair", 0, 200, None, 20, None),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def _write_csv(path: Path, fieldnames, rows) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _metadata(revision: str = "test-revision"):
    return importer.SourceMetadata(
        source_url="https://example.test/licensed-tag-pack",
        license="MIT",
        revision=revision,
    )


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def test_normalization_and_conservative_newtextdoc_selection():
    assert importer.normalize_tag("  ＢＬＵＥ   Eyes  ") == "blue_eyes"

    selected, reason = importer.select_newtextdoc_candidate(
        "ロングヘアー,长发,단발"
    )
    assert (selected, reason) == ("长发", "selected_unique_han")

    selected, reason = importer.select_newtextdoc_candidate(
        "ロングヘアー,長髪,长发,단발"
    )
    assert selected is None
    assert reason == "ambiguous_translation"

    selected, reason = importer.select_newtextdoc_candidate(
        "女性,少女,女孩,姑娘,女"
    )
    assert selected is None
    assert reason == "ambiguous_translation"

    selected, reason = importer.select_newtextdoc_candidate("白背景")
    assert (selected, reason) == ("白背景", "selected_unique_han")


def test_newtextdoc_dry_run_stages_without_writing_or_backing_up(tmp_path: Path):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "danbooru_tags.csv"
    backups = tmp_path / "backups"
    _make_database(database)
    _write_csv(
        source,
        ["tag", "category", "count", "alias"],
        [
            {
                "tag": "long_hair",
                "category": 0,
                "count": 500,
                "alias": "ロングヘアー,长发,단발",
            },
            {
                "tag": "black_hair",
                "category": 0,
                "count": 400,
                "alias": "ブラックヘア,黑发,흑발",
            },
            {
                "tag": "1girl",
                "category": 0,
                "count": 900,
                "alias": "女性,少女,女孩,姑娘,女",
            },
            {
                "tag": "white_background",
                "category": 0,
                "count": 300,
                "alias": "白背景",
            },
            {
                "tag": "no_alias",
                "category": 0,
                "count": 1,
                "alias": "",
            },
        ],
    )

    report = importer.import_translation_pack(
        source,
        database,
        _metadata("newtextdoc-snapshot"),
        dry_run=True,
        pack_format="auto",
        backup_dir=backups,
    )

    assert report["status"] == "dry_run"
    assert report["backup_path"] is None
    assert report["pack"]["format"] == "newtextdoc"
    assert report["pack"]["total_rows"] == 5
    assert report["pack"]["staged_rows"] == 3
    assert report["pack"]["skipped_ambiguous_translation"] == 1
    assert report["pack"]["skipped_no_translation"] == 1
    assert report["target_before"]["would_fill_translations"] == 1
    assert report["target_before"]["would_insert_tags"] == 0
    assert report["target_before"]["would_reject_missing_target_tags"] == 2
    assert not backups.exists()

    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='long_hair'"
        ).fetchone()[0] is None
        assert not _table_exists(connection, "tag_translation_imports")
    finally:
        connection.close()


def test_import_preserves_existing_translation_backs_up_and_is_idempotent(
    tmp_path: Path,
):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "generic.csv"
    backups = tmp_path / "backups"
    _make_database(database)
    _write_csv(
        source,
        ["tag", "category", "post_count", "cn_name"],
        [
            {
                "tag": "  ＢＬＵＥ Eyes ",
                "category": 4,
                "post_count": 999,
                "cn_name": "新蓝眼",
            },
            {
                "tag": "Long Hair",
                "category": 0,
                "post_count": 800,
                "cn_name": "长发",
            },
            {
                "tag": "Black Hair",
                "category": 0,
                "post_count": 700,
                "cn_name": "黑发",
            },
            {
                "tag": "bad_translation",
                "category": 0,
                "post_count": 1,
                "cn_name": "English only",
            },
        ],
    )

    report = importer.import_translation_pack(
        source,
        database,
        _metadata("generic-snapshot"),
        apply=True,
        backup_dir=backups,
        pack_format="generic",
    )

    assert report["status"] == "imported"
    assert report["pack"]["rejected_rows"] == 1
    assert report["counts"] == {
        "inserted_tags": 0,
        "filled_translations": 1,
        "preserved_translations": 1,
    }
    assert report["skipped_missing_target_tags"] == 1
    backup_path = Path(report["backup_path"])
    assert backup_path.is_file()
    assert backup_path.parent == backups.resolve()

    connection = sqlite3.connect(str(database))
    try:
        rows = {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT tag, translation_cn, category, post_count FROM hot_tags"
            )
        }
        assert rows["blue_eyes"] == ("现有蓝眼", 0, 100)
        assert rows["long_hair"] == ("长发", 0, 200)
        assert "black_hair" not in rows
        assert "bad_translation" not in rows
        assert connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM hot_tags_fts_docsize"
        ).fetchone()[0] == 2
        provenance = connection.execute(
            """
            SELECT source_url, declared_license, revision, sha256,
                   inserted_tags, filled_translations, preserved_translations
            FROM tag_translation_imports
            """
        ).fetchone()
        assert provenance[:3] == (
            "https://example.test/licensed-tag-pack",
            "MIT",
            "generic-snapshot",
        )
        assert len(provenance[3]) == 64
        assert provenance[4:] == (0, 1, 1)
    finally:
        connection.close()

    backup = sqlite3.connect(str(backup_path))
    try:
        assert backup.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='long_hair'"
        ).fetchone()[0] is None
        assert backup.execute(
            "SELECT 1 FROM hot_tags WHERE tag='black_hair'"
        ).fetchone() is None
        assert not _table_exists(backup, "tag_translation_imports")
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        backup.close()

    second_report = importer.import_translation_pack(
        source,
        database,
        _metadata("generic-snapshot"),
        apply=True,
        backup_dir=backups,
    )
    assert second_report["status"] == "already_imported"
    assert second_report["backup_path"] is None
    assert len(list(backups.iterdir())) == 1


def test_artist_rows_are_skipped_and_live_artist_category_is_authoritative(
    tmp_path: Path,
):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "category-guard.csv"
    backups = tmp_path / "backups"
    _make_database(database)
    connection = sqlite3.connect(str(database))
    try:
        connection.executemany(
            """
            INSERT INTO hot_tags(
                tag, category, post_count, translation_cn, last_updated, aliases
            ) VALUES (?, ?, ?, NULL, 30, NULL)
            """,
            [
                ("known_artist", 1, 50),
                ("allowed_copyright", 3, 30),
                ("allowed_character", 4, 20),
                ("allowed_meta", 5, 10),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    _write_csv(
        source,
        ["tag", "category", "post_count", "translation_cn"],
        [
            {
                # The source lies about this tag, but the live category wins.
                "tag": "known_artist",
                "category": 0,
                "post_count": 500,
                "translation_cn": "已知艺术家",
            },
            {
                "tag": "new_artist",
                "category": 1,
                "post_count": 400,
                "translation_cn": "新增艺术家",
            },
            {
                "tag": "disallowed_category_two",
                "category": 2,
                "post_count": 350,
                "translation_cn": "禁用类别",
            },
            {
                "tag": "allowed_copyright",
                "category": 3,
                "post_count": 300,
                "translation_cn": "允许版权",
            },
            {
                "tag": "allowed_character",
                "category": 4,
                "post_count": 200,
                "translation_cn": "允许角色",
            },
            {
                "tag": "allowed_meta",
                "category": 5,
                "post_count": 100,
                "translation_cn": "允许元标签",
            },
        ],
    )

    report = importer.import_translation_pack(
        source,
        database,
        _metadata("category-guard"),
        apply=True,
        backup_dir=backups,
        pack_format="generic",
    )

    assert report["pack"]["total_rows"] == 6
    assert report["pack"]["staged_rows"] == 4
    assert report["pack"]["skipped_disallowed_category"] == 2
    assert report["target_before"]["would_insert_tags"] == 0
    assert report["target_before"]["would_reject_missing_target_tags"] == 0
    assert report["target_before"]["would_fill_translations"] == 3
    assert report["target_before"]["would_skip_disallowed_target_category"] == 1
    assert report["skipped_disallowed_target_category"] == 1
    assert report["counts"] == {
        "inserted_tags": 0,
        "filled_translations": 3,
        "preserved_translations": 0,
    }

    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='known_artist'"
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT 1 FROM hot_tags WHERE tag='new_artist'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM hot_tags WHERE tag='disallowed_category_two'"
        ).fetchone() is None
        assert connection.execute(
            """
            SELECT COUNT(*) FROM hot_tags
            WHERE category IN (3, 4, 5)
              AND NULLIF(TRIM(translation_cn), '') IS NOT NULL
            """
        ).fetchone()[0] == 3
        # Two explicit disallowed rows plus one rejected by live metadata.
        assert connection.execute(
            "SELECT skipped_rows FROM tag_translation_imports"
        ).fetchone()[0] == 3
    finally:
        connection.close()


def test_validation_failure_does_not_touch_target(tmp_path: Path):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "bad.csv"
    backups = tmp_path / "backups"
    _make_database(database)
    _write_csv(
        source,
        ["tag", "category", "count", "translation_cn"],
        [
            {
                "tag": "valid_tag",
                "category": 0,
                "count": 1,
                "translation_cn": "有效翻译",
            },
            {
                "tag": "oversize_tag",
                "category": 0,
                "count": 1,
                "translation_cn": "汉" * (importer.MAX_TRANSLATION_BYTES + 1),
            },
        ],
    )

    with pytest.raises(importer.ImportValidationError, match="rejected row ratio"):
        importer.import_translation_pack(
            source,
            database,
            _metadata("bad-snapshot"),
            backup_dir=backups,
            max_reject_ratio=0.25,
        )

    assert not backups.exists()
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0] == 2
        assert not _table_exists(connection, "tag_translation_imports")
    finally:
        connection.close()

    with pytest.raises(importer.ImportValidationError, match="license"):
        importer.import_translation_pack(
            source,
            database,
            importer.SourceMetadata(
                source_url="https://example.test/no-license",
                license="unknown",
                revision="bad-license",
            ),
            dry_run=True,
            max_reject_ratio=1.0,
        )


def test_cli_dry_run_emits_and_writes_json_report(tmp_path: Path, capsys):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "generic.csv"
    json_report = tmp_path / "reports" / "dry-run.json"
    _make_database(database)
    _write_csv(
        source,
        ["tag", "category", "count", "lang_zh"],
        [
            {
                "tag": "long_hair",
                "category": 0,
                "count": 500,
                "lang_zh": "长发",
            }
        ],
    )

    exit_code = importer.main(
        [
            str(source),
            "--db",
            str(database),
            "--source-url",
            "https://example.test/pack",
            "--license",
            "CC0-1.0",
            "--revision",
            "cli-snapshot",
            "--dry-run",
            "--json-report",
            str(json_report),
        ]
    )

    assert exit_code == 0
    stdout_report = json.loads(capsys.readouterr().out)
    file_report = json.loads(json_report.read_text(encoding="utf-8"))
    assert stdout_report == file_report
    assert file_report["status"] == "dry_run"
    assert file_report["target_before"]["would_fill_translations"] == 1


@pytest.mark.parametrize("protected_kind", ["database", "input"])
def test_cli_json_report_cannot_overwrite_input_or_database(
    tmp_path: Path, capsys, protected_kind: str,
):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "generic.csv"
    _make_database(database)
    _write_csv(
        source,
        ["tag", "category", "count", "translation_cn"],
        [
            {
                "tag": "long_hair",
                "category": 0,
                "count": 500,
                "translation_cn": "长发",
            }
        ],
    )
    protected = database if protected_kind == "database" else source
    before = protected.read_bytes()

    exit_code = importer.main(
        [
            str(source),
            "--db",
            str(database),
            "--source-url",
            "https://example.test/pack",
            "--license",
            "MIT",
            "--revision",
            "report-path-guard-{}".format(protected_kind),
            "--json-report",
            str(protected),
        ]
    )

    assert exit_code == 2
    error_report = json.loads(capsys.readouterr().out)
    assert error_report["error"]["code"] == "validation_error"
    assert "must not be" in error_report["error"]["message"]
    assert protected.read_bytes() == before
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not _table_exists(connection, "tag_translation_imports")
    finally:
        connection.close()


def test_cli_json_report_rejects_hardlink_alias_of_database(tmp_path: Path, capsys):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "generic.csv"
    hardlink_report = tmp_path / "report-hardlink.json"
    _make_database(database)
    _write_csv(
        source,
        ["tag", "category", "count", "translation_cn"],
        [
            {
                "tag": "long_hair",
                "category": 0,
                "count": 500,
                "translation_cn": "长发",
            }
        ],
    )
    try:
        os.link(database, hardlink_report)
    except OSError as exc:  # pragma: no cover - filesystem capability boundary
        pytest.skip("hard links are unavailable: {}".format(exc))
    before = database.read_bytes()

    exit_code = importer.main(
        [
            str(source),
            "--db",
            str(database),
            "--source-url",
            "https://example.test/pack",
            "--license",
            "MIT",
            "--revision",
            "report-hardlink-guard",
            "--json-report",
            str(hardlink_report),
        ]
    )

    assert exit_code == 2
    error_report = json.loads(capsys.readouterr().out)
    assert error_report["error"]["code"] == "validation_error"
    assert database.read_bytes() == before
    assert hardlink_report.read_bytes() == before


def test_json_report_exclusive_create_refuses_race_and_cleans_partial(
    tmp_path: Path, monkeypatch,
):
    protected = tmp_path / "tags_cache.db"
    protected.write_bytes(b"sqlite-placeholder")
    report_path = tmp_path / "report.json"
    importer._validate_json_report_destination(report_path, [protected])
    report_path.write_text("concurrent-owner\n", encoding="utf-8")

    with pytest.raises(importer.ImportValidationError, match="already exists"):
        importer._write_json_report(
            {"status": "dry_run"},
            report_path,
            protected_paths=[protected],
        )
    assert report_path.read_text(encoding="utf-8") == "concurrent-owner\n"

    partial_path = tmp_path / "partial.json"

    def fail_fsync(_descriptor):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(importer.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated fsync failure"):
        importer._write_json_report(
            {"status": "dry_run"},
            partial_path,
            protected_paths=[protected],
        )
    assert not partial_path.exists()


def test_default_mode_is_dry_run_and_apply_conflicts_with_legacy_flag(
    tmp_path: Path, capsys,
):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "generic.csv"
    backups = tmp_path / "backups"
    _make_database(database)
    _write_csv(
        source,
        ["tag", "category", "count", "translation_cn"],
        [
            {
                "tag": "long_hair",
                "category": 0,
                "count": 500,
                "translation_cn": "长发",
            }
        ],
    )

    report = importer.import_translation_pack(
        source,
        database,
        _metadata("default-dry-run"),
        backup_dir=backups,
    )

    assert report["status"] == "dry_run"
    assert report["dry_run"] is True
    assert not backups.exists()
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='long_hair'"
        ).fetchone()[0] is None
        assert not _table_exists(connection, "tag_translation_imports")
    finally:
        connection.close()

    cli_exit = importer.main(
        [
            str(source),
            "--db",
            str(database),
            "--source-url",
            "https://example.test/pack",
            "--license",
            "MIT",
            "--revision",
            "default-cli-dry-run",
        ]
    )
    assert cli_exit == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"

    with pytest.raises(SystemExit):
        importer.build_argument_parser().parse_args(
            [
                str(source),
                "--source-url",
                "https://example.test/pack",
                "--license",
                "MIT",
                "--revision",
                "conflicting-mode",
                "--apply",
                "--dry-run",
            ]
        )

    with pytest.raises(importer.ImportValidationError, match="mutually exclusive"):
        importer.import_translation_pack(
            source,
            database,
            _metadata("conflicting-api-mode"),
            apply=True,
            dry_run=True,
        )


def test_cli_apply_to_exact_live_path_requires_second_confirmation(
    tmp_path: Path, monkeypatch, capsys
):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "generic.csv"
    backups = tmp_path / "backups"
    _make_database(database)
    _write_csv(
        source,
        ["tag", "category", "count", "translation_cn"],
        [
            {
                "tag": "long_hair",
                "category": 0,
                "count": 500,
                "translation_cn": "长发",
            }
        ],
    )
    monkeypatch.setattr(importer, "DEFAULT_DB_PATH", database.resolve())
    base_arguments = [
        str(source),
        "--db",
        str(database),
        "--source-url",
        "https://example.test/pack",
        "--license",
        "MIT",
        "--revision",
        "live-guard",
        "--backup-dir",
        str(backups),
        "--apply",
    ]

    assert importer.main(base_arguments) == 2
    error_report = json.loads(capsys.readouterr().out)
    assert error_report["error"]["code"] == "target_database_error"
    assert "--allow-live-db" in error_report["error"]["message"]
    assert not backups.exists()

    assert importer.main(base_arguments + ["--allow-live-db"]) == 0
    applied_report = json.loads(capsys.readouterr().out)
    assert applied_report["status"] == "imported"
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='long_hair'"
        ).fetchone()[0] == "长发"
    finally:
        connection.close()


def test_fts_counts_real_docsize_rows_and_rebuild_repairs_missing_document(
    tmp_path: Path,
):
    database = tmp_path / "tags_cache.db"
    source = tmp_path / "generic.csv"
    _make_database(database)
    _write_csv(
        source,
        ["tag", "category", "count", "translation_cn"],
        [
            {
                "tag": "long_hair",
                "category": 0,
                "count": 500,
                "translation_cn": "长发",
            }
        ],
    )
    connection = sqlite3.connect(str(database))
    try:
        # External-content COUNT still proxies hot_tags even after a real FTS
        # shadow document is removed, which is why docsize must be inspected.
        connection.execute(
            "DELETE FROM hot_tags_fts_docsize "
            "WHERE id = (SELECT MIN(id) FROM hot_tags_fts_docsize)"
        )
        connection.commit()
        assert connection.execute("SELECT COUNT(*) FROM hot_tags_fts").fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM hot_tags_fts_docsize"
        ).fetchone()[0] == 1
    finally:
        connection.close()

    dry_report = importer.import_translation_pack(
        source,
        database,
        _metadata("fts-real-count-dry"),
    )
    assert dry_report["target_before"]["fts_rows"] == 1
    assert dry_report["target_before"]["fts_matches_hot_tags"] is False

    apply_report = importer.import_translation_pack(
        source,
        database,
        _metadata("fts-real-count-apply"),
        apply=True,
    )
    assert apply_report["target_after"]["fts_rows"] == 2
    assert apply_report["target_after"]["fts_matches_hot_tags"] is True
