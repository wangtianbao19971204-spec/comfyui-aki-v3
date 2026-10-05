from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = PLUGIN_ROOT / "tools" / "apply_phase3_reviewed_tag_pack.py"
SPEC = importlib.util.spec_from_file_location("phase3_reviewed_tag_pack", TOOL_PATH)
assert SPEC and SPEC.loader
phase3 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = phase3
SPEC.loader.exec_module(phase3)


TRANSLATION_COLUMNS = [
    "tag",
    "category",
    "post_count",
    "translation_cn",
    "expected_translation_cn",
    "evidence_url",
    "evidence_kind",
    "confidence",
    "review_note",
]
ALIAS_COLUMNS = [
    "action",
    "alias",
    "canonical_tag",
    "source_url",
    "source_record_id",
    "verified_at_utc",
    "review_note",
    "clear_identity_translation",
    "expected_identity_translation",
]


def _write_csv(path: Path, columns, rows) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _translation_csv(path: Path, **overrides) -> Path:
    row = {
        "tag": "eye_mask",
        "category": "0",
        "post_count": "21275",
        "translation_cn": "眼罩",
        "expected_translation_cn": "",
        "evidence_url": "https://safebooru.donmai.us/wiki_pages/eye_mask",
        "evidence_kind": "danbooru_wiki_definition",
        "confidence": "A",
        "review_note": "人工复核",
    }
    row.update(overrides)
    return _write_csv(path, TRANSLATION_COLUMNS, [row])


def _alias_csv(
    path: Path,
    *,
    expected="宝可梦 日月",
    include_delete=True,
    delete_canonical="pokemon_sm",
) -> Path:
    rows = []
    if include_delete:
        rows.append(
            {
                "action": "delete",
                "alias": "pokemon_sun_and_moon",
                "canonical_tag": delete_canonical,
                "source_url": "https://danbooru.donmai.us/tag_aliases",
                "source_record_id": "old-direction",
                "verified_at_utc": "2026-07-22T12:00:00Z",
                "review_note": "删除反向别名",
                "clear_identity_translation": "false",
                "expected_identity_translation": "",
            }
        )
    rows.append(
        {
            "action": "upsert",
            "alias": "pokemon_sm",
            "canonical_tag": "pokemon_sun_and_moon",
            "source_url": "https://danbooru.donmai.us/tag_aliases",
            "source_record_id": "correct-direction",
            "verified_at_utc": "2026-07-22T12:00:00Z",
            "review_note": "缩写指向正式标签",
            "clear_identity_translation": "true",
            "expected_identity_translation": expected,
        }
    )
    return _write_csv(path, ALIAS_COLUMNS, rows)


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
            CREATE TABLE tag_aliases (
                alias TEXT PRIMARY KEY COLLATE NOCASE,
                canonical_tag TEXT NOT NULL,
                relation_type TEXT NOT NULL DEFAULT 'official_alias',
                source_name TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                declared_license TEXT NOT NULL DEFAULT '',
                source_revision TEXT NOT NULL DEFAULT '',
                source_sha256 TEXT NOT NULL DEFAULT '',
                imported_at INTEGER NOT NULL
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
                ("eye_mask", 0, 21275, None),
                ("brown_socks", 0, 5448, "棕色袜子"),
                ("artist_alpha", 1, 20000, None),
                ("pokemon_sm", 3, 30000, "宝可梦 日月"),
                ("pokemon_sun_and_moon", 3, 40000, "宝可梦 太阳/月亮"),
                ("legacy_a", 0, 100, None),
                ("legacy_b", 0, 90, None),
            ],
        )
        connection.executemany(
            """
            INSERT INTO tag_aliases(
                alias, canonical_tag, relation_type, source_name, source_url,
                declared_license, source_revision, source_sha256, imported_at
            ) VALUES (?, ?, 'official_alias', 'fixture', '', 'MIT', 'fixture', '', 1)
            """,
            [
                ("pokemon_sun_and_moon", "pokemon_sm"),
                # A historical cycle proves the migration audits legacy damage
                # without making zero global cycles a delivery precondition.
                ("legacy_a", "legacy_b"),
                ("legacy_b", "legacy_a"),
            ],
        )
        # Intentionally stale: apply mode must rebuild the actual FTS index.
        connection.execute(
            """
            INSERT INTO hot_tags_fts(rowid, tag, translation_cn)
            SELECT rowid, tag, translation_cn FROM hot_tags WHERE tag='brown_socks'
            """
        )
        connection.commit()
    finally:
        connection.close()


