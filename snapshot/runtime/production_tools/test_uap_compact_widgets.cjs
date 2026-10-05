// Regression checks for empty/populated LoRA sizing and UAP group reflow.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const workflow = JSON.parse(read(process.argv[2] || 'ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json'));
let events = [];
const sizing = vm.createContext({
    app: {}, setTimeout: fn => fn(),
    window: { dispatchEvent: event => events.push(event) },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
});
vm.runInContext(read('ComfyUI/custom_nodes/ComfyUI-Lora-Manager/web/comfyui/loras_widget_utils.js')
    .replace(/^import .*;$/m, '').replaceAll('export ', ''), sizing);
let empty = true;
const css = new Map();
const container = {
    classList: { toggle() {} }, querySelector: () => empty ? {} : null,
    style: { setProperty: (key, value) => css.set(key, value) },
};
const node = {
    properties: { uap_compact_widgets: true }, inputs: [{}], outputs: [{}, {}, {}],
    size: [400, 350], setSize(value) { this.size = value; }, setDirtyCanvas() {},
};
const update = height => sizing.updateWidgetHeight(container, height, 200, node);
update(100);
assert.equal(node.size[1], 200);
assert.equal(css.get('--comfy-widget-height'), '32px');
empty = false; update(84);
assert.equal(node.size[1], 252);
update(444);
assert.equal(css.get('--comfy-widget-height'), '164px');
assert.equal(node.size[1], 332);
empty = true; update(100);
assert.equal(node.size[1], 200);
const eventCount = events.length;
update(100);
assert.equal(events.length, eventCount, 'Stable sizing must not trigger a reflow loop');
node.properties.uap_compact_widgets = false;
update(100);
assert.equal(css.get('--comfy-widget-height'), '200px');
empty = false; update(444);
assert.equal(css.get('--comfy-widget-height'), '444px');
assert.equal(events.length, eventCount, 'Ordinary workflows must keep their previous behavior');

let extension, listener, frame;
const graph = {
    _nodes: structuredClone(workflow.nodes), extra: structuredClone(workflow.extra),
    _groups: workflow.groups.map(g => ({ title: g.title, _pos: g.bounding.slice(0, 2), _size: g.bounding.slice(2) })),
    setDirtyCanvas() {},
};
for (const n of graph._nodes) n.graph = graph;
const app = { graph, registerExtension(e) { extension = e; } };
vm.runInNewContext(read('ComfyUI/custom_nodes/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_compact_layout.js')
    .replace(/^import .*;$/m, ''), {
    app, window: { addEventListener(type, callback) { listener = callback; } },
    requestAnimationFrame(callback) { frame = callback; return 1; },
});
extension.setup(); extension.afterConfigureGraph();
const subject = graph._nodes.find(n => n.type === 'Lora Stacker (LoraManager)');
const originalHeight = subject.size[1];
const invariant = () => JSON.stringify(graph._nodes.map(n => [n.id, n.mode, n.widgets_values, n.inputs, n.outputs]));
const before = invariant();
const intersects = (a, b) => a.pos[0] < b.pos[0] + b.size[0] && b.pos[0] < a.pos[0] + a.size[0]
    && a.pos[1] - 30 < b.pos[1] + b.size[1] && b.pos[1] - 30 < a.pos[1] + a.size[1];
function verifyGeometry() {
    for (let i = 0; i < graph._nodes.length; i++) {
        const a = graph._nodes[i];
        const group = graph._groups.find(g => g.title === a.properties.uap_layout_group);
        assert.ok(group, `Node ${a.id} needs an owner group`);
        assert.ok(a.pos[0] >= group._pos[0] && a.pos[1] - 30 >= group._pos[1]);
        assert.ok(a.pos[0] + a.size[0] <= group._pos[0] + group._size[0] + 0.1);
        assert.ok(a.pos[1] + a.size[1] <= group._pos[1] + group._size[1] + 0.1);
        for (const b of graph._nodes.slice(i + 1)) assert.ok(!intersects(a, b), `${a.id} overlaps ${b.id}`);
    }
    assert.equal(invariant(), before, 'Reflow must preserve graph values and modes');
}
subject.size[1] += 132;
listener({ detail: { node: subject } }); frame(); verifyGeometry();
subject.size[1] = originalHeight;
listener({ detail: { node: subject } }); frame(); verifyGeometry();
extension.beforeConfigureGraph(); frame = undefined;
listener({ detail: { node: subject } });
assert.equal(frame, undefined, 'Ignore sizing events during graph configuration');
console.log('PASS: empty/populated/capped/ordinary sizing; growth/shrink reflow; geometry and semantic invariants; graph configuration guard.');
