from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from .tag_library import TagLibrary

_MAX_ITEMS = 500000
_FORMAT = 'weilin-tags-v1'
_CONTRACT = 'tag-import-preflight-v1'

_GROUP_FIELDS = frozenset(('p_uuid', 'name', 'color', 'create_time', 'id_index'))
_SUBGROUP_FIELDS = frozenset(('g_uuid', 'name', 'color', 'p_uuid', 'create_time', 'id_index', 'group_id'))
_TAG_FIELDS = frozenset((
    't_uuid', 'resource_id', 'kind', 'text', 'desc', 'color', 'create_time',
    'g_uuid', 'subgroup_id', 'subgroup_name', 'p_uuid', 'group_name',
    'favorite', 'notes', 'collection_ids', 'themes', 'id_index',
))


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _metadata(conn, identity):
    row = conn.execute(
        'SELECT data FROM workbench_tag_meta WHERE tag_uuid=?', (identity,)
    ).fetchone()
    return json.loads(row[0]) if row else {}


def _effective_metadata(data):
    return {
        'favorite': bool(data.get('favorite', False)),
        'notes': data.get('notes', ''),
        'collection_ids': data.get('collection_ids', []),
        'themes': data.get('themes', []),
    }


def _tag_state(conn, identity):
    row = conn.execute(
        'SELECT text,desc,color,g_uuid FROM tag_tags WHERE t_uuid=?', (identity,)
    ).fetchone()
    if row is None:
        return None
    return {
        'text': row['text'], 'desc': row['desc'], 'color': row['color'],
        'g_uuid': row['g_uuid'], 'metadata': _effective_metadata(_metadata(conn, identity)),
    }


def _category_state(conn, entity, identity):
    table, key, fields = {
        'group': ('tag_groups', 'p_uuid', ('name', 'color')),
        'subgroup': ('tag_subgroups', 'g_uuid', ('name', 'color', 'p_uuid')),
    }[entity]
    row = conn.execute(
        f'SELECT {",".join(fields)} FROM {table} WHERE {key}=?', (identity,)
    ).fetchone()
    return tuple(row[field] for field in fields) if row else None


def _tag_changed(before, after):
    if before is None or after is None:
        return []
    fields = [field for field in ('text', 'desc', 'color', 'g_uuid')
              if before[field] != after[field]]
    fields.extend(field for field in ('favorite', 'notes', 'collection_ids', 'themes')
                  if before['metadata'][field] != after['metadata'][field])
    return fields


def _category_changed(before, after, entity):
    if before is None or after is None:
        return []
    names = ('name', 'color') if entity == 'group' else ('name', 'color', 'p_uuid')
    return [name for name, old, new in zip(names, before, after) if old != new]


def _validate_rows(rows, key, message):
    if not isinstance(rows, list):
        raise ValueError(message)
    identities = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(message)
        identity = row.get(key)
        if not isinstance(identity, str) or not identity:
            raise ValueError('Tag 文件的稳定 ID 缺失或重复')
        identities.append(identity)
    if len(set(identities)) != len(identities):
        raise ValueError('Tag 文件的稳定 ID 缺失或重复')
    return identities


def _validate_bundle(bundle, known):
    if not isinstance(bundle, dict) or bundle.get('format') != _FORMAT:
        raise ValueError('请选择共享 Tag 管理导出的 JSON 文件')
    groups = _validate_rows(bundle.get('groups'), 'p_uuid', 'Tag 文件缺少分类或词条列表')
    subgroups = _validate_rows(bundle.get('subgroups'), 'g_uuid', 'Tag 文件缺少分类或词条列表')
    items = bundle.get('items')
    if not isinstance(items, list) or len(items) > _MAX_ITEMS:
        raise ValueError('Tag 文件格式或数量无效')
    tag_ids = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Tag 文件格式或数量无效')
        identity = item.get('t_uuid')
        if not isinstance(identity, str) or not identity:
            raise ValueError('Tag 文件的稳定 ID 缺失或重复')
        tag_ids.append(identity)
        if 'themes' in item:
            TagLibrary.validate_themes(item['themes'])
        memberships = item.get('collection_ids', [])
        if not isinstance(memberships, list) or any(not isinstance(value, str) for value in memberships):
            raise ValueError('收藏组必须是 ID 列表')
        if any(value not in known for value in memberships):
            raise ValueError('收藏组已不存在，请重新选择。未保存当前修改。')
    if len(set(tag_ids)) != len(tag_ids):
        raise ValueError('Tag 文件的稳定 ID 缺失或重复')
    return groups, subgroups, tag_ids


def _ignored(rows, allowed):
    return [sorted(set(row) - allowed) for row in rows]


def _counts(states, changes, ignored):
    new = sum(state is None for state in states)
    updated = sum(state is not None and bool(fields)
                  for state, fields in zip(states, changes))
    duplicate = sum(state is not None and not fields
                    for state, fields in zip(states, changes))
    unsupported = sum(bool(fields) for fields in ignored)
    return {
        'new': new,
        'updated': updated,
        'suspected_duplicate': duplicate,
        'unsupported': unsupported,
        'version_conflicts': 0,
        'total_records': len(states),
        'will_write': new + updated,
        'will_skip': duplicate,
    }


