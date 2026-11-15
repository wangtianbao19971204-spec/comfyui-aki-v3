// Comprehensive offline regression test for all 8 standalone lightweight UAP workflows.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const runtime = path.resolve(__dirname, '..');
const pack = path.join(runtime, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench');
const web = path.join(pack, 'web');
const dailyPath = path.join(pack, 'modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js');

const stripModule = text => text.replace(/^import\s[\s\S]*?;\r?\n/gm, '').replace(/^export\s+/gm, '');

const SUITE = [
    {id: 'k2', choice: '@workflow:k2', file: 'Krea2_精简生产_v1.json', task: 'generate', label: '开始生图', queue: ['1136', '1138', '1226'], posId: 1233, negId: 1185},
    {id: 'moss', choice: '@workflow:moss', file: 'MOSS_精简生产_v1.json', task: 'generate', label: '开始生图', queue: ['10'], posId: 5, negId: 6},
    {id: 'ext04', choice: '@workflow:ext04', file: '生产扩展_04_Krea2_指令编辑.json', task: 'generate', label: '开始指令编辑', queue: ['10', '80', '81'], posId: 4, negId: 5},
    {id: 'caption', choice: '@workflow:caption', file: '工具_图片反推_提示词提取.json', task: 'caption', label: '开始反推', queue: ['1171'], posId: 1233, negId: null},
    {id: 'ext06', choice: '@workflow:ext06', file: '生产扩展_06_透明素材_抠图导出.json', task: 'generate', label: '开始抠图', queue: ['10', '80', '81'], posId: null, negId: null},
    {id: 'ext08', choice: '@workflow:ext08', file: '生产扩展_08_超分_二倍交付.json', task: 'generate', label: '开始放大', queue: ['10', '80', '81'], posId: null, negId: null},
    {id: 'ext09', choice: '@workflow:ext09', file: '生产扩展_09_超分_四倍素材.json', task: 'generate', label: '开始放大', queue: ['10', '80', '81'], posId: null, negId: null},
    {id: 'stocking', choice: '@workflow:stocking', file: '生产扩展_丝袜纹理修复.json', task: 'generate', label: '开始纹理修复', queue: ['2', '3'], posId: null, negId: null},
];

function hydrateGraph(spec) {
    const links = Object.fromEntries((spec.links || []).map(l => [l[0], {
        id: l[0], origin_id: l[1], origin_slot: l[2], target_id: l[3], target_slot: l[4], type: l[5],
    }]));
    const nodes = (spec.nodes || []).map(raw => {
        const n = structuredClone(raw);
        n.comfyClass = n.type;
        if (n.widgets_values_named) {
            n.widgets = Object.entries(n.widgets_values_named).map(([name, value]) => ({name, value: structuredClone(value), options: {}}));
        } else if (n.type === 'CR Prompt Text') {
            n.widgets = [{name: 'prompt', value: String(n.widgets_values?.[0] ?? ''), options: {}}];
        } else if (n.type === 'Krea2EditGroundedEncode') {
            n.widgets = [
                {name: 'prompt', value: String(n.widgets_values?.[0] ?? ''), options: {}},
                {name: 'grounding_px', value: n.widgets_values?.[1], options: {}},
                {name: 'system_prompt', value: String(n.widgets_values?.[2] ?? ''), options: {}},
            ];
        } else if (n.type === 'CLIPTextEncode') {
            n.widgets = [{name: 'text', value: String(n.widgets_values?.[0] ?? ''), options: {}}];
        } else if (n.type === 'LoadImage') {
            n.widgets = [{name: 'image', value: String(n.widgets_values?.[0] ?? 'demo.png'), options: {values: ['demo.png']}}];
        } else if (n.type === 'UNETLoader') {
            n.widgets = [{name: 'unet_name', value: String(n.widgets_values?.[0] ?? ''), options: {}}];
        } else if (n.type === 'CLIPLoader') {
            n.widgets = [
                {name: 'clip_name', value: String(n.widgets_values?.[0] ?? ''), options: {}},
                {name: 'type', value: String(n.widgets_values?.[1] ?? ''), options: {}},
            ];
        } else if (n.type === 'VAELoader') {
            n.widgets = [{name: 'vae_name', value: String(n.widgets_values?.[0] ?? ''), options: {}}];
        } else if (n.type === 'LoraLoaderModelOnly') {
            n.widgets = [
                {name: 'lora_name', value: String(n.widgets_values?.[0] ?? ''), options: {}},
                {name: 'strength_model', value: Number(n.widgets_values?.[1] ?? 1), options: {}},
            ];
        } else if (n.type === 'Lora Loader (LoraManager)' || n.type === 'Lora Stacker (LoraManager)') {
            n.widgets = [
                {name: '__lm_autocomplete_meta_text', value: n.widgets_values?.[0] || {}, options: {}},
                {name: 'text', value: String(n.widgets_values?.[1] ?? ''), options: {}},
                {name: 'loras', value: structuredClone(n.widgets_values?.[2] ?? []), options: {}},
            ];
            n.lorasWidget = n.widgets[2];
        } else if (n.type === 'StockingTextureStudio') {
            n.widgets = [{name: 'project_json', value: JSON.stringify({asset: 'ready.png'}), options: {}}];
        } else {
            n.widgets = [];
        }
        return n;
    });
    return {
        id: spec.id || 'standalone-fixture',
        _nodes: nodes,
        links,
        extra: structuredClone(spec.extra || {}),
        getNodeById(id) {return this._nodes.find(item => String(item.id) === String(id)) || null;},
        beforeChange() {},
        afterChange() {},
        setDirtyCanvas() {},
    };
}

const navCtx = vm.createContext({
    console,
    window: {unifiedUapNavigation: {activateBranch(id) {navCtx.activated = id;}}},
});
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'repair_workflow.js'), 'utf8')), navCtx);
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'task_activity.js'), 'utf8')), navCtx);
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'runtime_controls.js'), 'utf8')), navCtx);

