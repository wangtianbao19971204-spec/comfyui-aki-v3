"""Persist shared-reference repairs independently from the model cache."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import threading

from ..utils.settings_paths import get_settings_dir

_QUEUE_LOCK = threading.RLock()
_UNSAVED = []


def _queue_path() -> str:
    return os.path.join(get_settings_dir(), 'shared_reference_repairs.json')


def _read_queue() -> list:
    try:
        with open(_queue_path(), encoding='utf-8') as stream:
            rows = json.load(stream)
    except FileNotFoundError:
        return []
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not all(key in row for key in ('id', 'model_type', 'old_path', 'new_path')) for row in rows):
        raise ValueError('Invalid shared reference repair queue; restore its backup before retrying')
    return rows


def _write_queue(rows: list) -> None:
    path = _queue_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.reference-repairs-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(rows, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _repair(model_type: str, pairs: list) -> dict:
    from server import PromptServer
    with _QUEUE_LOCK:
        incoming = []
        for old, new in pairs:
            identity = json.dumps([model_type, str(old), str(new) if new is not None else None])
            incoming.append({'id': hashlib.sha256(identity.encode()).hexdigest(), 'model_type': model_type,
                             'old_path': str(old), 'new_path': str(new) if new is not None else None})
        for row in incoming:
            if row['id'] not in {item['id'] for item in _UNSAVED}:
                _UNSAVED.append(row)
        try:
            rows = _read_queue()
            known = {row['id'] for row in rows}
            additions = [row for row in _UNSAVED if row['id'] not in known]
            if additions:
                rows.extend(additions)
                _write_queue(rows)
            _UNSAVED.clear()
        except Exception as error:
            return {'status': 'recovery_not_saved', 'error': str(error), 'operations': list(_UNSAVED),
                    'recovery_action': 'Model files changed. Keep this page open, copy the old/new paths, restore write access to the LoRA Manager settings directory, then Refresh to retry. Do not repeat the file operation.'}
        pending = [row for row in rows if row['model_type'] == model_type]
        while pending:
            group, paths = [], set()
            deleting = pending[0]['new_path'] is None
            for row in pending:
                involved = {row['old_path'], row['new_path']} - {None}
                if (row['new_path'] is None) != deleting or involved & paths:
                    break
                group.append(row)
                paths.update(involved)
            try:
                batch_name = 'weilin_prune_references' if deleting else 'weilin_relocate_references'
                batch = getattr(PromptServer.instance, batch_name, None)
                if batch is not None:
                    argument = [row['old_path'] for row in group] if deleting else [(row['old_path'], row['new_path']) for row in group]
                    outcome = batch(model_type, argument)
                    if isinstance(outcome, dict) and outcome.get('success') is False:
                        raise RuntimeError(outcome.get('error') or 'Shared reference synchronization failed')
                else:
                    callback = getattr(PromptServer.instance, 'weilin_relocate_reference', None)
                    if callback is None:
                        raise RuntimeError('Shared collection owner is unavailable')
                    for row in group:
                        outcome = callback(model_type, row['old_path'], row['new_path'])
                        if isinstance(outcome, dict) and outcome.get('success') is False:
                            raise RuntimeError(outcome.get('error') or 'Shared reference synchronization failed')
                completed = {row['id'] for row in group}
                remaining = [item for item in rows if item['id'] not in completed]
                _write_queue(remaining)
                rows = remaining
                pending = [row for row in rows if row['model_type'] == model_type]
            except Exception as error:
                return {'status': 'pending', 'error': str(error), 'operations': pending,
                        'recovery_action': 'Model files changed; shared references are pending. Restore the shared collection owner and use Refresh to retry. Do not repeat the file operation.'}
        return {'status': 'complete', 'operations': []}


async def relocate_reference(model_type: str, old_path: str, new_path: str | None = None) -> dict:
    return await asyncio.to_thread(_repair, model_type, [(old_path, new_path)])


async def prune_references(model_type: str, paths) -> dict:
    return await asyncio.to_thread(_repair, model_type, [(path, None) for path in (paths or ())])


async def relocate_references(model_type: str, pairs) -> dict:
    return await asyncio.to_thread(_repair, model_type, list(pairs or ()))


async def retry_pending_references(model_type: str) -> dict:
    """Retry even when a rescan finds no filesystem differences."""
    return await asyncio.to_thread(_repair, model_type, [])
