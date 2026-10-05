const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../ComfyUI/custom_nodes/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_workbench.js'), 'utf8')
    .replace(/^import .*;$/m, '').replaceAll('export function ', 'function ');
const nodes = new Map([[1, {mode: 0}], [2, {mode: 2}], [3, {mode: 4}], [4, {mode: 2}], [5, {mode: 2}]]);
const settings = {activeBranch: 'a', branches: [
    {id: 'a', label: 'A', nodeIds: [1, 2, 3], modes: {1: 0, 2: 2, 3: 4}},
    {id: 'b', label: 'B', nodeIds: [4, 5], modes: {4: 0, 5: 4}},
]};
const ds = {scale: 0.1, offset: [900, -1200]};
const app = {
    registerExtension() {},
    graph: {extra: {uap_workbench: settings}, _groups: [{title: 'Target', _pos: [4000, 8000], _size: [900, 600]}],
        getNodeById: id => nodes.get(id), beforeChange() {}, afterChange() {}, setDirtyCanvas() {}},
    canvas: {ds, canvas: {getBoundingClientRect: () => ({left: 0, top: 54, width: 1869, height: 1266})},
        setZoom(value) {ds.scale = value;}, setDirty() {}}
};
const context = vm.createContext({app, document: {querySelector: () => null, getElementById: () => ({hidden: false, getBoundingClientRect: () => ({bottom: 246})})}});
vm.runInContext(source, context);
vm.runInContext('activate = {}; status = {}; viewBranch = "b"; activateBranch();', context);
assert.deepEqual([...nodes.values()].map(n => n.mode), [2, 2, 2, 0, 4], 'Switch must restore bypassed state and mute the old branch');
nodes.get(5).mode = 2;
vm.runInContext('viewBranch = "a"; activateBranch();', context);
assert.deepEqual([...nodes.values()].map(n => n.mode), [0, 2, 4, 2, 2], 'A must recover its original optional and bypassed states');
vm.runInContext('viewBranch = "b"; activateBranch();', context);
assert.equal(nodes.get(5).mode, 2, 'A user change within B must survive a round trip');
nodes.get(4).mode = 4;
vm.runInContext('activateBranch();', context);
assert.equal(nodes.get(4).mode, 4, 'Activating the current branch must not reset it');
vm.runInContext('focusGroups(["Target"]);', context);
const transform = JSON.stringify(ds);
ds.scale = 0.87;
ds.offset = [-120000, 2];
vm.runInContext('focusGroups(["Target"]);', context);
assert.equal(JSON.stringify(ds), transform, 'Navigation must land identically from different starting zooms');
const [group] = app.graph._groups;
const left = (group._pos[0] + ds.offset[0]) * ds.scale;
const top = (group._pos[1] + ds.offset[1]) * ds.scale;
assert(left >= 90 && left + group._size[0] * ds.scale <= 1829);
assert(top >= 220 && top + group._size[1] * ds.scale <= 1186, 'Target must fit below the toolbar in CSS pixels');
assert.equal(vm.runInContext('focusGroups(["Missing"]);', context), false);
context.document.querySelector = () => ({getBoundingClientRect: () => ({right: 620, width: 560})});
vm.runInContext('focusGroups(["Target"]);', context);
assert((group._pos[0] + ds.offset[0]) * ds.scale >= 644, 'The group must clear the open sidebar');
console.log('PASS: optional modes, bypass modes, edited state round trip, idempotent activation, repeatable navigation, viewport fit, missing target.');
