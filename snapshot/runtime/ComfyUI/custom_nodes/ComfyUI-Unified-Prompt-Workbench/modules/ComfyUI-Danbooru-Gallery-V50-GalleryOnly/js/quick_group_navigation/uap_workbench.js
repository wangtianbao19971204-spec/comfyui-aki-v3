import { app } from "../../../scripts/app.js";
import { createDailyControls } from "./uap_daily_controls.js";
import {mountFunctionIcon} from '/extensions/ComfyUI-Unified-Prompt-Workbench/ui_identity.js';
import {installWorkflowGuard} from '/extensions/ComfyUI-Unified-Prompt-Workbench/runtime_controls.js';
import {workflowChoices, isWorkflowChoice, openWorkflowChoice} from '/extensions/ComfyUI-Unified-Prompt-Workbench/repair_workflow.js';

export function focusGroups(names, zoom = 1) {
    const groups = app.graph._groups.filter(g => names.includes(g.title));
    if (!groups.length) return false;
    const x = Math.min(...groups.map(g => g._pos[0]));
    const y = Math.min(...groups.map(g => g._pos[1]));
    const right = Math.max(...groups.map(g => g._pos[0] + g._size[0]));
    const bottom = Math.max(...groups.map(g => g._pos[1] + g._size[1]));
    const canvas = app.canvas;
    const rect = canvas.canvas.getBoundingClientRect();
    const toolbar = document.getElementById("uap-workbench-nav");
    const navBottom = toolbar && !toolbar.hidden ? toolbar.getBoundingClientRect().bottom - rect.top : 70;
    const sidebar = document.querySelector(".side-bar-panel")?.getBoundingClientRect();
    const left = Math.max(90, sidebar?.width > 0 ? sidebar.right - rect.left + 24 : 0);
    const top = Math.max(90, navBottom + 28);
    const width = rect.width - left - 40, height = rect.height - top - 80;
    const scale = Math.max(0.05, Math.min(1, width / (right - x + 48), height / (bottom - y + 48)) * zoom);
    canvas.setZoom(scale, [0, 0]);
    canvas.ds.offset[0] = (left + width / 2) / scale - (x + right) / 2;
    canvas.ds.offset[1] = (top + 24 * scale) / scale - y;
    canvas.setDirty(true, true);
    return true;
}

let panel, branchSelect, activate, status, stageRow, detailSelect, prev, next, dailyControls;
let viewBranch, stageId, detailIndex = -1;
const config = () => app.graph?.extra?.uap_workbench;
const branch = () => config()?.branches.find(b => b.id === viewBranch);
const stage = () => branch()?.stages.find(s => s.id === stageId);

function element(tag, text, parent, attrs = {}) {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    Object.assign(el, attrs);
    parent?.append(el);
    return el;
}

function view(focus=true) {
    const s = stage();
    if (!s) return;
    const names = detailIndex < 0 ? s.groups : [s.groups[detailIndex]];
    if(focus)focusGroups(names);
    config().viewBranch = viewBranch;
    config().stage = stageId;
    detailSelect.value = String(detailIndex);
    const stages = branch().stages;
    prev.disabled = stages[0] === s && detailIndex <= 0;
    next.disabled = stages.at(-1) === s && detailIndex === s.groups.length - 1;
}

function setStage(id, overview = false, focus = true) {
    stageId = id;
    const compact=id==='daily',toggle=panel.querySelector('.uap-collapse-toggle');
    panel.classList.toggle('uap-collapsed',compact);
    if(toggle){toggle.textContent=compact?'展开导航':'收起导航';toggle.setAttribute('aria-expanded',String(!compact));}
    const s = stage();
    // Daily controls stay together; advanced stages open their first tool.
    detailIndex = overview || id === "daily" ? -1 : 0;
    stageRow.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.stage === id)));
    detailSelect.replaceChildren();
    element("option", "本阶段全览", detailSelect, { value: "-1" });
    s.groups.forEach((name, i) => element("option", name.replace(/ · .+$/, ""), detailSelect, { value: String(i) }));
    view(focus);
    dailyControls.show(id === "daily");
}

function updateStatus() {
    const c = config();
    const active = c.branches.find(b => b.id === c.activeBranch);
    activate.disabled = viewBranch === c.activeBranch;
    activate.hidden = activate.disabled;
    status.textContent = activate.disabled ? "已启用" : "浏览未启用分支";
    status.title = `已启用：${active?.label || "未选择"}`;
    status.dataset.active = String(activate.disabled);
    activate.textContent = activate.disabled ? "当前分支已启用" : "启用此分支";
    dailyControls.render(branch(), viewBranch === c.activeBranch);
}

