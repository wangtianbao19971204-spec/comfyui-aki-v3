"""Extend the completed audit without rerunning its UAP branch topology scans."""
import ast
import copy
import datetime
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
WORKFLOWS = ROOT / "ComfyUI/user/default/workflows"
RESULT = OUT / "workflow_inventory_all_17.json"
MATRIX = OUT / "workflow_matrix_all_17.md"
assert not RESULT.exists() and not MATRIX.exists(), "Preserve completed evidence"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

original_path = OUT / "workflow_inventory.json"
original = json.loads(original_path.read_text(encoding="utf-8"))
audit_source = OUT / "inspect_workflows.py"
tree = ast.parse(audit_source.read_text(encoding="utf-8"), filename=str(audit_source))
# Load only the existing helper definitions and their constants, before its main scan.
prefix = []
for statement in tree.body:
    if isinstance(statement, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "paths" for target in statement.targets):
        break
    if isinstance(statement, (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef)):
        prefix.append(statement)
namespace = {"__file__": str(audit_source)}
exec(compile(ast.Module(body=prefix, type_ignores=[]), str(audit_source), "exec"), namespace)
inspect = namespace["inspect"]

names = ["生产套件_02_Anima2.9B_动漫生产_v2.json"] + sorted(
    path.name for path in WORKFLOWS.glob("*.json")
    if path.name.startswith(("Anima_推荐版_", "Krea2_", "▶▷Krea2-")))
assert len(names) == 7
rows = copy.deepcopy(original["independent_workflows"])
before_hashes = {row["file"]: row["sha256"] for row in rows}
before_hashes[original["uap"]["path"]] = original["uap"]["sha256"]
assert all(sha(Path(path)) == digest for path, digest in before_hashes.items()), "Completed workflows changed"
before_hashes.update({str(WORKFLOWS / name): sha(WORKFLOWS / name) for name in names})
added = [inspect(WORKFLOWS / name) for name in names]
rows.extend(added)
rows.sort(key=lambda row: Path(row["file"]).name)
assert len(rows) == 16 and len(before_hashes) == 17

receipts_root = ROOT / "benchmark_reports/2026-09-30_next_workbench/production_selector_entry_fix"
suite02_receipts = [receipts_root / name for name in (
    "anima29_workspace_entry_browser_receipt.json",
    "anima29_library_entry_browser_receipt.json",
    "final_integrated_entry_browser_receipt.json",
    "final_reopen_lock_source_browser_receipt.json")]
assert all(path.is_file() for path in suite02_receipts)

uap = copy.deepcopy(original["uap"])

def annotate(row, branch=None):
    path = Path(row["file"])
    # One file read only provides saved modes for direct-field rejection evidence.
    # Existing UAP branch prompt topology is reused without running inspect again.
    data = raw_uap if branch else json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in data["nodes"]}
    restored = branch.get("modes", {}) if branch else {}
    for target in row["prompt_targets"]:
        encoder = nodes[target["encoder"]["id"]]
        source = target["editable_source"]
        saved_enabled = encoder.get("mode", 0) == 0 and (
            not branch or uap["active_branch_in_saved_file"] == branch["id"])
        restored_enabled = restored.get(str(encoder["id"]), encoder.get("mode", 0)) == 0
        direct_linked = target["encoder"]["input_link"] is not None
        target["direct_encoder_field_guard"] = {
            "saved_mode": encoder.get("mode", 0),
            "branch_restored_mode": restored.get(str(encoder["id"]), encoder.get("mode", 0)),
            "rejection_reasons_in_saved_file":
                ([] if saved_enabled else ["disabled_or_inactive_branch"]) + (["linked_field"] if direct_linked else []),
            "rejection_reasons_after_correct_branch_activation_expected":
                ([] if restored_enabled else ["disabled"]) + (["linked_field"] if direct_linked else []),
        }
        source_reasons = []
        if not source["writable_in_saved_graph"]:
            if source["mode"] != 0 or branch and uap["active_branch_in_saved_file"] != branch["id"]:
                source_reasons.append("disabled_or_inactive_branch")
            if source["input_link"] is not None:
                source_reasons.append("linked_field")
            if not source["saved_string_field_present"]:
                source_reasons.append("unsupported_or_missing_saved_string_field")
        target["editable_source_guard"] = {
            "rejection_reasons_in_saved_file": source_reasons,
            "writable_in_saved_graph": source["writable_in_saved_graph"],
            "writable_after_correct_branch_activation_expected": source["writable_after_correct_branch_activation_expected"],
            "live_browser_widget_readonly_checked_in_this_audit": False,
        }
        target["has_potential_sampler_path"] = bool(target["sampler_path"])
        target["direction_not_certified"] = target["direction"] == "unknown"
    if path.name == names[0]:
        row["prior_gui_evidence"] = {
            "scope": "Previous formal suite02 six-selector entry and reopen-lock verification; no repeat GUI acceptance in this audit.",
            "workflow_sha256_matches_previous_formal_a29": row["sha256"] == "d3a5ede958685ee40115f5d95295a50a6c49fc3698536bbfc6877745adb596d0",
            "receipts": [{"file": str(path), "sha256": sha(path)} for path in suite02_receipts],
        }

