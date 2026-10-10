// A saved workflow opens in its own ComfyUI tab; existing graphs stay intact.
export const REPAIR_PATH = 'workflows/生产扩展_丝袜纹理修复.json';
export const MAIN_PATH = 'workflows/UAP统一生产工作台_v2.json';
export const REPAIR_CHOICE = '@workflow:stocking';

export function workflowChoices(config) {
    const choices=(config?.branches||[]).map(b=>({value:b.id,label:b.label}));
    if(choices.some(b=>b.value==='stocking')) {
        return [
            {value:'@main',label:'返回统一生产工作台'},
            {value:'@main:ext05',label:'裁剪精修'},
            ...choices,
            {value:'@main:ext08',label:'2× 放大'},
            {value:'@main:ext09',label:'4× 放大'},
        ];
    }
    const before=choices.findIndex(b=>b.value==='ext08'||b.value==='ext09');
    choices.splice(before<0?choices.length:before,0,{value:REPAIR_CHOICE,label:'丝袜纹理修复'});
    return choices;
}

export function isWorkflowChoice(value) { return value===REPAIR_CHOICE||/^@main(?::ext0[589])?$/.test(value); }

let opening=false;
export async function openWorkflowChoice(app,value) {
    if(!isWorkflowChoice(value))throw new Error('未知的独立工作流。');
    if(opening)return false;
    const store=app.extensionManager?.workflow;
    if(!store?.syncWorkflows||!store?.getWorkflowByPath||!app.loadGraphData)
        throw new Error('工作流列表尚未就绪，请从左侧工作流列表打开。');
    opening=true;
    try {
        const previous=app.graph,active=store.activeWorkflow;
        await store.syncWorkflows();
        const unchanged=()=>app.graph===previous&&store.activeWorkflow===active;
        if(!unchanged())throw new Error('工作流已变化，请重新选择入口。');
        const path=value===REPAIR_CHOICE?REPAIR_PATH:MAIN_PATH;
        const workflow=store.getWorkflowByPath(path);
        if(!workflow)throw new Error('找不到 '+path.split('/').at(-1)+'，请确认已安装独立工作流。');
        // Match ComfyUI's workflow service: the store's openWorkflow only sets
        // tab metadata. Passing the workflow to loadGraphData also preserves
        // the outgoing change tracker and restores the selected tab's draft.
        const fromDisk=!workflow.isLoaded;
        if(fromDisk)await workflow.load();
        if(!unchanged())throw new Error('工作流已变化，请重新选择入口。');
        await app.loadGraphData(JSON.parse(JSON.stringify(workflow.activeState)),true,true,workflow,
            {checkForRerouteMigration:false,deferWarnings:true,skipAssetScans:!fromDisk});
        const branch=value.startsWith('@main:')?value.split(':')[1]:null;
        if(branch) {
            if(!app.graph?.extra?.uap_workbench?.branches?.some(b=>b.id===branch))
                throw new Error('已打开工作流，但其中没有对应分支。');
            window.unifiedUapNavigation.activateBranch(branch);
        }
        return true;
    } finally { opening=false; }
}

export function stockingProject(node) {
    try { return JSON.parse(node?.widgets?.find(w=>w.name==='project_json')?.value||'{}'); }
    catch { return {}; }
}

export function mountStockingControls(host,{app,node,element,isCurrent}) {
    const section=element('section',null,host,{className:'desk-stocking'});
    section.dataset.deskArea='parameters';
    element('h3','丝袜纹理修复',section);
    element('p','打开编辑器，导入 PNG / JPG / PSD；双腿分别修边，检查袜口、脚部与遮挡边界，为每个部位画走向线。调整纹理后点击“应用到节点”。',section);
    const button=element('button','打开修复编辑器',section,{type:'button'});
    const status=element('p','',section);status.setAttribute('role','status');
    button.onclick=()=>{
        if(!isCurrent()) {status.textContent='工作流已变化，请重新打开控制台。';return;}
        const editor=node.widgets?.find(w=>w.name==='打开完整编辑器');
        if(!editor?.callback) {status.textContent='完整编辑器尚未加载，请刷新页面。';return;}
        editor.callback();
    };
    element('p','应用后运行本工作流，同时保存成品和透明丝袜图层。需要继续放大时，在任务列表选择 2× 或 4× 放大并载入成品。',section);
    element('p','摩尔纹默认关闭；开启前先在编辑器中完成深度计算。油光仍为试验效果，建议从低强度开始预览。',section);
    const sync=()=>{
        const project=stockingProject(node);
        status.textContent=project.asset?`已应用：${project.name||'图片'} · ${project.regions?.length||0} 个部位`:'尚未应用图片；请先在编辑器中完成导入和应用。';
        button.disabled=!isCurrent();
    };
    sync();return sync;
}
