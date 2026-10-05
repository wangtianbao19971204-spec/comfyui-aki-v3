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
TOOL_PATH = PLUGIN_ROOT / "tools" / "build_weilin_gallery_integration.py"
SPEC = importlib.util.spec_from_file_location("weilin_gallery_integration", TOOL_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gallery_database(path: Path, rows: list[tuple[str, int, int, str | None]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE hot_tags("
        "tag TEXT PRIMARY KEY, category INTEGER, post_count INTEGER, translation_cn TEXT)"
    )
    connection.executemany("INSERT INTO hot_tags VALUES (?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


def _weilin_tags_database(
    path: Path,
    *,
    groups: list[tuple[int, str, str]],
    subgroups: list[tuple[int, int, str, str, str]],
    tags: list[tuple[int, int, str, str, str, str]],
) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE tag_groups("
        "id_index INTEGER PRIMARY KEY, name TEXT, color TEXT, create_time INTEGER, p_uuid TEXT)"
    )
    connection.execute(
        "CREATE TABLE tag_subgroups("
        "id_index INTEGER PRIMARY KEY, group_id INTEGER, name TEXT, color TEXT, "
        "create_time INTEGER, p_uuid TEXT, g_uuid TEXT)"
    )
    connection.execute(
        "CREATE TABLE tag_tags("
        "id_index INTEGER PRIMARY KEY, subgroup_id INTEGER, text TEXT, desc TEXT, color TEXT, "
        "create_time INTEGER, t_uuid TEXT, g_uuid TEXT)"
    )
    connection.executemany(
        "INSERT INTO tag_groups(id_index, name, p_uuid) VALUES (?, ?, ?)", groups
    )
    connection.executemany(
        "INSERT INTO tag_subgroups(id_index, group_id, name, p_uuid, g_uuid) "
        "VALUES (?, ?, ?, ?, ?)",
        subgroups,
    )
    connection.executemany(
        "INSERT INTO tag_tags(id_index, subgroup_id, text, desc, t_uuid, g_uuid) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        tags,
    )
    connection.commit()
    connection.close()


def _weilin_danbooru_database(
    path: Path, rows: list[tuple[int, str, int, str]]
) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE danbooru_tag("
        "id_index INTEGER PRIMARY KEY, tag TEXT, color_id INTEGER, translate TEXT, "
        "hot INTEGER DEFAULT 0, aliases INTEGER DEFAULT 0)"
    )
    connection.executemany(
        "INSERT INTO danbooru_tag(id_index, tag, color_id, translate) VALUES (?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()


def _consensus_csv(path: Path, rows: list[tuple[str, int, int, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("tag", "category", "post_count", "translation_cn"))
        writer.writerows(rows)


def _fixture(tmp_path: Path) -> dict[str, Path | str]:
    gallery = tmp_path / "gallery.sqlite"
    tags_db = tmp_path / "weilin-tags.sqlite"
    danbooru_db = tmp_path / "weilin-danbooru.sqlite"
    consensus = tmp_path / "triple.csv"
    long_prompt = (
        "  masterpiece, best quality, one girl with windblown silver hair, "
        "standing beside a moonlit lake, cinematic rim lighting\n  "
    )
    _gallery_database(
        gallery,
        [
            ("robot_girl", 0, 1000, None),
            ("known_character", 4, 900, None),
            ("artist_name", 1, 800, None),
            ("existing_tag", 0, 700, "已有翻译"),
            ("conflict_tag", 0, 600, None),
            ("triple_conflict", 0, 500, None),
            ("unsafe_tag", 0, 400, None),
        ],
    )
    _weilin_tags_database(
        tags_db,
        groups=[(1, "人物", "group-1")],
        subgroups=[
            (1, 1, "机械", "subgroup-1", "group-link-1"),
            (2, 1, "画师", "subgroup-2", "group-link-2"),
        ],
        tags=[
            (1, 1, "robot girl", "机器人女孩", "tag-robot", "tag-group-1"),
            (2, 1, "known_character", "已知角色", "tag-character", "tag-group-1"),
            (3, 2, "artist_name", "艺术家名字", "tag-artist", "tag-group-2"),
            (4, 1, long_prompt, "完整长句", "tag-long", "tag-group-1"),
            (5, 1, "existing_tag", "已有翻译", "tag-existing", "tag-group-1"),
            (6, 1, "conflict_tag", "冲突甲", "tag-conflict-a", "tag-group-1"),
            (7, 1, "conflict tag", "冲突乙", "tag-conflict-b", "tag-group-1"),
            (8, 1, "triple_conflict", "三方冲突", "tag-triple", "tag-group-1"),
            (9, 1, "unsafe_tag", "这是一个超过二十四个汉字而且绝对不会被导入翻译包的超长翻译值", "tag-unsafe", "tag-group-1"),
            (10, 1, "unknown_artist", "未知画师", "tag-unknown-artist", "tag-group-1"),
        ],
    )
    _weilin_danbooru_database(
        danbooru_db,
        [
            (1, "robot_girl", 0, "机器人女孩-通用-Robot girl"),
            (2, "known_character", 4, "已知角色-示例-Known character"),
            (3, "artist_name", 1, "艺术家名字-Artist"),
            (4, "existing_tag", 0, "已有翻译"),
            (5, "conflict_tag", 0, "冲突甲"),
            (6, "triple_conflict", 0, "三方冲突"),
            (7, "unsafe_tag", 0, "这是一个超过二十四个汉字而且绝对不会被导入翻译包的超长翻译值"),
            (8, "unknown_artist", 1, "未知画师"),
        ],
    )
    _consensus_csv(
        consensus,
        [
            ("robot_girl", 0, 1000, "机器人女孩"),
            ("known_character", 4, 900, "已知角色"),
            ("artist_name", 1, 800, "艺术家名字"),
            ("existing_tag", 0, 700, "已有翻译"),
            ("conflict_tag", 0, 600, "冲突甲"),
            ("triple_conflict", 0, 500, "三方冲突"),
            ("triple_conflict", 0, 500, "另一译名"),
            ("unsafe_tag", 0, 400, "这是一个超过二十四个汉字而且绝对不会被导入翻译包的超长翻译值"),
        ],
    )
    return {
        "gallery": gallery,
        "tags_db": tags_db,
        "danbooru_db": danbooru_db,
        "consensus": consensus,
        "long_prompt": long_prompt,
    }


def _build(tmp_path: Path, fixture: dict[str, Path | str], name: str = "result"):
    directory = tmp_path / name
    return builder.build_weilin_gallery_integration(
        gallery_db_path=fixture["gallery"],
        weilin_tags_db_path=fixture["tags_db"],
        weilin_danbooru_db_path=fixture["danbooru_db"],
        triple_consensus_path=fixture["consensus"],
        output_path=directory / "translations.csv",
        taxonomy_path=directory / "taxonomy.jsonl",
        report_path=directory / "report.json",
    )


def test_exact_consensus_only_and_databases_remain_unchanged(tmp_path: Path):
    fixture = _fixture(tmp_path)
    inputs = [fixture[name] for name in ("gallery", "tags_db", "danbooru_db", "consensus")]
    before = {_path: _sha256(_path) for _path in inputs}

    report = _build(tmp_path, fixture)

    with Path(report["output"]["path"]).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "tag": "robot_girl",
            "category": "0",
            "post_count": "1000",
            "translation_cn": "机器人女孩",
        },
        {
            "tag": "known_character",
            "category": "4",
            "post_count": "900",
            "translation_cn": "已知角色",
        },
    ]
    assert report["database_mutated"] is False
    assert report["inputs_unchanged"] is True
    assert report["policy"]["artist_allowed"] is False
    assert report["source"] == {
        "name": "WeiLin ComfyUI Tools Prompt data",
        "upstream_url": builder.WEILIN_UPSTREAM_URL,
        "license": "MIT",
    }
    assert report["decisions"]["accepted"] == 2
    assert report["decisions"]["gallery_translation_already_present"] == 1
    assert report["decisions"]["weilin_taxonomy_translation_conflict"] == 1
    assert report["decisions"]["triple_consensus_translation_conflict"] == 1
    assert report["decisions"]["translation_too_long"] == 1
    for path in inputs:
        assert _sha256(path) == before[path]
        source_entry = next(
            value
            for value in report["inputs"].values()
            if Path(value["path"]) == path.resolve()
        )
        assert source_entry["sha256"] == before[path]
        assert source_entry["read_only"] is True


def test_artist_subgroup_is_excluded_and_long_prompt_is_verbatim(tmp_path: Path):
    fixture = _fixture(tmp_path)
    report = _build(tmp_path, fixture)
    taxonomy = [
        json.loads(line)
        for line in Path(report["taxonomy"]["path"]).read_text(encoding="utf-8").splitlines()
    ]

    assert not any(row["t_uuid"] == "tag-artist" for row in taxonomy)
    assert not any(row["t_uuid"] == "tag-unknown-artist" for row in taxonomy)
    long_row = next(row for row in taxonomy if row["t_uuid"] == "tag-long")
    assert long_row["raw_text"] == fixture["long_prompt"]
    assert long_row["kind"] == "prompt_phrase"
    assert long_row["is_long_text"] is True
    assert long_row["group"] == "人物"
    assert long_row["subgroup"] == "机械"
    assert long_row["t_uuid"] == "tag-long"
    stats = report["taxonomy"]["stats"]
    assert stats["artist_subgroup_excluded"] == 1
    assert stats["weilin_danbooru_artist_rows_excluded"] == 1
    assert stats["artist_rows_excluded"] == 2
    assert stats["translation_long_text_excluded"] == 1


def test_real_weilin_artist_bucket_names_and_ids_are_fail_closed():
    assert builder._artist_scope_reason("画面", "艺术家风格", 77) == "artist_subgroup"
    assert builder._artist_scope_reason("画面", "一键画师串", 493) == "artist_subgroup"
    # Id remains authoritative if a future snapshot renames the visible label.
    assert builder._artist_scope_reason("画面", "renamed", 77) == "artist_subgroup"


def test_danbooru_disagreement_and_category_mismatch_are_rejected(tmp_path: Path):
    gallery = tmp_path / "gallery.sqlite"
    tags_db = tmp_path / "tags.sqlite"
    danbooru = tmp_path / "danbooru.sqlite"
    consensus = tmp_path / "triple.csv"
    _gallery_database(
        gallery,
        [("different", 0, 10, None), ("wrong_category", 4, 9, None)],
    )
    _weilin_tags_database(
        tags_db,
        groups=[(1, "人物", "g")],
        subgroups=[(1, 1, "普通", "s", "sg")],
        tags=[
            (1, 1, "different", "译名甲", "t1", "tg"),
            (2, 1, "wrong_category", "译名乙", "t2", "tg"),
        ],
    )
    _weilin_danbooru_database(
        danbooru,
        [(1, "different", 0, "译名丙"), (2, "wrong_category", 0, "译名乙")],
    )
    _consensus_csv(
        consensus,
        [("different", 0, 10, "译名甲"), ("wrong_category", 4, 9, "译名乙")],
    )
    fixture = {
        "gallery": gallery,
        "tags_db": tags_db,
        "danbooru_db": danbooru,
        "consensus": consensus,
    }

    report = _build(tmp_path, fixture)

    assert report["output"]["rows"] == 0
    assert report["decisions"] == {
        "weilin_danbooru_category_mismatch": 1,
        "weilin_sources_disagree": 1,
    }


def test_path_and_hardlink_guards_run_before_writes(tmp_path: Path):
    fixture = _fixture(tmp_path)
    before = _sha256(fixture["gallery"])
    alias = tmp_path / "gallery-alias.jsonl"
    os.link(fixture["gallery"], alias)

    with pytest.raises(builder.WeiLinIntegrationBuildError, match="hard-link collision"):
        builder.build_weilin_gallery_integration(
            gallery_db_path=fixture["gallery"],
            weilin_tags_db_path=fixture["tags_db"],
            weilin_danbooru_db_path=fixture["danbooru_db"],
            triple_consensus_path=fixture["consensus"],
            output_path=tmp_path / "translations.csv",
            taxonomy_path=alias,
            report_path=tmp_path / "report.json",
        )
    assert _sha256(fixture["gallery"]) == before
    assert not (tmp_path / "translations.csv").exists()
    assert not (tmp_path / "report.json").exists()

    same_output = tmp_path / "same-output"
    with pytest.raises(builder.WeiLinIntegrationBuildError, match="distinct files"):
        builder.build_weilin_gallery_integration(
            gallery_db_path=fixture["gallery"],
            weilin_tags_db_path=fixture["tags_db"],
            weilin_danbooru_db_path=fixture["danbooru_db"],
            triple_consensus_path=fixture["consensus"],
            output_path=same_output,
            taxonomy_path=same_output,
            report_path=tmp_path / "other-report.json",
        )


def test_existing_artifact_is_never_overwritten(tmp_path: Path):
    fixture = _fixture(tmp_path)
    output = tmp_path / "translations.csv"
    output.write_text("sentinel", encoding="utf-8")

    with pytest.raises(builder.WeiLinIntegrationBuildError, match="refusing to overwrite"):
        builder.build_weilin_gallery_integration(
            gallery_db_path=fixture["gallery"],
            weilin_tags_db_path=fixture["tags_db"],
            weilin_danbooru_db_path=fixture["danbooru_db"],
            triple_consensus_path=fixture["consensus"],
            output_path=output,
            taxonomy_path=tmp_path / "taxonomy.jsonl",
            report_path=tmp_path / "report.json",
        )
    assert output.read_text(encoding="utf-8") == "sentinel"
    assert not (tmp_path / "taxonomy.jsonl").exists()
    assert not (tmp_path / "report.json").exists()


def test_csv_and_taxonomy_are_deterministic(tmp_path: Path):
    fixture = _fixture(tmp_path)
    first = _build(tmp_path, fixture, "first")
    second = _build(tmp_path, fixture, "second")

    first_csv = Path(first["output"]["path"])
    second_csv = Path(second["output"]["path"])
    first_taxonomy = Path(first["taxonomy"]["path"])
    second_taxonomy = Path(second["taxonomy"]["path"])
    assert first_csv.read_bytes() == second_csv.read_bytes()
    assert first_taxonomy.read_bytes() == second_taxonomy.read_bytes()
    assert first["output"]["sha256"] == second["output"]["sha256"]
    assert first["taxonomy"]["sha256"] == second["taxonomy"]["sha256"]
    assert first["decisions"] == second["decisions"]
    assert first["taxonomy"]["stats"] == second["taxonomy"]["stats"]
