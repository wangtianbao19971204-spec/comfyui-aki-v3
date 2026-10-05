import {api} from '../../scripts/api.js';
import {commitWidget} from './prompt_target.js';

const children=node=>node.subgraph?.nodes||node.subgraph?._nodes||[];
const widget=(node,name)=>node.widgets?.find(item=>item.name===name);
const partNames={hand:'手',foot:'脚',face:'脸',eyes:'眼',eye:'眼',region_standard:'区域标准',region_fast:'区域快速'};

export function mountRefinementControls(host,{app,branch,nodes,isCurrent}){
    const graph=app.graph,parts=nodes.filter(node=>node.properties?.uap_refinement);
    const order=['hand','foot','region_standard','region_fast','face','eye','eyes'];
    parts.sort((a,b)=>order.indexOf(a.properties.uap_refinement)-order.indexOf(b.properties.uap_refinement));
    const upscaler=nodes.find(node=>node.type==='UltimateSDUpscale');
    if(!parts.length&&!upscaler)return {sync(){},dispose(){}};
    const el=(tag,text,parent,attrs={})=>{const item=document.createElement(tag);if(text)item.textContent=text;Object.assign(item,attrs);parent.append(item);return item;};
    const box=el('section','',host,{className:'desk-refinement-controls'});box.dataset.deskArea='refinement';
    el('h3','细化与二放 · 常用参数',box);
    el('small','开关在上方；下面直接编辑原节点参数，不新增重绘阶段。各阶段种子独立。',box);
    const rows=[],fields=[];let disposed=false,promptId=null;
    const current=()=>!disposed&&isCurrent()&&app.graph===graph&&graph.extra?.uap_workbench?.activeBranch===branch.id;
    function bind(parent,node,name,label,owner){
        const value=widget(node,name);if(!value)return;
        const row=el('label','',parent,{className:/^(seed|control_after_generate)$/.test(name)?'field wide':'field'});el('span',label,row);
        let choices=value.options?.values;if(typeof choices==='function')choices=choices();
        const input=el(Array.isArray(choices)?'select':'input','',row);input.setAttribute('aria-label',label);
        if(Array.isArray(choices))for(const option of choices)el('option',String(option),input,{value:String(option)});
        else {input.type='number';input.step=/seed|steps|guide_size/.test(name)?'1':'any';input.required=true;if(Number.isFinite(value.options?.min))input.min=String(value.options.min);if(Number.isFinite(value.options?.max))input.max=String(value.options.max);}
        const valid=()=>current()&&graph.getNodeById(owner.id)===owner&&(owner===node||children(owner).includes(node))&&node.widgets?.includes(value)&&!node.inputs?.some(port=>port.name===name&&port.link!=null);
        const sync=()=>{input.disabled=!valid();if(document.activeElement!==input)input.value=String(value.value);};
        const apply=()=>{
            if(!valid()){input.setAttribute('aria-invalid','true');return;}
            const next=Array.isArray(choices)?input.value:Number(input.value);
            if(!input.checkValidity()||(!Array.isArray(choices)&&(!input.value.trim()||!Number.isFinite(next)))){input.setAttribute('aria-invalid','true');return;}
            input.removeAttribute('aria-invalid');commitWidget(app,node,value,next);sync();
        };input.oninput=apply;input.onchange=apply;fields.push(sync);sync();
    }
    for(const owner of parts){
        const title=partNames[owner.properties.uap_refinement]||owner.title?.replace(/^\[[^\]]+\]\s*/,'')||'细化';
        const detail=el('details','',box,{className:'desk-refinement-part'}),summary=el('summary','',detail);
        const status=el('small','',detail,{className:'desk-refinement-status'});status.setAttribute('role','status');
        const inner=children(owner),models=inner.filter(node=>node.type==='UltralyticsDetectorProvider');
        el('small',models.map(node=>String(widget(node,'model_name')?.value||'').split(/[\\/]/).at(-1)).filter(Boolean).join(' / ')||'检测器在子图内查看',detail,{className:'desk-detector-summary'});
        const grid=el('div','',detail,{className:'fields'});
        const detectors=inner.filter(node=>['ImpactSimpleDetectorSEGS','SegmDetectorSEGS'].includes(node.type));
        detectors.forEach((node,index)=>{
            const suffix=detectors.length>1?` ${index+1}`:'';
            bind(grid,node,widget(node,'bbox_threshold')?'bbox_threshold':'threshold',`${title}检测阈值${suffix}`,owner);
            bind(grid,node,'crop_factor',`${title}裁剪上下文${suffix}`,owner);
        });
        const detailers=inner.filter(node=>['DetailerForEach','DetailerForEachPipe'].includes(node.type));
        detailers.forEach((node,index)=>{
            const suffix=detailers.length>1?` ${index+1}`:'';
            bind(grid,node,'denoise',`${title}局部降噪${suffix}`,owner);
            bind(grid,node,'seed',`${title}局部种子${suffix}`,owner);
            bind(grid,node,'control_after_generate',`${title}种子模式${suffix}`,owner);
        });
        rows.push({owner,title,summary,status,detailers,execution:''});
    }
    if(upscaler){
        const detail=el('details','',box,{className:'desk-refinement-part'});el('summary','分块二放 · 参数独立',detail);
        const grid=el('div','',detail,{className:'fields'});
        for(const [name,label] of [['upscale_by','二放最终倍率'],['denoise','二放降噪'],['seed','二放种子'],['control_after_generate','二放种子模式']])bind(grid,upscaler,name,label,upscaler);
        el('small','使用当前主线 LoRA；开关关闭时透传。接缝算法与强度保留在原节点。',detail);
    }
    el('small','执行状态只来自本浏览器收到的后端事件。上游未回传命中数/重绘数时不会推测；“执行结束”不等于检测命中。',box);
    function sync(){
        if(disposed)return;fields.forEach(update=>update());
        for(const row of rows){
            const enabled=row.owner.mode===0;
            const strength=row.detailers.map(node=>widget(node,'denoise')?.value).filter(value=>value!=null).join('/');
            row.summary.textContent=`${row.title} · ${enabled?'开启':'关闭'}${strength?' · 降噪 '+strength:''}`;
            row.status.textContent=!enabled?'关闭 · 原图透传':row.execution||'已启用 · 尚未观察到本次执行';
        }
    }
    const started=event=>{if(!current())return;promptId=event.detail?.prompt_id;for(const row of rows)row.execution='';sync();};
    const executing=event=>{
        if(!current()||!promptId||event.detail?.prompt_id!==promptId)return;
        const id=String(event.detail?.node??'');
        for(const row of rows)if(id===String(row.owner.id)||id.startsWith(row.owner.id+':'))row.execution='处理中 · 命中统计尚未回传';sync();
    };
    const cached=event=>{
        if(!current()||!promptId||event.detail?.prompt_id!==promptId)return;
        for(const row of rows)if(event.detail.nodes?.some(id=>String(id)===String(row.owner.id)||String(id).startsWith(row.owner.id+':')))row.execution='缓存复用 · 不是本次重新重绘';sync();
    };
    const finished=event=>{
        if(!current()||!promptId||event.detail?.prompt_id!==promptId)return;
        for(const row of rows)if(row.execution.startsWith('处理中'))row.execution=event.type==='execution_success'?'执行结束 · 上游未回传命中/重绘数量':'执行中断 · 查看任务错误';sync();
    };
    const events=[['execution_start',started],['executing',executing],['execution_cached',cached],['execution_success',finished],['execution_error',finished],['execution_interrupted',finished]];
    for(const [name,callback] of events)api.addEventListener(name,callback);
    sync();return {sync,dispose(){disposed=true;for(const [name,callback] of events)api.removeEventListener(name,callback);}};
}
