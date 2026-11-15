// Offline unit & isolation test for standalone MOSS workflow + Krea2/MOSS mutual non-interference.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const runtime = path.resolve(__dirname, '..');
const pack = path.join(runtime, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench');
const web = path.join(pack, 'web');
const dailyPath = path.join(pack, 'modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js');
const lmTargetsPath = path.join(pack, 'modules/comfyui-lora-manager/web/comfyui/workflow_targets.js');
const lmAutocompletePath = path.join(pack, 'modules/comfyui-lora-manager/web/comfyui/autocomplete.js');

const stripModule = text => text.replace(/^import\s[\s\S]*?;\r?\n/gm, '').replace(/^export\s+/gm, '');

// 1. Standalone graph structure, physical model-only CLIP isolation, and zero UAP v2 mutation
const templateBytes = fs.readFileSync(path.join(__dirname, 'templates/MOSS_精简生产_v1.json'));
const workflowBytes = fs.readFileSync(path.join(runtime, 'ComfyUI/user/default/workflows/MOSS_精简生产_v1.json'));
assert.deepEqual(templateBytes, workflowBytes, 'MOSS template and runtime workflow must match byte-for-byte');

const uapMainBytes = fs.readFileSync(path.join(runtime, 'ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json'));
const uapTemplateBytes = fs.readFileSync(path.join(__dirname, 'templates/UAP统一生产工作台_v2.json'));
assert.deepEqual(uapMainBytes, uapTemplateBytes, 'Main UAP v2 and its template must remain identical');
const uapMain = JSON.parse(uapMainBytes.toString('utf8'));
assert.equal(uapMain.nodes.some(n => n.type === 'EmptyFlux2LatentImage' || /moss/i.test(n.title || '')), false,
    'Main UAP v2 must stay free of MOSS nodes');

const moss = JSON.parse(workflowBytes.toString('utf8'));
assert.equal(moss.id, 'moss-lean-production-v1');
assert.notEqual(moss.id, uapMain.id, 'MOSS workflow ID must differ from Krea2 UAP workflow ID to isolate history');
assert.equal(moss.nodes.length, 13);
assert.equal(moss.links.length, 11);
assert.equal(moss.groups.length, 4);

const byId = id => moss.nodes.find(n => n.id === id);
for (const link of moss.links) {
    const [linkId, srcId, srcSlot, dstId, dstSlot] = link;
    assert(byId(srcId).outputs[srcSlot].links.includes(linkId), `Source #${srcId} missing link ${linkId}`);
    assert.equal(byId(dstId).inputs[dstSlot].link, linkId, `Target #${dstId} missing link ${linkId}`);
}

// Physical CLIP isolation: #4 Lora Loader has no clip input/output links; #2 CLIPLoader feeds #5 and #6 directly
const loraNodeSpec = byId(4);
assert.equal(loraNodeSpec.inputs.find(i => i.name === 'clip').link, null, '#4 Lora Loader clip input must be disconnected');
assert.deepEqual(loraNodeSpec.outputs.find(o => o.name === 'CLIP').links, [], '#4 Lora Loader CLIP output must be unused');
assert.deepEqual(byId(2).outputs[0].links, [4, 5], '#2 CLIPLoader must feed #5 and #6 directly');
assert.equal(byId(5).inputs.find(i => i.name === 'trigger_words1').link, 11, '#4 trigger_words must still feed #5');
assert.equal(byId(8).widgets_values[2], 40, 'KSampler steps widget_values must match 40');
assert.equal(byId(8).widgets_values_named.steps, 40);
assert.equal(byId(10).widgets_values[0], 'Production_MOSS/moss', 'MOSS SaveImage must use isolated output directory');
assert.equal(byId(10).properties.uap_layout_group, '03 成品保存 · MOSS');

console.log('PASS: MOSS standalone graph, physical CLIP disconnection, link closure, and output directory isolation.');

// 2. Navigation choices, native tab round-trip without mutating Krea2 draft, and taskPlan target resolution
const navCtx = vm.createContext({
    console,
    window: {unifiedUapNavigation: {activateBranch(id) {navCtx.activated = id;}}},
});
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'repair_workflow.js'), 'utf8')), navCtx);
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'task_activity.js'), 'utf8')), navCtx);

