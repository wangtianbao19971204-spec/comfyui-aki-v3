import {manageModal} from './modal_focus.js';
// A target owns its serialization; all entry points share position and undo rules.
const writers = new WeakMap();
const managedPanels = '#tb-shared-preset-panel, #tb-shared-preset-editor, #unified-tag-manager, #unified-workbench, #uw-prompt-use, #uw-reference-groups, .uw-target-actions';

export function formatEmbeddingReference(relativePath) {
    const path=String(relativePath || '').replace(/\\/g,'/');
    if(!path || /\s/.test(path)) throw new Error('Embedding 路径为空或含空格，当前提示词语法不支持；请先在模型管理中核对文件名。');
    if(path.startsWith('/') || /^[a-z]:/i.test(path) || path.split('/').some(part=>part==='..')) throw new Error('Embedding 必须使用模型目录内的相对路径。');
    return ('embedding:'+path.replace(/\.[^/.]+$/,'')).replace(/[()]/g,'\\$&');
}

export function isEnabledTarget(app, node, graph = app.graph) {
    if (!node || app.graph !== graph || graph.getNodeById(node.id) !== node || (node.mode != null && node.mode !== 0)) return false;
    const state = graph.extra?.uap_workbench;
    return !state || state.branches?.some(branch => branch.id === state.activeBranch && branch.nodeIds?.some(id => String(id) === String(node.id))) === true;
}

export function isWritableTarget(app, node, widget, graph = app.graph) {
    return isEnabledTarget(app,node,graph) && node.widgets?.includes(widget) &&
        !node.inputs?.some(input => (input.widget?.name || input.name) === widget.name && input.link != null);
}

export function commitWidget(app, node, widget, value) {
    const graph = node.graph || app.graph;
    if (widget.value === value) return;
    graph.beforeChange?.();
    try {
        widget.value = value;
        const input = widget.inputEl || widget.element || widget.input;
        if (typeof input?.value === 'string' && typeof value === 'string') input.value = value;
        widget.callback?.call(widget, value, app.canvas, node);
    } finally {
        graph.afterChange?.();
        graph.setDirtyCanvas?.(true, true);
    }
}

// Both completion providers use native undo and the same input event fallback.
export function replaceInputRange(input, text, start, end, finalCaret = start + text.length) {
    if (!input?.isConnected || !Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end < start || end > input.value.length) return false;
    input.focus(); input.setSelectionRange(start, end);
    let inserted = false;
    try { inserted = input.ownerDocument.execCommand('insertText', false, text); } catch {}
    if (!inserted) { input.setRangeText(text, start, end, 'end'); input.dispatchEvent(new Event('input', {bubbles:true})); }
    const caret = Math.max(0, Math.min(input.value.length, finalCaret));
    input.setSelectionRange(caret, caret);
    return true;
}

export function captureSelection(input, value = input?.value) {
    return typeof value === 'string' && Number.isInteger(input?.selectionStart)
        ? {value, start: input.selectionStart, end: input.selectionEnd} : null;
}

