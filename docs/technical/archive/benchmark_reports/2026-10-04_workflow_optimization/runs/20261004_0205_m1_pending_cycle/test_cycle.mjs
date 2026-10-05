import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {JSDOM} from 'file:///G:/ComfyUI-aki-v3/benchmark_reports/2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';
const root='G:/ComfyUI-aki-v3/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/';
const source=process.argv[2]||root+'pending_prompts.js';
const out=process.argv[3]||new URL('tests.json',import.meta.url);
const checks=[];
async function fixture(){
    const dom=new JSDOM('<div id="unified-workbench"><div id="host"></div></div><textarea id="target">adult traveler</textarea><textarea id="other">blur</textarea>',{url:'http://localhost/',runScripts:'outside-only'});
    const d=dom.window.document,context=dom.getInternalVMContext(),cache=new Map();
    async function load(name){if(cache.has(name))return cache.get(name);const m=new vm.SourceTextModule(fs.readFileSync(name==='pending_prompts.js'?source:root+name,'utf8'),{context});cache.set(name,m);return m;}
    const module=await load('pending_prompts.js');await module.link(spec=>load(spec.replace('./','')));await module.evaluate();
    const create=cache.get('prompt_target.js').namespace.createTextInserter;
    const records={coat:'blue jacket',pose:'standing'}, reports=[];
    let gate=null,destination=d.querySelector('#target'),writer,direction='positive',valid=true,time=1000;
    dom.window.Date.now=()=>time;
    dom.window.fetch=async url=>{if(gate)await gate;return {ok:true,json:async()=>({item:{text:records[new URL(url,'http://localhost').searchParams.get('id')]}})};};
    const element=(tag,text,parent,props={})=>{const el=Object.assign(d.createElement(tag),props);if(text!=null)el.textContent=text;parent?.append(el);return el;};
    const button=(label,key,callback,parent)=>{const el=element('button',label,parent);el.dataset.uw=key;el.onclick=callback;return el;};
    const pending=module.namespace.createPendingPrompts({element,button,onCount(){},report:m=>reports.push(m),insertionOptions:()=>{
        writer?.dispose();const target=destination;
        writer=create({key:target,inputElement:target,commaSeparated:true,validate:()=>valid,read:()=>target.value,write:value=>{target.value=value;}});
        return {onInsert:writer,targetDirection:direction,targetLabel:target.id};
    }});
    const host=d.querySelector('#host'),settle=()=>new Promise(r=>setTimeout(r,0));
    const action=label=>[...host.querySelectorAll('button')].find(b=>b.textContent===label);
    const mode=()=>host.querySelector('[aria-label="提示词写入方式"]');
    const change=(el,value)=>{el.value=value;el.dispatchEvent(new dom.window.Event('change'));};
    const setMode=async value=>{change(mode(),value);await settle();};
    const add=id=>pending.add({provider:'tag',id,text:records[id],title:id});
    const preview=()=>host.querySelectorAll('.uw-pending-preview')[1]?.textContent;
    const apply=async()=>{await action('应用到目标').onclick();await settle();};
    const undo=async()=>{action('撤销本次写入').click();await settle();};
    add('coat');pending.render(host);await settle();
    return {dom,d,host,pending,records,reports,action,mode,setMode,add,preview,apply,undo,settle,change,
        get value(){return destination.value;},set value(v){destination.value=v;},tick(){time+=1000;},
        switchTarget(){destination=d.querySelector('#other');direction='negative';pending.refreshTarget();},
        block(){gate=new Promise(r=>{this.release=()=>{gate=null;r();};});},
        invalidate(){valid=false;},close(){writer.dispose();dom.window.close();}};
}
async function test(name,run){const f=await fixture();try{await run(f);checks.push({name,passed:true});}catch(error){checks.push({name,passed:false,error:error.message});}finally{f.close();}}

