"""Refresh the immutable dependency from raw Git blobs at an explicit full SHA.

Run in the maintained adapter source, test, then publish the fixed copy. This
never checks out or executes upstream development material, downloads models,
or changes the supplied upstream repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
STATIC = {"app.js", "look.js", "i18n.js", "index.html", "style.css", "i18n/en.json"}


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def sync(repo, commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("An explicit full commit SHA is required; floating refs are not accepted")
    actual = git(repo, "rev-parse", "--verify", commit + "^{commit}").decode().strip()
    if actual != commit:
        raise ValueError("Dependency commit did not resolve exactly")
    names = git(repo, "ls-tree", "-r", "--name-only", commit, "--", "stocking").decode().splitlines()
    names = [n for n in names if (n.startswith("stocking/") and n.count("/") == 1 and n.endswith(".py"))
             or (n.startswith("stocking/static/") and n[len("stocking/static/"):] in STATIC)]
    if not {"stocking/document.py", "stocking/server.py", "stocking/__init__.py"} <= set(names):
        raise ValueError("Upstream dependency layout changed")
    blobs = {n[len("stocking/"):]: git(repo, "show", commit + ":" + n) for n in sorted(names)}
    license_bytes = git(repo, "show", commit + ":LICENSE")
    if b"MIT License" not in license_bytes or b"Silvermoong" not in license_bytes:
        raise ValueError("Review upstream license before upgrading")
    provenance = {
        "repository": "https://github.com/silvermoong/stocking-texture-tool",
        "commit": commit, "license": "MIT", "snapshot_format": 2,
        "license_sha256": hashlib.sha256(license_bytes).hexdigest(),
        "files": [{"file": n, "sha256": hashlib.sha256(b).hexdigest()} for n, b in blobs.items()],
        "local_adapters": ["vendor/__init__.py", "vendor/i18n.py"],
        "integration": "Unmodified raw Git blobs in upstream/stocking; vendor supplies a host-local namespace and request-local i18n. Upstream services are not started.",
    }
    dependency = ROOT / "upstream/stocking"
    existing = {p.relative_to(dependency).as_posix() for p in dependency.rglob("*") if p.is_file()
                and "__pycache__" not in p.parts} if dependency.exists() else set()
    if existing - blobs.keys():
        raise ValueError("Review removed dependency files before upgrading: " + str(sorted(existing - blobs.keys())))
    for name, content in blobs.items():
        path = dependency / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (ROOT / "upstream/LICENSE").write_bytes(license_bytes)
    (ROOT / "UPSTREAM.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Read-only upstream Git object repository")
    parser.add_argument("--commit", required=True, help="Reviewed full SHA, never main or HEAD")
    args = parser.parse_args()
    report = sync(args.repo, args.commit)
    print(json.dumps({"commit": report["commit"], "raw_blob_files": len(report["files"])}))
