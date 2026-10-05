"""Shared collection membership for resources maintained by other providers.

Only references live here. Model metadata, image Tags and favorite state remain
with their original service. No model path is opened or modified by this module.
"""
import asyncio
import copy
import os
from datetime import datetime

from aiohttp import web
from server import PromptServer

from . import prompt_selector as store
from .selector_library import collection_groups, migrate_collections

PROVIDERS = {'loras', 'checkpoints', 'embeddings', 'danbooru', 'gelbooru', 'yandere', 'civitai'}


def identity(provider, resource):
    if provider not in PROVIDERS or not isinstance(resource, str) or not resource.strip() or len(resource) > 4096:
        raise ValueError('资源引用无效')
    if provider in {'loras', 'checkpoints', 'embeddings'}:
        resource = os.path.normcase(resource).replace('\\', '/')
    return provider, resource


def read_references(provider=None, resource=None, group_id=None):
    data = store._read_prompt_data_cached()
    groups = collection_groups(data)
    known = {item['id'] for item in groups}
    if provider and provider not in PROVIDERS:
        raise ValueError('资源来源无效')
    if group_id and group_id not in known:
        raise ValueError('收藏组已不存在，请刷新列表')
    if resource is not None:
        provider, resource = identity(provider, resource)
    records = []
    for source, entries in data.get('selector_library', {}).get('references', {}).items():
        if provider and source != provider:
            continue
        for key, memberships in entries.items():
            if resource is not None and key != resource:
                continue
            normalized = [item for item in memberships if item in known] or ['default']
            if not group_id or group_id in normalized:
                records.append({'provider': source, 'resource': key, 'group_ids': normalized})
    return {'groups': groups, 'items': records, 'revision': store._revision(data)}


def save_references(payload):
    rows = payload.get('items')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValueError('每次可修改 1 至 500 个资源引用')
    with store._PROMPT_FILE_LOCK:
        current = store._read_prompt_data_cached()
        store._require_revision(payload, current)
        updated = copy.deepcopy(current)
        migrate_collections(updated)
        known = {item['id'] for item in collection_groups(updated)}
        references = updated['selector_library'].setdefault('references', {})
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('资源引用格式无效')
            provider, resource = identity(row.get('provider'), row.get('resource'))
            if (provider, resource) in seen:
                raise ValueError('同一次修改中不能重复指定同一资源')
            seen.add((provider, resource))
            groups = row.get('group_ids')
            if not isinstance(groups, list) or any(not isinstance(group, str) or group not in known for group in groups):
                raise ValueError('收藏组已变化，请重新读取后选择')
            records = references.setdefault(provider, {})
            if groups:
                records[resource] = list(dict.fromkeys(groups))
            else:
                records.pop(resource, None)
        changed = updated != current
        if changed:
            updated['last_modified'] = datetime.now().isoformat()
            store._atomic_save_json(store.DATA_FILE, updated, compact=True,
                create_backup=store._should_create_route_branch_backup(), expected_revision=store._revision(current))
            store._cache_prompt_data(updated)
        return {'success': True, 'changed': changed, 'revision': store._revision(updated)}


def relocate_reference(model_type, old_path, new_path=None):
    """Follow the successful file mutation performed by the model owner."""
    provider = {'lora':'loras', 'checkpoint':'checkpoints', 'embedding':'embeddings'}[model_type]
    _, old_key = identity(provider, old_path)
    new_key = identity(provider, new_path)[1] if new_path else None
    if new_key == old_key:
        return
    with store._PROMPT_FILE_LOCK:
        current = store._read_prompt_data_cached()
        records = current.get('selector_library', {}).get('references', {}).get(provider, {})
        if old_key not in records:
            return
        updated = copy.deepcopy(current)
        target = updated['selector_library']['references'][provider]
        members = target.pop(old_key)
        if new_key:
            target[new_key] = list(dict.fromkeys([*target.get(new_key, []), *members]))
        updated['last_modified'] = datetime.now().isoformat()
        store._atomic_save_json(store.DATA_FILE, updated, compact=True,
            create_backup=store._should_create_route_branch_backup(), expected_revision=store._revision(current))
        store._cache_prompt_data(updated)


