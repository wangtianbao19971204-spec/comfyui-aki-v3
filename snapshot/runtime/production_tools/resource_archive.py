"""Archive or restore the reviewed historical snapshots, without overwriting files."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "_archives/2026-09-28_workflow_cleanup"
REPORT = ROOT / "benchmark_reports/2026-09-28_workflow_ui/overnight_optimization"
MANIFEST = ARCHIVE / "manifest.json"
GROUPS = {"historical_library_snapshots", "historical_ui_recovery_snapshots"}


def safe_path(relative, *, archive=False):
    base = ARCHIVE / "payload" if archive else ROOT
    path = base / relative
    resolved = path.resolve(strict=False)
    if resolved == base.resolve() or not resolved.is_relative_to(base.resolve()):
        raise ValueError(f"Path escaped its declared root: {relative}")
    cursor = path
    while cursor != ROOT:
        if cursor.exists() and (cursor.is_symlink() or cursor.is_junction()):
            raise ValueError(f"Directory or file link is not eligible: {relative}")
        if cursor == cursor.parent:
            raise ValueError(f"Path did not resolve through the workspace: {relative}")
        cursor = cursor.parent
    return path


def available(path):
    """An exclusive Windows handle rejects any concurrently open shared handle."""
    if os.name != "nt":
        raise RuntimeError("This archive requires Windows exclusive-handle checks.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000 | 0x00010000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "File is open or cannot be exclusively read/moved", str(path))
    close(handle)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def check_file(path, entry, *, hash_file=True):
    if not path.is_file():
        raise FileNotFoundError(path)
    info = path.stat()
    if info.st_size != entry["bytes"] or info.st_mtime_ns != entry["mtime_ns"]:
        raise RuntimeError(f"File changed since review: {entry['path']}")
    available(path)
    if hash_file and digest(path) != entry["sha256"]:
        raise RuntimeError(f"Hash differs from frozen manifest: {entry['path']}")


def log(event, entry=None, **values):
    line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **values}
    if entry:
        line.update(path=entry["path"], group=entry["group"], sha256=entry.get("sha256"))
    with (ARCHIVE / "operations.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(line, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["workspace"] != str(ROOT) or manifest["archive"] != str(ARCHIVE):
        raise ValueError("Manifest does not belong to the current workspace/archive.")
    if not manifest.get("complete") or {row["group"] for row in manifest["entries"]} - GROUPS:
        raise ValueError("Manifest is incomplete or contains an unapproved group.")
    if len({row["path"] for row in manifest["entries"]}) != len(manifest["entries"]):
        raise ValueError("Duplicate manifest paths.")
    return manifest


def plan():
    if MANIFEST.exists():
        raise FileExistsError("Existing frozen manifest will not be overwritten.")
    inventory_path = REPORT / "resources_plugins_audit.json"
    reference_path = REPORT / "archive_dependency_scan.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    references = json.loads(reference_path.read_text(encoding="utf-8"))
    excluded = set(references["excluded_candidate_paths"])
    reviewed = inventory["archival_plan"]["groups"]
    if {group["name"] for group in reviewed} != GROUPS or sum(len(group["files"]) for group in reviewed) != 207:
        raise ValueError("Reviewed candidate set is no longer the approved two groups/207 files.")
    safe_path(str(ARCHIVE.relative_to(ROOT)))
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    safe_path(str((ARCHIVE / "payload").relative_to(ROOT)))
    entries = []
    for group in reviewed:
        for item in group["files"]:
            if item["path"] in excluded:
                continue
            entry = {**item, "group": group["name"]}
            source = safe_path(entry["path"])
            target = safe_path(entry["path"], archive=True)
            if target.exists():
                raise FileExistsError(target)
            check_file(source, entry, hash_file=False)
            entry["sha256"] = digest(source)
            check_file(source, entry, hash_file=False)
            entries.append(entry)
            log("planned", entry)
            if len(entries) % 10 == 0:
                print(json.dumps({"phase": "plan", "files_hashed": len(entries)}, ensure_ascii=False), flush=True)
    manifest = {"version": 1, "complete": True, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "workspace": str(ROOT), "archive": str(ARCHIVE), "inventory_sha256": digest(inventory_path), "dependency_scan_sha256": digest(reference_path), "excluded_paths": sorted(excluded), "entries": entries, "file_count": len(entries), "logical_bytes": sum(item["bytes"] for item in entries), "reclaimed_bytes": 0, "method": "Same-volume rename with per-file SHA-256 and exclusive handle checks; reversible, no deletion or compression."}
    with MANIFEST.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    log("manifest_frozen", file_count=len(entries), manifest_sha256=digest(MANIFEST))
    print(json.dumps({"manifest_complete": True, "files": len(entries), "logical_bytes": manifest["logical_bytes"]}, ensure_ascii=False), flush=True)


def select(manifest, args):
    entries = manifest["entries"]
    if args.group:
        entries = [row for row in entries if row["group"] == args.group]
    if args.file:
        requested = {str(Path(value)) for value in args.file}
        entries = [row for row in entries if row["path"] in requested]
        if {row["path"] for row in entries} != requested:
            raise ValueError("At least one requested file is not in the frozen group/manifest.")
    if not entries:
        raise ValueError("No manifest entries selected.")
    return entries


def execute(args):
    manifest = load_manifest()
    entries = select(manifest, args)
    summary = {"action": args.action, "selected": len(entries), "applied": args.apply, "processed": 0, "already_in_place": 0, "locations": {"original": 0, "archive": 0}}
    for entry in entries:
        original = safe_path(entry["path"])
        archived = safe_path(entry["path"], archive=True)
        if original.exists() and archived.exists():
            raise FileExistsError(f"Both paths exist; refusing overwrite: {entry['path']}")
        if not original.exists() and not archived.exists():
            raise FileNotFoundError(f"Neither path exists: {entry['path']}")
        current = original if original.exists() else archived
        desired = original if args.action == "restore" else archived
        check_file(current, entry)
        if args.action == "verify":
            summary["locations"]["original" if current == original else "archive"] += 1
        elif current == desired:
            summary["already_in_place"] += 1
        elif args.apply:
            desired.parent.mkdir(parents=True, exist_ok=True)
            safe_path(entry["path"], archive=desired == archived)
            available(current)
            log("move_started", entry, direction=args.action)
            try:
                current.rename(desired)
                log("moved", entry, direction=args.action)
                check_file(desired, entry)
                log("verified", entry, direction=args.action)
            except Exception as error:
                log("failed", entry, direction=args.action, error_type=type(error).__name__)
                raise
        summary["processed"] += 1
        if summary["processed"] % 10 == 0:
            print(json.dumps({"phase": args.action, "processed": summary["processed"], "selected": len(entries)}, ensure_ascii=False), flush=True)
    log("operation_complete", **summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "archive", "restore", "verify"])
    parser.add_argument("--group", choices=sorted(GROUPS))
    parser.add_argument("--file", action="append", help="Exact workspace-relative path from manifest; may be repeated.")
    parser.add_argument("--apply", action="store_true", help="Actually rename files for archive/restore; otherwise validate only.")
    args = parser.parse_args()
    if args.action == "plan":
        if args.group or args.file or args.apply:
            parser.error("plan always freezes the complete reviewed candidate set; do not pass selection or --apply")
        plan()
    else:
        execute(args)


if __name__ == "__main__":
    main()
