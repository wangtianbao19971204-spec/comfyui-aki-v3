// Offline native queue lifecycle fault injection. No server or model calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/run_controls.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const deferred = () => {let resolve, reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject};};
const settle = async () => {for (let count = 0; count < 8; count++) await Promise.resolve();};
class Element {
    constructor(tag) {this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {};}
    append(node) {this.children.push(node);}
    replaceChildren() {this.children = [];}
    setAttribute(key, value) {this.attributes[key] = value;}
}
function harness(options = {}) {
    const listeners = new Map(), calls = [], reports = [], submitted = [], buttons = new Map(), queue = {Running: [], Pending: []};
    const api = {
        addEventListener(name, callback) {if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(callback);},
        removeEventListener(name, callback) {listeners.get(name)?.delete(callback);},
        emit(name, detail) {for (const callback of [...listeners.get(name) || []]) callback({detail});},
        getQueue: async () => queue, fetchApi: async () => ({ok: true, json: async () => ({})}),
        interrupt: async id => {calls.push(['interrupt', id]);}, ...options.api,
    };
    const element = (tag, text, parent, props = {}) => {const node = Object.assign(new Element(tag), props); if (text != null) node.textContent = text; parent?.append(node); return node;};
    const button = (label, key, callback, parent) => {const node = element('button', label, parent); node.onclick = callback; buttons.set(key, node); return node;};
    const app = {graph: {id: 'fixture-graph', _nodes: []}, nextQueueRequestId: 1, queueItems: [], processingQueue: false, async queuePrompt(...args) {
        calls.push(['queue', ...args]); const requestId = this.nextQueueRequestId++;
        api.emit('promptQueueing', {requestId, batchCount: 1});
        api.emit('promptQueued', {requestId, batchCount: 1}); return true;
    }, ...options.app};
    const report = message => reports.push(message); report.clear = key => reports.push(['clear', key]);
    const context = vm.createContext({api, URLSearchParams, setTimeout, clearTimeout}); vm.runInContext(source, context);
    const host = new Element('div');
    const controls = context.mountRunControls(host, {app, element, button, report,
        prepareTask: options.prepareTask || (() => ({task: 'generate', label: '生成', queueNodeIds: ['final']})), onSubmitted: task => submitted.push(task)});
    controls.setTask({task: 'generate', label: '生成', reason: ''});
    return {api, app, controls, calls, reports, submitted, buttons, listeners, host, queue,
        status: host.children[0].children[0], history: host.children[1], run: buttons.get('run'), stop: buttons.get('interrupt')};
}
let cases = 0;
async function test(name, callback) {await callback(); cases++; console.log('PASS: ' + name);}
async function main() {
    await test('accepted matching receipt forwards partial target and clears errors once', async () => {
        const h = harness(); await settle(); await h.run.onclick();
        assert.equal(h.submitted.length, 1); assert.equal(h.reports.filter(value => Array.isArray(value)).length, 1);
        assert.equal(JSON.stringify(h.calls[0][3]), JSON.stringify({queueNodeIds: ['final']}));
        assert.equal(h.listeners.get('promptQueued').size, 0); assert.equal(h.run.disabled, false);
    });
    await test('no receipt, wrong receipt, false rejection and network failure never claim submission', async () => {
        for (const mode of ['missing', 'different', 'rejected', 'network']) {
            const h = harness(); h.app.queuePrompt = async () => {
                if (mode === 'network') throw new Error('fixture disconnect');
                if (mode === 'different') {h.api.emit('promptQueueing', {requestId: 7}); h.api.emit('promptQueued', {requestId: 8, batchCount: 1});}
                return mode !== 'rejected';
            };
            await assert.rejects(() => h.run.onclick(), mode === 'network' ? /disconnect/ : /未提交/);
            assert.equal(h.submitted.length, 0); assert.equal(h.run.disabled, false);
            assert.equal(h.listeners.get('promptQueueing').size, 0); assert.equal(h.listeners.get('promptQueued').size, 0);
        }
    });
    await test('reason/empty target blocks queuing', async () => {
        for (const plan of [{reason: 'fixture not ready', queueNodeIds: ['final']}, {queueNodeIds: []}]) {
            const h = harness({prepareTask: () => plan}); await assert.rejects(() => h.run.onclick()); assert.equal(h.calls.length, 0);
        }
    });
    await test('repeated click during preparation submits only once', async () => {
        const pending = deferred(); let prepared = 0;
        const h = harness({prepareTask: () => {prepared++; return pending.promise;}});
        const first = h.run.onclick(); await h.run.onclick(); assert.equal(prepared, 1);
        pending.resolve({queueNodeIds: ['final']}); await first; assert.equal(h.calls.length, 1);
    });
    await test('dispose during preparation never submits an old task', async () => {
        const pending = deferred(), h = harness({prepareTask: () => pending.promise});
        const first = h.run.onclick(); h.controls.dispose(); pending.resolve({queueNodeIds: ['final']}); await first;
        assert.equal(h.calls.length, 0); for (const name of ['status', 'execution_success', 'execution_error']) assert.equal(h.listeners.get(name).size, 0);
    });
    await test('stop rejects missing running ID and never interrupts a different task', async () => {
        const h = harness(); await settle(); await h.stop.onclick(); assert.equal(h.calls.length, 0);
        h.queue.Running = [{}]; await assert.rejects(() => h.stop.onclick(), /无法确认/); assert.equal(h.calls.length, 0);
        h.queue.Running = [{prompt_id: 'own-running'}]; await h.stop.onclick(); assert.equal(h.calls[0][1], 'own-running');
    });
    await test('repeated stop and dispose during queue read cause no repeated interruption', async () => {
        const gate = deferred(), h = harness(); await settle();
        h.api.getQueue = () => gate.promise;
        const stopping = h.stop.onclick(); await h.stop.onclick(); h.controls.dispose();
        gate.resolve({Running: [{prompt_id: 'old-job'}], Pending: []}); await stopping; assert.equal(h.calls.length, 0);
    });
    await test('queue/interrupt failure allows retry and does not forge success', async () => {
        const h = harness(); await settle(); h.api.getQueue = async () => {throw new Error('fixture queue unavailable');};
        await assert.rejects(() => h.stop.onclick(), /queue unavailable/); assert.equal(h.stop.attributes['aria-disabled'], 'false');
        h.api.getQueue = async () => ({Running: [{prompt_id: 'job'}], Pending: []});
        h.api.interrupt = async () => {throw new Error('fixture interrupt failed');};
        await assert.rejects(() => h.stop.onclick(), /interrupt failed/); assert.equal(h.stop.attributes['aria-disabled'], 'false');
    });
    await test('cancel active optimization once and never call backend interrupt', async () => {
        const work = deferred(), cancel = deferred(); let cancellations = 0;
        const h = harness({prepareTask: () => ({task: 'optimize', execute: () => work.promise, cancel: () => {cancellations++; return cancel.promise;}})});
        h.controls.setTask({task: 'optimize', label: '优化'}); const running = h.run.onclick(); await settle();
        const stopping = h.stop.onclick(); await h.stop.onclick(); assert.equal(cancellations, 1);
        work.resolve(false); cancel.resolve(true); await Promise.all([running, stopping]);
        assert.match(h.status.textContent, /已取消/); assert.equal(h.calls.length, 0);
    });
    await test('failed optimization and disposed late result do not claim completion', async () => {
        const failed = harness({prepareTask: () => ({execute: async () => {throw new Error('fixture optimizer down');}})});
        await assert.rejects(() => failed.run.onclick(), /optimizer down/); assert.match(failed.status.textContent, /失败/);
        const work = deferred(); let cancelled = 0;
        const h = harness({prepareTask: () => ({execute: () => work.promise, cancel: async () => {cancelled++;}})});
        const running = h.run.onclick(); await settle(); h.controls.dispose(); const before = h.status.textContent;
        work.resolve(true); await running; assert.equal(h.status.textContent, before); assert.equal(cancelled, 1);
    });
    await test('later refresh owns status and malformed history remains a readable failure', async () => {
        const h = harness(); await settle(); const old = deferred(), latest = deferred(); let calls = 0;
        h.api.getQueue = () => (++calls === 1 ? old.promise : latest.promise);
        const first = h.buttons.get('refresh-run').onclick(), second = h.buttons.get('refresh-run').onclick();
        latest.resolve({Running: [{prompt_id: 'fresh'}], Pending: []}); await second;
        old.resolve({Running: [], Pending: []}); await first; assert.match(h.status.textContent, /运行中 1/);
        h.history.open = true; h.api.getQueue = async () => h.queue;
        h.api.fetchApi = async () => ({ok: true, json: async () => {throw new Error('fixture bad history JSON');}});
        await h.buttons.get('refresh-run').onclick(); assert.match(h.status.textContent, /读取失败/);
    });
    await test('native buffered request waits for its own receipt instead of claiming not submitted', async () => {
        const h = harness(); await settle();
        h.app.nextQueueRequestId = 7;
        h.app.processingQueue = true;
        h.app.queuePrompt = async () => {
            h.app.queueItems.push({requestId: 7}); h.api.emit('promptQueueing', {requestId: 7, batchCount: 1}); return false;
        };
        const running = h.run.onclick(); running.catch(() => {}); await settle();
        assert.equal(h.run.disabled, true, 'A native buffered request is still pending');
        h.app.queueItems = []; h.api.emit('promptQueued', {requestId: 99, batchCount: 1}); await settle(); assert.equal(h.submitted.length, 0);
        h.api.emit('promptQueued', {requestId: 7, batchCount: 1}); h.app.processingQueue = false;
        await running; assert.equal(h.submitted.length, 1);
    });
    await test('buffered rejection, graph switch and disposal exit without foreign success or leaked listeners', async () => {
        for (const mode of ['rejected', 'graph', 'branch', 'dispose']) {
            const h = harness(); await settle(); h.app.processingQueue = true;
            h.app.queuePrompt = async () => {h.api.emit('promptQueueing', {requestId: 1, batchCount: 1}); return false;};
            const running = h.run.onclick(); running.catch(() => {}); await settle();
            assert.equal(h.run.disabled, true);
            if (mode === 'rejected') h.app.processingQueue = false;
            if (mode === 'graph') h.app.graph = {id: 'other-graph', _nodes: []};
            if (mode === 'branch') h.app.graph.extra = {uap_workbench: {activeBranch: 'different'}};
            if (mode === 'dispose') h.controls.dispose();
            if (mode === 'dispose') await running;
            else await assert.rejects(() => running, mode === 'rejected' ? /未提交/ : /工作流已切换/);
            assert.equal(h.submitted.length, 0); assert.equal(h.listeners.get('promptQueueing').size, 0); assert.equal(h.listeners.get('promptQueued').size, 0);
            if (mode === 'graph' || mode === 'branch') assert.match(h.status.textContent, /队列核对/);
        }
    });
    await test('native next request identity rejects an unrelated interleaved queueing event', async () => {
        const h = harness(); h.app.queuePrompt = async () => {
            h.api.emit('promptQueueing', {requestId: 99, batchCount: 1}); h.api.emit('promptQueued', {requestId: 99, batchCount: 1});
            h.api.emit('promptQueueing', {requestId: 1, batchCount: 1}); return true;
        };
        await assert.rejects(() => h.run.onclick(), /未提交/); assert.equal(h.submitted.length, 0);
    });
    console.log(`PASS: ${cases} run-control lifecycle scenarios; isolated event/API fixtures only.`);
}
main().catch(error => {console.error(error); process.exitCode = 1;});
