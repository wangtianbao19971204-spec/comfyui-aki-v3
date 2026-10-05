import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {JSDOM} from 'file:///G:/ComfyUI-aki-v3/benchmark_reports/2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const liveRoot='G:/ComfyUI-aki-v3/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench';
const sourceRoot=process.env.WORKBENCH_SOURCE_ROOT||liveRoot;
const readSource=filename=>{
    const candidate=path.join(sourceRoot,path.relative(liveRoot,filename));
    return fs.readFileSync(fs.existsSync(candidate)?candidate:filename,'utf8');
};
const dom=new JSDOM('',{url:'http://127.0.0.1:8190/',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,d=w.document,context=dom.getInternalVMContext();
const requests=[],views=[],checks=[];
const topics={identity:'角色',artist_style:'画师',clothing_accessory:'服装',pose_action:'动作',background_environment:'背景',style_quality:'画风与质量'};
const categories=[{id:'old-source',name:'旧来源',prompt_count:1}];
w.fetch=async(url,options={})=>{
    const parsed=new URL(String(url),w.location.href);
    requests.push({url:parsed,method:options.method||'GET'});
    const data=parsed.pathname.endsWith('/library/index')?{
        version:3,settings:{},total_prompts:0,categories,semantic_classes:topics,
        semantic_subcategories:{},selector_groups:{resource:[]},selector_class_kinds:{},
        filter_pool:{theme:topics,subcategory:{},subcategory_values:{},refinements:{}},
    }:parsed.pathname.includes('/collections/')?{groups:[],items:[]}:{items:[],total:0,groups:[],collections:[],revision:'fixture'};
    return {ok:true,status:200,headers:{get:()=> '"fixture"'},json:async()=>data,text:async()=>''};
};
w.eval(readSource(path.join(liveRoot,'modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/dist/javascript/zz_tb_shared_preset_manager.js')));
d.addEventListener('shared-library-view',event=>views.push(event.detail));
const fields=['character_tags','artist_tags','clothing_tags','pose_tags','background_tags','style_quality_tags'];
const nodes=fields.map((name,index)=>({id:index+1,title:'正向验收 '+name,mode:0,widgets:[{name,value:'forest, sunlight',callback(){throw new Error('Unexpected prompt write');}}]}));
const graph={id:'fixture',_nodes:nodes,getNodeById(id){return this._nodes.find(node=>node.id===id);}};
for(const node of nodes)node.graph=graph;
let extension;
const app={graph,canvas:{},ui:{settings:{show(){}}},registerExtension(value){extension=value;}};
const modules=new Map();
async function load(filename){
    if(modules.has(filename))return modules.get(filename);
    if(filename==='app'||filename==='api'){
        const value=filename==='app'?app:{getQueue:async()=>({Running:[],Pending:[]}),addEventListener(){},removeEventListener(){}};
        const module=new vm.SyntheticModule([filename],function(){this.setExport(filename,value);},{context});
        modules.set(filename,module);return module;
    }
    const module=new vm.SourceTextModule(readSource(filename),{context,identifier:filename});
    modules.set(filename,module);
    await module.link(spec=>spec.endsWith('/scripts/app.js')?load('app'):spec.endsWith('/scripts/api.js')?load('api'):load(path.resolve(path.dirname(filename),spec)));
    return module;
}
const lastPage=()=>requests.findLast(item=>item.url.pathname.endsWith('/library/prompts')).url.searchParams;
const themes=()=>lastPage().getAll('filter').filter(value=>value.startsWith('theme:'));
const click=async key=>{
    const button=d.querySelector(`[data-uw="${key}"]`);assert(button,key);
    await button.onclick();
};
const toggleMode=async()=>{
    const button=[...d.querySelectorAll('.tb-spm-pool-chosen button')].find(item=>item.textContent.startsWith('同组：'));
    assert(button,'pool join mode');button.onclick();
    await new Promise(resolve=>setTimeout(resolve,0));
    await new Promise(resolve=>setTimeout(resolve,0));
};
let shell;
try{
    await load(path.join(liveRoot,'web/modal_focus.js'));
    await load(path.join(liveRoot,'web/prompt_target.js'));
    const module=await load(path.join(liveRoot,'web/workbench_shell.js'));
    await module.evaluate();await extension.setup();
    shell=await module.namespace.openWorkbench({page:'library'});
    await click('theme-identity');await click('theme-artist_style');
    assert.deepEqual(themes(),['theme:identity','theme:artist_style']);
    assert.equal(lastPage().get('filter_mode'),null);
    checks.push('ordinary sidebar accumulates distinct themes');
    await toggleMode();
    assert.equal(lastPage().get('filter_mode'),'all');
    assert.deepEqual(themes(),['theme:identity','theme:artist_style']);
    checks.push('ordinary all mode changes join semantics without replacing themes');
    assert(shell.close());
    shell=await module.namespace.openWorkbench({page:'library'});
    assert.deepEqual(themes(),['theme:identity','theme:artist_style']);
    assert.equal(lastPage().get('filter_mode'),'all');
    checks.push('ordinary workbench close and reopen retains the existing pool');
    await toggleMode();
    assert.equal(lastPage().get('filter_mode'),null);
    assert.deepEqual(themes(),['theme:identity','theme:artist_style']);
    checks.push('ordinary any mode remains selectable after reopening');

    const order=Object.keys(topics);
    for(let index=0;index<order.length;index++){
        const topic=order[index],node=nodes[index];
        // Feed the shell the same source/query state it receives from the real library.
        shell.root.dispatchEvent(new w.CustomEvent('shared-library-view',{bubbles:true,detail:{theme:views.at(-1).theme,selectedThemes:views.at(-1).selectedThemes,themes:Object.entries(topics),source:'old-source',subcategory:'old-subcategory',collection:'old-collection',query:'old query',view:'all'}}));
        d.querySelector('[aria-label="跨来源搜索资料、Tag 和模型"]').value='old header query';
        const opts={page:'library',type:'prompts',theme:topic,view:'all',reset:true,
            target:{node,widget:node.widgets[0],direction:'positive',label:node.title},
            selector:{node,section:fields[index].slice(0,-5),label:topics[topic],native:async()=>{}}};
        await shell.open(opts);
        assert.deepEqual(themes(),['theme:'+topic]);
        assert.equal(lastPage().get('q'),null);
        assert.equal(lastPage().get('category_id'),null);
        assert.equal(lastPage().get('collection'),null);
        assert.equal(d.querySelector('[aria-label="跨来源搜索资料、Tag 和模型"]').value,'');
        assert.deepEqual([...views.at(-1).selectedThemes],[topic]);
        checks.push(topic+' explicit node entry replaces old scope and clears source/query');
        if(index===1){
            await shell.open(opts);
            assert.deepEqual(themes(),['theme:'+topic]);
            assert.deepEqual([...views.at(-1).selectedThemes],[topic]);
            checks.push('same B entry after clearing still restores B exactly once');
        }
        assert(shell.close());shell=null;
        if(index<order.length-1)shell=await module.namespace.openWorkbench({page:'library'});
    }

    shell=await module.namespace.openWorkbench({page:'library'});
    await click('theme-identity');
    assert.deepEqual(themes(),['theme:style_quality','theme:identity']);
    await click('theme-identity');
    assert.deepEqual(themes(),['theme:style_quality']);
    checks.push('ordinary sidebar still toggles one theme without clearing others');
    await click('all');assert.deepEqual(themes(),[]);
    checks.push('explicit all action clears the pool');
    await w.tbOpenSharedPresetManager({mount:d.querySelector('.uw-library-host'),view:'all',semanticClass:'identity',categoryId:'old-source',query:'kept query',clearPool:true});
    assert.deepEqual(themes(),['theme:identity']);
    assert.equal(lastPage().get('category_id'),'old-source');
    assert.equal(lastPage().get('q'),'kept query');
    checks.push('clearPool resets pool only; caller-specified source and query remain valid');
    assert(requests.every(item=>item.method==='GET'));
    assert(nodes.every(node=>node.widgets[0].value==='forest, sunlight'));
    checks.push('fixture makes no library mutations, prompt writes or queue submissions');
    console.log(JSON.stringify({passed:true,count:checks.length,checks},null,2));
}finally{shell?.close();dom.window.close();}