raw_uap = json.loads(Path(uap["path"]).read_text(encoding="utf-8"))
branch_specs = {branch["id"]: branch for branch in raw_uap["extra"]["uap_workbench"]["branches"]}
for row in rows:
    annotate(row)
for row in uap["branches"]:
    annotate(row, branch_specs[row["scope"]])
assert all(sha(Path(path)) == digest for path, digest in before_hashes.items()), "Formal files changed during audit"

result = {
    "verified_at": datetime.datetime.now().astimezone().isoformat(),
    "status": "readonly_saved_workflow_matrix_17_complete",
    "formal_workflow_files_checked": 17,
    "independent_workflow_count": 16,
    "scope": "Current production suite01/02/03/99, extensions04-09, three recommended Anima files, three older Krea2 files, and UAP v2 nine branches.",
    "excluded_retained_file": str(WORKFLOWS / "UAP统一生产工作台_v1.json"),
    "excluded_reason": "Retained UAP v1 is outside the requested current v2 matrix of 17 files.",
    "original_inventory": {"file": str(original_path), "sha256": sha(original_path), "verified_at": original["verified_at"]},
    "reused_audit_helper": {"file": str(audit_source), "sha256": sha(audit_source)},
    "uap_branch_topology_reused": True,
    "independent_workflows": rows,
    "uap": uap,
    "formal_file_sha256": before_hashes,
    "formal_files_unchanged_during_audit": True,
    "production_writes": 0, "workflow_writes": 0, "browser_actions": 0, "queue_actions": 0,
    "limits": original["limits"] + [
        "Disabled and linked statuses reflect saved fields and modes; live UI input readonly flags remain root GUI work.",
        "Other model-specific combined encoders are recorded as auxiliary encoder nodes when not on the established main prompt chain.",
        "UAP v1 is explicitly excluded; all other 17 workflow files are included.",
        "Prior suite02 receipts are historical GUI evidence, not this audit's live browser acceptance.",
    ],
}
# Combined encoders and their output links are included, but their multi-field runtime body is not synthesized.
for row in rows:
    data = json.loads(Path(row["file"]).read_text(encoding="utf-8"))
    row["other_encoder_nodes"] = [
        {"id": node["id"], "type": node["type"], "mode": node.get("mode", 0),
         "output_links": [link for output in node.get("outputs", []) for link in (output.get("links") or [])],
         "inputs": [{"name": port.get("name"), "type": port.get("type"), "link": port.get("link")} for port in node.get("inputs", [])]}
        for node in data["nodes"] if "Encode" in node["type"] and node["type"] not in namespace["ENCODERS"]
    ]
RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def target_text(row, direction):
    matches = [item for item in row["prompt_targets"] if item["direction"] == direction]
    texts = []
    for item in matches:
        source = item["editable_source"]
        source_status = "源可写" if source["writable_in_saved_graph"] else "源拒绝：" + ",".join(item["editable_source_guard"]["rejection_reasons_in_saved_file"])
        direct_status = ",".join(item["direct_encoder_field_guard"]["rejection_reasons_in_saved_file"]) or "直接字段可写"
        texts.append(f"#{source['id']}.{source['field']} → #{item['encoder']['id']}（{source_status}；编码{direct_status}）")
    return "；".join(texts) or "不适用"

