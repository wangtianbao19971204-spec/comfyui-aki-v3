const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const runtime = path.resolve(__dirname, '..');
const web = path.join(runtime, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web');
const canvasWriteSource = fs.readFileSync(path.join(web, 'canvas_write.js'), 'utf8').replace(/^export /gm, '');
const source = fs.readFileSync(path.join(web, 'control_switches.js'), 'utf8').replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const context = vm.createContext({commitWidget: (_, node, widget, value) => {widget.value = value; widget.callback?.(value);}});
vm.runInContext(canvasWriteSource, context);
vm.runInContext(source, context);

function load(data) {
    const definitions = new Map((data.definitions?.subgraphs || []).map(graph => [graph.id, graph]));
    function graph(raw) {
        const result = {...raw, _nodes: [], beforeChange() {}, afterChange() {}, setDirtyCanvas() {}, getNodeById(id) {return this._nodes.find(node => String(node.id) === String(id));}};
        for (const item of raw.nodes) {
            const node = structuredClone(item); node.graph = result;
            const names = node.type === 'DazzleSwitch' ? ['select', 'mode', 'select_override'] : node.type === 'LoadImage' ? ['image'] : [];
            node.widgets = names.map((name, index) => ({name, value: node.widgets_values[index]}));
            if (definitions.has(node.type)) node.subgraph = graph(definitions.get(node.type));
            result._nodes.push(node);
        }
        return result;
    }
    return graph(data);
}
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const selected = node => {
    const value = node.widgets.find(widget => widget.name === 'select').value;
    return node.inputs.find(port => (port.label || port.name) === value)?.name || value;
};
const mode = (node, name) => node.widgets.find(widget => widget.name === name).value;

const targets = [
    ['ComfyUI/user/default/workflows', 'UAP统一生产工作台_v2.json', 'k2'],
    ['production_tools/templates', 'UAP统一生产工作台_v2.json', 'k2'],
    ['ComfyUI/user/default/workflows', '生产套件_03_Krea2_一体化生产_v2.json', null],
    ['production_tools/templates', '生产套件_03_Krea2_一体化生产_v2.json', null],
    ['ComfyUI/user/default/workflows', 'Krea2_精简生产_v1.json', null],
];
let cases = 0, eraseCycles = 0;
for (const [folder, file, id] of targets) {
    const data = read(path.join(runtime, folder, file));
    const graph = load(data), app = {graph};
    const branch = id && graph.extra.uap_workbench.branches.find(branch => branch.id === id);
    const before = JSON.stringify(data);
    const scope = context.controlScope(graph, branch);
    assert.ok(scope, `${folder}/${file}/${id}: recognized`);
    assert.equal(JSON.stringify(data), before, 'Discovery never edits saved user data');
    assert.equal(context.controlState(scope).enabled, false, `${folder}/${file}: Krea2 Depth control defaults to OFF`);

    const savedBranchModes = branch ? JSON.stringify(branch.modes) : null;
    const links = JSON.stringify([graph.links, ...graph._nodes.filter(node => node.subgraph).map(node => node.subgraph.links)]);

    context.setControl(app, scope, false);
    assert.equal(context.controlState(scope).enabled, false);
    assert.equal(selected(scope.model), 'input_02');
    for (const node of [scope.compact, scope.encode, scope.apply, scope.loader])
        if (node) node.mode = 0;
    assert.equal(context.controlState(scope).enabled, false, 'Legacy node enable leaves explicit base-model route disabled');

    context.setControl(app, scope, true, 'reference');
    assert.equal(context.controlState(scope).enabled, true);
    assert.equal(selected(scope.model), 'input_01');
    assert.equal(mode(scope.model, 'mode'), 'strict', 'A missing control source must not silently fall back');
    assert.equal(mode(scope.model, 'select_override'), 0);
    scope.model.mode = 2;
    assert.equal(context.controlState(scope).enabled, false, 'A muted model selector cannot report active control');
    scope.model.mode = 0;

    if (scope.pose) {
        context.setControl(app, scope, true, 'pose');
        assert.equal(scope.pose.mode, 0);
        assert.equal(context.controlState(scope).source, 'pose');
        context.setControl(app, scope, false);
        assert.equal(context.controlState(scope).source, 'pose', 'Turning control off keeps the selected source');
        context.setControl(app, scope, true);
        assert.equal(context.controlState(scope).source, 'pose');
        assert.equal(scope.poseDepth.mode, 0);
        assert.equal(scope.poseReference.mode, 0);
    } else {
        assert.throws(() => context.setControl(app, scope, true, 'pose'), /姿势工作室/);
    }

    context.setErase(app, scope, true);
    assert.equal(context.controlState(scope).source, 'reference', 'One erase action also selects its supported source');
    assert.equal(context.controlState(scope).enabled, true);
    assert.equal(context.controlState(scope).erase, true);
    if (scope.pose) assert.equal(scope.pose.mode, 2);
    context.setErase(app, scope, false);
    assert.equal(context.controlState(scope).erase, false);
    if (scope.erase) assert.equal(selected(scope.erase), 'input_02');
    else assert.equal(scope.composite.mode, 4, 'Only the composite is bypassed, never the whole control subgraph');

    if (branch) assert.equal(JSON.stringify(branch.modes), savedBranchModes, 'Runtime toggles write node.mode without mutating branches[].modes');
    assert.equal(JSON.stringify([graph.links, ...graph._nodes.filter(node => node.subgraph).map(node => node.subgraph.links)]), links, 'Buttons never rewire graphs');

    const protectedValues = () => {
        const flatten = graph => graph._nodes.flatMap(node => [[node.id, node.type, node.inputs, node.outputs, node.widgets_values,
            node.widgets.filter(widget => !['select', 'mode', 'select_override'].includes(widget.name))], ...(node.subgraph ? flatten(node.subgraph) : [])]);
        return JSON.stringify([graph.links, flatten(graph)]);
    };
    const originalValues = protectedValues();
    for (let round = 0; round < 100; round++) {
        context.setErase(app, scope, true);
        assert.equal(context.controlState(scope).erase, true);
        context.setErase(app, scope, false);
        assert.equal(context.controlState(scope).erase, false);
        assert.equal(context.controlState(scope).enabled, true, 'Erasing off keeps reference control enabled');
        eraseCycles++;
    }
    assert.equal(protectedValues(), originalValues, 'Repeated erasing never changes links, prompts, models, inputs or mask files');
    scope.model.inputs.push({name: 'select_override', link: 999});
    const snapshot = scope.nodes.map(node => [node.mode, node.widgets.map(widget => widget.value)]);
    assert.throws(() => context.setControl(app, scope, false), /控制选择/);
    assert.deepEqual(scope.nodes.map(node => [node.mode, node.widgets.map(widget => widget.value)]), snapshot);
    cases++;
}
assert.equal(context.controlScope({_nodes: [], getNodeById() {}}), null);
console.log(`PASS: ${cases} real workflow scopes; default-off Krea2 Depth control, strict routing, zero rewiring and ${eraseCycles} erase on/off cycles.`);

class Element {
    constructor(tag) {this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.style = {};}
    append(child) {this.children.push(child);}
    setAttribute(name, value) {this.attributes[name] = value;}
    remove() {this.removed = true;}
}
const all = node => [node, ...node.children.flatMap(all)];
function controlUi(uap = true) {
    const image = {alpha: 255, delayed: false, decodes: 0};
    const document = {
        createElement: tag => tag === 'canvas' ? {getContext: () => ({drawImage() {}, getImageData: () => ({data: [0, 0, 0, image.alpha]})})} : new Element(tag),
        querySelector: () => null,
        body: new Element('body'),
    };
    const dom = vm.createContext({
        document, URLSearchParams, setTimeout: fn => {fn(); return 0;}, requestAnimationFrame: fn => {fn(); return 0;},
        location: {href: 'http://127.0.0.1:8188/'}, history: {state: null, replaceState() {}},
        api: {apiURL: value => value},
        Image: class {constructor() {this.naturalWidth = this.naturalHeight = 1;} decode() {image.decodes++; return image.delayed ? new Promise((resolve, reject) => {image.resolve = resolve; image.reject = reject;}) : Promise.resolve();}},
        commitWidget: (_, node, widget, value) => {widget.value = value;},
    });
    vm.runInContext(canvasWriteSource, dom);
    vm.runInContext(source, dom);
    const file = uap ? 'UAP统一生产工作台_v2.json' : '生产套件_03_Krea2_一体化生产_v2.json';
    const graph = load(read(path.join(runtime, 'ComfyUI/user/default/workflows', file)));
    const branch = uap ? graph.extra.uap_workbench.branches.find(item => item.id === 'k2') : null;
    if (branch) graph.extra.uap_workbench.activeBranch = branch.id;
    const editor = {};
    const app = {rootGraph: graph, graph, canvas: {setGraph(next) {app.graph = next;}, deselectAllNodes() {}, selectNode(node) {editor.selected = node;}}, extensionManager: {command: {async execute(name) {editor.command = name;}}}};
    const host = new Element('div'), panel = dom.mountControlSwitches(host, app, branch), scope = dom.controlScope(graph, branch);
    const input = label => all(host).find(node => node.attributes['aria-label'] === label);
    const erase = input('启用擦线'), enabled = input('启用控制');
    const status = () => all(host).find(node => node.attributes.role === 'status').textContent || '';
    return {image, dom, graph, branch, editor, app, host, panel, scope, input, erase, enabled, status};
}
const fresh = () => { const h = controlUi(); if (h.enabled.checked) { h.enabled.checked = false; h.enabled.onchange(); } return h; };
async function ui() {
    const {image, editor, host, panel, scope, erase, enabled, status} = controlUi();
    assert.ok(scope, 'Krea2 UAP branch mounts a control scope');
    assert.equal(enabled.checked, false, 'Krea2 UAP control checkbox starts unchecked');
    assert.equal(erase.checked, false, 'Disabled control does not show erasing as active');
    erase.checked = true; await erase.onchange();
    assert.equal(scope.apply.mode, 2, 'RGB/no selection cannot enable control through erasing');
    assert.match(status(), /还没有擦线区域/);
    image.alpha = 0; erase.checked = true; await erase.onchange();
    assert.equal(scope.apply.mode, 0); assert.equal(erase.checked, true);
    enabled.checked = false; enabled.onchange(); assert.equal(erase.checked, false);
    const edit = all(host).find(node => node.textContent === '画擦线区域'); await edit.onclick();
    assert.equal(editor.selected, scope.mask); assert.equal(editor.command, 'Comfy.MaskEditor.OpenMaskEditor');
    enabled.checked = false; enabled.onchange();
    image.delayed = true; erase.checked = true; const pending = erase.onchange();
    scope.mask.graph._nodes = scope.mask.graph._nodes.filter(node => node !== scope.mask); scope.mask.graph = null;
    image.resolve(); await pending; panel.sync();
    assert.equal(scope.apply.mode, 2); assert.equal(edit.disabled, true); assert.equal(erase.disabled, true);
    panel.dispose(); assert.equal(host.children[0].removed, true);
    console.log('PASS: empty alpha guard, automatic control enable, direct editor, deleted mask during async check and disposal.');

    for (const kind of ['empty', 'linked', 'unreadable']) {
        const h = fresh();
        if (kind === 'empty') h.scope.mask.widgets[0].value = '';
        if (kind === 'linked') h.scope.mask.inputs.push({name: 'image', link: 999});
        if (kind === 'unreadable') h.image.delayed = true;
        h.erase.checked = true; const pending = h.erase.onchange();
        if (kind === 'unreadable') h.image.reject(new Error('Fixture missing image'));
        await pending;
        assert.equal(h.scope.apply.mode, 2, `${kind}: failed input cannot enable control`);
        assert.equal(h.erase.checked, false); assert.equal(h.erase.disabled, false);
        assert.match(h.status(), kind === 'empty' ? /先画/ : kind === 'linked' ? /其他输入/ : /无法读取/);
        if (kind !== 'unreadable') assert.equal(h.image.decodes, 0);
    }
    {
        const h = fresh(); h.image.alpha = 0; h.image.delayed = true;
        h.erase.checked = true; const pending = h.erase.onchange();
        h.erase.checked = true; await h.erase.onchange();
        assert.equal(h.image.decodes, 1, 'Repeated clicks do not launch competing image reads');
        h.image.resolve(); await pending; assert.equal(h.scope.apply.mode, 0); assert.equal(h.erase.checked, true);
    }
    for (const kind of ['mask-value', 'branch', 'root-graph', 'dispose', 'deleted-model']) {
        const h = fresh(); h.image.alpha = 0; h.image.delayed = true;
        h.erase.checked = true; const pending = h.erase.onchange();
        if (kind === 'mask-value') h.scope.mask.widgets[0].value = 'different mask.png';
        if (kind === 'branch') h.graph.extra.uap_workbench.activeBranch = 'ext04';
        if (kind === 'root-graph') {h.app.rootGraph = h.app.graph = {_nodes: []};}
        if (kind === 'dispose') h.panel.dispose();
        if (kind === 'deleted-model') {h.graph._nodes = h.graph._nodes.filter(node => node !== h.scope.model); h.scope.model.graph = null;}
        h.image.resolve(); await pending;
        assert.equal(h.scope.apply.mode, 2, `${kind}: old async result cannot change the workflow`);
        if (kind !== 'mask-value') assert.equal(h.erase.disabled, true);
    }
    for (const role of ['encode', 'apply', 'loader', 'mask']) {
        const h = controlUi();
        h.graph._nodes = h.graph._nodes.filter(node => node !== h.scope[role] && !(node.subgraph?._nodes || []).includes(h.scope[role]));
        assert.equal(h.dom.controlScope(h.graph), null, `Missing required ${role} cannot mount a partial panel`);
    }
    console.log('PASS: empty/linked/unreadable masks, duplicate clicks, stale filename/branch/graph/model, disposed handlers and missing roles.');
}
ui().catch(error => {console.error(error); process.exitCode = 1;});

function lifecycle() {
    const document = {head: new Element('head'), body: new Element('body'), createElement: tag => new Element(tag)};
    let ext = null, disposed = 0, mounts = 0;
    const root = {model: {id: 1}}, app = {rootGraph: root, registerExtension: extension => {ext = extension; extension.setup();}};
    const page = vm.createContext({app, document, controlScope: graph => ({model: graph.model}), mountControlSwitches: () => {mounts++; return {sync() {}, dispose() {disposed++;}};}});
    vm.runInContext(fs.readFileSync(path.join(web, 'control_panel.js'), 'utf8').replace(/^import .*;\r?\n/gm, ''), page);
    const button = document.body.children[0]; button.onclick(); assert.equal(mounts, 1);
    root.model = {id: 1}; ext.afterConfigureGraph(); button.onclick();
    assert.equal(mounts, 2); assert.equal(disposed, 1, 'Native configure reuses the graph but replaces nodes; rebuild the panel');
    root.extra = {uap_workbench: {}}; ext.afterConfigureGraph(); assert.equal(button.hidden, true);
    console.log('PASS: standalone panel rebinds on event-driven workflow replacement and hides for UAP.');
}
lifecycle();
