from types import SimpleNamespace
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from py.services.connectivity_guard import OFFLINE_COOLDOWN_ERROR, OFFLINE_FRIENDLY_MESSAGE
from py.services.errors import RateLimitError
from py.services.metadata_sync_service import MetadataSyncService, _merge_ordered_unique


class DummySettings:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values = values or {}

    def get(self, key: str, default=None):
        return self._values.get(key, default)


def build_service(
    *,
    settings_values: dict[str, Any] | None = None,
    default_provider: SimpleNamespace | None = None,
    provider_selector: AsyncMock | None = None,
):
    metadata_manager = SimpleNamespace(
        save_metadata=AsyncMock(),
        hydrate_model_data=AsyncMock(side_effect=lambda payload: payload),
    )
    preview_service = SimpleNamespace(ensure_preview_for_metadata=AsyncMock())
    settings = DummySettings(settings_values)

    provider = default_provider or SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(),
        get_model_version_info=AsyncMock(return_value=(None, "No provider could retrieve the data")),
    )
    if default_provider is None:
        provider.get_model_by_hash.return_value = (None, None)

    default_provider_factory = AsyncMock(return_value=provider)
    provider_selector = provider_selector or AsyncMock(return_value=provider)

    service = MetadataSyncService(
        metadata_manager=metadata_manager,
        preview_service=preview_service,
        settings=settings,  # pyright: ignore[reportArgumentType]
        default_metadata_provider_factory=default_provider_factory,
        metadata_provider_selector=provider_selector,
    )

    return SimpleNamespace(
        service=service,
        metadata_manager=metadata_manager,
        preview_service=preview_service,
        default_provider=provider,
        default_provider_factory=default_provider_factory,
        provider_selector=provider_selector,
    )


def preview_model(tmp_path, *, images=None, preview_url=""):
    model_path = tmp_path / "规范 LoRA 名称.safetensors"
    model_path.write_bytes(b"isolated placeholder")
    return {
        "file_path": str(model_path).replace("\\", "/"), "model_name": "【Anima｜画风】规范名称",
        "sha256": "a" * 64, "preview_url": preview_url,
        "base_model": "Anima", "favorite": True, "notes": "private notes preserved",
        "tags": ["maintained-tag"], "custom": {"nested": ["preserve"]},
        "civitai": {"id": 123, "trainedWords": ["maintained trigger"], "images": images or []},
    }


def successful_preview_write(helpers, tmp_path):
    preview = tmp_path / "preview.png"

    async def write_preview(metadata_path, data, images):
        preview.write_bytes(b"isolated preview")
        data["preview_url"] = str(preview)
        data["preview_nsfw_level"] = 1

    helpers.preview_service.ensure_preview_for_metadata.side_effect = write_preview
    helpers.metadata_manager.save_metadata.return_value = True
    return preview


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_preview", [False, True])
async def test_fetch_missing_preview_uses_saved_candidates_and_preserves_metadata(tmp_path, stale_preview):
    helpers = build_service()
    images = [{"url": "https://example.test/saved.png", "nsfwLevel": 1}]
    model = preview_model(tmp_path, images=images, preview_url=str(tmp_path / "missing.png") if stale_preview else "")
    original = deepcopy(model)
    preview = successful_preview_write(helpers, tmp_path)
    update_cache = AsyncMock(return_value=True)

    ok, error = await helpers.service.fetch_missing_preview(
        sha256="", file_path=model["file_path"], model_data=model, update_cache_func=update_cache
    )

    assert ok is True and error is None
    assert model == {**original, "preview_url": str(preview), "preview_nsfw_level": 1}
    helpers.default_provider_factory.assert_not_awaited()
    helpers.preview_service.ensure_preview_for_metadata.assert_awaited_once()
    assert helpers.preview_service.ensure_preview_for_metadata.await_args.args[2] == images
    saved = helpers.metadata_manager.save_metadata.await_args.args[1]
    assert saved == model
    update_cache.assert_awaited_once_with(model["file_path"], model["file_path"], saved)


