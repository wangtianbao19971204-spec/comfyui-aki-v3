import {api} from '../../scripts/api.js';

export function mountRunControls(host,{app,element,button,report}){
    const bar=element('div',null,host,{className:'uw-toolbar'}),status=element('span','',bar);status.setAttribute('role','status');
    const run=button('运行一次','run',async()=>{run.disabled=true;status.textContent='正在提交当前工作流…';try{const result=await app.queuePrompt(0,1);if(result===false)throw new Error('工作流未提交，请查看节点或运行错误提示。');await refresh();}finally{run.disabled=false;}},bar);
    const stop=button('停止当前运行','interrupt',async()=>{
        if(stopping||disposed)return;
        stopping=true;stop.setAttribute('aria-disabled','true');
        try{
            const queue=await api.getQueue({throwOnError:true});if(disposed)return;
            hasRunning=queue.Running.length>0;
            if(!hasRunning){report('当前没有正在运行的任务。');return;}
            const item=queue.Running[0],id=item.prompt?.[1]||item[1]||item.prompt_id;
            if(typeof id!=='string'||!id)throw new Error('无法确认正在运行的任务，请在 ComfyUI 队列中停止。');
            await api.interrupt(id);if(!disposed)await refresh();
        }finally{
            stopping=false;
            if(!disposed){stop.setAttribute('aria-disabled','false');stop.disabled=!hasRunning;}
        }
    },bar);
    const history=element('details',null,host,{className:'uw-run-history'});element('summary','队列与最近结果',history);const results=element('div',null,history);
    button('刷新状态','refresh-run',refresh,bar);
    let disposed=false,version=0,stopping=false,hasRunning=false;
    async function refresh(){
        const token=++version;
        try{
            const queue=await api.getQueue({throwOnError:true});if(disposed||token!==version)return;
            status.textContent=`运行中 ${queue.Running.length} · 等待 ${queue.Pending.length}`;hasRunning=queue.Running.length>0;if(!stopping)stop.disabled=!hasRunning;
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
        }catch(error){if(!disposed&&token===version){status.textContent='状态读取失败；可重试。';report(error);}}
    }
    const update=()=>void refresh();history.ontoggle=update;api.addEventListener('status',update);api.addEventListener('execution_success',update);api.addEventListener('execution_error',update);void refresh();
    return {dispose(){disposed=true;version++;for(const event of ['status','execution_success','execution_error'])api.removeEventListener(event,update);}};
}
