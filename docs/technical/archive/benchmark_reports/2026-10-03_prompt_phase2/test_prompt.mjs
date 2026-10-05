import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
const base=new URL('./',import.meta.url);
const source=fs.readFileSync(new URL('staged/prompt_target.js',base),'utf8').replace("import {manageModal} from './modal_focus.js';",'const manageModal=()=>()=>{};');
const {createTextInserter,createWidgetInserter}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const results=[];
async function test(name,fn){await fn();results.push(name);}
let value,key,valid;
const reset=(text='mountain path')=>{value=text;key={};valid=true;};
const writer=(kind,options={})=>createTextInserter({key,fragmentKind:kind,commaSeparated:true,read:()=>value,write:v=>value=v,validate:()=>valid,...options});
await test('category replacement survives close/reopen and leaves existing identical text alone',async()=>{
 reset('adult traveler, manual base');let w=writer('character');await w('adult traveler');w.dispose();w=writer('character');
 const p=await w.preview({text:'adult hiker',action:'replace_fragment'});assert.equal(p.affected,'adult traveler');assert.equal(p.after,'adult traveler, manual base, adult hiker');assert.equal(value,'adult traveler, manual base, adult traveler');
 await w({text:'adult hiker',action:'replace_fragment',expectedCurrent:p.before});assert.equal(value,p.after);assert(w.undoLast());assert.equal(value,p.before);
});
await test('interleaved category writes preserve and move ranges; undo restores provenance',async()=>{
 reset();await writer('character')('adult traveler');await writer('clothing')('blue coat');await writer('pose')('walking');
 let w=writer('character');await w({action:'replace_fragment',text:'adult mountain hiker'});assert.equal(value,'mountain path, adult mountain hiker, blue coat, walking');
 w=writer('clothing');await w({action:'replace_fragment',text:'green jacket'});assert.equal(value,'mountain path, adult mountain hiker, green jacket, walking');assert(w.undoLast());
 w=writer('pose');await w({action:'replace_fragment',text:'standing'});assert.equal(value,'mountain path, adult mountain hiker, blue coat, standing');
});
await test('manual edits fail closed; new append starts a fresh record',async()=>{
 reset();const w=writer('character');await w('adult traveler');value+=' manual';await assert.rejects(w.preview({action:'replace_fragment',text:'adult hiker'}),/没有可安全/);
 const old=value;await w('adult explorer');await w({action:'replace_fragment',text:'adult hiker'});assert.equal(value,old+', adult hiker');
});
await test('unknown category, new page key, stale target and stale preview refuse replacement',async()=>{
 reset();await writer('character')('adult traveler');await assert.rejects(writer('pose')({action:'replace_fragment',text:'walking'}),/没有可安全/);
 key={};await assert.rejects(writer('character')({action:'replace_fragment',text:'adult hiker'}),/没有可安全/);
 await writer('character')('adult traveler');const w=writer('character');const p=await w.preview({action:'replace_fragment',text:'adult hiker'});value+=' manual';await assert.rejects(w({...p,expectedCurrent:p.before}),/预览后/);
 valid=false;await assert.rejects(w('anything'),/目标工作流/);
});
await test('generic writes track unaffected ranges and invalidate replaced/overlapping fragments',async()=>{
 reset();await writer('character')('adult traveler');await writer(null)('sunset');await writer('character')({action:'replace_fragment',text:'adult hiker'});assert.equal(value,'mountain path, adult hiker, sunset');
 await writer(null)({action:'replace_prompt',text:'new manual scene'});await assert.rejects(writer('character')({action:'replace_fragment',text:'adult traveler'}),/没有可安全/);
});
await test('cursor insertion shifts ranges and overlapping selection invalidates tracking',async()=>{
 reset();await writer('character')('adult traveler');let w=writer(null,{selectionSnapshot:{value,start:0,end:0}});await w({action:'append_cursor',text:'sunset'});
 w=writer('character');await w({action:'replace_fragment',text:'adult hiker'});assert.equal(value,'sunset, mountain path, adult hiker');
 const start=value.indexOf('hiker');await writer(null,{selectionSnapshot:{value,start,end:start+5}})({action:'replace_selection',text:'explorer'});
 await assert.rejects(writer('character')({action:'replace_fragment',text:'adult traveler'}),/没有可安全/);
});
await test('special prompt syntax remains verbatim and only the latest same-kind insertion is replaced',async()=>{
 reset('(mountain:1.2), __weather__, <lora:coat:0.7>, embedding:path\\(v2\\)');const original=value;let w=writer('character');await w('adult traveler');await w('adult explorer');await w({action:'replace_fragment',text:'adult hiker'});assert.equal(value,original+', adult traveler, adult hiker');
});
await test('widget and active-branch validation blocks stale dialogs',async()=>{
 const widget={name:'text',value:'base'};const node={id:1,widgets:[widget],mode:0};const graph={id:'qa',getNodeById:()=>node,extra:{uap_workbench:{activeBranch:'a',branches:[{id:'a',nodeIds:[1]},{id:'b',nodeIds:[]}]}}};const app={graph};node.graph=graph;
 const w=createWidgetInserter(app,{node,widget},{fragmentKind:'character',commaSeparated:true});await w('adult traveler');graph.extra.uap_workbench.activeBranch='b';await assert.rejects(w({action:'replace_fragment',text:'adult hiker'}),/目标工作流/);assert.equal(widget.value,'base, adult traveler');
});
const character=fs.readFileSync(new URL('staged/anima_character_selector.js',base),'utf8');
const helpers=character.slice(character.indexOf('function splitPromptTokens'),character.indexOf('function formatCharacterDisplayName'));
const ctx=vm.createContext({});vm.runInContext(helpers,ctx);
await test('shared primary tags display even without detail_tags; display merges details without changing insertion helpers',()=>{
 const arr=x=>Array.from(x);assert.deepEqual(arr(ctx.getCharacterDisplayTags({shared:true,tags:'adult traveler, blue coat',detail_tags:[]})),['adult traveler','blue coat']);
 assert.deepEqual(arr(ctx.getCharacterDisplayTags({shared:true,tags:'adult traveler, blue coat',detail_tags:['blue coat','silver hair']})),['adult traveler','blue coat','silver hair']);
 assert.deepEqual(arr(ctx.getExplicitCharacterTags({shared:true,tags:'adult traveler',detail_tags:[]})),[]);
 assert.deepEqual(arr(ctx.getCharacterDisplayTags({shared:true,tags:'',detail_tags:[]})),[]);
 assert.deepEqual(arr(ctx.getCharacterDisplayTags({isCustom:true,customContent:'adult hiker, green jacket'})),['adult hiker','green jacket']);
 assert.deepEqual(arr(ctx.getCharacterTags({name:'traveler',tags:['blue coat']})),['blue coat']);
});
await test('character apply builder stays unchanged',()=>{
 const old=fs.readFileSync(new URL('before/anima_character_selector.js',base),'utf8');const extract=s=>s.slice(s.indexOf('async function buildValidatedSelection'),s.indexOf("footer.style.flexWrap"));assert.equal(extract(old),extract(character));
});
fs.writeFileSync(new URL('tests.json',base),JSON.stringify({passed:results.length,tests:results},null,2));console.log(JSON.stringify({passed:results.length,tests:results}));