@pytest.mark.asyncio
async def test_fetch_missing_preview_hash_fallback_only_uses_remote_images(tmp_path):
    helpers = build_service()
    model = preview_model(tmp_path)
    model["civitai"].pop("id")
    original = deepcopy(model)
    remote = {"id": 999, "model": {"name": "Remote name"}, "baseModel": "Other", "trainedWords": ["remote trigger"], "tags": ["remote tag"], "images": [{"url": "https://example.test/remote.png", "nsfwLevel": 1}]}
    helpers.default_provider.get_model_by_hash.return_value = (remote, None)
    preview = successful_preview_write(helpers, tmp_path)

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model, update_cache_func=AsyncMock(return_value=True)
    )

    assert ok is True and error is None
    helpers.default_provider.get_model_by_hash.assert_awaited_once_with("a" * 64)
    assert helpers.preview_service.ensure_preview_for_metadata.await_args.args[2] == remote["images"]
    assert model == {**original, "preview_url": str(preview), "preview_nsfw_level": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("sha256", ["a" * 64, "A" * 64, ""])
async def test_fetch_missing_preview_queries_exact_linked_version_and_preserves_fields(tmp_path, sha256):
    helpers = build_service()
    model = preview_model(tmp_path)
    model["civitai"]["modelId"] = 456
    original = deepcopy(model)
    remote = {
        "id": 123, "modelId": 456, "name": "Remote version name",
        "model": {"name": "Remote model name"}, "trainedWords": ["remote trigger"],
        "images": [{"url": "https://example.test/linked.png", "nsfwLevel": 1}],
        "files": [{"hashes": {"SHA256": "a" * 64}}],
    }
    helpers.default_provider.get_model_version_info.return_value = (remote, None)
    preview = successful_preview_write(helpers, tmp_path)

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=sha256, file_path=model["file_path"], model_data=model,
        update_cache_func=AsyncMock(return_value=True),
    )

    assert ok is True and error is None
    helpers.default_provider.get_model_version_info.assert_awaited_once_with("123")
    helpers.default_provider.get_model_by_hash.assert_not_awaited()
    assert helpers.preview_service.ensure_preview_for_metadata.await_args.args[2] == remote["images"]
    assert model == {**original, "preview_url": str(preview), "preview_nsfw_level": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected", [
    ({"id": 999}, "Preview metadata does not match the linked version"),
    ({"modelId": 999}, "Preview metadata does not match the linked model"),
    ({"files": [{"hashes": {"SHA256": "b" * 64}}]}, "Linked version has no file matching this model's SHA256"),
    ({"files": None}, "Linked version has no file matching this model's SHA256"),
    ({"files": 1}, "Linked version has no file matching this model's SHA256"),
    ({"images": []}, "No preview images available"),
])
async def test_fetch_missing_preview_rejects_wrong_linked_identity_without_writes(tmp_path, change, expected):
    helpers = build_service()
    model = preview_model(tmp_path)
    model["civitai"]["modelId"] = 456
    original = deepcopy(model)
    remote = {
        "id": 123, "modelId": 456,
        "images": [{"url": "https://example.test/wrong.png"}],
        "files": [{"hashes": {"SHA256": "a" * 64}}], **change,
    }
    helpers.default_provider.get_model_version_info.return_value = (remote, None)
    update_cache = AsyncMock()

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model,
        update_cache_func=update_cache,
    )

    assert ok is False and error == expected
    assert model == original
    helpers.default_provider.get_model_by_hash.assert_not_awaited()
    helpers.preview_service.ensure_preview_for_metadata.assert_not_awaited()
    helpers.metadata_manager.save_metadata.assert_not_awaited()
    update_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_missing_preview_checks_saved_hash_when_caller_hash_is_empty(tmp_path):
    helpers = build_service()
    model = preview_model(tmp_path)
    helpers.default_provider.get_model_version_info.return_value = ({
        "id": 123, "images": [{"url": "https://example.test/wrong.png"}],
        "files": [{"hashes": {"SHA256": "b" * 64}}],
    }, None)

    ok, error = await helpers.service.fetch_missing_preview(
        sha256="", file_path=model["file_path"], model_data=model, update_cache_func=AsyncMock(),
    )

    assert ok is False and error == "Linked version has no file matching this model's SHA256"
    helpers.preview_service.ensure_preview_for_metadata.assert_not_awaited()
    helpers.metadata_manager.save_metadata.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_error", ["Rate limited", OFFLINE_FRIENDLY_MESSAGE, "HTTP 401: authentication required"])
async def test_fetch_missing_preview_keeps_linked_provider_error_without_hash_retry(tmp_path, provider_error):
    helpers = build_service()
    model = preview_model(tmp_path)
    helpers.default_provider.get_model_version_info.return_value = (None, provider_error)

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model,
        update_cache_func=AsyncMock(),
    )

    assert ok is False and error == provider_error
    helpers.default_provider.get_model_by_hash.assert_not_awaited()
    helpers.metadata_manager.save_metadata.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("version_id", [True, "bad", -1, "1.0"])
async def test_fetch_missing_preview_rejects_invalid_linked_version_before_network(tmp_path, version_id):
    helpers = build_service()
    model = preview_model(tmp_path)
    model["civitai"]["id"] = version_id

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model,
        update_cache_func=AsyncMock(),
    )

    assert ok is False and error == "Invalid linked model version ID"
    helpers.default_provider_factory.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_ok", [True, False])
async def test_fetch_missing_preview_keeps_existing_local_image(tmp_path, cache_ok):
    helpers = build_service()
    preview = tmp_path / "existing.png"
    preview.write_bytes(b"existing")
    model = preview_model(tmp_path, preview_url=str(preview))
    original = deepcopy(model)
    update_cache = AsyncMock(return_value=cache_ok)

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model, update_cache_func=update_cache
    )

    assert ok is cache_ok
    assert error == (None if cache_ok else "Failed to update model cache for existing preview")
    assert model == original and preview.read_bytes() == b"existing"
    helpers.default_provider_factory.assert_not_awaited()
    helpers.preview_service.ensure_preview_for_metadata.assert_not_awaited()
    helpers.metadata_manager.save_metadata.assert_not_awaited()
    update_cache.assert_awaited_once_with(model["file_path"], model["file_path"], original)


