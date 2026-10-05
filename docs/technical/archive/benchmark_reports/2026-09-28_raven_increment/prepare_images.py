"""Bind and download every image in the fixed 816-entry Raven increment."""
import hashlib
import json
import shutil
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WEB = ROOT / "benchmark_reports/2026-09-28_web_image_reaudit/current_web"
OLD = ROOT / "benchmark_reports/2026-09-27_codex_update/sources/web/raven_composition.json"
GAP = ROOT / "benchmark_reports/2026-09-28_web_image_reaudit/CURRENT_GAP.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


gap = read(GAP)
pointer = read(WEB / "current.json")
manifest = read(WEB / "manifest.json")
assert pointer["release"] == gap["current_release"]
assert manifest["contentHash"] == pointer["contentHash"]
assert hashlib.sha256((WEB / "raven_composition.json").read_bytes()).hexdigest() == manifest["files"]["raven_composition.json"]["sha256"]
old_ids = {e["id"] for e in read(OLD)["entries"]}
added = [e for e in read(WEB / "raven_composition.json")["entries"] if e["id"] not in old_ids]
assert len(added) == gap["new_image_entries"] == 816
rows = []
for e in added:
    assert e["rating"] == "safe" and e["image"] and len(e.get("images") or []) == 1
    asset = e.get("assetCodexId") or "raven_composition"
    url = "https://assets.quicktagcloud.com/images/" + quote(asset, safe="") + "/" + quote(e["image"], safe="/")
    if e.get("assetRev"):
        url += "?v=" + quote(e["assetRev"], safe="")
    suffix = Path(e["image"]).suffix.lower()
    assert suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
    filename = "web_" + hashlib.sha256(url.encode()).hexdigest()[:24] + suffix
    rows.append({"filename": filename, "url": url, "source": "raven_composition:" + e["id"],
                 "source_entry_sha256": hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True).encode()).hexdigest()})
assert len({r["filename"] for r in rows}) == len(rows)
(HERE / "image_plan.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
shutil.copy2(ROOT / "benchmark_reports/2026-09-27_codex_update/fetch_images.py", HERE / "fetch_images.py")
print("PLANNED", len(rows), "IMAGES", flush=True)
