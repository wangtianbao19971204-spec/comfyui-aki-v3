import {createWidgetInserter} from './prompt_target.js';

const link = value => Array.isArray(value) && value.length === 2 && typeof value[1] === 'number';
const samplers = new Set(['KSampler', 'KSamplerAdvanced']);
const loaders = new Set(['UNETLoader', 'CheckpointLoaderSimple', 'CheckpointLoader', 'Unet Loader (LoraManager)', 'Checkpoint Loader (LoraManager)']);
const managerLoras = new Set(['Lora Loader (LoraManager)', 'Lora Stacker (LoraManager)']);

export function containsTrigger(text, trigger) {
    const escaped = trigger.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return !!escaped && new RegExp(`(?<![\\p{L}\\p{N}_])${escaped}(?![\\p{L}\\p{N}_])`, 'iu').test(text);
}

// Only resolve contracts whose backend output is a known, unchanged string.
// Runtime cleaners, randomizers and conditioning transforms stay explicit.
function promptText(api, value, seen = new Set()) {
    if (typeof value === 'string') return {text: value, path: []};
    if (!link(value)) return {reason: '未连接可读的提示词', path: []};
    const [id, slot] = value, node = api[id];
    if (!node || seen.has(String(id))) return {reason: '来源缺失或存在循环', path: [String(id)]};
    seen.add(String(id));
    const type = node.class_type, inputs = node.inputs || {};
    let result;
    if (type === 'CLIPTextEncode' && slot === 0) result = promptText(api, inputs.text, seen);
    else if (['CR Prompt Text', 'PrimitiveString', 'PrimitiveStringMultiline'].includes(type) && slot === 0) result = promptText(api, inputs.prompt ?? inputs.value, seen);
    else if (type === 'WeiLinPromptUI' && slot === 0 && inputs.auto_random === false &&
        !inputs.opt_text && !inputs.lora_str && typeof inputs.positive === 'string' &&
        !/^\s*[{[]/.test(inputs.positive) && !/<wlr:/i.test(inputs.positive)) {
        result = {text: inputs.positive, path: [], source: {id: String(id), widget: 'positive'}};
    } else result = {reason: `${type} 的输出需运行时确认`, path: []};
    if (!result.source && result.text != null && !link(inputs.text) && type === 'CLIPTextEncode') result.source = {id: String(id), widget: 'text'};
    if (!result.source && result.text != null && ['CR Prompt Text', 'PrimitiveString', 'PrimitiveStringMultiline'].includes(type)) result.source = {id: String(id), widget: type === 'CR Prompt Text' ? 'prompt' : 'value'};
    return {...result, path: [`${type} #${id}`, ...result.path]};
}

export function inspectPrompt(api, samplerId) {
    const sampler = api[samplerId];
    if (!sampler || !samplers.has(sampler.class_type)) throw new Error('采样器已失效，请重新检查。');
    const positive = promptText(api, sampler.inputs.positive);
    const negative = promptText(api, sampler.inputs.negative);
    const models = [], loras = [], unknown = [], visited = new Set();
    function walk(value, via = 'model') {
        if (!link(value) || visited.has(`${via}:${value[0]}`)) return;
        const id = String(value[0]), node = api[id];
        visited.add(`${via}:${id}`);
        if (!node) { unknown.push(`#${id} 来源缺失`); return; }
        const inputs = node.inputs || {}, type = node.class_type;
        if (loaders.has(type)) {
            const file = inputs.unet_name ?? inputs.ckpt_name;
            const model = models.find(item => item.id === id);
            if (model) model.via.push(via);
            else models.push({id, file: typeof file === 'string' ? file : '文件名由运行时决定', via: [via]});
        } else if (managerLoras.has(type)) {
            const rows = inputs.loras?.__value__ ?? inputs.loras;
            if (!Array.isArray(rows) || link(rows)) unknown.push(`${type} #${id} 的 LoRA 列表需运行时确认`);
            else for (const row of rows) {
                if (!row.active) continue;
                if (typeof row.name !== 'string' || !Number.isFinite(Number(row.strength)) || !Number.isFinite(Number(row.clipStrength ?? row.strength))) unknown.push(`${type} #${id} 的 LoRA 配置需运行时确认`);
                else if (Number(row.strength) !== 0 || Number(row.clipStrength ?? row.strength) !== 0) loras.push({name: row.name, id});
            }
        } else if (['LoraLoader', 'LoraLoaderModelOnly'].includes(type)) {
            if (typeof inputs.lora_name !== 'string' || link(inputs.strength_model) || link(inputs.strength_clip) || !Number.isFinite(Number(inputs.strength_model)) || !Number.isFinite(Number(inputs.strength_clip ?? 0))) unknown.push(`${type} #${id} 的文件名或强度需运行时确认`);
            else if (Number(inputs.strength_model) !== 0 || Number(inputs.strength_clip ?? 0) !== 0) loras.push({name: inputs.lora_name, id});
        } else if (!['CLIPLoader', 'DualCLIPLoader', 'CLIPSetLastLayer'].includes(type)) unknown.push(`${type} #${id}`);
        for (const name of ['model', 'clip', 'lora_stack']) walk(inputs[name], name === 'clip' ? 'clip' : via);
    }
    walk(sampler.inputs.model);
    // LoRAs on the actual encoder's CLIP path also affect conditioning.
    for (const value of [sampler.inputs.positive, sampler.inputs.negative]) {
        const encode = link(value) && api[value[0]];
        if (encode?.class_type === 'CLIPTextEncode') walk(encode.inputs.clip, 'clip');
    }
    const cfg = sampler.inputs.cfg;
    const patched = unknown.length > 0 || /cfg_pp/.test(sampler.inputs.sampler_name || '');
    const cfgNote = typeof cfg !== 'number' ? 'CFG 由运行时决定；负向作用待确认。' : cfg === 1 ?
        `CFG = 1：标准 CFG 路径中负向不参与引导。${patched ? '当前含额外节点或引导采样器，最终作用需按其实现确认。' : ''}` :
        `CFG = ${cfg}：标准 CFG 路径会使用负向条件。${patched ? '当前含额外节点，实际作用以其实现为准。' : ''}`;
    return {positive, negative, models, loras: [...new Map(loras.map(item => [item.name, item])).values()], unknown: [...new Set(unknown)], cfgNote};
}

export function modelNote(file) {
    if (/animayume[_\\/.-]*v?15/i.test(file)) return 'AnimaYume v1.5；原版 Anima LoRA 的兼容性需逐个验证。';
    if (/anima.*2[._-]?9|anima29|2\.9b/i.test(file)) return 'Anima 2.9B：原版 28 层 LoRA / LLLite 不可直接视为 40 层兼容。';
    if (/krea2/i.test(file)) return 'Krea2：提示词与采样参数应按当前具体模型版本设置。';
    return '文件名取自上游加载器；架构与 LoRA 兼容性不能仅凭分支名称判断。';
}

const element = (tag, text, parent, props = {}) => {
    const node = Object.assign(document.createElement(tag), props);
    node.textContent = text; parent.append(node); return node;
};

export function mountPromptInspector(host, app, branch, isCurrent) {
    const graph = app.graph;
    const root = element('section', '', host, {className: 'desk-prompt-inspector'});
    root.dataset.deskArea = 'prompts';
    element('h3', '实际出图提示词检查', root);
    element('small', '按采样器连线检查；只读取当前工作流，不提交生成任务。', root);
    const toolbar = element('div', '', root, {className: 'plugin-tools'});
    const refresh = element('button', '检查当前分支', toolbar, {type: 'button'});
    const select = element('select', '', toolbar, {hidden: true});
    select.setAttribute('aria-label', '检查采样器');
    const status = element('p', '点击检查，查看进入采样器的提示词、模型与 LoRA 触发词。', root);
    status.setAttribute('role', 'status');
    const body = element('div', '', root);
    root.style.cssText = 'min-width:0;overflow-wrap:anywhere';
    let disposed = false, controller, writer, snapshot = '', api, version = 0, rows = [], prepared;
    const valid = () => !disposed && app.graph === graph && isCurrent() && graph.extra?.uap_workbench?.activeBranch === branch.id;
    // No new polling: the daily controls' existing visible-only sync calls this.
    const fingerprint = () => {
        const pending = [...branch.nodeIds], seen = new Set(), state = [];
        while (pending.length) {
            const id = pending.pop();
            if (seen.has(String(id))) continue;
            seen.add(String(id));
            const node = graph.getNodeById(id);
            if (!node) { state.push([id, null]); continue; }
            const inputs = (node.inputs || []).map(input => {
                const edge = graph.links[input.link];
                if (edge) pending.push(edge.origin_id);
                return [input.name, input.link, edge?.origin_id, edge?.origin_slot];
            });
            state.push([node.id, node.type, node.mode, inputs,
                (node.widgets || []).filter(w => ['string', 'number', 'boolean'].includes(typeof w.value) || w === node.lorasWidget)
                    .map(w => [w.name, w.value])]);
        }
        return JSON.stringify(state);
    };
    const fresh = () => valid() && snapshot === fingerprint();
    function clear() { controller?.abort(); writer?.dispose(); writer = null; prepared = null; rows = []; body.replaceChildren(); }
    function sync() {
        if (snapshot && !fresh()) {
            status.textContent = '工作流已变化；以下是上次检查结果，请重新检查。';
            body.querySelectorAll('input,button').forEach(node => { if (node.dataset.undo !== 'true') node.disabled = true; });
        }
    }
    async function draw() {
        clear(); const ticket = ++version;
        if (!fresh()) { sync(); return; }
        controller = new AbortController();
        const currentController = controller;
        const report = inspectPrompt(api, select.value);
        element('p', report.cfgNote, body);
        for (const [name, result] of [['正向', report.positive], ['负向', report.negative]]) {
            element('strong', `${name} · ${result.text != null ? '可确定的编码输入' : '待运行确认'}`, body);
            element('small', result.path.join(' ← '), body, {style: 'display:block;margin:4px 0'});
            if (result.text != null) {
                const text = element('textarea', '', body, {readOnly: true, value: result.text, style: 'height:76px;max-height:180px'});
                text.setAttribute('aria-label', `实际${name}提示词`);
            } else element('p', result.reason, body);
        }
        for (const model of report.models) {
            element('p', `${model.via.includes('model') ? '采样器模型' : 'CLIP 关联模型（仅编码器链路）'} #${model.id}：${model.file}`, body);
            element('small', modelNote(model.file), body);
        }
        if (!report.models.some(model => model.via.includes('model'))) element('p', '尚未确认采样器的基础模型；请核对模型链路中的未解析节点。', body);
        if (report.unknown.length) element('p', `未完整解析的上游节点：${report.unknown.join('；')}。`, body);
        const loraBox = element('div', '', body);
        element('h4', '已连接 LoRA 的触发词', loraBox);
        element('small', '按本地元数据核对。触发词可能是可选词或互斥变体，请按模型说明选择。', loraBox);
        if (!report.loras.length) { element('p', '未发现可静态确认、启用且非零强度的 LoRA。', loraBox); return; }
        status.textContent = '正在读取本地 LoRA 元数据…';
        const results = await Promise.all(report.loras.map(async lora => {
            try {
                const response = await fetch(`/api/lm/loras/get-trigger-words?name=${encodeURIComponent(lora.name)}`, {signal: currentController.signal, cache: 'no-store'});
                const data = await response.json();
                if (!response.ok || !data.success || !Array.isArray(data.trigger_words)) throw new Error(response.status === 409 ? '同名文件不唯一，请使用完整路径' : '本地元数据读取失败，可重新检查');
                return {...lora, words: data.trigger_words.filter(w => typeof w === 'string' && w.trim())};
            } catch (error) { return {...lora, error: error.message}; }
        }));
        if (disposed || ticket !== version || currentController.signal.aborted || !fresh()) { sync(); return; }
        const source = report.positive.source;
        const node = source && graph.getNodeById(source.id);
        const widget = node?.widgets?.find(w => w.name === source.widget);
        const writable = widget && String(widget.value ?? '') === report.positive.text;
        for (const item of results) {
            element('p', `${item.name} · #${item.id}`, loraBox);
            if (item.error || !item.words.length) { element('small', item.error || '元数据未提供触发词；这不代表模型一定不需要。', loraBox); continue; }
            for (const word of [...new Set(item.words)]) {
                const present = report.positive.text != null && containsTrigger(report.positive.text, word);
                const label = element('label', '', loraBox, {style: 'display:flex;align-items:start;gap:6px;margin:5px 0'});
                const check = element('input', '', label, {type: 'checkbox', disabled: !writable || present});
                element('span', `${word} · ${present ? '已出现' : report.positive.text == null ? '待运行确认' : '未出现'}`, label);
                rows.push({check, word});
            }
        }
        const failures = results.filter(item => item.error).length;
        status.textContent = failures ? `连线检查完成；${failures} 个 LoRA 的元数据读取失败，请查看下方提示。` : '检查完成；只有连线可确定的文本显示为编码输入。';
        if (!writable) { element('p', '当前正向来源不可直接写入；请在实际来源节点处理触发词。', loraBox); return; }
        const actions = element('div', '', loraBox, {className: 'plugin-tools uw-target-actions'});
        const preview = element('button', '预览追加所选触发词', actions, {type: 'button'});
        preview.disabled = !rows.some(row => !row.check.disabled);
        const apply = element('button', '确认追加', actions, {type: 'button', hidden: true});
        const undo = element('button', '撤销本次追加', actions, {type: 'button', disabled: true}); undo.dataset.undo = 'true';
        const text = element('textarea', '', loraBox, {readOnly: true, hidden: true, style: 'height:76px;max-height:180px'}); text.setAttribute('aria-label', '触发词追加预览');
        const resetPreview = () => { prepared = null; apply.hidden = true; text.hidden = true; };
        rows.forEach(row => { row.check.onchange = resetPreview; });
        preview.onclick = async () => {
            try {
                if (!fresh()) throw new Error('工作流已变化，请重新检查。');
                const words = [...new Set(rows.filter(r => r.check.checked).map(r => r.word))];
                if (!words.length) throw new Error('请先勾选需要的触发词。');
                writer?.dispose();
                writer = createWidgetInserter(app, {node, widget}, {commaSeparated: true, validate: valid});
                writer.onUndoInvalidated = () => {undo.disabled = true;};
                prepared = await writer.preview({text: words.join(', '), action: 'append_end'});
                if (prepared.status !== 'preview') throw new Error('目标不可直接写入，请检查原节点。');
                text.value = prepared.after; text.hidden = false; apply.hidden = false;
                status.textContent = '请核对追加后的完整提示词。';
            } catch (error) { resetPreview(); status.textContent = error.message; }
        };
        apply.onclick = async () => {
            try {
                if (!prepared || !fresh()) { resetPreview(); sync(); return; }
                const result = await writer({text: prepared.text, action: 'append_end', expectedCurrent: prepared.before});
                resetPreview(); undo.disabled = result.status !== 'inserted';
                sync();
                if (result.status !== 'inserted') status.textContent = '目标已变化，本次未写入，请重新检查。';
            } catch (error) { resetPreview(); status.textContent = error.message; }
        };
        undo.onclick = () => { const restored = writer?.undoLast(); undo.disabled = true; status.textContent = restored ? '已撤销本次追加，请重新检查。' : '目标已变化，无法撤销旧操作。'; };
    }
    refresh.onclick = async () => {
        clear(); const ticket = ++version; select.hidden = true; snapshot = '';
        if (!valid()) return;
        refresh.disabled = true; status.textContent = '正在追溯采样器连线…';
        const before = fingerprint();
        try {
            const output = await app.graphToPrompt();
            if (!valid() || ticket !== version || before !== fingerprint()) throw new Error('工作流在检查期间变化，请重试。');
            api = output.output; snapshot = before;
            const ids = new Set(branch.nodeIds.map(String));
            const candidates = Object.entries(api).filter(([id, node]) => samplers.has(node.class_type) && ids.has(id));
            select.replaceChildren();
            for (const [id, node] of candidates) element('option', `${node._meta?.title || node.class_type} #${id}`, select, {value: id});
            select.hidden = !candidates.length;
            if (!candidates.length) { status.textContent = '当前分支未发现可检查的启用采样器；暂支持顶层 KSampler / KSamplerAdvanced。'; return; }
            status.textContent = `已找到 ${candidates.length} 个采样器；下方显示所选采样器的输入。`;
            await draw().catch(error => { if (valid()) status.textContent = error.message; });
        } catch (error) { if (valid() && ticket === version) status.textContent = error.message; }
        finally { if (!disposed) refresh.disabled = false; }
    };
    select.onchange = () => draw().catch(error => { if (valid()) status.textContent = error.message; });
    return {sync, dispose() { disposed = true; ++version; clear(); root.remove(); }};
}
