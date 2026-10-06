import {api as defaultApi} from '../../scripts/api.js';
import {validateBrowserPendingResource} from './pending_prompts.js';

const route='/unified-workbench/browser-import',eventName='unified-workbench-browser-prompt',draftKey='uw-pending-draft';
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let installation;

function browserResource(payload){
    if(!payload||payload.destination!=='workbench'||typeof payload.positive!=='string'||!payload.positive.trim()||typeof payload.negative!=='string'||
        typeof payload.title!=='string'||Array.from(payload.title).length>256)throw new Error('网页提示词格式无效，请检查原网页后重新发送。');
    const resource={provider:'browser',id:payload.import_id,source_url:payload.source_url,title:payload.title||'网页临时提示词',
        sections:{positive:payload.positive,negative:payload.negative}};
    return {resource,parts:validateBrowserPendingResource(resource)};
}

function storedDraft(storage,parts){
    let raw,items;
    try{raw=storage.getItem(draftKey);items=JSON.parse(raw||'[]');}
    catch{throw new Error('网页提示词会话存储不可用，尚未确认接收。');}
    if(!Array.isArray(items)||!parts.every(part=>items.some(item=>item&&item.provider==='browser'&&item.id===part.id&&item.usage===part.usage&&item.sectionKey===part.usage&&
        item.source_url===part.source_url&&item.sourceText===part.sourceText&&typeof item.text==='string'&&Array.from(item.text).length<=(part.usage==='positive'?65536:16384)&&
        Number.isFinite(item.weight)&&item.weight>=0&&item.weight<=3))){throw new Error('网页提示词未完整保存到本页会话，尚未确认接收。');}
    try{storage.setItem(draftKey,raw);if(storage.getItem(draftKey)!==raw)throw new Error();}
    catch{throw new Error('网页提示词会话保存失败，尚未确认接收。');}
}

