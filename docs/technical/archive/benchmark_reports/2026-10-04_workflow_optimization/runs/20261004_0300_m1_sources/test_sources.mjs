import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import {JSDOM} from 'file:///G:/ComfyUI-aki-v3/benchmark_reports/2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';
const root='G:/ComfyUI-aki-v3/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench';
const checks=[];
const kinds=['character','clothing','pose','background','artist','style_quality'];
async function fixture(){
    const dom=new JSDOM('<div id="unified-workbench"><div id="host"></div><div id="selector"></div></div><textarea id="target">base</textarea>',{url:'http://localhost/',runScripts:'outside-only'});
    const d=dom.window.document,context=dom.getInternalVMContext(),cache=new Map();
    async function load(file){file=path.normalize(file);if(cache.has(file))return cache.get(file);const m=new vm.SourceTextModule(fs.readFileSync(file,'utf8'),{context,identifier:file});cache.set(file,m);return m;}
    function resolve(spec,parent){if(spec.startsWith('/extensions/ComfyUI-Unified-Prompt-Workbench/'))return root+'/web/'+spec.split('/').at(-1);return path.resolve(path.dirname(parent.identifier),spec);}
    async function entry(file){const m=await load(file);await m.link((spec,parent)=>load(resolve(spec,parent)));await m.evaluate();return m.namespace;}
    const pendingModule=await entry(root+'/web/pending_prompts.js');
    const ui=await entry(root+'/modules/comfyui-anima-tools/js/anima_selector_ui.js');
    const create=cache.get(path.normalize(root+'/web/prompt_target.js')).namespace.createTextInserter;
    const target=d.querySelector('#target'),host=d.querySelector('#host'),reports=[],requests=[],sources={},library={};
    let writer,direction='positive',fail=false;
    const make=(kind,id=kind)=>({id,name:id,name_zh:id,shared:true,tags:kind+' tag, ',_semantic:{binding:id+'-v1',disposition:'reviewed',manual_search_eligible:true,usage:'positive',content_type:'fragment'}});
    for(const kind of kinds)sources[kind]=[make(kind)];
    const response=data=>({ok:!fail,status:fail?503:200,headers:{get:()=> 'm1-fixture'},json:async()=>data});
    dom.window.fetch=async(url,options={})=>{const u=new URL(url,'http://localhost');requests.push({url:u.href,method:options.method||'GET',body:options.body});
        if(u.pathname==='/anima-tools/shared-prompts')return response({items:sources[u.searchParams.get('kind')]});
        if(u.pathname==='/anima-tools/artist-page')return response({success:!fail,lookup:sources.artist});
        if(u.pathname==='/prompt_selector/library/prompt')return response({prompt:library[u.searchParams.get('prompt_id')]});
        if(u.pathname==='/prompt_selector/library/index')return response({revision:'m1-fixture'});
        if(u.pathname==='/prompt_selector/prompts/mark_used')return response({revision:'m1-fixture'});
        if(u.pathname==='/prompt_selector/tags/item')return response({item:{text:'neutral tag'}});
        throw Error('Unexpected route '+u.pathname);
    };
    const element=(tag,text,parent,props={})=>{const el=Object.assign(d.createElement(tag),props);if(text!=null)el.textContent=text;parent?.append(el);return el;};
    const button=(label,key,callback,parent)=>{const el=element('button',label,parent);el.dataset.uw=key;el.onclick=callback;return el;};
    const pending=pendingModule.createPendingPrompts({element,button,onCount(){},report:m=>reports.push(m),insertionOptions:()=>{
        writer?.dispose();writer=create({key:target,inputElement:target,commaSeparated:true,read:()=>target.value,write:value=>target.value=value});
        return {onInsert:writer,targetDirection:direction,targetLabel:'test'};
    }});
    const settle=()=>new Promise(r=>setTimeout(r,0));
    const action=label=>[...host.querySelectorAll('button')].find(b=>b.textContent===label);
    const change=(el,value)=>{el.value=value;el.dispatchEvent(new dom.window.Event('change'));};
    const render=async()=>{pending.render(host);await settle();};
    const resource=kind=>{const item=sources[kind][0];return {provider:'anima',id:`${kind}:${item.id}`,kind,sourceId:item.id,sourceBinding:item._semantic.binding,text:item.tags,usage:'positive'};};
    return {dom,d,host,target,reports,requests,sources,library,make,pending,resource,change,render,action,settle,
        async apply(){await action('应用到目标').onclick();await settle();},
        async scope(value){change(host.querySelector('[aria-label="待用列表方向"]'),value);await settle();},
        async direction(value){direction=value;pending.refreshTarget();await settle();},
        preview(){return host.querySelectorAll('.uw-pending-preview')[1]?.textContent;},
        fail(){fail=true;},
        async ingress(kind,items){const graph={id:'fixture',getNodeById:()=>node},widget={name:'text',value:'base'},node={id:1,widgets:[widget],graph};const app={graph};
            dom.window.unifiedQueuePrompts=async resources=>pending.addMany(resources);
            const controls=ui.mountSelectorInsertionActions(d.querySelector('#selector'),{app,node,widget,kind,getSelectedItems:()=>items,resolveText:async()=>items.map(i=>i.tags).join(', ')});
            await controls.queue.onclick();controls.dispose();return d.querySelector('.anima-selector-insertion-status').textContent;
        },async replaceFromSelector(kind){
            const graph={id:'fixture',getNodeById:()=>node},widget={name:'text',value:'base'},node={id:1,widgets:[widget],graph};const app={graph};let text='first fragment';
            const controls=ui.mountSelectorInsertionActions(d.querySelector('#selector'),{app,node,widget,kind,getSelectedItems:()=>[],resolveText:async()=>text});
            await controls.apply.onclick();assert.equal(widget.value,'base, first fragment');text='second fragment';
            change(controls.picker,'replace_fragment');await controls.apply.onclick();assert.equal(widget.value,'base, first fragment');
            await controls.apply.onclick();assert.equal(widget.value,'base, second fragment');controls.undo.click();assert.equal(widget.value,'base, first fragment');controls.dispose();
        },close(){writer?.dispose();dom.window.close();}};
}
async function test(name,run){const f=await fixture();try{await run(f);checks.push({name,passed:true});}catch(error){checks.push({name,passed:false,error:error.message});}finally{f.close();}}
for(const kind of ['character','clothing','pose'])await test(kind+' current selector replacement bridge previews confirms and undoes',async f=>f.replaceFromSelector(kind));
for(const kind of kinds)await test(kind+' selector ingress preserves identity and duplicate guard',async f=>{
    await f.ingress(kind,f.sources[kind]);assert.equal(f.pending.items.length,1);assert.equal(f.pending.items[0].sourceId,kind);assert.equal(f.pending.items[0].usage,'positive');
    assert.equal(f.pending.addMany([f.resource(kind)]).duplicate,1);await f.render();await f.apply();assert.equal(f.target.value,'base, '+kind+' tag');
    if(kind==='artist'){const req=f.requests.find(r=>r.method==='POST');assert.deepEqual(JSON.parse(req.body).lookup_keys,['shared:artist']);}
});
await test('source with no stable binding cannot enter pending list',async f=>{const bad={...f.sources.pose[0],_semantic:{}};await f.ingress('pose',[bad]);assert.equal(f.pending.items.length,0);});
await test('six kinds compose once in order; artist lookup separate',async f=>{f.pending.addMany(kinds.map(k=>f.resource(k)));await f.render();await f.apply();assert.equal(f.target.value,'base, '+kinds.map(k=>k+' tag').join(', '));assert.equal(f.requests.length,6);});
await test('positive-only selector content cannot be written to negative target',async f=>{f.pending.addMany([f.resource('pose')]);await f.render();await f.direction('negative');await f.apply();assert.equal(f.target.value,'base');assert.match(f.reports.at(-1),/正负向与目标不同/);});
await test('revised binding forces review; retry uses refreshed binding',async f=>{f.pending.addMany([f.resource('pose')]);await f.render();f.sources.pose[0]._semantic.binding='pose-v2';await f.apply();assert.equal(f.target.value,'base');assert.match(f.reports.at(-1),/原资料已更新/);await f.apply();assert.equal(f.target.value,'base, pose tag');});
for(const invalid of ['missing','quarantined','ineligible','negative','no_binding'])await test('unavailable source '+invalid+' blocks write and retains draft',async f=>{
    f.pending.addMany([f.resource('pose')]);await f.render();const s=f.sources.pose[0]._semantic;
    if(invalid==='missing')f.sources.pose=[];else if(invalid==='quarantined')s.disposition='quarantined';else if(invalid==='ineligible')s.manual_search_eligible=false;else if(invalid==='negative')s.usage='negative';else s.binding='';
    await f.apply();assert.equal(f.target.value,'base');assert.equal(f.pending.items.length,1);assert.match(f.reports.at(-1),/已不可用/);
});
await test('network failure blocks write and retains draft',async f=>{f.pending.addMany([f.resource('pose')]);await f.render();f.fail();await f.apply();assert.equal(f.target.value,'base');assert.equal(f.pending.items.length,1);});
await test('mixed prompt requires completed split and applies each direction separately',async f=>{
    f.library.mix={prompt:'adult traveler, blur',_semantic:{manual_search_eligible:true,usage:'mixed'}};
    f.pending.add({provider:'library',id:'mix',title:'mixed',text:f.library.mix.prompt,usage:'mixed'});await f.render();await f.apply();assert.equal(f.target.value,'base');
    f.action('拆分正负向').click();await f.apply();assert.match(f.reports.at(-1),/保留或取消/);
    const inputs=f.host.querySelectorAll('.uw-split-editor textarea');inputs[0].value='adult traveler';inputs[1].value='blur';f.action('保留拆分结果').click();await f.settle();
    await f.scope('positive');assert.equal(f.preview(),'base, adult traveler');await f.apply();assert.equal(f.target.value,'base, adult traveler');f.action('撤销本次写入').click();await f.settle();assert.equal(f.target.value,'base');
    await f.scope('negative');await f.direction('negative');await f.apply();assert.equal(f.target.value,'base, blur');assert.equal(f.pending.items.length,2);
});
await test('cancel unfinished split retains original and continues blocking mixed direction',async f=>{
    f.library.mix={prompt:'adult traveler, blur',_semantic:{manual_search_eligible:true,usage:'mixed'}};
    f.pending.add({provider:'library',id:'mix',text:f.library.mix.prompt,usage:'mixed'});await f.render();f.action('拆分正负向').click();f.action('取消拆分').click();await f.apply();assert.equal(f.target.value,'base');assert.match(f.reports.at(-1),/正负向与目标不同/);assert(!f.pending.items[0].splitDraft);
});
await test('split and local edits survive upstream text update but require review',async f=>{
    f.library.mix={prompt:'old mixed',_semantic:{manual_search_eligible:true,usage:'mixed'}};
    f.pending.add({provider:'library',id:'mix',text:'old mixed',usage:'mixed'});await f.render();f.action('拆分正负向').click();f.host.querySelector('.uw-split-editor textarea').value='(adult traveler:1.2)';f.action('保留拆分结果').click();await f.settle();
    f.library.mix.prompt='new mixed';await f.apply();assert.equal(f.target.value,'base');assert.equal(f.pending.items[0].text,'(adult traveler:1.2)');assert.match(f.reports.at(-1),/原资料已更新/);await f.apply();assert.equal(f.target.value,'base, (adult traveler:1.2)');
});
await test('structured plan keeps both sections and fails closed when section disappears',async f=>{
    const sections={positive:'adult traveler',negative:'blur'};f.library.plan={prompt:'plan',plan_sections:sections,_semantic:{manual_search_eligible:true,usage:'mixed'}};
    f.pending.add({provider:'library',id:'plan',title:'plan',sections});await f.render();assert.equal(f.pending.items.length,2);await f.scope('negative');await f.direction('negative');delete sections.negative;await f.apply();assert.equal(f.target.value,'base');assert.match(f.reports.at(-1),/分段已变化/);
});
await test('disabled item is not read; target-neutral tags follow selected direction',async f=>{
    f.pending.addMany([f.resource('pose')]);f.pending.add({provider:'tag',id:'tag',text:'neutral tag'});await f.render();const enabled=f.host.querySelector('input[type=checkbox]');enabled.checked=false;enabled.dispatchEvent(new f.dom.window.Event('change'));await f.scope('negative');await f.direction('negative');await f.apply();assert.equal(f.target.value,'base, neutral tag');assert(!f.requests.some(r=>r.url.includes('shared-prompts')));
});
const result={passed:checks.every(c=>c.passed),checks};fs.writeFileSync(new URL('source_tests.json',import.meta.url),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));if(!result.passed)process.exitCode=1;
