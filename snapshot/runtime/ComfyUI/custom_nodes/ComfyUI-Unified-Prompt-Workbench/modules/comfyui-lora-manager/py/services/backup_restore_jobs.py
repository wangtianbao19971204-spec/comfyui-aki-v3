"""Durable restore jobs for the native model backup workflow.

``backup_plan`` builds a read-only, fingerprint-bound plan, ``backup_executor``
performs the per-file replacements and this module owns everything that must
outlive a request: the uploaded archive, the plan token, the persistent job
ledger and the owner coordination (settings restore context, SQLite checkpoint
binding, model-update/download-history suspension and the runtime refresh).

Nothing here invents a second copy of the restored data: the ledger stores
status, per-unit results and the derived checkpoint transitions only.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from .backup_checkpoint_binding import BindingError, CheckpointBinding
from .backup_executor import InitialJournalError, execute_plan
from .backup_fingerprints import FingerprintError, fingerprint_path
from .backup_plan import PlanError

MAX_LEDGER_JOBS = 24
MAX_UPLOADS = 8
SQLITE_KINDS = ("model_update", "download_history")
# Restore kind -> registered service name used by the owning service registry.
OWNER_SERVICES = (("model_update", "model_update_service"),
                  ("download_history", "downloaded_version_history_service"))
TERMINAL_STATUSES = ("completed", "partial", "cancelled", "failed")
_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_OPERATION = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class JobError(ValueError):
    """Invalid job request or unknown job."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _write_json(path: str, payload: Mapping[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".jobs-", suffix=".json", dir=directory or None)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
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


class UploadStore:
    """Private copies of uploaded archives plus their reviewed plan."""

    def __init__(self, root: str, *, max_uploads: int = MAX_UPLOADS, max_bytes: int = 2 * 1024 * 1024 * 1024):
        self.root = root
        self.max_uploads = max_uploads
        self.max_bytes = max_bytes
        os.makedirs(self.root, exist_ok=True)

    def _plan_path(self, upload_id: str) -> str:
        return os.path.join(self.root, f"{upload_id}.plan.json")

    def path(self, upload_id: str) -> str:
        if not _OPERATION.match(str(upload_id or "")):
            raise JobError("invalid upload id")
        path = os.path.join(self.root, f"{upload_id}.zip")
        if not os.path.isfile(path):
            raise JobError("uploaded archive is no longer available; preview it again")
        return path

    def record(self, upload_id: str, plan: Mapping[str, Any], archive_name: str) -> None:
        _write_json(self._plan_path(upload_id), {"upload_id": upload_id, "archive_name": archive_name,
                                                 "plan": plan, "created_at": _now()})
        self._prune()

    def load(self, upload_id: str) -> dict:
        if not _OPERATION.match(str(upload_id or "")):
            raise JobError("invalid upload id")
        path = self._plan_path(upload_id)
        if not os.path.isfile(path):
            raise JobError("uploaded archive is no longer available; preview it again")
        with open(path, "r", encoding="utf-8") as handle:
            record = json.load(handle)
        self.path(upload_id)
        return record

    def save_archive(self, data: bytes, archive_name: str) -> str:
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise JobError("empty upload")
        if len(data) > self.max_bytes:
            raise JobError("uploaded archive is too large")
        upload_id = str(uuid.uuid4())
        target = os.path.join(self.root, f"{upload_id}.zip")
        fd, temp = tempfile.mkstemp(prefix=".upload-", suffix=".zip", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(bytes(data))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                try:
                    os.remove(temp)
                except OSError:
                    pass
        return upload_id

    def _prune(self) -> None:
        entries = []
        for name in os.listdir(self.root):
            if name.endswith(".plan.json"):
                path = os.path.join(self.root, name)
                try:
                    entries.append((os.path.getmtime(path), name[: -len(".plan.json")]))
                except OSError:
                    continue
        entries.sort(reverse=True)
        for _, upload_id in entries[self.max_uploads:]:
            for name in (f"{upload_id}.plan.json", f"{upload_id}.zip"):
                try:
                    os.remove(os.path.join(self.root, name))
                except OSError:
                    pass


class JobLedger:
    """Bounded, atomically written restore job ledger."""

    def __init__(self, path: str, *, max_jobs: int = MAX_LEDGER_JOBS):
        self.path = path
        self.max_jobs = max_jobs
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, list):
            for record in payload:
                if isinstance(record, dict) and isinstance(record.get("operation_id"), str):
                    self._jobs[record["operation_id"]] = record
        self._truncate()

    def _truncate(self) -> None:
        if len(self._jobs) <= self.max_jobs:
            return
        ordered = sorted(self._jobs.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)
        keep = {item["operation_id"] for item in ordered[: self.max_jobs]}
        self._jobs = {key: value for key, value in self._jobs.items() if key in keep}

    def _save(self) -> None:
        ordered = sorted(self._jobs.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)
        _write_json(self.path, ordered)

    def create(self, record: Mapping[str, Any]) -> dict:
        with self._lock:
            stored = dict(record)
            stored["updated_at"] = _now()
            self._jobs[stored["operation_id"]] = stored
            self._truncate()
            self._save()
            return json.loads(json.dumps(stored))

    def update(self, operation_id: str, **fields) -> dict:
        with self._lock:
            record = self._jobs.get(operation_id)
            if record is None:
                raise JobError("unknown operation")
            record.update(fields)
            record["updated_at"] = _now()
            self._save()
            return json.loads(json.dumps(record))

    def get(self, operation_id: str) -> dict:
        with self._lock:
            record = self._jobs.get(operation_id)
            if record is None:
                raise JobError("unknown operation")
            return json.loads(json.dumps(record))

    def latest(self) -> Optional[dict]:
        with self._lock:
            if not self._jobs:
                return None
            ordered = sorted(self._jobs.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)
            return json.loads(json.dumps(ordered[0]))

    def list(self) -> list[dict]:
        with self._lock:
            ordered = sorted(self._jobs.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)
            return json.loads(json.dumps(ordered))