const mainChoices = navCtx.workflowChoices(uapMain.extra.uap_workbench);
assert.deepEqual(Array.from(mainChoices, c => c.value), [
    'k2', 'ext04', '@workflow:moss', '@workflow:caption', 'ext06', 'ext08', 'ext09', '@workflow:stocking',
]);
const mossChoices = navCtx.workflowChoices(moss.extra.uap_workbench);
assert.deepEqual(Array.from(mossChoices, c => c.value), [
    '@workflow:k2', 'moss', '@workflow:ext04', '@workflow:caption', '@workflow:ext06', '@workflow:ext08', '@workflow:ext09', '@workflow:stocking',
]);

// Runtime graph mock for MOSS
function buildRuntimeNodes(spec) {
    return spec.nodes.map(n => {
        const widgets = [];
        if (n.widgets_values_named) {
            for (const [name, value] of Object.entries(n.widgets_values_named)) {
                widgets.push({name, value: structuredClone(value), options: {}});
            }
        }
        const runtimeNode = {
            ...structuredClone(n),
            comfyClass: n.type,
            widgets,
        };
        if (n.type === 'Lora Loader (LoraManager)') {
            runtimeNode.lorasWidget = widgets.find(w => w.name === 'loras');
        }
        return runtimeNode;
    });
}

const mossNodes = buildRuntimeNodes(moss);
const mossLinks = Object.fromEntries(moss.links.map(l => [l[0], {
    id: l[0], origin_id: l[1], origin_slot: l[2], target_id: l[3], target_slot: l[4], type: l[5],
}]));
const mossGraph = {
    id: moss.id,
    _nodes: mossNodes,
    links: mossLinks,
    extra: structuredClone(moss.extra),
    getNodeById(id) {return this._nodes.find(item => String(item.id) === String(id));},
    beforeChange() {},
    afterChange() {},
    setDirtyCanvas() {},
};

const mossPlan = navCtx.taskPlan({graph: mossGraph}, 'generate');
assert.equal(mossPlan.label, '开始生图');
assert.equal(mossPlan.reason, '');
assert.deepEqual(Array.from(mossPlan.queueNodeIds), ['10']);
console.log('PASS: Krea2 <-> MOSS workflow choices and MOSS taskPlan output target (#10).');

// 3. Prompt resolution, non-interference with Lora Loader text widget, static/runtime prompt inspectors
const promptCtx = vm.createContext({
    console,
    app: {graph: mossGraph},
    api: {},
    window: {addEventListener() {}},
    document: {head: {append() {}}, body: {append() {}}, createElement: () => ({setAttribute() {}, addEventListener() {}, append() {}, style: {}})},
    setInterval: () => 1,
});
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'prompt_target.js'), 'utf8')), promptCtx);
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'resource_actions.js'), 'utf8')), promptCtx);
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'static_prompt_inspector.js'), 'utf8')), promptCtx);
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'prompt_inspector.js'), 'utf8')), promptCtx);

const dailyCtx = vm.createContext({
    console,
    app: {graph: mossGraph, canvas: {}},
    api: {},
    window: {addEventListener() {}},
    document: {head: {append() {}}, body: {append() {}}, createElement: () => ({setAttribute() {}, addEventListener() {}, append() {}, style: {}})},
    setInterval: () => 1,
    sharedCommitWidget: (app, node, widget, value) => {widget.value = value; return true;},
    createWidgetInserter: () => () => {},
    mountPromptInspector: () => ({sync() {}, dispose() {}}),
    mountRuntimeControls: () => ({sync() {}, dispose() {}}),
    mountRefinementControls: () => ({sync() {}, dispose() {}}),
    attachPromptAutocomplete: () => {},
    mountThemeToggle: () => {},
    mountStockingControls: () => () => {},
    SELECTOR_TOOLS: [],
    openPromptSelector: () => {},
    modelOptionIssue: () => '',
    refinementBatchIssue: () => '',
});
vm.runInContext(stripModule(fs.readFileSync(dailyPath, 'utf8')), dailyCtx);

