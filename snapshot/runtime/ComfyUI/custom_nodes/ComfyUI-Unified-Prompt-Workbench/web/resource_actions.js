import {manageModal} from './modal_focus.js';
import {isWritableTarget,isEnabledTarget,createWidgetInserter,captureSelection,mountInsertionActions} from './prompt_target.js';
const selections=new WeakMap();
let hostApp;
const el=(tag,text,parent)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;parent?.append(node);return node;};

const portDirection=name=>/^(?:negative|negative_prompt)$/.test(name||'')?'negative':/^(?:positive|positive_prompt)$/.test(name||'')?'positive':null;

export function promptDirection(app,node,widget) {
    const explicit=portDirection(widget.name);
    if(explicit)return explicit;
    const graph=app.graph,directions=new Set(),visited=new Set(),pending=[node];
    const state=graph.extra?.uap_workbench;
    const members=state?.branches?.find(branch=>branch.id===state.activeBranch)?.nodeIds;
    const inBranch=current=>!members||members.some(id=>String(id)===String(current.id));
    while(pending.length){
        const current=pending.pop();if(visited.has(current))continue;visited.add(current);
        for(const output of current.outputs||[]){
            if(!['STRING','CONDITIONING','*'].includes(output.type)||/help|status|json/i.test(output.name||''))continue;
            for(const id of output.links||[]){
                const link=graph.links?.[id],next=link&&graph.getNodeById(link.target_id);
                if(!next||!inBranch(next))continue;
                const input=next.inputs?.[link.target_slot],direction=portDirection(input?.name);
                if(direction){directions.add(direction);continue;}
                pending.push(next);
            }
        }
    }
    if(directions.size)return directions.size===1?[...directions][0]:'unknown';
    const title=node.title||'';
    const positive=/正向|正面提示词|\bpositive\b/i.test(title),negative=/负向|负面提示词|\bnegative\b/i.test(title);
    return positive!==negative?(positive?'positive':'negative'):'unknown';
}

export function promptUsage(app,node){
    const graph=app.graph,state=graph?.extra?.uap_workbench;
    const members=state?.branches?.find(branch=>branch.id===state.activeBranch)?.nodeIds;
    const pending=[node],visited=new Set();
    while(pending.length){
        const current=pending.pop();if(visited.has(current))continue;visited.add(current);
        if(current!==node&&/^(KSampler|SamplerCustomAdvanced|UltimateSDUpscale|DetailerForEach|DetailerForEachPipe)$/.test(current.type||current.comfyClass||''))return 'generation';
        for(const output of current.outputs||[]){
            if(!['STRING','CONDITIONING','BASIC_PIPE','*'].includes(output.type)||/help|status|json/i.test(output.name||''))continue;
            for(const id of output.links||[]){
                const link=graph.links?.[id],next=link&&graph.getNodeById(link.target_id);
                if(next&&(next.mode==null||next.mode===0)&&(!members||members.some(id=>String(id)===String(next.id))))pending.push(next);
            }
        }
    }
    return 'draft';
}

export function listPromptTargets(app) {
    const targets=[];
    for(const node of app.graph?._nodes || []) {
        if(!isEnabledTarget(app,node)||/^(?:MarkdownNote|Note|ShowText\|pysssss)$/.test(node.comfyClass||node.type||''))continue;
        for(const widget of node.widgets || []) {
            if(typeof widget.value!=='string' || !/^(text|prompt|positive|negative|positive_prompt|negative_prompt|[a-z_]+_tags)$/.test(widget.name || ''))continue;
            if(widget.options?.readOnly||widget.options?.readonly||widget.inputEl?.readOnly||!isWritableTarget(app,node,widget))continue;
            const direction=promptDirection(app,node,widget);
            const usage=promptUsage(app,node);
            targets.push({node,widget,direction,usage,label:`【${usage==='generation'?'生成输入':'草稿·需采用'}】${node.title || node.type} #${node.id} / ${widget.name}${direction==='negative'?'（负向）':direction==='positive'?'（正向）':''}`});
        }
    }
    return targets.sort((a,b)=>(a.usage==='generation'?0:1)-(b.usage==='generation'?0:1));
}

