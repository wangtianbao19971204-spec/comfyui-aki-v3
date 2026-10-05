(async()=>{
 const s=__m5;
 const readListeners=getEventListeners;
 const listeners=()=>({window:Object.fromEntries(Object.entries(readListeners(window)).map(([k,v])=>[k,v.length])),document:Object.fromEntries(Object.entries(readListeners(document)).map(([k,v])=>[k,v.length]))});
 const rows=[];
 for(let i=0;i<5;i++){
  document.querySelector('#unified-workbench [data-uw="close"]')?.click();
  await s.waitFor(()=>!document.querySelector('#unified-workbench'));
  const before={listeners:listeners(),dom:document.querySelectorAll('*').length};
  const sample=await s.measure('pending_warm_'+(i+1),()=>{const b=[...document.querySelectorAll('#uap-daily-desk button')].find(b=>b.textContent==='待用列表 · 组合预览');b.focus();b.click();},()=>document.querySelectorAll('#unified-workbench .uw-pending-item').length===6&&[...document.querySelectorAll('#unified-workbench .uw-pending-preview')].at(-1)?.textContent.includes(__m5.expectedPending),'#unified-workbench');
  const cardCount=document.querySelectorAll('#unified-workbench .uw-pending-item').length;
  document.querySelector('#unified-workbench [data-uw="close"]').click();
  await s.waitFor(()=>!document.querySelector('#unified-workbench'));
  rows.push({sample,cardCount,before,after:{listeners:listeners(),dom:document.querySelectorAll('*').length,focus:document.activeElement?.textContent?.trim().slice(0,30)}});
 }
 s.pendingCycles=rows;
 return rows;
})()
