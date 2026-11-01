"""Fetch only new source previews into a new private directory; never publish."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen

from audit_current import indexed, read, verify_file


def image_url(meta, entry, image):
    if not image or image.startswith(("/", "\\")) or ".." in Path(image).parts:
        raise ValueError("Invalid preview image path")
    if meta.get("assetPathMode") == "relative":
        url = urljoin(meta["assetBaseUrl"].rstrip("/") + "/", image)
    else:
        url = "https://assets.quicktagcloud.com/images/" + quote(entry.get("assetCodexId") or meta["id"], safe="")
        url += "/" + quote(image, safe="/")
        if entry.get("assetRev"):
            url += "?v=" + quote(entry["assetRev"], safe="")
    if urlsplit(url).scheme != "https":
        raise ValueError("Preview source must be HTTPS")
    return url


def filename(url):
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"):
        raise ValueError("Unsupported preview format")
    return "web_" + hashlib.sha256(url.encode()).hexdigest()[:24] + suffix


def plan(baseline, current):
    manifests = [read(root / "manifest.json") for root in (baseline, current)]
    catalogs = [indexed(read(verify_file(root, manifest, "codexes.json")))
                for root, manifest in zip((baseline, current), manifests)]
    result = []
    for dataset, meta in catalogs[1].items():
        new = indexed(read(verify_file(current, manifests[1], dataset + ".json"))["entries"])
        old = indexed(read(verify_file(baseline, manifests[0], dataset + ".json"))["entries"]) if dataset in catalogs[0] else {}
        # External sources cannot silently fall back to a release when mutable.
        if meta.get("dataUrl"):
            for root in (baseline, current):
                if not (root / (dataset + ".external.json")).is_file():
                    raise ValueError("Missing external source snapshot")
            old = indexed(read(baseline / (dataset + ".external.json"))["entries"])
            new = indexed(read(current / (dataset + ".external.json"))["entries"])
        for entry_id, entry in new.items():
            if entry_id in old:
                continue
            paths = [row.get("path") for row in entry.get("images", []) if isinstance(row, dict)]
            if entry.get("image"):
                paths.insert(0, entry["image"])
            for image in dict.fromkeys(paths):
                if not image:
                    continue
                url = image_url(meta, entry, image)
                result.append({"source": dataset + ":" + entry_id, "dataset": dataset,
                               "entry_id": entry_id, "source_image": image,
                               "url": url, "filename": filename(url),
                               "expected_width": entry.get("imageWidth"),
                               "expected_height": entry.get("imageHeight")})
    return result


def fetch(row, directory):
    from PIL import Image
    request = Request(row["url"], headers={"User-Agent": "ComfyUI-source-sync/1"})
    with urlopen(request, timeout=45) as response:
        data = response.read(64 * 1024 * 1024 + 1)
    if not data or len(data) > 64 * 1024 * 1024:
        raise ValueError("Invalid preview size")
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        width, height = image.size
    # Website width/height may describe the original PNG rather than preview.
    target = directory / row["filename"]
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError("Different bytes map to the same preview name")
    else:
        with target.open("xb") as stream:
            stream.write(data)
    return {**row, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "width": width, "height": height, "decoded": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", required=True, type=Path)
    parser.add_argument("--baseline-web", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = plan(args.baseline_web, args.web)
    args.output.mkdir(parents=True, exist_ok=False)
    image_dir = args.output / "images"
    image_dir.mkdir()
    # Small bounded parallelism; all futures are consumed before writing success.
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda row: fetch(row, image_dir), rows))
    with (args.output / "image_receipts.json").open("x", encoding="utf-8") as stream:
        json.dump(receipts, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"source_rows": len(receipts), "unique_files": len({r["filename"] for r in receipts}),
                      "bytes": sum(r["bytes"] for r in receipts), "passed": True}))


if __name__ == "__main__":
    main()
