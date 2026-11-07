import {commitWidget} from './prompt_target.js';
import {taskPlan} from './task_activity.js';
import {mountAnimaControl} from './anima_control.js';
import {mountControlSwitches} from './control_switches.js';

const modelPath=value=>String(value||'').replace(/\\/g,'/');
export function modelOptionIssue(name,value,branch,contracts){
    if(!branch?.modelFamily||!['unet_name','clip_name','vae_name'].includes(name))return '';
    const family=contracts?.families?.[branch.modelFamily],path=modelPath(value);
    if(!family)return '当前工作流缺少已核验的模型配套清单，请保存未完成编辑后加载最新版 UAP。';
    if(name==='unet_name'){const known=contracts?.models?.[path];return !known||known.family===branch.modelFamily?'':`${family.label} 分支只能加载同架构底模；此文件登记为 ${known.family}。`;}
    return family[name==='clip_name'?'clip':'vae'].includes(path)?'':`${family.label} 的${name==='clip_name'?'文本编码器':'VAE'}不匹配已核验组合。`;
}

export function modelCompatibilityIssue(nodes,branch,contracts){
    if(!branch?.modelFamily||!nodes.some(node=>node.type==='UNETLoader'&&node.mode===0))return '';
    for(const [type,name] of [['UNETLoader','unet_name'],['CLIPLoader','clip_name'],['VAELoader','vae_name']]){
        const node=nodes.find(node=>node.type===type&&node.mode===0);
        if(!node)return `当前分支缺少启用的 ${type}，请恢复本分支模型组合。`;
        if(node.inputs?.some(input=>input.name===name&&input.link!=null))return '模型名称由连线提供，配套检查无法确认；请在模型节点中直接选择已核验组合。';
        const issue=modelOptionIssue(name,node.widgets?.find(widget=>widget.name===name)?.value,branch,contracts);
        if(issue)return issue;
        if(type==='CLIPLoader'){
            if(node.inputs?.some(input=>input.name==='type'&&input.link!=null))return '文本编码器类型由连线提供，无法确认配套。';
            if(node.widgets?.find(widget=>widget.name==='type')?.value!==contracts.families[branch.modelFamily].clip_type)return '文本编码器 type 与当前模型族不匹配，请从原节点恢复配套类型。';
        }
    }
    return '';
}

export function legacyControlIssue(nodes) {
    const model=nodes.find(node=>node.type==='UNETLoader');
    const linked=model?.inputs?.some(input=>input.name==='unet_name'&&input.link!=null);
    const name=String(model?.widgets?.find(w=>w.name==='unet_name')?.value||'');
    if(linked)return '基模名称由连线输入，无法确认 LLLite 兼容性；请先断开模型名连线并选择已核对的基模。';
    return /anima[-_ .]?2[._ ]?9|2\.9b|29b/i.test(name)?'Anima 2.9B 是 40 层；此处的原版 28 层 LLLite 不兼容。请关闭线稿/姿态和 VNCCS 控制，或切换兼容的原版基模。':'';
}

export function refinementBatchIssue(nodes) {
    for(const node of nodes){
        const batch=node.widgets?.find(w=>w.name==='batch_size');
        if(node.mode!==0||!batch)continue;
        if(node.inputs?.some(input=>input.name==='batch_size'&&input.link!=null))return '细化要求单任务 batch = 1；批量数由连线输入，无法确认，请改用固定单张输入。';
        if(Number(batch.value)!==1)return '部位细化不支持单任务多图 batch。请把“批量”设为 1；多张可排队多个单张任务。';
    }
    return '';
}

export function workflowGuardIssue(nodes,branch,contracts) {
    const active=nodes.filter(node=>node.mode===0);
    const modelIssue=modelCompatibilityIssue(nodes,branch,contracts);if(modelIssue)return modelIssue;
    if(active.some(node=>node.properties?.uap_legacy_lllite||node.type==='AnimaLLLiteApply_sdscripts')){
        const issue=legacyControlIssue(nodes);if(issue)return issue;
    }
    const parts=active.filter(node=>node.properties?.uap_refinement);
    if(parts.length){
        const issue=refinementBatchIssue(nodes);if(issue)return issue;
        const presets=parts.map(node=>node.properties?.uap_exclusive_refinement).filter(Boolean);
        if(new Set(presets).size!==presets.length)return '区域细化“标准”和“快速”只能选一个，请关闭其中一个，避免重复重绘。';
    }
    return '';
}