const resolved = dailyCtx.resolveBranchPromptNodes(mossNodes);
assert.equal(resolved.positive?.id, 5, 'Positive prompt must resolve to #5 Prompt (LoraManager)');
assert.equal(resolved.negative?.id, 6, 'Negative prompt must resolve to #6 CLIPTextEncode');

const targets = promptCtx.listPromptTargets({graph: mossGraph});
assert.deepEqual(Array.from(targets, t => [t.node.id, t.widget.name, t.direction, t.usage]), [
    [5, 'text', 'positive', 'generation'],
    [6, 'text', 'negative', 'generation'],
], 'Lora Loader #4 / text and Notes must never appear as prompt targets');

const dims = dailyCtx.dimensionSources(mossGraph.getNodeById(7));
assert.ok(dims && dims.length === 2, 'EmptyFlux2LatentImage #7 must resolve width/height sources');
assert.deepEqual([dims[0].widget.value, dims[1].widget.value], [1024, 1280]);

const staticRows = promptCtx.inspectStaticPromptInputs(mossGraph, moss.extra.uap_workbench.branches[0]);
assert.equal(staticRows.length, 2);
assert.equal(staticRows[0].node.id, 5);
assert.equal(staticRows[0].status, 'source');
assert.equal(staticRows[1].node.id, 6);
assert.equal(staticRows[1].status, 'static');

const apiPrompt = {
    1: {class_type: 'Unet Loader (LoraManager)', inputs: {unet_name: byId(1).widgets_values_named.unet_name}},
    2: {class_type: 'CLIPLoader', inputs: {clip_name: byId(2).widgets_values_named.clip_name, type: 'moss_image'}},
    4: {class_type: 'Lora Loader (LoraManager)', inputs: {model: ['1', 0], loras: {__value__: []}}},
    5: {class_type: 'Prompt (LoraManager)', inputs: {clip: ['2', 0], trigger_words1: ['4', 2], text: 'moss positive scene'}},
    6: {class_type: 'CLIPTextEncode', inputs: {clip: ['2', 0], text: 'moss negative'}},
    8: {class_type: 'KSampler', inputs: {model: ['4', 0], positive: ['5', 0], negative: ['6', 0], cfg: 3, sampler_name: 'euler'}},
};
const inspected = promptCtx.inspectPrompt(apiPrompt, '8');
assert.equal(inspected.positive.text, 'moss positive scene');
assert.deepEqual(JSON.parse(JSON.stringify(inspected.positive.source)), {id: '5', widget: 'text'});
assert.equal(inspected.negative.text, 'moss negative');
assert.equal(inspected.models.length, 1);
assert.match(promptCtx.modelNote(inspected.models[0].file), /MOSS.*moss_image/);
console.log('PASS: Prompt (LoraManager), EmptyFlux2LatentImage, prompt target exclusion for #4, and static/runtime inspectors.');

// 4. Krea2 <-> MOSS bidirectional model, encoder, VAE, LoRA, browser URL, and clipStrength=0 isolation
class El {
    constructor(tag) {
        this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {};
        this.textContent = ''; this.disabled = false; this.value = ''; this.isConnected = true;
    }
    append(node) {this.children.push(node); node.parent = this; return node;}
    replaceChildren() {for (const c of this.children) c.parent = null; this.children.length = 0;}
    setAttribute(k, v) {this.attributes[k] = v;}
    querySelector(sel) {return sel === 'h3' ? this.children.find(c => c.tagName === 'h3') : null;}
    addEventListener(type, fn) {this['on_' + type] = fn;}
    contains() {return false;}
}

const runtimeSource = stripModule(fs.readFileSync(path.join(web, 'runtime_controls.js'), 'utf8'));
const guardCommits = [];
const guardCtx = vm.createContext({
    console,
    document: {createElement: tag => new El(tag)},
    commitWidget: (...args) => guardCommits.push(args),
    taskPlan: () => ({reason: '', queueNodeIds: ['10']}),
    fetch: async url => ({
        ok: true,
        json: async () => ({
            'Unet Loader (LoraManager)': {
                input: {
                    required: {
                        unet_name: [[
                            'moss\\图像生成\\Moss__MOSS Image__Base__BF16__cv3409868__f3301907.safetensors',
                            'moss\\图像生成\\Moss__MOSS Image__SFT__BF16__cv3409867__f3301903.safetensors',
                            'krea2\\图像生成\\Krea2__Krea2-Anime__v3.0__FP8__cv3435333__f3334536.safetensors',
                        ]],
                    },
                },
            },
        }),
    }),
});
vm.runInContext(runtimeSource, guardCtx);

