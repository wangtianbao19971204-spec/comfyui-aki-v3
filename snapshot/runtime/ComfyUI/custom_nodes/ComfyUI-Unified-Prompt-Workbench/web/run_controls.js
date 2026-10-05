import {api} from '../../scripts/api.js';

export function mountRunControls(host,{app,element,button,report,prepareTask,onSubmitted,historyHost=host}){
    const bar=element('div',null,host,{className:'uw-toolbar uw-run-actions'}),status=element('span','',bar);status.setAttribute('role','status');
    let submitting=false,currentTask=null,activeService=null,serviceStatus='';
    const run=button(prepareTask?'选择任务':'运行一次','run',async()=>{
        if(submitting||disposed)return;
        submitting=true;run.disabled=true;status.textContent='正在检查并提交任务…';
        try{
            const task=await prepareTask?.();if(disposed)return;
            if(task&&(task.reason||(!task.execute&&!task.queueNodeIds?.length)))throw new Error(task.reason||'当前任务没有可运行的输出节点。');
            if(task?.execute){
                activeService=task;serviceStatus='正在优化提示词…';status.textContent=serviceStatus;updateStop();
                const result=await task.execute();
                serviceStatus=result===false?'本次优化已取消。':'优化完成，请检查右侧结果。';
                if(!disposed)status.textContent=serviceStatus;
            }else{
                let requestId=null,queued=false,result;
                const queueing=event=>{if(requestId===null&&event.detail?.requestId!=null)requestId=event.detail.requestId;};
                const accepted=event=>{if(requestId!==null&&event.detail?.requestId===requestId&&event.detail.batchCount>0)queued=true;};
                api.addEventListener('promptQueueing',queueing);api.addEventListener('promptQueued',accepted);
                try{result=task?await app.queuePrompt(0,1,{queueNodeIds:task.queueNodeIds}):await app.queuePrompt(0,1);}
                finally{api.removeEventListener('promptQueueing',queueing);api.removeEventListener('promptQueued',accepted);}
                if(result===false||!queued)throw new Error('任务未提交，请查看节点或运行错误提示。');
                if(!disposed){report.clear?.('run-controls');onSubmitted?.(task);await refresh();}
            }
        }catch(error){
            if(activeService)serviceStatus='优化失败，请按提示调整后重试。';
            if(!disposed)status.textContent=activeService?serviceStatus:'任务未提交，请按提示调整后重试。';
            throw error;
        }finally{activeService=null;submitting=false;if(!disposed){run.disabled=Boolean(currentTask?.reason);updateStop();}}
    },bar);
    run.disabled=Boolean(prepareTask);
    const stop=button('停止当前运行','interrupt',async()=>{
        if(stopping||disposed)return;
        stopping=true;stop.setAttribute('aria-disabled','true');
        try{
            if(activeService){await activeService.cancel?.();return;}
            if(currentTask?.task==='optimize'){report('当前没有正在优化的提示词。');return;}
            const queue=await api.getQueue({throwOnError:true});if(disposed)return;
            hasRunning=queue.Running.length>0;
            if(!hasRunning){report('当前没有正在运行的任务。');return;}
            const item=queue.Running[0],id=item.prompt?.[1]||item[1]||item.prompt_id;
            if(typeof id!=='string'||!id)throw new Error('无法确认正在运行的任务，请在 ComfyUI 队列中停止。');
            await api.interrupt(id);if(!disposed)await refresh();
        }finally{
            stopping=false;
            if(!disposed){stop.setAttribute('aria-disabled','false');updateStop();}
        }
    },bar);
    const history=element('details',null,historyHost,{className:'uw-run-history'});element('summary','队列与最近结果',history);const results=element('div',null,history);
    button('刷新状态','refresh-run',refresh,history);
    let disposed=false,version=0,stopping=false,hasRunning=false;
    function updateStop(){
        stop.textContent=activeService?'取消提示词优化':'停止当前运行';
        if(!stopping)stop.disabled=currentTask?.task==='optimize'?!activeService:!activeService&&!hasRunning;
    }
    async function refresh(){
        const token=++version;
        try{
            const queue=await api.getQueue({throwOnError:true});if(disposed||token!==version)return;
            status.textContent=activeService?'正在优化提示词…':currentTask?.task==='optimize'&&serviceStatus?serviceStatus:`运行中 ${queue.Running.length} · 等待 ${queue.Pending.length}`;hasRunning=queue.Running.length>0;updateStop();
            if(!history.open)return;
            const response=await api.fetchApi('/history?max_items=20');if(!response.ok)throw new Error('历史记录暂时不可读，请重试。');
            const records=await response.json();if(disposed||token!==version)return;results.replaceChildren();
            if(!Object.keys(records).length)element('p','还没有运行记录。',results);
            for(const[id,record]of Object.entries(records).reverse()){
                const row=element('section',null,results,{className:'uw-resource-row'});element('span',`${record.status?.status_str==='success'?'完成':record.status?.status_str==='error'?'失败':'运行记录'} · ${id.slice(0,8)}`,row);
                for(const output of Object.values(record.outputs||{}))for(const picture of output.images||[]){
                    const url='/view?'+new URLSearchParams({filename:picture.filename,subfolder:picture.subfolder||'',type:picture.type||'output'});
                    const link=element('a','查看图片',row,{href:url,target:'_blank',rel:'noopener'});link.title=picture.filename;
                }
                if(record.status?.status_str==='error'){const message=record.status.messages?.find(entry=>entry[0]==='execution_error')?.[1];element('p',message?.exception_message||'请回到画布检查运行错误。',row);}
            }
        }catch(error){if(!disposed&&token===version&&!activeService){status.textContent='状态读取失败；可重试。';report(error);}}
    }
    const update=()=>void refresh();history.ontoggle=update;api.addEventListener('status',update);api.addEventListener('execution_success',update);api.addEventListener('execution_error',update);void refresh();
    return {setTask(task){currentTask=task;run.textContent=task.label;run.title=task.reason||task.label;run.disabled=submitting||Boolean(task.reason);updateStop();},dispose(){disposed=true;version++;if(activeService)void Promise.resolve(activeService.cancel?.()).catch(()=>{});for(const event of ['status','execution_success','execution_error'])api.removeEventListener(event,update);}};
}
