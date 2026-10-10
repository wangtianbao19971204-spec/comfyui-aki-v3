import {commitWidget, isEnabledTarget} from './prompt_target.js';
import {listPromptTargets,attachPromptAutocomplete,promptDirection} from './resource_actions.js';
import {mountRunControls} from './run_controls.js';
import {mountTaskActivity} from './task_activity.js';
import {inspectStaticPromptInputs} from './static_prompt_inspector.js';
import {workflowChoices, isWorkflowChoice, openWorkflowChoice} from './repair_workflow.js';

export function mountWorkspace(host, {app, element, button, browse, selectTarget, report, savePlan, models, close}) {
    host.classList.add('uw-workspace-page');
    const toolbar=element('div',null,host,{className:'uw-toolbar uw-workspace-context'});
    const workflowTitle=element('h2','当前工作流',toolbar);
    const auxiliary=element('details',null,host,{className:'uw-workspace-extra'});
    element('summary','工作流工具与检查',auxiliary);
    const workflowTools=element('div',null,auxiliary,{className:'uw-toolbar'});
    button('选择其他工作流 ↗','workspace-other-workflow',()=>{
        const sidebar=app.extensionManager?.sidebarTab;
        if(!sidebar?.sidebarTabs?.some(tab=>tab.id==='workflows')||typeof sidebar.toggleSidebarTab!=='function')throw new Error('工作流列表尚未就绪，请从 ComfyUI 左侧工作流入口打开。');
        if(close()===false)return;
        window.unifiedDailyControls?.show(false);
        if(sidebar.activeSidebarTabId!=='workflows')sidebar.toggleSidebarTab('workflows');
        app.canvas?.canvas?.focus?.({preventScroll:true});
    },workflowTools);
    button('模型','workspace-models',()=>models('loras'),workflowTools);
    const branchBar=element('div',null,host,{className:'uw-toolbar uw-branch-controls',hidden:true});
    const branchLabel=element('label','切换到 ',branchBar),branchPicker=element('select',null,branchLabel);branchPicker.setAttribute('aria-label','选择要切换的工作分支');
    const switchBranch=button('启用并切换','workspace-switch-branch',()=>{
        const state=app.graph?.extra?.uap_workbench;
        if(branchGraph!==app.graph||!state?.branches?.some(branch=>branch.id===branchPicker.value))throw new Error('工作流已变化，请重新选择分支。');
        if(!window.unifiedUapNavigation)throw new Error('分支导航仍在加载，请稍后重试。');
        window.unifiedUapNavigation.activateBranch(branchPicker.value);refresh();
    },branchBar);
    const activeBranch=element('span','',branchBar);activeBranch.setAttribute('role','status');
    const branchSummary=element('p','',host,{className:'uw-task-description uw-branch-summary',hidden:true});
    const staticPanel=element('details',null,auxiliary,{className:'uw-static-inspector'});
    element('summary','编码前文本检查 · 只读',staticPanel);
    const staticBody=element('div',null,staticPanel);
    let checkedGraph=null,checkedBranch='';
    button('检查当前活动分支','inspect-static-text',()=>{
        const graph=app.graph,state=graph?.extra?.uap_workbench;
        const branch=state?.branches?.find(item=>item.id===state.activeBranch);
        staticBody.replaceChildren();checkedGraph=graph;checkedBranch=state?.activeBranch||'';
        if(!branch){element('p','当前工作流没有已登记的活动分支。',staticBody);return;}
        element('p','这是检查时的静态快照；编辑字段或切换分支后请重新检查。不会排队、运行节点或加载模型。',staticBody);
        const rows=inspectStaticPromptInputs(graph,branch);
        if(!rows.length){element('p','当前分支不使用提示词编码。',staticBody);return;}
        for(const row of rows){
            const card=element('section',null,staticBody,{className:'uw-static-inspector-row'});
            const direction=promptDirection(app,row.node,{name:row.node.type==='CLIPTextEncode'?'text':'prompt'});
            element('strong',row.label+' · '+({positive:'正向',negative:'负向'}[direction]||'方向未判定'),card);
            element('p',row.reason,card);
            if(row.source)element('small','来源：'+row.source,card);
            if(row.status==='static')element('pre',row.text,card);
            if(row.status==='source')element('pre',row.text,card);
            if(row.sourceNode)button('定位动态来源节点','inspect-source',()=>{
                if(close()===false)return;
                app.canvas?.centerOnNode?.(row.sourceNode);
                app.canvas?.canvas?.focus?.({preventScroll:true});
            },card);
        }
    },staticPanel);
    let branchGraph=null,branchSignature='',lastActiveBranch='';
    function refreshBranchPicker(){
        const path=app.extensionManager?.workflow?.activeWorkflow?.path;
        workflowTitle.textContent=path?'当前工作流 · '+String(path).split(/[\\/]/).at(-1):'当前工作流';
        workflowTitle.title=workflowTitle.textContent;
        const state=app.graph?.extra?.uap_workbench;
        branchBar.hidden=branchSummary.hidden=!state?.branches?.length;if(branchBar.hidden)return;
        const signature=state.branches.map(branch=>`${branch.id}:${branch.label}`).join('|');
        if(branchGraph!==app.graph||branchSignature!==signature){
            branchPicker.replaceChildren();for(const choice of workflowChoices(state))element('option',choice.label,branchPicker,{value:choice.value});
            branchPicker.value=state.activeBranch;branchGraph=app.graph;branchSignature=signature;
        }
        if(lastActiveBranch!==state.activeBranch&&branchPicker.value===lastActiveBranch)branchPicker.value=state.activeBranch;
        lastActiveBranch=state.activeBranch;
        const selected=state.branches.find(branch=>branch.id===branchPicker.value),active=state.branches.find(branch=>branch.id===state.activeBranch);
        switchBranch.disabled=!selected||selected===active;
        switchBranch.textContent=selected===active?'当前已启用':'启用并切换';
        activeBranch.textContent='正在编辑与运行：'+(active?.label||'未选择');
        const nodes=selected?.nodeIds.map(id=>app.graph.getNodeById(id)).filter(Boolean)||[];
        const has=type=>nodes.some(node=>node.type===type);
        const use=has('StockingTextureStudio')?'导入图片 / PSD → 纹理修复 → 成品与透明图层':has('BiRefNetRMBG')?'图片 → 抠图 → 透明素材':has('ImagePadForOutpaint')?'输入图片 → 扩展边缘 → 结果':has('OlmDragCrop')?'输入图片 → 裁剪精修 → 回贴':has('Krea2EditGroundedEncode')?'输入图片 + 编辑指令 → 结果':!has('KSampler')&&has('UpscaleModelLoader')?'输入图片 → 模型放大 → 结果':'提示词 + 模型 + 参数 → 生成图片';
        const details=has('StockingTextureStudio')?'点击打开修复编辑器；应用到节点后输出。':has('BiRefNetRMBG')?'不需要提示词。':selected?.id==='a29'?'使用 2.9B 模型；原版 Anima 的 LLLite 控制模型不通用。':selected?.id==='a1'?'原版 Anima，使用此分支的 LoRA 与控制组件。':selected?.id==='ext08'?'OmniSR 原生4×，随后缩放0.5×，最终2×；修改后按合成倍率交付。':selected?.id==='ext09'?'预设为四倍素材，使用放大模型的原始输出。':'';
        branchSummary.hidden=selected===active&&!details;
        branchSummary.textContent=(selected===active?'当前流程：':'待切换流程：')+use+'。'+details+(selected===active?'':' 仅选择不会切换运行；点击“启用并切换”后，控制项和运行任务会一起切换。');
    }
    branchPicker.onchange=async()=>{
        const value=branchPicker.value;
        if(!isWorkflowChoice(value)) {refreshBranchPicker();return;}
        branchPicker.value=app.graph?.extra?.uap_workbench?.activeBranch;
        try {await openWorkflowChoice(app,value);refresh();}
        catch(error) {report(error);}
    };
    const planHost=element('div',null,auxiliary,{hidden:true,className:'uw-plan-create'});
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
    },workflowTools);
    const actions=element('div',null,host,{className:'uw-workspace-actions'});
    const taskActions=element('div',null,actions,{className:'uw-task-actions'});
    const runs=mountRunControls(actions,{app,element,button,report,historyHost:auxiliary,prepareTask:()=>activity.prepare(),onSubmitted:plan=>activity.submitted(plan.label)});
    const selectorHost=element('details',null,actions,{className:'uw-selector-disclosure',hidden:true});
    element('summary','提示词选择器',selectorHost);
    const taskInputs=element('div',null,host,{className:'uw-task-inputs'});
    const layout=element('div',null,host,{className:'uw-workspace-layout'});
    layout.dataset.view='controls';
    const viewBar=element('div',null,host,{className:'uw-workspace-view-tabs'});
    viewBar.setAttribute('role','group');viewBar.setAttribute('aria-label','切换参数与结果');
    host.insertBefore(viewBar,layout);
    const viewButtons=[];
    for(const [value,label] of [['controls','参数与输入'],['results','结果与状态']]){
        const tab=button(label,'workspace-view-'+value,()=>{
            layout.dataset.view=value;
            for(const [key,item] of viewButtons)item.setAttribute('aria-pressed',String(key===value));
        },viewBar);tab.setAttribute('aria-pressed',String(value==='controls'));viewButtons.push([value,tab]);
    }
    const controls=element('div',null,layout,{className:'uw-workspace-controls'});
    const prompts=element('div',null,controls,{className:'uw-prompt-grid'});
    const native=element('div',null,controls,{className:'uw-native-daily',hidden:true});
    const tools=element('details',null,controls,{className:'uw-tools'});
    const activityHost=element('aside',null,layout,{className:'uw-task-activity'});
    activityHost.setAttribute('aria-label','当前任务与结果');
    const activity=mountTaskActivity(activityHost,{app,element,button,report,actionsHost:taskActions,inputHost:taskInputs,onChange:plan=>runs.setTask(plan)});
    host.append(auxiliary);
    element('summary','提示词工具与常用参数',tools);
    const editors=element('div',null,tools,{className:'uw-toolbar'});
    const parameters=element('div',null,tools,{className:'uw-parameter-grid'});
    let graph=null, signature='', inputs=[],parameterInputs=[],restoreDaily=null,dailyBranch=null,dailyGraph=null,dailyNodes=[];
    const detachInputs=()=>{for(const {input}of inputs)for(const owner of new Set([input._promptAutocompleteOwner,input._promptAutocompleteFallback]))owner?.destroy?.();};
    const attachInputs=()=>inputs.forEach(({input})=>attachPromptAutocomplete(input));window.addEventListener('lora-manager:autocomplete-ready',attachInputs);
    const valid=(node,widget)=>graph===app.graph && isEnabledTarget(app,node) && node.widgets?.includes(widget);
    const validPrompt=(node,widget)=>graph===app.graph && listPromptTargets(app).some(target=>target.node===node&&target.widget===widget);
    function refresh() {
        refreshBranchPicker();
        selectorHost.hidden=!listPromptTargets(app).some(target=>target.direction==='positive');
        if(checkedGraph&&(checkedGraph!==app.graph||checkedBranch!==app.graph?.extra?.uap_workbench?.activeBranch)){
            checkedGraph=null;staticBody.replaceChildren();element('p','分支或工作流已变化，请重新检查。',staticBody);
        }
        activity.refresh();
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
            button('定位节点','locate',()=>{
                if(!validPrompt(target.node,target.widget))throw new Error('目标节点已变化，请重新选择。');
                if(close()===false)return;
                app.canvas?.centerOnNode?.(target.node);
                app.canvas?.canvas?.focus?.({preventScroll:true});
            },row);
        }
        for(const node of nodes) {
            const open=node.widgets?.find(w=>w.type==='button' && /打开提示词|Open.*Prompt/i.test(w.name));
            if(open)button((node.title || node.type)+' · 翻译 / 随机 / 历史','native-editor',()=>open.callback(),editors);
            for(const widget of node.widgets || []) {
                if(!['width','height','steps','cfg','seed','denoise','strength_model'].includes(widget.name) || typeof widget.value!=='number')continue;
                const labels={width:'宽度',height:'高度',steps:'步数',cfg:'CFG',seed:'种子',denoise:'降噪',strength_model:'模型强度'};
                const label=element('label',`${labels[widget.name]} · ${node.title || node.type}`,parameters);
                const input=element('input',null,label,{type:'number',value:String(widget.value),step:['width','height','steps','seed'].includes(widget.name)?'1':'any'});
                input.setAttribute('aria-label', `${labels[widget.name]} · ${node.title || node.type}`);
                if(widget.options?.min!=null)input.min=widget.options.min;
                if(widget.options?.max!=null)input.max=widget.options.max;
                parameterInputs.push({input,node,widget});
                input.oninput=()=>input.removeAttribute('aria-invalid');
                input.onchange=()=>{
                    if(!valid(node,widget)){report('参数节点已失效');return;}
                    const value=Number(input.value);
                    if(!input.value.trim()||!Number.isFinite(value)||!input.checkValidity()){
                        input.setAttribute('aria-invalid','true');report('请输入有效数值'+(input.min!==''?'，最小 '+input.min:'')+(input.max!==''?'，最大 '+input.max:'')+'；原参数未修改。');return;
                    }
                    input.removeAttribute('aria-invalid');commitWidget(app,node,widget,value);
                };
            }
        }
    }
    if(!host.hidden)refresh();
    return {refresh, selectorHost, setActive(value){activity.setActive(value);}, dispose(){runs.dispose();activity.dispose();restoreDaily?.();restoreDaily=null;detachInputs();window.removeEventListener('lora-manager:autocomplete-ready',attachInputs);inputs=[];parameterInputs=[];}};
}
