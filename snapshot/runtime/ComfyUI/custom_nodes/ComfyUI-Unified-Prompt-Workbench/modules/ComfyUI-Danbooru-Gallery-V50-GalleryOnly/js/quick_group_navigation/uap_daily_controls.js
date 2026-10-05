import {createWidgetInserter, commitWidget as sharedCommitWidget} from '/extensions/ComfyUI-Unified-Prompt-Workbench/prompt_target.js';
import {mountPromptInspector} from '/extensions/ComfyUI-Unified-Prompt-Workbench/prompt_inspector.js';
import {mountRuntimeControls,legacyControlIssue,refinementBatchIssue,modelOptionIssue} from '/extensions/ComfyUI-Unified-Prompt-Workbench/runtime_controls.js';
import {mountRefinementControls} from '/extensions/ComfyUI-Unified-Prompt-Workbench/refinement_controls.js';
import {attachPromptAutocomplete} from '/extensions/ComfyUI-Unified-Prompt-Workbench/resource_actions.js';
import {mountThemeToggle} from '/extensions/ComfyUI-Unified-Prompt-Workbench/ui_theme.js';
import {SELECTOR_TOOLS, openPromptSelector} from '/extensions/ComfyUI-Unified-Prompt-Workbench/selector_tools.js';
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const shortTitle = value => value.replace(/^\[[^\]]+\]\s*/, "").replace(/ · .+$/, "");
const el = (tag, text, parent, props = {}) => {
    const item = Object.assign(document.createElement(tag), props);
    if (text) item.textContent = text;
    parent?.append(item);
    return item;
};

export function widgetSource(node, name) {
    const input = node?.inputs?.find(i => (i.widget?.name || i.name) === name);
    if (input?.link != null) {
        const link = app.graph.links[input.link];
        const source = link && app.graph.getNodeById(link.origin_id);
        const widget = source?.widgets?.find(w => w.name === name || w.name === "value" || w.name === "seed");
        return widget ? { node: source, widget } : null;
    }
    const widget = node?.widgets?.find(w => w.name === name);
    return widget ? { node, widget } : null;
}

function promptWidgetSource(node, preferred) {
    return widgetSource(node, preferred) || widgetSource(node, "text") || widgetSource(node, "prompt");
}

export function commitWidget(node, widget, value) {
    if (app.graph?.getNodeById(node?.id) !== node || !node?.widgets?.includes(widget)) return false;
    return sharedCommitWidget(app, node, widget, value);
}

export function resolveLocalLoraName(input, files, format = "legacy") {
    const stem = value => value.replace(/\\/g, "/").replace(/\.[^.\/]+$/, "");
    const basename = value => stem(value).split("/").at(-1);
    const exact = files.find(file => file === input);
    const matches = exact ? [exact] : files.filter(file => basename(file) === input);
    if (!matches.length) throw new Error("请选择列表中的本地 LoRA 文件。");
    if (matches.length > 1) throw new Error("存在同名文件，请选择完整目录路径。");
    if (format !== "full" && files.filter(file => basename(file).toLowerCase() === basename(matches[0]).toLowerCase()).length > 1) {
        throw new Error("存在同名文件，请先在 LoRA Manager 开启完整路径语法，再刷新控制台。");
    }
    return format === "full" ? stem(matches[0]) : basename(matches[0]);
}

export function createPromptInserter(source, branchId) {
    return createWidgetInserter(app, source, {validate: () => app.graph.extra?.uap_workbench?.activeBranch === branchId});
}

function find03ATargets(selectorNode) {
    const graph = app.graph;
    const branches = graph.extra?.uap_workbench?.branches || [];
    if (!selectorNode || selectorNode.type !== "PromptSelector" || !/^\[03A\]/.test(selectorNode.title || selectorNode.properties?.label || "")) {
        throw new Error("当前节点不是未连接输出的 [03A] PromptSelector。请从 03A 分支入口打开资料库。");
    }
    if (selectorNode.outputs?.some(output => (output?.links || []).length)) {
        throw new Error("[03A] PromptSelector 输出已连接，已拒绝直接写入以避免双写。");
    }
    if (graph.getNodeById(selectorNode.id) !== selectorNode) throw new Error("模板节点已失效，请从当前工作流重新打开。");
    const memberships = branches.filter(item => item.nodeIds?.some(id => String(id) === String(selectorNode.id)));
    if (memberships.length !== 1) throw new Error("模板节点所属分支不唯一，请检查工作流后重试。");
    const branch = memberships[0];
    if (!branch || graph.extra?.uap_workbench?.activeBranch !== branch.id) throw new Error("当前 03A 分支未启用，请先启用该分支后重试。");
    const nodes = branch.nodeIds.map(id => graph.getNodeById(id)).filter(Boolean);
    const positiveCandidates = nodes.filter(node => /^\[00W-1(?:P)?\]/.test(node.title || ""));
    const negativeCandidates = nodes.filter(node => /^\[00W-1N\]/.test(node.title || ""));
    if (positiveCandidates.length !== 1 || negativeCandidates.length !== 1) {
        throw new Error("当前 03A 分支的正向或负向目标不唯一，已拒绝猜测写入目标。");
    }
    const positive = positiveCandidates[0];
    const negative = negativeCandidates[0];
    const targets = [];
    for (const [direction, node, widgetName] of [["positive", positive, "positive"], ["negative", negative, "prompt"]]) {
        const source = promptWidgetSource(node, widgetName);
        if (source && (node.mode == null || node.mode === 0) && (source.node.mode == null || source.node.mode === 0)) targets.push({ direction, ownerNode: node, label: `${branch.label} / ${direction === "negative" ? "负向" : "正向"} #${source.node.id}`, source });
    }
    if (!targets.length) throw new Error("当前 03A 分支没有可写入的正向或负向目标。");
    return { branch, targets };
}

export async function open03ATemplateLibrary(selectorNode) {
    const { branch, targets } = find03ATargets(selectorNode);
    if (!window.weilinOpenSharedPresets) throw new Error("共享资料库尚未加载，请稍后重试。");
    const targetOptions = targets.map(target => ({ ...target.source, label: target.label, direction: target.direction, validateTarget: () => {
        const current = app.graph.getNodeById(selectorNode.id);
        return current === selectorNode && !(selectorNode.outputs || []).some(output => (output?.links || []).length) &&
            app.graph.extra?.uap_workbench?.activeBranch === branch.id &&
            app.graph.extra?.uap_workbench?.branches?.includes(branch) &&
            branch.nodeIds.some(id => String(id) === String(selectorNode.id)) &&
            branch.nodeIds.some(id => String(id) === String(target.ownerNode.id)) &&
            app.graph.getNodeById(target.ownerNode.id) === target.ownerNode &&
            (target.ownerNode.mode == null || target.ownerNode.mode === 0);
    } }));
    if(window.unifiedOpenWorkbench)return window.unifiedOpenWorkbench({page:'library',view:'plans',targetOptions});
    const choices=targetOptions.map(target=>({label:target.label,direction:target.direction,onInsert:createPromptInserter(target,branch.id)}));
    return window.weilinOpenSharedPresets({ view: "plans", targetChoices: choices });
}

