from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sqlite3
import sys
import types
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DB_SOURCE = PLUGIN_ROOT / "py" / "shared" / "db" / "db_manager.py"


def _load_db_manager_module(monkeypatch):
    package_names = ("aliasdb", "aliasdb.shared", "aliasdb.shared.db", "aliasdb.utils")
    for package_name in package_names:
        package = types.ModuleType(package_name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, package_name, package)
    logger_module = types.ModuleType("aliasdb.utils.logger")
    logger_module.get_logger = lambda _name: logging.getLogger("tag-alias-db-test")
    monkeypatch.setitem(sys.modules, "aliasdb.utils.logger", logger_module)

    module_name = "aliasdb.shared.db.db_manager"
    spec = importlib.util.spec_from_file_location(module_name, DB_SOURCE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_delivery_config(path: Path, runtime_root: Path, tag_db: Path) -> None:
    path.write_text(
        json.dumps({
            "schemaVersion": 1,
            "runtimeRoot": str(runtime_root.resolve()),
            "isolatedTagDatabase": str(tag_db.resolve()),
        }),
        encoding="utf-8",
    )


def test_delivery_tag_database_override_is_guarded_and_confined(monkeypatch, tmp_path):
    module = _load_db_manager_module(monkeypatch)
    runtime_base = (tmp_path / "runtime-base").resolve()
    run_root = runtime_base / "run-one"
    run_root.mkdir(parents=True)
    isolated_db = run_root / "plugin-data" / "tags_cache.db"
    isolated_db.parent.mkdir()
    sqlite3.connect(isolated_db).close()
    config_path = run_root / "test-config.json"
    _write_delivery_config(config_path, run_root, isolated_db)
    monkeypatch.setattr(module, "_DELIVERY_RUNTIME_BASE", runtime_base)

    monkeypatch.setenv("DANBOORU_GALLERY_DELIVERY_TEST", "1")
    monkeypatch.setenv("DANBOORU_GALLERY_TEST_CONFIG", str(config_path))
    monkeypatch.setenv("DANBOORU_GALLERY_TAG_DB_PATH", str(isolated_db))
    manager = module.TagDatabaseManager()
    assert Path(manager.db_path) == isolated_db.resolve()
    explicit_manager = module.TagDatabaseManager(str(isolated_db))
    assert Path(explicit_manager.db_path) == isolated_db.resolve()
    with pytest.raises(RuntimeError, match="does not match the isolated delivery database"):
        module.TagDatabaseManager(str(tmp_path / "explicit-bypass.db"))

    async def initialize_isolated_copy():
        await manager.initialize_database()
        connection = await manager.get_connection()
        row = await (await connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tag_aliases'"
        )).fetchone()
        assert row[0] == "tag_aliases"
        await manager.close()

    asyncio.run(initialize_isolated_copy())

    outside_db = tmp_path / "outside.db"
    outside_db.write_bytes(b"outside")
    _write_delivery_config(config_path, run_root, outside_db)
    monkeypatch.setenv("DANBOORU_GALLERY_TAG_DB_PATH", str(outside_db))
    with pytest.raises(RuntimeError, match="escaped its declared runtimeRoot"):
        module.TagDatabaseManager()


def test_delivery_tag_database_override_fails_closed_but_is_ignored_in_production(
    monkeypatch, tmp_path
):
    module = _load_db_manager_module(monkeypatch)
    monkeypatch.setenv("DANBOORU_GALLERY_DELIVERY_TEST", "1")
    monkeypatch.delenv("DANBOORU_GALLERY_TAG_DB_PATH", raising=False)
    with pytest.raises(RuntimeError, match="DANBOORU_GALLERY_TAG_DB_PATH is required"):
        module.TagDatabaseManager()

    arbitrary = tmp_path / "must-not-be-used.db"
    monkeypatch.setenv("DANBOORU_GALLERY_DELIVERY_TEST", "0")
    monkeypatch.setenv("DANBOORU_GALLERY_TAG_DB_PATH", str(arbitrary))
    manager = module.TagDatabaseManager()
    expected = DB_SOURCE.parent.parent / "data" / "tags_cache.db"
    assert Path(manager.db_path) == expected
    assert not arbitrary.exists()


