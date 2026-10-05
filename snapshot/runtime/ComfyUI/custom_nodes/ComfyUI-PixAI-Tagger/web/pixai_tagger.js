import {app} from '../../../scripts/app.js';
import {api} from '../../../scripts/api.js';
import {ComfyWidgets} from '../../../scripts/widgets.js';

export function migrateGraph(value) {
    if (Array.isArray(value)) { value.forEach(migrateGraph); return; }
    if (!value || typeof value !== 'object') return;
    if (value.type === 'WD14Tagger|pysssss') {
        const old = value.widgets_values || [];
        value.type = 'PixAITagger';
        value.widgets_values = ['pixai-tagger-v1.0', 0.17, 0.27, old[3] ?? true, old[4] ?? false, old[5] ?? '', 'character,general', 0.15, 0.24, 0.17, 0.41];
        value.widgets_values_named = Object.fromEntries(['model', 'threshold', 'character_threshold', 'replace_underscore', 'trailing_comma', 'exclude_tags', 'categories', 'style_threshold', 'copyright_threshold', 'meta_threshold', 'rating_threshold'].map((name, i) => [name, value.widgets_values[i]]));
        value.properties = {...value.properties, 'Node name for S&R': 'PixAITagger'};
        delete value.properties.cnr_id;
        delete value.properties.ver;
        if (value.outputs?.length === 1) {
            value.outputs[0].name = 'tags';
            value.outputs.push({name:'scores_json', type:'STRING', links:null});
        }
    }
    for (const [key, item] of Object.entries(value)) {
        if (typeof item === 'string' && ['title', 'name', 'label', 'uap_layout_group', 'group', 'customSortAlphabet'].includes(key)) value[key] = item.replaceAll('WD14', 'PixAI');
        else if (['groups', 'safe_mute_groups'].includes(key) && Array.isArray(item)) value[key] = item.map(group => {
            if (typeof group === 'string') return group.replaceAll('WD14', 'PixAI');
            migrateGraph(group); return group;
        });
        else migrateGraph(item);
    }
}

const pending = new Map();
function showResult() {
    const dialog = document.createElement('dialog');
    dialog.style.cssText = 'width:min(700px,90vw);background:var(--comfy-menu-bg);color:var(--fg-color);border:1px solid var(--border-color);border-radius:12px;padding:20px';
    const title = document.createElement('h3'); title.textContent = 'PixAI Tagger v1.0';
    const status = document.createElement('p'); status.textContent = '正在提交标签反推…';
    const text = document.createElement('textarea'); text.readOnly = true; text.setAttribute('aria-label', 'PixAI 反推结果');
    text.style.cssText = 'width:100%;height:240px;box-sizing:border-box';
    const close = document.createElement('button'); close.textContent = '关闭'; close.onclick = () => dialog.close();
    dialog.append(title, status, text, close); document.body.append(dialog);
    dialog.addEventListener('close', () => dialog.remove(), {once:true}); dialog.showModal();
    return {status, text};
}

async function tagImage(src) {
    const query = new URL(src, location.href).searchParams;
    const filename = query.get('filename'), type = query.get('type') || 'output';
    if (!filename || !['input', 'output', 'temp'].includes(type)) throw new Error('图片路径不可用。');
    const image = `${query.get('subfolder') ? query.get('subfolder') + '/' : ''}${filename} [${type}]`;
    const view = showResult();
    try {
        const response = await api.fetchApi('/prompt', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
            client_id:api.clientId,
            prompt:{
                pixai_menu_image:{class_type:'LoadImage', inputs:{image}},
                pixai_menu_tags:{class_type:'PixAITagger', inputs:{image:['pixai_menu_image', 0], model:'pixai-tagger-v1.0', threshold:0.17, character_threshold:0.27, replace_underscore:true, trailing_comma:false, exclude_tags:''}}
            }
        })});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error?.message || '标签反推提交失败。');
        pending.set(result.prompt_id, view);
        view.status.textContent = '已加入 ComfyUI 队列，完成后显示结果。';
    } catch (error) { view.status.textContent = error.message; }
}

app.registerExtension({
    name:'local.PixAITagger',
    beforeConfigureGraph(data) { migrateGraph(data); },
    setup() {
        api.addEventListener('execution_success', async ({detail}) => {
            const view = pending.get(detail.prompt_id); if (!view) return;
            pending.delete(detail.prompt_id);
            try {
                const response = await api.fetchApi(`/history/${encodeURIComponent(detail.prompt_id)}`);
                if (!response.ok) throw new Error('结果读取失败，请在队列历史中查看。');
                const history = await response.json();
                view.text.value = (history[detail.prompt_id]?.outputs?.pixai_menu_tags?.tags || []).join('\n');
                view.status.textContent = '反推完成，可选中并复制标签。';
            } catch (error) { view.status.textContent = error.message; }
        });
        for (const event of ['execution_error', 'execution_interrupted']) api.addEventListener(event, ({detail}) => {
            const view = pending.get(detail.prompt_id); if (!view) return;
            pending.delete(detail.prompt_id); view.status.textContent = detail.exception_message || '反推已中断。';
        });
    },
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === 'PixAITagger') {
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function(message) {
                onExecuted?.apply(this, arguments);
                let widget = this.widgets?.find(item => item.name === 'tags');
                if (!widget) {
                    widget = ComfyWidgets.STRING(this, 'tags', ['STRING', {multiline:true}], app).widget;
                    widget.inputEl.readOnly = true; widget.options.serialize = false;
                }
                widget.value = (message.tags || []).join('\n'); this.onResize?.(this.size);
            };
            return;
        }
        const extraMenu = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function(_, options) {
            const result = extraMenu?.apply(this, arguments);
            const img = this.imgs?.[this.imageIndex ?? this.overIndex];
            if (img) options.push({content:'PixAI Tagger · 标签反推', callback:() => tagImage(img.src)});
            return result;
        };
    }
});