export function createDailyControls(jump) {
    window.__uapOpen03ATemplateLibrary = open03ATemplateLibrary;
    const style = el("style", "", document.head);
    style.textContent = `
      #uap-daily-desk{position:fixed;left:76px;top:254px;width:min(1270px,calc(100vw - 106px));max-height:calc(100vh - 280px);overflow:auto;z-index:949;background:#19212afc;color:#dbe5ed;border:1px solid #526372;border-radius:8px;box-shadow:0 10px 36px #0008;padding:10px;font:13px/1.35 system-ui,sans-serif;box-sizing:border-box}
      #uap-daily-desk[hidden]{display:none}
      #uap-daily-desk[data-workbench-mounted] :is(.desk-expand-workbench,.uw-theme-toggle){display:none}
      body #uap-daily-desk{z-index:1001}
      body #uap-workbench-nav{z-index:1002}
      body:has(#uap-daily-desk:not([hidden])) .qgn-floating-ball{z-index:948!important}
      #uap-daily-desk *{box-sizing:border-box}
      #uap-daily-desk .desk-head{display:flex;gap:10px;align-items:center;margin-bottom:8px}
      #uap-daily-desk .desk-head small{flex:1;color:#9cb0c0}
      #uap-daily-desk fieldset{display:grid;grid-template-columns:minmax(260px,1fr) minmax(310px,1.1fr) minmax(300px,1fr);gap:10px;border:0;padding:0;margin:0;min-width:0}
      #uap-daily-desk fieldset:disabled{opacity:.55}
      #uap-daily-desk .desk-column{min-width:0}
      #uap-daily-desk .desk-parameters{grid-column:1/-1;margin-bottom:0}
      #uap-daily-desk .desk-parameters .fields{grid-template-columns:repeat(6,minmax(0,1fr))}
      #uap-daily-desk .desk-parameters .field.wide{grid-column:span 2}
      #uap-daily-desk .desk-parameters .presets{margin:0;float:right}
      #uap-daily-desk h3{font-size:13px;color:#aad4e3;margin:0 0 6px;display:flex;align-items:center;justify-content:space-between}
      #uap-daily-desk section{border:1px solid #394754;border-radius:6px;padding:8px;margin:0 0 8px;background:#202b35}
      #uap-daily-desk input,#uap-daily-desk select,#uap-daily-desk textarea,#uap-daily-desk button{font:inherit;color:inherit;background:#121a22;border:1px solid #4a5967;border-radius:4px;min-width:0;padding:4px 6px}
      #uap-daily-desk button{cursor:pointer;white-space:nowrap}
      #uap-daily-desk button:hover{background:#365060}
      #uap-daily-desk input:focus,#uap-daily-desk select:focus,#uap-daily-desk textarea:focus{outline:1px solid #80bed7}
      #uap-daily-desk textarea{display:block;width:100%;height:88px;resize:vertical;max-height:250px;margin:3px 0 6px;line-height:1.4}
      #uap-daily-desk textarea.negative{height:48px}
      #uap-daily-desk .fields{display:grid;grid-template-columns:1fr 1fr;gap:6px}
      #uap-daily-desk .field{display:grid;grid-template-columns:58px minmax(0,1fr);align-items:center;gap:4px}
      #uap-daily-desk .field.wide{grid-column:1/-1}
      #uap-daily-desk .presets{display:flex;gap:5px;margin-top:6px}
      #uap-daily-desk .presets button{flex:1}
      #uap-daily-desk .plugin-tools{display:flex;flex-wrap:wrap;gap:4px;margin:5px 0}
      #uap-daily-desk .plugin-tools button{padding:3px 6px;font-size:12px}
      #uap-daily-desk .plugin-tools .switch{padding:0;min-height:25px;font-size:12px}
      #uap-daily-desk .switches{display:grid;grid-template-columns:1fr 1fr;gap:3px 7px}
      #uap-daily-desk .switch{display:flex;align-items:center;gap:4px;min-width:0;padding:3px 0;min-height:28px}
      #uap-daily-desk .switch span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
      #uap-daily-desk input[type=checkbox]{accent-color:#62abc5;width:15px;height:15px;margin:0;flex:none}
      #uap-daily-desk .jump{padding:1px 5px;font-size:11px;background:transparent;border-color:transparent;color:#9bc8da}
      #uap-daily-desk .lora-add{display:flex;gap:4px}
      #uap-daily-desk .lora-add input{width:100%}
      #uap-daily-desk .lora-rows{max-height:190px;overflow:auto}
      #uap-daily-desk .lora-row{display:grid;grid-template-columns:16px minmax(0,1fr) 55px 24px;align-items:center;gap:4px;margin-top:5px}
      #uap-daily-desk .lora-row span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      #uap-daily-desk .lora-row input[type=number]{width:55px}
      #uap-daily-desk .lora-clip{font-size:11px;color:#aeb9c4;display:flex;align-items:center;justify-content:flex-end;gap:5px;margin-top:3px}
      #uap-daily-desk .lora-clip input{width:60px}
      #uap-daily-desk .desk-error{color:#efb6a0;font-size:12px}
      @media(max-width:1050px){#uap-daily-desk fieldset{grid-template-columns:1fr 1fr}#uap-daily-desk .desk-column:nth-child(3){grid-column:1/-1}#uap-daily-desk .desk-parameters .fields{grid-template-columns:repeat(3,minmax(0,1fr))}}
    `;
    const panel = el("div", "", document.body, { id: "uap-daily-desk", hidden: true });
    panel.setAttribute("role", "region"); panel.setAttribute("aria-label", "UAP 常用控制台");
    panel.addEventListener("keydown", e => {
        if (e.defaultPrevented || e.isComposing || e.keyCode === 229) { e.stopPropagation(); return; }
        if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
            e.preventDefault(); e.stopPropagation();
            const tools = panel.querySelector('.desk-embedded-tools');
            if (tools) tools.open = true;
            const search = panel.querySelector('.desk-find-bar input');
            search?.focus(); search?.select();
            return;
        }
        if ((e.ctrlKey || e.metaKey) && ["s", "enter"].includes(e.key.toLowerCase())) return;
        const editing = e.target.closest('input,textarea,select,[contenteditable=true]');
        if (panel.dataset.workbenchMounted && (e.key === 'Tab' || (e.key === 'Escape' && !editing))) return;
        if (e.key === 'Escape' && !editing) { e.preventDefault(); setShown(false); }
        e.stopPropagation();
    });
    for (const type of ['copy', 'cut', 'paste']) panel.addEventListener(type, event => event.stopPropagation());
    panel.addEventListener("wheel", e => e.stopPropagation());
    let currentBranch, active, sync = [], loraOptions, renderedGraph, renderedNodes = [], promptInspector, runtimeControls, refinementControls;
    const isCurrent = () => app.graph === renderedGraph && currentBranch &&
        app.graph.extra?.uap_workbench?.branches?.some(branch => branch.id === currentBranch.id) &&
        renderedNodes.every(node => app.graph.getNodeById(node.id) === node);
    for (const type of ['input','change','click']) panel.addEventListener(type, event => {
        if (event.target.closest('fieldset') && (!isCurrent() || app.graph.extra?.uap_workbench?.activeBranch !== currentBranch.id)) {
            event.preventDefault(); event.stopImmediatePropagation(); panel.hidden = true;
        }
    }, true);
    let promptInputs = [];
    const promptSources = new WeakMap();
    const attachAutocomplete = attachPromptAutocomplete;
    window.addEventListener('lora-manager:autocomplete-ready', () => promptInputs.forEach(attachAutocomplete));
    const hideAutocomplete = () => promptInputs.forEach(input => input._promptAutocompleteOwner?.hide());
    window.addEventListener("lora-manager:updated", event => {
        if (currentBranch?.nodeIds?.some(id => String(id) === String(event.detail?.nodeId))) sync.forEach(fn => fn(true));
    });
    let shown = false, returnFocus = null;
    function setShown(value) {
        const wasShown = shown && !panel.hidden, focusedInside = panel.contains(document.activeElement);
        if (value && !focusedInside) returnFocus = document.activeElement;
        shown = value; panel.hidden = !value;
        if (!value) {
            hideAutocomplete();
            if (focusedInside && returnFocus?.isConnected) returnFocus.focus({preventScroll:true});
        } else if (!wasShown || !focusedInside) panel.querySelector('button')?.focus({preventScroll:true});
        position();
    }
    function openWorkbench(options={}) {
        if(!window.unifiedOpenWorkbench)throw new Error('工作台入口正在加载，请稍后重试。');
        if(panel.dataset.workbenchMounted)return window.unifiedOpenWorkbench(options);
        const scrollTop=panel.scrollTop,focus=document.activeElement,graph=app.graph;
        return window.unifiedOpenWorkbench({...options,returnTo:{label:'常用控制台',onReturn:()=>{
            const config=app.graph?.extra?.uap_workbench;
            const branch=config?.branches?.find(item=>item.id===config.viewBranch)||config?.branches?.find(item=>item.id===config.activeBranch);
            if(!branch)return;
            if(!isCurrent()||currentBranch!==branch||active!==(branch.id===config.activeBranch))
                render(branch,branch.id===config.activeBranch);
            setShown(true);
            if(app.graph===graph){panel.scrollTop=scrollTop;if(focus?.isConnected&&panel.contains(focus))focus.focus({preventScroll:true});}
        }}});
    }
    const position = () => {
        const heading=panel.querySelector('.desk-heading small');
        if(heading&&currentBranch){const text=`${currentBranch.label} · ${!active?'浏览中，请先启用此分支':panel.dataset.workbenchMounted?'修改实时同步，使用上方任务按钮运行':'修改实时同步；运行仅处理当前图像任务'}`;if(heading.textContent!==text)heading.textContent=text;}
        if (panel.dataset.workbenchMounted) {if(panel.style.position!=='relative')panel.style.cssText='position:relative;inset:auto;width:100%;max-height:none;z-index:auto';return;}
        const nav = document.getElementById("uap-workbench-nav")?.getBoundingClientRect();
        if (!nav) return;
        const layout={top:`${nav.bottom + 8}px`,left:`${nav.left}px`,width:`min(1270px, calc(100vw - ${nav.left + 24}px))`,maxHeight:`calc(100vh - ${nav.bottom + 28}px)`};
        for(const [key,value] of Object.entries(layout))if(panel.style[key]!==value)panel.style[key]=value;
    };
    const locateOnCanvas = navigate => {
        if (panel._workbenchClose && panel._workbenchClose() === false) return;
        navigate();
        setShown(false);
        app.canvas?.canvas?.focus?.({preventScroll:true});
    };
    const openNode = node => locateOnCanvas(() => {
        const group = node.properties?.uap_layout_group;
        if (group) jump(group); else app.canvas?.centerOnNode?.(node);
    });
    function section(parent, title, node) {
        const box = el("section", "", parent), heading = el("h3", title, box);
        box.tabIndex = -1;
        if (node) el("button", "原节点 ↗", heading, { className: "jump", type: "button", onclick: () => openNode(node) });
        return box;
    }
    function bindField(parent, node, name, label, wide = false) {
        const source = widgetSource(node, name);
        const modelField=/^(unet_name|ckpt_name|clip_name|vae_name|model_name|lora_name)$/.test(name);
        if (!source) {
            if(node&&modelField){const row=el('label','',parent,{className:'field wide'});el('span',label,row);el('small','由连线控制，请从原节点调整。',row);}
            return;
        }
        const { widget } = source;
        const row = el("label", "", parent, { className: `field${wide ? " wide" : ""}` });
        el("span", label, row);
        const values = typeof widget.options?.values === "function" ? widget.options.values() : widget.options?.values;
        const control = el(Array.isArray(values)||modelField ? "select" : "input", "", row);
        control.setAttribute("aria-label", label);
        if (Array.isArray(values)||modelField) {
            if(!modelField)values.forEach(v => el("option", String(v), control, { value: String(v) }));
        }
        else {
            control.type = typeof widget.value === "number" ? "number" : "text";
            if (control.type === "number") {
                control.required = true;
                const step = widget.options?.step2;
                control.step = source.node.type === "PrimitiveFloat" ? "any" : Number.isFinite(step) && step > 0 ? String(step) : /cfg|denoise|strength/.test(name) || /降噪|强度/.test(label) || !Number.isInteger(widget.value) ? "any" : "1";
                if (Number.isFinite(widget.options?.min)) control.min = widget.options.min;
                if (Number.isFinite(widget.options?.max)) control.max = widget.options.max;
            }
        }
        control.value = widget.value;
        const modelHint=modelField?el('small','',row):null;
        const syncModel=()=>{
            if(!modelHint)return;
            const values=typeof widget.options?.values==='function'?widget.options.values():widget.options?.values;
            const available=Array.isArray(values)?values.map(String):[],current=String(widget.value??'');
            const listed=available.includes(current);
            const options=available.map(value=>{const issue=modelOptionIssue(name,value,currentBranch,app.graph.extra?.uap_model_contracts);return {value,textContent:value+(issue?'（不兼容/未核验）':''),disabled:!!issue};});
            if(widget.value!=null&&!listed)options.unshift({value:current,textContent:`${current}（当前文件不可用）`,disabled:true});
            if(control.options.length!==options.length||options.some((option,index)=>{
                const previous=control.options[index];
                return previous.value!==option.value||previous.textContent!==option.textContent||previous.disabled!==option.disabled;
            })){
                control.replaceChildren();options.forEach(option=>el('option','',control,option));control.value=current;
            }
            control.disabled=!available.length;
            modelHint.textContent=!available.length?'本地模型列表为空或尚未加载，请刷新控制台。':!listed?'当前文件不可用，请在列表中选择已有模型。':modelOptionIssue(name,current,currentBranch,app.graph.extra?.uap_model_contracts);
        };
        syncModel();
        const apply = () => {
            const value = control.type === "number" ? Number(control.value) : control.value;
            if(modelField&&modelOptionIssue(name,value,currentBranch,app.graph.extra?.uap_model_contracts))return false;
            if (control.type === "number" && (control.value === "" || !control.checkValidity() || !Number.isFinite(value))) return false;
            // A generic PrimitiveFloat must retain the precision of its linked parameter.
            const options = widget.options;
            const preciseFloat = source.node.type === "PrimitiveFloat" && options?.round;
            try {
                if (preciseFloat) widget.options = { ...options, round: 0 };
                commitWidget(source.node, widget, value);
            } finally {
                if (preciseFloat) widget.options = options;
            }
            syncModel();
            return true;
        };
        control.oninput = apply;
        control.onchange = () => {
            if (!apply()) {control.setAttribute('aria-invalid','true');control.reportValidity();}
            else control.removeAttribute('aria-invalid');
        };
        sync.push(() => {syncModel();if (document.activeElement !== control && control.value !== String(widget.value)) control.value = widget.value;});
        return control;
    }
    function prompt(parent, node, name, label, negative = false) {
        const source = promptWidgetSource(node, name);
        if (!source) return;
        el("label", label, parent);
        const input = el("textarea", "", parent, { className: negative ? "negative" : "", value: source.widget.value || "" });
        input.setAttribute("aria-label", label);
        promptInputs.push(input);
        promptSources.set(input, source);
        attachAutocomplete(input);
        input.oninput = input.onchange = () => commitWidget(source.node, source.widget, input.value);
        sync.push(() => { if (document.activeElement !== input && input.value !== source.widget.value) input.value = source.widget.value || ""; });
        return input;
    }
    function loraCard(parent, node, title) {
        const box = section(parent, title, node), widget = node.lorasWidget;
        box.classList.add('desk-lora-card');
        box.dataset.deskArea = 'models';
        const error = el("div", "", box, { className: "desk-error" });
        error.setAttribute('role','status');
        const browser = el("button", "浏览器", box.querySelector("h3"), { type: "button", className: "jump", title: `打开 LoRA Manager，写入${title}` });
        browser.onclick = () => {
            try {
                if (!window.loraManagerOpenForNode) throw new Error("LoRA Manager 入口正在加载，请刷新页面。");
                window.loraManagerOpenForNode(node);
            } catch (err) { error.textContent = err.message; }
        };
        if (!widget) { el("small", "控件正在加载，请刷新控制台。", box); return; }
        const add = el("div", "", box, { className: "lora-add" });
        const search = el("input", "", add, { placeholder: "搜索本地 LoRA…" });
        search.setAttribute("list", "uap-local-loras");
        search.setAttribute("aria-label", `${title} 选择 LoRA`);
        const commit = (values, force = false) => { commitWidget(node, widget, values); draw(force); };
        const addButton=el("button", "+", add, { title: `添加到${title}`, type: "button", onclick: async () => {
            error.textContent = "";
            const name = search.value.trim();
            let storedName;
            try {
                const { files, format } = await loraOptions;
                if (!search.isConnected || !active || !currentBranch?.nodeIds?.some(id => String(id) === String(node.id))) return;
                storedName = resolveLocalLoraName(name, files, format);
            } catch (err) { error.textContent = err.message; return; }
            if ((widget.value || []).some(v => v.name === storedName)) { error.textContent = "该 LoRA 已在本栏。"; return; }
            commit([...(widget.value || []), { name: storedName, strength: 1, clipStrength: 1, active: true, expanded: false, locked: false }], true);
            search.value = "";
        } });
        addButton.setAttribute('aria-label',`添加到${title}`);
        search.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();addButton.click();}});
        const rows = el("div", "", box, { className: "lora-rows" });
        let last;
        function draw(force = false) {
            const signature = JSON.stringify(widget.value);
            if (signature === last || (!force && rows.contains(document.activeElement))) return;
            last = signature; rows.replaceChildren();
            (widget.value || []).forEach((entry, index) => {
                const update = patch => commit(widget.value.map((v, i) => i === index ? { ...v, ...patch } : v));
                const row = el("div", "", rows, { className: "lora-row" });
                const check = el("input", "", row, { type: "checkbox", checked: entry.active !== false });
                check.setAttribute("aria-label", `${title} ${entry.name} 启用`);
                check.onchange = () => update({ active: check.checked });
                el("span", entry.name, row, { title: entry.name });
                const strength = el("input", "", row, { type: "number", value: entry.strength, step: "0.05" });
                strength.setAttribute("aria-label", `${title} ${entry.name} 强度`);
                strength.oninput = strength.onchange = () => { if (strength.value !== "" && Number.isFinite(Number(strength.value))) update({ strength: Number(strength.value), ...(!entry.expanded ? { clipStrength: Number(strength.value) } : {}) }); };
                el("button", "×", row, { title: `移除 ${entry.name}`, type: "button", onclick: () => commit(widget.value.filter((_, i) => i !== index), true) });
                if (entry.expanded || entry.clipStrength !== entry.strength) {
                    const clip = el("label", "CLIP", rows, { className: "lora-clip" });
                    const value = el("input", "", clip, { type: "number", value: entry.clipStrength, step: "0.05" });
                    value.oninput = value.onchange = () => { if (value.value !== "" && Number.isFinite(Number(value.value))) update({ clipStrength: Number(value.value) }); };
                }
            });
        }
        draw(); sync.push(draw);
    }
    function fitEmbeddedTools() {
        const top=panel.querySelector('.desk-top'),fold=panel.querySelector('.desk-embedded-tools');
        if(panel.dataset.workbenchMounted&&top&&!fold){
            const details=el('details','',null,{className:'desk-embedded-tools'});
            el('summary','查找控制项与控制台工具',details);
            top.before(details);details.append(top);
        }else if(!panel.dataset.workbenchMounted&&fold)fold.replaceWith(top);
    }
    function render(branch, isActive) {
        promptInspector?.dispose(); promptInspector = null;
        runtimeControls?.dispose(); runtimeControls = null;
        refinementControls?.dispose(); refinementControls = null;
        const restoreFocus = panel.contains(document.activeElement);
        const embeddedToolsOpen=panel.querySelector('.desk-embedded-tools')?.open||false;
        promptInputs.forEach(input => {
            input._promptAutocompleteOwner?.destroy();
            input._promptAutocompleteFallback?.destroy();
        });
        promptInputs = [];
        currentBranch = branch; active = isActive; sync = []; panel.replaceChildren();
        if (!branch) { panel.hidden = true; return; }
        const nodes = branch.nodeIds.map(id => app.graph.getNodeById(id)).filter(Boolean);
        renderedGraph = app.graph; renderedNodes = nodes;
        const find = type => nodes.find(n => n.type === type || n.comfyClass === type);
        const top=el('div','',panel,{className:'desk-top'});
        const head = el("div", "", top, { className: "desk-head" });
        const heading=el('div','',head,{className:'desk-heading'});
        el("strong", "常用控制台", heading);
        el("small", `${branch.label} · ${isActive ? "修改实时同步；运行仅处理当前图像任务" : "浏览中，请先启用此分支"}`, heading);
        const headActions=el('div','',head,{className:'desk-head-actions'});
        const runCurrent=el('button','运行当前图像任务',headActions,{type:'button',className:'desk-run-current',disabled:!isActive});
        let running=false;
        const runStatus=el('small','',top,{className:'desk-run-status'});runStatus.setAttribute('role','status');
        runCurrent.onclick=async()=>{
            if(!isCurrent()||!active||running)return;running=true;runCurrent.disabled=true;
            let requestId=null,queued=false;
            const queueing=event=>{if(requestId===null&&event.detail?.requestId!=null)requestId=event.detail.requestId;};
            const accepted=event=>{if(requestId!==null&&event.detail?.requestId===requestId&&event.detail.batchCount>0)queued=true;};
            api.addEventListener('promptQueueing',queueing);api.addEventListener('promptQueued',accepted);
            try{const result=await app.queuePrompt(0,1);runStatus.textContent=result===false||!queued?'未提交，请查看检查提示。':'任务已加入队列；请查看任务结果。';}
            catch(error){runStatus.textContent=error.message;}
            finally{api.removeEventListener('promptQueueing',queueing);api.removeEventListener('promptQueued',accepted);running=false;runCurrent.disabled=!active||!isCurrent();}
        };
        const libraryShortcut=el('button','资料库',headActions,{type:'button',className:'desk-library-shortcut',title:'打开资料库，使用下方选择的正向或负向目标'});
        el("button", "展开完整工作台", headActions, {type:"button",className:'desk-expand-workbench',onclick:()=>openWorkbench({page:'workspace'})});
        mountThemeToggle(headActions);
        el("button", "刷新", headActions, { className: 'desk-refresh', type: "button", onclick: () => { loraOptions = null; render(currentBranch, active); } });
        el("button", "收起 · 看画布", headActions, { type: "button", onclick: () => { if(panel._workbenchClose){panel._workbenchClose();return;}setShown(false); } });
        const findBar=el('div','',top,{className:'desk-find-bar'});
        const findControl=el('input','',findBar,{type:'search',placeholder:'查找控制项：尺寸、LoRA、提示词、开关…'});
        findControl.setAttribute('aria-label','查找常用控制项');
        findControl.setAttribute('aria-keyshortcuts','Control+k Meta+k');
        findControl.title='在控制台内按 Ctrl / ⌘ + K 查找；Esc 清除搜索';
        const findStatus=el('span','',findBar);findStatus.setAttribute('role','status');
        const clearFind=el('button','清除',findBar,{type:'button',hidden:true});
        const shortcuts=el('div','',findBar,{className:'desk-shortcuts'});shortcuts.setAttribute('role','group');shortcuts.setAttribute('aria-label','定位控制区域');
        const markArea=key=>{
            for(const button of shortcuts.querySelectorAll('button')){
                if(button.dataset.deskArea===key)button.setAttribute('aria-current','location');
                else button.removeAttribute('aria-current');
            }
            for(const section of fields.querySelectorAll('section[data-desk-area]'))section.classList.toggle('desk-area-current',section.dataset.deskArea===key);
        };
        const applyFind=()=>{
            const query=findControl.value.trim().toLowerCase();let matches=0;
            markArea(null);
            fields.dataset.filtering=String(!!query);
            for(const section of fields.querySelectorAll('section')){
                const labels=[...section.querySelectorAll('[aria-label]')].map(item=>item.getAttribute('aria-label')).join(' ');
                section.hidden=!!query&&!(section.textContent+' '+labels).toLowerCase().includes(query);
                if(!section.hidden)matches++;
            }
            for(const column of fields.querySelectorAll('.desk-column'))column.hidden=!!query&&![...column.querySelectorAll('section')].some(section=>!section.hidden);
            clearFind.hidden=!query;findStatus.textContent=query?(matches?'找到 '+matches+' 个区域':'没有匹配的控制项，请更换关键词。'):'';
        };
        let composing=false;
        findControl.addEventListener('compositionstart',()=>{composing=true;});
        findControl.addEventListener('compositionend',()=>{composing=false;applyFind();});
        findControl.oninput=event=>{if(!composing&&!event.isComposing)applyFind();};
        clearFind.onclick=()=>{findControl.value='';applyFind();findControl.focus();};
        findControl.onkeydown=event=>{if(composing||event.isComposing||event.keyCode===229)return;if(event.key==='Escape'&&findControl.value){event.preventDefault();event.stopPropagation();clearFind.click();}};
        const fields = el("fieldset", "", panel, { disabled: !isActive });
        fields.addEventListener('focusin',event=>markArea(event.target.closest('section[data-desk-area]')?.dataset.deskArea));
        const left = el("div", "", fields, { className: "desk-column" });
        const middle = el("div", "", fields, { className: "desk-column" });
        const right = el("div", "", fields, { className: "desk-column" });
        const positive = find("WeiLinPromptUI") || nodes.find(n => /正向|正面/.test(n.title));
        const negative = nodes.find(n => /\[00W-1N\]/.test(n.title)) || nodes.find(n => /负向/.test(n.title));
        const textBox = section(left, "提示词", positive);
        textBox.dataset.deskArea='prompts';
        const positiveTextArea = prompt(textBox, positive, positive?.comfyClass === "WeiLinPromptUI" || positive?.type === "WeiLinPromptUI" ? "positive" : "text", find('Krea2EditGroundedEncode')?"编辑指令":"常用正向提示词");
        const negativeTextArea = prompt(textBox, negative, negative?.widgets?.some(w => w.name === "prompt") ? "prompt" : "text", "常用负向提示词", true);
        const pluginTools = el("div", "", textBox, { className: "plugin-tools desk-prompt-actions" });
        const pluginStatus = el("div", "", textBox, { className: "desk-error" });
        const action = (label, callback, parent = pluginTools) => el("button", label, parent, { type: "button", onclick: async () => {
            pluginStatus.textContent = "";
            try { await callback(); } catch (err) { pluginStatus.textContent = err.message; }
        } });
        action("编辑提示词", async () => {
            const source = promptTarget.value === "negative" ? negative : positive;
            const textarea = promptTarget.value === "negative" ? negativeTextArea : positiveTextArea;
            if (promptTarget.value !== "negative" && positive?.openWeiLinPromptEditor) {
                if(panel._workbenchClose&&panel._workbenchClose()===false)return;
                await positive.openWeiLinPromptEditor();
                shown = false;
                panel.hidden = true;
                hideAutocomplete();
                return;
            }
            if (!textarea) throw new Error("当前方向没有可编辑的提示词目标。");
            textarea.focus();
        });
        const targetLabel=el('label','插入到',pluginTools,{className:'desk-target-label'});
        const promptTarget = el("select", "", targetLabel, { title: "资料库插入目标" });
        promptTarget.setAttribute("aria-label", "资料库插入目标");
        const positiveSource = promptWidgetSource(positive, positive?.type === "WeiLinPromptUI" ? "positive" : "text");
        const negativeSource = promptWidgetSource(negative, negative?.widgets?.some(w => w.name === "prompt") ? "prompt" : "text");
        const bindInsertionTarget = (source, textarea) => {
            if (!source || !textarea) return;
            source.inputElement = textarea;
            source.selectionSnapshot = {
                value: String(source.widget.value ?? ""),
                start: Number.isInteger(textarea.selectionStart) ? textarea.selectionStart : null,
                end: Number.isInteger(textarea.selectionEnd) ? textarea.selectionEnd : null,
            };
        };
        if (positiveSource) el("option", "正向", promptTarget, { value: "positive" });
        if (negativeSource) el("option", "负向", promptTarget, { value: "negative" });
        const libraryAction=action("资料库", async () => {
            if (!window.weilinOpenSharedPresets) throw new Error("资料库入口正在加载，请刷新页面。");
            const source = promptTarget.value === "negative" ? negativeSource : positiveSource;
            if (!source) throw new Error("当前分支没有可编辑的提示词目标。");
            bindInsertionTarget(source, promptTarget.value === "negative" ? negativeTextArea : positiveTextArea);
            await openWorkbench({page:'library',target:{node:source.node,widget:source.widget,direction:promptTarget.value,label:`${branch.label} / ${promptTarget.value === 'negative' ? '负向' : '正向'} #${source.node.id}`},inputElement:source.inputElement,reset:true});
        });
        libraryAction.classList.add('desk-library-action');
        pluginTools.hidden=!positiveSource&&!negativeSource;
        libraryShortcut.title=positiveSource||negativeSource?'打开资料库，使用下方选择的正向或负向目标':'浏览资料库';
        libraryShortcut.onclick=()=>isCurrent()&&app.graph.extra?.uap_workbench?.activeBranch===branch.id&&(positiveSource||negativeSource)?libraryAction.onclick():openWorkbench({page:'library'});
        el("small", positiveSource?"选择器 · 写入当前正向提示词":"当前没有可编辑的正向提示词目标，可继续浏览资料。", textBox, {className:'desk-selector-hint'});
        const animaTools = el("div", "", textBox, { className: "plugin-tools" });
        for (const {kind, label} of positiveSource&&positiveTextArea?SELECTOR_TOOLS:[]) {
            const selectorButton = action(label, async () => {
                if (!isCurrent() || app.graph.extra?.uap_workbench?.activeBranch !== branch.id) throw new Error("当前分支已变化，请重新打开常用控制台。");
                const source = positiveSource;
                if (!source || !positiveTextArea) throw new Error("当前分支没有可编辑的正向提示词目标。");
                bindInsertionTarget(source, positiveTextArea);
                const target = {node:source.node, widget:source.widget, direction:'positive', label:`${branch.label} / 正向 #${source.node.id}`};
                await openWorkbench({page:'library', target, inputElement:source.inputElement, reset:true,
                    selector:{node:source.node, section:kind, label, native:() => openPromptSelector(app, kind, target)}, openSelector:true});
            }, animaTools);
            selectorButton.classList.add('desk-selector-action');
            selectorButton.disabled = !positiveSource || !positiveTextArea;
        }
        action('待用列表 · 组合预览', async () => {
            if (!isCurrent() || app.graph.extra?.uap_workbench?.activeBranch !== branch.id) throw new Error('当前分支已变化，请重新打开常用控制台。');
            if (positiveSource && positiveTextArea) bindInsertionTarget(positiveSource, positiveTextArea);
            const target = positiveSource ? {node:positiveSource.node, widget:positiveSource.widget, direction:'positive', label:`${branch.label} / 正向 #${positiveSource.node.id}`} : null;
            const workbench = await openWorkbench({page:'library', target, inputElement:positiveSource?.inputElement, reset:true, openPending:true});
            await workbench.showPending();
        }, animaTools);
        const size = find("EmptyLatentImage") || find("EmptySD3LatentImage");
        const sampler = find("KSampler"), seed = find("easy seed");
        const params = section(fields, "尺寸 · 种子 · 采样", size || sampler);
        params.dataset.deskArea='parameters';
        params.classList.add("desk-parameters");
        const grid = el("div", "", params, { className: "fields" });
        for (const [node, name, label, wide] of [[size,"width","宽度"],[size,"height","高度"],[size,"batch_size","批量"],[seed || sampler,"seed","种子",true],[seed || sampler,"control_after_generate","种子模式"],[sampler,"steps","步数"],[sampler,"cfg","CFG"],[sampler,"sampler_name","采样器",true],[sampler,"scheduler","调度器"],[sampler,"denoise","降噪"]]) bindField(grid,node,name,label,wide);
        if (sampler && !widgetSource(sampler, "denoise")) {
            for (const node of nodes.filter(n => n.type === "PrimitiveFloat" && /denoise/i.test(n.title))) {
                const label = /文生图/.test(node.title) ? "文生降噪" : /遮罩/.test(node.title) ? "遮罩降噪" : "图生降噪";
                bindField(grid, node, "value", label);
            }
        }
        if (size) {
            const presets = el("div", "", params.querySelector("h3"), { className: "presets" });
            [["方图",1024,1024],["竖图",832,1216],["横图",1216,832]].forEach(([label,w,h]) => el("button",label,presets,{type:"button",title:`${w} × ${h}`,onclick:()=>{for(const [name,value] of [["width",w],["height",h]]){const source=widgetSource(size,name);if(source)commitWidget(source.node,source.widget,value);}sync.forEach(fn=>fn());}}));
        }
        if(!grid.children.length)params.remove();
        if(!positiveTextArea&&!negativeTextArea)textBox.remove();
        if(positiveTextArea||negativeTextArea){promptInspector = mountPromptInspector(left, app, branch, isCurrent);sync.push(promptInspector.sync);}
        runtimeControls = mountRuntimeControls(left, app, branch, nodes, isCurrent);
        sync.push(runtimeControls.sync);
        const clipNode=find('CLIPLoader');
        const modelFields=[
            [find('UNETLoader'),'unet_name','基础模型'],
            [find('CheckpointLoaderSimple')||find('CheckpointLoader'),'ckpt_name','整合模型'],
            [clipNode,'clip_name','文本编码器'],
            [find('VAELoader'),'vae_name','VAE'],
            [find('UpscaleModelLoader'),'model_name','放大模型'],
        ].filter(([node])=>node);
        if(modelFields.length){
            const box=section(middle,'当前分支模型',modelFields[0][0]);box.dataset.deskArea='models';
            const fields=el('div','',box,{className:'fields'});
            for(const [node,name,label]of modelFields)bindField(fields,node,name,label,true);
            el('small','模型仅应用于当前分支；基础模型、文本编码器与 VAE 需配套。',box);
        }
        {
            const hint=el('small','',middle.querySelector('[data-desk-area=models]')||middle,{className:'desk-encoder-hint'});hint.dataset.encoderHint='';
            const scopeHint={
                a1:'01 Anima 原版与 02 Anima 2.9B',a29:'01 Anima 原版与 02 Anima 2.9B',ext07:'01 Anima 原版与 07 左右扩图',
                k2:'03 Krea2与 04 指令编辑',ext04:'03 Krea2与 04 指令编辑',ext05:'02 Anima 2.9B与 05 裁剪精修',
            }[branch.id]||branch.label;
            let renderedHint='';
            // The 750ms sync loop calls this repeatedly; rebuild only when the text changes,
            // otherwise every poll discards and recreates the same nodes.
            const setHintText=text=>{
                if(text===renderedHint)return;
                renderedHint=text;hint.textContent=text;
            };
            const renderEncoderHint=()=>{
                if(!hint.isConnected){renderedHint='';return;}
                if(!clipNode){setHintText('本分支不含文本编码器：该流程只用图像或放大模型，不需要文本编码器设置。');return;}
                const source=widgetSource(clipNode,'clip_name');
                if(!source||String(source.widget.value??'')===''){
                    setHintText('文本编码器由连线控制或当前不可读，类型请从原节点查看。');return;
                }
                const file=String(source.widget.value);
                const typeWidget=clipNode.widgets?.find(widget=>widget.name==='type');
                const type=typeWidget?String(typeWidget.value??''):'';
                const family=type==='stable_diffusion'?'Anima 原生文本编码器':type==='krea2'?'Krea2 专用文本编码器':/anima/i.test(file)?'Anima 系列编码器文件':/qwen3|krea/i.test(file)?'Qwen3-VL 系列编码器文件':'';
                const bypassed=(clipNode.mode!=null&&clipNode.mode!==0)||(source.node.mode!=null&&source.node.mode!==0);
                const main=`文本编码器 #${clipNode.id}：${file} · 类型 ${type||'未提供'}${family?`（${family}）`:''}；适用：${scopeHint}。${bypassed?'当前分支未启用，此编码器处于旁路状态，切换后生效。':''}`;
                const note=`编码器文件与类型都取自当前节点、只读显示，未改动任何值。type 字段按原样呈现：${type==='stable_diffusion'?'Anima 使用 stable_diffusion 是正常设置，不是错误配置；':'不同模型体系的 type 不能互换；'}更换模型体系时两者都要在节点里一起改。`;
                const signature=main+'\u0000'+note;
                if(signature===renderedHint)return;
                renderedHint=signature;
                hint.replaceChildren();
                el('span',main,hint);
                el('button','原节点 ↗',hint,{className:'jump',type:'button',title:'定位文本编码器节点',onclick:()=>openNode(clipNode)});
                el('span',note,hint);
            };
            renderEncoderHint();
            sync.push(renderEncoderHint);
        }
        for(const [type,title,items]of [
            ['ImagePadForOutpaint','扩图范围',[['left','向左扩展'],['right','向右扩展'],['top','向上扩展'],['bottom','向下扩展'],['feathering','边缘羽化']]],
            ['ImageScaleBy','输出缩放',[['scale_by','缩放倍数'],['upscale_method','缩放算法']]],
            ['BiRefNetRMBG','抠图设置',[['model','抠图模型'],['mask_blur','边缘柔化'],['mask_offset','边缘偏移'],['background','背景']]],
        ]){
            const node=find(type);if(!node)continue;
            const box=section(left,title,node);box.dataset.deskArea='parameters';const fields=el('div','',box,{className:'fields'});
            for(const [name,label]of items)bindField(fields,node,name,label);
            if(type==='ImageScaleBy'){
                const summary=el('small','',box);
                sync.push(()=>{const factor=widgetSource(node,'scale_by')?.widget.value;const file=String(find('UpscaleModelLoader')?.widgets?.find(w=>w.name==='model_name')?.value||'');summary.textContent=/4x|x4/i.test(file)?`模型4× × 后续缩放${factor}× = 最终${4*Number(factor)}×`:'此倍率乘在放大模型输出之后；更换模型后请核对原生倍率。';});
            }
        }
        const loras = nodes.filter(n => /Lora (Stacker|Loader) \(LoraManager\)/.test(n.type));
        const loraOrder=node=>/角色/.test(node.title)?0:/基础/.test(node.title)?1:/风格/.test(node.title)?2:3;
        loras.sort((a,b) => loraOrder(a)-loraOrder(b)||a.id-b.id);
        if (loras.length) {
            el("h3", "LoRA 选择 · 启用 · 强度", middle, {className:'desk-lora-heading'});
            for (const node of loras) loraCard(middle,node, /角色/.test(node.title)?"角色 / 姿势":/基础/.test(node.title)?"基础 / 修复":/风格/.test(node.title)?"风格 / 补充":"汇合 / 追加");
        } else {
            const model = find("LoraLoaderModelOnly") || find("AnimaMultiLoraLoader");
            if (model) { const box=section(middle,"LoRA",model);box.dataset.deskArea='models';const grid=el("div","",box,{className:"fields"});for(const [name,label] of [["lora_name","LoRA"],["strength_model","强度"]])bindField(grid,model,name,label,true); }
            el("small", "扩展流程的其余参数可从原节点入口调整。", middle);
        }
        const modes = section(left,"出图模式");
        modes.dataset.deskArea='switches';
        for (const node of nodes.filter(n => n.type === "PrimitiveBoolean" && /\[00W-/.test(n.title))) {
            const source=widgetSource(node,"value");if(!source)continue;
            const label=el("label","",modes,{className:"switch"});const check=el("input","",label,{type:"checkbox",checked:!!source.widget.value});
            const title=shortTitle(node.title);check.setAttribute("aria-label",title);el("span",title,label,{title});
            check.onchange=()=>commitWidget(node,source.widget,check.checked);sync.push(()=>{check.checked=!!source.widget.value;});
        }
        if(!modes.querySelector('input'))modes.remove();
        const controllers=nodes.filter(n=>/Fast Groups (Muter|Bypasser)/.test(n.type));
        for(const controller of controllers){
            controller.refreshWidgets?.();
            const box=section(right,/Bypasser/.test(controller.type)?"细化组件开关":"工具开关",controller);
            box.dataset.deskArea='switches';
            const grid=el("div","",box,{className:"switches"});
            for(const widget of controller.widgets || []){
                if(typeof widget.doModeChange!=="function")continue;
                const group=widget.group;if(!group)continue;
                const title=group.title.replace(/^(?:SW|FX)-\S+\s*/,"").replace(/ · .+$/,"");
                const row=el("label","",grid,{className:"switch",title});
                const check=el("input","",row,{type:"checkbox",checked:!!widget.toggled});check.setAttribute("aria-label",`开关 ${title}`);
                el("span",title,row);el("button","↗",row,{className:"jump",type:"button",title:`定位 ${title}`,onclick:e=>{e.preventDefault();locateOnCanvas(()=>jump(group.title));}});
                const members=()=>nodes.filter(node=>node.properties?.uap_layout_group===group.title);
                const blocked=()=>members().some(node=>node.properties?.uap_legacy_lllite)?legacyControlIssue(nodes):members().some(node=>node.properties?.uap_refinement)?refinementBatchIssue(nodes):'';
                check.onchange=()=>{
                    const issue=check.checked&&blocked();
                    if(issue){check.checked=!!widget.toggled;pluginStatus.textContent=issue;return;}
                    app.graph.beforeChange();
                    try{
                        const exclusive=members().find(node=>node.properties?.uap_exclusive_refinement)?.properties.uap_exclusive_refinement;
                        if(check.checked&&exclusive)for(const other of controller.widgets||[]){
                            if(other===widget||!other.group||typeof other.doModeChange!=='function')continue;
                            if(nodes.some(node=>node.properties?.uap_layout_group===other.group.title&&node.properties?.uap_exclusive_refinement===exclusive))other.doModeChange(false);
                        }
                        widget.doModeChange(check.checked);
                    }finally{app.graph.afterChange();app.graph.setDirtyCanvas(true,true);}
                    sync.forEach(fn=>fn());
                };
                sync.push(()=>{check.checked=!!widget.toggled;const issue=blocked();check.disabled=!!issue&&!check.checked;check.title=issue||title;row.title=issue||title;});
            }
        }
        refinementControls=mountRefinementControls(right,{app,branch,nodes,isCurrent});sync.push(refinementControls.sync);
        for(const [key,label] of [['prompts','提示词'],['models','模型 / LoRA'],['switches','开关'],['refinement','细化参数'],['parameters','生成参数']]){
            const section=fields.querySelector(`[data-desk-area="${key}"]`);if(!section)continue;
            section.id=`uap-desk-area-${key}`;section.tabIndex=-1;
            const shortcut=el('button',label,shortcuts,{type:'button',title:`定位到${label}；不会修改参数`,onclick:()=>{
                findControl.value='';applyFind();markArea(key);section.focus({preventScroll:true});
                const scrollHost=panel.closest('.uw-main'),viewTabs=scrollHost?.querySelector('.uw-workspace-view-tabs');
                const tabHeight=viewTabs?.getBoundingClientRect().height||0;
                const offset=getComputedStyle(top).position==='sticky'?top.getBoundingClientRect().height+12:
                    tabHeight?tabHeight+parseFloat(getComputedStyle(scrollHost).paddingTop)+12:16;
                section.style.scrollMarginTop=`${offset}px`;section.scrollIntoView({block:'start'});
            }});
            shortcut.dataset.deskArea=key;shortcut.setAttribute('aria-controls',section.id);
        }
        const list=el("datalist","",panel,{id:"uap-local-loras"});
        if(!loraOptions)loraOptions=Promise.all([fetch("/object_info/LoraLoader"),fetch("/api/lm/settings")]).then(async responses=>{
            if(responses.some(r=>!r.ok))throw new Error("本地 LoRA 列表或设置读取失败，请刷新后重试。");
            const [info,settings]=await Promise.all(responses.map(r=>r.json()));
            return {files:info.LoraLoader.input.required.lora_name[0],format:settings.settings?.lora_syntax_format || "legacy"};
        });
        loraOptions.then(({files})=>{if(list.isConnected)files.forEach(name=>el("option","",list,{value:name}));}).catch(err=>{if(pluginStatus.isConnected)pluginStatus.textContent=err.message;});
        fitEmbeddedTools();
        const embeddedTools=panel.querySelector('.desk-embedded-tools');
        if(embeddedTools)embeddedTools.open=embeddedToolsOpen;
        panel.hidden=!shown;position();
        if (restoreFocus && shown) (embeddedTools&&!embeddedTools.open?embeddedTools.querySelector('summary'):panel.querySelector('.desk-refresh'))?.focus({preventScroll:true});
    }
    setInterval(()=>{if(!document.hidden&&panel.isConnected&&!panel.closest('[hidden],[inert]')){if(!isCurrent()){panel.hidden=true;shown=false;hideAutocomplete();return;}const fields=panel.querySelector("fieldset");if(fields){const disabled=app.graph.extra?.uap_workbench?.activeBranch!==currentBranch.id;if(fields.disabled!==disabled)fields.disabled=disabled;}position();sync.forEach(fn=>fn());}},750);
    window.addEventListener("resize",position);
    const controls = {
        render,
        openWorkbench,
        getPromptInput(node, widget){
            if(!isCurrent()||app.graph.extra?.uap_workbench?.activeBranch!==currentBranch?.id)return null;
            return promptInputs.find(input=>input.isConnected&&promptSources.get(input)?.node===node&&promptSources.get(input)?.widget===widget)||null;
        },
        readPlan(){
            if(!isCurrent()||app.graph.extra?.uap_workbench?.activeBranch!==currentBranch?.id)throw new Error('当前分支已失效，请重新选择。');
            const nodes=currentBranch.nodeIds.map(id=>app.graph.getNodeById(id)).filter(Boolean);
            const positive=nodes.find(n=>n.type==='WeiLinPromptUI'||n.comfyClass==='WeiLinPromptUI')||nodes.find(n=>/正向|正面/.test(n.title));
            const negative=nodes.find(n=>/\[00W-1N\]/.test(n.title))||nodes.find(n=>/负向/.test(n.title));
            const read=(node,name)=>{
                if(!node)return '';
                const source=promptWidgetSource(node,name);
                if(!source||typeof source.widget.value!=='string'||(node.mode!=null&&node.mode!==0)||(source.node.mode!=null&&source.node.mode!==0))throw new Error('提示词来源已变化或无法读取，请检查当前分支的节点与连线。');
                return source.widget.value;
            };
            return {positive:read(positive,positive?.type==='WeiLinPromptUI'||positive?.comfyClass==='WeiLinPromptUI'?'positive':'text'),negative:read(negative,negative?.widgets?.some(w=>w.name==='prompt')?'prompt':'text')};
        },
        mount(host, branch, onClose) {
            const marker=document.createComment('daily-controls-return'),previousShown=shown,previousStyle=panel.style.cssText;
            const reuse=isCurrent()&&currentBranch===branch&&active;
            panel.parentNode.insertBefore(marker,panel);host.append(panel);panel.dataset.workbenchMounted='true';panel._workbenchClose=onClose;shown=true;
            if(reuse){panel.hidden=false;position();}else render(branch,true);
            fitEmbeddedTools();
            return () => {
                if(marker.parentNode)marker.replaceWith(panel);
                delete panel.dataset.workbenchMounted;delete panel._workbenchClose;
                fitEmbeddedTools();
                panel.style.cssText=previousStyle;shown=previousShown;panel.hidden=!shown;
                const config=app.graph?.extra?.uap_workbench;
                const viewed=config?.branches?.find(item=>item.id===config.viewBranch);
                if(viewed&&isCurrent()&&(currentBranch!==viewed||active!==(viewed.id===config.activeBranch)))
                    render(viewed,viewed.id===config.activeBranch);
                else position();
            };
        },
        show: setShown,
        toggle(){setShown(!shown);},
    };
    window.unifiedDailyControls=controls;
    return controls;
}
