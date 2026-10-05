(async()=>{
 const s=__m5;
 const readListeners=getEventListeners;
 const listeners=()=>({window:Object.fromEntries(Object.entries(readListeners(window)).map(([k,v])=>[k,v.length])),document:Object.fromEntries(Object.entries(readListeners(document)).map(([k,v])=>[k,v.length]))});
 const rows=[];
 for(let i=0;i<3;i++){
  document.querySelector('#unified-workbench [data-uw="close"]')?.click();
  await s.waitFor(()=>!document.querySelector('#unified-workbench'));
  const before={listeners:listeners(),dom:document.querySelectorAll('*').length};
  const sample=await s.measure('library_warm_'+(i+1),()=>{const b=[...document.querySelectorAll('#uap-daily-desk button')].find(b=>b.textContent==='资料库');b.focus();b.click();},()=>!!document.querySelector('#unified-workbench .tb-spm-card'),'#unified-workbench');
  const cardCount=document.querySelectorAll('#unified-workbench .tb-spm-card').length;
  document.querySelector('#unified-workbench [data-uw="close"]').click();
  await s.waitFor(()=>!document.querySelector('#unified-workbench'));
  rows.push({sample,cardCount,before,after:{listeners:listeners(),dom:document.querySelectorAll('*').length,focus:document.activeElement?.textContent?.trim().slice(0,30)}});
 }
 s.libraryCycles=rows;
 return rows;
})()
