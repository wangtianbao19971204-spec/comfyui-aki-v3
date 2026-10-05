const providers={prompts:'提示词',tags:'基础 Tag',loras:'LoRA',checkpoints:'基础模型',embeddings:'Embedding'};

// Aggregate the original services without keeping a second editable catalog.
export function mountResourceResults(host,{element,button,scope={},open,more,extraSections=[],state={}}) {
    const controller=new AbortController();
    const bar=element('div',null,host,{className:'uw-toolbar'});
    const sections=[...extraSections];
    const filters=[['all','全部'],['text','资料'],['models','模型']];if(extraSections.some(section=>section.dataset.kind==='images'))filters.push(['images','图片']);
    function filter(value){state.filter=value;for(const section of sections)section.hidden=value!=='all'&&section.dataset.kind!==value;for(const b of bar.querySelectorAll('button'))b.setAttribute('aria-pressed',String(b.dataset.uw==='results-'+value));}
    for(const [value,label]of filters)button(label,'results-'+value,()=>filter(value),bar);
    const jobs=Object.keys(providers).map(kind=>{
        const params=new URLSearchParams(kind==='prompts'?{view:scope.favorites?'favorites':'all',limit:12}:kind==='tags'?{limit:12}:{page_size:12});
        if(scope.query)params.set(kind==='prompts'||kind==='tags'?'q':'search',scope.query);
        if(scope.group)params.set(kind==='prompts'||kind==='tags'?'collection':'shared_collection',scope.group);
        if(scope.favorites&&kind!=='prompts')params.set(kind==='tags'?'favorite':'favorites_only','true');
        const path=kind==='prompts'?'/prompt_selector/library/prompts':kind==='tags'?'/prompt_selector/tags/page':'/api/lm/'+kind+'/list';
        const section=element('section',null,host,{className:'uw-result-section'});section.dataset.kind=['prompts','tags'].includes(kind)?'text':'models';sections.push(section);
        const title=element('h3',providers[kind],section),list=element('div',null,section);element('p','正在读取…',list);
        let loading=false,retryButton=null;
        async function load(){
            if(loading||controller.signal.aborted)return;
            loading=true;retryButton?.setAttribute('aria-disabled','true');list.setAttribute('aria-busy','true');
            try{
                const response=await fetch(path+'?'+params,{cache:'no-store',signal:controller.signal}),data=await response.json();
                if(!response.ok)throw new Error(data.error||'来源暂时不可用');if(controller.signal.aborted)return;
                const focused=list.contains(document.activeElement);
                list.replaceChildren();const items=data.items||[];title.textContent=providers[kind]+' · '+(data.total??items.length);
                if(!items.length)element('p','暂无符合条件的内容',list);
                for(const item of items){
                    const row=element('div',null,list,{className:'uw-resource-row'});
                    const entry=button(item.alias||item.text||item.model_name||item.file_name||item.id,'result-'+kind,()=>open(kind,item,scope),row);entry.dataset.resourceKey=JSON.stringify([kind,item.resource_id||item.id||item.file_path]);
                    if(item.favorite)element('small','已收藏',row);
                    if(scope.query&&item.match_reason)element('small',item.match_reason,row);
                }
                button('查看全部 '+providers[kind],'results-more-'+kind,()=>more(kind,scope),list);
                if(focused)list.querySelector('button')?.focus();
            }catch(error){
                if(controller.signal.aborted)return;
                const focused=list.contains(document.activeElement);
                title.textContent=providers[kind]+' · 暂不可读';list.replaceChildren();element('p','来源暂不可用，请检查服务连接后重试；这不表示资料为空。',list);const details=element('details',null,list);element('summary','错误详情',details);element('p',error.message,details);retryButton=button('重试此来源','results-retry',load,list);
                if(focused)retryButton.focus();
            }finally{loading=false;retryButton?.removeAttribute('aria-disabled');list.removeAttribute('aria-busy');}
        }
        return load();
    });
    filter(filters.some(([value])=>value===state.filter)?state.filter:'all');
    return {ready:Promise.all(jobs),dispose:()=>controller.abort()};
}