export function createTextInserter(adapter) {
    const {read, write, validate = () => true, inputElement: input, commaSeparated = false} = adapter;
    const key = adapter.key || input;
    if (key) writers.get(key)?.dispose();
    let selection = adapter.selectionSnapshot ? {...adapter.selectionSnapshot} : null;
    let busy = false, disposed = false, undo = null, invalidated = false;
    const valid = () => !disposed && validate() === true;
    const ensure = () => {if (!valid()) throw new Error('目标工作流、分支或编辑窗口已变化，请从当前目标重新打开。');};
    const sync = snapshot => {
        selection = snapshot;
        if (snapshot && typeof input?.value === 'string') {
            if (input.value !== snapshot.value) input.value = snapshot.value;
            input.setSelectionRange?.(snapshot.start, snapshot.end);
        }
    };
    const invalidate = () => {if (!busy && undo) {invalidated = true; insert.onUndoInvalidated?.();}};
    const updateSelection = () => {
        if (adapter.followSelection && input?.ownerDocument?.activeElement === input) {
            selection = captureSelection(input, read());
            setActions();
        }
    };
    const external = event => {if (!event.target?.closest?.(managedPanels)) invalidate();};
    const undoKey = event => {if ((event.ctrlKey || event.metaKey) && /^[zy]$/i.test(event.key)) invalidate();};
    const owner = input?.ownerDocument || globalThis.document;
    input?.addEventListener?.('input', invalidate);
    input?.addEventListener?.('change', invalidate);
    for (const event of ['select','keyup','mouseup','input']) input?.addEventListener?.(event, updateSelection);
    owner?.addEventListener?.('input', external, true);
    owner?.addEventListener?.('change', external, true);
    owner?.addEventListener?.('keydown', undoKey, true);
    const insert = async request => {
        if (disposed) return {status:'stale'};
        if (busy) return {status:'busy'};
        busy = true;
        try {
            await Promise.resolve(); ensure();
            const spec = typeof request === 'string' ? {text:request} : request || {};
            const text = String(spec.text ?? '');
            if (!text.trim()) return {status:'empty'};
            const current = String(read() ?? ''), action = spec.action || 'append_end';
            if (spec.expectedCurrent != null && spec.expectedCurrent !== current) throw new Error('目标正文在预览后发生变化，请重新预览。');
            if (!['append_end','append_cursor','replace_selection','replace_prompt'].includes(action)) throw new Error('未知的提示词操作');
            const snapshotCurrent = selection && (selection.value === current || adapter.equivalent?.(selection.value, current)) && Number.isInteger(selection.start) && Number.isInteger(selection.end) && selection.start >= 0 && selection.end <= current.length && selection.end >= selection.start;
            let start = current.length, end = start;
            if (action === 'append_cursor' || action === 'replace_selection') {
                if (!snapshotCurrent) throw new Error('目标正文已变化，原光标位置已失效，请重新选择。');
                if (action === 'append_cursor' && selection.start !== selection.end) throw new Error('请先定位光标，或使用替换选区。');
                if (action === 'replace_selection' && selection.start === selection.end) throw new Error('请先在当前目标中选择文本，再执行替换选区。');
                start = selection.start; end = selection.end;
            } else if (action === 'replace_prompt') {start = 0; end = current.length;}
            const left = current.slice(0,start), right = current.slice(end);
            let prefix = '', suffix = '';
            if (action !== 'replace_prompt' && commaSeparated) {
                prefix = left.trim() && !/[,\n]\s*$/.test(left) ? ', ' : left && !/\s$/.test(left) ? ' ' : '';
                suffix = right.trim() && !/^\s*[,\n]/.test(right) ? ', ' : '';
            } else if (action === 'append_end' && current) prefix = ', ';
            const next = left + prefix + text + suffix + right;
            if (spec.preview === true) return {status:'preview',before:current,affected:current.slice(start,end),after:next,start,end,text,action};
            if (next === current) return {status:'unchanged'};
            const beforeSelection = snapshotCurrent ? {...selection} : null;
            write(next);
            if (adapter.settleWrite) await adapter.settleWrite();
            ensure();
            const committed = read();
            if (committed !== next && !adapter.equivalent?.(committed, next)) {undo = null; throw new Error('目标在写入时改变了正文，请返回目标核对。');}
            const cursor = start + prefix.length + text.length;
            if (selection) sync({value:committed,start:action === 'replace_selection' ? start : cursor,end:cursor});
            invalidated = false;
            undo = {before:current,after:committed,beforeSelection};
            return {status:'inserted',action,text};
        } finally {busy = false;}
    };
    insert.undoLast = () => {
        if (!undo || invalidated || !valid() || (read() !== undo.after && !adapter.equivalent?.(read(), undo.after))) return false;
        busy = true;
        try {const item = undo; write(item.before); sync(item.beforeSelection); undo = null; return true;}
        finally {busy = false;}
    };
    insert.readCurrentText = () => {ensure(); return String(read() ?? '');};
    insert.preview = request => insert({...request,preview:true});
    insert.reviewInsert = request => reviewInsertion(insert,request);
    insert.onUndoInvalidated = null;
    const setActions = () => {
        insert.supportsActions = ['append_end','replace_prompt'];
        if (adapter.followSelection) insert.supportsActions.push('append_cursor','replace_selection');
        else if (selection && Number.isInteger(selection.start)) insert.supportsActions.push(selection.start === selection.end ? 'append_cursor' : 'replace_selection');
    };
    insert.dispose = () => {
        disposed = true;
        input?.removeEventListener?.('input',invalidate); input?.removeEventListener?.('change',invalidate);
        for (const event of ['select','keyup','mouseup','input']) input?.removeEventListener?.(event,updateSelection);
        owner?.removeEventListener?.('input',external,true); owner?.removeEventListener?.('change',external,true); owner?.removeEventListener?.('keydown',undoKey,true);
        if (key && writers.get(key) === insert) writers.delete(key);
    };
    if (key) writers.set(key,insert);
    setActions();
    return insert;
}

