const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const cp=require('node:child_process');
const run=__dirname,root=path.join(run,'candidate');
const web=path.join(root,'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web');
const read=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const wf=read(path.join(root,'ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json'));
let checks=0;const check=(condition,message)=>{assert(condition,message);checks++;};
const load=(name,bindings={})=>{const context=vm.createContext({...bindings,Set,Map,WeakSet,WeakMap,console});vm.runInContext(fs.readFileSync(path.join(web,name),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,''),context,{filename:name});return context;};
const activity=load('task_activity.js');
const runtime=load('runtime_controls.js',{taskPlan:activity.taskPlan,commitWidget(){}});
const targets=load('resource_actions.js',{isEnabledTarget:(app,node)=>node.mode===0,isWritableTarget:(app,node,w)=>!node.inputs?.some(p=>p.name===w.name&&p.link!=null)});
const schema=read(path.join(run,'object_info.json'));
function fakeNode(node){
    let names=[];const meta=schema[node.type]?.input||{};
    for(const group of ['required','optional'])for(const [name,spec] of Object.entries(meta[group]||{})){
        if((Array.isArray(spec[0])||['STRING','FLOAT','INT','BOOLEAN'].includes(spec[0]))&&!spec[1]?.forceInput){names.push(name);if(name==='seed')names.push('control_after_generate');}
    }
    return {...structuredClone(node),widgets:names.map((name,i)=>({name,value:node.widgets_values?.[i]}))};
}
function branchGraph(id){
    const nodes=wf.nodes.map(fakeNode),config=structuredClone(wf.extra.uap_workbench);
    config.activeBranch=id;const selected=config.branches.find(b=>b.id===id);
    for(const node of nodes)node.mode=selected.nodeIds.includes(node.id)?selected.modes[String(node.id)]??0:2;
    const graph={_nodes:nodes,extra:{...wf.extra,uap_workbench:config},links:Object.fromEntries(wf.links.map(l=>[l[0],{id:l[0],origin_id:l[1],origin_slot:l[2],target_id:l[3],target_slot:l[4]}])),getNodeById:id=>nodes.find(n=>String(n.id)===String(id))};
    return {graph,branch:selected,nodes:nodes.filter(n=>selected.nodeIds.includes(n.id))};
}
for(const branch of wf.extra.uap_workbench.branches){
    const current=branchGraph(branch.id),app={graph:current.graph};
    check(runtime.workflowGuardIssue(current.nodes,current.branch,wf.extra.uap_model_contracts)==='',branch.id+' default guard');
    const plan=activity.taskPlan(app,'generate');
    check(!plan.reason&&plan.queueNodeIds.length>0,branch.id+' generation plan');
    check(plan.targets.every(item=>['SaveImage','PreviewImage','VRAMCleanup'].includes(item.node.type)),branch.id+' scoped outputs');
}
const a1=branchGraph('a1'),model=a1.nodes.find(n=>n.type==='UNETLoader'),clip=a1.nodes.find(n=>n.type==='CLIPLoader'),vae=a1.nodes.find(n=>n.type==='VAELoader');
const find=(node,name)=>node.widgets.find(w=>w.name===name);
const originalModel=find(model,'unet_name').value;
for(const [name,record] of Object.entries(wf.extra.uap_model_contracts.models)){
    find(model,'unet_name').value=name;
    const issue=runtime.modelCompatibilityIssue(a1.nodes,a1.branch,wf.extra.uap_model_contracts);
    check((issue==='')===(record.family==='anima'),'header-bound family '+name);
}
find(model,'unet_name').value='unknown.safetensors';check(!!runtime.modelCompatibilityIssue(a1.nodes,a1.branch,wf.extra.uap_model_contracts),'unverified blocked');find(model,'unet_name').value=originalModel;
const originalClip=find(clip,'type').value;find(clip,'type').value='krea2';check(runtime.modelCompatibilityIssue(a1.nodes,a1.branch,wf.extra.uap_model_contracts).includes('type'),'CLIP type guard');find(clip,'type').value=originalClip;
const originalVae=find(vae,'vae_name').value;find(vae,'vae_name').value='qwen_image_2.1_vae_bf16.safetensors';check(!!runtime.modelCompatibilityIssue(a1.nodes,a1.branch,wf.extra.uap_model_contracts),'VAE guard');find(vae,'vae_name').value=originalVae;
const ext=branchGraph('ext07');find(ext.nodes.find(n=>n.type==='UNETLoader'),'unet_name').value='Anima-2.9B/anima29B_v10_bf16.safetensors';check(!!runtime.workflowGuardIssue(ext.nodes,ext.branch,wf.extra.uap_model_contracts),'outpaint cross-family guard');
const bare=[{type:'UNETLoader',mode:0,widgets:[{name:'unet_name',value:'anima29B.safetensors'}]},{type:'AnimaLLLiteApply_sdscripts',mode:0}];check(runtime.workflowGuardIssue(bare).includes('40 层'),'LLLite direct type guard');
for(const id of ['a1','a29','k2','ext04','ext05','ext07']){
    const current=branchGraph(id),items=targets.listPromptTargets({graph:current.graph});
    check(items.some(item=>item.usage==='generation'&&item.direction==='positive'),id+' actual positive target');
    check(items.filter(item=>[1061,1077,1232].includes(item.node.id)).every(item=>item.usage==='draft'),id+' drafts not generation');
    check(items[0]?.usage==='generation',id+' prioritizes actual target');
}
for(const id of ['ext06','ext08','ext09'])check(!targets.listPromptTargets({graph:branchGraph(id).graph}).length,id+' no prompt targets');
async function queueTests(){
    const current=branchGraph('a1'),calls=[],dialogs=[];
    const app={graph:current.graph,queuePrompt:async(...args)=>{calls.push(args);return 'queued';},ui:{dialog:{show:text=>dialogs.push(text)}}};
    runtime.installWorkflowGuard(app);runtime.installWorkflowGuard(app);
    check(await app.queuePrompt(0,1)==='queued','generic queue delegates');
    check(calls.length===1&&calls[0][2].queueNodeIds.join()===activity.taskPlan(app,'generate').queueNodeIds.join(),'generic queue is image task only');
    const comparer=current.nodes.find(node=>node.type==='Image Comparer (rgthree)');comparer.mode=0;
    check(activity.taskPlan(app,'generate').queueNodeIds.includes(String(comparer.id)),'enabled stage comparison retained in image task');comparer.mode=2;
    await app.queuePrompt(0,1,{queueNodeIds:['caption-node'],batchCount:1});check(calls[1][2].queueNodeIds[0]==='caption-node','explicit task targets preserved');
    find(current.nodes.find(n=>n.type==='VAELoader'),'vae_name').value='pixel_space';
    check(await app.queuePrompt(0,1)===false&&calls.length===2&&dialogs.length===1,'reject before submission');
    const other={graph:{extra:{}},queuePrompt:async()=> 'unchanged'};runtime.installWorkflowGuard(other);check(await other.queuePrompt(0,1)==='unchanged','non UAP unaffected');
}
queueTests().then(()=>{
    const jsFiles=[...fs.readdirSync(web).filter(name=>name.endsWith('.js')).map(name=>path.join(web,name)),...['uap_daily_controls.js','uap_workbench.js'].map(name=>path.join(root,'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation',name))];
    for(const file of jsFiles){cp.execFileSync(process.execPath,['--check',file]);checks++;}
    fs.writeFileSync(path.join(run,'unit_results.json'),JSON.stringify({passed:true,checks,scope:'Unit and syntax, not browser or inference'},null,2));
    console.log(JSON.stringify({passed:true,checks}));
}).catch(error=>{console.error(error);process.exitCode=1;});
