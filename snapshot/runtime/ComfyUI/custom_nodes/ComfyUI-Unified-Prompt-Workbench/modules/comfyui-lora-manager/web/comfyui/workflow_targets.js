import { app } from "../../scripts/app.js";
import { getNodeReference } from "./utils.js";

export function getTargetBranch(node, root = app.graph) {
    const workbench = root?.extra?.uap_workbench;
  if (getNodeReference(node)?.graph_id !== (root?.id ?? "root")) return undefined;
  return workbench?.branches?.find(branch =>
    branch.nodeIds.some(id => String(id) === String(node.id)));
}

export function isWorkflowTargetEnabled(node, root = app.graph) {
  if (!node || (node.mode !== undefined && node.mode !== 0)) return false;
  const workbench = root?.extra?.uap_workbench;
  if (!workbench) return true;
  return getTargetBranch(node, root)?.id === workbench.activeBranch;
}

export function getTargetToken(node) {
  // Vue may expose multiple proxies for a graph node. Keep the runtime token on
  // the node itself; this field is not part of its serialized properties.
  if (!node._lmTargetToken) node._lmTargetToken = crypto.randomUUID();
  return node._lmTargetToken;
}

export function openLoraBrowserForNode(node) {
  if (!isWorkflowTargetEnabled(node)) throw new Error("请先启用目标分支和 LoRA 节点。");
  const reference = getNodeReference(node);
  const branch = getTargetBranch(node);
  const url = new URL("/loras", window.location.origin);
  url.searchParams.set("lm_target", `${reference.graph_id}:${reference.node_id}`);
  url.searchParams.set("lm_token", getTargetToken(node));
  url.searchParams.set("lm_label", [branch?.label, node.title || node.comfyClass].filter(Boolean).join(" / "));
  const folder = { a1: "anima", a29: "anima", k2: "krea2" }[branch?.id];
  if (folder) url.searchParams.set("lm_folder", folder);
  window.open(url.href, "uap-lora-manager");
}
