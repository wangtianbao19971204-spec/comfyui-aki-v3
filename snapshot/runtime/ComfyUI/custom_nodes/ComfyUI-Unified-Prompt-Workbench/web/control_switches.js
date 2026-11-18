import {api} from '../../../scripts/api.js';
import {commitWidget} from './prompt_target.js';
import {setNodeMode} from './canvas_write.js';

const children = node => node?.subgraph?._nodes || [];
const widget = (node, name) => node?.widgets?.find(item => item.name === name);
const named = (nodes, prefix) => nodes.find(node => node.title?.startsWith(prefix));
const selection = node => {
    const value = widget(node, 'select')?.value;
    return node?.inputs?.find(port => port.name.startsWith('input_') && (port.label || port.name) === value)?.name || value;
};

export function controlScope(graph, branch) {
    const nodes = branch ? branch.nodeIds.map(id => graph.getNodeById(id)).filter(Boolean) : graph._nodes;
    const model = nodes.find(node => node.type === 'DazzleSwitch' && node.title?.startsWith('[02G'));
    if (!model) return null;
    const compact = nodes.find(node => children(node).some(child => child.type === 'Krea2ControlImageEncode'));
    const inside = compact ? children(compact) : nodes;
    const encode = inside.find(node => node.type === 'Krea2ControlImageEncode');
    const apply = nodes.find(node => node.type === 'Krea2ControlApply');
    const loader = nodes.find(node => node.type === 'Krea2ControlLoRALoader');
    const source = named(inside, '[05R1]') || named(inside, '[05B6]');
    const mask = named(inside, '[05C2]');
    if (!encode || !apply || !loader || !mask || !named(inside, '[05C7]')) return null;
    return {graph, branch, nodes, model, compact, encode, apply, loader, source, mask,
        pose: nodes.find(node => node.type === 'VNCCS_PoseStudio'),
        poseReference: named(nodes, '[09A]'), poseDepth: named(inside, '[09R]') || named(inside, '[05B4P]'),
        reference: named(nodes, '[05A]'), preprocessor: named(inside, '[05B5]'),
        erase: named(inside, '[05R2]'), composite: named(inside, '[05C7]')};
}

function checkSelector(node) {
    for (const name of ['select', 'mode', 'select_override']) {
        const item = widget(node, name);
        if (!item || node.inputs?.some(port => port.name === name && port.link != null))
            throw new Error('控制选择由其他输入提供，请恢复此流程的原控制选择器。');
    }
}

function select(app, node, value) {
    const port = node.inputs.find(port => port.name === value);
    for (const [name, next] of [['select', port?.label || value], ['mode', 'strict'], ['select_override', 0]]) {
        const item = widget(node, name);
        commitWidget(app, node, item, next);
    }
}

export function controlState(scope) {
    const modelSelection = selection(scope.model);
    const modelReady = input => scope.model.mode === 0 && Number(widget(scope.model, 'select_override')?.value || 0) === 0 &&
        (modelSelection === input || modelSelection === '(none)' && widget(scope.model, 'mode')?.value === 'priority');
    const source = scope.source ? (selection(scope.source) === 'input_02' ? 'pose' : 'reference') : 'reference';
    return {enabled: scope.apply.mode === 0 && scope.loader.mode === 0 && (!scope.compact || scope.compact.mode === 0) && modelReady('input_01'), source,
        erase: (source === 'reference' || !!scope.erase) && (scope.erase ? selection(scope.erase) === 'input_01' : scope.composite.mode === 0)};
}