const dailyCtx = vm.createContext({
    console,
    app: {graph: null, canvas: {}},
    api: {},
    window: {addEventListener() {}},
    document: {head: {append() {}}, body: {append() {}}, createElement: () => ({setAttribute() {}, addEventListener() {}, append() {}, style: {}})},
    setInterval: () => 1,
    sharedCommitWidget: () => true,
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
vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'prompt_target.js'), 'utf8')), dailyCtx);
vm.runInContext(stripModule(fs.readFileSync(dailyPath, 'utf8')), dailyCtx);

const parsedById = new Map();

for (const item of SUITE) {
    const wfPath = path.join(runtime, 'ComfyUI/user/default/workflows', item.file);
    const tplPath = path.join(__dirname, 'templates', item.file);
    const wfBytes = fs.readFileSync(wfPath);
    const tplBytes = fs.readFileSync(tplPath);
    assert.deepEqual(wfBytes, tplBytes, `${item.file}: workflow and template must match byte-for-byte`);

    const spec = JSON.parse(wfBytes.toString('utf8'));
    parsedById.set(item.id, spec);

    const uap = spec.extra?.uap_workbench;
    assert.ok(uap, `${item.file}: missing extra.uap_workbench`);
    assert.equal(uap.branches.length, 1, `${item.file}: standalone workflow must have exactly 1 branch`);
    assert.equal(uap.activeBranch, item.id);
    assert.equal(uap.branches[0].id, item.id);

    // Stage groups must be disjoint
    const stageGroups = uap.branches[0].stages.flatMap(s => s.groups);
    assert.equal(stageGroups.length, new Set(stageGroups).size, `${item.file}: stage groups must not repeat`);

    // Peer workflow dropdown choices
    const choices = navCtx.workflowChoices(uap);
    const expectedValues = SUITE.map(peer => peer.id === item.id ? item.id : peer.choice);
    assert.deepEqual(Array.from(choices, c => c.value), expectedValues, `${item.file}: peer dropdown choices mismatch`);

    // Hydrate & verify taskPlan + prompt resolution + workflowGuard
    const graph = hydrateGraph(spec);
    dailyCtx.app.graph = graph;
    const prompts = dailyCtx.resolveBranchPromptNodes(graph._nodes);
    assert.equal(prompts.positive?.id ?? null, item.posId, `${item.file}: positive prompt node mismatch`);
    assert.equal(prompts.negative?.id ?? null, item.negId, `${item.file}: negative prompt node mismatch`);

    const plan = navCtx.taskPlan({graph}, item.task);
    assert.equal(plan.label, item.label, `${item.file}: taskPlan label mismatch`);
    assert.equal(plan.reason, '', `${item.file}: unexpected taskPlan block reason: ${plan.reason}`);
    assert.deepEqual(Array.from(plan.queueNodeIds).sort(), [...item.queue].sort(), `${item.file}: queueNodeIds mismatch`);

    assert.equal(navCtx.workflowGuardIssue(graph._nodes, uap.branches[0], spec.extra?.uap_model_contracts), '',
        `${item.file}: workflowGuardIssue must pass cleanly`);
}

