import {api} from '../../../scripts/api.js';
import {commitWidget} from './prompt_target.js';
import {mountControlSwitches} from './control_switches.js';

const children = owner => owner?.subgraph?._nodes || owner?.subgraph?.nodes || [];
const widget = (node, name) => node?.widgets?.find(item => item.name === name);
export const controlChoices = [
    ['PyraCannyPreprocessor', '细致线稿'], ['HEDPreprocessor', '柔和线稿'],
    ['Manga2Anime_LineArt_Preprocessor', '漫画线稿'], ['DepthAnythingV2Preprocessor', '深度图'],
];

export function controlNodes(owner) {
    const roles = owner?.properties?.anima_control_roles || {};
    return Object.fromEntries(Object.entries(roles).map(([role, id]) =>
        [role, children(owner).find(node => String(node.id) === String(id))]));
}

export function mountAnimaControl(host, app, branch, nodes, isCurrent) {
    const owner = nodes.find(node => node.properties?.uap_anima_control);
    if (!owner) return {sync() {}, dispose() {}};
    const graph = app.graph, controls = controlNodes(owner), rows = [];
    let disposed = false, uploading = false;
    const current = () => !disposed && isCurrent() && app.graph === graph &&
        graph.extra?.uap_workbench?.activeBranch === branch.id && graph.getNodeById(owner.id) === owner;
    const valid = (node, value) => current() && children(owner).includes(node) &&
        node.widgets?.includes(value) && !node.inputs?.some(port => port.name === value.name && port.link != null);
    const el = (tag, text, parent, attrs = {}) => {
        const item = document.createElement(tag); if (text) item.textContent = text;
        Object.assign(item, attrs); parent.append(item); return item;
    };
    const box = el('section', '', host, {className: 'desk-anima-control'});
    box.dataset.deskArea = 'parameters';
    const switches = mountControlSwitches(box, app, branch, isCurrent);
    el('h3', '姿态与构图控制', box);
    el('small', '从参考图提取线稿或深度图；只处理选中的方式。', box);
    const grid = el('div', '', box, {className: 'fields'});
    function bind(parent, node, name, label, options) {
        const value = widget(node, name); if (!value) return;
        const row = el('label', '', parent, {className: 'field'}); el('span', label, row);
        let choices = options || value.options?.values;
        if (typeof choices === 'function') choices = choices();
        const select = Array.isArray(choices);
        const input = el(select ? 'select' : 'input', '', row);
        input.setAttribute('aria-label', label);
        if (select) {
            for (const option of choices) {
                const [key, title] = Array.isArray(option) ? option : [option, option];
                el('option', String(title), input, {value: String(key)});
            }
        } else {
            input.type = 'number'; input.step = String(value.options?.step ? value.options.step / 10 : 'any');
            input.required = true;
            if (Number.isFinite(value.options?.min)) input.min = value.options.min;
            if (Number.isFinite(value.options?.max)) input.max = value.options.max;
        }
        input.onchange = () => {
            if (!valid(node, value) || !input.checkValidity()) return;
            const next = select ? input.value : Number(input.value);
            if (!select && (!input.value.trim() || !Number.isFinite(next))) return;
            commitWidget(app, node, value, next); sync();
        };
        rows.push(() => {
            input.disabled = !valid(node, value);
            if (select && ![...input.options].some(option => option.value === String(value.value)))
                el('option', String(value.value), input, {value: String(value.value)});
            if (document.activeElement !== input) input.value = String(value.value);
        });
        return input;
    }
    const reference = controls.reference, imageWidget = widget(reference, 'image');
    const referencePicker = bind(grid, reference, 'image', '姿态参考图');
    const upload = el('input', '', box, {type: 'file', accept: 'image/*', hidden: true});
    const uploadButton = el('button', '上传参考图', box, {type: 'button'});
    uploadButton.onclick = () => upload.click();
    const status = el('small', '', box); status.setAttribute('role', 'status');
    upload.onchange = async () => {
        const file = upload.files?.[0]; if (!file || uploading || !valid(reference, imageWidget)) return;
        uploading = true; sync();
        try {
            const body = new FormData(); body.append('image', file); body.append('type', 'input');
            const response = await api.fetchApi('/upload/image', {method: 'POST', body});
            if (!response.ok) throw new Error('参考图上传失败。');
            const data = await response.json();
            if (!valid(reference, imageWidget)) throw new Error('工作流已切换；图片已上传，请在新流程中重新选择。');
            const name = (data.subfolder ? data.subfolder + '/' : '') + data.name;
            if (Array.isArray(imageWidget.options?.values) && !imageWidget.options.values.includes(name)) imageWidget.options.values.push(name);
            if (referencePicker && ![...referencePicker.options].some(option => option.value === name)) el('option', name, referencePicker, {value: name});
            commitWidget(app, reference, imageWidget, name); status.textContent = '参考图已更新。';
        } catch (error) { if (!disposed) status.textContent = error.message; }
        finally { uploading = false; upload.value = ''; sync(); }
    };
    bind(grid, controls.preprocessor, 'preprocessor', '控制方式', controlChoices);
    bind(grid, controls.apply, 'strength', '控制强度');
    const preview = el('img', '', box, {alt: '最终控制图', hidden: true});
    preview.style.cssText = 'max-width:100%;max-height:300px;object-fit:contain;margin:8px auto';
    const previewHint = el('small', '执行控制分支后，这里显示最终控制图。', box);
    const details = el('details', '', box);
    el('summary', '高级 · 时段与权重', details);
    const edit = el('button', '打开擦线与导出子图', details, {type: 'button'});
    edit.onclick = () => { if (current()) app.canvas.openSubgraph(controls.advanced.subgraph); };
    const advancedGrid = el('div', '', details, {className: 'fields'});
    bind(advancedGrid, controls.preprocessor, 'resolution', '控制图分辨率');
    bind(advancedGrid, controls.apply, 'start_percent', '控制开始');
    bind(advancedGrid, controls.apply, 'end_percent', '控制结束');
    bind(advancedGrid, controls.loader, 'lllite_name', '控制权重');
    el('small', '取消勾选会直接使用预处理图，原遮罩与导出设置仍保留。擦线用于线稿；深度图建议关闭，黑色覆盖区域可能生成额外的空间结构。', details);
    function sync() {
        if (disposed) return;
        switches.sync(); edit.disabled = !current();
        uploadButton.disabled = uploading || !imageWidget || !valid(reference, imageWidget);
        rows.forEach(update => update());
        const picture = app.nodeOutputs?.[`${owner.subgraph.id}:${controls.preview?.id}`]?.images?.[0];
        const source = picture && api.apiURL('/view?' + new URLSearchParams({
            filename: picture.filename, subfolder: picture.subfolder || '', type: picture.type || 'temp',
        }));
        preview.hidden = !source; previewHint.hidden = !!source;
        if (source && preview.src !== source) preview.src = source;
    }
    const completed = () => { if (current()) sync(); };
    api.addEventListener('execution_success', completed);
    sync();
    return {sync, dispose() {disposed = true; switches.dispose(); api.removeEventListener('execution_success', completed);}};
}
