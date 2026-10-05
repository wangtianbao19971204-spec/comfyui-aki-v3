(async()=>{
 const s=__m5;
 const readListeners=getEventListeners;
 const listeners=()=>({window:Object.fromEntries(Object.entries(readListeners(window)).map(([k,v])=>[k,v.length])),document:Object.fromEntries(Object.entries(readListeners(document)).map(([k,v])=>[k,v.length]))});
 const rows=[];
 for(let i=0;i<5;i++){
  document.querySelector('#anima-pose-selector-overlay')?.unifiedClose();
  await s.waitFor(()=>!document.querySelector('#anima-pose-selector-overlay'));
  const before={listeners:listeners(),dom:document.querySelectorAll('*').length};
  const sample=await s.measure('pose_warm_'+(i+1),()=>{const b=[...document.querySelectorAll('#uap-daily-desk button')].find(b=>b.textContent==='姿势选择器');b.focus();b.click();},()=>!!document.querySelector('#anima-pose-selector-overlay [data-key]'),'#anima-pose-selector-overlay');
  const cardCount=document.querySelectorAll('#anima-pose-selector-overlay [data-key]').length;
  document.querySelector('#anima-pose-selector-overlay').unifiedClose();
  await s.waitFor(()=>!document.querySelector('#anima-pose-selector-overlay'));
  rows.push({sample,cardCount,before,after:{listeners:listeners(),dom:document.querySelectorAll('*').length,focus:document.activeElement?.textContent?.trim().slice(0,30)}});
 }
 s.poseCycles=rows;
 return rows;
})()