// Verify Krea2_精简生产_v1 direct #1173 -> #1200 MODEL connection and zero depth control
const k2Spec = parsedById.get('k2');
assert.equal(k2Spec.nodes.length, 36);
assert.equal(k2Spec.links.length, 47);
assert.deepEqual(k2Spec.definitions?.subgraphs || [], []);
const k2Sampler = k2Spec.nodes.find(n => n.id === 1200);
const modelLinkId = k2Sampler.inputs.find(i => i.name === 'model').link;
const modelLink = k2Spec.links.find(l => l[0] === modelLinkId);
assert.deepEqual([modelLink[1], modelLink[2], modelLink[3], modelLink[4]], [1173, 0, 1200, 0],
    '#1173 Lora Loader MODEL must wire directly into #1200 KSampler.model');

// Verify installWorkflowGuard queues #1171 on standalone caption workflow via defaultTask='caption'
(async () => {
    const captionGraph = hydrateGraph(parsedById.get('caption'));
    let queuedArgs = null;
    const captionApp = {
        graph: captionGraph,
        ui: {dialog: {show(msg) {throw new Error('Unexpected guard dialog: ' + msg);}}},
        async queuePrompt(...args) {queuedArgs = args; return true;},
    };
    navCtx.installWorkflowGuard(captionApp);
    await captionApp.queuePrompt(0, 1);
    assert.deepEqual(Array.from(queuedArgs[2].queueNodeIds), ['1171'],
        'Native/console run on standalone caption workflow must queue enabled PixAI #1171 output');

    // Verify openWorkflowChoice across all 8 standalone @workflow:* entries + @main fallback when UAP v2 is retired
    const storeRecords = new Map(SUITE.map(item => [
        `workflows/${item.file}`,
        {path: `workflows/${item.file}`, isLoaded: true, activeState: parsedById.get(item.id)},
    ]));
    const openedPaths = [];
    const currentGraph = hydrateGraph(k2Spec);
    const tabApp = {
        graph: currentGraph,
        async loadGraphData(data, clean, restore, wf) {
            assert.equal(clean, true);
            assert.equal(restore, true);
            openedPaths.push(wf.path);
        },
        extensionManager: {
            workflow: {
                activeWorkflow: storeRecords.get('workflows/Krea2_精简生产_v1.json'),
                async syncWorkflows() {},
                // Simulate retired UAP统一生产工作台_v2.json (not in storeRecords)
                getWorkflowByPath: p => storeRecords.get(p) || null,
            },
        },
    };
    for (const item of SUITE) {
        assert.equal(await navCtx.openWorkflowChoice(tabApp, item.choice), true);
    }
    assert.equal(await navCtx.openWorkflowChoice(tabApp, '@main'), true, '@main falls back to Krea2_精简生产_v1.json');
    assert.equal(await navCtx.openWorkflowChoice(tabApp, '@main:ext08'), true, '@main:ext08 falls back to 生产扩展_08');
    assert.equal(await navCtx.openWorkflowChoice(tabApp, '@main:ext09'), true, '@main:ext09 falls back to 生产扩展_09');
    assert.equal(openedPaths.length, SUITE.length + 3);
    assert.deepEqual(openedPaths.slice(-3), [
        'workflows/Krea2_精简生产_v1.json',
        'workflows/生产扩展_08_超分_二倍交付.json',
        'workflows/生产扩展_09_超分_四倍素材.json',
    ]);

    // Verify uap_erase_ui_v2 does not inject broken fallback card when depthControl === false
    const eraseCtx = vm.createContext({
        app: {graph: currentGraph, registerExtension(ext) {ext.setup();}},
        window: {},
        setInterval: () => 1,
        mountControlSwitches: () => null,
        document: {
            head: {append() {}},
            querySelector: sel => sel === '#unified-workbench .uw-workspace-controls' ? {
                contains: () => false,
                querySelector: () => null,
                insertBefore() {throw new Error('uap_erase_ui_v2 must not mount host when depthControl === false');},
            } : null,
            createElement: () => ({dataset: {}, style: {}, append() {}, replaceChildren() {}, setAttribute() {}}),
        },
    });
    vm.runInContext(stripModule(fs.readFileSync(path.join(web, 'uap_erase_ui_v2.js'), 'utf8')), eraseCtx);

    console.log('PASS: All 8 standalone UAP workflows verified (byte parity, disjoint groups, peer navigation, taskPlan, prompts, guards, @main retirement fallback, and depth-control suppression).');
})().catch(err => {
    console.error(err);
    process.exitCode = 1;
});
