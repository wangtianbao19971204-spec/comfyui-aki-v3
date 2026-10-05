import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path


RUN = Path(__file__).resolve().parent
PROJECT = RUN.parents[3]
OLD_WORKFLOW = RUN.parent / "20261002_181634/M6c2_isolated_workflow.json"
FORMAL_WORKFLOW = PROJECT / "ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json"
RUN_ID = RUN.name
POSITIVE = f"M9_POSITIVE_BASELINE_{RUN_ID}, M9_POSITIVE_TAIL,"
NEGATIVE = f"M9_NEGATIVE_BASELINE_{RUN_ID}, M9_NEGATIVE_TAIL"
CATEGORY_ID = f"m9-category-{RUN_ID}"
REVISION = f"m9-isolated-{RUN_ID}"
BRANCH_ID = f"m9-{RUN_ID}"
GROUP_NAME = "M9 隔离提示词与参数"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(name, payload):
    path = RUN / name
    assert path.parent == RUN
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def node_structure(source, node_id, title, position, widget_values):
    node = {
        "id": node_id,
        "type": source["type"],
        "pos": position,
        "size": deepcopy(source["size"]),
        "flags": {"collapsed": False},
        "order": node_id - 1,
        "mode": 0,
        "inputs": [],
        "outputs": [],
        "title": title,
        "properties": {"Node name for S&R": source["type"]},
        "widgets_values": list(widget_values.values()),
        "widgets_values_named": dict(widget_values),
    }
    for original in source.get("inputs", []):
        slot = {key: deepcopy(original[key]) for key in ("localized_name", "name", "type", "shape", "widget") if key in original}
        slot["link"] = None
        node["inputs"].append(slot)
    for index, original in enumerate(source.get("outputs", [])):
        slot = {key: deepcopy(original[key]) for key in ("localized_name", "name", "type") if key in original}
        slot.update(slot_index=index, links=None)
        node["outputs"].append(slot)
    return node


def synthetic_item(direction):
    item_id = f"m9-{direction}-{RUN_ID}"
    body = f"M9_SYNTHETIC_{direction.upper()}_{RUN_ID}"
    binding = hashlib.sha256(f"{item_id}|{direction}|{body}".encode()).hexdigest()
    return {
        "id": item_id,
        "alias": f"M9 隔离{'正向' if direction == 'positive' else '负向'}验证词",
        "prompt": body,
        "description": "仅用于本轮浏览器隔离响应，不保存到正式资料库。",
        "image": "",
        "tags": [],
        "favorite": False,
        "template": False,
        "is_user_plan": False,
        "usage_count": 0,
        "last_used": None,
        "_categoryId": CATEGORY_ID,
        "_categoryName": "M9 隔离资料",
        "_semantic": {
            "binding": binding,
            "disposition": "classified",
            "content_type": "fragment",
            "usage": direction,
            "declared_usage": direction,
            "model_scope": "unknown",
            "themes": [],
            "theme_ids": [],
            "refinements": [],
            "manual_search_eligible": True,
            "random_pool_eligible": False,
            "strict_model_pool_eligible": False,
            "semantic_review_status": "m9_synthetic_fixture_only",
        },
    }


source_hashes = {str(path): digest(path) for path in (OLD_WORKFLOW, FORMAL_WORKFLOW)}
old_workflow = read(OLD_WORKFLOW)
formal_workflow = read(FORMAL_WORKFLOW)
weilin_source = next(node for node in old_workflow["nodes"] if node["type"] == "WeiLinPromptUI")
formal_sources = {kind: next(node for node in formal_workflow["nodes"] if node["type"] == kind)
                  for kind in ("CLIPTextEncode", "EmptyLatentImage", "KSampler")}
nodes = [
    node_structure(weilin_source, 1, "[00W-1P] M9 隔离正向目标", [100, 120], {
        "positive": POSITIVE, "auto_random": False, "lora_str": "", "temp_str": "",
        "temp_lora_str": "", "random_template": "", "打开提示词编辑器": "", "打开Lora堆": "",
    }),
    node_structure(formal_sources["CLIPTextEncode"], 2, "[00W-1N] M9 隔离负向目标", [680, 120], {"text": NEGATIVE}),
    node_structure(formal_sources["EmptyLatentImage"], 3, "M9 隔离尺寸", [100, 480], {"width": 768, "height": 1024, "batch_size": 1}),
    node_structure(formal_sources["KSampler"], 4, "M9 隔离采样参数", [470, 480], {
        "seed": 424242, "control_after_generate": "fixed", "steps": 20, "cfg": 7.0,
        "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
    }),
]
workflow = {
    "id": "a45ec08f-03af-4e18-8b5a-021720214109",
    "revision": 0,
    "last_node_id": 4,
    "last_link_id": 0,
    "nodes": nodes,
    "links": [],
    "groups": [{"title": GROUP_NAME, "bounding": [60, 60, 1040, 740], "color": "#3f789e", "font_size": 24, "flags": {}}],
    "config": {},
    "extra": {"uap_workbench": {
        "version": 1, "activeBranch": BRANCH_ID, "viewBranch": BRANCH_ID, "stage": "daily",
        "branches": [{
            "id": BRANCH_ID, "label": "M9 隔离验证", "group": GROUP_NAME, "nodeIds": [1, 2, 3, 4],
            "modes": {str(node_id): 0 for node_id in range(1, 5)},
            "stages": [{"id": "daily", "label": "隔离提示词与参数", "groups": [GROUP_NAME]}],
            "dailyRows": [[GROUP_NAME]],
        }],
    }},
    "version": 0.4,
}
items = [synthetic_item(direction) for direction in ("positive", "negative")]
listing = {
    "last_modified": REVISION, "items": items, "total": 2, "offset": 0, "limit": 30,
    "categories": [{"id": CATEGORY_ID, "name": "M9 隔离资料", "updated_at": REVISION, "prompt_count": 2, "prompts": []}],
    "has_more": False, "category_id": "", "category_name": "", "query": "", "view": "all",
    "review_counts": {"classified": 2, "reviewed": 0, "pending": 0},
    "filter_counts": {"theme": {}, "subcategory": {}, "count": {}, "detail": {}, "mode": "any"},
}
payloads = {"M9_isolated_workflow.json": workflow, "list_fixture.json": listing}
for item in items:
    direction = item["_semantic"]["usage"]
    payloads[f"detail_{direction}_fixture.json"] = {
        "prompt": deepcopy(item),
        "category": {"id": CATEGORY_ID, "name": "M9 隔离资料", "updated_at": REVISION, "prompt_count": 2, "prompts": []},
        "revision": REVISION, "requested_id": item["id"], "redirected": False,
    }

