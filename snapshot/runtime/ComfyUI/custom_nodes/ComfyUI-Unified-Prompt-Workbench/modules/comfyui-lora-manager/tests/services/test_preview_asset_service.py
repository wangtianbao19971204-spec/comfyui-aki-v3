from pathlib import Path
import json
from io import BytesIO
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from py.services import preview_asset_service
from py.services.preview_asset_service import PreviewAssetService
from py.utils.exif_utils import ExifUtils


def encoded_image_bytes(format="PNG"):
    output = BytesIO()
    Image.new("RGB", (4, 4), color="blue").save(output, format=format)
    return output.getvalue()


class StubMetadataManager:
    async def save_metadata(self, *_args: Any, **_kwargs: Any) -> bool:  # pragma: no cover - helper
        return True


class RecordingExifUtils:
    def __init__(self) -> None:
        self.called = False

    def optimize_image(self, **kwargs):
        self.called = True
        return kwargs["image_data"], {}


@pytest.mark.asyncio
async def test_ensure_preview_prefers_rewritten_civitai_image(tmp_path):
    metadata_path = tmp_path / "model.metadata.json"
    metadata_path.write_text("{}")
    local_metadata: dict[str, Any] = {}

    class Downloader:
        def __init__(self):
            self.file_calls: list[tuple[str, str]] = []
            self.memory_calls = 0

        async def download_file(self, url, path, use_auth=False):
            self.file_calls.append((url, path))
            if "width=450,optimized=true" in url:
                Path(path).write_bytes(encoded_image_bytes())
                return True, None
            return False, "fail"

        async def download_to_memory(self, *_args, **_kwargs):
            self.memory_calls += 1
            return False, b"", {}

    downloader = Downloader()

    async def downloader_factory():
        return downloader

    exif_utils = RecordingExifUtils()
    service = PreviewAssetService(
        metadata_manager=StubMetadataManager(),
        downloader_factory=downloader_factory,
        exif_utils=exif_utils,
    )

    images: List[Dict[str, object]] = [
        {
            "url": "https://image.civitai.com/container/example/original=true/sample.jpeg",
            "type": "image",
            "nsfwLevel": 3,
        }
    ]

    await service.ensure_preview_for_metadata(str(metadata_path), local_metadata, images)

    assert downloader.memory_calls == 0
    assert exif_utils.called is False
    assert len(downloader.file_calls) == 1
    assert "width=450,optimized=true" in downloader.file_calls[0][0]
    preview_path = Path(local_metadata["preview_url"])
    assert preview_path.exists()
    assert preview_path.suffix == ".jpeg"
    assert local_metadata["preview_nsfw_level"] == 3


@pytest.mark.asyncio
async def test_ensure_preview_falls_back_to_webp_when_rewrite_fails(tmp_path):
    metadata_path = tmp_path / "model.metadata.json"
    metadata_path.write_text("{}")
    local_metadata: dict[str, Any] = {}

    class Downloader:
        def __init__(self):
            self.file_calls: list[tuple[str, str]] = []
            self.memory_calls = 0

        async def download_file(self, url, path, use_auth=False):
            self.file_calls.append((url, path))
            return False, "fail"

        async def download_to_memory(self, *_args, **_kwargs):
            self.memory_calls += 1
            return True, encoded_image_bytes(), {}

    downloader = Downloader()

    async def downloader_factory():
        return downloader

    class ExifUtils:
        def __init__(self):
            self.calls = 0

        def optimize_image(self, **kwargs):
            self.calls += 1
            return encoded_image_bytes("WEBP"), {}

    exif_utils = ExifUtils()

    service = PreviewAssetService(
        metadata_manager=StubMetadataManager(),
        downloader_factory=downloader_factory,
        exif_utils=exif_utils,
    )

    images: List[Dict[str, object]] = [
        {
            "url": "https://image.civitai.com/container/example/original=true/sample.png",
            "type": "image",
            "nsfwLevel": 1,
        }
    ]

    await service.ensure_preview_for_metadata(str(metadata_path), local_metadata, images)

    assert downloader.memory_calls == 1
    assert exif_utils.calls == 1
    preview_path = Path(local_metadata["preview_url"])
    assert preview_path.exists()
    assert preview_path.suffix == ".webp"


