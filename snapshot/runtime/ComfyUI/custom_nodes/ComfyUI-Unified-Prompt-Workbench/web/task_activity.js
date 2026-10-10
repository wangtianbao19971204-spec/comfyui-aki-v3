import {api} from '../../scripts/api.js';
import {commitWidget, createWidgetInserter, isWritableTarget} from './prompt_target.js';
import {listPromptTargets} from './resource_actions.js';
import {mountPromptOptimizer} from './prompt_optimizer.js';
import {stockingProject} from './repair_workflow.js';

const methods=[['SW-01C','PixAI · 标签反推'],['SW-01D','JoyCaption · 三路反推'],['SW-01B','在线模型 · 综合反推']];
const imageTypes=new Set(['SaveImage','PreviewImage']);
const captionMethod=node=>methods.find(([prefix])=>String(node.properties?.uap_layout_group||'').startsWith(prefix))?.[0]||(node.type==='PixAITagger'?'SW-01C':undefined);

// Execution IDs use the native colon-separated subgraph instance path.
export function taskNodes(app){
    const graph=app.graph,state=graph?.extra?.uap_workbench;
    const branch=state?.branches?.find(item=>item.id===state.activeBranch);
    const roots=(graph?._nodes||[]).filter(node=>!state||branch?.nodeIds?.some(id=>String(id)===String(node.id)));
    const entries=[];
    function visit(node,path,root,method,enabled,scope){
        const id=path?`${path}:${node.id}`:String(node.id);
        enabled=enabled&&(node.mode==null||node.mode===0);
        entries.push({node,id,root,method,enabled,scope});
        for(const child of node.subgraph?.nodes||node.subgraph?._nodes||[])visit(child,id,root,method,enabled,node.subgraph);
    }
    for(const node of roots)visit(node,'',node,captionMethod(node),true,graph);
    return {graph,branch,roots,entries};
}

function captionResults(context,method){
    return context.entries.flatMap(item=>{
        if(item.node.type!=='ShowText|pysssss'||(item.method&&item.method!==method))return [];
        if(method!=='SW-01C')return item.method===method?[item]:[];
        // This group also contains gallery-import text, which must not stand in for PixAI.
        const visited=new Set(),sources=[];
        const entries=new Map(context.entries.filter(entry=>entry.scope===item.scope).map(entry=>[String(entry.node.id),entry]));
        function fromPixAI(node){
            if(!node||visited.has(node)||!entries.has(String(node.id)))return;visited.add(node);
            if(node.type==='PixAITagger'){sources.push(entries.get(String(node.id)));return;}
            for(const input of node.inputs||[]){
                const links=item.scope.links,link=Array.isArray(links)?links.find(link=>String(link.id??link[0])===String(input.link)):links?.[input.link];
                if(!link)continue;
                const id=link.origin_id??link[1];
                fromPixAI(entries.get(String(id))?.node);
            }
        }
        fromPixAI(item.node);
        return sources.length?[{...item,enabled:item.enabled&&sources.every(source=>source.enabled)}]:[];
    });
}

function deliveryGroups(context){
    const groups=context.roots.map(node=>node.properties?.uap_layout_group||'');
    const primary=groups.filter(group=>/^03\s/.test(group));
    return new Set(primary.length?primary:context.branch?.stages?.find(stage=>stage.id==='compare')?.groups||[]);
}

function generationResults(context){
    const groups=deliveryGroups(context);
    return context.entries.filter(item=>imageTypes.has(item.node.type)&&!item.method&&(!context.branch||groups.has(item.root.properties?.uap_layout_group)));
}

function imageTaskName(context){
    const has=type=>context.roots.some(node=>node.type===type);
    if(has('StockingTextureStudio'))return '纹理修复';
    return has('BiRefNetRMBG')?'抠图':has('ImagePadForOutpaint')?'扩图':has('OlmDragCrop')?'局部精修':has('Krea2EditGroundedEncode')?'指令编辑':!has('KSampler')&&has('UpscaleModelLoader')?'放大':'生图';
}

