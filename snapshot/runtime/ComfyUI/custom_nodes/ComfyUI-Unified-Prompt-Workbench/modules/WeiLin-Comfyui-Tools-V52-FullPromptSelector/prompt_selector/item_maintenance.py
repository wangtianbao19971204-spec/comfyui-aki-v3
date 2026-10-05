"""Unified single-item metadata service for Tag and shared prompt resources.

The single-item dialog is a thin dispatch layer: a row is owned either by the
legacy WeiLin Tag database (:class:`TagLibrary`, optimistic revision through
``If-Match``) or by the shared prompt store (``prompt_selector.data.json``,
optimistic revision through ``last_modified``).  Nothing here invents a third
storage, migrates records or renames collections.
"""
from __future__ import annotations

import copy
import os
import threading
from datetime import datetime
from typing import Any

from ..app.server.dao import dao
from . import prompt_selector as prompt_store
from .semantic_projection import binding as semantic_binding, decision_for, read_projection
from .selector_library import apply_collection, collection_groups, selector_kind, validate_groups
from .tag_library import TagConflict, TagLibrary


_WRITE_LOCK = threading.RLock()


def classify_identity(resource_id: Any):
    """Resolve the owner namespace of a single resource identity.

    ``tag:<uuid>`` addresses a legacy Tag row.  Everything else is a shared
    resource id: Anima selector entries use ``anima-<kind>-<hash>`` while the
    WeiLin library keeps its own UUIDs, and both live in the same prompt store.
    """
    if not isinstance(resource_id, str) or not resource_id.strip():
        raise ValueError('缺少 resource_id')
    value = resource_id.strip()
    if value.startswith('tag:'):
        identity = value[4:]
        if not identity:
            raise ValueError('Tag 身份无效')
        return 'tag', identity, value
    return 'prompt', value, value


def _groups(data):
    groups = collection_groups(data)
    validate_groups(groups)
    return groups


def _state():
    data = prompt_store._read_prompt_data_cached()
    return data, _groups(data), prompt_store._revision(data)


def _valid_collection_ids(value, groups):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('收藏组必须是 ID 列表')
    known = {str(group.get('id')) for group in groups}
    if any(item not in known for item in value):
        raise ValueError('收藏组已不存在，请重新选择。未保存当前修改。')
    return list(dict.fromkeys(value))


def _memberships(item, groups):
    """Keep the same membership shape the classic Tag and selector surfaces use."""
    known = {str(group.get('id')) for group in groups}
    identities = [identity for identity in item.get('collection_ids') or [] if identity in known]
    return identities or (['default'] if item.get('favorite') else [])


def _find_prompt(data, resource_id):
    def walk(category):
        if not isinstance(category, dict):
            return None
        for prompt in category.get('prompts', []) or []:
            if isinstance(prompt, dict) and prompt.get('id') == resource_id:
                return category, prompt
        for child in category.get('categories', []) or []:
            found = walk(child)
            if found:
                return found
        return None
    for category in data.get('categories', []) or []:
        found = walk(category)
        if found:
            return found
    raise KeyError('资料已移动或不存在，请刷新后重试')


def _decision(category, prompt):
    explicit = prompt.get('_classification')
    if isinstance(explicit, dict) and explicit.get('binding') == semantic_binding(category, prompt):
        return explicit
    projection_path = os.path.join(prompt_store.PROMPT_STORE_DIR, 'semantic_projection.json')
    if not os.path.exists(projection_path):
        return {}
    return decision_for(read_projection(projection_path), category, prompt)


def _prompt_kind(category, prompt):
    return selector_kind(_decision(category, prompt)) or 'resource'


def _tag_view(resource_id, groups, collection_revision):
    library = TagLibrary(dao.tags_db_path)
    result = library.get(resource_id[4:])
    item = result['item']
    favorite = bool(item.get('favorite'))
    return {
        'resource_id': resource_id,
        'owner': 'tag',
        'kind': 'tag',
        'favorite': favorite,
        'notes': str(item.get('notes') or ''),
        # The legacy Tag surface keeps no collection alias.
        'nickname': '',
        'collection_ids': _memberships({'favorite': favorite, 'collection_ids': item.get('collection_ids')}, groups),
        'revision': result['revision'],
        'owner_revision': result['revision'],
        # The catalog lives in the shared store; the row itself is owned by the Tag database.
        'collection_revision': collection_revision,
        'collections': groups,
    }


