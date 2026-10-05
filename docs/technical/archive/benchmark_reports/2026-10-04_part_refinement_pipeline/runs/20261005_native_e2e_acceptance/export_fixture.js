(async()=>{
    const {app}=await import('/scripts/app.js');
    const {taskPlan}=await import('/extensions/ComfyUI-Unified-Prompt-Workbench/task_activity.js');
    const {workflowGuardIssue}=await import('/extensions/ComfyUI-Unified-Prompt-Workbench/runtime_controls.js');
    const response=await fetch('/userdata/'+encodeURIComponent('workflows/UAP统一生产工作台_v2.json'),{cache:'no-store'});
    const bytes=await response.arrayBuffer();
    const sourceSha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(n=>n.toString(16).padStart(2,'0')).join('');
    if(sourceSha!=='c00cab75d4c4264376b355d735de87fa96077c0e23889252bc763de1921e6f2a')throw Error('Published workflow changed');
    const source=JSON.parse(new TextDecoder().decode(bytes));
    const positive='Anime-style full-body illustration of one adult man, 30 years old, short dark hair, wearing a loose blue athletic T-shirt and gray knee-length sports shorts. Standing barefoot on a pale indoor gym floor, both feet completely visible, both open hands visible at his sides, feet apart, relaxed upright pose. Complete figure from head to toes with space below the feet, front view, clear face and eyes, clean line art, soft daylight, plain light gray background.';
    const negative='text, watermark, blurry, cropped, out of frame, duplicate person, nudity';
    const edit='Change the blue T-shirt to a dark green T-shirt. Keep the same adult man, face, pose, gray knee-length shorts, bare feet and pale indoor gym background. Preserve the illustration style.';
    const neutralImage='_codex_qa/live_acceptance_20261004/k2_full_2026100402/00_base_00001_.png [output]';
    window.__nativeAcceptanceApp=app;
    window.__exportNativeCase=async function(caseName){
        const full=caseName.endsWith('_full'),branchId=caseName.split('_')[0],wf=structuredClone(source);
        const config=wf.extra.uap_workbench,b=config.branches.find(b=>b.id===branchId);
        config.activeBranch=config.viewBranch=branchId;config.stage=b.stages[0].id;
        for(const branch of config.branches)for(const id of branch.nodeIds){const n=wf.nodes.find(n=>String(n.id)===String(id));if(n)n.mode=branch.id===branchId?(branch.modes[id]??0):2;}
        await app.loadGraphData(wf,true,false);
        const nodes=b.nodeIds.map(id=>app.graph.getNodeById(id)).filter(Boolean);
        const changes=[];
        function set(node,name,value){const w=node.widgets?.find(w=>w.name===name);if(w&&w.value!==value){changes.push({id:String(node.id),type:node.type,field:name,value});w.value=value;}}
        function setup(node){
            if(['WeiLinPromptUI','CLIPTextEncode','CR Prompt Text','Krea2EditGroundedEncode'].includes(node.type)){
                for(const w of node.widgets||[])if(typeof w.value==='string'&&['text','positive','negative','prompt'].includes(w.name)){
                    const isNegative=w.name==='negative'||/负向|负面|negative/i.test(node.title||'');
                    set(node,w.name,isNegative?negative:(branchId==='ext04'?edit:positive));
                }
            }
            if(node.type==='LoadImage')set(node,'image',neutralImage);
            for(const w of node.widgets||[]){if(['seed','noise_seed','seed_num'].includes(w.name))set(node,w.name,2026100501);if(w.name==='control_after_generate')set(node,w.name,'fixed');}
            if(node.type==='SaveImage')set(node,'filename_prefix',`_codex_qa/native_e2e_20261005/${caseName}/${node.id}_final`);
            if(node.properties?.uap_refinement){node.mode=full&&['hand','foot','face','eye','eyes'].includes(node.properties.uap_refinement)?0:4;changes.push({id:String(node.id),field:'mode',value:node.mode});}
            if(node.type==='PrimitiveBoolean'&&/分块二放/.test(node.title||''))set(node,'value',full);
            for(const child of node.subgraph?.nodes||[])setup(child);
        }
        nodes.forEach(setup);
        const liveBranch=app.graph.extra.uap_workbench.branches.find(x=>x.id===branchId);
        const issue=workflowGuardIssue(nodes,liveBranch,app.graph.extra.uap_model_contracts);
        if(issue)throw Error(issue);
        const plan=taskPlan(app,'generate');if(plan.reason)throw Error(plan.reason);
        const prompt=(await app.graphToPrompt()).output,targets=[...plan.queueNodeIds];
        const save=(id,ref,name)=>{prompt[id]={class_type:'SaveImage',inputs:{images:ref,filename_prefix:`_codex_qa/native_e2e_20261005/${caseName}/${name}`}};targets.push(id);};
        const decode=nodes.find(n=>n.type==='VAEDecode');
        if(['a1','a29','k2'].includes(branchId))save('qa_base',[String(decode.id),0],'00_base');
        if(full)for(const [id,n] of Object.entries(prompt)){
            if(n.class_type==='DetailerForEach')save('qa_stage_'+id,[id,0],'stage_'+id.replaceAll(':','_'));
            if(n.class_type==='ImpactSimpleDetectorSEGS'){
                const mask='qa_mask_'+id,im='qa_mask_image_'+id;
                prompt[mask]={class_type:'SegsToCombinedMask',inputs:{segs:[id,0]}};
                prompt[im]={class_type:'MaskToImage',inputs:{mask:[mask,0]}};
                save('qa_mask_save_'+id,[im,0],'mask_'+id.replaceAll(':','_'));
            }
        }
        if(branchId.startsWith('ext')){const input=nodes.find(n=>n.type==='LoadImage');save('qa_input',[String(input.id),0],'00_input');}
        return {case:caseName,branch:branchId,source_sha:sourceSha,method:'Native app.graphToPrompt serialization of an unsaved current production copy; taskPlan output targets plus QA image/mask saves',prompt,targets,overrides:changes,seed:2026100501,neutral_input:neutralImage,dimensions:nodes.filter(n=>/Empty.*LatentImage/.test(n.type)).map(n=>({id:n.id,widgets:n.widgets.filter(w=>['width','height','batch_size'].includes(w.name)).map(w=>({name:w.name,value:w.value}))})),guard_issue:issue};
    };
    return {ready:true,sourceSha,branches:source.extra.uap_workbench.branches.length};
})()
