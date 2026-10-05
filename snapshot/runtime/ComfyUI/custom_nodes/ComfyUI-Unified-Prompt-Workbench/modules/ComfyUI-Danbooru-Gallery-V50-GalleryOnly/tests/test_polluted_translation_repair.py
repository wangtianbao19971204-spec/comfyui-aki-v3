from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = PLUGIN_ROOT / "tools" / "repair_polluted_tag_translations.py"
SPEC = importlib.util.spec_from_file_location("polluted_translation_repair", TOOL_PATH)
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
            ) VALUES (?, ?, ?, ?, 1, NULL)
            """,
            [
                ("blue_eyes", 0, 1000, "蓝眼睛"),
                ("middle_dot_name", 4, 950, "桃乐丝・威斯特（美妙旋律）"),
                ("kana_name", 4, 900, "初音ミク"),
                ("hangul_name", 4, 800, "미쿠"),
                ("control_pollution", 5, 700, "来源\t待补"),
                ("ptilopsis_(arknights)", 4, 600, "ptilopsis_(arknights)"),
                ("chibi_miku", 4, 500, "souryuu_asuka_langley"),
                ("souryuu_asuka_langley", 4, 490, "惣流·明日香·兰格雷"),
                ("vocaloid_(software)", 3, 400, "VOCALOID"),
                ("vocaloid", 3, 390, "歌声合成软件"),
                ("bdsm", 0, 300, "BDSM"),
                ("jojo", 3, 290, "JOJO"),
                ("hero_(series)", 3, 200, "英雄"),
                ("one_piece", 3, 150, "一拳超人"),
                ("lyn_(blade_&_soul)", 4, 125, "剑灵"),
                ("artist_kana", 1, 100, "アーティスト"),
            ],
        )
        # Deliberately stale/incomplete; apply must rebuild it transactionally.
        connection.execute(
            "INSERT INTO hot_tags_fts(rowid,tag,translation_cn) "
            "SELECT rowid,tag,translation_cn FROM hot_tags WHERE tag='blue_eyes'"
        )
        connection.commit()
    finally:
        connection.close()


def _translations(path: Path) -> dict[str, str | None]:
    connection = sqlite3.connect(str(path))
    try:
        return dict(connection.execute("SELECT tag,translation_cn FROM hot_tags"))
    finally:
        connection.close()


def _table_exists(path: Path, name: str) -> bool:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None
    finally:
        connection.close()


def test_default_dry_run_is_read_only_and_conservative(tmp_path: Path):
    database = tmp_path / "tags.sqlite"
    backup_dir = tmp_path / "backups"
    _make_database(database)
    before = _translations(database)

    report = repair.repair_database(database, backup_dir=backup_dir)

    assert report["mode"] == "dry-run"
    assert report["applied"] is False
    assert report["backup"] is None
    assert report["analysis"]["clear_candidates"] == 7
    assert report["analysis"]["clear_reason_counts"] == {
        "contains_hangul": 1,
        "contains_kana": 1,
        "control_character": 1,
        "known_cross_title_collision": 2,
        "translation_equals_unrelated_live_tag": 1,
        "unresolved_exact_tag_syntax": 1,
    }
    assert report["analysis"]["audit_reason_counts"] == {
        "han_parenthesis_shape_mismatch": 3,
        "translation_equals_related_live_tag": 1,
    }
    assert report["policy"]["latin_only_is_clear_reason"] is False
    assert report["policy"]["han_parenthesis_mismatch_action"] == "audit_only"
    assert report["before"]["fts_rows"] == 1
    assert report["after"]["fts_rows"] == 16
    assert _translations(database) == before
    assert not _table_exists(database, "tag_translation_history")
    assert not backup_dir.exists()

    clear_tags = {row["tag"] for row in report["analysis"]["clear_samples"]}
    assert clear_tags == {
        "kana_name",
        "hangul_name",
        "control_pollution",
        "ptilopsis_(arknights)",
        "chibi_miku",
        "lyn_(blade_&_soul)",
        "one_piece",
    }
    preserved = {row["tag"] for row in report["analysis"]["preserved_non_han_samples"]}
    assert {"vocaloid_(software)", "bdsm", "jojo"}.issubset(preserved)
    assert "artist_kana" not in clear_tags
    assert before["middle_dot_name"] == "桃乐丝・威斯特（美妙旋律）"


def test_apply_backs_up_histories_clears_and_preserves_identity(tmp_path: Path):
    database = tmp_path / "tags.sqlite"
    backup_dir = tmp_path / "backups"
    _make_database(database)
    before = _translations(database)

    report = repair.repair_database(database, apply=True, backup_dir=backup_dir)

    assert report["applied"] is True
    assert report["changes"] == {
        "history_rows_inserted": 7,
        "translation_values_cleared": 7,
        "fts_rows_rebuilt": 16,
    }
    assert report["after"]["total_tags"] == report["before"]["total_tags"] == 16
    assert report["after"]["fts_rows"] == 16
    assert report["after"]["fts_matches_hot_tags"] is True
    assert report["after_analysis"]["clear_candidates"] == 0
    assert report["integrity"] == {"before": "ok", "backup": "ok", "after": "ok"}

    translations = _translations(database)
    for tag in (
        "kana_name",
        "hangul_name",
        "control_pollution",
        "ptilopsis_(arknights)",
        "chibi_miku",
        "lyn_(blade_&_soul)",
        "one_piece",
    ):
        assert translations[tag] is None
    assert translations["vocaloid_(software)"] == "VOCALOID"
    assert translations["bdsm"] == "BDSM"
    assert translations["jojo"] == "JOJO"
    assert translations["hero_(series)"] == "英雄"
    assert translations["middle_dot_name"] == "桃乐丝・威斯特（美妙旋律）"
    assert translations["artist_kana"] == "アーティスト"

    connection = sqlite3.connect(str(database))
    try:
        history = connection.execute(
            "SELECT tag,old_translation_cn,new_translation_cn,change_type,reason,run_id "
            "FROM tag_translation_history ORDER BY tag"
        ).fetchall()
        assert len(history) == 7
        assert {row[0] for row in history} == {
            "kana_name",
            "hangul_name",
            "control_pollution",
            "ptilopsis_(arknights)",
            "chibi_miku",
            "lyn_(blade_&_soul)",
            "one_piece",
        }
        assert all(row[2] is None for row in history)
        assert all(row[3] == "clear_polluted_translation" for row in history)
        assert all(row[4].startswith("automatic_clear:") for row in history)
        assert all(row[5] == report["run_id"] for row in history)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()

    backup = Path(report["backup"]["path"])
    assert backup.is_file()
    assert len(report["backup"]["sha256"]) == 64
    assert _translations(backup) == before
    assert not _table_exists(backup, "tag_translation_history")


def test_second_apply_is_idempotent(tmp_path: Path):
    database = tmp_path / "tags.sqlite"
    backup_dir = tmp_path / "backups"
    _make_database(database)
    first = repair.repair_database(database, apply=True, backup_dir=backup_dir)
    second = repair.repair_database(database, apply=True, backup_dir=backup_dir)

    assert second["analysis"]["clear_candidates"] == 0
    assert second["changes"]["history_rows_inserted"] == 0
    assert second["changes"]["translation_values_cleared"] == 0
    assert second["after"]["history_rows"] == first["after"]["history_rows"]
    assert Path(first["backup"]["path"]) != Path(second["backup"]["path"])


def test_live_database_needs_second_explicit_confirmation(tmp_path: Path, monkeypatch):
    database = tmp_path / "tags.sqlite"
    backup_dir = tmp_path / "backups"
    _make_database(database)
    monkeypatch.setattr(repair, "DEFAULT_LIVE_DB", database.resolve())

    with pytest.raises(repair.PollutionRepairError, match="allow_live_db"):
        repair.repair_database(database, apply=True, backup_dir=backup_dir)
    assert not backup_dir.exists()
    assert _translations(database)["kana_name"] == "初音ミク"


def test_cli_defaults_to_dry_run_and_writes_auditable_outputs(tmp_path: Path, capsys):
    database = tmp_path / "tags.sqlite"
    report_path = tmp_path / "report.json"
    review_path = tmp_path / "review.jsonl"
    _make_database(database)

    result = repair.main(
        [
            "--db", str(database),
            "--json-report", str(report_path),
            "--review-jsonl", str(review_path),
        ]
    )
    assert result == 0
    stdout_report = json.loads(capsys.readouterr().out)
    file_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert stdout_report["mode"] == file_report["mode"] == "dry-run"
    assert stdout_report["analysis"]["clear_candidates"] == 7
    actions = {
        json.loads(line)["action"]
        for line in review_path.read_text(encoding="utf-8").splitlines()
    }
    assert actions == {"clear", "audit_only", "preserve_non_han"}
    assert _translations(database)["kana_name"] == "初音ミク"


@pytest.mark.parametrize("option", ["--json-report", "--review-jsonl"])
def test_cli_rejects_output_path_that_resolves_to_database(
    tmp_path: Path, capsys, option: str
):
    database = tmp_path / "tags.sqlite"
    _make_database(database)
    before = database.read_bytes()

    assert repair.main(["--db", str(database), option, str(database)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "resolves to target database" in error["error"]
    assert database.read_bytes() == before


@pytest.mark.parametrize("option", ["--json-report", "--review-jsonl"])
def test_cli_rejects_output_hardlink_to_database(
    tmp_path: Path, capsys, option: str
):
    database = tmp_path / "tags.sqlite"
    database_alias = tmp_path / "artifact.json"
    _make_database(database)
    before = database.read_bytes()
    os.link(database, database_alias)

    assert repair.main(["--db", str(database), option, str(database_alias)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "hard link" in error["error"]
    assert database.read_bytes() == before


def test_cli_rejects_report_review_hardlink_collision(tmp_path: Path, capsys):
    database = tmp_path / "tags.sqlite"
    report_path = tmp_path / "report.json"
    review_path = tmp_path / "review.jsonl"
    _make_database(database)
    before = database.read_bytes()
    report_path.write_text("sentinel", encoding="utf-8")
    os.link(report_path, review_path)

    assert repair.main([
        "--db", str(database),
        "--json-report", str(report_path),
        "--review-jsonl", str(review_path),
    ]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "hard-link collision" in error["error"]
    assert report_path.read_text(encoding="utf-8") == "sentinel"
    assert database.read_bytes() == before


def test_backup_writer_rejects_database_hardlink(tmp_path: Path):
    database = tmp_path / "tags.sqlite"
    backup_alias = tmp_path / "backup.sqlite"
    _make_database(database)
    before = database.read_bytes()
    os.link(database, backup_alias)

    with pytest.raises(repair.PollutionRepairError, match="target database"):
        repair._create_verified_backup(database, backup_alias)
    assert database.read_bytes() == before
