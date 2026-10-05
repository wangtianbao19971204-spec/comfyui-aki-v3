(async()=>{
 const app=__m4.app,g=app.graph,c=g.extra.uap_workbench;
 const b=c.branches.find(x=>x.id===__m4.branchToAudit);
 unifiedUapNavigation.activateBranch(b.id);unifiedDailyControls.render(b,true);unifiedDailyControls.show(true);
 const ids=new Set(b.nodeIds.map(String));
 const nodes=()=>b.nodeIds.map(id=>g.getNodeById(id)).filter(Boolean);
 const result={branch:b.id,label:b.label,checks:[],controls:[],errors:[]};
 const check=(name,value,detail)=>{result.checks.push({name,passed:!!value,...(detail?{detail}:{})});if(!value)result.errors.push(name);};
 const snapshot=()=>g.serialize().nodes.map(n=>({id:String(n.id),mode:n.mode,widgets:n.widgets_values,named:n.widgets_values_named}));
 const diffs=(a,z)=>a.filter(n=>JSON.stringify(n)!==JSON.stringify(z.find(x=>x.id===n.id))).map(n=>({id:n.id,before:n,after:z.find(x=>x.id===n.id)}));
 const findControl=label=>[...document.querySelectorAll('#uap-daily-desk input,#uap-daily-desk select')].find(e=>e.getAttribute('aria-label')===label);
 const emit=(control,value)=>{if(control.type==='checkbox'){control.checked=value;control.dispatchEvent(new Event('change',{bubbles:true}));}else{control.value=String(value);control.dispatchEvent(new Event('input',{bubbles:true}));control.dispatchEvent(new Event('change',{bubbles:true}));}};
 const initial=snapshot(),initialLinks=JSON.stringify(g.serialize().links);
 check('only selected branch active',c.activeBranch===b.id&&c.branches.filter(other=>other.id!==b.id).flatMap(other=>other.nodeIds).every(id=>g.getNodeById(id)?.mode===2));
 const choices=[...document.querySelectorAll('#uap-daily-desk input[type=number],#uap-daily-desk select')].filter(e=>e.getAttribute('aria-label')&&!['界面主题','资料库插入目标','检查采样器'].includes(e.getAttribute('aria-label')));
 for(const control of choices){
  const label=control.getAttribute('aria-label'),old=control.value,before=snapshot();
  if(control.disabled){result.controls.push({label,status:'disabled'});continue;}
  let value;
  if(control.tagName==='SELECT')value=[...control.options].find(o=>!o.disabled&&o.value!==old)?.value;
  else{
   const step=['宽度','高度'].includes(label)?64:control.step==='any'?0.1:Number(control.step)||1;
   const max=control.max===''?Infinity:Number(control.max),min=control.min===''?-Infinity:Number(control.min);
   value=Number((Number(old)+step<=max?Number(old)+step:Number(old)-step).toFixed(8));
   if(value<min)value=undefined;
  }
  if(value===undefined){result.controls.push({label,status:'no_alternative',current:old});continue;}
  emit(control,value);
  const changed=diffs(before,snapshot());
  check(label+' commits to active graph',changed.length>0&&changed.every(d=>ids.has(d.id)),changed.map(x=>x.id));
  const contains=changed.some(d=>JSON.stringify(d.after.widgets).includes(JSON.stringify(typeof value==='number'?value:String(value))));
  check(label+' value serialized',contains);
  result.controls.push({label,kind:control.type,old,value,changed});
  emit(control,old);
  check(label+' restored exactly',diffs(before,snapshot()).length===0);
 }
 for(const control of (__m4.numericOnly?[]:[...document.querySelectorAll('#uap-daily-desk input[type=checkbox]')])){
  const label=control.getAttribute('aria-label');if(!label)continue;
  const before=snapshot(),old=control.checked;
  if(control.disabled){result.controls.push({label,status:'disabled'});continue;}
  let groupWidget,groupOwner;
  for(const n of nodes().filter(n=>/Fast Groups/.test(n.type)))for(const w of n.widgets||[]){
   if(w.group&&'开关 '+w.group.title.replace(/^(?:SW|FX)-\S+\s*/,'').replace(/ · .+$/,'')===label){groupWidget=w;groupOwner=n;}
  }
  const expectedGroup=groupWidget?.group?._nodes?.map(n=>String(n.id));
  emit(control,!old);
  const changed=diffs(before,snapshot());
  check(label+' changes only active branch',changed.length>0&&changed.every(d=>ids.has(d.id)),changed.map(x=>x.id));
  if(expectedGroup){
   check(label+' matches group members',changed.every(d=>expectedGroup.includes(d.id)||d.id===String(groupOwner.id)));
   check(label+' enables real group nodes',expectedGroup.every(id=>g.getNodeById(id).mode===(!old?0:/Bypasser/.test(nodes().find(n=>n.widgets?.includes(groupWidget)).type)?4:2)));
  }
  if(label==='出图后卸载模型')check(label+' both flags match user choice',nodes().filter(n=>n.type==='VRAMCleanup').every(n=>['offload_model','offload_cache'].every(name=>n.widgets.find(w=>w.name===name).value===!old)));
  result.controls.push({label,kind:'checkbox',old,value:!old,groupMembers:expectedGroup,changed});
  emit(control,old);
  check(label+' restored exactly',diffs(before,snapshot()).length===0);
 }
 check('all branch values and modes restored',diffs(initial,snapshot()).length===0);
 check('all links unchanged',JSON.stringify(g.serialize().links)===initialLinks);
 const generated=await app.graphToPrompt();
 result.apiClasses=[...new Set(Object.values(generated.output).map(n=>n.class_type))];
 result.samplerIds=Object.entries(generated.output).filter(([id,n])=>/KSampler/.test(n.class_type)).map(([id])=>id);
 result.passed=result.checks.every(c=>c.passed);
 __m4.branchResults??=[];__m4.branchResults.push(result);
 return result;
})()
