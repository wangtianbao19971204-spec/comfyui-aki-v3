"""Archive original local Git databases and construct credential-safe histories.

Only ``backup`` writes outside a new bare repository. It copies, never modifies,
the original Git databases. ``redact`` writes exact Git objects into a fresh
repository, so commits untouched by the known secret retain their original IDs.
No command modifies the maintenance repository refs or contacts a remote.
"""
import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zlib


ENV = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
CORE_SECRET_BLOB = "8ab57bb26c59abeb2b3acab3a707b420014801d9"
CORE_SECRET_VALUE_SHA256 = "1379f7aa87af53d92dc3358bd28381062275ef61049ead78401f01100e2a7478"
KNOWN_REDACTIONS = {
    CORE_SECRET_BLOB: {
        "value_sha256": CORE_SECRET_VALUE_SHA256,
        "replacement": b"REDACTED_API_KEY",
        "expected_occurrences": 1,
    }
}
MAIN_REDACTIONS = {
    "26c0537843ec84dd07c2d2e5d7d80d02ce25b8a5": {
        "value_sha256": "24946ae845eb1272521808b7f8645f531e84cbb6fb03b40479d2c12fcf32f4fa",
        "replacement": b"", "expected_occurrences": 1,
    },
    "681c7328b35b15d8463ab8f4479d1d086632b549": {
        "value_sha256": "24946ae845eb1272521808b7f8645f531e84cbb6fb03b40479d2c12fcf32f4fa",
        "replacement": b"", "expected_occurrences": 2,
    },
}
SECRET_ASSIGNMENT = re.compile(rb"\b(?:api_key|public_token|access_token)\s*=\s*([\"'])([^\"'\r\n]+)\1")
QUERY_TOKEN = re.compile(rb"[?&](?:access_token|api_key|token)=([^&#\s\"'<>]+)")


def git(git_dir, *args, data=None, check=True):
    result = subprocess.run(
        ["git", f"--git-dir={git_dir}", *args],
        input=data, capture_output=True, env=ENV,
    )
    if check and result.returncode:
        raise RuntimeError(f"Git {args[0]} failed with exit {result.returncode}")
    return result


def git_lines(git_dir, *args, data=None):
    return git(git_dir, *args, data=data).stdout.decode("utf-8", "replace").splitlines()


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def has_reparse(path):
    metadata = path.lstat()
    return path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def validate_new_path(path, parent=None):
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("Destination already exists")
    for ancestor in path.parents:
        if ancestor.exists() and has_reparse(ancestor):
            raise ValueError("Destination traverses a link or reparse point")
    path = path.resolve()
    if parent is not None and not path.is_relative_to(Path(parent).resolve()):
        raise ValueError("Destination is outside its permitted parent")
    return path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory_files(directory):
    records = {}
    for current, folders, names in os.walk(directory):
        for name in folders + names:
            file = Path(current) / name
            if has_reparse(file):
                raise ValueError("Git archive contains a link or reparse point")
        for name in names:
            file = Path(current) / name
            records[file.relative_to(directory).as_posix()] = {
                "size": file.stat().st_size, "sha256": sha256(file),
            }
    return records


def backup_originals(runtime, destination):
    runtime = Path(runtime).resolve()
    destination = validate_new_path(destination, runtime / "maintenance/private-archives")
    repositories = {
        "core": runtime / "ComfyUI/.git",
        "workbench": runtime / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/.git",
    }
    for source in repositories.values():
        if not source.is_dir() or has_reparse(source):
            raise ValueError("Expected a real source .git directory")
        if (source / "index.lock").exists() or (source / "packed-refs.lock").exists():
            raise ValueError("Source Git operation is active")
    destination.mkdir(parents=True)
    receipt = {"schema": 1, "private_archive": True, "original_repositories_modified": False, "repositories": {}}
    for name, source in repositories.items():
        target = destination / f"{name}.git"
        receipt["repositories"][name] = backup_single(source, target, destination / f"{name}-private-file-manifest.json")
    save_new(destination / "PRIVATE_ARCHIVE_RECEIPT.json", receipt)
    return receipt