export function setControl(app, scope, enabled, source = controlState(scope).source) {
    if (source === 'pose' && !scope.pose) throw new Error('此流程没有姿势工作室。');
    checkSelector(scope.model);
    if (scope.source) checkSelector(scope.source);
    const graph = scope.graph;
    graph.beforeChange?.();
    try {
        select(app, scope.model, enabled ? 'input_01' : 'input_02');
        scope.model.properties.control_source = source;
        setNodeMode(app, scope.model, 0);
        if (scope.source) select(app, scope.source, source === 'pose' ? 'input_02' : 'input_01');
        for (const node of [scope.compact, scope.encode, scope.apply, scope.loader]) setNodeMode(app, node, enabled ? 0 : 2);
        for (const node of [scope.pose, scope.poseReference, scope.poseDepth]) setNodeMode(app, node, enabled && source === 'pose' ? 0 : 2);
        if (enabled && source === 'reference') setNodeMode(app, scope.reference, 0);
    } finally {graph.afterChange?.(); graph.setDirtyCanvas?.(true, true);}
}

export function setErase(app, scope, enabled) {
    if (scope.erase) checkSelector(scope.erase);
    const graph = scope.graph;
    graph.beforeChange?.();
    try {
        if (enabled) setControl(app, scope, true, 'reference');
        if (scope.erase) select(app, scope.erase, enabled ? 'input_01' : 'input_02');
        else setNodeMode(app, scope.composite, enabled ? 0 : 4);
    } finally {graph.afterChange?.(); graph.setDirtyCanvas?.(true, true);}
}

export async function maskHasSelection(node) {
    if (node.inputs?.some(port => port.name === 'image' && port.link != null))
        throw new Error('遮罩文件由其他输入提供，无法核对擦线区域。');
    const value = String(widget(node, 'image')?.value || '');
    const match = value.match(/^(.*?)(?: \[(input|temp|output)\])?$/);
    const path = match[1].replace(/\\/g, '/'), index = path.lastIndexOf('/');
    if (!path) throw new Error('请先画出擦线区域并保存。');
    const image = new Image();
    image.src = api.apiURL('/view?' + new URLSearchParams({filename: path.slice(index + 1), subfolder: path.slice(0, Math.max(index, 0)), type: match[2] || 'input'}));
    try {await image.decode();} catch {throw new Error('遮罩图片无法读取，请点“画擦线区域”重新保存。');}
    const canvas = document.createElement('canvas'); canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d'); context.drawImage(image, 0, 0);
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let i = 3; i < data.length; i += 4) if (data[i] < 255) return true;
    return false;
}


function previewCanvas(scope) {
    const graph = scope.graph;
    const lineart = named(scope.nodes, '[05B5]'), preview = named(scope.nodes, '[05V5]');
    if (!lineart || !preview || lineart.graph !== graph || preview.graph !== graph) return null;
    return preview;
}

async function previewImages(app, node) {
    const request = await app.queuePrompt(0, 1, {queueNodeIds: [node.id]});
    const promptId = request?.prompt_id || request?.promptId;
    if (!promptId) throw new Error('无法提交线稿画布任务，请检查队列。');
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
        let history = null;
        try { const response = await api.fetchApi('/history/' + encodeURIComponent(promptId)); history = response.ok ? await response.json() : null; } catch {}
        const entry = history?.[promptId] || Object.values(history || {})[0];
        if (entry?.status?.status_str === 'error') throw new Error('线稿画布生成失败，请检查工作流报错。');
        if (entry?.status?.completed === true || entry?.status?.status_str === 'success')
            return entry.outputs?.[String(node.id)]?.images || [];
        await new Promise(resolve => setTimeout(resolve, 500));
    }
    throw new Error('线稿画布生成超时，请查看队列。');
}

async function uploadPreview(image) {
    const url = image.src || api.apiURL('/view?' + new URLSearchParams({filename: image.filename, subfolder: image.subfolder || '', type: image.type || 'temp'}));
    const response = await fetch(url);
    if (!response.ok) throw new Error('无法读取线稿画布图片。');
    const body = new FormData();
    body.append('image', await response.blob(), `erase_canvas_${Date.now()}.png`);
    body.append('type', 'input');
    const uploaded = await (await api.fetchApi('/upload/image', {method: 'POST', body})).json();
    const name = [uploaded.subfolder, uploaded.name].filter(Boolean).join('/');
    if (!name) throw new Error('线稿画布上传失败。');
    return name;
}

