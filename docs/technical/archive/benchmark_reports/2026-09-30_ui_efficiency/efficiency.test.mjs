import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {performance} from 'node:perf_hooks';
import {JSDOM} from '../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const root='ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/';
const report='benchmark_reports/2026-09-30_ui_efficiency/';
const native='modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/js_node/prompt_selector/prompt_selector.js';
const daily='modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js';
const library='modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/dist/javascript/zz_tb_shared_preset_manager.js';
const read=(file,before=false)=>fs.readFileSync((before?report+'before/':root)+file,'utf8');
const checks=[];
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
const makeDom=html=>new JSDOM(html,{url:'http://localhost/',runScripts:'outside-only',pretendToBeVisual:true});

function renderNative(before=false){
    const dom=makeDom('<div class="ps-library-modal"><button id="ps-library-close"></button><input id="ps-library-search-input"><div class="ps-prompt-list-container"></div></div>');
    const w=dom.window,d=w.document;
    const source=read(native,before),start=source.indexOf('this.renderPromptList = ('),end=source.indexOf('this.buildCategoryTree =',start);
    let selected=null,edited=null;
    const prompts=Array.from({length:3000},(_,i)=>({id:'p'+i,alias:'Entry '+i,prompt:'neutral test '+i,tags:[],description:'',favorite:false}));
    w.fixture={promptData:{categories:[{name:'test',prompts}]},currentFilter:{favorites:false,tags:[]},selectedForBatch:new Set(),selectedForBatchSources:new Map(),
        showPromptTooltip(){},hidePromptTooltip(){},loadPrompt(p){selected=p.id;},showEditModal(p,category){edited=[p.id,category];}};
    w.t=s=>s;
    w.eval('(function(){'+source.slice(start,end)+'}).call(window.fixture)');
    const begin=performance.now();w.fixture.renderPromptList('test');const elapsed=performance.now()-begin;
    const count=d.querySelectorAll('.ps-prompt-list-item').length;
    if(!before){
        assert.equal(count,80);d.querySelector('.ps-load-more').click();assert.equal(d.querySelectorAll('.ps-prompt-list-item').length,160);
        assert.equal(new Set([...d.querySelectorAll('.ps-prompt-list-item')].map(x=>x.dataset.promptId)).size,160);
        const first=d.querySelector('.ps-prompt-list-item');first.focus();first.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
        assert.equal(d.activeElement.dataset.promptId,'p1');d.activeElement.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));assert.equal(selected,'p1');
        w.fixture.renderPromptList('test');assert.equal(d.querySelectorAll('.ps-prompt-list-item').length,160);
        d.querySelector('input').value='Entry 2999';w.fixture.renderPromptList(null);
        assert.equal(d.querySelectorAll('.ps-prompt-list-item').length,1);
        d.querySelector('.ps-edit-btn').click();assert.deepEqual(edited,['p2999','test']);
        d.querySelector('input').value='no-match';w.fixture.renderPromptList(null);assert.equal(d.querySelectorAll('.ps-prompt-list-item').length,0);
        checks.push('WeiLin: bounded initial render, append without duplicates, focus keys, retained visible count, global search source and empty state');
    }
    dom.window.close();return {fixtureItems:3000,renderedRows:count,renderMs:Math.round(elapsed)};
}

async function dailyIdle(before=false){
    const dom=makeDom('<div id="host"></div>'),w=dom.window,d=w.document,timers=[];
    w.setInterval=fn=>{timers.push(fn);return timers.length;};
    const node={id:1,type:'WeiLinPromptUI',title:'正向',mode:0,widgets:[{name:'positive',value:'neutral'}]};
    const branch={id:'one',label:'One',nodeIds:[1]};
    let reads=0;
    w.appFixture={graph:{extra:{uap_workbench:{activeBranch:'one',branches:[branch]}},getNodeById:()=>{reads++;return node;}},canvas:{}};
    w.fetch=async()=>({ok:true,json:async()=>({LoraLoader:{input:{required:{lora_name:[[]]}}},settings:{}})});
    w.eval('const app=window.appFixture, sharedCommitWidget=()=>{},attachPromptAutocomplete=()=>{},createWidgetInserter=()=>{},mountThemeToggle=()=>{};'+read(daily,before).replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'')+';window.controls=createDailyControls(()=>{});');
    w.controls.render(branch,true);w.controls.mount(d.querySelector('#host'),branch,()=>{});await tick();
    const observer=new w.MutationObserver(()=>{});observer.observe(d.querySelector('#uap-daily-desk'),{subtree:true,attributes:true,childList:true,characterData:true});
    for(let i=0;i<100;i++)timers.forEach(fn=>fn());
    const mutations=observer.takeRecords().length;
    d.querySelector('#host').hidden=true;reads=0;for(let i=0;i<100;i++)timers.forEach(fn=>fn());
    const hiddenReads=reads;
    if(!before){assert.equal(mutations,0);assert.equal(hiddenReads,0);checks.push('UAP: no repeated DOM writes while unchanged; hidden ancestor skips graph scans');}
    observer.disconnect();dom.window.close();return {ticks:100,unchangedDomMutations:mutations,hiddenGraphReads:hiddenReads};
}

