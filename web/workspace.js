import {commitWidget, isEnabledTarget} from './prompt_target.js';
import {listPromptTargets,attachPromptAutocomplete} from './resource_actions.js';
import {mountRunControls} from './run_controls.js';

export function mountWorkspace(host, {app, element, button, browse, selectTarget, report, savePlan, models, close}) {
    const toolbar=element('div',null,host,{className:'uw-toolbar'});
    element('h2','当前工作流',toolbar);
    button('模型','workspace-models',()=>models('loras'),toolbar);
    const planHost=element('div',null,host,{hidden:true,className:'uw-plan-create'});
    button('保存正负向方案','workspace-save-pair',()=>{
        if(restoreDaily&&window.unifiedDailyControls?.readPlan){const sections=window.unifiedDailyControls.readPlan();return savePlan(Object.values(sections).join('\n'),'mixed','当前分支',sections);}
        planHost.replaceChildren();planHost.hidden=false;const capturedGraph=app.graph,targets=listPromptTargets(app),picks={};
        element('p','选择要保存的正向和负向字段。这会另存共享方案，原节点继续保留当前内容。',planHost);
        for(const [direction,label]of [['positive','正向来源'],['negative','负向来源']]){
            const select=element('select',null,element('label',label,planHost));select.setAttribute('aria-label',label);picks[direction]=select;element('option','不包含这个方向',select,{value:''});
            targets.forEach((target,index)=>element('option',target.label,select,{value:String(index)}));const known=targets.map((target,index)=>({target,index})).filter(({target})=>target.direction===direction);if(known.length===1)select.value=String(known[0].index);
        }
        button('编辑并保存方案','save-pair',()=>{
            if(capturedGraph!==app.graph)throw new Error('工作流已切换，请重新选择来源。');
            if(picks.positive.value!==''&&picks.positive.value===picks.negative.value)throw new Error('同一字段不能同时作为正向和负向来源。');
            const currentTargets=listPromptTargets(app);
            const sections={positive:'',negative:''};for(const [direction,picker]of Object.entries(picks))if(picker.value!==''){const target=targets[Number(picker.value)];if(!currentTargets.some(current=>current.node===target.node&&current.widget===target.widget))throw new Error('来源字段已变化，请重新选择。');sections[direction]=String(target.widget.value||'');}
            return savePlan(Object.values(sections).join('\n'),'mixed','当前工作流',sections);
        },planHost);button('收起','cancel-pair',()=>{planHost.hidden=true;},planHost);
    },toolbar);
    const runs=mountRunControls(host,{app,element,button,report});
    const prompts=element('div',null,host,{className:'uw-prompt-grid'});
    const native=element('div',null,host,{className:'uw-native-daily',hidden:true});
    const tools=element('details',null,host,{className:'uw-tools'});
    element('summary','提示词工具与常用参数',tools);
    const editors=element('div',null,tools,{className:'uw-toolbar'});
    const parameters=element('div',null,tools,{className:'uw-parameter-grid'});
    let graph=null, signature='', inputs=[],parameterInputs=[],restoreDaily=null,dailyBranch=null,dailyGraph=null,dailyNodes=[];
    const detachInputs=()=>{for(const {input}of inputs)for(const owner of new Set([input._promptAutocompleteOwner,input._promptAutocompleteFallback]))owner?.destroy?.();};
    const attachInputs=()=>inputs.forEach(({input})=>attachPromptAutocomplete(input));window.addEventListener('lora-manager:autocomplete-ready',attachInputs);
    const valid=(node,widget)=>graph===app.graph && isEnabledTarget(app,node) && node.widgets?.includes(widget);
    const validPrompt=(node,widget)=>graph===app.graph && listPromptTargets(app).some(target=>target.node===node&&target.widget===widget);
    function refresh() {
        const branchState=app.graph?.extra?.uap_workbench;
        const branch=branchState?.branches?.find(item=>item.id===branchState.activeBranch);
        if(branch && window.unifiedDailyControls) {
            const members=branch.nodeIds.map(id=>app.graph.getNodeById(id));
            if(dailyGraph!==app.graph || dailyBranch!==branch || members.length!==dailyNodes.length || members.some((node,i)=>node!==dailyNodes[i]) || !native.firstElementChild) {
                restoreDaily?.();restoreDaily=window.unifiedDailyControls.mount(native,branch,close);dailyGraph=app.graph;dailyBranch=branch;dailyNodes=members;
            }
            prompts.hidden=true;tools.hidden=true;native.hidden=false;return;
        }
        if(restoreDaily){restoreDaily();restoreDaily=null;dailyBranch=null;dailyGraph=null;}
        native.hidden=true;prompts.hidden=false;tools.hidden=false;
        const targets=listPromptTargets(app);
        const nodes=(app.graph?._nodes || []).filter(node=>isEnabledTarget(app,node));
        const parameterTargets=nodes.flatMap(node=>(node.widgets||[]).filter(widget=>['width','height','steps','cfg','seed','denoise','strength_model'].includes(widget.name)&&typeof widget.value==='number').map(widget=>({node,widget})));
        const next=targets.map(t=>`${t.node.id}:${t.widget.name}`).join('|')+';'+nodes.map(n=>n.id).join(',');
        if(graph===app.graph && signature===next && targets.every((t,i)=>inputs[i]?.target.node===t.node && inputs[i]?.target.widget===t.widget) && parameterTargets.length===parameterInputs.length && parameterTargets.every((t,i)=>parameterInputs[i].node===t.node&&parameterInputs[i].widget===t.widget)) {
            for(const {input,target} of inputs){input.disabled=false;if(document.activeElement!==input && input.value!==String(target.widget.value))input.value=String(target.widget.value);}
            for(const {input,widget} of parameterInputs)if(document.activeElement!==input && input.value!==String(widget.value))input.value=String(widget.value);
            return;
        }
        graph=app.graph; signature=next;detachInputs();inputs=[];parameterInputs=[];
        prompts.replaceChildren(); editors.replaceChildren(); parameters.replaceChildren();
        if(!targets.length)element('p','当前没有已启用且可编辑的提示词字段。可先浏览资料库，或通过节点搜索添加提示词节点。',prompts);
        for(const target of targets) {
            const card=element('section',null,prompts,{className:'uw-prompt-card'});
            element('label',target.label,card);
            const input=element('textarea',null,card,{className:'comfy-multiline-input',value:String(target.widget.value || ''),spellcheck:false});
            input.setAttribute('aria-label',target.label); inputs.push({input,target});
            attachPromptAutocomplete(input);
            input.onfocus=()=>selectTarget(target,input);
            input.oninput=()=>{if(!validPrompt(target.node,target.widget)){input.disabled=true;report('目标已变化，当前输入保留在页面，请重新选择。');return;}commitWidget(app,target.node,target.widget,input.value);};
            const row=element('div',null,card,{className:'uw-toolbar'});
            button('找资料','browse',()=>browse(target,input),row);
            button('保存提示词方案','save-plan',()=>{if(!validPrompt(target.node,target.widget))throw new Error('当前目标已失效');return savePlan(input.value,target.direction,target.label);},row);
            button('定位节点','locate',()=>app.canvas?.centerOnNode?.(target.node),row);
        }
        for(const node of nodes) {
            const open=node.widgets?.find(w=>w.type==='button' && /打开提示词|Open.*Prompt/i.test(w.name));
            if(open)button((node.title || node.type)+' · 翻译 / 随机 / 历史','native-editor',()=>open.callback(),editors);
            for(const widget of node.widgets || []) {
                if(!['width','height','steps','cfg','seed','denoise','strength_model'].includes(widget.name) || typeof widget.value!=='number')continue;
                const labels={width:'宽度',height:'高度',steps:'步数',cfg:'CFG',seed:'种子',denoise:'降噪',strength_model:'模型强度'};
                const label=element('label',`${labels[widget.name]} · ${node.title || node.type}`,parameters);
                const input=element('input',null,label,{type:'number',value:String(widget.value),step:widget.options?.step || 'any'});
                parameterInputs.push({input,node,widget});
                input.onchange=()=>{if(!valid(node,widget)){report('参数节点已失效');return;}const value=Number(input.value);if(!Number.isFinite(value)){report('请输入有效数值');return;}commitWidget(app,node,widget,value);};
            }
        }
    }
    refresh();
    return {refresh, dispose(){runs.dispose();restoreDaily?.();restoreDaily=null;detachInputs();window.removeEventListener('lora-manager:autocomplete-ready',attachInputs);inputs=[];parameterInputs=[];}};
}