const guardedApps=new WeakSet();
export function installWorkflowGuard(app) {
    if(guardedApps.has(app))return;
    guardedApps.add(app);
    const queuePrompt=app.queuePrompt;
    app.queuePrompt=async function(...args){
        const graph=app.rootGraph||app.graph;
        const config=graph?.extra?.uap_workbench;
        const scopes=config?.branches?.map(branch=>({branch,nodes:branch.nodeIds.map(id=>graph.getNodeById(id)).filter(Boolean)}))
            ||(graph?.extra?.uap_refinement_workflow?[{nodes:graph._nodes}]:[]);
        for(const {nodes,branch} of scopes){
            const issue=workflowGuardIssue(nodes,branch,graph?.extra?.uap_model_contracts);
            if(issue){app.ui?.dialog?.show(issue);return false;}
        }
        if(config&&!Array.isArray(args[2]?.queueNodeIds)){
            const plan=taskPlan(app,'generate');
            if(plan.reason){app.ui?.dialog?.show(plan.reason);return false;}
            args[2]={...args[2],queueNodeIds:plan.queueNodeIds};
        }
        return queuePrompt.apply(this,args);
    };
}

export function cleanupMode(nodes) {
    const values=nodes.flatMap(node=>['offload_model','offload_cache'].map(name=>node.widgets?.find(w=>w.name===name)?.value));
    if (!values.length) return 'custom';
    return values.every(v=>v===false)?'resident':values.every(v=>v===true)?'release':'custom';
}

export function mountModelSwitch(host,app,branch,nodes,isCurrent){
    const graph=app.graph, graphId=graph.id;
    const modelNode=nodes.find(node=>node.type==='UNETLoader'&&node.mode===0);
    if(!modelNode)return null;
    const element=(tag,text,parent,attrs={})=>{const el=document.createElement(tag);if(text)el.textContent=text;Object.assign(el,attrs);parent.append(el);return el;};
    let disposed=false, signature='';
    const current=()=>!disposed&&isCurrent()&&app.graph===graph&&graph.id===graphId&&graph.extra?.uap_workbench?.activeBranch===branch.id;
    const widget=()=>modelNode.widgets?.find(item=>item.name==='unet_name');
    const writable=()=>current()&&app.graph.getNodeById(modelNode.id)===modelNode&&modelNode.mode===0&&!modelNode.inputs?.some(input=>input.name==='unet_name'&&input.link!=null);
    const box=element('section','',host);box.dataset.deskArea='models';
    const heading=element('h3','底模快切 · 当前分支',box);
    const refresh=element('button','刷新列表',heading,{type:'button',className:'jump'});
    const row=element('div','',box,{className:'plugin-tools'});
    const label=element('label','基础模型',row,{className:'switch'});
    const select=element('select','',label);
    select.setAttribute('aria-label','切换当前分支底模');
    const note=element('small','',box);note.setAttribute('role','status');
    element('small','只改本分支 UNETLoader 的 unet_name；步数、CFG、编码器与 LoRA 不随之变化。放进 models/diffusion_models 的底模刷新后即可选中。',box);
    select.onchange=()=>{
        const item=widget();
        if(!writable()||!item){sync();note.textContent='分支未启用或模型名由连线控制，请在原节点调整。';return;}
        if(select.value===String(item.value))return;
        const issue=modelOptionIssue('unet_name',select.value,branch,graph.extra?.uap_model_contracts);
        if(issue){select.value=String(item.value);note.textContent=issue;return;}
        commitWidget(app,modelNode,item,select.value);
        sync();note.textContent='已切换到 '+select.value+'；采样参数不随底模自动调整。';
    };
    refresh.onclick=async()=>{
        try{
            const response=await fetch('/object_info/UNETLoader',{cache:'no-store'});
            if(!response.ok)throw new Error('HTTP '+response.status);
            const values=(await response.json())?.UNETLoader?.input?.required?.unet_name?.[0];
            if(!Array.isArray(values)||!values.length)throw new Error('模型列表为空');
            const item=widget();
            if(item)item.options={...item.options,values};
            signature='';sync();
            note.textContent='已刷新：本机列表 '+values.length+' 个底模。';
        }catch(error){note.textContent='刷新失败：'+error.message;}
    };
    function sync(){
        if(disposed)return;
        const item=widget();
        if(!item){select.disabled=true;note.textContent='当前分支的底模节点缺少 unet_name 控件。';return;}
        const raw=typeof item.options?.values==='function'?item.options.values():item.options?.values;
        const available=Array.isArray(raw)?raw.map(String):[],value=String(item.value??'');
        const key=available.join('\u0000')+'\u0001'+value;
        if(key!==signature){
            signature=key;select.replaceChildren();
            if(value&&!available.includes(value)){const option=element('option',value+'（当前文件不可用）',select,{value});option.disabled=true;}
            for(const item2 of available){
                const option=element('option',item2,select,{value:item2});
                if(modelOptionIssue('unet_name',item2,branch,graph.extra?.uap_model_contracts)){option.disabled=true;option.textContent=item2+'（架构不符）';}
            }
        }
        select.value=value;
        select.disabled=!available.length||!writable();
        note.textContent=!current()?'浏览未启用分支；启用后可切换。':!available.length?'本地模型列表为空，请点“刷新列表”。':modelOptionIssue('unet_name',value,branch,graph.extra?.uap_model_contracts)||'当前：'+value;
    }
    sync();
    return {sync,dispose(){disposed=true;}};
}

