// Regression checks for the nav VRAM/RAM readout fed by ComfyUI's /system_stats.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const runtime = path.resolve(__dirname, '..');
const web = path.join(runtime, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web');
const source = fs.readFileSync(path.join(web, 'system_stats.js'), 'utf8').replace(/^export /gm, '');
const live = {
    system: {ram_total: 33446264832, ram_free: 2252148736},
    devices: [{name: 'cuda:0 NVIDIA GeForce RTX 5090 D : cudaMallocAsync', type: 'cuda', index: 0,
        vram_total: 34162016256, vram_free: 984750604, torch_vram_total: 872415232, torch_vram_free: 560007692}],
};

function element(tag) {
    const node = {
        tag, children: [], dataset: {}, style: {}, attrs: {}, textContent: '', title: '', className: '', type: '',
        parent: null, hidden: false, detached: false,
        setAttribute(name, value) { this.attrs[name] = String(value); },
        append(...items) { for (const item of items) { item.parent = node; node.children.push(item); } },
        remove() { this.detached = true; },
        get offsetParent() { return this.hidden || this.detached ? null : {tag: 'offsetParent'}; },
    };
    return node;
}

function boot(respond) {
    const document = {hidden: false, listeners: new Map(), createElement: element};
    document.addEventListener = (type, callback) => { document.listeners.set(type, callback); };
    document.removeEventListener = (type, callback) => { if (document.listeners.get(type) === callback) document.listeners.delete(type); };
    const timeouts = new Map(), intervals = new Map(), calls = [];
    let next = 1;
    const context = {
        document, console, AbortController,
        fetch: (url, options) => { calls.push({url, options}); return respond(calls.length, options); },
        setTimeout: callback => { const id = next++; timeouts.set(id, callback); return id; },
        clearTimeout: id => { timeouts.delete(id); },
        setInterval: callback => { const id = next++; intervals.set(id, callback); return id; },
        clearInterval: id => { intervals.delete(id); },
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    return {context, document, calls, timeouts, intervals, tick: () => new Promise(resolve => setImmediate(resolve))};
}

const answered = payload => () => Promise.resolve({ok: true, status: 200, json: async () => payload});

(function identify() {
    const {context} = boot(answered(live));
    const usage = context.readUsage(live);
    assert.equal(usage.gpu.total, 34162016256);
    assert.equal(usage.gpu.free, 984750604);
    assert.deepEqual(usage.gpu.devices, ['cuda:0 NVIDIA GeForce RTX 5090 D : cudaMallocAsync']);
    assert.equal(usage.ram.total, 33446264832);
    const measures = context.describeUsage(usage);
    assert.equal(measures.gpu.value, '30.9/31.8G');
    assert.equal(measures.gpu.level, 'hot');
    assert.equal(measures.ram.value, '29.1/31.1G');
    assert.equal(measures.ram.level, 'warn');

    const multi = context.readUsage({system: {ram_total: 100, ram_free: 40}, devices: [
        {name: 'a', type: 'cuda', vram_total: 100, vram_free: 50},
        {name: 'b', type: 'cuda', vram_total: 100, vram_free: 25},
        {name: 'mac', type: 'mps', vram_total: 999, vram_free: 0},
        {name: 'cpu', type: 'cpu', vram_total: 999, vram_free: 0},
    ]});
    assert.equal(multi.gpu.total, 200, 'Multiple accelerators add up');
    assert.equal(multi.gpu.free, 75);
    assert.deepEqual(multi.gpu.devices, ['a', 'b'], 'Unified memory and CPU entries are not VRAM');
    const cpuOnly = context.readUsage({system: {ram_total: 64, ram_free: 60}, devices: [{name: 'mps', type: 'mps', vram_total: 64, vram_free: 60}]});
    assert.equal(cpuOnly.gpu, null);
    assert.equal(context.describeUsage(cpuOnly).gpu.value, '—');
    assert.equal(context.describeUsage(cpuOnly).gpu.level, 'wait');

    const level = (total, free) => context.describeUsage({gpu: {total, free}, ram: null}).gpu.level;
    assert.equal(level(100, 20), 'normal');
    assert.equal(level(100, 15), 'warn');
    assert.equal(level(100, 14), 'warn');
    assert.equal(level(100, 5), 'hot');
    assert.equal(level(100, 100), 'normal', 'An idle device is not a warning');
    assert.equal(context.describeUsage({gpu: {total: 100, free: 100}, ram: null}).gpu.value, '0.0/0.0G');
    assert.throws(() => context.readUsage(null), /内存数据格式异常/);
    assert.throws(() => context.readUsage('nope'), /内存数据格式异常/);
    assert.throws(() => context.readUsage({system: {}, devices: []}), /未报告显存与内存容量/);
})();

(async function mount() {
    let mode = 'ok';
    const env = boot((call, options) => {
        if (mode === 'fail') return Promise.resolve({ok: false, status: 500});
        if (mode === 'hold') return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted'))));
        return answered(live)();
    });
    const host = element('div');
    const widget = env.context.mountSystemStats(host);
    assert.equal(host.children.length, 1, 'The readout mounts once into the nav');
    assert.equal(widget.root.dataset.uw, 'system-stats');
    assert.equal(widget.root.attrs.role, 'group');
    await env.tick();
    assert.deepEqual(env.calls.map(call => call.url), ['/system_stats']);
    assert.equal(env.calls[0].options.cache, 'no-store');
    const [gpu, ram] = widget.root.children;
    assert.equal(gpu.dataset.uw, 'system-gpu');
    assert.equal(gpu.dataset.state, 'hot');
    assert.equal(gpu.children[0].textContent, 'GPU');
    assert.equal(gpu.children[1].textContent, '30.9/31.8G');
    assert.equal(gpu.children[2].children[0].style.width, '97.1%');
    assert.equal(ram.children[0].textContent, '内存');
    assert.equal(ram.children[1].textContent, '29.1/31.1G');
    assert.equal(ram.children[2].children[0].style.width, '93.3%');
    assert.equal(ram.dataset.state, 'warn');
    assert.match(gpu.title, /^GPU 已用 30\.9\/31\.8G，可用 0\.9G。/);
    assert.match(gpu.title, /RTX 5090 D/, 'The tooltip names the device');
    assert.match(gpu.title, /点击立即刷新/);
    assert.equal(gpu.attrs['aria-label'], 'GPU 已用 30.9/31.8G，可用 0.9G。');
    assert.equal(ram.attrs['aria-label'], '内存 已用 29.1/31.1G，可用 2.1G。');

    const [timerId, interval] = [...env.intervals.entries()][0];
    assert.equal(env.calls.length, 1);
    interval();
    await env.tick();
    assert.equal(env.calls.length, 2, 'The interval polls again');
    assert.ok(env.intervals.has(timerId));

    mode = 'fail';
    interval();
    await env.tick();
    assert.equal(gpu.dataset.stale, 'true', 'A failed poll keeps the last numbers but marks them stale');
    assert.equal(gpu.children[1].textContent, '30.9/31.8G');
    assert.equal(gpu.dataset.state, 'hot');
    assert.match(gpu.title, /暂时无法读取（服务返回 500）/);
    mode = 'ok';
    interval();
    await env.tick();
    assert.equal(gpu.dataset.stale, undefined, 'The next good poll clears the stale mark');

    env.document.hidden = true;
    const hiddenStart = env.calls.length;
    interval();
    await env.tick();
    assert.equal(env.calls.length, hiddenStart, 'A background tab does not poll');
    env.document.hidden = false;
    widget.root.hidden = true;
    interval();
    await env.tick();
    assert.equal(env.calls.length, hiddenStart, 'A covered workbench does not poll');
    widget.root.hidden = false;
    env.document.listeners.get('visibilitychange')();
    await env.tick();
    assert.equal(env.calls.length, hiddenStart + 1, 'Coming back to the tab refreshes at once');

    gpu.onclick();
    await env.tick();
    assert.equal(env.calls.length, hiddenStart + 2, 'Clicking the readout refreshes it');

    mode = 'hold';
    gpu.onclick();
    gpu.onclick();
    await env.tick();
    assert.equal(env.calls.length, hiddenStart + 3, 'A slow request is never stacked');
    [...env.timeouts.values()].at(-1)();
    await env.tick();
    assert.match(gpu.title, /请求超过 6 秒/);
    assert.equal(env.timeouts.size, 0, 'The abort timer is cleared');

    widget.dispose();
    assert.equal(env.intervals.size, 0, 'Closing the workbench stops polling');
    assert.equal(env.document.listeners.size, 0);
    assert.equal(widget.root.detached, true);
    const disposedStart = env.calls.length;
    await widget.refresh();
    assert.equal(env.calls.length, disposedStart, 'A disposed readout never fetches again');

    const shell = fs.readFileSync(path.join(web, 'workbench_shell.js'), 'utf8');
    assert.match(shell, /import \{mountSystemStats\} from '\.\/system_stats\.js';/);
    assert.match(shell, /const systemStats=mountSystemStats\(nav\);/);
    assert.match(shell, /clearInterval\(targetTimer\);systemStats\.dispose\(\);/);
    assert.ok(shell.indexOf('mountSystemStats(nav)') < shell.indexOf("button('收起侧栏'"),
        'The readout sits left of the sidebar toggle');
    const css = fs.readFileSync(path.join(web, 'workbench.css'), 'utf8');
    assert.match(css, /\.uw-sysstats\+\[data-uw=sidebar-toggle\]\{margin-left:8px\}/, 'The readout may not split the toggle auto margin');
    assert.match(css, /\.uw-sysstat-meter>span\{display:block;height:100%;width:0;background:currentColor/);
    const studio = fs.readFileSync(path.join(web, 'studio.css'), 'utf8');
    assert.equal((studio.match(/--uw-warn:/g) || []).length, 4, 'Every theme defines the warning tone');

    console.log('PASS: parse/aggregate/format/level rules; poll, failure, hidden tab, click, overlap, abort and disposal lifecycles; nav wiring and theme tokens.');
})().catch(error => { console.error(error); process.exit(1); });
