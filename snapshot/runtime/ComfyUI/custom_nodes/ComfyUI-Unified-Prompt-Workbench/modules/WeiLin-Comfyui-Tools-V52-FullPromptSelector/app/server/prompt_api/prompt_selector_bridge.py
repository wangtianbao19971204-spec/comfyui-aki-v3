# -*- coding: utf-8 -*-
"""
WeiLin <-> PromptSelector bridge.

WeiLin owns the Prompt Selector shared library.  The canonical store is
user_data/prompt_selector under this plug-in.  No Gallery location is scanned or used.
"""

import json
import os
from aiohttp import web
from server import PromptServer

BASE_URL = "/weilin/prompt_ui/api/"


def _plugin_root() -> str:
    # app/server/prompt_api/prompt_selector_bridge.py -> plugin root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))


def _prompt_selector_candidates():
    # V52+: Prompt Selector is fully owned by WeiLin; no Gallery fallback.
    yield os.path.join(_plugin_root(), "user_data", "prompt_selector")


def _find_prompt_selector_dir():
    seen = set()
    for p in _prompt_selector_candidates():
        p = os.path.abspath(p)
        if p in seen:
            continue
        seen.add(p)
        data_path = os.path.join(p, "data.json")
        if os.path.isfile(data_path):
            return p
    return None


def _checked_locations():
    locs = []
    seen = set()
    for p in _prompt_selector_candidates():
        p = os.path.abspath(os.path.join(p, "data.json"))
        if p not in seen:
            seen.add(p)
            locs.append(p)
    return locs[:20]


def _sanitize_data(data):
    """Return only the fields the front-end panel needs."""
    categories = []
    for cat in data.get("categories", []) or []:
        prompts = []
        for item in cat.get("prompts", []) or []:
            prompts.append({
                "id": item.get("id", ""),
                "alias": item.get("alias", ""),
                "prompt": item.get("prompt", ""),
                "description": item.get("description", ""),
                "image": item.get("image", ""),
                "tags": item.get("tags", []),
                "favorite": bool(item.get("favorite", False)),
                "updated_at": item.get("updated_at", item.get("created_at", "")),
            })
        categories.append({
            "id": cat.get("id", cat.get("name", "")),
            "name": cat.get("name", "未分类"),
            "updated_at": cat.get("updated_at", ""),
            "prompts": prompts,
        })
    return {
        "version": data.get("version", ""),
        "settings": data.get("settings", {}),
        "last_modified": data.get("last_modified", ""),
        "categories": categories,
    }


@PromptServer.instance.routes.get(BASE_URL + "prompt_selector_bridge/data")
async def _weilin_prompt_selector_bridge_data(request):
    prompt_selector_dir = _find_prompt_selector_dir()
    if not prompt_selector_dir:
        return web.json_response({
            "code": 404,
            "error": "WeiLin PromptSelector data.json not found under user_data/prompt_selector.",
            "checked": _checked_locations(),
        }, status=404)

    data_path = os.path.join(prompt_selector_dir, "data.json")
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        safe = _sanitize_data(data)
        safe["bridge"] = {
            "source": data_path,
            "preview_dir": os.path.join(prompt_selector_dir, "preview"),
        }
        return web.json_response({"code": 200, "data": safe})
    except Exception as e:
        return web.json_response({"code": 500, "error": str(e)}, status=500)


@PromptServer.instance.routes.get(BASE_URL + "prompt_selector_bridge/preview/{filename:.*}")
async def _weilin_prompt_selector_bridge_preview(request):
    prompt_selector_dir = _find_prompt_selector_dir()
    if not prompt_selector_dir:
        raise web.HTTPNotFound()

    # PromptSelector stores just a filename in prompt.image. Reject paths.
    filename = os.path.basename(request.match_info.get("filename", ""))
    if not filename:
        raise web.HTTPNotFound()

    preview_dir = os.path.abspath(os.path.join(prompt_selector_dir, "preview"))
    image_path = os.path.abspath(os.path.join(preview_dir, filename))
    if not image_path.startswith(preview_dir + os.sep):
        raise web.HTTPForbidden()
    if not os.path.isfile(image_path):
        raise web.HTTPNotFound()

    return web.FileResponse(image_path)
