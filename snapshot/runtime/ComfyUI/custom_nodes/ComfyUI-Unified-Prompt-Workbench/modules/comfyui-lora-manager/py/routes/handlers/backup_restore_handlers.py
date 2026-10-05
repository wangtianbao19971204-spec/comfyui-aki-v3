"""HTTP surface for the native, plan-bound restore workflow.

Routes never write a single byte themselves: they upload the archive, hand it
to :class:`RestoreCoordinator` for a read-only preview, then start or observe a
durable job. Every write decision stays with the reviewed plan.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Mapping, Optional

from aiohttp import web

from ...services.backup_restore_jobs import JobError, RestoreCoordinator
from ...services.backup_plan import PlanError
from ...services.service_registry import ServiceRegistry  # type: ignore[import]

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 512 * 1024 * 1024


def _options_from_form(existing: Optional[str], selected: Optional[str]):
    options: dict[str, Any] = {}
    if existing is not None:
        if existing not in ("skip", "overwrite"):
            raise JobError("existing must be 'skip' or 'overwrite'")
        options["existing"] = existing
    if selected is not None and selected != "":
        try:
            parsed = json.loads(selected)
        except ValueError as exc:
            raise JobError("selected_indices must be a JSON array") from exc
        if not isinstance(parsed, list) or any(
                isinstance(item, bool) or not isinstance(item, int) for item in parsed):
            raise JobError("selected_indices must be a JSON array of integers")
        options["selected_indices"] = parsed
    return options or None


class BackupRestoreHandler:
    """Preview, start, observe and cancel native restore jobs."""

    def __init__(
        self,
        *,
        backup_service_factory: Callable[[], Any] = ServiceRegistry.get_backup_service,
        settings_manager_provider: Optional[Callable[[], Any]] = None,
        service_provider: Optional[Callable[[str], Any]] = None,
        coordinator: Optional[RestoreCoordinator] = None,
    ) -> None:
        self._backup_service_factory = backup_service_factory
        self._service_provider = service_provider
        self._coordinator = coordinator
        if settings_manager_provider is None:
            from ...services.settings_manager import get_settings_manager

            settings_manager_provider = get_settings_manager
        self._settings_manager_provider = settings_manager_provider

    def _owner(self) -> RestoreCoordinator:
        if self._coordinator is None:
            provider = self._service_provider
            if provider is None:
                provider = ServiceRegistry.get_service_sync
            self._coordinator = RestoreCoordinator(
                backup_service_factory=self._backup_service_factory,
                settings_manager_provider=self._settings_manager_provider,
                service_provider=provider,
            )
        return self._coordinator

    @staticmethod
    def _error(message: str, status: int = 400) -> web.Response:
        return web.json_response({"success": False, "error": message}, status=status)

    async def _read_upload(self, request: web.Request) -> tuple[bytes, str, dict]:
        if not request.content_type.startswith("multipart/"):
            raise JobError("restore preview requires a multipart upload")
        data = bytearray()
        filename = "backup.zip"
        fields: dict[str, str] = {}
        reader = await request.multipart()
        field = await reader.next()
        while field is not None:
            if getattr(field, "filename", None):
                filename = str(field.filename or "backup.zip")
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_UPLOAD_BYTES:
                        raise JobError("uploaded archive is too large")
            else:
                fields[field.name] = (await field.text()).strip()
            field = await reader.next()
        if not data:
            raise JobError("missing backup archive")
        return bytes(data), filename, fields

    # ---- routes --------------------------------------------------------
    async def preview_restore(self, request: web.Request) -> web.Response:
        try:
            data, filename, fields = await self._read_upload(request)
            options = _options_from_form(fields.get("existing"), fields.get("selected_indices"))
            result = await self._owner().preview(data, filename, options=options)
            return web.json_response({"success": True, **result})
        except (JobError, PlanError) as exc:
            return self._error(str(exc))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error previewing restore: %s", exc, exc_info=True)
            return self._error(str(exc), 500)

    async def start_restore(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return self._error("restore request requires JSON")
        try:
            job = await self._owner().start(payload)
            return web.json_response({"success": True, **job})
        except JobError as exc:
            logger.info("Restore start refused: %s | payload=%s", exc,
                        json.dumps({key: value for key, value in (payload or {}).items()
                                    if key != "options"}, ensure_ascii=False))
            return self._error(str(exc))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error starting restore: %s", exc, exc_info=True)
            return self._error(str(exc), 500)

    async def get_restore_status(self, request: web.Request) -> web.Response:
        operation_id = request.match_info.get("operation_id") or request.query.get("operation_id")
        try:
            if operation_id in (None, "", "latest"):
                job = self._owner().latest()
                if job is None:
                    return self._error("no restore job has been recorded", 404)
            else:
                job = self._owner().status(operation_id)
            return web.json_response({"success": True, **job})
        except JobError as exc:
            return self._error(str(exc), self._job_status_code(str(exc), operation_id))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error reading restore status: %s", exc, exc_info=True)
            return self._error(str(exc), 500)

    async def cancel_restore(self, request: web.Request) -> web.Response:
        operation_id = request.match_info.get("operation_id") or request.query.get("operation_id")
        try:
            if not operation_id:
                return self._error("operation_id is required")
            return web.json_response({"success": True, **self._owner().cancel(operation_id)})
        except JobError as exc:
            return self._error(str(exc), self._job_status_code(str(exc), operation_id))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error cancelling restore: %s", exc, exc_info=True)
            return self._error(str(exc), 500)

    async def get_restore_manifest(self, request: web.Request) -> web.Response:
        operation_id = request.match_info.get("operation_id") or request.query.get("operation_id")
        try:
            if not operation_id:
                return self._error("operation_id is required")
            return web.json_response(self._owner().manifest(operation_id))
        except JobError as exc:
            return self._error(str(exc), self._job_status_code(str(exc), operation_id))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error exporting restore result: %s", exc, exc_info=True)
            return self._error(str(exc), 500)

    async def list_restore_jobs(self, request: web.Request) -> web.Response:
        try:
            owner = self._owner()
            jobs = [] if owner._ledger is None else owner._ledger.list()
            return web.json_response({"success": True, "jobs": jobs})
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error listing restore jobs: %s", exc, exc_info=True)
            return self._error(str(exc), 500)

    @staticmethod
    def _job_status_code(message: str, operation_id: Optional[str]) -> int:
        """A well-formed but unknown job is a missing resource, not a bad request."""
        if not operation_id or "invalid" in message:
            return 400
        if message in ("unknown operation", "no restore has been started yet"):
            return 404
        return 400
