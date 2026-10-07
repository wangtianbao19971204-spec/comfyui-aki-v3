"""核对功能目录、说明链接与实现、测试、示例的对应关系。

检查工作树或真实暂存区，不写入部署文件。规则见 docs/technical/README.md。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import unicodedata

REPO = Path(__file__).resolve().parent.parent
CATALOG = "docs/technical/catalog.json"
SOURCE_PREFIXES = ("snapshot/runtime/", "snapshot/library/", "snapshot/inventory/", "scripts/",
                   "database/", "tests/", "governance/", "examples/", ".githooks/", ".github/")
ARCHIVE = "docs/technical/archive"
ARCHIVE_REGISTRY = "governance/technical-archive.json"
ARCHIVE_README = ARCHIVE + "/README.md"
# The fixed README emitted by technical_archive.py, not an unregistered payload slot.
ARCHIVE_README_SHA256 = "7eb9714f7829f9487ac1ea2d7789eae601445ac206c43b5a1e545c1d53a437ef"
ARCHIVE_ROLES = {"implementation", "test", "evidence", "documentation", "license", "standard", "configuration"}
ARCHIVE_FILE_LIMIT = 2 * 1024 * 1024
ARCHIVE_REGISTRY_LIMIT = 64 * 1024 * 1024


def git(repo, *args, inherit_index=False):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS="1")
    # commit -a / --only may present the prospective commit through a temporary index.
    # Preserve only this deliberate staged-view input, never a redirected Git/work tree.
    if inherit_index and os.environ.get("GIT_INDEX_FILE"):
        env["GIT_INDEX_FILE"] = os.environ["GIT_INDEX_FILE"]
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args],
                            capture_output=True, env=env)
    if result.returncode:
        raise ValueError("Git inspection failed: " + args[0])
    return result.stdout


def relative(value, *, prefix=False):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("Expected a portable repository-relative path")
    raw = value[:-1] if prefix and value.endswith("/") else value
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in ("", ".", "..", ".git") for part in raw.split("/")):
        raise ValueError("Unsafe repository-relative path")
    if any(char in value for char in "*?[]"):
        raise ValueError("Catalog paths must be exact files or directory prefixes, not globs")
    return value


def linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


class View:
    def __init__(self, repo, staged=False):
        self.repo = Path(repo).resolve()
        self.staged = staged
        self.index = {}
        if staged:
            for item in git(self.repo, "ls-files", "--stage", "-z", inherit_index=True).split(b"\0"):
                if not item:
                    continue
                metadata, name = item.split(b"\t", 1)
                mode, oid, stage = metadata.decode("ascii").split()
                if stage != "0":
                    raise ValueError("Unmerged Git index cannot be validated")
                self.index[name.decode("utf-8")] = (mode, oid)

    def exists(self, name):
        relative(name)
        if self.staged:
            return name in self.index and self.index[name][0] in {"100644", "100755"}
        path = self.repo
        for part in name.split("/"):
            path /= part
            if not path.exists() or linked(path):
                return False
        return path.is_file()

    def read(self, name):
        if not self.exists(name):
            raise ValueError("Missing or linked catalog file: " + name)
        if self.staged:
            return git(self.repo, "cat-file", "blob", self.index[name][1])
        return (self.repo / name).read_bytes()

    def link_exists(self, name):
        if self.exists(name):
            return True
        if self.staged:
            return any(path.startswith(name + "/") for path in self.index)
        path = self.repo
        for part in name.split("/"):
            path /= part
            if not path.exists() or linked(path):
                return False
        return path.is_dir()


def archive_relative(value):
    relative(value)
    devices = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if re.search(r'[<>|"\x00-\x1f]', value) or any(
        part.rstrip(" .") != part or unicodedata.normalize("NFKC", part) != part or
        part.split(".")[0].casefold() in devices for part in value.split("/")
    ):
        raise ValueError("Invalid canonical archive source")
    return value


def archive_stat(view, name):
    """Inspect local archive paths without following any link or reparse point."""
    path = view.repo
    parts = relative(name).split("/")
    for number, part in enumerate(parts):
        path /= part
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked archive path")
        if number < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError("Archive parent is not a directory")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("Hardlinked archive file")
    return info


def archive_bytes(view, name, limit=ARCHIVE_FILE_LIMIT):
    if view.staged:
        if not view.exists(name):
            raise ValueError("Missing or non-regular indexed archive file")
        size = int(git(view.repo, "cat-file", "-s", view.index[name][1]))
        if size > limit:
            raise ValueError("Archive file exceeds its byte limit")
        data = view.read(name)
        if len(data) != size:
            raise ValueError("Indexed archive file size changed")
        return data
    before = archive_stat(view, name)
    if before is None or not stat.S_ISREG(before.st_mode):
        raise ValueError("Missing or non-regular archive file")
    if before.st_size > limit:
        raise ValueError("Archive file exceeds its byte limit")
    with (view.repo / name).open("rb") as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(limit + 1)
    after = archive_stat(view, name)
    if after is None or not stat.S_ISREG(after.st_mode) or len(data) > limit or len(data) != after.st_size or len({
        (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns) for item in (before, opened, after)
    }) != 1:
        raise ValueError("Archive file changed during verification")
    return data


def archive_inventory(view):
    if view.staged:
        names = {name for name in view.index if name.startswith(ARCHIVE + "/")}
        if ARCHIVE in view.index or any(view.index[name][0] not in {"100644", "100755"} for name in names):
            raise ValueError("Non-regular indexed archive path")
    else:
        root = archive_stat(view, ARCHIVE)
        if root is None or not stat.S_ISDIR(root.st_mode):
            raise ValueError("Archive root is not an ordinary directory")
        names = set()
        for folder, directories, files in os.walk(view.repo / ARCHIVE, followlinks=False):
            for name in directories + files:
                path = Path(folder) / name
                relative_name = path.relative_to(view.repo).as_posix()
                info = archive_stat(view, relative_name)
                if info is None or not (stat.S_ISDIR(info.st_mode) if name in directories else stat.S_ISREG(info.st_mode)):
                    raise ValueError("Non-regular archive tree entry")
                if name in files:
                    names.add(relative_name)
    for name in names:
        archive_relative(name.removeprefix(ARCHIVE + "/"))
    return names


def unique_archive_json(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate archive registry JSON key")
        value[key] = item
    return value


def check_archive(view):
    """Verify inert archival bytes; never import or execute archived sources."""
    if view.staged:
        present = ARCHIVE in view.index or any(name.startswith(ARCHIVE + "/") for name in view.index)
        registered = ARCHIVE_REGISTRY in view.index
    else:
        present = archive_stat(view, ARCHIVE) is not None
        registered = archive_stat(view, ARCHIVE_REGISTRY) is not None
    if not present and not registered:
        return set(), 0
    if not present or not registered:
        raise ValueError("Archive tree and provenance registry must both be present")
    raw = archive_bytes(view, ARCHIVE_REGISTRY, ARCHIVE_REGISTRY_LIMIT)
    value = json.loads(raw, object_pairs_hook=unique_archive_json)
    if not isinstance(value, dict) or set(value) != {"schema", "role", "files"} or type(value["schema"]) is not int or value["schema"] != 1 or value["role"] != "historical_reference_not_deployable" or not isinstance(value["files"], list):
        raise ValueError("Invalid archive registry schema")
    expected, claims = {ARCHIVE_README: ARCHIVE_README_SHA256}, {ARCHIVE_README.casefold()}
    for row in value["files"]:
        if not isinstance(row, dict) or set(row) != {"source", "path", "sha256", "role"}:
            raise ValueError("Invalid archive registry entry")
        source = archive_relative(row["source"])
        target = ARCHIVE + "/" + source
        if row["path"] != target or not isinstance(row["role"], str) or row["role"] not in ARCHIVE_ROLES or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise ValueError("Invalid archive mapping, role or SHA-256")
        if target.casefold() in claims:
            raise ValueError("Duplicate or reserved archive registry target")
        claims.add(target.casefold())
        expected[target] = row["sha256"]
    actual = archive_inventory(view)
    if actual != set(expected):
        raise ValueError("Archive inventory has unregistered or missing files")
    for name, expected_hash in expected.items():
        if hashlib.sha256(archive_bytes(view, name)).hexdigest() != expected_hash:
            raise ValueError("Archive SHA-256 mismatch: " + name)
    return set(expected) | {ARCHIVE_REGISTRY}, len(value["files"])


def markdown_links(text):
    # Only authored handoff pages are checked, not verbatim historical archives.
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for match in re.finditer(r"\[[^\]\n]*\]\((<[^>]+>|[^)\n]+)\)", text):
        target = match.group(1).strip().strip("<>")
        if not target or target.startswith(("#", "https://", "http://", "mailto:")):
            continue
        yield target.split("#", 1)[0]


def link_target(document, target):
    from urllib.parse import unquote
    target = unquote(target)
    if "\\" in target or ":" in target or target.startswith("/"):
        raise ValueError("Authored technical docs require portable relative links")
    parts = list(PurePosixPath(document).parent.parts)
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise ValueError("Documentation link escapes repository")
            parts.pop()
        else:
            parts.append(part)
    return relative("/".join(parts))


def check(repo=REPO, staged=False, enforce_changes=False, require_tracked=False):
    view = View(repo, staged)
    errors = []
    data = json.loads(view.read(CATALOG).decode("utf-8-sig"))
    if data.get("schema") != 1 or not isinstance(data.get("features"), list) or not data["features"]:
        raise ValueError("Unsupported or empty feature catalog")
    ids, documents, referenced = set(), set(), {CATALOG}
    features = []
    for feature in data["features"]:
        identity = feature.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9-]+", identity) or identity in ids:
            errors.append("Invalid or duplicate feature ID: " + identity)
            continue
        ids.add(identity)
        document = relative(feature.get("document"))
        if not document.startswith("docs/technical/") or not document.endswith(".md") or document in documents:
            errors.append(identity + ": invalid or shared feature document")
        documents.add(document)
        paths = [document]
        for key in ("implementation", "tests", "evidence", "examples"):
            values = feature.get(key, [])
            if not isinstance(values, list) or (key in {"implementation", "examples"} and not values):
                errors.append(identity + ": missing " + key + " list")
                continue
            paths.extend(relative(value) for value in values)
        if feature.get("acceptance") not in {"historical", "checked-source", "in-progress"}:
            errors.append(identity + ": explicit acceptance boundary required")
        watches = feature.get("watch", [])
        if not isinstance(watches, list) or not watches:
            errors.append(identity + ": missing change ownership")
        for value in watches:
            relative(value, prefix=True)
        for name in paths:
            referenced.add(name)
            if not view.exists(name):
                errors.append(identity + ": missing regular file " + name)
        if view.exists(document):
            content = view.read(document).decode("utf-8-sig")
            if not re.search(r"\d{4}-\d{2}-\d{2}", content) or not re.search(r"变更|更新", content):
                errors.append(identity + ": dated update note required")
            if content.count("\n## ") < 3:
                errors.append(identity + ": feature handoff needs implementation, verification and limits")
        features.append(feature)
    authored = list(data.get("indexes", [])) + sorted(documents)
    for document in authored:
        relative(document)
        referenced.add(document)
        if not view.exists(document):
            errors.append("Missing technical index: " + document)
            continue
        for target in markdown_links(view.read(document).decode("utf-8-sig")):
            try:
                name = link_target(document, target)
                if view.exists(name):
                    referenced.add(name)
                if not view.link_exists(name):
                    errors.append(document + ": broken link to " + name)
            except ValueError as exc:
                errors.append(document + ": " + str(exc))
    archive_files = 0
    try:
        archive_references, archive_files = check_archive(view)
        referenced.update(archive_references)
    except (ValueError, OSError, UnicodeError) as exc:
        errors.append("Historical archive: " + str(exc))
    if require_tracked and not staged:
        tracked = set(git(repo, "ls-files", "-z").decode("utf-8").split("\0"))
        errors.extend("Not tracked: " + name for name in sorted(referenced - tracked))
    changed, affected = [], set()
    if enforce_changes:
        if not staged:
            raise ValueError("Change enforcement requires --staged, never guesses from a dirty worktree")
        changed = [name for name in git(repo, "diff", "--cached", "--name-only", "--no-renames", "-z", inherit_index=True).decode("utf-8").split("\0") if name]
        for name in changed:
            if not name.startswith(SOURCE_PREFIXES):
                continue
            matches = []
            for feature in features:
                for watch in feature["watch"]:
                    if name == watch or (watch.endswith("/") and name.startswith(watch)):
                        matches.append((len(watch), feature))
            if not matches:
                errors.append("No technical owner for changed source: " + name)
                continue
            most_specific = max(length for length, _ in matches)
            for length, feature in matches:
                if length != most_specific:
                    continue
                affected.add(feature["id"])
                notes = "docs/technical/changes/" + feature["id"] + "/"
                matching_notes = [p for p in changed if p.startswith(notes) and p.endswith(".md") and view.exists(p)]
                valid_notes = []
                for note in matching_notes:
                    content = view.read(note).decode("utf-8-sig")
                    if len(content.strip()) >= 40 and re.search(r"\d{4}-\d{2}-\d{2}", content) and "#" in content:
                        valid_notes.append(note)
                    else:
                        errors.append(feature["id"] + ": empty or undated technical change note")
                if feature["document"] not in changed and not valid_notes:
                    errors.append(feature["id"] + ": source changed without its technical update note")
    return {"pass": not errors, "mode": "staged" if staged else "working-tree", "features": len(features),
            "referenced_files": len(referenced), "archive_files": archive_files, "affected_features": sorted(affected),
            "errors": sorted(set(errors)), "production_modified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--enforce-changes", action="store_true")
    parser.add_argument("--require-tracked", action="store_true")
    args = parser.parse_args()
    try:
        result = check(staged=args.staged, enforce_changes=args.enforce_changes, require_tracked=args.require_tracked)
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = {"pass": False, "errors": [str(exc)], "production_modified": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