def relocate_references(model_type, pairs):
    """Follow a whole batch of file moves that a rescan proved by fingerprint.

    A rescan can show one path gone while the very same file - identical
    ``sha256``, or the same file name and byte size when a side carries no hash -
    is now listed somewhere else.  The scanner only hands over one-to-one
    matches, so those memberships move to the new path in a single locked,
    compact write; every path the scanner could not prove is dropped by
    ``prune_references`` instead.  Nothing here looks at file names to guess a
    replacement.
    """
    provider = {'lora':'loras', 'checkpoint':'checkpoints', 'embedding':'embeddings'}[model_type]
    moves, skipped = [], 0
    for pair in pairs or ():
        try:
            old_path, new_path = pair
            _, old_key = identity(provider, old_path)
            _, new_key = identity(provider, new_path)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if old_key != new_key and (old_key, new_key) not in moves:
            moves.append((old_key, new_key))
    with store._PROMPT_FILE_LOCK:
        current = store._read_prompt_data_cached()
        records = current.get('selector_library', {}).get('references', {}).get(provider, {})
        carried = [(old_key, new_key) for old_key, new_key in moves if old_key in records]
        if not carried:
            return {'success': True, 'changed': False, 'moved': 0, 'skipped': skipped,
                    'revision': store._revision(current)}
        updated = copy.deepcopy(current)
        target = updated['selector_library']['references'][provider]
        for old_key, new_key in carried:
            members = target.pop(old_key)
            target[new_key] = list(dict.fromkeys([*target.get(new_key, []), *members]))
        updated['last_modified'] = datetime.now().isoformat()
        store._atomic_save_json(store.DATA_FILE, updated, compact=True,
            create_backup=store._should_create_route_branch_backup(), expected_revision=store._revision(current))
        store._cache_prompt_data(updated)
        return {'success': True, 'changed': True, 'moved': len(carried), 'skipped': skipped,
                'revision': store._revision(updated)}


def prune_references(model_type, paths):
    """Drop references whose file disappeared outside the app's own operations.

    A rescan can only see that a path is gone; it must never guess a replacement
    by file name.  Every vanished path therefore loses its membership in one
    locked, compact write, so the shared directory cannot keep pointing at files
    that no longer exist.
    """
    provider = {'lora':'loras', 'checkpoint':'checkpoints', 'embedding':'embeddings'}[model_type]
    keys, removed = [], []
    for path in paths or ():
        try:
            _, key = identity(provider, path)
        except ValueError:
            continue
        if key not in keys:
            keys.append(key)
    with store._PROMPT_FILE_LOCK:
        current = store._read_prompt_data_cached()
        records = current.get('selector_library', {}).get('references', {}).get(provider, {})
        removed = [key for key in keys if key in records]
        if not removed:
            return {'success': True, 'changed': False, 'removed': 0,
                    'revision': store._revision(current)}
        updated = copy.deepcopy(current)
        target = updated['selector_library']['references'][provider]
        for key in removed:
            target.pop(key, None)
        if not target:
            updated['selector_library']['references'].pop(provider, None)
        updated['last_modified'] = datetime.now().isoformat()
        store._atomic_save_json(store.DATA_FILE, updated, compact=True,
            create_backup=store._should_create_route_branch_backup(), expected_revision=store._revision(current))
        store._cache_prompt_data(updated)
        return {'success': True, 'changed': True, 'removed': len(removed),
                'revision': store._revision(updated)}


@PromptServer.instance.routes.get('/prompt_selector/collections/references')
async def references_index(request):
    try:
        return store._success_response(await asyncio.to_thread(read_references,
            request.query.get('provider'), request.query.get('resource'), request.query.get('group_id')))
    except ValueError as error:
        return web.json_response({'error': str(error)}, status=400)


@PromptServer.instance.routes.post('/prompt_selector/collections/references')
async def references_update(request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('资源分组操作必须为对象')
        payload['base_revision'] = store._request_revision(request, payload)
        async with store._PROMPT_DATA_LOCK:
            return store._success_response(await asyncio.to_thread(save_references, payload))
    except store.RevisionConflict as error:
        return store._with_etag(web.json_response({'error': str(error), 'conflict': True}, status=409), error.actual)
    except (ValueError, TypeError) as error:
        return web.json_response({'error': str(error)}, status=400)


PromptServer.instance.weilin_reference_collections = read_references
PromptServer.instance.weilin_relocate_reference = relocate_reference
PromptServer.instance.weilin_relocate_references = relocate_references
PromptServer.instance.weilin_prune_references = prune_references
