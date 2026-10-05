from __future__ import annotations

import csv
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = PLUGIN_ROOT / "tools" / "preflight_highfreq_translation_delivery.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("highfreq_delivery_preflight_test", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _create_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
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
            CREATE TRIGGER hot_tags_ai AFTER INSERT ON hot_tags BEGIN
                INSERT INTO hot_tags_fts(rowid, tag, translation_cn)
                VALUES (new.rowid, new.tag, new.translation_cn);
            END;
            CREATE TRIGGER hot_tags_au AFTER UPDATE ON hot_tags BEGIN
                INSERT INTO hot_tags_fts(hot_tags_fts, rowid, tag, translation_cn)
                VALUES('delete', old.rowid, old.tag, old.translation_cn);
                INSERT INTO hot_tags_fts(rowid, tag, translation_cn)
                VALUES (new.rowid, new.tag, new.translation_cn);
            END;
            CREATE TRIGGER hot_tags_ad AFTER DELETE ON hot_tags BEGIN
                INSERT INTO hot_tags_fts(hot_tags_fts, rowid, tag, translation_cn)
                VALUES('delete', old.rowid, old.tag, old.translation_cn);
            END;
            """
        )
        connection.executemany(
            "INSERT INTO hot_tags VALUES (?, ?, ?, ?, 1, NULL)",
            [
                ("striped_clothes", 0, 100, None),
                ("kaname_madoka", 4, 90, None),
                ("artist_name", 1, 80, None),
                ("commentary_request", 5, 70, None),
            ],
        )
        connection.execute("INSERT INTO hot_tags_fts(hot_tags_fts) VALUES('rebuild')")


def _create_pack(path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("tag", "category", "post_count", "translation_cn"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "tag": "striped_clothes",
                "category": 0,
                "post_count": 100,
                "translation_cn": "条纹服装",
            }
        )
        writer.writerow(
            {
                "tag": "kaname_madoka",
                "category": 4,
                "post_count": 90,
                "translation_cn": "鹿目圆",
            }
        )
        writer.writerow(
            {
                "tag": "commentary_request",
                "category": 5,
                "post_count": 70,
                "translation_cn": "评注请求",
            }
        )


def test_preflight_builds_audited_staging_database_without_mutating_inputs(tmp_path):
    tool = _load_tool()
    baseline = tmp_path / "baseline.sqlite"
    pack = tmp_path / "pack.csv"
    output = tmp_path / "preflight-v1"
    _create_database(baseline)
    _create_pack(pack)
    baseline_before = baseline.read_bytes()
    pack_before = pack.read_bytes()

    report = tool.run_preflight(
        baseline_db=baseline,
        input_csv=pack,
        output_dir=output,
        source_url="https://example.test/audited-pack",
        declared_license="MIT",
        revision="fixture-v1",
        expected_hot_tags=4,
        expected_artist_translated=0,
    )

    assert report["status"] == "PASS"
    assert report["live_database_touched"] is False
    assert report["comfyui_process_started_or_stopped"] is False
    assert report["translation_increase"] == 3
    assert report["staging"]["hot_tags"] == 4
    assert report["staging"]["fts_rows"] == 4
    assert report["staging"]["artist_translated"] == 0
    assert report["translation_values"]["matched_rows"] == 3
    assert all(row["match"] for row in report["fts_samples"])
    assert all(
        row["english_match"] and row["chinese_match"]
        for row in report["runtime_autocomplete_samples"]
    )
    assert baseline.read_bytes() == baseline_before
    assert pack.read_bytes() == pack_before
    assert (output / "preflight_report.json").is_file()
    with sqlite3.connect(output / "tags_cache_preflight.sqlite") as connection:
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='striped_clothes'"
        ).fetchone() == ("条纹服装",)
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='artist_name'"
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT translation_cn FROM hot_tags WHERE tag='commentary_request'"
        ).fetchone() == ("评注请求",)

    with pytest.raises(FileExistsError):
        tool.run_preflight(
            baseline_db=baseline,
            input_csv=pack,
            output_dir=output,
            source_url="https://example.test/audited-pack",
            declared_license="MIT",
            revision="fixture-v1",
            expected_hot_tags=4,
            expected_artist_translated=0,
        )


def test_preflight_refuses_the_plugin_live_database(tmp_path):
    tool = _load_tool()
    pack = tmp_path / "pack.csv"
    _create_pack(pack)
    with pytest.raises(tool.PreflightError, match="live Gallery database is forbidden"):
        tool.run_preflight(
            baseline_db=tool.LIVE_DB_PATH,
            input_csv=pack,
            output_dir=tmp_path / "should-not-exist",
            source_url="https://example.test/audited-pack",
            declared_license="MIT",
            revision="fixture-v1",
            expected_hot_tags=3,
            expected_artist_translated=0,
        )
