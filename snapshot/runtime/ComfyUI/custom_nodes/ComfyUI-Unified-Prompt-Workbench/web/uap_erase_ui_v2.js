import { app } from "../../../scripts/app.js";
import { mountControlSwitches } from "./control_switches.js";

// Independent UAP erase UI loader. It exists so the control card still mounts
// when an older workspace.js is cached or when workspace.js fails to mount it.
const HOST_CLASS = "uap-erase-v2-host";
const CARD_ATTR = "uapEraseV2";
let host = null;
let handle = null;
let mountedGraph = null;
let mountedBranch = null;
let styleAdded = false;

function branch() {
    const state = app.graph?.extra?.uap_workbench;
    return state?.branches?.find(item => item.id === state.activeBranch);
}

function nativeCard() {
    return document.querySelector(".desk-control-switches:not([data-uap-erase-v2])");
}

function cleanup() {
    handle?.dispose();
    handle = null;
    host?.remove();
    host = null;
    mountedGraph = null;
    mountedBranch = null;
}

function ensureHost() {
    const controls = document.querySelector("#unified-workbench .uw-workspace-controls");
    if (!controls) return null;
    if (!host) {
        host = document.createElement("div");
        host.className = `uw-control-switches-host ${HOST_CLASS}`;
        host.dataset[CARD_ATTR] = "1";
        host.style.cssText = "grid-column:1/-1;margin:0 0 14px";
    }
    if (!controls.contains(host)) {
        const prompts = controls.querySelector(".uw-prompt-grid");
        controls.insertBefore(host, prompts || controls.firstChild);
    }
    return host;
}

function ensureStyle() {
    if (styleAdded) return;
    styleAdded = true;
    const style = document.createElement("style");
    style.textContent = `
      #unified-workbench .${HOST_CLASS} .desk-control-switches{display:flex;flex-direction:column;gap:4px;margin:0;padding:12px;border:1px solid var(--uw-border,#465460);border-radius:10px;background:var(--uw-panel,#202b35)}
      #unified-workbench .${HOST_CLASS} .desk-control-switches h3{margin:0 0 4px;font-size:16px}
      #unified-workbench .${HOST_CLASS} .desk-control-switches label{display:flex;gap:8px;align-items:center;margin:4px 0}
      #unified-workbench .${HOST_CLASS} .desk-control-switches small{opacity:.8}
    `;
    document.head.append(style);
}

// 只读：这里只提示从磁盘重开，绝不把画布再喂回 loadGraphData。
// 旧实现（bindCurrentGraph / repairCurrentGraph）会把 serialize() 结果或文件内容回灌画布：
// 内核 1.55 下 WeiLinPromptUI 的 serialize id 会变成 -1，回灌后节点丢失、连线悬空，
// 随后 graphToPrompt 抛 “No input node found for id [1179] slot [1] text”。
function noticeReload(status) {
    if (!status) return;
    status.textContent = "当前画布缺少控制/擦线节点。请关闭此标签页，从工作流列表重新打开 UAP统一生产工作台_v2.json；参数在文件里，直接重开即可。";
}

function render() {
    const b = branch();
    const controls = document.querySelector("#unified-workbench .uw-workspace-controls");
    if (!b || b.id !== "k2" || b.depthControl === false || !controls) {
        cleanup();
        return;
    }
    const existing = nativeCard();
    if (existing) {
        cleanup();
        return;
    }
    const h = ensureHost();
    if (!h) return;
    ensureStyle();
    if (mountedGraph !== app.graph || mountedBranch !== b || !handle) {
        handle?.dispose();
        handle = null;
        h.replaceChildren();
        handle = mountControlSwitches(h, app, b, () => branch() === b);
        const card = h.querySelector(".desk-control-switches");
        if (card) card.dataset[CARD_ATTR] = "1";
        mountedGraph = app.graph;
        mountedBranch = b;
        if (!card) {
            const fallback = document.createElement("section");
            fallback.className = "desk-control-switches";
            fallback.dataset[CARD_ATTR] = "1";
            fallback.innerHTML = "<h3>控制与擦线</h3><p>当前画布缺少 <code>[05C2]</code>/<code>[05C7]</code>/<code>[05R2]</code>。请关闭此标签页，从工作流列表重新打开 UAP统一生产工作台_v2.json。</p>";
            const status = document.createElement("small");
            status.setAttribute("role", "status");
            status.textContent = "参数保存在文件中；重开即可恢复，不要在本页保存。";
            fallback.append(status);
            h.append(fallback);
        }
    }
    handle?.sync();
}

app.registerExtension({
    name: "UAP.EraseUI.v2",
    setup() {
        window.__uapEraseV2 = "loaded";
        setInterval(render, 750);
        render();
    },
});
