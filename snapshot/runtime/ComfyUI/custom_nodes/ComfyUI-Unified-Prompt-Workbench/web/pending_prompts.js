import {mountInsertionActions} from './prompt_target.js';
import {readModelPrompt} from './prompt_resource.js';
const animaKinds=new Set(['character','clothing','pose','background','artist','style_quality']);
const browserLimits={positive:65536,negative:16384};
const browserUuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function browserIdentity(resource){
    if(typeof resource.id!=='string'||!browserUuid.test(resource.id))throw new Error('网页提示词缺少有效的接收 UUID。');
    let url;
    try{url=new URL(resource.source_url);}catch{throw new Error('网页提示词来源地址无效。');}
    const host=url.hostname;
    const publicPostQuery=host==='gelbooru.com'&&url.pathname==='/index.php'&&/^\?page=post&s=view&id=[0-9]+$/.test(url.search);
    let decodedPath;
    try{decodedPath=decodeURIComponent(url.pathname);}catch{throw new Error('网页提示词来源地址无效。');}
    if(typeof resource.source_url!=='string'||resource.source_url.length>2048||url.protocol!=='https:'||url.username||url.password||(url.search&&!publicPostQuery)||url.hash||url.port||url.href!==resource.source_url||url.pathname.startsWith('//')||
        /[\s\\\u0000-\u001f\u007f]/.test(decodedPath)||decodedPath.split('/').some(part=>part==='.'||part==='..')||
        /[\s\\\u0000-\u001f\u007f]/.test(resource.source_url)||!host.includes('.')||/^[\d.]+$|[:\[\]]/.test(host)||/(?:^|\.)(?:localhost|local|internal|lan|home|test|invalid|onion)$/.test(host)){
        throw new Error('网页提示词来源须为公开 HTTPS 地址，不能包含认证或额外查询信息。');
    }
    return {id:resource.id.toLowerCase(),source_url:resource.source_url};
}

function browserText(text,usage,allowEmpty=false){
    if(!Object.hasOwn(browserLimits,usage))throw new Error('网页提示词必须明确正向或负向。');
    if(typeof text!=='string'||(!allowEmpty&&!text.trim()))throw new Error('网页提示词正文不能为空。');
    if(Array.from(text).length>browserLimits[usage])throw new Error('网页提示词正文超过当前方向的长度上限。');
    return text;
}

function browserItem(resource,restored=false){
    const identity=browserIdentity(resource),usage=resource.usage;
    if(restored&&typeof resource.sourceText!=='string')throw new Error('网页提示词草稿缺少原始正文。');
    const sourceText=browserText(resource.sourceText??resource.text,usage);
    const text=browserText(restored?resource.text:resource.text??sourceText,usage,restored);
    if(!restored&&text!==sourceText)throw new Error('新接收的网页提示词必须与原始正文一致。');
    if(resource.sectionKey!=null&&resource.sectionKey!==usage)throw new Error('网页提示词分段与正负向不一致。');
    if(restored&&(!Number.isFinite(resource.weight)||resource.weight<0||resource.weight>3))throw new Error('网页提示词草稿权重无效。');
    const item={provider:'browser',...identity,usage,sectionKey:usage,sourceText,text,title:typeof resource.title==='string'?resource.title:'网页临时提示词',
        weight:restored?resource.weight:1,enabled:restored?resource.enabled!==false:true,modified:restored&&(resource.modified===true||text!==sourceText)};
    // The received identity, direction and original body never become editable draft state.
    for(const key of ['provider','id','source_url','usage','sectionKey','sourceText'])Object.defineProperty(item,key,{writable:false,configurable:false});
    return item;
}

