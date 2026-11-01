"""Compare frozen website snapshots without modifying a running library.

Raw differences retain JSON types, missing/null, case, spacing and array order.
The output contains source content and belongs in private batch evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return left == right


def escape(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def differences(left, right, path=""):
    if equal(left, right):
        return []
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(left.keys() | right.keys()):
            child = path + "/" + escape(key)
            if key not in left or key not in right:
                row = {"path": child, "old_present": key in left, "new_present": key in right}
                if key in left:
                    row["old"] = left[key]
                if key in right:
                    row["new"] = right[key]
                result.append(row)
            else:
                result.extend(differences(left[key], right[key], child))
        return result
    # Retain the complete array when its length/order changes, including images.
    return [{"path": path, "old_present": True, "new_present": True,
             "old": left, "new": right}]


def safe_file(root, name):
    relative = PurePosixPath(name)
    if (relative.is_absolute() or not relative.parts or any(p in (".", "..") for p in relative.parts)
            or "\\" in name or ":" in name):
        raise ValueError("Unsafe source file name")
    target = Path(root).joinpath(*relative.parts)
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Source file escapes snapshot")
    return target


def verify_file(root, manifest, name):
    path = safe_file(root, name)
    spec = manifest["files"][name]
    size = spec.get("size", spec.get("bytes"))
    if not path.is_file() or path.stat().st_size != size or digest(path) != spec["sha256"]:
        raise ValueError("Source manifest mismatch: " + name)
    return path


def indexed(items, field="id"):
    result = {}
    for item in items:
        key = item[field]
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Missing or duplicate source identity")
        result[key] = item
    return result


def document_delta(old, new):
    old_rows, new_rows = indexed(old["entries"]), indexed(new["entries"])
    added = [key for key in new_rows if key not in old_rows]
    removed = [key for key in old_rows if key not in new_rows]
    changed = []
    for key in new_rows:
        if key in old_rows:
            fields = differences(old_rows[key], new_rows[key])
            if fields:
                changed.append({"id": key, "fields": fields})
    fields = Counter(row["path"] for item in changed for row in item["fields"])
    return {"old_entries": len(old_rows), "new_entries": len(new_rows),
            "added": [new_rows[k] for k in added], "removed": [old_rows[k] for k in removed],
            "changed": changed, "field_counts": dict(fields),
            "entry_order_changed": list(old_rows) != list(new_rows),
            "metadata": differences({k: v for k, v in old.items() if k != "entries"},
                                    {k: v for k, v in new.items() if k != "entries"})}


def audit(old_root, new_root):
    roots = (Path(old_root), Path(new_root))
    manifests = [read(root / "manifest.json") for root in roots]
    pointers = [read(root / "current.json") for root in roots]
    for manifest, pointer in zip(manifests, pointers):
        if manifest.get("release") != pointer["release"] or manifest["contentHash"] != pointer["contentHash"]:
            raise ValueError("Pointer and manifest identify different releases")
    catalogs = [indexed(read(verify_file(root, manifest, "codexes.json")))
                for root, manifest in zip(roots, manifests)]
    result = {"schema": "website-source-delta/v1", "old_release": pointers[0],
              "new_release": pointers[1], "catalog": differences(catalogs[0], catalogs[1]),
              "datasets": {}, "supplemental": {}, "manifest_changes": [],
              "unread_changed_files": [], "external_sources": {}}
    for name in sorted(manifests[0]["files"].keys() | manifests[1]["files"].keys()):
        a, b = manifests[0]["files"].get(name), manifests[1]["files"].get(name)
        if equal(a, b):
            continue
        result["manifest_changes"].append({"file": name, "old": a, "new": b})
        if not name.startswith("tag_zh/") and name not in ("media.json", "updates.json"):
            continue
        docs = []
        for root, manifest, spec in zip(roots, manifests, (a, b)):
            docs.append(read(verify_file(root, manifest, name)) if spec else None)
        result["supplemental"][name] = differences(*docs)
    for dataset in sorted(catalogs[0].keys() | catalogs[1].keys()):
        docs = []
        for root, manifest, catalog in zip(roots, manifests, catalogs):
            if dataset not in catalog:
                docs.append({"entries": []})
                continue
            name = dataset + ".json"
            doc = read(verify_file(root, manifest, name))
            external = root / (dataset + ".external.json")
            if external.exists():
                doc = read(external)
                result["external_sources"].setdefault(dataset, []).append({
                    "snapshot": str(root.resolve()), "sha256": digest(external),
                    "bytes": external.stat().st_size,
                    "note": "External bytes require separate start/end acquisition receipts"})
            elif catalog[dataset].get("dataUrl"):
                raise ValueError("External dataUrl not captured: " + dataset)
            docs.append(doc)
        result["datasets"][dataset] = document_delta(*docs)
    for row in result["manifest_changes"]:
        name = row["file"]
        if name in result["supplemental"] or name == "codexes.json" or name.removesuffix(".json") in result["datasets"]:
            continue
        # Do not silently claim that a changed non-dataset file was examined.
        if all(spec is None or safe_file(root, name).exists()
               for root, spec in zip(roots, (row["old"], row["new"]))):
            docs = [read(verify_file(root, manifest, name)) if spec else None
                    for root, manifest, spec in zip(roots, manifests, (row["old"], row["new"]))]
            result["supplemental"][name] = differences(*docs)
        else:
            result["unread_changed_files"].append(name)
    totals = Counter()
    for row in result["datasets"].values():
        totals.update({"old_entries": row["old_entries"], "new_entries": row["new_entries"],
                       "added": len(row["added"]), "removed": len(row["removed"]),
                       "changed": len(row["changed"])})
    result["summary"] = dict(totals, datasets=len(result["datasets"]),
                              unread_changed_files=len(result["unread_changed_files"]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.baseline, args.current)
    # Never replace evidence or a source file supplied by the caller.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result["summary"], ensure_ascii=False))
    raise SystemExit(bool(result["unread_changed_files"]))


if __name__ == "__main__":
    main()