const k2Branch = uapMain.extra.uap_workbench.branches.find(b => b.id === 'k2');
const k2Contracts = uapMain.extra.uap_model_contracts;
const mossBranch = moss.extra.uap_workbench.branches[0];
const mossContracts = moss.extra.uap_model_contracts;

// Krea2 rejects MOSS resources, accepts Krea2 resources
assert.match(guardCtx.modelOptionIssue('unet_name', 'moss/图像生成/Moss__MOSS Image__Base__BF16__cv3409868__f3301907.safetensors', k2Branch, k2Contracts), /moss/);
assert.match(guardCtx.modelOptionIssue('clip_name', 'Moss__Qwen3.5 9B Text Encoder__v1__BF16__sha__7E6E9F08D598.safetensors', k2Branch, k2Contracts), /不匹配/);
assert.match(guardCtx.modelOptionIssue('vae_name', 'Moss__Flux2 VAE__v1__FP32__cv3409867__f3301980.safetensors', k2Branch, k2Contracts), /不匹配/);
assert.match(guardCtx.modelOptionIssue('lora_name', 'moss/画风与画师/Moss__748cm (MOSS) _ Artist styles__v1.0__BF16__cv3424711__f3319394.safetensors', k2Branch, k2Contracts), /moss/);
assert.match(guardCtx.modelOptionIssue('lora_name', 'Moss__748cm Style _ MOSS, KREA 2 & Anima__MOSS__BF16__cv3435405__f3332255', k2Branch, k2Contracts), /moss/);
assert.equal(guardCtx.modelOptionIssue('lora_name', 'krea2/画风与画师/NIJISIS_krea2_V2.safetensors', k2Branch, k2Contracts), '');
assert.equal(guardCtx.modelOptionIssue('lora_name', 'Krea2__748cm Style__v1', k2Branch, k2Contracts), '');

// MOSS rejects Krea2 resources, accepts MOSS resources (including multi-family-named Moss__ files)
assert.match(guardCtx.modelOptionIssue('unet_name', 'krea2/图像生成/Krea2__Krea2-Anime__v3.0__FP8__cv3435333__f3334536.safetensors', mossBranch, mossContracts), /krea2/);
assert.match(guardCtx.modelOptionIssue('clip_name', 'qwen3-vl-4b-heretic.safetensors', mossBranch, mossContracts), /不匹配/);
assert.match(guardCtx.modelOptionIssue('vae_name', 'krea2RealVae_v10.safetensors', mossBranch, mossContracts), /不匹配/);
assert.match(guardCtx.modelOptionIssue('lora_name', 'krea2/画风与画师/NIJISIS_krea2_V2.safetensors', mossBranch, mossContracts), /krea2/);
assert.match(guardCtx.modelOptionIssue('lora_name', 'Krea2__748cm Style__v1', mossBranch, mossContracts), /krea2/);
assert.equal(guardCtx.modelOptionIssue('unet_name', 'moss/图像生成/Moss__MOSS Image__SFT__BF16__cv3409867__f3301903.safetensors', mossBranch, mossContracts), '');
assert.equal(guardCtx.modelOptionIssue('clip_name', 'Moss__Qwen3.5 9B Text Encoder__v1__W4A8-GPTQ__cv3409867__f3301906.safetensors', mossBranch, mossContracts), '');
assert.equal(guardCtx.modelOptionIssue('vae_name', 'Moss__Flux2 VAE__v1__FP32__cv3409867__f3301980.safetensors', mossBranch, mossContracts), '');
assert.equal(guardCtx.modelOptionIssue('lora_name', 'Moss__748cm Style _ MOSS, KREA 2 & Anima__MOSS__BF16__cv3435405__f3332255', mossBranch, mossContracts), '');

