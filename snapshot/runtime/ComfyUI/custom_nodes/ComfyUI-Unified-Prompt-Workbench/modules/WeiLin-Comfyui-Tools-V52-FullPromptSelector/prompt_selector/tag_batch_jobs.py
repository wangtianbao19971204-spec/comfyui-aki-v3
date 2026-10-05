from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


MAX_RECORDS = 500
DEFAULT_QUEUE_CAPACITY = 8
DEFAULT_TERMINAL_CAPACITY = 64
_TERMINAL = frozenset(("committed", "cancelled", "not_committed", "unknown"))


class BatchError(ValueError):
    pass


class BatchConflict(BatchError):
    def __init__(self, message: str, revision: Optional[str] = None):
        super().__init__(message)
        self.revision = revision


class QueueFull(BatchError):
    pass


class UnknownJob(BatchError):
    pass


class _Cancelled(Exception):
    pass


@dataclass
class _Job:
    token: str
    request: dict[str, Any]
    fingerprint: str
    status: str = "queued"
    processed: int = 0
    committed: Optional[int] = 0
    uncommitted: Optional[int] = 0
    after_revision: Optional[str] = None
    failure: Optional[dict[str, Any]] = None
    cancel_requested: bool = False
    committing: bool = False
    completion_order: int = 0
    condition: threading.Condition = field(default_factory=lambda: threading.Condition(threading.RLock()))

    def snapshot(self) -> dict[str, Any]:
        with self.condition:
            total = len(self.request["resource_ids"])
            return {
                "contract": "weilin-tag-batch-operation-v1",
                "token": self.token,
                "status": self.status,
                "atomic": True,
                "processed": self.processed,
                "total": total,
                "committed": self.committed,
                "uncommitted": self.uncommitted,
                "before_revision": self.request["expected_tag_revision"],
                "after_revision": self.after_revision,
                "collection_revision": self.request["expected_collection_revision"],
                "operation": self.request["operation"],
                "resource_count": total,
                "failure": copy.deepcopy(self.failure),
            }


