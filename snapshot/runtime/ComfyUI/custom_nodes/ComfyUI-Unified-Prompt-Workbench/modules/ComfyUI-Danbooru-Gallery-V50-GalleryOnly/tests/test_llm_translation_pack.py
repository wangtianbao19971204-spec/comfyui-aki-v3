import importlib.util
import csv
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PLUGIN_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))
MODULE_PATH = TOOLS_DIR / "generate_tag_llm_translations.py"
SPEC = importlib.util.spec_from_file_location("generate_tag_llm_translations", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_llm_validation_keeps_identity_qualifiers():
    assert MODULE.validate_translation("alice_(series)", "爱丽丝（某系列）")[0] == "爱丽丝(某系列)"
    assert MODULE.validate_translation("alice_(series)", "爱丽丝")[1] == "qualifier_lost"
    assert MODULE.validate_translation("alice", "アリス")[1] == "no_han"
    assert MODULE.validate_translation("alice_(series)", "爱丽丝(某系列")[1] == "qualifier_lost"


def test_llm_decision_parser_requires_confidence_and_exact_keys():
    assert MODULE.parse_translation_decision(
        "wuthering_waves", {"translation_cn": "鸣潮", "confidence": "h"}
    ) == ("鸣潮", "H", "accepted")
    assert MODULE.parse_translation_decision(
        "wuthering_waves", {"translation_cn": "鸣潮"}
    ) == (None, None, "decision_keys")
    assert MODULE.parse_translation_decision("wuthering_waves", "鸣潮\tM") == (
        "鸣潮",
        "M",
        "accepted",
    )
    assert MODULE.parse_translation_decision("wuthering_waves", "H|鸣潮") == (
        "鸣潮",
        "H",
        "accepted",
    )
    assert MODULE.parse_translation_decision("wuthering_waves", "鸣潮") == (
        None,
        None,
        "decision_format",
    )


def test_llm_reference_loader_uses_first_normalized_tag(tmp_path):
    path = tmp_path / "reference.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("tag", "translation_cn"))
        writer.writeheader()
        writer.writerow({"tag": "Wuthering Waves", "translation_cn": "鸣潮"})
        writer.writerow({"tag": "wuthering_waves", "translation_cn": "错误"})
    assert MODULE.load_references(path) == {"wuthering_waves": "鸣潮"}


def test_llm_selection_excludes_artist_and_existing_curated(tmp_path):
    db_path = tmp_path / "tags.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT PRIMARY KEY, category INTEGER, post_count INTEGER, translation_cn TEXT)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?, ?)",
        [
            ("good_general", 0, 100, None),
            ("blocked_artist", 1, 90, None),
            ("static_character", 4, 80, None),
            ("already_translated", 3, 70, "已有"),
        ],
    )
    connection.commit()
    connection.close()

    rows, counts = MODULE.select_candidates(
        db_path, {"static_character": "静态角色"}, 6, 64, None
    )
    assert [row["tag"] for row in rows] == ["good_general"]
    assert counts["skipped_disallowed_category"] == 1
    assert counts["skipped_curated_fallback"] == 1


def test_candidate_csv_requires_tag_and_preserves_first_exact_occurrence(tmp_path):
    invalid = tmp_path / "invalid.csv"
    invalid.write_text("name\nmissing_tag_column\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a tag column"):
        MODULE.load_candidate_tags(invalid)

    candidate_csv = tmp_path / "candidates.csv"
    with candidate_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("tag", "translation_cn"))
        writer.writeheader()
        writer.writerow({"tag": "third_tag", "translation_cn": "unused"})
        writer.writerow({"tag": " first_tag ", "translation_cn": "unused"})
        writer.writerow({"tag": "third_tag", "translation_cn": "duplicate"})
        writer.writerow({"tag": "", "translation_cn": "empty"})

    tags, counts = MODULE.load_candidate_tags(candidate_csv)

    assert tags == ["third_tag", "first_tag"]
    assert counts == {
        "input_rows": 4,
        "duplicate_tags": 1,
        "empty_tags": 1,
        "unique_tags": 2,
    }
    provenance = MODULE.candidate_csv_provenance(candidate_csv, counts)
    assert provenance["candidate_csv"] == str(candidate_csv.resolve())
    assert provenance["candidate_csv_sha256"] == MODULE.file_sha256(candidate_csv)
    assert provenance["candidate_csv_input_rows"] == 4
    assert provenance["candidate_csv_unique_tags"] == 2
    assert provenance["candidate_csv_duplicate_tags"] == 1
    assert provenance["candidate_csv_empty_tags"] == 1


