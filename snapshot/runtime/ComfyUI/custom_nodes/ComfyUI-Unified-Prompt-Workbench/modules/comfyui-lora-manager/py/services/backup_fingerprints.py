"""Read-only fingerprints for SQLite backup coordination."""
import copy
import hashlib
import os
import re
import stat


class FingerprintError(ValueError):
    pass


_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_MISSING = object()


def _path(value):
    if isinstance(value, bytes) or not isinstance(value, (str, os.PathLike)):
        raise FingerprintError("path must be a text path")
    try:
        value = os.fspath(value)
    except TypeError as exc:
        raise FingerprintError("invalid path") from exc
    if isinstance(value, bytes) or not os.path.isabs(value) or "\0" in value:
        raise FingerprintError("path must be absolute")
    return value


def _stamp(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise FingerprintError("cannot inspect path") from exc
    attrs = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(info.st_mode) or attrs & reparse:
        raise FingerprintError("symlink or reparse point is not allowed")
    if not stat.S_ISREG(info.st_mode):
        raise FingerprintError("path must name a regular file")
    return (info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _fingerprint(stamp, digest=None):
    if stamp is None:
        return {"exists": False, "sha256": None, "size": 0, "mtime_ns": None}
    return {"exists": True, "sha256": digest, "size": stamp[2],
            "mtime_ns": stamp[3]}


def _same_stamp(left, right):
    return left == right


def _hash_file(path, expected):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            opened = os.fstat(stream.fileno())
            actual = (opened.st_dev, opened.st_ino, opened.st_size,
                      opened.st_mtime_ns, opened.st_ctime_ns)
            opened_stamp = actual
            # Windows path and handle metadata may expose different ctime values.
            # Compare common identity here; retain full within-API change checks.
            if expected[:4] != actual[:4]:
                raise FingerprintError("path changed during inspection")
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            closed = os.fstat(stream.fileno())
    except FingerprintError:
        raise
    except OSError as exc:
        raise FingerprintError("cannot read path") from exc
    actual = (closed.st_dev, closed.st_ino, closed.st_size,
              closed.st_mtime_ns, closed.st_ctime_ns)
    if not _same_stamp(opened_stamp, actual):
        raise FingerprintError("path changed during inspection")
    return digest.hexdigest()


def fingerprint_path(path, *, sqlite=False):
    """Return a read-only, group-consistent fingerprint."""
    path = _path(path)
    if not isinstance(sqlite, bool):
        raise FingerprintError("sqlite must be bool")
    paths = [path]
    if sqlite:
        paths.extend((path + "-wal", path + "-journal"))
    before = [_stamp(item) for item in paths]
    if before[0] is None and any(item is not None and item[2] > 0
                                 for item in before[1:]):
        raise FingerprintError("orphaned SQLite sidecar state")
    hashes = [None if stamp is None else _hash_file(item, stamp)
              for item, stamp in zip(paths, before)]
    after = [_stamp(item) for item in paths]
    if before != after:
        raise FingerprintError("path changed during group inspection")
    result = _fingerprint(before[0], hashes[0])
    if sqlite:
        result["sqlite_files"] = {
            "wal": _fingerprint(before[1], hashes[1]),
            "journal": _fingerprint(before[2], hashes[2]),
        }
    return result


def _plain(value):
    if not isinstance(value, dict) or set(value) != {"exists", "sha256", "size", "mtime_ns"}:
        raise FingerprintError("invalid fingerprint keys")
    exists = value["exists"]
    size = value["size"]
    mtime = value["mtime_ns"]
    digest = value["sha256"]
    if type(exists) is not bool or type(size) is not int or size < 0:
        raise FingerprintError("invalid fingerprint types")
    if exists:
        if not isinstance(digest, str) or not _HEX.fullmatch(digest):
            raise FingerprintError("invalid sha256")
        if type(mtime) is not int:
            raise FingerprintError("invalid mtime_ns")
    else:
        if digest is not None or size != 0 or mtime is not None:
            raise FingerprintError("invalid missing fingerprint")
    return {"exists": exists, "sha256": digest.lower() if digest is not None else None, "size": size,
            "mtime_ns": mtime}


def validate_fingerprint(value):
    if not isinstance(value, dict):
        raise FingerprintError("fingerprint must be a dict")
    keys = set(value)
    if keys not in ({"exists", "sha256", "size", "mtime_ns"},
                    {"exists", "sha256", "size", "mtime_ns", "sqlite_files"}):
        raise FingerprintError("invalid fingerprint keys")
    result = _plain({key: value[key] for key in ("exists", "sha256", "size", "mtime_ns")})
    if "sqlite_files" in value:
        sides = value["sqlite_files"]
        if not isinstance(sides, dict) or set(sides) != {"wal", "journal"}:
            raise FingerprintError("invalid sqlite_files")
        result["sqlite_files"] = {key: _plain(sides[key])
                                   for key in ("wal", "journal")}
        if not result["exists"] and any(item["exists"] and item["size"] > 0 for item in result["sqlite_files"].values()):
            raise FingerprintError("orphaned SQLite sidecar state")
    return copy.deepcopy(result)


def same_fingerprint(a, b):
    try:
        return validate_fingerprint(a) == validate_fingerprint(b)
    except FingerprintError:
        return False


def has_sqlite_changes(value):
    normalized = validate_fingerprint(value)
    sides = normalized.get("sqlite_files")
    return bool(sides and any(item["exists"] and item["size"] > 0
                              for item in sides.values()))
