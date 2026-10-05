(async () => {
  if (window.__m9cLife) throw Error('Lifecycle collector already installed');
  const {app} = await import('/scripts/app.js');
  const graph = app.graph, graphId = 'a2b12b8e-d5c6-5b86-9dc9-26ab3378cbf8';
  const positive = graph?.getNodeById(1063)?.widgets?.find(w => w.name === 'positive');
  const negative = graph?.getNodeById(1030)?.widgets?.find(w => w.name === 'text');
  if (graph?.id !== graphId || positive?.value !== 'M9B synthetic 1063' || negative?.value !== '') throw Error('Wrong isolated workflow/baseline');
  const branch = graph.extra?.uap_workbench?.activeBranch;
  const native = {setTimeout: window.setTimeout, clearTimeout: window.clearTimeout, setInterval: window.setInterval, clearInterval: window.clearInterval};
  const timerById = new Map(), timerEvents = [], snapshots = [], closes = new Map();
  const counts = {timeout_created: 0, interval_created: 0, timeout_fired: 0, timeout_cleared: 0, interval_cleared: 0, untracked_string_callbacks: 0};
  const installedAt = performance.now();
  let cleaned = false;
  const ownerPattern = /(?:anima_clothing_selector|anima_shared_prompt_data|workbench_shell)\.js(?::|\?|$)/;
  const origin = () => String(new Error().stack || '').split('\n').find(line => ownerPattern.test(line))?.trim() || null;
  const event = data => {if (timerEvents.length < 2000) timerEvents.push(data);};
  const track = (id, kind, delay, owner) => {
    const record = {id: String(id), kind, requested_delay_ms: Number.isFinite(Number(delay)) ? Number(delay) : null, registered_ms: performance.now(), owner_frame: owner};
    timerById.set(id, record); counts[kind + '_created']++; event({event: 'created', ...record});
  };
  const retire = (id, why) => {
    const record = timerById.get(id);
    if (!record) return;
    timerById.delete(id); counts[record.kind + '_' + why]++; event({event: why, ...record, finished_ms: performance.now()});
  };
  function setTimeoutObserved(callback, delay, ...args) {
    const owner = origin();
    if (!owner) return native.setTimeout.call(this, callback, delay, ...args);
    if (typeof callback !== 'function') {counts.untracked_string_callbacks++; return native.setTimeout.call(this, callback, delay, ...args);}
    let id;
    // Only the browser-scheduled wrapper holds callback. The metadata map/events do not store callbacks or DOM targets.
    id = native.setTimeout.call(this, function(...callbackArgs) {
      retire(id, 'fired');
      return Reflect.apply(callback, this, callbackArgs);
    }, delay, ...args);
    track(id, 'timeout', delay, owner);
    return id;
  }
  function setIntervalObserved(callback, delay, ...args) {
    const owner = origin();
    const id = native.setInterval.call(this, callback, delay, ...args);
    if (owner) {
      if (typeof callback !== 'function') counts.untracked_string_callbacks++;
      track(id, 'interval', delay, owner);
    }
    return id;
  }
  function clearTimeoutObserved(id) {retire(id, 'cleared'); return native.clearTimeout.call(this, id);}
  function clearIntervalObserved(id) {retire(id, 'cleared'); return native.clearInterval.call(this, id);}
  const wrappers = {setTimeout: setTimeoutObserved, clearTimeout: clearTimeoutObserved, setInterval: setIntervalObserved, clearInterval: clearIntervalObserved};
  const identity = () => ({
    valid: app.graph === graph && graph.id === graphId && graph.extra?.uap_workbench?.activeBranch === branch &&
      graph.getNodeById(1063)?.widgets?.includes(positive) && graph.getNodeById(1030)?.widgets?.includes(negative),
    graph_id: graph.id, branch: graph.extra?.uap_workbench?.activeBranch,
    positive: positive.value, negative: negative.value,
    prompts_unchanged: positive.value === 'M9B synthetic 1063' && negative.value === ''
  });
  const dom = () => {
    const workbench = document.querySelector('#unified-workbench');
    const overlay = document.querySelector('#anima-clothing-selector-overlay');
    return {
      clothing_overlays: document.querySelectorAll('#anima-clothing-selector-overlay').length,
      clothing_cards: document.querySelectorAll('#anima-clothing-selector-overlay .anima-clothing-card').length,
      clothing_descendants: overlay?.querySelectorAll('*').length || 0,
      workbench_count: document.querySelectorAll('#unified-workbench').length,
      workbench_descendants: workbench?.querySelectorAll('*').length || 0,
      workbench_visible: !!workbench && !workbench.closest('[hidden],[inert]') && workbench.getClientRects().length > 0,
      total_document_elements: document.querySelectorAll('*').length,
      focus: document.activeElement?.getAttribute('aria-label') || document.activeElement?.textContent?.trim().slice(0, 100) || document.activeElement?.tagName || null
    };
  };
  const timers = () => ({
    scope: 'Only timers registered after collector installation with a matching source frame; not a full-page or pre-installation enumeration',
    source_patterns: ['anima_clothing_selector.js', 'anima_shared_prompt_data.js', 'workbench_shell.js'],
    counts: {...counts}, active: [...timerById.values()],
    active_timeouts: [...timerById.values()].filter(t => t.kind === 'timeout').length,
    active_intervals: [...timerById.values()].filter(t => t.kind === 'interval').length,
    event_count: timerEvents.length,
    callbacks_retained_in_metadata: false
  });
  function markClosed(cycle) {
    if (cleaned || !Number.isInteger(cycle) || cycle < 0 || cycle > 10) throw Error('Invalid lifecycle cycle');
    const state = identity(), dimensions = dom();
    if (!state.valid || !state.prompts_unchanged || dimensions.clothing_overlays || dimensions.clothing_cards) throw Error('Close selector and preserve isolated prompts before markClosed');
    const marker = {cycle, closed_at_ms: performance.now(), wall_time: new Date().toISOString(), dom: dimensions};
    closes.set(cycle, marker);
    return marker;
  }
  function sample(cycle) {
    const marker = closes.get(cycle), now = performance.now();
    if (cleaned || ![0, 5, 10].includes(cycle) || !marker || now - marker.closed_at_ms < 5000) throw Error('Sample cycle 0/5/10 at least 5000ms after markClosed');
    if (snapshots.some(s => s.cycle === cycle)) throw Error('Cycle already sampled; preserve one observation per checkpoint');
    const state = identity(), dimensions = dom();
    if (!state.valid || !state.prompts_unchanged || dimensions.clothing_overlays || dimensions.clothing_cards) throw Error('Closed-state/isolated-prompt guard failed');
    const memory = performance.memory;
    const entries = performance.getEntriesByType('resource').filter(r => r.startTime >= marker.closed_at_ms && r.name.startsWith(location.origin));
    const row = {
      cycle, wall_time: new Date().toISOString(), sample_ms: now, closed_at_ms: marker.closed_at_ms,
      settled_ms: now - marker.closed_at_ms, visibility: document.visibilityState, focused: document.hasFocus(),
      identity: state, dom: dimensions,
      page_js_heap: memory ? {used_bytes: memory.usedJSHeapSize, total_bytes: memory.totalJSHeapSize, limit_bytes: memory.jsHeapSizeLimit, source: 'performance.memory; may be coarse'} : {status: 'unavailable'},
      source_attributed_new_timers: timers(),
      settle_requests: entries.map(r => ({path: r.name.slice(location.origin.length), start_ms_after_close: r.startTime - marker.closed_at_ms, duration_ms: r.duration, transfer_bytes: r.transferSize, initiator: r.initiatorType})),
      global_listener_evidence: 'Attach separate CDP DOMDebugger.getEventListeners(window/document) filtered by the matching executed-source scriptIds; do not substitute a whole-page count',
      renderer_rss: {status: 'unavailable', reason: 'No reliably mapped renderer PID in this collector'},
      service_rss: {status: 'attach_companion_lifecycle_service_sample', same_cycle: cycle}
    };
    snapshots.push(row);
    return structuredClone(row);
  }
  const snapshot = () => structuredClone({version: 'm9c-lifecycle-1', installed_at_ms: installedAt, cleaned, samples: snapshots, closed_markers: [...closes.values()], timers: timers(), timer_events: timerEvents});
  for (const [key, wrapper] of Object.entries(wrappers)) window[key] = wrapper;
  window.__m9cLife = {
    markClosed, sample, snapshot,
    cleanup() {
      if (Object.entries(wrappers).some(([key, wrapper]) => window[key] !== wrapper)) throw Error('Another timer wrapper is above M9c; restore it first');
      for (const [key, original] of Object.entries(native)) window[key] = original;
      cleaned = true;
      const receipt = snapshot(); delete window.__m9cLife; return receipt;
    }
  };
  return {installed: true, version: 'm9c-lifecycle-1', baseline: identity(), dom: dom(), timer_scope: timers().scope, next: 'markClosed(0); wait at least 5 seconds; sample(0) and collect same-cycle CDP/service resources'};
})()
