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
MODULE_PATH = PLUGIN_ROOT / "tools" / "build_boorutagcart_translation_pack.py"
SPEC = importlib.util.spec_from_file_location(
    "build_boorutagcart_translation_pack", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
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
            ("unique_general", 0, 160, None),
            ("blocked_artist", 1, 150, None),
            ("blocked_category_two", 2, 140, None),
            ("work_(series)", 3, 130, None),
            ("alice_(game)", 4, 120, None),
            ("bob_(game)", 4, 115, None),
            ("metadata_tag", 5, 110, None),
            ("already_translated", 0, 100, "已有翻译"),
            ("ambiguous_tag", 0, 90, None),
            ("one_valid_tag", 0, 80, None),
            ("mixed_kana", 0, 70, None),
            ("mixed_hangul", 0, 60, None),
            ("one_two_three_four_five_six_seven", 0, 50, None),
            ("extra_qualifier", 0, 40, None),
        ],
    )
    connection.commit()
    connection.close()


def write_headerless_source(path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(
            [
                ("unique_general", "唯一翻译", "general"),
                ("blocked_artist", "艺术家译名", "artist"),
                ("blocked_category_two", "旧类别", "unknown"),
                ("work_(series)", "作品（系列）", "copyright"),
                ("alice_(game)", "爱丽丝", "lost qualifier"),
                ("bob_(game)", "鲍勃（游戏）", "character"),
                ("metadata_tag", "元标签", "meta"),
                ("already_translated", "替换译名", "must preserve"),
                ("ambiguous_tag", "候选一|候选二", "ambiguous"),
                ("one_valid_tag", "唯一候选|カナ", "one valid"),
                ("mixed_kana", "中文カナ", "kana"),
                ("mixed_hangul", "中文한글", "hangul"),
                (
                    "one_two_three_four_five_six_seven",
                    "七个词",
                    "too many words",
                ),
                ("extra_qualifier", "额外（限定）", "extra qualifier"),
                ("not_in_live", "不存在", "not live"),
                ("malformed", "only two columns"),
            ]
        )


def test_pinned_source_metadata_is_exact():
    assert MODULE.SOURCE_REVISION == "18bd2b3d81aeceade9fd24559d8957dafa22e1a3"
    assert MODULE.SOURCE_SHA256 == (
        "41869c065b0c067f2e5e88e2d1152a3509da53bfc71c87ab6a9beff1d1fca1a1"
    )
    assert MODULE.SOURCE_LICENSE == "GPL-3.0"
    assert MODULE.SOURCE_REVISION in MODULE.SOURCE_BLOB_URL
    assert MODULE.SOURCE_REVISION in MODULE.SOURCE_RAW_URL


def test_build_pack_is_read_only_and_applies_all_quality_guards(tmp_path: Path):
    database = tmp_path / "tags.db"
    source = tmp_path / "reference.csv"
    output = tmp_path / "output" / "translations.csv"
    report_path = tmp_path / "output" / "report.json"
    review_path = tmp_path / "output" / "review.jsonl"
    make_database(database)
    write_headerless_source(source)
    database_before = database.read_bytes()
    source_sha256 = MODULE.file_sha256(source)

    report = MODULE.build_pack(
        source,
        database,
        output,
        report_path,
        review_path,
        expected_sha256=source_sha256,
    )

    assert database.read_bytes() == database_before
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["tag"]: row for row in csv.DictReader(handle)}
    assert set(rows) == {
        "unique_general",
        "work_(series)",
        "bob_(game)",
        "metadata_tag",
        "one_valid_tag",
    }
    assert rows["work_(series)"]["translation_cn"] == "作品(系列)"
    assert rows["bob_(game)"]["category"] == "4"
    assert rows["one_valid_tag"]["translation_cn"] == "唯一候选"
    assert all(int(row["category"]) in {0, 3, 4, 5} for row in rows.values())
    assert "blocked_artist" not in rows

    review_rows = [
        json.loads(line)
        for line in review_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    reviews_by_tag = {
        row["tag"]: row for row in review_rows if isinstance(row.get("tag"), str)
    }
    assert reviews_by_tag["ambiguous_tag"]["reason"] == "ambiguous_candidates"
    assert reviews_by_tag["ambiguous_tag"]["valid_candidates"] == [
        "候选一",
        "候选二",
    ]
    assert reviews_by_tag["alice_(game)"]["reason"] == "no_valid_candidate"
    assert reviews_by_tag["alice_(game)"]["rejected_candidates"][0][
        "reason"
    ] == "qualifier_mismatch"
    assert reviews_by_tag["mixed_kana"]["rejected_candidates"][0][
        "reason"
    ] == "contains_kana"
    assert reviews_by_tag["mixed_hangul"]["rejected_candidates"][0][
        "reason"
    ] == "contains_hangul"
    assert reviews_by_tag["one_two_three_four_five_six_seven"]["reason"] == (
        "tag_word_count"
    )
    assert "blocked_artist" not in reviews_by_tag
    assert any(row.get("reason") == "malformed_row" for row in review_rows)

    report_from_disk = json.loads(report_path.read_text(encoding="utf-8"))
    assert report == report_from_disk
    assert report["mode"] == "build_only"
    assert report["database_mutated"] is False
    assert report["database"]["read_only"] is True
    assert report["database"]["query_only"] is True
    assert report["source"]["actual_sha256"] == source_sha256
    assert report["source_row_counts"] == {
        "artist_rows": 1,
        "disallowed_category_rows": 1,
        "eligible_database_rows": 11,
        "existing_translation_rows": 1,
        "input_rows": 16,
        "malformed_rows": 1,
        "not_in_live_database_rows": 1,
    }
    assert report["decision_counts"] == {
        "accepted_unique_candidate": 5,
        "review_ambiguous_candidates": 1,
        "review_no_valid_candidate": 4,
        "review_tag_word_count": 1,
    }
    assert report["output"]["rows"] == 5
    assert report["output"]["category_counts"] == {
        "0": 2,
        "3": 1,
        "4": 1,
        "5": 1,
    }
    assert report["review"]["rows"] == 7


def test_hash_mismatch_fails_before_creating_outputs(tmp_path: Path):
    database = tmp_path / "tags.db"
    source = tmp_path / "reference.csv"
    output = tmp_path / "translations.csv"
    report = tmp_path / "report.json"
    review = tmp_path / "review.jsonl"
    make_database(database)
    write_headerless_source(source)

    with pytest.raises(MODULE.PackBuildError, match="SHA256 mismatch"):
        MODULE.build_pack(
            source,
            database,
            output,
            report,
            review,
            expected_sha256="0" * 64,
        )

    assert not output.exists()
    assert not report.exists()
    assert not review.exists()


def test_candidate_parentheses_must_match_complete_source_groups():
    assert MODULE.validate_candidate("alice_(game)", "爱丽丝（游戏）") == (
        "爱丽丝(游戏)",
        "accepted",
    )
    assert MODULE.validate_candidate("alice_(game)", "爱丽丝") == (
        None,
        "qualifier_mismatch",
    )


def test_build_pack_rejects_hardlinks_to_inputs_and_between_artifacts(tmp_path: Path):
    database = tmp_path / "tags.db"
    source = tmp_path / "reference.csv"
    make_database(database)
    write_headerless_source(source)
    database_before = database.read_bytes()
    source_hash = MODULE.file_sha256(source)

    output = tmp_path / "database-hardlink.csv"
    os.link(database, output)
    with pytest.raises(MODULE.PackBuildError, match="hard-link collision"):
        MODULE.build_pack(
            source,
            database,
            output,
            tmp_path / "report.json",
            tmp_path / "review.jsonl",
            expected_sha256=source_hash,
        )
    assert database.read_bytes() == database_before

    source_alias = tmp_path / "source-hardlink.csv"
    os.link(source, source_alias)
    with pytest.raises(MODULE.PackBuildError, match="hard-link collision"):
        MODULE.build_pack(
            source,
            database,
            source_alias,
            tmp_path / "report.json",
            tmp_path / "review.jsonl",
            expected_sha256=source_hash,
        )
    assert MODULE.file_sha256(source) == source_hash

    report = tmp_path / "shared-report.json"
    review = tmp_path / "shared-review.jsonl"
    report.write_text("sentinel", encoding="utf-8")
    os.link(report, review)
    with pytest.raises(MODULE.PackBuildError, match="hard-link collision"):
        MODULE.build_pack(
            source,
            database,
            tmp_path / "translations.csv",
            report,
            review,
            expected_sha256=source_hash,
        )
    assert report.read_text(encoding="utf-8") == "sentinel"
    assert MODULE.validate_candidate("alice_(game)", "爱丽丝（游戏") == (
        None,
        "qualifier_mismatch",
    )
