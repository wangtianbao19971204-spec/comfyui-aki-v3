import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {createHash} from 'node:crypto';
import {JSDOM} from '../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const pluginRoot=path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench');
const scriptRoot=path.join(pluginRoot,'modules/comfyui-anima-tools/js');
const reportRoot=path.resolve('benchmark_reports/2026-09-30_next_workbench');
const dom=new JSDOM('<textarea></textarea><main></main>',{url:'http://127.0.0.1:8188/',runScripts:'outside-only'});
const context=dom.getInternalVMContext(),doc=dom.window.document;
const files={
    modal:path.join(pluginRoot,'web/modal_focus.js'),
    target:path.join(pluginRoot,'web/prompt_target.js'),
    identity:path.join(scriptRoot,'anima_prompt_identity.js'),
    selectors:path.join(scriptRoot,'anima_selector_ui.js'),
};
const modules=new Map();
async function load(name){
    if(modules.has(name))return modules.get(name);
    const module=new vm.SourceTextModule(fs.readFileSync(files[name],'utf8'),{context,identifier:files[name]});modules.set(name,module);
    await module.link(spec=>{
        if(spec.endsWith('modal_focus.js'))return load('modal');
        if(spec.endsWith('prompt_target.js'))return load('target');
        if(spec.endsWith('anima_prompt_identity.js'))return load('identity');
        if(spec.endsWith('ui_identity.js'))return new vm.SyntheticModule(['mountFunctionCard'],function(){this.setExport('mountFunctionCard',()=>{throw Error('unused UI identity');});},{context});
        throw Error('unexpected dependency '+spec);
    });
    return module;
}
const selectorModule=await load('selectors'),identityModule=await load('identity');
await selectorModule.evaluate();await identityModule.evaluate();
const original='forest, sunlight',input=doc.querySelector('textarea');input.value=original;
const widget={name:'pose_tags',value:original,inputEl:input};
const node={id:7,mode:0,widgets:[widget],inputs:[]};
let commits=0;
const graph={id:'qa-shared-graph',extra:{uap_workbench:{activeBranch:'a',branches:[{id:'a',nodeIds:[7]},{id:'b',nodeIds:[7]}]}},
    getNodeById:id=>id===7?node:null,beforeChange(){commits++;},afterChange(){},setDirtyCanvas(){}};
node.graph=graph;const app={graph,canvas:{}};
const frozenTarget=identityModule.namespace.capturePromptTarget(node,widget,()=>app.graph);
const controls=selectorModule.namespace.mountSelectorInsertionActions(doc.querySelector('main'),{app,node,widget,
    resolveText:()=>{frozenTarget();return 'standing';},kind:'pose',getSelectedItems:()=>[]});
