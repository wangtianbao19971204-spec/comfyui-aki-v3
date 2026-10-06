const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const events = [];
const seed = { id: 1, widgets: [{ name: 'seed', value: 42 }] };
const sampler = { id: 2, inputs: [{ name: 'seed', link: 7 }], widgets: [{ name: 'seed', value: -1 }, { name: 'steps', value: 30 }] };
const graph = {
    links: { 7: { origin_id: 1 } }, getNodeById: id => id === 1 ? seed : sampler,
    beforeChange: () => events.push('before'), afterChange: () => events.push('after'),
    setDirtyCanvas: () => events.push('dirty'),
};
const context = vm.createContext({ app: { graph, canvas: {} } });
vm.runInContext(fs.readFileSync(path.join(root, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/prompt_target.js'), 'utf8')
    .replace(/^import .*;\r?$/gm, '').replaceAll('export ', '') + '\nconst sharedCommitWidget = commitWidget;', context);
vm.runInContext(fs.readFileSync(path.join(root, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js'), 'utf8')
    .replace(/^import .*;\r?$/gm, '').replaceAll('export ', ''), context);
assert.equal(context.widgetSource(sampler, 'seed').node, seed, 'Edit the connected seed source, not the unused sampler seed');
assert.equal(context.widgetSource(sampler, 'steps').node, sampler);
assert.equal(context.widgetSource(undefined, 'width'), null);
assert.equal(context.widgetSource(sampler, 'unknown'), null);
const widget = seed.widgets[0];
let callbackValue;
widget.callback = value => { callbackValue = value; };
context.commitWidget(seed, widget, 123);
assert.equal(seed.widgets[0].value, 123); assert.equal(callbackValue, 123);
assert.equal(sampler.widgets[0].value, -1);
assert.deepEqual(events, ['before', 'after', 'dirty']);
context.commitWidget(seed, widget, 123);
assert.equal(events.length, 3, 'Repeated input/change must not duplicate the transaction');
widget.callback = () => { throw new Error('callback failed'); };
assert.throws(() => context.commitWidget(seed, widget, 124), /callback failed/);
assert.deepEqual(events.slice(-3), ['before', 'after', 'dirty']);
const workflow = JSON.parse(fs.readFileSync(path.join(root, 'ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json'), 'utf8'));
for (const branch of workflow.extra.uap_workbench.branches.filter(b => b.dailyRows)) {
    const daily = branch.stages.find(s => s.id === 'daily');
    assert.deepEqual(branch.dailyRows.flat(), daily.groups);
    assert.ok(daily.groups.some(title => title.startsWith('CORE-02B')), 'LoRA belongs beside daily inputs');
    assert.ok(daily.groups.some(title => title.startsWith('CTRL-00')), 'Tool switches belong beside daily inputs');
    const groups = branch.stages.flatMap(stage => stage.groups);
    assert.equal(groups.length, new Set(groups).size, 'Navigation groups must have one stage');
}
console.log('PASS: linked source editing, native callbacks, no-op edits, transaction cleanup, daily LoRA/switch grouping.');