export function createWidgetInserter(app, source, options = {}) {
    const graph = app.graph, graphId = graph.id, {node,widget} = source;
    const token = node._uwPromptTargetToken ||= crypto.randomUUID();
    const inputElement = source.inputElement || widget.inputEl || widget.element || widget.input;
    return createTextInserter({
        key:widget,inputElement,selectionSnapshot:source.selectionSnapshot ?? captureSelection(inputElement,String(widget.value ?? '')),
        commaSeparated:options.commaSeparated === true,
        read:() => String(widget.value ?? ''), write:value => commitWidget(app,node,widget,value),
        validate:() => app.graph === graph && graph.id === graphId && isWritableTarget(app,node,widget,graph) && node._uwPromptTargetToken === token &&
            (!source.validateTarget || source.validateTarget() === true) && (!options.validate || options.validate() === true),
    });
}

export function mountInsertionActions(host, onInsert, textProvider, report = () => {}, onApplied = null) {
    host.classList.add('uw-target-actions');
    const labels = {append_end:'追加末尾',append_cursor:'插入光标',replace_selection:'替换选区',replace_prompt:'替换全文'};
    const picker = document.createElement('select'); picker.setAttribute('aria-label','提示词写入方式');
    for (const action of onInsert.supportsActions || ['append_end']) {
        const option = document.createElement('option'); option.value = action; option.textContent = labels[action]; picker.append(option);
    }
    if(onInsert.supportsActions?.includes(onInsert.defaultAction))picker.value=onInsert.defaultAction;
    const apply = document.createElement('button'); apply.textContent = '应用到目标';
    const undo = document.createElement('button'); undo.textContent = '撤销本次写入'; undo.disabled = true;
    const preview = document.createElement('div'); preview.className='uw-replace-preview'; preview.hidden=true;
    let reviewed=null;
    const resetPreview=()=>{reviewed=null;preview.hidden=true;apply.textContent=picker.value.startsWith('replace_')?'预览替换':'应用到目标';};
    picker.addEventListener('change',resetPreview);resetPreview();
    apply.onclick = async () => {
        apply.disabled = true;
        try {
            const text = await textProvider();
            if(picker.value.startsWith('replace_')&&onInsert.preview){
                const next=await onInsert.preview({text,action:picker.value});
                if(next?.status!=='preview')throw new Error('目标不可用，请重新选择。');
                if(!reviewed||reviewed.before!==next.before||reviewed.text!==text||reviewed.action!==picker.value||reviewed.start!==next.start||reviewed.end!==next.end){
                    reviewed=next;preview.replaceChildren();preview.hidden=false;
                    for(const[label,value]of [['将被替换的内容',next.affected||'（空）'],['替换后的完整提示词',next.after]]){const title=document.createElement('strong'),body=document.createElement('pre');title.textContent=label;body.textContent=value;preview.append(title,body);}
                    apply.textContent='确认替换';report('请核对受影响内容，再确认替换。');return;
                }
            }
            const result = await onInsert({text,action:picker.value,...(reviewed?{expectedCurrent:reviewed.before}:{})});
            if (result?.status !== 'inserted' && result?.status !== 'unchanged') throw new Error('目标不可用或未选择内容，请重新打开。');
            undo.disabled = result.status !== 'inserted' || !onInsert.undoLast;
            report(result.status === 'inserted' ? '已应用到目标。' : '正文未变化。');
            resetPreview();
            if(result.status === 'inserted')await onApplied?.(result);
        } catch(error) {report(error.message);}
        finally {apply.disabled = false;}
    };
    undo.onclick = () => {const done = onInsert.undoLast?.(); undo.disabled = true; report(done ? '已撤销本次写入。' : '目标已变化，无法撤销旧操作。');};
    onInsert.onUndoInvalidated = () => {undo.disabled = true;};
    host.append(picker,apply,undo,preview);
    return {picker,apply,undo};
}

