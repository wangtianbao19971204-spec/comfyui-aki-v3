import {mountInsertionActions} from './prompt_target.js';
import {readModelPrompt} from './prompt_resource.js';

export function createPendingPrompts({element,button,insertionOptions,report,onCount,draft=[]}) {
    const items=draft;
    let host=null,controls=null,actions=null,targetNote=null,scope='all',generation=0;
    const providers=['library','tag','loras','embeddings','gallery'];
    if(!items.length)try{const saved=JSON.parse(sessionStorage.getItem('uw-pending-draft')||'[]');if(Array.isArray(saved))items.push(...saved.filter(item=>providers.includes(item.provider)&&item.id));}catch{}
    const persist=()=>{generation++;onCount(items.length);try{sessionStorage.setItem('uw-pending-draft',JSON.stringify(items));}catch{report('浏览器无法保存会话草稿；当前页面内的内容仍然保留。');}};
    onCount(items.length);
    async function read(item) {
        if(['loras','embeddings'].includes(item.provider))return {text:await readModelPrompt(item.provider,item.id),usage:'target'};
        if(item.provider==='gallery'){
            if(typeof item.resolveText!=='function')throw new Error('图库待用草稿仍保留；请在原图库重新选取并加入，以便核对当前图片。');
            return {text:await item.resolveText(),usage:'target'};
        }
        const url=item.provider==='library'?'/prompt_selector/library/prompt?'+new URLSearchParams({prompt_id:item.id,include_semantic:'1',selection:'1'}):'/prompt_selector/tags/item?'+new URLSearchParams({id:item.id});
        const response=await fetch(url,{cache:'no-store'}),data=await response.json();
        if(!response.ok)throw new Error(data.error || '原资料不可读，请移除此项或重试。');
        if(item.provider==='library') {
            const semantic=data.prompt?._semantic;
            if(semantic && semantic.manual_search_eligible!==true)throw new Error('资料尚未确认用途，请先完成共享资料编辑。');
            if(item.sectionKey){const text=data.prompt.plan_sections?.[item.sectionKey];if(typeof text!=='string')throw new Error('原方案分段已变化，请移除后重新加入。');return {text,usage:item.sectionKey};}
            return {text:data.prompt.prompt,usage:semantic?.usage || item.usage};
        }
        return {text:data.item.text,usage:'target'};
    }
    const included=item=>scope==='all'||item.usage==='target'||item.usage===scope;
    function compose(){return items.filter(included).map(item=>item.weight===1?item.text:`(${item.text}:${item.weight})`).filter(Boolean).join(', ');}
    const add=resource=>{
        if(!providers.includes(resource.provider)||!resource.id)throw new Error('缺少资源的稳定身份。');
        if(resource.sections){for(const direction of ['positive','negative'])if(resource.sections[direction]?.trim())add({...resource,sections:null,text:resource.sections[direction],sectionKey:direction,usage:direction,title:resource.title+(direction==='positive'?' · 正向':' · 负向')});return;}
        const existing=items.find(item=>item.provider===resource.provider&&item.id===resource.id&&item.sectionKey===resource.sectionKey);
        if(existing){if(resource.resolveText){existing.resolveText=resource.resolveText;report('已重新关联原图库选择，临时编辑仍保留。');}else report('这条资料已在待用列表。');return;}
        items.push({...resource,text:String(resource.text || ''),usage:resource.usage || 'target',weight:1,modified:false});
        persist();report(`已加入待用列表，共 ${items.length} 条。`);if(host?.isConnected)render(host);
    };
    let preparedItems=[];
    async function recordApplied(){
        const ids=[...new Set(preparedItems.filter(item=>item.provider==='library').map(item=>item.id))];
        if(!ids.length)return;
        let revision=null,failed=0;
        const refreshRevision=async()=>{
            const response=await fetch('/prompt_selector/library/index',{cache:'no-store'}),data=await response.json();
            if(!response.ok)throw new Error('无法读取使用记录版本');
            const value=response.headers.get('ETag')||data.last_modified||data.revision;
            if(!value)throw new Error('缺少使用记录版本');
            return value;
        };
        for(const prompt_id of ids){
            try{
                for(let attempt=0;attempt<3;attempt++){
                    revision??=await refreshRevision();
                    const response=await fetch('/prompt_selector/prompts/mark_used',{method:'POST',headers:{'Content-Type':'application/json','If-Match':revision},body:JSON.stringify({prompt_id})});
                    if(response.status===409&&attempt<2){revision=null;continue;}
                    if(!response.ok)throw new Error('使用记录保存失败');
                    const data=await response.json();revision=response.headers.get('ETag')||data.revision||null;
                    break;
                }
            }catch{failed++;revision=null;}
        }
        if(failed)report('已应用到目标，但部分最近使用记录未保存。请检查服务连接；无需重复插入正文。');
    }
    async function prepare(direction){
        preparedItems=[];
        if(!items.length)throw new Error('待用列表为空，请从资料卡片加入。');
        const selected=items.filter(included),version=generation;
        if(!selected.length)throw new Error('这个方向没有待用内容。');
        if(selected.some(item=>item.splitDraft))throw new Error('请先保留或取消正在编辑的拆分，再应用待用内容。');
        const latest=await Promise.all(selected.map(read));let changed=false;
        if(version!==generation)throw new Error('待用内容或方向已变化，请核对预览后重新应用。');
        latest.forEach((value,i)=>{
            const item=selected[i];
            if(!item.modified && value.text!==item.text){item.text=value.text;changed=true;}
            if(item.sourceText!=null&&value.text!==item.sourceText){item.sourceText=value.text;changed=true;}
            if(!item.split&&item.usage!=='target'&&value.usage!==item.usage){item.usage=value.usage;changed=true;}
        });
        if(changed){persist();render(host);throw new Error('原资料已更新，请核对预览；手动拆分和临时编辑的内容保留，再次应用前请检查。');}
        if(selected.some(item=>item.usage!=='target'&&item.usage!==direction))throw new Error('待用资料的正负向与目标不同，请选择对应方向分开应用；混合正文需要先拆分。');
        preparedItems=selected.map(item=>({provider:item.provider,id:item.id}));
        return compose();
    }
    function refreshTarget(){
        if(!actions?.isConnected)return;
        actions.replaceChildren();controls=null;
        const options=insertionOptions();
        targetNote.textContent=options.onInsert?'将应用到：'+options.targetLabel+(options.targetDirection==='negative'?' · 负向':' · 正向'):'请在底栏选择目标并确认正负向。';
        if(options.onInsert)controls=mountInsertionActions(actions,options.onInsert,()=>prepare(options.targetDirection),report,recordApplied);
    }
    function render(parent,focus=null){
        host=parent;if(!host?.isConnected)return;host.replaceChildren();controls=null;actions=null;targetNote=null;
        element('p','会话草稿自动保留，重新打开工作台可继续。排序、权重与正文编辑只影响本次使用。',host);
        if(!items.length){element('p','从资料或 Tag 的“更多”中加入待用列表。单条资料仍可直接插入。',host);if(focus){host.tabIndex=-1;host.setAttribute('role','region');host.setAttribute('aria-label','待用列表');host.focus();}return;}
        const filter=element('label','本次应用 ',host),picker=element('select',null,filter);picker.setAttribute('aria-label','待用列表方向');
        for(const[value,label]of [['all','全部待用内容'],['positive','仅正向与随目标内容'],['negative','仅负向与随目标内容']])element('option',label,picker,{value});picker.value=scope;picker.onchange=()=>{scope=picker.value;generation++;render(host,{scope:true});};
        const list=element('div',null,host);
        items.forEach((item,index)=>{
            const row=element('section',null,list,{className:'uw-pending-item'});
            const bar=element('div',null,row,{className:'uw-toolbar'});element('strong',item.title || item.id,bar);
            const move=delta=>{const other=index+delta;if(other<0||other>=items.length)return;[items[index],items[other]]=[items[other],items[index]];persist();render(host,{item,action:delta<0?'pending-up':'pending-down'});};
            button('上移','pending-up',()=>move(-1),bar).disabled=index===0;
            button('下移','pending-down',()=>move(1),bar).disabled=index===items.length-1;
            button('移除','pending-remove',()=>{items.splice(index,1);persist();render(host,{item:items[Math.min(index,items.length-1)],action:'pending-remove'});},bar);
            const weight=element('input',null,bar,{type:'number',step:0.05,min:0,max:3,value:String(item.weight)});weight.setAttribute('aria-label','本次权重');
            weight.onchange=()=>{const value=Number(weight.value);if(!Number.isFinite(value)||value<0||value>3){report('权重应在 0 到 3 之间');weight.value=String(item.weight);return;}item.weight=value;persist();updatePreview();};
            element('small',item.usage==='target'?'随当前目标':item.usage==='positive'?'正向':item.usage==='negative'?'负向':'包含正负向，需拆分',row);
            const text=element('textarea',null,row,{value:item.text});text.setAttribute('aria-label','仅本次使用的正文');
            text.oninput=()=>{item.sourceText??=item.text;item.text=text.value;item.modified=true;persist();updatePreview();};
            const showSplit=()=>{
                if(row.querySelector('.uw-split-editor'))return;
                const form=element('div',null,row,{className:'uw-split-editor'});element('p','请分别填写要用于正向和负向的内容，允许只填写一项。上方保留原文供对照。',form);
                const positive=element('textarea',null,element('label','正向',form),{value:item.splitDraft.positive}),negative=element('textarea',null,element('label','负向',form),{value:item.splitDraft.negative});
                const retain=()=>{item.splitDraft={positive:positive.value,negative:negative.value};persist();};
                positive.oninput=retain;negative.oninput=retain;
                button('保留拆分结果','pending-split-save',()=>{
                    const parts=[['positive',positive.value.trim()],['negative',negative.value.trim()]].filter(([,text])=>text);
                    if(!parts.length)throw new Error('请至少填写一个方向。');
                    const {splitDraft,...original}=item;
                    items.splice(index,1,...parts.map(([usage,text])=>({...original,usage,text,split:true,modified:true,sourceText:item.sourceText??item.text,title:(item.title||'资料')+(usage==='positive'?' · 正向':' · 负向')})));persist();render(host,{item:items[index]});
                },form);
                button('取消拆分','pending-split-cancel',()=>{delete item.splitDraft;persist();form.remove();row.querySelector('[data-uw="pending-split"]')?.focus();},form);
            };
            if(item.splitDraft||!['positive','negative','target'].includes(item.usage))button('拆分正负向','pending-split',()=>{
                if(!item.splitDraft){item.splitDraft={positive:'',negative:''};persist();}
                showSplit();
            },bar);
            if(item.splitDraft)showSplit();
        });
        const preview=element('pre',compose(),host,{className:'uw-pending-preview'});
        const updatePreview=()=>{preview.textContent=compose();if(controls)controls.undo.disabled=true;};
        targetNote=element('p','',host);
        actions=element('div',null,host,{className:'uw-toolbar uw-use-actions'});
        refreshTarget();
        if(focus?.scope)picker.focus();
        else if(focus?.item){
            const row=list.children[items.indexOf(focus.item)];
            const action=focus.action&&row?.querySelector(`[data-uw="${focus.action}"]:not([disabled])`);
            (action||row?.querySelector('[aria-label="仅本次使用的正文"]'))?.focus();
        }
    }
    return {add,render,refreshTarget,prepare,compose,get items(){return items.map(item=>({...item}));}};
}