@pytest.mark.asyncio
@pytest.mark.parametrize("sha256", ["", "partial-hash", "g" * 64])
async def test_fetch_missing_preview_rejects_incomplete_hash_without_candidates(tmp_path, sha256):
    helpers = build_service()
    model = preview_model(tmp_path)
    model["civitai"].pop("id")
    model["sha256"] = sha256

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=sha256, file_path=model["file_path"], model_data=model, update_cache_func=AsyncMock(return_value=True)
    )

    assert ok is False and "complete SHA256" in error
    helpers.default_provider_factory.assert_not_awaited()
    helpers.metadata_manager.save_metadata.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("remote,error_message,expected", [
    (None, "Model not found", "Model not found"),
    ({"id": 1, "images": []}, None, "No preview images available"),
])
async def test_fetch_missing_preview_reports_missing_remote_images(tmp_path, remote, error_message, expected):
    helpers = build_service()
    helpers.default_provider.get_model_by_hash.return_value = (remote, error_message)
    model = preview_model(tmp_path)
    model["civitai"].pop("id")

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model, update_cache_func=AsyncMock(return_value=True)
    )

    assert ok is False and error == expected
    helpers.preview_service.ensure_preview_for_metadata.assert_not_awaited()
    helpers.metadata_manager.save_metadata.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("set_missing_url", [False, True])
