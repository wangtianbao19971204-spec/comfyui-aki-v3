// Offline mount smoke test for the workbench shell: catches build-time reference
// errors (the panel used to go blank when a new host was inserted before the
// control host was declared). No server, workflow or GPU calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const runtime = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(runtime, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/workspace.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

class El {
    constructor(tag) {
        this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {};
        this.classList = {add() {}, remove() {}, toggle() {}, contains() {return false;}};
        this.textContent = ''; this.hidden = true; this.value = ''; this.className = '';
    }
    append(node) {this.children.push(node); node.parent = this; return node;}
    insertBefore(node, reference) {
        if (!reference) throw new TypeError('insertBefore: reference node is missing');
        const index = this.children.indexOf(reference);
        if (index < 0) throw new TypeError('insertBefore: reference node is not a child');
        this.children.splice(index, 0, node); node.parent = this; return node;
    }
    replaceChildren() {this.children.length = 0;}
    setAttribute(key, value) {this.attributes[key] = value;}
    removeAttribute(key) {delete this.attributes[key];}
    get firstElementChild() {return this.children[0] || null;}
    get childElementCount() {return this.children.length;}
    contains() {return false;}
    querySelectorAll() {return [];}
    addEventListener() {}
}

const inert = () => ({
    refresh() {}, sync() {}, prepare: () => ({reason: '', queueNodeIds: []}), setTask() {}, setActive() {},
    submitted() {}, dispose() {}, setShown() {}, mount: () => () => {},
});
const context = vm.createContext({
    document: {createElement: tag => new El(tag)},
    window: {addEventListener() {}, removeEventListener() {}, unifiedDailyControls: null},
    setTimeout, clearTimeout, HTMLElement: El,
    listPromptTargets: () => [], attachPromptAutocomplete() {}, commitWidget() {},
    isEnabledTarget: () => true, promptDirection: () => '', inspectStaticPromptInputs: () => ({}),
    workflowChoices: () => [], isWorkflowChoice: () => false, openWorkflowChoice() {},
    mountRunControls: inert, mountTaskActivity: inert, mountControlSwitches: inert, mountModelSwitch: inert,
});
vm.runInContext(source, context);

const worked = vm.runInContext('typeof mountWorkspace', context);
assert.equal(worked, 'function', 'mountWorkspace is exported');

const element = (tag, text, parent, props = {}) => {
    const node = Object.assign(new El(tag), props);
    if (text != null) node.textContent = text;
    parent?.append(node);
    return node;
};
const button = (label, key, callback, parent) => {
    const node = element('button', label, parent);
    node.onclick = callback; node.dataset.key = key;
    return node;
};

const node = {id: 1183, type: 'UNETLoader', mode: 0, widgets: [], inputs: []};
const app = {
    graph: {
        id: 'fixture', _nodes: [node],
        extra: {uap_workbench: {activeBranch: 'k2', branches: [{id: 'k2', label: 'Krea2 生产', nodeIds: [1183], stages: [], dailyRows: null}]}},
        getNodeById(id) {return this._nodes.find(item => String(item.id) === String(id));},
    },
};
const host = new El('div');
host.hidden = true;   // skip refresh(); the build path is what used to throw
const view = context.mountWorkspace(host, {
    app, element, button, browse() {}, selectTarget() {}, report() {}, savePlan() {}, models() {}, close() {},
});
assert.ok(view && typeof view.dispose === 'function', 'mountWorkspace returns a disposable view');
const modelHosts = [];
const walk = root => {
    if (root.className === 'uw-model-switch-host') modelHosts.push(root);
    for (const child of root.children) walk(child);
};
walk(host);
assert.equal(modelHosts.length, 1, 'exactly one model-switch host is created');
assert.equal(host.children.length > 0, true, 'the shell renders content');
view.dispose();
console.log('PASS: workspace shell mounts, hosts the model switcher once and disposes');
