// A saved workflow opens in its own ComfyUI tab; existing graphs stay intact.
export const K2_PATH = 'workflows/Krea2_精简生产_v1.json';
export const MOSS_PATH = 'workflows/MOSS_精简生产_v1.json';
export const EXT04_PATH = 'workflows/生产扩展_04_Krea2_指令编辑.json';
export const CAPTION_PATH = 'workflows/工具_图片反推_提示词提取.json';
export const EXT06_PATH = 'workflows/生产扩展_06_透明素材_抠图导出.json';
export const EXT08_PATH = 'workflows/生产扩展_08_超分_二倍交付.json';
export const EXT09_PATH = 'workflows/生产扩展_09_超分_四倍素材.json';
export const REPAIR_PATH = 'workflows/生产扩展_丝袜纹理修复.json';
export const MAIN_PATH = 'workflows/UAP统一生产工作台_v2.json';

export const K2_CHOICE = '@workflow:k2';
export const MOSS_CHOICE = '@workflow:moss';
export const EXT04_CHOICE = '@workflow:ext04';
export const CAPTION_CHOICE = '@workflow:caption';
export const EXT06_CHOICE = '@workflow:ext06';
export const EXT08_CHOICE = '@workflow:ext08';
export const EXT09_CHOICE = '@workflow:ext09';
export const REPAIR_CHOICE = '@workflow:stocking';

export const STANDALONE_WORKFLOWS = [
    {id:'k2', choice:K2_CHOICE, path:K2_PATH, label:'Krea2 图像生成'},
    {id:'moss', choice:MOSS_CHOICE, path:MOSS_PATH, label:'MOSS 图像生成'},
    {id:'ext04', choice:EXT04_CHOICE, path:EXT04_PATH, label:'Krea2 指令编辑'},
    {id:'caption', choice:CAPTION_CHOICE, path:CAPTION_PATH, label:'图片反推 · 提示词提取'},
    {id:'ext06', choice:EXT06_CHOICE, path:EXT06_PATH, label:'透明素材抠图导出'},
    {id:'ext08', choice:EXT08_CHOICE, path:EXT08_PATH, label:'超分二倍交付'},
    {id:'ext09', choice:EXT09_CHOICE, path:EXT09_PATH, label:'超分四倍素材'},
    {id:'stocking', choice:REPAIR_CHOICE, path:REPAIR_PATH, label:'丝袜纹理修复'},
];
const STANDALONE_BY_ID = new Map(STANDALONE_WORKFLOWS.map(item => [item.id, item]));
const STANDALONE_BY_CHOICE = new Map(STANDALONE_WORKFLOWS.map(item => [item.choice, item]));

export function workflowChoices(config) {
    const choices=(config?.branches||[]).map(b=>({value:b.id,label:b.label}));
    if(choices.length===1&&STANDALONE_BY_ID.has(choices[0].value)) {
        const current=choices[0];
        return STANDALONE_WORKFLOWS.map(item =>
            item.id===current.value
                ? {value:current.value, label:current.label||item.label}
                : {value:item.choice, label:item.label}
        );
    }
    const genAfter=choices.findLastIndex(b=>b.value==='k2'||b.value==='ext04');
    if(genAfter>=0)choices.splice(genAfter+1,0,{value:MOSS_CHOICE,label:'MOSS 图像生成'},{value:CAPTION_CHOICE,label:'图片反推 · 提示词提取'});
    const after=choices.findLastIndex(b=>b.value==='ext08'||b.value==='ext09');
    choices.splice(after<0?choices.length:after+1,0,{value:REPAIR_CHOICE,label:'丝袜纹理修复'});
    return choices;
}

export function isWorkflowChoice(value) { return STANDALONE_BY_CHOICE.has(value)||/^@main(?::ext0[89])?$/.test(value); }

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
        const standalone=STANDALONE_BY_CHOICE.get(value);
        let path=standalone?standalone.path:MAIN_PATH;
        let workflow=store.getWorkflowByPath(path);
        let usedStandaloneFallback=false;
        if(!workflow&&!standalone) {
            const fallbackPath=value==='@main:ext08'?EXT08_PATH:value==='@main:ext09'?EXT09_PATH:K2_PATH;
            workflow=store.getWorkflowByPath(fallbackPath);
            if(workflow){path=fallbackPath;usedStandaloneFallback=true;}
        }
        if(!workflow)throw new Error('找不到 '+path.split('/').at(-1)+'，请确认已安装独立工作流。');
        // Match ComfyUI's workflow service: the store's openWorkflow only sets
        // tab metadata. Passing the workflow to loadGraphData also preserves
        // the outgoing change tracker and restores the selected tab's draft.
        const fromDisk=!workflow.isLoaded;
        if(fromDisk)await workflow.load();
        if(!unchanged())throw new Error('工作流已变化，请重新选择入口。');
        await app.loadGraphData(JSON.parse(JSON.stringify(workflow.activeState)),true,true,workflow,
            {checkForRerouteMigration:false,deferWarnings:true,skipAssetScans:!fromDisk});
        const branch=!usedStandaloneFallback&&value.startsWith('@main:')?value.split(':')[1]:null;
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
    element('p','建议先完成精修和 2× / 4× 放大，再导入最终尺寸图片修复纹理。应用后运行本工作流，同时保存成品和透明丝袜图层。',section);
    element('p','摩尔纹默认关闭；开启前先在编辑器中完成深度计算。油光仍为试验效果，建议从低强度开始预览。',section);
    element('p','编辑器顶部可切换 GPU / CPU；精确对照原版时请选择 CPU。离开或关闭编辑器会释放模型缓存，草稿和计算完成的深度会保留。',section);
    const sync=()=>{
        const project=stockingProject(node);
        status.textContent=project.asset?`已应用：${project.name||'图片'} · ${project.regions?.length||0} 个部位`:'尚未应用图片；请先在编辑器中完成导入和应用。';
        button.disabled=!isCurrent();
    };
    sync();return sync;
}
