#!/usr/bin/env python3
"""Validate UAP read-only or export a NEW candidate from its canonical template.

Independent workflows are historical snapshots, not the current release source.
Use --legacy-sources only for an explicit experimental rebuild; the CLI never
overwrites production, templates or an existing candidate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "ComfyUI" / "user" / "default" / "workflows"
DEFAULT_OUTPUT = WORKFLOW_DIR / "UAP统一生产工作台_v1.json"
OPTIMIZED_OUTPUT = WORKFLOW_DIR / "UAP统一生产工作台_v2.json"
CANONICAL_SOURCE = ROOT / "production_tools/templates/UAP统一生产工作台_v2.json"

# The compact layout keeps source node coordinates intact relative to each
# branch, but packs the three main lanes and the utility row from measured
# source bounds.  Tight group boxes remove unused canvas area without changing
# graph connectivity or widget sizes.
BRANCH_GAP = 1200
UTILITY_GAP = 600
ROW_GAP = 1400
GROUP_MARGIN = 10

# Small, source-local collision fixes for the compact presentation.  They
# affect only the generated UAP copy; source workflows and links stay intact.
COMPACT_NODE_NUDGES = {
    "a1": {"[03I]": (80, 0)},
    "k2": {"[00B5]": (480, 0), "id:573": (0, 350)},
}


SOURCES = [
    {
        "file": "生产套件_01_Anima原版_LoRA生产_v2.json",
        "key": "a1",
        "suffix": "· A1 原版",
        "offset": (0, 0),
        "label": "Anima 原版生产",
        "nav": "[01] Anima 原版生产",
        "color": "#4D6C5B",
    },
    {
        "file": "生产套件_02_Anima2.9B_动漫生产_v2.json",
        "key": "a29",
        "suffix": "· A29 2.9B",
        "offset": (15000, 0),
        "label": "Anima 2.9B 生产",
        "nav": "[02] Anima 2.9B 生产",
        "color": "#5C5878",
    },
    {
        "file": "生产套件_03_Krea2_一体化生产_v2.json",
        "key": "k2",
        "suffix": "· K2 Krea2",
        "offset": (30000, 0),
        "label": "Krea2 生产",
        "nav": "[03] Krea2 生产",
        "color": "#4D6C5B",
    },
    {
        "file": "生产扩展_04_Krea2_指令编辑.json",
        "key": "ext04",
        "suffix": "· EXT04",
        "offset": (0, 8000),
        "label": "Krea2 指令编辑",
        "nav": "[04] Krea2 指令编辑",
        "color": "#70566D",
    },
    {
        "file": "生产扩展_05_Anima2.9_裁剪精修回贴.json",
        "key": "ext05",
        "suffix": "· EXT05",
        "offset": (5000, 8000),
        "label": "Anima2.9 裁剪精修回贴",
        "nav": "[05] Anima2.9 裁剪精修回贴",
        "color": "#78633F",
    },
    {
        "file": "生产扩展_06_透明素材_抠图导出.json",
        "key": "ext06",
        "suffix": "· EXT06",
        "offset": (10000, 8000),
        "label": "透明素材抠图导出",
        "nav": "[06] 透明素材抠图导出",
        "color": "#55705A",
    },
    {
        "file": "生产扩展_07_Anima原版_左右扩图.json",
        "key": "ext07",
        "suffix": "· EXT07",
        "offset": (15000, 8000),
        "label": "Anima 原版左右扩图",
        "nav": "[07] Anima 原版左右扩图",
        "color": "#5C5878",
    },
    {
        "file": "生产扩展_08_超分_二倍交付.json",
        "key": "ext08",
        "suffix": "· EXT08",
        "offset": (20000, 8000),
        "label": "超分二倍交付",
        "nav": "[08] 超分二倍交付",
        "color": "#4D6C5B",
    },
    {
        "file": "生产扩展_09_超分_四倍素材.json",
        "key": "ext09",
        "suffix": "· EXT09",
        "offset": (25000, 8000),
        "label": "超分四倍素材",
        "nav": "[09] 超分四倍素材",
        "color": "#4D6C5B",
    },
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def translated_pos(pos: Any, offset: tuple[int, int]) -> list[float]:
    if not isinstance(pos, list) or len(pos) < 2:
        return list(pos) if isinstance(pos, list) else [offset[0], offset[1]]
    result = list(pos)
    result[0] = result[0] + offset[0]
    result[1] = result[1] + offset[1]
    return result


def remap_link_value(value: Any, link_map: dict[int, int]) -> Any:
    if isinstance(value, int):
        return link_map.get(value, value)
    return value


def _remap_nested_link_ids(value: Any, link_map: dict[int, int]) -> Any:
    if isinstance(value, list):
        return [_remap_nested_link_ids(item, link_map) for item in value]
    if isinstance(value, dict):
        return {k: _remap_nested_link_ids(v, link_map) for k, v in value.items()}
    if isinstance(value, int):
        return link_map.get(value, value)
    return value


def _remap_subgraph_payload(item: dict[str, Any], def_map: dict[str, str], node_base: int, link_base: int, group_base: int) -> dict[str, Any]:
    """Give one subgraph private numeric namespaces as well as a UUID."""
    node_ids = [int(node["id"]) for node in item.get("nodes", []) if isinstance(node.get("id"), int) and node["id"] >= 0]
    link_ids = [int(link["id"]) for link in item.get("links", []) if isinstance(link, dict) and isinstance(link.get("id"), int)]
    group_ids = [int(group["id"]) for group in item.get("groups", []) if isinstance(group.get("id"), int)]
    node_map = {old: node_base + i for i, old in enumerate(node_ids)}
    link_map = {old: link_base + i for i, old in enumerate(link_ids)}
    group_map = {old: group_base + i for i, old in enumerate(group_ids)}

    for node in item.get("nodes", []):
        old_id = node.get("id")
        if isinstance(old_id, int) and old_id in node_map:
            node["id"] = node_map[old_id]
        if node.get("type") in def_map:
            node["type"] = def_map[node["type"]]
        for inp in node.get("inputs", []):
            if isinstance(inp.get("link"), int):
                inp["link"] = link_map.get(inp["link"], inp["link"])
        for out in node.get("outputs", []):
            links = out.get("links")
            if isinstance(links, list):
                out["links"] = [link_map.get(int(link), link) for link in links]
            elif isinstance(links, int):
                out["links"] = link_map.get(links, links)

    for link in item.get("links", []):
        if not isinstance(link, dict):
            continue
        if isinstance(link.get("id"), int):
            link["id"] = link_map.get(link["id"], link["id"])
        if isinstance(link.get("origin_id"), int):
            link["origin_id"] = node_map.get(link["origin_id"], link["origin_id"])
        if isinstance(link.get("target_id"), int):
            link["target_id"] = node_map.get(link["target_id"], link["target_id"])

    for group in item.get("groups", []):
        if isinstance(group.get("id"), int):
            group["id"] = group_map.get(group["id"], group["id"])
    for endpoint in (item.get("inputs", []), item.get("outputs", [])):
        for spec in endpoint:
            if isinstance(spec.get("linkIds"), list):
                spec["linkIds"] = [link_map.get(int(link), link) for link in spec["linkIds"]]
    # UE metadata is optional and varies by frontend version.  Remap numeric
    # link references without touching labels, UUIDs, or node coordinates.
    if isinstance(item.get("extra"), dict):
        item["extra"] = _remap_nested_link_ids(item["extra"], link_map)
    return item


def remap_subgraphs(source_defs: list[dict[str, Any]], key: str, inner_node_start: int, inner_link_start: int, inner_group_start: int) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Copy embedded subgraphs and give each source branch private UUIDs."""
    uuid_map: dict[str, str] = {}
    for subgraph in source_defs:
        old_id = str(subgraph.get("id", ""))
        # UUID5 makes regeneration stable while guaranteeing A1/A29 isolation.
        uuid_map[old_id] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"codex-uap/{key}/{old_id}"))

    copied: list[dict[str, Any]] = []
    for subgraph in source_defs:
        item = copy.deepcopy(subgraph)
        old_id = str(item.get("id", ""))
        item["id"] = uuid_map[old_id]
        item = _remap_subgraph_payload(
            item,
            uuid_map,
            inner_node_start,
            inner_link_start,
            inner_group_start,
        )
        inner_node_start += 1000
        inner_link_start += 2000
        inner_group_start += 100
        copied.append(item)
    return copied, uuid_map


