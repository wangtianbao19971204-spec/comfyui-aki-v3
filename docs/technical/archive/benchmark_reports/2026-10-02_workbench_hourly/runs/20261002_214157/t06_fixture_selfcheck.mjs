import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

const directory = new URL('./', import.meta.url);
const source = await fs.readFile(new URL('t06_collector.js', directory), 'utf8');
const widget = {name: 'positive', value: 'M9B synthetic 1063'};
const sideWidget = {name: 'text', value: ''};
const node = {widgets: [widget], inputs: []}, sideNode = {widgets: [sideWidget]};
const input = {value: widget.value, isConnected: true, closest: () => null, getClientRects: () => [{}]};
const app = {graph: {id: 'a2b12b8e-d5c6-5b86-9dc9-26ab3378cbf8', extra: {uap_workbench: {activeBranch: 'a1'}}, getNodeById: id => id === 1063 ? node : id === 1030 ? sideNode : null}};
const passthrough = [];
const baseFetch = async (resource, init) => {
  passthrough.push({resource, init});
  return new Response('{}', {headers: {'Content-Type': 'application/json'}});
};
const window = {__m9b: {}, fetch: baseFetch};
const context = vm.createContext({
  window, __testApp: app, performance, URL, Response, Request, structuredClone,
  location: {href: 'http://127.0.0.1:8188/', origin: 'http://127.0.0.1:8188'},
  document: {querySelectorAll: () => [input], querySelector: () => null, hidden: false, hasFocus: () => true},
  setTimeout, clearTimeout, queueMicrotask
});
// Only replace browser module resolution. This test does not reproduce real DOM, production insertion, or paint timing.
const result = await vm.runInContext(source.replace("await import('/scripts/app.js')", '({app: __testApp})'), context);
assert.equal(result.installed, true);
assert.ok(Object.values(result.fixture_checks).every(Boolean));
const id = result.fixture_id, categoryId = result.category_id;
const index = await (await window.fetch('/prompt_selector/library/index')).json();
const list = await (await window.fetch('/prompt_selector/library/prompts?view=all&limit=30')).json();
const detail = await (await window.fetch('/prompt_selector/library/prompt?prompt_id=' + id + '&selection=1')).json();
assert.equal(index.categories.length, 1);
assert.equal(index.categories[0].prompt_count, 1);
assert.equal(list.total, 1);
assert.equal(list.items.length, 1);
assert.equal(list.items[0].id, id);
assert.equal(detail.requested_id, id);
assert.equal(detail.prompt.prompt, list.items[0].prompt);
assert.equal(detail.prompt._semantic.binding, list.items[0]._semantic.binding);
assert.equal(detail.prompt._semantic.usage, 'positive');
assert.equal(detail.prompt._categoryId, categoryId);
const marked = await window.fetch('/prompt_selector/prompts/mark_used', {method: 'POST', body: JSON.stringify({prompt_id: id, category_id: categoryId})});
assert.equal(marked.status, 200);
assert.equal(passthrough.length, 0);
const rejected = [];
for (const [path, init] of [
  ['/prompt_selector/library/prompt?prompt_id=real-data', undefined],
  ['/prompt_selector/prompts/mark_used', {method: 'POST', body: JSON.stringify({prompt_id: 'real-data', category_id: categoryId})}],
  ['/prompt', {method: 'POST', body: '{}'}],
  ['/api/userdata/workflows/test.json', {method: 'POST', body: '{}'}]
]) {
  let failed = false;
  try {await window.fetch(path, init);} catch (error) {failed = /M9c isolated guard/.test(error.message);}
  assert.equal(failed, true, path);
  rejected.push(path);
}
assert.equal(passthrough.length, 0);
await window.fetch('/system_stats');
assert.equal(passthrough.length, 1);
const snapshot = window.__m9cT06.snapshot();
assert.equal(snapshot.current.node_value, 'M9B synthetic 1063');
assert.equal(snapshot.current.bound_input_value, 'M9B synthetic 1063');
assert.equal(snapshot.current.side_value, '');
assert.equal(snapshot.requests.length, 4);
assert.equal(snapshot.blocked.length, 4);
window.__m9cT06.cleanup();
assert.equal(window.fetch, baseFetch);
assert.equal(window.__m9cT06, undefined);
const receipt = {
  status: 'PASS', tested_at: new Date().toISOString(),
  scope: 'Node VM fixture/guard contract only; not live browser, insertion/undo, XHR, or performance acceptance',
  source: fileURLToPath(new URL('t06_collector.js', directory)),
  fixture_checks: result.fixture_checks, synthetic_requests: snapshot.requests.length,
  expected_rejections: rejected, cleanup_restored_underlying_guard: true,
  graph_values_unchanged: true
};
await fs.writeFile(new URL('t06_fixture_selfcheck.json', directory), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify(receipt));