def test_alias_schema_is_idempotent_and_searches_canonical_tag(monkeypatch, tmp_path):
    module = _load_db_manager_module(monkeypatch)

    async def scenario():
        manager = module.TagDatabaseManager(str(tmp_path / "aliases.db"))
        await manager.initialize_database()
        await manager.initialize_database()

        connection = await manager.get_connection()
        columns = {
            row[1]
            for row in await (await connection.execute(
                "PRAGMA table_info(tag_aliases)"
            )).fetchall()
        }
        assert {
            "alias",
            "canonical_tag",
            "relation_type",
            "source_name",
            "source_url",
            "declared_license",
            "source_revision",
            "source_sha256",
            "imported_at",
        } <= columns
        indexes = {
            row[1]
            for row in await (await connection.execute(
                "PRAGMA index_list(tag_aliases)"
            )).fetchall()
        }
        assert "idx_tag_aliases_canonical" in indexes
        assert "idx_tag_aliases_source_revision" in indexes

        await manager.insert_tag(
            "cat_ears", 0, 250, "猫耳", ["historic local alias"]
        )
        alias_row = {
            "alias": "kitty_ears",
            "canonical_tag": "cat_ears",
            "source_name": "deepghs/site_tags",
            "source_url": "https://huggingface.co/datasets/deepghs/site_tags",
            "declared_license": "CC-BY-4.0",
            "source_revision": "revision-one",
            "source_sha256": "abc123",
        }
        await manager.insert_tag_aliases_batch([alias_row])
        alias_row["source_revision"] = "revision-two"
        await manager.insert_tag_aliases_batch([alias_row])

        count, revision = await (await connection.execute(
            "SELECT COUNT(*), MAX(source_revision) FROM tag_aliases"
        )).fetchone()
        assert (count, revision) == (1, "revision-two")
        assert await manager.get_tags_count() == 1

        prefix_result = await manager.search_tags_by_prefix("kitty_ears", 10)
        assert prefix_result == [{
            "tag": "cat_ears",
            "category": 0,
            "post_count": 250,
            "translation_cn": "猫耳",
            "aliases": ["historic local alias"],
            "matched_alias": "kitty_ears",
        }]

        optimized_result = await manager.search_tags_optimized(
            "KITTY_EARS", 10, search_type="english"
        )
        assert optimized_result[0]["tag"] == "cat_ears"
        assert optimized_result[0]["matched_alias"] == "kitty_ears"
        assert optimized_result[0]["translation_cn"] == "猫耳"

        assert await manager.get_translations(
            ["KITTY EARS", "cat_ears", "missing"]
        ) == {
            "KITTY EARS": "猫耳",
            "cat_ears": "猫耳",
        }
        assert await manager.get_categories(
            ["KITTY EARS", "cat_ears", "missing"]
        ) == {
            "KITTY EARS": 0,
            "cat_ears": 0,
        }

        # Even if a stale row survives under the official alias spelling, the
        # alias resolves to the canonical row while the stale identity remains
        # present and untouched in hot_tags.
        await manager.insert_tag("kitty_ears", 4, 5, "旧角色译名")
        alias_first = await manager.search_tags_by_prefix("kitty_ears", 1)
        assert alias_first[0]["tag"] == "cat_ears"
        assert alias_first[0]["translation_cn"] == "猫耳"
        assert await manager.get_translations(["kitty_ears"]) == {
            "kitty_ears": "猫耳"
        }
        assert await manager.get_categories(["kitty_ears"]) == {"kitty_ears": 0}
        assert (await manager.get_tag("kitty_ears"))["translation_cn"] == "旧角色译名"
        assert await manager.get_tags_count() == 2

        canonical = await manager.get_tag("cat_ears")
        assert canonical["aliases"] == ["historic local alias"]
        healthy, error = await manager.check_database_health()
        assert (healthy, error) == (True, None)
        await manager.close()

    asyncio.run(scenario())


