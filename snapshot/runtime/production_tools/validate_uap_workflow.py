#!/usr/bin/env python3
"""Validate the generated UAP workbench and write a small audit receipt."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from merge_unified_workflow import OPTIMIZED_OUTPUT, ROOT, SOURCES, read_json, validate


REPORT = ROOT / "benchmark_reports" / "2026-09-06_plugin_optimization" / "uap_integration_validation.json"
PLUGIN_JS = ROOT / "ComfyUI" / "custom_nodes" / "ComfyUI-Danbooru-Gallery-V50-GalleryOnly" / "js" / "quick_group_navigation" / "quick_group_navigation.js"
PLUGIN_CSS = ROOT / "ComfyUI" / "custom_nodes" / "ComfyUI-Danbooru-Gallery-V50-GalleryOnly" / "js" / "quick_group_navigation" / "styles.css"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def endpoint(path: str) -> dict[str, object]:
    url = f"http://127.0.0.1:8188{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read()
            return {"url": url, "status": response.status, "bytes": len(body)}
    except Exception as exc:  # pragma: no cover - the receipt should retain the failure
        return {"url": url, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", type=Path, default=OPTIMIZED_OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    workflow = args.workflow if args.workflow.is_absolute() else ROOT / args.workflow
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    data = read_json(workflow)
    errors = validate(data, forbid_browser_receiver=True)
    source_paths = [ROOT / "ComfyUI" / "user" / "default" / "workflows" / spec["file"] for spec in SOURCES]
    titles = {g.get("title") for g in data.get("groups", [])}
    qgn = data.get("extra", {}).get("qgn_navigation_groups", [])
    integration = data.get("extra", {}).get("codex_uap_integration", {})
    suite = data.get("extra", {}).get("production_suite", {})
    branch_stats = suite.get("source_stats", [])
    expected_default = "[01] Anima 原版生产"
    if integration.get("default_active_branch") != expected_default:
        errors.append("default active branch is not [01] Anima 原版生产")
    if integration.get("branch_policy") != "one_active_model_branch_at_a_time":
        errors.append("UAP branch policy is not one_active_model_branch_at_a_time")
    for index, stat in enumerate(branch_stats):
        if not isinstance(stat, dict):
            errors.append(f"source_stats entry {index} is not an object")
            continue
        if index == 0 and int(stat.get("active_nodes", 0)) <= 0:
            errors.append("Anima original branch has no active nodes")
        if index > 0:
            if int(stat.get("active_nodes", 0)) != 0:
                errors.append(f"branch {stat.get('file')} is active by default")
            if int(stat.get("muted_nodes", 0)) != int(stat.get("nodes", 0)):
                errors.append(f"branch {stat.get('file')} is not fully muted by default")
    model_wrappers = [
        group for group in data.get("groups", [])
        if isinstance(group.get("title"), str) and group["title"].startswith(tuple(f"[0{i}]" for i in range(1, 10)))
    ]
    control_nodes = [
        node for node in data.get("nodes", [])
        if node.get("title") in {"UAP统一生产工作台 · 使用说明", "UAP-00 主模型/扩展分支单选（默认 A1）"}
    ]
    controls_outside_wrappers = True
    for node in control_nodes:
        x, y = node.get("pos", [0, 0])[:2]
        for group in model_wrappers:
            gx, gy, gw, gh = group.get("bounding", [0, 0, 0, 0])
            if gx <= x <= gx + gw and gy <= y <= gy + gh:
                controls_outside_wrappers = False
                errors.append(f"global control node {node.get('title')} is inside {group.get('title')}")
    def overlap_area(first: list[int], second: list[int]) -> int:
        fx, fy, fw, fh = first[:4]
        sx, sy, sw, sh = second[:4]
        return max(0, min(fx + fw, sx + sw) - max(fx, sx)) * max(0, min(fy + fh, sy + sh) - max(fy, sy))

    wrapper_overlap_count = sum(
        1 for index, first in enumerate(model_wrappers)
        for second in model_wrappers[index + 1:]
        if overlap_area(first.get("bounding", [0, 0, 0, 0]), second.get("bounding", [0, 0, 0, 0])) > 0
    )
    inner_overlap_count = 0
    for suffix in ("· A1 原版", "· A29 2.9B", "· K2 Krea2"):
        branch_groups = [
            group for group in data.get("groups", [])
            if isinstance(group.get("title"), str) and group["title"].endswith(suffix)
        ]
        inner_overlap_count += sum(
            1 for index, first in enumerate(branch_groups)
            for second in branch_groups[index + 1:]
            if overlap_area(first.get("bounding", [0, 0, 0, 0]), second.get("bounding", [0, 0, 0, 0])) > 0
        )
    node_overlap_count = 0
    for wrapper in model_wrappers:
        wx, wy, ww, wh = wrapper.get("bounding", [0, 0, 0, 0])
        wrapper_nodes = []
        for node in data.get("nodes", []):
            nx, ny = node.get("pos", [0, 0])[:2]
            nw, nh = node.get("size", [300, 200])[:2]
            if wx <= nx + nw / 2 <= wx + ww and wy <= ny + nh / 2 <= wy + wh:
                wrapper_nodes.append(node)
        for index, first in enumerate(wrapper_nodes):
            fx, fy = first.get("pos", [0, 0])[:2]
            fw, fh = first.get("size", [300, 200])[:2]
            for second in wrapper_nodes[index + 1:]:
                if overlap_area([fx, fy, fw, fh], [*second.get("pos", [0, 0])[:2], *second.get("size", [300, 200])[:2]]) > 0:
                    node_overlap_count += 1
    if integration.get("layout") == "tight_groups_measured_pack" and wrapper_overlap_count:
        errors.append(f"compact model wrappers overlap: {wrapper_overlap_count}")
    if integration.get("layout") == "tight_groups_measured_pack" and inner_overlap_count:
        errors.append(f"compact inner groups overlap: {inner_overlap_count}")
    if integration.get("layout") == "tight_groups_measured_pack" and node_overlap_count:
        errors.append(f"compact nodes overlap: {node_overlap_count}")
    if model_wrappers:
        left = min(group["bounding"][0] for group in model_wrappers)
        top = min(group["bounding"][1] for group in model_wrappers)
        right = max(group["bounding"][0] + group["bounding"][2] for group in model_wrappers)
        bottom = max(group["bounding"][1] + group["bounding"][3] for group in model_wrappers)
        wrapper_extent = {"left": left, "top": top, "right": right, "bottom": bottom, "width": right - left, "height": bottom - top}
    else:
        wrapper_extent = None
    receipt = {
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "workflow": str(workflow),
        "workflow_sha256": sha256(workflow),
        "template": str(ROOT / "production_tools" / "templates" / workflow.name),
        "template_sha256": sha256(ROOT / "production_tools" / "templates" / workflow.name),
        "workflow_variant": data.get("extra", {}).get("workflow_variant"),
        "layout": data.get("extra", {}).get("codex_uap_integration", {}).get("layout"),
        "counts": {
            "nodes": len(data.get("nodes", [])),
            "links": len(data.get("links", [])),
            "groups": len(data.get("groups", [])),
            "subgraphs": len(data.get("definitions", {}).get("subgraphs", [])),
            "qgn_navigation_slots": len(qgn),
        },
        "branch_policy": integration.get("branch_policy"),
        "default_active_branch": integration.get("default_active_branch"),
        "branch_mode_stats": branch_stats,
        "controls_outside_model_wrappers": controls_outside_wrappers,
        "layout_metrics": {
            "model_wrapper_overlap_count": wrapper_overlap_count,
            "inner_group_overlap_count": inner_overlap_count,
            "node_overlap_pairs": node_overlap_count,
            "model_wrapper_extent": wrapper_extent,
        },
        "source_workflows": [
            {"file": str(path), "exists": path.exists(), "sha256": sha256(path) if path.exists() else None}
            for path in source_paths
        ],
        "qgn_exact_group_targets": all(item.get("groupName") in titles for item in qgn),
        "validation_errors": errors,
        "plugin_static_assets": {
            "javascript_exists": PLUGIN_JS.exists(),
            "stylesheet_exists": PLUGIN_CSS.exists(),
            "stylesheet_url": "/extensions/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/quick_group_navigation/styles.css",
        },
        "server_checks": {
            "system_stats": endpoint("/system_stats"),
            "object_info": endpoint("/object_info"),
            "qgn_stylesheet": endpoint("/extensions/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/quick_group_navigation/styles.css"),
        },
        "ui_checks": {
            "status": "not_run_by_static_validator",
            "queue_submitted": False,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "validation": "passed" if not errors else "failed", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