await controls.apply.onclick();
const applied=widget.value;assert.equal(applied,original+', standing');assert.equal(controls.undo.disabled,false);assert.equal(commits,1);
graph.extra.uap_workbench.activeBranch='b';
let captureBlocked=false;try{frozenTarget();}catch{captureBlocked=true;}
assert.equal(captureBlocked,true);
await controls.apply.onclick();
const status=()=>doc.querySelector('.anima-selector-insertion-status').textContent;
const applyStatus=status();assert.equal(widget.value,applied);assert.equal(commits,1);
controls.undo.onclick();
const afterUndo=widget.value,undoStatus=status(),undoCommits=commits-1;
const passed=afterUndo===applied&&undoCommits===0&&controls.undo.disabled&&/无法撤销旧操作/.test(undoStatus);
const cases=[];
async function undoCase(name,{kind='pose',workbench=true,mutate,reject=true}={}){
    const field={name:kind+'_tags',value:original},targetNode={id:17,mode:0,widgets:[field],inputs:[]};
    let transactions=0;
    const targetGraph={id:'qa-'+name,extra:workbench?{uap_workbench:{activeBranch:'a',branches:[{id:'a',nodeIds:[17]},{id:'b',nodeIds:[17]}]}}:{},
        getNodeById:id=>id===17?targetNode:null,beforeChange(){transactions++;},afterChange(){},setDirtyCanvas(){}};
    targetNode.graph=targetGraph;const targetApp={graph:targetGraph,canvas:{}};
    const frozen=identityModule.namespace.capturePromptTarget(targetNode,field,()=>targetApp.graph);
    const host=doc.body.appendChild(doc.createElement('main'));
    const surface=selectorModule.namespace.mountSelectorInsertionActions(host,{app:targetApp,node:targetNode,widget:field,
        resolveText:()=>{frozen();return 'standing';},kind,getSelectedItems:()=>[]});
    await surface.apply.onclick();assert.equal(transactions,1);assert.equal(field.value,applied);
    mutate?.({app:targetApp,graph:targetGraph,node:targetNode,widget:field});
    if(reject){await surface.apply.onclick();assert.equal(transactions,1);assert.equal(field.value,applied);}
    surface.undo.onclick();
    assert.equal(field.value,reject?applied:original);assert.equal(transactions,reject?1:2);
    assert.equal(surface.undo.disabled,true);
    const message=host.querySelector('.anima-selector-insertion-status').textContent;
    assert.match(message,reject?/无法撤销旧操作/:/已撤销本次写入/);
    cases.push({name,kind,rejected:reject,undoWrites:transactions-1,passed:true,message});surface.dispose();host.remove();
}
for(const kind of ['character','clothing','pose','background','artist','style_quality']){
    await undoCase(kind+'_shared_node_other_branch',{kind,mutate:({graph})=>{graph.extra.uap_workbench.activeBranch='b';}});
    await undoCase(kind+'_normal_same_branch',{kind,reject:false});
}
await undoCase('other_branch_excludes_node',{mutate:({graph})=>{graph.extra.uap_workbench.branches[1].nodeIds=[];graph.extra.uap_workbench.activeBranch='b';}});
await undoCase('workbench_removed_after_apply',{mutate:({graph})=>{delete graph.extra.uap_workbench;}});
await undoCase('workbench_added_after_apply',{workbench:false,mutate:({graph})=>{graph.extra.uap_workbench={activeBranch:'new',branches:[{id:'new',nodeIds:[17]}]};}});
await undoCase('normal_without_workbench',{workbench:false,reject:false});
await undoCase('workflow_replaced',{mutate:({app,graph})=>{app.graph={...graph};}});
await undoCase('graph_id_changed',{mutate:({graph})=>{graph.id='qa-replacement';}});
await undoCase('node_deleted',{mutate:({graph})=>{graph.getNodeById=()=>null;}});
await undoCase('widget_replaced',{mutate:({node})=>{node.widgets=[];}});
await undoCase('widget_connected',{mutate:({node,widget})=>{node.inputs=[{name:widget.name,link:123}];}});
await undoCase('node_muted',{mutate:({node})=>{node.mode=2;}});
const receipt={passed,reproducedUnsafeUndo:!passed,scenario:'one physical node belongs to both branches; switch active branch after applying through its original selector',
    expected:{captureBlocked:true,oldApplyWrites:0,oldUndoWrites:0,targetAfterUndo:applied,undoDisabled:true},
    actual:{captureBlocked,oldApplyWrites:0,oldUndoWrites:undoCommits,targetAfterUndo:afterUndo,undoDisabled:controls.undo.disabled,applyStatus,undoStatus},
    cases,
    hashes:Object.fromEntries(Object.entries(files).map(([name,file])=>[name,{path:path.relative(process.cwd(),file),sha256:createHash('sha256').update(fs.readFileSync(file)).digest('hex')}])),
};
const receiptName=passed?'selector_branch_undo_pass_2026-10-01.json':'selector_branch_undo_failure_2026-10-01.json';
const receiptPath=path.join(reportRoot,receiptName);
if(!passed&&fs.existsSync(receiptPath))assert.equal(JSON.parse(fs.readFileSync(receiptPath,'utf8')).reproducedUnsafeUndo,true,'existing failure receipt must stay intact');
else fs.writeFileSync(receiptPath,JSON.stringify(receipt,null,2));
console.log(JSON.stringify(receipt,null,2));
controls.dispose();dom.window.close();
assert.equal(passed,true,'old selector undo must not write after the frozen branch changes');
