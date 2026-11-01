// Original-site annotations are read-only and never become prompt/editor fields.
const hosts = new Set(['novelai.quicktagcloud.com', 'novelai-tag.pages.dev', 'prompt-vault-gallery.pages.dev']);
const element = (tag, text, parent) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    parent?.append(node);
    return node;
};
const safeUrl = value => {
    try {
        if (typeof value !== 'string' || /[\s\\]/.test(value)) return '';
        const url = new URL(value);
        return url.protocol === 'https:' && hosts.has(url.hostname) && !url.username && !url.password && (!url.port || url.port === '443') ? url.href : '';
    } catch { return ''; }
};

export function renderSourceNotes(host, values) {
    host.replaceChildren();
    const notes = Array.isArray(values) ? values.filter(row => row && typeof row.note === 'string' && row.note.trim()) : [];
    host.hidden = !notes.length;
    if (!notes.length) return;
    const section = element('section', null, host);
    section.setAttribute('aria-label', '来源说明');
    element('h3', '来源说明', section);
    for (const row of notes) {
        const entry = element('div', null, section);
        entry.style.marginBlock = '10px';
        const labels = [row.title, row.entry_title].filter(value => typeof value === 'string' && value.trim());
        if (labels.length) element('strong', [...new Set(labels)].join(' · '), entry);
        const body = element('div', row.note, entry);
        body.style.whiteSpace = 'pre-wrap';
        body.style.overflowWrap = 'anywhere';
        const url = safeUrl(row.url);
        if (url) {
            const link = element('a', '查看原站', entry);
            link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        }
    }
}

export function mountSourceNotes(host, resourceId, {request = globalThis.fetch, isCurrent = () => host.isConnected} = {}) {
    let closed = false, version = 0, controller;
    const current = stamp => !closed && stamp === version && host.isConnected && isCurrent();
    const load = async () => {
        if (closed || !host.isConnected || !isCurrent()) return;
        const stamp = ++version;
        controller?.abort(); controller = new AbortController();
        host.hidden = false; host.replaceChildren();
        element('small', '正在读取来源说明…', host);
        try {
            const response = await request('/prompt_selector/source-notes?' + new URLSearchParams({resource_id: String(resourceId)}),
                {method: 'GET', cache: 'no-store', signal: controller.signal});
            if (!response.ok) throw new Error('unavailable');
            const result = await response.json();
            if (current(stamp)) renderSourceNotes(host, result.source_notes);
        } catch (error) {
            if (!current(stamp) || error?.name === 'AbortError') return;
            host.replaceChildren();
            element('span', '来源说明暂不可读。', host);
            const retry = element('button', '重试', host); retry.type = 'button';
            retry.onclick = () => void load();
        }
    };
    return {ready: load(), reload: load, dispose() { closed = true; version++; controller?.abort(); }};
}
