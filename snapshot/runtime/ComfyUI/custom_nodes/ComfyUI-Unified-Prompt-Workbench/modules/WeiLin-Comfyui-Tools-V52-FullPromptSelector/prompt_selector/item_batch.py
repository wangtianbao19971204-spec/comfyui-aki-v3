"""Batch metadata maintenance for shared library resources.

Applies the exact same per-item semantics as the single-item service
(``item_maintenance``): favourite, collection membership and notes/alias are
written through ``apply_collection`` so ``_collection`` and
``_selector_favorites[kind]`` stay in step.  One reviewed revision covers the
whole batch and a single atomic save commits it.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Iterable, Mapping

from . import item_maintenance as items
from . import prompt_selector as prompt_store

MAX_ITEMS = 500
CHANGE_FIELDS = ("favorite", "notes", "nickname", "collection_add", "collection_remove")


def _resource_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError('resource_ids 必须是列表')
    identities = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError('resource_ids 只能包含非空文本')
        identity = entry.strip()
        if identity.startswith('tag:'):
            raise ValueError('Tag 请使用 Tag 管理的批量操作；本接口只处理共享资料。')
        identities.append(identity)
    unique = list(dict.fromkeys(identities))
    if not unique:
        raise ValueError('请先选择资料。')
    if len(unique) > MAX_ITEMS:
        raise ValueError(f'一次最多 {MAX_ITEMS} 条，请减少选择后再试。')
    return unique


def _changes(payload: Mapping[str, Any]) -> dict:
    unknown = set(payload) - {'resource_ids', 'base_revision', 'revision', *CHANGE_FIELDS}
    if unknown:
        raise ValueError('不支持的批量字段: ' + ', '.join(sorted(unknown)))
    if not any(field in payload for field in CHANGE_FIELDS):
        raise ValueError('批量维护至少需要一项修改。')
    changes: dict[str, Any] = {}
    if 'favorite' in payload:
        if type(payload['favorite']) is not bool:
            raise ValueError('收藏状态必须为布尔值')
        changes['favorite'] = payload['favorite']
    for field in ('notes', 'nickname'):
        if field in payload:
            if not isinstance(payload[field], str):
                raise ValueError(('备注' if field == 'notes' else '收藏别名') + '必须为文本')
            changes[field] = payload[field]
    for field in ('collection_add', 'collection_remove'):
        if field in payload:
            value = payload[field]
            if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
                raise ValueError('收藏组必须是 ID 列表')
            changes[field] = list(dict.fromkeys(value))
    return changes


def _merge_memberships(current: Iterable[str], add: Iterable[str], remove: Iterable[str], known: set) -> list:
    result = [identity for identity in current or [] if identity in known]
    for identity in add or []:
        if identity not in known:
            raise ValueError('收藏组已不存在，请重新选择。未保存当前修改。')
        if identity not in result:
            result.append(identity)
    for identity in remove or []:
        if identity not in known:
            raise ValueError('收藏组已不存在，请重新选择。未保存当前修改。')
        result = [value for value in result if value != identity]
    return result


def apply_batch(payload: Mapping[str, Any]) -> dict:
    """Apply one metadata change set to many shared resources atomically."""
    if not isinstance(payload, Mapping):
        raise ValueError('批量维护需要对象')
    resource_ids = _resource_ids(payload.get('resource_ids'))
    changes = _changes(payload)
    expected = payload.get('base_revision', payload.get('revision'))
    if not isinstance(expected, str) or not expected.strip():
        raise ValueError('请先读取当前共享库版本')
    expected = expected.strip()
    if len(expected) >= 2 and expected.startswith('"') and expected.endswith('"'):
        expected = expected[1:-1]

    with prompt_store._PROMPT_FILE_LOCK:
        current = prompt_store._read_prompt_data_cached()
        prompt_store._require_revision({'base_revision': expected}, current)
        groups = items._groups(current)
        known = {str(group.get('id')) for group in groups}
        updated = copy.deepcopy(current)

        located = {}
        missing = []
        for identity in resource_ids:
            try:
                located[identity] = items._find_prompt(updated, identity)
            except KeyError:
                missing.append(identity)
        if missing:
            raise ValueError('部分资料已不存在，请刷新列表后重试：' + ', '.join(missing[:10]))

        results = []
        for identity in resource_ids:
            category, prompt = located[identity]
            metadata = prompt.get('_collection') if isinstance(prompt.get('_collection'), dict) else {}
            memberships = _merge_memberships(metadata.get('groupIds') or [], changes.get('collection_add'),
                                              changes.get('collection_remove'), known)
            details = {}
            if 'notes' in changes:
                details['notes'] = changes['notes']
            if 'nickname' in changes:
                details['nickname'] = changes['nickname']
            items.apply_collection(updated, prompt, items._decision(category, prompt),
                                   memberships, details=details)
            if 'favorite' in changes:
                prompt['favorite'] = changes['favorite']
            results.append({'resource_id': identity, 'status': 'applied',
                            'favorite': bool(prompt.get('favorite')),
                            'notes': str(prompt['_collection'].get('notes') or ''),
                            'nickname': str(prompt['_collection'].get('nickname') or ''),
                            'collection_ids': list(prompt['_collection'].get('groupIds') or [])})

        stamp = datetime.now().isoformat()
        updated['last_modified'] = stamp
        prompt_store._atomic_save_json(
            prompt_store.DATA_FILE, updated, compact=True,
            create_backup=prompt_store._should_create_route_branch_backup(),
            expected_revision=expected)
        prompt_store._cache_prompt_data(updated)
        revision = prompt_store._revision(updated)

    return {
        'success': True,
        'revision': revision,
        'counts': {'requested': len(resource_ids), 'applied': len(results),
                   'failed': 0, 'unchanged': 0},
        'items': results,
        'collections': groups,
        'changes': sorted(changes),
    }