export function createBrowserImportReceiver({api=defaultApi,openWorkbench,storage={getItem:key=>globalThis.sessionStorage.getItem(key),setItem:(key,value)=>globalThis.sessionStorage.setItem(key,value)},request=globalThis.fetch,
    makeUuid=()=>globalThis.crypto.randomUUID(),report=()=>{},setTimer=setTimeout,clearTimer=clearTimeout}={}){
    const receiverId=makeUuid();
    if(!uuid.test(receiverId))throw new Error('网页接收窗口初始化失败。');
    let serial=Promise.resolve(),disposed=false;
    const accepted=new Set(),retried=new Set(),timers=new Map();
    const enqueue=task=>{const result=serial.then(()=>disposed?undefined:task());serial=result.catch(()=>{});return result;};
    async function call(path,body){
        const controller=new AbortController(),timer=setTimer(()=>controller.abort(),10000);
        try{
            const response=await request(route+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,
                ...(body?{body:JSON.stringify(body)}:{}),cache:'no-store',signal:controller.signal});
            let data;try{data=await response.json();}catch{throw new Error('网页接收服务响应异常，请重试接收。');}
            return {status:response.status,ok:response.ok,data};
        }catch(error){if(error.message?.startsWith('网页'))throw error;throw new Error('网页接收服务暂时不可达，请重试接收。');}
        finally{clearTimer(timer);}
    }
    function later(id,delay){
        if(disposed||retried.has(id))return false;
        retried.add(id);
        const wait=Math.min(65000,Math.max(1000,Number.isFinite(delay)?delay+100:61000));
        timers.set(id,setTimer(()=>{timers.delete(id);void backfill();},wait));return true;
    }
    async function release(body){try{await call('/release',body);}catch{report('本页尚未确认接收；服务恢复后可以重试。');}}
    async function receive(payload){
        let body=null,saved=false;
        try{
            const initial=browserResource(payload),id=initial.resource.id.toLowerCase();
            if(accepted.has(id))return;
            const claim=await call('/claim',{import_id:id,receiver_id:receiverId});
            if(claim.ok&&claim.data.ok&&claim.data.delivery==='accepted'){accepted.add(id);return;}
            if(claim.status===409&&claim.data.error==='already_claimed'){
                const scheduled=later(id,claim.data.retry_after_ms);
                report(scheduled?'另一窗口正在接收这条网页提示词，稍后会检查接收结果。':'这条网页提示词仍由另一窗口接收，可稍后重试。');return;
            }
            if(!claim.ok||claim.data.ok!==true||claim.data.delivery!=='claimed'||!uuid.test(claim.data.claim_token||''))throw new Error('网页提示词尚未取得接收权限，请重试接收。');
            body={import_id:id,receiver_id:receiverId,claim_token:claim.data.claim_token};
            const claimed=browserResource(claim.data.payload);
            if(claimed.resource.id.toLowerCase()!==id)throw new Error('网页接收回执不一致，尚未确认接收。');
            if(disposed){await release(body);return;}
            const owner=await openWorkbench({page:'library'});
            if(disposed){await release(body);return;}
            if(!Number.isFinite(claim.data.claim_expires_at)||claim.data.claim_expires_at*1000<=Date.now()){
                later(id,1000);throw new Error('网页接收权限已到期，稍后会重新检查接收。');
            }
            // The pending list owns draft edits and never writes a workflow target here.
            owner.addPending(claimed.resource);
            storedDraft(storage,claimed.parts);saved=true;
            try{await owner.showPending();}catch{report('网页提示词已保留在本页待用列表，请关闭当前编辑后查看。');}
            let acknowledged=false;
            for(let attempt=0;attempt<2;attempt++){
                try{const ack=await call('/ack',body);if(ack.ok&&ack.data.ok===true&&ack.data.delivery==='accepted'){acknowledged=true;break;}}
                catch{}
            }
            if(!acknowledged){
                later(id,Math.max(0,(Number(claim.data.claim_expires_at)*1000||Date.now()+61000)-Date.now()));
                report('网页提示词已保留在本页待用列表，但服务尚未确认接收；请稍后重试接收。');return;
            }
            accepted.add(id);if(timers.has(id)){clearTimer(timers.get(id));timers.delete(id);}
            report('网页提示词已加入工作台待用列表，请核对后采用。');
        }catch(error){
            if(body&&!saved)await release(body);
            report(error.message?.startsWith('网页')?error.message:'网页提示词接收失败，尚未确认接收。');
        }
    }
    function backfill(){return enqueue(async()=>{
        try{
            const result=await call('');
            if(!result.ok||result.data.ok!==true||!Array.isArray(result.data.items))throw new Error('网页待接收列表暂时不可读，请重试接收。');
            for(const payload of result.data.items){if(disposed)return;await receive(payload);}
        }catch(error){report(error.message?.startsWith('网页')?error.message:'网页接收服务暂时不可达，请重试接收。');}
    });}
    const onPrompt=event=>{void enqueue(()=>receive(event.detail));},onReconnect=()=>{void backfill();};
    api.addEventListener(eventName,onPrompt);api.addEventListener('reconnected',onReconnect);
    const ready=backfill();
    return {receiverId,ready,backfill,whenIdle:()=>serial,dispose(){disposed=true;api.removeEventListener(eventName,onPrompt);api.removeEventListener('reconnected',onReconnect);for(const timer of timers.values())clearTimer(timer);timers.clear();}};
}

export function installBrowserImportReceiver({openWorkbench,api=defaultApi}={}){
    if(installation)return installation;
    let notice;
    const report=message=>{
        if(!notice){
            notice=document.createElement('section');notice.id='uw-browser-import-status';notice.setAttribute('role','status');
            notice.style.cssText='position:fixed;right:16px;bottom:16px;z-index:2147483200;max-width:420px;padding:12px;border:1px solid var(--uw-border,#8290a8);border-radius:10px;background:var(--uw-panel,#242a34);color:var(--uw-text,#eee);font:14px system-ui;box-shadow:0 3px 12px #0005';
            const text=document.createElement('span'),retry=document.createElement('button'),close=document.createElement('button');
            retry.textContent='重试接收';retry.onclick=()=>{void installation.backfill();};close.textContent='关闭';close.onclick=()=>{notice.hidden=true;};
            notice.append(text,retry,close);document.body.append(notice);
        }
        notice.firstChild.textContent=message;notice.hidden=false;
    };
    installation=createBrowserImportReceiver({api,openWorkbench,report});return installation;
}
