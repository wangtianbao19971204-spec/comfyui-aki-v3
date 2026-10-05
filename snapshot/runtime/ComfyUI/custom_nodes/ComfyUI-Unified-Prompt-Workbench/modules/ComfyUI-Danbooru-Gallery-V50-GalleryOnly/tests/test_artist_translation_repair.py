from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = PLUGIN_ROOT / "tools" / "repair_artist_translations.py"
SPEC = importlib.util.spec_from_file_location("artist_translation_repair", TOOL_PATH)
assert SPEC and SPEC.loader
repair = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = repair
SPEC.loader.exec_module(repair)


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
            CREATE VIRTUAL TABLE hot_tags_fts USING fts5(
                tag,
                translation_cn,
                content='hot_tags',
                content_rowid='rowid',
                tokenize='unicode61'
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
                ("artist_alpha", 1, 50, "艺术家甲", 1, None),
                ("artist_whitespace", 1, 40, "  ", 1, None),
                ("artist_empty", 1, 30, None, 1, None),
                ("blue_eyes", 0, 100, "蓝眼睛", 1, None),
                ("hero_(series)", 4, 80, "英雄（系列）", 1, None),
            ],
        )
        # Deliberately leave the FTS index incomplete so apply mode proves it
        # performs a full rebuild rather than relying on update triggers.
        connection.execute(
            """
            INSERT INTO hot_tags_fts(rowid, tag, translation_cn)
            SELECT rowid, tag, translation_cn FROM hot_tags WHERE tag = 'blue_eyes'
            """
        )
        connection.commit()
    finally:
        connection.close()


def _fetch_translations(path: Path):
    connection = sqlite3.connect(str(path))
    try:
        return dict(
            connection.execute(
                "SELECT tag, translation_cn FROM hot_tags ORDER BY tag"
            ).fetchall()
        )
    finally:
        connection.close()


def _table_exists(path: Path, table: str) -> bool:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None
    finally:
        connection.close()


def test_default_dry_run_is_read_only_and_reports_projection(tmp_path):
    db_path = tmp_path / "tags.db"
    backup_dir = tmp_path / "backups"
    _make_database(db_path)
    before_values = _fetch_translations(db_path)

    report = repair.repair_database(db_path, backup_dir=backup_dir)

    assert report["mode"] == "dry-run"
    assert report["applied"] is False
    assert report["backup"] is None
    assert report["before"]["artist_translation_values"] == 2
    assert report["before"]["artist_translated_tags"] == 1
    assert report["before"]["fts_rows"] == 1
    assert report["after_is_projection"] is True
    assert report["after"]["artist_translation_values"] == 0
    assert report["after"]["artist_translation_values_sha256"] != report["before"][
        "artist_translation_values_sha256"
    ]
    assert report["after"]["fts_rows"] == 5
    assert report["integrity"] == {"before": "ok", "backup": None, "after": None}
    assert _fetch_translations(db_path) == before_values
    assert not _table_exists(db_path, "tag_translation_history")
    assert not backup_dir.exists()


def test_apply_backs_up_then_histories_clears_and_rebuilds(tmp_path):
    db_path = tmp_path / "tags.db"
    backup_dir = tmp_path / "backups"
    _make_database(db_path)

    report = repair.repair_database(db_path, apply=True, backup_dir=backup_dir)

    assert report["mode"] == "apply"
    assert report["applied"] is True
    assert report["changes"] == {
        "history_rows_inserted": 2,
        "artist_translation_values_cleared": 2,
        "fts_rows_rebuilt": 5,
    }
    assert report["after"]["artist_translation_values"] == 0
    assert report["after"]["artist_translated_tags"] == 0
    assert report["after"]["fts_rows"] == 5
    assert report["after"]["fts_matches_hot_tags"] is True
    assert report["integrity"] == {"before": "ok", "backup": "ok", "after": "ok"}

    target_values = _fetch_translations(db_path)
    assert target_values["artist_alpha"] is None
    assert target_values["artist_whitespace"] is None
    assert target_values["blue_eyes"] == "蓝眼睛"
    assert target_values["hero_(series)"] == "英雄（系列）"

    connection = sqlite3.connect(str(db_path))
    try:
        history = connection.execute(
            """
            SELECT tag, old_translation_cn, new_translation_cn, change_type, run_id
            FROM tag_translation_history ORDER BY tag
            """
        ).fetchall()
        assert history == [
            (
                "artist_alpha",
                "艺术家甲",
                None,
                "clear_artist_translation",
                report["run_id"],
            ),
            (
                "artist_whitespace",
                "  ",
                None,
                "clear_artist_translation",
                report["run_id"],
            ),
        ]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()

    backup_path = Path(report["backup"]["path"])
    assert backup_path.is_file()
    assert len(report["backup"]["sha256"]) == 64
    assert _fetch_translations(backup_path)["artist_alpha"] == "艺术家甲"
    assert not _table_exists(backup_path, "tag_translation_history")
    backup_connection = sqlite3.connect(str(backup_path))
    try:
        assert backup_connection.execute(
            "SELECT COUNT(*) FROM hot_tags_fts_docsize"
        ).fetchone()[0] == 1
        assert backup_connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        backup_connection.close()


def test_second_apply_is_idempotent_and_cli_defaults_to_dry_run(tmp_path, capsys):
    db_path = tmp_path / "tags.db"
    backup_dir = tmp_path / "backups"
    _make_database(db_path)
    first = repair.repair_database(db_path, apply=True, backup_dir=backup_dir)

    assert repair.main(["--db", str(db_path), "--backup-dir", str(backup_dir)]) == 0
    cli_report = __import__("json").loads(capsys.readouterr().out)
    assert cli_report["mode"] == "dry-run"
    assert cli_report["applied"] is False

    second = repair.repair_database(db_path, apply=True, backup_dir=backup_dir)
    assert second["changes"]["history_rows_inserted"] == 0
    assert second["changes"]["artist_translation_values_cleared"] == 0
    assert second["after"]["history_rows"] == first["after"]["history_rows"]
    assert Path(second["backup"]["path"]).is_file()
    assert Path(second["backup"]["path"]) != Path(first["backup"]["path"])


def test_live_database_apply_requires_second_confirmation(monkeypatch, tmp_path):
    db_path = tmp_path / "live-tags-cache.db"
    _make_database(db_path)
    monkeypatch.setattr(repair, "DEFAULT_LIVE_DB", db_path.resolve())

    with pytest.raises(repair.RepairError, match="allow_live_db=True"):
        repair.repair_database(
            db_path,
            apply=True,
            backup_dir=tmp_path / "backups",
        )

    report = repair.repair_database(
        db_path,
        apply=True,
        allow_live_db=True,
        backup_dir=tmp_path / "backups",
    )
    assert report["applied"] is True
    assert report["is_plugin_live_db"] is True
    assert report["live_apply_guard"] is True