async def test_fetch_missing_preview_requires_file_to_land(tmp_path, set_missing_url):
    helpers = build_service()
    model = preview_model(tmp_path, images=[{"url": "https://example.test/preview.png"}])
    original = deepcopy(model)
    if set_missing_url:
        helpers.preview_service.ensure_preview_for_metadata.side_effect = lambda path, data, images: data.update(preview_url=str(tmp_path / "never-created.png"))
    update_cache = AsyncMock(return_value=True)

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model, update_cache_func=update_cache
    )

    assert ok is False and error == "Preview download did not create a local file"
    assert model == original
    helpers.metadata_manager.save_metadata.assert_not_awaited()
    update_cache.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("save_ok,cache_ok,expected", [
    (False, True, "Failed to save preview metadata"),
    (True, False, "Preview saved but model cache update failed"),
])
async def test_fetch_missing_preview_reports_save_and_cache_failures(tmp_path, save_ok, cache_ok, expected):
    helpers = build_service()
    model = preview_model(tmp_path, images=[{"url": "https://example.test/preview.png"}])
    original = deepcopy(model)
    successful_preview_write(helpers, tmp_path)
    helpers.metadata_manager.save_metadata.return_value = save_ok
    update_cache = AsyncMock(return_value=cache_ok)

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model, update_cache_func=update_cache
    )

    assert ok is False and error == expected
    assert model == original
    if save_ok:
        update_cache.assert_awaited_once()
    else:
        update_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_missing_preview_recovers_cache_failure_without_redownload(tmp_path):
    helpers = build_service()
    model = preview_model(tmp_path, images=[{"url": "https://example.test/preview.png"}])
    original = deepcopy(model)
    preview = successful_preview_write(helpers, tmp_path)
    update_cache = AsyncMock(side_effect=[False, True])

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model, update_cache_func=update_cache
    )

    assert ok is False and error == "Preview saved but model cache update failed"
    assert model == original
    sidecar_model = deepcopy(helpers.metadata_manager.save_metadata.await_args.args[1])
    assert sidecar_model["preview_url"] == str(preview)

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=sidecar_model["sha256"], file_path=sidecar_model["file_path"], model_data=sidecar_model, update_cache_func=update_cache
    )

    assert ok is True and error is None
    assert update_cache.await_count == 2
    helpers.preview_service.ensure_preview_for_metadata.assert_awaited_once()
    helpers.metadata_manager.save_metadata.assert_awaited_once()
    helpers.default_provider_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_missing_preview_uses_existing_selection_and_anonymous_download_contract(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from py.services import preview_asset_service
    from py.services.preview_asset_service import PreviewAssetService
    from py.utils.exif_utils import ExifUtils
    from py.utils.metadata_manager import MetadataManager

    helpers = build_service()
    images = [
        {"url": "https://example.test/mature.png", "nsfwLevel": 16, "type": "image"},
        {"url": "https://example.test/safe.png", "nsfwLevel": 1, "type": "image"},
    ]
    model = preview_model(tmp_path, images=images)
    original = deepcopy(model)
    image_buffer = io.BytesIO()
    Image.new("RGB", (80, 48), (20, 40, 60)).save(image_buffer, format="PNG")
    downloader = SimpleNamespace(download_to_memory=AsyncMock(return_value=(True, image_buffer.getvalue(), {})))
    helpers.service._metadata_manager = MetadataManager
    helpers.service._preview_service = PreviewAssetService(
        metadata_manager=MetadataManager, downloader_factory=AsyncMock(return_value=downloader), exif_utils=ExifUtils
    )
    monkeypatch.setattr(preview_asset_service, "get_settings_manager", lambda: DummySettings({"blur_mature_content": True, "mature_blur_level": "R"}))

    ok, error = await helpers.service.fetch_missing_preview(
        sha256=model["sha256"], file_path=model["file_path"], model_data=model, update_cache_func=AsyncMock(return_value=True)
    )

    assert ok is True and error is None
    downloader.download_to_memory.assert_awaited_once_with("https://example.test/safe.png", use_auth=False)
    preview = Path(model["preview_url"])
    with Image.open(preview) as image:
        image.load()
        assert image.format == "WEBP"
    assert model["preview_nsfw_level"] == 1
    saved = json.loads(Path(model["file_path"]).with_suffix(".metadata.json").read_text(encoding="utf-8"))
    for key in original:
        if key != "preview_url":
            assert saved[key] == original[key]
    helpers.default_provider_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_model_metadata_merges_and_persists():
    helpers = build_service()

    local = {
        "civitai": {"trainedWords": ["alpha"], "creator": {"id": 1}},
        "modelDescription": "",
        "tags": [],
        "model_name": "Local",
    }
    remote = {
        "source": "api",
        "trainedWords": ["beta"],
        "model": {
            "name": "Remote Model",
            "description": "desc",
            "tags": ["style"],
            "creator": {"id": 2},
            "allowNoCredit": False,
            "allowCommercialUse": ["Image"],
            "allowDerivatives": False,
            "allowDifferentLicense": True,
        },
        "baseModel": "sdxl",
        "images": ["img"],
    }

    result = await helpers.service.update_model_metadata(
        "path/to/model.metadata.json",
        local,
        remote,
        helpers.default_provider,
    )

    assert set(result["civitai"]["trainedWords"]) == {"alpha", "beta"}
    assert result["model_name"] == "Remote Model"
    assert result["modelDescription"] == "desc"
    assert result["tags"] == ["style"]
    assert result["base_model"] == "SDXL 1.0"
    civitai_model = result["civitai"]["model"]
    assert civitai_model["allowNoCredit"] is False
    assert civitai_model["allowCommercialUse"] == ["Image"]
    assert civitai_model["allowDerivatives"] is False
    assert civitai_model["allowDifferentLicense"] is True
    for key in ("allowNoCredit", "allowCommercialUse", "allowDerivatives", "allowDifferentLicense"):
        assert key not in result

    helpers.preview_service.ensure_preview_for_metadata.assert_awaited_once()
    helpers.metadata_manager.save_metadata.assert_awaited_once_with(
        "path/to/model.metadata.json",
        result,
    )


def test_merge_ordered_unique_keeps_first_seen_order():
    assert _merge_ordered_unique(["b", "a"], ["a", "c", "b", "d"]) == [
        "b",
        "a",
        "c",
        "d",
    ]
    assert _merge_ordered_unique([], ["x"]) == ["x"]
    assert _merge_ordered_unique(["x"], []) == ["x"]


@pytest.mark.asyncio
async def test_update_model_metadata_preserves_trained_word_order():
    """Trigger word order (prompt order) must survive a metadata refresh."""

    helpers = build_service()

    local = {
        "civitai": {"trainedWords": ["zeta style", "alpha", "beta"]},
        "model_name": "Local",
    }
    remote = {
        "source": "api",
        "trainedWords": ["beta", "gamma", "alpha"],
        "model": {"name": "Remote Model"},
    }

    result = await helpers.service.update_model_metadata(
        "path/to/model.metadata.json",
        local,
        remote,
        helpers.default_provider,
    )

    # Saved order first, newly discovered words appended, duplicates dropped
    assert result["civitai"]["trainedWords"] == [
        "zeta style",
        "alpha",
        "beta",
        "gamma",
    ]


@pytest.mark.asyncio
async def test_update_model_metadata_propagates_civitai_autov3():
    helpers = build_service()

    local = {
        "sha256": "111aabbf94dd9e59c05d842fccf57bec915b2a3c237f6b54f8d614e40858d717",
        "autov3": "",
        "model_name": "Local",
    }
    remote = {
        "source": "api",
        "model": {"name": "Remote Model", "description": "", "tags": []},
        "images": [],
        "files": [
            {
                "name": "other.safetensors",
                "hashes": {"SHA256": "ZZZ999"},
            },
            {
                "name": "model.safetensors",
                "hashes": {
                    "SHA256": "111aabbf94dd9e59c05d842fccf57bec915b2a3c237f6b54f8d614e40858d717",
                    "AutoV3": "8A582E901D7F",
                },
            },
        ],
    }

    result = await helpers.service.update_model_metadata(
        "path/to/model.metadata.json",
        local,
        remote,
        helpers.default_provider,
    )

    # Civitai-first: the '' (checked-unavailable) state is upgraded in-session
    # by the freshly fetched metadata, without any header re-read.
    assert result["autov3"] == "8a582e901d7f"


@pytest.mark.asyncio
async def test_update_model_metadata_keeps_autov3_without_matching_file():
    helpers = build_service()

    local = {"sha256": "abc123", "autov3": "", "model_name": "Local"}
    remote = {
        "source": "api",
        "model": {"name": "Remote Model", "description": "", "tags": []},
        "images": [],
        "files": [{"name": "other.safetensors", "hashes": {"SHA256": "ZZZ999", "AutoV3": "ABCDEF123456"}}],
    }

    result = await helpers.service.update_model_metadata(
        "path/to/model.metadata.json",
        local,
        remote,
        helpers.default_provider,
    )

    assert result["autov3"] == ""


@pytest.mark.asyncio
async def test_fetch_and_update_model_success_updates_cache(tmp_path):
    helpers = build_service()

    civitai_payload = {
        "source": "api",
        "model": {"name": "Remote", "description": "", "tags": ["tag"]},
        "images": [],
        "baseModel": "sdxl",
    }
    helpers.default_provider.get_model_by_hash.return_value = (civitai_payload, None)

    model_path = tmp_path / "model.safetensors"

    async def hydrate(payload: Dict[str, Any]) -> Dict[str, Any]:
        payload["hydrated"] = True
        return payload

    helpers.metadata_manager.hydrate_model_data.side_effect = hydrate

    model_data: Dict[str, Any] = {
        "model_name": "Local",
        "folder": "root",
        "file_path": str(model_path),
    }
    update_cache = AsyncMock(return_value=True)

    await hydrate(model_data)
    helpers.metadata_manager.hydrate_model_data.reset_mock()

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="abc",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=update_cache,
    )

    assert ok and error is None
    assert model_data["from_civitai"] is True
    assert model_data["civitai_deleted"] is False
    assert "civitai" in model_data
    assert model_data["metadata_source"] == "civitai_api"
    civitai_model = model_data["civitai"]["model"]
    assert civitai_model["allowNoCredit"] is True
    assert civitai_model["allowDerivatives"] is True
    assert civitai_model["allowDifferentLicense"] is True
    assert civitai_model["allowCommercialUse"] == ["Sell"]
    for key in ("allowNoCredit", "allowCommercialUse", "allowDerivatives", "allowDifferentLicense"):
        assert key not in model_data

    helpers.metadata_manager.hydrate_model_data.assert_not_awaited()
    assert model_data["hydrated"] is True

    metadata_path = str(model_path.with_suffix(".metadata.json"))
    await_args = helpers.metadata_manager.save_metadata.await_args_list
    assert await_args, "expected metadata to be persisted"
    last_call = await_args[-1]
    assert last_call.args[0] == metadata_path
    persisted_payload = last_call.args[1]
    assert persisted_payload["hydrated"] is True
    civitai_model = persisted_payload["civitai"]["model"]
    assert civitai_model["allowNoCredit"] is True
    assert civitai_model["allowCommercialUse"] == ["Sell"]
    for key in ("allowNoCredit", "allowCommercialUse", "allowDerivatives", "allowDifferentLicense"):
        assert key not in persisted_payload
    update_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_and_update_model_keeps_deleted_flag_false_for_archive_source(tmp_path):
    helpers = build_service()

    civitai_payload = {
        "source": "archive_db",
        "model": {"name": "Recovered", "description": "", "tags": ["tag"]},
        "images": [],
        "baseModel": "sd15",
    }
    helpers.default_provider.get_model_by_hash.return_value = (civitai_payload, None)

    model_path = tmp_path / "model.safetensors"
    model_data = {
        "model_name": "Local",
        "folder": "root",
        "file_path": str(model_path),
    }
    update_cache = AsyncMock(return_value=True)

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="abc",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=update_cache,
    )

    assert ok and error is None
    assert model_data["metadata_source"] == "archive_db"
    assert model_data["civitai_deleted"] is False
    update_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_and_update_model_handles_missing_remote_metadata(tmp_path):
    helpers = build_service()
    helpers.default_provider.get_model_by_hash.return_value = (None, "Model not found")

    model_path = tmp_path / "model.safetensors"

    async def hydrate(payload: Dict[str, Any]) -> Dict[str, Any]:
        payload["hydrated"] = True
        return payload

    helpers.metadata_manager.hydrate_model_data.side_effect = hydrate

    model_data: Dict[str, Any] = {
        "model_name": "Local",
        "folder": "root",
        "file_path": str(model_path),
    }

    await hydrate(model_data)
    helpers.metadata_manager.hydrate_model_data.reset_mock()

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="missing",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=AsyncMock(),
    )

    assert not ok
    assert "Model not found" in error