def _snapshot(path: Path):
    connection = sqlite3.connect(str(path))
    try:
        translations = connection.execute(
            "SELECT tag, translation_cn, last_updated FROM hot_tags ORDER BY tag"
        ).fetchall()
        aliases = connection.execute(
            "SELECT alias, canonical_tag FROM tag_aliases ORDER BY alias"
        ).fetchall()
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        fts_rows = connection.execute(
            "SELECT COUNT(*) FROM hot_tags_fts_docsize"
        ).fetchone()[0]
        return translations, aliases, tables, fts_rows
    finally:
        connection.close()


def test_default_dry_run_is_read_only_and_reports_pack_hash(tmp_path):
    database = tmp_path / "tags.db"
    translations = _translation_csv(tmp_path / "translations.csv")
    aliases = _alias_csv(tmp_path / "aliases.csv")
    backup_dir = tmp_path / "backups"
    _make_database(database)
    before = _snapshot(database)

    report = phase3.apply_reviewed_tag_pack(
        database,
        translation_csv=translations,
        alias_csv=aliases,
        backup_dir=backup_dir,
    )

    assert report["mode"] == "dry-run"
    assert report["applied"] is False
    assert report["backup"] is None
    assert len(report["pack"]["sha256"]) == 64
    assert report["planned_changes"] == {
        "translations_to_fill": 1,
        "translations_to_correct": 0,
        "translation_noops": 0,
        "identity_translations_to_clear": 1,
        "history_rows_to_insert": 2,
        "aliases_to_insert": 1,
        "aliases_to_update": 0,
        "aliases_to_delete": 1,
        "fts_rows_to_rebuild": 7,
    }
    assert report["changes"]["translations_corrected"] == 0
    assert report["before"]["alias_graph"] == {
        "alias_rows": 3,
        "chain_edges": 2,
        "cycle_components": 1,
        "cycle_nodes": 2,
    }
    assert report["after"]["alias_graph"] == report["before"]["alias_graph"]
    assert report["after_is_projection"] is True
    assert report["quick_check"] == {"before": "ok", "backup": None, "after": None}
    json.dumps(report, ensure_ascii=False)
    assert _snapshot(database) == before
    assert not backup_dir.exists()
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='tag_translation_history'"
        ).fetchone() is None
    finally:
        connection.close()


def test_apply_backs_up_histories_fills_repairs_alias_and_rebuilds_fts(tmp_path):
    database = tmp_path / "tags.db"
    translations = _translation_csv(tmp_path / "translations.csv")
    aliases = _alias_csv(tmp_path / "aliases.csv")
    backup_dir = tmp_path / "backups"
    _make_database(database)

    report = phase3.apply_reviewed_tag_pack(
        database,
        translation_csv=translations,
        alias_csv=aliases,
        apply=True,
        backup_dir=backup_dir,
    )

    assert report["applied"] is True
    assert report["changes"] == {
        "translations_filled": 1,
        "translations_corrected": 0,
        "translation_noops": 0,
        "identity_translations_cleared": 1,
        "history_rows_inserted": 2,
        "aliases_inserted": 1,
        "aliases_updated": 0,
        "aliases_deleted": 1,
        "fts_rows_rebuilt": 7,
    }
    assert report["integrity"] == {"before": "ok", "backup": "ok", "after": "ok"}
    assert report["quick_check"] == {"before": "ok", "backup": "ok", "after": "ok"}
    assert report["database_committed"] is True
    assert report["after"]["fts_matches_hot_tags"] is True

    connection = sqlite3.connect(str(database))
    try:
        values = dict(connection.execute("SELECT tag, translation_cn FROM hot_tags"))
        assert values["eye_mask"] == "眼罩"
        assert values["pokemon_sm"] is None
        assert values["brown_socks"] == "棕色袜子"
        assert dict(connection.execute("SELECT alias, canonical_tag FROM tag_aliases")) == {
            "pokemon_sm": "pokemon_sun_and_moon",
            "legacy_a": "legacy_b",
            "legacy_b": "legacy_a",
        }
        history = connection.execute(
            """
            SELECT tag, old_translation_cn, new_translation_cn, change_type
            FROM tag_translation_history ORDER BY tag
            """
        ).fetchall()
        assert history == [
            ("eye_mask", None, "眼罩", "phase3_translation_fill"),
            (
                "pokemon_sm",
                "宝可梦 日月",
                None,
                "alias_identity_translation_cleared",
            ),
        ]
        assert connection.execute("SELECT COUNT(*) FROM hot_tags_fts_docsize").fetchone()[0] == 7
        assert connection.execute(
            "SELECT tag FROM hot_tags_fts WHERE hot_tags_fts MATCH ?",
            ("眼罩",),
        ).fetchall() == [("eye_mask",)]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()

    backup = Path(report["backup"]["path"])
    assert backup.is_file()
    assert report["backup"]["method"] == "sqlite_backup_api"
    assert len(report["backup"]["sha256"]) == 64
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == report["backup"]["sha256"]
    backup_connection = sqlite3.connect(str(backup))
    try:
        assert backup_connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='eye_mask'"
        ).fetchone()[0] is None
        assert backup_connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='pokemon_sm'"
        ).fetchone()[0] == "宝可梦 日月"
        assert backup_connection.execute(
            "SELECT canonical_tag FROM tag_aliases WHERE alias='pokemon_sun_and_moon'"
        ).fetchone()[0] == "pokemon_sm"
        assert backup_connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='tag_translation_history'"
        ).fetchone() is None
        assert backup_connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup_connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        backup_connection.close()


