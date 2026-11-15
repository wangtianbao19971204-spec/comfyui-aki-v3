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

(async () => {
    const shellSource = fs.readFileSync(path.join(runtime, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/workbench_shell.js'), 'utf8')
        .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
    class ShellEl extends El {
        constructor(tag) {super(tag); this.style = {}; this.options = []; this.isConnected = true;}
        after(sibling) {if (this.parent) {const i = this.parent.children.indexOf(this); this.parent.children.splice(i + 1, 0, sibling); sibling.parent = this.parent;}}
        prepend(child) {this.children.unshift(child); child.parent = this; return child;}
        remove() {this.isConnected = false; if (this.parent) {const i = this.parent.children.indexOf(this); if (i >= 0) this.parent.children.splice(i, 1); this.parent = null;}}
        focus() {}
        select() {}
        closest() {return null;}
        getClientRects() {return [];}
        querySelector(sel) {
            const all = this.querySelectorAll(sel);
            return all[0] || null;
        }
        querySelectorAll(sel) {
            const out = [];
            const visit = item => {
                for (const child of item.children || []) {
                    if (sel === 'h2' && child.tagName === 'h2') out.push(child);
                    else if (sel === '[data-uw="close"]' && child.dataset?.uw === 'close') out.push(child);
                    else if (sel === '[aria-current=page]' && child.attributes?.['aria-current'] === 'page') out.push(child);
                    visit(child);
                }
            };
            visit(this);
            return out;
        }
    }
    const body = new ShellEl('body'), head = new ShellEl('head');
    let pendingRenders = 0, gateResolve = null;
    const shellCtx = vm.createContext({
        app: {...app, registerExtension() {}},
        document: {body, head, activeElement: body, hidden: false, createElement: tag => new ShellEl(tag), createComment: () => new ShellEl('#comment'), getElementById: () => null, querySelector: () => null},
        window: {location: {origin: 'http://127.0.0.1:8188'}, addEventListener() {}, removeEventListener() {}},
        location: {origin: 'http://127.0.0.1:8188'},
        localStorage: {getItem: () => null, setItem() {}},
        AbortController, URL, URLSearchParams,
        setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
        openTagManager: async () => {}, closeTagManager: () => true,
        createWidgetInserter: () => ({dispose() {}, supportsActions: []}), captureSelection: () => null, mountInsertionActions() {},
        installResourceActions() {}, listPromptTargets: () => [], sourceForTarget: t => t,
        getReferenceCollections: async () => ({items: []}), openReferenceCollections() {},
        mountWorkspace: () => ({setActive() {}, refresh() {}, dispose() {}, selectorHost: new ShellEl('div')}),
        createPendingPrompts: ({onCount}) => {onCount(0); return {add() {}, addMany() {}, render() {pendingRenders++;}, refreshTarget() {}};},
        installBrowserImportReceiver() {}, mountResourceResults: () => ({ready: Promise.resolve(), dispose() {}}),
        openNativeSettings() {}, installUiTheme() {}, mountThemeToggle() {}, installCanvasTheme() {}, mountCanvasThemeSetting() {},
        toolIdentity: {workspace: {title: 'w', purpose: 'p'}, library: {title: 'l', purpose: 'p'}},
        mountFunctionCard() {}, mountFunctionIcon() {},
        mountSelectorTools: () => ({refresh() {}}), openPromptSelector: async () => {},
        mountSystemStats: () => ({dispose() {}}),
        fetch: async url => {
            if (String(url).includes('/collections/index') && gateResolve) await new Promise(r => {gateResolve = r;});
            return {ok: true, status: 200, json: async () => ({modules: [], groups: []})};
        },
    });
    vm.runInContext(shellSource, shellCtx);
    const wb = await shellCtx.openWorkbench({page: 'library', openPending: true});
    assert.ok(wb, 'openWorkbench returns workbench instance');
    assert.equal(pendingRenders, 1, 'openPending renders pending view immediately');
    assert.ok(wb.root.querySelectorAll('h2').some(item => item.textContent === '待用列表'), 'pending heading is rendered');
    await wb.showPending();
    assert.equal(pendingRenders, 1, 'subsequent showPending is idempotent while pending utility is active');
    wb.close();

    gateResolve = true;
    const opening = shellCtx.openWorkbench({page: 'library', openPending: true});
    await Promise.resolve();
    const liveRoot = body.children.find(child => child.id === 'unified-workbench');
    assert.ok(liveRoot, 'workbench mounted before sidebar fetch settles');
    await liveRoot.querySelector('[data-uw="close"]').onclick();
    gateResolve();
    gateResolve = null;
    const closedInstance = await opening;
    assert.ok(closedInstance, 'openWorkbench never resolves to null when closed mid-open');
    assert.equal(await closedInstance.showPending(), false, 'showPending safely no-ops after mid-open close');
    console.log('PASS: workspace shell mounts, hosts the model switcher once, and openPending survives mid-open close');
})().catch(error => {console.error(error); process.exitCode = 1;});
