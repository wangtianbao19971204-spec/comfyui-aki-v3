const MANIFEST = new URL('./historical_resource_links.json', import.meta.url);
const LABELS = {
    one_to_one_exact_body: '原文相同',
    one_to_one_normalized_body: '规范化后相近',
    multiple_records: '多记录候选，分别保留',
};
let manifestPromise;

async function readJSON(url) {
    const response = await fetch(url, {cache: 'no-store', signal: AbortSignal.timeout(15000)});
    if (!response.ok) { const error = new Error(`HTTP ${response.status}`); error.status = response.status; throw error; }
    const value = await response.json();
    if (value.error) throw new Error(value.error);
    return value;
}

function manifest() {
    if (!manifestPromise) manifestPromise = readJSON(MANIFEST).then(value => {
        if (value.schema !== 'workbench-historical-resource-links-v1' || !Array.isArray(value.links)) throw new Error('Invalid historical links');
        return value.links;
    }).catch(error => {manifestPromise = null; throw error;});
    return manifestPromise;
}

function element(tag, text, parent) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    parent.append(node);
    return node;
}

async function currentRecord(record) {
    if (record.kind === 'tag') {
        const {item} = await readJSON('/prompt_selector/tags/item?id=' + encodeURIComponent(record.id));
        if (!item || item.resource_id !== record.id) throw new Error('Tag identity changed');
        return {text: item.text || '', name: 'Tag', category: [item.group_name, item.subgroup_name].filter(Boolean).join(' / '), description: item.desc || '', notes: item.notes || ''};
    }
    const value = await readJSON('/prompt_selector/library/prompt?prompt_id=' + encodeURIComponent(record.id));
    if (!value.prompt || value.prompt.id !== record.id) throw new Error('Prompt identity changed');
    return {text: value.prompt.prompt || '', name: value.prompt.alias || '共享资料', category: value.category?.name || '', description: value.prompt.description || '', notes: ''};
}

async function digest(text) {
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
}

