"""Cross-version contracts for the unified workbench customizations."""
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from py.services.pending_delete_service import PendingDeleteService
from py.services.settings_manager import SettingsManager, RestoreCoordinationError
from py.utils.usage_stats import UsageStats


@pytest.mark.parametrize('operation', ['undo', 'purge', 'retry'])
async def test_shared_references_follow_permanent_delete_only(tmp_path, monkeypatch, operation):
    service = PendingDeleteService()
    monkeypatch.setattr(service, '_opportunistic_purge', AsyncMock())
    monkeypatch.setattr(service, '_arm_purge_timer', lambda _: None)
    repair = AsyncMock(return_value={'status': 'complete'})
    monkeypatch.setattr('py.services.shared_collection_bridge.prune_references', repair)
    root = tmp_path / 'models'
    root.mkdir()
    model = root / 'example.safetensors'
    model.write_bytes(b'local model')
    class Scanner:
        model_type = 'lora'
        def get_model_roots(self): return [str(root)]
        def _find_root_for_file(self, path): return str(root)
    batch = await service.stage_model_delete(scanner=Scanner(), target_dir=str(root),
        file_name='example', main_extension='.safetensors',
        original_file_path=str(model), cached_entry=None)
    assert batch and not model.exists()
    repair.assert_not_called()
    if operation == 'undo':
        await service.undo(batch)
        assert model.read_bytes() == b'local model'
        repair.assert_not_called()
        return
    manifest_path = root / '.lm-pending-delete' / batch / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['expires_at'] = int(time.time()) - 1
    manifest_path.write_text(json.dumps(manifest))
    if operation == 'retry':
        repair.return_value = {'status': 'recovery_not_saved'}
        await service.purge_batch(batch)
        assert manifest_path.exists()
        repair.return_value = {'status': 'complete'}
    await service.purge_batch(batch)
    repair.assert_called_with('lora', [str(model)])
    assert not manifest_path.exists()


def test_filename_template_cannot_mutate_during_restore(tmp_path, monkeypatch):
    monkeypatch.setattr('py.services.settings_manager.ensure_settings_file', lambda logger=None: str(tmp_path/'settings.json'))
    manager = SettingsManager()
    with manager.begin_restore({}):
        with pytest.raises(RestoreCoordinationError):
            manager.get_download_filename_template('lora')


async def test_statistics_reload_before_background_writer_resumes(tmp_path):
    stats = object.__new__(UsageStats)
    stats._lock = asyncio.Lock()
    stats._stats_file_path = str(tmp_path/'stats.json')
    stats.stats = {'checkpoints': {}, 'loras': {}, 'embeddings': {}, 'total_executions': 3}
    stats._is_dirty = True
    Path(stats._stats_file_path).write_text(json.dumps(stats.stats))
    async with stats.suspend_for_restore():
        assert stats._lock.locked()
        replacement = dict(stats.stats, total_executions=12)
        temporary = tmp_path/'incoming.json'
        temporary.write_text(json.dumps(replacement))
        temporary.replace(stats._stats_file_path)
    assert stats.stats['total_executions'] == 12
    assert not stats._is_dirty
