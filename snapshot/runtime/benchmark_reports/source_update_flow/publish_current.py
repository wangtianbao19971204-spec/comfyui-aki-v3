"""Prepare/apply an explicitly scoped data-only release with complete rollback.

No source deployment, generation, queue clearing or model downloads are performed.
The spec, backups and receipts are private batch evidence, never Git payloads.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from audit_current import read, safe_file


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def now():
    return datetime.now(timezone.utc).isoformat()


def get(port, route):
    # Loopback service checks must not inherit a workstation HTTP proxy.
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=60)) as connection:
        connection.request("GET", route)
        response = connection.getresponse()
        body = response.read()
        require(response.status == 200, "Local service check returned HTTP " + str(response.status))
        return json.loads(body)


def empty(port):
    state = get(port, "/queue")
    require(not state["queue_running"] and not state["queue_pending"], "Queue is not empty")
    return state


def listeners(port):
    import psutil
    return sorted({c.pid for c in psutil.net_connections(kind="tcp")
                   if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port})


def owner(runtime, port, expected=None):
    import psutil
    ids = listeners(port)
    require(len(ids) == 1, "Expected exactly one service listener")
    process = psutil.Process(ids[0])
    require(Path(process.exe()).resolve() == (runtime / "python/python.exe").resolve(), "Unexpected service executable")
    command = process.cmdline()
    require(Path(process.cwd()).resolve() == (runtime / "ComfyUI").resolve(), "Unexpected service working directory")
    require("main.py" in command or str(runtime / "ComfyUI/main.py") in command, "Unexpected service command")
    record = {"pid": process.pid, "created": process.create_time(), "command": command,
              "cwd": process.cwd()}
    if expected:
        require(record == expected, "Service ownership changed")
    return process, record


def backup_sqlite(source, target):
    require(not target.exists(), "Backup target already exists")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as origin:
        with closing(sqlite3.connect(target)) as destination:
            origin.backup(destination)
            require(destination.execute("pragma integrity_check").fetchone()[0] == "ok", "Invalid SQLite backup")


def fingerprint(path):
    result = {}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        schema = conn.execute("select type,name,tbl_name,sql from sqlite_master order by type,name").fetchall()
        result["schema"] = hashlib.sha256(json.dumps(schema).encode()).hexdigest()
        tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' order by name")]
        for table in tables:
            name = '"' + table.replace('"', '""') + '"'
            columns = [row[1] for row in conn.execute("pragma table_info(" + name + ")")]
            order = ",".join('"' + col.replace('"', '""') + '"' for col in columns)
            digest = hashlib.sha256()
            count = 0
            for row in conn.execute("select * from " + name + " order by " + order):
                encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"),
                                     default=lambda b: {"blob_hex": b.hex()}).encode("utf-8")
                digest.update(encoded + b"\n")
                count += 1
            result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def atomic_copy(source, target):
    temporary = target.with_name(target.name + ".source-sync-" + uuid.uuid4().hex + ".tmp")
    try:
        with source.open("rb") as inp, temporary.open("xb") as out:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        require(sha(source) == sha(temporary), "Copy hash mismatch")
        os.replace(temporary, target)
    finally:
        # Only our unique file; a failed copy must not obstruct group rollback.
        temporary.unlink(missing_ok=True)


def checkpoint(path):
    # mode=rw refuses a missing database instead of creating an empty one.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)) as conn:
        row = conn.execute("pragma wal_checkpoint(TRUNCATE)").fetchone()
        require(row[0] == 0, "SQLite checkpoint is busy")
        require(conn.execute("pragma integrity_check").fetchone()[0] == "ok", "SQLite integrity failure")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            require(suffix != "-wal" or sidecar.stat().st_size == 0, "Nonempty WAL must be preserved")
            sidecar.unlink()


def check_sources(spec):
    for item in spec.get("source_pointers", []):
        parsed = urlsplit(item["url"])
        require(parsed.scheme == "https" and parsed.hostname in {
            "assets.quicktagcloud.com", "novelai.quicktagcloud.com", "prompt-vault-gallery.pages.dev"},
            "Unexpected source pointer host")
        request = Request(item["url"], headers={"User-Agent": "Mozilla/5.0 (ComfyUI source audit)"})
        with urlopen(request, timeout=30) as response:
            require(hashlib.sha256(response.read()).hexdigest() == item["sha256"], "Website release changed")


def prepare(runtime, batch, spec):
    runtime = runtime.resolve()
    require(not batch.resolve().is_relative_to(runtime), "Release evidence must stay outside runtime")
    process, identity = owner(runtime, spec["port"])
    empty(spec["port"])
    check_sources(spec)
    batch.mkdir(parents=True, exist_ok=False)
    backup = batch / "backup"
    backup.mkdir()
    rows = []
    targets = [str(safe_file(runtime, item["runtime_relative"]).resolve()).casefold()
               for item in spec["files"]]
    require(len(set(targets)) == len(targets), "Duplicate deployment target")
    for index, item in enumerate(spec["files"]):
        target = safe_file(runtime, item["runtime_relative"])
        require("/user_data/" in item["runtime_relative"] and target.is_file(), "Only existing user-data files may be replaced")
        source = Path(item["stage_path"]).resolve()
        require(source.is_file() and not source.is_relative_to(runtime), "Stage must be isolated")
        base = backup / (str(index) + "_" + target.name)
        if item["kind"] == "sqlite":
            backup_sqlite(target, base)
            require(fingerprint(base) == fingerprint(Path(item["baseline_path"])), "Live database changed since staging")
        else:
            shutil.copy2(target, base)
            require(sha(target) == sha(base), "Live file changed during backup")
            require(sha(base) == sha(Path(item["baseline_path"])), "Live JSON changed since staging")
        rows.append({**item, "stage_sha256": sha(source), "backup_path": str(base),
                     "backup_sha256": sha(base),
                     "before_fingerprint": fingerprint(base) if item["kind"] == "sqlite" else None,
                     "stage_fingerprint": fingerprint(source) if item["kind"] == "sqlite" else None})
    owner(runtime, spec["port"], identity)
    empty(spec["port"])
    plan = {"schema": "data-source-release/v1", "prepared_at": now(), "runtime": str(runtime),
            "owner": identity, "spec": spec, "files": rows,
            "baseline_index": get(spec["port"], "/prompt_selector/library/index"), "applied": False}
    save(batch / "plan.json", plan)
    print(json.dumps({"prepared": True, "files": len(rows), "plan_sha256": sha(batch / "plan.json")}))


def apply(batch, reviewed_sha):
    require(sha(batch / "plan.json") == reviewed_sha, "Plan review hash mismatch")
    plan = read(batch / "plan.json")
    runtime, spec = Path(plan["runtime"]), plan["spec"]
    require(not (batch / "release_receipt.json").exists(), "Release already attempted; retain its evidence")
    for row in plan["files"]:
        require(sha(Path(row["stage_path"])) == row["stage_sha256"], "Stage changed")
        require(sha(Path(row["backup_path"])) == row["backup_sha256"], "Rollback backup changed")
    for path, expected in spec["bound_receipts"].items():
        require(sha(Path(path)) == expected, "Bound stage evidence changed")
    process, identity = owner(runtime, spec["port"], plan["owner"])
    environment = process.environ()  # Never serialize credential-bearing environment values.
    empty(spec["port"])
    check_sources(spec)
    receipt = {"phase": "prepared", "passed": False, "applied": False, "events": [],
               "plan_sha256": reviewed_sha, "installed_images": []}
    spawned = {}

    def state(phase, **values):
        receipt.update(phase=phase, **values)
        receipt["events"].append({"at": now(), "phase": phase})
        save(batch / "release_receipt.json", receipt)
        print(phase, flush=True)

    def start(label):
        require(not listeners(spec["port"]), "Port occupied before restart")
        with (batch / (label + ".out.log")).open("ab") as out, (batch / (label + ".err.log")).open("ab") as err:
            child = subprocess.Popen(identity["command"], cwd=identity["cwd"], env=environment,
                                     stdout=out, stderr=err, close_fds=True,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        import psutil
        spawned["child"] = child
        spawned["created"] = psutil.Process(child.pid).create_time()
        state(label + "_starting", new_pid=child.pid, new_created=spawned["created"])
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            require(child.poll() is None, "Service exited during restart")
            try:
                current, record = owner(runtime, spec["port"])
                require(current.pid == child.pid, "Unexpected service after restart")
                empty(spec["port"])
                status = get(spec["port"], "/unified-workbench/status")
                require(not status["degraded"] and all(m.get("ready") for m in status["modules"]), "Workbench not ready")
                return record
            except (OSError, RuntimeError, ValueError):
                time.sleep(2)
        raise RuntimeError("Service startup timed out")

    stop_attempted = stopped = replaced = False
    try:
        state("preflight")
        # Images are immutable additions; preexisting different bytes never overwritten.
        for image in spec["images"]:
            source = Path(image["path"])
            target = safe_file(runtime, image["runtime_relative"])
            require(sha(source) == image["sha256"], "Staged image changed")
            if target.exists():
                require(sha(target) == image["sha256"], "Existing preview collision")
            else:
                atomic_copy(source, target)
                receipt["installed_images"].append(image["runtime_relative"])
        owner(runtime, spec["port"], identity)
        empty(spec["port"])
        stop_attempted = True
        process.terminate()
        process.wait(90)
        stopped = True
        require(not listeners(spec["port"]), "Service still listening")
        state("stopped")
        # Checkpoint first, including on rollback, so nonempty WAL is never discarded.
        for row in plan["files"]:
            target = safe_file(runtime, row["runtime_relative"])
            if row["kind"] == "sqlite":
                checkpoint(target)
                require(fingerprint(target) == row["before_fingerprint"], "Database drift before release")
            else:
                require(sha(target) == row["backup_sha256"], "File drift before release")
        for row in plan["files"]:
            # Mark before first replacement so partial failures always restore the group.
            replaced = True
            atomic_copy(Path(row["stage_path"]), safe_file(runtime, row["runtime_relative"]))
        state("data_installed", applied=True)
        record = start("production")
        state("awaiting_acceptance", service=record)
        plan["expected_live_owner"] = record
        from accept_current import verify
        acceptance = verify(plan, batch)
        require(acceptance.get("passed") is True, "Live acceptance did not pass")
        save(batch / "live_acceptance.json", acceptance)
        state("accepted", passed=True, acceptance_sha256=sha(batch / "live_acceptance.json"))
    except BaseException as exc:
        state("failed", error=type(exc).__name__ + ": " + str(exc))
        if stop_attempted:
            import psutil
            child = spawned.get("child")
            if child is not None and child.poll() is None:
                current = psutil.Process(child.pid)
                require(current.create_time() == spawned["created"]
                        and current.cmdline() == identity["command"], "Spawned service identity changed")
                current.terminate()
                current.wait(90)
            # A timeout can occur after termination was sent. Reconcile its
            # actual liveness before restarting or touching any SQLite file.
            try:
                original = psutil.Process(identity["pid"])
                original_alive = original.is_running() and original.create_time() == identity["created"]
            except psutil.NoSuchProcess:
                original_alive = False
            require(not original_alive, "Original service remains alive after stop attempt; rollback not safe")
            require(not listeners(spec["port"]), "Unowned rollback listener")
            if replaced:
                for row in plan["files"]:
                    target = safe_file(runtime, row["runtime_relative"])
                    if row["kind"] == "sqlite":
                        checkpoint(target)
                    atomic_copy(Path(row["backup_path"]), target)
            record = start("rollback")
            state("rolled_back", applied=False, service=record)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--runtime", required=True, type=Path)
    prep.add_argument("--batch", required=True, type=Path)
    prep.add_argument("--spec", required=True, type=Path)
    release = commands.add_parser("apply")
    release.add_argument("--batch", required=True, type=Path)
    release.add_argument("--review-sha256", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.runtime, args.batch, read(args.spec))
    else:
        apply(args.batch, args.review_sha256)


if __name__ == "__main__":
    main()
