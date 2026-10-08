"""Service for processing preview assets for models."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from copy import deepcopy
from io import BytesIO
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence
from urllib.parse import urlparse

from PIL import Image, ImageSequence

from ..utils.constants import CARD_PREVIEW_WIDTH, PREVIEW_EXTENSIONS
from ..utils.civitai_utils import rewrite_preview_url
from ..utils.preview_selection import resolve_mature_threshold, select_preview_media
from .settings_manager import get_settings_manager

logger = logging.getLogger(__name__)


class PreviewAssetService:
    """Manage fetching and persisting preview assets."""

    def __init__(
        self,
        *,
        metadata_manager,
        downloader_factory: Callable[[], Awaitable[Any]],
        exif_utils,
    ) -> None:
        self._metadata_manager = metadata_manager
        self._downloader_factory = downloader_factory
        self._exif_utils = exif_utils

    @staticmethod
    def _temporary_path(folder: str) -> str:
        descriptor, path = tempfile.mkstemp(prefix=".lm-preview-", suffix=".tmp", dir=folder)
        os.close(descriptor)
        return path

    @staticmethod
    def _clean_temporary(path: Optional[str]) -> None:
        if not path:
            return
        for candidate in (path, path + ".part"):
            try:
                if os.path.lexists(candidate):
                    os.remove(candidate)
            except OSError as exc:
                logger.warning("Could not remove preview temporary file %s: %s", candidate, exc)

    @staticmethod
    def _safe_preview_path(metadata_path: str, extension: str, model_path: Optional[str] = None) -> str:
        extension = extension.lower()
        if extension not in PREVIEW_EXTENSIONS:
            raise ValueError("Unsupported preview extension")
        suffix = ".metadata.json"
        if not metadata_path.endswith(suffix):
            raise ValueError("Invalid preview metadata path")
        preview_path = metadata_path[:-len(suffix)] + extension
        resolved = os.path.normcase(os.path.abspath(preview_path))
        protected = [metadata_path] + ([model_path] if model_path else [])
        if any(resolved == os.path.normcase(os.path.abspath(path)) for path in protected):
            raise ValueError("Preview destination overlaps model or metadata")
        return preview_path

    @staticmethod
    def _validate_image_bytes(content: bytes) -> None:
        """Reject unreadable images before changing any preview assets."""
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValueError("Invalid preview image: image data is empty or invalid")
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
            # Header inspection alone misses truncated pixels and later GIF frames.
            with Image.open(BytesIO(content)) as image:
                for frame in ImageSequence.Iterator(image):
                    frame.load()
        except Exception as exc:
            raise ValueError("Invalid preview image: the selected file is not a readable image") from exc

    @classmethod
    def _write_bytes_atomic(cls, path: str, content: bytes) -> None:
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValueError("Preview content is empty or invalid")
        temporary = cls._temporary_path(os.path.dirname(path))
        try:
            with open(temporary, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            cls._clean_temporary(temporary)

    @classmethod
    async def _download_preview_atomic(
        cls, downloader, url: str, path: str, *, validate_image: bool = False
    ) -> bool:
        temporary = cls._temporary_path(os.path.dirname(path))
        try:
            success, _ = await downloader.download_file(url, temporary, use_auth=False)
            if not success or not os.path.isfile(temporary) or os.path.getsize(temporary) == 0:
                return False
            if validate_image:
                try:
                    with open(temporary, "rb") as handle:
                        cls._validate_image_bytes(handle.read())
                except ValueError as exc:
                    logger.warning("Downloaded preview is not a valid image: %s", exc)
                    return False
            # A valid preview that appeared during download wins over this fetch.
            if not os.path.isfile(path):
                os.replace(temporary, path)
            return True
        finally:
            cls._clean_temporary(temporary)

    @classmethod
    def _backup_file(cls, path: str) -> Optional[str]:
        if not os.path.isfile(path):
            return None
        backup = cls._temporary_path(os.path.dirname(path))
        try:
            shutil.copyfile(path, backup)
            return backup
        except Exception:
            cls._clean_temporary(backup)
            raise

    @staticmethod
    def _restore_file(path: str, backup: Optional[str]) -> None:
        if backup:
            os.replace(backup, path)
        elif os.path.lexists(path):
            os.remove(path)

    async def ensure_preview_for_metadata(
        self,
        metadata_path: str,
        local_metadata: Dict[str, object],
        images: Sequence[Dict[str, object]] | None,
    ) -> None:
        """Ensure preview assets exist for the supplied metadata entry."""

        if local_metadata.get("preview_url") and os.path.isfile(
            str(local_metadata["preview_url"])
        ):
            return

        if not images:
            return

        settings_manager = get_settings_manager()
        blur_mature_content = bool(
            settings_manager.get("blur_mature_content", True)
        )
        mature_threshold = resolve_mature_threshold(
            {"mature_blur_level": settings_manager.get("mature_blur_level", "R")}
        )
        first_preview, nsfw_level = select_preview_media(
            images,
            blur_mature_content=blur_mature_content,
            mature_threshold=mature_threshold,
        )

        if not first_preview:
            return

        is_video = first_preview.get("type") == "video"
        preview_url = first_preview.get("url")

        if not preview_url:
            return

        preview_url = str(preview_url)

        def extension_from_url(url: str, fallback: str) -> str:
            try:
                parsed = urlparse(url)
            except ValueError:
                return fallback
            ext = os.path.splitext(parsed.path)[1].lower()
            return ext or fallback

        downloader = await self._downloader_factory()

        if is_video:
            extension = extension_from_url(preview_url, ".mp4")
            preview_path = self._safe_preview_path(metadata_path, extension, local_metadata.get("file_path"))
            rewritten_url, rewritten = rewrite_preview_url(preview_url, media_type="video")

            attempt_urls = []
            if rewritten:
                attempt_urls.append(rewritten_url)
            attempt_urls.append(preview_url)

            seen: set[str] = set()
            for candidate in attempt_urls:
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)

                success = await self._download_preview_atomic(downloader, candidate, preview_path)
                if success:
                    local_metadata["preview_url"] = preview_path.replace(os.sep, "/")
                    local_metadata["preview_nsfw_level"] = nsfw_level
                    return
        else:
            rewritten_url, rewritten = rewrite_preview_url(preview_url, media_type="image")
            if rewritten:
                extension = extension_from_url(preview_url, ".png")
                preview_path = self._safe_preview_path(metadata_path, extension, local_metadata.get("file_path"))
                success = await self._download_preview_atomic(
                    downloader, rewritten_url, preview_path, validate_image=True
                )
                if success:
                    local_metadata["preview_url"] = preview_path.replace(os.sep, "/")
                    local_metadata["preview_nsfw_level"] = nsfw_level
                    return

            extension = ".webp"
            preview_path = self._safe_preview_path(metadata_path, extension, local_metadata.get("file_path"))
            success, content, _headers = await downloader.download_to_memory(
                preview_url, use_auth=False
            )
            if not success:
                return

            self._validate_image_bytes(content)
            try:
                optimized_data, _ = self._exif_utils.optimize_image(
                    image_data=content,
                    target_width=CARD_PREVIEW_WIDTH,
                    format="webp",
                    quality=85,
                    preserve_metadata=False,
                )
                self._validate_image_bytes(optimized_data)
                if not os.path.isfile(preview_path):
                    self._write_bytes_atomic(preview_path, optimized_data)
            except Exception as exc:  # pragma: no cover - defensive path
                logger.error("Error optimizing preview image: %s", exc)
                try:
                    if not os.path.isfile(preview_path):
                        self._write_bytes_atomic(preview_path, content)
                except Exception as save_exc:
                    logger.error("Error saving preview image: %s", save_exc)
                    return

            local_metadata["preview_url"] = preview_path.replace(os.sep, "/")
            local_metadata["preview_nsfw_level"] = nsfw_level

    async def replace_preview(
        self,
        *,
        model_path: str,
        preview_data: bytes,
        content_type: str,
        original_filename: Optional[str],
        nsfw_level: int,
        update_preview_in_cache: Callable[[str, str, int], Awaitable[bool]],
        metadata_loader: Callable[[str], Awaitable[Dict[str, object]]],
    ) -> Dict[str, object]:
        """Replace an existing preview asset for a model."""

        base_name = os.path.splitext(os.path.basename(model_path))[0]
        folder = os.path.dirname(model_path)

        extension, optimized_data = await self._convert_preview(
            preview_data, content_type, original_filename
        )

        metadata_path = os.path.splitext(model_path)[0] + ".metadata.json"
        preview_path = self._safe_preview_path(metadata_path, extension, model_path).replace(os.sep, "/")
        metadata = await metadata_loader(metadata_path)
        if not isinstance(metadata, dict):
            raise ValueError("Invalid preview metadata")
        previous_metadata = deepcopy(metadata)
        metadata = deepcopy(metadata)
        preview_backup = metadata_backup = None
        installed = cache_attempted = False
        retained_backups: set[str] = set()
        try:
            preview_backup = self._backup_file(preview_path)
            metadata_backup = self._backup_file(metadata_path)
            self._write_bytes_atomic(preview_path, optimized_data)
            installed = True
            metadata["preview_url"] = preview_path
            metadata["preview_nsfw_level"] = nsfw_level
            if not await self._metadata_manager.save_metadata(model_path, metadata):
                raise RuntimeError("Failed to save preview metadata")
            cache_attempted = True
            if not await update_preview_in_cache(model_path, preview_path, nsfw_level):
                raise RuntimeError("Failed to update preview cache")
        except Exception as exc:
            recovery_errors = []
            if installed:
                for target, backup in ((preview_path, preview_backup), (metadata_path, metadata_backup)):
                    try:
                        self._restore_file(target, backup)
                    except OSError as recovery_exc:
                        if backup and os.path.isfile(backup):
                            retained_backups.add(backup)
                            recovery_errors.append(f"recovery backup retained: {backup}: {recovery_exc}")
                        else:
                            recovery_errors.append(str(recovery_exc))
            if cache_attempted:
                try:
                    restored = await update_preview_in_cache(
                        model_path, previous_metadata.get("preview_url", ""),
                        previous_metadata.get("preview_nsfw_level", 0),
                    )
                    if not restored:
                        recovery_errors.append("cache recovery failed")
                except Exception as recovery_exc:
                    recovery_errors.append(str(recovery_exc))
            if recovery_errors:
                raise RuntimeError(f"{exc}; preview recovery incomplete: {'; '.join(recovery_errors)}") from exc
            raise
        finally:
            if preview_backup not in retained_backups:
                self._clean_temporary(preview_backup)
            if metadata_backup not in retained_backups:
                self._clean_temporary(metadata_backup)

        # Delete old variants only after the image, metadata and cache are committed.
        for ext in PREVIEW_EXTENSIONS:
            existing_preview = os.path.join(folder, base_name + ext)
            if os.path.normcase(os.path.abspath(existing_preview)) == os.path.normcase(os.path.abspath(preview_path)):
                continue
            if os.path.isfile(existing_preview):
                try:
                    os.remove(existing_preview)
                except OSError as exc:
                    logger.warning("Failed to delete old preview %s: %s", existing_preview, exc)
        return {"preview_path": preview_path, "preview_nsfw_level": nsfw_level}

    async def _convert_preview(
        self, data: bytes, content_type: str, original_filename: Optional[str]
    ) -> tuple[str, bytes]:
        """Convert preview bytes to the persisted representation."""

        if content_type.startswith("video/"):
            extension = self._resolve_video_extension(content_type, original_filename)
            return extension, data

        self._validate_image_bytes(data)
        original_ext = (original_filename or "").lower()
        if original_ext.endswith(".gif") or content_type.lower() == "image/gif":
            return ".gif", data

        optimized_data, _ = self._exif_utils.optimize_image(
            image_data=data,
            target_width=CARD_PREVIEW_WIDTH,
            format="webp",
            quality=85,
            preserve_metadata=False,
        )
        self._validate_image_bytes(optimized_data)
        return ".webp", optimized_data

    def _resolve_video_extension(self, content_type: str, original_filename: Optional[str]) -> str:
        """Infer the best extension for a video preview."""

        if original_filename:
            extension = os.path.splitext(original_filename)[1].lower()
            if extension in {".mp4", ".webm", ".mov", ".avi"}:
                return extension

        if "webm" in content_type:
            return ".webm"
        return ".mp4"