@pytest.mark.asyncio
async def test_fetch_and_update_model_returns_friendly_offline_message(tmp_path):
    helpers = build_service()
    helpers.default_provider.get_model_by_hash.return_value = (None, OFFLINE_COOLDOWN_ERROR)

    model_path = tmp_path / "model.safetensors"
    model_data = {
        "model_name": "Local",
        "folder": "root",
        "file_path": str(model_path),
    }
    update_cache = AsyncMock(return_value=True)

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="abc",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=update_cache,
    )

    assert ok is False
    assert error is not None
    assert OFFLINE_FRIENDLY_MESSAGE in error
    update_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_and_update_model_respects_deleted_without_archive():
    helpers = build_service(settings_values={"enable_metadata_archive_db": False})

    model_data = {
        "civitai_deleted": True,
        "file_path": "/tmp/model.safetensors",
    }
    update_cache = AsyncMock()

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="abc",
        file_path="/tmp/model.safetensors",
        model_data=model_data,
        update_cache_func=update_cache,
    )

    assert not ok
    assert "metadata archive DB is not enabled" in error
    helpers.default_provider_factory.assert_not_awaited()
    helpers.metadata_manager.hydrate_model_data.assert_not_awaited()
    # Now update_cache_func IS called to persist the not-found flags to SQLite
    update_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_and_update_model_prefers_civarchive_for_deleted_models(tmp_path):
    default_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(),
    )
    civarchive_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(
            return_value=(
                {
                    "source": "civarchive",
                    "model": {"name": "Recovered", "description": "", "tags": []},
                    "images": [],
                    "baseModel": "sdxl",
                },
                None,
            )
        ),
        get_model_version=AsyncMock(),
    )

    async def select_provider(name: str):
        return civarchive_provider if name == "civarchive_api" else default_provider

    provider_selector = AsyncMock(side_effect=select_provider)
    helpers = build_service(
        settings_values={"enable_metadata_archive_db": False},
        default_provider=default_provider,
        provider_selector=provider_selector,
    )

    model_path = tmp_path / "model.safetensors"
    model_data = {
        "civitai_deleted": True,
        "metadata_source": "civarchive",
        "civitai": {"source": "civarchive"},
        "file_path": str(model_path),
    }
    update_cache = AsyncMock()

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="deadbeef",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=update_cache,
    )

    assert ok
    assert error is None
    provider_selector.assert_awaited_with("civarchive_api")
    helpers.default_provider_factory.assert_not_awaited()
    civarchive_provider.get_model_by_hash.assert_awaited_once_with("deadbeef")
    update_cache.assert_awaited()
    assert model_data["metadata_source"] == "civarchive"
    assert model_data["civitai_deleted"] is True
    helpers.metadata_manager.save_metadata.assert_awaited()