function setBranch(id, focus = true) {
    viewBranch = id;
    branchSelect.value = id;
    stageRow.replaceChildren();
    branch().stages.forEach((s, index) => {
        const button = element("button", `${index + 1} ${s.label}`, stageRow);
        button.dataset.stage = s.id;
        button.onclick = () => setStage(s.id);
    });
    updateStatus();
    if (focus) setStage(branch().stages[0].id);
}

export function syncNavigationTarget(groupName) {
    const c = config();
    if (!c) return;
    for (const b of c.branches) {
        const target = b.stages.find(s => s.groups.includes(groupName));
        if (!target) continue;
        setBranch(b.id, false);
        setStage(target.id);
        detailIndex = target.groups.indexOf(groupName);
        view();
        return;
    }
}

function activateBranch(branchId=viewBranch) {
    const c = config();
    if (!c?.branches?.some(branch=>branch.id===branchId)) throw new Error('工作流已变化，请重新选择分支。');
    if (c.activeBranch === branchId) return;
    app.graph.beforeChange();
    const previous = c.branches.find(b => b.id === c.activeBranch);
    if (previous) {
        previous.nodeIds.forEach(id => {
            const node = app.graph.getNodeById(id);
            if (node) previous.modes[id] = node.mode;
        });
    }
    for (const b of c.branches) {
        for (const id of b.nodeIds) {
            const node = app.graph.getNodeById(id);
            if (node) node.mode = b.id === branchId ? b.modes[id] ?? 0 : 2;
        }
    }
    c.activeBranch = branchId;
    c.viewBranch = branchId;
    app.graph.afterChange();
    app.graph.setDirtyCanvas(true, true);
    setBranch(branchId,false);
    setStage(branch().stages[0].id,true,false);
}

function advance(direction) {
    const steps = branch().stages.flatMap(s => s.groups.map((_, index) => ({ stage: s.id, index })));
    let index = steps.findIndex(p => p.stage === stageId && p.index === Math.max(0, detailIndex));
    const delta = detailIndex < 0 && direction > 0 ? 0 : direction;
    const target = steps[Math.max(0, Math.min(steps.length - 1, index + delta))];
    setStage(target.stage);
    detailIndex = target.index;
    view();
}

