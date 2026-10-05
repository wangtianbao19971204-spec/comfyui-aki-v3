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
TOOL_PATH = PLUGIN_ROOT / "tools" / "build_consensus_tag_translation_pack.py"
SPEC = importlib.util.spec_from_file_location("consensus_translation_pack", TOOL_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE hot_tags("
        "tag TEXT PRIMARY KEY, category INTEGER, post_count INTEGER, translation_cn TEXT)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?, ?)",
        [
            ("long_hair", 0, 1000, None),
            ("source_request", 5, 900, None),
            ("bleach", 3, 800, None),
            ("alice_(example)", 4, 700, None),
            ("kept", 0, 600, "已有翻译"),
            ("artist_name", 1, 500, None),
        ],
    )
    connection.commit()
    connection.close()


def _csv(path: Path, rows: list[tuple[str, int, int, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("tag", "category", "post_count", "translation_cn"))
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_conservative_policy_blocks_artist_and_model_only_proper_names(tmp_path: Path):
    database = tmp_path / "tags.sqlite"
    _database(database)
    before = _sha256(database)

    primary = tmp_path / "primary.csv"
    validator_one = tmp_path / "validator_one.csv"
    validator_two = tmp_path / "validator_two.csv"
    trusted = tmp_path / "trusted.csv"
    observer = tmp_path / "observer.csv"
    common_rows = [
        ("long_hair", 0, 1000, "长发"),
        ("source_request", 5, 900, "来源请求"),
        ("bleach", 3, 800, "漂白"),
        ("alice_(example)", 4, 700, "爱丽丝(示例)"),
        ("kept", 0, 600, "覆盖翻译"),
        ("artist_name", 0, 500, "伪装艺术家"),
        # Exact-tag policy: this must not be attached to long_hair.
        ("long-hair", 0, 1, "长发"),
    ]
    _csv(primary, common_rows)
    _csv(validator_one, common_rows)
    _csv(validator_two, common_rows)
    _csv(
        trusted,
        [
            ("bleach", 3, 800, "死神"),
            ("alice_(example)", 4, 700, "爱丽丝(示例)"),
        ],
    )
    _csv(observer, [("long_hair", 0, 1000, "长头发")])

    report = builder.build_consensus_pack(
        db_path=database,
        primary_specs=[builder.SourceSpec("licensed", primary, "primary")],
        validator_specs=[
            builder.SourceSpec("model_a", validator_one, "validator"),
            builder.SourceSpec("model_b", validator_two, "validator"),
        ],
        trusted_specs=[builder.SourceSpec("authority", trusted, "trusted")],
        output_path=tmp_path / "output.csv",
        report_path=tmp_path / "report.json",
        review_path=tmp_path / "review.jsonl",
        observer_specs=[builder.SourceSpec("reference_leaked", observer, "observer")],
    )

    with Path(report["output"]["path"]).open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["tag"]: row for row in csv.DictReader(handle)}
    assert rows == {
        "long_hair": {
            "tag": "long_hair",
            "category": "0",
            "post_count": "1000",
            "translation_cn": "长发",
        },
        "source_request": {
            "tag": "source_request",
            "category": "5",
            "post_count": "900",
            "translation_cn": "来源请求",
        },
        "bleach": {
            "tag": "bleach",
            "category": "3",
            "post_count": "800",
            "translation_cn": "死神",
        },
        "alice_(example)": {
            "tag": "alice_(example)",
            "category": "4",
            "post_count": "700",
            "translation_cn": "爱丽丝(示例)",
        },
    }
    assert report["database_mutated"] is False
    assert report["policy"]["artist_allowed"] is False
    assert report["policy"]["fuzzy_identity_merge"] is False
    assert report["policy"]["observer_sources_are_non_voting"] is True
    assert {source["name"] for source in report["sources"]} == {
        "licensed", "model_a", "model_b", "authority", "reference_leaked"
    }
    assert _sha256(database) == before


def test_validator_disagreement_and_qualifier_loss_go_to_review(tmp_path: Path):
    database = tmp_path / "tags.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags("
        "tag TEXT PRIMARY KEY, category INTEGER, post_count INTEGER, translation_cn TEXT)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?, NULL)",
        [
            ("striped_clothes", 0, 100),
            ("photoshop_(medium)", 5, 90),
            ("bad_latin", 0, 80),
        ],
    )
    connection.commit()
    connection.close()

    primary = tmp_path / "primary.csv"
    validator_one = tmp_path / "one.csv"
    validator_two = tmp_path / "two.csv"
    _csv(
        primary,
        [
            ("striped_clothes", 0, 100, "条纹服装"),
            ("photoshop_(medium)", 5, 90, "Photoshop媒介"),
            ("bad_latin", 0, 80, "错误Name"),
        ],
    )
    _csv(validator_one, [("striped_clothes", 0, 100, "条纹服装")])
    _csv(validator_two, [("striped_clothes", 0, 100, "条纹衣服")])

    report = builder.build_consensus_pack(
        db_path=database,
        primary_specs=[builder.SourceSpec("licensed", primary, "primary")],
        validator_specs=[
            builder.SourceSpec("model_a", validator_one, "validator"),
            builder.SourceSpec("model_b", validator_two, "validator"),
        ],
        trusted_specs=[],
        output_path=tmp_path / "output.csv",
        report_path=tmp_path / "report.json",
        review_path=tmp_path / "review.jsonl",
    )

    assert report["output"]["rows"] == 0
    assert report["decisions"]["validator_disagreement"] == 1
    source_stats = {source["name"]: source["stats"] for source in report["sources"]}
    assert source_stats["licensed"]["invalid_qualifier_shape_mismatch"] == 1
    assert source_stats["licensed"]["invalid_unexplained_latin"] == 1
    review = [json.loads(line) for line in Path(report["review"]["path"]).read_text(encoding="utf-8").splitlines()]
    assert review[0]["decision"] == "validator_disagreement"


def test_proper_names_need_trusted_source_even_with_full_consensus(tmp_path: Path):
    database = tmp_path / "tags.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags("
        "tag TEXT PRIMARY KEY, category INTEGER, post_count INTEGER, translation_cn TEXT)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?, NULL)",
        [("known_work", 3, 100), ("known_character", 4, 90)],
    )
    connection.commit()
    connection.close()
    rows = [("known_work", 3, 100, "已知作品"), ("known_character", 4, 90, "已知角色")]
    files = []
    for name in ("primary", "one", "two"):
        path = tmp_path / (name + ".csv")
        _csv(path, rows)
        files.append(path)

    report = builder.build_consensus_pack(
        db_path=database,
        primary_specs=[builder.SourceSpec("licensed", files[0], "primary")],
        validator_specs=[
            builder.SourceSpec("model_a", files[1], "validator"),
            builder.SourceSpec("model_b", files[2], "validator"),
        ],
        trusted_specs=[],
        output_path=tmp_path / "output.csv",
        report_path=tmp_path / "report.json",
        review_path=tmp_path / "review.jsonl",
    )
    assert report["output"]["rows"] == 0
    assert report["decisions"] == {"proper_name_requires_trusted_source": 2}


