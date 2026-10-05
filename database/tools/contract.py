"""Check the public database contract and create disposable, isolated examples.

This tool never accepts a running database path. It writes only a NEW named
directory below this checkout's ignored local/database-checks directory.
"""
from __future__ import annotations

import argparse
import codecs
import contextlib
import hashlib
import json
import re
import sqlite3
from pathlib import Path, PurePosixPath


REPO = Path(__file__).resolve().parents[2]
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
IDENTIFIER = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\Z")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def confined(root: Path, relative: str) -> Path:
    """Reject Windows drives, traversal, links/junctions and ambiguous paths."""
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise ValueError("Only portable relative paths are accepted")
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(p in {"", ".", ".."} for p in relative.split("/")):
        raise ValueError("Invalid relative path")
    root = root.resolve()
    path = root
    for part in parts:
        path = path / part
        try:
            is_reparse_point = bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
        except FileNotFoundError:
            is_reparse_point = False
        if path.is_symlink() or is_reparse_point:
            raise ValueError("Linked paths are not accepted")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Path escapes its authorized directory")
    return path


def sandbox(repo: Path, name: str) -> Path:
    if not NAME.fullmatch(name):
        raise ValueError("Use a simple example name; paths are not accepted")
    if name.casefold() in {"con", "prn", "aux", "nul", *(f"com{x}" for x in range(1, 10)), *(f"lpt{x}" for x in range(1, 10))}:
        raise ValueError("Reserved device name")
    return confined(repo, "local/database-checks/" + name)


def statements(lines):
    pending = ""
    for line in lines:
        pending += line
        if len(pending) > 64 * 1024 * 1024:
            raise ValueError("Unreasonably large SQL statement")
        if sqlite3.complete_statement(pending):
            yield pending.strip()
            pending = ""
    if pending.strip():
        raise ValueError("Incomplete SQL statement")


def schema_rows(conn):
    result = []
    for kind, name, table, sql in conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ):
        result.append({"type": kind, "name": name, "table": table, "sql": sql.strip().rstrip(";")})
    return result


