import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const directory = new URL('./', import.meta.url);
const source = await fs.readFile(new URL('t06_collector.js', directory), 'utf8');
let now = 0, nextFrame = 1;
const frames = new Map(), microtasks = [], clickListeners = new Set(), observers = [];
const widget = {name: 'positive', value: 'M9B synthetic 1063'}, side = {name: 'text', value: ''};
const node = {widgets: [widget], inputs: []}, sideNode = {widgets: [side]};
const input = {value: widget.value, isConnected: true, closest: () => null, getClientRects: () => [{}]};
const panel = {}, status = {textContent: ''};
const mode = {value: 'append_end'}, card = {querySelector: () => mode};
const button = {disabled: false, closest: selector => selector === '.tb-spm-card' ? card : null, getClientRects: () => [{}]};
const app = {graph: {id: 'a2b12b8e-d5c6-5b86-9dc9-26ab3378cbf8', extra: {uap_workbench: {activeBranch: 'a1'}}, getNodeById: id => id === 1063 ? node : sideNode}};
class FakeObserver {
  constructor(callback) {this.callback = callback; this.connected = false; observers.push(this);}
  observe() {this.connected = true;}
  disconnect() {this.connected = false;}
}
const document = {
  querySelectorAll: () => [input],
  querySelector: selector => selector.endsWith('.tb-spm-target-status') ? status : selector === '#tb-shared-preset-panel' ? panel : button,
  addEventListener: (event, listener) => clickListeners.add(listener),
  removeEventListener: (event, listener) => clickListeners.delete(listener),
  hidden: false, hasFocus: () => true
};
const window = {__m9b: {}, fetch: async () => new Response('{}')};
const context = vm.createContext({
  window, document, __testApp: app, performance: {now: () => now}, URL, Response, structuredClone,
  location: {href: 'http://127.0.0.1:8188/', origin: 'http://127.0.0.1:8188'},
  MutationObserver: FakeObserver, setTimeout, clearTimeout, queueMicrotask: callback => microtasks.push(callback),
  requestAnimationFrame: callback => {const id = nextFrame++; frames.set(id, callback); return id;},
  cancelAnimationFrame: id => frames.delete(id)
});
await vm.runInContext(source.replace("await import('/scripts/app.js')", '({app: __testApp})'), context);
const collector = window.__m9cT06;
const armed = collector.arm('insert', {cohort: 'synthetic_collector_contract'});
now = 100;
for (const listener of [...clickListeners]) listener({isTrusted: true, target: {closest: selector => selector === armed.selector ? button : null}});
while (microtasks.length) microtasks.shift()();
assert.equal(frames.size, 1, 'not-ready microtask must schedule one rAF fallback');
now = 107;
widget.value = input.value = armed.expected;
for (const observer of observers) if (observer.connected) observer.callback();
assert.equal(frames.size, 1, 'MO ready must replace fallback with exactly one paint callback');
now = 108;
for (const observer of observers) if (observer.connected) observer.callback();
assert.equal(frames.size, 1, 'repeated MO notifications must not duplicate paint callbacks');
function tick(timestamp) {
  now = timestamp;
  const pending = [...frames.values()]; frames.clear();
  pending.forEach(callback => callback(timestamp));
}
tick(1100);
assert.equal(frames.size, 1);
tick(2100);
const sample = await collector.wait();
assert.equal(sample.status, 'ready_after_two_animation_frames');
assert.equal(sample.both_ready_ms, 7);
assert.equal(sample.both_ready_source, 'mutation_observer');
assert.equal(sample.duration_ms, 2000);
assert.equal(sample.raf_tail_ms, 1993);
assert.equal(sample.raf_tails[0].first_wait_ms, 993);
assert.equal(sample.raf_tails[0].second_wait_ms, 1000);
assert.equal(sample.mutation_checks, 2);
assert.equal(sample.microtask_checks, 1);
assert.equal(sample.raf_checks, 0);
assert.equal(frames.size, 0);
assert.equal(clickListeners.size, 0);
assert.ok(observers.every(observer => !observer.connected));
collector.cleanup();
const receipt = {
  status: 'PASS', tested_at: new Date().toISOString(), collector_version: sample.collector_version,
  scope: 'Synthetic collector scheduling contract only; fake clock, fake observer, fake click, no production insertion or browser performance evidence',
  checks: {mo_ready_precedes_raf_tail: true, duplicate_mo_does_not_duplicate_raf: true, fallback_cancelled_on_mo_ready: true, observers_and_frames_cleaned: true},
  synthetic_sample: sample
};
await fs.writeFile(new URL('t06_observer_selfcheck.json', directory), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify({status: receipt.status, scope: receipt.scope, checks: receipt.checks}));
