"""Prepare stable archive sources without mutating owner databases."""
import contextlib
import hashlib
import math
import os
import secrets
import sqlite3
import tempfile
import time
from pathlib import Path

_SQLITE_KINDS = {"download_history", "model_update"}
_JSON_KINDS = {"settings", "symlink_map", "usage_stats"}
_CHUNK = 1024 * 1024


def _validate_timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout_seconds must be a positive finite number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout_seconds must be a positive finite number")
    return float(value)


def _fingerprint(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _new_path(staging_dir):
    fd, name = tempfile.mkstemp(
        prefix="backup-" + secrets.token_hex(8) + "-", dir=os.fspath(staging_dir)
    )
    os.close(fd)
    return name


def _copy_bytes(source, staging_dir, original_stat, created):
    if not os.path.isfile(source) or os.path.islink(source):
        raise ValueError("JSON source is not a regular, non-symlink file")
    before = _fingerprint(original_stat)
    destination = _new_path(staging_dir)
    created.add(destination)
    digest = hashlib.sha256()
    try:
        with open(source, "rb") as inp, open(destination, "wb") as out:
            opened = os.fstat(inp.fileno())
            if _fingerprint(opened)[:4] != before[:4]:
                raise RuntimeError("source changed during snapshot")
            while True:
                block = inp.read(_CHUNK)
                if not block:
                    break
                out.write(block)
                digest.update(block)
            ending = os.fstat(inp.fileno())
            out.flush()
            os.fsync(out.fileno())
        after = os.lstat(source)
        if _fingerprint(ending) != _fingerprint(opened) or _fingerprint(after) != before:
            raise RuntimeError("source changed during snapshot")
        size = os.stat(destination).st_size
        return destination, digest.hexdigest(), size
    except Exception:
        raise


def _sqlite_snapshot(source, staging_dir, timeout, original_stat, created):
    destination = _new_path(staging_dir)
    created.add(destination)
    created.update(destination + suffix for suffix in ("-wal", "-shm", "-journal"))
    deadline = time.monotonic() + timeout
    uri = Path(source).as_uri() + "?mode=ro"
    try:
        with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=timeout)) as src:
            with contextlib.closing(sqlite3.connect(destination, timeout=timeout)) as dst:
                def progress(status, remaining, total):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("SQLite backup timed out")

                if time.monotonic() >= deadline:
                    raise TimeoutError("SQLite backup timed out")
                src.backup(dst, pages=256, progress=progress, sleep=0.001)
                if time.monotonic() >= deadline:
                    raise TimeoutError("SQLite backup timed out")
                dst.execute("PRAGMA journal_mode=DELETE")
                dst.commit()
                row = dst.execute("PRAGMA integrity_check").fetchone()
                if not row or row[0].lower() != "ok":
                    raise sqlite3.DatabaseError("destination integrity_check failed")
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                os.unlink(destination + suffix)
            except FileNotFoundError:
                pass
        with open(destination, "rb") as inp:
            digest = hashlib.sha256()
            while True:
                block = inp.read(_CHUNK)
                if not block:
                    break
                digest.update(block)
        return destination, digest.hexdigest(), os.stat(destination).st_size
    except Exception:
        raise


def prepare_sources(raw_targets, staging_dir, *, timeout_seconds=30):
    """Return staged source metadata for the supplied owner paths."""
    timeout = _validate_timeout(timeout_seconds)
    staging = os.fspath(staging_dir)
    if not os.path.isdir(staging):
        raise ValueError("staging_dir must already exist")

    targets = []
    archives = set()
    owners = set()
    for item in raw_targets:
        try:
            kind, archive_path, target_path = item
        except (TypeError, ValueError):
            raise ValueError("raw_targets entries must be triples")
        if kind not in _SQLITE_KINDS | _JSON_KINDS:
            raise ValueError("unknown backup kind: %r" % (kind,))
        target = os.fspath(target_path)
        if not os.path.isabs(target):
            raise ValueError("target paths must be absolute")
        archive = os.fspath(archive_path)
        owner_key = os.path.normcase(os.path.normpath(target))
        if archive in archives:
            raise ValueError("duplicate archive path")
        if owner_key in owners:
            raise ValueError("duplicate target path")
        archives.add(archive)
        owners.add(owner_key)
        targets.append((kind, archive, target))

    created = set()
    result = []
    try:
        for kind, archive, target in targets:
            try:
                stat = os.lstat(target)
            except FileNotFoundError:
                continue
            if not os.path.isfile(target) or os.path.islink(target):
                raise ValueError("Backup source is not a regular, non-symlink file")
            if kind in _SQLITE_KINDS:
                staged, digest, size = _sqlite_snapshot(
                    target, staging, timeout, stat, created
                )
            else:
                staged, digest, size = _copy_bytes(target, staging, stat, created)
            result.append({
                "kind": kind,
                "archive_path": archive,
                "target_path": target,
                "source_path": staged,
                "sha256": digest,
                "size": size,
                "mtime": stat.st_mtime,
            })
        return result
    except Exception:
        for path in list(created):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        raise
