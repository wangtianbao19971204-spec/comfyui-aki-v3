from __future__ import annotations

import ast
import asyncio
import importlib.util
import logging
import re
import sys
import types
import unicodedata
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GALLERY_SOURCE = PLUGIN_ROOT / "py" / "danbooru_gallery" / "danbooru_gallery.py"
DB_SOURCE = PLUGIN_ROOT / "py" / "shared" / "db" / "db_manager.py"


def _load_translation_runtime():
    tree = ast.parse(GALLERY_SOURCE.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_normalize_translation_tag"
        )
        or (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_resolve_tag_translations"
        )
        or (isinstance(node, ast.ClassDef) and node.name == "TagTranslationSystem")
    ]
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {
        "csv": __import__("csv"),
        "json": __import__("json"),
        "os": __import__("os"),
        "re": re,
        "unicodedata": unicodedata,
        "PLUGIN_DIR": str(PLUGIN_ROOT / "py" / "danbooru_gallery"),
        "logger": logging.getLogger("translation-test"),
    }
    exec(compile(module, str(GALLERY_SOURCE), "exec"), namespace)
    return namespace


def _load_translation_class():
    return _load_translation_runtime()["TagTranslationSystem"]


def _load_db_manager_module(monkeypatch):
    package_names = ("tagtest", "tagtest.shared", "tagtest.shared.db", "tagtest.utils")
    for package_name in package_names:
        package = types.ModuleType(package_name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, package_name, package)
    logger_module = types.ModuleType("tagtest.utils.logger")
    logger_module.get_logger = lambda _name: logging.getLogger("tag-db-test")
    monkeypatch.setitem(sys.modules, "tagtest.utils.logger", logger_module)

    module_name = "tagtest.shared.db.db_manager"
    spec = importlib.util.spec_from_file_location(module_name, DB_SOURCE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_static_translation_normalizes_case_unicode_and_prompt_spaces():
    translation_class = _load_translation_class()
    translator = translation_class()
    translator.loaded = True
    translator.en_to_cn = {"long_hair": "长发", "1girl": "1名女孩"}

    assert translator.translate_tag("LONG HAIR") == "长发"
    assert translator.translate_tag("  long_hair  ") == "长发"
    assert translator.translate_tag("１ＧＩＲＬ") == "1名女孩"
    assert translator.translate_tags_batch(["Long Hair", "missing"]) == {
        "Long Hair": "长发"
    }


def test_chinese_reverse_search_is_one_to_many_without_separator_merging():
    translation_class = _load_translation_class()
    translator = translation_class()
    translator.loaded = True
    translator.en_to_cn = {
        "one_piece": "同名译文",
        "one-piece": "同名译文",
        "hero_(alternate_costume)": "英雄（替代服装）",
    }
    translator.cn_to_en = {}
    for english, chinese in translator.en_to_cn.items():
        translator._register_chinese_reverse(chinese, english)
    translator._build_chinese_search_index()

    same_label = translator.search_chinese_tags("同名译文", limit=10)
    assert [item["english"] for item in same_label] == ["one_piece", "one-piece"]
    assert translator.translate_tag("one_piece") == "同名译文"
    assert translator.translate_tag("one-piece") == "同名译文"

    qualified = translator.search_chinese_tags("替代服装", limit=10)
    assert qualified[0]["english"] == "hero_(alternate_costume)"


def test_resolver_masks_static_artist_and_prefers_database_translation():
    namespace = _load_translation_runtime()
    translator = namespace["TagTranslationSystem"]()
    translator.loaded = True
    translator.en_to_cn = {
        "alphonse_mucha": "阿尔丰斯·穆夏",
        "black_footwear": "黑色的鞋",
        "hero_(alternate_costume)": "英雄（替代服装）",
        "unknown_static_tag": "未知静态标签",
    }
    events = []

    class FakeDatabase:
        async def get_categories(self, tags):
            events.append(("categories", list(tags)))
            return {
                "alphonse_mucha": 1,
                "black_footwear": 0,
                "hero_(alternate_costume)": 4,
            }

        async def get_translations(self, tags):
            events.append(("translations", list(tags)))
            return {"black_footwear": "黑色鞋子"}

    namespace["translation_system"] = translator
    namespace["get_db_manager"] = lambda: FakeDatabase()

    resolved = asyncio.run(namespace["_resolve_tag_translations"]([
        "alphonse_mucha",
        "black_footwear",
        "hero_(alternate_costume)",
        "unknown_static_tag",
    ]))

    assert events[0][0] == "categories"
    assert "alphonse_mucha" not in events[1][1]
    assert "unknown_static_tag" not in events[1][1]
    assert "alphonse_mucha" not in resolved
    assert "unknown_static_tag" not in resolved
    assert resolved["black_footwear"] == "黑色鞋子"
    assert resolved["hero_(alternate_costume)"] == "英雄（替代服装）"


def test_tag_sync_upsert_preserves_translation_and_bulk_lookup(monkeypatch, tmp_path):
    module = _load_db_manager_module(monkeypatch)

    async def scenario():
        manager = module.TagDatabaseManager(str(tmp_path / "tags.db"))
        await manager.initialize_database()
        await manager.insert_tag("long_hair", 0, 10, "长发", ["long hair"])
        await manager.get_connection()
        await manager.insert_tags_batch(
            [{"tag": "long_hair", "category": 0, "post_count": 20}]
        )

        row = await manager.get_tag("long_hair")
        assert row["translation_cn"] == "长发"
        assert row["aliases"] == ["long hair"]
        assert row["post_count"] == 20
        assert await manager.get_translations(["LONG HAIR", "long_hair", "missing"]) == {
            "LONG HAIR": "长发",
            "long_hair": "长发",
        }

        connection = await manager.get_connection()
        hot_count = (await (await connection.execute("SELECT COUNT(*) FROM hot_tags")).fetchone())[0]
        fts_count = (await (await connection.execute("SELECT COUNT(*) FROM hot_tags_fts")).fetchone())[0]
        assert (hot_count, fts_count) == (1, 1)
        await manager.close()

    asyncio.run(scenario())


def test_translation_and_autocomplete_routes_use_one_resolver():
    source = GALLERY_SOURCE.read_text(encoding="utf-8")
    assert "raw_categories = await get_categories(clean_tags)" in source
    assert "db_translations = await db.get_translations(non_artist_tags)" in source
    assert "translations = await _resolve_tag_translations(tags)" in source
    assert "translation = (await _resolve_tag_translations([tag])).get(tag)" in source
    assert "'translation': tag.get('translation_cn')" not in source
    assert source.count("translations = await _resolve_tag_translations(names)") >= 6
    assert "if tag.get('category') != 1 and translations.get(tag['tag'])" in source