// Historical text matches are references, never identity merges or write instructions.
export async function mountHistoricalLinks(host, source, {readOnly = false} = {}) {
    if (host.dataset.loading === 'true') return;
    host.dataset.loading = 'true';
    host.classList.add('wb-historical-links');
    for (const type of ['copy', 'cut', 'paste']) host['on' + type] = event => event.stopPropagation();
    host.style.cssText = 'margin:10px 0;padding:10px;border:1px solid #666;border-radius:6px;font-size:13px;overflow-wrap:anywhere';
    if (!host.childElementCount) host.textContent = '正在读取历史关联…';
    let links;
    try {links = await manifest();}
    catch (_) {
        delete host.dataset.loading;
        if (!host.isConnected) return;
        const focused = host.contains(document.activeElement);
        host.textContent = '历史关联暂不可读。';
        const retry = element('button', '重试', host); retry.type = 'button';
        retry.onclick = () => mountHistoricalLinks(host, source, {readOnly});
        if (focused) retry.focus();
        await mountAppliedLinks(host, source, readOnly);
        return;
    }
    delete host.dataset.loading;
    if (!host.isConnected) return;
    const groups = links.filter(group => group.records.some(record => record.kind === source.kind && record.id === source.id));
    const focused = host.contains(document.activeElement);
    const dialog = host.closest('[role="dialog"]');
    host.replaceChildren();
    if (!groups.length) {
        await mountAppliedLinks(host, source, readOnly);
        if (focused) dialog?.querySelector('button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled])')?.focus();
        return;
    }
    const details = element('details', null, host);
    const summary = element('summary', '历史关联记录', details);
    if (focused) summary.focus();
    element('p', '历史文本对应，不代表同一条记录。正文、描述和分类各自保留；这里只读查看。', details);
    const contents = element('div', null, details);
    let loading = false;
    const refresh = element('button', '重新读取关联', details); refresh.type = 'button';
    const render = async () => {
        if (loading || !host.isConnected) return;
        loading = true; refresh.setAttribute('aria-disabled', 'true'); contents.replaceChildren();
        contents.setAttribute('aria-busy', 'true');
        const reads = new Map();
        const read = record => {
            const key = record.kind + ':' + record.id;
            if (!reads.has(key)) reads.set(key, currentRecord(record).then(async value => ({...value, digest: await digest(value.text)})).catch(error => ({error})));
            return reads.get(key);
        };
        try {
            for (const group of groups) {
                const section = element('section', null, contents);
                element('h4', LABELS[group.relation] || '历史候选', section);
                const self = group.records.find(record => record.kind === source.kind && record.id === source.id);
                const state = element('p', '正在核对当前记录…', section);
                const origin = await read(self);
                if (!host.isConnected) return;
                state.textContent = origin.error ? (origin.error.status === 404 ? '当前记录已不存在，历史对应需要复核。' : '当前记录暂不可读，尚未核实。') : origin.digest !== self.body_digest ? '当前记录正文已变化，历史对应需要复核。' : '当前记录正文与历史核对时一致。';
                for (const record of group.records) {
                    if (record.kind === source.kind && record.id === source.id) continue;
                    const row = element('details', null, section);
                    row.dataset.kind = record.kind; row.dataset.recordId = record.id;
                    const heading = element('summary', (record.kind === 'tag' ? 'Tag' : '共享资料') + ' · 正在读取…', row);
                    const current = await read(record);
                    if (!host.isConnected) return;
                    if (current.error) {
                        heading.textContent = (record.kind === 'tag' ? 'Tag' : '共享资料') + (current.error.status === 404 ? ' · 记录已不存在' : ' · 暂不可读，请重新读取');
                        continue;
                    }
                    heading.textContent = (record.kind === 'tag' ? 'Tag' : '共享资料') + ' · ' + current.name + (current.category ? ' · ' + current.category : '');
                    element('p', current.digest === record.body_digest ? '正文与历史核对时一致。' : '正文已变化，历史对应需要复核。', row);
                    if (current.description) element('p', '描述：' + current.description, row);
                    if (current.notes) element('p', '备注：' + current.notes, row);
                    const body = element('pre', current.text, row);
                    body.style.cssText = 'white-space:pre-wrap;max-height:220px;overflow:auto;user-select:text;font:inherit';
                    body.tabIndex = 0; body.setAttribute('aria-label', '关联记录正文（只读）');
                }
            }
        } finally {loading = false; refresh.removeAttribute('aria-disabled'); contents.removeAttribute('aria-busy');}
    };
    details.addEventListener('toggle', () => {if (details.open) render();});
    refresh.onclick = render;
    await mountAppliedLinks(host, source, readOnly);
}