function browserParts(resource){
    browserIdentity(resource);
    if(resource.usage!=null&&!Object.hasOwn(browserLimits,resource.usage))throw new Error('网页提示词必须明确正向或负向。');
    if(resource.sections==null)return [browserItem(resource)];
    if(typeof resource.sections!=='object'||Array.isArray(resource.sections)||Object.keys(resource.sections).some(key=>!Object.hasOwn(browserLimits,key)))throw new Error('网页提示词分段必须明确正向或负向。');
    const parts=[];
    for(const usage of ['positive','negative']){
        const text=resource.sections[usage];
        if(text==null)continue;
        if(typeof text!=='string')throw new Error('网页提示词分段正文无效。');
        browserText(text,usage,true);
        if(!text.trim())continue;
        parts.push(browserItem({...resource,sections:null,text,sourceText:text,sectionKey:usage,usage,title:(resource.title||'网页临时提示词')+(usage==='positive'?' · 正向':' · 负向')}));
    }
    if(!parts.length)throw new Error('网页提示词正文不能为空。');
    return parts;
}

export function validateBrowserPendingResource(resource){return browserParts(resource);}

export function createPendingPrompts({element,button,insertionOptions,report,onCount,openSource,draft=[]}) {
    const items=draft;
    let host=null,controls=null,actions=null,targetNote=null,fullPreview=null,scope='all',generation=0,previewVersion=0,previewWriter=null,previewDirection='',previewBefore=null;
    const providers=['library','tag','loras','embeddings','gallery','anima','browser'];
    if(!items.length)try{const saved=JSON.parse(sessionStorage.getItem('uw-pending-draft')||'[]');if(Array.isArray(saved))items.push(...saved.filter(item=>providers.includes(item.provider)&&item.id));}catch{}
    const browserSeen=new Set();
    for(let index=0;index<items.length;index++)if(items[index].provider==='browser'){
        try{const item=browserItem(items[index],true),key=item.id+':'+item.usage;if(browserSeen.has(key)){items.splice(index--,1);continue;}browserSeen.add(key);items[index]=item;}
        catch{items.splice(index--,1);report('无效的网页待用草稿未载入，请重新发送原网页提示词。');}
    }
    const persist=()=>{generation++;onCount(items.length);try{sessionStorage.setItem('uw-pending-draft',JSON.stringify(items));}catch{report('浏览器无法保存会话草稿；当前页面内的内容仍然保留。');}};
    onCount(items.length);
    async function read(item,sharedReads,selected) {
        if(item.provider==='browser'){
            browserIdentity(item);browserText(item.text,item.usage);browserText(item.sourceText,item.usage);
            return {text:item.sourceText,usage:item.usage};
        }
        if(item.provider==='anima'){
            if(!animaKinds.has(item.kind)||!item.sourceId)throw new Error('选择器待用项缺少稳定来源，请移除后重新加入。');
            if(!sharedReads.has(item.kind))sharedReads.set(item.kind,(async()=>{
                if(item.kind==='artist'){
                    const keys=selected.filter(entry=>entry.provider==='anima'&&entry.kind==='artist').map(entry=>'shared:'+entry.sourceId);
                    const response=await fetch('/anima-tools/artist-page',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected_keys:keys,lookup_keys:keys,limit:0}),cache:'no-store'});
                    const data=await response.json();
                    if(!response.ok||!data.success)throw new Error(data.error||'原画师资料暂不可读，请稍后重试。');
                    return new Map((data.lookup||[]).map(entry=>[String(entry.id),entry]));
                }
                const response=await fetch('/anima-tools/shared-prompts?'+new URLSearchParams({kind:item.kind}),{cache:'no-store'});
                if(!response.ok)throw new Error('原选择器资料暂不可读，请稍后重试。');
                const data=await response.json();return new Map((data.items||[]).map(entry=>[String(entry.id),entry]));
            })());
            const fresh=(await sharedReads.get(item.kind)).get(item.sourceId),semantic=fresh?._semantic;
            if(!fresh?.shared||!semantic?.binding||!['reviewed','classified'].includes(semantic.disposition)||semantic.manual_search_eligible!==true||semantic.usage!=='positive'||!['atomic_tag','fragment'].includes(semantic.content_type))throw new Error('原选择器资料已不可用，请移除后重新加入。');
            return {text:fresh.tags,usage:'positive',binding:semantic.binding};
        }
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
    const included=item=>item.enabled!==false&&(scope==='all'||item.usage==='target'||item.usage===scope);
    function compose(){return items.filter(item=>included(item)&&item.text.trim()).map(item=>{
        const text=item.provider==='anima'?item.text.replace(/(?:\s*,\s*)+$/,''):item.text;
        return item.weight===1?text:`(${text}:${item.weight})`;
    }).join(', ');}
    const add=resource=>{
        if(!providers.includes(resource.provider)||!resource.id)throw new Error('缺少资源的稳定身份。');
        if(resource.provider==='browser'){
            const parts=browserParts(resource),newItems=[];
            for(const part of parts){
                const existing=items.find(item=>item.provider==='browser'&&item.id===part.id&&item.sectionKey===part.sectionKey);
                if(existing){if(existing.sourceText!==part.sourceText||existing.source_url!==part.source_url)throw new Error('网页接收 UUID 已存在，但原文或来源不同，请重新发送。');}
                else newItems.push(part);
            }
            if(!newItems.length){persist();report('这条网页提示词已在待用列表，临时编辑仍保留。');return;}
            items.push(...newItems);persist();report(`已加入待用列表，共 ${items.length} 条。`);if(host?.isConnected)render(host);return;
        }
        if(resource.provider==='anima'&&(!animaKinds.has(resource.kind)||!resource.sourceId||resource.id!==`${resource.kind}:${resource.sourceId}`||!resource.sourceBinding))throw new Error('选择器资料缺少稳定来源。');
        if(resource.sections){for(const direction of ['positive','negative'])if(resource.sections[direction]?.trim())add({...resource,sections:null,text:resource.sections[direction],sectionKey:direction,usage:direction,title:resource.title+(direction==='positive'?' · 正向':' · 负向')});return;}
        const existing=items.find(item=>item.provider===resource.provider&&item.id===resource.id&&item.sectionKey===resource.sectionKey);
        if(existing){if(resource.resolveText){existing.resolveText=resource.resolveText;report('已重新关联原图库选择，临时编辑仍保留。');}else report('这条资料已在待用列表。');return;}
        items.push({...resource,text:String(resource.text || ''),usage:resource.usage || 'target',weight:1,enabled:true,modified:false});
        persist();report(`已加入待用列表，共 ${items.length} 条。`);if(host?.isConnected)render(host);
    };
    const addMany=resources=>{
        if(!Array.isArray(resources)||!resources.length)throw new Error('请先选择至少一条资料。');
        if(resources.some(resource=>resource.provider!=='anima'||!animaKinds.has(resource.kind)||!resource.sourceId||resource.id!==`${resource.kind}:${resource.sourceId}`||!resource.sourceBinding||!String(resource.text||'').trim()))throw new Error('选择器资料缺少稳定来源或正文。');
        const seen=new Set(items.map(item=>`${item.provider}:${item.id}:${item.sectionKey||''}`));
        let added=0,duplicate=0;
        for(const resource of resources){
            const key=`${resource.provider}:${resource.id}:${resource.sectionKey||''}`;
            if(seen.has(key)){duplicate++;continue;}
            seen.add(key);items.push({...resource,text:String(resource.text),weight:1,enabled:true,modified:false});added++;
        }
        if(added){persist();if(host?.isConnected)render(host);}
        report(added?`已加入 ${added} 条待用${duplicate?`；${duplicate} 条已存在，未重复加入`:''}。`:`${duplicate} 条资料已在待用列表，未重复加入。`);
        return {added,duplicate};
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
        if(selected.some(item=>!item.text.trim()))throw new Error('待用内容中有空白正文，请填写或移除后再应用。');
        const sharedReads=new Map(),latest=await Promise.all(selected.map(item=>read(item,sharedReads,selected)));let changed=false;
        if(version!==generation)throw new Error('待用内容或方向已变化，请核对预览后重新应用。');
        latest.forEach((value,i)=>{
            const item=selected[i];
            if(item.provider!=='browser'&&!item.modified && value.text!==item.text){item.text=value.text;changed=true;}
            if(item.provider!=='browser'&&item.sourceText!=null&&value.text!==item.sourceText){item.sourceText=value.text;changed=true;}
            if(item.provider==='anima'&&value.binding!==item.sourceBinding){item.sourceBinding=value.binding;changed=true;}
            if(item.provider!=='browser'&&!item.split&&item.usage!=='target'&&value.usage!==item.usage){item.usage=value.usage;changed=true;}
        });
        if(changed){persist();render(host);throw new Error('原资料已更新，请核对预览；手动拆分和临时编辑的内容保留，再次应用前请检查。');}
        if(selected.some(item=>item.usage!=='target'&&item.usage!==direction))throw new Error('待用资料的正负向与目标不同，请选择对应方向分开应用；混合正文需要先拆分。');
        preparedItems=selected.map(item=>({provider:item.provider,id:item.id}));
        return compose();
    }
    async function updateFullPreview(){
        if(!fullPreview?.isConnected)return;
        const version=++previewVersion,writer=previewWriter,selected=items.filter(included),text=compose();
        previewBefore=null;
        if(!writer){fullPreview.textContent='请选择当前工作流的写入目标和正负方向。';return;}
        if(!selected.length){fullPreview.textContent='本次没有已启用的待用内容。';return;}
        if(selected.some(item=>item.splitDraft||!item.text.trim()||(item.usage!=='target'&&item.usage!==previewDirection))){fullPreview.textContent='请先处理空正文、未完成拆分或与目标不一致的正负向。';return;}
        try{
            let result=await writer.preview({text,action:controls?.picker.value||'append_end'});
            if(result?.status==='busy'){
                await new Promise(resolve=>setTimeout(resolve,0));
                if(version!==previewVersion||!fullPreview?.isConnected)return;
                result=await writer.preview({text,action:controls?.picker.value||'append_end'});
            }
            if(version!==previewVersion||!fullPreview?.isConnected)return;
            if(result?.status!=='preview')throw new Error('目标暂不可用，请重新选择。');
            previewBefore=result.before;
            fullPreview.textContent=result.after;
        }catch(error){if(version===previewVersion&&fullPreview?.isConnected)fullPreview.textContent=error.message;}
    }
    function refreshTarget(action=null){
        if(!actions?.isConnected)return;
        actions.replaceChildren();controls=null;previewBefore=null;
        const options=insertionOptions();
        previewWriter=options.onInsert||null;previewDirection=options.targetDirection||'';
        targetNote.textContent=options.onInsert?'将应用到：'+options.targetLabel+(options.targetDirection==='negative'?' · 负向':' · 正向'):'请在底栏选择目标并确认正负向。';
        if(options.onInsert){
            controls=mountInsertionActions(actions,options.onInsert,()=>prepare(options.targetDirection),report,recordApplied,()=>previewBefore);
            if(options.onInsert.supportsActions?.includes(action)){
                controls.picker.value=action;
                controls.picker.dispatchEvent(new Event('change'));
            }
            const apply=controls.apply,applyAction=apply.onclick;
            apply.onclick=async()=>{
                try{await applyAction();}
                finally{if(controls?.apply===apply)await updateFullPreview();}
            };
            controls.undo.addEventListener('click',()=>{void updateFullPreview();});
            controls.picker.addEventListener('change',updateFullPreview);
        }
        void updateFullPreview();
    }
    function render(parent,focus=null){
        const action=parent===host&&host?.isConnected?controls?.picker.value:null;
        host=parent;if(!host?.isConnected)return;host.replaceChildren();controls=null;actions=null;targetNote=null;fullPreview=null;
        element('p','会话草稿自动保留，重新打开工作台可继续。排序、权重与正文编辑只影响本次使用。',host);
        element('small','权重会写为 (内容:数值)；不同分支的编码器可能按原文处理，请在应用前核对完整字段。',host);
        if(!items.length){element('p','从资料或 Tag 的“更多”中加入待用列表。单条资料仍可直接插入。',host);if(focus){host.tabIndex=-1;host.setAttribute('role','region');host.setAttribute('aria-label','待用列表');host.focus();}return;}
        const filter=element('label','本次应用 ',host),picker=element('select',null,filter);picker.setAttribute('aria-label','待用列表方向');
        for(const[value,label]of [['all','全部待用内容'],['positive','仅正向与随目标内容'],['negative','仅负向与随目标内容']])element('option',label,picker,{value});picker.value=scope;picker.onchange=()=>{scope=picker.value;generation++;render(host,{scope:true});};
        const list=element('div',null,host);
        items.forEach((item,index)=>{
            const row=element('section',null,list,{className:'uw-pending-item'});
            row.dataset.uwDisabled=String(item.enabled===false);
            const bar=element('div',null,row,{className:'uw-toolbar'});element('strong',item.title || item.id,bar);
            const sourceLabels={library:'共享资料',tag:'基础 Tag',loras:'LoRA',embeddings:'Embedding',gallery:'图库',anima:'Anima 选择器',browser:'网页临时提示词'};
            if(item.provider==='anima')sourceLabels.anima+=' · '+({character:'角色',clothing:'服装',pose:'姿势',background:'背景',artist:'画师',style_quality:'画风质量'}[item.kind]||item.kind);
            const source=element('small','来源：'+(sourceLabels[item.provider]||item.provider)+(item.modified?' · 本次已编辑':''),row);source.title=item.id;
            if(item.provider==='browser'){
                element('small',item.source_url,row);
                const original=element('details',null,row);element('summary','接收到的原始正文',original);element('pre',item.sourceText,original);
            }else if(openSource)button('查看来源','pending-source',()=>openSource(item),bar);
            const enabled=element('input',null,element('label','本次启用',bar),{type:'checkbox'});enabled.checked=item.enabled!==false;enabled.setAttribute('aria-label',(item.title||item.id)+' · 本次启用');
            enabled.onchange=()=>{item.enabled=enabled.checked;row.dataset.uwDisabled=String(!enabled.checked);persist();updatePreview();};
            const move=delta=>{const other=index+delta;if(other<0||other>=items.length)return;[items[index],items[other]]=[items[other],items[index]];persist();render(host,{item,action:delta<0?'pending-up':'pending-down'});};
            button('上移','pending-up',()=>move(-1),bar).disabled=index===0;
            button('下移','pending-down',()=>move(1),bar).disabled=index===items.length-1;
            button('移除','pending-remove',()=>{items.splice(index,1);persist();render(host,{item:items[Math.min(index,items.length-1)],action:'pending-remove'});},bar);
            const weight=element('input',null,bar,{type:'number',step:0.05,min:0,max:3,value:String(item.weight)});weight.setAttribute('aria-label','本次权重');
            weight.onchange=()=>{const value=Number(weight.value);if(!weight.value.trim()||!Number.isFinite(value)||value<0||value>3){report('请输入 0 到 3 之间的权重；原权重已保留。');weight.value=String(item.weight);return;}item.weight=value;persist();updatePreview();};
            element('small',' · '+(item.usage==='target'?'随当前目标':item.usage==='positive'?'正向':item.usage==='negative'?'负向':'包含正负向，需拆分'),row);
            const text=element('textarea',null,row,{value:item.text});text.setAttribute('aria-label','仅本次使用的正文');
            text.oninput=()=>{item.sourceText??=item.text;item.text=text.value;item.modified=true;source.textContent='来源：'+(sourceLabels[item.provider]||item.provider)+' · 本次已编辑';persist();updatePreview();};
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
        element('strong','待用内容',host);
        const preview=element('pre',compose(),host,{className:'uw-pending-preview'});
        element('strong','写入后的完整字段 · 应用前会复核原资料',host);
        fullPreview=element('pre','',host,{className:'uw-pending-preview'});
        const updatePreview=()=>{preview.textContent=compose();if(controls)controls.undo.disabled=true;void updateFullPreview();};
        targetNote=element('p','',host);
        actions=element('div',null,host,{className:'uw-toolbar uw-use-actions'});
        refreshTarget(action);
        if(focus?.scope)picker.focus();
        else if(focus?.item){
            const row=list.children[items.indexOf(focus.item)];
            const action=focus.action&&row?.querySelector(`[data-uw="${focus.action}"]:not([disabled])`);
            (action||row?.querySelector('[aria-label="仅本次使用的正文"]'))?.focus();
        }
    }
    return {add,addMany,render,refreshTarget,prepare,compose,get items(){return items.map(item=>({...item}));}};
}
