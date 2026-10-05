import copy, json, os, threading, time
from pathlib import Path
import pytest
from py.services.settings_manager import SettingsManager, RestoreCoordinationError

LEGACY = {"recipes_path": "neutral-recipes"}

@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr("py.services.settings_manager.ensure_settings_file", lambda logger=None: str(tmp_path / "settings.json"))
    manager = SettingsManager()
    monkeypatch.setattr(manager, "_notify_library_change", lambda *args: None)
    return manager

def _neutral_payload():
    return {"language": "en", "libraries": {}}


def _publish_success(manager, ctx):
    """Simulate the trusted executor replacing the captured file, then publish."""
    path = ctx.serialized_settings_path
    incoming = Path(path).with_suffix(".incoming")
    incoming.write_text(json.dumps(ctx.serialized_payload), encoding="utf-8")
    os.replace(incoming, path)
    ctx.publish(executor_status="success", context_token=ctx)


def test_readonly_preflight_pure_empty(manager):
    before = copy.deepcopy(manager.settings)
    out = manager.readonly_preflight({})
    assert set(out) == {"serialized_payload", "runtime_candidate"}
    assert isinstance(out["serialized_payload"], dict)
    assert isinstance(out["runtime_candidate"], dict)
    assert manager.settings == before


@pytest.mark.parametrize("payload", [LEGACY, {"language": "zh"}, {}])
def test_readonly_preflight_legacy_payload_valid(manager, payload):
    out = manager.readonly_preflight(payload)
    assert out["serialized_payload"] == payload
    assert out["serialized_payload"] is not payload


@pytest.mark.parametrize(
    "payload",
    [
        {"folder_paths": [123]},
        {"extra_folder_paths": "notalist"},
        {"libraries": ["bad"]},
        {"libraries": {"": {}}},
        {"libraries": {"a": "notamapping"}},
    ],
)
def test_readonly_preflight_rejects_malformed(manager, payload):
    with pytest.raises(RestoreCoordinationError):
        manager.readonly_preflight(payload)


@pytest.mark.parametrize("method", ["readonly_preflight", "begin_restore"])
def test_malformed_rejected_both_entrypoints(manager, method):
    with pytest.raises(RestoreCoordinationError):
        getattr(manager, method)({"libraries": {"a": 1}})


MUTATIONS = [
    ("set", ("language", "zh")),
    ("delete", ("language",)),
    ("activate_library", ("missing",)),
    ("upsert_library", ("x",)),
    ("create_library", ("x",)),
    ("rename_library", ("a", "b")),
    ("delete_library", ("x",)),
    ("update_active_library_paths", ({},)),
    ("update_extra_folder_paths", ({},)),
    ("refresh_environment_variables", ()),
    ("_save_settings", ()),
]


@pytest.mark.parametrize("name,args", MUTATIONS)
def test_mutations_rejected_while_ctx_active(manager, name, args):
    ctx = manager.begin_restore(_neutral_payload())
    try:
        method = getattr(manager, name)
        with pytest.raises(RestoreCoordinationError):
            method(*args, **({"folder_paths": {}} if name == "create_library" else {}))
    finally:
        ctx.abort()


def test_nested_begin_same_thread_rejected(manager):
    ctx = manager.begin_restore(_neutral_payload())
    try:
        with pytest.raises(RestoreCoordinationError):
            manager.begin_restore(_neutral_payload())
    finally:
        ctx.abort()


def test_cross_thread_set_waits_then_proceeds(manager):
    ctx = manager.begin_restore(_neutral_payload())
    entered = threading.Event()
    done = threading.Event()

    def worker():
        entered.set()
        manager.set("language", "fr")
        done.set()

    t = threading.Thread(target=worker)
    t.start()
    assert entered.wait(timeout=2)
    time.sleep(0.1)
    assert not done.is_set()
    ctx.abort()
    assert done.wait(timeout=2)
    t.join(timeout=2)
    assert manager.settings.get("language") == "fr"


def test_foreign_thread_abort_does_not_clear_state(manager):
    ctx = manager.begin_restore(_neutral_payload())
    try:
        result = {}

        def worker():
            try:
                ctx.abort()
                result["ok"] = True
            except Exception as exc:  # pragma: no cover - defensive
                result["err"] = exc

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=2)
        assert manager._active_restore_context is ctx
    finally:
        ctx.abort()