def test_hardlinked_output_cannot_alias_database_or_source(tmp_path: Path):
    database = tmp_path / "tags.sqlite"
    _database(database)
    source = tmp_path / "primary.csv"
    _csv(source, [("long_hair", 0, 1000, "长发")])
    before = database.read_bytes()

    database_alias = tmp_path / "database-alias.csv"
    os.link(database, database_alias)
    with pytest.raises(builder.ConsensusBuildError, match="hard-link collision"):
        builder.build_consensus_pack(
            db_path=database,
            primary_specs=[builder.SourceSpec("licensed", source, "primary")],
            validator_specs=[],
            trusted_specs=[],
            output_path=database_alias,
            report_path=tmp_path / "report.json",
            review_path=tmp_path / "review.jsonl",
        )
    assert database.read_bytes() == before

    source_alias = tmp_path / "source-alias.csv"
    os.link(source, source_alias)
    with pytest.raises(builder.ConsensusBuildError, match="hard-link collision"):
        builder.build_consensus_pack(
            db_path=database,
            primary_specs=[builder.SourceSpec("licensed", source, "primary")],
            validator_specs=[],
            trusted_specs=[],
            output_path=source_alias,
            report_path=tmp_path / "report.json",
            review_path=tmp_path / "review.jsonl",
        )
    assert source.read_bytes() == source_alias.read_bytes()


def test_hardlinked_consensus_artifacts_cannot_alias_each_other(tmp_path: Path):
    database = tmp_path / "tags.sqlite"
    _database(database)
    source = tmp_path / "primary.csv"
    _csv(source, [("long_hair", 0, 1000, "长发")])
    report = tmp_path / "report.json"
    review = tmp_path / "review.jsonl"
    report.write_text("sentinel", encoding="utf-8")
    os.link(report, review)

    with pytest.raises(builder.ConsensusBuildError, match="hard-link collision"):
        builder.build_consensus_pack(
            db_path=database,
            primary_specs=[builder.SourceSpec("licensed", source, "primary")],
            validator_specs=[],
            trusted_specs=[],
            output_path=tmp_path / "output.csv",
            report_path=report,
            review_path=review,
        )
    assert report.read_text(encoding="utf-8") == "sentinel"
