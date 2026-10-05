import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {JSDOM} from '../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const root=path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web');
const dom=new JSDOM('<main></main>',{url:'http://127.0.0.1:8188/',runScripts:'dangerously'});
const win=dom.window,doc=win.document,context=dom.getInternalVMContext(),modules=new Map();
async function load(file){
    if(modules.has(file))return modules.get(file);
    const module=new vm.SourceTextModule(fs.readFileSync(file,'utf8'),{context,identifier:file});
    modules.set(file,module);
    await module.link(spec=>load(path.resolve(path.dirname(file),spec)));
    return module;
}
const targetModule=await load(path.join(root,'prompt_target.js'));
const pendingModule=await load(path.join(root,'pending_prompts.js'));
await pendingModule.evaluate();

const element=(tag,text,parent,props={})=>{
    const node=Object.assign(doc.createElement(tag),props);
    if(text!=null)node.textContent=text;
    parent?.append(node);
    return node;
};
const button=(label,key,callback,parent)=>{
    const node=element('button',label,parent);
    node.dataset.uw=key;node.onclick=callback;
    return node;
};
let target='blue sky,\nsoft light';
const messages=[],sourceVisits=[];
win.fetch=async url=>({ok:true,json:async()=>({item:{text:String(url).includes('tag:b')?'standing':String(url).includes('tag:c')?'soft light':'red coat'}})});
const writer=targetModule.namespace.createTextInserter({read:()=>target,write:value=>{target=value;},validate:()=>true,commaSeparated:true});
const draft=[
    {provider:'tag',id:'tag:b',title:'B',text:'standing',usage:'target',weight:1,modified:true},
    {provider:'tag',id:'tag:a',title:'A',text:'red coat',usage:'target',weight:1.5,modified:true},
    {provider:'tag',id:'tag:c',title:'C',text:'soft light',usage:'target',weight:1,modified:true},
];
const basket=pendingModule.namespace.createPendingPrompts({element,button,draft,onCount(){},report:message=>messages.push(message),
    insertionOptions:()=>({onInsert:writer,targetLabel:'test #1',targetDirection:'positive'}),openSource:item=>sourceVisits.push(item.id)});
basket.render(doc.querySelector('main'));
const rows=[...doc.querySelectorAll('.uw-pending-item')];
assert.equal(rows.length,3);
rows[2].querySelector('input[type=checkbox]').checked=false;
rows[2].querySelector('input[type=checkbox]').onchange();
await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(basket.compose(),'standing, (red coat:1.5)');
assert.equal(doc.querySelectorAll('.uw-pending-preview')[1].textContent,'blue sky,\nsoft light, standing, (red coat:1.5)');
assert.equal(basket.items[2].enabled,false);
assert.equal(target,'blue sky,\nsoft light');
rows[0].querySelector('[data-uw=pending-source]').onclick();
assert.deepEqual(sourceVisits,['tag:b']);

target='manual change';
await doc.querySelector('.uw-use-actions button').onclick();
assert.equal(target,'manual change');
assert(messages.some(value=>value.includes('目标正文在预览后发生变化')));

const restoredDraft=basket.items;
assert.equal(restoredDraft[2].enabled,false);
win.sessionStorage.removeItem('uw-pending-draft');
let sharedReads=0;
win.fetch=async url=>{
    assert(String(url).startsWith('/anima-tools/shared-prompts?'));
    sharedReads++;
    return {ok:true,json:async()=>({items:[
        {id:'a',shared:true,tags:'fresh a,',_semantic:{binding:'v2',disposition:'reviewed',manual_search_eligible:true,usage:'positive',content_type:'fragment'}},
        {id:'b',shared:true,tags:'fresh b,',_semantic:{binding:'v2',disposition:'reviewed',manual_search_eligible:true,usage:'positive',content_type:'fragment'}},
    ]})};
};
const selectorDraft=[];
const selectorBasket=pendingModule.namespace.createPendingPrompts({element,button,draft:selectorDraft,onCount(){},report:message=>messages.push(message),insertionOptions:()=>({onInsert:writer,targetLabel:'test #1',targetDirection:'positive'})});
const resources=[
    {provider:'anima',kind:'character',sourceId:'a',id:'character:a',sourceBinding:'v1',title:'A',text:'old a,',usage:'positive'},
    {provider:'anima',kind:'character',sourceId:'b',id:'character:b',sourceBinding:'v1',title:'B',text:'old b,',usage:'positive'},
];
assert.equal(JSON.stringify(selectorBasket.addMany(resources)),JSON.stringify({added:2,duplicate:0}));
assert.equal(JSON.stringify(selectorBasket.addMany([resources[0]])),JSON.stringify({added:0,duplicate:1}));
assert.equal(selectorBasket.compose(),'old a, old b');
assert.equal(target,'manual change');
await assert.rejects(()=>selectorBasket.prepare('positive'),/原资料已更新/);
assert.equal(sharedReads,1);
assert.equal(selectorBasket.compose(),'fresh a, fresh b');
assert.equal(await selectorBasket.prepare('positive'),'fresh a, fresh b');
assert.equal(sharedReads,2);
assert.equal(target,'manual change');
win.sessionStorage.removeItem('uw-pending-draft');
let artistReads=0;
win.fetch=async (url,options)=>{
    assert.equal(url,'/anima-tools/artist-page');
    const query=JSON.parse(options.body);
    assert.deepEqual(query.selected_keys,['shared:artist-1']);
    assert.deepEqual(query.lookup_keys,['shared:artist-1']);
    assert.equal(query.limit,0);
    artistReads++;
    return {ok:true,json:async()=>({success:true,lookup:[{id:'artist-1',shared:true,tags:'artist prompt,',_semantic:{binding:'v1',disposition:'reviewed',manual_search_eligible:true,usage:'positive',content_type:'fragment'}}]})};
};
const artistBasket=pendingModule.namespace.createPendingPrompts({element,button,draft:[],onCount(){},report:message=>messages.push(message),insertionOptions:()=>({onInsert:writer,targetLabel:'test #1',targetDirection:'positive'})});
artistBasket.addMany([{provider:'anima',kind:'artist',sourceId:'artist-1',id:'artist:artist-1',sourceBinding:'v1',title:'Artist',text:'artist prompt,',usage:'positive'}]);
assert.equal(await artistBasket.prepare('positive'),'artist prompt');
assert.equal(artistReads,1);
assert.equal(target,'manual change');

