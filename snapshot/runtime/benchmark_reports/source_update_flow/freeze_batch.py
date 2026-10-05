"""Freeze a collected batch into a reviewable, initially unapproved manifest."""
import argparse
import json
import os
from pathlib import Path

from flow_gate import read, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path, help="batch directory after website and Word extraction")
    parser.add_argument("output", type=Path, help="manifest JSON to create")
    parser.add_argument("--original-documents", type=Path, help="directory containing the original .docx files")
    args = parser.parse_args()
    batch = args.batch.resolve()
    web = batch / "sources/web"
    docs = batch / "sources/docx"
    pointer = read(web / "current.json")
    catalog = read(web / "codexes.json")
    source_files = {}
    for path in sorted(web.glob("*.json")):
        source_files[str(path.relative_to(batch)).replace("\\", "/")] = sha(path)
    for path in sorted(docs.glob("*.json")):
        source_files[str(path.relative_to(batch)).replace("\\", "/")] = sha(path)
    summary = read(docs / "summary.json")
    originals = {}
    if args.original_documents:
        for item in summary:
            path = (args.original_documents / item["file"]).resolve()
            if not path.is_file() or sha(path) != item["sha256"]:
                raise SystemExit(f"Word original missing or hash mismatch: {path}")
            originals[item["file"]] = {"path": str(path), "sha256": item["sha256"]}
    rows = imaged = 0
    for meta in catalog:
        name = meta["id"] + (".external.json" if (web / (meta["id"] + ".external.json")).exists() else ".json")
        entries = read(web / name)["entries"]
        rows += len(entries)
        imaged += sum(bool(entry.get("image")) for entry in entries)
    result = {
        "schema": "source-update-batch/v1",
        "batch_dir": os.path.relpath(batch, args.output.resolve().parent).replace("\\", "/"),
        "web_release": pointer["release"],
        "dataset_count": len(catalog),
        "web_rows": rows,
        "web_imaged_rows": imaged,
        "document_count": len(summary),
        "document_rows": len(read(docs / "entries.json")),
        "document_sha256": {item["file"]: item["sha256"] for item in summary},
        "original_documents": originals,
        "source_files": source_files,
        "historical_replay": False,
        "review": {"source_hold": False, "classification": False, "image_scope": None},
    }
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite frozen manifest: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
