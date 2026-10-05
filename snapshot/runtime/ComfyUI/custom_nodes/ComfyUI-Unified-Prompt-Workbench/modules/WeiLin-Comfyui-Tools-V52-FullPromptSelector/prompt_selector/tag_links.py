"""Applied, traceable links between legacy Tag records and shared resources.

The audited candidate file stays read-only; this module owns the *applied*
relations a user explicitly creates (or promotes from an audited candidate).
Nothing here merges records, rewrites bodies or moves categories: a link is a
separate, additive record keyed by both stable identities so a Tag may keep
several links and a shared resource may be referenced by several Tags.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Any, Mapping, Optional

from . import item_maintenance as items
from . import prompt_selector as prompt_store
from .tag_library import TagLibrary

LINK_VERSION = 1
LINK_NAME = 'tag_links.json'
RELATIONS = ('manual', 'one_to_one_exact_body', 'one_to_one_normalized_body', 'multiple_records')
_LOCK = threading.RLock()


class LinkError(ValueError):
    """Invalid link request."""


class LinkConflict(LinkError):
    """The link store changed since the caller read it."""

    def __init__(self, expected: Any, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__('链接关系已被其他窗口修改，请重新读取后再保存。')


def link_path() -> str:
    return os.path.join(prompt_store.PROMPT_STORE_DIR, LINK_NAME)


def _empty() -> dict:
    return {'version': LINK_VERSION, 'updated_at': '', 'links': []}


def load_links() -> dict:
    path = link_path()
    if not os.path.exists(path):
        return _empty()
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise LinkError('链接关系文件无法读取：' + str(exc)) from exc
    if not isinstance(payload, dict) or payload.get('version') != LINK_VERSION or not isinstance(payload.get('links'), list):
        raise LinkError('链接关系文件格式不受支持')
    return payload


def _save(payload: Mapping[str, Any]) -> None:
    path = link_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.tag-links-', suffix='.json', dir=directory or None)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass


def _require_revision(expected: Any, current: Mapping[str, Any]) -> None:
    actual = str(current.get('updated_at') or '')
    if expected is None:
        raise LinkError('请先读取当前链接关系版本')
    text = str(expected).strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    if text != actual:
        raise LinkConflict(text, actual)


def _normalize(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LinkError(f'缺少{label}')
    return value.strip().removeprefix('tag:') if label == 'Tag 身份' else value.strip()


def _require_tag(tag_uuid: str) -> str:
    identity = str(tag_uuid or '').strip()
    if identity.startswith('tag:'):
        identity = identity[4:]
    if not identity:
        raise LinkError('缺少 Tag 身份')
    TagLibrary(items.dao.tags_db_path).get(identity)
    return identity


def _require_resource(resource_id: str) -> str:
    identity = str(resource_id or '').strip()
    if not identity:
        raise LinkError('缺少共享资料身份')
    data = prompt_store._read_prompt_data_cached()
    items._find_prompt(data, identity)
    return identity


def _view(payload: Mapping[str, Any]) -> dict:
    return {'version': payload.get('version'), 'revision': str(payload.get('updated_at') or ''),
            'links': [dict(link) for link in payload.get('links') or []]}


def lookup(*, tag_uuid: Optional[str] = None, resource_id: Optional[str] = None) -> dict:
    if (tag_uuid is None) == (resource_id is None):
        raise LinkError('必须且仅指定 tag_uuid 或 resource_id 其中一个身份')
    payload = load_links()
    tag_identity = _normalize(tag_uuid, 'Tag 身份') if tag_uuid is not None else None
    resource_identity = _normalize(resource_id, '共享资料身份') if resource_id is not None else None
    links = [dict(link) for link in payload.get('links') or []
             if (tag_identity is None or link.get('tag_uuid') == tag_identity)
             and (resource_identity is None or link.get('resource_id') == resource_identity)]
    return {'query': {'tag_uuid': tag_identity, 'resource_id': resource_identity},
            'links': links, 'count': len(links), 'revision': str(payload.get('updated_at') or ''),
            'writes_to_sources': False}


def link(*, tag_uuid: Any, resource_id: Any, relation: Any = 'manual',
         source: Any = 'manual', note: Any = '', expected: Any = None) -> dict:
    tag_identity = _require_tag(_normalize(tag_uuid, 'Tag 身份'))
    resource_identity = _require_resource(_normalize(resource_id, '共享资料身份'))
    relation_name = str(relation or 'manual')
    if relation_name not in RELATIONS:
        raise LinkError('未知的关联类型')
    if note is not None and not isinstance(note, str):
        raise LinkError('关联说明必须为文本')
    with _LOCK:
        payload = load_links()
        _require_revision(expected, payload)
        if any(link.get('tag_uuid') == tag_identity and link.get('resource_id') == resource_identity
               for link in payload.get('links') or []):
            raise LinkError('这两条记录已经建立关联。')
        record = {'link_id': str(uuid.uuid4()), 'tag_uuid': tag_identity,
                  'resource_id': resource_identity, 'relation': relation_name,
                  'source': str(source or 'manual')[:32], 'note': note or '',
                  'created_at': datetime.now().isoformat()}
        payload['links'] = [*(payload.get('links') or []), record]
        payload['updated_at'] = record['created_at']
        _save(payload)
        return {'success': True, 'link': record, **_view(payload)}


def unlink(*, link_id: Any = None, tag_uuid: Any = None, resource_id: Any = None, expected: Any = None) -> dict:
    with _LOCK:
        payload = load_links()
        _require_revision(expected, payload)
        links = payload.get('links') or []
        if link_id:
            identity = str(link_id)
            remaining = [link for link in links if link.get('link_id') != identity]
            removed = [link for link in links if link.get('link_id') == identity]
        else:
            tag_identity = _normalize(tag_uuid, 'Tag 身份')
            resource_identity = _normalize(resource_id, '共享资料身份')
            remaining = [link for link in links
                         if not (link.get('tag_uuid') == tag_identity and link.get('resource_id') == resource_identity)]
            removed = [link for link in links
                       if link.get('tag_uuid') == tag_identity and link.get('resource_id') == resource_identity]
        if not removed:
            raise LinkError('没有找到要解除的关联。')
        payload['links'] = remaining
        payload['updated_at'] = datetime.now().isoformat()
        _save(payload)
        return {'success': True, 'removed': removed, **_view(payload)}