def schema_digest(conn):
    return digest(json.dumps(schema_rows(conn), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8"))


def row_counts(conn):
    return {row["name"]: conn.execute('SELECT COUNT(*) FROM "' + row["name"].replace('"', '""') + '"').fetchone()[0]
            for row in schema_rows(conn) if row["type"] == "table"}


def execute_ddl(conn, sql):
    """No ATTACH, extension loading, external reads or data-copy statements."""
    for statement in statements(sql.splitlines(keepends=True)):
        if not re.match(r"CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX|TRIGGER|VIEW)\b", statement, re.I):
            raise ValueError("Baseline files must contain CREATE definitions only")
        # The connection is in-memory or a brand-new isolated file. A baseline
        # is declarative; rejecting AS SELECT prevents implicit data inserts.
        if re.match(r"CREATE\s+TABLE\b", statement, re.I) and re.search(r"\bAS\s+SELECT\b", statement, re.I):
            raise ValueError("CREATE TABLE AS SELECT is not a schema baseline")
        conn.execute(statement)


def seed(conn, fixture):
    for table, rows in fixture["tables"].items():
        if not IDENTIFIER.fullmatch(table):
            raise ValueError("Invalid fixture table")
        for row in rows:
            fields = list(row)
            if not fields or any(not IDENTIFIER.fullmatch(field) for field in fields):
                raise ValueError("Invalid fixture column")
            names = ",".join('"' + field + '"' for field in fields)
            conn.execute('INSERT INTO "' + table + '" (' + names + ') VALUES (' +
                         ",".join("?" for _ in fields) + ")", tuple(row[field] for field in fields))


def load_contract(repo: Path):
    contract = read_json(confined(repo, "database/contract.json"))
    plan = read_json(confined(repo, "database/migrations/index.json"))
    if contract["contract_version"] != 1 or plan["format"] != 1:
        raise ValueError("Unsupported contract format")
    if plan["current_version"] != contract["baseline_version"] or plan["current_version"] != 1:
        raise ValueError("Implement and review a migration runner before adding another version")
    if len(plan["migrations"]) != 1 or plan["migrations"][0]["version"] != 1:
        raise ValueError("Invalid baseline migration plan")
    listed = plan["migrations"][0]["schemas"]
    if listed != {key: value["schema"] for key, value in contract["databases"].items()}:
        raise ValueError("Migration plan and database contract disagree")
    for key, item in contract["databases"].items():
        if not IDENTIFIER.fullmatch(key) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*\.db", item["filename"]):
            raise ValueError("Invalid database identity")
        for field in ("schema", "fixture"):
            payload = confined(repo, item[field]).read_bytes()
            if digest(payload) != item[field + "_sha256"]:
                raise ValueError(f"Contract content hash mismatch: {key}/{field}")
    return contract


def verified_dump_ddl(snapshot: Path, entry):
    """Stream checked SQL chunks, return DDL only; never execute source rows."""
    whole = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8")()
    byte_count = 0

    def lines():
        nonlocal byte_count
        tail = ""
        for part in entry["parts"]:
            relative = str(PurePosixPath(entry["path"]) / part["path"])
            payload = confined(snapshot, relative).read_bytes()
            if len(payload) != part["bytes"] or digest(payload) != part["sha256"]:
                raise ValueError("Snapshot SQL chunk hash mismatch")
            whole.update(payload)
            byte_count += len(payload)
            chunks = (tail + decoder.decode(payload)).split("\n")
            tail = chunks.pop()
            yield from (line + "\n" for line in chunks)
        tail += decoder.decode(b"", final=True)
        if tail:
            yield tail

    ddl = [stmt for stmt in statements(lines()) if stmt.upper().startswith("CREATE ")]
    if whole.hexdigest() != entry["sql_sha256"] or byte_count != entry["sql_bytes"]:
        raise ValueError("Snapshot complete SQL hash mismatch")
    return "\n".join(ddl) + "\n"


def check(repo: Path = REPO, against_snapshot: bool = False):
    contract = load_contract(repo)
    entries = {}
    if against_snapshot:
        manifest = read_json(confined(repo, "snapshot/manifest.json"))
        entries = {item["source"]: item for item in manifest["files"] if item["kind"] == "sqlite_sql"}
    result = {}
    for key, item in contract["databases"].items():
        with contextlib.closing(sqlite3.connect(":memory:")) as conn:
            execute_ddl(conn, confined(repo, item["schema"]).read_text(encoding="utf-8"))
            if schema_digest(conn) != item["schema_fingerprint"]:
                raise ValueError(f"Schema fingerprint mismatch: {key}")
            counts = row_counts(conn)
            if any(counts.values()):
                raise ValueError("Schema baseline contains production rows")
            seed(conn, read_json(confined(repo, item["fixture"])))
            if row_counts(conn) != item["fixture_expected_rows"]:
                raise ValueError(f"Fixture/trigger row counts differ: {key}")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(f"Fixture integrity error: {key}")
        if against_snapshot:
            entry = entries.get(item["source_path"])
            if not entry or entry["sql_sha256"] != item["source_sql_sha256"]:
                raise ValueError(f"Source contract needs an explicit re-baseline: {key}")
            source_ddl = verified_dump_ddl(confined(repo, "snapshot"), entry)
            with contextlib.closing(sqlite3.connect(":memory:")) as conn:
                execute_ddl(conn, source_ddl)
                if schema_digest(conn) != item["schema_fingerprint"]:
                    raise ValueError(f"Baseline differs from accepted source DDL: {key}")
        result[key] = {"tables": len(counts), "source_ddl_verified": against_snapshot,
                       "fixture_expected_rows": item["fixture_expected_rows"]}
    return {"pass": True, "baseline_version": contract["baseline_version"], "databases": result}


def initialize(name: str, fixtures: bool = False, repo: Path = REPO):
    destination = sandbox(repo, name)
    if destination.exists():
        raise FileExistsError("Refusing to overwrite an existing isolated directory")
    check(repo)
    contract = load_contract(repo)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()  # No exist_ok: a competing caller must not overwrite.
    receipt = {"format": 1, "purpose": "isolated_database_contract_example", "fixtures": fixtures,
               "baseline_version": contract["baseline_version"], "databases": {}}
    for key, item in contract["databases"].items():
        database = confined(destination, item["filename"])
        with database.open("xb"):
            pass
        with contextlib.closing(sqlite3.connect(str(database))) as conn:
            execute_ddl(conn, confined(repo, item["schema"]).read_text(encoding="utf-8"))
            if fixtures:
                seed(conn, read_json(confined(repo, item["fixture"])))
            conn.commit()
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(f"Isolated integrity error: {key}")
            receipt["databases"][key] = {"filename": item["filename"],
                "schema_fingerprint": schema_digest(conn), "rows": row_counts(conn)}
        receipt["databases"][key]["sha256"] = digest(database.read_bytes())
    with confined(destination, "DATABASE_RECEIPT.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return verify(name, repo)


def verify(name: str, repo: Path = REPO):
    destination = sandbox(repo, name)
    contract = load_contract(repo)
    receipt = read_json(confined(destination, "DATABASE_RECEIPT.json"))
    if receipt.get("purpose") != "isolated_database_contract_example" or receipt.get("baseline_version") != contract["baseline_version"]:
        raise ValueError("Not a matching isolated database receipt")
    if set(receipt["databases"]) != set(contract["databases"]):
        raise ValueError("Receipt database list mismatch")
    for key, item in contract["databases"].items():
        recorded = receipt["databases"][key]
        if recorded["filename"] != item["filename"]:
            raise ValueError("Receipt database filename mismatch")
        path = confined(destination, item["filename"])
        if digest(path.read_bytes()) != recorded["sha256"]:
            raise ValueError(f"Isolated database bytes changed: {key}")
        with contextlib.closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(f"Isolated integrity error: {key}")
            if schema_digest(conn) != item["schema_fingerprint"]:
                raise ValueError(f"Isolated schema mismatch: {key}")
            expected = item["fixture_expected_rows"] if receipt["fixtures"] else {table: 0 for table in item["fixture_expected_rows"]}
            if row_counts(conn) != expected or row_counts(conn) != recorded["rows"]:
                raise ValueError(f"Isolated row counts changed: {key}")
    return {"pass": True, "name": name, "fixtures": receipt["fixtures"],
            "baseline_version": contract["baseline_version"], "database_count": len(contract["databases"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    checker = commands.add_parser("check")
    checker.add_argument("--against-snapshot", action="store_true")
    creator = commands.add_parser("init")
    creator.add_argument("--name", required=True)
    creator.add_argument("--fixtures", action="store_true")
    verifier = commands.add_parser("verify")
    verifier.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        if args.command == "check":
            result = check(against_snapshot=args.against_snapshot)
        elif args.command == "init":
            result = initialize(args.name, args.fixtures)
        else:
            result = verify(args.name)
    except (ValueError, OSError, sqlite3.Error, KeyError) as error:
        # Never include row contents or SQL statement values in diagnostic output.
        raise SystemExit(f"Database contract check failed ({type(error).__name__}): {str(error) if not isinstance(error, sqlite3.Error) else 'SQLite rejected the contract; inspect the checked-in schema locally'}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
