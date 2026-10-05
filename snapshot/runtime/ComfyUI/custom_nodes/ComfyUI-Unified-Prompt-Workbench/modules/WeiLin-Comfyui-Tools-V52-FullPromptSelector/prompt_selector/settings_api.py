"""Small, revision-bound owner for the WeiLin prompt-selector settings.

The legacy whole-library save (``POST /prompt_selector/data``) posts the reviewed
projection back to the server: at the current library size that is ~110 MB, which
exceeds ComfyUI's request limit, and when it does land it rewrites the file with
``indent=4`` (roughly doubling it).  ``settings`` is one small subtree, so it gets
its own owner: a single locked, atomic, compact write of just that subtree.
"""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime

from aiohttp import web
from server import PromptServer

from . import prompt_selector as store


SETTINGS_BYTE_LIMIT = 64 * 1024


def read_settings():
    data = store._read_prompt_data_cached()
    return {'success': True, 'settings': copy.deepcopy(data.get('settings') or {}),
            'revision': store._revision(data)}


def write_settings(payload):
    """Replace the settings subtree in one atomic, compact save."""
    if not isinstance(payload, dict):
        raise ValueError('设置保存需要对象')
    submitted = payload.get('settings')
    if not isinstance(submitted, dict):
        raise ValueError('settings 必须为对象')
    encoded = json.dumps(submitted, ensure_ascii=False).encode('utf-8')
    if len(encoded) > SETTINGS_BYTE_LIMIT:
        raise ValueError(f'设置内容过大（上限 {SETTINGS_BYTE_LIMIT // 1024} KB）；本端点只保存设置')
    with store._PROMPT_FILE_LOCK:
        current = store._read_prompt_data_cached()
        store._require_revision(payload, current)
        updated = copy.deepcopy(current)
        updated['settings'] = copy.deepcopy(submitted)
        updated['last_modified'] = datetime.now().isoformat()
        store._atomic_save_json(store.DATA_FILE, updated, compact=True,
            create_backup=store._should_create_route_branch_backup(),
            expected_revision=store._revision(current))
        store._cache_prompt_data(updated)
        return {'success': True, 'settings': copy.deepcopy(submitted),
                'revision': store._revision(updated)}


@PromptServer.instance.routes.get('/prompt_selector/settings')
async def get_settings(request):
    try:
        result = await asyncio.to_thread(read_settings)
        return store._with_etag(web.json_response(result), result['revision'])
    except Exception as error:  # noqa: BLE001 - the route reports instead of hiding
        store.logger.error('读取设置失败: %s', error)
        return web.json_response({'error': str(error)}, status=500)


@PromptServer.instance.routes.post('/prompt_selector/settings')
async def save_settings(request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('设置保存需要对象')
        payload['base_revision'] = store._request_revision(request, payload)
        if not payload['base_revision']:
            return web.json_response({'error': '请先读取当前共享库版本'}, status=428)
        async with store._PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(write_settings, payload)
        return store._with_etag(web.json_response(result), result['revision'])
    except store.RevisionConflict as error:
        return store._with_etag(web.json_response(
            {'error': str(error), 'conflict': True, 'current_revision': error.actual}, status=409),
            error.actual)
    except (ValueError, TypeError) as error:
        return web.json_response({'error': str(error)}, status=400)
    except Exception as error:  # noqa: BLE001
        store.logger.error('保存设置失败: %s', error)
        return web.json_response({'error': str(error)}, status=500)
