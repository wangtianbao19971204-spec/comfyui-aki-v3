import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {JSDOM} from 'file:///G:/ComfyUI-aki-v3/benchmark_reports/2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const root='ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/js_node/prompt_selector';
const dom=new JSDOM('<main></main>',{runScripts:'outside-only'});
const context=dom.getInternalVMContext();
const module=new vm.SourceTextModule(fs.readFileSync(`${root}/native_library_browser.js`,'utf8'),{context});
await module.link(()=>{});await module.evaluate();
const {document}=dom.window;
const items=[
    {id:'one',alias:'QA one',prompt:'alpha',_categoryId:'qa',_categoryName:'QA'},
    {id:'two',alias:'QA two',prompt:'beta',_categoryId:'qa',_categoryName:'QA'},
];
let releaseFirstRevision,revisionReads=0,loadCalls=0,feedbackCalls=0;
const request=async path=>{
    if(path.endsWith('/library/index'))return {ok:true,json:async()=>({categories:[{id:'qa',name:'QA',prompt_count:2}]})};
    if(path.includes('/library/prompts?'))return {ok:true,json:async()=>({items,total:2,offset:0,last_modified:'qa-rev'})};
    if(path.endsWith('/library/revision')){
        revisionReads++;
        if(revisionReads===1)return new Promise(resolve=>{releaseFirstRevision=resolve;});
        return {ok:true,json:async()=>({revision:'qa-rev'})};
    }
    throw Error(`unexpected request ${path}`);
};
const widget={name:'selected_prompts',value:'blue sky'};
const node={id:7,widgets:[widget],properties:{selectedPrompts:'{"QA":["old"]}',promptWeights:'{}'},
    loadPrompt({prompt}){loadCalls++;widget.value=prompt;}};
const graph={getNodeById:id=>id===7?node:null};node.graph=graph;
await module.namespace.openPagedPromptLibrary({node,request,currentGraph:()=>graph,manageModal:()=>()=>{},onApplied:()=>{feedbackCalls++;throw Error('feedback unavailable');}});
const apply=document.querySelector('.ps-paged-footer .ps-paged-primary');
const undo=document.querySelector('.ps-paged-footer button:last-child');
const boxes=[...document.querySelectorAll('.ps-paged-row input')];
boxes[0].click();
apply.click();assert.equal(apply.textContent,'确认载入');
apply.click();assert(releaseFirstRevision);
boxes[1].click();
assert.equal(document.querySelector('.ps-paged-review').hidden,true);
releaseFirstRevision({ok:true,json:async()=>({revision:'qa-rev'})});
await new Promise(setImmediate);
assert.equal(loadCalls,0);
assert.equal(widget.value,'blue sky');
assert.match(document.querySelector('.ps-paged-status').textContent,/重新确认/);
apply.click();assert.match(document.querySelector('.ps-paged-review').textContent,/alpha, beta/);
apply.click();await new Promise(setImmediate);
assert.equal(loadCalls,1);
assert.equal(widget.value,'alpha, beta');
assert.equal(node.properties.selectedPrompts,'{}');
assert.equal(undo.disabled,false);
assert.match(document.querySelector('.ps-paged-status').textContent,/已载入当前节点，可撤销/);
undo.click();assert.equal(widget.value,'blue sky');
assert.equal(node.properties.selectedPrompts,'{"QA":["old"]}');
assert.match(document.querySelector('.ps-paged-status').textContent,/已撤销本次载入/);
apply.click();apply.click();await new Promise(setImmediate);
assert.equal(widget.value,'alpha, beta');
widget.value='manual edit';undo.click();
assert.equal(widget.value,'manual edit');
assert.match(document.querySelector('.ps-paged-status').textContent,/目标已变化/);
assert.equal(loadCalls,3);
assert.equal(feedbackCalls,3);
console.log(JSON.stringify({passed:true,revisionReads,loadCalls,feedbackCalls,checks:['old confirmation cannot apply a newer preview','feedback failure preserves write and undo','feedback failure preserves undo result','manual target change blocks old undo']}));
dom.window.close();