// Applied links are an explicit, additive relation between two stable identities.
// They never merge records, rewrite bodies or move categories.
async function mountAppliedLinks(host, source, readOnly) {
    const section = element('section', null, host);
    section.style.cssText = 'margin-top:10px;border-top:1px solid #555;padding-top:8px';
    element('h4', readOnly ? '关联记录（只读）' : '关联记录（可编辑）', section);
    element('p', '关联只记录稳定 ID 之间的对应：不合并记录、不改正文、不动分类。', section);
    const list = element('div', null, section);
    const status = element('p', '', section);
    status.setAttribute('role', 'status');
    const row = element('div', null, section);
    row.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;align-items:center';
    const input = readOnly ? null : element('input', null, row);
    if (input) input.placeholder = source.kind === 'tag' ? '共享资料 ID' : 'Tag UUID';
    const add = readOnly ? null : element('button', '建立关联', row);
    if (add) add.type = 'button';
    const refresh = element('button', '重新读取关联', row);
    refresh.type = 'button';
    const candidates = element('div', null, section);
    let revision = '';
    const query = source.kind === 'tag'
        ? 'tag_uuid=' + encodeURIComponent(String(source.id).replace(/^tag:/, ''))
        : 'resource_id=' + encodeURIComponent(source.id);
    const counterpartOf = link => (source.kind === 'tag' ? link.resource_id : link.tag_uuid);

    const save = async payload => {
        status.textContent = '正在保存关联…';
        const response = await fetch('/prompt_selector/tags/links', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'If-Match': revision},
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.error) {
            const error = new Error(data.error || `HTTP ${response.status}`);
            error.conflict = response.status === 409;
            throw error;
        }
        if (data.revision) revision = data.revision;
        return data;
    };

    const href = counterpart => (source.kind === 'tag'
        ? {tag_uuid: source.id, resource_id: counterpart}
        : {tag_uuid: counterpart, resource_id: source.id});

    const render = async () => {
        if (!host.isConnected) return;
        status.textContent = '正在读取关联…';
        let data;
        try {
            data = await readJSON('/prompt_selector/tags/links?' + query);
        } catch (error) {
            if (!host.isConnected) return;
            status.textContent = '关联暂不可读：' + error.message;
            return;
        }
        if (!host.isConnected) return;
        revision = data.revision || '';
        const applied = data.links || [];
        list.replaceChildren();
        if (!applied.length) element('p', '尚未建立关联。', list);
        const appliedIds = new Set(applied.map(counterpartOf));
        for (const link of applied) {
            const line = element('p', null, list);
            element('span', (source.kind === 'tag' ? '资料 ' : 'Tag ') + counterpartOf(link)
                + (link.relation && link.relation !== 'manual' ? ' · ' + (LABELS[link.relation] || link.relation) : '')
                + (link.note ? ' · ' + link.note : ''), line);
            if (readOnly) continue;
            const remove = element('button', '解除', line);
            remove.type = 'button';
            remove.onclick = async () => {
                remove.disabled = true;
                try { await save({action: 'unlink', link_id: link.link_id}); await render(); }
                catch (error) {
                    remove.disabled = false;
                    status.textContent = error.message;
                    if (error.conflict) await render();
                }
            };
        }
        candidates.replaceChildren();
        const pending = [];
        for (const group of data.candidates || []) {
            const rows = source.kind === 'tag' ? group.prompt_targets || [] : group.tag_sources || [];
            for (const record of rows) {
                const counterpart = source.kind === 'tag' ? record.resource_id : record.tag_uuid;
                if (!counterpart || appliedIds.has(counterpart)) continue;
                pending.push({counterpart, relation: group.relation || 'manual'});
            }
        }
        if (pending.length) {
            element('p', readOnly ? '历史候选（各自保留正文与分类）：' : '历史候选（可转为关联，各自保留正文与分类）：', candidates);
            for (const item of pending) {
                const line = element('p', null, candidates);
                element('span', (source.kind === 'tag' ? '资料 ' : 'Tag ') + item.counterpart
                    + ' · ' + (LABELS[item.relation] || item.relation), line);
                if (readOnly) continue;
                const link = element('button', '建立关联', line);
                link.type = 'button';
                link.onclick = async () => {
                    link.disabled = true;
                    try { await save({action: 'link', ...href(item.counterpart), relation: item.relation, source: 'candidate'}); await render(); }
                    catch (error) {
                        link.disabled = false;
                        status.textContent = error.message;
                        if (error.conflict) await render();
                    }
                };
            }
        }
        status.textContent = applied.length ? `已建立 ${applied.length} 条关联。` : '';
    };

    if (add) add.onclick = async () => {
        const value = input.value.trim();
        if (!value) { status.textContent = '请填写要关联的稳定 ID。'; return; }
        add.disabled = true;
        try {
            await save({action: 'link', ...href(value)});
            input.value = '';
            await render();
        } catch (error) {
            status.textContent = error.message;
            if (error.conflict) await render();
        } finally {
            add.disabled = false;
        }
    };
    refresh.onclick = render;
    await render();
}