def extra_guard_text(row):
    unknown = [item for item in row["prompt_targets"] if item["direction"] == "unknown"]
    return "；".join(f"#{item['encoder']['id']}方向未知/" + ",".join(item["direct_encoder_field_guard"]["rejection_reasons_in_saved_file"]) for item in unknown) or "—"

def applicability(row):
    status = row["six_selector_applicability"]
    if status.startswith("not_applicable"):
        return "不适用"
    if status.startswith("instruction"):
        return "编辑指令字段；语义未验收"
    if Path(row["file"]).name == names[0]:
        return "上一轮六入口GUI证据；本轮静态保全"
    return "正向技术可适配；GUI待核"

lines = ["# 正式17工作流与UAP九分支只读矩阵", "",
         "本轮17份文件含16份独立工作流及UAP v2；旧UAP v1保留但不在本轮范围。全部正式JSON在审计前后SHA一致。旧10份矩阵及冻结包未改；UAP九分支拓扑复用已完成库存，只补保存mode/字段连线拒绝信息。", "",
         "source可写只指已知保存STRING字段、mode和输入连线条件；不代表真实浏览器readonly、最终动态编码正文、生成实跑或模型标签语义通过。02上一轮GUI收据列于JSON，本轮不重复验收。", "",
         "| 正式文件 | 节点/短SHA | 实际正向与字段守卫 | 实际负向与字段守卫 | 六类适用性 |", "|---|---|---|---|---|"]
for row in rows:
    path = Path(row["file"])
    lines.append(f"| [{path.name}]({path.as_posix()}) | {row['node_count']} / {row['sha256'][:12]} | {target_text(row,'positive')} | {target_text(row,'negative')} | {applicability(row)} |")
path = Path(uap["path"])
lines.append(f"| [{path.name}]({path.as_posix()}) | {uap['nodes']} / {uap['sha256'][:12]} | 九分支见下表 | 九分支见下表 | 随当前分支目标 |")
lines += ["", "## UAP v2 九分支", "",
          "保存activeBranch=a1。其他分支源mode2属于未激活状态；分支切换恢复后的mode0只是静态预期。本轮不操作分支，不跨分支猜写。", "",
          "| 分支 | 节点 | 正向源 | 负向源 | 六类适用性 |", "|---|---:|---|---|---|"]
for row in uap["branches"]:
    lines.append(f"| {row['scope']} {row['label']} | {row['node_count']} | {namespace['target_text'](row,'positive') if 'target_text' in namespace else target_text(row,'positive')} | {target_text(row,'negative')} | {applicability(row)} |")
lines += ["", "## 明确拒绝与边界", "",
          "- 正向WeiLin→CLIP链应写WeiLin positive；CLIP text已linked，拒绝直写。Krea2负向应写CR Prompt Text：独立#542，UAP k2#1185；其CLIP text同样linked。", 
          "- 两份旧Krea2工作流均有#381 CLIPTextEncode（mode2，text linked→mode2的#207导入节点）。该辅助编码器拒绝写入，不作为主生成目标。其#550 AnimaPromptPlusClipEncode无输出连线，保留为未连入主链的辅助工具。",
          "- 旧▶▷Krea2整合中#164正向与#173负向mode0直接可写；#255/#264/#300 mode4旁路，拒绝写入。未知方向行仍列JSON，不靠标题强猜。",
          "- 释放显存99、抠图06、纯超分08/09均无提示词生成链，六类选择器明确不适用。扩展04为编辑指令字段，普通标签语义未验收。",
          "- 推荐版的角色/服装/姿势节点已存在不等于六类前端入口齐全；不以选择器节点存在来认证正式正向链。", "",
          "全部SHA、保存字段守卫、潜在生成路径、其他编码器、上一轮02收据及拒绝状态见workflow_inventory_all_17.json。本轮生产写入、正式工作流写入、浏览器动作、队列动作均为0。", ""]
MATRIX.write_text("\n".join(lines), encoding="utf-8")
assert all(sha(Path(path)) == digest for path, digest in before_hashes.items())
print(json.dumps({"status": result["status"], "formal_files": 17, "independent": 16,
                  "uap_branches_reused": 9, "inventory": str(RESULT), "matrix": str(MATRIX),
                  "formal_files_unchanged": True}, ensure_ascii=False))
