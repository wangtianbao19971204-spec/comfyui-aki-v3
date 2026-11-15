#!/usr/bin/env python3
"""Build and validate the standalone lightweight UAP production workflow suite.

Upgrades existing standalone workflows and extracts the standalone image-caption
workflow into byte-identical pairs under:
  - snapshot/runtime/ComfyUI/user/default/workflows/
  - snapshot/runtime/production_tools/templates/

Design invariants:
  1. Never mutate user-saved prompt strings, LoRA lists, model selections, seeds,
     or sampling parameters in existing workflows.
  2. Krea2_精简生产_v1.json drops legacy depth/pose control (#1160/#1161/#1187/#1190/#130163
     and subgraph 945c8bd5-57ab-4054-ae97-da28ca17ccfc), wiring #1173 MODEL directly
     to #1200 KSampler and #1192 UltimateSDUpscale.
  3. 工具_图片反推_提示词提取.json extracts the 3-way captioning pipeline (PixAI local tagger,
     JoyCaption 3-way, Multi-API 5-model + Judge) plus a positive draft prompt node (#1233)
     and Fast Groups Muter (#1227) into an independent UAP workflow.
  4. 生产扩展_04 / 06 / 08 / 09 gain clean non-overlapping UAP groups and uap_workbench
     metadata with zero changes to node IDs, links, or widget values.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from build_moss_workflow import MODEL_CONTRACTS

TOOLS_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = TOOLS_DIR.parent
WORKFLOWS_DIR = RUNTIME_DIR / "ComfyUI" / "user" / "default" / "workflows"
TEMPLATES_DIR = TOOLS_DIR / "templates"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_pair(filename: str, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for folder in (WORKFLOWS_DIR, TEMPLATES_DIR):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_text(rendered, encoding="utf-8")


def overlap_area(box_a: list[float], box_b: list[float]) -> float:
    ax, ay, aw, ah = box_a[:4]
    bx, by, bw, bh = box_b[:4]
    dx = min(ax + aw, bx + bw) - max(ax, bx)
    dy = min(ay + ah, by + bh) - max(ay, by)
    return max(0.0, dx) * max(0.0, dy)


def make_group_from_nodes(
    title: str,
    nodes: list[dict[str, Any]],
    color: str,
    pad_x: int = 28,
    pad_top: int = 64,
    pad_bottom: int = 28,
) -> dict[str, Any]:
    if not nodes:
        raise ValueError(f"Empty group {title}")
    left = min(float(n["pos"][0]) for n in nodes) - pad_x
    top = min(float(n["pos"][1]) for n in nodes) - pad_top
    right = max(float(n["pos"][0]) + float(n["size"][0]) for n in nodes) + pad_x
    bottom = max(float(n["pos"][1]) + float(n["size"][1]) for n in nodes) + pad_bottom
    return {
        "title": title,
        "bounding": [round(left), round(top), round(right - left), round(bottom - top)],
        "color": color,
        "font_size": 24,
        "flags": {},
    }


def verify_workflow_geometry_and_links(name: str, wf: dict[str, Any]) -> None:
    nodes_by_id = {int(n["id"]): n for n in wf["nodes"]}
    if len(nodes_by_id) != len(wf["nodes"]):
        raise AssertionError(f"{name}: duplicate node IDs")

    link_ids = set()
    for link in wf["links"]:
        lid, src_id, src_slot, dst_id, dst_slot = int(link[0]), int(link[1]), int(link[2]), int(link[3]), int(link[4])
        if lid in link_ids:
            raise AssertionError(f"{name}: duplicate link #{lid}")
        link_ids.add(lid)
        if src_id not in nodes_by_id or dst_id not in nodes_by_id:
            raise AssertionError(f"{name}: dangling link #{lid} ({src_id} -> {dst_id})")
        src_links = nodes_by_id[src_id]["outputs"][src_slot].get("links") or []
        if lid not in src_links:
            raise AssertionError(f"{name}: source #{src_id}[{src_slot}] missing link #{lid}")
        if nodes_by_id[dst_id]["inputs"][dst_slot].get("link") != lid:
            raise AssertionError(f"{name}: target #{dst_id}[{dst_slot}] missing link #{lid}")

    for n in wf["nodes"]:
        for inp in n.get("inputs", []):
            lid = inp.get("link")
            if lid is not None and int(lid) not in link_ids:
                raise AssertionError(f"{name}: node #{n['id']} input {inp.get('name')} has orphan link {lid}")
        for out in n.get("outputs", []):
            for lid in out.get("links") or []:
                if int(lid) not in link_ids:
                    raise AssertionError(f"{name}: node #{n['id']} output {out.get('name')} has orphan link {lid}")

    groups = wf.get("groups", [])
    group_titles = {g["title"] for g in groups}
    for n in wf["nodes"]:
        lg = n.get("properties", {}).get("uap_layout_group")
        if lg not in group_titles:
            raise AssertionError(f"{name}: node #{n['id']} uap_layout_group={lg!r} not in groups")

    # Verify zero node-node overlap across the entire workflow
    for idx, a in enumerate(wf["nodes"]):
        box_a = [float(a["pos"][0]), float(a["pos"][1]), float(a["size"][0]), float(a["size"][1])]
        for b in wf["nodes"][idx + 1 :]:
            box_b = [float(b["pos"][0]), float(b["pos"][1]), float(b["size"][0]), float(b["size"][1])]
            if overlap_area(box_a, box_b) > 0:
                raise AssertionError(f"{name}: nodes #{a['id']} and #{b['id']} overlap")

    # Verify zero group-group overlap
    for idx, ga in enumerate(groups):
        for gb in groups[idx + 1 :]:
            if overlap_area(ga["bounding"], gb["bounding"]) > 0:
                raise AssertionError(f"{name}: groups {ga['title']!r} and {gb['title']!r} overlap")

    # Verify stage groups are strictly disjoint and cover all groups
    uap = wf["extra"]["uap_workbench"]
    for branch in uap["branches"]:
        stage_groups = [g for s in branch["stages"] for g in s["groups"]]
        if len(stage_groups) != len(set(stage_groups)):
            raise AssertionError(f"{name}: duplicate group across stages: {stage_groups}")
        if set(stage_groups) != group_titles:
            raise AssertionError(f"{name}: stage groups {set(stage_groups)} != workflow groups {group_titles}")


def build_krea2_lean() -> dict[str, Any]:
    src_path = TEMPLATES_DIR / "Krea2_精简生产_v1.json"
    if not src_path.exists():
        src_path = WORKFLOWS_DIR / "Krea2_精简生产_v1.json"
    wf = copy.deepcopy(read_json(src_path))

    # Remove depth/pose control nodes and subgraph
    removed_nodes = {1160, 1161, 1187, 1190, 130163}
    removed_links = {10254, 10255, 10257, 10258, 338024, 338026, 338027, 338031}

    wf["nodes"] = [n for n in wf["nodes"] if int(n["id"]) not in removed_nodes]
    wf["definitions"] = {"subgraphs": []}

    new_links = []
    for link in wf["links"]:
        lid = int(link[0])
        if lid in removed_links:
            continue
        if lid == 10259:
            # Rewire KSampler #1200 model input directly from #1173 Lora Loader (LoraManager) slot 0
            new_links.append([10259, 1173, 0, 1200, 0, "MODEL"])
        else:
            new_links.append(link)
    wf["links"] = new_links

    by_id = {int(n["id"]): n for n in wf["nodes"]}
    for n in wf["nodes"]:
        for inp in n.get("inputs", []):
            if inp.get("link") in removed_links:
                inp["link"] = None
        for out in n.get("outputs", []):
            if isinstance(out.get("links"), list):
                out["links"] = [lid for lid in out["links"] if lid not in removed_links]

    if 10259 not in by_id[1173]["outputs"][0]["links"]:
        by_id[1173]["outputs"][0]["links"].append(10259)
    by_id[1200]["inputs"][0]["link"] = 10259

    # Ensure LoraManager widget IDs metadata on all 4 LoRA nodes
    for lid_node in (1199, 1181, 1197, 1173):
        by_id[lid_node].setdefault("properties", {})["__lm_widget_ids"] = [
            "__lm_autocomplete_meta_text",
            "text",
            "loras",
        ]

    by_id[1183]["title"] = "[02C] 基础模型 · Krea2"
    by_id[1206]["title"] = "[01A-IMG2IMG-IN] 图生图 / 遮罩修复输入图"
    by_id[130172]["widgets_values"] = [
        "## Krea2 精简生产 v1（UAP 独立轻量工作流）\n\n"
        "- **纯粹生成链路**：`UNETLoader` → 三栏 `LoRA Stacker` + `LoRA Loader` → `KSampler` → `VAEDecode` →（可选）`1.5× USDU 分块二放` → `SaveImage`（36 节点 / 0 子图 / 已移除深度控制与反推累赘）。\n"
        "- **提示词与词库**：正向 `[00W-1] #1233`、负向 `[00W-1N] #1185`，均可在 UAP 常用控制台或完整工作台直接编写、插入共享词库与补全。\n"
        "- **模式切换**：`[00W-2]` 使用输入图（关 = 基础文生图）、`[00W-3]` 遮罩修复、`[00W-4]` 1.5× 分块二放。\n"
        "- **对等互跳**：通过顶部 UAP 流程下拉可在 Krea2、MOSS、指令编辑、图片反推、抠图、2×/4× 超分、丝袜修复之间保留草稿无损切换。\n"
    ]

    # Clean, compact, non-overlapping group layout near origin
    g1 = "01 提示词与出图模式 · Krea2"
    g2 = "02 模型、LoRA 与主采样 · Krea2"
    g3 = "03 成品预览与保存 · Krea2"
    g4 = "04 图生图与遮罩修复 · Krea2"
    g5 = "05 分块二放 1.5× 与说明 · Krea2"

    layout: dict[int, tuple[str, list[int], list[int] | None]] = {
        # Group 1: Prompts & Switches (x: 40..840, y: 140..760)
        1233: (g1, [40, 140], [420, 240]),
        1185: (g1, [40, 430], [420, 150]),
        1210: (g1, [490, 140], [330, 60]),
        1211: (g1, [490, 235], [330, 60]),
        1219: (g1, [490, 330], [330, 60]),
        1179: (g1, [490, 430], [330, 110]),
        1178: (g1, [490, 580], [330, 110]),
        # Group 2: Models, LoRAs & Main Sampler (x: 930..2190, y: 140..930)
        1183: (g2, [930, 140], [380, 100]),
        1177: (g2, [930, 280], [380, 110]),
        1201: (g2, [930, 430], [380, 70]),
        1205: (g2, [930, 540], [380, 110]),
        1186: (g2, [930, 690], [380, 110]),
        1199: (g2, [1350, 140], [410, 190]),
        1181: (g2, [1350, 370], [410, 190]),
        1197: (g2, [1350, 600], [410, 190]),
        1173: (g2, [1800, 140], [410, 240]),
        1200: (g2, [1800, 420], [410, 280]),
        1135: (g2, [1800, 740], [410, 60]),
        # Group 3: Delivery Preview & Save (x: 2320..2760, y: 140..780)
        1138: (g3, [2320, 140], [420, 340]),
        1136: (g3, [2320, 520], [420, 90]),
        1226: (g3, [2320, 650], [420, 110]),
        # Group 4: Img2Img & Inpaint Routing (x: 40..1520, y: 980..1530)
        1206: (g4, [40, 980], [420, 340]),
        1203: (g4, [40, 1360], [420, 95]),
        1202: (g4, [500, 980], [310, 80]),
        1209: (g4, [500, 1100], [310, 105]),
        1214: (g4, [500, 1245], [310, 70]),
        1215: (g4, [500, 1350], [310, 70]),
        1216: (g4, [500, 1455], [310, 70]),
        1212: (g4, [850, 980], [310, 105]),
        1213: (g4, [850, 1130], [310, 105]),
        1217: (g4, [850, 1280], [310, 105]),
        1218: (g4, [850, 1430], [310, 105]),
        # Group 5: 1.5x USDU & README (x: 1280..2740, y: 980..1640)
        1158: (g5, [1280, 980], [360, 80]),
        1220: (g5, [1280, 1100], [360, 105]),
        130172: (g5, [1280, 1250], [480, 340]),
        1192: (g5, [1800, 980], [410, 640]),
    }

    for nid, (gname, pos, size) in layout.items():
        node = by_id[nid]
        node["pos"] = list(pos)
        if size is not None:
            node["size"] = list(size)
        node["mode"] = 0
        props = node.setdefault("properties", {})
        props["uap_layout_group"] = gname
        props["uap_default_mode"] = 0
        props.pop("uap_compact_widgets", None)
        props.pop("control_source", None)

    group_specs = [
        (g1, "#4D6C5B"),
        (g2, "#46637A"),
        (g3, "#5E7352"),
        (g4, "#6C5B4D"),
        (g5, "#5D5370"),
    ]
    wf["groups"] = [
        make_group_from_nodes(title, [n for n in wf["nodes"] if n["properties"]["uap_layout_group"] == title], color)
        for title, color in group_specs
    ]

    all_ids = sorted(int(n["id"]) for n in wf["nodes"])
    wf["id"] = "krea2-lean-production-v1"
    extra = wf.setdefault("extra", {})
    extra["workflow_display_name"] = "Krea2 精简生产 v1"
    extra["workflow_variant"] = "krea2_lean_uap_v1"
    extra["qgn_navigation_groups"] = [
        {"groupName": title, "shortcut": str(i + 1)} for i, (title, _) in enumerate(group_specs)
    ]
    extra["uap_model_contracts"] = copy.deepcopy(MODEL_CONTRACTS)
    extra["uap_workbench"] = {
        "version": 1,
        "activeBranch": "k2",
        "viewBranch": "k2",
        "stage": "daily",
        "compactWidgets": False,
        "branches": [
            {
                "id": "k2",
                "label": "Krea2 图像生成",
                "modelFamily": "krea2",
                "depthControl": False,
                "dailyRows": [[g1, g2, g3]],
                "group": g1,
                "nodeIds": all_ids,
                "modes": {str(i): 0 for i in all_ids},
                "stages": [
                    {"id": "daily", "label": "日常生图", "groups": [g1, g2, g3]},
                    {"id": "input", "label": "图生图与遮罩", "groups": [g4]},
                    {"id": "refine", "label": "1.5× 二放与说明", "groups": [g5]},
                ],
            }
        ],
    }
    extra["ds"] = {"scale": 0.72, "offset": [40, 40]}
    verify_workflow_geometry_and_links("Krea2_精简生产_v1.json", wf)
    return wf


def build_caption_extract() -> dict[str, Any]:
    uap = read_json(TEMPLATES_DIR / "UAP统一生产工作台_v2.json")
    uap_by_id = {int(n["id"]): copy.deepcopy(n) for n in uap["nodes"]}

    g_in = "CORE-01A 参考图输入与提示词整理 · 反推"
    g_pixai = "SW-01C PixAI 标签反推 · 反推"
    g_joy = "SW-01D JoyCaption 三路反推 · 反推"
    g_online = "SW-01B 在线五模型反推 · 反推"

    extract_ids = [
        1206, 1203, 1227,
        1156, 1171,
        1130, 1133, 1129, 1132, 1131, 1134,
        1151, 1184, 1207, 1165, 1174, 1204, 1166, 1154, 1175,
    ]
    nodes = [uap_by_id[nid] for nid in extract_ids]

    # Add #1233 positive draft prompt node & #130172 README node
    draft_node = {
        "id": 1233,
        "type": "CR Prompt Text",
        "title": "[00W-1] 反推提示词整理草稿（正向）",
        "pos": [40, 540],
        "size": [440, 220],
        "flags": {},
        "order": 20,
        "mode": 0,
        "inputs": [{"localized_name": "prompt", "name": "prompt", "type": "STRING", "widget": {"name": "prompt"}, "link": None}],
        "outputs": [
            {"localized_name": "prompt", "name": "prompt", "type": "STRING", "links": []},
            {"localized_name": "show_help", "name": "show_help", "type": "STRING", "links": []},
        ],
        "properties": {"Node name for S&R": "CR Prompt Text"},
        "widgets_values": [""],
    }
    readme_node = {
        "id": 130172,
        "type": "MarkdownNote",
        "title": "[00-README] 图片反推 · 提示词提取",
        "pos": [520, 540],
        "size": [380, 220],
        "flags": {},
        "order": 21,
        "mode": 0,
        "inputs": [],
        "outputs": [],
        "properties": {"Node name for S&R": "MarkdownNote"},
        "widgets_values": [
            "## 图片反推 · 提示词提取（UAP 独立工具工作流）\n\n"
            "- **PixAI 标签反推（默认启用）**：本地极速 Danbooru/动漫标签提取，直接点击「运行当前反推任务」或完整工作台「开始反推」。\n"
            "- **JoyCaption 三路反推（按需开启）**：本地自然语言草稿、Tag 与设计语言分析。\n"
            "- **在线五模型并发反推（按需开启）**：并发调用 5 路视觉模型并经 Judge 汇总为混合提示词。\n"
            "- **整理与带走**：反推结果可一键「复制结果」或「追加到正向」汇总到 `#1233` 草稿框，再通过顶部 UAP 下拉切回 Krea2 / MOSS 生成。\n"
        ],
    }
    nodes.extend([draft_node, readme_node])

    kept_set = {int(n["id"]) for n in nodes}
    kept_links = []
    for link in uap["links"]:
        if int(link[1]) in kept_set and int(link[3]) in kept_set:
            kept_links.append(copy.deepcopy(link))
    kept_link_ids = {int(l[0]) for l in kept_links}

    by_id = {int(n["id"]): n for n in nodes}
    for n in nodes:
        for inp in n.get("inputs", []):
            if inp.get("link") is not None and int(inp["link"]) not in kept_link_ids:
                inp["link"] = None
        for out in n.get("outputs", []):
            if isinstance(out.get("links"), list):
                out["links"] = [lid for lid in out["links"] if int(lid) in kept_link_ids]

    # Clear stale cached runtime output previews from ShowText nodes
    for nid in (1171, 1132, 1133, 1134, 1207, 1165, 1174, 1204, 1166, 1175):
        by_id[nid]["widgets_values"] = [""]

    by_id[1206]["title"] = "[01A] 待反推参考图输入"
    by_id[1203]["title"] = "[01B] 在线识图长边缩放 · 1024"
    by_id[1227]["title"] = "CTRL-00 反推引擎开关（PixAI 默认开启）"
    by_id[1156]["title"] = "[01C-PixAI] PixAI 本地 Tag 反推"

    # Layout & default modes: PixAI (SW-01C) enabled by default (mode=0); heavy JoyCaption & Multi-API muted (mode=2)
    layout: dict[int, tuple[str, int, list[int], list[int]]] = {
        # Group 1: Input & Draft (x: 40..900, y: 140..760)
        1206: (g_in, 0, [40, 140], [440, 350]),
        1203: (g_in, 0, [520, 140], [380, 100]),
        1227: (g_in, 0, [520, 280], [380, 210]),
        1233: (g_in, 0, [40, 540], [440, 220]),
        130172: (g_in, 0, [520, 540], [380, 220]),
        # Group 2: SW-01C PixAI (x: 1000..1820, y: 140..520) -> mode 0!
        1156: (g_pixai, 0, [1000, 140], [390, 340]),
        1171: (g_pixai, 0, [1430, 140], [390, 340]),
        # Group 3: SW-01D JoyCaption 3-way (x: 1000..1820, y: 650..1580) -> mode 2
        1130: (g_joy, 2, [1000, 650], [390, 270]),
        1133: (g_joy, 2, [1430, 650], [390, 270]),
        1129: (g_joy, 2, [1000, 960], [390, 270]),
        1132: (g_joy, 2, [1430, 960], [390, 270]),
        1131: (g_joy, 2, [1000, 1270], [390, 270]),
        1134: (g_joy, 2, [1430, 1270], [390, 270]),
        # Group 4: SW-01B Online 5-model + Judge (x: 1920..3180, y: 140..1540) -> mode 2
        1151: (g_online, 2, [1920, 140], [420, 200]),
        1184: (g_online, 2, [1920, 380], [420, 680]),
        1154: (g_online, 2, [1920, 1100], [420, 420]),
        1207: (g_online, 2, [2380, 140], [380, 220]),
        1165: (g_online, 2, [2800, 140], [380, 220]),
        1174: (g_online, 2, [2380, 400], [380, 220]),
        1204: (g_online, 2, [2800, 400], [380, 220]),
        1166: (g_online, 2, [2380, 660], [380, 220]),
        1175: (g_online, 2, [2380, 940], [800, 320]),
    }

    for nid, (gname, mode, pos, size) in layout.items():
        node = by_id[nid]
        node["pos"] = list(pos)
        node["size"] = list(size)
        node["mode"] = mode
        props = node.setdefault("properties", {})
        props["uap_layout_group"] = gname
        props["uap_default_mode"] = mode
        props.pop("uap_compact_widgets", None)

    group_specs = [
        (g_in, "#4D6C5B"),
        (g_pixai, "#46637A"),
        (g_joy, "#6C5B4D"),
        (g_online, "#5D5370"),
    ]
    groups = [
        make_group_from_nodes(title, [n for n in nodes if n["properties"]["uap_layout_group"] == title], color)
        for title, color in group_specs
    ]

    all_ids = sorted(int(n["id"]) for n in nodes)
    wf = {
        "id": "uap-standalone-caption-extract",
        "revision": 0,
        "last_node_id": max(all_ids),
        "last_link_id": max(kept_link_ids) if kept_link_ids else 0,
        "nodes": nodes,
        "links": kept_links,
        "groups": groups,
        "definitions": {"subgraphs": []},
        "config": {},
        "extra": {
            "workflow_display_name": "工具 · 图片反推与提示词提取",
            "workflow_variant": "caption_extract_uap_v1",
            "qgn_navigation_groups": [
                {"groupName": title, "shortcut": str(i + 1)} for i, (title, _) in enumerate(group_specs)
            ],
            "uap_workbench": {
                "version": 1,
                "activeBranch": "caption",
                "viewBranch": "caption",
                "stage": "daily",
                "compactWidgets": False,
                "branches": [
                    {
                        "id": "caption",
                        "label": "图片反推 · 提示词提取",
                        "defaultTask": "caption",
                        "defaultCaptionMethod": "SW-01C",
                        "group": g_in,
                        "nodeIds": all_ids,
                        "modes": {str(nid): int(by_id[nid]["mode"]) for nid in all_ids},
                        "stages": [
                            {"id": "daily", "label": "输入与 PixAI 反推", "groups": [g_in, g_pixai]},
                            {"id": "joycaption", "label": "JoyCaption 三路", "groups": [g_joy]},
                            {"id": "online", "label": "在线五模型综合", "groups": [g_online]},
                        ],
                    }
                ],
            },
            "ds": {"scale": 0.78, "offset": [40, 40]},
        },
        "version": 0.4,
    }
    verify_workflow_geometry_and_links("工具_图片反推_提示词提取.json", wf)
    return wf


def upgrade_extension_workflow(
    filename: str,
    wf_id: str,
    branch_id: str,
    branch_label: str,
    group_assignments: list[tuple[str, str, list[int]]],
    pos_overrides: dict[int, list[int]] | None = None,
    model_family: str | None = None,
) -> dict[str, Any]:
    wf = copy.deepcopy(read_json(TEMPLATES_DIR / filename))
    by_id = {int(n["id"]): n for n in wf["nodes"]}

    if pos_overrides:
        for nid, pos in pos_overrides.items():
            by_id[nid]["pos"] = list(pos)

    for title, _, member_ids in group_assignments:
        for nid in member_ids:
            node = by_id[nid]
            node["mode"] = int(node.get("mode", 0))
            props = node.setdefault("properties", {})
            props["uap_layout_group"] = title
            props["uap_default_mode"] = node["mode"]

    wf["id"] = wf_id
    wf["groups"] = [
        make_group_from_nodes(title, [by_id[nid] for nid in member_ids], color)
        for title, color, member_ids in group_assignments
    ]

    daily_groups = [title for title, _, _ in group_assignments if not title.startswith("04 ")]
    guide_groups = [title for title, _, _ in group_assignments if title.startswith("04 ")]
    stages = [{"id": "daily", "label": "日常操作", "groups": daily_groups}]
    if guide_groups:
        stages.append({"id": "guide", "label": "使用说明", "groups": guide_groups})

    all_ids = sorted(by_id.keys())
    branch_spec: dict[str, Any] = {
        "id": branch_id,
        "label": branch_label,
        "group": group_assignments[0][0],
        "nodeIds": all_ids,
        "modes": {str(nid): int(by_id[nid].get("mode", 0)) for nid in all_ids},
        "stages": stages,
    }
    if model_family:
        branch_spec["modelFamily"] = model_family

    extra = wf.setdefault("extra", {})
    extra["qgn_navigation_groups"] = [
        {"groupName": title, "shortcut": str(i + 1)} for i, (title, _, _) in enumerate(group_assignments)
    ]
    if model_family:
        extra["uap_model_contracts"] = copy.deepcopy(MODEL_CONTRACTS)
    extra["uap_workbench"] = {
        "version": 1,
        "activeBranch": branch_id,
        "viewBranch": branch_id,
        "stage": "daily",
        "compactWidgets": False,
        "branches": [branch_spec],
    }
    extra.setdefault("ds", {"scale": 0.75, "offset": [40, 80]})
    verify_workflow_geometry_and_links(filename, wf)
    return wf


def build_all() -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}

    outputs["Krea2_精简生产_v1.json"] = build_krea2_lean()
    outputs["工具_图片反推_提示词提取.json"] = build_caption_extract()

    outputs["生产扩展_04_Krea2_指令编辑.json"] = upgrade_extension_workflow(
        filename="生产扩展_04_Krea2_指令编辑.json",
        wf_id="uap-standalone-ext04-krea2-edit",
        branch_id="ext04",
        branch_label="Krea2 指令编辑",
        group_assignments=[
            ("01 输入、指令与模型 · EXT04", "#70566D", [1, 2, 8, 11, 4, 5, 12, 13]),
            ("02 尺寸与采样 · EXT04", "#46637A", [6, 14, 7, 9]),
            ("03 预览与保存 · EXT04", "#5E7352", [10, 80, 81]),
            ("04 使用说明 · EXT04", "#5A5F66", [900]),
        ],
        pos_overrides={
            6: [840, 520],
            8: [0, 1040],
            11: [0, 1560],
            900: [0, -540],
        },
        model_family="krea2",
    )

    outputs["生产扩展_06_透明素材_抠图导出.json"] = upgrade_extension_workflow(
        filename="生产扩展_06_透明素材_抠图导出.json",
        wf_id="uap-standalone-ext06-rmbg",
        branch_id="ext06",
        branch_label="透明素材抠图导出",
        group_assignments=[
            ("01 输入与抠图处理 · EXT06", "#55705A", [11, 12]),
            ("03 预览与保存 · EXT06", "#5E7352", [10, 80, 81]),
            ("04 使用说明 · EXT06", "#5A5F66", [900]),
        ],
        pos_overrides={900: [0, -540]},
    )

    outputs["生产扩展_08_超分_二倍交付.json"] = upgrade_extension_workflow(
        filename="生产扩展_08_超分_二倍交付.json",
        wf_id="uap-standalone-ext08-upscale-2x",
        branch_id="ext08",
        branch_label="超分二倍交付",
        group_assignments=[
            ("01 输入与超分缩放 · EXT08", "#4D6C5B", [11, 12, 13, 14]),
            ("03 预览与保存 · EXT08", "#5E7352", [10, 80, 81]),
            ("04 使用说明 · EXT08", "#5A5F66", [900]),
        ],
        pos_overrides={900: [0, -540]},
    )

    outputs["生产扩展_09_超分_四倍素材.json"] = upgrade_extension_workflow(
        filename="生产扩展_09_超分_四倍素材.json",
        wf_id="uap-standalone-ext09-upscale-4x",
        branch_id="ext09",
        branch_label="超分四倍素材",
        group_assignments=[
            ("01 输入与四倍超分 · EXT09", "#4D6C5B", [11, 12, 13]),
            ("03 预览与保存 · EXT09", "#5E7352", [10, 80, 81]),
            ("04 使用说明 · EXT09", "#5A5F66", [900]),
        ],
        pos_overrides={900: [0, -540]},
    )

    for fname, data in outputs.items():
        write_pair(fname, data)
    return outputs


if __name__ == "__main__":
    built = build_all()
    for name, wf in built.items():
        print(f"Built {name}: id={wf['id']} nodes={len(wf['nodes'])} links={len(wf['links'])} groups={len(wf['groups'])}")
