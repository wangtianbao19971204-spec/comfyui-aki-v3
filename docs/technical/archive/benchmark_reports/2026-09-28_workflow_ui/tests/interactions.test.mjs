import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {JSDOM, VirtualConsole} from '../../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const root=path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench');
const checks=[];
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
function setup(){
    const errors=[],console=new VirtualConsole();console.on('jsdomError',error=>errors.push(error.message));
    const dom=new JSDOM('<button id="opener">打开</button><main></main>',{url:'http://localhost/',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console});
    const w=dom.window,d=w.document,context=dom.getInternalVMContext(),modules=new Map();
    w.HTMLElement.prototype.getClientRects=function(){return this.isConnected&&!this.closest('[hidden]')?[{}]:[];};
    w.structuredClone=structuredClone;
    async function load(relative){
        const file=path.resolve(root,relative);if(modules.has(file))return modules.get(file);
        const m=file.endsWith('run_controls.js')?new vm.SyntheticModule(['mountRunControls'],function(){this.setExport('mountRunControls',()=>({dispose(){}}));},{context}):new vm.SourceTextModule(fs.readFileSync(file,'utf8'),{context,identifier:file});
        modules.set(file,m);
        if(m instanceof vm.SourceTextModule)await m.link(spec=>load(path.resolve(path.dirname(file),spec)));
        return m;
    }
    return {dom,w,d,load,errors};
}
{
    const {dom,w,d,load,errors}=setup();let offline=false,indexOffline=true,copied='',writes=0;
    Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>{copied=text;}}});
    const requests=[];
    w.fetch=async(url,options={})=>{
        assert(!options.method||options.method==='GET','browse tests must not write');
        if(options.method==='POST')writes++;
        const u=new URL(url,'http://localhost');let data;
        if(u.pathname.endsWith('/index')){if(indexOffline)throw Error('index offline');data={groups:[],collections:[],revision:'v1'};}
        else if(u.pathname.endsWith('/page')){
            requests.push(Object.fromEntries(u.searchParams));if(offline)throw Error('offline');
            const offset=Number(u.searchParams.get('offset')),limit=Number(u.searchParams.get('limit'));
            const all=Array.from({length:270},(_,i)=>({resource_id:'tag:'+i,text:'tag_'+i,desc:'标签 '+i}));
            const items=u.searchParams.get('q')==='missing'?[]:all.slice(offset,offset+limit);
            data={items,total:u.searchParams.get('q')==='missing'?0:270,revision:'v1'};
        }else throw Error('Unexpected URL '+url);
        return {ok:true,json:async()=>structuredClone(data)};
    };
    const module=await load('web/tag_manager.js');await module.evaluate();
    await module.namespace.openTagManager({mount:d.querySelector('main')});
    const button=text=>[...d.querySelectorAll('button')].find(item=>item.textContent===text);
    const ids=()=>[...d.querySelectorAll('[data-resource-id]')].map(item=>item.dataset.resourceId);
    assert.equal(button('重新加载').hidden,false);assert.equal(button('下一页').disabled,true);
    indexOffline=false;await button('重新加载').onclick();assert.equal(button('重新加载').hidden,true);
    checks.push('first-load catalog failure offers a retry that reloads both categories and results');
    const first=ids();assert.equal(first.length,120);
    button('下一页').click();await tick();assert.equal(requests.at(-1).offset,'120');assert.equal(ids()[0],'tag:120');assert(!ids().some(id=>first.includes(id)));
    button('上一页').click();await tick();assert.deepEqual(ids(),first);
    checks.push('Tag card pagination uses 120 consistently without overlap');
    const check=d.querySelector('.ut-card input');check.checked=true;check.dispatchEvent(new w.Event('change',{bubbles:true}));
    button('切换为列表').click();await tick();assert.equal(requests.at(-1).limit,'100');assert.equal(d.querySelector('.ut-row input').checked,true);
    button('下一页').click();await tick();assert.equal(ids()[0],'tag:100');
    checks.push('list mode uses 100 per page and switching view preserves selected tags');
    const before=ids();offline=true;button('下一页').click();await tick();assert.deepEqual(ids(),before);assert.equal(d.querySelector('.ut-list').getAttribute('aria-busy'),'false');assert.equal(button('重新加载').hidden,false);
    offline=false;button('重新加载').click();await tick();assert.equal(ids()[0],'tag:200');assert.equal(button('重新加载').hidden,true);
    checks.push('failed page request keeps results and retry loads the intended page');
    button('复制').click();await tick();assert.equal(copied,'tag_200');assert.equal(writes,0);
    checks.push('copy uses exact original Tag text and does not write the library');
    const search=d.querySelector('.ut-search');search.value='missing';search.dispatchEvent(new w.Event('input',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,280));
    assert(d.querySelector('.uw-empty-state'));d.querySelector('.uw-empty-state button').click();await tick();assert.equal(search.value,'');assert.equal(ids().length,100);
    search.value='missing';search.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await tick();assert.equal(search.value,'');assert(d.querySelector('#unified-tag-manager'));
    checks.push('empty results offer a working reset; Escape clears search without closing');
    module.namespace.closeTagManager();assert.deepEqual(errors,[]);dom.window.close();
}
{
    const {dom,w,d,load,errors}=setup();
    await load('web/modal_focus.js');await load('web/prompt_target.js');
    const module=await load('web/workspace.js');await module.evaluate();
    const widget={name:'steps',value:20,options:{min:1,max:100,step:10}},node={id:1,mode:0,type:'Sampler',widgets:[widget]};
    const app={graph:{_nodes:[node],getNodeById:()=>node,beforeChange(){},afterChange(){},setDirtyCanvas(){}}};let reports=[];
    const element=(tag,text,parent,props={})=>{const el=Object.assign(d.createElement(tag),props);if(text!=null)el.textContent=text;parent?.append(el);return el;};
    const button=(text,key,callback,parent)=>{const el=element('button',text,parent);el.onclick=callback;return el;};
    const workspace=module.namespace.mountWorkspace(d.querySelector('main'),{app,element,button,report:message=>reports.push(message),selectTarget(){},close(){},browse(){},models(){},savePlan(){}});
    const input=d.querySelector('input[type=number]');
    for(const invalid of ['','0','101','2.5']){input.value=invalid;input.onchange();assert.equal(widget.value,20);assert.equal(input.getAttribute('aria-invalid'),'true');}
    input.value='21';input.onchange();assert.equal(widget.value,21);assert.equal(input.hasAttribute('aria-invalid'),false);
    checks.push('blank, out-of-range and fractional integer parameters cannot overwrite valid values');
    workspace.dispose();assert.deepEqual(errors,[]);dom.window.close();
}
{
    const {dom,w,d,load,errors}=setup();const module=await load('modules/comfyui-anima-tools/js/anima_selector_ui.js');await module.evaluate();
    let close=0,selected=0;
    const overlay=d.createElement('div');overlay.innerHTML='<div><input type="search" placeholder="搜索角色"><div tabindex="0" class="anima-shared-resource-card"><button>编辑</button></div><button>关闭</button></div>';d.body.append(overlay);overlay.unifiedClose=()=>close++;
    const card=overlay.querySelector('.anima-shared-resource-card'),search=overlay.querySelector('input');card.onclick=()=>selected++;
    card.querySelector('button').onclick=event=>event.stopPropagation();
    const release=module.namespace.installSelectorExperience(overlay,'character');
    const key=(target,key,extra={})=>target.dispatchEvent(new w.KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,...extra}));
    key(card,'Enter');key(card,' ');assert.equal(selected,2);key(card.querySelector('button'),'Enter');assert.equal(selected,2);
    key(card,'Enter',{isComposing:true});assert.equal(selected,2);
    search.value='query';key(search,'Escape');assert.equal(search.value,'');assert.equal(close,0);
    key(card,'f',{ctrlKey:true});assert.equal(d.activeElement,search);key(search,'Escape');assert.equal(close,1);
    assert.equal(overlay.getAttribute('role'),'dialog');release();
    checks.push('selector cards support Enter and Space without selecting through nested editor controls or IME');
    checks.push('character and artist dialogs gain search shortcuts and Escape priority');
    const dialog=d.createElement('div');d.body.append(dialog);let attempts=0;
    const buttons=module.namespace.createModalButtons({dialog,cancelText:'取消',confirmText:'保存',buttonClass:'test',onConfirm:async()=>{attempts++;if(attempts===1)throw Error('保存失败');return true;}});dialog.append(buttons);
    await buttons.lastChild.onclick();assert(dialog.isConnected);assert.equal(buttons.firstChild.disabled,false);assert.equal(buttons.lastChild.disabled,false);assert(dialog.querySelector('[role=alert]'));
    await buttons.lastChild.onclick();assert(!dialog.isConnected);assert.equal(attempts,2);
    checks.push('failed selector saves show an error, re-enable both buttons and can be retried');
    assert.deepEqual(errors,[]);dom.window.close();
}
fs.writeFileSync('benchmark_reports/2026-09-28_workflow_ui/evidence/interactions.json',JSON.stringify({passed:true,checks},null,2));
console.log(JSON.stringify({passed:true,checks},null,2));