def test_candidate_csv_selection_is_ordered_and_cannot_bypass_db_guards(tmp_path):
    db_path = tmp_path / "tags.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT PRIMARY KEY, category INTEGER, post_count INTEGER, translation_cn TEXT)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?, ?)",
        [
            ("first_general", 0, 1000, None),
            ("blocked_artist", 1, 900, None),
            ("blocked_unknown", 2, 800, None),
            ("curated_character", 4, 700, None),
            ("last_character", 4, 600, None),
            ("already_translated", 3, 500, "已有翻译"),
            ("third_meta", 5, 1, None),
        ],
    )
    connection.commit()
    connection.close()

    rows, counts = MODULE.select_candidates(
        db_path,
        curated={"curated_character": "已有静态翻译"},
        max_words=6,
        max_tag_chars=64,
        limit=None,
        candidate_tags=[
            "third_meta",
            "blocked_artist",
            "first_general",
            "first_general",
            "already_translated",
            "absent_tag",
            "curated_character",
            "blocked_unknown",
            "last_character",
        ],
    )

    assert [row["tag"] for row in rows] == [
        "third_meta",
        "first_general",
        "last_character",
    ]
    assert [row["category"] for row in rows] == [5, 0, 4]
    assert counts["skipped_candidate_duplicate"] == 1
    assert counts["skipped_candidate_not_missing_or_absent"] == 2
    assert counts["skipped_disallowed_category"] == 2
    assert counts["skipped_curated_fallback"] == 1
    assert counts["selected"] == 3

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag = 'third_meta'"
        ).fetchone() == (None,)
    finally:
        connection.close()


def test_llm_main_checks_all_artifact_paths_before_runtime_loading(tmp_path):
    database = tmp_path / "tags.db"
    model = tmp_path / "model.gguf"
    runtime = tmp_path / "llama-runtime"
    database.write_bytes(b"database-sentinel")
    model.write_bytes(b"model-sentinel")
    runtime.mkdir()

    with pytest.raises(SystemExit, match="must not overwrite input database"):
        MODULE.main(
            [
                "--db", str(database),
                "--model", str(model),
                "--llama-runtime", str(runtime),
                "--output", str(database),
                "--report", str(tmp_path / "report.json"),
                "--errors", str(tmp_path / "errors.jsonl"),
            ]
        )
    assert database.read_bytes() == b"database-sentinel"


def test_llm_artifacts_cannot_overwrite_reference_or_model_files(tmp_path):
    database = tmp_path / "tags.db"
    model = tmp_path / "model.gguf"
    reference = tmp_path / "reference.csv"
    runtime = tmp_path / "llama-runtime"
    database.write_bytes(b"database")
    model.write_bytes(b"model-sentinel")
    reference.write_text("tag,translation_cn\n", encoding="utf-8")
    runtime.mkdir()

    with pytest.raises(SystemExit, match="reference_csv"):
        MODULE.main(
            [
                "--db", str(database),
                "--model", str(model),
                "--llama-runtime", str(runtime),
                "--output", str(tmp_path / "output.csv"),
                "--report", str(tmp_path / "report.json"),
                "--errors", str(reference),
                "--reference-csv", str(reference),
            ]
        )
    assert reference.read_text(encoding="utf-8") == "tag,translation_cn\n"
