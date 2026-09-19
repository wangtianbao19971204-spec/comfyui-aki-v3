import {mountInsertionActions} from './prompt_target.js';
const ROOT_ID = 'unified-tag-manager';
const API = '/prompt_selector/tags';
let activeManager = null;

export function closeTagManager() {
    return activeManager ? activeManager.close(false) : true;
}

function element(tag, text, parent, attributes = {}) {
    const node = Object.assign(document.createElement(tag), attributes);
    if (text != null) node.textContent = text;
    parent?.appendChild(node);
    return node;
}

function installStyle() {
    if (document.getElementById('unified-tag-style')) return;
    const style = element('style', null, document.head, { id: 'unified-tag-style' });
    style.textContent = `#${ROOT_ID}{position:fixed;inset:5%;z-index:2147482310;background:#1d2028;color:#eee;border:1px solid #677185;border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:12px;font:14px system-ui;box-sizing:border-box}
    #${ROOT_ID}.mounted{position:relative;inset:auto;height:70vh;min-height:360px;z-index:auto}
    #${ROOT_ID} header,#${ROOT_ID} .ut-toolbar,#${ROOT_ID} footer{display:flex;gap:8px;align-items:center;flex-wrap:wrap;flex-shrink:0}
    #${ROOT_ID} h2{margin:0 auto 0 0;font-size:18px}#${ROOT_ID} input,#${ROOT_ID} select,#${ROOT_ID} textarea,#${ROOT_ID} button{font:inherit;color:inherit;background:#303540;border:1px solid #737b8d;border-radius:6px;padding:7px;box-sizing:border-box}
    #${ROOT_ID} button{cursor:pointer}#${ROOT_ID} button:disabled{opacity:.45;cursor:default}#${ROOT_ID} input[type=checkbox]{width:auto}
    #${ROOT_ID} .ut-search{min-width:180px;flex:1}#${ROOT_ID} .ut-list{min-height:0;overflow:auto;flex:1}
    #${ROOT_ID} .ut-cat-filter{min-width:130px;max-width:190px}#${ROOT_ID} .ut-cat-filter:focus{outline:2px solid #a78bfa;outline-offset:1px}
    #${ROOT_ID} .ut-row{display:flex;align-items:center;gap:8px;padding:9px 3px;border-bottom:1px solid #3e4552}#${ROOT_ID} .ut-body{min-width:0;flex:1;white-space:pre-wrap;overflow-wrap:anywhere}#${ROOT_ID} small{display:block;color:#b7bdca;margin-top:4px}
    #${ROOT_ID} .ut-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;align-content:start;padding:2px}
    #${ROOT_ID} .ut-card{border:1px solid #3e4552;border-radius:8px;background:#252a34;padding:8px;display:flex;flex-direction:column;gap:4px;min-width:0}
    #${ROOT_ID} .ut-card-img{width:100%;height:120px;object-fit:cover;border-radius:6px;background:#111;display:block}
    #${ROOT_ID} .ut-card-head{display:flex;align-items:center;gap:6px;min-width:0}
    #${ROOT_ID} .ut-card-head input{flex:0 0 auto;margin:0}
    #${ROOT_ID} .ut-card-desc{font-weight:600;color:#eceaf5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #${ROOT_ID} .ut-card-text{font-size:12px;color:#b9c0d0;overflow-wrap:anywhere;line-height:1.35}
    #${ROOT_ID} .ut-card-where{font-size:11px;color:#8b93a5;margin:0}
    #${ROOT_ID} .ut-card-actions{display:flex;flex-wrap:wrap;gap:4px;margin-top:auto;padding-top:2px}
    #${ROOT_ID} .ut-card-actions button,#${ROOT_ID} .ut-card-actions summary{padding:3px 6px;font-size:12px}
    #${ROOT_ID} .ut-card:hover{border-color:#8c54e6}
    #${ROOT_ID} .ut-string-link{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:6px 9px;border:1px solid #6d5aa8;border-radius:8px;background:#2b2740;font-size:13px;color:#ded7ff}
    #${ROOT_ID} .ut-string-link p{margin:0}#${ROOT_ID} .ut-string-link b{color:#fff}
    #${ROOT_ID} .ut-dialog{position:absolute;inset:0;background:#000b;z-index:2;display:flex;align-items:center;justify-content:center;padding:12px}
    #${ROOT_ID} .ut-form{background:#232833;border:1px solid #717e94;border-radius:10px;padding:16px;width:min(640px,100%);max-height:100%;overflow:auto;box-sizing:border-box;display:flex;flex-direction:column;gap:10px}
    #${ROOT_ID} .ut-form label{display:flex;flex-direction:column;gap:5px}#${ROOT_ID} .ut-form textarea{min-height:90px;resize:vertical}#${ROOT_ID} [role=status]{white-space:pre-wrap;color:#c8baf4}`;
}