def test_prefix_search_treats_like_metacharacters_literally_and_deduplicates_aliases(
    monkeypatch, tmp_path
):
    module = _load_db_manager_module(monkeypatch)

    async def scenario():
        manager = module.TagDatabaseManager(str(tmp_path / "literal-prefix.db"))
        await manager.initialize_database()
        await manager.insert_tags_batch([
            {"tag": "foo_bar", "category": 0, "post_count": 500},
            {"tag": "fooxbar", "category": 0, "post_count": 900},
            {"tag": "shared_target", "category": 0, "post_count": 800},
            *[
                {
                    "tag": "unique_target_{}".format(index),
                    "category": 0,
                    "post_count": 700 - index,
                }
                for index in range(6)
            ],
        ])

        source = {
            "source_name": "fixture",
            "source_url": "https://example.invalid/fixture",
            "declared_license": "CC0-1.0",
            "source_revision": "1",
            "source_sha256": "deadbeef",
        }
        aliases = [
            {
                **source,
                "alias": "literal_alias",
                "canonical_tag": "foo_bar",
            },
            {
                **source,
                "alias": "literalxalias",
                "canonical_tag": "fooxbar",
            },
        ]
        aliases.extend(
            {
                **source,
                "alias": "same_{:02d}".format(index),
                "canonical_tag": "shared_target",
            }
            for index in range(45)
        )
        aliases.extend(
            {
                **source,
                "alias": "same_unique_{:02d}".format(index),
                "canonical_tag": "unique_target_{}".format(index),
            }
            for index in range(6)
        )
        await manager.insert_tag_aliases_batch(aliases)

        direct = await manager.search_tags_by_prefix("foo_", 10)
        assert [row["tag"] for row in direct] == ["foo_bar"]

        literal_alias = await manager.search_tags_by_prefix("literal_", 10)
        assert [row["tag"] for row in literal_alias] == ["foo_bar"]
        assert literal_alias[0]["matched_alias"] == "literal_alias"

        deduplicated = await manager.search_tags_by_prefix("same_", 5)
        assert len(deduplicated) == 5
        assert len({row["tag"] for row in deduplicated}) == 5
        assert deduplicated[0]["tag"] == "shared_target"
        await manager.close()

    asyncio.run(scenario())


