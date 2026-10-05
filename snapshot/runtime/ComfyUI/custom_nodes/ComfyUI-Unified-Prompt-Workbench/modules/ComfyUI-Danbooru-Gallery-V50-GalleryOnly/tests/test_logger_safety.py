from __future__ import annotations

import importlib.util
import logging
import sys
import uuid
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LOGGER_SOURCE = PLUGIN_ROOT / "py" / "utils" / "logger.py"


def _close_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _load_logger_module(monkeypatch, log_dir: Path):
    monkeypatch.setenv("DANBOORU_GALLERY_LOG_DIR", str(log_dir.resolve()))
    module_name = f"gallery_logger_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, LOGGER_SOURCE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_setup_logging_appends_session_without_truncating_existing_history(
    monkeypatch, tmp_path
):
    plugin_logger = logging.getLogger("danbooru_gallery")
    _close_handlers(plugin_logger)
    log_path = tmp_path / "danbooru_gallery.log"
    log_path.write_text("PREVIOUS-CRASH-EVIDENCE\n", encoding="utf-8")

    module = _load_logger_module(monkeypatch, tmp_path)
    try:
        module.setup_logging()
        module.get_logger("append_test").info("CURRENT-SESSION-MESSAGE")
        for handler in plugin_logger.handlers:
            handler.flush()
    finally:
        _close_handlers(plugin_logger)

    second_module = _load_logger_module(monkeypatch, tmp_path)
    try:
        second_module.setup_logging()
        second_module.get_logger("second_session").info("SECOND-SESSION-MESSAGE")
        for handler in plugin_logger.handlers:
            handler.flush()
    finally:
        _close_handlers(plugin_logger)

    content = log_path.read_text(encoding="utf-8")
    assert content.startswith("PREVIOUS-CRASH-EVIDENCE\n")
    assert f"会话开始: {module.LOG_SESSION_ID}" in content
    assert f"会话开始: {second_module.LOG_SESSION_ID}" in content
    assert "CURRENT-SESSION-MESSAGE" in content
    assert "SECOND-SESSION-MESSAGE" in content
    assert "追加写入" in content


def test_safe_rotating_handler_keeps_bounded_archives(monkeypatch, tmp_path):
    module = _load_logger_module(monkeypatch, tmp_path)
    log_path = tmp_path / "rotation.log"
    logger = logging.getLogger(f"rotation-test-{uuid.uuid4().hex}")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = module.SafeRotatingFileHandler(
        log_path,
        max_bytes=180,
        backup_count=2,
        mode="a",
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    try:
        for index in range(12):
            logger.info("record-%02d-%s", index, "x" * 80)
        handler.flush()
    finally:
        _close_handlers(logger)

    assert log_path.is_file()
    assert Path(f"{log_path}.1").is_file()
    assert Path(f"{log_path}.2").is_file()
    assert not Path(f"{log_path}.3").exists()
    assert "record-11" in log_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="append mode"):
        module.SafeRotatingFileHandler(log_path, mode="w")
