// Isolated graph fixtures exercise production dimension helpers without a server or GPU.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const unified = 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/';
const source = relative => fs.readFileSync(path.join(root, unified, relative), 'utf8')
    .replace(/^import .*;\r?$/gm, '').replaceAll('export ', '');
const shared = source('web/prompt_target.js');
const daily = source('modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js');

function fixture() {
    const nodes = new Map(), events = [], callbacks = [], undo = [];
    let depth = 0, before;
    const branch = {id: 'a1', nodeIds: [10, 11]};
    const otherBranch = {id: 'a29', nodeIds: [20]};
    const snapshot = () => [...nodes.values()].map(node => ({id: node.id,
        values: (node.widgets || []).map(widget => widget.value)}));
    const graph = {
        _nodes: [], links: {}, extra: {uap_workbench: {activeBranch: 'a1', branches: [branch, otherBranch]}},
        getNodeById: id => nodes.get(Number(id)),
        beforeChange() { events.push('before'); if (depth++ === 0) before = snapshot(); },
        afterChange() {
            events.push('after'); assert(depth > 0, 'Every transaction must be opened before closing');
            if (--depth === 0) {
                const after = snapshot();
                if (JSON.stringify(before) !== JSON.stringify(after)) undo.push({before, after});
            }
        },
        setDirtyCanvas() { events.push('dirty'); },
    };
    const addNode = node => { node.graph = graph; nodes.set(node.id, node); graph._nodes.push(node); return node; };
    const numeric = (name, value, options = {}) => ({name, value,
        options: {min: 16, max: 16384, step: 80, step2: 8, ...options},
        callback(value) { callbacks.push({name, value, receiver: this}); }});
    const size = addNode({id: 10, mode: 0, type: 'EmptyLatentImage',
        inputs: ['width', 'height', 'batch_size'].map(name => ({name, link: null})),
        widgets: [numeric('width', 1344), numeric('height', 768), numeric('batch_size', 1, {min: 1, step: 10, step2: 1})]});
    const sampler = addNode({id: 11, mode: 0, type: 'KSampler', inputs: [],
        widgets: [numeric('seed', 42, {min: 0, step2: 1}), numeric('cfg', 5, {min: 0, step2: 0.1})]});
    const other = addNode({id: 20, mode: 0, type: 'EmptyLatentImage', inputs: [],
        widgets: [numeric('width', 1024), numeric('height', 1024), numeric('batch_size', 1, {min: 1, step2: 1})]});
    const app = {graph, canvas: {}};
    const context = vm.createContext({app});
    vm.runInContext(shared + '\nconst sharedCommitWidget = commitWidget;', context);
    vm.runInContext(daily, context);
    const values = () => size.widgets.map(widget => widget.value);
    const connect = (name, id = 30, sharedSource = null) => {
        const slot = size.inputs.findIndex(input => input.name === name);
        const linkId = 100 + slot;
        const widget = size.widgets.find(widget => widget.name === name);
        const sourceNode = sharedSource || addNode({id, mode: 0, type: 'PrimitiveNode',
            inputs: [], outputs: [{name: 'INT', type: 'INT', links: []}],
            widgets: [numeric('value', widget.value)]});
        if (!branch.nodeIds.includes(sourceNode.id)) branch.nodeIds.push(sourceNode.id);
        graph.links[linkId] = {id: linkId, origin_id: sourceNode.id, origin_slot: 0,
            target_id: size.id, target_slot: slot, type: 'INT'};
        sourceNode.outputs[0].links.push(linkId);
        size.inputs[slot].link = linkId;
        sourceNode.widgets[0].callback = function(value) {
            callbacks.push({name: 'source', value, receiver: this});
            for (const id of sourceNode.outputs[0].links) {
                const link = graph.links[id], target = graph.getNodeById(link.target_id);
                const input = target?.inputs?.[link.target_slot];
                const destination = target?.widgets?.find(widget => widget.name === input?.name);
                if (destination) { destination.value = value; destination.callback?.call(destination, value, app.canvas, target); }
            }
        };
        return sourceNode;
    };
    const linkAdditional = (sourceNode, target, name, id = 200) => {
        target.inputs ||= [];
        const targetSlot = target.inputs.push({name, link: id}) - 1;
        graph.links[id] = {id, origin_id: sourceNode.id, origin_slot: 0,
            target_id: target.id, target_slot: targetSlot, type: 'INT'};
        sourceNode.outputs[0].links.push(id);
    };
    const applyUndo = () => {
        const previous = undo.pop(); assert(previous, 'A successful pair creates an undo entry');
        for (const entry of previous.before) {
            const node = graph.getNodeById(entry.id);
            entry.values.forEach((value, index) => { node.widgets[index].value = value; });
        }
    };
    return {context, app, graph, nodes, branch, otherBranch, size, sampler, other,
        values, events, callbacks, undo, connect, linkAdditional, applyUndo,
        depth: () => depth, snapshot};
}