@pytest.mark.parametrize("status", ["failed", "unknown", None, 1])
def test_publish_rejects_bad_status(manager, status):
    ctx = manager.begin_restore(_neutral_payload())
    path = ctx.serialized_settings_path
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ctx.serialized_payload, fh)
    with pytest.raises(RestoreCoordinationError):
        ctx.publish(executor_status=status, context_token=ctx)


def test_publish_rejects_wrong_token(manager):
    ctx = manager.begin_restore(_neutral_payload())
    path = ctx.serialized_settings_path
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ctx.serialized_payload, fh)
    with pytest.raises(RestoreCoordinationError):
        ctx.publish(executor_status="success", context_token=object())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: os.remove(p),
        lambda p: Path(p).write_text("not json"),
        lambda p: Path(p).write_text(json.dumps({"language": "zz"})),
    ],
)
def test_publish_rejects_disk_mismatch(manager, mutate):
    ctx = manager.begin_restore(_neutral_payload())
    mutate(ctx.serialized_settings_path)
    with pytest.raises(RestoreCoordinationError):
        ctx.publish(executor_status="success", context_token=ctx)


def test_publish_success_applies_candidate(manager):
    payload = {"language": "zh", "active_library": "foo", "libraries": {"foo": {"folder_paths": {}}}}
    ctx = manager.begin_restore(payload)
    before = copy.deepcopy(manager.settings)
    _publish_success(manager, ctx)
    assert manager.settings.get("language") == "zh"
    assert manager.settings != before
    assert ctx.closed
    assert manager._active_restore_context is None


def test_runtime_candidate_is_defensive_copy(manager):
    ctx = manager.begin_restore({"language": "en", "active_library": "a", "libraries": {"a": {}}})
    try:
        c1 = ctx.runtime_candidate
        c1["language"] = "zzz"
        c2 = ctx.runtime_candidate
        assert c2["language"] == "en"
    finally:
        ctx.abort()


def test_changed_settings_path_rejects_on_publish(manager, tmp_path):
    ctx = manager.begin_restore(_neutral_payload())
    with open(ctx.serialized_settings_path, "w", encoding="utf-8") as fh:
        json.dump(ctx.serialized_payload, fh)
    manager.settings_file = str(tmp_path / "other.json")
    with pytest.raises(RestoreCoordinationError):
        ctx.publish(executor_status="success", context_token=ctx)


def test_native_serialization_roundtrip_is_pure_and_deterministic(manager):
    payload = manager._serialize_settings_for_disk()
    original = copy.deepcopy(manager.settings)
    disk = Path(manager.settings_file).read_bytes()
    first = manager.readonly_preflight(payload)
    second = manager.readonly_preflight(payload)
    assert first == second
    assert manager.settings == original
    assert Path(manager.settings_file).read_bytes() == disk
    for key in ("active_library", "libraries", "folder_paths", "recipes_path", "use_portable_settings"):
        assert first["runtime_candidate"][key] == original[key]


@pytest.mark.parametrize("payload", [{"use_portable_settings": "false"}, {"recipes_path": 17}, {"value": float("nan")}, {1: "bad"}])
def test_invalid_known_types_fail_both_entrypoints(manager, payload):
    for method in (manager.readonly_preflight, manager.begin_restore):
        with pytest.raises(RestoreCoordinationError):
            method(payload)
    assert manager._active_restore_context is None


def test_stale_revision_and_copied_payload_cannot_publish(manager):
    before = copy.deepcopy(manager.settings)
    with manager.begin_restore({"language": "zh"}) as ctx:
        copied = ctx.serialized_payload
        copied["language"] = "untrusted"
        assert ctx.serialized_payload["language"] == "zh"
        Path(ctx.serialized_settings_path).write_text(json.dumps(ctx.serialized_payload), encoding="utf-8")
        manager._settings_revision += 1
        with pytest.raises(RestoreCoordinationError):
            ctx.publish(executor_status="success", context_token=ctx)
    assert manager.settings == before