def test_existing_translation_conflict_is_rejected_without_writes(tmp_path):
    database = tmp_path / "tags.db"
    translations = _translation_csv(
        tmp_path / "translations.csv",
        tag="brown_socks",
        post_count="5448",
        translation_cn="褐色袜子",
    )
    _make_database(database)
    before = _snapshot(database)

    with pytest.raises(phase3.PackValidationError, match="refusing to overwrite"):
        phase3.apply_reviewed_tag_pack(database, translation_csv=translations)

    assert _snapshot(database) == before


def test_guarded_existing_translation_correction_is_applied_and_recorded(tmp_path):
    database = tmp_path / "tags.db"
    translations = _translation_csv(
        tmp_path / "translations.csv",
        tag="brown_socks",
        post_count="5448",
        translation_cn="褐色袜子",
        expected_translation_cn="棕色袜子",
    )
    _make_database(database)

    report = phase3.apply_reviewed_tag_pack(
        database,
        translation_csv=translations,
        apply=True,
        backup_dir=tmp_path / "backups",
    )

    assert report["changes"]["translations_corrected"] == 1
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='brown_socks'"
        ).fetchone()[0] == "褐色袜子"
        assert connection.execute(
            "SELECT old_translation_cn,new_translation_cn,change_type "
            "FROM tag_translation_history WHERE tag='brown_socks'"
        ).fetchone() == (
            "棕色袜子",
            "褐色袜子",
            "phase3_translation_correction",
        )
    finally:
        connection.close()


def test_guarded_existing_translation_correction_rejects_stale_old_value(tmp_path):
    database = tmp_path / "tags.db"
    translations = _translation_csv(
        tmp_path / "translations.csv",
        tag="brown_socks",
        post_count="5448",
        translation_cn="褐色袜子",
        expected_translation_cn="陈旧旧值",
    )
    _make_database(database)
    before = _snapshot(database)

    with pytest.raises(phase3.PackValidationError, match="expected translation conflict"):
        phase3.apply_reviewed_tag_pack(database, translation_csv=translations)

    assert _snapshot(database) == before


def test_post_count_conflict_is_rejected_without_writes(tmp_path):
    database = tmp_path / "tags.db"
    translations = _translation_csv(
        tmp_path / "translations.csv",
        tag="eye_mask",
        post_count="21274",
        translation_cn="眼罩",
    )
    _make_database(database)
    before = _snapshot(database)

    with pytest.raises(phase3.PackValidationError, match="post_count conflict"):
        phase3.apply_reviewed_tag_pack(database, translation_csv=translations)

    assert _snapshot(database) == before


