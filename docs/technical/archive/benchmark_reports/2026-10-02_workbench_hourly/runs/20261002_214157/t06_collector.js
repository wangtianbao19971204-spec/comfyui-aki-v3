(async () => {
  if (window.__m9cT06) throw Error('T06 collector already installed');
  if (!window.__m9b) throw Error('Install the existing M9b fetch/XHR write guard first');
  const {app} = await import('/scripts/app.js');
  const graph = app.graph;
  const graphId = 'a2b12b8e-d5c6-5b86-9dc9-26ab3378cbf8';
  const baseline = 'M9B synthetic 1063';
  if (graph?.id !== graphId || graph.extra?.uap_workbench?.activeBranch !== 'a1') throw Error('Wrong isolated graph or branch');
  const node = graph.getNodeById(1063), sideNode = graph.getNodeById(1030);
  const widget = node?.widgets?.find(w => w.name === 'positive');
  const sideWidget = sideNode?.widgets?.find(w => w.name === 'text');
  const inputs = [...document.querySelectorAll('#uap-daily-desk textarea:not(.negative)')].filter(e => e.value === baseline && e.isConnected);
  if (!widget || widget.value !== baseline || !sideWidget || sideWidget.value !== '' || inputs.length !== 1) throw Error('Isolated baseline or unique UAP positive textarea missing');
  if (node.inputs?.some(i => (i.widget?.name || i.name) === 'positive' && i.link != null)) throw Error('T06 positive input is linked');
  const input = inputs[0];
  const visible = e => !!e && !e.closest('[hidden],[inert]') && e.getClientRects().length > 0;
  if (!visible(input)) throw Error('Initialize T06 while the UAP positive textarea is visible');
  const fixtureId = 'm9c-positive-20261002_214157';
  const categoryId = 'm9c-category-20261002_214157';
  const text = 'M9C_SYNTHETIC_POSITIVE_20261002_214157';
  const inserted = baseline + ', ' + text;
  const revision = 'm9c-isolated-20261002_214157';
  const item = {
    id: fixtureId, alias: 'M9c 隔离正向计时词', prompt: text,
    description: 'T06 browser-only synthetic fixture; never persisted.', image: '', tags: [],
    favorite: false, template: false, is_user_plan: false, usage_count: 0, last_used: null,
    _categoryId: categoryId, _categoryName: 'M9c 隔离计时',
    _semantic: {
      binding: '477108373d1773a147a9faa6c4833ef98ae3ab9608974d1c0304a721aacb91ff',
      disposition: 'classified', content_type: 'fragment', usage: 'positive', declared_usage: 'positive',
      model_scope: 'unknown', themes: [], theme_ids: [], refinements: [], manual_search_eligible: true,
      random_pool_eligible: false, strict_model_pool_eligible: false, semantic_review_status: 'm9c_synthetic_fixture_only'
    }
  };
  const category = {id: categoryId, name: item._categoryName, updated_at: revision, prompt_count: 1, prompts: []};
  const list = {
    last_modified: revision, categories: [category], items: [item], total: 1, offset: 0, limit: 30,
    has_more: false, category_id: '', category_name: '', query: '', view: 'all',
    review_counts: {classified: 1, reviewed: 0, pending: 0},
    filter_counts: {theme: {}, subcategory: {}, count: {}, detail: {}, mode: 'any'}
  };
  const detail = {prompt: item, category, revision, requested_id: fixtureId, redirected: false};
  const fixtureCheck = {
    one_positive_item: list.total === 1 && list.items.length === 1 && item._semantic.usage === 'positive',
    category_count_matches: category.prompt_count === 1 && item._categoryId === category.id,
    detail_matches: detail.requested_id === item.id && detail.prompt.prompt === list.items[0].prompt && detail.prompt._semantic.binding === list.items[0]._semantic.binding,
    synthetic_only: fixtureId.startsWith('m9c-') && categoryId.startsWith('m9c-') && text.startsWith('M9C_SYNTHETIC_')
  };
  if (!Object.values(fixtureCheck).every(Boolean)) throw Error('Fixture consistency check failed');
  const originalFetch = window.fetch;
  const requests = [], blocked = [], samples = [];
  let active = null, cleaned = false;
  const read = (includeGeometry = true) => ({
    valid: app.graph === graph && graph.id === graphId && graph.extra?.uap_workbench?.activeBranch === 'a1' &&
      graph.getNodeById(1063) === node && node.widgets.includes(widget) && graph.getNodeById(1030) === sideNode &&
      sideNode.widgets.includes(sideWidget) && input.isConnected,
    graph_id: graph.id, branch: graph.extra?.uap_workbench?.activeBranch,
    node_id: 1063, node_value: String(widget.value ?? ''), bound_input_value: input.value,
    bound_input_connected: input.isConnected, bound_input_visible: includeGeometry ? visible(input) : null,
    side_node_id: 1030, side_value: String(sideWidget.value ?? ''), side_unchanged: sideWidget.value === '',
    target_status: document.querySelector('#tb-shared-preset-panel .tb-spm-target-status')?.textContent || '',
    hidden: document.hidden, focused: document.hasFocus()
  });
  const matches = (state, expected) => state.valid && state.side_unchanged && state.node_value === expected && state.bound_input_value === expected;
  const response = (data, record) => {
    record.responded_ms = performance.now();
    requests.push(record);
    return new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json', 'ETag': '"' + revision + '"'}});
  };
  const reject = (method, url, reason) => {
    blocked.push({method, path: url.pathname, at_ms: performance.now(), reason});
    throw new TypeError('M9c isolated guard: ' + reason);
  };
  async function fixtureFetch(resource, init) {
    const method = String(init?.method || resource?.method || 'GET').toUpperCase();
    const url = new URL(typeof resource === 'string' || resource instanceof URL ? String(resource) : resource.url, location.href);
    const record = {method, path: url.pathname + url.search, started_ms: performance.now(), synthetic: true};
    if (url.origin === location.origin && method === 'GET') {
      if (url.pathname === '/prompt_selector/library/index' || url.pathname === '/prompt_selector/library/prompts') return response(list, record);
      if (url.pathname === '/prompt_selector/library/prompt') {
        if (url.searchParams.get('prompt_id') !== fixtureId) return reject(method, url, 'non-fixture detail read');
        return response(detail, record);
      }
    }
    if (url.origin === location.origin && method === 'POST' && url.pathname === '/prompt_selector/prompts/mark_used') {
      let body;
      try {body = JSON.parse(init?.body ?? await resource.clone().text());} catch {return reject(method, url, 'invalid mark_used body');}
      if (body.prompt_id !== fixtureId || body.category_id !== categoryId) return reject(method, url, 'non-fixture mark_used');
      record.fixture_id = fixtureId;
      return response({}, record);
    }
    const safeRead = ['GET', 'HEAD', 'OPTIONS'].includes(method);
    const allowedPost = url.origin === location.origin && method === 'POST' && ['/anima-tools/artist-page', '/api/lm/loras/cycler-list', '/danbooru/logs/batch'].includes(url.pathname);
    if (!safeRead && !allowedPost) return reject(method, url, 'write denied');
    return originalFetch.call(this, resource, init);
  }
  const insertSelector = '#tb-shared-preset-panel .tb-spm-card[data-prompt-id="' + fixtureId + '"] [data-act="insert"]';
  const undoSelector = '#tb-shared-preset-panel [data-action="undo-insert"]';
  function arm(kind, metadata = {}) {
    if (cleaned || active) throw Error('T06 unavailable or previous measurement unfinished');
    if (!['insert', 'undo'].includes(kind)) throw Error('Use arm("insert") or arm("undo")');
    const expected = kind === 'insert' ? inserted : baseline;
    const before = read();
    if (!matches(before, kind === 'insert' ? baseline : inserted)) throw Error('T06 precondition failed: target/input/side state');
    const selector = kind === 'insert' ? insertSelector : undoSelector;
    const button = document.querySelector(selector);
    if (!visible(button) || button.disabled) throw Error('T06 target button is unavailable');
    if (kind === 'insert' && button.closest('.tb-spm-card').querySelector('[data-act="insert-mode"]')?.value !== 'append_end') throw Error('Select append_end before arming');
    const panel = document.querySelector('#tb-shared-preset-panel');
    if (!panel) throw Error('T06 library panel is missing');
    let start = null, timer, frame = null, paint1 = null, paint2 = null, observer;
    let nodeAt = null, inputAt = null, bothAt = null, nodeSource = null, inputSource = null, bothSource = null;
    let frames = 0, mutations = 0, microtasks = 0, trusted = null, painting = false, readyResets = 0, currentTail = null;
    const rafTails = [];
    const armAt = performance.now(), requestOffset = requests.length, blockOffset = blocked.length;
    const finish = status => {
      if (!active || active.finish !== finish) return;
      document.removeEventListener('click', begin, true);
      observer?.disconnect();
      clearTimeout(timer);
      [frame, paint1, paint2].forEach(id => id != null && cancelAnimationFrame(id));
      const end = performance.now(), final = read();
      const duration = at => start == null || at == null ? null : at - start;
      const sample = {
        case_id: 'T06_' + kind, ...metadata, status, click_trusted: trusted, collector_version: '2-dom-observer-raf-tail',
        arm_ms: armAt, start_ms: start, end_ms: end,
        node_ready_ms: duration(nodeAt), bound_input_ready_ms: duration(inputAt), both_ready_ms: duration(bothAt),
        node_ready_source: nodeSource, bound_input_ready_source: inputSource, both_ready_source: bothSource,
        paint_opportunity_ms: status === 'ready_after_two_animation_frames' ? duration(end) : null,
        raf_tail_ms: status === 'ready_after_two_animation_frames' && bothAt != null ? end - bothAt : null,
        raf_tails: rafTails, ready_resets: readyResets,
        duration_ms: duration(end), raf_checks: frames, mutation_checks: mutations, microtask_checks: microtasks, before, final,
        synthetic_requests: requests.slice(requestOffset), blocked: blocked.slice(blockOffset),
        scope: 'isolated frontend insertion/undo; synthetic detail and mark_used responses; not backend persistence latency'
      };
      samples.push(sample);
      const waiters = active.waiters;
      active = null;
      waiters.forEach(resolve => resolve(sample));
    };
    const scheduleFallback = () => {
      if (frame != null || painting) return;
      frame = requestAnimationFrame(() => {frame = null; check('raf_fallback');});
    };
    const resetReady = () => {
      if (bothAt != null) readyResets++;
      bothAt = null; bothSource = null; painting = false;
      [paint1, paint2].forEach(id => id != null && cancelAnimationFrame(id));
      paint1 = paint2 = null;
      if (currentTail) currentTail.invalidated = true;
      currentTail = null;
    };
    const stableForPaint = () => {
      if (!active || active.finish !== finish) return false;
      const state = read(false);
      if (!state.valid || !state.side_unchanged) {finish('invalid_target_or_side_changed'); return false;}
      if (state.hidden) {finish('invalid_hidden_document'); return false;}
      if (matches(state, expected)) return true;
      resetReady(); scheduleFallback(); return false;
    };
    const check = source => {
      if (!active || active.finish !== finish) return;
      if (source === 'raf_fallback') frames++;
      else if (source === 'mutation_observer') mutations++;
      else if (source === 'microtask') microtasks++;
      // Do not force geometry/layout while measuring value readiness.
      const state = read(false), now = performance.now();
      if (!state.valid || !state.side_unchanged) return finish('invalid_target_or_side_changed');
      if (state.hidden) return finish('invalid_hidden_document');
      if (state.node_value === expected && nodeAt == null) {nodeAt = now; nodeSource = source;}
      if (state.bound_input_value === expected && inputAt == null) {inputAt = now; inputSource = source;}
      if (matches(state, expected)) {
        if (bothAt == null) {bothAt = now; bothSource = source;}
        if (painting) return;
        painting = true;
        if (frame != null) cancelAnimationFrame(frame);
        frame = null;
        const tail = currentTail = {ready_ms: bothAt - start, ready_source: bothSource, first_requested_ms: performance.now() - start};
        rafTails.push(tail);
        paint1 = requestAnimationFrame(() => {
          paint1 = null;
          tail.first_callback_ms = performance.now() - start;
          tail.first_wait_ms = tail.first_callback_ms - tail.first_requested_ms;
          if (!stableForPaint()) return;
          tail.second_requested_ms = performance.now() - start;
          paint2 = requestAnimationFrame(() => {
            paint2 = null;
            tail.second_callback_ms = performance.now() - start;
            tail.second_wait_ms = tail.second_callback_ms - tail.second_requested_ms;
            if (stableForPaint()) finish('ready_after_two_animation_frames');
          });
        });
      } else {
        if (painting) resetReady();
        scheduleFallback();
      }
    };
    function begin(event) {
      if (!event.target?.closest?.(selector)) return;
      document.removeEventListener('click', begin, true);
      clearTimeout(timer);
      start = performance.now(); trusted = event.isTrusted;
      if (!trusted) return finish('invalid_untrusted_click');
      const state = read();
      if (!matches(state, kind === 'insert' ? baseline : inserted)) return finish('invalid_preclick_state');
      observer = new MutationObserver(() => check('mutation_observer'));
      observer.observe(panel, {childList: true, subtree: true, attributes: true, characterData: true});
      timer = setTimeout(() => finish('timeout_after_click'), 10000);
      queueMicrotask(() => check('microtask'));
    }
    active = {kind, metadata, waiters: [], finish};
    document.addEventListener('click', begin, true);
    timer = setTimeout(() => finish('timeout_waiting_for_click'), 60000);
    return {armed: kind, selector, expected};
  }
  const snapshot = () => structuredClone({
    fixture: {id: fixtureId, category_id: categoryId, prompt: text, baseline, inserted, checks: fixtureCheck},
    samples, requests, blocked, active: active ? {kind: active.kind, metadata: active.metadata} : null,
    current: read(), wrapper_active: window.fetch === fixtureFetch, cleaned,
    collector_version: '2-dom-observer-raf-tail',
    timing: 'Click capture to exact node/input read after relevant panel DOM mutations, with an active-only rAF fallback. Two later rAF callback waits are recorded separately; they are not insertion execution time or proof of painted pixels.'
  });
  window.fetch = fixtureFetch;
  window.__m9cT06 = {
    arm, wait: () => active ? new Promise(resolve => active.waiters.push(resolve)) : Promise.resolve(samples.at(-1)),
    snapshot,
    cleanup: () => {
      active?.finish('cancelled_by_cleanup');
      if (window.fetch !== fixtureFetch) throw Error('T06 cleanup order changed; restore the upper wrapper first');
      window.fetch = originalFetch; cleaned = true;
      const result = snapshot(); delete window.__m9cT06; return result;
    }
  };
  return {installed: true, fixture_id: fixtureId, category_id: categoryId, fixture_checks: fixtureCheck, current: read(), insert_selector: insertSelector, undo_selector: undoSelector};
})()