@pytest.mark.asyncio
async def test_ensure_preview_rewrites_civitai_video(tmp_path):
    metadata_path = tmp_path / "model.metadata.json"
    metadata_path.write_text("{}")
    local_metadata: dict[str, Any] = {}

    class Downloader:
        def __init__(self):
            self.file_calls: list[tuple[str, str]] = []

        async def download_file(self, url, path, use_auth=False):
            self.file_calls.append((url, path))
            if "transcode=true,width=450,optimized=true" in url:
                Path(path).write_bytes(b"video-data")
                return True, None
            if url.endswith(".mp4"):
                return False, "fail"
            return False, "unexpected"

        async def download_to_memory(self, *_args, **_kwargs):
            pytest.fail("download_to_memory should not be used for video previews")

    downloader = Downloader()

    async def downloader_factory():
        return downloader

    service = PreviewAssetService(
        metadata_manager=StubMetadataManager(),
        downloader_factory=downloader_factory,
        exif_utils=RecordingExifUtils(),
    )

    images: List[Dict[str, object]] = [
        {
            "url": "https://image.civitai.com/container/example/original=true/sample.mp4",
            "type": "video",
            "nsfwLevel": 2,
        }
    ]

    await service.ensure_preview_for_metadata(str(metadata_path), local_metadata, images)

    assert len(downloader.file_calls) >= 1
    assert any("transcode=true,width=450,optimized=true" in url for url, _ in downloader.file_calls)
    preview_path = Path(local_metadata["preview_url"])
    assert preview_path.exists()
    assert preview_path.suffix == ".mp4"
    assert local_metadata["preview_nsfw_level"] == 2


