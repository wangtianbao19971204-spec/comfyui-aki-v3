(async()=>{
 const {app}=await import('/scripts/app.js');
 if(app.graph._nodes.length!==292)throw Error('Original graph not ready');
 window.__m5={app,originalGraph:structuredClone(app.graph.serialize()),local:Object.fromEntries(Object.entries(localStorage)),session:Object.fromEntries(Object.entries(sessionStorage)),blocked:[],requests:[],samples:[],fetch:window.fetch,xhrOpen:XMLHttpRequest.prototype.open,xhrSend:XMLHttpRequest.prototype.send,beacon:navigator.sendBeacon};
 const s=__m5;
 window.fetch=async function(input,init){
  const method=String(init?.method||input?.method||'GET').toUpperCase(),url=String(input?.url||input);
  if(!['GET','HEAD','OPTIONS'].includes(method)){s.blocked.push({url,method});return new Response('{}',{status:409,headers:{'Content-Type':'application/json'}});}
  const row={url,method,start:performance.now()};s.requests.push(row);
  try{const r=await s.fetch.call(this,input,init);row.status=r.status;row.headersMs=performance.now()-row.start;return r;}catch(e){row.error=String(e);throw e;}
 };
 XMLHttpRequest.prototype.open=function(method,url,...rest){this.__m5Method=String(method).toUpperCase();this.__m5Url=String(url);return s.xhrOpen.call(this,method,url,...rest);};
 XMLHttpRequest.prototype.send=function(...args){if(!['GET','HEAD','OPTIONS'].includes(this.__m5Method)){s.blocked.push({url:this.__m5Url,method:this.__m5Method});throw Error('M5 blocks production writes');}return s.xhrSend.apply(this,args);};
 navigator.sendBeacon=function(url){s.blocked.push({url:String(url),method:'BEACON'});return false;};
 s.waitFor=async predicate=>{const end=performance.now()+15000;while(!predicate()){if(performance.now()>end)throw Error('M5 readiness timed out');await new Promise(requestAnimationFrame);}await new Promise(requestAnimationFrame);};
 s.measure=async(name,action,ready,selector)=>{
  const index=s.requests.length,start=performance.now();await action();await s.waitFor(ready);
  const root=document.querySelector(selector),rect=root?.getBoundingClientRect();
  const row={name,ms:performance.now()-start,viewport:[innerWidth,innerHeight],requests:s.requests.slice(index).map(r=>({...r})),documentNodes:document.querySelectorAll('*').length,rootNodes:root?.querySelectorAll('*').length||0,rootCount:document.querySelectorAll(selector).length,images:root?.querySelectorAll('img').length||0,focusInside:!!root?.contains(document.activeElement),horizontalOverflow:root?root.scrollWidth>root.clientWidth+1:null,rect:rect?{x:rect.x,y:rect.y,width:rect.width,height:rect.height}:null};
  s.samples.push(row);return row;
 };
 sessionStorage.removeItem('uw-pending-draft');
 return {nodes:app.graph._nodes.length,ready:!!window.unifiedDailyControls};
})()