@pytest.mark.asyncio
async def test_fetch_and_update_model_falls_back_to_sqlite_after_civarchive_failure(tmp_path):
    default_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(),
    )
    civarchive_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(return_value=(None, "Model not found")),
        get_model_version=AsyncMock(),
    )
    sqlite_payload = {
        "source": "archive_db",
        "model": {"name": "Recovered", "description": "", "tags": []},
        "images": [],
        "baseModel": "sdxl",
    }
    sqlite_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(return_value=(sqlite_payload, None)),
        get_model_version=AsyncMock(),
    )

    async def select_provider(name: str):
        if name == "civarchive_api":
            return civarchive_provider
        if name == "sqlite":
            return sqlite_provider
        return default_provider

    provider_selector = AsyncMock(side_effect=select_provider)
    helpers = build_service(
        settings_values={"enable_metadata_archive_db": True},
        default_provider=default_provider,
        provider_selector=provider_selector,
    )

    model_path = tmp_path / "model.safetensors"
    model_data = {
        "civitai_deleted": True,
        "db_checked": False,
        "file_path": str(model_path),
    }
    update_cache = AsyncMock()

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="cafe",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=update_cache,
    )

    assert ok and error is None
    assert civarchive_provider.get_model_by_hash.await_count == 1
    assert sqlite_provider.get_model_by_hash.await_count == 1
    assert model_data["metadata_source"] == "archive_db"
    assert model_data["db_checked"] is True
    assert model_data["civitai_deleted"] is True
    assert provider_selector.await_args_list[0].args == ("civarchive_api",)
    assert provider_selector.await_args_list[1].args == ("sqlite",)
    update_cache.assert_awaited()
    helpers.metadata_manager.save_metadata.assert_awaited()


@pytest.mark.asyncio
async def test_fetch_and_update_model_returns_rate_limit_error(tmp_path):
    rate_error = RateLimitError("limited", retry_after=7)
    default_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(side_effect=rate_error),
        get_model_version=AsyncMock(),
    )
    helpers = build_service(default_provider=default_provider)

    model_path = tmp_path / "model.safetensors"
    model_data = {
        "file_path": str(model_path),
        "model_name": "Local",
    }
    update_cache = AsyncMock()

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="deadbeef",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=update_cache,
    )

    assert ok is False
    assert error is not None and "Rate limited" in error
    helpers.metadata_manager.save_metadata.assert_not_awaited()
    update_cache.assert_not_awaited()
    helpers.provider_selector.assert_not_awaited()