def test_artist_translation_is_cleared_and_masked_everywhere(monkeypatch, tmp_path):
    module = _load_db_manager_module(monkeypatch)

    async def scenario():
        manager = module.TagDatabaseManager(str(tmp_path / "artists.db"))
        await manager.initialize_database()

        await manager.insert_tag("artist_name", 1, 99, "艺术家译名")
        await manager.insert_tag("moves_to_artist", 0, 80, "旧翻译")
        await manager.insert_tag("moves_to_artist", 1, 81)
        await manager.insert_tags_batch([
            {
                "tag": "batch_artist",
                "category": 1,
                "post_count": 70,
                "translation_cn": "批量艺术家译名",
            },
            {
                "tag": "character_name",
                "category": 4,
                "post_count": 60,
                "translation_cn": "角色名",
            },
        ])

        connection = await manager.get_connection()
        raw = {
            row["tag"]: row["translation_cn"]
            for row in await (await connection.execute(
                "SELECT tag, translation_cn FROM hot_tags"
            )).fetchall()
        }
        assert raw["artist_name"] is None
        assert raw["moves_to_artist"] is None
        assert raw["batch_artist"] is None
        assert raw["character_name"] == "角色名"

        # Simulate an older database that still contains a stale artist
        # translation.  Reads must mask it even before a cleanup migration.
        await connection.execute(
            "UPDATE hot_tags SET translation_cn = ? WHERE tag = ?",
            ("遗留艺术家译名", "artist_name"),
        )
        await connection.commit()

        await manager.insert_tag_aliases_batch([{
            "alias": "artist_alias",
            "canonical_tag": "artist_name",
            "source_name": "fixture",
            "source_url": "https://example.invalid/fixture",
            "declared_license": "CC0-1.0",
            "source_revision": "1",
            "source_sha256": "deadbeef",
        }])

        assert await manager.get_translations(
            ["artist_name", "artist_alias", "character_name"]
        ) == {"character_name": "角色名"}
        assert await manager.get_categories(
            ["artist_name", "artist_alias", "character_name"]
        ) == {
            "artist_name": 1,
            "artist_alias": 1,
            "character_name": 4,
        }

        artist = await manager.get_tag("artist_name")
        assert artist["translation_cn"] is None
        prefix = await manager.search_tags_by_prefix("artist_", 10)
        assert {row["tag"] for row in prefix} == {"artist_name"}
        assert prefix[0]["translation_cn"] is None
        alias_prefix = await manager.search_tags_by_prefix("artist_alias", 10)
        assert alias_prefix[0]["tag"] == "artist_name"
        assert alias_prefix[0]["translation_cn"] is None

        assert await manager.search_tags_by_translation("遗留艺术家译名", 10) == []
        assert await manager.search_tags_optimized(
            "遗留艺术家译名", 10, search_type="chinese"
        ) == []

        all_rows = {row["tag"]: row for row in await manager.get_all_tags()}
        assert all_rows["artist_name"]["translation_cn"] is None
        assert all_rows["character_name"]["translation_cn"] == "角色名"
        await manager.close()

    asyncio.run(scenario())


def test_nonartist_upsert_still_preserves_or_fills_translation(monkeypatch, tmp_path):
    module = _load_db_manager_module(monkeypatch)

    async def scenario():
        manager = module.TagDatabaseManager(str(tmp_path / "upsert.db"))
        await manager.initialize_database()
        await manager.insert_tag("general_tag", 0, 1, "通用标签")
        await manager.insert_tags_batch([
            {"tag": "general_tag", "category": 0, "post_count": 2},
            {
                "tag": "was_artist",
                "category": 1,
                "post_count": 3,
                "translation_cn": "不会写入",
            },
        ])
        await manager.insert_tag("was_artist", 4, 4, "现在是角色")

        assert (await manager.get_tag("general_tag"))["translation_cn"] == "通用标签"
        assert (await manager.get_tag("was_artist"))["translation_cn"] == "现在是角色"
        await manager.close()

    asyncio.run(scenario())


def test_chinese_fts_search_quotes_translated_tag_punctuation(monkeypatch, tmp_path):
    module = _load_db_manager_module(monkeypatch)

    async def scenario():
        manager = module.TagDatabaseManager(str(tmp_path / "punctuation-search.db"))
        await manager.initialize_database()
        await manager.insert_tags_batch([
            {
                "tag": "commentary",
                "category": 5,
                "post_count": 100,
                "translation_cn": "作者注释(英文可读)",
            },
            {
                "tag": ">_<",
                "category": 0,
                "post_count": 90,
                "translation_cn": "用力闭眼|>_<形紧闭眼",
            },
        ])

        commentary = await manager.search_tags_optimized(
            "作者注释(英文可读)", 10, search_type="chinese"
        )
        assert commentary[0]["tag"] == "commentary"

        symbolic = await manager.search_tags_optimized(
            "用力闭眼|>_<形紧闭眼", 10, search_type="chinese"
        )
        assert symbolic[0]["tag"] == ">_<"

        partial = await manager.search_tags_optimized(
            "作者注释", 10, search_type="chinese"
        )
        assert any(row["tag"] == "commentary" for row in partial)
        await manager.close()

    asyncio.run(scenario())