def source_bounds(nodes: list[dict[str, Any]], margin: int = 160) -> list[int]:
    if not nodes:
        return [0, 0, 1200, 900]
    left = min(int(n.get("pos", [0, 0])[0]) for n in nodes)
    top = min(int(n.get("pos", [0, 0])[1]) for n in nodes)
    right = max(int(n.get("pos", [0, 0])[0]) + int(n.get("size", [300, 200])[0]) for n in nodes)
    bottom = max(int(n.get("pos", [0, 0])[1]) + int(n.get("size", [300, 200])[1]) for n in nodes)
    return [left - margin, top - margin, max(1200, right - left + 2 * margin), max(700, bottom - top + 2 * margin)]


def source_rect(nodes: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    """Return the source node rectangle before any branch translation."""
    if not nodes:
        return (0, 0, 1200, 900)
    left = min(int(n.get("pos", [0, 0])[0]) for n in nodes)
    top = min(int(n.get("pos", [0, 0])[1]) for n in nodes)
    right = max(int(n.get("pos", [0, 0])[0]) + int(n.get("size", [300, 200])[0]) for n in nodes)
    bottom = max(int(n.get("pos", [0, 0])[1]) + int(n.get("size", [300, 200])[1]) for n in nodes)
    return (left, top, max(1200, right - left), max(700, bottom - top))


def tight_group_bounds(group: dict[str, Any], source_nodes: list[dict[str, Any]], margin: int = GROUP_MARGIN) -> list[int]:
    """Fit a source group around its member nodes while preserving its identity."""
    gx, gy, gw, gh = [int(v) for v in group.get("bounding", [0, 0, 800, 500])[:4]]
    members: list[dict[str, Any]] = []
    for node in source_nodes:
        x, y = [int(v) for v in node.get("pos", [0, 0])[:2]]
        w, h = [int(v) for v in node.get("size", [300, 200])[:2]]
        cx, cy = x + w / 2, y + h / 2
        if gx <= cx <= gx + gw and gy <= cy <= gy + gh:
            members.append(node)
    if not members:
        return [gx, gy, gw, gh]
    left = min(int(n.get("pos", [0, 0])[0]) for n in members)
    top = min(int(n.get("pos", [0, 0])[1]) for n in members)
    right = max(int(n.get("pos", [0, 0])[0]) + int(n.get("size", [300, 200])[0]) for n in members)
    bottom = max(int(n.get("pos", [0, 0])[1]) + int(n.get("size", [300, 200])[1]) for n in members)
    return [left - margin, top - margin, max(260, right - left + 2 * margin), max(180, bottom - top + 2 * margin)]


def compact_offsets(source_items: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[tuple[int, int]]:
    """Pack main lanes horizontally and utilities into a tight second row."""
    offsets: list[tuple[int, int]] = [(0, 0)] * len(source_items)
    x_cursor = 0
    main_bottom = 0
    for index in range(min(3, len(source_items))):
        _, src = source_items[index]
        left, top, width, height = source_rect(src.get("nodes", []))
        offsets[index] = (x_cursor - left, -top)
        x_cursor += width + BRANCH_GAP
        main_bottom = max(main_bottom, height)

    x_cursor = 0
    utility_y = main_bottom + ROW_GAP
    for index in range(3, len(source_items)):
        _, src = source_items[index]
        left, top, width, _ = source_rect(src.get("nodes", []))
        offsets[index] = (x_cursor - left, utility_y - top)
        x_cursor += width + UTILITY_GAP
    return offsets


def compact_source(spec: dict[str, Any], source: dict[str, Any], compact: bool) -> dict[str, Any]:
    """Copy source metadata and nudge only known visual collisions in v2."""
    item = copy.deepcopy(source)
    if not compact:
        return item
    nudges = COMPACT_NODE_NUDGES.get(spec["key"], {})
    for node in item.get("nodes", []):
        title = node.get("title", "")
        nudge = nudges.get(f"id:{node.get('id')}")
        if nudge is None:
            for prefix, candidate in nudges.items():
                if not prefix.startswith("id:") and isinstance(title, str) and title.startswith(prefix):
                    nudge = candidate
                    break
        if nudge is not None:
            dx, dy = nudge
            pos = list(node.get("pos", [0, 0]))
            pos[0] += dx
            pos[1] += dy
            node["pos"] = pos
    return item


def make_group(group_id: int, title: str, bounding: list[int], color: str, pinned: bool = True) -> dict[str, Any]:
    return {
        "id": group_id,
        "title": title,
        "bounding": bounding,
        "color": color,
        "flags": {"pinned": pinned},
    }


def add_uap_note(node_id: int, group_id: int, compact: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    note = {
        "id": node_id,
        "type": "MarkdownNote",
        # Keep the control panel outside every model/extension wrapper.  A
        # group containing a real workflow node is more portable across
        # LiteGraph versions than a note-only group, while the separate
        # coordinates prevent muting A1 from muting the global selector.
        "pos": [-2000, -2200 if compact else -3530],
        "size": [1050, 760],
        "flags": {"pinned": True},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [],
        "title": "UAP统一生产工作台 · 使用说明",
        "properties": {"Node name for S&R": "MarkdownNote"},
        "widgets_values": (
            "# UAP 统一生产工作台\n\n"
            "这是一个统一画布，分支之间保持断开，避免 Anima / Krea2 的模型、CLIP、VAE 和控制链误接。\n\n"
            "## 导航\n"
            "- 快捷键 1：总控台；2：Anima 原版；3：Anima 2.9B；4：Krea2\n"
            "- 快捷键 5~8：扩展工具；9：超分二倍；0：超分四倍；L：释放显存\n"
            "- 也可以点击右下角 QGN 罗盘，按分组跳转。\n\n"
            "## 运行原则\n"
            "1. 在总控台的 UAP-00 分支单选器中选择一个分支；默认只有 Anima 原版启用。\n"
            "2. 只启用一个主模型或扩展分支；可选 SW/FX 组按需打开。\n"
            "3. 扩展工具是独立小流水线，选择后再按各自输入执行。\n"
            "4. 完成后运行 [10] 显存释放与收尾。\n\n"
            "原始工作流文件仍保留在工作流目录，可随时回退。"
        ),
        "color": "#46647A",
        "bgcolor": "#1E2A34",
    }
    group_y = -2400 if compact else -3730
    group = make_group(group_id, "[00] UAP统一工作台总控台", [-2200, group_y, 1650, 1850], "#46647A")
    return note, group


def add_branch_selector(node_id: int, compact: bool = False) -> dict[str, Any]:
    """A single global branch switch keeps queue execution resource-safe."""
    return {
        "id": node_id,
        "type": "Fast Groups Muter (rgthree)",
        "pos": [-2000, -1720 if compact else -3050],
        "size": [610, 250],
        "flags": {"pinned": True},
        "order": 1,
        "mode": 0,
        "inputs": [],
        "outputs": [{"name": "OPT_CONNECTION", "type": "*", "links": None}],
        "title": "UAP-00 主模型/扩展分支单选（默认 A1）",
        "properties": {
            "matchColors": "",
            "matchTitle": r"^\[0[1-9]\]",
            "showNav": True,
            "showAllGraphs": True,
            "sort": "alphanumeric",
            "customSortAlphabet": "[01],[02],[03],[04],[05],[06],[07],[08],[09]",
            "toggleRestriction": "always one",
        },
        "color": "#46647A",
        "bgcolor": "#1E2A34",
    }


def merge(output: Path | None, compact: bool = False) -> dict[str, Any]:
    base = read_json(WORKFLOW_DIR / SOURCES[0]["file"])
    source_items = [
        (spec, compact_source(spec, read_json(WORKFLOW_DIR / spec["file"]), compact))
        for spec in SOURCES
    ]
    layout_offsets = compact_offsets(source_items) if compact else [tuple(spec["offset"]) for spec in SOURCES]
    merged_nodes: list[dict[str, Any]] = []
    merged_links: list[list[Any]] = []
    merged_groups: list[dict[str, Any]] = []
    merged_defs: list[dict[str, Any]] = []
    nav_groups: list[dict[str, Any]] = []

    next_node_id = 1000
    next_link_id = 10000
    next_group_id = 1
    next_inner_node_id = 100000
    next_inner_link_id = 300000
    next_inner_group_id = 500000
    max_order = 0
    source_stats: list[dict[str, Any]] = []

    # The nav note and wrapper are added first so the wrapper remains behind the
    # inner source groups in LiteGraph's painter.
    note, note_group = add_uap_note(next_node_id, next_group_id, compact=compact)
    merged_nodes.append(note)
    merged_groups.append(note_group)
    nav_groups.append({"id": "uap_nav_00", "groupName": note_group["title"], "shortcutKey": "1", "zoomScale": 85, "order": 0})
    next_node_id += 1
    next_group_id += 1
    merged_nodes.append(add_branch_selector(next_node_id, compact=compact))
    next_node_id += 1

    for index, spec in enumerate(SOURCES, start=1):
        src = source_items[index - 1][1]
        branch_offset = layout_offsets[index - 1]
        old_node_ids = [int(n["id"]) for n in src.get("nodes", [])]
        old_link_ids = [int(link.get("id", link[0])) if isinstance(link, dict) else int(link[0]) for link in src.get("links", [])]
        node_map = {old: next_node_id + i for i, old in enumerate(old_node_ids)}
        next_node_id += len(old_node_ids)
        link_map = {old: next_link_id + i for i, old in enumerate(old_link_ids)}
        next_link_id += len(old_link_ids)
        group_map = {int(g["id"]): next_group_id + i for i, g in enumerate(src.get("groups", []))}
        next_group_id += len(group_map)

        defs, def_map = remap_subgraphs(
            src.get("definitions", {}).get("subgraphs", []),
            spec["key"],
            next_inner_node_id,
            next_inner_link_id,
            next_inner_group_id,
        )
        next_inner_node_id += len(defs) * 1000
        next_inner_link_id += len(defs) * 2000
        next_inner_group_id += len(defs) * 100
        merged_defs.extend(defs)

        copied_nodes: list[dict[str, Any]] = []
        order_offset = index * 1000
        for node in src.get("nodes", []):
            copied = copy.deepcopy(node)
            copied["id"] = node_map[int(node["id"])]
            copied["pos"] = translated_pos(copied.get("pos", [0, 0]), branch_offset)
            if isinstance(copied.get("order"), int):
                copied["order"] += order_offset
                max_order = max(max_order, copied["order"])
            # A single active branch is the safe default for a unified canvas.
            # The UAP-00 Fast Groups Muter can unmute another wrapper and keeps
            # the one-active rule when the user switches from the UI.
            if index != 1:
                copied["mode"] = 2
            if copied.get("type") in def_map:
                copied["type"] = def_map[copied["type"]]
            for inp in copied.get("inputs", []):
                if isinstance(inp.get("link"), int):
                    inp["link"] = remap_link_value(inp["link"], link_map)
            for out in copied.get("outputs", []):
                links = out.get("links")
                if isinstance(links, list):
                    out["links"] = [link_map.get(int(link), link) for link in links]
                elif isinstance(links, int):
                    out["links"] = link_map.get(links, links)
            props = copied.get("properties")
            if isinstance(props, dict) and isinstance(props.get("customSortAlphabet"), str):
                entries = [item.strip() for item in props["customSortAlphabet"].split(",") if item.strip()]
                props["customSortAlphabet"] = ",".join(f"{item} {spec['suffix']}" for item in entries)
            copied_nodes.append(copied)

        copied_links: list[list[Any]] = []
        for link in src.get("links", []):
            if isinstance(link, dict):
                # This format is used only inside subgraphs, but accept it for
                # forward compatibility with future ComfyUI exports.
                continue
            copied_links.append([
                link_map[int(link[0])],
                node_map[int(link[1])],
                link[2],
                node_map[int(link[3])],
                link[4],
                link[5] if len(link) > 5 else None,
            ])

        copied_groups: list[dict[str, Any]] = []
        for group in src.get("groups", []):
            copied_group = copy.deepcopy(group)
            copied_group["id"] = group_map[int(group["id"])]
            copied_group["title"] = f"{group.get('title', '未命名分组')} {spec['suffix']}"
            tight = tight_group_bounds(group, src.get("nodes", [])) if compact else group.get("bounding", [0, 0, 800, 500])
            copied_group["bounding"] = translated_pos(tight, branch_offset)
            copied_groups.append(copied_group)

        # One large wrapper is the stable QGN target for each branch.  It does
        # not replace the inner groups, so existing rgthree muters still work.
        wrapper_id = next_group_id
        next_group_id += 1
        bounds = source_bounds(copied_nodes)
        wrapper = make_group(wrapper_id, spec["nav"], bounds, spec["color"])
        merged_groups.append(wrapper)
        merged_groups.extend(copied_groups)
        shortcut = str((index + 1) % 10)  # 2..9, 0 for the ninth source
        nav_groups.append({
            "id": f"uap_nav_{index:02d}",
            "groupName": spec["nav"],
            "shortcutKey": shortcut,
            "zoomScale": 75,
            "order": index,
        })

        merged_nodes.extend(copied_nodes)
        merged_links.extend(copied_links)
        source_stats.append({
            "file": spec["file"],
            "label": spec["label"],
            "nodes": len(copied_nodes),
            "active_nodes": sum(1 for node in copied_nodes if node.get("mode", 0) == 0),
            "muted_nodes": sum(1 for node in copied_nodes if node.get("mode") == 2),
            "links": len(copied_links),
            "groups": len(copied_groups) + 1,
            "subgraphs": len(defs),
            "offset": list(branch_offset),
            "suffix": spec["suffix"],
            "layout_nudges": copy.deepcopy(COMPACT_NODE_NUDGES.get(spec["key"], {})) if compact else {},
        })

    # [10] is a navigation slot for the existing cleanup/release workflow.
    # It is represented by a compact note and a group; the actual extension 99
    # is already a standalone workflow because it must not be embedded in a
    # generation graph.
    release_note_id = next_node_id
    release_group_id = next_group_id
    if compact:
        ext_x = 0
        ext_y = max(source_rect(item[1].get("nodes", []))[1] + source_rect(item[1].get("nodes", []))[3] for item in source_items[:3]) + ROW_GAP
        for item in source_items[3:]:
            _, _, width, _ = source_rect(item[1].get("nodes", []))
            ext_x += width + UTILITY_GAP
        release_pos = [ext_x, ext_y]
    else:
        release_pos = [30000, 8000]
    release_note = {
        "id": release_note_id,
        "type": "MarkdownNote",
        "pos": release_pos,
        "size": [1000, 580],
        "flags": {"pinned": True},
        "order": max_order + 10,
        "mode": 0,
        "inputs": [],
        "outputs": [],
        "title": "[10] 显存释放与收尾",
        "properties": {"Node name for S&R": "MarkdownNote"},
        "widgets_values": "# [10] 显存释放与收尾\n\n生成完成后，执行工作流目录中的 `生产套件_99_释放模型显存_v2.json`，或使用生产工具的 `/free`、`unload_models`、`free_memory` 命令。\n\n统一工作台不把释放节点硬接到各分支，避免执行图把缓存清理误当成生成依赖。",
        "color": "#6B5942",
        "bgcolor": "#2D261D",
    }
    merged_nodes.append(release_note)
    merged_groups.append(make_group(release_group_id, "[10] 显存释放与收尾", [release_pos[0] - 200, release_pos[1] - 200, 1450, 1000], "#6B5942"))
    nav_groups.append({"id": "uap_nav_10", "groupName": "[10] 显存释放与收尾", "shortcutKey": "L", "zoomScale": 90, "order": 10})

    extra = copy.deepcopy(base.get("extra", {}))
    extra.update({
        "workflow_display_name": "UAP统一生产工作台（Anima / Krea2 / 扩展）" + (" · 紧凑排版 v2" if compact else ""),
        "workflow_variant": "unified_disconnected_branches_compact_v2" if compact else "unified_disconnected_branches",
        "qgn_navigation_groups": nav_groups,
        "qgn_locked": False,
        "codex_uap_integration": {
            "version": 2 if compact else 1,
            "branch_policy": "one_active_model_branch_at_a_time",
            "default_active_branch": "[01] Anima 原版生产",
            "muted_by_default": ["[02] Anima 2.9B 生产", "[03] Krea2 生产", "[04] Krea2 指令编辑", "[05] Anima2.9 裁剪精修回贴", "[06] 透明素材抠图导出", "[07] Anima 原版左右扩图", "[08] 超分二倍交付", "[09] 超分四倍素材"],
            "branches_are_disconnected": True,
            "navigation": "QGN exact group title + keyboard shortcut",
            "source_workflows_preserved": True,
            "model_families": ["Anima original", "Anima 2.9B", "Krea2"],
            "utility_extensions": [s["file"] for s in SOURCES if s["key"].startswith("ext")],
            "release_workflow": "生产套件_99_释放模型显存_v2.json",
            "generated_by": "production_tools/merge_unified_workflow.py",
            "layout": "tight_groups_measured_pack" if compact else "source_offsets",
            "layout_repairs": copy.deepcopy(COMPACT_NODE_NUDGES) if compact else {},
        },
        "production_suite": {
            "version": 4 if compact else 3,
            "model_family": "multi-branch",
            "integrated_modes": ["anima_original", "anima_2_9b", "krea2", "utility_extensions"],
            "safe_rule": "只启用一个主模型分支；扩展分支独立执行",
            "navigation_slots": len(nav_groups),
            "source_stats": source_stats,
        },
    })
    extra["ds"] = {"scale": 0.7, "offset": [0, 0]}

    merged = {
        "id": "uap-unified-production-workbench-v2" if compact else "uap-unified-production-workbench-v1",
        "revision": 1,
        "last_node_id": max(n["id"] for n in merged_nodes),
        "last_link_id": max((link[0] for link in merged_links), default=0),
        "nodes": merged_nodes,
        "links": merged_links,
        "groups": merged_groups,
        "definitions": {"subgraphs": merged_defs},
        "config": copy.deepcopy(base.get("config", {})),
        "extra": extra,
        "version": 0.4,
    }
    if output is not None:
        write_json(output, merged)
    return merged


def validate(data: dict[str, Any], *, forbid_browser_receiver: bool = False) -> list[str]:
    errors: list[str] = []
    node_ids = [n.get("id") for n in data.get("nodes", [])]
    if len(node_ids) != len(set(node_ids)):
        errors.append("duplicate top-level node ids")
    link_ids = [link[0] for link in data.get("links", []) if isinstance(link, list) and link]
    if len(link_ids) != len(set(link_ids)):
        errors.append("duplicate top-level link ids")
    node_set = set(node_ids)
    link_set = set(link_ids)
    for link in data.get("links", []):
        if not isinstance(link, list) or len(link) < 5:
            errors.append("malformed top-level link")
            continue
        if link[1] not in node_set or link[3] not in node_set:
            errors.append(f"link {link[0]} points to a missing node")
    for node in data.get("nodes", []):
        for inp in node.get("inputs", []):
            if isinstance(inp.get("link"), int) and inp["link"] not in link_set:
                errors.append(f"node {node['id']} input points to missing link {inp['link']}")
        for out in node.get("outputs", []):
            for link in out.get("links") or []:
                if link not in link_set:
                    errors.append(f"node {node['id']} output points to missing link {link}")
    group_titles = [g.get("title") for g in data.get("groups", [])]
    if len(group_titles) != len(set(group_titles)):
        errors.append("duplicate group titles")
    titles = {g.get("title") for g in data.get("groups", [])}
    for item in data.get("extra", {}).get("qgn_navigation_groups", []):
        if item.get("groupName") not in titles:
            errors.append(f"QGN target is not an exact group title: {item.get('groupName')}")
    def_ids = [s.get("id") for s in data.get("definitions", {}).get("subgraphs", [])]
    if len(def_ids) != len(set(def_ids)):
        errors.append("duplicate embedded subgraph ids")
    def_set = set(def_ids)
    for node in data.get("nodes", []):
        node_type = node.get("type")
        if isinstance(node_type, str) and node_type.startswith("uap-") and node_type not in def_set:
            errors.append(f"node {node.get('id')} points to missing embedded subgraph {node_type}")
    if forbid_browser_receiver:
        graphs = [data, *data.get("definitions", {}).get("subgraphs", [])]
        for graph_index, graph in enumerate(graphs):
            nodes = {node["id"]: node for node in graph.get("nodes", [])}
            if len(nodes) != len(graph.get("nodes", [])):
                errors.append(f"graph {graph_index} has duplicate node ids")
            virtual = {item["id"] for item in (graph.get("inputNode", {}), graph.get("outputNode", {})) if "id" in item}
            links = {}
            for link in graph.get("links", []):
                if isinstance(link, dict):
                    row = [link.get(key) for key in ("id", "origin_id", "origin_slot", "target_id", "target_slot")]
                elif isinstance(link, list) and len(link) >= 5:
                    row = link[:5]
                else:
                    errors.append(f"graph {graph_index} has malformed link")
                    continue
                if any(type(value) is not int for value in row):
                    errors.append(f"graph {graph_index} has invalid link fields")
                    continue
                link_id, origin, origin_slot, target, target_slot = row
                if link_id in links:
                    errors.append(f"graph {graph_index} has duplicate link {link_id}")
                links[link_id] = (origin, origin_slot, target, target_slot)
                if origin not in nodes and origin not in virtual or target not in nodes and target not in virtual:
                    errors.append(f"graph {graph_index} link {link_id} points to missing node")
            for link_id, (origin, origin_slot, target, target_slot) in links.items():
                source_ports = graph.get("inputs", []) if origin == graph.get("inputNode", {}).get("id") else nodes.get(origin, {}).get("outputs", [])
                target_ports = graph.get("outputs", []) if target == graph.get("outputNode", {}).get("id") else nodes.get(target, {}).get("inputs", [])
                if not 0 <= origin_slot < len(source_ports) or not 0 <= target_slot < len(target_ports):
                    errors.append(f"graph {graph_index} link {link_id} points to missing port")
                    continue
                source_links = source_ports[origin_slot].get("linkIds" if origin in virtual else "links") or []
                target_links = target_ports[target_slot].get("linkIds", []) if target in virtual else [target_ports[target_slot].get("link")]
                if link_id not in source_links or link_id not in target_links:
                    errors.append(f"graph {graph_index} link {link_id} is absent from its endpoint ports")
            for node in graph.get("nodes", []):
                if node.get("type") == "DanbooruBrowserImportV05":
                    errors.append(f"graph {graph_index} node {node['id']} uses retired browser receiver; use workbench pending prompts")
                for slot, inp in enumerate(node.get("inputs", [])):
                    link_id = inp.get("link")
                    if link_id is not None and (link_id not in links or links[link_id][2:] != (node["id"], slot)):
                        errors.append(f"graph {graph_index} node {node['id']} input {slot} has inconsistent link")
                for slot, out in enumerate(node.get("outputs", [])):
                    for link_id in out.get("links") or []:
                        if link_id not in links or links[link_id][:2] != (node["id"], slot):
                            errors.append(f"graph {graph_index} node {node['id']} output {slot} has inconsistent link")
            for direction, virtual_key, slots in (("input", "inputNode", graph.get("inputs", [])), ("output", "outputNode", graph.get("outputs", []))):
                virtual_id = graph.get(virtual_key, {}).get("id")
                for slot, port in enumerate(slots):
                    for link_id in port.get("linkIds") or []:
                        expected = (virtual_id, slot)
                        endpoint = links.get(link_id, (None, None, None, None))
                        if (endpoint[:2] if direction == "input" else endpoint[2:]) != expected:
                            errors.append(f"graph {graph_index} virtual {direction} {slot} has inconsistent link")
        for branch in data.get("extra", {}).get("uap_workbench", {}).get("branches", []):
            branch_ids = set(branch.get("nodeIds", []))
            if not branch_ids <= node_set:
                errors.append(f"branch {branch.get('id')} refers to missing node")
            if not set(branch.get("modes", {})) <= {str(node_id) for node_id in branch_ids}:
                errors.append(f"branch {branch.get('id')} has obsolete saved mode")
            for stage in branch.get("stages", []):
                if any(title not in titles for title in stage.get("groups", [])):
                    errors.append(f"branch {branch.get('id')} stage {stage.get('id')} refers to missing group")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="existing file to validate, or a NEW candidate file to export")
    parser.add_argument("--compact", action="store_true", help="compact layout for explicit historical-source rebuilds")
    parser.add_argument("--validate", action="store_true", help="read-only validation; never merge or write")
    parser.add_argument("--legacy-sources", action="store_true", help="rebuild historical independent sources into a candidate only")
    args = parser.parse_args()
    if args.validate and args.legacy_sources:
        parser.error("--validate is read-only and cannot be combined with --legacy-sources")
    if not args.validate and args.output is None:
        parser.error("Choose --validate to check the current UAP, or --output <new candidate.json> to export. Production is never overwritten.")
    raw_output = args.output or OPTIMIZED_OUTPUT
    output = (raw_output if raw_output.is_absolute() else ROOT / raw_output).resolve()
    canonical_payload = None
    if args.validate:
        data = read_json(output)
    else:
        protected = (WORKFLOW_DIR.resolve(), CANONICAL_SOURCE.parent.resolve())
        if any(output.is_relative_to(directory) for directory in protected):
            parser.error("Refusing production/template output. Export to a candidate directory, review and publish with guards.")
        if output.exists():
            parser.error("Candidate already exists; choose a new path. No files were changed.")
        if args.legacy_sources:
            data = merge(None, compact=args.compact)
        else:
            canonical_payload = CANONICAL_SOURCE.read_bytes()
            data = json.loads(canonical_payload)
    errors = validate(data, forbid_browser_receiver=not args.legacy_sources)
    if errors:
        raise SystemExit("Validation failed:\n- " + "\n- ".join(errors))
    if not args.validate:
        if args.legacy_sources:
            write_json(output, data)
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as stream:
                stream.write(canonical_payload)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(json.dumps({
        "output": str(output),
        "sha256": digest,
        "nodes": len(data["nodes"]),
        "links": len(data["links"]),
        "groups": len(data["groups"]),
        "subgraphs": len(data["definitions"]["subgraphs"]),
        "qgn_slots": len(data["extra"]["qgn_navigation_groups"]),
        "validation": "passed",
        "read_only": args.validate,
        "source": "checked file" if args.validate else "historical snapshots" if args.legacy_sources else str(CANONICAL_SOURCE),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
