const ENDPOINT = '/prompt_selector/collections/references';
const el = (tag,text,parent) => {const node=document.createElement(tag);if(text!=null)node.textContent=text;parent?.append(node);return node;};
export async function getReferenceCollections(reference = {}) {
    const params = new URLSearchParams(Object.entries(reference).filter(([,value])=>value!=null));
    const response = await fetch(ENDPOINT+'?'+params,{cache:'no-store'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '读取共享分组失败');
    return result;
}

export async function installModelCollectionFilter() {
    if(window.frameElement?.closest('#unified-workbench'))return;
    if(document.getElementById('uw-model-group-filter'))return;
    const grid=document.getElementById('modelGrid');if(!grid)return;
    const bar=el('div',null);bar.id='uw-model-group-filter';bar.style.cssText='display:flex;gap:8px;align-items:center;padding:8px;flex-wrap:wrap';
    grid.parentElement.insertBefore(bar,grid);
    try{
        const response=await fetch('/prompt_selector/collections/index',{cache:'no-store'});if(!response.ok){bar.remove();return;}
        const data=await response.json();el('span','共享分组',bar);
        const picker=el('select',null,bar);picker.setAttribute('aria-label','模型共享分组');
        const all=el('option','全部组',picker);all.value='';
        for(const group of data.groups){const option=el('option',group.name,picker);option.value=group.id;}
        picker.value=new URLSearchParams(window.location.search).get('uw_group') || '';
        picker.onchange=()=>{const url=new URL(window.location.href);if(picker.value)url.searchParams.set('uw_group',picker.value);else url.searchParams.delete('uw_group');window.location.assign(url.href);};
    }catch(error){bar.textContent='共享分组暂不可读：'+error.message;}
}

export async function openReferenceCollections(reference, options = {}) {
    if (document.getElementById('uw-reference-groups')) throw new Error('请先保存或关闭当前分组编辑窗口。');
    const previousFocus = document.activeElement;
    let data=null,selected=new Set(),saving=false,reading=false,managing=false,closed=false;
    const root=el('section',null,document.body);root.id='uw-reference-groups';root.setAttribute('role','dialog');root.setAttribute('aria-label','共享资源分组');
    root.setAttribute('aria-modal','true');root.tabIndex=-1;
    root.style.cssText='position:fixed;inset:18% 22%;z-index:2147483000;background:#242a34;color:#eee;border:1px solid #8290a8;border-radius:12px;padding:22px;overflow:auto;font:14px system-ui;box-shadow:0 0 0 100vmax #0008';
    el('h2',options.title || '共享资源分组',root);
    el('p','这些组与资料库、Tag、模型和图库共用。清空分组不会删除资源或取消原收藏。',root);
    const list=el('div',null,root),status=el('p','',root);status.setAttribute('role','status');
    const actions=el('div',null,root);actions.style.cssText='display:flex;gap:10px;flex-wrap:wrap';
    const save=el('button','保存分组',actions),reload=el('button','重新读取版本',actions),manage=el('button','管理共用组',actions),cancel=el('button','关闭',actions);
    const render=()=>{
        list.replaceChildren();
        const groups=[...data.groups,...[...selected].filter(id=>!data.groups.some(group=>group.id===id)).map(id=>({id,name:'已删除的组（取消勾选后可保存）'}))];
        for(const group of groups){const label=el('label',null,list);label.style.cssText='display:block;padding:7px';const input=el('input',null,label);input.type='checkbox';input.checked=selected.has(group.id);input.dataset.groupId=group.id;input.onchange=()=>input.checked?selected.add(group.id):selected.delete(group.id);label.append(document.createTextNode(' '+group.name));}
    };
    const close=()=>{
        if(saving || closed)return;
        closed=true;root.remove();
        const target=previousFocus?.closest('details:not([open])')?.querySelector('summary') || previousFocus;
        if(target?.isConnected && !target.disabled && target.getClientRects().length && getComputedStyle(target).visibility!=='hidden')target.focus();
        options.onClose?.();
    };cancel.onclick=close;
    for(const type of ['copy','cut','paste'])root.addEventListener(type,event=>event.stopPropagation());
    root.addEventListener('keydown',event=>{
        event.stopPropagation();
        if(event.defaultPrevented || event.isComposing)return;
        if(event.key==='Tab'){
            const items=[...root.querySelectorAll('input,button')].filter(item=>!item.disabled && item.tabIndex>=0 && item.getClientRects().length);
            const first=items[0],last=items.at(-1);
            if(!first){event.preventDefault();root.focus();}
            else if(document.activeElement===root || event.shiftKey && document.activeElement===first || !event.shiftKey && document.activeElement===last){event.preventDefault();(event.shiftKey?last:first).focus();}
        }
        if(event.key==='Escape'){event.preventDefault();close();}
    });
    const readLatest=async()=>{
        if(reading||saving||closed)return;
        reading=true;
        const previous=document.activeElement;
        if(previous===save||previous===manage)root.focus();
        save.disabled=true;manage.disabled=true;reload.setAttribute('aria-disabled','true');status.textContent='正在读取共享分组…';
        try{
            const latest=await getReferenceCollections(reference);
            if(closed)return;
            const first=!data,focusedGroup=list.contains(document.activeElement)?document.activeElement.dataset.groupId:null;
            if(first)selected=new Set(latest.items[0]?.group_ids||[]);
            data=latest;render();
            status.textContent=first?'':'已读取最新版本，当前勾选保留；请核对后保存。';
            if(focusedGroup)([...list.querySelectorAll('input')].find(input=>input.dataset.groupId===focusedGroup)||reload).focus();
        }catch(error){if(!closed)status.textContent=error.message;}
        finally{
            reading=false;
            if(!closed){
                save.disabled=!data;manage.disabled=!data;reload.removeAttribute('aria-disabled');
                if(document.activeElement===root){
                    if((previous===save||previous===manage)&&!previous.disabled)previous.focus();
                    else (list.querySelector('input')||reload).focus();
                }
            }
        }
    };
    reload.onclick=readLatest;
    save.onclick=async()=>{
        if(saving||reading||closed||!data)return;saving=true;save.disabled=true;reload.disabled=true;manage.disabled=true;cancel.disabled=true;
        for(const input of list.querySelectorAll('input'))input.disabled=true;
        root.focus();
        try{
            const response=await fetch(ENDPOINT,{method:'POST',headers:{'Content-Type':'application/json','If-Match':data.revision},body:JSON.stringify({items:[{...reference,group_ids:[...selected]}]})});
            const result=await response.json();if(!response.ok)throw new Error(result.error || '分组已变化，请重新读取版本后核对。');
            window.dispatchEvent(new CustomEvent('unified-collections-updated',{detail:{revision:result.revision}}));saving=false;close();options.onSaved?.();
        }catch(error){status.textContent=error.message;}finally{
            saving=false;save.disabled=false;reload.disabled=false;manage.disabled=false;cancel.disabled=false;
            for(const input of list.querySelectorAll('input'))input.disabled=false;
            if(root.isConnected && document.activeElement===root)save.focus();
        }
    };
    manage.onclick=async()=>{
        if(saving||reading||managing||closed||!data)return;
        const owner=window.weilinOpenSharedPresets?window:window.parent;
        if(!owner?.weilinOpenSharedPresets){status.textContent='请从 ComfyUI 统一工作台管理共用组。';return;}
        managing=true;root.style.visibility='hidden';
        const restore=async()=>{
            if(closed)return;
            managing=false;
            root.style.visibility='';manage.focus();
            await readLatest();
        };
        try{await owner.weilinOpenSharedPresets({collectionsOnly:true,selectorKind:'resource',onClose:restore});}
        catch(error){managing=false;root.style.visibility='';status.textContent=error.message;if(!closed)manage.focus();}
    };
    root.focus();await readLatest();return {root,close};
}