const cases = [];
const test = (name, run) => cases.push({name, run});
const unchanged = (f, run) => {
    const before = JSON.stringify(f.snapshot()), count = f.events.length;
    assert.equal(run(), false, 'Unsafe pair must be refused');
    assert.equal(JSON.stringify(f.snapshot()), before, 'Refusal must preserve all node values');
    assert.equal(f.events.length, count, 'Prevalidation refusal must not open a transaction');
};

test('swap, reverse swap, native callbacks and one undo entry per pair', () => {
    const f = fixture(), sources = f.context.dimensionSources(f.size);
    assert.equal(f.context.commitDimensions(f.size, 768, 1344, sources), true);
    assert.deepEqual(f.values(), [768, 1344, 1]);
    assert.equal(f.undo.length, 1, 'Nested widget changes form a single undo action');
    assert.equal(f.callbacks.length, 2);
    assert.equal(f.callbacks[0].receiver, f.size.widgets[0]);
    assert.equal(f.depth(), 0);
    assert.equal(f.context.commitDimensions(f.size, 1344, 768, sources), true);
    assert.deepEqual(f.values(), [1344, 768, 1]);
    assert.equal(f.undo.length, 2);
    f.applyUndo(); assert.deepEqual(f.values(), [768, 1344, 1]);
    f.applyUndo(); assert.deepEqual(f.values(), [1344, 768, 1]);
    assert.deepEqual(f.sampler.widgets.map(widget => widget.value), [42, 5]);
    assert.deepEqual(f.other.widgets.map(widget => widget.value), [1024, 1024, 1]);
});
test('unchanged dimensions do not call callbacks or create undo', () => {
    const f = fixture();
    assert.equal(f.context.commitDimensions(f.size, 1344, 768), true);
    assert.deepEqual(f.events, []); assert.deepEqual(f.callbacks, []); assert.equal(f.undo.length, 0);
});
test('both destinations are checked before either write', () => {
    const f = fixture(); f.size.widgets[1].options.max = 1024;
    unchanged(f, () => f.context.commitDimensions(f.size, 768, 1344));
    unchanged(f, () => f.context.commitDimensions(f.size, 770, 768));
    for (const value of [0, -8, 512.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])
        unchanged(f, () => f.context.commitDimensions(f.size, value, 768));
});
test('choices follow dynamic min, max and the real step2 with a nonzero offset', () => {
    const f = fixture(), options = {min: 16, max: 900, step: 240, step2: 24};
    const widget = {options};
    assert.equal(f.context.dimensionValueAllowed(640, [widget]), true);
    assert.equal(f.context.dimensionValueAllowed(768, [widget]), false);
    assert.deepEqual(Array.from(f.context.dimensionChoices([widget])), [640, 832]);
    let maximum = 700; Object.defineProperty(options, 'max', {get: () => maximum});
    assert.deepEqual(Array.from(f.context.dimensionChoices([widget])), [640]);
    maximum = 900; options.min = 40;
    assert.equal(f.context.dimensionValueAllowed(640, [widget]), true);
    assert.equal(f.context.dimensionValueAllowed(16, [widget]), false);
    options.step2 = 16; options.min = 16;
    assert.equal(f.context.dimensionValueAllowed(1024, [widget]), false, 'Current maximum remains effective');
    maximum = 16384;
    assert.equal(f.context.dimensionValueAllowed(1024, [widget]), true, 'Legacy step must not replace step2');
});
test('dynamic destination limits are read again at commit time', () => {
    const f = fixture(), sources = f.context.dimensionSources(f.size);
    let maximum = 16384;
    Object.defineProperty(f.size.widgets[1].options, 'max', {get: () => maximum});
    maximum = 1024;
    unchanged(f, () => f.context.commitDimensions(f.size, 768, 1344, sources));
});
test('linked dimensions update real primitive sources and native target callbacks', () => {
    const f = fixture(), source = f.connect('width'), sources = f.context.dimensionSources(f.size);
    assert.equal(sources[0].node, source);
    assert.equal(f.context.commitDimensions(f.size, 768, 1344, sources), true);
    assert.equal(source.widgets[0].value, 768);
    assert.deepEqual(f.values(), [768, 1344, 1]);
    assert(f.callbacks.some(call => call.name === 'source' && call.receiver === source.widgets[0]));
    assert.equal(f.undo.length, 1); f.applyUndo();
    assert.equal(source.widgets[0].value, 1344); assert.deepEqual(f.values(), [1344, 768, 1]);
});
test('linked destination constraints supplement broader source constraints', () => {
    const f = fixture(), source = f.connect('width');
    source.widgets[0].options = {min: 1, max: 32768, step2: 1};
    unchanged(f, () => f.context.commitDimensions(f.size, 1025, 768));
    unchanged(f, () => f.context.commitDimensions(f.size, 20000, 768));
});
test('reconnected or deleted links refuse previously captured sources', () => {
    for (const change of ['reconnect', 'delete']) {
        const f = fixture(); f.connect('width');
        const sources = f.context.dimensionSources(f.size);
        if (change === 'reconnect') {
            const newSource = {id: 31, graph: f.graph, mode: 0, type: 'PrimitiveNode', inputs: [],
                outputs: [{links: [100]}], widgets: [{name: 'value', value: 1344, options: {min: 16, max: 16384, step2: 8}}]};
            f.nodes.set(31, newSource); f.graph._nodes.push(newSource); f.branch.nodeIds.push(31);
            f.graph.links[100].origin_id = 31;
        } else delete f.graph.links[100];
        unchanged(f, () => f.context.commitDimensions(f.size, 768, 1344, sources));
    }
});
test('replaced nodes, widgets, graph and source input links refuse stale edits', () => {
    for (const change of ['owner', 'source', 'widget', 'graph', 'linked-source']) {
        const f = fixture(), source = f.connect('width'), sources = f.context.dimensionSources(f.size);
        if (change === 'owner') f.nodes.set(f.size.id, {...f.size});
        if (change === 'source') f.nodes.set(source.id, {...source});
        if (change === 'widget') source.widgets[0] = {...source.widgets[0]};
        if (change === 'graph') f.app.graph = {...f.graph, getNodeById: () => null};
        if (change === 'linked-source') source.inputs = [{name: 'value', link: 999}];
        unchanged(f, () => f.context.commitDimensions(f.size, 768, 1344, sources));
    }
});
test('muted owner and sources refuse dimension edits', () => {
    for (const muted of ['owner', 'source']) {
        const f = fixture(), source = f.connect('width'), sources = f.context.dimensionSources(f.size);
        (muted === 'owner' ? f.size : source).mode = 2;
        unchanged(f, () => f.context.commitDimensions(f.size, 768, 1344, sources));
    }
});
test('width and height sharing one widget are refused', () => {
    const f = fixture(), source = f.connect('width'); f.connect('height', 30, source);
    assert.equal(f.context.dimensionSources(f.size), null);
    unchanged(f, () => f.context.commitDimensions(f.size, 768, 1344));
});
test('inactive branches and sources belonging to another branch are refused', () => {
    for (const change of ['inactive', 'outside', 'ambiguous']) {
        const f = fixture(), source = f.connect('width'), sources = f.context.dimensionSources(f.size);
        if (change === 'inactive') f.graph.extra.uap_workbench.activeBranch = 'a29';
        if (change === 'outside') { f.branch.nodeIds = f.branch.nodeIds.filter(id => id !== source.id); f.otherBranch.nodeIds.push(source.id); }
        if (change === 'ambiguous') f.otherBranch.nodeIds.push(source.id);
        assert.equal(f.context.dimensionSources(f.size) === null, true, `Refuse branch state: ${change}`);
        unchanged(f, () => f.context.commitDimensions(f.size, 768, 1344, sources));
    }
});
test('source fan-out to another branch or an unrelated parameter is refused', () => {
    for (const target of ['other-branch', 'other-field']) {
        const f = fixture(), source = f.connect('width');
        f.linkAdditional(source, target === 'other-branch' ? f.other : f.sampler,
            target === 'other-branch' ? 'width' : 'seed');
        unchanged(f, () => f.context.commitDimensions(f.size, 768, 1344));
    }
});
test('callback failure restores both values and closes the transaction', () => {
    for (const failingIndex of [0, 1]) {
        const f = fixture(), original = f.values(), widget = f.size.widgets[failingIndex];
        const oldCallback = widget.callback;
        widget.callback = function(value) {
            oldCallback.call(this, value);
            if (value !== original[failingIndex]) throw new Error('native callback rejected dimension');
        };
        let accepted, error;
        try { accepted = f.context.commitDimensions(f.size, 768, 1344); } catch (caught) { error = caught; }
        assert(error || accepted === false, 'Failed native callback must not report success');
        assert.deepEqual(f.values(), original, 'Neither dimension may remain partially changed');
        assert.equal(f.depth(), 0); assert.equal(f.undo.length, 0, 'Restored failure leaves no partial undo snapshot');
    }
});
test('linked callback failure restores primitive and propagated destination values', () => {
    const f = fixture(), source = f.connect('width'), original = f.values();
    const callback = f.size.widgets[1].callback;
    f.size.widgets[1].callback = function(value) {
        callback.call(this, value);
        if (value !== original[1]) throw new Error('height callback rejected dimension');
    };
    let accepted, error;
    try { accepted = f.context.commitDimensions(f.size, 768, 1344); } catch (caught) { error = caught; }
    assert(error || accepted === false);
    assert.equal(source.widgets[0].value, 1344);
    assert.deepEqual(f.values(), original); assert.equal(f.depth(), 0); assert.equal(f.undo.length, 0);
});
test('callback invalidating the second widget cannot report a successful partial pair', () => {
    const f = fixture(), original = f.values();
    const callback = f.size.widgets[0].callback;
    f.size.widgets[0].callback = function(value) {
        callback.call(this, value);
        if (value !== original[0]) f.size.widgets[1] = {...f.size.widgets[1]};
    };
    assert.equal(f.context.commitDimensions(f.size, 768, 1344), false);
    assert.deepEqual(f.values(), original, 'Refuse the stale second widget and restore the first dimension');
    assert.equal(f.depth(), 0); assert.equal(f.undo.length, 0);
});
test('native callback changing the requested number cannot silently succeed', () => {
    const f = fixture(), original = f.values();
    const callback = f.size.widgets[0].callback;
    f.size.widgets[0].callback = function(value) {
        callback.call(this, value);
        if (value !== original[0]) this.value = value - 8;
    };
    assert.equal(f.context.commitDimensions(f.size, 768, 1344), false);
    assert.deepEqual(f.values(), original); assert.equal(f.depth(), 0); assert.equal(f.undo.length, 0);
});

test('callback changing the other dimension range prevents the second write', () => {
    const f = fixture(), original = f.values();
    const callback = f.size.widgets[0].callback;
    f.size.widgets[0].callback = function(value) {
        callback.call(this, value);
        f.size.widgets[1].options.max = value === original[0] ? 16384 : 1024;
    };
    assert.equal(f.context.commitDimensions(f.size, 768, 1344), false);
    assert.deepEqual(f.values(), original); assert.equal(f.depth(), 0); assert.equal(f.undo.length, 0);
});

const results = cases.map(({name, run}) => {
    try { run(); return {name, pass: true}; }
    catch (error) { return {name, pass: false, error: error.message}; }
});
const failures = results.filter(result => !result.pass);
console.log(JSON.stringify({pass: failures.length === 0, cases: results.length, failures}, null, 2));
if (failures.length) process.exitCode = 1;
