const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const web=path.join(__dirname,'../ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web');
const context=vm.createContext({console,window:{unifiedUapNavigation:{activateBranch(id){context.activated=id;}}}});
vm.runInContext(fs.readFileSync(path.join(web,'repair_workflow.js'),'utf8').replace(/^export /gm,''),context);
const choices=context.workflowChoices({branches:[{id:'ext05',label:'精修'},{id:'ext08',label:'2×'},{id:'ext09',label:'4×'}]});
assert.deepEqual(Array.from(choices,c=>c.value),['ext05','@workflow:stocking','ext08','ext09']);
const original=JSON.stringify(choices);
assert.equal(context.workflowChoices({branches:[]}).length,1);
assert.equal(JSON.stringify(choices),original);
const workflow=JSON.parse(fs.readFileSync(path.join(__dirname,'templates/生产扩展_丝袜纹理修复.json'),'utf8'));
assert.deepEqual(workflow.nodes.map(n=>n.type),['StockingTextureStudio','SaveImage','SaveImage','Note']);
assert.equal(workflow.nodes[0].widgets_values[0],'{}');
assert(workflow.nodes[0].inputs.every(i=>i.link==null));
assert.equal(workflow.links.length,2);
for(const link of workflow.links){
    assert(workflow.nodes.find(n=>n.id===link[1]).outputs[link[2]].links.includes(link[0]));
    assert.equal(workflow.nodes.find(n=>n.id===link[3]).inputs[link[4]].link,link[0]);
}
assert.deepEqual(fs.readFileSync(path.join(__dirname,'templates/生产扩展_丝袜纹理修复.json')),
    fs.readFileSync(path.join(__dirname,'../ComfyUI/user/default/workflows/生产扩展_丝袜纹理修复.json')));
vm.runInContext(fs.readFileSync(path.join(web,'task_activity.js'),'utf8')
    .replace(/^import .*;\r?$/gm,'').replace(/^export /gm,''),context);
const nodes=workflow.nodes.filter(n=>n.type!=='Note').map(n=>({...n,widgets:[{name:'project_json',value:'{}'}]}));
const graph={_nodes:nodes,extra:workflow.extra,getNodeById:id=>nodes.find(n=>n.id===id)};
const app={graph};
let plan=context.taskPlan(app,'generate');
assert.match(plan.reason,/应用到节点/);assert.equal(plan.label,'开始纹理修复');
nodes[0].widgets[0].value=JSON.stringify({asset:'saved.png'});
plan=context.taskPlan(app,'generate');
assert.equal(plan.reason,'');assert.deepEqual(Array.from(plan.queueNodeIds),['2','3']);
(async()=>{
    let opened=null;
    const state={marker:'unsaved original',extra:{uap_workbench:{branches:[{id:'ext08'}]}}};
    const persisted={path:'repair',isLoaded:true,activeState:{nodes:['repair']}},main={path:'main',isLoaded:true,activeState:{nodes:['main']}};
    const app={graph:state,async loadGraphData(data,clean,restore,w){
        assert.equal(JSON.stringify(data),JSON.stringify(w.activeState));assert.notEqual(data,w.activeState);
        assert.equal(clean,true);assert.equal(restore,true);opened=w;
    },extensionManager:{workflow:{
        async syncWorkflows(){},getWorkflowByPath:p=>p.includes('丝袜')?persisted:main,
        async openWorkflow(){throw new Error('Store-only tab switches must never be used');}
    }}};
    assert.equal(await context.openWorkflowChoice(app,'@workflow:stocking'),true);
    assert.equal(opened,persisted);assert.equal(app.graph,state);
    assert.equal(state.marker,'unsaved original');
    await context.openWorkflowChoice(app,'@main:ext08');assert.equal(context.activated,'ext08');
    app.extensionManager.workflow.getWorkflowByPath=()=>null;
    await assert.rejects(()=>context.openWorkflowChoice(app,'@workflow:stocking'),/找不到/);
    assert.equal(app.graph,state);
    app.extensionManager.workflow.syncWorkflows=async()=>{app.graph={};};
    await assert.rejects(()=>context.openWorkflowChoice(app,'@workflow:stocking'),/已变化/);
    console.log('PASS: independent graph, dual PNG outputs, clean template, peer order, native tab opening, unsaved graph preservation, stale navigation rejection, repair readiness and target isolation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
