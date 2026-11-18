const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const events = [];
const seed = { id: 1, widgets: [{ name: 'seed', value: 42 }] };
const sampler = { id: 2, inputs: [{ name: 'seed', link: 7 }], widgets: [{ name: 'seed', value: -1 }, { name: 'steps', value: 30 }] };
const upstreamPrompt = { id: 3, type: 'CR Prompt Text', inputs: [{ name: 'prompt', link: null, widget: { name: 'prompt' } }], widgets: [{ name: 'prompt', value: 'upstream positive' }] };
const linkedClipEncode = { id: 4, type: 'CLIPTextEncode', inputs: [{ name: 'text', link: 8, widget: { name: 'text' } }], widgets: [{ name: 'text', value: 'overridden' }] };
const graph = {
    links: { 7: { origin_id: 1 }, 8: { origin_id: 3 } },
    getNodeById: id => ({ 1: seed, 2: sampler, 3: upstreamPrompt, 4: linkedClipEncode })[id] || null,
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
assert.equal(context.promptWidgetSource(linkedClipEncode, 'text').node, upstreamPrompt, 'Trace linked CLIPTextEncode.text upstream to CR Prompt Text.prompt');
assert.equal(context.promptWidgetSource(linkedClipEncode, 'text').widget.name, 'prompt');

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

function hydrateWorkflow(data) {
    const links = Object.fromEntries((data.links || []).map(l => [l[0], { origin_id: l[1], origin_slot: l[2], target_id: l[3], target_slot: l[4], type: l[5] }]));
    const nodes = (data.nodes || []).map(raw => {
        const node = structuredClone(raw);
        if (node.type === 'CR Prompt Text') {
            node.widgets = [{ name: 'prompt', value: String(node.widgets_values?.[0] ?? '') }];
        } else if (node.type === 'Krea2EditGroundedEncode') {
            node.widgets = [
                { name: 'prompt', value: String(node.widgets_values?.[0] ?? '') },
                { name: 'grounding_px', value: node.widgets_values?.[1] },
                { name: 'system_prompt', value: String(node.widgets_values?.[2] ?? '') },
            ];
        } else if (node.type === 'CLIPTextEncode') {
            node.widgets = [{ name: 'text', value: String(node.widgets_values?.[0] ?? '') }];
        } else if (node.type === 'ShowText|pysssss') {
            node.widgets = [{ name: 'text_0', value: 'readonly preview' }];
        } else {
            node.widgets = [];
        }
        return node;
    });
    const byId = new Map(nodes.map(n => [String(n.id), n]));
    return { links, nodes, getNodeById: id => byId.get(String(id)) || null };
}

const workflow = JSON.parse(fs.readFileSync(path.join(root, 'ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json'), 'utf8'));
for (const branch of workflow.extra.uap_workbench.branches) {
    const groups = branch.stages.flatMap(stage => stage.groups);
    assert.equal(groups.length, new Set(groups).size, `${branch.id}: Navigation groups must have one stage`);
}

const hydratedUap = hydrateWorkflow(workflow);
context.app.graph = hydratedUap;

// Verify Krea2 main branch resolves #1233 (positive) & #1185 (negative), never #1175 ShowText or #1179 linked CLIPTextEncode
const k2Branch = workflow.extra.uap_workbench.branches.find(b => b.id === 'k2');
const k2Nodes = k2Branch.nodeIds.map(id => hydratedUap.getNodeById(id)).filter(Boolean);
assert.ok(k2Nodes.some(n => n.id === 1175 && n.type === 'ShowText|pysssss'), 'Fixture keeps #1175 ShowText ahead of #1233');
const k2Prompts = context.resolveBranchPromptNodes(k2Nodes);
assert.equal(k2Prompts.positive?.id, 1233, 'Krea2 branch must bind positive prompt to #1233 [00W-1]');
assert.equal(k2Prompts.negative?.id, 1185, 'Krea2 branch must bind negative prompt to #1185 [00W-1N]');
assert.equal(context.preferredPromptWidget(k2Prompts.positive), 'prompt');
assert.equal(context.promptWidgetSource(k2Prompts.positive)?.node?.id, 1233);
assert.deepEqual(k2Prompts.positive.inputs[0].widget, { name: 'prompt' }, '#1233 CR Prompt Text preserves prompt widget metadata');

// Verify ext04 branch resolves #1236 (positive edit instruction) & #1237 (negative)
const ext04Branch = workflow.extra.uap_workbench.branches.find(b => b.id === 'ext04');
const ext04Nodes = ext04Branch.nodeIds.map(id => hydratedUap.getNodeById(id)).filter(Boolean);
const ext04Prompts = context.resolveBranchPromptNodes(ext04Nodes);
assert.equal(ext04Prompts.positive?.id, 1236, 'ext04 positive resolves to #1236 Krea2EditGroundedEncode');
assert.equal(ext04Prompts.negative?.id, 1237, 'ext04 negative resolves to #1237 Krea2EditGroundedEncode');

// Verify standalone Krea2_精简生产_v1.json also resolves #1233 & #1185 cleanly
const leanK2 = JSON.parse(fs.readFileSync(path.join(root, 'ComfyUI/user/default/workflows/Krea2_精简生产_v1.json'), 'utf8'));
const hydratedLean = hydrateWorkflow(leanK2);
context.app.graph = hydratedLean;
const leanPrompts = context.resolveBranchPromptNodes(hydratedLean.nodes);
assert.equal(leanPrompts.positive?.id, 1233);
assert.equal(leanPrompts.negative?.id, 1185);
assert.deepEqual(leanPrompts.positive.inputs[0].widget, { name: 'prompt' });

console.log('PASS: linked source editing, ShowText interception defense, Krea2 #1233/#1185 & ext04 #1236/#1237 prompt resolution, native callbacks.');
