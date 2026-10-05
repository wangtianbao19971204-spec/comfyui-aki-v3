(async()=>{
    const cfg=app.graph.extra.uap_workbench,branch=cfg.branches.find(b=>b.id===cfg.activeBranch);
    unifiedDailyControls.render(branch,true);unifiedDailyControls.show(true);
    const initial=await app.graphToPrompt(),api=initial.output;
    const samplers=Object.entries(api).filter(([id,n])=>branch.nodeIds.map(String).includes(id)&&['KSampler','KSamplerAdvanced'].includes(n.class_type));
    const result={branch:branch.id,label:branch.label,checks:[],sources:[],samplers:samplers.map(([id])=>id)};
    function check(name,passed){result.checks.push({name,passed:!!passed});if(!passed)throw Error(name);}
    function source(value){
        if(!Array.isArray(value))return null;
        const [id,slot]=value,n=api[id];if(!n||slot!==0)return null;
        if(n.class_type==='CLIPTextEncode')return Array.isArray(n.inputs.text)?source(n.inputs.text):{id,widget:'text'};
        if(n.class_type==='WeiLinPromptUI')return {id,widget:'positive'};
        if(n.class_type==='CR Prompt Text')return {id,widget:'prompt'};
        if(n.class_type==='Krea2EditGroundedEncode')return {id,widget:'prompt',runtime:true};
        return null;
    }
    const promptState=()=>JSON.stringify(app.graph._nodes.map(n=>[n.id,(n.widgets||[]).filter(w=>['positive','negative','text','prompt','system_prompt','auto_random','lora_str'].includes(w.name)).map(w=>[w.name,w.value])]));
    const before=promptState(),links=JSON.stringify(app.graph.serialize().links);
    for(const [samplerId,sampler] of samplers){
        for(const direction of ['positive','negative']){
            const target=source(sampler.inputs[direction]);check(direction+' source resolved',target);
            const node=app.graph.getNodeById(target.id),widget=node.widgets.find(w=>w.name===target.widget);
            const input=unifiedDailyControls.getPromptInput(node,widget);
            check(direction+' console is bound to actual source widget',input&&input.getAttribute('aria-label')===`常用${direction==='positive'?'正向':'负向'}提示词`);
            check(direction+' original console text matches API',input.value===api[target.id].inputs[target.widget]);
            const saved=input.value,marker=`neutral ${branch.id} ${direction}, (soft daylight:1.1), forest, forest`;
            input.value=marker;input.dispatchEvent(new Event('input',{bubbles:true}));
            const changed=await app.graphToPrompt(),report=__r5.inspect(changed.output,samplerId);
            check(direction+' input reaches serialized source exactly',changed.output[target.id].inputs[target.widget]===marker);
            if(!target.runtime)check(direction+' inspector preserves weights and repeated fragments',report[direction].text===marker);
            else check(direction+' grounded conditioning remains explicitly runtime',report[direction].text==null&&report[direction].reason.includes('运行时'));
            input.value=saved;input.dispatchEvent(new Event('input',{bubbles:true}));
            result.sources.push({samplerId,direction,target,before:saved,marker,inspector:target.runtime?'runtime':'exact',restored:widget.value===saved});
        }
    }
    if(!samplers.length){
        check('image-only branch has no positive text target',!document.querySelector('[aria-label="常用正向提示词"]'));
        check('image-only branch has no negative text target',!document.querySelector('[aria-label="常用负向提示词"]'));
    }
    check('all prompt fields restored',before===promptState());
    check('links unchanged by console writes',links===JSON.stringify(app.graph.serialize().links));
    await document.querySelector('.desk-prompt-inspector button').onclick();
    result.inspectorUI=document.querySelector('.desk-prompt-inspector').innerText;
    if(!samplers.length)check('no unsupported sampler claim',result.inspectorUI.includes('未发现可检查的启用采样器'));
    result.passed=result.checks.every(c=>c.passed);__r5.captures.push(result);
    return result;
})()
