// Offline DOM harness for the workbench base-model switcher. No server or GPU calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const runtime = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(runtime, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/runtime_controls.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

class El {
    constructor(tag) {this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.textContent = ''; this.disabled = false; this.value = '';}
    append(node) {this.children.push(node); node.parent = this; return node;}
    replaceChildren() {for (const child of this.children) child.parent = null; this.children.length = 0;}
    setAttribute(key, value) {this.attributes[key] = value;}
    set innerHTML(value) {this.children.length = 0;}
}

const VERIFIED = 'krea2/图像生成/Krea2__Krea2-Anime__v3.0__FP8__f3334536.safetensors';
const PENDING = 'krea2/图像生成/Krea2__LUSTIFY!__v10__BF16__f3015315.safetensors';

function harness(options = {}) {
    const commits = [];
    const context = vm.createContext({
        document: {createElement: tag => new El(tag)},
        commitWidget: (...args) => commits.push(args),
        mountAnimaControl: () => ({sync() {}, dispose() {}}),
        mountControlSwitches: () => null,
        taskPlan: () => ({reason: '', queueNodeIds: []}),
        fetch: options.fetch || (async () => ({ok: false, status: 500, json: async () => ({})})),
    });
    vm.runInContext(source, context);
    const values = [VERIFIED, PENDING], contracts = {[VERIFIED]: {family: 'krea2', blocks: 28}};
    if (options.extraModel) {values.push(options.extraModel); contracts[options.extraModel] = {family: options.extraFamily || 'anima', blocks: 28};}
    const widget = {name: 'unet_name', value: options.value ?? VERIFIED, options: {values}};
    const node = {id: 1183, type: 'UNETLoader', mode: 0, widgets: [widget], inputs: options.linked ? [{name: 'unet_name', link: 7}] : []};
    const graph = {
        id: 'fixture', _nodes: [node], extra: {uap_workbench: {activeBranch: 'k2'}, uap_model_contracts: {families: {krea2: {label: 'Krea2'}}, models: contracts}},
        getNodeById(id) {return this._nodes.find(item => String(item.id) === String(id));},
    };
    const app = {graph};
    const branch = {id: 'k2', label: 'Krea2 生产', modelFamily: 'krea2', nodeIds: [1183]};
    const host = new El('div');
    const controls = context.mountRuntimeControls(host, app, branch, [node], () => options.active !== false);
    const walk = (root, predicate) => {
        if (predicate(root)) return root;
        for (const child of root.children) {const found = walk(child, predicate); if (found) return found;}
        return null;
    };
    const find = predicate => walk(host, predicate);
    const section = () => find(node => node.tagName === 'section' && node.children.some(child => child.textContent === '底模快切 · 当前分支'));
    const picker = () => {const scope = section(); return scope && walk(scope, node => node.tagName === 'select');};
    const note = () => {const scope = section(); return scope && walk(scope, node => node.attributes.role === 'status');};
    const button = label => find(node => node.tagName === 'button' && node.textContent === label);
    return {app, controls, host, commits, widget, node, picker, note, button};
}

let cases = 0;
function test(name, callback) {callback(); cases++; console.log('PASS: ' + name);}

test('select lists installed base models and shows the current one', () => {
    const h = harness();
    const select = h.picker();
    assert.ok(select, 'base-model select is rendered');
    assert.equal(select.children.length, 2);
    assert.equal(select.value, VERIFIED);
    assert.equal(h.note().textContent, '当前：' + VERIFIED);
    assert.equal(select.disabled, false);
    assert.equal(h.commits.length, 0);
});

test('a model that is only in the folder is selectable without registration', () => {
    const h = harness();
    const select = h.picker();
    const pending = select.children.find(option => option.value === PENDING);
    assert.equal(pending.disabled, false, 'unregistered but installed models stay selectable');
    assert.doesNotMatch(pending.textContent, /不兼容|未核验/);
    select.value = PENDING;
    select.onchange();
    assert.equal(h.commits.length, 1);
    assert.deepEqual(h.commits[0].slice(1, 4), [h.node, h.widget, PENDING]);
    assert.match(h.note().textContent, /已切换到/);
});

test('a model registered for another family is refused', () => {
    const foreign = 'krea2/图像生成/一些 Anima 底模.safetensors';
    const h = harness({extraModel: foreign, extraFamily: 'anima'});
    const select = h.picker();
    const option = select.children.find(item => item.value === foreign);
    assert.equal(option.disabled, true);
    assert.match(option.textContent, /架构不符/);
    select.value = foreign;
    select.onchange();
    assert.equal(h.commits.length, 0);
    assert.match(h.note().textContent, /只能加载同架构底模/);
});

test('choosing a registered model commits the widget once', () => {
    const h = harness({value: PENDING});
    const select = h.picker();
    select.value = VERIFIED;
    select.onchange();
    assert.equal(h.commits.length, 1);
    assert.deepEqual(h.commits[0].slice(1, 4), [h.node, h.widget, VERIFIED]);
    assert.match(h.note().textContent, /已切换到/);
});

test('linked model name disables the dropdown instead of overwriting the link', () => {
    const h = harness({linked: true});
    const select = h.picker();
    assert.equal(select.disabled, true);
    select.value = VERIFIED;
    select.onchange();
    assert.equal(h.commits.length, 0);
    assert.match(h.note().textContent, /由连线控制/);
});

test('browsing an inactive branch does not switch models', () => {
    const h = harness({active: false});
    const select = h.picker();
    assert.equal(select.disabled, true);
    assert.match(h.note().textContent, /浏览未启用分支/);
});

test('refresh reloads the local list without touching the saved model', async () => {
    const values = [VERIFIED, PENDING, 'krea2/图像生成/extra.safetensors'];
    const h = harness({fetch: async () => ({ok: true, json: async () => ({UNETLoader: {input: {required: {unet_name: [values]}}}})})});
    const refresh = h.button('刷新列表');
    await refresh.onclick();
    assert.equal(h.picker().children.length, 3);
    assert.equal(h.commits.length, 0);
    assert.match(h.note().textContent, /已刷新/);
});

console.log(`\n${cases} cases passed`);