def test_duplicate_translation_rows_cannot_drop_a_guard(tmp_path):
    database = tmp_path / "tags.db"
    row = {
        "tag": "eye_mask",
        "category": "0",
        "post_count": "",
        "translation_cn": "眼罩",
        "expected_translation_cn": "",
        "evidence_url": "https://safebooru.donmai.us/wiki_pages/eye_mask",
        "evidence_kind": "danbooru_wiki_definition",
        "confidence": "A",
        "review_note": "人工复核",
    }
    guarded_row = dict(row)
    guarded_row["post_count"] = "21275"
    translations = _write_csv(
        tmp_path / "translations.csv",
        TRANSLATION_COLUMNS,
        [row, guarded_row],
    )
    _make_database(database)
    before = _snapshot(database)

    with pytest.raises(
        phase3.PackValidationError,
        match="conflicting duplicate translation rows",
    ):
        phase3.apply_reviewed_tag_pack(database, translation_csv=translations)

    assert _snapshot(database) == before


def test_artist_translation_and_artist_alias_are_forbidden(tmp_path):
    database = tmp_path / "tags.db"
    _make_database(database)
    artist_translation = _translation_csv(
        tmp_path / "artist.csv",
        tag="artist_alpha",
        category="1",
        translation_cn="艺术家甲",
    )
    with pytest.raises(phase3.PackValidationError, match="artist category 1"):
        phase3.apply_reviewed_tag_pack(database, translation_csv=artist_translation)

    artist_alias = _write_csv(
        tmp_path / "artist-alias.csv",
        ALIAS_COLUMNS,
        [
            {
                "action": "upsert",
                "alias": "artist_a",
                "canonical_tag": "artist_alpha",
                "source_url": "",
                "source_record_id": "manual",
                "verified_at_utc": "",
                "review_note": "",
                "clear_identity_translation": "false",
                "expected_identity_translation": "",
            }
        ],
    )
    with pytest.raises(phase3.PackValidationError, match="artist alias canonical"):
        phase3.apply_reviewed_tag_pack(database, alias_csv=artist_alias)


def test_alias_upsert_must_be_one_hop_and_identity_clear_is_exact(tmp_path):
    database = tmp_path / "tags.db"
    _make_database(database)
    before = _snapshot(database)

    # Without deleting the old reverse relation, the proposed canonical is
    # itself still an alias.  The reviewed upsert is therefore a chain/cycle.
    chained = _alias_csv(tmp_path / "chained.csv", include_delete=False)
    with pytest.raises(phase3.PackValidationError, match="directly to a non-alias"):
        phase3.apply_reviewed_tag_pack(database, alias_csv=chained)

    mismatch = _alias_csv(tmp_path / "mismatch.csv", expected="错误的旧值")
    with pytest.raises(phase3.PackValidationError, match="expected value does not match"):
        phase3.apply_reviewed_tag_pack(database, alias_csv=mismatch)

    wrong_delete_guard = _alias_csv(
        tmp_path / "wrong-delete.csv", delete_canonical="legacy_a"
    )
    with pytest.raises(phase3.PackValidationError, match="alias delete conflict"):
        phase3.apply_reviewed_tag_pack(database, alias_csv=wrong_delete_guard)

    assert _snapshot(database) == before


def test_live_apply_requires_second_confirmation_and_cli_defaults_to_dry_run(
    monkeypatch, tmp_path, capsys
):
    database = tmp_path / "live-tags-cache.db"
    translations = _translation_csv(tmp_path / "translations.csv")
    backup_dir = tmp_path / "backups"
    _make_database(database)
    monkeypatch.setattr(phase3, "DEFAULT_LIVE_DB", database.resolve())

    with pytest.raises(phase3.TargetDatabaseError, match="allow_live_db=True"):
        phase3.apply_reviewed_tag_pack(
            database,
            translation_csv=translations,
            apply=True,
            backup_dir=backup_dir,
        )
    assert not backup_dir.exists()

    assert phase3.main(
        ["--db", str(database), "--translation-csv", str(translations)]
    ) == 0
    cli_report = json.loads(capsys.readouterr().out)
    assert cli_report["mode"] == "dry-run"
    assert cli_report["applied"] is False

    report = phase3.apply_reviewed_tag_pack(
        database,
        translation_csv=translations,
        apply=True,
        allow_live_db=True,
        backup_dir=backup_dir,
    )
    assert report["applied"] is True
    assert report["is_plugin_live_db"] is True
    assert Path(report["backup"]["path"]).is_file()