class _CheckpointTracker:
    """Bracket each owning service's in-lock checkpoint with a sealed receipt."""

    def __init__(self, binding: CheckpointBinding, plan: Mapping[str, Any]):
        self.binding = binding
        self.index = {}
        self.paths = {}
        for unit in plan.get("units") or []:
            if (isinstance(unit, dict) and unit.get("action") == "write"
                    and unit.get("kind") in SQLITE_KINDS and isinstance(unit.get("target"), str)):
                self.index[_key(unit["target"])] = unit["index"]
                self.paths[unit["index"]] = unit["target"]
        self.pending: dict[int, Any] = {}
        self.receipts: list[Any] = []
        self.synthetic: list[int] = []

    def verify(self, path) -> None:
        index = self.index.get(_key(path))
        if index is None:
            return
        if index in self.pending:
            return
        self.pending[index] = self.binding.begin(index, path)

    def settle(self, path) -> None:
        index = self.index.get(_key(path))
        if index is None or index not in self.pending:
            return
        self.receipts.append(self.binding.finish(self.pending.pop(index), path))

    def seal_unregistered(self) -> list[int]:
        """Seal SQLite units whose owner is not registered for this restore.

        Nothing checkpoints those databases, so the binding must still account
        for them: an immediate snapshot/finish pair asserts the logical state is
        untouched, and the executor re-reads the fingerprint immediately before
        replacing the file.
        """
        issued = {receipt.to_dict()["unit_index"] for receipt in self.receipts}
        for index in sorted(self.paths):
            if index in self.pending or index in issued:
                continue
            pending = self.binding.begin(index, self.paths[index])
            self.receipts.append(self.binding.finish(pending, self.paths[index]))
            self.synthetic.append(index)
        return list(self.synthetic)


def _counts_from_units(units) -> dict:
    counts = {name: 0 for name in ("committed", "failed", "cancelled", "skipped", "pending", "unknown")}
    for unit in units or []:
        state = unit.get("state") if isinstance(unit, dict) else None
        if state in counts:
            counts[state] += 1
    return counts