function mount() {
    const style = element("style", "", document.head);
    style.textContent = `
      #uap-workbench-nav { position:fixed; top:114px; left:76px; max-width:calc(100vw - 106px); z-index:950; color:#dce5eb; background:rgba(24,31,40,.97); border:1px solid #465460; border-radius:10px; padding:9px 12px; box-shadow:0 5px 20px #0005; font:13px/1.4 system-ui,sans-serif; }
      #uap-workbench-nav[hidden] { display:none; }
      #uap-workbench-nav .uap-row { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
      #uap-workbench-nav .uap-details { margin-top:8px; }
      #uap-workbench-nav strong { color:#9ccad5; letter-spacing:1px; margin-right:4px; }
      #uap-workbench-nav button, #uap-workbench-nav select { font:inherit; color:inherit; background:#28333f; border:1px solid #4a5966; border-radius:6px; min-height:32px; padding:4px 10px; cursor:pointer; }
      #uap-workbench-nav button:hover { background:#3a4c5a; }
      #uap-workbench-nav button:focus-visible, #uap-workbench-nav select:focus-visible { outline:2px solid #9bd5e5; outline-offset:2px; }
      #uap-workbench-nav button[aria-pressed=true] { background:#3d6574; border-color:#83aebd; color:white; }
      #uap-workbench-nav button:disabled { opacity:.5; cursor:default; }
      #uap-workbench-nav .uap-status { font-size:12px; color:#a6b8a7; }
      #uap-workbench-nav .uap-stages { margin-top:8px; }
      #uap-workbench-nav .uap-detail-select { max-width:450px; min-width:260px; }
      #uap-workbench-nav.uap-collapsed .uap-details { display:none; }
      @media(max-width:1000px) { #uap-workbench-nav { left:64px; top:114px; } #uap-workbench-nav .uap-status { display:none; } }
    `;
    panel = element("nav", "", document.body, { id: "uap-workbench-nav", hidden: true });
    panel.setAttribute("aria-label", "UAP 工作顺序导航");
    const first = element("div", "", panel, { className: "uap-row uap-primary-row" });
    dailyControls = createDailyControls(syncNavigationTarget);
    element("strong", "UAP", first);
    const mainActions = element("div", "", first, {className:"uap-main-actions"});
    mainActions.setAttribute('role','group');mainActions.setAttribute('aria-label','常用页面');
    const consoleButton=element("button", "常用控制台", mainActions, {type:"button",className:"uap-console-button",title:"调整提示词、LoRA 与生成参数"});
    mountFunctionIcon(consoleButton,'console');
    consoleButton.onclick = () => {
        panel.classList.add('uap-collapsed');collapse.textContent='展开导航';collapse.setAttribute('aria-expanded','false');
        dailyControls.render(branch(), viewBranch === config().activeBranch);
        dailyControls.show(true);
    };
    const libraryButton=element("button", "资料库", mainActions, {type:"button",className:"uap-library-button",title:"搜索、筛选与收藏提示词资料"});
    mountFunctionIcon(libraryButton,'library');
    libraryButton.onclick = async () => {
        try {
            if(!window.unifiedOpenWorkbench)throw new Error('资料库入口尚未加载，请刷新 ComfyUI。');
            await dailyControls.openWorkbench({page:'library'});
        } catch(error) {status.textContent=error.message;}
    };
    branchSelect = element("select", "", first);
    branchSelect.setAttribute("aria-label", "浏览工作分支");
    branchSelect.onchange = async () => {
        const value=branchSelect.value;
        if(!isWorkflowChoice(value)) {setBranch(value);return;}
        branchSelect.value=viewBranch;
        try {await openWorkflowChoice(app,value);}
        catch(error) {status.textContent=error.message;}
    };
    activate = element("button", "启用此分支", first);
    activate.onclick = () => activateBranch(viewBranch);
    status = element("span", "", first, { className: "uap-status" });
    status.setAttribute('role','status');
    mountThemeToggle(first);
    const collapse = element("button", "收起导航", first);
    collapse.className='uap-collapse-toggle';
    collapse.onclick = () => {
        const closed = panel.classList.toggle("uap-collapsed");
        collapse.textContent = closed ? "展开导航" : "收起导航";
        collapse.setAttribute('aria-expanded',String(!closed));
    };
    collapse.setAttribute('aria-expanded','true');collapse.setAttribute('aria-controls','uap-stage-navigation');
    const details = element("div", "", panel, { className: "uap-details",id:'uap-stage-navigation' });
    stageRow = element("div", "", details, { className: "uap-row uap-stages" });
    const bottom = element("div", "", details, { className: "uap-row uap-details" });
    prev = element("button", "← 上一步", bottom);
    prev.onclick = () => advance(-1);
    detailSelect = element("select", "", bottom, { className: "uap-detail-select" });
    detailSelect.setAttribute("aria-label", "当前阶段操作区");
    detailSelect.onchange = () => { detailIndex = Number(detailSelect.value); view(); };
    next = element("button", "下一步 →", bottom);
    next.onclick = () => advance(1);
    element("button", "回到日常操作", bottom).onclick = () => setStage(branch().stages[0].id);
    element("button", "分支全览", bottom).onclick = () => focusGroups([branch().group]);
    panel.addEventListener("keydown", event => event.stopPropagation());
    let watchedSidebar;
    const sidebarResize = new ResizeObserver(positionPanel);
    function positionPanel() {
        const sidebar = document.querySelector(".side-bar-panel");
        if (sidebar !== watchedSidebar) {
            sidebarResize.disconnect();
            if (sidebar) sidebarResize.observe(sidebar);
            watchedSidebar = sidebar;
        }
        const rect = sidebar?.getBoundingClientRect();
        const left = Math.max(76, rect?.width > 0 ? rect.right + 16 : 0);
        panel.style.left = `${left}px`;
        panel.style.maxWidth = `calc(100vw - ${left + 24}px)`;
    }
    const splitter = document.querySelector(".p-splitter-horizontal");
    if (splitter) new MutationObserver(positionPanel).observe(splitter, { childList: true });
    window.addEventListener("resize", positionPanel);
    positionPanel();
    let inSubgraph=false;
    setInterval(()=>{
        const nested=!!app.canvas?.graph&&app.canvas.graph!==(app.rootGraph||app.graph);
        if(nested===inSubgraph)return;
        inSubgraph=nested;panel.dataset.subgraph=String(nested);
        if(nested)dailyControls.show(false);
    },250);
    window.unifiedUapNavigation={activateBranch};
}

app.registerExtension({
    name: "UAP.WorkbenchNavigation",
    setup() { installWorkflowGuard(app); mount(); },
    afterConfigureGraph() {
        const c = config();
        panel.hidden = !c;
        if (!c) { dailyControls.show(false); return; }
        branchSelect.replaceChildren();
        workflowChoices(c).forEach(b => element("option", b.label, branchSelect, { value: b.value }));
        setBranch(c.viewBranch || c.activeBranch, false);
        const requestedStage = branch().stages.some(s => s.id === c.stage) ? c.stage : branch().stages[0].id;
        requestAnimationFrame(() => requestAnimationFrame(() => setStage(requestedStage)));
    },
});
import {mountThemeToggle} from '/extensions/ComfyUI-Unified-Prompt-Workbench/ui_theme.js';
