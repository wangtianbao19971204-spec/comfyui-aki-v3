import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {JSDOM} from '../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const base=path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-anima-tools/js');
const reportRoot=path.resolve('benchmark_reports/2026-09-30_next_workbench');
const previous=path.join(reportRoot,'before_selector_lifecycle_2026-10-01',path.relative(process.cwd(),base));
const read=(directory,kind)=>fs.readFileSync(path.join(directory,`anima_${kind}_selector.js`),'utf8').replace(/\r\n/g,'\n');
function functionSource(source,name){
    const start=source.indexOf(`    function ${name}(`);
    const asyncStart=source.indexOf(`    async function ${name}(`);
    const found=start<0?asyncStart:start;
    assert(found>=0,`missing function ${name}`);
    const end=source.indexOf('\n    }',found);
    assert(end>=0,`missing end of ${name}`);
    return source.slice(found,end+6);
}
const uiSource=fs.readFileSync(path.join(base,'anima_selector_ui.js'),'utf8');
const debounceSource=uiSource.match(/export function debounce[\s\S]*?\n\}/)[0].replace('export ','');
const item={id:'qa-source',shared:true,source_prompt_id:'qa-source',name:'QA source',tags:'qa source'};
function galleryFixture(kind,source,items=[item]){
    const dom=new JSDOM('<input type="search"><section><div id="list"></div></section>',{url:'http://127.0.0.1:8188/',runScripts:'outside-only'});
    const win=dom.window,context=dom.getInternalVMContext(),timers=new Map();let sequence=0;
    win.setTimeout=callback=>{const id=++sequence;timers.set(id,callback);return id;};
    win.clearTimeout=id=>timers.delete(id);win.fixtureItems=items;
    vm.runInContext(`
        let isClosed=false,currentPage=1,totalPages=1,filteredData=[],lastScrollTop=0;
        let observedAfterClose=0,renders=0,storageWrites=0,paginationUpdates=0;
        const targets=new Set(),searchInput=document.querySelector('input'),overlay=document.querySelector('section'),listContainer=document.getElementById('list');
        const styleSheet=document.head.appendChild(document.createElement('style'));
        const imageObserver={observe(image){targets.add(image);if(isClosed)observedAfterClose++;},disconnect(){targets.clear();}};
        const insertionControls={dispose(){}},stopLibrarySync=()=>{},disposeDialog=()=>{};
        const activeFilters={collection:'all',categories:new Set(),traits:new Set()},activeSort='id-asc',showSelectedOnly=false;
        const favoriteItems=[],favoriteMap=new Map(),favoriteSet=new Set(),selectedClothing=new Set(),selectedBackground=new Set(),selectedPose=new Set();
        let clothingData=fixtureItems,backgroundData=fixtureItems,poseData=fixtureItems;
        const PAGE_STORAGE_KEY='qa-page',getItemKey=item=>item.id,getPromptSearchRank=()=>0,rankPromptSearchResults=items=>items;
        const updatePaginationBar=()=>{paginationUpdates++;},updateCountLabel=()=>{renders++;};
        const createCard=item=>{const card=document.createElement('article'),image=document.createElement('img');
            const edit=document.createElement('button');edit.className='anima-shared-resource-edit';edit.dataset.promptId=item.source_prompt_id;card.append(image,edit);imageObserver.observe(image);return card;};
        const createCustomPlaceholderCard=()=>document.createElement('article');
        const createEl=tag=>document.createElement(tag),escapeHtml=text=>text,t=text=>text,THEME={accentText:'#fff'};
        const originalSetItem=localStorage.setItem.bind(localStorage);
        Object.getPrototypeOf(localStorage).setItem=function(key,value){storageWrites++;originalSetItem(key,value);};
        ${debounceSource}
        ${functionSource(source,'triggerFilter')}
        ${functionSource(source,'renderCurrentPage')}
        ${functionSource(source,'closeModal')}
    `,context);
    let searchStart=source.indexOf('    let searchTimer;');
    if(searchStart<0)searchStart=source.indexOf('    searchInput.addEventListener("input", debounce(');
    const searchEnd=source.indexOf('\n    function renderSidebar(',searchStart);
    assert(searchStart>=0&&searchEnd>searchStart,'missing production search handler');
    vm.runInContext(source.slice(searchStart,searchEnd),context);
    const snapshot=()=>vm.runInContext('({closed:isClosed,targets:targets.size,observedAfterClose,renders,storageWrites,paginationUpdates,sourceCards:listContainer.querySelectorAll(".anima-shared-resource-edit").length})',context);
    return {dom,context,timers,snapshot,run:code=>vm.runInContext(code,context),flushTimers(){for(const [id,callback]of [...timers]){timers.delete(id);callback();}}};
}
const results=[];
for(const kind of ['clothing','background','pose']){
    for(const [version,directory]of [['before',previous],['current',base]]){
        const fixture=galleryFixture(kind,read(directory,kind));
        fixture.run('triggerFilter()');assert.equal(fixture.snapshot().sourceCards,1);
        fixture.run("searchInput.value='qa';searchInput.dispatchEvent(new Event('input'));closeModal()");
        const closed=fixture.snapshot();assert.equal(closed.targets,0);
        const pendingTimers=fixture.timers.size;fixture.flushTimers();
        const after=fixture.snapshot();
        if(version==='current'){
            assert.equal(pendingTimers,0);assert.equal(after.observedAfterClose,0);
            assert.equal(after.renders,closed.renders);assert.equal(after.storageWrites,closed.storageWrites);
            fixture.run('triggerFilter();renderCurrentPage()');
            assert.equal(fixture.snapshot().observedAfterClose,0);assert.equal(fixture.snapshot().renders,closed.renders);
        }else{
            assert(pendingTimers>0);assert(after.observedAfterClose>0,'old source must reproduce observing images after close');
        }
        results.push({kind,version,pendingTimers,observedAfterClose:after.observedAfterClose});fixture.dom.window.close();
    }
}
for(const [version,directory]of [['before',previous],['current',base]]){
    const source=read(directory,'character'),dom=new JSDOM('',{runScripts:'outside-only'}),context=dom.getInternalVMContext();
    const styleStart=source.indexOf('    const styleSheet = document.createElement("style");');
    const styleEnd=source.indexOf('    document.head.appendChild(styleSheet);',styleStart)+'    document.head.appendChild(styleSheet);'.length;
    for(let round=0;round<3;round++)vm.runInContext(`(()=>{
        let isClosed=false;
        const modalOverlay=document.body.appendChild(document.createElement('section'));
        const stopLibrarySync=()=>{},insertionControls={dispose(){}},hideCharacterTagsTooltip=()=>{},charImageObserver={disconnect(){}};
        ${source.slice(styleStart,styleEnd)}
        ${functionSource(source,'closeModal')}
        closeModal();
    })()`,context);
    const styles=dom.window.document.head.querySelectorAll('style').length;
    assert.equal(styles,version==='before'?3:0);results.push({kind:'character',version,stylesAfterThreeCloses:styles});dom.window.close();
}

