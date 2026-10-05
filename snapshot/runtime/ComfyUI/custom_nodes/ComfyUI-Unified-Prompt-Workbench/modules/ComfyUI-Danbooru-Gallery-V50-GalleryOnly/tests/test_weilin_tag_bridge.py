from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PLUGIN_ROOT / "py" / "shared" / "db" / "weilin_tag_bridge.py"
SPEC = importlib.util.spec_from_file_location("weilin_tag_bridge_tested", MODULE_PATH)
assert SPEC and SPEC.loader
bridge_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge_module
SPEC.loader.exec_module(bridge_module)


def _make_tags_db(path: Path, long_prompt: str) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(
            """
            CREATE TABLE tag_groups (
                id_index INTEGER PRIMARY KEY,
                name TEXT,
                color TEXT,
                create_time INTEGER,
                p_uuid TEXT
            );
            CREATE TABLE tag_subgroups (
                id_index INTEGER PRIMARY KEY,
                group_id INTEGER,
                name TEXT,
                color TEXT,
                create_time INTEGER,
                p_uuid TEXT,
                g_uuid TEXT
            );
            CREATE TABLE tag_tags (
                id_index INTEGER PRIMARY KEY,
                subgroup_id INTEGER,
                text TEXT,
                desc TEXT,
                color TEXT,
                create_time INTEGER,
                t_uuid TEXT,
                g_uuid TEXT
            );
            """
        )
        connection.executemany(
            "INSERT INTO tag_groups VALUES (?,?,?,?,?)",
            (
                (1, "人物", "group-color", 1, "group-1"),
                (2, "画面", "group-color", 1, "group-2"),
            ),
        )
        connection.executemany(
            "INSERT INTO tag_subgroups VALUES (?,?,?,?,?,?,?)",
            (
                (10, 1, "基础", "sub-color", 1, "group-1", "sub-10"),
                (77, 2, "艺术家风格", "sub-color", 1, "group-2", "sub-77"),
            ),
        )
        connection.executemany(
            "INSERT INTO tag_tags VALUES (?,?,?,?,?,?,?,?)",
            (
                (1, 10, "1girl", "1个女孩", "c1", 1, "uuid-atomic", "sub-10"),
                (2, 10, long_prompt, "完整长提示词", "c2", 1, "uuid-long", "sub-10"),
                (3, 10, "centurii-chan", "错误标成角色的画师", "c3", 1, "uuid-artist", "sub-10"),
                (4, 77, "some_artist", "画师", "c4", 1, "uuid-style", "sub-77"),
                (5, 10, "blue eyes,", "蓝眼睛", "c5", 1, "uuid-trailing", "sub-10"),
                (6, 10, "100%_safe", "百分号测试", "c6", 1, "uuid-percent", "sub-10"),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _make_danbooru_db(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE danbooru_tag (
                id_index INTEGER PRIMARY KEY,
                tag TEXT,
                color_id INTEGER,
                translate TEXT,
                hot INTEGER,
                aliases INTEGER
            )
            """
        )
        connection.executemany(
            "INSERT INTO danbooru_tag VALUES (?,?,?,?,?,?)",
            (
                (1, "1girl", 0, "1个女孩", 100, 0),
                (2, "blue_eyes", 0, "蓝眼睛", 90, 0),
                (3, "centurii-chan", 4, "画师", 80, 0),
                (4, "100%_safe", 0, "百分号测试", 70, 0),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _make_gallery_db(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE hot_tags (
                tag TEXT PRIMARY KEY,
                category INTEGER,
                post_count INTEGER,
                translation_cn TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO hot_tags VALUES (?,?,?,?)",
            (
                ("1girl", 0, 5000, "1个女孩"),
                ("blue_eyes", 0, 4000, "蓝眼睛"),
                ("centurii-chan", 1, 3000, None),
                ("100%_safe", 0, 2000, "百分号测试"),
            ),
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture()
def catalog(tmp_path: Path):
    long_prompt = "masterpiece, " + "very detailed cinematic lighting, " * 12 + "end"
    tags_db = tmp_path / "weilin-tags.sqlite"
    danbooru_db = tmp_path / "weilin-danbooru.sqlite"
    gallery_db = tmp_path / "gallery.sqlite"
    _make_tags_db(tags_db, long_prompt)
    _make_danbooru_db(danbooru_db)
    _make_gallery_db(gallery_db)
    bridge = bridge_module.WeiLinTagBridge(
        tags_db_path=tags_db,
        danbooru_db_path=danbooru_db,
        gallery_db_path=gallery_db,
    )
    return bridge, long_prompt


def test_facets_preserve_weilin_taxonomy_and_exclude_artist_subgroups(catalog):
    bridge, _ = catalog
    result = bridge.facets()

    assert result["available"] is True
    assert result["summary"]["groups"] == 1
    assert result["summary"]["subgroups"] == 1
    assert result["summary"]["items"] == 4
    assert result["groups"][0]["name"] == "人物"
    assert result["groups"][0]["subgroups"][0]["name"] == "基础"
    assert result["preservation"] == {
        "raw_text_unchanged": True,
        "prompt_text_truncated": False,
        "site_filters_accept_prompt_phrases": False,
    }


def test_long_prompt_is_returned_byte_for_byte_and_never_site_filterable(catalog):
    bridge, long_prompt = catalog
    result = bridge.search(query="cinematic", kind="prompt_phrase")

    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["kind"] == "prompt_phrase"
    assert item["raw_text"] == long_prompt
    assert item["copy_text"] == long_prompt
    assert item["site_filterable"] is False
    assert item["gallery_tag"] is None
    assert bridge.get_item("uuid-long")["raw_text"] == long_prompt


def test_atomic_rows_link_to_gallery_and_single_trailing_comma_is_non_destructive(catalog):
    bridge, _ = catalog
    girl = bridge.search(query="1girl", kind="atomic_tag")["items"][0]
    trailing = bridge.search(query="blue eyes", kind="atomic_tag")["items"][0]

    assert girl["gallery_tag"] == "1girl"
    assert girl["gallery_translation"] == "1个女孩"
    assert girl["site_filterable"] is True
    assert trailing["raw_text"] == "blue eyes,"
    assert trailing["gallery_tag"] == "blue_eyes"
    assert trailing["site_filterable"] is True


def test_gallery_artist_identity_is_authoritative_even_if_weilin_says_character(catalog):
    bridge, _ = catalog

    assert bridge.search(query="centurii", kind="atomic_tag")["items"] == []
    assert bridge.get_item("uuid-artist") is None
    assert bridge.search(query="some_artist")["items"] == []


def test_danbooru_artist_identity_is_also_excluded_before_facets_and_pagination(catalog):
    bridge, _ = catalog
    with sqlite3.connect(str(bridge.tags_db_path)) as connection:
        connection.execute(
            "INSERT INTO tag_tags VALUES (?,?,?,?,?,?,?,?)",
            (7, 10, "danbooru_only_artist", "artist", "c7", 1, "uuid-db-artist", "sub-10"),
        )
    with sqlite3.connect(str(bridge.danbooru_db_path)) as connection:
        connection.execute(
            "INSERT INTO danbooru_tag VALUES (?,?,?,?,?,?)",
            (5, "danbooru_only_artist", 1, "artist", 60, 0),
        )

    assert bridge.search(query="danbooru_only_artist")["items"] == []
    assert bridge.get_item("uuid-db-artist") is None
    assert bridge.facets()["summary"]["items"] == 4


def test_wal_commit_invalidates_artist_and_facet_caches(catalog):
    bridge, _ = catalog
    with sqlite3.connect(str(bridge.tags_db_path)) as connection:
        connection.execute(
            "INSERT INTO tag_tags VALUES (?,?,?,?,?,?,?,?)",
            (8, 10, "wal_artist", "artist", "c8", 1, "uuid-wal-artist", "sub-10"),
        )

    writer = sqlite3.connect(str(bridge.danbooru_db_path))
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone()[0].casefold() == "wal"
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        assert bridge.search(query="wal_artist")["items"][0]["id"] == 8
        assert bridge.facets()["summary"]["items"] == 5
        main_before = bridge.danbooru_db_path.stat()

        writer.execute(
            "INSERT INTO danbooru_tag VALUES (?,?,?,?,?,?)",
            (99, "wal_artist", 1, "artist", 50, 0),
        )
        writer.commit()
        main_after = bridge.danbooru_db_path.stat()
        assert (main_after.st_size, main_after.st_mtime_ns) == (
            main_before.st_size,
            main_before.st_mtime_ns,
        )
        assert Path(str(bridge.danbooru_db_path) + "-wal").is_file()

        assert bridge.search(query="wal_artist")["items"] == []
        assert bridge.get_item("uuid-wal-artist") is None
        assert bridge.facets()["summary"]["items"] == 4
    finally:
        writer.close()


def test_literal_like_escaping_and_pagination(catalog):
    bridge, _ = catalog
    literal = bridge.search(query="100%", limit=1)
    page_one = bridge.search(group_id=1, limit=1, page=1)
    page_two = bridge.search(group_id=1, limit=1, page=2)

    assert [item["raw_text"] for item in literal["items"]] == ["100%_safe"]
    assert page_one["items"][0]["id"] != page_two["items"][0]["id"]
    assert page_one["has_more"] is True


def test_cursor_pages_are_stable_when_artist_rows_fall_between_visible_ids(catalog):
    bridge, _ = catalog
    first = bridge.search(group_id=1, limit=2, page=1)
    second = bridge.search(
        group_id=1,
        limit=2,
        page=2,
        cursor=first["next_cursor"],
    )

    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert first_ids == {1, 2}
    assert second_ids == {5, 6}
    assert first_ids.isdisjoint(second_ids)
    assert 3 not in first_ids | second_ids
    assert first["next_cursor"] == "2"
    assert second["next_cursor"] is None


def test_large_category_remains_reachable_beyond_legacy_page_1000(catalog):
    bridge, _ = catalog
    with sqlite3.connect(str(bridge.tags_db_path)) as connection:
        connection.executemany(
            "INSERT INTO tag_tags VALUES (?,?,?,?,?,?,?,?)",
            (
                (
                    item_id,
                    10,
                    f"bulk_tag_{item_id}",
                    "bulk",
                    "bulk-color",
                    1,
                    f"bulk-uuid-{item_id}",
                    "sub-10",
                )
                for item_id in range(100, 30200)
            ),
        )

    legacy = bridge.search(group_id=1, limit=30, page=1001)
    keyset = bridge.search(group_id=1, limit=30, page=1002, cursor=legacy["next_cursor"])
    legacy_ids = {item["id"] for item in legacy["items"]}
    keyset_ids = {item["id"] for item in keyset["items"]}
    assert legacy["page"] == 1001
    assert len(legacy_ids) == 30
    assert legacy["next_cursor"] is not None
    assert keyset_ids
    assert legacy_ids.isdisjoint(keyset_ids)


def test_invalid_filters_and_missing_database_fail_closed(catalog, tmp_path: Path):
    bridge, _ = catalog
    with pytest.raises(bridge_module.WeiLinCatalogError, match="group_id"):
        bridge.search(group_id="not-an-int")
    with pytest.raises(bridge_module.WeiLinCatalogError, match="kind"):
        bridge.search(kind="artist")

    missing = bridge_module.WeiLinTagBridge(
        tags_db_path=tmp_path / "missing.sqlite",
        danbooru_db_path=bridge.danbooru_db_path,
        gallery_db_path=bridge.gallery_db_path,
    )
    status = missing.status()
    assert status["available"] is False
    assert "unavailable" in status["error"]
