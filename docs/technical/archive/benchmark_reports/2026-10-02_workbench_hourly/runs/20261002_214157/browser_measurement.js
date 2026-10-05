(() => {
  if (window.__m9b) throw Error('Collector already installed');
  const originalFetch = window.fetch;
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  const xhrRequests = new WeakMap();
  const blocked = [];
  let syntheticLogAcks = 0;
  const permitted = (method, url) => ['GET', 'HEAD', 'OPTIONS'].includes(method) ||
    (method === 'POST' && ['/anima-tools/artist-page','/api/lm/loras/cycler-list'].includes(new URL(url, location.href).pathname));
  window.fetch = function(input, init) {
    const method = String(init?.method || input?.method || 'GET').toUpperCase();
    const url = typeof input === 'string' ? input : input.url;
    if (method === 'POST' && new URL(url, location.href).pathname === '/danbooru/logs/batch') {
      syntheticLogAcks++;
      return Promise.resolve(new Response('{}', {status:200, headers:{'Content-Type':'application/json'}}));
    }
    if (!permitted(method, url)) {
      blocked.push({method, path:new URL(url, location.href).pathname, at:performance.now()});
      return Promise.reject(new TypeError('M9b isolated write guard'));
    }
    return originalFetch.apply(this, arguments);
  };
  XMLHttpRequest.prototype.open = function(method, url) {
    xhrRequests.set(this, {method:String(method).toUpperCase(), url});
    return originalOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function() {
    const r = xhrRequests.get(this);
    if (r && !permitted(r.method, r.url)) {
      blocked.push({method:r.method, path:new URL(r.url, location.href).pathname, at:performance.now()});
      throw new DOMException('M9b isolated write guard', 'AbortError');
    }
    return originalSend.apply(this, arguments);
  };
  const visible = e => !!e && !e.closest('[hidden],[inert]') && e.getClientRects().length > 0;
  const allReady = {
    T01: () => visible(document.querySelector('#uap-daily-desk')) && !!document.querySelector('#uap-daily-desk fieldset:not(:disabled) input[aria-label="宽度"]'),
    T02: () => !!document.querySelector('#unified-workbench[data-page="workspace"] .uw-native-daily #uap-daily-desk[data-workbench-mounted] fieldset:not(:disabled)') && visible(document.querySelector('#unified-workbench [data-uw="page-workspace"][aria-current="page"]')),
    T03: () => document.querySelector('#uap-daily-desk input[aria-label="查找常用控制项"]')?.value === '尺寸' && document.querySelector('#uap-daily-desk fieldset')?.dataset.filtering === 'true' && visible(document.querySelector('#uap-daily-desk section[data-desk-area="parameters"]')) && document.querySelector('#uap-daily-desk .desk-find-bar > [role="status"]')?.textContent === '找到 1 个区域',
    T04: (query='hoodie') => [...document.querySelectorAll('#unified-workbench .uw-page:not([hidden])')].some(p => p.querySelector('h2')?.textContent === `搜索：${query}` && p.querySelectorAll('.uw-result-section').length === 5 && !p.querySelector('[aria-busy="true"],[data-uw="results-retry"]') && ['prompts','tags','loras','checkpoints','embeddings'].every(k => p.querySelector(`[data-uw="results-more-${k}"]`))),
    T05_clothing: () => visible(document.querySelector('#unified-workbench .uw-native-selector #anima-clothing-selector-overlay[data-unified-embedded="true"] .anima-clothing-card[data-key]')),
    T05_artist: () => {const root=document.querySelector('#unified-workbench .uw-native-selector #anima-selector-overlay[data-unified-embedded="true"]');return visible(root?.querySelector('.anima-artist-list:not([inert]) > [data-key]')) && !root.querySelector('[role="alert"]') && !/正在筛选|失败/.test(root.querySelector('.anima-pagination-stats')?.textContent || '');}
  };
  const samples = [];
  let active;
  function arm(spec) {
    if (active) throw Error('Unfinished measurement');
    let start, readyAt, observer, timer, painting = false, mutationChecks=0;
    const finish = result => {
      document.removeEventListener(spec.event, begin, true);
      observer?.disconnect(); clearTimeout(timer);
      const end=performance.now();
      const entries=start == null ? [] : performance.getEntriesByType('resource').filter(r => r.startTime >= start && r.startTime <= end && r.name.startsWith(location.origin) && !r.name.includes('/api/jobs'));
      samples.push({...spec,...result,start_ms:start,dom_ready_ms:readyAt,end_ms:end,dom_duration_ms:readyAt == null ? null : readyAt-start,duration_ms:start == null ? null : end-start,mutation_checks:mutationChecks,hidden:document.hidden,focused:document.hasFocus(),requests:entries.map(r=>({path:r.name.slice(location.origin.length),start_ms:r.startTime-start,duration_ms:r.duration,transfer_bytes:r.transferSize,encoded_bytes:r.encodedBodySize,initiator:r.initiatorType}))});
      active?.waiters.forEach(resolve=>resolve(samples.at(-1)));
      active=null;
    };
    const check = () => {
      mutationChecks++;
      if (!allReady[spec.case_id](spec.query) || painting) return;
      readyAt ??= performance.now();
      painting=true;
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        painting=false;
        if (active && allReady[spec.case_id](spec.query)) finish({status:'ready_after_two_animation_frames'});
      }));
    };
    function begin(e) {
      const target=e.target.closest(spec.selector);
      if (!target || (spec.text && target.textContent.trim() !== spec.text) || (spec.value && target.value !== spec.value)) return;
      document.removeEventListener(spec.event, begin, true);
      start=performance.now();
      observer=new MutationObserver(check); observer.observe(document.body,{childList:true,subtree:true,attributes:true,characterData:true});
      timer=setTimeout(()=>finish({status:'timeout'}),10000);
      queueMicrotask(check);
    }
    active={spec,waiters:[],cancel:()=>finish({status:'cancelled'})};
    document.addEventListener(spec.event,begin,true);
  }
  const snapshot = () => ({samples,blocked,syntheticLogAcks,active:active?.spec || null,viewport:[innerWidth,innerHeight],hidden:document.hidden,focus:document.hasFocus(),heap:performance.memory?.usedJSHeapSize});
  window.__m9b={arm,snapshot,wait:()=>active ? new Promise(resolve=>active.waiters.push(resolve)) : Promise.resolve(samples.at(-1)),ready:id=>allReady[id](),cleanup:()=>{active?.cancel();window.fetch=originalFetch;XMLHttpRequest.prototype.open=originalOpen;XMLHttpRequest.prototype.send=originalSend;delete window.__m9b;}};
  performance.setResourceTimingBufferSize(3000);
  return {installed:true,readyChecks:Object.keys(allReady)};
})()