// Legacy card actions share the same range calculation and guarded commit.
export async function reviewInsertion(onInsert,request){
    if(!request?.action?.startsWith('replace_')||!onInsert.preview)return onInsert(request);
    if(document.getElementById('uw-replacement-review'))return {status:'busy'};
    let preview=await onInsert.preview(request);if(preview.status!=='preview')return preview;
    const root=document.createElement('section');root.id='uw-replacement-review';root.className='uw-target-actions';root.setAttribute('role','dialog');root.setAttribute('aria-label','确认提示词替换');
    root.style.cssText='position:fixed;inset:8% max(12px,15%);z-index:2147483100;overflow:auto;background:#202631;color:#eef;padding:20px;border:1px solid #9182a5;border-radius:10px;box-shadow:0 0 0 100vmax #0008';
    const content=document.createElement('div'),note=document.createElement('p'),actions=document.createElement('footer'),confirm=document.createElement('button'),cancel=document.createElement('button');
    confirm.textContent='确认替换';cancel.textContent='取消';actions.style.cssText='position:sticky;bottom:0;background:#202631;display:flex;gap:10px;padding:12px';actions.append(confirm,cancel);root.append(content,note,actions);document.body.append(root);
    const draw=()=>{content.replaceChildren();for(const[label,value]of [['将被替换的内容',preview.affected||'（空）'],['替换后的完整提示词',preview.after]]){const h=document.createElement('h3'),p=document.createElement('pre');h.textContent=label;p.textContent=value;p.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere';content.append(h,p);}};draw();
    return new Promise(resolve=>{
        const finish=result=>{root.remove();releaseModal();resolve(result);};cancel.onclick=()=>finish({status:'cancelled'});
        const releaseModal=manageModal(root,{initialFocus:confirm,onClose:()=>{if(!cancel.disabled)cancel.onclick();}});
        root.onkeydown=event=>{if(event.key==='Escape'&&!event.isComposing){event.preventDefault();event.stopPropagation();if(!cancel.disabled)cancel.onclick();}};
        confirm.onclick=async()=>{confirm.disabled=true;cancel.disabled=true;try{
            await request.validatePreview?.();const next=await onInsert.preview(request);if(next.status!=='preview')throw new Error('目标已失效，请取消后重新选择。');
            if(next.before!==preview.before||next.start!==preview.start||next.end!==preview.end){preview=next;draw();note.textContent='目标已改变，已更新预览，请重新核对。';return;}
            finish(await onInsert({...request,expectedCurrent:preview.before}));
        }catch(error){note.textContent=error.message;}finally{confirm.disabled=false;cancel.disabled=false;}};
    });
}
