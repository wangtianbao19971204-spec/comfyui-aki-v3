from __future__ import annotations

import csv
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = PLUGIN_ROOT / "tools" / "build_public_tag_translation_pack.py"
SPEC = importlib.util.spec_from_file_location("public_pack_builder", BUILDER_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def test_builds_strict_chinese_packs_and_uses_best_metadata(tmp_path: Path):
    database = tmp_path / "tags.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT, category INTEGER, post_count INTEGER)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?)",
        [
            ("long_hair", 0, 999),
            ("hero_(series)", 3, 998),
            ("ambiguous", 0, 997),
            ("kana", 0, 996),
            ("hangul", 0, 995),
            ("ascii_parentheses", 0, 994),
            ("cjk_parentheses", 0, 993),
            ("too_long", 0, 992),
            ("exact_limit", 0, 991),
            ("low_count", 0, 990),
            ("artist_tag", 1, 989),
            ("meta_tag", 5, 988),
            ("one_valid_candidate", 0, 987),
            ("ascii", 0, 986),
        ],
    )
    connection.commit()
    connection.close()

    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    table = pa.table(
        {
            "tag": [
                "Long Hair",
                r"hero \(series\)",
                "ambiguous",
                "kana",
                "hangul",
                "ascii parentheses",
                "cjk parentheses",
                "too long",
                "exact limit",
                "low count",
                "artist tag",
                "meta tag",
                "one valid candidate",
            ],
            "type_name": [
                "general",
                "copyright",
                "general",
                "general",
                "general",
                "general",
                "general",
                "general",
                "general",
                "general",
                "artist",
                "meta",
                "general",
            ],
            "count": [100, 150, 100, 100, 100, 100, 100, 100, 100, 99, 500, 500, 100],
            "lang_zh": [
                ["长发"],
                ["英雄"],
                ["甲", "乙"],
                ["中文カナ"],
                ["中文한글"],
                ["说明(note)"],
                ["说明（注）"],
                ["中" * 65],
                ["中" * 64],
                ["低频"],
                ["画师"],
                ["元数据"],
                ["有效", "カナ"],
            ],
        }
    )
    pq.write_table(table, parquet_dir / "part.parquet")

    curated = tmp_path / "curated.json"
    curated.write_text(
        json.dumps(
            {
                "LONG HAIR": "人工长发",
                "hero (series)": "英雄系列",
                "artist tag": "人工画师",
                "meta tag": "人工元数据",
                "ascii": "ASCII only",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = builder.build_packs(
        tmp_path / "output",
        db_path=database,
        nextaltair_dir=parquet_dir,
        curated_json=curated,
    )
    assert report["outputs"]["nextaltair"]["rows"] == 5
    assert report["outputs"]["curated"]["rows"] == 3

    with Path(report["outputs"]["nextaltair"]["path"]).open(
        encoding="utf-8-sig", newline=""
    ) as source:
        next_rows = {row["tag"]: row for row in csv.DictReader(source)}
    assert next_rows["long_hair"]["translation_cn"] == "长发"
    assert next_rows["long_hair"]["post_count"] == "100"
    assert next_rows["hero_(series)"]["category"] == "3"
    assert next_rows["exact_limit"]["translation_cn"] == "中" * 64
    assert next_rows["one_valid_candidate"]["translation_cn"] == "有效"
    assert "ambiguous" not in next_rows
    assert "kana" not in next_rows
    assert "hangul" not in next_rows
    assert "ascii_parentheses" not in next_rows
    assert "cjk_parentheses" not in next_rows
    assert "too_long" not in next_rows
    assert "low_count" not in next_rows
    assert "artist_tag" not in next_rows
    assert next_rows["meta_tag"]["category"] == "5"

    with Path(report["outputs"]["curated"]["path"]).open(
        encoding="utf-8-sig", newline=""
    ) as source:
        curated_rows = {row["tag"]: row for row in csv.DictReader(source)}
    assert curated_rows["long_hair"]["post_count"] == "999"
    assert curated_rows["hero_(series)"]["category"] == "3"
    assert curated_rows["hero_(series)"]["post_count"] == "998"
    assert "artist_tag" not in curated_rows
    assert curated_rows["meta_tag"]["category"] == "5"
    assert curated_rows["meta_tag"]["post_count"] == "988"
    assert "ascii" not in curated_rows


def test_local_artist_category_blocks_misreported_public_rows(tmp_path: Path):
    database = tmp_path / "tags.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT, category INTEGER, post_count INTEGER)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?)",
        [
            ("misreported_artist", 1, 999),
            ("allowed_character", 4, 998),
            ("allowed_meta", 5, 997),
        ],
    )
    connection.commit()
    connection.close()

    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    table = pa.table(
        {
            "tag": ["misreported artist", "allowed character", "allowed meta"],
            "type_name": ["general", "character", "meta"],
            "count": [500, 500, 500],
            "lang_zh": [["错报艺术家"], ["允许角色"], ["允许元标签"]],
        }
    )
    pq.write_table(table, parquet_dir / "part.parquet")

    curated = tmp_path / "curated.json"
    curated.write_text(
        json.dumps(
            {
                "misreported artist": "人工艺术家",
                "allowed character": "人工角色",
                "allowed meta": "人工元标签",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = builder.build_packs(
        tmp_path / "output",
        db_path=database,
        nextaltair_dir=parquet_dir,
        curated_json=curated,
    )
    with Path(report["outputs"]["nextaltair"]["path"]).open(
        encoding="utf-8-sig", newline=""
    ) as source:
        next_rows = {row["tag"]: row for row in csv.DictReader(source)}
    with Path(report["outputs"]["curated"]["path"]).open(
        encoding="utf-8-sig", newline=""
    ) as source:
        curated_rows = {row["tag"]: row for row in csv.DictReader(source)}

    assert set(next_rows) == {"allowed_character", "allowed_meta"}
    assert set(curated_rows) == {"allowed_character", "allowed_meta"}
    assert next_rows["allowed_meta"]["category"] == "5"
    assert curated_rows["allowed_character"]["category"] == "4"


def test_write_pack_filters_disallowed_categories_at_output_boundary(tmp_path: Path):
    output = tmp_path / "pack.csv"
    report = builder.write_pack(
        output,
        {
            "artist_tag": ("艺术家", 1, 30),
            "category_two": ("旧类别", 2, 20),
            "character_tag": ("角色", 4, 10),
        },
        {
            "artist_tag": (1, 30),
            "category_two": (2, 20),
            "character_tag": (4, 10),
        },
    )

    with output.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    assert report["rows"] == 1
    assert [row["tag"] for row in rows] == ["character_tag"]


def test_normalized_conflicts_prefer_local_category_then_higher_count(tmp_path: Path):
    database = tmp_path / "tags.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT, category INTEGER, post_count INTEGER)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?)",
        [
            ("normalized_conflict", 4, 999),
            ("count_conflict", 3, 889),
            ("same_category_conflict", 0, 888),
        ],
    )
    connection.commit()
    connection.close()

    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    table = pa.table(
        {
            "tag": [
                "normalized conflict",
                "normalized_conflict",
                "count conflict",
                "count_conflict",
                "same category conflict",
                "same_category_conflict",
            ],
            "type_name": [
                "general",
                "character",
                "general",
                "copyright",
                "general",
                "general",
            ],
            "count": [900, 100, 100, 500, 100, 300],
            "lang_zh": [
                ["错误分类高频"],
                ["匹配分类"],
                ["低频"],
                ["高频"],
                ["同类低频"],
                ["同类高频"],
            ],
        }
    )
    pq.write_table(table, parquet_dir / "part.parquet")

    report = builder.build_packs(
        tmp_path / "output",
        db_path=database,
        nextaltair_dir=parquet_dir,
    )
    with Path(report["outputs"]["nextaltair"]["path"]).open(
        encoding="utf-8-sig", newline=""
    ) as source:
        rows = {row["tag"]: row for row in csv.DictReader(source)}

    assert rows["normalized_conflict"]["translation_cn"] == "匹配分类"
    assert rows["normalized_conflict"]["category"] == "4"
    assert rows["normalized_conflict"]["post_count"] == "100"
    assert rows["count_conflict"]["translation_cn"] == "高频"
    assert rows["count_conflict"]["category"] == "3"
    assert rows["same_category_conflict"]["translation_cn"] == "同类高频"
    assert rows["same_category_conflict"]["post_count"] == "300"


def test_database_is_required_and_opened_read_only_with_query_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    with pytest.raises(FileNotFoundError, match="database not found"):
        builder.load_local_metadata(tmp_path / "missing.db")

    database = tmp_path / "tags.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT, category INTEGER, post_count INTEGER)"
    )
    connection.execute("INSERT INTO hot_tags VALUES ('known_tag', 0, 10)")
    connection.commit()
    connection.close()

    calls = []
    real_connect = builder.sqlite3.connect

    def recording_connect(database_name, *args, **kwargs):
        calls.append((database_name, kwargs.copy()))
        return real_connect(database_name, *args, **kwargs)

    monkeypatch.setattr(builder.sqlite3, "connect", recording_connect)
    assert builder.load_local_metadata(database) == {"known_tag": (0, 10)}
    assert len(calls) == 1
    assert str(calls[0][0]).endswith("?mode=ro")
    assert calls[0][1]["uri"] is True


def test_all_sources_require_exact_local_tag_and_database_category(tmp_path: Path):
    database = tmp_path / "tags.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT, category INTEGER, post_count INTEGER)"
    )
    connection.executemany(
        "INSERT INTO hot_tags VALUES (?, ?, ?)",
        [
            ("allowed_general", 0, 900),
            ("allowed_character", 4, 800),
            ("local_artist", 1, 700),
            ("unsupported_category", 2, 600),
            ("category_mismatch", 4, 500),
            ("source_artist", 0, 400),
        ],
    )
    connection.commit()
    connection.close()

    chinese = chr(0x4E2D) + chr(0x6587)
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    pq.write_table(
        pa.table(
            {
                "tag": [
                    "allowed general",
                    "allowed character",
                    "local artist",
                    "unsupported category",
                    "category mismatch",
                    "source artist",
                    "missing local",
                ],
                "type_name": [
                    "general",
                    "character",
                    "general",
                    "general",
                    "general",
                    "artist",
                    "general",
                ],
                "count": [100] * 7,
                "lang_zh": [[chinese]] * 7,
            }
        ),
        parquet_dir / "part.parquet",
    )
    curated = tmp_path / "curated.json"
    curated.write_text(
        json.dumps(
            {
                "allowed general": chinese,
                "allowed character": chinese,
                "local artist": chinese,
                "unsupported category": chinese,
                "missing local": chinese,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = builder.build_packs(
        tmp_path / "output",
        db_path=database,
        nextaltair_dir=parquet_dir,
        curated_json=curated,
    )
    with Path(report["outputs"]["nextaltair"]["path"]).open(
        encoding="utf-8-sig", newline=""
    ) as source:
        next_rows = {row["tag"]: row for row in csv.DictReader(source)}
    with Path(report["outputs"]["curated"]["path"]).open(
        encoding="utf-8-sig", newline=""
    ) as source:
        curated_rows = {row["tag"]: row for row in csv.DictReader(source)}

    assert set(next_rows) == {"allowed_general", "allowed_character"}
    assert next_rows["allowed_character"]["category"] == "4"
    assert set(curated_rows) == {"allowed_general", "allowed_character"}
    assert curated_rows["allowed_character"]["category"] == "4"
    next_rejections = report["source_rejections"]["nextaltair"]
    assert next_rejections["missing_local_tag"] == 1
    assert next_rejections["artist_local_category"] == 1
    assert next_rejections["disallowed_local_category"] == 1
    assert next_rejections["source_category_mismatch"] == 1
    assert next_rejections["source_artist_category"] == 1
    curated_rejections = report["source_rejections"]["curated"]
    assert curated_rejections["missing_local_tag"] == 1
    assert curated_rejections["artist_local_category"] == 1
    assert curated_rejections["disallowed_local_category"] == 1


def test_artifact_paths_cannot_alias_database_sources_or_each_other(tmp_path: Path):
    database = tmp_path / "tags.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT, category INTEGER, post_count INTEGER)"
    )
    connection.execute("INSERT INTO hot_tags VALUES ('known_tag', 0, 10)")
    connection.commit()
    connection.close()
    curated = tmp_path / "curated.json"
    curated.write_text(json.dumps({"known_tag": chr(0x4E2D)}), encoding="utf-8")

    hardlink_output_dir = tmp_path / "hardlink-output"
    hardlink_output_dir.mkdir()
    os.link(database, hardlink_output_dir / "curated_tag_translations.csv")
    with pytest.raises(ValueError, match="must not overwrite database input"):
        builder.build_packs(
            hardlink_output_dir,
            db_path=database,
            curated_json=curated,
        )
    with sqlite3.connect(database) as check:
        assert check.execute("SELECT count(*) FROM hot_tags").fetchone()[0] == 1

    with pytest.raises(ValueError, match="must not overwrite curated JSON input"):
        builder.build_packs(
            tmp_path / "second-output",
            db_path=database,
            curated_json=curated,
            report_path=curated,
        )
    assert not (tmp_path / "second-output").exists()

    colliding_output = tmp_path / "third-output"
    with pytest.raises(ValueError, match="output paths must be distinct"):
        builder.build_packs(
            colliding_output,
            db_path=database,
            curated_json=curated,
            report_path=colliding_output / "curated_tag_translations.csv",
        )
    assert not colliding_output.exists()


def test_main_writes_report_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = tmp_path / "tags.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hot_tags(tag TEXT, category INTEGER, post_count INTEGER)"
    )
    connection.execute("INSERT INTO hot_tags VALUES ('known_tag', 0, 10)")
    connection.commit()
    connection.close()
    curated = tmp_path / "curated.json"
    curated.write_text(json.dumps({"known_tag": chr(0x4E2D)}), encoding="utf-8")
    report_path = tmp_path / "report.json"
    replace_targets = []
    real_replace = builder.os.replace

    def recording_replace(source, destination):
        replace_targets.append(Path(destination).resolve())
        return real_replace(source, destination)

    monkeypatch.setattr(builder.os, "replace", recording_replace)
    assert (
        builder.main(
            [
                "--output-dir",
                str(tmp_path / "output"),
                "--db",
                str(database),
                "--curated-json",
                str(curated),
                "--report",
                str(report_path),
            ]
        )
        == 0
    )
    assert report_path.resolve() in replace_targets
    assert json.loads(report_path.read_text(encoding="utf-8"))["database"][
        "query_only"
    ] is True
    assert not list(tmp_path.glob("report.json.*.tmp"))
