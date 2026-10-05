import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const ROUTE = "/tb_multi_api_caption_v16";

function nodeIsRunner(node) {
  return node?.comfyClass === "TB_Multi_API_Caption_SmartRunner_V16";
}

function nodeIsJudge(node) {
  return node?.comfyClass === "TB_Anima_Prompt_Judge_API_V16";
}

async function getCatalog() {
  const r = await fetch(`${ROUTE}/api/providers`);
  return await r.json();
}

function findWidget(node, name) {
  return node.widgets?.find(w => w.name === name);
}

function setComboValues(widget, values, value) {
  if (!widget) return;
  widget.options = widget.options || {};
  widget.options.values = values;
  if (value !== undefined && values.includes(value)) widget.value = value;
  else if (!values.includes(widget.value)) widget.value = values[0];
}

async function refreshCombos(node) {
  let data;
  try { data = await getCatalog(); } catch (e) { console.warn(e); return; }
  const providers = (data.providers || []).map(p => p.name).filter(Boolean);
  if (!providers.length) providers.push("<none>");

  if (nodeIsRunner(node)) {
    for (let i = 1; i <= 5; i++) {
      const pw = findWidget(node, `slot_${i}_provider`);
      const mw = findWidget(node, `slot_${i}_model`);
      setComboValues(pw, providers, pw?.value);
      const provider = (data.providers || []).find(p => p.name === pw?.value) || (data.providers || [])[0];
      let models = provider?.models || [];
      models = ["<manual>", ...models.filter(Boolean)];
      setComboValues(mw, models, mw?.value);
    }
  }

  if (nodeIsJudge(node)) {
    const pw = findWidget(node, "judge_provider");
    const mw = findWidget(node, "judge_model");
    setComboValues(pw, providers, pw?.value);
    const provider = (data.providers || []).find(p => p.name === pw?.value) || (data.providers || [])[0];
    let models = provider?.models || [];
    models = ["<manual>", ...models.filter(Boolean)];
    setComboValues(mw, models, mw?.value);
  }

  app.graph.setDirtyCanvas(true, true);
}

function toggleSlots(node) {
  node.__tbSlotsCollapsed = !node.__tbSlotsCollapsed;
  for (const w of node.widgets || []) {
    if (/^(enable_|slot_\d+_provider|slot_\d+_model)/.test(w.name)) {
      w.__tbOrigType = w.__tbOrigType || w.type;
      w.type = node.__tbSlotsCollapsed ? "hidden" : w.__tbOrigType;
      w.computeSize = node.__tbSlotsCollapsed ? () => [0, -4] : undefined;
    }
  }
  node.setSize(node.computeSize());
  app.graph.setDirtyCanvas(true, true);
}

function addToolbar(node) {
  if (node.__tbToolbarAdded) return;
  node.__tbToolbarAdded = true;

  node.addWidget("button", "⚙ 配置 API / 模型", null, () => {
    window.open(`${location.origin}${ROUTE}/config`, "_blank");
  });

  node.addWidget("button", "↻ 重新读取配置", null, () => {
    refreshCombos(node);
  });

  node.addWidget("button", "🔁 手动强制重跑", null, () => {
    bumpRunId(node);
  });

  if (nodeIsRunner(node)) {
    node.addWidget("button", "🧹 清除结果缓存", null, async () => {
      try {
        await fetch(`${ROUTE}/api/clear_cache`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({node_id: String(node.id)})
        });
        node.__tbStatus = {overall_status: "cache cleared", models: []};
        app.graph.setDirtyCanvas(true, true);
      } catch (e) {
        console.warn("TB clear cache failed", e);
      }
    });

    node.addWidget("button", "▸/▾ 折叠模型槽位", null, () => {
      toggleSlots(node);
    });
  }

  setTimeout(() => {
    refreshCombos(node).then(() => {
      if (nodeIsRunner(node)) {
        node.__tbSlotsCollapsed = false;
        toggleSlots(node);
      }
    });
  }, 300);
}

function drawStatus(node, ctx) {
  const status = node.__tbStatus;
  if (!status) return;

  const lines = [];
  if (status.overall_status) {
    lines.push(`${status.overall_status} | ${status.total_seconds ?? "-"}s`);
  }
  for (const m of status.models || []) {
    const name = (m.model || m.label || `slot ${m.slot}`).split("/").pop();
    const src = m.source === "cache" ? "cached" : (m.status || "-");
    const t = m.seconds != null ? `${m.seconds}s` : "";
    lines.push(`${m.slot}. ${src} ${t} ${name}`);
  }
  if (!lines.length) return;

  ctx.save();
  ctx.font = "11px monospace";
  const x = 8;
  const y = 28;
  const w = Math.min(node.size[0] - 16, 390);
  const h = 18 + lines.length * 15;
  ctx.fillStyle = "rgba(0,0,0,0.72)";
  ctx.strokeStyle = "rgba(255,255,255,0.22)";
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 8);
  ctx.fill();
  ctx.stroke();

  lines.forEach((line, idx) => {
    ctx.fillStyle = idx === 0 ? "rgba(255,255,255,0.95)" : "rgba(210,230,255,0.95)";
    ctx.fillText(line.slice(0, 60), x + 8, y + 16 + idx * 15);
  });
  ctx.restore();
}