async function selectorKeys(){
    const dom=makeDom('<div class="overlay"><div><input placeholder="搜索"><div class="grid" style="display:grid;grid-template-columns:100px 100px"><div class="anima-shared-resource-card" tabindex="0"></div><div class="anima-shared-resource-card" tabindex="0"></div><div class="anima-shared-resource-card" tabindex="0"></div></div></div></div>');
    const w=dom.window,d=w.document,context=dom.getInternalVMContext();
    const module=new vm.SourceTextModule(read('modules/comfyui-anima-tools/js/anima_selector_ui.js'),{context});
    await module.link(async specifier=>new vm.SyntheticModule(specifier.includes('ui_identity')?['mountFunctionCard']:['createWidgetInserter','mountInsertionActions'],function(){for(const name of (specifier.includes('ui_identity')?['mountFunctionCard']:['createWidgetInserter','mountInsertionActions']))this.setExport(name,()=>{});},{context}));
    await module.evaluate();
    const overlay=d.querySelector('.overlay'),input=d.querySelector('input'),cards=[...d.querySelectorAll('.anima-shared-resource-card')];
    const release=module.namespace.installSelectorExperience(overlay,'pose');let searches=0;input.oninput=()=>searches++;
    input.dispatchEvent(new w.CompositionEvent('compositionstart'));input.dispatchEvent(new w.InputEvent('input',{bubbles:true,isComposing:true}));assert.equal(searches,0);
    input.dispatchEvent(new w.CompositionEvent('compositionend'));assert.equal(searches,1);
    cards[0].focus();cards[0].dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));assert.equal(d.activeElement,cards[2]);
    cards[2].dispatchEvent(new w.KeyboardEvent('keydown',{key:'Home',bubbles:true}));assert.equal(d.activeElement,cards[0]);
    release();dom.window.close();checks.push('Shared selectors: IME deferred until composition completes; keyboard navigation follows grid columns');
}

async function librarySearch(){
    const dom=makeDom('<button id="caller">Open</button>'),w=dom.window,d=w.document;
    w.structuredClone=structuredClone;w.IntersectionObserver=class{observe(){}unobserve(){}disconnect(){}};
    w.HTMLElement.prototype.getClientRects=function(){return this.isConnected&&!this.closest('[hidden]')?[{}]:[];};
    const requests=[],pending=[];let defer=false;
    const response=items=>({ok:true,status:200,headers:{get:()=>null},json:async()=>items});
    const item=id=>({id,alias:id,prompt:'body '+id,strings:true,_categoryId:'c',_categoryName:'ATG',_semantic:{manual_search_eligible:true,usage:'positive'}});
    w.fetch=async(url)=>{
        const u=new URL(url,'http://localhost');
        if(u.pathname.endsWith('/library/index'))return response({categories:[{id:'c',name:'ATG',prompt_count:1}]});
        if(u.pathname.endsWith('/library/prompts')){requests.push(u.searchParams.get('q')||'');if(defer)return new Promise(resolve=>pending.push({q:u.searchParams.get('q'),resolve}));return response({items:[item('before')],total:1});}
        if(u.pathname.includes('embedding'))return response({items:[],embeddings:[]});
        return response({});
    };
    w.eval(read(library));d.querySelector('#caller').focus();await w.tbOpenSharedPresetManager({});
    const search=d.querySelector('.tb-spm-search'),list=d.querySelector('.tb-spm-list'),first=list.querySelector('.tb-spm-card');assert(first);
    assert(!first.textContent.includes('null'));assert(first.querySelector('.tb-spm-actions > [data-act=copy]'));
    const timers=[];w.setTimeout=(fn)=>{timers.push(fn);return timers.length;};w.clearTimeout=id=>{if(id)timers[id-1]=null;};
    search.value='中';search.dispatchEvent(new w.CompositionEvent('compositionstart'));search.dispatchEvent(new w.InputEvent('input',{bubbles:true,isComposing:true}));assert.equal(requests.length,1);assert.equal(list.firstElementChild,first);
    search.dispatchEvent(new w.CompositionEvent('compositionend'));assert.equal(list.firstElementChild,first);assert.equal(list.inert,true);
    defer=true;const firstSearch=timers.filter(Boolean).at(-1)();await tick();assert.equal(pending.length,1);
    search.value='new';search.dispatchEvent(new w.Event('input'));const secondSearch=timers.filter(Boolean).at(-1)();await tick();assert.equal(pending.length,2);
    pending[1].resolve(response({items:[item('new')],total:1}));await secondSearch;
    pending[0].resolve(response({items:[item('old')],total:1}));await firstSearch;
    assert.equal(list.querySelector('.tb-spm-alias').textContent,'new');assert.equal(list.inert,false);assert(!list.hasAttribute('aria-busy'));
    checks.push('Library: IME no premature request, retained DOM during typing, stale reply discarded, search unlock, ATG actions contain no null text, direct copy');
    dom.window.close();
}

const before={native:renderNative(true),uap:await dailyIdle(true)};
const after={native:renderNative(),uap:await dailyIdle()};
await selectorKeys();await librarySearch();
const result={passed:true,before,after,checks,limitations:'Render timing uses jsdom and synthetic neutral data; not a browser FPS, heap or GPU benchmark.'};
fs.writeFileSync(report+'efficiency_results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
