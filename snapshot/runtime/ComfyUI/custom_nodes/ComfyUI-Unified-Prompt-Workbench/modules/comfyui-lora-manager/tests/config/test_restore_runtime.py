"""Independent native Config checks and original-owner refresh protocol checks."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from py import config as config_module
from py.services import settings_manager as settings_module
from py.services.service_registry import ServiceRegistry


@pytest.fixture
def env(tmp_path, monkeypatch):
    roots = {}
    for kind in ('loras', 'checkpoints', 'embeddings'):
        path = tmp_path / kind
        path.mkdir()
        roots[kind] = [str(path)]
    canonical = tmp_path / 'cache' / 'symlink_map.json'
    calls = []
    def cache_path(kind, *, create_dir=True):
        calls.append(create_dir)
        if create_dir:
            canonical.parent.mkdir(parents=True, exist_ok=True)
        return str(canonical)
    monkeypatch.setattr(config_module.folder_paths, 'get_folder_paths', lambda kind: roots.get(kind, []))
    monkeypatch.setattr(config_module, 'standalone_mode', True)
    monkeypatch.setattr(config_module, 'get_cache_file_path', cache_path)
    cfg = config_module.Config()
    monkeypatch.setattr(settings_module, 'ensure_settings_file', lambda logger=None: str(tmp_path / 'settings.json'))
    manager = settings_module.SettingsManager()
    monkeypatch.setattr(config_module, 'config', cfg)
    monkeypatch.setattr(ServiceRegistry, '_services', {})
    return SimpleNamespace(cfg=cfg, manager=manager, roots=roots, canonical=canonical, calls=calls, root=tmp_path)


def forbid_write():
    raise AssertionError('Restore refresh must not save the cache')


def restore(env):
    env.cfg.apply_library_settings({'folder_paths': env.roots}, symlink_cache_policy='restore_no_write')


def test_valid_cache_is_readonly(env, monkeypatch):
    before = env.canonical.read_bytes()
    monkeypatch.setattr(env.cfg, '_save_symlink_cache', forbid_write)
    monkeypatch.setattr(config_module, 'get_legacy_cache_paths', lambda *a: pytest.fail('legacy cache access'))
    env.calls.clear()
    restore(env)
    assert env.canonical.read_bytes() == before
    assert env.calls == [False]
    assert env.cfg._cached_fingerprint == env.cfg._build_symlink_fingerprint()


def test_stale_cache_uses_real_scan_without_write(env, monkeypatch):
    before = env.canonical.read_bytes()
    target = env.root / 'linked_models'
    target.mkdir()
    preview = target / 'preview.png'
    preview.write_bytes(b'neutral')
    link = Path(env.roots['loras'][0]) / 'link'
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(env.cfg, '_save_symlink_cache', forbid_write)
    restore(env)
    assert env.canonical.read_bytes() == before
    assert env.cfg._path_mappings[env.cfg._normalize_path(str(target))] == env.cfg._normalize_path(str(link))
    assert env.cfg.is_preview_path_allowed(str(preview))


def test_missing_cache_does_not_create_parent(env, monkeypatch):
    missing = env.root / 'missing' / 'nested' / 'cache.json'
    calls = []
    def path(kind, *, create_dir=True):
        calls.append(create_dir)
        assert not create_dir
        return str(missing)
    monkeypatch.setattr(config_module, 'get_cache_file_path', path)
    monkeypatch.setattr(env.cfg, '_save_symlink_cache', forbid_write)
    restore(env)
    assert calls == [False]
    assert not missing.parent.exists()


@pytest.mark.parametrize('content', ['{bad', '[]', '{"path_mappings": {"x": 2}}'])
def test_invalid_canonical_is_not_hidden_by_legacy(env, monkeypatch, content):
    env.canonical.write_text(content, encoding='utf-8')
    monkeypatch.setattr(config_module, 'get_legacy_cache_paths', lambda *a: pytest.fail('legacy fallback'))
    monkeypatch.setattr(env.cfg, '_save_symlink_cache', forbid_write)
    with pytest.raises(ValueError):
        restore(env)
    assert env.canonical.read_text(encoding='utf-8') == content


def test_unknown_policy_has_no_effect(env):
    before = copy.deepcopy(env.cfg._path_mappings), list(env.cfg.loras_roots), env.canonical.read_bytes()
    with pytest.raises(ValueError):
        env.cfg.apply_library_settings({}, symlink_cache_policy='invalid')
    assert before == (env.cfg._path_mappings, env.cfg.loras_roots, env.canonical.read_bytes())


def test_unregistered_is_benign_and_config_precedes_callbacks(env, monkeypatch):
    events = []
    monkeypatch.setattr(env.cfg, 'apply_library_settings', lambda *a, **kw: events.append(('config', kw)))
    ServiceRegistry._services['model_update_service'] = SimpleNamespace(on_library_changed=lambda: events.append('model'))
    result = env.manager.refresh_restored_runtime(restored_owners=['settings'])
    assert result['complete'] and not result['scan_completion_verified']
    assert events == [('config', {'symlink_cache_policy': 'restore_no_write'}), 'model']
    assert result['owners']['lora_scanner']['status'] == 'unregistered'


@pytest.mark.parametrize('name,flag', [('model_update_service', '_restore_suspended'), ('downloaded_version_history_service', '_suspended')])
def test_suspension_prevents_all_refresh_effects(env, monkeypatch, name, flag):
    events = []
    monkeypatch.setattr(env.cfg, 'apply_library_settings', lambda *a, **k: events.append('config'))
    ServiceRegistry._services[name] = SimpleNamespace(**{flag: True})
    ServiceRegistry._services['lora_scanner'] = SimpleNamespace(on_library_changed=lambda: events.append('scanner'))
    result = env.manager.refresh_restored_runtime(restored_owners=['settings'])
    assert not result['complete'] and events == []


def test_config_failure_blocks_scanners(env, monkeypatch):
    events = []
    def fail(*a, **k): raise RuntimeError('neutral config failure')
    monkeypatch.setattr(env.cfg, 'apply_library_settings', fail)
    ServiceRegistry._services['lora_scanner'] = SimpleNamespace(on_library_changed=lambda: events.append('scanner'))
    result = env.manager.refresh_restored_runtime(restored_owners=['settings'])
    assert not result['complete'] and events == []
    assert result['owners']['config']['status'] == 'failed'
    assert result['owners']['lora_scanner']['status'] == 'skipped'


def test_scanner_failure_continues_independent_callbacks(env, monkeypatch):
    events = []
    monkeypatch.setattr(env.cfg, 'apply_library_settings', lambda *a, **k: events.append('config'))
    def fail(): raise RuntimeError('neutral scanner failure')
    ServiceRegistry._services['lora_scanner'] = SimpleNamespace(on_library_changed=fail)
    ServiceRegistry._services['recipe_scanner'] = SimpleNamespace(on_library_changed=lambda: events.append('recipe'))
    result = env.manager.refresh_restored_runtime(restored_owners=['settings'])
    assert not result['complete'] and events == ['config', 'recipe']
    assert result['owners']['lora_scanner']['status'] == 'failed'
    assert result['owners']['recipe_scanner']['status'] == 'applied'


def test_database_only_does_not_switch_paths(env, monkeypatch):
    events = []
    monkeypatch.setattr(env.cfg, 'apply_library_settings', lambda *a, **k: events.append('config'))
    ServiceRegistry._services['model_update_service'] = SimpleNamespace(on_library_changed=lambda: events.append('switch'))
    result = env.manager.refresh_restored_runtime(restored_owners=['model_update', 'download_history'])
    assert result['complete'] and events == []
    assert result['owners']['config']['status'] == 'unchanged'


@pytest.mark.parametrize('owners', ['settings', ['unknown'], [1], None])
def test_invalid_input_has_no_effect(env, monkeypatch, owners):
    events = []
    monkeypatch.setattr(env.cfg, 'apply_library_settings', lambda *a, **k: events.append('config'))
    with pytest.raises((TypeError, ValueError)):
        env.manager.refresh_restored_runtime(restored_owners=owners)
    assert events == []


def test_registry_failure_is_not_unregistered(env, monkeypatch):
    events = []
    monkeypatch.setattr(env.cfg, 'apply_library_settings', lambda *a, **k: events.append('config'))
    def fail(name): raise RuntimeError('neutral registry failure')
    monkeypatch.setattr(ServiceRegistry, 'get_service_sync', fail)
    result = env.manager.refresh_restored_runtime(restored_owners=['settings'])
    assert not result['complete'] and events == []
    assert result['owners']['lora_scanner']['status'] == 'failed'


def test_refresh_cannot_run_inside_settings_restore(env, monkeypatch):
    events = []
    monkeypatch.setattr(env.cfg, 'apply_library_settings', lambda *a, **k: events.append('config'))
    with env.manager.begin_restore({}):
        with pytest.raises(settings_module.RestoreCoordinationError):
            env.manager.refresh_restored_runtime(restored_owners=['settings'])
    assert events == []
