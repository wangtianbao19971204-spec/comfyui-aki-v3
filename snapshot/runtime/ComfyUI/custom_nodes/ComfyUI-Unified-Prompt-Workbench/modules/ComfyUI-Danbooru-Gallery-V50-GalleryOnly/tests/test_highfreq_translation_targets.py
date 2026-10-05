import csv
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = PLUGIN_ROOT / "tools" / "build_highfreq_translation_targets.py"
SPEC = importlib.util.spec_from_file_location("highfreq_translation_targets", TOOL_PATH)
builder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(builder)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gallery_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE hot_tags (
            tag TEXT PRIMARY KEY,
            category INTEGER NOT NULL,
            post_count INTEGER NOT NULL,
            translation_cn TEXT
        );
        CREATE TABLE tag_aliases (
            alias TEXT PRIMARY KEY,
            canonical_tag TEXT NOT NULL
        );
        """
    )
    connection.executemany(
        "INSERT INTO hot_tags(tag, category, post_count, translation_cn) VALUES (?, ?, ?, ?)",
        [
            ("translated", 0, 1000, "已有翻译"),
            ("artist_name", 1, 990, None),
            ("meta_tag", 5, 980, None),
            ("^_^", 0, 970, None),
            ("one_two_three_four_five_six_seven", 0, 960, None),
            ("x" * 65, 0, 950, None),
            ("www.example", 0, 940, None),
            ("old_alpha", 0, 930, None),
            ("canonical_alpha", 0, 920, "规范中文"),
            ("general_alpha", 0, 100, None),
            ("copyright_beta", 3, 90, ""),
            ("character_gamma", 4, 80, None),
            ("general_delta", 0, 70, None),
        ],
    )
    connection.execute(
        "INSERT INTO tag_aliases(alias, canonical_tag) VALUES (?, ?)",
        ("old_alpha", "canonical_alpha"),
    )
    connection.commit()
    connection.close()


def _weilin_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE tag_groups (id_index INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE tag_subgroups (
            id_index INTEGER PRIMARY KEY,
            group_id INTEGER,
            name TEXT
        );
        CREATE TABLE tag_tags (
            id_index INTEGER PRIMARY KEY,
            subgroup_id INTEGER,
            text TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO tag_groups(id_index, name) VALUES (?, ?)",
        [(1, "人物"), (2, "作品资料"), (3, "画面")],
    )
    connection.executemany(
        "INSERT INTO tag_subgroups(id_index, group_id, name) VALUES (?, ?, ?)",
        [
            (1, 1, "服装"),
            (2, 1, "动作"),
            (3, 2, "动画"),
            (77, 3, "艺术家风格"),
        ],
    )
    connection.executemany(
        "INSERT INTO tag_tags(id_index, subgroup_id, text) VALUES (?, ?, ?)",
        [
            (1, 1, "general alpha"),
            (2, 2, "general_alpha"),
            (3, 3, "copyright beta,"),
            (4, 77, "character_gamma"),
            (5, 1, "character gamma, long prompt fragment"),
        ],
    )
    connection.commit()
    connection.close()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    gallery = tmp_path / "gallery.sqlite"
    weilin = tmp_path / "weilin.sqlite"
    _gallery_database(gallery)
    _weilin_database(weilin)
    return gallery, weilin


def _build(tmp_path: Path, gallery: Path, weilin: Path, name: str = "build"):
    directory = tmp_path / name
    return builder.build_highfreq_translation_targets(
        gallery_db_path=gallery,
        weilin_tags_db_path=weilin,
        output_path=directory / "targets.csv",
        report_path=directory / "report.json",
        limit=3,
    )


def test_selection_policy_and_exact_count_are_deterministic(tmp_path: Path):
    gallery, weilin = _fixture(tmp_path)
    before = {_path: _sha256(_path) for _path in (gallery, weilin)}

    report = _build(tmp_path, gallery, weilin)
    with Path(report["output"]["path"]).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert [row["tag"] for row in rows] == [
        "general_alpha",
        "copyright_beta",
        "character_gamma",
    ]
    assert [row["rank"] for row in rows] == ["1", "2", "3"]
    assert rows[0]["category_name"] == "general"
    assert rows[1]["category_name"] == "copyright"
    assert rows[2]["category_name"] == "character"
    assert report["selection"]["rows"] == 3
    assert report["selection"]["decisions"]["selected"] == 3
    assert report["selection"]["decisions"]["no_alphanumeric_word"] == 1
    assert report["selection"]["decisions"]["over_word_limit"] == 1
    assert report["selection"]["decisions"]["over_character_limit"] == 1
    assert report["selection"]["decisions"]["url_like_tag"] == 1
    assert report["selection"]["decisions"]["canonical_translation_inheritable"] == 1
    assert report["database_mutated"] is False
    assert report["inputs_unchanged"] is True
    for path in (gallery, weilin):
        assert _sha256(path) == before[path]


def test_weilin_atomic_exact_paths_and_gallery_fallback(tmp_path: Path):
    gallery, weilin = _fixture(tmp_path)
    report = _build(tmp_path, gallery, weilin)
    with Path(report["output"]["path"]).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = {row["tag"]: row for row in csv.DictReader(handle)}

    general = rows["general_alpha"]
    assert general["classification_source"] == "weilin_exact_atomic"
    assert general["weilin_group"] == "人物"
    assert general["weilin_subgroup"] == "服装"
    assert general["weilin_match_count"] == "2"
    assert [path["subgroup"] for path in json.loads(general["weilin_paths_json"])] == [
        "服装",
        "动作",
    ]

    copyright_row = rows["copyright_beta"]
    assert copyright_row["classification_source"] == "weilin_exact_atomic"
    assert copyright_row["weilin_group"] == "作品资料"
    assert copyright_row["weilin_subgroup"] == "动画"

    character = rows["character_gamma"]
    assert character["classification_source"] == "gallery_category_fallback"
    assert character["weilin_group"] == "Gallery 角色"
    assert character["weilin_subgroup"] == "未命中 WeiLin"
    assert character["weilin_match_count"] == "0"
    assert report["weilin_mapping"]["stats"]["artist_scope_matches_excluded"] == 1
    assert report["weilin_mapping"]["stats"]["selected_tags_with_exact_match"] == 2
    assert report["weilin_mapping"]["stats"]["selected_tags_without_exact_match"] == 1


def test_refuses_overwrite_and_insufficient_target_count(tmp_path: Path):
    gallery, weilin = _fixture(tmp_path)
    output = tmp_path / "targets.csv"
    output.write_text("sentinel", encoding="utf-8")
    with pytest.raises(builder.HighFrequencyTargetBuildError, match="refusing to overwrite"):
        builder.build_highfreq_translation_targets(
            gallery_db_path=gallery,
            weilin_tags_db_path=weilin,
            output_path=output,
            report_path=tmp_path / "report.json",
            limit=3,
        )
    assert output.read_text(encoding="utf-8") == "sentinel"
    assert not (tmp_path / "report.json").exists()

    with pytest.raises(builder.HighFrequencyTargetBuildError, match="exactly 99"):
        builder.build_highfreq_translation_targets(
            gallery_db_path=gallery,
            weilin_tags_db_path=weilin,
            output_path=tmp_path / "not-written.csv",
            report_path=tmp_path / "not-written.json",
            limit=99,
        )
    assert not (tmp_path / "not-written.csv").exists()
    assert not (tmp_path / "not-written.json").exists()


def test_csv_is_repeatable_for_identical_inputs(tmp_path: Path):
    gallery, weilin = _fixture(tmp_path)
    first = _build(tmp_path, gallery, weilin, "first")
    second = _build(tmp_path, gallery, weilin, "second")
    assert Path(first["output"]["path"]).read_bytes() == Path(
        second["output"]["path"]
    ).read_bytes()
    assert first["output"]["sha256"] == second["output"]["sha256"]