// Queue-time guard blocks foreign LoRAs and validates Unet Loader (LoraManager)
assert.equal(guardCtx.workflowGuardIssue(mossNodes, mossBranch, mossContracts), '');
mossGraph.getNodeById(4).lorasWidget.value = [{name: 'Krea2__ ForeignStyle', strength: 0.8, clipStrength: 0, active: true}];
assert.match(guardCtx.workflowGuardIssue(mossNodes, mossBranch, mossContracts), /Krea2__ ForeignStyle.*krea2/);
mossGraph.getNodeById(4).lorasWidget.value = [{name: 'Krea2__ ForeignStyle', strength: 0.8, clipStrength: 0, active: false}];
assert.equal(guardCtx.workflowGuardIssue(mossNodes, mossBranch, mossContracts), '', 'Disabled foreign LoRA entry does not block run');
mossGraph.getNodeById(4).lorasWidget.value = [];

// mountRuntimeControls on MOSS mounts both VRAM free button and Unet Loader (LoraManager) model switcher
const host = new El('div');
guardCtx.mountRuntimeControls(host, {graph: mossGraph}, mossBranch, mossNodes, () => true);
const walkEl = (root, pred) => {
    if (pred(root)) return root;
    for (const c of root.children || []) {const hit = walkEl(c, pred); if (hit) return hit;}
    return null;
};
assert.ok(walkEl(host, n => n.tagName === 'button' && n.textContent === '立即释放模型与缓存'), 'MOSS runtime controls must expose /free button');
const modelSection = walkEl(host, n => n.tagName === 'section' && n.children.some(c => c.textContent === '底模快切 · 当前分支'));
assert.ok(modelSection, 'Unet Loader (LoraManager) must mount base-model quick switch');

// LoRA browser URL folder isolation
let openedUrl = '';
const browserCtx = vm.createContext({
    app: {graph: mossGraph},
    URL,
    crypto: crypto.webcrypto,
    getNodeReference: node => ({graph_id: mossGraph.id, node_id: node.id}),
    window: {location: {origin: 'http://127.0.0.1:8188'}, open: url => {openedUrl = url;}},
});
vm.runInContext(stripModule(fs.readFileSync(lmTargetsPath, 'utf8')), browserCtx);
browserCtx.openLoraBrowserForNode(mossGraph.getNodeById(4));
assert.match(openedUrl, /lm_folder=moss/, 'MOSS LoRA browser must lock folder to moss');

