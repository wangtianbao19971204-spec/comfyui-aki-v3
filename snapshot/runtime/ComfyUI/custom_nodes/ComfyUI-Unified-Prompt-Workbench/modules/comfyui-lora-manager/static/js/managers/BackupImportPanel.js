// BackupImportPanel.mjs
// Standalone, dependency-free interaction module for the native model backup workflow.
// Injected API adapter; no backend URLs, no settings/cache, no page reload.

const NS = 'bip';
const STORAGE_KEY = 'bip.operation_id.v1';
const DEFAULT_TIMEOUT_MS = 30000;
const POLL_INTERVAL_MS = 1000;

const TERMINAL = new Set(['completed', 'partial', 'cancelled', 'failed']);

const ZH = {
  title: '备份导入',
  fileLabel: '备份文件',
  noFile: '尚未选择文件',
  previewing: '正在解析预览…',
  counts: '预览统计',
  cNew: '新增',
  cUpdated: '更新',
  cDup: '疑似重复',
  cUnsupported: '不支持',
  cConflict: '版本冲突',
  existingLabel: '已有模型处理方式',
  skip: '跳过',
  overwrite: '覆盖',
  writeSkip: '将写入 / 将跳过',
  confirm: '确认恢复',
  cancel: '取消任务',
  export: '导出结果',
  recover: '恢复上次任务',
  close: '关闭',
  status: '状态',
  units: '明细',
  persistFail: '无法持久化恢复令牌：关闭页面后可能无法恢复，本次会话内仍可恢复。',
  persistFailMemory: '恢复令牌仅保存在内存中，关闭页面后无法恢复。',
  cryptoFail: '当前环境缺少加密随机数支持，无法安全确认恢复。',
  protocolError: '后端响应标识不匹配，已忽略该结果。',
  timeout: '请求超时（未确认后端状态）。',
  refreshNeeded: '后端提示需要刷新。请手动操作，界面不会自动重载。',
  partialWarn: '部分完成，并非全部成功。',
  cancelled: '任务已取消。',
  failed: '任务失败。',
  completed: '已完成。',
  unknown: '未知',
  unknownWarn: '状态未知，自动轮询已停止，请手动恢复。',
  running: '进行中',
  committed: '已写入',
  failedCount: '失败',
  skippedCount: '已跳过',
  pendingCount: '待处理',
  unknownCount: '未知',
  cancelledCount: '已取消',
  exportFail: '导出失败：',
  recoverNone: '没有可恢复的任务。',
  recoverWorking: '正在查询上次任务…',
};