export function taskPlan(app,task,method){
    const context=taskNodes(app),{entries,roots}=context;
    const candidates=task==='generate'?generationResults(context):captionResults(context,method);
    const targets=candidates.filter(item=>item.enabled);
    // These connected output nodes preserve the workflow's explicit after-run cleanup.
    if(task==='generate'&&targets.length){
        const groups=deliveryGroups(context);
        targets.push(...entries.filter(item=>item.enabled&&item.node.type==='VRAMCleanup'&&groups.has(item.root.properties?.uap_layout_group)&&item.node.inputs?.some(input=>input.name==='anything'&&input.link!=null)));
        targets.push(...entries.filter(item=>item.enabled&&item.node.type==='Image Comparer (rgthree)'&&String(item.root.properties?.uap_layout_group||'').startsWith('SW-10V')));
    }
    const methodRoots=roots.filter(node=>captionMethod(node)===method);
    const label=task==='generate'?'开始'+imageTaskName(context):task==='caption'?'开始反推':'开始优化';
    let reason=app.rootGraph&&app.rootGraph!==app.graph?'请先返回主工作流，再选择要执行的任务。':task==='optimize'?'请在提示词优化面板中准备草稿。'
        : !candidates.length?'当前分支没有可识别的'+(task==='generate'?'图片输出节点。':'反推结果节点。')
        : !targets.length?'请先启用'+(task==='generate'?'当前分支的图片输出节点。':'所选反推工具。'):'';
    const editor=roots.find(node=>node.type==='StockingTextureStudio');
    if(!reason&&task==='generate'&&editor&&!editor.inputs?.some(i=>i.name==='image'&&i.link!=null)&&!stockingProject(editor).asset)
        reason='请打开修复编辑器，导入图片并应用到节点。';
    return {...context,task,method,label,reason,methodRoots,targets,queueNodeIds:targets.map(item=>item.id)};
}

function imageUrl(picture){
    return '/view?'+new URLSearchParams({filename:picture.filename,subfolder:picture.subfolder||'',type:picture.type||'output'});
}

function referenceNodes(context,method,task='caption'){
    const visited=new Set(),images=[];
    function upstream(node){
        if(!node||visited.has(node))return;visited.add(node);
        if(node.type==='LoadImage')images.push(node);
        for(const input of node.inputs||[]){
            const link=context.graph?.links?.[input.link];
            if(link)upstream(context.graph.getNodeById(link.origin_id??link[1]));
        }
    }
    const origins=task==='generate'?generationResults(context).map(item=>item.root):context.roots.filter(node=>captionMethod(node)===method);
    origins.forEach(upstream);
    return images;
}