win.sessionStorage.removeItem('uw-pending-draft');
win.fetch=async()=>({ok:true,json:async()=>({item:{text:'red coat'}})});
const weightBasket=pendingModule.namespace.createPendingPrompts({element,button,
    draft:[{provider:'tag',id:'weight-case',title:'Weight case',text:'red coat',usage:'target',weight:1,enabled:true,modified:true}],
    onCount(){},report:message=>messages.push(message),
    insertionOptions:()=>({onInsert:writer,targetLabel:'test #1',targetDirection:'positive'})});
weightBasket.render(doc.querySelector('main'));
const weightField=doc.querySelector('[aria-label="本次权重"]');
const fullWeightPreview=doc.querySelectorAll('.uw-pending-preview')[1];
for(const [input,weight,body,field] of [
    ['0',0,'(red coat:0)','manual change, (red coat:0)'],
    ['1',1,'red coat','manual change, red coat'],
    ['1.5',1.5,'(red coat:1.5)','manual change, (red coat:1.5)'],
    ['3',3,'(red coat:3)','manual change, (red coat:3)'],
]){
    weightField.value=input;weightField.dispatchEvent(new win.Event('change'));
    await new Promise(resolve=>setTimeout(resolve,5));
    assert.equal(weightBasket.items[0].weight,weight,input);
    assert.equal(weightBasket.compose(),body,input);
    assert.equal(fullWeightPreview.textContent,field,input);
    assert.equal(target,'manual change');
}
for(const input of ['-1','3.1','','Infinity','-Infinity','NaN','1e309']){
    const beforeMessages=messages.length;
    weightField.value=input;weightField.dispatchEvent(new win.Event('change'));
    assert.equal(weightField.value,'3',input);
    assert.equal(weightBasket.items[0].weight,3,input);
    assert.equal(weightBasket.compose(),'(red coat:3)',input);
    assert.equal(fullWeightPreview.textContent,'manual change, (red coat:3)',input);
    assert.equal(JSON.parse(win.sessionStorage.getItem('uw-pending-draft'))[0].weight,3,input);
    assert.equal(messages.length,beforeMessages+1,input);
    assert.match(messages.at(-1),/原权重已保留/,input);
    assert.equal(target,'manual change');
}
weightField.value='0';weightField.dispatchEvent(new win.Event('change'));
const enabledField=doc.querySelector('.uw-pending-item input[type=checkbox]');
enabledField.checked=false;enabledField.dispatchEvent(new win.Event('change'));
assert.equal(weightBasket.compose(),'');
assert.equal(weightBasket.items[0].weight,0);
assert.equal(weightBasket.items[0].enabled,false);
assert.equal(fullWeightPreview.textContent,'本次没有已启用的待用内容。');
enabledField.checked=true;enabledField.dispatchEvent(new win.Event('change'));
await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(weightBasket.compose(),'(red coat:0)');
assert.equal(fullWeightPreview.textContent,'manual change, (red coat:0)');
await [...doc.querySelectorAll('.uw-use-actions button')].find(node=>node.textContent==='应用到目标').onclick();
assert.equal(target,'manual change, (red coat:0)');
[...doc.querySelectorAll('.uw-use-actions button')].find(node=>node.textContent==='撤销本次写入').onclick();
assert.equal(target,'manual change');
writer.dispose();dom.window.close();
console.log(JSON.stringify({pass:true,checks:['paused item stays in draft and leaves composition','full field preview follows existing comma and weight rules','source navigation retains identity','manual target edit prevents stale append','selector batch deduplicates stable IDs and refreshes each kind once before applying','changed source requires another explicit apply','artist preparation uses one-ID paged lookup instead of the full catalog','weights 0, 1, 1.5 and 3 have exact composition and complete field previews','out-of-range, blank and non-finite weight inputs retain the previous value and draft','zero weight remains enabled and written while a paused item is excluded; undo restores the target','no production target changed']},null,2));