class RestoreCoordinator:
    """Owns restore lifecycle: preview, durable job, owner coordination."""

    def __init__(
        self,
        *,
        backup_service_factory: Callable[[], Any],
        settings_manager_provider: Callable[[], Any],
        service_provider: Optional[Callable[[str], Any]] = None,
        store_root: Optional[str] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._backup_service_factory = backup_service_factory
        self._settings_manager_provider = settings_manager_provider
        self._service_provider = service_provider
        self._store_root = store_root
        self._loop = loop
        self._uploads: Optional[UploadStore] = None
        self._ledger: Optional[JobLedger] = None
        self._cancels: dict[str, threading.Event] = {}

    # ---- storage -------------------------------------------------------
    async def _ensure_store(self) -> tuple[UploadStore, JobLedger]:
        if self._uploads is None or self._ledger is None:
            root = self._store_root
            if root is None:
                service = await self._backup_service_factory()
                root = os.path.join(service.get_backup_dir(), "restore")
            self._uploads = UploadStore(os.path.join(root, "uploads"))
            self._ledger = JobLedger(os.path.join(root, "jobs.json"))
        return self._uploads, self._ledger

    # ---- preview -------------------------------------------------------
    async def preview(self, data: bytes, archive_name: str, options=None, limits=None) -> dict:
        uploads, _ = await self._ensure_store()
        service = await self._backup_service_factory()
        if len(data) > (limits or {}).get("compressed_bytes", 10 ** 12):
            raise JobError("uploaded archive is too large")
        upload_id = uploads.save_archive(data, archive_name)
        try:
            plan = await asyncio.to_thread(service.preview_restore, uploads.path(upload_id),
                                           options=options, limits=limits)
        except Exception:
            try:
                os.remove(uploads.path(upload_id))
            except OSError:
                pass
            raise
        uploads.record(upload_id, plan, archive_name)
        return {"upload_id": upload_id, "plan": plan}

    # ---- start / status ------------------------------------------------
    async def start(self, payload: Mapping[str, Any]) -> dict:
        uploads, ledger = await self._ensure_store()
        if not isinstance(payload, Mapping):
            raise JobError("job request must be an object")
        upload_id = payload.get("upload_id")
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, str) or not _OPERATION.match(operation_id):
            raise JobError("invalid operation id")
        record = uploads.load(upload_id)
        plan = record.get("plan")
        if not isinstance(plan, dict):
            raise JobError("reviewed plan is missing")
        if payload.get("plan_hash") != plan.get("plan_hash"):
            raise JobError("plan hash mismatch; preview the archive again")
        options = payload.get("options")
        reviewed = plan.get("options")
        if options is not None and options != reviewed:
            raise JobError("options changed after preview; preview the archive again")
        try:
            ledger.get(operation_id)
        except JobError:
            pass
        else:
            raise JobError("operation id already exists")
        archive_path = uploads.path(upload_id)
        try:
            digest, size, _ = _archive_stamp(archive_path)
        except OSError as exc:
            raise JobError(f"cannot read uploaded archive: {exc}") from exc
        if plan.get("archive_sha256") and digest.lower() != str(plan["archive_sha256"]).lower():
            raise JobError("uploaded archive changed after preview")
        job = ledger.create({
            "contract": "weilin-native-restore-v1",
            "operation_id": operation_id,
            "upload_id": upload_id,
            "archive_name": record.get("archive_name"),
            "archive_sha256": digest,
            "plan_hash": plan.get("plan_hash"),
            "status": "running",
            "created_at": _now(),
            "started_at": _now(),
            "finished_at": None,
            "counts": _counts_from_units([]),
            "units": [],
            "committed_kinds": [],
            "refresh": None,
            "refresh_required": False,
            "error": None,
        })
        self._cancels[operation_id] = threading.Event()
        loop = self._loop or asyncio.get_running_loop()
        loop.create_task(self._run(operation_id, archive_path, plan))
        return job

    def status(self, operation_id: str) -> dict:
        if self._ledger is None:
            raise JobError("no restore has been started yet")
        return self._ledger.get(operation_id)

    def latest(self) -> Optional[dict]:
        return None if self._ledger is None else self._ledger.latest()

    def manifest(self, operation_id: str) -> dict:
        record = self.status(operation_id)
        return {
            "contract": record.get("contract"),
            "operation_id": record.get("operation_id"),
            "archive_name": record.get("archive_name"),
            "status": record.get("status"),
            "plan_hash": record.get("plan_hash"),
            "created_at": record.get("created_at"),
            "finished_at": record.get("finished_at"),
            "counts": record.get("counts"),
            "units": record.get("units"),
            "committed_kinds": record.get("committed_kinds"),
            "refresh": record.get("refresh"),
            "refresh_required": record.get("refresh_required"),
            "error": record.get("error"),
        }

    def cancel(self, operation_id: str) -> dict:
        record = self.status(operation_id)
        event = self._cancels.get(operation_id)
        if record.get("status") != "running":
            return record
        if event is not None:
            event.set()
        try:
            return self._ledger.update(operation_id, cancel_requested=True)
        except JobError:
            return record

    # ---- execution -----------------------------------------------------
    def _cancelled(self, operation_id: str) -> bool:
        event = self._cancels.get(operation_id)
        return bool(event and event.is_set())

    def _fingerprint(self, plan: Mapping[str, Any]):
        modes = {}
        for unit in plan.get("units") or []:
            if isinstance(unit, dict) and isinstance(unit.get("target"), str):
                modes[_key(unit["target"])] = unit.get("kind") in SQLITE_KINDS

        def read(path):
            key = _key(path)
            if key not in modes:
                raise FingerprintError("destination is outside the reviewed plan")
            return fingerprint_path(path, sqlite=modes[key])
        return read

    def _journal(self, operation_id: str, snapshot: Mapping[str, Any]) -> None:
        if self._ledger is None:
            raise JobError("ledger is not ready")
        self._ledger.update(
            operation_id,
            status="running" if snapshot.get("status") == "running" else snapshot.get("status"),
            counts=snapshot.get("counts") or _counts_from_units(snapshot.get("units")),
            units=snapshot.get("units"),
            error=snapshot.get("error"),
        )

    def _service(self, name: str):
        if self._service_provider is None:
            return None
        try:
            return self._service_provider(name)
        except Exception:
            return None

    @staticmethod
    def _archived_settings(archive_path: str, plan: Mapping[str, Any]) -> Optional[dict]:
        for unit in plan.get("units") or []:
            if (isinstance(unit, dict) and unit.get("kind") == "settings"
                    and unit.get("action") == "write" and isinstance(unit.get("member"), str)):
                import zipfile

                with zipfile.ZipFile(archive_path) as archive:
                    raw = archive.read(unit["member"])
                return json.loads(raw.decode("utf-8"))
        return None

    def _execute(self, operation_id: str, archive_path: str, plan: Mapping[str, Any]) -> dict:
        """Synchronous worker: settings context + executor + settings publication."""
        settings = self._settings_manager_provider()
        payload = self._archived_settings(archive_path, plan)
        context = None
        if payload is not None:
            context = settings.begin_restore(payload)
        outcome = {"result": None, "committed_kinds": [], "publish_error": None, "context": bool(context)}
        try:
            result = execute_plan(
                archive_path,
                plan,
                journal=lambda snapshot: self._journal(operation_id, snapshot),
                fingerprint=self._fingerprint(plan),
                cancelled=lambda: self._cancelled(operation_id),
            )
            outcome["result"] = result
            committed = {unit.get("kind") for unit in (result.get("units") or [])
                         if isinstance(unit, dict) and unit.get("state") == "committed"}
            settings_unit = next((unit for unit in (plan.get("units") or [])
                                  if isinstance(unit, dict) and unit.get("kind") == "settings"), None)
            if context is not None:
                if settings_unit is not None and settings_unit.get("kind") in committed:
                    try:
                        context.publish(executor_status="success", context_token=context)
                        outcome["committed_kinds"].append("settings")
                    except Exception as exc:  # committed disk, runtime not published
                        outcome["publish_error"] = str(exc)
                        try:
                            context.abort()
                        except Exception:
                            pass
                else:
                    try:
                        context.abort()
                    except Exception:
                        pass
            outcome["committed_kinds"].extend(
                kind for kind in committed if kind in (*SQLITE_KINDS, "symlink_map", "usage_stats"))
            return outcome
        except InitialJournalError as exc:
            outcome["result"] = exc.result
            if context is not None:
                try:
                    context.abort()
                except Exception:
                    pass
            outcome["publish_error"] = "initial journal failed; nothing was written"
            return outcome
        except Exception as exc:
            if context is not None:
                try:
                    context.abort()
                except Exception:
                    pass
            raise

    async def _acquire_owners(self, tracker: _CheckpointTracker, plan=None):
        """Suspend registered owners; returns a stacked async context manager."""
        import contextlib

        stack = contextlib.AsyncExitStack()
        suspended = []
        try:
            if any(unit.get("kind") == "usage_stats" and unit.get("action") == "write"
                   for unit in (plan or {}).get("units", [])):
                from ..utils.usage_stats import UsageStats
                stats = UsageStats._instance
                if stats is not None and stats._initialized:
                    await stack.enter_async_context(stats.suspend_for_restore())
                    suspended.append("usage_stats")
            for kind, service_name in OWNER_SERVICES:
                service = self._service(service_name)
                if service is None or not hasattr(service, "suspend_for_restore"):
                    continue
                await stack.enter_async_context(service.suspend_for_restore(verify=tracker.verify))
                path = getattr(service, "_db_path", None)
                if isinstance(path, str):
                    tracker.settle(path)
                suspended.append(kind)
        except Exception:
            await stack.aclose()
            raise
        return stack, suspended

    async def _run(self, operation_id: str, archive_path: str, plan: Mapping[str, Any]) -> None:
        ledger = self._ledger
        assert ledger is not None
        committed_kinds: list[str] = []
        suspended: list[str] = []
        sealed: list[int] = []
        try:
            binding = CheckpointBinding(plan, scratch_dir=os.path.dirname(archive_path))
            tracker = _CheckpointTracker(binding, plan)
            with binding:
                stack, suspended = await self._acquire_owners(tracker, plan)
                try:
                    sealed = tracker.seal_unregistered()
                    derived = binding.derive(tracker.receipts)
                    outcome = await asyncio.to_thread(self._execute, operation_id, archive_path, derived)
                finally:
                    await stack.aclose()
            result = outcome.get("result") or {}
            committed_kinds = list(outcome.get("committed_kinds") or [])
            refresh = None
            refresh_required = bool(outcome.get("publish_error"))
            if committed_kinds:
                try:
                    settings = self._settings_manager_provider()
                    refresh = await asyncio.to_thread(
                        settings.refresh_restored_runtime, restored_owners=committed_kinds)
                    refresh_required = refresh_required or not refresh.get("complete", False)
                except Exception as exc:
                    refresh = {"error": str(exc)}
                    refresh_required = True
            units = result.get("units") or []
            counts = result.get("counts") or _counts_from_units(units)
            if result.get("status") == "cancelled":
                status = "cancelled"
            elif result.get("success") and counts.get("failed", 0) == 0 and result.get("error") is None:
                status = "completed"
            elif counts.get("committed", 0) > 0:
                status = "partial"
            elif counts.get("unknown", 0) > 0 or result.get("error") == "journal_error":
                status = "failed"
                refresh_required = True
            else:
                status = "failed"
            ledger.update(operation_id, status=status, finished_at=_now(), counts=counts, units=units,
                          committed_kinds=committed_kinds, refresh=refresh,
                          refresh_required=refresh_required, publish_error=outcome.get("publish_error"),
                          error=result.get("error"), suspended=suspended,
                          checkpointed_units=[index for index in tracker.paths if index not in sealed],
                          unregistered_units=sealed)
        except BindingError as exc:
            ledger.update(operation_id, status="failed", finished_at=_now(), refresh_required=True,
                          error=f"checkpoint binding refused the run: {exc}",
                          suspended=suspended, unregistered_units=sealed)
        except Exception as exc:
            ledger.update(operation_id, status="failed", finished_at=_now(), refresh_required=True,
                          error=str(exc), committed_kinds=committed_kinds,
                          suspended=suspended, unregistered_units=sealed)
        finally:
            self._cancels.pop(operation_id, None)


def _archive_stamp(path: str) -> tuple[str, int, float]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size, os.path.getmtime(path)
