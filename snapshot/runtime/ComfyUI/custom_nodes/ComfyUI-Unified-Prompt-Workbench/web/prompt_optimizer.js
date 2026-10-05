import {api} from '../../scripts/api.js';
import {createWidgetInserter, isWritableTarget, mountInsertionActions} from './prompt_target.js';
import {listPromptTargets, sourceForTarget} from './resource_actions.js';

const prefix='/prompt-assistant/api';
const requestTimeout=120000;
// Draft text survives closing this panel, only while its graph stays in memory.
const sessionDrafts=new WeakMap();

export function mountPromptOptimizer(host,{app,element,button,report=()=>{},onChange=()=>{}}){
    let active=false,disposed=false,config=null,configError='',configLoading=false,configRequest=null;
    let context=null,targets=[],target=null,source=null,pending=null,result=null,writer=null,timer=null;
    let draftVersion=0,configVersion=0,lastNotice=null;
    const root=element('section',null,host,{className:'uw-prompt-optimizer'});
    const settings=element('div',null,root,{className:'uw-optimizer-settings'});
    const service=element('p','尚未读取服务配置',settings,{className:'uw-task-description'});
    element('p','点击“开始优化”会将草稿发送到上述服务（本机或在线）；原提示词保留。',settings,{className:'uw-task-description'});
    const sourceRow=element('div',null,root,{className:'uw-toolbar uw-optimizer-source'});
    const sourceLabel=element('label','读取与写入字段',sourceRow),picker=element('select',null,sourceLabel);
    picker.setAttribute('aria-label','优化提示词字段');
    const read=button('读取到草稿','optimizer-read',()=>{
        refresh();if(!target||!isWritableTarget(app,target.node,target.widget))throw new Error('请先选择当前分支中可写的提示词字段。');
        void cancel('已重新读取草稿，本次请求已取消。');
        draft.value=String(target.widget.value||'');source={...target,value:draft.value};draftVersion++;
        invalidateResult('已重新读取草稿，请再次优化。');setStatus('已读取到草稿，原提示词未改动。');notify();
    },sourceRow);
    const draftLabel=element('label','本次优化草稿',root),draft=element('textarea',null,draftLabel,{className:'uw-optimizer-draft',rows:7,placeholder:'粘贴提示词，或从上方字段读取。可在这里调整本次优化内容。'});
    draft.setAttribute('aria-label','本次优化草稿');draft.spellcheck=false;
    const serviceDetails=element('details',null,root,{className:'uw-optimizer-service-details'});
    element('summary','扩写规则与刷新服务',serviceDetails);
    const rule=element('p','',serviceDetails,{className:'uw-task-description'});
    const reload=button('刷新服务','optimizer-refresh',()=>loadConfiguration(),serviceDetails);
    const status=element('p','',root,{className:'uw-optimizer-status'});status.setAttribute('role','status');
    const output=element('section',null,root,{className:'uw-optimizer-output',hidden:true});
    element('h3','优化结果',output);
    const resultHint=element('p','结果仅供预览，核对后手动写入。',output,{className:'uw-task-description'});
    const preview=element('textarea',null,output,{rows:8,readOnly:true});preview.setAttribute('aria-label','优化结果');
    const outputRow=element('div',null,output,{className:'uw-toolbar'});
    button('复制结果','optimizer-copy',async()=>{
        if(!preview.value.trim())return;
        try{await navigator.clipboard.writeText(preview.value);setStatus('优化结果已复制。');}
        catch{preview.focus();preview.select();setStatus('无法自动复制，已选中结果，请按 Ctrl+C。');}
    },outputRow);
    const actionHost=element('div',null,output,{className:'uw-toolbar'});
    context=currentContext();
    const saved=sessionDrafts.get(context.graph)?.get(context.branch||null);
    if(saved&&sameContext(saved.context,context)){
        draft.value=saved.text;
        status.textContent='已恢复此工作流与分支的优化草稿。仅恢复文本，请重新选择读取与写入字段。';
    }

    function currentContext(){
        const graph=app.graph,state=graph?.extra?.uap_workbench;
        return {graph,id:graph?.id,state,branchId:state?.activeBranch,branch:state?.branches?.find(item=>item.id===state.activeBranch)};
    }
    function sameContext(a,b=currentContext()){
        return !!a&&a.graph===b.graph&&a.id===b.id&&a.state===b.state&&a.branchId===b.branchId&&a.branch===b.branch;
    }
    function sourceChanged(){return source&&(!isWritableTarget(app,source.node,source.widget)||source.widget.value!==source.value);}
    function targetMatches(captured){
        return !captured?!target:target?.node===captured.node&&target?.widget===captured.widget&&isWritableTarget(app,captured.node,captured.widget);
    }
    function requestStillCurrent(item){
        return !disposed&&active&&root.isConnected&&sameContext(item.context)&&item.version===draftVersion&&item.draft===draft.value&&targetMatches(item.target)&&
            (!item.target||String(item.target.widget.value??'')===item.targetValue)&&!sourceChanged();
    }
    function setStatus(message){if(!disposed){status.textContent=message;if(active)report(message);}}
    function reason(){
        if(disposed||!active)return '请先打开提示词优化。';
        if(pending)return '正在优化，可点击“取消提示词优化”停止本次请求。';
        if(configLoading)return '正在读取服务与规则…';
        if(configError)return configError;
        if(!config)return '请先读取提示词助手的服务配置。';
        if(!config.provider||!config.model)return '尚未选择扩写服务或模型，请在提示词助手设置中配置后刷新服务。';
        if(!config.rule)return '尚未选择有效的扩写规则，请在提示词助手设置中选择后刷新服务。';
        if(sourceChanged())return '来源正文已变化，请重新读取到草稿，或编辑草稿后作为独立文本优化。';
        if(!draft.value.trim())return '请粘贴提示词，或点击“读取到草稿”。';
        return '';
    }
    function notify(){
        if(disposed)return;const current=reason();
        if(current!==lastNotice){lastNotice=current;onChange({task:'optimize',label:'开始优化',reason:current});}
    }
    function invalidateResult(message){
        if(!result)return;result.valid=false;writer?.dispose();writer=null;actionHost.replaceChildren();
        resultHint.textContent=message+' 下方旧结果仍可复制。';
    }
    function capture(){return {context:currentContext(),version:draftVersion,draft:draft.value,target,targetValue:target?String(target.widget.value??''):null};}

    async function readConfiguration(signal){
        const readJson=async path=>{
            const response=await api.fetchApi(prefix+path,{signal,cache:'no-store'});
            if(response.status===404)throw new Error('提示词助手未加载，当前优化功能不可用；请检查启动配置。');
            if(!response.ok)throw new Error('服务配置读取失败，请点击“刷新服务”重试。');
            try{return await response.json();}catch{throw new Error('服务配置格式异常，请点击“刷新服务”重试。');}
        };
        const [llm,rules]=await Promise.all([readJson('/config/llm/masked'),readJson('/config/system_prompts')]);
        // Retain only display fields; keys, endpoints and full rules never enter UI state.
        return {provider:String(llm?.provider||''),model:String(llm?.model||''),rule:String(rules?.expand_prompts?.[rules?.active_prompts?.expand]?.name||'')};
    }
    async function loadConfiguration(){
        if(disposed||configLoading||pending)return;
        const version=++configVersion,controller=new AbortController();configRequest=controller;configLoading=true;configError='';notify();
        reload.disabled=true;
        const timeout=setTimeout(()=>controller.abort(),10000);
        try{
            const next=await readConfiguration(controller.signal);
            if(disposed||version!==configVersion)return;
            config=next;service.textContent=next.provider&&next.model?`服务：${next.provider} · 模型：${next.model}`:'尚未选择扩写服务或模型';
            rule.textContent=next.rule?'扩写规则：'+next.rule:'尚未选择有效的扩写规则';
        }catch(error){
            if(disposed||version!==configVersion)return;
            config=null;configError=controller.signal.aborted?'服务配置读取超时，请点击“刷新服务”重试。':error.message?.startsWith('提示词助手未加载')?error.message:'服务配置读取失败，请点击“刷新服务”重试。';
            service.textContent=configError;rule.textContent='';
        }finally{
            clearTimeout(timeout);if(!disposed&&version===configVersion){configLoading=false;configRequest=null;reload.disabled=false;notify();}
        }
    }
    async function cancel(message='本次优化已取消，草稿已保留。',timedOut=false){
        const item=pending;if(!item||item.stopped)return item?.cancelPromise;
        item.stopped=true;
        if(timedOut)item.reject(new Error(message));else item.resolve(false);
        item.controller.abort();
        setStatus(message);
        if(!item.sent)return true;
        item.cancelPromise=(async()=>{
            const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
            try{
                const response=await api.fetchApi(prefix+'/request/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:item.id}),signal:controller.signal});
                if(!response.ok&&response.status!==404)throw new Error('cancel');
                return true;
            }catch{
                if(!disposed&&!pending)setStatus('已停止接收结果，但未确认服务端取消；旧结果不会写回，可重新尝试。');
                return false;
            }finally{clearTimeout(timeout);}
        })();
        return item.cancelPromise;
    }
    function mountResult(item,text){
        result={context:item.context,version:item.version,draft:item.draft,target:item.target,text,valid:true,expected:item.targetValue};output.hidden=false;preview.value=text;
        resultHint.textContent=target?'请核对优化结果，再选择写入方式；替换全文需要先预览确认。':'当前没有可写字段，可先复制结果。';
        writer?.dispose();writer=null;actionHost.replaceChildren();
        if(!target)return;
        const record=result,destination=target;
        const valid=()=>record===result&&record.valid&&active&&!disposed&&sameContext(record.context)&&record.version===draftVersion&&record.draft===draft.value&&targetMatches(destination);
        const base=createWidgetInserter(app,sourceForTarget(destination),{commaSeparated:true,validate:valid});
        const guarded=async request=>{
            if(!valid()||String(destination.widget.value??'')!==record.expected)throw new Error('目标正文或工作流已变化，请重新优化后写入。');
            const applied=await base({...request,expectedCurrent:record.expected});
            if(applied.status==='inserted'){record.expected=String(destination.widget.value??'');source=null;}
            return applied;
        };
        guarded.supportsActions=base.supportsActions;guarded.defaultAction='replace_prompt';
        guarded.preview=request=>guarded({...request,preview:true});
        guarded.undoLast=()=>{
            if(!valid()||String(destination.widget.value??'')!==record.expected)return false;
            const done=base.undoLast();if(done){record.expected=String(destination.widget.value??'');source=null;}return done;
        };
        Object.defineProperty(guarded,'onUndoInvalidated',{set:value=>{base.onUndoInvalidated=value;}});
        guarded.dispose=()=>base.dispose();writer=guarded;
        mountInsertionActions(actionHost,guarded,()=>{
            if(!valid())throw new Error('该结果已过期，请重新优化。');return record.text;
        },setStatus);
    }
    async function run(captured){
        refresh();const unavailable=reason();if(unavailable)throw new Error(unavailable);
        if(!requestStillCurrent(captured))throw new Error('草稿、来源或工作流已变化，请重新点击开始优化。');
        const item={...captured,id:'uw-optimize-'+crypto.randomUUID(),controller:new AbortController(),stopped:false,sent:false};
        const stopped=new Promise((resolve,reject)=>{item.resolve=resolve;item.reject=reject;});
        pending=item;reload.disabled=true;invalidateResult('正在重新优化。');setStatus('正在检查所选服务…');notify();
        const timeout=setTimeout(()=>void cancel('优化超过 2 分钟，已取消本次请求。可调整草稿后重试。',true),requestTimeout);
        try{
            const work=(async()=>{
                const latest=await readConfiguration(item.controller.signal);
                if(item.stopped)return false;
                if(!requestStillCurrent(item))throw new Error('草稿、来源或工作流已变化，本次优化未发送。');
                if(latest.provider!==config.provider||latest.model!==config.model||latest.rule!==config.rule){
                    config=latest;service.textContent=`服务：${latest.provider||'未选择'} · 模型：${latest.model||'未选择'}`;rule.textContent='扩写规则：'+(latest.rule||'未选择');
                    throw new Error('服务、模型或规则已变化，请核对更新后的信息，再点击开始优化。');
                }
                item.sent=true;setStatus('正在优化提示词…可随时取消。');
                const response=await api.fetchApi(prefix+'/llm/expand',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:item.draft,request_id:item.id}),signal:item.controller.signal});
                if(item.stopped)return false;
                if(response.status===404)throw new Error('提示词助手未加载，请检查启动配置后刷新服务。');
                if(!response.ok)throw new Error('优化服务请求失败，请检查所选服务后重试。');
                let data;try{data=await response.json();}catch{throw new Error('优化服务返回格式异常，请检查服务后重试。');}
                if(item.stopped)return false;
                if(!requestStillCurrent(item)){void cancel('来源、目标或工作流已变化，本次结果已丢弃。');return false;}
                if(!data?.success||typeof data.data?.expanded!=='string'||!data.data.expanded.trim())throw new Error('服务未返回可用的优化结果，请检查服务与规则后重试。');
                mountResult(item,data.data.expanded);setStatus('优化完成。原提示词未改动，请核对后手动写入。');return true;
            })();
            return await Promise.race([work,stopped]);
        }catch(error){
            const message=error.message?.includes('请')||error.message?.includes('已变化')||error.message?.startsWith('优化超过')?error.message:'优化连接中断，请检查服务后重试。';
            if(!item.stopped)setStatus(message);
            throw new Error(message);
        }finally{
            clearTimeout(timeout);if(pending===item)pending=null;
            if(!disposed){reload.disabled=false;notify();}
        }
    }
    function refresh(){
        if(disposed)return;
        if(active&&!root.isConnected){dispose();return;}
        const next=currentContext(),changed=context&&!sameContext(context,next);
        if(changed){
            void cancel('工作流或分支已切换，本次优化已取消。');source=null;target=null;invalidateResult('工作流或分支已切换，请重新优化。');
            if(draft.value.trim())setStatus('工作流或分支已切换，草稿保留为独立文本；请重新选择读取与写入字段。');
        }
        context=next;
        const available=listPromptTargets(app);
        if(changed||available.length!==targets.length||available.some((item,i)=>item.node!==targets[i]?.node||item.widget!==targets[i]?.widget||item.label!==targets[i]?.label)){
            const previous=target;targets=available;
            target=targets.find(item=>item.node===previous?.node&&item.widget===previous?.widget)||null;
            if(previous&&!target){void cancel('提示词字段已失效，本次优化已取消。');invalidateResult('提示词字段已失效，请重新选择并优化。');}
            picker.replaceChildren();element('option','独立草稿 · 仅复制结果',picker,{value:''});
            targets.forEach((item,i)=>element('option',item.label,picker,{value:String(i)}));
            picker.value=target?String(targets.indexOf(target)):'';
        }
        read.disabled=!target;
        if(pending&&!requestStillCurrent(pending))void cancel('草稿、来源或目标已变化，本次优化已取消。');
        if(result?.valid&&(!sameContext(result.context)||!targetMatches(result.target)||result.version!==draftVersion||result.draft!==draft.value||sourceChanged()||(result.target&&String(result.target.widget.value??'')!==result.expected)))invalidateResult('草稿、来源或目标已变化，请重新优化。');
        notify();
    }
    picker.onchange=()=>{
        void cancel('已切换提示词字段，本次优化已取消。');target=picker.value===''?null:targets[Number(picker.value)]||null;source=null;draftVersion++;
        invalidateResult('写入字段已切换，请重新优化。');read.disabled=!target;notify();
    };
    draft.addEventListener('input',()=>{
        draftVersion++;source=null;void cancel('草稿已修改，本次优化已取消。');invalidateResult('草稿已修改，请重新优化。');notify();
    });
    function setActive(value){
        if(disposed||active===Boolean(value))return;active=Boolean(value);
        if(active){refresh();timer=setInterval(refresh,600);if(!config&&!configLoading)void loadConfiguration();}
        else{clearInterval(timer);timer=null;void cancel('已切换任务，本次优化已取消。');}
    }
    function dispose(){
        if(disposed)return;
        if(context?.graph){
            let entries=sessionDrafts.get(context.graph);
            if(!entries){entries=new Map();sessionDrafts.set(context.graph,entries);}
            if(draft.value)entries.set(context.branch||null,{context,text:draft.value});else entries.delete(context.branch||null);
        }
        void cancel('优化窗口已关闭，本次请求已取消。');disposed=true;active=false;configVersion++;
        clearInterval(timer);configRequest?.abort();writer?.dispose();writer=null;
    }
    return {refresh,prepare(){refresh();const captured=capture();return {task:'optimize',label:'开始优化',reason:reason(),execute:()=>run(captured),cancel:()=>cancel()};},setActive,dispose};
}
