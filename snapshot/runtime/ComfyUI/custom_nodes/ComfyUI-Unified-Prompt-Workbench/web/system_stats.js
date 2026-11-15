// Nav readout for VRAM and system RAM. ComfyUI's /system_stats is the source
// model loading and the queue use, so this bar cannot disagree with them.
const POLL_MS = 2500;
const GIB = 1024 ** 3;
const WARN_PERCENT = 85;
const HOT_PERCENT = 95;

const sizes = bytes => (Math.max(0, bytes) / GIB).toFixed(1);

export function readUsage(payload) {
    if (!payload || typeof payload !== 'object') throw new Error('内存数据格式异常');
    const system = payload.system || {};
    // Unified-memory devices (mps) repeat ram_total, so only accelerator memory counts as VRAM.
    const devices = (Array.isArray(payload.devices) ? payload.devices : []).filter(device => device && device.type !== 'cpu' && device.type !== 'mps');
    const vramTotal = devices.reduce((sum, device) => sum + (Number(device.vram_total) || 0), 0);
    const vramFree = devices.reduce((sum, device) => sum + (Number(device.vram_free) || 0), 0);
    const ramTotal = Number(system.ram_total) || 0;
    const ramFree = Number(system.ram_free) || 0;
    if (!vramTotal && !ramTotal) throw new Error('未报告显存与内存容量');
    return {
        gpu: vramTotal ? {total: vramTotal, free: Math.min(vramFree, vramTotal), devices: devices.map(device => device.name || 'GPU')} : null,
        ram: ramTotal ? {total: ramTotal, free: Math.min(ramFree, ramTotal)} : null,
    };
}

export function describeUsage(usage) {
    const measure = (label, item) => {
        if (!item) return {label, value: '—', percent: 0, level: 'wait', free: 0, devices: []};
        const used = Math.max(0, item.total - item.free), percent = used / item.total * 100;
        return {
            label, percent, free: item.free, devices: item.devices || [],
            value: `${sizes(used)}/${sizes(item.total)}G`,
            level: percent >= HOT_PERCENT ? 'hot' : percent >= WARN_PERCENT ? 'warn' : 'normal',
        };
    };
    return {gpu: measure('GPU', usage.gpu), ram: measure('内存', usage.ram)};
}

export function mountSystemStats(host) {
    const root = document.createElement('div');
    root.className = 'uw-sysstats'; root.dataset.uw = 'system-stats';
    root.setAttribute('role', 'group'); root.setAttribute('aria-label', '显存与内存占用');
    const chips = [['gpu', 'GPU'], ['ram', '内存']].map(([kind, label]) => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'uw-sysstat';
        button.dataset.uw = 'system-' + kind; button.dataset.state = 'wait';
        const name = document.createElement('span'); name.className = 'uw-sysstat-name'; name.textContent = label;
        const value = document.createElement('span'); value.className = 'uw-sysstat-value'; value.textContent = '—';
        const meter = document.createElement('span'); meter.className = 'uw-sysstat-meter';
        const fill = document.createElement('span'); meter.append(fill);
        button.append(name, value, meter); root.append(button);
        return {kind, label, button, value, fill};
    });
    host.append(root);

    let timer = null, inFlight = null, disposed = false;
    const unavailable = reason => {
        for (const chip of chips) {
            chip.button.dataset.stale = 'true';
            chip.button.title = `${chip.label}：暂时无法读取（${reason}），稍后自动重试。`;
            chip.button.setAttribute('aria-label', `${chip.label}用量暂时无法读取`);
        }
    };
    const paint = measures => chips.forEach(chip => {
        const measure = measures[chip.kind];
        delete chip.button.dataset.stale;
        chip.button.dataset.state = measure.level;
        chip.value.textContent = measure.value;
        chip.fill.style.width = Math.min(100, measure.percent).toFixed(1) + '%';
        const detail = measure.level === 'wait' ? `${chip.label}：当前运行环境没有报告这项容量。` : `${chip.label} 已用 ${measure.value}，可用 ${sizes(measure.free)}G。`;
        chip.button.title = [detail, ...measure.devices, '来源：ComfyUI /system_stats · 每 2.5 秒刷新 · 点击立即刷新'].join('\n');
        chip.button.setAttribute('aria-label', detail);
    });
    // The workbench stays mounted while another dialog covers it; skip polling then.
    const hidden = () => document.hidden || root.offsetParent === null;
    async function refresh() {
        if (disposed || inFlight || hidden()) return;
        const controller = new AbortController(); inFlight = controller;
        const timeout = setTimeout(() => controller.abort(), 6000);
        try {
            const response = await fetch('/system_stats', {cache: 'no-store', signal: controller.signal});
            if (!response.ok) throw new Error(`服务返回 ${response.status}`);
            const measures = describeUsage(readUsage(await response.json()));
            if (!disposed) paint(measures);
        } catch (error) {
            if (!disposed) unavailable(controller.signal.aborted ? '请求超过 6 秒' : error.message);
        } finally {
            clearTimeout(timeout);
            if (inFlight === controller) inFlight = null;
        }
    }
    const wake = () => { if (!document.hidden) void refresh(); };
    for (const chip of chips) chip.button.onclick = () => void refresh();
    document.addEventListener('visibilitychange', wake);
    timer = setInterval(() => void refresh(), POLL_MS);
    void refresh();
    return {
        root,
        refresh,
        dispose() {
            disposed = true; clearInterval(timer); document.removeEventListener('visibilitychange', wake);
            inFlight?.abort(); inFlight = null; root.remove();
        },
    };
}