function fitMaskEditor() {
    const root = document.querySelector('.maskEditor-dialog-root');
    if (!root) return;
    const panel = root.closest('.fixed');
    if (panel) {
        panel.style.inset = '0';
        panel.style.left = '0';
        panel.style.top = '0';
        panel.style.width = '100vw';
        panel.style.height = '100vh';
        panel.style.maxWidth = '100vw';
        panel.style.maxHeight = '100vh';
        panel.style.zIndex = '100000';
        panel.style.overflow = 'auto';
        panel.style.transform = 'none';
        panel.style.translate = 'none';
        panel.style.margin = '0';
    }
    root.style.minWidth = '0';
    root.style.minHeight = '0';
}

function leaveWorkbenchForMaskEditor() {
    const root = document.querySelector('#unified-workbench');
    if (!root) return;
    root.querySelector('[data-uw="close"]')?.click();
    if (root.isConnected) root.style.display = 'none';
    const back = document.createElement('button');
    back.type = 'button';
    back.textContent = '返回工作台';
    back.style.cssText = 'position:fixed;right:22px;bottom:76px;z-index:100000;padding:9px 14px;border:1px solid #648494;border-radius:8px;background:#233744;color:#e4f1f8;cursor:pointer;box-shadow:0 4px 16px #0008';
    back.onclick = () => {
        back.remove();
        root.remove();
        window.unifiedOpenWorkbench?.({page: 'workspace'});
    };
    document.body.append(back);
}

export async function prepareMaskCanvas(app, scope, status) {
    const preview = previewCanvas(scope);
    if (!preview) {
        const imageWidget = widget(scope.mask, 'image');
        const reference = scope.reference || scope.graph?._nodes?.find(node => node.title?.startsWith('[05A]'));
        const referenceImage = widget(reference, 'image')?.value;
        if (!imageWidget || !referenceImage) return false;
        commitWidget(app, scope.mask, imageWidget, referenceImage);
        status.textContent = '遮罩画布已载入参考图；涂抹要擦掉的区域后保存。';
        return true;
    }
    let images = preview.imgs?.length ? [...preview.imgs] : null;
    if (!images) {
        status.textContent = '正在生成当前线稿画布…';
        const graph = scope.graph, saved = preview.mode;
        graph.beforeChange?.();
        setNodeMode(app, preview, 0);
        graph.afterChange?.(); graph.setDirtyCanvas?.(true, true);
        try {
            images = await previewImages(app, preview);
        } finally {
            graph.beforeChange?.();
            setNodeMode(app, preview, saved);
            graph.afterChange?.(); graph.setDirtyCanvas?.(true, true);
        }
    }
    if (!images?.length) return false;
    if (!preview.imgs?.length) preview.imgs = images;
    const name = await uploadPreview(images[0]);
    const imageWidget = widget(scope.mask, 'image');
    if (!imageWidget) throw new Error('找不到遮罩图片控件。');
    const values = imageWidget.options?.values;
    if (Array.isArray(values) && !values.includes(name)) values.push(name);
    commitWidget(app, scope.mask, imageWidget, name);
    return true;
}