def _category_actions(rows, ids, before, changes, entity, ignored):
    actions = []
    for index, (identity, old, fields, extra) in enumerate(zip(ids, before, changes, ignored)):
        disposition = 'new' if old is None else 'updated' if fields else 'suspected_duplicate'
        actions.append({
            'stable_id': identity,
            'source_index': index,
            'source_coordinate': f'{entity}s[{index}]',
            'disposition': disposition,
            'changed_fields': fields,
            'ignored_field_names': extra,
        })
    return actions


def preview_tag_import(path, bundle, overwrite, collection_revision, known_collections):
    known = tuple(known_collections) if isinstance(known_collections, (list, tuple)) else None
    if known is None or any(not isinstance(value, str) for value in known) or len(set(known)) != len(known):
        raise ValueError('收藏组列表无效')
    known_set = set(known)
    group_ids, subgroup_ids, tag_ids = _validate_bundle(bundle, known_set)
    canonical_bundle_hash = _digest(bundle)
    source = memory = None
    try:
        source_path = Path(path).resolve()
        uri = 'file:' + quote(str(source_path), safe='/') + '?mode=ro'
        source = sqlite3.connect(uri, uri=True)
        source.row_factory = sqlite3.Row
        source.execute('BEGIN')
        memory = sqlite3.connect(':memory:')
        memory.row_factory = sqlite3.Row
        source.backup(memory)
        base_revision = TagLibrary.revision_of(memory)

        groups = bundle['groups']
        subgroups = bundle['subgroups']
        items = bundle['items']
        before_groups = [_category_state(memory, 'group', identity) for identity in group_ids]
        before_subgroups = [_category_state(memory, 'subgroup', identity) for identity in subgroup_ids]
        before_tags = [_tag_state(memory, identity) for identity in tag_ids]

        # Show policy conflicts before the user enables overwrite. Simulation
        # may inspect the overwrite outcome, but that plan cannot be committed.
        group_conflicts = [i for i, (old, row) in enumerate(zip(before_groups, groups))
                           if old is not None and old != tuple(row.get(k, '') for k in ('name', 'color'))]
        subgroup_conflicts = [i for i, (old, row) in enumerate(zip(before_subgroups, subgroups))
                              if old is not None and old != tuple(row.get(k, '') for k in ('name', 'color', 'p_uuid'))]
        tag_conflicts = [i for i, (old, row) in enumerate(zip(before_tags, items))
                        if old is not None and any(old[k] != row.get(k, '') for k in ('text', 'desc', 'color', 'g_uuid'))]
        blocked = overwrite is not True and bool(group_conflicts or subgroup_conflicts or tag_conflicts)
        executor = object.__new__(TagLibrary)
        executor.import_bundle(memory, bundle, overwrite is True or blocked)

        after_groups = [_category_state(memory, 'group', identity) for identity in group_ids]
        after_subgroups = [_category_state(memory, 'subgroup', identity) for identity in subgroup_ids]
        after_tags = [_tag_state(memory, identity) for identity in tag_ids]
        group_changes = [_category_changed(a, b, 'group') for a, b in zip(before_groups, after_groups)]
        subgroup_changes = [_category_changed(a, b, 'subgroup') for a, b in zip(before_subgroups, after_subgroups)]
        tag_changes = [_tag_changed(a, b) for a, b in zip(before_tags, after_tags)]
        group_ignored = _ignored(groups, _GROUP_FIELDS)
        subgroup_ignored = _ignored(subgroups, _SUBGROUP_FIELDS)
        tag_ignored = _ignored(items, _TAG_FIELDS)

        plans = []
        for index, (identity, old, fields, extra) in enumerate(zip(tag_ids, before_tags, tag_changes, tag_ignored)):
            plans.append({
                'stable_id': identity,
                'source_index': index,
                'source_coordinate': f'items[{index}]',
                'disposition': 'new' if old is None else 'updated' if fields else 'suspected_duplicate',
                'changed_fields': fields,
                'ignored_field_names': extra,
            })
        token_input = {
            'contract': _CONTRACT,
            'bundle': bundle,
            'overwrite': overwrite is True,
            'base_revision': base_revision,
            'collection_revision': collection_revision,
            'known_collections': list(known),
        }
        return {
            'contract': _CONTRACT,
            'base_revision': base_revision,
            'collection_revision': collection_revision,
            'canonical_bundle_hash': canonical_bundle_hash,
            'overwrite': overwrite is True,
            'preflight_token': _digest(token_input),
            'committable': not blocked,
            'blocked_reason': '同一 ID 的内容有变化，请核对后选择允许覆盖，再重新预览。' if blocked else None,
            'counts': {**_counts(before_tags, tag_changes, tag_ignored), 'version_conflicts': len(tag_conflicts) if blocked else 0},
            'items': plans,
            'category_counts': {
                'groups': {**_counts(before_groups, group_changes, group_ignored), 'version_conflicts': len(group_conflicts) if blocked else 0, 'actions': _category_actions(groups, group_ids, before_groups, group_changes, 'group', group_ignored)},
                'subgroups': {**_counts(before_subgroups, subgroup_changes, subgroup_ignored), 'version_conflicts': len(subgroup_conflicts) if blocked else 0, 'actions': _category_actions(subgroups, subgroup_ids, before_subgroups, subgroup_changes, 'subgroup', subgroup_ignored)},
            },
        }
    finally:
        if memory is not None:
            memory.close()
        if source is not None:
            source.close()
