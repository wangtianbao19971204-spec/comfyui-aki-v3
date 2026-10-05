"""Read-only inventory for the pinned Raven increment."""
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
AUDIT = ROOT / "benchmark_reports/2026-09-28_web_image_reaudit"
WEB = AUDIT / "current_web"
PROD = ROOT / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector"
DB = PROD / "user_data/userdatas_zh_CN_tags.db"


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").replace("_", " ").replace("\\", "")
    s = re.sub(r"\s+", " ", s).strip().casefold()
    return re.sub(r"\s*([,:{}\[\]()])\s*", r"\1", s).strip(", ")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


old = read(AUDIT.with_name("2026-09-27_codex_update") / "sources/web/raven_composition.json")
new = read(WEB / "raven_composition.json")
old_ids = {e["id"] for e in old["entries"]}
added = [e for e in new["entries"] if e["id"] not in old_ids]
assert len(added) == 816
rows = []
with sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True) as db:
    by_body = defaultdict(list)
    for uid, text in db.execute("select t_uuid,text from tag_tags"):
        by_body[norm(text)].append((uid, text))
    for e in added:
        matches = by_body.get(norm(e["tags"]), [])
        rows.append({"id": e["id"], "tags": e["tags"], "title": e.get("title"), "path": e.get("path"),
                     "image": e.get("image"), "assetRev": e.get("assetRev"),
                     "match_count": len(matches), "match_ids": [x[0] for x in matches],
                     "match_texts": [x[1] for x in matches],
                     "source_sha256": hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True).encode()).hexdigest()})
result = {"rows": len(rows), "exact_matches": sum(bool(r["match_ids"]) for r in rows),
          "new_bodies": sum(not r["match_ids"] for r in rows),
          "same_body_duplicate_targets": len({uid for r in rows for uid in r["match_ids"]}),
          "same_body_repeated_sources": dict(Counter(norm(r["tags"]) for r in rows).most_common(10)),
          "path_counts": [{"path": list(path), "count": n} for path, n in Counter(tuple(r["path"] or []) for r in rows).most_common()],
          "comma_count": dict(Counter(len([x for x in re.split(r"[,，]", r["tags"]) if x.strip()]) for r in rows)),
          "body_lengths": {"max": max(len(r["tags"]) for r in rows), "min": min(len(r["tags"]) for r in rows)},
          "match_multiplicity": dict(Counter(r["match_count"] for r in rows))}
HERE.mkdir(exist_ok=True)
(HERE / "inventory.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
with (HERE / "rows.jsonl").open("w", encoding="utf-8", newline="\n") as out:
    for row in rows:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
print(json.dumps(result, ensure_ascii=False))