export function mountControlSwitches(host, app, branch, isCurrent = () => true) {
    const graph = app.rootGraph || app.graph, scope = controlScope(graph, branch);
    if (!scope) return {sync() {}, dispose() {}};
    let disposed = false, checking = false;
    const targets = Object.values(scope).filter(node => typeof node?.type === 'string' && node.id != null);
    const current = () => !disposed && isCurrent() && (app.rootGraph || app.graph) === graph &&
        (!branch || graph.extra?.uap_workbench?.activeBranch === branch.id) &&
        targets.every(node => node.graph?.getNodeById(node.id) === node);
    const el = (tag, text, parent, props = {}) => {const item = Object.assign(document.createElement(tag), props); if (text) item.textContent = text; parent.append(item); return item;};
    const box = el('section', '', host, {className: 'desk-control-switches'}); box.dataset.deskArea = 'parameters';
    el('h3', '控制与擦线', box);
    const enabled = el('input', '', el('label', '启用控制 ', box, {className: 'switch'}), {type: 'checkbox'}); enabled.setAttribute('aria-label', '启用控制');
    const source = scope.source ? el('select', '', el('label', '控制来源 ', box, {className: 'field'})) : null;
    if (source) {
        source.setAttribute('aria-label', '控制来源');
        el('option', '参考图', source, {value: 'reference'});
        if (scope.pose) el('option', '姿势工作室', source, {value: 'pose'});
    }
    const erase = el('input', '', el('label', '启用擦线 ', box, {className: 'switch'}), {type: 'checkbox'}); erase.setAttribute('aria-label', '启用擦线');
    const edit = el('button', '画擦线区域', box, {type: 'button'});
    const status = el('small', '', box); status.setAttribute('role', 'status');
    el('small', '画好区域并保存，再打开擦线。会自动启用参考图控制；无需换线或开分组。', box);
    const run = action => {if (!current()) return; try {action(); status.textContent = '';} catch (error) {status.textContent = error.message;} sync();};
    enabled.onchange = () => run(() => setControl(app, scope, enabled.checked, source?.value || 'reference'));
    if (source) source.onchange = () => run(() => setControl(app, scope, true, source.value));
    erase.onchange = async () => {
        if (!current() || checking) return;
        if (!erase.checked) return run(() => setErase(app, scope, false));
        const maskValue = widget(scope.mask, 'image')?.value;
        checking = true; sync();
        try {
            const selected = await maskHasSelection(scope.mask);
            if (!current() || widget(scope.mask, 'image')?.value !== maskValue) return;
            if (!selected) throw new Error('还没有擦线区域。点“画擦线区域”，涂抹后保存，再开启。');
            setErase(app, scope, true); status.textContent = '擦线已启用，参考图控制已接通。';
        } catch (error) {if (current()) status.textContent = error.message;}
        finally {checking = false; sync();}
    };
    edit.onclick = async () => {
        if (!current()) return;
        const originalUrl = location.href;
        const restoreUrl = () => {
            if (location.href !== originalUrl) history.replaceState(history.state, '', originalUrl);
        };
        edit.disabled = true;
        try {
            let canvas = false;
            try { canvas = await prepareMaskCanvas(app, scope, status); }
            catch (error) { if (current()) status.textContent = error.message; }
            if (!current()) return;
            if (scope.mask.graph !== app.graph) app.canvas.setGraph(scope.mask.graph);
            await new Promise(resolve => requestAnimationFrame(resolve));
            if (!current()) return;
            app.canvas.deselectAllNodes(); app.canvas.selectNode(scope.mask);
            await app.extensionManager.command.execute('Comfy.MaskEditor.OpenMaskEditor');
            app.canvas.setGraph(app.rootGraph);
            restoreUrl();
            fitMaskEditor();
            await new Promise(resolve => setTimeout(resolve, 150));
            fitMaskEditor();
            restoreUrl();
            leaveWorkbenchForMaskEditor();
            restoreUrl();
            status.textContent = canvas ? '画布已载入参考图，涂抹后保存，再打开“启用擦线”。'
                : '在编辑器里涂抹要擦掉的区域，保存后打开“启用擦线”。';
        } catch { status.textContent = '无法打开蒙版编辑器，请检查线稿预览与遮罩图片是否存在。'; }
        finally { if (current()) { edit.disabled = false; sync(); } }
    };
    function sync() {
        if (disposed) return;
        const state = controlState(scope), writable = current() && !checking;
        enabled.checked = state.enabled; erase.checked = state.enabled && state.erase;
        if (source && document.activeElement !== source) source.value = state.source;
        enabled.disabled = erase.disabled = edit.disabled = !writable;
        if (source) source.disabled = !writable;
    }
    sync();
    return {sync, dispose() {disposed = true; box.remove();}};
}

