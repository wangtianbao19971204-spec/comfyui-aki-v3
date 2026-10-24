"""Cross-restart cache for the reviewed per-prompt semantics.

``_library_entry`` derives one row's reviewed view from its semantic binding:
the binding hash, the subcategory rules, the theme ids and the refinement
regexes.  On the current 325k-row library that pass is the bulk of the
multi-minute cold start, yet its result only depends on the row's binding, the
projection document and ``REFINEMENT_VERSION``.  This module keeps those results
in ``cache/semantic_cache.v1.msgpack.zst`` so a restart only re-derives the rows
whose binding changed.

The cache is optional: when msgpack or zstandard is missing it simply reports
itself unavailable and the caller keeps the uncached rebuild path.  A broken,
truncated or stale file is always a cache miss, never an error.
"""

import logging
import os
import threading
import time

try:
    import msgpack
    import zstandard
except Exception:  # noqa: BLE001 - the cache is optional, never a runtime requirement
    msgpack = None
    zstandard = None

logger = logging.getLogger("weilin.prompt_selector")

CACHE_FORMAT = 1
CACHE_FILENAME = "semantic_cache.v1.msgpack.zst"
STORE_DELAY = 2.0

AVAILABLE = msgpack is not None and zstandard is not None

_PENDING = {"payload": None, "timer": None}
_PENDING_LOCK = threading.Lock()


def load(cache_dir, projection, refinement_version):
    """Return the persisted ``{prompt_id: [binding, semantic]}`` or None.

    Every failure mode (missing file, unsupported format, another projection or
    refinement version, truncated payload) is reported as a cache miss so the
    caller rebuilds the projection instead of failing a request.
    """
    if not AVAILABLE:
        return None
    path = os.path.join(cache_dir, CACHE_FILENAME)
    started = time.perf_counter()
    try:
        with open(path, "rb") as stream:
            blob = stream.read()
        payload = msgpack.unpackb(zstandard.ZstdDecompressor().decompress(blob), raw=False)
        if not isinstance(payload, dict) or payload.get("format") != CACHE_FORMAT:
            logger.warning("[Workbench] semantic cache ignored: unsupported format")
            return None
        if payload.get("refinement_version") != refinement_version:
            logger.info("[Workbench] semantic cache ignored: refinement version changed")
            return None
        if list(payload.get("projection") or []) != list(projection):
            logger.info("[Workbench] semantic cache ignored: semantic projection changed")
            return None
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            logger.warning("[Workbench] semantic cache ignored: entry table missing")
            return None
    except FileNotFoundError:
        return None
    except Exception as error:  # noqa: BLE001 - a broken cache must never fail a read
        logger.warning("[Workbench] semantic cache ignored: %s", error)
        return None
    logger.info("[Workbench] semantic cache loaded in %.1f s: %d entries (%.1f MB)",
                time.perf_counter() - started, len(entries), os.path.getsize(path) / (1024 * 1024))
    return entries


def store(cache_dir, projection, refinement_version, entries):
    """Persist ``entries`` after a short debounce so a burst of edits writes once."""
    if not AVAILABLE or not entries:
        return
    # The dict copy is atomic under the GIL; later in-place edits must not race the writer.
    snapshot = dict(entries)
    header = {"format": CACHE_FORMAT, "refinement_version": refinement_version,
              "projection": list(projection)}
    with _PENDING_LOCK:
        _PENDING["payload"] = (cache_dir, header, snapshot)
        if _PENDING["timer"] is not None:
            _PENDING["timer"].cancel()
        timer = threading.Timer(STORE_DELAY, _run_pending)
        timer.daemon = True
        _PENDING["timer"] = timer
        timer.start()


def flush():
    """Write the pending snapshot without waiting for the debounce (tests/shutdown)."""
    with _PENDING_LOCK:
        timer = _PENDING["timer"]
        _PENDING["timer"] = None
    if timer is None:
        return False
    timer.cancel()
    _run_pending()
    return True


def _run_pending():
    with _PENDING_LOCK:
        payload = _PENDING["payload"]
        _PENDING["payload"] = None
        _PENDING["timer"] = None
    if payload is not None:
        _write(*payload)


def _write(cache_dir, header, entries):
    path = os.path.join(cache_dir, CACHE_FILENAME)
    temp_path = path + ".tmp"
    started = time.perf_counter()
    try:
        os.makedirs(cache_dir, exist_ok=True)
        payload = dict(header)
        payload["entries"] = entries
        packed = zstandard.ZstdCompressor().compress(msgpack.packb(payload, use_bin_type=True))
        with open(temp_path, "wb") as stream:
            stream.write(packed)
            stream.flush()
        os.replace(temp_path, path)
    except Exception as error:  # noqa: BLE001 - persisting the cache is best effort
        logger.warning("[Workbench] semantic cache store skipped: %s", error)
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return
    logger.info("[Workbench] semantic cache stored in %.1f s: %d entries (%.1f MB)",
                time.perf_counter() - started, len(entries), len(packed) / (1024 * 1024))
