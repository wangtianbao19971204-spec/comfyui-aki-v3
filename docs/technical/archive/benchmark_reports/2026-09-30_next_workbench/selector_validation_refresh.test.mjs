import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {JSDOM} from '../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const source=process.env.ANIMA_SHARED_SOURCE||path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-anima-tools/js/anima_shared_prompt_data.js');
const dom=new JSDOM('',{url:'http://127.0.0.1:8188/',runScripts:'outside-only'});
const win=dom.window,context=dom.getInternalVMContext(),requests=[];
win.fetch=(url,options)=>new Promise(resolve=>requests.push({url:new URL(url,win.location.href),options,resolve}));
const ui=new vm.SyntheticModule(['installSelectorExperience'],function(){this.setExport('installSelectorExperience',()=>()=>{});},{context});
const module=new vm.SourceTextModule(fs.readFileSync(source,'utf8'),{context,identifier:source});
await module.link(()=>ui);await module.evaluate();
const {loadSharedPromptItems,refreshMergedPromptItems,validateSharedPromptSelection}=module.namespace;
const item=(tags,binding)=>({id:'shared-character-a',name:'Fixture A',tags,shared:true,
    _semantic:{binding,disposition:'reviewed',manual_search_eligible:true,usage:'positive',content_type:'fragment'}});
const first=item('red coat','v1'),updated=item('green coat','v2');
const respond=(index,items)=>requests[index].resolve({ok:true,json:async()=>({enabled:true,items})});
const outcome=promise=>promise.then(value=>({value}),error=>({error}));

const oldRead=outcome(loadSharedPromptItems('character'));
const validating=validateSharedPromptSelection('character',[first]);
assert.equal(requests.length,2,'validation starts a fresh read instead of reusing the earlier in-flight request');
assert.equal(requests[1].url.pathname,'/anima-tools/shared-prompts');
assert.equal(requests[1].url.searchParams.get('kind'),'character');
assert.equal(requests[1].url.searchParams.has('refresh'),false,'validation does not force a server rebuild');
assert.equal(requests[1].options.cache,'no-store');
respond(1,[first]);await validating;
respond(0,[updated]);assert.equal((await oldRead).error?.code,'STALE_SHARED_PROMPTS');

const nextRead=outcome(loadSharedPromptItems('character'));
assert.equal(requests.length,3,'completed results are not reused without checking the server again');
const syncing=refreshMergedPromptItems('character',[]);
assert.equal(requests.length,4);
assert.equal(requests[3].url.searchParams.has('refresh'),true,'explicit sync retains its server refresh request');
assert.equal(requests[3].options.cache,'no-store');
respond(3,[updated]);assert.equal((await syncing)[0].tags,'green coat');
respond(2,[first]);assert.equal((await nextRead).error?.code,'STALE_SHARED_PROMPTS');

const changed=assert.rejects(()=>validateSharedPromptSelection('character',[first]),/资料已变更/);
assert.equal(requests[4].url.searchParams.has('refresh'),false);
respond(4,[updated]);await changed;
const rejected=assert.rejects(()=>validateSharedPromptSelection('character',[updated]),/资料已变更/);
respond(5,[{...updated,_semantic:{...updated._semantic,manual_search_eligible:false}}]);await rejected;
await validateSharedPromptSelection('character',[{isCustom:true}]);
assert.equal(requests.length,6);
dom.window.close();
console.log(JSON.stringify({passed:true,checks:[
    'selection validation reads anew with HTTP no-store and no server refresh parameter',
    'late results from the replaced in-flight request are rejected by request identity',
    'explicit sync still requests server refresh and invalidates the older in-flight read',
    'source body or binding changes and revoked semantic eligibility still reject the selection',
]}));