@pytest.mark.asyncio
async def test_relink_metadata_fetches_version_without_overwriting_sha(tmp_path):
    provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(
            return_value={
                "files": [
                    {
                        "primary": True,
                        "type": "Model",
                        "hashes": {"SHA256": "ABCDEF"},
                    }
                ],
                "model": {"name": "Remote"},
                "images": [],
            }
        ),
    )

    helpers = build_service(default_provider=provider)

    metadata = {"model_name": "Local", "sha256": "original"}
    result = await helpers.service.relink_metadata(
        file_path=str(tmp_path / "model.safetensors"),
        metadata=metadata,
        model_id=1,
        model_version_id=2,
    )

    assert result["model_name"] == "Remote"
    assert result["sha256"] == "original"
    helpers.metadata_manager.save_metadata.assert_awaited_once()


@pytest.mark.asyncio
async def test_relink_metadata_raises_when_version_missing():
    provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(return_value=None),
    )

    helpers = build_service(default_provider=provider)

    with pytest.raises(ValueError):
        await helpers.service.relink_metadata(
            file_path="/tmp/model.safetensors",
            metadata={},
            model_id=9,
            model_version_id=None,
        )


@pytest.mark.asyncio
async def test_relink_metadata_uses_named_civarchive_provider(tmp_path):
    default_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(),
    )
    civarchive_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(
            return_value={
                "files": [
                    {
                        "primary": True,
                        "type": "Model",
                        "hashes": {"SHA256": "ABCDEF"},
                    }
                ],
                "model": {"name": "Archived"},
                "images": [],
            }
        ),
    )

    async def select_provider(name: str):
        return civarchive_provider if name == "civarchive_api" else default_provider

    provider_selector = AsyncMock(side_effect=select_provider)
    helpers = build_service(
        default_provider=default_provider,
        provider_selector=provider_selector,
    )

    metadata = {"model_name": "Local", "sha256": "original"}
    result = await helpers.service.relink_metadata(
        file_path=str(tmp_path / "model.safetensors"),
        metadata=metadata,
        model_id=1,
        model_version_id=2,
        provider_name="civarchive_api",
    )

    assert result["model_name"] == "Archived"
    assert result["sha256"] == "original"
    provider_selector.assert_awaited_with("civarchive_api")
    civarchive_provider.get_model_version.assert_awaited_once_with(1, 2)
    helpers.default_provider_factory.assert_not_awaited()
    helpers.metadata_manager.save_metadata.assert_awaited_once()


@pytest.mark.asyncio
async def test_relink_metadata_raises_when_version_missing_with_civarchive():
    default_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(),
    )
    civarchive_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(return_value=None),
    )

    async def select_provider(name: str):
        return civarchive_provider if name == "civarchive_api" else default_provider

    provider_selector = AsyncMock(side_effect=select_provider)
    helpers = build_service(
        default_provider=default_provider,
        provider_selector=provider_selector,
    )

    with pytest.raises(ValueError, match="CivitArchive"):
        await helpers.service.relink_metadata(
            file_path="/tmp/model.safetensors",
            metadata={},
            model_id=9,
            model_version_id=None,
            provider_name="civarchive_api",
        )


@pytest.mark.asyncio
async def test_relink_metadata_raises_friendly_error_when_provider_unavailable():
    provider_selector = AsyncMock(
        side_effect=ValueError("Provider 'civarchive_api' is not registered")
    )
    helpers = build_service(provider_selector=provider_selector)

    with pytest.raises(ValueError, match="CivitArchive is not available or not enabled"):
        await helpers.service.relink_metadata(
            file_path="/tmp/model.safetensors",
            metadata={},
            model_id=9,
            model_version_id=None,
            provider_name="civarchive_api",
        )


@pytest.mark.asyncio
async def test_relink_metadata_default_call_uses_default_provider_factory(tmp_path):
    helpers = build_service()
    helpers.default_provider.get_model_version.return_value = {
        "files": [
            {
                "primary": True,
                "type": "Model",
                "hashes": {"SHA256": "ABCDEF"},
            }
        ],
        "model": {"name": "Remote"},
        "images": [],
    }

    result = await helpers.service.relink_metadata(
        file_path=str(tmp_path / "model.safetensors"),
        metadata={"model_name": "Local", "sha256": "original"},
        model_id=1,
        model_version_id=None,
    )

    assert result["model_name"] == "Remote"
    assert result["sha256"] == "original"
    helpers.default_provider_factory.assert_awaited_once()
    helpers.provider_selector.assert_not_awaited()
    helpers.metadata_manager.save_metadata.assert_awaited_once()

