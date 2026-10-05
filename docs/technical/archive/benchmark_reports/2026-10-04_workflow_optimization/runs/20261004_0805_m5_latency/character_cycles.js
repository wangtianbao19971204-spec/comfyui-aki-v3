(async()=>{
 const s=__m5;
 const readListeners=getEventListeners;
 const listeners=()=>({window:Object.fromEntries(Object.entries(readListeners(window)).map(([k,v])=>[k,v.length])),document:Object.fromEntries(Object.entries(readListeners(document)).map(([k,v])=>[k,v.length]))});
 const rows=[];
 for(let i=0;i<5;i++){
  document.querySelector('#anima-char-selector-overlay')?.unifiedClose();
  await s.waitFor(()=>!document.querySelector('#anima-char-selector-overlay'));
  const before={listeners:listeners(),dom:document.querySelectorAll('*').length};
  const sample=await s.measure('character_warm_'+(i+1),()=>[...document.querySelectorAll('#uap-daily-desk button')].find(b=>b.textContent==='角色选择器').click(),()=>!!document.querySelector('#anima-char-selector-overlay [data-selector-key]'),'#anima-char-selector-overlay');
  const cardCount=document.querySelectorAll('#anima-char-selector-overlay [data-selector-key]').length;
  document.querySelector('#anima-char-selector-overlay').unifiedClose();
  await s.waitFor(()=>!document.querySelector('#anima-char-selector-overlay'));
  rows.push({sample,cardCount,before,after:{listeners:listeners(),dom:document.querySelectorAll('*').length,focus:document.activeElement?.textContent?.trim().slice(0,30)}});
 }
 s.characterCycles=rows;
 return rows;
})()
