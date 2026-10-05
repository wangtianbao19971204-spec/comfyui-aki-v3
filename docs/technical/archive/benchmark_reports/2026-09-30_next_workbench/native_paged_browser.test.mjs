import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {JSDOM} from 'file:///G:/ComfyUI-aki-v3/benchmark_reports/2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const root = 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/js_node/prompt_selector';
const fixture = JSON.parse(fs.readFileSync('benchmark_reports/2026-09-30_next_workbench/candidate_data/native_193.json','utf8'));
const dom = new JSDOM('<button id="entry">词库</button>', {runScripts:'outside-only',pretendToBeVisual:true});
const context = dom.getInternalVMContext();
const module = new vm.SourceTextModule(fs.readFileSync(`${root}/native_library_browser.js`, 'utf8'), {context});
await module.link(() => {});
await module.evaluate();
const {document, Event} = dom.window;
const rows = fixture.map(item => ({id:item.id, alias:item.text, prompt:item.text,
    _categoryId:`qa-${item.group}`, _categoryName:`QA 分类 ${item.group}`}));
let revision = 'qa-rev-1', pageRequests = 0, fullReads = 0, saved = 0, favoriteWrites = 0, categoryWrites = 0;
const categories = [1,2,3].map(group => ({id:`qa-${group}`,name:`QA 分类 ${group}`,prompt_count:rows.filter(row=>row._categoryId===`qa-${group}`).length}));
const request = async (path,options={}) => {
    if (path.includes('/prompt_selector/data')) fullReads++;
    if (path.endsWith('/categories/create')) {
        const payload=JSON.parse(options.body);
        assert.equal(options.headers['If-Match'],revision);
        categories.push({id:'qa-created',name:payload.name,prompt_count:0});
        categoryWrites++;revision=`qa-category-${categoryWrites}`;
        return {ok:true,json:async()=>({success:true,revision})};
    }
    if (path.endsWith('/category/rename')) {
        const payload=JSON.parse(options.body), found=categories.find(item=>item.name===payload.old_name);
        assert(found);assert.equal(options.headers['If-Match'],revision);
        found.name=payload.new_name;
        for(const row of rows)if(row._categoryId===found.id)row._categoryName=found.name;
        categoryWrites++;revision=`qa-category-${categoryWrites}`;
        return {ok:true,json:async()=>({success:true,revision})};
    }
    if (path.endsWith('/category/delete')) {
        const payload=JSON.parse(options.body), index=categories.findIndex(item=>item.name===payload.name);
        assert(index>=0);assert.equal(options.headers['If-Match'],revision);
        const [removed]=categories.splice(index,1);
        for(let i=rows.length-1;i>=0;i--)if(rows[i]._categoryId===removed.id)rows.splice(i,1);
        categoryWrites++;revision=`qa-category-${categoryWrites}`;
        return {ok:true,json:async()=>({success:true,revision})};
    }
    if (path.endsWith('/prompts/upsert')) {
        const payload=JSON.parse(options.body);
        if(options.headers['If-Match']!==revision)return {ok:false,status:409,json:async()=>({error:'revision conflict'})};
        if(payload.mode==='create'){
            const entry=categories.find(item=>item.id===payload.target_category_id);assert(entry);
            rows.push({id:'qa-created-prompt',alias:payload.prompt.alias,prompt:payload.prompt.prompt,_categoryId:entry.id,_categoryName:entry.name});
            entry.prompt_count++;
        }else{
            const row=rows.find(item=>item.id===payload.prompt.id&&item._categoryId===payload.target_category_id);
            assert(row);Object.assign(row,{alias:payload.prompt.alias,prompt:payload.prompt.prompt});
        }
        revision=`qa-rev-${++saved+1}`;
        return {ok:true,json:async()=>({success:true,revision,prompt:payload.prompt})};
    }
    if (path.endsWith('/prompts/toggle_favorite')) {
        const payload=JSON.parse(options.body), row=rows.find(item=>item.id===payload.prompt_id&&item._categoryId===payload.category_id);
        assert(row); assert.equal(options.headers['If-Match'],revision);
        row.favorite=payload.favorite; favoriteWrites++; revision=`qa-fav-${favoriteWrites}`;
        return {ok:true,json:async()=>({success:true,revision})};
    }
    if (path.includes('/library/prompt?')) {
        const params=new URL(`http://local${path}`).searchParams;
        const row=rows.find(item=>item.id===params.get('prompt_id')&&item._categoryId===params.get('category_id'));
        return {ok:!!row,status:row?200:404,json:async()=>({prompt:row,category:{id:row._categoryId,name:row._categoryName},revision})};
    }
    if (path.endsWith('/library/index')) return {ok:true,json:async()=>({categories,last_modified:revision})};
    if (path.endsWith('/library/revision')) return {ok:true,json:async()=>({revision})};
    if (path.includes('/library/prompts?')) {
        pageRequests++;
        const params = new URL(`http://local${path}`).searchParams;
        const query = (params.get('q') || '').toLowerCase();
        const categoryId = params.get('category_id') || '';
        const all = rows.filter(row => (!categoryId || row._categoryId===categoryId) &&
            (!query || [row.alias,row.prompt].some(value=>value.toLowerCase().includes(query))));
        const offset = Number(params.get('offset')), limit = Number(params.get('limit'));
        return {ok:true,json:async()=>({items:all.slice(offset,offset+limit),total:all.length,
            offset,limit,has_more:offset+limit<all.length,last_modified:revision})};
    }
    throw new Error(`unexpected request: ${path}`);
};
const widget = {name:'selected_prompts',value:'blue sky'};
let loadCalls=0;
const node = {id:7,selectedCategory:'',widgets:[widget],
    properties:{selectedPrompts:'{"QA 分类 1":["old"]}',promptWeights:'{"QA 分类 1":{"old":1.2}}'},
    loadPrompt({prompt}){loadCalls++;widget.value=prompt;}};