def backup_single(source, destination, manifest_path):
    source = Path(source).resolve()
    destination = validate_new_path(destination)
    manifest_path = validate_new_path(manifest_path)
    if destination.is_relative_to(source):
        raise ValueError("Git backup cannot be inside its source")
    if not source.is_dir() or has_reparse(source):
        raise ValueError("Expected a real source Git directory")
    if (source / "index.lock").exists() or (source / "packed-refs.lock").exists():
        raise ValueError("Source Git operation is active")
    before = inventory_files(source)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    after = inventory_files(source)
    copied = inventory_files(destination)
    if before != after or before != copied:
        raise RuntimeError("Source changed or private Git backup failed byte verification")
    save_new(manifest_path, before)
    return {
        "head": git(source, "rev-parse", "HEAD").stdout.decode().strip(),
        "files": len(before), "bytes": sum(x["size"] for x in before.values()),
        "byte_identical": True,
    }


def object_metadata(source):
    records = {}
    for line in git_lines(source, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype) %(objectsize)"):
        oid, kind, size = line.split()
        records[oid] = {"type": kind, "size": int(size)}
    return records


def object_stream(source, oids):
    process = subprocess.Popen(
        ["git", f"--git-dir={source}", "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV,
    )
    try:
        for oid in oids:
            process.stdin.write(oid.encode("ascii") + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().strip().split()
            if len(header) != 3:
                raise RuntimeError("Invalid Git object stream header")
            size = int(header[2])
            payload = process.stdout.read(size)
            if process.stdout.read(1) != b"\n" or len(payload) != size:
                raise RuntimeError("Truncated Git object stream")
            yield oid, header[1].decode("ascii"), payload
    finally:
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
        process.wait()


def put_object(destination, kind, payload):
    raw = kind.encode("ascii") + b" " + str(len(payload)).encode("ascii") + b"\0" + payload
    oid = hashlib.sha1(raw).hexdigest()
    path = destination / "objects" / oid[:2] / oid[2:]
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        with path.open("xb") as stream:
            stream.write(zlib.compress(raw))
    return oid


def tree_entries(payload):
    position = 0
    while position < len(payload):
        end = payload.index(b"\0", position)
        header = payload[position:end + 1]
        oid = payload[end + 1:end + 21]
        if len(oid) != 20:
            raise ValueError("Malformed SHA-1 tree")
        mode = header.split(b" ", 1)[0]
        yield header, oid.hex(), mode
        position = end + 21


def redact_blob(payload, specification):
    candidates = {match.group(2) for match in SECRET_ASSIGNMENT.finditer(payload)}
    candidates.update(match.group(1) for match in QUERY_TOKEN.finditer(payload))
    matches = [value for value in candidates if hashlib.sha256(value).hexdigest() == specification["value_sha256"]]
    if len(matches) != 1:
        raise ValueError("Known secret candidate count did not match")
    secret = matches[0]
    if payload.count(secret) != specification["expected_occurrences"]:
        raise ValueError("Known secret occurrence count did not match")
    result = payload.replace(secret, specification["replacement"])
    if secret in result:
        raise ValueError("Known secret still present after redaction")
    return result


def header_records(header):
    records = []
    for line in header.split(b"\n"):
        if line.startswith(b" ") and records:
            records[-1] += b"\n" + line
        else:
            records.append(line)
    return records


def rewrite_commit(payload, tree_map, commit_map):
    header, message = payload.split(b"\n\n", 1)
    records = header_records(header)
    rewritten = []
    changed = False
    for record in records:
        if record.startswith(b"tree "):
            new = b"tree " + tree_map[record[5:].decode("ascii")].encode("ascii")
        elif record.startswith(b"parent "):
            new = b"parent " + commit_map[record[7:].decode("ascii")].encode("ascii")
        else:
            new = record
        changed |= new != record
        rewritten.append(new)
    stripped = []
    if changed:
        retained = []
        for record in rewritten:
            name = record.split(b" ", 1)[0]
            if name in {b"gpgsig", b"gpgsig-sha256", b"mergetag"}:
                stripped.append(name.decode("ascii"))
            else:
                retained.append(record)
        rewritten = retained
    return b"\n".join(rewritten) + b"\n\n" + message, stripped


def source_refs(source):
    records = []
    for line in git_lines(source, "for-each-ref", "--format=%(refname)%09%(objectname)%09%(objecttype)%09%(*objectname)%09%(symref)"):
        name, oid, kind, peeled, symbolic = line.split("\t")
        records.append({"ref": name, "oid": oid, "type": kind, "peeled": peeled or None, "symbolic": symbolic or None})
    return records


def build_public_repository(source, destination, report_path, redactions=None):
    source = Path(source).resolve()
    destination = validate_new_path(destination)
    report_path = validate_new_path(report_path)
    redactions = redactions or {}
    if git(source, "rev-parse", "--show-object-format").stdout.strip() != b"sha1":
        raise ValueError("Only SHA-1 repositories are supported")
    metadata = object_metadata(source)
    if not set(redactions).issubset(metadata):
        raise ValueError("Required redaction object is missing")
    refs = source_refs(source)
    commits = {oid for oid, item in metadata.items() if item["type"] == "commit"}
    reachable_commits = set(git_lines(source, "rev-list", "--all"))
    reflog_commits = set(git_lines(source, "rev-list", "--all", "--reflog"))
    graph = git_lines(source, "rev-list", "--topo-order", "--reverse", "--parents", "--stdin", data=("\n".join(sorted(commits)) + "\n").encode("ascii"))
    parents = {parts[0]: parts[1:] for parts in (line.split() for line in graph)}
    tips = commits - {parent for items in parents.values() for parent in items}
    recovered_tips = tips - reachable_commits
    include_objects = set()
    for line in git_lines(source, "rev-list", "--objects", "--stdin", data=("\n".join(sorted(commits)) + "\n").encode("ascii")):
        include_objects.add(line.partition(" ")[0])
    # Annotated tags may refer to a tree/blob, not only to commits.
    for line in git_lines(source, "rev-list", "--objects", "--all"):
        include_objects.add(line.partition(" ")[0])
    include_objects.update(oid for oid, item in metadata.items() if item["type"] == "tag")
    if not set(redactions).issubset(include_objects):
        raise ValueError("Required redaction object is not in the exported graph")
    destination.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", str(destination)], check=True, capture_output=True, env=ENV)
    object_map = {}
    raw_trees = {}
    raw_commits = {}
    raw_tags = {}
    redaction_records = []
    written = 0
    for oid, kind, payload in object_stream(source, sorted(include_objects)):
        if kind == "blob":
            if oid in redactions:
                payload = redact_blob(payload, redactions[oid])
            new_oid = put_object(destination, kind, payload)
            object_map[oid] = new_oid
            if oid in redactions:
                redaction_records.append({"old_blob": oid, "new_blob": new_oid, "replacement": redactions[oid]["replacement"].decode("ascii"), "occurrences": redactions[oid]["expected_occurrences"]})
        elif kind == "tree":
            raw_trees[oid] = payload
        elif kind == "commit":
            raw_commits[oid] = payload
        elif kind == "tag":
            raw_tags[oid] = payload
        written += 1
        if written % 10000 == 0:
            print(json.dumps({"phase": "object_read", "objects": written}), flush=True)

    def rewrite_tree(oid):
        if oid in object_map:
            return object_map[oid]
        pieces = []
        for prefix, child, mode in tree_entries(raw_trees[oid]):
            if mode == b"40000":
                new_child = rewrite_tree(child)
            elif mode == b"160000":
                new_child = child
            else:
                new_child = object_map[child]
            pieces.append(prefix + bytes.fromhex(new_child))
        object_map[oid] = put_object(destination, "tree", b"".join(pieces))
        return object_map[oid]

    for oid in raw_trees:
        rewrite_tree(oid)
    commit_map = {}
    stripped_signatures = []
    for line in graph:
        oid = line.split()[0]
        rewritten, stripped = rewrite_commit(raw_commits[oid], object_map, commit_map)
        commit_map[oid] = put_object(destination, "commit", rewritten)
        object_map[oid] = commit_map[oid]
        if stripped:
            stripped_signatures.append({"old_commit": oid, "new_commit": commit_map[oid], "removed_headers": stripped})

    def rewrite_tag(oid):
        if oid in object_map:
            return object_map[oid]
        payload = raw_tags[oid]
        first_line, rest = payload.split(b"\n", 1)
        target = first_line.removeprefix(b"object ").decode("ascii")
        new_target = rewrite_tag(target) if target in raw_tags else object_map[target]
        rewritten = b"object " + new_target.encode("ascii") + b"\n" + rest
        if target != new_target:
            rewritten = re.sub(rb"\n-----BEGIN PGP SIGNATURE-----.*?-----END PGP SIGNATURE-----\n?", b"\n", rewritten, flags=re.S)
        object_map[oid] = put_object(destination, "tag", rewritten)
        return object_map[oid]

    for oid in raw_tags:
        rewrite_tag(oid)
    ref_commands = []
    ref_map = []
    for record in refs:
        new_oid = object_map[record["oid"]]
        ref_map.append(dict(record, public_oid=new_oid))
        if not record["symbolic"]:
            ref_commands.append(f"create {record['ref']} {new_oid}")
    for oid in sorted(recovered_tips):
        ref_commands.append(f"create refs/archive-recovered/{oid} {commit_map[oid]}")
    git(destination, "update-ref", "--stdin", data=("\n".join(ref_commands) + "\n").encode("utf-8"))
    for record in refs:
        if record["symbolic"]:
            git(destination, "symbolic-ref", record["ref"], record["symbolic"])
    symbolic_head = git(source, "symbolic-ref", "-q", "HEAD", check=False)
    if symbolic_head.returncode == 0:
        git(destination, "symbolic-ref", "HEAD", symbolic_head.stdout.decode().strip())
    else:
        head = git(source, "rev-parse", "HEAD").stdout.decode().strip()
        git(destination, "update-ref", "HEAD", commit_map[head])
    actual_commits = set(git_lines(destination, "rev-list", "--all"))
    if actual_commits != set(commit_map.values()) or len(commit_map) != len(commits) or len(actual_commits) != len(commits):
        raise RuntimeError("Public commit coverage check failed")
    actual_objects = object_metadata(destination)
    if set(redactions) & set(actual_objects):
        raise RuntimeError("Original credential-bearing blob exists in public repository")
    git(destination, "fsck", "--full", "--strict")
    report = {
        "schema": 1, "component": source.name.removesuffix(".git"),
        "source_original_commit_count": len(commits),
        "source_ref_reachable_commits": len(reachable_commits),
        "source_reflog_only_commits": len(reflog_commits - reachable_commits),
        "source_fully_unreachable_commits": len(commits - reachable_commits - reflog_commits),
        "source_ref_counts": dict(collections.Counter(x["ref"].split("/")[1] for x in refs)),
        "public_commit_count": len(actual_commits),
        "unchanged_commit_ids": sum(old == new for old, new in commit_map.items()),
        "rewritten_commit_ids": sum(old != new for old, new in commit_map.items()),
        "original_commit_ids": sorted(commits),
        "commit_map": commit_map, "refs": ref_map,
        "recovered_tips": {old: commit_map[old] for old in sorted(recovered_tips)},
        "all_graph_tips": {old: commit_map[old] for old in sorted(tips)},
        "redactions": redaction_records,
        "stripped_invalid_signatures": stripped_signatures,
        "all_commit_metadata_and_messages_preserved": True,
        "parent_order_preserved_via_commit_map": True,
        "known_credential_blobs_absent_from_entire_object_database": True,
        "fsck_strict_passed": True,
        "limitations": [
            "Author, committer, timestamps, encoding and message are preserved; signatures of rewritten commits cannot remain valid and are listed if removed.",
            "All original objects and reflogs remain only in the separate private archive.",
            "This exact redaction is not a substitute for independent public-history credential scanning.",
        ],
    }
    save_new(report_path, report)
    return report


def verify_mapping(source, destination, report):
    source = Path(source)
    destination = Path(destination)
    mapping = report["commit_map"]
    old_commits = {oid: payload for oid, _, payload in object_stream(source, sorted(mapping))}
    new_commits = {oid: payload for oid, _, payload in object_stream(destination, sorted(set(mapping.values())))}
    blob_mapping = {item["old_blob"]: item["new_blob"] for item in report["redactions"]}
    checked_tree_pairs = set()

    def check_tree(old, new):
        if old == new or (old, new) in checked_tree_pairs:
            return
        checked_tree_pairs.add((old, new))
        old_entries = list(tree_entries(git(source, "cat-file", "tree", old).stdout))
        new_entries = list(tree_entries(git(destination, "cat-file", "tree", new).stdout))
        if len(old_entries) != len(new_entries):
            raise RuntimeError("Tree entry count changed during redaction")
        for (old_name, old_oid, old_mode), (new_name, new_oid, new_mode) in zip(old_entries, new_entries):
            if old_name != new_name or old_mode != new_mode:
                raise RuntimeError("Tree names, order or modes changed during redaction")
            if old_mode == b"40000":
                check_tree(old_oid, new_oid)
            elif new_oid != blob_mapping.get(old_oid, old_oid):
                raise RuntimeError("Unexpected content change outside known credential blobs")

    for old, new in mapping.items():
        old_header, old_message = old_commits[old].split(b"\n\n", 1)
        new_header, new_message = new_commits[new].split(b"\n\n", 1)
        if old_message != new_message:
            raise RuntimeError("Commit message changed")
        old_records = header_records(old_header)
        new_records = header_records(new_header)
        old_parents = [record[7:].decode() for record in old_records if record.startswith(b"parent ")]
        new_parents = [record[7:].decode() for record in new_records if record.startswith(b"parent ")]
        if [mapping[parent] for parent in old_parents] != new_parents:
            raise RuntimeError("Parent order or ancestry changed")
        ignored_headers = {b"tree", b"parent"}
        if old != new:
            ignored_headers |= {b"gpgsig", b"gpgsig-sha256", b"mergetag"}
        old_metadata = [record for record in old_records if record.split(b" ", 1)[0] not in ignored_headers]
        new_metadata = [record for record in new_records if record.split(b" ", 1)[0] not in ignored_headers]
        if old_metadata != new_metadata:
            raise RuntimeError("Commit metadata changed")
        old_tree = next(record[5:].decode() for record in old_records if record.startswith(b"tree "))
        new_tree = next(record[5:].decode() for record in new_records if record.startswith(b"tree "))
        check_tree(old_tree, new_tree)
    refs = {item["ref"]: item for item in source_refs(destination)}
    for old_ref in report["refs"]:
        if refs[old_ref["ref"]]["oid"] != old_ref["public_oid"]:
            raise RuntimeError("Original ref mapping does not match mirror")
    for oid in blob_mapping:
        if git(destination, "cat-file", "-e", oid, check=False).returncode == 0:
            raise RuntimeError("Original credential blob present")
    if set(git_lines(destination, "rev-list", "--all")) != set(mapping.values()):
        raise RuntimeError("Reachable public commits do not exactly match mapping")
    return {
        "schema": 1, "commits_verified": len(mapping),
        "changed_tree_pairs_verified": len(checked_tree_pairs),
        "refs_verified": len(report["refs"]),
        "messages_metadata_and_parent_order_preserved": True,
        "only_known_blob_changes": True,
        "original_secret_blobs_absent": True,
        "public_commit_coverage_exact": True,
    }


def aggregate_history(public_git, report, receipt_path, parent_limit=64):
    """Add an empty-tree archive branch to an already verified bare mirror."""
    public_git = Path(public_git).resolve()
    receipt_path = validate_new_path(receipt_path)
    if git(public_git, "rev-parse", "--is-bare-repository").stdout.strip() != b"true":
        raise ValueError("Aggregation is restricted to an isolated bare mirror")
    if not 2 <= parent_limit <= 64:
        raise ValueError("Parent limit must be between 2 and 64")
    archive_ref = "refs/heads/history-archive"
    if git(public_git, "show-ref", "--verify", "--quiet", archive_ref, check=False).returncode == 0:
        raise ValueError("Archive ref already exists")
    expected = set(report["commit_map"].values())
    tips = sorted(set(report["all_graph_tips"].values()))
    if not tips or any(not re.fullmatch(r"[0-9a-f]{40}", oid) for oid in tips):
        raise ValueError("Invalid public graph tips")
    tip_payload = ("\n".join(tips) + "\n").encode("ascii")
    if set(git_lines(public_git, "rev-list", "--stdin", data=tip_payload)) != expected:
        raise RuntimeError("Archive tips do not exactly cover the mapped history")
    if set(git_lines(public_git, "rev-list", "--all")) != expected:
        raise RuntimeError("Mirror changed since original mapping verification")
    for item in report["redactions"]:
        if git(public_git, "cat-file", "-e", item["old_blob"], check=False).returncode == 0:
            raise RuntimeError("Credential-bearing original blob is present")
    empty_tree = put_object(public_git, "tree", b"")
    moment = datetime.now(timezone.utc)
    identity = f"ComfyUI Maintenance <maintenance@local.invalid> {int(moment.timestamp())} +0000".encode("ascii")
    current = tips
    created = []
    level = 1
    while len(current) > 1 or not created:
        groups = [current[start:start + parent_limit] for start in range(0, len(current), parent_limit)]
        next_level = []
        for number, parents in enumerate(groups, 1):
            header = b"tree " + empty_tree.encode("ascii")
            header += b"".join(b"\nparent " + parent.encode("ascii") for parent in parents)
            header += b"\nauthor " + identity + b"\ncommitter " + identity
            message = (
                f"Archive legacy {report['component']} history (level {level}, group {number}/{len(groups)})\n\n"
                f"Preserve {len(parents)} parent histories without changing runtime files.\n"
                f"The archive covers {len(expected)} credential-redacted legacy commits and {len(tips)} source graph tips.\n"
                "This empty-tree commit is provenance only, not a runnable ComfyUI revision.\n"
                "Original private objects and old-to-public mappings are kept separately.\n"
            ).encode("utf-8")
            oid = put_object(public_git, "commit", header + b"\n\n" + message)
            created.append({"commit": oid, "level": level, "parent_count": len(parents)})
            next_level.append(oid)
        current = next_level
        level += 1
    archive = current[0]
    reachable = set(git_lines(public_git, "rev-list", archive))
    if reachable != expected | {item["commit"] for item in created}:
        raise RuntimeError("Aggregate archive coverage differs from original history")
    git(public_git, "update-ref", "--stdin", data=f"create {archive_ref} {archive}\n".encode("ascii"))
    git(public_git, "fsck", "--full", "--strict")
    result = {
        "schema": 1, "created_at": moment.isoformat(), "archive_ref": archive_ref,
        "archive_commit": archive, "tree": empty_tree, "source_graph_tips": len(tips),
        "source_public_commits": len(expected), "aggregate_commits_created": len(created),
        "archive_reachable_commits": len(reachable), "maximum_parent_count": max(item["parent_count"] for item in created) if created else 0,
        "all_mapped_commits_reachable": True, "original_refs_and_tags_unchanged": True,
        "fsck_strict_passed": True, "created_commits": created,
    }
    save_new(receipt_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    archive = commands.add_parser("backup")
    archive.add_argument("--runtime", type=Path, required=True)
    archive.add_argument("--destination", type=Path, required=True)
    archive_main = commands.add_parser("backup-main")
    archive_main.add_argument("--runtime", type=Path, required=True)
    archive_main.add_argument("--destination", type=Path, required=True)
    redact = commands.add_parser("redact")
    redact.add_argument("--source-git", type=Path, required=True)
    redact.add_argument("--destination", type=Path, required=True)
    redact.add_argument("--report", type=Path, required=True)
    redact.add_argument("--component", choices=["core", "workbench", "main"], required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--source-git", type=Path, required=True)
    verify.add_argument("--public-git", type=Path, required=True)
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--receipt", type=Path, required=True)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--public-git", type=Path, required=True)
    aggregate.add_argument("--report", type=Path, required=True)
    aggregate.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        result = backup_originals(args.runtime, args.destination)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "backup-main":
        runtime = args.runtime.resolve()
        destination = validate_new_path(args.destination, runtime / "maintenance/private-archives")
        result = backup_single(runtime / "maintenance/comfyui/.git", destination, destination.with_name("main-private-file-manifest.json"))
        save_new(destination.with_name("main-private-receipt.json"), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "verify":
        report = json.loads(args.report.read_text(encoding="utf-8"))
        result = verify_mapping(args.source_git, args.public_git, report)
        save_new(args.receipt, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "aggregate":
        report = json.loads(args.report.read_text(encoding="utf-8"))
        result = aggregate_history(args.public_git, report, args.receipt)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        rules = {"core": KNOWN_REDACTIONS, "main": MAIN_REDACTIONS, "workbench": {}}[args.component]
        result = build_public_repository(args.source_git, args.destination, args.report, rules)
        print(json.dumps({key: result[key] for key in ["source_original_commit_count", "public_commit_count", "unchanged_commit_ids", "rewritten_commit_ids", "redactions", "fsck_strict_passed"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
