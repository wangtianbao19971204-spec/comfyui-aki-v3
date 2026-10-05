import importlib.util
import os
import sqlite3
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PLUGIN_ROOT / "tools" / "generate_tag_machine_translations.py"
SPEC = importlib.util.spec_from_file_location("generate_tag_machine_translations", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def make_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE hot_tags (
            tag TEXT PRIMARY KEY,
            category INTEGER NOT NULL,
            post_count INTEGER NOT NULL,
            translation_cn TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?, ?)",
        [
            ("short_general", 0, 100, None),
            ("blocked_artist", 1, 90, None),
            ("known_static", 4, 80, None),
            ("already_done", 3, 70, "已有译文"),
            ("one_two_three_four_five_six_seven", 0, 60, None),
            ("character_name_(series)", 4, 50, None),
        ],
    )
    connection.commit()
    connection.close()


def test_selection_never_includes_artist_and_preserves_curated(tmp_path):
    db_path = tmp_path / "tags.db"
    make_db(db_path)
    rows, report = MODULE.select_candidates(
        db_path,
        {"known_static": "已有静态译文"},
        max_words=6,
        max_tag_chars=64,
    )

    assert [row["tag"] for row in rows] == ["short_general", "character_name_(series)"]
    assert report["skipped_disallowed_category"] == 1
    assert report["skipped_curated_fallback"] == 1
    assert report["skipped_word_count"] == 1


def test_translation_validation_rejects_unsafe_output():
    assert MODULE.validate_translation("striped_clothes", 0, "条纹衣服")[0] == "条纹衣服"
    assert MODULE.validate_translation("name_(series)", 4, "角色名")[1] == "qualifier_lost"
    assert MODULE.validate_translation("name", 4, "Name名字")[1] == "latin_residue"
    assert MODULE.validate_translation("name", 4, "キャラ")[1] == "no_han"


def test_nearby_tags_keep_distinct_identities():
    assert MODULE.normalize_tag("one piece") == "one_piece"
    assert MODULE.normalize_tag("one-piece") == "one-piece"


def test_category_subset_can_target_general_and_meta_without_weakening_artist_guard(tmp_path):
    db_path = tmp_path / "tags.db"
    make_db(db_path)
    rows, report = MODULE.select_candidates(
        db_path,
        {},
        max_words=6,
        max_tag_chars=64,
        allowed_categories=frozenset({0, 5}),
    )

    assert [row["tag"] for row in rows] == ["short_general"]
    assert report["skipped_disallowed_category"] == 3


def test_parse_categories_fails_closed_for_artist_or_unknown_categories():
    assert MODULE.parse_categories("0,5") == frozenset({0, 5})
    with pytest.raises(ValueError, match="artist is forbidden"):
        MODULE.parse_categories("0,1,5")
    with pytest.raises(ValueError, match="artist is forbidden"):
        MODULE.parse_categories("0,2")


def test_artifact_guard_rejects_database_hardlinks_and_artifact_aliases(tmp_path):
    database = tmp_path / "tags.db"
    database.write_bytes(b"database-sentinel")
    output = tmp_path / "output.csv"
    report = tmp_path / "report.json"
    try:
        os.link(database, output)
    except OSError as exc:  # pragma: no cover - filesystem capability boundary
        pytest.skip("hard links are unavailable: {}".format(exc))

    with pytest.raises(MODULE.ArtifactPathError, match="database"):
        MODULE.validate_artifact_paths(
            {"output": output, "report": report},
            {"database": database},
        )
    assert database.read_bytes() == b"database-sentinel"

    output.unlink()
    output.write_text("checkpoint\n", encoding="utf-8")
    os.link(output, report)
    with pytest.raises(MODULE.ArtifactPathError, match="must be distinct"):
        MODULE.validate_artifact_paths(
            {"output": output, "report": report},
            {"database": database},
        )


def test_artifact_guard_rejects_files_inside_model_or_source_roots(tmp_path):
    model_root = tmp_path / "model"
    source_root = tmp_path / "sources"
    model_root.mkdir()
    source_root.mkdir()

    with pytest.raises(MODULE.ArtifactPathError, match="model"):
        MODULE.validate_artifact_paths(
            {"output": model_root / "config.json"},
            {},
            protected_roots={"model": model_root, "sources": source_root},
        )
    with pytest.raises(MODULE.ArtifactPathError, match="sources"):
        MODULE.validate_artifact_paths(
            {"output": source_root / "all_tags_cn.json"},
            {},
            protected_roots={"model": model_root, "sources": source_root},
        )


def test_machine_main_checks_artifact_paths_before_model_loading(tmp_path):
    database = tmp_path / "tags.db"
    database.write_bytes(b"database-sentinel")
    model = tmp_path / "model"
    model.mkdir()

    with pytest.raises(SystemExit, match="must not overwrite input database"):
        MODULE.main(
            [
                "--db", str(database),
                "--model", str(model),
                "--output", str(database),
                "--report", str(tmp_path / "report.json"),
            ]
        )
    assert database.read_bytes() == b"database-sentinel"