@pytest.mark.asyncio
async def test_ensure_preview_respects_blur_setting(monkeypatch, tmp_path):
    metadata_path = tmp_path / "model.metadata.json"
    metadata_path.write_text("{}")
    local_metadata: dict[str, Any] = {}

    class Downloader:
        def __init__(self):
            self.file_calls: list[tuple[str, str]] = []

        async def download_file(self, url, path, use_auth=False):
            self.file_calls.append((url, path))
            Path(path).write_bytes(encoded_image_bytes())
            return True, None

        async def download_to_memory(self, *_args, **_kwargs):
            pytest.fail("download_to_memory should not be used when download_file succeeds")

    downloader = Downloader()

    async def downloader_factory():
        return downloader

    class StubSettingsManager:
        def __init__(self, blur: bool) -> None:
            self.blur = blur

        def get(self, key: str, default=None):
            if key == "blur_mature_content":
                return self.blur
            return default

    monkeypatch.setattr(
        preview_asset_service,
        "get_settings_manager",
        lambda: StubSettingsManager(True),
    )

    service = PreviewAssetService(
        metadata_manager=StubMetadataManager(),
        downloader_factory=downloader_factory,
        exif_utils=RecordingExifUtils(),
    )

    images: List[Dict[str, object]] = [
        {
            "url": "https://image.civitai.com/container/example/original=true/nsfw.jpeg",
            "type": "image",
            "nsfwLevel": 8,
        },
        {
            "url": "https://image.civitai.com/container/example/original=true/safe.jpeg",
            "type": "image",
            "nsfwLevel": 1,
        },
    ]

    await service.ensure_preview_for_metadata(str(metadata_path), local_metadata, images)

    assert len(downloader.file_calls) == 1
    requested_url = downloader.file_calls[0][0]
    assert "safe.jpeg" in requested_url
    assert local_metadata["preview_nsfw_level"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", ["video", "image"])
@pytest.mark.parametrize("extension", [".safetensors", ".json", ".exe"])
async def test_remote_suffix_cannot_overwrite_model_or_metadata(tmp_path, media_type, extension):
    model = tmp_path / "model.safetensors"
    metadata = tmp_path / "model.metadata.json"
    model.write_bytes(b"original model")
    metadata.write_bytes(b'{"private":"preserved"}')
    downloader = type("Downloader", (), {"download_file": AsyncMock(), "download_to_memory": AsyncMock()})()
    service = PreviewAssetService(metadata_manager=StubMetadataManager(),
        downloader_factory=AsyncMock(return_value=downloader), exif_utils=RecordingExifUtils())
    payload = {"file_path": str(model)}
    with pytest.raises(ValueError, match="Unsupported preview extension"):
        await service.ensure_preview_for_metadata(str(metadata), payload, [{
            "url": f"https://image.civitai.com/container/example/original=true/sample{extension}",
            "type": media_type,
        }])
    assert model.read_bytes() == b"original model"
    assert metadata.read_bytes() == b'{"private":"preserved"}'
    assert "preview_url" not in payload
    downloader.download_file.assert_not_awaited()
    downloader.download_to_memory.assert_not_awaited()
    assert not list(tmp_path.glob(".lm-preview-*"))


@pytest.mark.asyncio
async def test_failed_download_removes_partial_temporary_files(tmp_path):
    metadata = tmp_path / "model.metadata.json"
    metadata.write_bytes(b"{}")
    destination = tmp_path / "model.mp4"

    async def partial_download(url, path, **kwargs):
        assert Path(path) != destination
        Path(path).write_bytes(b"partial")
        Path(path + ".part").write_bytes(b"partial resume")
        return False, "failed"

    downloader = type("Downloader", (), {"download_file": AsyncMock(side_effect=partial_download)})()
    service = PreviewAssetService(metadata_manager=StubMetadataManager(),
        downloader_factory=AsyncMock(return_value=downloader), exif_utils=RecordingExifUtils())
    payload = {}
    await service.ensure_preview_for_metadata(str(metadata), payload,
        [{"url": "https://example.test/image.mp4", "type": "video"}])
    assert not destination.exists() and "preview_url" not in payload
    assert not list(tmp_path.glob(".lm-preview-*"))


@pytest.mark.asyncio
async def test_download_does_not_overwrite_a_preview_appearing_while_fetching(tmp_path):
    metadata = tmp_path / "model.metadata.json"
    metadata.write_bytes(b"{}")
    destination = tmp_path / "model.mp4"

    async def downloaded(url, path, **kwargs):
        Path(path).write_bytes(b"fetched video")
        destination.write_bytes(b"user preview")
        return True, path

    downloader = type("Downloader", (), {"download_file": AsyncMock(side_effect=downloaded)})()
    service = PreviewAssetService(metadata_manager=StubMetadataManager(),
        downloader_factory=AsyncMock(return_value=downloader), exif_utils=RecordingExifUtils())
    payload = {}
    await service.ensure_preview_for_metadata(str(metadata), payload,
        [{"url": "https://example.test/image.mp4", "type": "video"}])
    assert destination.read_bytes() == b"user preview"
    assert payload["preview_url"] == str(destination).replace("\\", "/")
    assert not list(tmp_path.glob(".lm-preview-*"))


def replacement_fixture(tmp_path):
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"model weights")
    previous = tmp_path / "model.webp"
    previous.write_bytes(b"old preview")
    metadata = tmp_path / "model.metadata.json"
    payload = {"file_path": str(model), "preview_url": str(previous), "preview_nsfw_level": 2,
        "model_name": "maintained name", "favorite": True, "notes": "private preserved", "custom": {"nested": [1]}}
    original = json.dumps(payload, indent=2).encode()
    metadata.write_bytes(original)

    async def save(path, value):
        metadata.write_text(json.dumps(value), encoding="utf-8")
        return True

    manager = type("Manager", (), {"save_metadata": AsyncMock(side_effect=save)})()
    service = PreviewAssetService(metadata_manager=manager,
        downloader_factory=AsyncMock(), exif_utils=RecordingExifUtils())
    loader = AsyncMock(side_effect=lambda _: json.loads(metadata.read_text(encoding="utf-8")))
    return service, manager, loader, model, previous, metadata, original


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["write", "metadata", "cache"])
async def test_replace_failure_restores_existing_preview_and_sidecar(tmp_path, monkeypatch, failure):
    service, manager, loader, model, previous, metadata, original = replacement_fixture(tmp_path)
    new_preview = encoded_image_bytes()
    calls = []

    async def cache(path, preview, level):
        calls.append((path, preview, level))
        return not (failure == "cache" and len(calls) == 1)

    if failure == "metadata":
        manager.save_metadata = AsyncMock(return_value=False)
    if failure == "write":
        atomic_replace = preview_asset_service.os.replace

        def fail_preview_write(source, destination):
            if str(destination).endswith("model.webp"):
                raise OSError("preview write denied")
            return atomic_replace(source, destination)

        monkeypatch.setattr(preview_asset_service.os, "replace", fail_preview_write)
    with pytest.raises((RuntimeError, OSError)):
        await service.replace_preview(model_path=str(model), preview_data=new_preview, content_type="image/png",
            original_filename="new.png", nsfw_level=4, update_preview_in_cache=cache, metadata_loader=loader)
    assert previous.read_bytes() == b"old preview"
    assert metadata.read_bytes() == original
    assert model.read_bytes() == b"model weights"
    assert not list(tmp_path.glob(".lm-preview-*"))
    if failure == "cache":
        assert calls[-1] == (str(model), str(previous), 2), "Restore the original cache pointer and level"
    else:
        assert calls == []