def test_csv_parse_and_hash_use_the_same_single_immutable_snapshot(
    monkeypatch, tmp_path
):
    translations = _translation_csv(tmp_path / "translations.csv")
    original_bytes = translations.read_bytes()
    original_reader = phase3._read_csv_bytes
    calls = []

    def read_then_replace(path):
        immutable = original_reader(path)
        calls.append(Path(path))
        _translation_csv(
            Path(path),
            tag="brown_socks",
            post_count="5448",
            translation_cn="棕色袜子",
        )
        return immutable

    monkeypatch.setattr(phase3, "_read_csv_bytes", read_then_replace)
    pack = phase3.load_reviewed_pack(translation_csv=translations)

    assert len(calls) == 1
    assert pack.translations[0].tag == "eye_mask"
    assert pack.translations[0].translation_cn == "眼罩"
    assert pack.translation_sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert translations.read_bytes() != original_bytes


def test_apply_rolls_back_if_transaction_verification_fails(monkeypatch, tmp_path):
    database = tmp_path / "tags.db"
    translations = _translation_csv(tmp_path / "translations.csv")
    backup_dir = tmp_path / "backups"
    _make_database(database)
    before = _snapshot(database)
    original_apply = phase3._apply_plan

    def apply_then_fail(*args, **kwargs):
        original_apply(*args, **kwargs)
        raise phase3.TargetDatabaseError("forced verification failure")

    monkeypatch.setattr(phase3, "_apply_plan", apply_then_fail)
    with pytest.raises(phase3.TargetDatabaseError, match="forced verification failure"):
        phase3.apply_reviewed_tag_pack(
            database,
            translation_csv=translations,
            apply=True,
            backup_dir=backup_dir,
        )

    assert _snapshot(database) == before
    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    assert _snapshot(backups[0]) == before


def test_report_write_failure_after_commit_has_unambiguous_success_state(
    monkeypatch, tmp_path, capsys
):
    database = tmp_path / "tags.db"
    translations = _translation_csv(tmp_path / "translations.csv")
    report_path = tmp_path / "reports" / "phase3.json"
    backup_dir = tmp_path / "backups"
    _make_database(database)

    def fail_report_write(path, report):
        raise OSError("simulated disk failure after preflight")

    monkeypatch.setattr(phase3, "_write_json_report", fail_report_write)
    exit_code = phase3.main(
        [
            "--db",
            str(database),
            "--translation-csv",
            str(translations),
            "--apply",
            "--backup-dir",
            str(backup_dir),
            "--report",
            str(report_path),
        ]
    )
    captured = capsys.readouterr()
    success_report = json.loads(captured.out)
    auxiliary_error = json.loads(captured.err)

    assert exit_code == 3
    assert success_report["success"] is True
    assert success_report["applied"] is True
    assert success_report["database_committed"] is True
    assert success_report["report_output"]["written"] is False
    assert success_report["warnings"]
    assert auxiliary_error["success"] is True
    assert auxiliary_error["error_code"] == "report_write_failed_after_migration"
    assert auxiliary_error["database_committed"] is True
    assert auxiliary_error["applied"] is True
    assert not report_path.exists()
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='eye_mask'"
        ).fetchone()[0] == "眼罩"
    finally:
        connection.close()
    assert len(list(backup_dir.glob("*.db"))) == 1


def test_report_target_is_preflighted_before_apply(tmp_path, capsys):
    database = tmp_path / "tags.db"
    translations = _translation_csv(tmp_path / "translations.csv")
    backup_dir = tmp_path / "backups"
    _make_database(database)
    before = _snapshot(database)

    exit_code = phase3.main(
        [
            "--db",
            str(database),
            "--translation-csv",
            str(translations),
            "--apply",
            "--backup-dir",
            str(backup_dir),
            "--report",
            str(database),
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert error["success"] is False
    assert error["database_committed"] is False
    assert error["applied"] is False
    assert _snapshot(database) == before
    assert not backup_dir.exists()
