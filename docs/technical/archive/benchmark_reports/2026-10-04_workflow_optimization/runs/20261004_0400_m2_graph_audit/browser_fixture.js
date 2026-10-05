(async()=>{
    const {mountPromptInspector}=await import(window.__m2Module);
    window.__m2Probe?.dispose();document.getElementById('m2-neutral-audit')?.remove();
    const host=document.createElement('aside');host.id='m2-neutral-audit';
    host.style.cssText='position:fixed;z-index:999999;inset:90px 50px 30px;background:#222731;color:#eef1f6;padding:24px;overflow:auto;border:2px solid #889dc5;border-radius:12px';
    document.body.append(host);
    const title=document.createElement('h2');title.textContent='M2 中性隔离验收 · 模型来源';host.append(title);
    const api={
        1:{class_type:'UNETLoader',inputs:{unet_name:'sampler-model.safetensors'}},
        2:{class_type:'CheckpointLoaderSimple',inputs:{ckpt_name:'encoder-associated.safetensors'}},
        3:{class_type:'CLIPTextEncode',inputs:{clip:['2',1],text:'neutral landscape'}},
        4:{class_type:'KSampler',inputs:{model:['1',0],positive:['3',0],negative:['3',0],cfg:7}},
        5:{class_type:'DazzleSwitch',inputs:{mode:'priority',input_01:['1',0]}}
    };
    const branch={id:'neutral',nodeIds:[1,2,3,4,5]};
    const nodes=Object.fromEntries(Object.entries(api).map(([id,n])=>[id,{id,type:n.class_type,mode:0,inputs:[],widgets:Object.entries(n.inputs).map(([name,value])=>({name,value}))}]));
    const graph={extra:{uap_workbench:{activeBranch:branch.id}},links:{},getNodeById:id=>nodes[id]};
    const testApp={graph,graphToPrompt:async()=>({output:api})};
    const probe=mountPromptInspector(host,testApp,branch,()=>true);
    window.__m2Probe={...probe,api,nodes,graph,host,check:async()=>host.querySelector('.desk-prompt-inspector button').onclick()};
    await __m2Probe.check();return host.innerText;
})()