@pytest.mark.asyncio
async def test_success_deletes_old_variants_only_after_metadata_and_cache_confirm(tmp_path):
    service, manager, loader, model, previous, metadata, original = replacement_fixture(tmp_path)
    new_preview = encoded_image_bytes()
    alternate = tmp_path / "model.png"
    alternate.write_bytes(b"old alternate")

    async def cache(path, preview, level):
        assert alternate.read_bytes() == b"old alternate", "Old variants still exist until the cache commits"
        assert Path(preview).read_bytes() == new_preview
        assert json.loads(metadata.read_bytes())["preview_url"] == preview
        return True

    result = await service.replace_preview(model_path=str(model), preview_data=new_preview, content_type="image/png",
        original_filename="new.png", nsfw_level=4, update_preview_in_cache=cache, metadata_loader=loader)
    assert result["preview_nsfw_level"] == 4 and previous.read_bytes() == new_preview
    assert not alternate.exists() and not list(tmp_path.glob(".lm-preview-*"))
    saved = json.loads(metadata.read_bytes())
    for key in ("model_name", "favorite", "notes", "custom"):
        assert saved[key] == json.loads(original)[key]
    assert model.read_bytes() == b"model weights"


@pytest.mark.asyncio
async def test_failed_rollback_retains_recovery_backup(tmp_path, monkeypatch):
    service, manager, loader, model, previous, metadata, original = replacement_fixture(tmp_path)
    manager.save_metadata = AsyncMock(return_value=False)
    restore = service._restore_file

    def failed_restore(path, backup):
        if path == str(previous).replace("\\", "/"):
            raise OSError("rollback denied")
        restore(path, backup)

    monkeypatch.setattr(service, "_restore_file", failed_restore)
    with pytest.raises(RuntimeError, match="recovery backup retained") as captured:
        await service.replace_preview(model_path=str(model), preview_data=encoded_image_bytes(), content_type="image/png",
            original_filename="new.png", nsfw_level=4, update_preview_in_cache=AsyncMock(return_value=True), metadata_loader=loader)
    backups = list(tmp_path.glob(".lm-preview-*.tmp"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"old preview"
    assert str(backups[0]) in str(captured.value)
    assert metadata.read_bytes() == original and model.read_bytes() == b"model weights"


@pytest.mark.asyncio
@pytest.mark.parametrize("data,content_type,filename", [
    (b"invalid image fixture", "image/png", "invalid.png"),
    (b"<html>upstream error</html>", "image/jpeg", "invalid.jpg"),
    (b"", "image/png", "empty.png"),
    (encoded_image_bytes()[:40], "image/png", "truncated.png"),
    (b"GIF89a truncated", "image/gif", "invalid.gif"),
])
async def test_real_exif_invalid_image_never_changes_existing_assets(tmp_path, data, content_type, filename):
    service, manager, loader, model, previous, metadata, original = replacement_fixture(tmp_path)
    service._exif_utils = ExifUtils
    cache = AsyncMock(return_value=True)

    with pytest.raises(ValueError, match="Invalid preview image"):
        await service.replace_preview(model_path=str(model), preview_data=data, content_type=content_type,
            original_filename=filename, nsfw_level=4, update_preview_in_cache=cache, metadata_loader=loader)

    manager.save_metadata.assert_not_awaited()
    loader.assert_not_awaited()
    cache.assert_not_awaited()
    assert previous.read_bytes() == b"old preview"
    assert metadata.read_bytes() == original and model.read_bytes() == b"model weights"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["model.metadata.json", "model.safetensors", "model.webp"]


@pytest.mark.asyncio
async def test_invalid_optimizer_output_never_changes_existing_assets(tmp_path):
    service, manager, loader, model, previous, metadata, original = replacement_fixture(tmp_path)
    service._exif_utils = type("InvalidOptimizer", (), {
        "optimize_image": staticmethod(lambda **kwargs: (b"invalid optimized image", ".webp"))})
    cache = AsyncMock(return_value=True)
    with pytest.raises(ValueError, match="Invalid preview image"):
        await service.replace_preview(model_path=str(model), preview_data=encoded_image_bytes(), content_type="image/png",
            original_filename="valid.png", nsfw_level=4, update_preview_in_cache=cache, metadata_loader=loader)
    manager.save_metadata.assert_not_awaited()
    cache.assert_not_awaited()
    assert previous.read_bytes() == b"old preview" and metadata.read_bytes() == original
    assert not list(tmp_path.glob(".lm-preview-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("rewritten", [False, True])
async def test_downloaded_html_is_rejected_without_changing_assets(tmp_path, rewritten):
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"model weights")
    metadata = tmp_path / "model.metadata.json"
    original = b'{"notes":"preserve private fields"}'
    metadata.write_bytes(original)
    previous = tmp_path / "model.gif"
    previous.write_bytes(b"previous image")
    invalid = b"<html>upstream error</html>"

    async def download_file(url, path, **kwargs):
        Path(path).write_bytes(invalid)
        return True, path

    downloader = type("Downloader", (), {
        "download_file": AsyncMock(side_effect=download_file),
        "download_to_memory": AsyncMock(return_value=(True, invalid, {}))})()
    service = PreviewAssetService(metadata_manager=StubMetadataManager(),
        downloader_factory=AsyncMock(return_value=downloader), exif_utils=ExifUtils)
    payload = {"file_path": str(model)}
    url = "https://image.civitai.com/container/example/original=true/sample.png" if rewritten else "https://example.test/sample.png"

    with pytest.raises(ValueError, match="Invalid preview image"):
        await service.ensure_preview_for_metadata(str(metadata), payload, [{"url": url, "type": "image"}])

    assert "preview_url" not in payload and "preview_nsfw_level" not in payload
    assert model.read_bytes() == b"model weights" and metadata.read_bytes() == original
    assert previous.read_bytes() == b"previous image"
    assert downloader.download_file.await_count == int(rewritten)
    downloader.download_to_memory.assert_awaited_once_with(url, use_auth=False)
    assert not list(tmp_path.glob(".lm-preview-*"))
    assert not (tmp_path / "model.png").exists() and not (tmp_path / "model.webp").exists()


@pytest.mark.asyncio
async def test_valid_animated_gif_preserves_frames_with_real_exif(tmp_path):
    service, manager, loader, model, previous, metadata, original = replacement_fixture(tmp_path)
    service._exif_utils = ExifUtils
    buffer = BytesIO()
    frames = [Image.new("RGB", (4, 4), color=color) for color in ("red", "blue")]
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    content = buffer.getvalue()
    result = await service.replace_preview(model_path=str(model), preview_data=content, content_type="image/gif",
        original_filename="valid.gif", nsfw_level=1, update_preview_in_cache=AsyncMock(return_value=True), metadata_loader=loader)
    assert Path(result["preview_path"]).read_bytes() == content
    with Image.open(result["preview_path"]) as saved:
        assert saved.n_frames == 2
    assert not previous.exists() and model.read_bytes() == b"model weights"
