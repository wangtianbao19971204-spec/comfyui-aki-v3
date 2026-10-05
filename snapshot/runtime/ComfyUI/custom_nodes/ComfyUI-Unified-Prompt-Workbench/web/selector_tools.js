import {listPromptTargets} from './resource_actions.js';

export const SELECTOR_TOOLS = [
    {kind:'character',label:'角色选择器',module:'character',open:'openCharacterSelectorModal'},
    {kind:'clothing',label:'服装选择器',module:'clothing',open:'openClothingSelectorModal'},
    {kind:'pose',label:'姿势选择器',module:'pose',open:'openPoseSelectorModal'},
    {kind:'background',label:'背景选择器',module:'background',open:'openBackgroundSelectorModal'},
    {kind:'artist',label:'画师选择器',module:'artist',open:'openArtistSelectorModal'},
    {kind:'style_quality',label:'画风 / 质量选择器',module:'pose',open:'openStyleQualitySelectorModal'},
];

export async function openPromptSelector(app, kind, target) {
    const tool=SELECTOR_TOOLS.find(item=>item.kind===kind);
    if(!tool)throw new Error('请选择可用的提示词选择器。');
    const graph=app.graph,graphId=graph?.id,branch=graph?.extra?.uap_workbench?.activeBranch;
    const valid=()=>app.graph===graph && graph.id===graphId && graph.extra?.uap_workbench?.activeBranch===branch &&
        listPromptTargets(app).some(item=>item.node===target?.node && item.widget===target?.widget && item.direction==='positive');
    if(!valid())throw new Error('请先选择当前工作流中可编辑的正向提示词目标。');
    const module=await import(`/extensions/comfyui-anima-tools/anima_${tool.module}_selector.js`);
    if(!valid())throw new Error('工作流或目标已变化，请重新选择目标后打开。');
    return module[tool.open](target.node,target.widget);
}

export function mountSelectorTools(host, {element,button,getTargets,getTarget,selectTarget,open,report}) {
    element('strong','提示词选择器',host);
    const row=element('div',null,host,{className:'uw-toolbar'});
    const label=element('label','写入正向 ',row),picker=element('select',null,label);
    picker.setAttribute('aria-label','选择器写入目标');
    const hint=element('small','',host);
    let targets=[],signature='',opening=false;
    picker.onchange=()=>selectTarget(picker.value===''?null:targets[Number(picker.value)]);
    const buttons=SELECTOR_TOOLS.map(tool=>button(tool.label,'open-selector-'+tool.kind,async()=>{
        const target=getTarget();
        if(!targets.some(item=>item.node===target?.node && item.widget===target?.widget)){
            picker.focus();report('请先选择正向提示词目标。');return;
        }
        if(opening)return;
        opening=true;refresh();
        try{await open(tool,target);}finally{opening=false;refresh();}
    },row));
    function refresh(){
        const next=getTargets().filter(item=>item.direction==='positive');
        const nextSignature=next.map(item=>`${item.node.id}:${item.widget.name}:${item.label}`).join('|');
        if(signature!==nextSignature || next.length!==targets.length || next.some((item,index)=>item.node!==targets[index]?.node || item.widget!==targets[index]?.widget) || !picker.options.length){
            targets=next;signature=nextSignature;picker.replaceChildren();
            element('option',targets.length?'请选择正向提示词目标':'当前没有可编辑的正向提示词',picker,{value:''});
            targets.forEach((target,index)=>element('option',target.label,picker,{value:String(index)}));
        }
        const target=getTarget(),index=targets.findIndex(item=>item.node===target?.node && item.widget===target?.widget);
        const empty=!targets.length;
        if(row.hidden!==empty)row.hidden=empty;
        const message=empty?'当前没有可编辑的正向提示词目标，可继续浏览资料。':'先选择目标；打开和选卡不会写入，点击应用后才写入。';
        if(hint.textContent!==message)hint.textContent=message;
        picker.value=index<0?'':String(index);
        picker.disabled=opening || !targets.length;
        buttons.forEach(control=>{control.disabled=opening || index<0;});
    }
    return {refresh};
}