const graph = {getNodeById:id=>id===7?node:null}; node.graph=graph;
const open = () => module.namespace.openPagedPromptLibrary({node,request,currentGraph:()=>graph,manageModal:()=>()=>{}});
const settle = async () => {await new Promise(resolve=>setTimeout(resolve,20));};
await open();
const search = document.querySelector('.ps-paged-toolbar input');
search.value='QA193'; search.dispatchEvent(new Event('input',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,290));
assert.equal(document.querySelectorAll('.ps-paged-row').length,80);
document.querySelector('.ps-paged-toolbar button').click();
assert.match(document.querySelector('.ps-paged-toolbar button:last-child').textContent,/80/);
document.querySelector('.ps-paged-footer button').click(); await settle();
assert.equal(document.querySelectorAll('.ps-paged-row').length,160);
assert.equal(document.querySelectorAll('.ps-paged-row input:checked').length,80);
document.querySelector('.ps-paged-toolbar button').click();
assert.equal(document.querySelectorAll('.ps-paged-row input:checked').length,160);
document.querySelector('.ps-paged-footer button').click(); await settle();
assert.equal(document.querySelectorAll('.ps-paged-row').length,193);
assert.equal(document.querySelectorAll('.ps-paged-row input:checked').length,160);
assert.equal(document.querySelector('.ps-paged-count').textContent,'已显示 193 / 193 条');
assert.equal(new Set([...document.querySelectorAll('.ps-paged-row')].map(row=>row.dataset.promptId)).size,193);
document.querySelector('.ps-paged-toolbar button:last-child').click();
assert.equal(document.querySelectorAll('.ps-paged-row input:checked').length,0);
document.querySelector('.ps-paged-row input').click();
search.value='no-match'; search.dispatchEvent(new Event('input',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,290));
assert.equal(document.querySelectorAll('.ps-paged-row').length,0);
assert.match(document.querySelector('.ps-paged-toolbar button:last-child').textContent,/1/);
search.value='QA193'; search.dispatchEvent(new Event('input',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,290));
assert.equal(document.querySelectorAll('.ps-paged-row input:checked').length,1);
const apply = document.querySelector('.ps-paged-primary');
apply.click(); assert.equal(widget.value,'blue sky'); assert.equal(apply.textContent,'确认载入');
apply.click(); await settle(); assert.equal(widget.value,rows[0].prompt);
assert.equal(node.properties.selectedPrompts,'{}');
assert.equal(node.properties.promptWeights,'{}');
document.querySelector('.ps-paged-footer button:last-child').click();
assert.equal(widget.value,'blue sky');
assert.equal(node.properties.selectedPrompts,'{"QA 分类 1":["old"]}');
assert.equal(node.properties.promptWeights,'{"QA 分类 1":{"old":1.2}}');
assert.equal(fullReads,0);
document.querySelector('.ps-paged-row button:last-child').click(); await settle();
assert.equal(document.querySelector('.ps-paged-editor-panel')?.getAttribute('class'),'ps-paged-editor-panel');
document.querySelector('.ps-paged-editor-panel input').value='QA193 renamed';
document.querySelector('.ps-paged-editor-panel textarea').value='QA193 blue_sky revised';
document.querySelector('.ps-paged-editor-actions button:last-child').click(); await settle();
assert.equal(rows[0].alias,'QA193 renamed');
assert.equal(rows[1].alias,fixture[1].text);
assert.equal(saved,1);
document.querySelector('.ps-paged-row button').click(); await settle();
assert.equal(rows[0].favorite,true);
assert.equal(rows[1].favorite,undefined);
assert.equal(favoriteWrites,1);
document.querySelector('.ps-paged-row button:last-child').click(); await settle();
document.querySelector('.ps-paged-editor-panel textarea').value='unsaved conflict draft';
revision='qa-external';
document.querySelector('.ps-paged-editor-actions button:last-child').click(); await settle();
assert.equal(document.querySelector('.ps-paged-editor-panel textarea').value,'unsaved conflict draft');
assert.match(document.querySelector('.ps-paged-editor-panel .ps-paged-status').textContent,/草稿仍在/);
assert.equal(saved,1);
document.querySelector('.ps-paged-editor-actions button').click();
search.value='';search.dispatchEvent(new Event('input',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,290));
document.querySelector('.ps-paged-header button').click();
document.querySelector('.ps-paged-category-name').value='QA 临时分类';
document.querySelector('.ps-paged-editor-actions button').click(); await settle();
assert(categories.some(item=>item.id==='qa-created'&&item.name==='QA 临时分类'));
assert.equal(document.querySelector('.ps-paged-editor'),null);
document.querySelector('.ps-paged-header button').click();
document.querySelector('.ps-paged-new-alias').value='QA New Item';
document.querySelector('.ps-paged-new-body').value='QA193 new body';
document.querySelector('.ps-paged-editor-actions .ps-paged-primary').click(); await settle();
assert(rows.some(item=>item.id==='qa-created-prompt'&&item._categoryId==='qa-created'));
document.querySelector('.ps-paged-header button').click();
document.querySelector('.ps-paged-category-name').value='QA 临时分类改名';
document.querySelectorAll('.ps-paged-editor-actions')[0].querySelectorAll('button')[1].click(); await settle();
assert(categories.some(item=>item.id==='qa-created'&&item.name==='QA 临时分类改名'));
document.querySelector('.ps-paged-header button').click();
const deleteButton=document.querySelectorAll('.ps-paged-editor-actions')[0].querySelectorAll('button')[2];
deleteButton.click();assert.equal(categoryWrites,2);
document.querySelector('.ps-paged-confirm-name').value='QA 临时分类改名';
deleteButton.click();await settle();
assert.equal(categoryWrites,3);
assert(!categories.some(item=>item.id==='qa-created'));
assert(!rows.some(item=>item.id==='qa-created-prompt'));
assert.equal(fullReads,0);
assert(pageRequests>=4);
document.querySelector('.ps-paged-header button:last-child').click();
let indexFailures=1,pageFailures=1,slowPending=null,delayedPromptRead=null,holdPromptRead=false;
const flakyRequest=(path,options)=>{
    if(path.endsWith('/library/index')&&indexFailures-- > 0)return Promise.resolve({ok:false,status:503,json:async()=>({})});
    if(path.includes('/library/prompt?')&&holdPromptRead)return new Promise(resolve=>{delayedPromptRead=resolve;});
    if(path.includes('/library/prompts?')&&new URL(`http://local${path}`).searchParams.get('q')==='slow')
        return new Promise(resolve=>{slowPending=resolve;});
    if(path.includes('/library/prompts?')&&pageFailures-- > 0)return Promise.resolve({ok:false,status:503,json:async()=>({})});
    return request(path,options);
};
await module.namespace.openPagedPromptLibrary({node,request:flakyRequest,currentGraph:()=>graph,manageModal:()=>()=>{}});
const retry=document.querySelector('.ps-paged-footer button:nth-child(4)');
assert.equal(retry.textContent,'重试读取');assert.equal(retry.hidden,false);
document.querySelector('.ps-paged-header button').click();
assert.equal(document.querySelector('.ps-paged-editor'),null);
assert.match(document.querySelector('.ps-paged-status').textContent,/尚未就绪/);
retry.click();await settle();assert.equal(retry.hidden,false);
retry.click();await settle();assert.equal(retry.hidden,true);
assert.equal(document.querySelectorAll('.ps-paged-row').length,80);
document.querySelector('.ps-paged-row input').click();
widget.value=rows[0].prompt;
const previousLoads=loadCalls;
document.querySelector('.ps-paged-primary').click();await settle();
assert.equal(loadCalls,previousLoads);
assert.match(document.querySelector('.ps-paged-status').textContent,/无需重复载入/);
document.querySelector('.ps-paged-row button:last-child').click();await settle();
document.querySelector('.ps-paged-editor-panel textarea').value='QA193 saved despite failed refresh';
pageFailures=1;
document.querySelector('.ps-paged-editor-actions button:last-child').click();await settle();
assert.equal(saved,3);
assert.equal(document.querySelector('.ps-paged-editor'),null);
assert.match(document.querySelector('.ps-paged-status').textContent,/已保存，但列表刷新失败/);
assert.equal(retry.hidden,false);
retry.click();await settle();assert.equal(retry.hidden,true);
const laterSearch=document.querySelector('.ps-paged-toolbar input');
laterSearch.value='slow';laterSearch.dispatchEvent(new Event('input',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,290));assert(slowPending);
laterSearch.value='QA193';laterSearch.dispatchEvent(new Event('input',{bubbles:true}));
assert.equal(document.querySelector('.ps-paged-list').inert,true);
slowPending({ok:true,json:async()=>({items:rows.slice(0,80),total:80,offset:0,last_modified:revision})});
await settle();assert.equal(document.querySelector('.ps-paged-list').inert,true);
await new Promise(resolve=>setTimeout(resolve,290));
assert.equal(document.querySelector('.ps-paged-list').inert,false);
assert.equal(document.querySelectorAll('.ps-paged-row').length,80);
assert.match(document.querySelector('.ps-paged-row strong').textContent,/QA193/);
document.querySelector('.ps-paged-header button').click();
document.querySelector('.ps-paged-category-name').value='QA Refresh Retry';
indexFailures=1;
document.querySelector('.ps-paged-editor-actions button').click();await settle();
assert.equal(categoryWrites,4);
assert.equal(document.querySelector('.ps-paged-editor'),null);
assert.match(document.querySelector('.ps-paged-status').textContent,/已保存，但列表刷新失败/);
assert.equal(retry.hidden,false);
retry.click();await settle();
assert.equal(retry.hidden,true);
assert.equal(document.querySelector('.ps-paged-toolbar select').value,'qa-created');
document.querySelector('.ps-paged-toolbar select').value='';
document.querySelector('.ps-paged-toolbar select').dispatchEvent(new Event('change',{bubbles:true}));await settle();
holdPromptRead=true;
const staleEdit=document.querySelector('.ps-paged-row button:last-child');staleEdit.click();
assert(delayedPromptRead);assert.equal(staleEdit.disabled,true);
laterSearch.value='no-match';laterSearch.dispatchEvent(new Event('input',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,290));
holdPromptRead=false;
delayedPromptRead(await request('/prompt_selector/library/prompt?prompt_id='+encodeURIComponent(rows[0].id)+'&category_id='+encodeURIComponent(rows[0]._categoryId)));
await settle();assert.equal(document.querySelector('.ps-paged-editor'),null);
assert.match(document.querySelector('.ps-paged-status').textContent,/列表已变化/);
console.log(JSON.stringify({passed:true,counts:[80,160,193],pageRequests,fullReads,saved,favoriteWrites,categoryWrites,checks:['visible-only selection','selection persists across search','unique category/id identity','preview before write','undo','exact-source edit and favorite','revision conflict keeps draft','lightweight category create/rename/delete and prompt create','index and page read retry','unchanged target avoids duplicate load','saved write remains explicit when page refresh fails','slow stale search stays inert and cannot repaint fast results','saved category retries failed index without re-submitting','stale item read cannot open an editor over a new search']}));
dom.window.close();