def _prompt_view(category, prompt, groups, revision, resource_id):
    metadata = prompt.get('_collection')
    if not isinstance(metadata, dict):
        # The shared editor creates ``_collection`` on demand, so an item that
        # was never grouped reads as an empty draft instead of an error.
        metadata = {}
    return {
        'resource_id': resource_id,
        'owner': 'prompt',
        'kind': _prompt_kind(category, prompt),
        'favorite': bool(prompt.get('favorite')),
        'notes': str(metadata.get('notes') or ''),
        'nickname': str(metadata.get('nickname') or ''),
        'collection_ids': _memberships(
            {'favorite': prompt.get('favorite'), 'collection_ids': metadata.get('groupIds')}, groups),
        'revision': revision,
        'owner_revision': revision,
        'collection_revision': revision,
        'collections': groups,
        'prompt': {
            'id': prompt.get('id'),
            'alias': prompt.get('alias', ''),
            'category_id': category.get('id'),
            'category_name': category.get('name', ''),
        },
    }


def read_item(resource_id):
    owner, _, canonical = classify_identity(resource_id)
    data, groups, revision = _state()
    if owner == 'tag':
        return _tag_view(canonical, groups, revision)
    category, prompt = _find_prompt(data, canonical)
    return _prompt_view(category, prompt, groups, revision, canonical)


def _payload(payload, groups):
    if not isinstance(payload, dict):
        raise ValueError('维护操作必须是对象')
    expected = payload.get('base_revision', payload.get('revision'))
    if not isinstance(expected, str) or not expected.strip():
        raise ValueError('请先读取当前资源版本')
    if type(payload.get('favorite')) is not bool:
        raise ValueError('收藏状态必须为布尔值')
    if not isinstance(payload.get('notes'), str):
        raise ValueError('备注必须为文本')
    nickname = payload.get('nickname')
    if nickname is not None and not isinstance(nickname, str):
        raise ValueError('收藏别名必须为文本')
    collection_ids = _valid_collection_ids(payload.get('collection_ids'), groups)
    expected = expected.strip()
    if len(expected) >= 2 and expected.startswith('"') and expected.endswith('"'):
        expected = expected[1:-1]
    return expected, payload['favorite'], payload['notes'], collection_ids, nickname


def _write_tag(canonical, expected, favorite, notes, collection_ids, nickname, groups, revision):
    if nickname:
        raise ValueError('Tag 收藏暂无别名，请留空。未保存当前修改。')
    library = TagLibrary(dao.tags_db_path)
    library.update({
        'operation': 'metadata',
        'resource_id': canonical,
        'favorite': favorite,
        'notes': notes,
        'collection_ids': collection_ids,
    }, expected)
    return _tag_view(canonical, groups, revision)


def _write_prompt(canonical, expected, favorite, notes, collection_ids, nickname, groups):
    with prompt_store._PROMPT_FILE_LOCK:
        current = prompt_store._read_prompt_data_cached()
        prompt_store._require_revision({'base_revision': expected}, current)
        _valid_collection_ids(collection_ids, _groups(current))
        updated = copy.deepcopy(current)
        updated_category, updated_prompt = _find_prompt(updated, canonical)
        # Same owner helpers the shared editor uses, so collection drafts under
        # ``_selector_favorites[kind]`` stay in step with ``_collection``.
        details = {'notes': notes}
        if nickname is not None:
            details['nickname'] = nickname
        apply_collection(updated, updated_prompt, _decision(updated_category, updated_prompt),
                         collection_ids, details=details)
        updated_prompt['favorite'] = favorite
        stamp = datetime.now().isoformat()
        updated_prompt['updated_at'] = stamp
        updated_category['updated_at'] = stamp
        updated['last_modified'] = stamp
        prompt_store._atomic_save_json(
            prompt_store.DATA_FILE,
            updated,
            compact=True,
            create_backup=prompt_store._should_create_route_branch_backup(),
            expected_revision=expected,
        )
        prompt_store._cache_prompt_data(updated)
        return _prompt_view(updated_category, updated_prompt, _groups(updated),
                            prompt_store._revision(updated), canonical)


def write_item(resource_id, payload):
    owner, _, canonical = classify_identity(resource_id)
    with _WRITE_LOCK:
        data, groups, revision = _state()
        expected, favorite, notes, collection_ids, nickname = _payload(payload, groups)
        if owner == 'tag':
            return _write_tag(canonical, expected, favorite, notes, collection_ids, nickname, groups, revision)
        return _write_prompt(canonical, expected, favorite, notes, collection_ids, nickname, groups)
