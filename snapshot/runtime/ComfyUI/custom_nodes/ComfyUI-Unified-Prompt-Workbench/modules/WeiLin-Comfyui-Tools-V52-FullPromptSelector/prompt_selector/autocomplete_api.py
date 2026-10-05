# -*- coding: utf-8 -*-
"""WeiLin-owned autocomplete API for Prompt Selector.

This module intentionally does not import or call ComfyUI-Danbooru-Gallery.
It queries WeiLin's own userdatas_*_danbooru.db database and exposes only the
three endpoints required by the Prompt Selector front-end.
"""

import asyncio
from contextlib import closing
import hashlib
import json
import logging
import os
import sqlite3
from aiohttp import web
from server import PromptServer

try:
    from ..app.server.dao.dao import danbooru_db_path
except Exception:
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    _user_data = os.path.join(_root, "user_data")
    _candidates = sorted(
        os.path.join(_user_data, name)
        for name in os.listdir(_user_data)
        if name.startswith("userdatas_") and name.endswith("_danbooru.db")
    ) if os.path.isdir(_user_data) else []
    danbooru_db_path = _candidates[0] if _candidates else os.path.join(_user_data, "userdatas_zh_CN_danbooru.db")

logger = logging.getLogger("weilin.prompt_selector.autocomplete")
BASE = "/weilin_prompt_selector"


def _dictionary_revision():
    signature = []
    for path in (danbooru_db_path, danbooru_db_path + "-wal"):
        try:
            stat = os.stat(path)
            signature.append((stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            signature.append(None)
    return hashlib.sha256(json.dumps(signature).encode("ascii")).hexdigest()


@PromptServer.instance.routes.get(BASE + "/autocomplete_revision")
async def autocomplete_revision(request):
    return web.json_response({"revision": _dictionary_revision()}, headers={"Cache-Control": "no-store"})

def _safe_limit(value, default=20, maximum=100):
    try:
        return max(1, min(int(value), maximum))
    except Exception:
        return default

def _like_escape(text):
    # Parameters are bound through sqlite3, so this is not an SQL injection path.
    # Keep LIKE wildcard behavior for advanced users who intentionally type % or _.
    return str(text or "")

def _aliases(value):
    if value in (None, "", 0, "0"):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []

def _query_english(query, limit):
    if not os.path.isfile(danbooru_db_path):
        logger.warning("WeiLin Danbooru DB not found: %s", danbooru_db_path)
        return []
    q = str(query or "").strip()
    escaped = _like_escape(q)
    prefix = escaped + "%"
    contains = "%" + escaped + "%"
    sql_prefix = """
        SELECT tag, color_id, translate, hot, aliases
        FROM danbooru_tag
        WHERE tag LIKE ?
        ORDER BY CASE WHEN tag = ? THEN 0 ELSE 1 END, hot DESC, tag ASC
        LIMIT ?
    """
    sql_contains = """
        SELECT tag, color_id, translate, hot, aliases
        FROM danbooru_tag
        WHERE tag LIKE ?
        ORDER BY CASE WHEN tag = ? THEN 0 WHEN tag LIKE ? THEN 1 ELSE 2 END,
                 hot DESC, tag ASC
        LIMIT ?
    """
    with closing(sqlite3.connect(danbooru_db_path)) as conn:
        rows = conn.execute(sql_prefix, (prefix, q, limit)).fetchall()
        if not rows:
            rows = conn.execute(sql_contains, (contains, q, prefix, limit)).fetchall()
    return [
        {
            "name": row[0],
            "tag": row[0],
            "category": row[1] or 0,
            "translation": row[2] or "",
            "post_count": row[3] or 0,
            "aliases": _aliases(row[4]),
        }
        for row in rows
    ]

def _query_chinese(query, limit):
    if not os.path.isfile(danbooru_db_path):
        logger.warning("WeiLin Danbooru DB not found: %s", danbooru_db_path)
        return []
    q = str(query or "").strip()
    escaped = _like_escape(q)
    prefix = escaped + "%"
    contains = "%" + escaped + "%"
    sql = """
        SELECT tag, color_id, translate, hot
        FROM danbooru_tag
        WHERE translate LIKE ? OR tag LIKE ?
        ORDER BY CASE
            WHEN translate = ? THEN 0
            WHEN translate LIKE ? THEN 1
            WHEN tag = ? THEN 2
            WHEN tag LIKE ? THEN 3
            ELSE 4 END,
            hot DESC, tag ASC
        LIMIT ?
    """
    with closing(sqlite3.connect(danbooru_db_path)) as conn:
        rows = conn.execute(sql, (contains, contains, q, prefix, q, prefix, limit)).fetchall()
    return [
        {
            "chinese": row[2] or "",
            "english": row[0],
            "tag": row[0],
            "translation_cn": row[2] or "",
            "category": row[1] or 0,
            "post_count": row[3] or 0,
        }
        for row in rows
    ]

@PromptServer.instance.routes.get(BASE + "/autocomplete")
async def autocomplete(request):
    query = request.query.get("query", "").strip()
    if not query:
        return web.json_response([])
    limit = _safe_limit(request.query.get("limit"), 20)
    try:
        rows = await asyncio.to_thread(_query_english, query, limit)
        for row in rows:
            row.pop("translation", None)
        return web.json_response(rows)
    except Exception as exc:
        logger.exception("Prompt Selector autocomplete failed: %s", exc)
        return web.json_response([])

@PromptServer.instance.routes.get(BASE + "/autocomplete_with_translation")
async def autocomplete_with_translation(request):
    query = request.query.get("query", "").strip()
    if not query:
        return web.json_response([])
    limit = _safe_limit(request.query.get("limit"), 20)
    try:
        return web.json_response(await asyncio.to_thread(_query_english, query, limit))
    except Exception as exc:
        logger.exception("Prompt Selector translated autocomplete failed: %s", exc)
        return web.json_response([])

@PromptServer.instance.routes.get(BASE + "/search_chinese")
async def search_chinese(request):
    query = request.query.get("query", "").strip()
    if not query:
        return web.json_response({"success": True, "results": []})
    limit = _safe_limit(request.query.get("limit"), 10)
    try:
        rows = await asyncio.to_thread(_query_chinese, query, limit)
        return web.json_response({"success": True, "query": query, "results": rows})
    except Exception as exc:
        logger.exception("Prompt Selector Chinese search failed: %s", exc)
        return web.json_response({"success": False, "error": str(exc), "results": []})
