"""Exercise the current artist page helpers without importing route-bearing ComfyUI modules."""
import ast
import gzip
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path


source = Path(__file__).resolve().parents[2] / (
    "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/"
    "modules/comfyui-anima-tools/nodes.py"
)
tree = ast.parse(source.read_text(encoding="utf-8"))
names = {"_artist_search_rank", "_artist_category_tree", "_artist_page",
         "_shared_prompt_category_paths_match_filter", "_normalize_shared_category_filter_value",
         "_get_artist_page_payload", "_parse_shared_prompt_filters", "_shared_prompt_item_matches_filters", "_shared_prompt_source_options"}
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
context = {"hashlib": hashlib, "re": re, "json": json,
           "_SHARED_PROMPT_PARENT_FILTER_PREFIX": "shared-parent:",
           "_SHARED_PROMPT_CHILD_FILTER_PREFIX": "shared-child:",
           "_SHARED_PROMPT_PATH_FILTER_PREFIX": "shared-path:",
           "_SHARED_PROMPT_CATEGORY_SEPARATOR": "\x1f"}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), context)
page = context["_artist_page"]

items = []
for number in range(193):
    name = "same name" if number in (3, 90) else f"artist {number:03d}"
    item = {"id": f"weilin:artist:{number}", "name": name,
            "tags": f"@{name}", "post_count": 193 - number,
            "uniqueness_score": number / 10 if number % 7 else None,
            "shared_category_paths": [{"levels": ["WeiLin / 画师", "A" if number < 100 else "B"],
                                      "parent": "WeiLin / 画师", "source": "A" if number < 100 else "B"}],
            "_semantic": {"binding": f"binding-{number}"}}
    items.append(item)
payload = {"items": items, "revision": "revision-1"}

seen = []
for offset in range(0, 193, 60):
    result, status = page(payload, {"revision": "revision-1", "offset": offset, "limit": 60,
                                    "sort": "works-desc"})
    assert status == 200 and result["total"] == 193
    seen.extend(item["id"] for item in result["items"])
assert len(seen) == len(set(seen)) == 193 and seen == [item["id"] for item in items]

result, status = page(payload, {"revision": "revision-1", "search": "same name",
                                "lookup_keys": ["shared:weilin:artist:90"], "sort": "name-asc"})
assert status == 200 and result["total"] == 2
assert {item["id"] for item in result["items"]} == {items[3]["id"], items[90]["id"]}
assert [item["id"] for item in result["lookup"]] == [items[90]["id"]]

result, status = page(payload, {"filter": "shared-path:WeiLin / 画师\x1fB", "include_tree": True,
                                "limit": 0})
assert status == 200 and result["total"] == 93 and result["items"] == []
assert result["tree"][0]["count"] == 193
assert [child["count"] for child in result["tree"][0]["children"]] == [100, 93]

result, status = page(payload, {"sort": "random", "random_seed": "fixed", "limit": 60})
again, _ = page(payload, {"sort": "random", "random_seed": "fixed", "offset": 60, "limit": 60})
assert not {item["id"] for item in result["items"]} & {item["id"] for item in again["items"]}
stale, status = page(payload, {"revision": "revision-0"})
assert status == 409 and stale["revision"] == "revision-1"

with tempfile.TemporaryDirectory() as directory:
    count = [0]
    fingerprint = [["source-v1"]]
    def build(_kind):
        count[0] += 1
        return payload
    context.update({"gzip": gzip, "json": json, "os": os, "threading": threading,
                    "_ARTIST_PAGE_CACHE_LOCK": threading.Lock(),
                    "_ARTIST_PAGE_CACHE": {"fingerprint": None, "payload": None},
                    "_ARTIST_PAGE_CACHE_PATH": os.path.join(directory, "artist.json.gz"),
                    "_artist_page_fingerprint": lambda: fingerprint[0],
                    "get_shared_prompt_payload": build})
    get_cached = context["_get_artist_page_payload"]
    assert get_cached()["revision"] == "revision-1" and count[0] == 1
    context["_ARTIST_PAGE_CACHE"] = {"fingerprint": None, "payload": None}
    assert get_cached()["revision"] == "revision-1" and count[0] == 1
    fingerprint[0] = ["source-v2"]
    assert get_cached()["revision"] == "revision-1" and count[0] == 2

print("artist page contract: pass (193 records, search, tree, zero limit, random, revision, cache invalidation)")