class TagBatchJobs:
    """A one-worker, bounded, atomic Tag move/delete registry."""

    def __init__(
        self,
        library_factory: Callable[[], Any],
        catalog_lock: Any,
        current_revisions: Callable[[], tuple[str, str, set[str]]],
        queue_capacity: int = DEFAULT_QUEUE_CAPACITY,
        terminal_capacity: int = DEFAULT_TERMINAL_CAPACITY,
    ):
        if queue_capacity < 1 or terminal_capacity < 0:
            raise ValueError("invalid batch capacity")
        self.library_factory = library_factory
        self.catalog_lock = catalog_lock
        self.current_revisions = current_revisions
        self._capacity = queue_capacity
        self._terminal_capacity = max(1, terminal_capacity)
        self._jobs: dict[str, _Job] = {}
        self._pending: deque[_Job] = deque()
        self._condition = threading.Condition(threading.RLock())
        self._stopping = False
        self._sequence = 0
        self._worker = threading.Thread(target=self._run, name="tag-batch-worker", daemon=True)
        self._worker.start()

    @staticmethod
    def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise BatchError("批量操作格式无效")
        token = payload.get("token")
        operation = payload.get("operation")
        ids = payload.get("resource_ids")
        tag_revision = payload.get("expected_tag_revision")
        collection_revision = payload.get("expected_collection_revision")
        target = payload.get("target_g_uuid")
        if not isinstance(token, str) or not token.strip() or len(token) > 200:
            raise BatchError("批量操作 token 无效")
        if operation not in ("move", "delete"):
            raise BatchError("批量操作只支持 move 或 delete")
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_RECORDS:
            raise BatchError("批量操作需要 1–500 个明确的 Tag ID")
        clean = []
        for value in ids:
            if not isinstance(value, str) or not value.startswith("tag:"):
                raise BatchError("Tag ID 必须使用 tag: 前缀")
            value = value[4:]
            if not value or value in clean:
                raise BatchError("Tag ID 必须非空且不能重复")
            clean.append(value)
        if not isinstance(tag_revision, str) or not tag_revision.strip():
            raise BatchError("需要 expected_tag_revision")
        if not isinstance(collection_revision, str) or not collection_revision.strip():
            raise BatchError("需要 expected_collection_revision")
        if operation == "move" and (not isinstance(target, str) or not target):
            raise BatchError("移动操作需要目标分类")
        if operation == "delete" and target is not None:
            raise BatchError("删除操作不能包含目标分类")
        return {
            "token": token,
            "operation": operation,
            "resource_ids": tuple(clean),
            "target_g_uuid": target,
            "expected_tag_revision": tag_revision.strip('"'),
            "expected_collection_revision": collection_revision,
        }

    @staticmethod
    def _fingerprint(request: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _job(self, token: str) -> _Job:
        if not isinstance(token, str):
            raise BatchError("批量操作 token 无效")
        with self._condition:
            job = self._jobs.get(token)
        if job is None:
            raise UnknownJob("批量操作不存在；服务可能已重启")
        return job

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = self._normalise(payload)
        token = request["token"]
        fingerprint = self._fingerprint(request)
        with self._condition:
            old = self._jobs.get(token)
            if old is not None:
                if old.fingerprint != fingerprint:
                    raise BatchConflict("token 已用于不同的批量操作")
                return old.snapshot()
            if self._stopping:
                raise BatchError("批量服务正在关闭")
            if len(self._pending) >= self._capacity:
                raise QueueFull("批量队列已满，请稍后重试")
            job = _Job(token, copy.deepcopy(request), fingerprint)
            self._jobs[token] = job
            self._pending.append(job)
            self._condition.notify_all()
            return job.snapshot()

    def status(self, token: str) -> dict[str, Any]:
        return self._job(token).snapshot()

    def cancel(self, token: str) -> dict[str, Any]:
        job = self._job(token)
        with job.condition:
            if job.status in _TERMINAL:
                return job.snapshot()
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.completion_order = time.monotonic_ns()
                job.committed = 0
                job.uncommitted = len(job.request["resource_ids"])
            else:
                job.status = "cancellation_pending"
            job.condition.notify_all()
        with self._condition:
            self._condition.notify_all()
        return job.snapshot()

    def export(self, token: str, failed: bool = False) -> dict[str, Any]:
        job = self._job(token)
        result = job.snapshot()
        if failed:
            failure = result["failure"] or {}
            ids = failure.get("failed_resource_ids", [])
        else:
            ids = ["tag:" + value for value in job.request["resource_ids"]]
        result["resource_ids"] = ids
        result["request"] = copy.deepcopy(job.request)
        result["request"]["resource_ids"] = ["tag:" + value for value in job.request["resource_ids"]]
        result["retryable_resource_ids"] = result["request"]["resource_ids"] if result["status"] in ("cancelled", "not_committed") else []
        result["export_kind"] = "failed_ids" if failed else "requested_ids"
        result["persistence"] = "memory_bounded_terminal_registry"
        return result

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stopping:
                    self._condition.wait()
                if not self._pending and self._stopping:
                    return
                job = self._pending.popleft()
            with job.condition:
                cancelled = job.status == "cancelled"
                if not cancelled:
                    job.status = "running"
                job.condition.notify_all()
            if not cancelled:
                self._execute(job)
            self._prune()

    @staticmethod
    def _failure(error: Exception, request: dict[str, Any], index: Optional[int]) -> dict[str, Any]:
        item = None
        if index is not None and 0 <= index < len(request["resource_ids"]):
            item = {
                "index": index,
                "resource_id": "tag:" + request["resource_ids"][index],
                "operation": request["operation"],
                "target_g_uuid": request["target_g_uuid"],
                "expected_tag_revision": request["expected_tag_revision"],
                "expected_collection_revision": request["expected_collection_revision"],
            }
        if isinstance(error, BatchConflict):
            result = {"code": "revision_conflict", "message": str(error), "current_revision": error.revision}
        elif isinstance(error, (BatchError, KeyError, ValueError)):
            result = {"code": "invalid_or_failed", "message": str(error)}
        else:
            result = {"code": "operation_failed", "message": "批量操作失败"}
        if item is not None:
            result["failed_index"] = index
            result["failed_resource_id"] = item["resource_id"]
            result["failed_row"] = item
            result["failed_resource_ids"] = [item["resource_id"]]
        return result

    def _execute(self, job: _Job) -> None:
        request = job.request
        failing_index: Optional[int] = None
        committed = False
        try:
            with self.catalog_lock:
                current_tag, current_collection, known_subgroups = self.current_revisions()
                if request["expected_collection_revision"] != current_collection:
                    raise BatchConflict("收藏组已更新，请重新读取后再保存", current_collection)
                if request["operation"] == "move" and request["target_g_uuid"] not in known_subgroups:
                    raise BatchError("目标分类已不存在，请刷新列表")
                library = self.library_factory()
                with library.connection() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        actual_tag = library.revision_of(conn)
                        if request["expected_tag_revision"] != actual_tag:
                            raise BatchConflict("Tag 库已更新，请重新读取后再保存", actual_tag)
                        for failing_index, identity in enumerate(request["resource_ids"]):
                            with job.condition:
                                if job.cancel_requested:
                                    raise _Cancelled()
                            payload = {
                                "operation": request["operation"],
                                "entity": "tag",
                                "resource_id": "tag:" + identity,
                            }
                            if request["operation"] == "move":
                                payload["g_uuid"] = request["target_g_uuid"]
                            library.apply(conn, payload)
                            with job.condition:
                                job.processed = failing_index + 1
                                job.condition.notify_all()
                        after_revision = library.revision_of(conn)
                        with job.condition:
                            if job.cancel_requested:
                                raise _Cancelled()
                            job.committing = True
                            job.status = "committing"
                        try:
                            conn.commit()
                        except Exception:
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                            with job.condition:
                                job.status = "unknown"
                                job.completion_order = time.monotonic_ns()
                                job.committing = False
                                job.committed = None
                                job.uncommitted = None
                                job.failure = {"code": "commit_outcome_unknown", "message": "提交结果未知"}
                                job.condition.notify_all()
                            return
                        committed = True
                        with job.condition:
                            job.status = "committed"
                            job.completion_order = time.monotonic_ns()
                            job.committing = False
                            job.committed = len(request["resource_ids"])
                            job.uncommitted = 0
                            job.after_revision = after_revision
                            job.condition.notify_all()
                    except _Cancelled:
                        conn.rollback()
                        raise
                    except Exception:
                        conn.rollback()
                        raise
        except _Cancelled:
            with job.condition:
                job.status = "cancelled"
                job.completion_order = time.monotonic_ns()
                job.committing = False
                job.processed = 0
                job.committed = 0
                job.uncommitted = len(request["resource_ids"])
                job.condition.notify_all()
        except Exception as error:
            with job.condition:
                if committed or job.status in ("committed", "unknown"):
                    return
                job.status = "not_committed"
                job.completion_order = time.monotonic_ns()
                job.committing = False
                job.committed = 0
                job.uncommitted = len(request["resource_ids"])
                job.failure = self._failure(error, request, failing_index)
                job.condition.notify_all()

    def _prune(self) -> None:
        with self._condition:
            terminals = []
            for job in self._jobs.values():
                with job.condition:
                    if job.status in _TERMINAL:
                        terminals.append(job)
            terminals.sort(key=lambda job: job.completion_order)
            while len(terminals) > self._terminal_capacity:
                victim = terminals.pop(0)
                if victim.status in _TERMINAL:
                    self._jobs.pop(victim.token, None)

    def close(self, timeout: Optional[float] = None) -> None:
        with self._condition:
            if self._stopping:
                worker = self._worker
            else:
                self._stopping = True
                for job in self._jobs.values():
                    with job.condition:
                        if job.status not in _TERMINAL:
                            job.cancel_requested = True
                            if job.status == "queued":
                                job.status = "cancelled"
                                job.completion_order = time.monotonic_ns()
                                job.committed = 0
                                job.uncommitted = len(job.request["resource_ids"])
                            else:
                                job.status = "cancellation_pending"
                            job.condition.notify_all()
                self._pending.clear()
                self._condition.notify_all()
                worker = self._worker
        worker.join(timeout)
        if worker.is_alive():
            raise RuntimeError("批量 worker 未能结束")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def load_tag_library(package_path: str):
    import importlib
    import importlib.util
    from pathlib import Path

    path = Path(package_path)
    if path.is_file():
        spec = importlib.util.spec_from_file_location("tag_batch_source_library", path)
        if spec is None or spec.loader is None:
            raise ImportError("无法加载 TagLibrary 模块")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.TagLibrary
    return importlib.import_module(package_path).TagLibrary