export function sourceForTarget(target) {
    const input=target.widget.inputEl || target.widget.element || target.widget.input;
    return {...target,inputElement:input,selectionSnapshot:selections.get(input) || captureSelection(input,String(target.widget.value ?? ''))};
}

export function attachPromptAutocomplete(input){
    const previous=input._promptAutocompleteOwner;
    if(window.loraManagerCreateAutocomplete){
        if(previous?.modelType==='prompt'&&!previous.destroyed)return previous;
        return window.loraManagerCreateAutocomplete(input,'prompt',{showPreview:false,getScale:()=>1,formatOnBlur:false});
    }
    return previous||window.promptLibraryAutocomplete?.attach(input);
}

export function installResourceActions(app) {
    hostApp=app;
    if(!window.__uwCaptureSelection) {
        window.__uwCaptureSelection=true;
        document.addEventListener('input',event=>{
            const input=event.target;
            if(!input?.matches?.('textarea.comfy-multiline-input,textarea.input-area,#uap-daily-desk textarea') || !window.loraManagerCreateAutocomplete) return;
            const token=input.value.slice(0,input.selectionEnd).split(/[,\n]/).at(-1).trim();
            if(!/^\/library(?:\s|$)/i.test(token) || input._promptAutocompleteOwner?.modelType==='prompt') return;
            const completion=window.loraManagerCreateAutocomplete(input,'prompt',{showPreview:false,getScale:()=>1,formatOnBlur:false});
            // Hand the normal dictionary back after this explicit library lookup.
            input.addEventListener('blur',()=>completion.destroy(),{once:true});
        },true);
        for(const event of ['focusout','select','keyup','mouseup']) document.addEventListener(event,e=>{
            const snapshot=captureSelection(e.target);if(snapshot)selections.set(e.target,snapshot);
        },true);
    }
    window.unifiedWorkbenchUsePrompt=openPromptUse;
}

export async function openPromptUse(options) {
    if(!hostApp) {
        if(window.parent!==window && window.parent.unifiedWorkbenchUsePrompt)return window.parent.unifiedWorkbenchUsePrompt(options);
        if(window.opener?.unifiedWorkbenchUsePrompt)return window.opener.unifiedWorkbenchUsePrompt(options);
        throw new Error('请从 ComfyUI 统一工作台打开资源，再选择提示词目标。');
    }
    if(window.unifiedUseResourcePrompt)return window.unifiedUseResourcePrompt(options);
    if(document.getElementById('uw-prompt-use'))throw new Error('请先关闭当前提示词操作窗口。');
    const targets=listPromptTargets(hostApp);
    if(!targets.length)throw new Error('当前工作流没有已启用且可写的提示词字段。');
    const root=el('section',null,document.body);root.id='uw-prompt-use';root.setAttribute('role','dialog');root.setAttribute('aria-label','使用资源提示词');
    root.style.cssText='position:fixed;inset:16% 18%;z-index:2147483100;background:#242a34;color:#eee;border:1px solid #8290a8;border-radius:12px;padding:22px;overflow:auto;font:14px system-ui;box-shadow:0 0 0 100vmax #0008';
    el('h2',options.title || '使用资源提示词',root);
    const picker=el('select',null,root);picker.setAttribute('aria-label','提示词目标');picker.style.cssText='max-width:100%;padding:8px';
    targets.forEach((target,index)=>{const option=el('option',target.label,picker);option.value=String(index);});
    el('p','选择目标和写入方式。点击应用时重新读取资源正文。',root);
    const host=el('div',null,root);host.style.cssText='display:flex;gap:9px;flex-wrap:wrap';
    const status=el('p','',root);status.setAttribute('role','status');
    const close=el('button','返回',root);let writer;
    const select=()=>{
        writer?.dispose();host.replaceChildren();
        const target=targets[Number(picker.value)];writer=createWidgetInserter(hostApp,sourceForTarget(target),{commaSeparated:true});
        mountInsertionActions(host,writer,options.resolveText || (()=>options.text || ''),message=>{status.textContent=message;});
    };
    picker.onchange=select;select();
    close.onclick=()=>{writer?.dispose();root.remove();releaseModal();options.onClose?.();};
    const releaseModal=manageModal(root,{initialFocus:picker,onClose:()=>close.onclick()});
    return {root,close:close.onclick};
}