export async function openTagManager(options = {}) {
    if (activeManager && !activeManager.root.isConnected) activeManager = null;
    if (activeManager) {
        if (!activeManager.close(false)) throw new Error('请先保存或关闭当前 Tag 编辑窗口。');
    }
    installStyle();
    const previousFocus = document.activeElement;
    const root = element('section', null, options.mount || document.body, { id: ROOT_ID });
    root.setAttribute('role', 'dialog'); root.setAttribute('aria-label', '共享 Tag 管理');
    const hidden = options.mount ? Array.from(options.mount.children).filter(node => node !== root).map(node => [node, node.style.display]) : [];
    for (const [node] of hidden) node.style.display = 'none';
    if (options.mount) root.classList.add('mounted');
    const header = element('header', null, root);
    element('h2', '共享 Tag 管理', header);
    const closeButton = element('button', '关闭', header, { type: 'button' });
    const filters = element('div', null, root, { className: 'ut-toolbar' });
    const search = element('input', null, filters, { placeholder: '搜索 Tag 或描述', className: 'ut-search', value: options.query || '' });
    search.setAttribute('aria-label', '搜索 Tag 或描述');
    const group = element('select', null, filters); group.setAttribute('aria-label', '主分类');
    let groupFilterText = options.state?.catFilter || '';
    const groupFilter = element('input', null, filters, { placeholder: '筛选主分类', className: 'ut-cat-filter', value: groupFilterText });
    groupFilter.setAttribute('aria-label', '筛选主分类');
    const subgroup = element('select', null, filters); subgroup.setAttribute('aria-label', '子分类');
    let subgroupFilterText = options.state?.subFilter || '';
    const subgroupFilter = element('input', null, filters, { placeholder: '筛选子分类', className: 'ut-cat-filter', value: subgroupFilterText });
    subgroupFilter.setAttribute('aria-label', '筛选子分类');
    let shapeValue = options.state?.shape || '';
    const shape = element('select', null, filters); shape.setAttribute('aria-label', '正文形状');
    for (const [value, label] of [['', '全部形状'], ['atomic', '基础 tag（单个）'], ['group', '两三个词'], ['string', '标签串（属提示词片段）']]) {
        element('option', label, shape, { value });
    }
    shape.value = shapeValue;
    let cardView = options.state?.cardView !== false;
    const viewToggle = element('button', cardView ? '切换为列表' : '切换为卡片', filters);
    viewToggle.setAttribute('aria-label', '切换 Tag 显示方式');
    const collectionFilter = element('select', null, filters); collectionFilter.setAttribute('aria-label', '共享分组');
    const favoritesLabel = element('label', null, filters);
    const onlyFavorites = element('input', null, favoritesLabel, { type: 'checkbox', checked: options.favorites === true });
    favoritesLabel.appendChild(document.createTextNode('只看收藏'));
    const toolbar = element('div', null, root, { className: 'ut-toolbar' });
    // 「标签 tags 串」里的分组大多在「提示词片段」已经有同名分类（逐 token 比对约一半条目
    // 两边完全一致），这里直接给一个回到那里的入口，桶里就不再是"另造一份"。
    const stringLinkBar = element('div', null, root, { className: 'ut-string-link' });
    stringLinkBar.style.display = 'none';
    const stringLinkText = element('p', '', stringLinkBar);
    const stringLinkButton = element('button', '在提示词片段打开', stringLinkBar, { type: 'button' });
    const bulkToolbar = element('div', null, root, { className: 'ut-toolbar' });
    bulkToolbar.setAttribute('aria-label', '所选 Tag 批量操作'); bulkToolbar.style.display = 'none';
    const list = element('div', null, root, { className: 'ut-list' });
    const status = element('div', '', root); status.setAttribute('role', 'status');
    const insertionHost = element('div', null, root, {className:'ut-toolbar'});
    let insertionControls;
    const footer = element('footer', null, root);
    const previous = element('button', '上一页', footer);
    const pageLabel = element('span', '', footer);
    const next = element('button', '下一页', footer);
    let revision = '', collectionRevision = '', groups = [], collections = [], rows = [], offset = 0, requestNumber = 0, editorOpen = false, closed = false, timer = null, dismissEditor = null, stringGroupUuid = '', stringMoved = null;
    const visible = item => item.getClientRects().length && (!item.closest('details:not([open])') || item.matches('summary'));
    const focusable = scope => [...scope.querySelectorAll('button,input,select,textarea,a[href],summary,[tabindex],[contenteditable=true]')].filter(item => !item.disabled && item.tabIndex >= 0 && visible(item));
    const restoreFocus = (target, fallback = search) => {
        if (target?.isConnected && !target.disabled && visible(target)) target.focus();
        else if (fallback?.isConnected) fallback.focus();
    };
    const selected = new Set();
    const close = (notify = true) => {
        if (closed) return true;
        if (editorOpen) { status.textContent = '请先保存或关闭当前编辑窗口。'; return false; }
        if (options.state) Object.assign(options.state, {query:search.value, group:group.value, subgroup:subgroup.value, collection:collectionFilter.value, favorites:onlyFavorites.checked, offset, selected:[...selected], scroll:list.scrollTop, catFilter:groupFilterText, subFilter:subgroupFilterText, shape:shapeValue, cardView});
        closed = true; options.onInsert?.dispose?.(); clearTimeout(timer); requestNumber++; root.remove();
        for (const [node, display] of hidden) node.style.display = display;
        if (activeManager?.root === root) activeManager = null;
        if (notify) options.onClose?.();
        restoreFocus(previousFocus, null);
        return true;
    };
    activeManager = { root, close }; closeButton.onclick = () => close();
    for (const type of ['copy', 'cut', 'paste']) root.addEventListener(type, event => {
        if (event.target.closest('input,textarea,[contenteditable=true]')) event.stopPropagation();
    });
    root.addEventListener('keydown', event => {
        event.stopPropagation();
        if (event.defaultPrevented || event.isComposing) return;
        const editor = root.querySelector('.ut-dialog');
        if (event.key === 'Tab' && (editor || !options.mount)) {
            const items = focusable(editor || root), first = items[0], last = items.at(-1);
            if (!items.length) { event.preventDefault(); return; }
            if (event.shiftKey && document.activeElement === first || !event.shiftKey && document.activeElement === last) {
                event.preventDefault(); (event.shiftKey ? last : first).focus();
            }
        }
        if (event.key !== 'Escape' || event.target.closest('input,textarea,select,[contenteditable=true]')) return;
        event.preventDefault();
        const details = event.target.closest('details[open]');
        if (details) { details.open = false; details.querySelector('summary')?.focus(); return; }
        if (editor) dismissEditor?.(); else close();
    });
    search.focus();
    const get = async (path) => {
        const response = await fetch(API + path, { cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    };
    const write = async (payload, expected = revision, expectedCollection = collectionRevision) => {
        const response = await fetch(API + '/update', { method: 'POST', headers: { 'Content-Type': 'application/json', 'If-Match': expected }, body: JSON.stringify({...payload, collection_revision:expectedCollection}) });
        const result = await response.json();
        if (!response.ok) { const error = new Error(result.error || `HTTP ${response.status}`); error.conflict = response.status === 409; throw error; }
        revision = result.revision;
        window.dispatchEvent(new CustomEvent('unified-tags-updated', { detail: { revision } }));
        return result;
    };
    const report = error => { status.textContent = error.message; };
    const categories = async () => {
        const data = await get('/index');
        groups = data.groups; revision = data.revision; collections = data.collections || []; collectionRevision = data.collection_revision || '';
        stringGroupUuid = data.string_group || '';
        stringMoved = data.string_moved && !data.string_moved.visible ? data.string_moved : null;
        const currentCollection = collectionFilter.value || options.collectionId || '';
        options.collectionId = '';
        collectionFilter.replaceChildren(); element('option', '全部分组', collectionFilter, { value:'' });
        for (const item of collections) element('option', item.name, collectionFilter, { value:item.id });
        collectionFilter.value = collections.some(item => item.id === currentCollection) ? currentCollection : '';
        const previousGroup = group.value, previousSubgroup = subgroup.value;
        renderGroups(previousGroup);
        renderSubgroups(previousSubgroup);
        renderStringLink();
    };
    // 66 areas and 859 leaves do not fit a native dropdown; each select gets a filter
    // box that only trims the option list, so the select itself stays keyboard-driven.
    const renderGroups = value => {
        const needle = groupFilterText.trim().toLowerCase();
        group.replaceChildren(); element('option', '全部主分类', group, { value: '' });
        let shown = 0;
        for (const row of groups) {
            if (needle && !String(row.name || '').toLowerCase().includes(needle)) continue;
            element('option', row.name, group, { value: row.p_uuid });
            shown += 1;
        }
        group.dataset.filtered = needle ? `匹配 ${shown} / ${groups.length} 个主分类` : '';
        group.title = group.dataset.filtered;
        group.value = [...group.options].some(option => option.value === value) ? value : '';
        return shown;
    };
    const renderSubgroups = value => {
        const needle = subgroupFilterText.trim().toLowerCase();
        subgroup.replaceChildren(); element('option', '全部子分类', subgroup, { value: '' });
        let shown = 0, total = 0;
        for (const parent of groups.filter(item => !group.value || item.p_uuid === group.value)) {
            for (const row of parent.groups) {
                total += 1;
                // 桶里的条目本身已带「区域 / 子夹」路径，不再重复父分类名。
                const prefix = parent.p_uuid === stringGroupUuid ? '' : `${parent.name} / `;
                const label = `${prefix}${row.name} (${row.count})`;
                if (needle && !label.toLowerCase().includes(needle)) continue;
                element('option', label, subgroup, { value: row.g_uuid });
                shown += 1;
            }
        }
        subgroup.dataset.filtered = needle ? `匹配 ${shown} / ${total} 个子分类` : '';
        subgroup.title = subgroup.dataset.filtered;
        subgroup.value = [...subgroup.options].some(option => option.value === value) ? (value || '') : '';
    };
    const stringLinkFor = () => {
        if (!stringGroupUuid || group.value !== stringGroupUuid) return null;
        const parent = groups.find(item => item.p_uuid === stringGroupUuid);
        const rows = parent?.groups || [];
        const picked = rows.find(item => item.g_uuid === subgroup.value);
        if (picked) return picked.library || null;
        const matched = rows.filter(item => item.library);
        if (!matched.length) return null;
        return {area: '', categories: matched.reduce((sum, item) => sum + item.library.categories, 0),
                count: matched.reduce((sum, item) => sum + item.library.count, 0),
                category_id: matched[0].library.category_id, category_name: matched[0].library.category_name,
                summary: matched.length};
    };
    const renderStringLink = () => {
        const link = stringLinkFor();
        if (!link && stringMoved) {
            // 串已经并入「提示词片段」，tag 侧不再单列桶，只提示一句去哪儿找。
            stringLinkBar.style.display = 'flex';
            stringLinkText.replaceChildren(document.createTextNode(
                `共 ${stringMoved.rows.toLocaleString()} 条 tags 串已按法典原分组并入「提示词片段」（${stringMoved.groups} 个分组），这里只列基础 tag。`));
            stringLinkButton.onclick = async () => {
                const opener = window.weilinOpenSharedPresets || window.tbOpenSharedPresetManager;
                if (typeof opener !== 'function') { status.textContent = '提示词片段入口尚未加载，请稍后重试。'; return; }
                try { await opener({view: 'all'}); } catch (error) { report(error); }
            };
            return;
        }
        stringLinkBar.style.display = link ? 'flex' : 'none';
        if (!link) return;
        stringLinkText.replaceChildren(document.createTextNode(link.summary
            ? `桶里有 ${link.summary} 个分组在「提示词片段」已有同名分类（共 ${link.count} 条），选中一个即可跳过去`
            : link.categories > 1
              ? `「${link.area}」在「提示词片段」有 ${link.categories} 个同名分类（${link.count} 条）`
              : `「${link.category_name}」在「提示词片段」里已有（${link.count} 条）`));
        stringLinkButton.onclick = async () => {
            const opener = window.weilinOpenSharedPresets || window.tbOpenSharedPresetManager;
            if (typeof opener !== 'function') { status.textContent = '提示词片段入口尚未加载，请稍后重试。'; return; }
            try { await opener({view: 'all', categoryId: link.category_id, sourceFilter: link.area || ''}); }
            catch (error) { report(error); }
        };
    };
    const load = async () => {
        const sequence = ++requestNumber;
        status.textContent = '正在读取…';
        list.classList.toggle('ut-cards', cardView);
        // 基础 Tag 看的是「法典分组分流」的结果：整组判成标签串的分组被搬到旁边的
        // 「标签 tags 串」里，所以除它以外的视图都只读基础 tag 那一侧。
        const scope = stringGroupUuid && group.value === stringGroupUuid ? 'strings' : 'tags';
        const query = new URLSearchParams({ q: search.value, group: group.value, subgroup: subgroup.value, collection:collectionFilter.value, offset, limit: cardView ? 120 : 100, favorite: onlyFavorites.checked, shape: shape.value, scope });
        const data = await get('/page?' + query);
        if (closed || sequence !== requestNumber) return;
        revision = data.revision; rows = data.items;
        const previousScroll = list.scrollTop;
        list.replaceChildren();
        for (const item of rows) {
            const row = element('div', null, list, { className: cardView ? 'ut-card' : 'ut-row' });
            row.dataset.resourceId = item.resource_id;
            // 有预览图（官方法典图鉴继承来的，或自己绑定的）就在卡片上方显示缩略图。
            if (cardView && item.preview) {
                element('img', null, row, {
                    className: 'ut-card-img', loading: 'lazy', decoding: 'async', alt: '',
                    src: '/prompt_selector/thumbnail/' + encodeURIComponent(item.preview),
                });
            }
            const host = cardView ? element('div', null, row, { className: 'ut-card-head' }) : row;
            const check = element('input', null, host, { type: 'checkbox', checked: selected.has(item.resource_id) });
            check.setAttribute('aria-label', '选择 ' + item.text);
            check.onchange = () => { check.checked ? selected.add(item.resource_id) : selected.delete(item.resource_id); updateCount(); };
            if (cardView) {
                element('span', item.desc || '（无中文）', host, { className: 'ut-card-desc' });
                element('div', item.text, row, { className: 'ut-card-text' });
                if (item.group_name || item.subgroup_name) {
                    element('small', `${item.group_name || ''} / ${item.subgroup_name || ''}`, row, { className: 'ut-card-where' });
                }
            } else {
                const body = element('div', null, row, { className: 'ut-body' });
                element('div', item.text, body);
                element('small', item.desc || '', body);
                element('small', `${item.group_name || ''} / ${item.subgroup_name || ''}`, body);
            }
            const actionHost = cardView ? element('div', null, row, { className: 'ut-card-actions' }) : row;
            const favorite = element('button', item.favorite ? '已收藏' : '收藏', actionHost);
            favorite.onclick = async () => { favorite.disabled = true; try { await write({ operation: 'metadata', resource_id: item.resource_id, favorite: !item.favorite }); await load(); } catch (error) { report(error); favorite.disabled = false; } };
            const apply = element('button', options.onInsert ? '插入' : '查看详情', actionHost);
            apply.onclick = () => options.onInsert ? inject([item.resource_id]) : editTag(item, true).catch(report);
            const more = element('details', null, actionHost, {className:'ut-more'}); element('summary', '更多', more);
            element('button', '编辑', more).onclick = () => editTag(item).catch(report);
            quickCollections(more, item);
            if (window.unifiedQueuePrompt) element('button', '加入待用列表', more).onclick = () => window.unifiedQueuePrompt({provider:'tag',id:item.resource_id,title:item.text,text:item.text,usage:'target'});
        }
        list.scrollTop = previousScroll;
        previous.disabled = offset === 0; next.disabled = offset + rows.length >= data.total;
        pageLabel.textContent = `${data.total ? offset + 1 : 0}–${offset + rows.length} / ${data.total}`;
        updateCount();
        if (shape.value === 'string') status.textContent = '这些是所长法典里的 tags 串（多词组合），平时用它们时更适合到「提示词片段」里找；这里保留原始分类便于核对。';
        if (scope === 'strings') status.textContent = '这些是从各分组里摘出来的 tags 串：单行正文达到 5 个词，或所在分组里串行占比超过 25%（整组迁移）。下面如果有跳转条，就是它已经在「提示词片段」里的对应分类。';
    };
    const updateCount = () => { bulkToolbar.style.display = selected.size ? 'flex' : 'none'; status.textContent = `已选 ${selected.size} 条（可能跨页），批量操作仅作用于已选项，不包含全部搜索结果。与 WeiLin 原 Tag 库共用正文和分类。`; };
    const reset = () => { offset = 0; selected.clear(); load().catch(report); };
    group.onchange = () => { renderSubgroups(); renderStringLink(); reset(); };
    subgroup.onchange = () => { renderStringLink(); reset(); };
    onlyFavorites.onchange = reset;
    collectionFilter.onchange = reset;
    shape.onchange = () => { shapeValue = shape.value; reset(); };
    viewToggle.onclick = () => {
        cardView = !cardView;
        viewToggle.textContent = cardView ? '切换为列表' : '切换为卡片';
        list.classList.toggle('ut-cards', cardView);
        reset();
    };
    groupFilter.oninput = () => {
        groupFilterText = groupFilter.value;
        const previous = group.value;
        renderGroups(previous);
        renderSubgroups(subgroup.value);
        if (group.value !== previous) reset();
    };
    subgroupFilter.oninput = () => {
        subgroupFilterText = subgroupFilter.value;
        renderSubgroups(subgroup.value);
    };
    search.oninput = () => { clearTimeout(timer); timer = setTimeout(reset, 250); };
    previous.onclick = () => { offset = Math.max(0, offset - 100); load().catch(report); };
    next.onclick = () => { offset += 100; load().catch(report); };
    const action = (name, callback) => { const parent = ['清空选择', '删除所选', '导出所选', '批量收藏', '取消收藏', '批量备注'].includes(name) ? bulkToolbar : toolbar; const button = element('button', name, parent); button.onclick = () => Promise.resolve().then(callback).catch(report); return button; };
    const inject = async identities => {
        try {
            if (!options.onInsert) throw new Error('请从目标提示词输入框打开 Tag 管理后插入。');
            if (!identities.length) throw new Error('请先选择 Tag。');
            const latest = await Promise.all(identities.map(id => get('/item?id=' + encodeURIComponent(id))));
            const text=latest.map(result => result.item.text).join(', ');
            const result = await (options.onInsert.reviewInsert||options.onInsert)({text,action:insertionControls?.picker.value||'append_end',validatePreview:async()=>{const fresh=await Promise.all(identities.map(id=>get('/item?id='+encodeURIComponent(id))));if(fresh.map(result=>result.item.text).join(', ')!==text)throw new Error('词条已更新，请取消后重新选择。');}});
            if(result?.status==='cancelled')return;
            if (result?.status && !['inserted', 'unchanged'].includes(result.status)) throw new Error('目标已失效，请从当前提示词重新打开。');
            if (insertionControls) insertionControls.undo.disabled = !options.onInsert.undoLast || result?.status !== 'inserted';
            status.textContent = `已插入 ${latest.length} 条 Tag。`;
        } catch (error) { report(error); }
    };
    const modal = title => {
        if (editorOpen) throw new Error('请先关闭当前编辑窗口。');
        editorOpen = true;
        const returnFocus = document.activeElement;
        const overlay = element('div', null, root, { className: 'ut-dialog' });
        const form = element('div', null, overlay, { className: 'ut-form' });
        form.setAttribute('role', 'dialog'); form.setAttribute('aria-label', title);
        element('h2', title, form);
        const error = element('div', '', form); error.setAttribute('role', 'status');
        const fields = element('div', null, form);
        const buttons = element('footer', null, form);
        const cancel = element('button', '取消', buttons), reload = element('button', '读取最新版本', buttons), save = element('button', '保存', buttons);
        reload.hidden = true;
        let saving = false, baseRevision = revision, baseCollectionRevision = collectionRevision;
        const dismiss = () => { if (saving) return; overlay.remove(); editorOpen = false; dismissEditor = null; restoreFocus(returnFocus); };
        dismissEditor = dismiss;
        cancel.onclick = dismiss;
        queueMicrotask(() => { if (overlay.isConnected) focusable(form)[0]?.focus(); });
        const field = (label, tag = 'input', value = '') => {
            const wrapper = element('label', label, fields);
            return element(tag, null, wrapper, { value });
        };
        reload.onclick = async () => {
            reload.disabled = true;
            try { await categories(); baseRevision = revision; baseCollectionRevision = collectionRevision; reload.hidden = true; save.disabled = false; error.textContent = '版本已更新，输入已保留，请核对后保存。'; }
            catch (failure) { error.textContent = failure.message; }
            finally { reload.disabled = false; }
        };
        const submit = callback => { save.onclick = async () => {
            if (saving) return; saving = true; save.disabled = true; cancel.disabled = true;
            try { const payload = callback(); await write(payload, baseRevision, baseCollectionRevision); if (payload.operation === 'batch') selected.clear(); saving = false; dismiss(); await categories(); await load(); if (document.activeElement === document.body) search.focus(); }
            catch (failure) { error.textContent = failure.message; reload.hidden = !failure.conflict; }
            finally { saving = false; save.disabled = !reload.hidden; cancel.disabled = false; }
        }; };
        return { field, submit, buttons, error, fields, form, save, cancel, dismiss, setBusy: value => { saving = value === true; } };
    };
    const categoryOptions = (select, selectedId = '') => {
        for (const parent of groups) for (const item of parent.groups) element('option', `${parent.name} / ${item.name}`, select, { value: item.g_uuid });
        if (selectedId) select.value = selectedId;
    };
    const collectionChoices = (field, groups, selectedIds) => {
        const choices=[...groups,...selectedIds.filter(id=>!groups.some(group=>group.id===id)).map(id=>({id,name:'已删除的组（取消勾选后可保存）'}))];
        return choices.map(group=>{const checkbox=field('分组：'+group.name);checkbox.type='checkbox';checkbox.checked=selectedIds.includes(group.id);checkbox.dataset.collectionId=group.id;return [group.id,checkbox];});
    };
    const quickCollections = (more, item) => {
        const section=element('section',null,more,{className:'ut-quick-collections'});
        const choices=element('div',null,section);choices.style.cssText='max-height:180px;overflow:auto';
        const message=element('p','',section);message.setAttribute('role','status');
        const save=element('button','保存分组',section),reload=element('button','重新读取分组',section);save.disabled=true;
        let snapshot=null,membership=[],selection=null,reading=false,saving=false;
        const read=async()=>{
            if(reading||saving)return;reading=true;save.disabled=true;reload.disabled=true;message.textContent='正在读取分组…';
            if(snapshot)selection=membership.filter(([,checkbox])=>checkbox.checked).map(([id])=>id);
            try{
                const latest=await get('/item?id='+encodeURIComponent(item.resource_id));if(!section.isConnected)return;
                snapshot=latest;selection=selection||[...(latest.item.collection_ids||[])];choices.replaceChildren();
                membership=collectionChoices(label=>{const row=element('label',label,choices);row.style.display='block';return element('input',null,row);},latest.collections||[],selection);message.textContent='';
            }catch(error){if(section.isConnected)message.textContent=error.message;}
            finally{reading=false;if(section.isConnected){save.disabled=!snapshot;reload.disabled=false;}}
        };
        more.addEventListener('toggle',()=>{if(more.open&&!snapshot)void read();});reload.onclick=read;
        save.onclick=async()=>{
            if(saving||reading||!snapshot||!section.isConnected)return;
            if(editorOpen){message.textContent='请先保存或关闭当前编辑。';return;}
            saving=true;save.disabled=true;reload.disabled=true;membership.forEach(([,checkbox])=>{checkbox.disabled=true;});message.textContent='正在保存分组…';
            try{
                await write({operation:'metadata',resource_id:item.resource_id,collection_ids:membership.filter(([,checkbox])=>checkbox.checked).map(([id])=>id)},snapshot.revision,snapshot.collection_revision);
                if(!section.isConnected)return;const scroll=list.scrollTop;await load();list.scrollTop=scroll;
                const summary=[...list.querySelectorAll('.ut-row')].find(row=>row.dataset.resourceId===item.resource_id)?.querySelector('.ut-more > summary');summary?.focus({preventScroll:true});
            }catch(error){if(section.isConnected)message.textContent=error.message;}
            finally{saving=false;if(section.isConnected){save.disabled=false;reload.disabled=false;membership.forEach(([,checkbox])=>{checkbox.disabled=false;});}}
        };
    };
    const editTag = async (item, readOnly = false) => {
        if (item) { const data = await get('/item?id=' + encodeURIComponent(item.resource_id)); item = data.item; revision = data.revision; collections = data.collections || collections; collectionRevision = data.collection_revision || collectionRevision; }
        const dialog = modal(item ? '编辑共享 Tag' : '新建共享 Tag');
        const text = dialog.field('Tag 正文', 'textarea', item?.text || '');
        const description = dialog.field('描述', 'textarea', item?.desc || '');
        const category = dialog.field('分类', 'select'); categoryOptions(category, item?.g_uuid || subgroup.value);
        const color = dialog.field('颜色', 'input', item?.color || '');
        const notes = dialog.field('备注', 'textarea', item?.notes || '');
        const favorite = dialog.field('收藏此 Tag'); favorite.type = 'checkbox'; favorite.checked = item?.favorite === true;
        const membership = collectionChoices(dialog.field, collections, item?.collection_ids || []);
        if (item) {
            const links = element('div', null, dialog.fields);
            const loadLinks = () => import('./historical_links.js').then(module => {
                if (links.isConnected) return module.mountHistoricalLinks(links, {kind:'tag', id:item.resource_id});
            }).catch(() => {
                if (!links.isConnected) return;
                links.textContent = '历史关联暂不可读。';
                const retry = element('button', '重试', links, {type:'button'}); retry.onclick = loadLinks;
            });
            loadLinks();
        }
        const identity = item?.resource_id || 'tag:' + crypto.randomUUID();
        dialog.submit(() => ({ operation: item ? 'edit' : 'create', resource_id: identity, text: text.value, desc: description.value, g_uuid: category.value, color: color.value, notes: notes.value,
            favorite:favorite.checked, collection_ids:membership.filter(([,checkbox])=>checkbox.checked).map(([id])=>id) }));
        if (readOnly) {
            dialog.form.querySelector('h2').textContent = 'Tag 详情'; dialog.cancel.textContent = '返回列表';
            dialog.form.setAttribute('aria-label', 'Tag 详情');
            dialog.fields.querySelectorAll('input,textarea,select').forEach(field => {field.disabled = true;});
            const submit = dialog.save.onclick; dialog.save.textContent = '编辑共享 Tag';
            dialog.save.onclick = () => {dialog.fields.querySelectorAll('input,textarea,select').forEach(field => {field.disabled = false;}); dialog.form.querySelector('h2').textContent = '编辑共享 Tag'; dialog.form.setAttribute('aria-label', '编辑共享 Tag'); dialog.save.textContent = '保存'; dialog.save.onclick = submit; text.focus();};
        }
    };
    const editCategory = (entity, create = false) => {
        const key = entity === 'group' ? 'p_uuid' : 'g_uuid';
        const identity = create ? '' : entity === 'group' ? group.value : subgroup.value;
        const row = entity === 'group' ? groups.find(item => item.p_uuid === identity) : groups.flatMap(item => item.groups).find(item => item.g_uuid === identity);
        const dialog = modal(row ? '编辑 Tag 分类' : '新建 Tag 分类');
        const name = dialog.field('分类名称', 'input', row?.name || '');
        const color = dialog.field('颜色', 'input', row?.color || '');
        const parent = entity === 'subgroup' ? dialog.field('主分类', 'select') : null;
        if (parent) { for (const item of groups) element('option', item.name, parent, { value: item.p_uuid }); parent.value = row?.p_uuid || group.value || groups[0]?.p_uuid || ''; }
        const newId = identity || crypto.randomUUID();
        dialog.submit(() => ({ entity, operation: row ? 'edit' : 'create', [key]: newId, name: name.value, color: color.value, ...(parent ? { p_uuid: parent.value } : {}) }));
    };
    action('新建 Tag', () => editTag());
    action('管理分组', async () => {
        if (typeof window.weilinOpenSharedPresets !== 'function') throw new Error('共享分组管理尚未加载，请稍后重试。');
        const returnFocus = document.activeElement;
        editorOpen = true; const display = root.style.display; root.style.display = 'none';
        const restore = async () => { editorOpen = false; root.style.display = display; restoreFocus(returnFocus); try { await categories(); await load(); } catch (error) { report(error); } };
        try { await window.weilinOpenSharedPresets({collectionsOnly:true,selectorKind:'tag',onClose:restore}); }
        catch (error) { await restore(); throw error; }
    });
    action('新建主分类', () => editCategory('group', true));
    action('新建子分类', () => editCategory('subgroup', true));
    action('编辑当前分类', () => { if (!group.value && !subgroup.value) throw new Error('请先选择分类。'); editCategory(subgroup.value ? 'subgroup' : 'group'); });
    action('删除空分类', () => {
        if (!group.value && !subgroup.value) throw new Error('请先选择分类。');
        const entity = subgroup.value ? 'subgroup' : 'group', key = subgroup.value ? 'g_uuid' : 'p_uuid';
        const identity = subgroup.value || group.value;
        const dialog = modal('删除空分类');
        dialog.error.textContent = '仅删除空分类；有成员时请先移动成员。';
        dialog.submit(() => ({ entity, operation: 'delete', [key]: identity }));
    });
    action('选中本页', () => { for (const item of rows) selected.add(item.resource_id); load().catch(report); });
    action('清空选择', () => { selected.clear(); load().catch(report); });
const BATCH_STORAGE_KEY = 'weilin-tag-batch-recovery';
const BATCH_TERMINALS = new Set(['committed', 'cancelled', 'not_committed', 'unknown']);
const BATCH_KNOWN_TERMINALS = new Set(['committed', 'cancelled', 'not_committed']);
const batchStorage = {
    read() {
        try {
            const value = sessionStorage.getItem(BATCH_STORAGE_KEY);
            return value ? JSON.parse(value) : null;
        } catch (error) {
            return null;
        }
    },
    write(value) {
        try {
            sessionStorage.setItem(BATCH_STORAGE_KEY, JSON.stringify(value));
            return true;
        } catch (error) {
            return false;
        }
    },
    clear(token) {
        if (!token) return false;
        try {
            const stored = sessionStorage.getItem(BATCH_STORAGE_KEY);
            if (!stored) return false;
            const value = JSON.parse(stored);
            if (value?.token !== token) return false;
            sessionStorage.removeItem(BATCH_STORAGE_KEY);
            return true;
        } catch (error) {
            return false;
        }
    }
};
const batchToken = () => {
    try { return crypto.randomUUID(); }
    catch (error) { return `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
};
const batchOperationText = () => '删除';
const batchTerminalText = status => ({
    queued: '等待执行',
    running: '处理中，尚未提交',
    committing: '正在提交',
    cancellation_pending: '正在确认取消结果',
    committed: '已完成',
    cancelled: '已取消，未写入',
    not_committed: '未提交，未写入',
    unknown: '结果未知，请恢复任务确认'
}[status] || status || '待核对');
const batchFetch = async (path, init = {}) => {
    const response = await fetch(API + path, { cache: 'no-store', ...init });
    let data = null;
    try { data = await response.json(); } catch (error) {}
    if (!response.ok) {
        const error = new Error(data?.error || (response.status === 404 ? '批量任务不存在；服务可能已重启。' : `请求失败（${response.status}）`));
        error.httpStatus = response.status;
        error.data = data;
        error.bodyKnown = data !== null;
        throw error;
    }
    return data;
};

const openBatchDialog = (recovery = null) => {
    let operation = 'delete';
    if (editorOpen) throw new Error('请先关闭当前编辑窗口。');
    const dialog = modal('批量删除');
    const confirm = dialog.field('再次确认删除所选 Tag');
    if (confirm) { confirm.type = 'checkbox'; confirm.checked = false; }
    const scope = element('div', '', dialog.fields, { role: 'status' });
    const recoveryLabel = element('div', recovery?.token ? `恢复编号：${recovery.token}` : '', dialog.fields);
    const progress = element('div', '', dialog.fields, { role: 'status' });
    const result = element('div', '', dialog.fields, { role: 'status' });
    const retryBox = element('div', null, dialog.fields);
    const recoverButton = element('button', '重新查询状态', dialog.buttons, { type: 'button' });
    const exportButton = element('button', '导出操作结果', dialog.buttons, { type: 'button' });
    const exportFailed = element('button', '导出失败 ID', dialog.buttons, { type: 'button' });
    const retryButton = element('button', '读取最新版本后重试', dialog.buttons, { type: 'button' });
    const finish = element('button', '完成并返回列表', dialog.buttons, { type: 'button' });
    result.hidden = true; retryBox.hidden = true; recoverButton.hidden = true; exportButton.hidden = true; exportFailed.hidden = true; retryButton.hidden = true; finish.hidden = true;

    let state = recovery ? 'recovery_needed' : 'configuring';
    let generation = 0;
    let timer = null;
    let pollPromise = null;
    let currentJob = null;
    let currentExport = null;
    let currentRequest = null;
    let originalIds = recovery ? null : [...selected];
    let finishing = false, retryLoading = false, cancelSent = false;
    confirm.parentElement.style.display = 'flex';
    let retryIds = [];
    let retryMode = false;
    let cancelIntent = false;
    let requestDispatched = false;
    let cancellationInFlight = false;
    let exportInFlight = false;
    let persistWarning = false;
    let lastKnownResult = null;

    const live = token => token === generation && dialog.form.isConnected;
    const active = () => ['start_pending', 'monitoring'].includes(state);
    const setBusy = value => {
        dialog.setBusy(value);
        if (confirm) confirm.disabled = value;
        retryBox.querySelectorAll('input').forEach(input => { input.disabled = value; });
        dialog.save.disabled = value || state !== 'configuring' && !retryMode;
        if (active()) dialog.cancel.disabled = cancellationInFlight;
    };
    const describe = job => {
        const terminal = BATCH_TERMINALS.has(job?.status);
        const committed = terminal && job.committed != null ? job.committed : (terminal ? '待核对' : '待核对');
        const uncommitted = terminal && job.uncommitted != null ? job.uncommitted : (terminal ? '待核对' : '待核对');
        return `状态：${batchTerminalText(job?.status)}\n进度：${job?.processed ?? '待核对'} / ${job?.total ?? '待核对'}\n已提交：${committed}\n未提交：${uncommitted}`;
    };
    const saveRecovery = request => {
        const ok = batchStorage.write({ token: request.token, operation: request.operation, expected_tag_revision: request.expected_tag_revision, expected_collection_revision: request.expected_collection_revision });
        recoveryLabel.textContent = `恢复编号：${request.token}${ok ? '' : '（浏览器无法保存，请保留此编号）'}`;
        if (!ok) {
            persistWarning = true;
            dialog.error.textContent = `无法写入会话恢复令牌。请保持此窗口打开；令牌：${request.token}`;
        }
    };
    const download = (data, name) => {
        if (!dialog.form.isConnected) return;
        const url = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }));
        const link = element('a', '', dialog.form, { href: url, download: name });
        link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 0);
    };
    const readExport = async (token, kind = '') => batchFetch('/batch/export?token=' + encodeURIComponent(token) + (kind ? '&kind=' + encodeURIComponent(kind) : ''));
    const renderRetry = () => {
        retryBox.replaceChildren(); retryBox.hidden = false;
        element('div', '默认勾选全部未提交 Tag；请明确取消勾选不应重试的 ID。', retryBox);
        for (const id of retryIds) {
            const label = element('label', null, retryBox); label.style.display = 'block';
            const checkbox = element('input', null, label, { type: 'checkbox', checked: true });
            checkbox.dataset.resourceId = id;
            label.appendChild(document.createTextNode(` ${id}`));
        }
    };
    const clearTimer = () => { if (timer) { clearTimeout(timer); timer = null; } };
    const stopPolling = () => { clearTimer(); pollPromise = null; };
    const showTerminal = async (job, token, mine) => {
        if (!live(mine)) return;
        state = 'terminal'; currentJob = job; lastKnownResult = job; stopPolling();
        try {
            const exported = await readExport(token);
            if (!live(mine)) return;
            currentExport = exported;
            originalIds = exported?.request?.resource_ids ? [...exported.request.resource_ids] : originalIds;
        } catch (error) {
            if (!live(mine)) return;
            dialog.error.textContent = `任务已结束，但结果详情暂不可读取：${error.message}。可稍后重新导出或恢复。`;
        }
        if (!live(mine)) return;
        result.textContent = describe(job) + (job.failure?.failed_resource_ids?.length ? `\n失败 ID：${job.failure.failed_resource_ids.join(', ')}` : '');
        result.hidden = false; exportButton.hidden = false; exportFailed.hidden = !(currentExport?.failure?.failed_resource_ids?.length);
        retryIds = currentExport?.retryable_resource_ids || [];
        retryButton.hidden = !['cancelled', 'not_committed'].includes(job.status) || !retryIds.length;
        finish.hidden = false; recoverButton.hidden = job.status !== 'unknown'; dialog.save.hidden = true; dialog.cancel.hidden = false; dialog.cancel.textContent = '关闭';
        dialog.setBusy(false); setBusy(false);
        if (job.status === 'unknown') dialog.error.textContent = `提交结果未知。令牌已保留：${token}。请重新查询状态，不能自动重试。`;
        else if (job.status === 'committed') dialog.error.textContent = `批量${batchOperationText(job.operation)}完成。`;
        else { dialog.error.textContent = `批量${batchOperationText(job.operation)}未写入任何记录。${job.failure?.message || ''} 可在确认最新版本后显式重试。`; renderRetry(); }
    };
    const poll = token => {
        if (pollPromise || !dialog.form.isConnected) return pollPromise;
        clearTimer();
        const mine = ++generation;
        state = 'monitoring'; setBusy(true); recoverButton.hidden = true;
        const loop = async () => {
            if (!live(mine)) return;
            try {
                const job = await batchFetch('/batch/status?token=' + encodeURIComponent(token));
                if (!live(mine)) return;
                currentJob = job; progress.textContent = describe(job);
                if (BATCH_TERMINALS.has(job.status)) { await showTerminal(job, token, mine); return; }
                if (cancelIntent && !cancelSent && !cancellationInFlight) await sendCancel(token);
                if (live(mine)) timer = setTimeout(loop, 500);
            } catch (error) {
                if (!live(mine)) return;
                state = 'recovery_needed'; stopPolling(); dialog.setBusy(false); setBusy(false); recoverButton.hidden = false; dialog.cancel.textContent = '关闭';
                dialog.error.textContent = `无法读取任务状态：${error.message}。恢复令牌已保留，不会自动重试。`;
            }
        };
        pollPromise = loop().finally(() => { if (live(mine)) pollPromise = null; });
        return pollPromise;
    };
    const sendCancel = async token => {
        if (cancellationInFlight || !token) return;
        cancellationInFlight = true; dialog.cancel.disabled = true; dialog.cancel.textContent = '正在取消…';
        try {
            await batchFetch('/batch/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) });
            cancelSent = true;
            if (!dialog.form.isConnected) return;
            dialog.error.textContent = '取消已请求，等待服务器确认终态…';
        } catch (error) {
            if (dialog.form.isConnected) dialog.error.textContent = `取消请求失败：${error.message}；任务上下文和恢复令牌仍保留。`;
        } finally {
            cancellationInFlight = false;
            if (dialog.form.isConnected && active()) dialog.cancel.disabled = false;
        }
        if (dialog.form.isConnected && !pollPromise && !timer && active()) void poll(token);
    };
    const cancelJob = () => {
        if (cancellationInFlight || state === 'terminal') return;
        cancelIntent = true;
        if (state === 'start_pending') { dialog.error.textContent = '已记录取消意图，启动确认后立即请求取消。'; return; }
        if (currentJob?.token) void sendCancel(currentJob.token);
    };
    const finishJob = async () => {
        if (!dialog.form.isConnected || active() || finishing) return;
        finishing = true; ++generation;
        const job = currentJob;
        if (job?.status === 'committed') for (const id of originalIds || []) selected.delete(id);
        if (job?.token && BATCH_KNOWN_TERMINALS.has(job.status)) batchStorage.clear(job.token);
        stopPolling();
        if (dialog.form.isConnected) dialog.dismiss();
        const scroll = list.scrollTop;
        try { await categories(); await load(); list.scrollTop = scroll; } catch (error) { report(error); }
    };
    const start = async ids => {
        if (state !== 'configuring' || requestDispatched || !dialog.form.isConnected) return;
        if (!ids.length) throw new Error('请至少明确选择一条 Tag。');
        if (ids.length > 500) throw new Error('单个原子批量任务最多包含 500 条 Tag。');
        if (operation === 'delete' && !confirm.checked) throw new Error('请勾选确认后再删除。');
        currentRequest = { token: batchToken(), operation, resource_ids: [...ids], expected_tag_revision: revision, expected_collection_revision: collectionRevision };
        cancelIntent = false; cancelSent = false; retryButton.hidden = true;
        requestDispatched = true; state = 'start_pending'; currentJob = { token: currentRequest.token, operation, status: 'queued', processed: 0, total: ids.length }; originalIds = [...ids];
        saveRecovery(currentRequest); dialog.setBusy(true); setBusy(true); dialog.cancel.textContent = '取消操作'; dialog.error.textContent = persistWarning ? dialog.error.textContent : '正在提交批量任务…'; progress.textContent = describe(currentJob);
        try {
            const job = await batchFetch('/batch/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(currentRequest) });
            if (!dialog.form.isConnected) return;
            currentJob = job; state = 'monitoring';
            if (cancelIntent) await sendCancel(currentRequest.token);
            await poll(currentRequest.token);
        } catch (error) {
            if (!dialog.form.isConnected) return;
            const definiteReject = error.bodyKnown && [400, 409, 429].includes(error.httpStatus);
            if (definiteReject) {
                state = 'configuring'; requestDispatched = false; currentJob = null; batchStorage.clear(currentRequest.token); dialog.setBusy(false); setBusy(false); dialog.cancel.textContent = '取消'; dialog.error.textContent = `任务未接受：${error.message}。请修正后再提交。`;
            } else {
                state = 'recovery_needed'; dialog.setBusy(false); setBusy(false); recoverButton.hidden = false; dialog.cancel.textContent = '关闭'; dialog.error.textContent = `无法确定启动结果：${error.message}。请使用“重新查询状态”；不会自动重试。令牌：${currentRequest.token}`;
            }
        }
    };
    const submit = () => {
        try {
            const ids = retryMode ? [...retryBox.querySelectorAll('input:checked')].map(node => node.dataset.resourceId) : [...originalIds || selected];
            if (retryMode && operation === 'delete' && !confirm.checked) throw new Error('重试删除前请再次勾选确认。');
            void start(ids).catch(error => { if (dialog.form.isConnected) dialog.error.textContent = error.message; });
        } catch (error) { dialog.error.textContent = error.message; }
    };
    const recover = async token => {
        if (!token || !dialog.form.isConnected) return;
        const mine = ++generation; stopPolling(); state = 'recovery_needed'; dialog.setBusy(true); setBusy(true); dialog.error.textContent = '正在读取原始批量请求…';
        try {
            const exported = await readExport(token);
            if (!live(mine)) return;
            currentExport = exported; currentRequest = exported.request; originalIds = [...(exported.request?.resource_ids || [])]; currentJob = { token, operation: exported.request?.operation || operation, status: 'unknown', total: originalIds.length };
            operation = currentJob.operation; saveRecovery({...exported.request, token}); scope.textContent = `已选 ${originalIds.length} 条（可能跨页），上限 500 条`;
            progress.textContent = `恢复范围：${originalIds.length} 条\n正在查询服务器状态…`;
            state = 'monitoring'; await poll(token);
        } catch (error) {
            if (!live(mine)) return;
            state = 'recovery_needed'; dialog.setBusy(false); setBusy(false); recoverButton.hidden = false; dialog.error.textContent = `无法恢复任务：${error.message}。原始范围无法核对，不会使用当前选择作为替代。令牌：${token}`;
        }
    };
    const retry = async () => {
        if (state !== 'terminal' || !retryIds.length || retryLoading) return;
        retryLoading = true; const mine = ++generation; setBusy(true); retryButton.disabled = true;
        try {
            const catalog = await get('/index');
            if (!live(mine)) return;
            if (currentJob?.token) batchStorage.clear(currentJob.token);
            groups = catalog.groups || groups; revision = catalog.revision; collectionRevision = catalog.collection_revision || '';
            retryMode = true; renderRetry(); result.hidden = true; currentExport = null; exportButton.hidden = true; exportFailed.hidden = true; dialog.save.hidden = false; dialog.save.disabled = true; dialog.cancel.hidden = false; finish.hidden = true; state = 'configuring'; requestDispatched = false; currentJob = null;
            if (confirm) confirm.checked = false;
            dialog.error.textContent = '已读取最新版本，请选择重试 ID，并再次确认删除。'; setBusy(false);
        } catch (error) { if (live(mine)) dialog.error.textContent = error.message; }
        finally { retryLoading = false; if (live(mine)) { retryButton.disabled = false; setBusy(false); } }
    };
    scope.textContent = recovery ? '已选 待核对 条（可能跨页），上限 500 条' : `已选 ${selected.size} 条（可能跨页），上限 500 条`;
    dialog.save.onclick = submit;
    dialog.cancel.onclick = () => { if (active()) cancelJob(); else if (state === 'terminal' && currentJob?.status === 'unknown') dialog.dismiss(); else if (state === 'terminal') void finishJob(); else dialog.dismiss(); };
    dialog.dismiss = (() => { const original = dialog.dismiss; return () => { if (active()) { dialog.error.textContent = '批量任务进行中，请先取消并等待服务器返回终态。'; return false; } stopPolling(); return original(); }; })();
    dismissEditor = () => { if (state === 'terminal' && currentJob?.status !== 'unknown') void finishJob(); else dialog.dismiss(); };
    recoverButton.onclick = () => void (originalIds ? poll(currentJob?.token || recovery?.token) : recover(currentJob?.token || recovery?.token)).catch(error => { if (dialog.form.isConnected) dialog.error.textContent = error.message; });
    exportButton.onclick = async () => {
        if (exportInFlight || !currentJob?.token) return;
        const mine = generation, token = currentJob.token;
        exportInFlight = true; exportButton.disabled = true;
        try { const exported = currentExport || await readExport(token); if (live(mine) && currentJob?.token === token) { currentExport = exported; download(exported, 'tag-batch-operation.json'); } }
        catch (error) { if (live(mine)) dialog.error.textContent = `导出失败，终态结果仍保留：${error.message}`; }
        finally { exportInFlight = false; if (exportButton.isConnected) exportButton.disabled = false; }
    };
    exportFailed.onclick = async () => { const mine = generation, token = currentJob?.token; try { const data = await readExport(token, 'failed'); if (live(mine) && currentJob?.token === token) download(data, 'tag-batch-failed.json'); } catch (error) { if (live(mine)) dialog.error.textContent = error.message; } };
    retryButton.onclick = () => void retry();
    finish.onclick = () => void finishJob();
    if (recovery) void recover(recovery.token);
};

action('删除所选', () => {
    if (!selected.size) throw new Error('请先选择 Tag。');
    const pending = batchStorage.read();
    if (pending?.token) throw new Error('已有未解决的批量任务，请先恢复。');
    openBatchDialog();
});
    // 批量元数据：与单条维护同一身份与同一版本，整批一次原子提交。
    const batchIdentities = (limit = 500) => {
        const identities = [...selected];
        if (!identities.length) throw new Error('请先选择 Tag。');
        if (identities.length > limit) throw new Error(`一次最多 ${limit} 条，请减少选择后再试。`);
        return identities;
    };
    const applyBatchMetadata = async changes => {
        const identities = batchIdentities();
        await write({ operation: 'batch', items: identities.map(resource_id => ({ operation: 'metadata', resource_id, ...changes })) });
        selected.clear(); updateCount();
        await categories(); await load();
        status.textContent = `已用同一版本提交 ${identities.length} 条 Tag 的批量修改（未提交者不写入）。`;
    };
    action('批量收藏', () => applyBatchMetadata({ favorite: true }));
    action('取消收藏', () => applyBatchMetadata({ favorite: false }));
    action('批量备注', () => {
        const identities = batchIdentities();
        const dialog = modal('批量设置备注');
        const notes = dialog.field('备注（留空表示清除）');
        dialog.error.textContent = `将设置 ${identities.length} 条 Tag 的备注。`;
        dialog.submit(() => ({ operation: 'batch', items: identities.map(resource_id => ({ operation: 'metadata', resource_id, notes: notes.value })) }));
    });
action('恢复批量任务', () => {
    const pending = batchStorage.read();
    if (!pending?.token) throw new Error('没有可恢复的批量任务。');
    openBatchDialog(pending);
});
action('手动恢复批量任务', () => {
    const dialog = modal('手动恢复批量任务');
    const input = dialog.field('恢复令牌');
    dialog.save.textContent = '查询状态';
    dialog.save.onclick = () => { const token = input.value.trim(); if (!token) { dialog.error.textContent = '请输入恢复令牌。'; return; } const pending = batchStorage.read(); if (pending?.token && pending.token !== token) { dialog.error.textContent = '请先核对已保留的批量任务。'; return; } batchStorage.write({token}); dialog.dismiss(); openBatchDialog({ token }); };
});
    action('导出全部', () => {
        const link = element('a', null, root, { href: API + '/export', download: 'shared-tags.json' }); link.click(); link.remove();
    });
    action('导出所选', () => {
        if (!selected.size) throw new Error('请先选择 Tag。');
        const link = element('a', null, root, { href: API + '/export?ids=' + encodeURIComponent([...selected].join(',')), download: 'shared-tags.json' }); link.click(); link.remove();
    });
    action('导入 JSON', () => {
        const dialog = modal('导入共享 Tag');
        const file = dialog.field('Tag 数据文件');
        file.type = 'file';
        file.accept = '.json,application/json';
        const overwrite = dialog.field('覆盖相同 ID 的已有内容');
        overwrite.type = 'checkbox';
        const fallback = dialog.field('文件中不存在于本机的分组归入默认分组');
        fallback.type = 'checkbox';
        const preview = element('button', '重新预览', dialog.buttons, { type: 'button' });
        const confirmLabel = element('label', null, dialog.fields);
        const confirm = element('input', null, confirmLabel, { type: 'checkbox' });
        confirmLabel.appendChild(document.createTextNode('我已核对以上五项统计和分类统计，确认按此计划导入。'));
        const countsBox = element('div', '', dialog.fields);
        const categoryBox = element('div', '', dialog.fields);
        const resultBox = element('div', '', dialog.fields);
        resultBox.hidden = true;
        const exportButton = element('button', '导出操作 JSON', dialog.buttons, { type: 'button' });
        exportButton.hidden = true;
        const complete = element('button', '完成并返回列表', dialog.buttons, { type: 'button' });
        complete.hidden = true;
        dialog.save.textContent = '导入';
        dialog.save.disabled = true;
        preview.disabled = true;
        let sourceFile = null, sourceBundle = null, plan = null, operation = null;
        let sequence = 0, submitting = false, completed = false, succeeded = false;
        const labels = ['new', 'updated', 'suspected_duplicate', 'unsupported', 'version_conflicts'];
        const labelNames = { new:'新增', updated:'更新', suspected_duplicate:'疑似重复', unsupported:'不支持', version_conflicts:'版本冲突' };
        const amount = value => value == null ? '待核对' : String(value);
        const countText = counts => labels.map(key => `${labelNames[key]}：${Number(counts?.[key] || 0)}`).join('；');
        const categoryText = counts => ['groups', 'subgroups'].map(key => `${key === 'groups' ? '主分类' : '子分类'}（${countText(counts?.[key])}）`).join('\n');
        const live = generation => generation === sequence && dialog.form.isConnected;
        const clearResult = () => {
            operation = null;
            resultBox.textContent = '';
            resultBox.hidden = true;
            exportButton.hidden = true;
        };
        const clearPlan = message => {
            plan = null;
            confirm.checked = false;
            dialog.save.disabled = true;
            countsBox.textContent = '';
            categoryBox.textContent = '';
            clearResult();
            if (message != null) dialog.error.textContent = message;
        };
        const setEditing = value => {
            file.disabled = value;
            overwrite.disabled = value;
            fallback.disabled = value;
            confirm.disabled = value;
            preview.disabled = value || !sourceBundle;
        };
        const readError = async response => {
            let data = null;
            try { data = await response.json(); } catch {}
            const error = new Error(data?.error || `HTTP ${response.status}`);
            error.operation = data?.operation;
            error.conflict = response.status === 409;
            return error;
        };
        const freshCatalog = async generation => {
            const response = await fetch(API + '/index', { cache: 'no-store' });
            if (!live(generation)) return null;
            const data = await response.json();
            if (!live(generation)) return null;
            if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
            return data;
        };
        const transform = (bundle, catalog) => {
            const imported = structuredClone(bundle);
            const known = new Set((catalog.collections || []).map(item => item.id));
            const missing = new Set(imported.items.flatMap(item => Array.isArray(item.collection_ids) ? item.collection_ids.filter(id => !known.has(id)) : []));
            if (missing.size && !fallback.checked) throw new Error(`文件含 ${missing.size} 个本机没有的分组。可勾选归入默认组，再预览；原文件保留组名和 ID。`);
            if (fallback.checked) for (const item of imported.items) if (Array.isArray(item.collection_ids)) item.collection_ids = [...new Set(item.collection_ids.map(id => known.has(id) ? id : 'default'))];
            return imported;
        };
        const showOperation = result => {
            const counts = result || {};
            resultBox.textContent = `已提交：${amount(counts.committed)} 条\n未提交：${amount(counts.uncommitted)} 条\n跳过：${amount(counts.skipped)} 条\n分类统计：\n${categoryText(counts.category_counts)}`;
            resultBox.hidden = false;
            exportButton.hidden = false;
        };
        const exportOperation = () => {
            if (!operation) return;
            const url = URL.createObjectURL(new Blob([JSON.stringify(operation)], { type:'application/json' }));
            const link = element('a', '', dialog.form, { href:url, download:'tag-import-operation.json' });
            link.click();
            link.remove();
            requestAnimationFrame(() => URL.revokeObjectURL(url));
        };
        const previewPlan = async generation => {
            if (!sourceBundle || !live(generation)) return;
            try {
                const catalog = await freshCatalog(generation);
                if (!catalog || !live(generation)) return;
                const transformed = transform(sourceBundle, catalog);
                const collectionVersion = catalog.collection_revision || '';
                const response = await fetch(API + '/pre_import', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ bundle:transformed, overwrite:overwrite.checked, collection_revision:collectionVersion }) });
                if (!live(generation)) return;
                const data = response.ok ? await response.json() : await readError(response);
                if (!live(generation)) return;
                if (!response.ok) throw data;
                if (data.contract !== 'tag-import-preflight-v1' || !data.preflight_token || data.base_revision == null || data.collection_revision == null) throw new Error('服务器返回了无效的导入预览。');
                revision = catalog.revision || revision;
                collectionRevision = catalog.collection_revision || collectionRevision;
                collections = catalog.collections || collections;
                plan = { committable:data.committable !== false, bundle:transformed, overwrite:overwrite.checked, baseRevision:data.base_revision, collectionRevision:data.collection_revision, token:data.preflight_token, counts:data.counts || {}, categoryCounts:data.category_counts || {} };
                countsBox.textContent = `五项统计：${countText(plan.counts)}；总记录：${Number(plan.counts.total_records || 0)}；将写入：${Number(plan.counts.will_write || 0)}；将跳过：${Number(plan.counts.will_skip || 0)}`;
                categoryBox.textContent = `分类统计：\n${categoryText(plan.categoryCounts)}`;
                confirm.disabled = !plan.committable;
                dialog.error.textContent = plan.committable ? '预览已生成，请核对统计并勾选确认。' : (data.blocked_reason || '存在未解决的覆盖冲突，请调整选项后重新预览。');
            } catch (error) {
                if (live(generation)) clearPlan(error.message);
            } finally {
                if (live(generation)) {
                    preview.disabled = !sourceBundle;
                    dialog.save.disabled = !(plan && plan.committable && confirm.checked);
                }
            }
        };
        const startPreview = () => {
            if (submitting || succeeded || !sourceBundle || !dialog.form.isConnected) return;
            const generation = ++sequence;
            clearPlan('正在读取最新分类并生成导入预览…');
            void previewPlan(generation);
        };
        file.onchange = async () => {
            if (submitting || succeeded) return;
            const selectedFile = file.files?.[0] || null;
            const generation = ++sequence;
            sourceFile = selectedFile;
            sourceBundle = null;
            clearPlan(selectedFile ? '正在读取文件…' : '请选择有效文件。');
            if (!selectedFile) return;
            try {
                const parsed = JSON.parse(await selectedFile.text());
                if (!live(generation) || sourceFile !== selectedFile) return;
                if (parsed.format !== 'weilin-tags-v1' || !Array.isArray(parsed.items)) throw new Error('请选择共享 Tag 导出的 JSON 文件。');
                sourceBundle = parsed;
                dialog.error.textContent = `已读取 ${parsed.items.length} 条，正在生成预览…`;
                const previewGeneration = ++sequence;
                clearPlan('正在读取最新分类并生成导入预览…');
                await previewPlan(previewGeneration);
            } catch (error) {
                if (live(generation) && sourceFile === selectedFile) { sourceBundle = null; clearPlan(error.message); }
            }
        };
        const optionChanged = () => {
            if (submitting || succeeded || !sourceBundle) return;
            const generation = ++sequence;
            clearPlan('选项已改变，请重新预览。');
            void previewPlan(generation);
        };
        overwrite.onchange = optionChanged;
        fallback.onchange = optionChanged;
        preview.onclick = startPreview;
        confirm.onchange = () => { dialog.save.disabled = !(plan && plan.committable && confirm.checked) || submitting; };
        exportButton.onclick = exportOperation;
        const finish = async () => {
            if (completed || submitting || !succeeded) return;
            completed = true;
            dialog.dismiss();
            const scroll = list.scrollTop;
            try { await categories(); await load(); list.scrollTop = scroll; }
            catch (error) { report(error); }
        };
        complete.onclick = finish;
        dialog.cancel.onclick = () => { if (operation && completed === false && dialog.save.hidden) void finish(); else if (!submitting) dialog.dismiss(); };
        dialog.save.onclick = async () => {
            if (submitting || succeeded || !plan?.committable || !confirm.checked || !dialog.form.isConnected) return;
            submitting = true;
            const submitted = plan;
            dialog.setBusy(true);
            setEditing(true);
            dialog.save.disabled = true;
            dialog.error.textContent = '正在提交导入…';
            try {
                const response = await fetch(API + '/update', { method:'POST', headers:{'Content-Type':'application/json','If-Match':submitted.baseRevision}, body:JSON.stringify({ operation:'import', bundle:submitted.bundle, overwrite:submitted.overwrite, collection_revision:submitted.collectionRevision, preflight_token:submitted.token, confirmed:true }) });
                const data = response.ok ? await response.json() : await readError(response);
                if (!response.ok) throw data;
                if (!data.operation || data.operation.contract !== 'weilin-tag-import-operation-v1') throw new Error('服务器未返回有效的导入操作结果。');
                revision = data.revision || revision;
                collectionRevision = data.collection_revision || collectionRevision;
                operation = data.operation;
                succeeded = true;
                dismissEditor = () => { if (!submitting) void finish(); };
                window.dispatchEvent(new CustomEvent('unified-tags-updated', { detail:{ revision } }));
                showOperation(operation);
                dialog.error.textContent = `导入完成：已提交 ${amount(operation.committed)} 条，未提交 ${amount(operation.uncommitted)} 条，跳过 ${amount(operation.skipped)} 条。`;
                dialog.save.hidden = true;
                preview.hidden = true;
                complete.hidden = false;
                file.disabled = true;
                overwrite.disabled = true;
                fallback.disabled = true;
                confirm.disabled = true;
            } catch (error) {
                const knownOperation = error.operation;
                clearPlan(knownOperation ? `导入未完成：${error.message}。可导出操作结果，或重新预览后重试。` : `无法确定导入结果：${error.message}。服务器可能已处理请求，请重新预览后再决定是否重试。`);
                if (knownOperation) { operation = knownOperation; showOperation(operation); }
            } finally {
                submitting = false;
                dialog.setBusy(false);
                if (dialog.form.isConnected && !dialog.save.hidden) { setEditing(false); dialog.save.disabled = !(plan && plan.committable && confirm.checked); }
            }
        };
    });
    if (options.onInsert) {
        element('span', options.targetLabel || '当前提示词目标', insertionHost);
        insertionControls = mountInsertionActions(insertionHost, options.onInsert, async () => {
            if (!selected.size) throw new Error('请先选择 Tag。');
            const latest = await Promise.all([...selected].map(id => get('/item?id=' + encodeURIComponent(id))));
            return latest.map(result => result.item.text).join(', ');
        }, message => {status.textContent = message;});
    }
    action('刷新', async () => { await categories(); await load(); });
    try {
        await categories();
        if (options.state) {
            const state = options.state; search.value = state.query || ''; group.value = state.group || ''; renderSubgroups(state.subgroup); collectionFilter.value = state.collection || ''; onlyFavorites.checked = !!state.favorites; offset = state.offset || 0;
            renderStringLink();
            for (const id of state.selected || []) selected.add(id);
        }
        await load(); if (options.state?.scroll) list.scrollTop = options.state.scroll;
        if (options.editTagId) await editTag({resource_id:options.editTagId.startsWith('tag:') ? options.editTagId : 'tag:' + options.editTagId}, options.readOnly === true);
    }
    catch (error) { report(error); }
    return activeManager;
}
