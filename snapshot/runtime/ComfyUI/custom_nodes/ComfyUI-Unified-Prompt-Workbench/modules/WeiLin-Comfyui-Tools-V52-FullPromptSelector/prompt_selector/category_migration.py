"""Give legacy categories the stable ids the editor and the item endpoints use.

A library written before categories carried ids is migrated by its own owner.
The node editor used to add the ids in memory and post the whole library back:
at the current size that body exceeds ComfyUI's request limit, and the server
then kept a category list without ids - which is exactly what
``/prompts/upsert`` looks a target category up by, so a save could land in
"默认/其他" instead of the category the user chose.  This endpoint applies the
same deterministic ``cat-<hash>`` scheme the editor uses, in one locked,
compact write, and hands the resulting names and ids back.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime

from aiohttp import web
from server import PromptServer

from . import prompt_selector as store


def _to_int32(value):
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def _utf16_units(text):
    encoded = text.encode('utf-16-le')
    return [int.from_bytes(encoded[index:index + 2], 'little')
            for index in range(0, len(encoded), 2)]


def simple_hash(text):
    """Reproduce the editor's ``simpleHash`` (32-bit JS integer arithmetic)."""
    value = 0
    for unit in _utf16_units(text):
        # In the editor: ``hash = ((hash << 5) - hash) + charCode; hash &= hash``
        value = _to_int32(value * 31 + unit)
    return f'{abs(value):08x}'


def deterministic_category_id(name):
    return f'cat-{simple_hash(str(name or ""))}'


def _children(category):
    nested = category.get('categories')
    return nested if isinstance(nested, list) else []


def _existing_ids(categories, collected=None):
    collected = set() if collected is None else collected
    for category in categories if isinstance(categories, list) else []:
        if not isinstance(category, dict):
            continue
        identifier = str(category.get('id') or '').strip()
        if identifier:
            collected.add(identifier)
        _existing_ids(_children(category), collected)
    return collected


def _rows(categories):
    """Mirror the category tree with just the identity the editor needs."""
    rows = []
    for category in categories if isinstance(categories, list) else []:
        if not isinstance(category, dict):
            continue
        row = {'name': str(category.get('name') or ''),
               'id': str(category.get('id') or '')}
        nested = _children(category)
        if nested:
            row['categories'] = _rows(nested)
        rows.append(row)
    return rows


def _assign_ids(categories, taken, now):
    """Id per category in document order; a repeated name gets a numbered suffix."""
    assigned = 0
    for category in categories if isinstance(categories, list) else []:
        if not isinstance(category, dict):
            continue
        name = str(category.get('name') or '')
        identifier = str(category.get('id') or '').strip()
        if not identifier:
            identifier = deterministic_category_id(name)
            suffix = 2
            while identifier in taken:
                identifier = f'{deterministic_category_id(name)}-{suffix}'
                suffix += 1
            category['id'] = identifier
            category['updated_at'] = now
            assigned += 1
        taken.add(identifier)
        assigned += _assign_ids(_children(category), taken, now)
    return assigned


def migrate_category_ids(payload):
    """Add the missing ids in place; a library that already has them is untouched."""
    with store._PROMPT_FILE_LOCK:
        current = store._read_prompt_data_cached()
        store._require_revision(payload, current)
        categories = current.get('categories') if isinstance(current, dict) else None
        if not isinstance(categories, list):
            raise ValueError('词库分类结构无效')
        taken = _existing_ids(categories)
        missing = sum(1 for category in _flatten(categories)
                      if not str(category.get('id') or '').strip())
        if not missing:
            return {'success': True, 'changed': False, 'migrated': 0,
                    'categories': _rows(categories), 'revision': store._revision(current)}
        updated = copy.deepcopy(current)
        now = datetime.now().isoformat()
        migrated = _assign_ids(updated['categories'], taken, now)
        projection = store.read_projection(store.os.path.join(store.PROMPT_STORE_DIR, 'semantic_projection.json'))
        for old_category, category in zip(_flatten(current['categories']), _flatten(updated['categories'])):
            for old_prompt, prompt in zip(old_category.get('prompts', []), category.get('prompts', [])):
                store.rebind_unchanged_prompt(projection, old_category, old_prompt, category, prompt)
        updated['last_modified'] = now
        store._atomic_save_json(store.DATA_FILE, updated, compact=True,
            create_backup=store._should_create_route_branch_backup(),
            expected_revision=store._revision(current))
        store._cache_prompt_data(updated)
        return {'success': True, 'changed': True, 'migrated': migrated,
                'categories': _rows(updated['categories']), 'revision': store._revision(updated)}


def _flatten(categories, collected=None):
    collected = [] if collected is None else collected
    for category in categories if isinstance(categories, list) else []:
        if not isinstance(category, dict):
            continue
        collected.append(category)
        _flatten(_children(category), collected)
    return collected


@PromptServer.instance.routes.post('/prompt_selector/categories/migrate_ids')
async def categories_migrate_ids(request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('分类迁移操作必须为对象')
        payload['base_revision'] = store._request_revision(request, payload)
        if not payload['base_revision']:
            return web.json_response({'error': '请先读取当前共享库版本'}, status=428)
        async with store._PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(migrate_category_ids, payload)
        return store._with_etag(web.json_response(result), result['revision'])
    except store.RevisionConflict as error:
        return store._with_etag(web.json_response(
            {'error': str(error), 'conflict': True, 'current_revision': error.actual}, status=409),
            error.actual)
    except (ValueError, TypeError) as error:
        return web.json_response({'error': str(error)}, status=400)
    except Exception as error:  # noqa: BLE001 - the route reports instead of hiding
        store.logger.error('分类 ID 迁移失败: %s', error)
        return web.json_response({'error': str(error)}, status=500)