export function mountTaskActivity(host,{app,element,button,report,onChange,actionsHost=host,inputHost=host}){
    let task='generate',method='SW-01C',context=null,signature='',disposed=false,active=true,historyVersion=0,record=null,writer=null;
    let reference=null,referenceWidget=null,referenceValue=null,uploading=false,historyDirty=false;
    const tabs=element('div',null,actionsHost,{className:'uw-task-tabs'});tabs.setAttribute('role','group');tabs.setAttribute('aria-label','当前任务');
    const choices=new Map();
    for(const [id,label,description]of [['generate','生图','参数 → 图片'],['caption','提示词反推','参考图 → 提示词'],['optimize','提示词优化','草稿 → 对照采用']]){
        const choice=button(label,'task-'+id,()=>{task=id;refresh(true);},tabs);
        element('small',description,choice);choices.set(id,choice);
    }
    const content=element('section',null,host,{className:'uw-task-content'});
    const heading=element('div',null,content,{className:'uw-task-heading'}),title=element('h2','',heading);
    const refreshResults=button('刷新结果','task-refresh',()=>loadHistory(),heading);
    const intro=element('p','',content,{className:'uw-task-description'});
    const caption=element('div',null,inputHost,{className:'uw-caption-inputs',hidden:true});
    const methodLabel=element('label','反推方式',caption),picker=element('select',null,methodLabel);picker.setAttribute('aria-label','反推方式');
    picker.onchange=()=>{method=picker.value;refresh(true);};
    const enable=button('启用所选反推工具','task-enable-caption',()=>{
        const plan=taskPlan(app,task,method);
        if(plan.graph!==context?.graph||plan.branch!==context?.branch)throw new Error('工作流已切换，请重新选择反推方式。');
        plan.graph.beforeChange?.();try{for(const node of plan.methodRoots)node.mode=0;}finally{plan.graph.afterChange?.();plan.graph.setDirtyCanvas?.(true,true);}
        refresh(true);
    },caption);
    const referenceLabel=element('label','参考图来源',caption),source=element('select',null,referenceLabel);source.setAttribute('aria-label','参考图来源');
    source.onchange=()=>{reference=context.roots.find(node=>String(node.id)===source.value);referenceValue=null;syncReference();};
    const inputRow=element('div',null,caption,{className:'uw-toolbar'}),files=element('select',null,inputRow);files.setAttribute('aria-label','已上传参考图');
    files.onchange=()=>{
        if(!reference||!isWritableTarget(app,reference,referenceWidget,context.graph)){report('参考图节点已变化，请重新选择。');return;}
        try{commitWidget(app,reference,referenceWidget,files.value);syncReference();}catch(error){report(error);}
    };
    const upload=element('input',null,inputRow,{type:'file',accept:'image/*',hidden:true});
    const uploadButton=button('上传参考图','task-upload',()=>upload.click(),inputRow);
    upload.onchange=async()=>{
        const file=upload.files?.[0];if(!file||uploading)return;
        const node=reference,widget=referenceWidget,graph=context?.graph;
        if(!isWritableTarget(app,node,widget,graph)){report('请先选择可编辑的参考图节点。');return;}
        uploading=true;uploadButton.disabled=true;
        try{
            const body=new FormData();body.append('image',file);body.append('type','input');
            const response=await api.fetchApi('/upload/image',{method:'POST',body});if(!response.ok)throw new Error('参考图上传失败，请重试。');
            const data=await response.json();
            if(disposed||!isWritableTarget(app,node,widget,graph)||reference!==node)throw new Error('参考图已上传，但目标已变化；请从已上传图片中重新选择。');
            const value=(data.subfolder?data.subfolder+'/':'')+data.name;
            if(Array.isArray(widget.options?.values)&&!widget.options.values.includes(value))widget.options.values.push(value);
            commitWidget(app,node,widget,value);referenceValue=null;syncReference();
        }catch(error){if(!disposed)report(error);}finally{uploading=false;upload.value='';if(!disposed)syncReference();}
    };
    const referencePreview=element('img',null,caption,{className:'uw-reference-image',alt:'当前输入图片',hidden:true});
    const referenceHint=element('p','',caption,{className:'uw-task-description'});
    referencePreview.onerror=()=>{referencePreview.hidden=true;referenceHint.textContent='参考图无法读取，请重新选择或上传。';};
    const readiness=element('p','',inputHost,{className:'uw-task-readiness'});readiness.setAttribute('role','status');
    const results=element('div',null,content,{className:'uw-task-results'});
    const resultStatus=element('p','',content,{className:'uw-task-description'});resultStatus.setAttribute('role','status');
    const optimizerHost=element('div',null,inputHost,{hidden:true});
    const optimizer=mountPromptOptimizer(optimizerHost,{app,element,button,report,onChange:state=>{
        if(task!=='optimize'||disposed)return;
        readiness.textContent=state.reason||'就绪 · 点击开始优化后，核对结果再决定是否写入。';
        readiness.dataset.ready=String(!state.reason);onChange(state);
    }});

    function syncReference(){
        referenceWidget=reference?.widgets?.find(widget=>widget.name==='image');
        const writable=reference&&isWritableTarget(app,reference,referenceWidget,context.graph);
        uploadButton.disabled=!writable||uploading;files.disabled=!writable||uploading;
        const value=String(referenceWidget?.value||'');
        if(referenceValue===value)return;const previous=referenceValue;referenceValue=value;
        let values=referenceWidget?.options?.values;if(typeof values==='function')values=values();
        files.replaceChildren();
        const options=Array.from(new Set([...(Array.isArray(values)?values:[]),...(value?[value]:[])]));
        if(!options.length)element('option','请上传参考图',files,{value:''});
        for(const name of options)element('option',name,files,{value:name});files.value=value;
        referenceHint.textContent=!reference?'当前分支没有已连接的输入图片节点。':!writable?'输入图片节点未启用或由连线控制，请在画布调整。':value?(task==='generate'&&context.branch?.dailyRows?'图片按左侧出图模式使用；文生图模式不使用参考图。':'上传或选择图片会同步到当前工作流。'):'请上传或选择输入图片。';
        referencePreview.hidden=!value;
        if(value){
            const annotation=value.match(/\s*\[(input|output|temp)\]\s*$/);
            const name=value.slice(0,annotation?.index??value.length).replace(/\\/g,'/'),split=name.lastIndexOf('/');
            referencePreview.src=imageUrl({filename:name.slice(split+1),subfolder:split<0?'':name.slice(0,split),type:annotation?.[1]||'input'});
        }
        else referencePreview.removeAttribute('src');
        if(previous!=null&&task==='caption')renderResults();
    }

    function plan(){
        if(task==='optimize')return {...taskNodes(app),...optimizer.prepare()};
        const next=taskPlan(app,task,method);
        const sources=referenceNodes(next,method,task);
        if(next.task==='caption'&&!next.reason&&(!sources.length||sources.some(node=>(node.mode!=null&&node.mode!==0)||!node.widgets?.find(widget=>widget.name==='image')?.value)))next.reason='请为所选反推方式连接并启用参考图节点，然后上传或选择图片。';
        if(next.task==='generate'&&next.branch&&!next.branch.dailyRows&&!next.reason&&sources.some(node=>(node.mode!=null&&node.mode!==0)||!node.widgets?.find(widget=>widget.name==='image')?.value))next.reason='请先选择并启用当前流程的输入图片。';
        return next;
    }

    function refresh(force=false){
        if(disposed)return;
        const next=taskNodes(app);
        const repairing=next.roots.some(node=>node.type==='StockingTextureStudio');
        if(repairing)task='generate';
        for(const [id,choice]of choices)choice.hidden=repairing&&id!=='generate';
        const changed=context?.graph!==next.graph||context?.branch!==next.branch||next.entries.some((item,i)=>context?.entries[i]?.node!==item.node)||context?.entries.length!==next.entries.length;
        if(changed){record=null;historyVersion++;reference=null;referenceValue=null;writer?.dispose();writer=null;}
        context=next;
        const nextSignature=task+'|'+method+'|'+next.entries.map(item=>`${item.id}:${item.node.mode}:${item.method}:${(item.node.inputs||[]).map(input=>input.link).join('/')}`).join(',');
        if(changed||force||signature!==nextSignature){
            signature=nextSignature;host.dataset.task=task;
            for(const [id,choice]of choices)choice.setAttribute('aria-pressed',String(id===task));
            const imageTask=imageTaskName(next);choices.get('generate').firstChild.textContent=imageTask;
            title.textContent=task==='generate'?imageTask+' · 结果预览':task==='caption'?'提示词反推 · 参考与结果':'提示词优化';
            intro.textContent=task==='generate'?`调整当前分支的参数与输入，点击“开始${imageTask}”。最终预览与保存图片会显示在这里。`:task==='caption'?'选好参考图和反推方式，再点击“开始反推”。结果可复制或追加到正向提示词。':'读取或粘贴草稿，点击“开始优化”。原提示词保留，结果可复制或预览后确认替换。';
            optimizerHost.hidden=task!=='optimize';
            content.hidden=task==='optimize';
            refreshResults.hidden=results.hidden=resultStatus.hidden=task==='optimize';
            methodLabel.hidden=task!=='caption';
            picker.replaceChildren();for(const [id,label]of methods)if(next.roots.some(node=>captionMethod(node)===id))element('option',label,picker,{value:id});
            if(![...picker.options].some(option=>option.value===method))method=picker.options[0]?.value||'SW-01C';picker.value=method;
            const nodes=referenceNodes(next,method,task);
            caption.hidden=task==='optimize'||(task==='generate'&&!nodes.length);
            referenceLabel.firstChild.textContent=task==='generate'?'输入图片来源':'参考图来源';
            source.replaceChildren();for(const node of nodes)element('option',node.title||`参考图 #${node.id}`,source,{value:String(node.id)});
            if(!nodes.includes(reference))reference=nodes.find(node=>/^CORE-01A/.test(node.properties?.uap_layout_group||''))||nodes[0]||null;
            source.value=reference?String(reference.id):'';referenceValue=null;
            renderResults();
        }
        optimizer.setActive(active&&task==='optimize');
        syncReference();
        const current=plan();
        enable.hidden=task!=='caption'||!current.methodRoots.some(node=>node.mode!==0);
        enable.textContent=method==='SW-01B'?'启用在线反推（使用已配置的外部服务）':'启用所选反推工具';
        readiness.textContent=current.reason||(task==='optimize'?'就绪 · 点击开始优化后，核对结果再决定是否写入。':task==='caption'&&method==='SW-01B'?'就绪 · 点击开始后，参考图将交给工作流中配置的在线服务。':`就绪 · ${task==='generate'?'生成当前分支的图片':'仅执行所选反推方式'}及其必要依赖`);
        readiness.hidden=task==='generate'&&!current.reason;
        readiness.dataset.ready=String(!current.reason);onChange(current);
        if(changed||historyDirty){historyDirty=false;void loadHistory();}
    }

    function compatible(entry){
        const workflow=entry.prompt?.[3]?.extra_pnginfo?.workflow;
        if(!workflow?.id||String(workflow.id)!==String(context.graph?.id))return false;
        const branch=workflow.extra?.uap_workbench?.activeBranch;
        return branch===(context.branch?.id);
    }

    async function loadHistory(){
        if(disposed||!context?.graph||task==='optimize')return;
        const version=++historyVersion,graph=context.graph,branch=context.branch;
        resultStatus.textContent='正在读取当前工作流的最近结果…';
        try{
            const response=await api.fetchApi('/history?max_items=30');if(!response.ok)throw new Error('最近结果读取失败，请点击“刷新结果”重试。');
            const records=await response.json();if(disposed||version!==historyVersion||graph!==context.graph||branch!==context.branch)return;
            record=Object.values(records).filter(compatible).sort((a,b)=>(b.prompt?.[0]||0)-(a.prompt?.[0]||0));renderResults();
        }catch(error){if(!disposed&&version===historyVersion)resultStatus.textContent=error.message||'最近结果读取失败，请重试。';}
    }

    function renderResults(){
        writer?.dispose();writer=null;results.replaceChildren();resultStatus.textContent='';
        if(task==='optimize')return;
        const outputs=task==='generate'?generationResults(context):captionResults(context,method);
        const ids=new Map(outputs.map(item=>[item.id,item]));
        const recent=record?.find(entry=>entry.prompt?.[4]?.some(id=>ids.has(String(id)))||Object.entries(entry.outputs||{}).some(([id,out])=>ids.has(id)&&(task==='generate'?out.images?.length:out.text?.length)));
        if(!recent){element('div',task==='generate'?'图片将在这里出现\n任务完成后自动更新，可点击查看原图。':'反推结果将在这里出现\n先选择参考图和反推方式。',results,{className:'uw-task-empty'});return;}
        resultStatus.textContent='当前工作流 · 最近一次'+(task==='generate'?imageTaskName(context):'反推')+'结果';
        if(task==='caption'&&referenceNodes(context,method).some(node=>{
            const old=recent.prompt?.[2]?.[String(node.id)]?.inputs?.image;
            return typeof old==='string'&&old!==node.widgets?.find(widget=>widget.name==='image')?.value;
        }))resultStatus.textContent='参考图已更换 · 下方为上次结果，请重新反推。';
        if(recent.status?.status_str==='error'){
            const error=recent.status.messages?.find(message=>message[0]==='execution_error')?.[1];
            resultStatus.textContent='本次任务失败 · '+(error?.exception_message||'请展开“队列与最近结果”查看错误。');
        }
        const seen=new Set();
        for(const [id,output]of Object.entries(recent.outputs||{})){
            if(!ids.has(id))continue;
            if(task==='generate')for(const picture of output.images||[]){
                const url=imageUrl(picture);if(seen.has(url))continue;seen.add(url);
                const link=element('a',null,results,{href:url,target:'_blank',rel:'noopener',className:'uw-generated-image'});
                element('img',null,link,{src:url,alt:ids.get(id).node.title||'生成结果',loading:'lazy'});element('span','查看原图 ↗',link);
            }
            else{
                const text=Array.isArray(output.text)?output.text.join('\n'):String(output.text||'');if(!text.trim())continue;
                const card=element('section',null,results,{className:'uw-caption-result'});element('h3',ids.get(id).node.title||'反推结果',card);
                const input=element('textarea',null,card,{value:text,readOnly:true});input.setAttribute('aria-label','反推结果');
                const row=element('div',null,card,{className:'uw-toolbar'});
                button('复制结果','task-copy-caption',async()=>{await navigator.clipboard.writeText(input.value);report('反推结果已复制。');},row);
                const target=element('select',null,row);target.setAttribute('aria-label','追加到正向字段');
                const targets=listPromptTargets(app).filter(item=>item.direction==='positive'&&item.usage==='generation');
                for(const [i,item]of targets.entries())element('option',item.label,target,{value:String(i)});
                const capturedGraph=context.graph,capturedBranch=context.branch;
                const apply=button('追加到正向','task-apply-caption',async()=>{
                    const current=taskNodes(app),destination=targets[Number(target.value)];
                    if(current.graph!==capturedGraph||current.branch!==capturedBranch||!listPromptTargets(app).some(item=>item.node===destination?.node&&item.widget===destination?.widget))throw new Error('正向字段已变化，请刷新结果后重新选择。');
                    writer?.dispose();writer=createWidgetInserter(app,destination,{commaSeparated:true,validate:()=>taskNodes(app).branch===capturedBranch});
                    const result=await writer({text:input.value,action:'append_end'});if(result.status==='inserted')report('反推结果已追加到正向提示词。');
                },row);apply.disabled=!targets.length;
            }
        }
    }

    const completed=()=>{historyDirty=true;if(!host.closest('[hidden]')){historyDirty=false;void loadHistory();}};
    api.addEventListener('execution_success',completed);api.addEventListener('execution_error',completed);
    return {refresh,plan,
        setActive(value){active=Boolean(value);optimizer.setActive(active&&task==='optimize');},
        async prepare(){
            refresh();const current=plan();if(current.reason)throw new Error(current.reason);
            if(current.execute)return current;
            const prompt=await app.graphToPrompt();
            const latest=plan();
            if(disposed||latest.graph!==current.graph||latest.branch!==current.branch||latest.task!==current.task||latest.method!==current.method||latest.queueNodeIds.join()!==current.queueNodeIds.join()||latest.reason)throw new Error('任务或工作流已变化，请重新运行。');
            if(!current.queueNodeIds.length||current.queueNodeIds.some(id=>!prompt.output?.[id]))throw new Error('所选任务的输出节点未就绪，请检查工具开关与连线。');
            return current;
        },
        submitted(label){resultStatus.textContent=label.replace('开始','')+'任务已提交，完成后自动显示结果。';},
        dispose(){disposed=true;historyVersion++;optimizer.dispose();writer?.dispose();for(const event of ['execution_success','execution_error'])api.removeEventListener(event,completed);}
    };
}
