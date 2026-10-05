"""Numbered, recoverable merge tasks for the shared prompt library.

「整理重复」already compared every selected source against the kept record and
saved the result in one atomic write.  What it did not do was answer the two
questions a maintenance action has to answer: *what happened to each source*,
and *how do I get that list back later*.  This module adds both, with the same
task shape as 批量归类 (``route_jobs``) and Tag 批量操作 (``tag_batch_jobs``):

* the client supplies a task number (``operation_id``);
* a status snapshot reports the outcome without inventing one;
* the per-item list and the unmerged ids can be exported;
* the result stays reachable by number, including after a restart, because a
  committed task writes its own record into ``_merge_history``.

The strict ``merge_preview`` gate and the single atomic save are unchanged; a
source that changed between the comparison and the confirmation is reported as
skipped instead of being merged silently.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
from collections import OrderedDict
from datetime import datetime

from aiohttp import web
from server import PromptServer

from . import prompt_selector as prompt_store
from .prompt_merge import (_library_index, apply_merge, merge_comparison, merge_plan,
                           merge_preview, merge_review_token, merge_task_record,
                           review_fingerprint)
from .semantic_projection import read_projection


CONTRACT = 'weilin-merge-task-v1'
REVIEW_CAPACITY = 32
TERMINAL_CAPACITY = 64
EXPORT_KINDS = ('items', 'requested_ids', 'unmerged_ids', 'failed_ids', 'skipped_ids')


class MergeTaskError(ValueError):
    """A refused or uncommitted merge task that still has a result list."""

    def __init__(self, message, report=None, *, conflict=False):
        super().__init__(message)
        self.report = report
        self.conflict = conflict


class UnknownTask(LookupError):
    pass


def _now():
    return datetime.now().isoformat()


def _clean_task_id(value):
    text = value.strip() if isinstance(value, str) else ''
    if not text or len(text) > 200:
        raise MergeTaskError('任务编号无效，请重新打开合并对照。')
    return text


def _counts(rows):
    counted = {'requested': len(rows), 'merged': 0, 'skipped': 0, 'kept': 0, 'failed': 0}
    for row in rows:
        counted[row['status']] = counted.get(row['status'], 0) + 1
    return counted


class MergeTasks:
    """Owner of reviewed merge comparisons and their numbered results."""

    def __init__(self, store=prompt_store, review_capacity=REVIEW_CAPACITY,
                 terminal_capacity=TERMINAL_CAPACITY):
        self.store = store
        self.review_capacity = max(1, review_capacity)
        self.terminal_capacity = max(1, terminal_capacity)
        self.mu = threading.RLock()
        self.reviews = OrderedDict()
        self.tasks = OrderedDict()

    # ---- shared plumbing ------------------------------------------------
    def _projection(self):
        return read_projection(os.path.join(self.store.PROMPT_STORE_DIR, 'semantic_projection.json'))

    def _review(self, payload):
        task_id = _clean_task_id(payload.get('operation_id'))
        with self.mu:
            reviewed = self.reviews.get(task_id)
        if reviewed is None:
            raise MergeTaskError('请先对照当前来源及元数据，再确认合并。')
        if (list(reviewed['prompt_ids']) != list(payload.get('prompt_ids') or [])
                or reviewed['canonical_id'] != payload.get('canonical_id')):
            raise MergeTaskError('对照范围已变化，请关闭后重新对照最新资料。')
        return task_id, reviewed

    def _remember_review(self, task_id, reviewed):
        with self.mu:
            self.reviews[task_id] = reviewed
            while len(self.reviews) > self.review_capacity:
                self.reviews.popitem(last=False)

    def _remember_task(self, task_id, record):
        with self.mu:
            self.tasks[task_id] = record
            while len(self.tasks) > self.terminal_capacity:
                self.tasks.popitem(last=False)

    def _snapshot(self, task_id):
        with self.mu:
            record = self.tasks.get(task_id)
        if record is not None:
            return copy.deepcopy(record)
        with self.store._PROMPT_FILE_LOCK:
            data = self.store._read_prompt_data_cached()
        durable = merge_task_record(data, task_id)
        if durable is None:
            raise UnknownTask(task_id)
        return self._durable_snapshot(task_id, durable)

    @staticmethod
    def _durable_snapshot(task_id, durable):
        rows = copy.deepcopy(durable.get('items') or [])
        return {'contract': CONTRACT, 'operation_id': task_id, 'status': 'committed',
                'atomic': True, 'canonical_id': durable.get('canonical_id'),
                'source_ids': list(durable.get('source_ids') or ()),
                'counts': copy.deepcopy(durable.get('counts') or _counts(rows)),
                'items': rows, 'failure': None,
                'before_revision': durable.get('before_revision'),
                'after_revision': durable.get('after_revision') or durable.get('at'),
                'started_at': durable.get('at'), 'finished_at': durable.get('at'),
                'persistence': 'durable_merge_history'}

    # ---- operations -----------------------------------------------------
    def preview(self, payload):
        """Read-only comparison plus the reviewed fingerprints bound to a number."""
        if not isinstance(payload, dict):
            raise MergeTaskError('合并对照需要对象')
        prompt_ids = payload.get('prompt_ids')
        canonical_id = payload.get('canonical_id')
        task_id = _clean_task_id(payload.get('operation_id'))
        with self.store._PROMPT_FILE_LOCK:
            data = self.store._read_prompt_data_cached()
            self.store._require_revision(payload, data)
            projection = self._projection()
            plan = merge_plan(data, projection, prompt_ids, canonical_id)
            comparison = merge_comparison(data, projection, prompt_ids, canonical_id)
            index = _library_index(data)
            reviewed = {prompt_id: review_fingerprint(projection, *index[prompt_id])
                        for prompt_id in prompt_ids if prompt_id in index}
            token = merge_review_token(canonical_id, prompt_ids, reviewed)
            revision = self.store._revision(data)
        self._remember_review(task_id, {'prompt_ids': list(prompt_ids), 'canonical_id': canonical_id,
                                        'token': token, 'revision': revision,
                                        'fingerprints': reviewed, 'at': _now()})
        return {'contract': CONTRACT, 'operation_id': task_id, 'status': 'reviewed',
                'atomic': True, 'revision': revision, 'review_token': token,
                'canonical_id': canonical_id, 'prompt_ids': list(prompt_ids),
                'differing_fields': list(comparison['differing_fields']),
                'sources': copy.deepcopy(comparison['sources']),
                'missing': list(comparison['missing']),
                'items': plan['rows'], 'counts': _counts(plan['rows']),
                'mergeable_ids': list(plan['mergeable_ids']),
                'persistence': 'reviewed_in_memory_then_durable_history'}

    def commit(self, payload):
        """Fold the reviewed selection into the kept record in one atomic save."""
        if not isinstance(payload, dict):
            raise MergeTaskError('合并提交需要对象')
        if payload.get('metadata_reviewed') is not True:
            raise MergeTaskError('请先对照当前来源及元数据，再确认合并。')
        task_id, reviewed = self._review(payload)
        if payload.get('review_token') != reviewed['token']:
            raise MergeTaskError('对照内容已变化，请关闭后重新对照最新资料。')
        expected = payload.get('base_revision') or reviewed['revision']
        started = _now()
        with self.store._PROMPT_FILE_LOCK:
            data = self.store._read_prompt_data_cached()
            try:
                self.store._require_revision({'base_revision': expected}, data)
            except prompt_store.RevisionConflict as error:
                plan = self._failed_plan(payload, '版本已变化：' + str(error))
                self._record(task_id, plan, 'not_committed', started,
                             failure={'code': 'revision_conflict', 'message': str(error),
                                      'current_revision': error.actual})
                raise MergeTaskError(str(error), self._snapshot(task_id), conflict=True) from error
            projection = self._projection()
            try:
                plan = merge_plan(data, projection, payload.get('prompt_ids'),
                                  payload.get('canonical_id'), reviewed=reviewed['fingerprints'])
            except ValueError as error:
                failed = self._failed_plan(payload, str(error))
                self._record(task_id, failed, 'not_committed', started,
                             failure={'code': 'selection_not_mergeable', 'message': str(error)})
                raise MergeTaskError(str(error), self._snapshot(task_id)) from error
            mergeable = plan['mergeable_ids']
            order = [pid for pid in payload['prompt_ids'] if pid in set(mergeable)]
            if not order:
                self._record(task_id, plan, 'not_committed', started,
                             failure={'code': 'no_mergeable_items',
                                      'message': '所选资料都没有并入保留资料；结果清单已保留，可导出后重新核对。'})
                raise MergeTaskError('所选资料都没有并入保留资料；结果清单已保留。',
                                     self._snapshot(task_id))
            subset = [plan['canonical_id'], *order]
            strict = merge_preview(data, projection, subset, plan['canonical_id'])
            try:
                merged, _ = apply_merge(data, projection, {
                    'prompt_ids': subset, 'canonical_id': plan['canonical_id'],
                    'metadata_reviewed': True, 'review_token': strict['review_token']}, _now())
                rows = copy.deepcopy(plan['rows'])
                counts = _counts(rows)
                self._attach_record(merged, task_id, rows, counts, expected, started,
                                    list(payload['prompt_ids']))
                self.store._atomic_save_json(
                    self.store.DATA_FILE, merged, create_backup=True, expected_revision=expected)
                self.store._cache_prompt_data(merged)
                revision = self.store._revision(merged)
            except prompt_store.RevisionConflict as error:
                failed = self._failed_plan(payload, '版本已变化：' + str(error), plan=plan)
                self._record(task_id, failed, 'not_committed', started,
                             failure={'code': 'revision_conflict', 'message': str(error),
                                      'current_revision': error.actual})
                raise MergeTaskError(str(error), self._snapshot(task_id), conflict=True) from error
            except Exception as error:  # noqa: BLE001 - the task owner reports the outcome
                failed = self._failed_plan(payload, '合并未完成：' + str(error), plan=plan)
                self._record(task_id, failed, 'unknown', started,
                             failure={'code': 'operation_failed', 'message': str(error)})
                raise MergeTaskError(str(error), self._snapshot(task_id)) from error
        self._remember_task(task_id, {'contract': CONTRACT, 'operation_id': task_id,
            'status': 'committed', 'atomic': True, 'canonical_id': plan['canonical_id'],
            'source_ids': list(payload['prompt_ids']), 'counts': counts, 'items': rows,
            'failure': None, 'before_revision': expected, 'after_revision': revision,
            'started_at': started, 'finished_at': _now(), 'revision': revision,
            'persistence': 'memory_bounded_terminal_registry+durable_merge_history'})
        return self._snapshot(task_id)

    def status(self, task_id):
        return self._snapshot(task_id)

    def export(self, task_id, kind='items'):
        if kind not in EXPORT_KINDS:
            raise MergeTaskError('不支持的导出类型：' + str(kind))
        snapshot = self._snapshot(task_id)
        rows = copy.deepcopy(snapshot.get('items') or [])
        requested = list(snapshot.get('source_ids') or [row['resource_id'] for row in rows])
        if kind == 'items':
            selected = rows
        elif kind == 'requested_ids':
            selected = []
        elif kind == 'failed_ids':
            selected = [row for row in rows if row['status'] == 'failed']
        elif kind == 'skipped_ids':
            selected = [row for row in rows if row['status'] == 'skipped']
        else:
            selected = [row for row in rows if row['status'] in ('failed', 'skipped')]
        return {'contract': CONTRACT, 'operation_id': task_id, 'status': snapshot.get('status'),
                'export_kind': kind, 'counts': copy.deepcopy(snapshot.get('counts')),
                'canonical_id': snapshot.get('canonical_id'),
                'items': selected,
                'resource_ids': [row['resource_id'] for row in selected],
                'requested_ids': requested,
                'failure': copy.deepcopy(snapshot.get('failure')),
                'persistence': snapshot.get('persistence')}

    # ---- row bookkeeping -------------------------------------------------
    @staticmethod
    def _failed_plan(payload, reason, plan=None):
        """Every selected source keeps the outcome that actually happened."""
        rows = []
        for row in (plan or {}).get('rows', []):
            if row['status'] == 'kept':
                rows.append(dict(row))
            else:
                rows.append(dict(row, status='failed', reason=reason))
        if not rows:
            canonical_id = payload.get('canonical_id')
            for prompt_id in payload.get('prompt_ids') or []:
                rows.append({'resource_id': prompt_id, 'target_id': canonical_id,
                             'status': 'kept' if prompt_id == canonical_id else 'failed',
                             'reason': '' if prompt_id == canonical_id else reason,
                             'category_id': '', 'category_name': '', 'alias': prompt_id})
        return {'canonical_id': payload.get('canonical_id'), 'rows': rows,
                'mergeable_ids': []}

    def _record(self, task_id, plan, status, started, failure=None):
        rows = copy.deepcopy(plan['rows'])
        self._remember_task(task_id, {'contract': CONTRACT, 'operation_id': task_id, 'status': status,
            'atomic': True, 'canonical_id': plan.get('canonical_id'),
            'source_ids': [row['resource_id'] for row in rows],
            'counts': _counts(rows), 'items': rows, 'failure': copy.deepcopy(failure),
            'before_revision': None, 'after_revision': None, 'started_at': started,
            'finished_at': _now(), 'revision': None, 'persistence': 'memory_bounded_terminal_registry'})

    @staticmethod
    def _attach_record(merged, task_id, rows, counts, before_revision, started, source_ids):
        history = merged.get('_merge_history') or []
        if not history:
            return
        history[-1].update({'task_id': task_id, 'items': copy.deepcopy(rows),
                            'counts': copy.deepcopy(counts), 'before_revision': before_revision,
                            'started_at': started, 'source_ids': list(source_ids)})


_MERGE_TASKS = None
_MERGE_TASKS_LOCK = threading.Lock()


def merge_tasks():
    global _MERGE_TASKS
    if _MERGE_TASKS is None:
        with _MERGE_TASKS_LOCK:
            if _MERGE_TASKS is None:
                _MERGE_TASKS = MergeTasks()
    return _MERGE_TASKS


def _json(payload, status=200, revision=None):
    response = web.json_response(payload, status=status)
    if revision is not None:
        prompt_store._with_etag(response, revision)
    return response


def _error_response(error, status):
    body = {'error': str(error)}
    if getattr(error, 'report', None) is not None:
        body.update(error.report)
    if getattr(error, 'conflict', False):
        body['conflict'] = True
    return _json(body, status=status)


async def _payload(request):
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


@PromptServer.instance.routes.post('/prompt_selector/prompts/merge_jobs/preview')
async def merge_job_preview(request):
    payload = await _payload(request)
    if payload is None:
        return _json({'error': 'Invalid JSON'}, status=400)
    payload = dict(payload)
    payload['base_revision'] = prompt_store._request_revision(request, payload)
    try:
        async with prompt_store._PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(merge_tasks().preview, payload)
        return _json(result, revision=result['revision'])
    except prompt_store.RevisionConflict as error:
        return _json({'error': str(error), 'conflict': True, 'current_revision': error.actual},
                     status=409, revision=error.actual)
    except MergeTaskError as error:
        return _error_response(error, 400)
    except ValueError as error:
        return _json({'error': str(error)}, status=400)
    except Exception as error:  # noqa: BLE001 - the route reports instead of hiding
        prompt_store.logger.error('合并对照失败: %s', error)
        return _json({'error': str(error)}, status=500)


@PromptServer.instance.routes.post('/prompt_selector/prompts/merge_jobs/commit')
async def merge_job_commit(request):
    payload = await _payload(request)
    if payload is None:
        return _json({'error': 'Invalid JSON'}, status=400)
    payload = dict(payload)
    payload['base_revision'] = prompt_store._request_revision(request, payload)
    try:
        async with prompt_store._PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(merge_tasks().commit, payload)
        return _json(result, revision=result.get('revision') or result.get('after_revision'))
    except MergeTaskError as error:
        return _error_response(error, 409 if error.conflict else 400)
    except prompt_store.RevisionConflict as error:
        return _json({'error': str(error), 'conflict': True, 'current_revision': error.actual},
                     status=409, revision=error.actual)
    except ValueError as error:
        return _json({'error': str(error)}, status=400)
    except Exception as error:  # noqa: BLE001
        prompt_store.logger.error('合并任务失败: %s', error)
        return _json({'error': str(error)}, status=500)


@PromptServer.instance.routes.get('/prompt_selector/prompts/merge_jobs/{operation_id}')
async def merge_job_status(request):
    operation_id = request.match_info.get('operation_id', '')
    try:
        result = await asyncio.to_thread(merge_tasks().status, operation_id)
        return _json(result)
    except UnknownTask:
        return _json({'error': '合并任务不存在；服务重启后请用任务编号重新核对结果。'}, status=404)
    except ValueError as error:
        return _json({'error': str(error)}, status=400)
    except Exception as error:  # noqa: BLE001
        prompt_store.logger.error('读取合并结果失败: %s', error)
        return _json({'error': str(error)}, status=500)


@PromptServer.instance.routes.get('/prompt_selector/prompts/merge_jobs/{operation_id}/export')
async def merge_job_export(request):
    operation_id = request.match_info.get('operation_id', '')
    kind = request.query.get('kind') or 'items'
    try:
        result = await asyncio.to_thread(merge_tasks().export, operation_id, kind)
        return _json(result)
    except UnknownTask:
        return _json({'error': '合并任务不存在；服务重启后请用任务编号重新核对结果。'}, status=404)
    except ValueError as error:
        return _json({'error': str(error)}, status=400)
    except Exception as error:  # noqa: BLE001
        prompt_store.logger.error('导出合并结果失败: %s', error)
        return _json({'error': str(error)}, status=500)