function getSelectedNodes() {
  const selected = app?.canvas?.selected_nodes;
  if (!selected) return [];
  if (Array.isArray(selected)) return selected.filter(Boolean);
  return Object.values(selected).filter(Boolean);
}

function allRunnerNodes() {
  return (app?.graph?._nodes || []).filter(nodeIsRunner);
}

function setWidgetValue(node, name, value) {
  const w = findWidget(node, name);
  if (!w) return false;
  w.value = value;
  return true;
}

function bumpRunId(node) {
  const rid = findWidget(node, "run_id");
  if (!rid) return;
  rid.value = Number(rid.value || 0) + 1;
  app.graph.setDirtyCanvas(true, true);
}

function getLinkById(linkId) {
  if (linkId == null || !app?.graph) return null;
  const links = app.graph.links;
  if (!links) return null;
  if (links instanceof Map) return links.get(linkId);
  return links[linkId];
}

function getOriginFromInput(input) {
  if (!input || input.link == null) return null;
  const link = getLinkById(input.link);
  if (!link) return null;
  const originId = link.origin_id ?? link.originId ?? link.origin;
  const originSlot = link.origin_slot ?? link.originSlot ?? link.slot;
  const originNode = app.graph.getNodeById ? app.graph.getNodeById(originId) : (app.graph._nodes || []).find(n => String(n.id) === String(originId));
  if (!originNode) return null;
  return { node: originNode, slot: Number(originSlot) };
}

function computeRequestedSlotsFromSelected() {
  const selected = getSelectedNodes();
  const map = new Map();

  function markAll(runner) {
    map.set(String(runner.id), { node: runner, all: true, slots: new Set() });
  }

  function markSlot(runner, slot) {
    const key = String(runner.id);
    let item = map.get(key);
    if (!item) {
      item = { node: runner, all: false, slots: new Set() };
      map.set(key, item);
    }
    if (!item.all) item.slots.add(slot);
  }

  for (const node of selected) {
    if (nodeIsRunner(node)) {
      markAll(node);
      continue;
    }

    for (const input of node.inputs || []) {
      const origin = getOriginFromInput(input);
      if (!origin || !nodeIsRunner(origin.node)) continue;
      if (Number.isFinite(origin.slot) && origin.slot >= 0 && origin.slot <= 4) {
        markSlot(origin.node, origin.slot + 1);
      } else {
        // successful_results / status_report / debug_json or unknown aggregate output
        markAll(origin.node);
      }
    }
  }

  return { selected, map };
}

let lastPrepareAt = 0;
function prepareSmartRequestedSlots() {
  const now = performance.now();
  if (now - lastPrepareAt < 80) return;
  lastPrepareAt = now;

  const runners = allRunnerNodes();
  if (!runners.length) return;
  const { selected, map } = computeRequestedSlotsFromSelected();

  // No selected nodes usually means normal Queue Prompt: run all enabled slots.
  if (!selected.length || !map.size) {
    for (const runner of runners) {
      setWidgetValue(runner, "requested_slots", "all");
    }
    return;
  }

  for (const runner of runners) {
    const item = map.get(String(runner.id));
    let value = "none";
    if (item?.all) value = "all";
    else if (item?.slots?.size) value = Array.from(item.slots).sort((a, b) => a - b).join(",");
    setWidgetValue(runner, "requested_slots", value);
  }
}



function runnerClassName() {
  return "TB_Multi_API_Caption_SmartRunner_V16";
}

function requestedValueFromItem(item) {
  if (!item) return "none";
  if (item.all) return "all";
  if (item.slots && item.slots.size) return Array.from(item.slots).sort((a, b) => a - b).join(",");
  return "none";
}

function computeRequestedFromPromptPayload(prompt) {
  const runners = new Map();
  if (!prompt || typeof prompt !== "object") return runners;

  for (const [id, node] of Object.entries(prompt)) {
    if (node?.class_type === runnerClassName()) {
      runners.set(String(id), { all: false, slots: new Set(), consumerCount: 0 });
    }
  }

  function mark(rid, outIdx) {
    const item = runners.get(String(rid));
    if (!item) return;
    item.consumerCount += 1;
    const n = Number(outIdx);
    if (Number.isFinite(n) && n >= 0 && n <= 4) item.slots.add(n + 1);
    else item.all = true;
  }

  function scanValue(v) {
    if (Array.isArray(v) && v.length >= 2) {
      mark(v[0], v[1]);
    } else if (v && typeof v === "object") {
      for (const vv of Object.values(v)) scanValue(vv);
    }
  }

  for (const [id, node] of Object.entries(prompt)) {
    if (!node || node.class_type === runnerClassName()) continue;
    const inputs = node.inputs || {};
    for (const v of Object.values(inputs)) scanValue(v);
  }

  for (const [rid, item] of runners.entries()) {
    if (!item.consumerCount) item.all = true;
  }
  return runners;
}

