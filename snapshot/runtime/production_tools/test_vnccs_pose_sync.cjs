const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../ComfyUI/custom_nodes/vnccs-utils/web/vnccs_pose_studio.js'), 'utf8');
const graph = nodes => ({getNodeById: id => nodes.find(node => String(node.id) === String(id))});
const pose = {id: 111001};
const sibling = {id: 111001};
const root = graph([{id: 1067, subgraph: graph([pose])}, {id: 1068, subgraph: graph([sibling])}, {id: 7}]);
const context = vm.createContext({app: {rootGraph: root, graph: graph([sibling])}});
vm.runInContext(source.slice(source.indexOf('function findExecutionNode('), source.indexOf('function getVNCCSSharedMorphWorker(')), context);
assert.equal(context.findExecutionNode('1067:111001'), pose, 'Execution path resolves from root even while another subgraph is open');
assert.equal(context.findExecutionNode('1068:111001'), sibling);
assert.equal(context.findExecutionNode('1069:111001'), null, 'Missing owner must not select a same-ID child elsewhere');
assert.equal(context.findExecutionNode('7').id, 7);
context.app.rootGraph = null;
context.app.graph = root;
assert.equal(context.findExecutionNode('1067:111001'), pose);
for (const event of ['vnccs_req_pose_sync', 'vnccs_apply_sam3d_pose']) {
    const handler = source.slice(source.indexOf(`api.addEventListener("${event}"`)).split('api.addEventListener(')[1];
    assert.ok(handler.includes('const node = findExecutionNode(nodeId);'));
}
console.log('VNCCS execution-path lookup passed');