assert [node["type"] for node in nodes] == ["WeiLinPromptUI", "CLIPTextEncode", "EmptyLatentImage", "KSampler"]
assert len(nodes) == 4 and workflow["links"] == []
assert all(slot["link"] is None for node in nodes for slot in node["inputs"])
assert all(not slot["links"] for node in nodes for slot in node["outputs"])
assert all(node["widgets_values"] == list(node["widgets_values_named"].values()) for node in nodes)
assert workflow["extra"]["uap_workbench"]["branches"][0]["nodeIds"] == [node["id"] for node in nodes]
assert {item["_semantic"]["usage"] for item in items} == {"positive", "negative"}
assert sum(category["prompt_count"] for category in listing["categories"]) == listing["total"] == len(items)
for item in items:
    direction = item["_semantic"]["usage"]
    assert payloads[f"detail_{direction}_fixture.json"]["prompt"] == item
    assert item["id"].startswith("m9-") and item["_categoryId"].startswith("m9-")
serialized = json.dumps(payloads, ensure_ascii=False)
for forbidden in ("M6", "M3D", "M3d", "_merge_sources", "_classification", "7e161c74-e474-56b8-ada0-93d53ab7d01c"):
    assert forbidden not in serialized, forbidden
assert "M9_POSITIVE_BASELINE" in serialized and "M9_NEGATIVE_BASELINE" in serialized
assert source_hashes == {str(path): digest(path) for path in (OLD_WORKFLOW, FORMAL_WORKFLOW)}
for name, payload in payloads.items():
    write(name, payload)
    assert read(RUN / name) == payload

provenance = {
    "run_id": RUN_ID,
    "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    "status": "static_fixture_ready_browser_not_loaded",
    "source_sha256": source_hashes,
    "source_usage": "Only allowlisted node socket/schema fields and node sizes were copied; all node ids, titles, values, properties, group/branch metadata and library records are isolated synthetic data.",
    "production_source_edits": 0,
    "formal_writes": 0,
    "browser_loaded": False,
    "browser_acceptance": "not_run",
    "node_ids": {"positive": 1, "negative": 2, "size": 3, "sampler": 4},
    "baselines": {"positive": POSITIVE, "negative": NEGATIVE, "width": 768, "height": 1024, "batch_size": 1, "seed": 424242, "steps": 20, "cfg": 7.0},
    "library_ids": {item["_semantic"]["usage"]: item["id"] for item in items},
    "category_id": CATEGORY_ID,
    "get_intercepts_required": {
        "/prompt_selector/library/index": "list_fixture.json; its synthetic categories must replace the production index as well, otherwise production isolated-area counts can reduce the displayed synthetic total to zero",
        "/prompt_selector/library/prompts": "list_fixture.json; apply test query/view/direction filtering to this two-item array when needed",
        "/prompt_selector/library/prompt": "match prompt_id exactly to detail_positive_fixture.json or detail_negative_fixture.json; reject unrecognized synthetic ids",
    },
    "write_interception_required": {
        "scope": "This test tab only; install before importing workflow or opening the isolated library",
        "default": "Block non-GET/HEAD requests unless explicitly handled by the fixture; never pass unexpected writes through",
        "mark_used": "POST /prompt_selector/prompts/mark_used may receive immediate synthetic HTTP 200 JSON {} only for the two known m9 ids/category; record intercepted requests",
        "other_writes": "No success emulation for favorite/save/upsert/delete/import/queue or workflow persistence; block and record unexpected attempts",
    },
    "static_checks": {
        "json_roundtrip": True, "exactly_four_nodes": True, "no_connections": True,
        "widget_values_equal_named_values": True, "branch_contains_all_nodes": True,
        "list_and_detail_exact_match": True, "no_historical_row_id_or_baseline": True,
        "no_formal_classification_or_merged_source_body": True, "source_files_unchanged": True,
    },
    "limitations": [
        "Not loaded in a browser; node registration, field binding, import behavior and actual controls remain unverified.",
        "A four-node fixture verifies target/parameter correctness only; it is not a production-sized workflow performance baseline.",
        "The graph deliberately has no connections or output nodes and must not be queued or saved as a formal workflow.",
        "The JSON files do not install request interception by themselves; verify test-tab isolation before UI writes.",
    ],
    "artifact_sha256": {name: digest(RUN / name) for name in payloads},
}
write("fixture_provenance.json", provenance)
assert read(RUN / "fixture_provenance.json") == provenance
print(json.dumps({"status": provenance["status"], "nodes": len(nodes), "library_items": len(items), "files": [*payloads, "fixture_provenance.json"], "static_checks": provenance["static_checks"]}, ensure_ascii=False))