function applyRequestedSlotsToPromptPayload(payload) {
  if (!payload || !payload.prompt || typeof payload.prompt !== "object") return payload;

  let selected = [];
  let selectedMap = new Map();
  try {
    const computed = computeRequestedSlotsFromSelected();
    selected = computed.selected || [];
    selectedMap = computed.map || new Map();
  } catch (e) {
    console.warn("TB selected-node detection failed; falling back to prompt graph inference", e);
  }

  const promptMap = computeRequestedFromPromptPayload(payload.prompt);
  const hasMeaningfulSelection = selected.length > 0 && selectedMap.size > 0;

  for (const [id, node] of Object.entries(payload.prompt)) {
    if (node?.class_type !== runnerClassName()) continue;
    node.inputs = node.inputs || {};

    let value;
    if (hasMeaningfulSelection) {
      value = requestedValueFromItem(selectedMap.get(String(id)));
    } else {
      value = requestedValueFromItem(promptMap.get(String(id)) || { all: true, slots: new Set() });
    }

    node.inputs.requested_slots = value;

    const liveNode = app?.graph?.getNodeById ? app.graph.getNodeById(Number(id)) : null;
    if (liveNode) {
      setWidgetValue(liveNode, "requested_slots", value);
    }
  }

  return payload;
}

function tryPatchPromptRequestArgs(args) {
  try {
    const url = String(args[0] || "");
    const init = args[1];
    const isPrompt = url.endsWith("/prompt") || url.includes("/prompt?") || url === "prompt" || url === "/prompt";
    if (!isPrompt || !init || !init.body || typeof init.body !== "string") return args;

    const payload = JSON.parse(init.body);
    if (!payload?.prompt) return args;
    applyRequestedSlotsToPromptPayload(payload);
    const patchedInit = { ...init, body: JSON.stringify(payload) };
    return [args[0], patchedInit, ...args.slice(2)];
  } catch (e) {
    console.warn("TB prompt payload patch failed", e);
    return args;
  }
}

function installPromptPayloadHook() {
  if (app.__tbMultiApiCaptionV16PayloadHooked) return;
  app.__tbMultiApiCaptionV16PayloadHooked = true;

  if (api && typeof api.fetchApi === "function") {
    const originalFetchApi = api.fetchApi.bind(api);
    api.fetchApi = function(...args) {
      return originalFetchApi(...tryPatchPromptRequestArgs(args));
    };
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = function(...args) {
    return originalFetch(...tryPatchPromptRequestArgs(args));
  };
}

function installQueueHook() {
  if (app.__tbMultiApiCaptionV16QueueHooked) return;
  app.__tbMultiApiCaptionV16QueueHooked = true;

  const original = app.queuePrompt;
  if (typeof original === "function") {
    app.queuePrompt = async function(...args) {
      try { prepareSmartRequestedSlots(); } catch (e) { console.warn("TB smart trigger failed", e); }
      return await original.apply(this, args);
    };
  }
}

api.addEventListener("tb_multi_api_caption_v16_status", (event) => {
  const detail = event.detail || {};
  for (const node of app.graph._nodes || []) {
    if (String(node.id) === String(detail.node_id)) {
      node.__tbStatus = detail.status || detail;
      app.graph.setDirtyCanvas(true, true);
      break;
    }
  }
});

app.registerExtension({
  name: "TB.MultiApiCaption.V16.RawFusionJudge",

  async setup() {
    installQueueHook();
    installPromptPayloadHook();
  },

  async beforeQueue() {
    try { prepareSmartRequestedSlots(); } catch (e) { console.warn("TB beforeQueue smart trigger failed", e); }
  },

  async nodeCreated(node) {
    if (nodeIsRunner(node) || nodeIsJudge(node)) {
      addToolbar(node);
    }
    if (nodeIsRunner(node)) {
      setTimeout(() => {
        const w = findWidget(node, "requested_slots");
        if (w) {
          w.__tbOrigType = w.__tbOrigType || w.type;
          w.type = "hidden";
          w.computeSize = () => [0, -4];
          node.setSize(node.computeSize());
          app.graph.setDirtyCanvas(true, true);
        }
      }, 100);
    }
  },

  beforeRegisterNodeDef(nodeType, nodeData, app) {
    if (nodeData.name !== "TB_Multi_API_Caption_SmartRunner_V16") return;

    const origDraw = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function(ctx) {
      if (origDraw) origDraw.apply(this, arguments);
      drawStatus(this, ctx);
    };
  }
});