const flush=async()=>{for(let index=0;index<5;index++)await Promise.resolve();};
function addPoseLoading(fixture,source,loadAll){
    const win=fixture.dom.window;let releaseIndex,releaseCategory;
    win.sharedPoseIndexPromise=new Promise(resolve=>{releaseIndex=resolve;});
    win.loadSharedPromptItems=()=>new Promise(resolve=>{releaseCategory=resolve;});
    vm.runInContext(`
        const config={loadAllOnOpen:${loadAll}},sharedKind='pose',localPoseData=[];
        let sharedIndexItems=[],dataById=new Map(),loadingSharedFilter='';
        const sharedLoadedItems=new Map(),loadedSharedFilters=new Set();
        const getPromptItemBaseKey=getItemKey,getPromptItemVariantKey=getItemKey,assignPromptSelectorKeys=items=>items,mergePromptItems=(left,right)=>[...left,...right];
        const pruneSharedCategoryFilters=()=>false,normalizeSharedCategoryNavigationFilters=()=>false,normalizeSelectorCategoryValue=value=>value;
        const persistFilters=()=>{},renderSidebar=()=>{},isSharedCategoryFilter=value=>value.startsWith('shared:');
        ${functionSource(source,'activeSharedCategoryFilter')}
        ${functionSource(source,'rebuildPoseDataFromSharedItems')}
        ${functionSource(source,'upsertSharedItems')}
        ${functionSource(source,'applySharedPoseItems')}
        ${functionSource(source,'ensureActiveSharedCategoryLoaded')}
    `,fixture.context);
    const token=source.includes('    await sharedPoseIndexPromise\n')?'    await sharedPoseIndexPromise\n':'    sharedPoseIndexPromise\n';
    const start=source.lastIndexOf(token),end=source.indexOf('\n}',start);
    assert(start>=0&&end>start,'missing production initial-loading chain');
    const open=fixture.run(`(async()=>{${source.slice(start,end)}})()`);
    return {open,releaseIndex:items=>releaseIndex(items),releaseCategory:items=>releaseCategory(items)};
}
for(const [version,directory]of [['before',previous],['current',base]]){
    const source=read(directory,'pose'),fixture=galleryFixture('pose',source,[]),loading=addPoseLoading(fixture,source,true);
    let settled=false;loading.open.then(()=>{settled=true;});await flush();
    assert.equal(settled,version==='before');assert.equal(fixture.snapshot().sourceCards,0);
    const settledBeforeFirstRender=settled;loading.releaseIndex([item]);await flush();await loading.open;
    assert.equal(fixture.snapshot().sourceCards,1);assert.equal(settled,true);
    results.push({kind:'pose_and_style_quality',version,settledBeforeFirstRender,sourceCardsAfterLoad:fixture.snapshot().sourceCards});fixture.run('closeModal()');fixture.dom.window.close();
}
for(const [version,directory]of [['before',previous],['current',base]]){
    const source=read(directory,'pose'),fixture=galleryFixture('pose',source,[]),loading=addPoseLoading(fixture,source,false);
    let settled=false;loading.open.then(()=>{settled=true;});
    fixture.run("activeFilters.categories.add('shared:qa')");
    loading.releaseIndex([]);await flush();
    assert.equal(settled,version==='before');const settledBeforeCategoryRender=settled;
    const paginationBeforeClose=fixture.snapshot().paginationUpdates;assert(paginationBeforeClose>0);
    fixture.run('closeModal()');loading.releaseCategory([item]);await flush();await loading.open;
    const paginationAfterClose=fixture.snapshot().paginationUpdates;
    assert.equal(paginationAfterClose-paginationBeforeClose,version==='before'?1:0);
    assert.equal(fixture.snapshot().observedAfterClose,0);
    results.push({kind:'pose_delayed_category',version,settledBeforeCategoryRender,paginationUpdatesAfterClose:paginationAfterClose-paginationBeforeClose});fixture.dom.window.close();
}
const receipt={passed:true,harness:'production search, close, filter, render and initial-loading functions executed with controlled timers and source promises; unrelated card layout and data services stubbed',checks:[
    'input followed by close cancels pending search in clothing, background, pose and shared style/quality implementation',
    'closed filters and renders do not reobserve detached images or write pagination state',
    'three character open/close cycles leave no per-window stylesheet',
    'pose/style opening resolves after first shared-source cards render',
    'late category load after close does not update detached pagination',
    'unmodified backups reproduce stale observer, stylesheet and early-opening failures',
],results};
fs.writeFileSync(path.join(reportRoot,'selector_lifecycle_test_2026-10-01.json'),JSON.stringify(receipt,null,2));
console.log(JSON.stringify(receipt,null,2));
