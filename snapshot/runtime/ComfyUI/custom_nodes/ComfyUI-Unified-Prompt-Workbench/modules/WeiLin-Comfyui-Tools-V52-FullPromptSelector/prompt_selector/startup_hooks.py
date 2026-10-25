"""Defer workbench start-up work until ComfyUI's HTTP app is starting.

The prompt library and Tag warm-ups are CPU-heavy and are only useful to the
workbench itself.  Importing this plugin must stay cheap for ComfyUI's own
start-up path, so heavy tasks subscribe here and run in a daemon thread once
the aiohttp application starts, instead of blocking or competing with the
plugin import phase.  ``UW_SKIP_LIBRARY_WARMUP=1`` keeps its existing meaning:
callers simply do not register the task.
"""

import logging
import threading
import time

logger = logging.getLogger("weilin.prompt_selector")

_REGISTERED = []


def _run_in_thread(callback, delay):
    def runner():
        if delay:
            time.sleep(delay)
        try:
            callback()
        except Exception:  # noqa: BLE001 - a failed warm-up must not kill the server
            logger.exception("[Workbench] startup task failed")

    thread = threading.Thread(target=runner, name="uw-startup-task", daemon=True)
    thread.start()


def register_after_start(callback, delay=0.0):
    """Run ``callback`` once ComfyUI's HTTP application is starting.

    Returns True when the callback was registered.  Registering the same
    callback twice is a no-op so tests and reloads stay deterministic.
    """
    if callback in _REGISTERED:
        return False

    app = None
    try:
        from server import PromptServer

        app = getattr(getattr(PromptServer, "instance", None), "app", None)
    except Exception:  # noqa: BLE001 - hosts without ComfyUI still import cleanly
        app = None

    if app is not None and hasattr(app, "on_startup"):
        async def _on_start(_app):
            _run_in_thread(callback, delay)

        app.on_startup.append(_on_start)
        _REGISTERED.append(callback)
        return True

    # No real aiohttp application (tests or unusual hosts): keep the work off
    # the import path anyway. The delay is a floor, not a promise of readiness.
    _REGISTERED.append(callback)
    timer = threading.Timer(max(delay, 3.0), _run_in_thread, args=(callback, 0.0))
    timer.daemon = True
    timer.start()
    return True
