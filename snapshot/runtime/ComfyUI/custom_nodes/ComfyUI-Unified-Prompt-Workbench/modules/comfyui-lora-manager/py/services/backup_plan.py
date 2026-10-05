if __package__:
    from .backup_fingerprints import FingerprintError, validate_fingerprint, has_sqlite_changes
else:
    from backup_fingerprints import FingerprintError, validate_fingerprint, has_sqlite_changes

import hashlib
import json
import os
import re
import stat
import zipfile


class PlanError(ValueError):
    """The archive cannot be safely planned."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _limits(given):
    out = {
        "compressed_bytes": 512 * 1024 * 1024,
        "member_bytes": 512 * 1024 * 1024,
        "expanded_bytes": 1024 * 1024 * 1024,
        "entries": 4096,
        "path_bytes": 1024,
        "manifest_bytes": 8 * 1024 * 1024,
    }
    if given is not None:
        if not isinstance(given, dict) or any(k not in out for k in given):
            raise PlanError("malformed limits")
        for key, value in given.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PlanError("invalid limit: " + key)
            out[key] = value
    return out


def _options(given):
    out = {"existing": "skip", "selected_indices": None}
    if given is not None:
        if not isinstance(given, dict) or any(k not in out for k in given):
            raise PlanError("unknown option")
        out.update(given)
    if out["existing"] not in ("overwrite", "skip"):
        raise PlanError("invalid existing option")
    selected = out["selected_indices"]
    if selected is not None:
        if not isinstance(selected, list) or any(
            isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in selected
        ):
            raise PlanError("invalid selected_indices")
        if len(set(selected)) != len(selected):
            raise PlanError("selected_indices must be unique")
    return out


def _member_path(name, maxlen, directory=False):
    if not isinstance(name, str) or not name or "\x00" in name:
        return False
    if len(name.encode("utf-8")) > maxlen or "\\" in name:
        return False
    if name.startswith("/") or name.startswith("//"):
        return False
    drive, _ = os.path.splitdrive(name)
    if drive or (len(name) > 1 and name[1] == ":"):
        return False
    value = name[:-1] if directory and name.endswith("/") else name
    if not value:
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") and ":" not in part and not part.endswith((" ", ".")) for part in parts)


def _fingerprint(value):
    try:
        return validate_fingerprint(value)
    except FingerprintError as exc:
        raise PlanError(str(exc)) from exc


def _read_member(zf, info, limits, expanded):
    if info.file_size > limits["member_bytes"]:
        raise PlanError("member limit exceeded")
    if expanded + info.file_size > limits["expanded_bytes"]:
        raise PlanError("expanded limit exceeded")
    digest = hashlib.sha256()
    size = 0
    try:
        with zf.open(info, "r") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > limits["member_bytes"] or expanded + size > limits["expanded_bytes"]:
                    raise PlanError("member or expanded limit exceeded")
                digest.update(block)
    except PlanError:
        raise
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, EOFError) as exc:
        raise PlanError("invalid ZIP member: " + str(exc))
    if size != info.file_size:
        raise PlanError("truncated ZIP member")
    return digest.hexdigest(), size


def _archive_stamp(path):
    st = os.stat(path)
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, getattr(st, "st_ctime_ns", 0))


def build_plan(archive_path, resolve_target, fingerprint, options=None, limits=None):
    limits = _limits(limits)
    options = _options(options)
    try:
        before = _archive_stamp(archive_path)
        if before[2] > limits["compressed_bytes"]:
            raise PlanError("compressed archive limit exceeded")
    except PlanError:
        raise
    except OSError as exc:
        raise PlanError("cannot stat archive: " + str(exc))

    archive_hash = hashlib.sha256()
    try:
        with open(archive_path, "rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                archive_hash.update(block)
        zf = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
        raise PlanError("invalid ZIP archive: " + str(exc))

    try:
        infos = zf.infolist()
        if len(infos) > limits["entries"]:
            raise PlanError("entry limit exceeded")
        by_name = {}
        directories = set()
        for info in infos:
            is_directory = info.is_dir() or info.filename.endswith("/")
            if not _member_path(info.filename, limits["path_bytes"], is_directory):
                raise PlanError("unsafe ZIP member path")
            if stat.S_ISLNK((info.external_attr >> 16) & 0xffff):
                raise PlanError("symlink ZIP member")
            if is_directory:
                directories.add(info.filename)
                continue
            by_name.setdefault(info.filename, []).append(info)
        if "manifest.json" not in by_name or len(by_name["manifest.json"]) != 1:
            raise PlanError("manifest.json is missing or duplicated")
        if by_name["manifest.json"][0].file_size > limits["manifest_bytes"]:
            raise PlanError("manifest limit exceeded")
        expanded = 0
        hashes = {}
        for info in infos:
            if info.filename in directories:
                continue
            digest, size = _read_member(zf, info, limits, expanded)
            expanded += size
            hashes.setdefault(info.filename, []).append((digest, size))
        manifest_info = by_name["manifest.json"][0]
        if manifest_info.file_size > limits["manifest_bytes"]:
            raise PlanError("manifest limit exceeded")
        try:
            manifest = json.loads(zf.read(manifest_info).decode("utf-8"))
        except (UnicodeError, ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise PlanError("invalid manifest.json: " + str(exc))
    finally:
        zf.close()

    try:
        after = _archive_stamp(archive_path)
    except OSError as exc:
        raise PlanError("cannot restat archive: " + str(exc))
    if before != after:
        raise PlanError("archive changed during planning")

    if not isinstance(manifest, dict) or not isinstance(manifest.get("manifest_version"), int) or isinstance(manifest.get("manifest_version"), bool):
        raise PlanError("malformed manifest_version")
    if manifest["manifest_version"] != 1:
        raise PlanError("unsupported manifest_version")
    if not isinstance(manifest.get("files"), list):
        raise PlanError("malformed manifest files")
    rows = manifest["files"]
    if len(rows) > limits["entries"]:
        raise PlanError("manifest entry limit exceeded")
    selected = options["selected_indices"]
    if selected is not None and any(i >= len(rows) for i in selected):
        raise PlanError("selected_indices out of range")
    selected_set = set(range(len(rows))) if selected is None else set(selected)

    known_metadata = {"manifest_version", "snapshot_type", "active_library", "created_at", "files"}
    unknown_fields = sorted(k for k in manifest if k not in known_metadata)
    units = []
    bad = set()
    member_rows = {}
    target_rows = {}
    fp_cache = {}
    duplicate_names = {name for name, values in by_name.items() if len(values) > 1}

    for index, record in enumerate(rows):
        unit = {"index": index, "member": None, "kind": None, "target": None,
                "current_fingerprint": None, "incoming_sha256": None, "size": None,
                "category": "unsupported", "action": "skip", "reason": "malformed record",
                "verification": "none"}
        units.append(unit)
        if not isinstance(record, dict) or not isinstance(record.get("kind"), str) or not isinstance(record.get("archive_path"), str):
            bad.add(index)
            continue
        member = record["archive_path"]
        kind = record["kind"]
        unit.update(member=member, kind=kind)
        is_dir = member.endswith("/")
        if not _member_path(member, limits["path_bytes"], is_dir) or (member not in hashes and member not in directories):
            bad.add(index)
            unit["reason"] = "invalid or missing member"
            continue
        if "target_path" in record and not isinstance(record["target_path"], str):
            bad.add(index)
            unit["reason"] = "malformed informational target_path"
            continue
        if is_dir:
            unit.update(reason="directory entry", verification="none")
            continue
        if "sha256" in record and (not isinstance(record["sha256"], str) or not re.fullmatch(r"[0-9a-fA-F]{64}", record["sha256"]) or len(hashes[member]) != 1 or record["sha256"].lower() != hashes[member][0][0]):
            bad.add(index)
            unit["reason"] = "manifest hash mismatch"
            continue
        if "size" in record and (isinstance(record["size"], bool) or not isinstance(record["size"], int) or record["size"] < 0 or len(hashes[member]) != 1 or record["size"] != hashes[member][0][1]):
            bad.add(index)
            unit["reason"] = "manifest size mismatch"
            continue
        incoming_sha, size = hashes[member][0]
        unit.update(incoming_sha256=incoming_sha, size=size, verification="verified" if "sha256" in record else "computed")
        member_rows.setdefault(member, []).append(index)
        try:
            target = resolve_target(kind, member)
        except Exception as exc:
            raise PlanError("target resolver failed: " + str(exc))
        if target is None:
            unit["reason"] = "unsupported kind"
            continue
        if not isinstance(target, str) or not os.path.isabs(target):
            raise PlanError("resolver returned non-absolute target")
        target = os.path.normpath(target)
        unit["target"] = target
        key = os.path.normcase(target)
        target_rows.setdefault(key, []).append(index)
        if key not in fp_cache:
            try:
                fp_cache[key] = _fingerprint(fingerprint(target))
            except PlanError:
                raise
            except Exception as exc:
                raise PlanError("fingerprint failed: " + str(exc))
        unit["current_fingerprint"] = dict(fp_cache[key])

    structural_conflicts = {i for name, indices in member_rows.items() if name in duplicate_names or len(indices) > 1 for i in indices}
    for indices in target_rows.values():
        if len(indices) > 1:
            structural_conflicts.update(indices)
    for name in duplicate_names:
        if name not in member_rows and name != "manifest.json":
            raise PlanError("unreferenced duplicate ZIP member")

    for unit in units:
        index = unit["index"]
        if index in structural_conflicts:
            unit.update(category="version_conflict", action="skip", reason="duplicate member or target")
            continue
        if index in bad or unit["target"] is None or unit["member"] in directories:
            continue
        fp = unit["current_fingerprint"]
        if not fp["exists"]:
            unit["category"] = "new"
            equal = False
        elif fp["sha256"].lower() == unit["incoming_sha256"].lower() and fp["size"] == unit["size"] and not has_sqlite_changes(fp):
            unit["category"] = "suspected_duplicate"
            equal = True
        else:
            unit["category"] = "updated"
            equal = False
        if equal:
            unit.update(action="skip", reason="incoming content already exists")
        elif index in selected_set and (not fp["exists"] or options["existing"] == "overwrite"):
            unit.update(action="write", reason="selected and permitted")
        else:
            unit.update(action="skip", reason="not selected or overwrite not permitted")

    counts = {key: 0 for key in ("new", "updated", "suspected_duplicate", "unsupported", "version_conflict")}
    for unit in units:
        counts[unit["category"]] += 1
    committable = not bad and not structural_conflicts
    plan = {
        "archive_sha256": archive_hash.hexdigest(),
        "options": options,
        "limits": limits,
        "counts": counts,
        "units": units,
        "committable": committable,
        "unknown_manifest_fields": unknown_fields,
        "units_unit": "files",
        "selected_count": len(selected_set),
        "will_write": [u["index"] for u in units if u["action"] == "write"],
        "will_skip": [u["index"] for u in units if u["action"] == "skip"],
    }
    plan["plan_hash"] = _sha(_canon(plan))
    return plan