export function mountRuntimeControls(host, app, branch, nodes, isCurrent) {
    const animaControl=mountAnimaControl(host,app,branch,nodes,isCurrent);
    const kreaControl=nodes.some(node=>node.properties?.uap_anima_control)?null:mountControlSwitches(host,app,branch,isCurrent);
    const graph=app.graph, graphId=graph.id;
    const cleanups=nodes.filter(node=>node.type==='VRAMCleanup');
    const model=nodes.find(node=>node.type==='UNETLoader');
    const needsControlHint=branch.id==='a29'||nodes.some(node=>/LLLite/.test(node.type+' '+(node.title||'')));
    const element=(tag,text,parent,attrs={})=>{const el=document.createElement(tag);if(text)el.textContent=text;Object.assign(el,attrs);parent.append(el);return el;};
    let disposed=false,busy=false;
    const current=()=>!disposed&&isCurrent()&&app.graph===graph&&graph.id===graphId&&graph.extra?.uap_workbench?.activeBranch===branch.id;
    const writable=()=>current()&&cleanups.length>0&&cleanups.every(node=>graph.getNodeById(node.id)===node&&node.mode===0&&['offload_model','offload_cache'].every(name=>node.widgets?.some(w=>w.name===name)&&!node.inputs?.some(input=>input.name===name&&input.link!=null)));
    let unload,release,status,hint;
    if(cleanups.length){
        const box=element('section','',host);box.dataset.deskArea='parameters';
        element('h3','连续出图 · 显存释放',box);
        const row=element('div','',box,{className:'plugin-tools'});
        const label=element('label','',row,{className:'switch'});
        unload=element('input','',label,{type:'checkbox'});unload.setAttribute('aria-label','出图后卸载模型');
        element('span','出图后卸载模型',label);
        status=element('small','',box);status.setAttribute('role','status');
        unload.onchange=()=>{
            if(!writable()){status.textContent='分支、清理节点或输入已变化，请刷新控制台。';sync();return;}
            const enabled=unload.checked;
            for(const node of cleanups)for(const name of ['offload_model','offload_cache'])commitWidget(app,node,node.widgets.find(w=>w.name===name),enabled);
            status.textContent=enabled?'本分支每张完成后卸载模型并清缓存。':'本分支保留模型供下一张复用；这会继续占用显存。';
        };
        release=element('button','立即释放模型与缓存',row,{type:'button'});
        release.onclick=async()=>{
            if(!current()||busy)return;
            busy=true;sync();
            try{
                const response=await fetch('/queue',{cache:'no-store'});
                if(!response.ok)throw new Error('无法核对队列，请稍后重试。');
                const queue=await response.json();
                if(!Array.isArray(queue.queue_running)||!Array.isArray(queue.queue_pending))throw new Error('队列状态不完整，请稍后重试。');
                if(queue.queue_running.length||queue.queue_pending.length)throw new Error('队列仍有任务，完成后再释放。');
                if(!current())throw new Error('当前分支已变化，请重新打开控制台。');
                const freed=await fetch('/free',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({unload_models:true,free_memory:true})});
                if(!freed.ok)throw new Error('释放请求失败，请稍后重试。');
                if(!disposed)status.textContent='已提交释放请求；后端空闲时处理。下一张会重新加载模型。';
            }catch(error){if(!disposed)status.textContent=error.message;}
            finally{busy=false;sync();}
        };
        element('small','勾选：本分支每张出图后卸载模型并清缓存；不勾选：保留模型。立即释放按钮用于现在清理整个后端。',box);
    }
    if(needsControlHint){
        const box=element('section','',host);box.dataset.deskArea='models';
        element('h3','Anima 控制兼容性',box);hint=element('small','',box);hint.setAttribute('role','status');
    }
    let modelStatus;
    if(branch.modelFamily){
        const box=element('section','',host);box.dataset.deskArea='models';
        element('h3','模型配套检查',box);modelStatus=element('small','',box);modelStatus.setAttribute('role','status');
    }
    const modelSwitch=mountModelSwitch(host,app,branch,nodes,isCurrent);
    if(nodes.some(node=>node.properties?.uap_refinement)){
        const box=element('section','',host);box.dataset.deskArea='parameters';
        element('h3','细化与二放 · 参数范围',box);
        element('small','手、脚、脸、眼独立开关；区域标准/快速二选一。细化时单任务批量须为 1，多张请排队多个单张任务。主采样、各细化子图和二放的步数/CFG/降噪/种子独立，不会自动同步；复现终稿须分别固定各阶段种子。',box);
    }
    function sync(){
        if(disposed)return;
        animaControl.sync();
        kreaControl?.sync();
        if(modelStatus){const issue=modelCompatibilityIssue(nodes,branch,graph.extra?.uap_model_contracts);modelStatus.textContent=!current()?'浏览未启用分支；启用后检查实际模型组合。':issue||'底模与 VAE 属于本分支家族；编码器文件/type 与 VAE 需配套。新底模只需放进 models/diffusion_models，刷新即可选中；此检查不保证 LoRA 兼容性或画质。';modelStatus.dataset.valid=String(!issue);}
        modelSwitch?.sync();
        if(unload){
            const mode=cleanupMode(cleanups);
            unload.checked=mode==='release';unload.indeterminate=mode==='custom';
            unload.title=mode==='custom'?'当前清理设置不一致；勾选统一卸载，取消统一保留。':'';
            unload.disabled=busy||!writable();release.disabled=busy||!current();
        }
        if(hint){
            const name=String(model?.widgets?.find(w=>w.name==='unet_name')?.value||'');
            const linked=model?.inputs?.some(input=>input.name==='unet_name'&&input.link!=null);
            const known29=!linked&&/anima[-_ ]?2[._]?9|2\.9b|29b/i.test(name);
            hint.textContent=known29&&nodes.some(node=>node.properties?.uap_native_lllite)?'此流程使用原生控制链与自动层映射；需要启用 Anima LoRA/ControlNet 兼容补丁。控制效果取决于参考图、方式和强度。':known29?'当前为 Anima 2.9B（40 层）；此旧流程仍使用原版 28 层 LLLite。请加载已适配的控制流程，或关闭线稿/姿态和 VNCCS 控制。':'LLLite 必须与实际基模的层数及权重版本匹配。当前模型未在此确认；请核对基模与控制权重，不据此认定兼容。';
        }
    }
    sync();return {sync,dispose(){disposed=true;animaControl.dispose();kreaControl?.dispose();modelSwitch?.dispose();}};
}
