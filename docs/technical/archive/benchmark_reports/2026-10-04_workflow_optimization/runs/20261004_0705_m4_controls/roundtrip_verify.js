(async()=>{
 const app=__m4.app,g=app.graph,c=g.extra.uap_workbench,checks=[];
 __m4.roundtripVerifyChecks=checks;
 const control=label=>[...document.querySelectorAll('#uap-daily-desk input,#uap-daily-desk select')].find(e=>e.getAttribute('aria-label')===label);
 const check=(name,passed)=>{checks.push({name,passed:!!passed});if(!passed)throw Error(name);};
 for(const row of __m4.roundtripExpected){
  unifiedUapNavigation.activateBranch(row.branch);const b=c.branches.find(b=>b.id===row.branch);unifiedDailyControls.render(b,true);
  if(row.numeric)check(row.branch+' numeric restored after JSON reload',Number(control(row.numeric.label).value)===row.numeric.value);
  check(row.branch+' unload restored after JSON reload',control('出图后卸载模型').checked===row.unload&&!control('出图后卸载模型').indeterminate);
  if(row.group){
   const deadline=performance.now()+3000;
   while(!control(row.group.label)?.checked&&performance.now()<deadline)await new Promise(requestAnimationFrame);
   check(row.branch+' refinement modes restored after JSON reload',row.group.nodeIds.every(id=>g.getNodeById(id).mode===0)&&control(row.group.label).checked);
  }
  if(row.model)check(row.branch+' model restored after JSON reload',control('基础模型').value===row.model);
 }
 check('links survive serialization/reload',JSON.stringify(g.serialize().links)===JSON.stringify(__m4.roundtripGraph.links));
 check('all node IDs survive serialization/reload',JSON.stringify(g.serialize().nodes.map(n=>n.id))===JSON.stringify(__m4.roundtripGraph.nodes.map(n=>n.id)));
 const forbidden=__m4.blocked.filter(x=>/^\/(?:api\/)?(prompt|free|userdata)/.test(x.url));
 check('no generation/unload/formal save requested',forbidden.length===0);
 return {passed:checks.every(x=>x.passed),checks,scope:'in-memory JSON serialization and full ComfyUI load; no formal disk save or generation'};
})()
