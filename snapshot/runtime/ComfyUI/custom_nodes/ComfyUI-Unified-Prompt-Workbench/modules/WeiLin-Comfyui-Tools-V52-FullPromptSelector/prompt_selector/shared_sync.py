"""同源正文同步：Tag 库与共享资料库对同一概念的正文保持一致。

两个库各自保存了一份所长法典内容（tag 库 289,631 行 / 资源库 101,294 条，其中 39,417 个概念
两边都有）。配对按"正文 token 集合"判定，只用无歧义的 1:1 配对；任何一侧改了正文，就把新正文
镜像到另一侧，镜像的每一步都写进 `shared_sync_log.json`，可审计、可回滚。

配对表 `shared_pairs.json` 是派生数据（`build_pairs()` 重新生成），只保存
`资源库条目 id -> Tag 行 uuid`；表里没有的条目不做任何同步，因此配对表过期只会"暂时不镜像"，
不会写错东西。

`UW_DISABLE_SHARED_SYNC=1` 可整体关闭镜像。
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

PAIR_NAME = 'shared_pairs.json'
LOG_NAME = 'shared_sync_log.json'
PAIR_VERSION = 1
LOG_LIMIT = 400
CJK = re.compile(r'[\u3400-\u9fff]')
WEIGHT = re.compile(r'^-?\d+(?:\.\d+)?::|::')
BIG = re.compile(r'[\[\]{}【】]')
LABEL = re.compile(r'^\s*(?:翻译|原\s*tag|备注|注意|提示|说明|注|ps)\s*[:：]\s*', re.IGNORECASE)

_PAIRS = {'loaded': False, 'map': {}, 'reverse': {}, 'meta': {}}


def disabled() -> bool:
    return os.environ.get('UW_DISABLE_SHARED_SYNC') == '1'


def _store_dir() -> Path:
    from . import prompt_selector as store
    return Path(store.PROMPT_STORE_DIR)


def pairs_path() -> Path:
    return _store_dir() / PAIR_NAME


def log_path() -> Path:
    return _store_dir() / LOG_NAME


def concept_key(text) -> tuple:
    """正文概念键：忽略权重、括号、大小写、全半角、逗号空格与中文字段前缀。"""
    value = unicodedata.normalize('NFKC', str(text or ''))
    value = LABEL.sub('', value)
    value = re.sub(r'-?\d+(?:\.\d+)?::(.*?)::', r'\1', value)
    value = BIG.sub('', value)
    value = value.replace('\\', '').replace('_', ' ')
    tokens = []
    for part in re.split(r'[,，、]', value):
        token = re.sub(r'\s+', ' ', part).strip(' ,，、:：').casefold()
        if not token:
            continue
        token = re.sub(r'\s*:\s*', ':', token)
        if CJK.search(token) and ':' in token:
            tail = token.split(':')[-1].strip()
            token = tail or token
        tokens.append(token)
    return tuple(sorted(tokens))


def load_pairs(force: bool = False) -> dict:
    if _PAIRS['loaded'] and not force:
        return _PAIRS
    _PAIRS.update(loaded=True, map={}, reverse={}, meta={})
    try:
        payload = json.loads(pairs_path().read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001 - no pair table means "nothing to mirror"
        return _PAIRS
    if payload.get('version') != PAIR_VERSION or not isinstance(payload.get('pairs'), dict):
        return _PAIRS
    mapping = {str(key): str(value) for key, value in payload['pairs'].items()}
    _PAIRS['map'] = mapping
    _PAIRS['reverse'] = {value: key for key, value in mapping.items()}
    _PAIRS['meta'] = {key: value for key, value in payload.items() if key != 'pairs'}
    return _PAIRS


def reset_cache() -> None:
    _PAIRS.update(loaded=False, map={}, reverse={}, meta={})


def build_pairs(tag_rows, library_rows) -> dict:
    """Pair every concept only one Tag row and one library entry hold."""
    tag_index, library_index = {}, {}
    for uuid_value, text in tag_rows:
        tag_index.setdefault(concept_key(text), []).append((uuid_value, text))
    for prompt_id, text in library_rows:
        library_index.setdefault(concept_key(text), []).append((prompt_id, text))
    pairs, ambiguous = {}, 0
    for key, tag_side in tag_index.items():
        library_side = library_index.get(key)
        if not library_side:
            continue
        if len(tag_side) != 1 or len(library_side) != 1:
            ambiguous += 1
            continue
        pairs[library_side[0][0]] = tag_side[0][0]
    return {'pairs': pairs, 'tag_concepts': len(tag_index), 'library_concepts': len(library_index),
            'ambiguous_concepts': ambiguous}


def _append_log(entry: dict) -> None:
    try:
        path = log_path()
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
            entries = document.get('entries') if isinstance(document, dict) else None
        except Exception:  # noqa: BLE001
            entries = None
        entries = entries if isinstance(entries, list) else []
        entries.append(entry)
        path.write_text(json.dumps({'version': PAIR_VERSION, 'entries': entries[-LOG_LIMIT:]},
                                   ensure_ascii=False, indent=1), encoding='utf-8')
    except Exception:  # noqa: BLE001 - logging must never break a write
        pass


def _mirror_result(action, source_id, target_id, old_text, new_text, ok, error=None) -> dict:
    return {'action': action, 'source': source_id, 'target': target_id, 'ok': ok,
            'old_text': (old_text or '')[:200], 'new_text': (new_text or '')[:200], 'error': error,
            'at': datetime.now().isoformat()}


def mirror_from_tag(tag_uuid, old_text, new_text) -> dict | None:
    """A Tag body edit happened: give the paired library entry the same body."""
    if disabled() or not new_text or new_text == old_text:
        return None
    prompt_id = load_pairs()['reverse'].get(str(tag_uuid))
    if not prompt_id:
        return None
    from . import prompt_selector as store
    try:
        with store._PROMPT_FILE_LOCK:
            data = store._read_prompt_data_cached()
            located = None
            for index, category in enumerate(data.get('categories', []) or []):
                for position, prompt in enumerate(category.get('prompts', []) or []):
                    if str(prompt.get('id')) == prompt_id:
                        located = (index, position, category, prompt)
                        break
                if located:
                    break
            if located is None:
                return None
            index, position, category, prompt = located
            if str(prompt.get('prompt') or '') == str(new_text):
                return None
            now = datetime.now().isoformat()
            prompts = list(category.get('prompts', []) or [])
            prompts[position] = {**prompt, 'prompt': new_text, 'updated_at': now}
            categories = list(data.get('categories', []) or [])
            categories[index] = {**category, 'prompts': prompts, 'updated_at': now}
            updated = {**data, 'categories': categories, 'last_modified': now}
            store._atomic_save_json(store.DATA_FILE, updated, create_backup=True, compact=True,
                                    expected_revision=store._revision(data))
            store._cache_prompt_data(updated, [prompt_id])
        result = _mirror_result('tag_to_library', tag_uuid, prompt_id, old_text, new_text, True)
    except Exception as error:  # noqa: BLE001 - the primary write already succeeded
        result = _mirror_result('tag_to_library', tag_uuid, prompt_id, old_text, new_text, False, str(error))
    _append_log(result)
    return result


def mirror_from_library(prompt_id, old_text, new_text) -> dict | None:
    """A library body edit happened: give the paired Tag row the same body."""
    if disabled() or not new_text or new_text == old_text:
        return None
    tag_uuid = load_pairs()['map'].get(str(prompt_id))
    if not tag_uuid:
        return None
    try:
        from ..app.server.dao import dao
        from . import prompt_selector as store
        from .tag_library import TagLibrary
        library = TagLibrary(dao.tags_db_path)
        current = library.get('tag:' + tag_uuid)['item']
        if str(current.get('text') or '') == str(new_text):
            return None
        library.update({'entity': 'tag', 'operation': 'edit', 't_uuid': tag_uuid, 'text': new_text},
                       expected=library.revision())
        result = _mirror_result('library_to_tag', prompt_id, tag_uuid, old_text, new_text, True)
    except Exception as error:  # noqa: BLE001 - the primary write already succeeded
        result = _mirror_result('library_to_tag', prompt_id, tag_uuid, old_text, new_text, False, str(error))
    _append_log(result)
    return result
