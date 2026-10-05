from __future__ import annotations

import importlib.util
import csv
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PLUGIN_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))
MODULE_PATH = TOOLS_DIR / "generate_tag_transformers_translations.py"
SPEC = importlib.util.spec_from_file_location(
    "generate_tag_transformers_translations", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_candidate_selection_excludes_artist_and_other_disallowed_categories(
    tmp_path: Path,
):
    database = tmp_path / "tags.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE hot_tags(
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
            ("allowed_general", 0, 100, None),
            ("blocked_artist", 1, 90, None),
            ("blocked_category_two", 2, 80, None),
            ("allowed_copyright", 3, 70, None),
            ("allowed_character_(series)", 4, 60, None),
            ("allowed_meta", 5, 50, None),
            ("already_translated", 0, 40, "已有翻译"),
        ],
    )
    connection.commit()
    connection.close()

    rows, counts = MODULE.select_candidates(
        database,
        curated={},
        max_words=6,
        max_tag_chars=64,
        limit=None,
    )

    assert [row["tag"] for row in rows] == [
        "allowed_general",
        "allowed_copyright",
        "allowed_character_(series)",
        "allowed_meta",
    ]
    assert {row["category"] for row in rows} == {0, 3, 4, 5}
    assert counts["skipped_disallowed_category"] == 2


def test_parse_model_output_accepts_h_m_and_l_confidence_markers():
    assert MODULE.parse_model_output("striped_clothes", "条纹衣物\tH") == (
        "条纹衣物",
        "H",
        "accepted",
    )
    assert MODULE.parse_model_output("black_footwear", "黑色鞋类|m") == (
        "黑色鞋类",
        "M",
        "accepted",
    )
    assert MODULE.parse_model_output("unknown_name", "未知专名｜l") == (
        "未知专名",
        "L",
        "accepted",
    )
    assert MODULE.parse_model_output("wuthering_waves", "鸣潮<TAB>H") == (
        "鸣潮",
        "H",
        "accepted",
    )
    assert MODULE.parse_model_output("wuthering_waves", "鸣潮<H>") == (
        None,
        None,
        "format",
    )


def test_candidate_selection_supports_safe_general_meta_subset(tmp_path: Path):
    database = tmp_path / "tags.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT PRIMARY KEY, category INTEGER, post_count INTEGER, translation_cn TEXT)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?, NULL)",
        [("general", 0, 4), ("artist", 1, 3), ("work", 3, 2), ("meta", 5, 1)],
    )
    connection.commit()
    connection.close()

    rows, counts = MODULE.select_candidates(
        database,
        curated={},
        max_words=6,
        max_tag_chars=64,
        limit=None,
        allowed_categories=frozenset({0, 5}),
    )

    assert [row["tag"] for row in rows] == ["general", "meta"]
    assert counts["skipped_disallowed_category"] == 2


def test_parse_model_output_preserves_every_parenthesized_qualifier():
    assert MODULE.parse_model_output(
        "alice_(series)", "爱丽丝（某系列）\tH"
    ) == ("爱丽丝(某系列)", "H", "accepted")
    assert MODULE.parse_model_output(
        "alice_(series)_(alternate)", "爱丽丝（某系列）（异装）\tM"
    ) == ("爱丽丝(某系列)(异装)", "M", "accepted")

    assert MODULE.parse_model_output("alice_(series)", "爱丽丝\tH") == (
        None,
        "H",
        "qualifier_lost",
    )
    assert MODULE.parse_model_output("alice_(series)", "爱丽丝(某系列\tH") == (
        None,
        "H",
        "qualifier_lost",
    )
    assert MODULE.parse_model_output("alice", "爱丽丝(某系列)\tH") == (
        None,
        "H",
        "qualifier_lost",
    )


def test_transformers_main_checks_review_and_output_paths_before_model_loading(
    tmp_path: Path,
):
    database = tmp_path / "tags.db"
    model = tmp_path / "model"
    reference = tmp_path / "reference.csv"
    database.write_bytes(b"database-sentinel")
    model.mkdir()
    reference.write_text("tag,translation_cn\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="reference_csv"):
        MODULE.main(
            [
                "--db", str(database),
                "--model", str(model),
                "--output", str(tmp_path / "output.csv"),
                "--report", str(tmp_path / "report.json"),
                "--review-queue", str(reference),
                "--reference-csv", str(reference),
            ]
        )
    assert reference.read_text(encoding="utf-8") == "tag,translation_cn\n"


def test_transformers_artifact_cannot_be_written_inside_model_snapshot(tmp_path: Path):
    database = tmp_path / "tags.db"
    model = tmp_path / "model"
    database.write_bytes(b"database-sentinel")
    model.mkdir()

    with pytest.raises(SystemExit, match="protected directory model"):
        MODULE.main(
            [
                "--db", str(database),
                "--model", str(model),
                "--output", str(model / "config.json"),
                "--report", str(tmp_path / "report.json"),
                "--review-queue", str(tmp_path / "review.jsonl"),
            ]
        )


def test_load_references_requires_standard_columns_and_deduplicates(tmp_path: Path):
    reference = tmp_path / "reference.csv"
    with reference.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("tag", "translation_cn"))
        writer.writeheader()
        writer.writerow({"tag": "Wuthering Waves", "translation_cn": "鸣潮"})
        writer.writerow({"tag": "wuthering_waves", "translation_cn": "错误覆盖"})

    assert MODULE.load_references(reference) == {"wuthering_waves": "鸣潮"}