function makeUuid(doc) {
  const w = doc && doc.defaultView;
  if (w && w.crypto && typeof w.crypto.randomUUID === 'function') return w.crypto.randomUUID();
  if (typeof crypto !== 'undefined' && crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return null;
}

function fmtCount(c) {
  if (c === null || c === undefined) return ZH.unknown;
  if (typeof c !== 'number' || Number.isNaN(c)) return ZH.unknown;
  return String(c);
}

function errMessage(e) {
  if (!e) return 'unknown';
  if (e.message === '__timeout__') return ZH.timeout;
  return String(e.message || e);
}

export function createBackupImportPanel({ document: doc, api, storage, onCompleted } = {}) {
  if (!doc) throw new Error('document required');
  if (!api || typeof api.preview !== 'function' || typeof api.start !== 'function' || typeof api.status !== 'function') {
    throw new Error('api adapter with preview/start/status required');
  }

  const state = {
    destroyed: false,
    open: false,
    gen: 0,
    file: null,
    options: { existing: 'skip', selected_indices: null },
    plan: null,
    planGen: 0,
    previewing: false,
    activeId: null,
    savedId: null,
    memoryOnly: false,
    persistFailed: false,
    started: false,
    startInflight: false,
    job: null,
    terminalSeen: new Set(),
    pollTimer: null,
    cancelInflight: false,
    exporting: false,
    lastFocus: null,
    recovering: false,
  };

  const els = {};
  let root = null;
  const timers = new Set();
  const callsInFlight = new Set();

  // ---- timeout-wrapped adapter call with tracked timer ----
  function callAdapter(fn) {
    const ms = DEFAULT_TIMEOUT_MS;
    return new Promise((resolve, reject) => {
      let settled = false;
      const t = setTimeout(() => {
        settled = true;
        timers.delete(t);
        reject(new Error('__timeout__'));
      }, ms);
      timers.add(t);
      Promise.resolve()
        .then(fn)
        .then((v) => {
          if (settled) return;
          settled = true;
          timers.delete(t);
          clearTimeout(t);
          resolve(v);
        })
        .catch((e) => {
          if (settled) return;
          settled = true;
          timers.delete(t);
          clearTimeout(t);
          reject(e);
        });
    });
  }

  function track(p) {
    const tracked = p.then(
      (v) => { callsInFlight.delete(tracked); return v; },
      (e) => { callsInFlight.delete(tracked); throw e; }
    );
    callsInFlight.add(tracked);
    return tracked;
  }

  function clearTimers() {
    for (const t of timers) clearTimeout(t);
    timers.clear();
  }

  // ---- storage ----
  function readSaved() {
    if (!storage) return null;
    try {
      const v = storage.getItem(STORAGE_KEY);
      return typeof v === 'string' && v.length ? v : null;
    } catch (_) { return null; }
  }
  function writeSaved(id) {
    state.savedId = id;
    if (!storage) {
      state.persistFailed = true; state.memoryOnly = true; return false;
    }
    try {
      storage.setItem(STORAGE_KEY, id);
      state.persistFailed = false; state.memoryOnly = false; return true;
    } catch (_) {
      state.persistFailed = true; state.memoryOnly = true; return false;
    }
  }
  function clearSavedIfMatches(id) {
    if (state.savedId === id) state.savedId = null;
    state.memoryOnly = false;
    state.persistFailed = false;
    if (!storage) return;
    try {
      const cur = storage.getItem(STORAGE_KEY);
      if (cur === id) storage.removeItem(STORAGE_KEY);
    } catch (_) {}
  }

  // ---- session helpers ----
  function sessionAlive(gen) { return !state.destroyed && state.open && gen === state.gen; }
  function beginSession() { state.gen += 1; return state.gen; }
  function endSession() { state.gen += 1; }

  function stopPolling() {
    if (state.pollTimer !== null) { clearTimeout(state.pollTimer); state.pollTimer = null; }
  }
  function startPolling(gen) {
    stopPolling();
    if (!state.activeId) return;
    state.pollTimer = setTimeout(() => {
      state.pollTimer = null;
      if (!sessionAlive(gen)) return;
      pollOnce(gen);
    }, POLL_INTERVAL_MS);
  }
  async function pollOnce(gen) {
    if (!state.activeId) return;
    const id = state.activeId;
    try {
      const job = await track(callAdapter(() => api.status(id)));
      if (!sessionAlive(gen)) return;
      applyJob(job, id, gen);
    } catch (_) {}
    const j = state.job;
    if (j && j.status === 'running' && sessionAlive(gen)) startPolling(gen);
  }

  // ---- DOM ----
  function el(tag, cls, text) {
    const e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function buildDOM() {
    root = el('div', NS + '-overlay');
    root.setAttribute('data-bip', '1');
    // Keep every panel interaction away from dialogs underneath: their
    // outside-click handlers must not treat panel clicks as background clicks.
    for (const type of ['mousedown', 'mouseup', 'click', 'dblclick']) {
      root.addEventListener(type, (event) => event.stopPropagation());
    }
    const dialog = el('div', NS + '-dialog');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', NS + '-title');
    root.appendChild(dialog);
    els.dialog = dialog;
    els.title = el('h2', NS + '-title', ZH.title);
    els.title.id = NS + '-title';
    dialog.appendChild(els.title);

    els.fileInfo = el('div', NS + '-fileinfo', ZH.noFile);
    dialog.appendChild(els.fileInfo);

    els.preview = el('div', NS + '-preview');
    els.preview.appendChild(el('div', NS + '-section', ZH.counts));
    els.cNew = el('div', NS + '-count');
    els.cUpdated = el('div', NS + '-count');
    els.cDup = el('div', NS + '-count');
    els.cUnsupported = el('div', NS + '-count');
    els.cConflict = el('div', NS + '-count');
    [els.cNew, els.cUpdated, els.cDup, els.cUnsupported, els.cConflict].forEach((c) => els.preview.appendChild(c));
    dialog.appendChild(els.preview);

    els.existingWrap = el('div', NS + '-existing');
    const existingLabel = el('label', NS + '-label', ZH.existingLabel);
    els.existingSelect = doc.createElement('select');
    els.existingSelect.className = NS + '-select';
    els.existingSelect.id = NS + '-existing-select';
    existingLabel.setAttribute('for', els.existingSelect.id);
    const optSkip = doc.createElement('option'); optSkip.value = 'skip'; optSkip.textContent = ZH.skip;
    const optOver = doc.createElement('option'); optOver.value = 'overwrite'; optOver.textContent = ZH.overwrite;
    els.existingSelect.appendChild(optSkip);
    els.existingSelect.appendChild(optOver);
    els.existingWrap.appendChild(existingLabel);
    els.existingWrap.appendChild(els.existingSelect);
    dialog.appendChild(els.existingWrap);

    els.writeSkip = el('div', NS + '-writeskip', '');
    dialog.appendChild(els.writeSkip);

    els.notice = el('div', NS + '-notice');
    els.notice.setAttribute('role', 'status');
    els.notice.setAttribute('aria-live', 'polite');
    dialog.appendChild(els.notice);

    els.status = el('div', NS + '-status');
    dialog.appendChild(els.status);

    els.unitsLabel = el('div', NS + '-section', ZH.units);
    els.unitsLabel.style.display = 'none';
    els.units = el('ul', NS + '-units');
    dialog.appendChild(els.unitsLabel);
    dialog.appendChild(els.units);

    els.buttons = el('div', NS + '-buttons');
    els.confirm = el('button', NS + '-btn ' + NS + '-btn-primary', ZH.confirm);
    els.confirm.type = 'button'; els.confirm.disabled = true;
    els.cancel = el('button', NS + '-btn', ZH.cancel);
    els.cancel.type = 'button'; els.cancel.disabled = true;
    els.export = el('button', NS + '-btn', ZH.export);
    els.export.type = 'button'; els.export.disabled = true;
    els.recover = el('button', NS + '-btn', ZH.recover);
    els.recover.type = 'button';
    els.close = el('button', NS + '-btn', ZH.close);
    els.close.type = 'button';
    [els.confirm, els.cancel, els.export, els.recover, els.close].forEach((b) => els.buttons.appendChild(b));
    dialog.appendChild(els.buttons);

    els.confirm.addEventListener('click', onConfirm);
    els.cancel.addEventListener('click', onCancel);
    els.export.addEventListener('click', onExport);
    els.recover.addEventListener('click', onRecover);
    els.close.addEventListener('click', onClose);
    els.existingSelect.addEventListener('change', onExistingChange);
  }

  // ---- render ----
  function renderPreview() {
    const p = state.plan;
    if (!p || !p.counts) {
      els.cNew.textContent = ZH.cNew + '：' + ZH.unknown;
      els.cUpdated.textContent = ZH.cUpdated + '：' + ZH.unknown;
      els.cDup.textContent = ZH.cDup + '：' + ZH.unknown;
      els.cUnsupported.textContent = ZH.cUnsupported + '：' + ZH.unknown;
      els.cConflict.textContent = ZH.cConflict + '：' + ZH.unknown;
      els.writeSkip.textContent = '';
      return;
    }
    const c = p.counts || {};
    els.cNew.textContent = ZH.cNew + '：' + fmtCount(c.new);
    els.cUpdated.textContent = ZH.cUpdated + '：' + fmtCount(c.updated);
    els.cDup.textContent = ZH.cDup + '：' + fmtCount(c.suspected_duplicate);
    els.cUnsupported.textContent = ZH.cUnsupported + '：' + fmtCount(c.unsupported);
    els.cConflict.textContent = ZH.cConflict + '：' + fmtCount(c.version_conflict);
    const wc = Array.isArray(p.will_write) ? p.will_write.length : 0;
    const sc = Array.isArray(p.will_skip) ? p.will_skip.length : 0;
    els.writeSkip.textContent = ZH.writeSkip + '：' + wc + ' / ' + sc;
  }

  function renderUnits(units) {
    while (els.units.firstChild) els.units.removeChild(els.units.firstChild);
    if (!Array.isArray(units) || units.length === 0) { els.unitsLabel.style.display = 'none'; return; }
    els.unitsLabel.style.display = '';
    for (const u of units) {
      const li = el('li', NS + '-unit');
      const name = u && (u.member || u.index);
      li.appendChild(el('span', NS + '-unit-name', String(name == null ? '' : name)));
      const details = [];
      if (u && u.kind) details.push(String(u.kind));
      if (u && u.category) details.push(String(u.category));
      if (u && u.action) details.push(String(u.action));
      if (u && u.state) details.push(String(u.state));
      if (u && u.reason) details.push(String(u.reason));
      if (details.length) li.appendChild(el('span', NS + '-unit-detail', details.join(' · ')));
      els.units.appendChild(li);
    }
  }

  function jobStatusLabel(s) {
    switch (s) {
      case 'running': return ZH.running;
      case 'completed': return ZH.completed;
      case 'partial': return ZH.partialWarn;
      case 'cancelled': return ZH.cancelled;
      case 'failed': return ZH.failed;
      case 'unknown': return ZH.unknown;
      default: return ZH.unknown;
    }
  }

  function renderJob() {
    const j = state.job;
    if (!j) { els.status.textContent = ''; renderUnits([]); return; }
    const parts = [ZH.status + '：' + jobStatusLabel(j.status)];
    if (j.counts && typeof j.counts === 'object') {
      const c = j.counts;
      parts.push(ZH.committed + ' ' + fmtCount(c.committed));
      parts.push(ZH.failedCount + ' ' + fmtCount(c.failed));
      parts.push(ZH.cancelledCount + ' ' + fmtCount(c.cancelled));
      parts.push(ZH.skippedCount + ' ' + fmtCount(c.skipped));
      parts.push(ZH.pendingCount + ' ' + fmtCount(c.pending));
      parts.push(ZH.unknownCount + ' ' + fmtCount(c.unknown));
    }
    els.status.textContent = parts.join(' · ');
    renderUnits(j.units);
  }

  function setNotice(text, kind) {
    els.notice.textContent = text || '';
    els.notice.className = NS + '-notice' + (kind ? ' ' + NS + '-notice-' + kind : '');
  }

  function setBusyPreview(busy) {
    state.previewing = busy;
    els.existingSelect.disabled = busy;
    updateConfirmEnabled();
    if (busy) setNotice(ZH.previewing);
  }

  function updateConfirmEnabled() {
    const can = !!state.plan && state.plan.committable === true && !state.previewing
      && !state.started && !state.startInflight && !state.recovering;
    els.confirm.disabled = !can;
  }

  function updateActionButtons() {
    const j = state.job;
    const running = j && j.status === 'running';
    els.cancel.disabled = !running || state.cancelInflight;
    els.export.disabled = !state.activeId || state.exporting;
    els.recover.disabled = state.started && running;
  }

  function renderAll() {
    els.fileInfo.textContent = state.file && state.file.name ? String(state.file.name) : ZH.noFile;
    renderPreview();
    renderJob();
    updateActionButtons();
    updateConfirmEnabled();
  }

  // ---- preview ----
  async function runPreview() {
    if (!state.file || state.started || state.startInflight) return;
    const gen = state.planGen + 1;
    state.planGen = gen;
    state.plan = null;
    renderPreview();
    updateConfirmEnabled();
    setBusyPreview(true);
    const session = state.gen;
    const optionsSnapshot = { existing: state.options.existing, selected_indices: state.options.selected_indices };
    try {
      const res = await track(callAdapter(() => api.preview(state.file, optionsSnapshot)));
      if (!sessionAlive(session) || gen !== state.planGen) return;
      const plan = res && res.plan;
      if (!res || typeof res.upload_id !== 'string' || !plan || typeof plan.plan_hash !== 'string') {
        setNotice(ZH.protocolError, 'warn');
        state.plan = null;
        return;
      }
      state.plan = {
        upload_id: res.upload_id,
        plan_hash: plan.plan_hash,
        committable: plan.committable === true,
        counts: plan.counts || null,
        will_write: plan.will_write,
        will_skip: plan.will_skip,
        units: plan.units,
        options: optionsSnapshot,
      };
      setNotice('');
    } catch (e) {
      if (!sessionAlive(session) || gen !== state.planGen) return;
      setNotice(errMessage(e), 'error');
      state.plan = null;
    } finally {
      if (sessionAlive(session) && gen === state.planGen) {
        setBusyPreview(false);
        renderPreview();
        updateConfirmEnabled();
      }
    }
  }

  function invalidatePlan() {
    state.plan = null;
    state.planGen += 1;
    renderPreview();
    updateConfirmEnabled();
  }

  function onExistingChange() {
    const v = els.existingSelect.value;
    const next = v === 'overwrite' ? 'overwrite' : 'skip';
    if (next === state.options.existing) return;
    state.options = { existing: next, selected_indices: null };
    invalidatePlan();
    if (state.file && !state.started && !state.startInflight) runPreview();
  }

  // ---- start ----
  function onConfirm() {
    if (state.started || state.startInflight || state.recovering) return;
    if (!state.plan || state.plan.committable !== true) return;
    if (!state.file) return;
    const id = makeUuid(doc);
    if (!id) { setNotice(ZH.cryptoFail, 'error'); return; }

    const plan = state.plan;
    const ok = writeSaved(id);
    state.activeId = id;
    state.started = true;
    state.startInflight = true;
    if (!ok) setNotice(state.memoryOnly && !storage ? ZH.persistFailMemory : ZH.persistFail, 'warn');
    else setNotice('');

    const payload = {
      upload_id: plan.upload_id,
      plan_hash: plan.plan_hash,
      options: { existing: plan.options.existing, selected_indices: plan.options.selected_indices },
      operation_id: id,
    };
    updateConfirmEnabled();
    updateActionButtons();
    const session = state.gen;
    track(callAdapter(() => api.start(payload)))
      .then((job) => {
        if (!sessionAlive(session)) return;
        state.startInflight = false;
        if (!job || job.operation_id !== id || state.activeId !== id) {
          setNotice(ZH.protocolError, 'warn');
          reconcile(id, session);
          return;
        }
        applyJob(job, id, session);
        if (job.status === 'running') startPolling(session);
      })
      .catch(() => {
        if (!sessionAlive(session)) return;
        state.startInflight = false;
        reconcile(id, session);
      });
  }

  async function reconcile(id, session) {
    if (state.activeId !== id) return;
    try {
      const job = await track(callAdapter(() => api.status(id)));
      if (!sessionAlive(session) || state.activeId !== id) return;
      applyJob(job, id, session);
      if (job && job.status === 'running') startPolling(session);
    } catch (_) {}
  }

  function applyJob(job, expectedId, session) {
    if (!job) return;
    if (job.operation_id !== expectedId) { setNotice(ZH.protocolError, 'warn'); return; }
    if (state.activeId && state.activeId !== expectedId) { setNotice(ZH.protocolError, 'warn'); return; }
    if (session !== undefined && !sessionAlive(session)) return;
    state.job = job;
    state.activeId = job.operation_id;
    state.startInflight = false;
    if (job.refresh_required) setNotice(ZH.refreshNeeded, 'warn');
    if (job.status === 'unknown') { stopPolling(); setNotice(ZH.unknownWarn, 'warn'); }
    if (TERMINAL.has(job.status)) { stopPolling(); maybeComplete(job); }
    renderJob();
    updateActionButtons();
  }

  function maybeComplete(job) {
    const id = job.operation_id;
    if (state.terminalSeen.has(id)) return;
    state.terminalSeen.add(id);
    clearSavedIfMatches(id);
    try { if (typeof onCompleted === 'function') onCompleted(job); } catch (_) {}
  }

  // ---- cancel / export / recover ----
  function onCancel() {
    const j = state.job;
    if (!j || j.status !== 'running' || !state.activeId) return;
    if (state.cancelInflight) return;
    state.cancelInflight = true;
    updateActionButtons();
    const id = state.activeId;
    const session = state.gen;
    track(callAdapter(() => api.cancel(id)))
      .then((job) => {
        if (!sessionAlive(session) || state.activeId !== id) return;
        state.cancelInflight = false;
        if (job && job.operation_id === id) applyJob(job, id, session);
        else if (job) setNotice(ZH.protocolError, 'warn');
        updateActionButtons();
      })
      .catch((e) => {
        if (!sessionAlive(session)) return;
        state.cancelInflight = false;
        setNotice(errMessage(e), 'error');
        updateActionButtons();
      });
  }

  function onExport() {
    if (!state.activeId || state.exporting) return;
    if (typeof api.export !== 'function') return;
    state.exporting = true;
    updateActionButtons();
    const id = state.activeId;
    const session = state.gen;
    track(callAdapter(() => api.export(id)))
      .then((manifest) => {
        if (!sessionAlive(session)) return;
        state.exporting = false;
        downloadManifest(manifest, id);
        updateActionButtons();
      })
      .catch((e) => {
        if (!sessionAlive(session)) return;
        state.exporting = false;
        setNotice(ZH.exportFail + errMessage(e), 'error');
        updateActionButtons();
      });
  }

  function downloadManifest(manifest, id) {
    const w = doc.defaultView || (typeof window !== 'undefined' ? window : null);
    if (!w) return;
    let text;
    try { text = JSON.stringify(manifest === undefined ? null : manifest, null, 2); }
    catch (_) { setNotice(ZH.exportFail + 'invalid manifest', 'error'); return; }
    let url = null;
    try {
      const blob = new w.Blob([text], { type: 'application/json' });
      url = w.URL.createObjectURL(blob);
      const a = doc.createElement('a');
      a.href = url;
      a.download = 'backup-import-' + id + '.json';
      a.rel = 'noopener';
      doc.body.appendChild(a);
      a.click();
      doc.body.removeChild(a);
    } catch (_) {
      setNotice(ZH.exportFail + 'download', 'error');
    } finally {
      if (url) { try { w.URL.revokeObjectURL(url); } catch (_) {} }
    }
  }

  function onRecover() {
    const id = state.savedId || readSaved();
    if (!id) { setNotice(ZH.recoverNone, 'warn'); return; }
    state.savedId = id;
    state.activeId = id;
    state.started = true;
    state.recovering = true;
    invalidatePlan();
    setNotice(ZH.recoverWorking);
    updateActionButtons();
    const session = state.gen;
    track(callAdapter(() => api.status(id)))
      .then((job) => {
        if (!sessionAlive(session) || state.activeId !== id) return;
        state.recovering = false;
        if (!job || job.operation_id !== id) {
          setNotice(ZH.protocolError, 'warn');
          updateActionButtons();
          return;
        }
        applyJob(job, id, session);
        if (job.status === 'running') startPolling(session);
        else if (job.status !== 'unknown') setNotice('');
      })
      .catch((e) => {
        if (!sessionAlive(session)) return;
        state.recovering = false;
        setNotice(errMessage(e), 'error');
        updateActionButtons();
      });
  }

  // ---- focus ----
  function onDocKeydown(e) {
    if (!state.open) return;
    if (e.key === 'Escape') { e.preventDefault(); onClose(); return; }
    if (e.key === 'Tab') trapTab(e);
  }

  function focusable() {
    const sel = 'button:not([disabled]), select:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return Array.from(els.dialog.querySelectorAll(sel)).filter((n) => {
      if (n.disabled) return false;
      if (n.hidden) return false;
      const style = n.style;
      if (style && style.display === 'none') return false;
      return true;
    });
  }

  function trapTab(e) {
    const items = focusable();
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = doc.activeElement;
    if (e.shiftKey && (active === first || !els.dialog.contains(active))) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && (active === last || !els.dialog.contains(active))) {
      e.preventDefault(); first.focus();
    }
  }

  function mount() {
    if (!root) buildDOM();
    if (!root.parentNode) doc.body.appendChild(root);
    state.lastFocus = doc.activeElement;
    state.open = true;
    doc.addEventListener('keydown', onDocKeydown, true);
    const first = focusable()[0];
    if (first) first.focus();
    else { els.dialog.setAttribute('tabindex', '-1'); els.dialog.focus(); }
  }

  function unmount() {
    if (!state.open && !root) return;
    state.open = false;
    endSession();
    stopPolling();
    clearTimers();
    doc.removeEventListener('keydown', onDocKeydown, true);
    if (root && root.parentNode) root.parentNode.removeChild(root);
    const lf = state.lastFocus;
    state.lastFocus = null;
    if (lf && typeof lf.focus === 'function') { try { lf.focus(); } catch (_) {} }
  }

  function onClose() { unmount(); }

  // ---- public API ----
  function open(file) {
    if (state.destroyed) return;
    if (state.open) {
      const first = focusable()[0];
      if (first) first.focus();
      return;
    }
    const j = state.job;
    const runningOrAmbiguous = state.started && (state.startInflight || !j || j.status === 'running' || j.status === 'unknown');
    if (runningOrAmbiguous) {
      beginSession();
      state.file = state.file || (file && typeof file === 'object' ? file : null);
      mount();
      renderAll();
      if (state.activeId) {
        const session = state.gen;
        track(callAdapter(() => api.status(state.activeId)))
          .then((job) => {
            if (!sessionAlive(session) || state.activeId !== job.operation_id) return;
            applyJob(job, state.activeId, session);
            if (job && job.status === 'running') startPolling(session);
          })
          .catch(() => {});
      }
      return;
    }
    beginSession();
    state.file = file && typeof file === 'object' ? file : null;
    state.plan = null;
    state.planGen += 1;
    state.options = { existing: 'skip', selected_indices: null };
    state.started = false;
    state.startInflight = false;
    state.job = null;
    state.cancelInflight = false;
    state.exporting = false;
    state.recovering = false;
    mount();
    if (els.existingSelect) els.existingSelect.value = 'skip';
    renderAll();
    setNotice('');
    if (state.file) runPreview();
  }

  function recover() {
    if (state.destroyed) return;
    const saved = state.savedId || readSaved();
    if (!state.open) {
      beginSession();
      mount();
      renderAll();
    }
    if (saved) { state.savedId = saved; onRecover(); }
    else setNotice(ZH.recoverNone, 'warn');
  }

  function destroy() {
    if (state.destroyed) return;
    state.destroyed = true;
    state.open = false;
    endSession();
    stopPolling();
    clearTimers();
    callsInFlight.clear();
    doc.removeEventListener('keydown', onDocKeydown, true);
    if (root && root.parentNode) root.parentNode.removeChild(root);
    root = null;
  }

  return { open, recover, destroy };
}

export default createBackupImportPanel;
