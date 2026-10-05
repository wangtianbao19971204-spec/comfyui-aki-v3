(async()=>{
 const app=__m4.app,g=app.graph,c=g.extra.uap_workbench,checks=[],expected=[];
 __m4.roundtripExpected=expected;__m4.roundtripChecks=checks;
 const check=(name,passed)=>{checks.push({name,passed:!!passed});if(!passed)throw Error(name);};
 const control=label=>[...document.querySelectorAll('#uap-daily-desk input,#uap-daily-desk select')].find(e=>e.getAttribute('aria-label')===label);
 const change=(el,value)=>{if(el.type==='checkbox')el.checked=value;else el.value=String(value);el.dispatchEvent(new Event(el.type==='checkbox'?'change':'input',{bubbles:true}));if(el.type!=='checkbox')el.dispatchEvent(new Event('change',{bubbles:true}));};
 for(const [i,b]of c.branches.entries()){
  unifiedUapNavigation.activateBranch(b.id);unifiedDailyControls.render(b,true);
  const ns=b.nodeIds.map(id=>g.getNodeById(id));
  const choice=['遮罩降噪','宽度','步数','向左扩展','缩放倍数'].map(label=>({label,input:control(label)})).find(x=>x.input);
  let numeric=null;
  if(choice){
   const value=choice.label==='遮罩降噪'?.37:Number((Number(choice.input.value)+(choice.label==='宽度'?64:Number(choice.input.step)||.1)).toFixed(8));
   change(choice.input,value);check(b.id+' numeric marker accepted',!choice.input.hasAttribute('aria-invalid'));
   numeric={label:choice.label,value};
  }
  const unload=control('出图后卸载模型');const cleanup=ns.find(n=>n.type==='VRAMCleanup');
  check(b.id+' saved default remains opt-in',unload&&!unload.checked&&!unload.indeterminate&&cleanup.widgets.filter(w=>['offload_model','offload_cache'].includes(w.name)).every(w=>w.value===false));
  const checked=i%2===0;change(unload,checked);
  let group=null;
  const controller=ns.find(n=>/Fast Groups Bypasser/.test(n.type));
  if(controller){
   const w=controller.widgets.find(w=>w.group&&/常规人脸/.test(w.group.title));
   if(w){const label='开关 '+w.group.title.replace(/^(?:SW|FX)-\S+\s*/,'').replace(/ · .+$/,'');change(control(label),true);group={label,nodeIds:w.group._nodes.map(n=>String(n.id)),mode:0};}
  }
  const model=control('基础模型');
  expected.push({branch:b.id,numeric,unload:checked,group,model:model?.value||null});
 }
 for(const row of expected){
  unifiedUapNavigation.activateBranch(row.branch);const b=c.branches.find(b=>b.id===row.branch);unifiedDailyControls.render(b,true);
  if(row.numeric)check(row.branch+' numeric survives branch switch',Number(control(row.numeric.label).value)===row.numeric.value);
  check(row.branch+' unload choice survives branch switch',control('出图后卸载模型').checked===row.unload);
  if(row.group){
   const deadline=performance.now()+3000;
   while(!control(row.group.label)?.checked&&performance.now()<deadline)await new Promise(requestAnimationFrame);
   check(row.branch+' enabled refinement survives branch switch',row.group.nodeIds.every(id=>g.getNodeById(id).mode===0)&&control(row.group.label).checked);
  }
  if(row.model)check(row.branch+' model remains selected',control('基础模型').value===row.model);
 }
 // Browser-only check for an inactive branch: its mounted controls must reject input.
 unifiedUapNavigation.activateBranch('a1');
 const picker=document.querySelector('#uap-workbench-nav select[aria-label="浏览工作分支"]');
 picker.value='a29';picker.dispatchEvent(new Event('change',{bubbles:true}));
 const inactive=control('步数'),b29=c.branches.find(b=>b.id==='a29'),sampler=b29.nodeIds.map(id=>g.getNodeById(id)).find(n=>n.type==='KSampler'),step=sampler.widgets.find(w=>w.name==='steps'),before=step.value;
 check('browsing another branch does not activate it',c.activeBranch==='a1'&&document.querySelector('#uap-daily-desk fieldset').disabled);
 change(inactive,99);check('inactive control cannot change node',step.value===before);
 unifiedUapNavigation.activateBranch('k2');unifiedDailyControls.render(c.branches.find(b=>b.id==='k2'),true);
 const clean=c.branches.find(b=>b.id==='k2').nodeIds.map(id=>g.getNodeById(id)).find(n=>n.type==='VRAMCleanup');
 clean.widgets.find(w=>w.name==='offload_cache').value=false;
 unifiedDailyControls.render(c.branches.find(b=>b.id==='k2'),true);
 check('mixed unload flags show indeterminate',control('出图后卸载模型').indeterminate);
 change(control('出图后卸载模型'),true);check('checking mixed state enables both flags',clean.widgets.filter(w=>['offload_model','offload_cache'].includes(w.name)).every(w=>w.value===true));
 __m4.roundtripExpected=expected;__m4.roundtripGraph=structuredClone(g.serialize());
 return {passed:checks.every(x=>x.passed),checks,expected,graph:__m4.roundtripGraph};
})()