(async () => {
    const refreshBtn = walkEl(modelSection, n => n.tagName === 'button' && n.textContent === '刷新列表');
    await refreshBtn.onclick();
    const select = walkEl(modelSection, n => n.tagName === 'select');
    assert.equal(select.children.length, 3);
    assert.equal(select.children[0].disabled, false);
    assert.equal(select.children[1].disabled, false);
    assert.equal(select.children[2].disabled, true, 'Krea2 model in refreshed list must be disabled in MOSS branch');
    assert.match(select.children[2].textContent, /架构不符/);

    // Verify native tab opening round-trip preserves unsaved Krea2 state
    const openedTabs = [];
    const kreaDraft = {marker: 'unsaved-krea2-prompt', extra: uapMain.extra};
    const mossRecord = {path: 'workflows/MOSS_精简生产_v1.json', isLoaded: true, activeState: moss};
    const mainRecord = {path: 'workflows/UAP统一生产工作台_v2.json', isLoaded: true, activeState: uapMain};
    const tabApp = {
        graph: kreaDraft,
        async loadGraphData(data, clean, restore, wf) {
            assert.notEqual(data, wf.activeState, 'Must deep-clone activeState before loadGraphData');
            assert.equal(clean, true);
            assert.equal(restore, true);
            openedTabs.push(wf.path);
        },
        extensionManager: {
            workflow: {
                activeWorkflow: mainRecord,
                async syncWorkflows() {},
                getWorkflowByPath: p => p.includes('MOSS_') ? mossRecord : mainRecord,
            },
        },
    };
    assert.equal(await navCtx.openWorkflowChoice(tabApp, '@workflow:moss'), true);
    assert.equal(kreaDraft.marker, 'unsaved-krea2-prompt', 'Opening MOSS must not mutate outgoing Krea2 graph');
    tabApp.graph = mossGraph;
    tabApp.extensionManager.workflow.activeWorkflow = mossRecord;
    assert.equal(await navCtx.openWorkflowChoice(tabApp, '@main'), true);
    assert.deepEqual(openedTabs, ['workflows/MOSS_精简生产_v1.json', 'workflows/UAP统一生产工作台_v2.json']);
    // Verify LoRA autocomplete folder scoping and MOSS clipStrength=0 tag insertion
    let activeFiltersPref = true;
    const acApp = {graph: mossGraph, canvas: {ds: {scale: 1}}};
    const acCtx = vm.createContext({
        console,
        app: acApp,
        api: {fetchApi: async () => ({ok: true, json: async () => ({})})},
        Event: class {constructor(t) {this.type = t;}},
        localStorage: {getItem: () => null, setItem() {}},
        window: {dispatchEvent() {}, addEventListener() {}},
        document: {head: {append() {}}, body: {append() {}}, createElement: tag => new El(tag), addEventListener() {}, removeEventListener() {}},
        WILDCARD_COMMANDS: {},
        createWildcardEmptyStateItem: () => ({}),
        createWildcardNoMatchesItem: () => ({}),
        getWildcardInsertText: () => '',
        getWildcardSearchEndpoint: () => '',
        isWildcardCommand: () => false,
        isWildcardInfoItem: () => false,
        formatEmbeddingReference: s => s,
        replaceInputRange: () => {},
        TextAreaCaretHelper: class {},
        getAutocompleteAppendCommaPreference: () => false,
        getAutocompleteAutoFormatPreference: () => false,
        getAutocompleteAcceptKeyPreference: () => 'both',
        getLoraActiveFiltersAutocompletePreference: () => activeFiltersPref,
        getPromptTagAutocompletePreference: () => true,
        getTagSpaceReplacementPreference: () => false,
        setLoraManagerSettingValue: () => {},
        showToast: () => {},
    });
    vm.runInContext(
        stripModule(fs.readFileSync(lmAutocompletePath, 'utf8')).replace(/^export\s*\{[^}]*\};\s*$/gm, '') +
        '\nthis.AutoComplete = AutoComplete; this.MODEL_BEHAVIORS = MODEL_BEHAVIORS;',
        acCtx,
    );
    assert.equal(acCtx.AutoComplete.prototype._getActiveLoraFilters.call({modelType: 'loras'}), 'folder=moss&recursive=true');
    const mossTag = await acCtx.MODEL_BEHAVIORS.loras.getInsertText({modelType: 'loras'}, 'moss/画风与画师/Moss__Demo.safetensors');
    assert.equal(mossTag, '<lora:Moss__Demo:1:0> ', 'MOSS autocomplete must force clipStrength=0 when usage tips omit clip strength');

    acApp.graph = {extra: structuredClone(uapMain.extra)};
    assert.equal(acCtx.AutoComplete.prototype._getActiveLoraFilters.call({modelType: 'loras'}), 'folder=krea2&recursive=true');
    const kreaTag = await acCtx.MODEL_BEHAVIORS.loras.getInsertText({modelType: 'loras'}, 'krea2/画风与画师/Krea2__Demo.safetensors');
    assert.equal(kreaTag, '<lora:Krea2__Demo:1> ');

    acApp.graph = {extra: {}};
    assert.equal(acCtx.AutoComplete.prototype._getActiveLoraFilters.call({modelType: 'loras'}), 'use_active_filters=true');
    activeFiltersPref = false;
    assert.equal(acCtx.AutoComplete.prototype._getActiveLoraFilters.call({modelType: 'loras'}), null);

    console.log('PASS: Krea2 <-> MOSS model/encoder/VAE/LoRA guards, Unet Loader (LoraManager) refresh, /free button, lm_folder=moss, autocomplete folder/clipStrength=0, and draft-preserving tab round-trip.');
})().catch(err => {
    console.error(err);
    process.exitCode = 1;
});