@pytest.mark.asyncio
async def test_fetch_and_update_model_persists_db_checked_when_sqlite_fails(tmp_path):
    """
    Regression test: When a deleted model is checked against sqlite and not found,
    db_checked=True must be persisted to disk so the model is skipped in future refreshes.

    Previously, db_checked was set in memory but never saved because the save_metadata
    call was inside the `if civitai_api_not_found:` block, which is False for deleted
    models (since the default CivitAI API is never tried).
    """
    default_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(),
        get_model_version=AsyncMock(),
    )
    civarchive_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(return_value=(None, "Model not found")),
        get_model_version=AsyncMock(),
    )
    sqlite_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(return_value=(None, "Model not found")),
        get_model_version=AsyncMock(),
    )

    async def select_provider(name: str):
        if name == "civarchive_api":
            return civarchive_provider
        if name == "sqlite":
            return sqlite_provider
        return default_provider

    provider_selector = AsyncMock(side_effect=select_provider)
    helpers = build_service(
        settings_values={"enable_metadata_archive_db": True},
        default_provider=default_provider,
        provider_selector=provider_selector,
    )

    model_path = tmp_path / "model.safetensors"
    model_data = {
        "civitai_deleted": True,
        "db_checked": False,
        "from_civitai": False,
        "file_path": str(model_path),
        "model_name": "Deleted Model",
    }
    update_cache = AsyncMock()

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="deadbeef",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=update_cache,
    )

    # The call should fail because neither provider found metadata
    assert not ok
    assert error is not None
    assert "Model not found" in error or "not found in metadata archive DB" in error

    # Both providers should have been tried
    assert civarchive_provider.get_model_by_hash.await_count == 1
    assert sqlite_provider.get_model_by_hash.await_count == 1

    # db_checked should be True in memory
    assert model_data["db_checked"] is True

    # CRITICAL: metadata should have been saved to disk with db_checked=True
    helpers.metadata_manager.save_metadata.assert_awaited_once()
    saved_call = helpers.metadata_manager.save_metadata.await_args
    saved_data = saved_call.args[1]
    assert saved_data["db_checked"] is True
    assert "folder" not in saved_data  # folder should be stripped
    assert "last_checked_at" in saved_data  # timestamp should be set


@pytest.mark.asyncio
async def test_fetch_and_update_model_does_not_overwrite_api_metadata_with_archive(tmp_path):
    helpers = build_service()

    # Existing high-quality metadata
    existing_civitai = {
        "source": "api", # will be normalized to civitai_api in some paths, but let's use what is_civitai_api_metadata expects
        "files": [{"id": 1}],
        "images": [{"url": "img1"}],
        "name": "High Quality",
        "trainedWords": ["keyword1"]
    }

    # Incoming lower-quality metadata from CivArchive (simulating fallback)
    civarchive_payload = {
        "source": "civarchive",
        "model": {"name": "Low Quality", "description": "low quality", "tags": []},
        "images": [], # Missing images
        "baseModel": "sdxl",
        "trainedWords": ["keyword2"]
    }
    helpers.default_provider.get_model_by_hash.return_value = (civarchive_payload, None)

    model_path = tmp_path / "model.safetensors"
    model_data: Dict[str, Any] = {
        "model_name": "High Quality",
        "metadata_source": "civitai_api",
        "civitai": existing_civitai,
        "file_path": str(model_path),
    }
    update_cache = AsyncMock(return_value=True)

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="abc",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=update_cache,
    )

    assert ok and error is None
    # Ensure the civitai block still contains the high-quality data
    assert model_data["civitai"]["name"] == "High Quality"
    assert "keyword1" in model_data["civitai"]["trainedWords"]
    # Source might be updated in model_data root, but the block should be protected if logic works
    assert model_data["metadata_source"] == "civarchive" 
    
    # Check that trained words were merged if any (though in this case we might skip the whole update)
    # Actually, according to the new logic, the update is SKIPPED entirely for the civitai block
    assert model_data["civitai"]["trainedWords"] == ["keyword1"]
    
    helpers.metadata_manager.save_metadata.assert_awaited()
    update_cache.assert_awaited()


@pytest.mark.asyncio
async def test_fetch_and_update_model_keeps_sqlite_last_resort_after_civarchive_rate_limit(tmp_path):
    """A CivArchive 429 must not block the local sqlite last resort (#1085)."""
    civarchive_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(
            side_effect=RateLimitError("limited", retry_after=30)
        ),
        get_model_version=AsyncMock(),
    )
    sqlite_payload = {
        "source": "archive_db",
        "model": {"name": "Recovered", "description": "", "tags": []},
        "images": [],
        "baseModel": "sdxl",
    }
    sqlite_provider = SimpleNamespace(
        get_model_by_hash=AsyncMock(return_value=(sqlite_payload, None)),
        get_model_version=AsyncMock(),
    )

    async def select_provider(name: str):
        if name == "civarchive_api":
            return civarchive_provider
        if name == "sqlite":
            return sqlite_provider
        raise AssertionError(f"unexpected provider request: {name}")

    helpers = build_service(
        settings_values={"enable_metadata_archive_db": True},
        provider_selector=AsyncMock(side_effect=select_provider),
    )

    model_path = tmp_path / "model.safetensors"
    model_data = {
        "civitai_deleted": True,
        "db_checked": False,
        "file_path": str(model_path),
    }
    update_cache = AsyncMock()

    ok, error = await helpers.service.fetch_and_update_model(
        sha256="cafe",
        file_path=str(model_path),
        model_data=model_data,
        update_cache_func=update_cache,
    )

    assert ok and error is None
    civarchive_provider.get_model_by_hash.assert_awaited_once()
    sqlite_provider.get_model_by_hash.assert_awaited_once()
    assert model_data["metadata_source"] == "archive_db"