await test('append refreshes complete preview; deliberate second apply and undo',async f=>{
    assert.equal(f.preview(),'adult traveler, blue jacket');await f.apply();assert.equal(f.value,'adult traveler, blue jacket');
    assert.equal(f.preview(),'adult traveler, blue jacket, blue jacket');f.tick();await f.apply();assert.equal(f.value,'adult traveler, blue jacket, blue jacket');
    await f.undo();assert.equal(f.value,'adult traveler, blue jacket');assert.equal(f.preview(),'adult traveler, blue jacket, blue jacket');
});
await test('fast second click does not duplicate; undo then retry works',async f=>{
    await f.apply();await f.apply();assert.equal(f.value,'adult traveler, blue jacket');await f.undo();assert.equal(f.value,'adult traveler');
    assert.equal(f.preview(),'adult traveler, blue jacket');await f.apply();assert.equal(f.value,'adult traveler, blue jacket');
});
await test('external edit blocks write then refreshes preview for explicit retry',async f=>{
    f.value='quiet forest';await f.apply();assert.equal(f.value,'quiet forest');assert.match(f.reports.at(-1),/预览/);
    assert.equal(f.preview(),'quiet forest, blue jacket');await f.apply();assert.equal(f.value,'quiet forest, blue jacket');
});
await test('replacement preview cancel confirm and undo preserve exact syntax',async f=>{
    const text='(blue coat:1.2), character\\(adult\\)\n<lora:coat:0.8>, embedding:style';f.records.coat=text;
    f.pending.items;await f.setMode('replace_prompt');await f.action('预览替换').onclick();await f.settle();
    assert.equal(f.mode().value,'replace_prompt');assert.equal(f.value,'adult traveler');
    await f.action('预览替换').onclick();f.action('取消替换').click();assert.equal(f.value,'adult traveler');
    await f.action('预览替换').onclick();await f.action('确认替换').onclick();assert.equal(f.value,text);await f.undo();assert.equal(f.value,'adult traveler');
});
await test('changed source refreshes before write and keeps insertion mode',async f=>{
    await f.setMode('replace_prompt');f.records.coat='green jacket';await f.action('预览替换').onclick();await f.settle();
    assert.equal(f.value,'adult traveler');assert.equal(f.mode().value,'replace_prompt');assert.equal(f.preview(),'green jacket');assert.match(f.reports.at(-1),/原资料已更新/);
});
await test('switch target during source read writes to neither target',async f=>{
    f.block();const operation=f.action('应用到目标').onclick();f.switchTarget();await f.settle();f.release();await operation;await f.settle();
    assert.equal(f.d.querySelector('#target').value,'adult traveler');assert.equal(f.value,'blur');assert.equal(f.preview(),'blur, blue jacket');
    await f.apply();assert.equal(f.value,'blur, blue jacket');
});
await test('modify composition during source read cancels old operation',async f=>{
    f.block();const operation=f.action('应用到目标').onclick();const input=f.host.querySelector('textarea');input.value='red jacket';input.dispatchEvent(new f.dom.window.Event('input'));
    f.release();await operation;await f.settle();assert.equal(f.value,'adult traveler');assert.match(f.reports.at(-1),/待用内容或方向已变化/);assert.equal(f.preview(),'adult traveler, red jacket');
});
await test('external edits invalidate undo and are never overwritten',async f=>{
    await f.apply();f.value='manual change';f.d.querySelector('#target').dispatchEvent(new f.dom.window.Event('input'));
    assert.equal(f.action('撤销本次写入').disabled,true);assert.equal(f.value,'manual change');
});
await test('expired workflow target prevents write',async f=>{f.invalidate();await f.apply();assert.equal(f.value,'adult traveler');assert.match(f.reports.at(-1),/目标工作流/);});
await test('weight enable and order edits keep replacement mode and preview',async f=>{
    f.add('pose');await f.settle();await f.setMode('replace_prompt');f.host.querySelector('[data-uw="pending-down"]').click();await f.settle();
    const weight=f.host.querySelector('[aria-label="本次权重"]');f.change(weight,'1.2');await f.settle();assert.equal(f.preview(),'(standing:1.2), blue jacket');
    const enabled=f.host.querySelector('input[type=checkbox]');enabled.checked=false;enabled.dispatchEvent(new f.dom.window.Event('change'));await f.settle();
    assert.equal(f.mode().value,'replace_prompt');assert.equal(f.preview(),'blue jacket');
});
const result={passed:checks.every(c=>c.passed),source,checks};fs.writeFileSync(out,JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));if(!result.passed)process.exitCode=1;
