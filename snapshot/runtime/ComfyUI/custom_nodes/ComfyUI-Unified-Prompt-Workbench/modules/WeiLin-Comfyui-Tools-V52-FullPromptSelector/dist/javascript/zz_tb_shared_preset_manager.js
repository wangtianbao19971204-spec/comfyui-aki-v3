(function () {
  if (window.__tbSharedPresetManagerLoaded) return;
  window.__tbSharedPresetManagerLoaded = true;

  const INDEX_URL = "/prompt_selector/library/index";
  const PAGE_URL = "/prompt_selector/library/prompts";
  const PROMPT_READ_URL = "/prompt_selector/library/prompt";
  const PROMPT_UPSERT_URL = "/prompt_selector/prompts/upsert";
  const PROMPT_MARK_USED_URL = "/prompt_selector/prompts/mark_used";
  const PROMPT_DELETE_URL = "/prompt_selector/prompts/delete";
  const ITEM_URL = "/prompt_selector/item";
  const ITEM_BATCH_URL = "/prompt_selector/items/batch";
  const MERGE_PREVIEW_URL = "/prompt_selector/prompts/merge_jobs/preview";
  const MERGE_COMMIT_URL = "/prompt_selector/prompts/merge_jobs/commit";
  const MERGE_TASK_URL = "/prompt_selector/prompts/merge_jobs/";
  const UPLOAD_URL = "/prompt_selector/upload_image";
  const THUMBNAIL_URL = "/prompt_selector/thumbnail/";
  const STYLE_ID = "tb-shared-preset-style";
  const PANEL_ID = "tb-shared-preset-panel";
  const EDITOR_ID = "tb-shared-preset-editor";
  const FLOATING_ENTRY_ID = "tb-shared-preset-floating-undo";
  const LIST_PAGE_SIZE = 30;
  const SEARCH_DEBOUNCE_MS = 280;
  const EAGER_PREVIEW_COUNT = 3;
  const ANIMA_REVIEW_PREFIXES = [
    "待归类/Anima复核/正太萝莉",
    "待归类/Anima复核/年龄安全",
    "待归类/Anima复核/年龄与安全风险",
    "待归类/Anima复核/画风质量镜头",
  ];
  // 默认浏览时隔离有专属入口的整区；明确搜索或筛选时保留所有匹配资料。
  const ISOLATED_AREAS = ["Anima 画师风格", "Krea2 情绪版", "画师串"];
  let activeArea = "";
  // 筛选池按大主题及其小主题分组；人物数量也是一个大主题。
  let poolFilters = [];
  const expandedPoolParents = new Set();
  const searchCollapsedPoolParents = new Set();
  let poolSearchText = '';
  let currentFilterCounts = null;
  let poolMode = "any";   // any=同组内任一命中；all=同组内全部命中（跨组始终同时满足）
  const filterDisclosureState = { advanced: false, pool: false };

  function rememberFilterDisclosure(details, name) {
    const key = `uw-library-${name}-open`;
    try {
      const saved = localStorage.getItem(key);
      if (saved === 'true' || saved === 'false') filterDisclosureState[name] = saved === 'true';
    } catch (_) {}
    details.open = filterDisclosureState[name];
    details.addEventListener('toggle', () => {
      filterDisclosureState[name] = details.open;
      try { localStorage.setItem(key, String(details.open)); } catch (_) {}
    });
  }

  let libraryData = null;
  // ETag of the last complete library snapshot accepted by this manager.
  let libraryRevision = null;
  let activeCategoryId = null;
  let searchText = "";
  let viewMode = "all";
  let activeUsage = "";
  let activeContentType = "";
  const LIBRARY_VIEWS = ["all", "favorites", "recent", "plans", "review"];
  function requestedView(view) {
    if (LIBRARY_VIEWS.includes(view)) return view;
    return "all";
  }
  let detailsOpenVersion = 0;
  let closeResourceDetails = null;
  const selectedPromptCards = new Set();
  const mergeSelection = new Set();
  let mergeMode = false;
  let currentItems = [];
  let currentItemsTotal = 0;
  let currentItemsLoading = false;
  let listController = null;
  let listError = null;
  let listRequestToken = 0;
  let searchTimer = null;
  let previewObserver = null;
  let loadMoreObserver = null;
  // 「显示更多」的自动续拉状态：只有用户自己滚过（滚轮 / 触摸 / 键盘 / 拖动滚动条）才武装，
  // 每补一页就解除武装；列表重建时的程序性滚动（scrollTop 回落）不算数，
  // 这样就不会出现"重建 → 按钮回到视口 → 又加载 → 又重建"的自触发闪屏。
  let loadMoreArmed = false;
  let loadMoreCleanup = null;
  function bindLoadMoreGesture(panel, onScrollCheck) {
    const controller = new AbortController();
    let frame = 0;
    const observer = new MutationObserver(() => { if (!panel.isConnected) cleanup(); });
    const cleanup = () => {
      controller.abort();
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
      loadMoreArmed = false;
      if (loadMoreCleanup === cleanup) loadMoreCleanup = null;
    };
    const arm = event => {
      if (event && event.isTrusted === false) return;
      loadMoreArmed = true;
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => { frame = 0; onScrollCheck(); });
    };
    for (const type of ["wheel", "touchmove", "keydown", "pointerdown"]) {
      window.addEventListener(type, arm, {capture: true, passive: true, signal: controller.signal});
    }
    window.addEventListener("scroll", onScrollCheck, {capture: true, signal: controller.signal});
    // 嵌入资料库可由工作台直接移除，独立面板也须在关闭时清理。
    for (let parent = panel.parentElement; parent; parent = parent.parentElement) {
      observer.observe(parent, {childList: true});
    }
    loadMoreCleanup = cleanup;
  }
  let editing = null; // {mode, categoryId, promptId, baseRevision}
  let editorOpenVersion = 0;

  function nowIso() { return new Date().toISOString(); }
  function uuid() {
    if (crypto && crypto.randomUUID) return crypto.randomUUID();
    return "tb-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }
  function escapeHtml(s) {
    return String(s || "").replace(/[&<>\"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[ch]));
  }
  function escapeAttr(s) { return escapeHtml(s).replace(/'/g, "&#39;"); }
  function embeddingReferences(text) {
    // Parenthesis escapes belong to the prompt parser; resource lookup uses the decoded path.
    const references = String(text || "").matchAll(/\bembedding:((?:\\[()]|[^\s,:()[\]<>])+)/gu);
    return [...new Set(Array.from(references, match => match[1].replace(/\\([()])/g, "$1").replace(/\\/g, "/")))];
  }
  let embeddingListRequest = null;
  function currentEmbeddingNames() {
    if (!embeddingListRequest) {
      embeddingListRequest = (async () => {
        const response = await fetchWithTimeout("/api/embeddings", { cache: "no-store" }, 5000);
        if (!response.ok) throw new Error("resource list unavailable");
        const names = await response.json();
        if (!Array.isArray(names)) throw new Error("invalid resource list");
        return new Set(names.map(name => String(name).replace(/\\/g, "/")));
      })().finally(() => { embeddingListRequest = null; });
    }
    return embeddingListRequest;
  }
  async function annotateEmbeddingReferences(card, text) {
    const references = embeddingReferences(text);
    if (!references.length) return;
    const note = document.createElement("div");
    note.className = "tb-spm-desc tb-spm-resource-status";
    note.textContent = "正在检查 Embedding 引用…";
    card.querySelector(".tb-spm-card-main").appendChild(note);
    try {
      const available = await currentEmbeddingNames();
      const missing = [], ambiguous = [];
      for (const name of references) {
        const stem = name.replace(/\.(?:safetensors|pt|bin)$/i, "");
        if (available.has(name) || available.has(stem)) continue;
        const basenameMatches = stem.includes("/") ? [] : [...available].filter(path => path.split("/").at(-1) === stem);
        if (basenameMatches.length > 1) ambiguous.push(name);
        else if (!basenameMatches.length) missing.push(name);
      }
      if (!note.isConnected) return;
      note.textContent = [missing.length ? `缺少 Embedding：${missing.join("、")}` : "",
        ambiguous.length ? `Embedding 同名需明确路径：${ambiguous.join("、")}` : ""].filter(Boolean).join("；");
      note.textContent = note.textContent ? note.textContent + "。原文已保留；请检查资源路径。" : "Embedding 引用可找到";
      note.dataset.resourceState = missing.length ? "missing" : ambiguous.length ? "ambiguous" : "available";
    } catch (_) {
      if (note.isConnected) {
        note.textContent = "暂时无法检查 Embedding；原文已保留。";
        note.dataset.resourceState = "unverified";
      }
    }
  }
  async function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
    if (typeof AbortController === "undefined") {
      return fetch(url, options);
    }
    const controller = new AbortController();
    const externalAbort=()=>controller.abort();
    options.signal?.addEventListener("abort",externalAbort,{once:true});
    if(options.signal?.aborted)controller.abort();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error(`请求超时：${url}`);
      }
      throw error;
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort",externalAbort);
    }
  }
  function responseRevision(resp) {
    return resp?.headers?.get?.("ETag") || "";
  }
  function revisionConflict(resp) {
    if (resp?.status !== 409) return false;
    const error = new Error("共享库已被其他窗口修改，请重新加载并对照当前草稿后再保存。");
    error.isRevisionConflict = true;
    return error;
  }
  async function fetchLibraryWrite(url, options = {}, timeoutMs = 30000) {
    const baseRevision = editing?.baseRevision || libraryRevision;
    if (!baseRevision) {
      throw new Error("缺少共享库快照版本，请先重新加载共享库。");
    }
    const headers = { ...(options.headers || {}), "If-Match": baseRevision };
    const resp = await fetchWithTimeout(url, { ...options, headers }, timeoutMs);
    const conflict = revisionConflict(resp);
    if (conflict) throw conflict;
    if (resp.ok) {
      const nextRevision = responseRevision(resp);
      if (nextRevision) libraryRevision = nextRevision;
    }
    return resp;
  }
  // ---- shared library batch metadata (same contract as the single-item surface) ----
  function bulkSelection() {
    return [...selectedPromptCards].map(String).filter(Boolean);
  }
  function bulkMetadataNode(panel, action) {
    return panel?.querySelector?.(`[data-action="${action}"]`) || null;
  }
  function setBulkMetadataStatus(panel, text, tone = "muted") {
    const node = bulkMetadataNode(panel, "bulk-meta-status");
    if (!node) return;
    node.textContent = text || "";
    node.dataset.tone = tone;
  }
  function updateBulkMetadataCount(panel) {
    const node = bulkMetadataNode(panel, "bulk-meta-count");
    if (!node) return;
    const count = selectedPromptCards.size;
    node.textContent = count
      ? `已选 ${count} 条（批量操作只作用于已选项）`
      : "已选 0 条（在列表里双击资料加入选择）";
  }
  async function writeBulkMetadata(changes) {
    const resourceIds = bulkSelection();
    if (!resourceIds.length) throw new Error("请先在列表里双击资料加入选择。");
    const response = await fetchLibraryWrite(ITEM_BATCH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resource_ids: resourceIds, ...changes }),
    }, 30000);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    if (data.revision) libraryRevision = data.revision;
    return data;
  }
  async function applyBulkMetadata(panel, changes, label) {
    const count = selectedPromptCards.size;
    setBulkMetadataStatus(panel, `正在提交 ${count} 条…`);
    try {
      const data = await writeBulkMetadata(changes);
      selectedPromptCards.clear();
      updateBulkMetadataCount(panel);
      await loadData(true, 15000, true);
      renderPanelContent();
      window.dispatchEvent(new CustomEvent("anima-tools-shared-prompts-updated"));
      setBulkMetadataStatus(panel, `已用同一版本提交 ${data?.counts?.applied ?? count} 条资料（${label}）。`, "saved");
    } catch (error) {
      setBulkMetadataStatus(panel, error?.message || String(error), "error");
      throw error;
    }
  }
  async function openBulkMetadataEditor(panel, mode) {
    if (!selectedPromptCards.size) {
      setBulkMetadataStatus(panel, "请先在列表里双击资料加入选择。", "error");
      return;
    }
    const editor = bulkMetadataNode(panel, "bulk-meta-editor");
    const title = bulkMetadataNode(panel, "bulk-meta-title");
    const choices = bulkMetadataNode(panel, "bulk-meta-choices");
    const notes = bulkMetadataNode(panel, "bulk-meta-notes");
    editor.dataset.mode = mode;
    editor.hidden = false;
    if (mode === "notes") {
      title.textContent = `批量设置备注（${selectedPromptCards.size} 条）`;
      choices.replaceChildren();
      notes.value = "";
      notes.hidden = false;
      notes.focus();
    } else {
      title.textContent = `${mode === "add" ? "批量加入分组" : "批量移出分组"}（${selectedPromptCards.size} 条）`;
      notes.hidden = true;
      notes.value = "";
      choices.replaceChildren();
      const response = await fetchWithTimeout("/prompt_selector/collections/index", { cache: "no-store" }, 15000);
      const index = await response.json();
      if (!response.ok) throw new Error(index.error || "读取分组失败");
      renderCollectionChoices(choices, index.groups || [], [], () => {});
    }
    setBulkMetadataStatus(panel, "");
  }
  async function fetchLibraryPrompt(promptId, timeoutMs = 15000, selection = false, includeSemantic = false) {
    const params = new URLSearchParams({ prompt_id: String(promptId || "") });
    if (selection) params.set("selection", "1");
    if (includeSemantic) params.set("include_semantic", "1");
    const resp = await fetchWithTimeout(`${PROMPT_READ_URL}?${params.toString()}`, { cache: "no-store" }, timeoutMs);
    const json = await resp.json().catch(() => ({}));
    if (!resp.ok || json.error) {
      const error = new Error(json.error || `HTTP ${resp.status}`);
      error.status = resp.status; error.revision = responseRevision(resp) || json.revision || "";
      error.deleted = !!json.deleted;
      throw error;
    }
    return { ...json, revision: responseRevision(resp) || json.revision || "" };
  }
  function unquoteRevision(value) {
    const text = String(value ?? "").trim();
    return text.length >= 2 && text.startsWith('"') && text.endsWith('"') ? text.slice(1, -1) : text;
  }
  async function fetchSharedItem(resourceId, timeoutMs = 15000) {
    const params = new URLSearchParams({ resource_id: String(resourceId || "") });
    const resp = await fetchWithTimeout(`${ITEM_URL}?${params.toString()}`, { cache: "no-store" }, timeoutMs);
    const json = await resp.json().catch(() => ({}));
    if (!resp.ok || json.error) {
      const error = new Error(json.error || `HTTP ${resp.status}`);
      error.status = resp.status;
      throw error;
    }
    return { ...json, revision: unquoteRevision(responseRevision(resp) || json.revision) };
  }
  // One maintenance body for single-item favorite/group/notes: the same route
  // the Tag surface and the six selector partitions resolve through.
  async function writeSharedItem(resourceId, revision, changes, timeoutMs = 30000) {
    const resp = await fetchWithTimeout(ITEM_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "If-Match": `"${unquoteRevision(revision)}"` },
      body: JSON.stringify({ resource_id: resourceId, ...changes }),
    }, timeoutMs);
    const conflict = revisionConflict(resp);
    if (conflict) throw conflict;
    const json = await resp.json().catch(() => ({}));
    if (!resp.ok || json.error) {
      const error = new Error(json.error || `HTTP ${resp.status}`);
      error.status = resp.status;
      throw error;
    }
    const next = unquoteRevision(responseRevision(resp) || json.revision);
    if (next) libraryRevision = next;
    return { ...json, revision: next || unquoteRevision(revision) };
  }
  let insertionTarget = null;
  let insertionVersion = 0;
  let lastInsertControl = null;
  function reportInsertion(message, control = lastInsertControl, previous = null) {
    const status = document.querySelector(`#${PANEL_ID} .tb-spm-target-status`);
    const feedback = control?.closest('.tb-spm-card')?.querySelector('.tb-spm-card-feedback');
    if (status && (previous === null || status.textContent === previous)) status.textContent = message;
    if (feedback?.isConnected && (previous === null || feedback.textContent === previous)) feedback.textContent = message;
  }
  function restoreInsertionFocus(originControl = lastInsertControl) {
    const panel = document.getElementById(PANEL_ID);
    const candidates = [originControl, panel?.querySelector('[aria-label="搜索当前资料库与筛选范围"]'), document.querySelector('#unified-workbench [data-uw="close"]')];
    for (const control of candidates) {
      if (control?.isConnected && !control.disabled && !control.closest('[hidden], [inert]') && control.getClientRects().length) {
        control.focus({preventScroll:true});
        return;
      }
    }
  }
  let insertionTargetChoices = [];
  let floatingUndo = null;
  function hideFloatingUndo() {
    floatingUndo?.remove?.();
    floatingUndo = null;
  }
  function showFloatingUndo(target) {
    hideFloatingUndo();
    if (typeof target?.onInsert?.undoLast !== "function") return;
    const button = document.createElement("button");
    button.id = FLOATING_ENTRY_ID;
    button.type = "button";
    button.textContent = "撤销本次插入";
    button.title = `撤销：${target.label}`;
    button.onclick = () => {
      insertionVersion++;
      const restored = target.onInsert.undoLast();
      document.querySelector?.("#tb-shared-preset-panel [data-action=\"undo-insert\"]")?.setAttribute("hidden", "");
      reportInsertion(restored ? `已撤销：${target.label}` : "撤销不可用：目标或正文已变化");
      hideFloatingUndo();
      restoreInsertionFocus();
    };
    const workbench = document.getElementById(PANEL_ID)?.closest('#unified-workbench');
    const footer = workbench?.querySelector('.uw-footer');
    (footer || document.body).appendChild(button);
    floatingUndo = button;
  }
  async function insertPrompt(prompt, action = "append_end", libraryItem = null, originControl = null) {
    const text = String(prompt || "");
    if (!text.trim()) { reportInsertion("未写入：正文为空", originControl); return; }
    if (insertionTarget) {
      if (insertPrompt.pending) return;
      insertPrompt.pending = true;
      const target = insertionTarget;
      const version = ++insertionVersion;
      const targetDirection = target.direction;
      const panel = document.getElementById(PANEL_ID);
      const targetLabel = `${targetDirection === 'negative' ? '负向' : targetDirection === 'positive' ? '正向' : ''} ${target.label}`.trim();
      const current = () => version === insertionVersion && insertionTarget === target && target.direction === targetDirection && panel?.isConnected;
      const report = (message, previous = null) => { if (current()) reportInsertion(message, originControl, previous); };
      const wasDisabled = originControl?.disabled;
      if (originControl) { originControl.disabled = true; originControl.setAttribute('aria-busy', 'true'); }
      // The first insert revalidates the item against the server, which takes over a second
      // on a cold library; show progress immediately so the click never looks ignored.
      report(`正在${action.startsWith('replace_') ? '替换' : '追加'}：${targetLabel}…`);
      try {
        const semantic = libraryItem?._semantic;
        if (libraryItem && (!semantic || !["reviewed", "classified"].includes(semantic.disposition) || semantic.manual_search_eligible !== true)) {
          throw new Error("该资料尚未通过审查，请先核查资料。");
        }
        if (semantic && (semantic.usage === "unknown" || !["positive", "negative"].includes(insertionTarget.direction)
            || (semantic.usage !== "both" && semantic.usage !== insertionTarget.direction))) {
          throw new Error("资料用途与当前目标方向未匹配，请选择对应的正向或负向目标。");
        }
        if (libraryItem) {
          const fresh = await fetchLibraryPrompt(libraryItem.id, 15000, true);
          if (!semantic.binding || fresh.prompt?._semantic?.binding !== semantic.binding
              || fresh.prompt?._semantic?.usage !== semantic.usage || fresh.prompt?.prompt !== text) {
            throw new Error("资料已变更，请刷新列表后重新选择。");
          }
        }
        if (!current()) return;
        const request = target.onInsert.supportsActions
          ? { text, action } : text;
        if(typeof request==='object'&&libraryItem)request.validatePreview=async()=>{const latest=await fetchLibraryPrompt(libraryItem.id,15000,true);if(latest.prompt?._semantic?.binding!==semantic.binding||latest.prompt?.prompt!==text)throw new Error('资料已变更，请取消后刷新列表。');};
        const result = await (target.onInsert.reviewInsert||target.onInsert)(request);
        if (!current()) return;
        if(result?.status==='cancelled') {
          report("已取消替换，目标未改变。");
          return;
        }
        if (result?.status === undefined) { report("未写入：目标暂不可用，请重新选择目标后再试"); return; }
        if (result?.status && result.status !== "inserted") {
          report(result.status === "busy" ? "正在写入，请稍候" : result.status === "stale" ? "未写入：目标已失效，请从当前分支重新打开资料库" : result.status === "empty" ? "未写入：正文为空" : "正文未变化");
          return;
        }
        const insertedMessage = `已${action.startsWith('replace_') ? '替换' : '追加'}到：${targetLabel}`;
        report(insertedMessage);
        lastInsertControl = originControl;
        if (typeof showFloatingUndo === "function") showFloatingUndo(target);
        const undoButton = document.querySelector(`#${PANEL_ID} [data-action="undo-insert"]`);
        if (undoButton) undoButton.hidden = false;
        if (libraryItem?._categoryId && libraryItem?.id) {
          // Recent-use persistence must not delay insertion or undo.
          void (async () => {
            try {
              const usedResp = await fetchLibraryWrite(PROMPT_MARK_USED_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ category_id: libraryItem._categoryId, prompt_id: libraryItem.id }),
              });
              if (!usedResp.ok) throw new Error(`HTTP ${usedResp.status}`);
              const usedAt = nowIso();
              libraryItem.last_used = usedAt;
              libraryItem.usage_count = Number(libraryItem.usage_count || 0) + 1;
            } catch (error) {
              report(`${insertedMessage}（正文已应用，使用记录未保存：${error?.message || error}）`, insertedMessage);
            }
          })();
        }
      } catch (error) {
        report(`写入失败，请核对目标：${error?.message || String(error)}`);
      } finally {
        insertPrompt.pending = false;
        if (originControl) { originControl.disabled = wasDisabled; originControl.removeAttribute('aria-busy'); }
        if (action.startsWith('replace_') && current() && document.activeElement === document.body) restoreInsertionFocus(originControl);
      }
      return;
    }
    reportInsertion("未写入：没有明确插入目标，请从提示词目标打开资料库。", originControl);
  }
  function normalizeData(data) {
    const d = data && typeof data === "object" ? data : {};
    d.version = d.version || "1.6";
    d.settings = d.settings || { language: "zh-CN", separator: ", ", save_selection: true };
    d.categories = Array.isArray(d.categories) ? d.categories : [];
    d.categories.forEach(cat => {
      cat.id = cat.id || uuid();
      cat.name = cat.name || "未分类";
      cat.updated_at = cat.updated_at || nowIso();
      cat.prompts = Array.isArray(cat.prompts) ? cat.prompts : [];
      const declaredCount = Number(cat.prompt_count);
      cat.prompt_count = Number.isFinite(declaredCount) ? Math.max(0, declaredCount) : cat.prompts.length;
      cat.prompts.forEach(p => {
        p.id = p.id || uuid();
        p.alias = p.alias || "";
        p.prompt = p.prompt || "";
        p.description = p.description || "";
        p.image = p.image || "";
        p.tags = Array.isArray(p.tags) ? p.tags : [];
        p.favorite = !!p.favorite;
        p.created_at = p.created_at || nowIso();
        p.updated_at = p.updated_at || p.created_at;
        if (p.usage_count == null) p.usage_count = 0;
        if (!('last_used' in p)) p.last_used = null;
      });
    });
    return d;
  }
  function resetCurrentItems() {
    loadMoreCleanup?.();
    listController?.abort();
    listError=null;
    currentItems = [];
    currentItemsTotal = 0;
    currentFilterCounts = null;
    currentItemsLoading = false;
    listRequestToken += 1;
  }
  let activeSemanticClass = "";
  let activeSubcategory = "";
  let activeCollection = "";
  async function loadItemPage(reset = false, timeoutMs = 30000) {
    if (reset) resetCurrentItems();
    listController?.abort();
    listController = new AbortController();
    const requestToken = ++listRequestToken;
    const requestRevision = libraryRevision;
    const params = new URLSearchParams();
    const query = searchText.trim();
    params.set("view", viewMode);
    if (query) params.set("q", query);
    // 主题与细分类一律走筛选池（可累积多选）；不再发单选的 theme / subcategory。
    if (activeCollection) params.set("collection", activeCollection);
    if (activeCategoryId) params.set("category_id", activeCategoryId);
    if (activeUsage) params.set("usage", activeUsage);
    if (activeContentType) params.set("content_type", activeContentType);
    params.set("offset", String(reset ? 0 : currentItems.length));
    params.set("limit", String(LIST_PAGE_SIZE));
    if (reset) params.set('include_filter_counts', '1');
    // 轴的线上名称：细分类用 sub（服务端口径），其余与池子里的键一致。
    for (const entry of poolFilters) {
      const wireAxis = entry.axis === "subcategory" ? "sub" : entry.axis;
      params.append("filter", `${wireAxis}:${entry.value}`);
    }
    if (poolMode === "all") params.set("filter_mode", "all");
    currentItemsLoading = true;
    listError=null;
    if (reset) renderFilterPool(document.getElementById(PANEL_ID));
    try {
      const resp = await fetchWithTimeout(`${PAGE_URL}?${params.toString()}`, { cache: "no-store", signal:listController.signal }, timeoutMs);
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok || json.error) throw new Error(json.error || `HTTP ${resp.status}`);
      // Discard stale responses before touching either the revision or list.
      if (requestToken !== listRequestToken) return currentItems;
      const revision = responseRevision(resp);
      if (!reset && requestRevision && revision && revision !== requestRevision) {
        currentItems=[];currentItemsTotal=0;
        throw new Error("共享库版本已变化，分页结果未与旧列表混合；请刷新后继续。");
      }
      if (!editing) {
        if (revision) libraryRevision = revision;
      }
      const incoming = Array.isArray(json.items) ? json.items : [];
      if (reset) currentItems = incoming;
      else {
        const seen = new Set(currentItems.map(item => `${item._categoryId || ""}:${item.id || ""}`));
        for (const item of incoming) {
          const key = `${item._categoryId || ""}:${item.id || ""}`;
          if (!seen.has(key)) {
            seen.add(key);
            currentItems.push(item);
          }
        }
      }
      currentItemsTotal = Math.max(currentItems.length, Number(json.total) || 0);
      if (reset || json.filter_counts) currentFilterCounts = json.filter_counts?.mode === poolMode ? json.filter_counts : null;
      return currentItems;
    } catch(error) {
      if(requestToken !== listRequestToken)return currentItems;
      error.listRequestToken=requestToken;
      listError=error;
      currentFilterCounts=null;
      renderFilterPool(document.getElementById(PANEL_ID));
      throw error;
    } finally {
      if (requestToken === listRequestToken) currentItemsLoading = false;
    }
  }
  async function loadData(force, timeoutMs = 30000, loadItems = true) {
    const previousActiveName = activeCategoryName();
    if (!libraryData || force) {
      const resp = await fetchWithTimeout(INDEX_URL, { cache: "no-store" }, timeoutMs);
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok || json.error) throw new Error(json.error || `HTTP ${resp.status}`);
      if (!editing) {
        const revision = responseRevision(resp);
        if (revision && libraryRevision && revision !== libraryRevision) currentFilterCounts = null;
        if (revision) libraryRevision = revision;
      }
      libraryData = normalizeData(json);
      if (!getCatById(activeCategoryId) && previousActiveName) {
        const replacement = libraryData.categories.find(category => category.name === previousActiveName);
        activeCategoryId = replacement ? categoryIdentity(replacement) : null;
      }
    }
    const groups = libraryData?.selector_groups?.resource || libraryData?.selector_groups?.pose || [];
    if (activeCollection && !groups.some(group => group.id === activeCollection)) activeCollection = '';
    if (loadItems) {
      const retainedCount = currentItems.length;
      let requestToken = listRequestToken + 2;
      await loadItemPage(true, timeoutMs);
      while (requestToken === listRequestToken && currentItems.length < Math.min(retainedCount, currentItemsTotal)) {
        const previousCount = currentItems.length;
        requestToken = listRequestToken + 1;
        await loadItemPage(false, timeoutMs);
        if (currentItems.length <= previousCount) break;
      }
    }
    return libraryData;
  }
  async function uploadPreview(file, alias) {
    if (!file) return "";
    const fd = new FormData();
    fd.append("image", file);
    fd.append("alias", alias || "preset");
    const resp = await fetch(UPLOAD_URL, { method: "POST", body: fd });
    const json = await resp.json().catch(() => ({}));
    if (!resp.ok || json.error) throw new Error(json.error || `HTTP ${resp.status}`);
    return json.filename || "";
  }
  function getCatById(id) {
    return (libraryData?.categories || []).find(c => (c.id || c.name) === id);
  }
  function categoryIdentity(cat) {
    return cat?.id || cat?.name || "";
  }
  function activeCategoryName() {
    const activeCat = getCatById(activeCategoryId);
    return activeCat?.name || "";
  }
  function groupedCategories() {
    const groups = new Map();
    for (const cat of (libraryData?.categories || [])) {
      const name = cat.name || "未分类";
      // 区域模式只列该区域的分类；普通模式隐藏有专属入口的两个整区。
      if (activeArea ? !name.startsWith(activeArea) : ISOLATED_AREAS.some(area => name.startsWith(area))) continue;
      if (!groups.has(name)) {
        groups.set(name, {
          name,
          id: categoryIdentity(cat),
          count: 0,
          objectCount: 0,
        });
      }
      const group = groups.get(name);
      group.count += Number.isFinite(Number(cat.prompt_count))
        ? Number(cat.prompt_count)
        : (cat.prompts || []).length;
      group.objectCount += 1;
      if (categoryIdentity(cat) === activeCategoryId) group.id = categoryIdentity(cat);
    }
    return Array.from(groups.values()).sort((left, right) => {
      const leftPriority = ANIMA_REVIEW_PREFIXES.findIndex(prefix => left.name.startsWith(prefix));
      const rightPriority = ANIMA_REVIEW_PREFIXES.findIndex(prefix => right.name.startsWith(prefix));
      const normalizedLeft = leftPriority < 0 ? ANIMA_REVIEW_PREFIXES.length : leftPriority;
      const normalizedRight = rightPriority < 0 ? ANIMA_REVIEW_PREFIXES.length : rightPriority;
      return normalizedLeft - normalizedRight;
    });
  }
  // 452 codex leaves do not fit one flat dropdown; the source picker groups them by
  // their top-level area and the toolbar filter narrows the list without hiding the
  // select itself, so keyboard use keeps working.
  let sourceFilterText = "";
  function categoryArea(name) {
    const text = String(name || "").trim();
    const cut = text.indexOf(" / ");
    return cut > 0 ? text.slice(0, cut) : "其他分类";
  }
  function isUnfilteredLibrary() {
    return !activeArea && viewMode === 'all' && !searchText.trim() && !poolFilters.length
      && !activeCategoryId && !activeCollection && !activeUsage && !activeContentType;
  }
  function allFilteredItems() {
    const items = currentItems;
    if (activeArea) {
      return items.filter(item => String(item._categoryName || "").startsWith(activeArea));
    }
    return isUnfilteredLibrary()
      ? items.filter(item => !ISOLATED_AREAS.some(area => String(item._categoryName || "").startsWith(area)))
      : items;
  }
  // ── 筛选池 ───────────────────────────────────────────────────────────────
  // 点一下加条件，再点移除；不同大主题下的小主题同时满足。
  function poolHas(axis, value) {
    return poolFilters.some(item => item.axis === axis && item.value === value);
  }
  function poolRefinement(value) {
    for (const children of Object.values(libraryData?.filter_pool?.refinements || {})) {
      const detail = children.find(item => item.id === value);
      if (detail) return detail;
    }
    return poolFilters.find(item => item.axis === 'detail' && item.value === value);
  }
  function selectPoolParent(parent) {
    const value = libraryData?.filter_pool?.subcategory_values?.[parent] || parent;
    poolFilters = poolFilters.filter(item => item.axis !== 'detail' || poolRefinement(item.value)?.parent !== parent);
    if (!poolHas('subcategory', value)) poolFilters.push({axis: 'subcategory', value});
    reloadPooledList({axis: 'subcategory', value});
  }
  function reloadPooledList(focusFilter = null) {
    syncActiveTheme();
    void (async () => {
      try {
        await loadItemPage(true, 15000);
        renderPanelContent({revealResults: true});
        if (focusFilter) {
          const pool = document.getElementById(PANEL_ID)?.querySelector('[data-action="filter-pool"]');
          const buttons = [...pool?.querySelectorAll('[data-pool-axis]') || []];
          const target = buttons.find(button => button.dataset.poolAxis === focusFilter.axis && button.dataset.poolValue === focusFilter.value)
            || buttons.find(button => button.dataset.poolAxis === 'subcategory' && button.dataset.poolValue === focusFilter.parentValue);
          target?.focus({preventScroll: true});
        }
      } catch (error) {
        showError(error);
      }
    })();
  }
  function togglePoolFilter(axis, value) {
    const parent = axis === 'detail' ? poolRefinement(value)?.parent : null;
    const index = poolFilters.findIndex(item => item.axis === axis && item.value === value);
    if (index >= 0) poolFilters.splice(index, 1);
    else if (axis === 'detail') {
      const detail = poolRefinement(value);
      if (!detail) return;
      const parentValue = libraryData?.filter_pool?.subcategory_values?.[detail.parent] || detail.parent;
      poolFilters = poolFilters.filter(item => !(item.axis === 'subcategory' && item.value === parentValue));
      poolFilters.push({axis, value, parent: detail.parent, label: detail.label, owner: detail.owner});
    } else poolFilters.push({ axis, value });
    syncActiveTheme();
    reloadPooledList({axis, value, parentValue: libraryData?.filter_pool?.subcategory_values?.[parent] || parent});
  }
  // activeSemanticClass 只是"最近点的主题"，用于新建资料的默认主题与侧边栏高亮；
  // 真正的筛选条件在 poolFilters 里，所以多选不会互相顶掉。
  function syncActiveTheme() {
    const themes = poolFilters.filter(item => item.axis === "theme");
    activeSemanticClass = themes.length ? themes[themes.length - 1].value : "";
  }
  function normalizePoolSearch(value) {
    return String(value || '').normalize('NFKC').toLowerCase().replace(/[_\s]+/g, ' ').trim();
  }
  function renderFilterPool(panel) {
    const host = panel?.querySelector('[data-action="filter-pool"]');
    if (!host) return;
    const summary = panel.querySelector('.tb-spm-pool-wrap > summary');
    if (summary) summary.textContent = `筛选池 · 已选 ${poolFilters.length} 项`;
    const pool = (libraryData && libraryData.filter_pool) || {};
    const classLabels = (libraryData && libraryData.semantic_classes) || {};
    const axisLabels = { theme: '大主题', subcategory: '小主题', count: '人物数量', detail: '细分' };
    const label = (axis, value) => {
      if (axis === 'theme') return classLabels[value] || value;
      if (axis === 'detail') {
        const detail = poolRefinement(value);
        return detail?.parent ? `${classLabels[detail.owner] || detail.owner} / ${detail.parent} / ${detail.label}` : value;
      }
      return axis === 'subcategory' && value.includes('::') ? value.slice(value.indexOf('::') + 2) : value;
    };
    const chip = (text, count, active, onClick) => {
      const button = document.createElement('button');
      button.className = 'tb-spm-small-btn' + (active ? ' primary' : '');
      button.textContent = Number.isFinite(Number(count)) && count !== undefined && count !== null
        ? `${text} ${count}` : text;
      if (count !== undefined && count !== null) button.title = `全库匹配 ${count} 条；组合筛选结果见列表`;
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
      button.onclick = onClick;
      return button;
    };
    // Keep the input node while updating results so typing never loses its caret.
    let search = host.querySelector('[data-pool-search]');
    let results = host.querySelector('[data-pool-results]');
    if (!search || !results) {
      host.replaceChildren();
      const bar = document.createElement('div');
      bar.className = 'tb-spm-pool-chosen';
      search = document.createElement('input');
      search.type = 'search';
      search.dataset.poolSearch = 'true';
      search.placeholder = '搜索筛选项（中文名称 / English tags）';
      search.setAttribute('aria-label', '搜索筛选池');
      search.style.cssText = 'flex:1;min-width:200px;padding:6px 8px;background:#202026;color:inherit;border:1px solid #555;border-radius:5px';
      const clearSearch = () => {
        poolSearchText = ''; searchCollapsedPoolParents.clear(); renderFilterPool(panel); search.focus({preventScroll:true});
      };
      search.oninput = () => {
        poolSearchText = search.value; searchCollapsedPoolParents.clear(); renderFilterPool(panel);
      };
      search.onkeydown = event => {
        if (event.key === 'Escape' && poolSearchText) { event.preventDefault(); event.stopPropagation(); clearSearch(); }
      };
      const clear = chip('清除搜索', undefined, false, clearSearch);
      clear.dataset.poolSearchClear = 'true';
      bar.append(search, clear);
      results = document.createElement('div');
      results.dataset.poolResults = 'true';
      host.append(bar, results);
    }
    if (search.value !== poolSearchText) search.value = poolSearchText;
    host.querySelector('[data-pool-search-clear]').hidden = !poolSearchText;
    results.replaceChildren();
    const terms = normalizePoolSearch(poolSearchText).split(' ').filter(Boolean);
    const matches = (...values) => {
      const haystack = normalizePoolSearch(values.flat(Infinity).join(' '));
      return terms.every(term => haystack.includes(term));
    };
    const filterChip = (axis, value, text, globalCount, onClick, allowZero = false) => {
      const counts = currentFilterCounts?.[axis];
      const count = counts && typeof counts === 'object' ? Number(counts[value]) || 0 : globalCount;
      const active = poolHas(axis, value);
      const button = chip(text, count, active, onClick || (() => togglePoolFilter(axis, value)));
      button.dataset.poolAxis = axis;
      button.dataset.poolValue = value;
      button.disabled = count === 0 && !active && !allowZero;
      button.title = counts ? `当前条件下可匹配 ${count} 条；全库 ${globalCount} 条` : `全库匹配 ${globalCount} 条；组合计数暂不可用`;
      return button;
    };
    const chosen = document.createElement('div');
    chosen.className = 'tb-spm-pool-chosen';
    const state = document.createElement('span');
    state.className = 'tb-spm-pool-state';
    state.textContent = poolFilters.length ? '已选：' : '筛选池（还没选条件）';
    chosen.append(state);
    for (const entry of poolFilters) {
      chosen.append(chip(`${axisLabels[entry.axis] || entry.axis}·${label(entry.axis, entry.value)} ×`,
        undefined, true, () => togglePoolFilter(entry.axis, entry.value)));
    }
    const selectedParents = new Set(poolFilters.filter(item => item.axis === 'detail').map(item => poolRefinement(item.value)?.parent).filter(Boolean));
    for (const parent of selectedParents) chosen.append(chip(`回到父类 · ${parent}`, undefined, false, () => selectPoolParent(parent)));
    const mode = document.createElement('button');
    mode.className = 'tb-spm-small-btn';
    mode.textContent = poolMode === 'all' ? '同组：全部满足' : '同组：任一命中';
    mode.title = '大主题为一组；每个大主题下的小主题各为一组；同一小主题下的细分为一组，不同父类的细分同时满足。';
    mode.onclick = () => { poolMode = poolMode === 'all' ? 'any' : 'all'; reloadPooledList(); };
    chosen.append(mode);
    if (poolFilters.length) {
      chosen.append(chip('清空筛选池', undefined, false, () => { poolFilters = []; expandedPoolParents.clear(); reloadPooledList(); }));
    }
    results.append(chosen);
    const section = (title, entries, factory) => {
      if (!entries.length) return;
      const box = document.createElement('div');
      box.className = 'tb-spm-pool-section';
      const name = document.createElement('span');
      name.className = 'tb-spm-pool-title';
      name.textContent = title;
      box.append(name);
      const list = document.createElement('div');
      list.className = 'tb-spm-pool-chips';
      entries.forEach(entry => list.append(factory(entry)));
      box.append(list);
      results.append(box);
      return box;
    };
    const setExpanded = (parent, expanded) => {
      if (terms.length) {
        if (expanded) searchCollapsedPoolParents.delete(parent); else searchCollapsedPoolParents.add(parent);
      } else if (expanded) expandedPoolParents.add(parent); else expandedPoolParents.delete(parent);
      renderFilterPool(panel);
      [...host.querySelectorAll('[data-pool-expand]')].find(button => button.dataset.poolExpand === parent)?.focus({preventScroll: true});
    };
    const refinementsFor = parent => (pool.refinements?.[parent] || []).filter(item => item.count >= 10 || poolHas('detail', item.id));
    const detailMatches = (themeId, parent, item) => matches(themeId, classLabels[themeId], parent, item.label, item.tags || []);
    const subValue = value => pool.subcategory_values?.[value] || value;
    const subPool = pool.subcategory || {};
    const eligibleParents = themeId => Object.entries(subPool[themeId] || {}).filter(([value, count]) => count >= 10 || poolHas('subcategory', subValue(value)) || selectedParents.has(value));
    const parentMatches = (themeId, parent) => matches(themeId, classLabels[themeId], parent) || refinementsFor(parent).some(item => detailMatches(themeId, parent, item));
    const countEntries = Object.entries(pool.count || {}).filter(([value, count]) => count >= 10 || poolHas('count', value));
    const themeEntries = Object.entries(pool.theme || {});
    const hasSearchMatch = themeEntries.some(([id]) => matches(id, classLabels[id]) || eligibleParents(id).some(([parent]) => parentMatches(id, parent)))
      || countEntries.some(([value]) => matches('person_count', classLabels.person_count, '人物数量', value));
    const visibleThemes = themeEntries.filter(([id]) => matches(id, classLabels[id]) || poolHas('theme', id)
      || eligibleParents(id).some(([parent]) => parentMatches(id, parent) || poolHas('subcategory', subValue(parent)) || selectedParents.has(parent))
      || (id === 'person_count' && countEntries.some(([value]) => matches('person_count', classLabels.person_count, '人物数量', value) || poolHas('count', value))));
    if (terms.length && !hasSearchMatch) {
      const empty = document.createElement('div');
      empty.className = 'tb-spm-status';
      empty.textContent = poolFilters.length ? '没有匹配的筛选项；已选路径仍保留。' : '没有匹配的筛选项。';
      results.append(empty);
    }
    section('大主题', visibleThemes, ([id, count]) => filterChip('theme', id, classLabels[id] || id, count));
    const isExpanded = parent => terms.length ? !searchCollapsedPoolParents.has(parent) : expandedPoolParents.has(parent);
    for (const [themeId] of visibleThemes) {
      if (themeId === 'person_count') {
        section(`小主题 · ${classLabels[themeId] || '人物数量'}`, countEntries.filter(([value]) => matches(themeId, classLabels[themeId], '人物数量', value) || poolHas('count', value)),
          ([value, count]) => filterChip('count', value, value, count));
      }
      const parents = eligibleParents(themeId).filter(([parent]) => parentMatches(themeId, parent) || poolHas('subcategory', subValue(parent)) || selectedParents.has(parent));
      section(`小主题 · ${classLabels[themeId] || themeId}`, parents, ([value, count]) => {
        const hasDetails = selectedParents.has(value);
        const parentButton = filterChip('subcategory', subValue(value), value, count, () => {
          if (hasDetails) selectPoolParent(value); else togglePoolFilter('subcategory', subValue(value));
        }, hasDetails);
        const children = refinementsFor(value);
        if (!children.length) return parentButton;
        parentButton.title += hasDetails ? '\n已选择细分；点击回到父类，右键展开细分。' : '\n点击筛选父类；右键或 → 键展开细分。';
        parentButton.oncontextmenu = event => { event.preventDefault(); event.stopPropagation(); setExpanded(value, true); };
        parentButton.onkeydown = event => {
          if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
            event.preventDefault(); event.stopPropagation(); setExpanded(value, event.key === 'ArrowRight');
          }
        };
        const wrapper = document.createElement('span');
        wrapper.className = 'tb-spm-pool-branch';
        const expanded = isExpanded(value);
        const arrow = chip(expanded ? '▾' : '▸', undefined, hasDetails, () => setExpanded(value, !expanded));
        arrow.classList.add('tb-spm-pool-expand');
        arrow.removeAttribute('aria-pressed');
        arrow.dataset.poolExpand = value;
        arrow.setAttribute('aria-expanded', String(expanded));
        arrow.setAttribute('aria-controls', 'tb-spm-detail-' + encodeURIComponent(value));
        arrow.setAttribute('aria-label', `${expanded ? '收起' : '展开'}${value}的细分`);
        arrow.title = `${expanded ? '收起' : '展开'}细分（不改变筛选）`;
        arrow.onkeydown = parentButton.onkeydown;
        wrapper.append(parentButton, arrow);
        return wrapper;
      });
      for (const [parent] of parents) {
        if (!isExpanded(parent)) continue;
        const box = section(`细分 · ${parent}`, refinementsFor(parent).filter(item => detailMatches(themeId, parent, item) || poolHas('detail', item.id)),
          item => filterChip('detail', item.id, item.label, item.count));
        if (box) {
          box.id = 'tb-spm-detail-' + encodeURIComponent(parent);
          box.classList.add('tb-spm-pool-detail');
          box.setAttribute('role', 'group');
          box.setAttribute('aria-label', `${parent}的细分`);
        }
      }
    }
  }

  function displayedItemsTotal() {
    if (!isUnfilteredLibrary()) return currentItemsTotal;
    let sum = 0;
    for (const cat of (libraryData?.categories || [])) {
      const name = cat.name || "";
      if (!ISOLATED_AREAS.some(area => name.startsWith(area))) continue;
      sum += Number.isFinite(Number(cat.prompt_count)) ? Number(cat.prompt_count) : (cat.prompts || []).length;
    }
    return Math.max(0, currentItemsTotal - sum);
  }
  // 卡片上那行分类：把这条片段归属的**全部内部主题分类**列出来
  // —— 主主题 + 相关主题（alternative_classes）+ 细分类（subcategories）。
  // 以前只显示主主题，看不出它其实还挂在别的主题/细分类下面。
  function cardThemeLine(item) {
    const semantic = item?._semantic || {};
    const labels = libraryData?.semantic_classes || {};
    const classes = (semantic.theme_ids || [semantic.primary_class, ...(semantic.alternative_classes || [])])
      .filter((id, index, all) => id && labels[id] && all.indexOf(id) === index)
      .map(id => labels[id]);
    // 兜底名（其他／日常与其他动作…）只是"没有更细的桶"，铺在卡片上是噪声，直接不显示。
    const BLANKET_SUB = ["其他", "日常与其他动作", "其他表情", "其他服饰", "其他场景"];
    const subs = [...new Set((semantic.subcategories || []).filter(Boolean))]
      .filter(label => !BLANKET_SUB.includes(label));
    const parts = [];
    if (classes.length) parts.push(classes.join("、"));
    if (subs.length) parts.push(`细分类：${subs.join("、")}`);
    return parts.join(" · ");
  }
  // 「2026.7.15 法典紫色新增；原目录：…；原名称：…」这类是导入/迁移的来源标注，
  // 不是给人看的描述：卡片正面不显示，只在「正文与来源」里标成「来源标注」。
  function isProvenanceDescription(text) {
    const value = String(text || "").trim();
    return /^20\d\d[.\-]/.test(value) || value.includes("原目录：");
  }
  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .tb-spm-btn { display:inline-flex; align-items:center; gap:6px; height:32px; padding:0 10px; border:1px solid #555; border-radius:8px; background:#302045; color:#f1eaff; cursor:pointer; font-size:13px; }
      .tb-spm-btn:hover { filter:brightness(1.16); }
      #${FLOATING_ENTRY_ID} { position:fixed; right:18px; bottom:74px; z-index:2147482201; height:38px; padding:0 14px; border:1px solid #8c54e6; border-radius:999px; background:#7835dc; color:#fff; box-shadow:0 10px 28px rgba(0,0,0,.42); font-weight:800; letter-spacing:0; cursor:pointer; display:flex; align-items:center; gap:8px; }
      #unified-workbench .uw-footer > #${FLOATING_ENTRY_ID} { position:static; z-index:auto; flex-shrink:0; margin-left:auto; box-shadow:none; }
      .tb-spm-card-feedback:not(:empty) { font-size:12px; line-height:1.5; padding:6px 0; overflow-wrap:anywhere; }
      #${FLOATING_ENTRY_ID}:hover { filter:brightness(1.12); transform:translateY(-1px); }
      #${PANEL_ID} { position:fixed; inset:28px 28px 28px auto; width:min(1080px, calc(100vw - 56px)); background:#1e1e1e; color:#f0f0f0; border:1px solid #444; border-radius:12px; box-shadow:0 18px 70px rgba(0,0,0,.48); z-index:2147482200; display:flex; flex-direction:column; overflow:hidden; font-family:system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
      #${PANEL_ID}.tb-spm-embedded { position:relative; inset:auto; width:100%; height:auto; max-height:none; box-sizing:border-box; box-shadow:none; z-index:auto; overflow:visible; }
      #${PANEL_ID}.tb-spm-embedded .tb-spm-head { position:sticky; top:0; z-index:6; height:auto; min-height:48px; flex-wrap:wrap; padding:8px 12px; }
      #${PANEL_ID}.tb-spm-embedded .tb-spm-search { min-width:140px; }
      #${PANEL_ID}.tb-spm-embedded .tb-spm-list { max-height:560px; min-height:240px; }
      #${PANEL_ID}.tb-spm-embedded .tb-spm-img-wrap:has(.tb-spm-no-img) { height:42px; flex-basis:42px; }
      .tb-spm-resource-tabs { display:flex; flex-wrap:wrap; align-items:center; gap:6px; padding:8px 0; }
      .tb-spm-resource-tabs [aria-pressed="true"] { background:#7835dc; color:#fff; }
      .tb-spm-resource-tabs small { color:#aaa; margin-left:8px; }
      .tb-spm-resource-host { min-width:0; }
      .tb-spm-resource-host:empty::after { content:"点击共享资料库或上方主题，查看共用的资源。"; display:block; padding:16px; color:#aaa; }
      .tag-manager-container.tb-spm-show-shared > .tag-manager { display:none !important; }
      .tag-manager-container:not(.tb-spm-show-shared) > .tb-spm-resource-host { display:none; }
      .weilin_prompt_ui_draggable-window:has(.tb-spm-show-shared) { min-width:min(1060px, calc(100vw - 116px)); min-height:min(760px, calc(100vh - 116px)); }
      .tb-spm-head { height:48px; display:flex; align-items:center; gap:10px; padding:0 12px; border-bottom:1px solid #3b3b3b; background:#282828; flex-shrink:0; }
      .tb-spm-title { font-weight:800; white-space:nowrap; color:#fff; }
      .tb-spm-views { display:flex; gap:6px; align-items:center; padding:6px 12px; border-bottom:1px solid #333; }
      .tb-spm-views [aria-selected="true"] { background:#7835dc; border-color:#8c54e6; }
      .tb-spm-view-hint { color:#a8b3c7; font-size:12px; margin-left:auto; }
      .tb-spm-management { flex-shrink:0; border-bottom:1px solid #333; }
      .tb-spm-management > summary { cursor:pointer; padding:7px 12px; color:#c4b5fd; }
      .tb-spm-management > .tb-spm-small-btn { margin:4px 12px; }
      .tb-spm-filters { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:8px 12px; border-bottom:1px solid #333; }
      .tb-spm-filters label { display:flex; gap:5px; align-items:center; color:#bbb; font-size:12px; }
      .tb-spm-filters select { min-width:0; max-width:200px; padding:5px 8px; border:1px solid #4a4a4a; border-radius:8px; background:#171717; color:#eee; }
      .tb-spm-subchips { display:flex; flex-wrap:nowrap; align-items:center; gap:6px; padding:6px 12px; border-bottom:1px solid #333; overflow-x:auto; }
      .tb-spm-subchips .tb-spm-small-btn { white-space:nowrap; flex:0 0 auto; }
      .tb-spm-subchips[hidden] { display:none; }
      .tb-spm-pool-wrap { border-bottom:1px solid #333; padding:4px 12px 8px; }
      .tb-spm-pool-wrap > summary { cursor:pointer; color:#c4b5fd; font-size:12px; padding:4px 0; }
      .tb-spm-pool-chosen { display:flex; flex-wrap:wrap; align-items:center; gap:6px; padding:4px 0 6px; }
      .tb-spm-pool-state { color:#a1a1aa; font-size:12px; }
      .tb-spm-pool-section { display:flex; align-items:flex-start; gap:8px; padding:3px 0; }
      .tb-spm-pool-title { flex:0 0 132px; color:#c4b5fd; font-size:12px; line-height:22px; }
      .tb-spm-pool-chips { display:flex; flex-wrap:wrap; gap:6px; flex:1 1 auto; min-width:0; }
      .tb-spm-pool-chips .tb-spm-small-btn { font-size:12px; }
      .tb-spm-pool-branch { display:inline-flex; align-items:center; gap:2px; }
      .tb-spm-pool-expand { min-width:26px; padding:0 6px; }
      .tb-spm-pool-detail { margin-left:12px; padding-left:8px; border-left:2px solid #66507e; }
      /* 主题 / 细分类的老单选控件已由筛选池接管（池子可累积多选），这里隐藏避免两套交互打架。 */
      .tb-spm-legacy-filter { display:none !important; }
      .tb-spm-view-hint { padding:6px 12px; color:#bbb; font-size:12px; }
      .tb-spm-plan-badge { color:#dec7ff; font-size:12px; }
      .tb-spm-string-badge { color:#9fd3ff; font-size:12px; }
      .tb-spm-tagedit { position:fixed; inset:0; background:rgba(0,0,0,.55); display:flex; align-items:center; justify-content:center; z-index:2147483000; }
      .tb-spm-tagedit-form { background:#22242c; border:1px solid #6d5aa8; border-radius:12px; padding:18px; width:min(620px,92vw); display:flex; flex-direction:column; gap:10px; color:#e8e6f2; }
      .tb-spm-tagedit-form h3 { margin:0; font-size:16px; }
      .tb-spm-tagedit-form label { display:flex; flex-direction:column; gap:5px; font-size:13px; }
      .tb-spm-tagedit-form input,.tb-spm-tagedit-form textarea { font:inherit; padding:7px; border-radius:6px; border:1px solid #737b8d; background:#2d313c; color:inherit; }
      .tb-spm-tagedit-actions { display:flex; gap:8px; justify-content:flex-end; }
      .tb-spm-tagedit-status { min-height:1em; font-size:12px; color:#ffb4b4; }
      .tb-spm-editor-source { border-top:1px solid #444; padding-top:8px; }
      .tb-spm-editor-source summary { cursor:pointer; margin-bottom:8px; }
      .tb-spm-plan-choice { display:flex; gap:8px; align-items:center; padding:10px; background:#292235; border-radius:8px; }
      .tb-spm-plan-choice input { width:auto; }
      .tb-spm-plan-help { font-size:12px; color:#bbb; margin:0; }
      .tb-spm-search { flex:1; height:30px; border:1px solid #4a4a4a; border-radius:8px; background:#171717; color:#f2f2f2; padding:0 10px; outline:none; }
      .tb-spm-small-btn { border:1px solid #555; border-radius:8px; background:#333; color:#eee; padding:6px 10px; cursor:pointer; white-space:nowrap; }
      .tb-spm-small-btn.primary { background:#7835dc; border-color:#8c54e6; color:#fff; font-weight:700; }
      .tb-spm-small-btn.danger { background:#4a2424; border-color:#7b3939; color:#ffcaca; }
      .tb-spm-small-btn:hover { filter:brightness(1.15); }
      .tb-spm-body { display:grid; grid-template-columns:1fr; min-height:0; flex:1; }
      .tb-spm-cats { border-right:1px solid #3b3b3b; overflow:auto; padding:8px; background:#202020; }
      .tb-spm-cat { width:100%; text-align:left; border:0; border-radius:8px; background:transparent; color:#ddd; padding:9px 10px; cursor:pointer; display:flex; justify-content:space-between; gap:8px; }
      .tb-spm-cat:hover { background:#303030; }
      .tb-spm-cat.active { background:#6b2bd9; color:#fff; }
      .tb-spm-count { opacity:.7; }
      .tb-spm-cat-filter { width:130px; height:30px; box-sizing:border-box; border:1px solid #4a4a4a; border-radius:8px; background:#171717; color:#f2f2f2; padding:0 9px; outline:none; }
      .tb-spm-cat-filter:focus { border-color:#8c54e6; box-shadow:0 0 0 2px rgba(140,84,230,.3); }
      .tb-spm-filters label.tb-spm-source-filter { display:flex; align-items:center; gap:6px; }
      /* grid-auto-rows 必须是 auto：曾经写成 1fr，在固定高度的滚动容器里所有行会平分高度，
         卡片被压成 1px（内容全被 overflow:hidden 吃掉），而且加 30 张卡片只让 scrollHeight
         涨 40px，于是"一屏装得下"永远成立 → 自动续拉一路补页 + 界面狂闪。 */
      .tb-spm-list { overflow:auto; min-height:0; padding:12px; display:grid; grid-template-columns:repeat(auto-fill, minmax(min(250px, 100%), 1fr)); grid-auto-rows:max-content; gap:12px; align-content:start; align-items:start; background:#181818; }
      .tb-spm-list > .tb-spm-status, .tb-spm-load-more { grid-column:1 / -1; }
      .tb-spm-card { border:1px solid #3d3d3d; border-radius:12px; background:#242424; overflow:hidden; display:flex; flex-direction:column; min-width:0; height:100%; }
      .tb-spm-img-wrap { height:190px; flex:0 0 190px; background:#111; display:flex; align-items:center; justify-content:center; border-bottom:1px solid #333; overflow:hidden; }
      .tb-spm-img-wrap img { width:100%; height:100%; object-fit:contain; object-position:center center; display:block; background:#111; }
      .tb-spm-no-img { color:#777; font-size:12px; }
      .tb-spm-load-more { min-height:44px; border:1px solid #4c4c4c; border-radius:8px; background:#2c2c2c; color:#f0f0f0; font-weight:800; cursor:pointer; }
      .tb-spm-load-more:hover { filter:brightness(1.14); }
      .tb-spm-card-main { padding:10px; display:flex; flex-direction:column; gap:8px; flex:1 0 auto; min-width:0; }
      .tb-spm-card-main > * { flex-shrink:0; }
      .tb-spm-merge-choice { font-size:12px; color:#d8c8ff; }
      .tb-spm-merge-tools { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:8px 12px; border-bottom:1px solid #4b3c61; background:#292235; flex-shrink:0; font-size:12px; }
      .tb-spm-merge-tools[hidden], .tb-spm-merge-choice[hidden] { display:none; }
      .tb-spm-alias { font-weight:750; line-height:1.25; overflow-wrap:anywhere; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; min-height:2.6em; }
      .tb-spm-catname { font-size:11px; color:#a993d5; }
      .tb-spm-prompt { color:#bfc6d1; font-size:12px; line-height:1.35; max-height:66px; overflow:hidden; word-break:break-word; }
      .tb-spm-desc { color:#8f98a3; font-size:12px; line-height:1.35; max-height:38px; overflow:hidden; }
      .tb-spm-actions { margin-top:auto; display:flex; gap:7px; flex-wrap:wrap; }
      .tb-spm-status { padding:16px; color:#bbb; }
      .tb-spm-error { color:#ff9b9b; }
      #${EDITOR_ID} { position:fixed; inset:0; z-index:2147482300; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,.55); color:#f0f0f0; font-family:system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
      .tb-spm-editor-box { width:min(760px, calc(100vw - 40px)); max-height:calc(100vh - 40px); overflow:hidden; display:flex; flex-direction:column; background:#222; border:1px solid #555; border-radius:12px; box-shadow:0 16px 60px rgba(0,0,0,.55); }
      .tb-spm-editor-head { display:flex; align-items:center; justify-content:space-between; padding:12px 14px; border-bottom:1px solid #444; background:#2b2b2b; font-weight:800; }
      .tb-spm-editor-form { padding:14px; display:grid; gap:10px; overflow:auto; min-height:0; }
      .tb-spm-editor-head,.tb-spm-editor-actions { flex-shrink:0; }
      .tb-spm-editor-recovery { max-height:28vh; overflow:auto; flex-shrink:0; }
      .tb-spm-views { flex-wrap:wrap; }
      .tb-spm-views select { max-width:220px; min-width:0; padding:5px 8px; border:1px solid #4a4a4a; border-radius:8px; background:#171717; color:#eee; }
      .tb-spm-field label { display:block; font-size:12px; color:#bfbfbf; margin-bottom:5px; }
      .tb-spm-field input, .tb-spm-field select, .tb-spm-field textarea { width:100%; box-sizing:border-box; border:1px solid #555; border-radius:8px; background:#151515; color:#eee; padding:8px 10px; outline:none; }
      .tb-spm-field textarea { min-height:96px; resize:vertical; }
      .tb-spm-field input[type="checkbox"] { width:auto; margin-right:6px; }
      .tb-spm-grid2 { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
      .tb-spm-editor-actions { display:flex; justify-content:flex-end; gap:8px; padding:12px 14px; border-top:1px solid #444; background:#252525; }
      .tb-spm-editor-recovery { margin:0 14px 12px; padding:10px; border:1px solid #a56b32; border-radius:8px; background:#3a2b20; }
      .tb-spm-recovery-title { font-weight:800; color:#ffd09a; margin-bottom:5px; }
      .tb-spm-recovery-error { color:#ffcaca; font-size:12px; margin-bottom:7px; }
      .tb-spm-recovery-compare pre { white-space:pre-wrap; max-height:130px; overflow:auto; margin:5px 0 9px; padding:7px; background:#211d1a; border-radius:5px; }
      .tb-spm-recovery-actions { display:flex; gap:8px; flex-wrap:wrap; }
      @media (max-width: 760px) { #${PANEL_ID} { left:14px; right:14px; bottom:14px; top:14px; width:auto; } .tb-spm-body { grid-template-columns:1fr; } .tb-spm-cats { display:flex; overflow:auto; border-right:0; border-bottom:1px solid #3b3b3b; } .tb-spm-cat { min-width:max-content; } .tb-spm-grid2 { grid-template-columns:1fr; } }
    `;
    document.head.appendChild(style);
  }
  function disconnectPreviewObserver() {
    if (previewObserver) previewObserver.disconnect();
    previewObserver = null;
  }
  function observeDeferredPreviews(listEl) {
    disconnectPreviewObserver();
    const images = Array.from(listEl?.querySelectorAll("img[data-src]") || []);
    if (!images.length) return;
    if (typeof IntersectionObserver === "undefined") {
      for (const image of images) {
        image.src = image.dataset.src;
        delete image.dataset.src;
      }
      return;
    }
    previewObserver = new IntersectionObserver((entries, observer) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const image = entry.target;
        if (image.dataset.src) {
          image.src = image.dataset.src;
          delete image.dataset.src;
        }
        observer.unobserve(image);
      }
    }, { root: listEl, rootMargin: "220px 0px", threshold: 0.01 });
    for (const image of images) previewObserver.observe(image);
  }
  function renderCategorySidebar(panel) {
    if (!panel) return;
    const catsEl = panel.querySelector(".tb-spm-cats");
    if (!catsEl) return;
    const activeCat = getCatById(activeCategoryId);
    catsEl.innerHTML = "";
    for (const group of groupedCategories()) {
      const id = group.id || group.name;
      const btn = document.createElement("button");
      const isActive = id === activeCategoryId || (!!activeCat?.name && group.name === activeCat.name);
      btn.className = "tb-spm-cat" + (isActive ? " active" : "");
      btn.dataset.categoryName = group.name || "";
      btn.title = group.objectCount > 1
        ? `同名分类对象 ${group.objectCount} 个，合计 ${group.count} 条`
        : `${group.count} 条`;
      btn.innerHTML = `<span>${escapeHtml(group.name || "未分类")}</span><span class="tb-spm-count">${group.count}</span>`;
      btn.onclick = async () => {
        viewMode = "all";
        activeCategoryId = id;
        searchText = "";
        const s = panel.querySelector(".tb-spm-search");
        if (s) s.value = "";
        resetCurrentItems();
        currentItemsLoading = true;
        renderPanelContent();
        try {
          await loadItemPage(true, 15000);
          renderPanelContent({revealResults: true});
        } catch (error) {
          showError(error);
        }
      };
      catsEl.appendChild(btn);
    }
  }
  function updateMergeControls(panel) {
    panel.querySelector('.tb-spm-merge-tools').hidden = !mergeMode;
    const toggle = panel.querySelector('[data-action="merge-mode"]');
    toggle.setAttribute('aria-pressed', String(mergeMode));
    toggle.textContent = mergeMode ? '正在整理重复资料' : '整理重复资料';
    const compare = panel.querySelector('[data-action="merge"]');
    compare.textContent = `查看合并对照（${mergeSelection.size}）`;
    compare.disabled = !mergeMode || mergeSelection.size < 2;
    panel.querySelectorAll('.tb-spm-merge-choice').forEach(label => {
      label.hidden = !mergeMode;
      if (!mergeMode) label.querySelector('input').checked = false;
    });
  }
  function revealFirstResult(panel, listEl) {
    listEl.scrollTop = 0;
    const first = listEl.querySelector('.tb-spm-card, .tb-spm-status');
    const outer = panel.closest('.uw-main');
    if (first && outer) {
      const head = panel.classList.contains('tb-spm-embedded') ? panel.querySelector('.tb-spm-head') : null;
      const inset = head ? head.getBoundingClientRect().height + parseFloat(getComputedStyle(outer).paddingTop || 0) : 0;
      outer.scrollTop += first.getBoundingClientRect().top - outer.getBoundingClientRect().top - inset - 8;
      panel.__tbRevealAnchor = { node: first, scrollTop: outer.scrollTop };
    }
  }
  function watchEmbeddedResize(panel) {
    panel.__tbResizeCleanup?.();
    if (!panel.classList.contains('tb-spm-embedded')) return;
    const outer = panel.closest('.uw-main');
    if (!outer) return;
    const controller = new AbortController();
    const observer = new MutationObserver(() => { if (!panel.isConnected) cleanup(); });
    let frame = 0;
    const cleanup = () => {
      controller.abort();
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
      delete panel.__tbResizeCleanup;
    };
    const onResize = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = 0;
        const anchor = panel.__tbRevealAnchor;
        if (!panel.isConnected || !anchor?.node?.isConnected || Math.abs(outer.scrollTop - anchor.scrollTop) > 2) return;
        const head = panel.querySelector('.tb-spm-head');
        if (!head) return;
        const gap = anchor.node.getBoundingClientRect().top - head.getBoundingClientRect().bottom;
        if (gap < 8) {
          outer.scrollTop += gap - 8;
          anchor.scrollTop = outer.scrollTop;
        }
      });
    };
    observer.observe(panel.parentElement, { childList: true });
    const workbench = panel.closest('#unified-workbench');
    if (workbench?.parentElement) observer.observe(workbench.parentElement, { childList: true });
    window.addEventListener('resize', onResize, { signal: controller.signal });
    panel.__tbResizeCleanup = cleanup;
  }
  // options.appendFrom > 0 = 续拉分页：只把新一页的卡片接到列表尾部，不重建整表。
  // 整表重建会把已经显示好的缩略图全部重刷一遍（视觉上就是闪一下），滚动位置也会被顶掉。
  function renderPanelContent(options = {}) {
    if(listError){showError(listError);return;}
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;
    loadMoreCleanup?.();
    const catsEl = panel.querySelector(".tb-spm-cats");
    const listEl = panel.querySelector(".tb-spm-list");
    listEl.inert = false; listEl.removeAttribute("aria-busy");
    const items = allFilteredItems();
    const visibleItems = items;
    const visibleTotal = displayedItemsTotal();
    let appendFrom = Number.isInteger(options.appendFrom) && options.appendFrom > 0 ? options.appendFrom : 0;
    // 只有"列表里确实已经摆着 appendFrom 张卡片、而且后面还有新条目"时才走追加路径。
    if (appendFrom && (visibleItems.length <= appendFrom || listEl.querySelectorAll(".tb-spm-card").length !== appendFrom)) {
      appendFrom = 0;
    }
    const previousScrollTop = listEl.scrollTop;
    let focused = null;
    let focusedId = null;
    let focusedAction = null;
    if (!appendFrom) {
      // 整表重建之后必须重新等一次真实滚动，否则"重建 → 按钮回到视口"会立刻又补一页。
      loadMoreArmed = false;
      updateViewControls(panel);
      updateMergeControls(panel);
      focused = listEl.contains(document.activeElement) ? document.activeElement : null;
      focusedId = focused?.closest('.tb-spm-card')?.dataset.promptId;
      focusedAction = focused?.dataset.act;
      const previousCatsScroll = catsEl ? catsEl.scrollTop : 0;
      renderCategorySidebar(panel);
      // 侧栏（全部来源/分类）是可滚动列表，重渲染后必须把滚动位置放回去，
      // 否则用户拖到一半松手时会因为一次重渲染弹回顶部。
      if (catsEl) catsEl.scrollTop = previousCatsScroll;
      disconnectPreviewObserver();
      listEl.innerHTML = "";
      if (loadMoreObserver) { loadMoreObserver.disconnect(); loadMoreObserver = null; }
    } else {
      // 续拉：只摘掉上一颗「显示更多」，已有卡片原地不动。
      listEl.querySelector(".tb-spm-load-more")?.remove();
    }
    if (!appendFrom) {
      if (currentItemsLoading && !items.length) {
        listEl.innerHTML = `<div class="tb-spm-status">正在加载资料...</div>`;
        return;
      }
      if (!items.length) {
        listEl.innerHTML = `<div class="tb-spm-status">${viewMode === "plans" ? "没有匹配的已保存方案。可从当前提示词保存方案，或在资料卡片上选择“设为我的方案”。原有组合段可在全部资料中查找。" : viewMode === "favorites" ? "没有匹配的收藏资料。可在编辑资料中设置收藏。" : viewMode === "recent" ? "还没有匹配的使用记录；明确插入资料后会记录最近使用。" : "没有匹配的资料，可清空筛选重试。"}</div>`;
        if (currentItems.length >= currentItemsTotal || !visibleTotal) {
          if (options.revealResults) revealFirstResult(panel, listEl);
          return;
        }
        listEl.innerHTML = '<div class="tb-spm-status">当前已加载页没有可展示的资料，可继续加载。</div>';
      }
    }
    let itemIndex = appendFrom;
    for (let itemAt = appendFrom; itemAt < visibleItems.length; itemAt += 1) {
      const item = visibleItems[itemAt];
      const card = document.createElement("div");
      card.className = "tb-spm-card";
      card.dataset.promptId = String(item.id);
      card.classList.toggle('tb-spm-card-selected', selectedPromptCards.has(String(item.id)));
      const imageSrc = item.image
        ? `${THUMBNAIL_URL}${encodeURIComponent(item.image)}?t=${encodeURIComponent(item.updated_at || "")}`
        : (/^https?:\/\//i.test(item.preview_url || '') ? item.preview_url : "");
      const imageLoading = itemIndex < EAGER_PREVIEW_COUNT ? "eager" : "lazy";
      const imageSourceAttr = itemIndex < EAGER_PREVIEW_COUNT
        ? `src="${escapeAttr(imageSrc)}"`
        : `data-src="${escapeAttr(imageSrc)}"`;
      const image = imageSrc
        ? `<img ${imageSourceAttr} alt="${escapeAttr(item.alias || '资料')}预览图" loading="${imageLoading}" decoding="async" data-preview-name="${escapeAttr(item.image)}">`
        : `<div class="tb-spm-no-img">${item.strings ? "暂无预览图 · 可点此绑定" : "暂无预览图"}</div>`;
      const supportedInsertActions = insertionTarget?.onInsert?.supportsActions || ["append_end"];
      const insertActionLabels = { append_end: "追加到末尾", append_cursor: "插入到光标", replace_selection: "替换选区", replace_prompt: "替换正文" };
      const insertOptions = supportedInsertActions
        .filter(action => insertActionLabels[action])
        .map(action => `<option value="${action}" ${action===insertionTarget?.onInsert?.defaultAction?'selected':''}>${insertActionLabels[action]}</option>`).join("");
      itemIndex += 1;
      card.innerHTML = `
        <div class="tb-spm-img-wrap">${image}</div>
        <div class="tb-spm-card-main">
          <div class="tb-spm-alias">${escapeHtml(item.alias || "未命名")}</div>
          ${item.match_reason ? `<div class="tb-spm-desc">命中：${escapeHtml(item.match_reason)}</div>` : ""}
          <label class="tb-spm-merge-choice" ${mergeMode ? "" : "hidden"}><input type="checkbox" data-act="merge-select" aria-label="选择合并：${escapeAttr(item.alias || item.id)}" ${mergeSelection.has(item.id) ? "checked" : ""}> 选中此资料</label>
          ${cardThemeLine(item) ? `<div class="tb-spm-desc">${escapeHtml(cardThemeLine(item))}</div>` : ""}
          <div class="tb-spm-desc">${escapeHtml(({atomic_tag:"单一概念",fragment:"片段",template:"组合段",model_reference:"模型引用"})[item._semantic?.content_type] || "形式待确认")}</div>
          ${item.is_user_plan === true ? '<div class="tb-spm-plan-badge">我的方案 · 明确保存后复用</div>' : ""}
          ${item.strings ? '<div class="tb-spm-string-badge">法典串 · 原法典分组（数据仍单一保存在 tag 字典）</div>' : ""}
          ${item._semantic?.declared_usage === "mixed" ? '<div class="tb-spm-desc">包含正负向分段，请编辑后分别使用</div>' : item._semantic?.usage === "negative" ? '<div class="tb-spm-desc">负向内容</div>' : ""}
          ${item._import_quarantine ? `<div class="tb-spm-desc">${item._semantic?.manual_search_eligible ? "原导入异常已人工确认" : "导入异常，需核查"}：${escapeHtml((Array.isArray(item._import_quarantine.issues) ? item._import_quarantine.issues : []).join("；"))}。原始记录已保留。</div>` : ""}
          <div class="tb-spm-prompt">${escapeHtml(String(item.prompt || "").slice(0, 360))}${String(item.prompt || "").length > 360 ? '…' : ''}</div>
          ${item.description && !isProvenanceDescription(item.description) ? `<div class="tb-spm-desc">${escapeHtml(item.description)}</div>` : ""}
          <div class="tb-spm-card-feedback" role="status" aria-live="polite"></div>
          <div class="tb-spm-actions">
            <select class="tb-spm-insert-mode" data-act="insert-mode" title="选择写入动作">${insertOptions}</select>
            <button class="tb-spm-small-btn primary" data-act="insert" ${item._semantic?.manual_search_eligible === true ? "" : 'disabled title="请先编辑并确认主题"'}>插入</button>
            <button class="tb-spm-small-btn" data-act="copy">复制</button>
            ${item.strings ? `<button class="tb-spm-small-btn" data-act="edit">编辑</button>` : `
            <button class="tb-spm-small-btn" data-act="edit">编辑</button>
            <button class="tb-spm-small-btn" data-act="plan" ${item._semantic?.manual_search_eligible === true ? "" : "disabled"}>${item.is_user_plan === true ? "取消方案标记" : "设为我的方案"}</button>
            <button class="tb-spm-small-btn danger" data-act="delete">删除</button>`}
          </div>
        </div>`;
      const previewImg = card.querySelector(".tb-spm-img-wrap img");
      const mergeCheckbox = card.querySelector('[data-act="merge-select"]');
      mergeCheckbox.onclick = event => event.stopPropagation();
      mergeCheckbox.onchange = () => {
        if (!mergeMode) return;
        if (mergeCheckbox.checked) mergeSelection.add(item.id); else mergeSelection.delete(item.id);
        updateMergeControls(panel);
      };
      if (previewImg) {
        previewImg.onerror = () => {
          const wrap = card.querySelector(".tb-spm-img-wrap");
          if (wrap) {
            const notice=document.createElement('div');notice.className='tb-spm-no-img';
            notice.textContent='预览图暂未加载，正文仍可使用。';
            const retry=document.createElement('button');retry.type='button';retry.className='tb-spm-small-btn';retry.textContent='重试预览图';
            retry.onclick=event=>{event.stopPropagation();wrap.replaceChildren(previewImg);previewImg.loading='eager';previewImg.src=imageSrc;};
            notice.append(document.createElement('br'),retry);wrap.replaceChildren(notice);
          }
        };
      }
      // 法典串没有自带预览图，允许自己上传并绑定（文件名存进 tag 元数据，
      // 缩略图仍走同一个 /prompt_selector/thumbnail 接口）。
      const bindPreview = async file => {
        if (!file) return;
        const form = new FormData();
        form.append("image", file);
        form.append("alias", "tag-" + String(item.id || "tag").replace(/[^a-zA-Z0-9]/g, "").slice(-16));
        const upload = await fetch("/prompt_selector/upload_image", {method: "POST", body: form});
        const uploaded = await upload.json().catch(() => ({}));
        if (!upload.ok || uploaded.error || !uploaded.filename) {
          throw new Error(uploaded.error || `上传失败 HTTP ${upload.status}`);
        }
        const response = await fetch("/prompt_selector/tags/update", {
          method: "POST",
          headers: {"Content-Type": "application/json", "If-Match": String(item._revision || "")},
          body: JSON.stringify({entity: "tag", operation: "metadata", resource_id: item.id,
                                preview: uploaded.filename}),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.error) throw new Error(result.error || `HTTP ${response.status}`);
        await loadData(true, 15000, true);
        renderPanelContent();
      };
      const imageWrap = card.querySelector(".tb-spm-img-wrap");
      if (item.strings && imageWrap) {
        imageWrap.style.cursor = "pointer";
        imageWrap.title = item.image ? "点击更换预览图" : "点击上传并绑定预览图";
        imageWrap.onclick = event => {
          event.stopPropagation();
          const picker = document.createElement("input");
          picker.type = "file";
          picker.accept = "image/*";
          picker.onchange = () => bindPreview(picker.files && picker.files[0]).catch(showError);
          picker.click();
        };
      }
      card.querySelector('[data-act="insert"]').onclick = (e) => {
        e.stopPropagation();
        const mode = card.querySelector('[data-act="insert-mode"]')?.value || "append_end";
        insertPrompt(item.prompt, mode, item, e.currentTarget);
      };
      const insertMode = card.querySelector('[data-act="insert-mode"]');
      const insertButton = card.querySelector('[data-act="insert"]');
      const updateInsertLabel = () => {
        insertButton.textContent = insertActionLabels[insertMode.value] || "追加到末尾";
        insertButton.disabled = !insertionTarget || item._semantic?.manual_search_eligible !== true;
      };
      insertMode.onchange = updateInsertLabel;
      updateInsertLabel();
      // 法典串条目（item.strings）来自 tag 字典，只提供插入/复制：编辑、删除、方案标记
      // 都是资源库侧的操作，这里刻意不渲染按钮。
      const editButton = card.querySelector('[data-act="edit"]');
      if (editButton) editButton.onclick = (e) => {
        e.stopPropagation();
        // 法典串的正文与中文名存在 tag 字典里，编辑走 tag 侧的 CAS 接口
        // （正文改动本身会按既有规则镜像回资源库里的同概念条目）。
        if (item.strings) openStringEditor(item); else openEditor("edit", item._categoryId, item.id);
      };
      const planButton = card.querySelector('[data-act="plan"]');
      if (planButton) planButton.onclick = async event => {
        event.stopPropagation();
        const button = card.querySelector('[data-act="plan"]');
        if (button.disabled) return;
        button.disabled = true;
        try {
          const resp = await fetchLibraryWrite("/prompt_selector/prompts/plan", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt_id: item.id, is_user_plan: item.is_user_plan !== true }),
          });
          const json = await resp.json().catch(() => ({}));
          if (!resp.ok || json.error) throw new Error(json.error || `HTTP ${resp.status}`);
          await loadData(true, 15000, true);
          renderPanelContent();
        } catch (error) { showError(error); }
        finally { button.disabled = false; }
      };
      const deleteButton = card.querySelector('[data-act="delete"]');
      if (deleteButton) deleteButton.onclick = async (e) => { e.stopPropagation(); await deletePrompt(item._categoryId, item.id, item.alias); };
    card.ondblclick = () => {
      selectedPromptCards.add(String(item.id));
      card.classList.add("tb-spm-card-selected");
      updateBulkMetadataCount(document.getElementById(PANEL_ID));
    };
      simplifyResourceCard(card, item);
      listEl.appendChild(card);
      void annotateEmbeddingReferences(card, item.prompt);
    }
    if (focusedId && focusedAction) {
      const card = [...listEl.querySelectorAll('.tb-spm-card')].find(item => item.dataset.promptId === focusedId);
      const action = [...card?.querySelectorAll('[data-act]') || []].find(item => item.dataset.act === focusedAction);
      const target=action?.closest('details:not([open])')?.querySelector('summary')||action;
      if (target && editorElementVisible(target) && !target.disabled) target.focus({preventScroll:true});
    }
    if (!appendFrom) listEl.scrollTop = previousScrollTop;
    if (currentItems.length < currentItemsTotal && visibleItems.length < visibleTotal) {
      const more = document.createElement("button");
      more.className = "tb-spm-load-more";
      more.textContent = `显示更多 / 共 ${visibleTotal} 条`;
      listEl.appendChild(more);
      // 滚到底自动续拉（按钮仍保留，加载失败时可点重试）。
      let loadingMore = false;
      const autoLoadMore = async () => {
        if (loadingMore) return;
        loadingMore = true;
        const moreFocused = document.activeElement === more;
        const renderedBefore = listEl.querySelectorAll('.tb-spm-card').length;
        more.textContent = "加载中…";
        const loadedBefore = currentItems.length;
        const page = loadItemPage(false, 15000);
        const pageToken = listRequestToken;
        try {
          await page;
          if (pageToken !== listRequestToken || !more.isConnected) return;
          if (allFilteredItems().length === renderedBefore) {
            if (currentItems.length >= currentItemsTotal || renderedBefore >= displayedItemsTotal()) {
              more.remove();
              loadMoreCleanup?.();
              if (moreFocused) listEl.querySelector('.tb-spm-card:last-child .tb-spm-alias')?.focus();
            } else if (currentItems.length === loadedBefore) {
              more.textContent = "分页未返回新资料，刷新列表后重试";
              more.onclick = () => panel.querySelector('[data-action="refresh"]')?.click();
              loadMoreCleanup?.();
            } else {
              more.textContent = "当前页无可展示资料，继续加载";
            }
            return;
          }
          // 只把新一页接到列表尾部：整表重建会把已显示的缩略图全部重刷并顶掉滚动位置，
          // 看起来就是一次闪屏。
          renderPanelContent({appendFrom: renderedBefore});
          if (moreFocused) {
            const nextCard = listEl.querySelectorAll('.tb-spm-card')[renderedBefore];
            (nextCard?.querySelector('.tb-spm-alias') || listEl.querySelector('.tb-spm-load-more'))?.focus();
          }
        } catch (error) {
          if (pageToken !== listRequestToken || !more.isConnected) return;
          more.textContent = "加载失败，点此重试";
          more.onclick = () => { more.onclick = null; void autoLoadMore(); };
        } finally {
          loadingMore = false;
        }
      };
      more.onclick = () => { void autoLoadMore(); };
      // 续拉触发条件（缺一不可）：
      //   ① 用户自己滚过（wheel / 触摸 / 键盘 / 拖动滚动条）——见 bindLoadMoreGesture，
      //      程序性滚动不算，列表重建后不会自触发；
      //   ② 「显示更多」这颗按钮（也就是最后一行的下一行）**完整落在视口里**；
      //   ③ 它所在的滚动容器确实已经滚到底；
      //   ④ 一次手势最多补一页：加载成功后解除武装，要再滚一次才会继续。
      // 不用 IntersectionObserver / 定时器的原因：
      //   ① 列表重建时 listEl.innerHTML="" 会让按钮瞬间回到视口，观察器立刻判定
      //      "该加载了" → 又加载 → 又重建，一路补页并狂闪；
      //   ② 嵌入模式（提示词片段）下列表是 overflow:visible，由外层 .uw-main 滚动，
      //      listEl.scrollHeight 恒等于 clientHeight，"一屏装得下"永远成立，同样会无限补页。
      const fullyInView = () => {
        const rect = more.getBoundingClientRect();
        const vh = window.innerHeight || document.documentElement.clientHeight || 0;
        return rect.height > 0 && rect.top >= 0 && rect.bottom <= vh - 2;
      };
      const atBottomOfScroller = () => {
        const candidates = [];
        const view = document.scrollingElement || document.documentElement;
        if (view) candidates.push(view);
        for (let node = more.parentElement; node; node = node.parentElement) {
          const overflowY = getComputedStyle(node).overflowY;
          if (overflowY === "auto" || overflowY === "scroll") candidates.push(node);
        }
        // 必须"真的能滚 + 已经滚到底"：不可滚动的容器不算，否则等于永远成立。
        return candidates.some(node => node.scrollHeight > node.clientHeight + 4
          && node.scrollTop + node.clientHeight >= node.scrollHeight - 4);
      };
      const onScrollCheck = () => {
        if (loadingMore || !more.isConnected || !loadMoreArmed) return;
        if (!fullyInView() || !atBottomOfScroller()) return;
        loadMoreArmed = false;
        void autoLoadMore();
      };
      bindLoadMoreGesture(panel, onScrollCheck);
    }
    if (options.revealResults) revealFirstResult(panel, listEl);
    observeDeferredPreviews(listEl);
  }
  // 法典串（item.strings）的编辑：正文与中文名存放在 tag 字典里，所以走 tag 侧的
  // CAS 接口；正文改动本身会按既有"双库同源"规则镜像回资源库的同概念条目。
  function openStringEditor(item) {
    document.getElementById("tb-string-editor")?.remove();
    const overlay = document.createElement("div");
    overlay.id = "tb-string-editor";
    overlay.className = "tb-spm-tagedit";
    overlay.innerHTML = `
      <form class="tb-spm-tagedit-form">
        <h3>编辑法典串</h3>
        <div class="tb-spm-desc">这条保存在 tag 字典（法典原分组：${escapeHtml(item._categoryName || "")}）；保存后会同步到基础 Tag。</div>
        <label>中文名<input name="desc" value="${escapeAttr(item.alias || "")}" placeholder="可以留空"></label>
        <label>正文<textarea name="text" rows="6">${escapeHtml(item.prompt || "")}</textarea></label>
        <div class="tb-spm-tagedit-actions">
          <button type="button" data-act="cancel">取消</button>
          <button type="submit" class="primary" data-act="save">保存</button>
        </div>
        <div class="tb-spm-tagedit-status" role="status"></div>
      </form>`;
    document.body.appendChild(overlay);
    const form = overlay.querySelector("form");
    const status = overlay.querySelector(".tb-spm-tagedit-status");
    const close = () => overlay.remove();
    overlay.querySelector('[data-act="cancel"]').onclick = close;
    overlay.onclick = event => { if (event.target === overlay) close(); };
    form.onsubmit = async event => {
      event.preventDefault();
      const button = form.querySelector('[data-act="save"]');
      button.disabled = true;
      status.textContent = "正在保存…";
      try {
        const response = await fetch("/prompt_selector/tags/update", {
          method: "POST",
          headers: {"Content-Type": "application/json", "If-Match": String(item._revision || "")},
          body: JSON.stringify({entity: "tag", operation: "edit", resource_id: item.id,
                                text: form.elements.text.value, desc: form.elements.desc.value}),
        });
        const json = await response.json().catch(() => ({}));
        if (response.status === 409) throw new Error("这条刚被别人改过，请刷新后再编辑。");
        if (!response.ok || json.error) throw new Error(json.error || `HTTP ${response.status}`);
        close();
        await loadData(true, 15000, true);
        renderPanelContent();
      } catch (error) {
        status.textContent = error.message || String(error);
        button.disabled = false;
      }
    };
    form.elements.text.focus();
  }
  function showError(err) {
    if(err?.listRequestToken != null && err.listRequestToken !== listRequestToken)return;
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;
    loadMoreCleanup?.();
    const raw = err && err.message ? err.message : String(err);
    const msg = /fetch|network|load failed/i.test(raw) ? "无法连接资料服务，请检查 ComfyUI 是否运行" : raw;
    const hint=panel.querySelector(".tb-spm-view-hint");if(hint)hint.textContent="读取失败 · 总数暂不可用，筛选与编辑草稿保留";
    panel.querySelector(".tb-spm-cats")?.replaceChildren();
    panel.querySelector(".tb-spm-list").innerHTML = `<div class="tb-spm-status tb-spm-error">${err?.deleted ? "这条资料当前已不存在，原收藏仍保留。请核对来源后恢复或重新收藏。" : `资料读取失败：${escapeHtml(msg)}。可刷新重试，未提交的编辑仍保留。`}</div>`;
  }
  function mergeSourceMarkup(row) {
    const p = row.prompt, semantic = row.classification || p._classification || {};
    const known = new Set(['id','alias','aliases','prompt','description','tags','image','favorite','template','usage_count','last_used','created_at','updated_at','_classification','_semantic','_merge_sources']);
    const other = Object.fromEntries(Object.entries(p).filter(([key]) => !known.has(key)));
    return `<details open><summary>${escapeHtml(p.alias)} · ${escapeHtml(row.category.name)}</summary><p>原 ID：${escapeHtml(p.id)}；收藏：${p.favorite ? '是' : '否'}；使用次数：${p.usage_count || 0}</p><p>用途：${semantic.usage === 'negative' ? '负向' : '正向'}；模型范围：${escapeHtml(semantic.model_scope)}；形式：${escapeHtml(({fragment:'局部片段',template:'组合段',atomic_tag:'单一概念',model_reference:'模型引用'})[semantic.content_type] || '未确认')}</p><p>别名：${escapeHtml((p.aliases || []).join('、'))}；标签：${escapeHtml((p.tags || []).join('、'))}</p><p>${escapeHtml(p.description || '')}</p>${p.image ? `<a href="/prompt_selector/preview/${encodeURIComponent(p.image)}" target="_blank" rel="noopener">原预览：${escapeHtml(p.image)}</a>` : '<p>无预览图</p>'}<pre style="white-space:pre-wrap;overflow-wrap:anywhere">${escapeHtml(p.prompt)}</pre>${Object.keys(other).length ? `<details><summary>其他来源字段</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${escapeHtml(JSON.stringify(other,null,2))}</pre></details>` : ''}</details>`;
  }
  async function openMergeReview() {
    if (!mergeMode || mergeSelection.size < 2 || editing || document.getElementById('tb-shared-merge-review')) return;
    const ids = [...mergeSelection];
    const revision = libraryRevision;
    const operationId = uuid();
    const overlay = document.createElement('div');
    overlay.id = 'tb-shared-merge-review';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', '合并资料对照');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:2147482300;background:#000a;display:grid;place-items:center';
    overlay.innerHTML = `<div style="background:#25252a;color:#eee;width:min(740px,94vw);max-height:90vh;overflow:auto;padding:18px;border-radius:10px">
      <h3>合并资料对照</h3>
      <p>任务编号：<code data-merge="number">${escapeHtml(operationId)}</code>。关闭后可按编号恢复这份清单。</p>
      <div data-merge="content">读取所选资料...</div>
      <div data-merge="result" hidden></div>
      <div data-merge="error" role="alert" style="color:#ffb4b4;white-space:pre-wrap"></div>
      <div data-merge="actions">
        <button data-merge="export">导出结果</button>
        <button data-merge="export-unmerged" disabled>导出未并入清单</button>
        <button data-merge="cancel">关闭</button>
        <button data-merge="commit" disabled>确认合并并保留全部来源</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    const cancel = overlay.querySelector('[data-merge="cancel"]');
    const commit = overlay.querySelector('[data-merge="commit"]');
    const error = overlay.querySelector('[data-merge="error"]');
    const resultHost = overlay.querySelector('[data-merge="result"]');
    const exportResult = overlay.querySelector('[data-merge="export"]');
    const exportUnmerged = overlay.querySelector('[data-merge="export-unmerged"]');
    cancel.onclick = () => overlay.remove();
    exportResult.onclick = () => exportMergeResult(operationId, 'items').catch(failure => { error.textContent = failure.message; });
    exportUnmerged.onclick = () => exportMergeResult(operationId, 'unmerged_ids').catch(failure => { error.textContent = failure.message; });
    const request = async (url, payload) => {
      const response = await fetchWithTimeout(url, {method:'POST', headers:{'Content-Type':'application/json','If-Match':revision}, body:JSON.stringify(payload)}, 30000);
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.error) {
        const failure = new Error(result.error || `HTTP ${response.status}`);
        failure.body = result;
        throw failure;
      }
      return result;
    };
    function showResult(result) {
      if (result.revision) libraryRevision = result.revision;
      resultHost.innerHTML = mergeResultMarkup(result);
      resultHost.hidden = false;
      exportUnmerged.disabled = !(result.items || []).some(row => row.status !== 'merged' && row.status !== 'kept');
      commit.hidden = true;
      cancel.disabled = false;
      cancel.textContent = result.status === 'committed' ? '完成' : '关闭';
    }
    try {
      const preview = await request(MERGE_PREVIEW_URL, {operation_id:operationId,prompt_ids:ids,canonical_id:ids[0]});
      if (!overlay.isConnected) return;
      const canonical = preview.sources.find(row => row.prompt.id === preview.canonical_id);
      const mergeable = (preview.items || []).filter(row => row.status === 'merged');
      overlay.querySelector('[data-merge="content"]').innerHTML = `<p>保留“${escapeHtml(canonical.prompt.alias)}”作为维护资料；其余旧 ID 指向它。正文不改写，原始记录和预览保留。</p><p>将并入 ${mergeable.length} 条：${escapeHtml(mergeable.map(row => row.alias || row.resource_id).join('、') || '无')}。以下逐条给出结果。</p><p>请核对各来源、收藏和其他元数据。差异字段：${escapeHtml(preview.differing_fields.map(key=>({alias:'名称',aliases:'别名',image:'预览',favorite:'收藏',description:'描述',tags:'标签',updated_at:'更新时间',created_at:'创建时间',usage_count:'使用次数',last_used:'最近使用'})[key] || key).join('、') || '无')}。</p>${mergeOutcomeMarkup(preview)}${preview.sources.map(mergeSourceMarkup).join('')}<label><input type="checkbox" data-merge="reviewed"> 我已核对来源及元数据差异，同意保留所有原始版本并合并维护</label>`;
      overlay.querySelector('[data-merge="reviewed"]').onchange = event => { commit.disabled = !event.target.checked; };
      if (!mergeable.length) {
        commit.textContent = '没有可并入的资料';
        overlay.querySelector('[data-merge="reviewed"]').disabled = true;
      }
      commit.onclick = async () => {
        if (commit.disabled) return;
        commit.disabled = true; cancel.disabled = true; error.textContent = '';
        try {
          const result = await request(MERGE_COMMIT_URL, {operation_id:operationId,prompt_ids:ids,canonical_id:preview.canonical_id,commit:true,metadata_reviewed:true,review_token:preview.review_token});
          showResult(result);
          mergeSelection.clear();
          await loadData(true,15000,true); renderPanelContent();
        } catch (failure) {
          const failed = failure.body && Array.isArray(failure.body.items) ? failure.body : null;
          if (failed) { showResult(failed); error.textContent = failure.message; }
          else { error.textContent = `合并未完成：${failure.message}。请关闭后重新对照最新资料。`; }
          cancel.disabled = false;
        }
      };
    } catch (failure) {
      error.textContent = `${failure.message}。请关闭后重新对照最新资料。`;
      commit.disabled = true;
    }
  }
  function mergeOutcomeMarkup(result) {
    const rows = Array.isArray(result.items) ? result.items : [];
    if (!rows.length) return '';
    return `<ul data-merge="outcome" style="padding-left:18px">${rows.map(row => `<li data-merge-row="${escapeAttr(row.resource_id)}" data-status="${escapeAttr(row.status)}">${escapeHtml(row.alias || row.resource_id)}（<code>${escapeHtml(row.resource_id)}</code>）${row.status === 'merged' ? `→ 并入 <code>${escapeHtml(row.target_id || '')}</code>` : row.status === 'kept' ? '→ 保留为维护资料' : row.status === 'skipped' ? `→ 未并入：${escapeHtml(row.reason || '未说明')}` : `→ 失败：${escapeHtml(row.reason || '未说明')}`}</li>`).join('')}</ul>`;
  }
  function mergeResultMarkup(result) {
    const counts = result.counts || {};
    const status = result.status || 'unknown';
    const failure = (result.failure && result.failure.message) || result.error || '';
    const headline = status === 'committed'
      ? `已保存：并入 ${counts.merged ?? 0} 条，保留 ${counts.kept ?? 0} 条，未并入 ${counts.skipped ?? 0} 条${counts.failed ? `，失败 ${counts.failed} 条` : ''}。`
      : `本次未写入任何资料：并入 0 条，未并入 ${counts.skipped ?? 0} 条，失败 ${counts.failed ?? 0} 条。`;
    return `<p>任务编号：<code data-merge="number">${escapeHtml(result.operation_id || '')}</code>（状态：${escapeHtml(status)}）</p>
      <p>${escapeHtml(headline)}${failure ? ` ${escapeHtml(failure)}` : ''}</p>
      <p>保留资料：<code>${escapeHtml(result.canonical_id || '')}</code>。逐条结果如下，可导出后交给其他窗口核对。</p>
      ${mergeOutcomeMarkup(result) || '<p>没有逐条结果。</p>'}`;
  }
  function downloadJsonFile(name, data) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url);
  }
  async function exportMergeResult(operationId, kind) {
    if (!operationId) throw new Error('缺少任务编号，无法导出');
    const response = await fetchWithTimeout(`${MERGE_TASK_URL}${encodeURIComponent(operationId)}/export?kind=${encodeURIComponent(kind)}`, {}, 20000);
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.error) throw new Error(result.error || `HTTP ${response.status}`);
    const label = kind === 'unmerged_ids' ? '合并未并入清单' : '合并结果';
    downloadJsonFile(`${label}-${operationId}.json`, result);
    return result;
  }
  function openMergeResultsDialog(initialId) {
    if (document.getElementById('tb-shared-merge-results')) return;
    const overlay = document.createElement('div');
    overlay.id = 'tb-shared-merge-results';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', '合并结果');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:2147482300;background:#000a;display:grid;place-items:center';
    overlay.innerHTML = `<div style="background:#25252a;color:#eee;width:min(740px,94vw);max-height:90vh;overflow:auto;padding:18px;border-radius:10px">
      <h3>合并结果</h3>
      <label>任务编号<input data-merge-results="number" placeholder="粘贴合并时显示的任务编号" value="${escapeAttr(initialId || '')}" style="display:block;width:100%;box-sizing:border-box;margin:6px 0;padding:8px"></label>
      <div data-merge-results="body">按编号核验后显示逐条结果。</div>
      <div data-merge-results="error" role="alert" style="color:#ffb4b4;white-space:pre-wrap"></div>
      <div>
        <button data-merge-results="check">核验结果</button>
        <button data-merge-results="export" disabled>导出结果</button>
        <button data-merge-results="export-unmerged" disabled>导出未并入清单</button>
        <button data-merge-results="close">关闭</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    const input = overlay.querySelector('[data-merge-results="number"]');
    const body = overlay.querySelector('[data-merge-results="body"]');
    const error = overlay.querySelector('[data-merge-results="error"]');
    const exportAll = overlay.querySelector('[data-merge-results="export"]');
    const exportUnmerged = overlay.querySelector('[data-merge-results="export-unmerged"]');
    overlay.querySelector('[data-merge-results="close"]').onclick = () => overlay.remove();
    async function check() {
      const id = input.value.trim();
      error.textContent = '';
      if (!id) { error.textContent = '请填写任务编号。'; return; }
      body.textContent = '正在读取合并结果…';
      try {
        const response = await fetchWithTimeout(`${MERGE_TASK_URL}${encodeURIComponent(id)}`, {}, 20000);
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.error) throw new Error(result.error || `HTTP ${response.status}`);
        body.innerHTML = mergeResultMarkup(result);
        exportAll.disabled = false; exportUnmerged.disabled = false;
      } catch (failure) {
        body.textContent = '按编号核验后显示逐条结果。';
        error.textContent = failure.message;
        exportAll.disabled = true; exportUnmerged.disabled = true;
      }
    }
    exportAll.onclick = () => exportMergeResult(input.value.trim(), 'items').catch(failure => { error.textContent = failure.message; });
    exportUnmerged.onclick = () => exportMergeResult(input.value.trim(), 'unmerged_ids').catch(failure => { error.textContent = failure.message; });
    overlay.querySelector('[data-merge-results="check"]').onclick = () => void check();
    if (initialId) void check(); else input.focus();
  }
  function renderCollectionChoices(host, groups, selected, onChange) {
    const choices = [...groups, ...selected.filter(id => !groups.some(group => group.id === id)).map(id => ({id, name:'已删除的组（取消勾选后可保存）'}))];
    for (const group of choices) {
      const row = document.createElement('label');row.style.display='block';
      const input = document.createElement('input');input.type='checkbox';input.value=group.id;
      input.dataset.collectionId=group.id;input.checked=selected.includes(group.id);
      input.onchange=()=>onChange(Array.from(host.querySelectorAll('input:checked'), element=>element.value));
      row.append(input,document.createTextNode(group.name));host.appendChild(row);
    }
  }
  function mountQuickCollections(menu, more, item) {
    const section=document.createElement('section');section.className='tb-spm-quick-collections';menu.append(section);
    const title=document.createElement('strong');title.textContent='加入分组';section.append(title);
    const choices=document.createElement('div');choices.style.cssText='max-height:180px;overflow:auto';section.append(choices);
    const status=document.createElement('p');status.setAttribute('role','status');section.append(status);
    const save=document.createElement('button');save.dataset.act='save-groups';save.className='tb-spm-small-btn';save.textContent='保存分组';save.disabled=true;section.append(save);
    const reload=document.createElement('button');reload.dataset.act='reload-groups';reload.className='tb-spm-small-btn';reload.textContent='重新读取分组';section.append(reload);
    let snapshot=null,selected=null,reading=false,saving=false;
    const read=async()=>{
      if(reading||saving)return;reading=true;save.disabled=true;reload.disabled=true;status.textContent='正在读取分组…';
      try {
        const latest=await fetchSharedItem(item.id,15000);
        if(!section.isConnected)return;
        snapshot=latest;selected=selected||[...(latest.collection_ids||['default'])];
        choices.replaceChildren();renderCollectionChoices(choices,latest.collections||[],selected,ids=>{selected=ids;});status.textContent='';
      }catch(error){if(section.isConnected)status.textContent=error.message;}
      finally{reading=false;if(section.isConnected){save.disabled=!snapshot;reload.disabled=false;}}
    };
    reload.onclick=read;more.addEventListener('toggle',()=>{if(more.open&&!snapshot)void read();});
    save.onclick=async event=>{
      event.stopPropagation();if(reading||saving||!snapshot)return;
      if(editing){status.textContent='请先保存或关闭当前编辑。';return;}
      saving=true;save.disabled=true;reload.disabled=true;choices.querySelectorAll('input').forEach(input=>{input.disabled=true;});status.textContent='正在保存分组…';
      try {
        const saved=await writeSharedItem(item.id,snapshot.revision,{favorite:snapshot.favorite,notes:snapshot.notes,nickname:snapshot.nickname,collection_ids:selected});
        if(!section.isConnected)return;
        snapshot=saved;selected=[...(saved.collection_ids||[])];
        await loadData(true,15000,true);renderPanelContent();window.dispatchEvent(new CustomEvent('anima-tools-shared-prompts-updated'));
      }catch(error){if(section.isConnected)status.textContent=error.message;}
      finally{saving=false;if(section.isConnected){save.disabled=false;reload.disabled=false;choices.querySelectorAll('input').forEach(input=>{input.disabled=false;});}}
    };
  }
  function simplifyResourceCard(card, item) {
    card.classList.add('tb-spm-simple-card');
    const actions = card.querySelector('.tb-spm-actions');
    const more = document.createElement('details'); more.className = 'tb-spm-more';
    const summary = document.createElement('summary'); summary.textContent = '更多'; more.append(summary);
    const menu = document.createElement('div'); more.append(menu);
    if (window.unifiedQueuePrompt) {
      const queue = document.createElement('button'); queue.className='tb-spm-small-btn'; queue.textContent='加入待用列表';
      queue.disabled = item._semantic?.manual_search_eligible !== true;
      queue.onclick = () => window.unifiedQueuePrompt({provider:'library',id:item.id,title:item.alias,text:item.prompt,usage:item._semantic?.usage,sections:item.plan_sections}); menu.append(queue);
    }
    for (const key of ['edit', 'plan', 'copy', 'delete']) {const action=card.querySelector(`[data-act="${key}"]`);if(action)menu.append(action);}
    const mode = card.querySelector('[data-act="insert-mode"]');
    const modeLabel = document.createElement('label'); modeLabel.textContent = '使用方式 '; modeLabel.append(mode); menu.prepend(modeLabel);
    const favorite = document.createElement('button'); favorite.className = 'tb-spm-small-btn';
    favorite.dataset.act = 'favorite'; favorite.textContent = item.favorite ? '★' : '☆';
    favorite.setAttribute('aria-label', item.favorite ? '取消收藏' : '收藏');
    favorite.setAttribute('aria-pressed', String(!!item.favorite));
    favorite.onclick = async event => {
      event.stopPropagation(); favorite.disabled = true;
      try {
        if (editing) throw new Error('请先保存或关闭当前编辑。');
        const latest = await fetchSharedItem(item.id, 15000);
        const data = await writeSharedItem(item.id, latest.revision, {favorite: !latest.favorite, notes: latest.notes, nickname: latest.nickname, collection_ids: latest.collection_ids});
        await loadData(true, 15000, true); renderPanelContent();
        window.dispatchEvent(new CustomEvent('anima-tools-shared-prompts-updated'));
      } catch (error) {
        card.querySelector('.tb-spm-card-feedback').textContent = `收藏更新失败：${error.message || String(error)}。可重试。`;
      } finally {
        favorite.disabled = false;
        const panel = document.getElementById(PANEL_ID);
        const current = [...panel?.querySelectorAll('.tb-spm-card') || []].find(row => row.dataset.promptId === String(item.id))?.querySelector('[data-act="favorite"]');
        (current || panel?.querySelector('.tb-spm-search'))?.focus();
      }
    };
    mountQuickCollections(menu, more, item);
    actions.append(favorite, more);
    actions.insertBefore(menu.querySelector('[data-act="copy"]'), favorite);
    const openDetails = async (event, selectBody = false) => {
      const returnFocus = event?.currentTarget || document.activeElement;
      const version = ++detailsOpenVersion;
      const {manageModal}=await import("/extensions/ComfyUI-Unified-Prompt-Workbench/modal_focus.js");
      if (version !== detailsOpenVersion || !card.isConnected || card.closest('[inert]')) return;
      closeResourceDetails?.();
      const overlay = document.createElement('section'); overlay.id = 'tb-shared-resource-details';
      overlay.setAttribute('role','dialog'); overlay.setAttribute('aria-label','资料详情'); overlay.setAttribute('aria-modal','true');
      const panel = document.createElement('div'); panel.className = 'tb-spm-details-sheet'; overlay.append(panel);
      const head = document.createElement('header'); panel.append(head);
      const title = document.createElement('h2'); title.textContent = item.alias || '资料详情'; head.append(title);
      const close = document.createElement('button'); close.textContent = '返回列表'; head.append(close);
      const closeDetails = () => {overlay.remove(); releaseModal(); if (closeResourceDetails === closeDetails) closeResourceDetails = null;};
      close.onclick = closeDetails;
      const imageSrc = item.image ? '/prompt_selector/preview/' + encodeURIComponent(item.image) : (/^https?:\/\//i.test(item.preview_url || '') ? item.preview_url : '');
      const content = document.createElement('div'); content.className = 'tb-spm-details-body';
      content.innerHTML = `
        <div class="tb-spm-catname">来源：${escapeHtml(item._categoryName || '未分类')}</div>
        <div>资料 ID：${escapeHtml(item.id || '暂无')}</div>
        ${imageSrc ? `<a class="tb-spm-small-btn" href="${escapeAttr(imageSrc)}" target="_blank" rel="noopener noreferrer">查看完整预览图 ↗</a>` : '<div>这条资料尚未绑定预览图，可在编辑中添加。</div>'}
        ${item.updated_at ? `<div>更新：${escapeHtml(item.updated_at)}</div>` : ''}
        ${item.description ? `<div>${isProvenanceDescription(item.description) ? '来源标注：' : ''}${escapeHtml(item.description)}</div>` : ''}
        ${item._semantic?.note ? `<div>分类备注：${escapeHtml(item._semantic.note)}${item._semantic.note_kind ? `（${escapeHtml(item._semantic.note_kind)}）` : ''}</div>` : ''}
        <pre tabindex="0" aria-label="完整提示词正文">${escapeHtml(item.prompt || '')}</pre>
        ${Array.isArray(item._merge_sources) && item._merge_sources.length ? `<details class="tb-spm-history"><summary>合并来源与历史版本（${item._merge_sources.length}）</summary><div></div></details>` : ''}
        ${item._import_quarantine ? `<div>导入位置：${escapeHtml(item._import_quarantine.source || '')}</div><button class="tb-spm-small-btn" data-act="export-original">导出原始记录</button>` : ''}`;
      panel.append(content);
      const body = content.querySelector('pre');
      const selectText = () => {body.focus({preventScroll:true});const range=document.createRange();range.selectNodeContents(body);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);};
      body.onkeydown = event => {if (!event.isComposing && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {event.preventDefault();event.stopPropagation();selectText();}};
      const history = content.querySelector('.tb-spm-history');
      if (history) history.ontoggle = () => {
        if (!history.open || history.querySelector('pre')) return;
        history.querySelector('div').innerHTML = item._merge_sources.map(row => `<div style="border-top:1px solid #555;padding:6px"><div>${escapeHtml(row.category?.name)} · ${escapeHtml(row.prompt?.alias)}</div><div>原 ID：${escapeHtml(row.prompt?.id)}；原收藏：${row.prompt?.favorite ? '是' : '否'}</div>${row.prompt?.image ? `<a href="/prompt_selector/preview/${encodeURIComponent(row.prompt.image)}" target="_blank" rel="noopener noreferrer">查看原预览：${escapeHtml(row.prompt.image)}</a>` : ''}<pre>${escapeHtml(row.prompt?.prompt || '')}</pre></div>`).join('');
      };
      const exportOriginal = content.querySelector('[data-act="export-original"]');
      if (exportOriginal) exportOriginal.onclick = () => {
        const url = URL.createObjectURL(new Blob([JSON.stringify(item._import_quarantine, null, 2)], {type:'application/json'}));
        const link = document.createElement('a');link.href=url;link.download=`prompt-original-${String(item.id || 'record').replace(/[^a-z0-9_-]/gi, '_')}.json`;link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
      const tools = document.createElement('footer'); panel.append(tools);
      const edit = document.createElement('button'); edit.textContent = '编辑共享资料'; tools.append(edit);
      edit.onclick = () => {closeDetails(); if(item.strings)openStringEditor(item);else openEditor('edit', item._categoryId, item.id);};
      const copy = document.createElement('button'); copy.textContent = '复制正文'; tools.append(copy);
      copy.onclick = async () => {try {await navigator.clipboard.writeText(String(item.prompt || '')); copy.textContent='已复制';} catch {copy.textContent='复制失败，已选中正文，请手动复制';selectText();}};
      const select = document.createElement('button');select.textContent='全选正文';select.onclick=selectText;tools.append(select);
      document.body.append(overlay);
      const releaseModal=manageModal(overlay,{initialFocus:selectBody ? body : close,onClose:closeDetails,returnFocus});
      closeResourceDetails = closeDetails;
      if (selectBody) selectText();
    };
    card.querySelector('[data-act="copy"]').onclick = async event => {
      event.stopPropagation();const copy=card.querySelector('[data-act="copy"]'),feedback=card.querySelector('.tb-spm-card-feedback');
      copy.disabled=true;
      try {await navigator.clipboard.writeText(String(item.prompt || ''));feedback.textContent='已复制完整正文。';}
      catch {feedback.textContent='复制未成功，已打开并选中完整正文，请手动复制。';await openDetails({currentTarget:copy},true);}
      finally {copy.disabled=false;}
    };
    const primary = card.querySelector('[data-act="insert"]');
    if (!insertionTarget) {primary.disabled = false; primary.textContent = '查看详情'; primary.onclick = openDetails;}
    else {const detailsButton = document.createElement('button'); detailsButton.className='tb-spm-small-btn'; detailsButton.textContent='查看详情'; detailsButton.onclick=openDetails; menu.prepend(detailsButton);}
    if(item.plan_sections&&window.unifiedQueuePrompt){primary.disabled=item._semantic?.manual_search_eligible!==true;primary.textContent='使用方案';primary.onclick=()=>window.unifiedQueuePrompt({provider:'library',id:item.id,title:item.alias,sections:item.plan_sections,open:true});}
    for(const selector of ['.tb-spm-alias','.tb-spm-prompt']){
      const trigger=card.querySelector(selector);trigger.tabIndex=0;trigger.setAttribute('role','button');trigger.onclick=openDetails;
      if (selector === '.tb-spm-prompt') trigger.setAttribute('aria-label', `查看完整正文：${item.alias || '未命名'}`);
      trigger.onkeydown=event=>{if(!event.isComposing&&(event.key==='Enter'||event.key===' ')){event.preventDefault();void openDetails(event);}};
    }
  }

  async function openPanel(options = {}) {
    if (editing) throw new Error("请先保存或关闭当前资料编辑窗口。");
    const openVersion = ++editorOpenVersion, opener = document.activeElement;
    const assertCurrentOpening = () => {
      if (openVersion !== editorOpenVersion || editing || !opener?.isConnected) throw new Error("此打开请求已失效，请从当前入口重新打开。");
    };
    if (options.collectionsOnly) {
      await loadData(true, 30000, false);
      assertCurrentOpening();
      openCollections(options);
      return true;
    }
    if (options.importOnly) {
      await loadData(true, 30000, false);
      assertCurrentOpening();
      openImport(options.onClose);
      return true;
    }
    if (options.editorOnly) {
      await loadData(true, 30000, false);
      assertCurrentOpening();
      if (options.createPrompt) {
        const draft = openEditor("create", options.categoryId || null, null, options.prefill || {});
        if (!draft) throw new Error("请先保存或关闭当前资料编辑窗口。");
        draft.onClose = options.onClose;
        return true;
      }
      const result = await fetchLibraryPrompt(options.promptId, 15000, false, true);
      assertCurrentOpening();
      if (result.revision) libraryRevision = result.revision;
      const draft = openEditor("edit", categoryIdentity(result.category), result.prompt.id,
        {...result.prompt, _categoryId:categoryIdentity(result.category), _categoryName:result.category.name});
      if (!draft) throw new Error("请先保存或关闭当前资料编辑窗口。");
      draft.onClose = options.onClose;
      return true;
    }
    insertionVersion++;
    hideFloatingUndo();
    insertionTargetChoices = Array.isArray(options.targetChoices) ? options.targetChoices.filter(item => typeof item?.onInsert === "function") : [];
    insertionTarget = insertionTargetChoices[0] || (typeof options.onInsert === "function"
      ? { onInsert: options.onInsert, label: options.targetLabel || "指定提示词", direction: options.targetDirection } : null);
    if (insertionTargetChoices.length) insertionTarget = insertionTargetChoices[0];
    if (insertionTarget?.onInsert) {
      const invalidateUndo = () => {
        insertionVersion++;
        hideFloatingUndo();
        reportInsertion("目标或正文已变化，无法撤销旧操作。");
        panel?.querySelector?.('[data-action="undo-insert"]')?.setAttribute("hidden", "");
      };
      insertionTargetChoices.forEach(choice => { if (choice.onInsert) choice.onInsert.onUndoInvalidated = invalidateUndo; });
      insertionTarget.onInsert.onUndoInvalidated = invalidateUndo;
    }
    injectStyle();
    let panel = document.getElementById(PANEL_ID);
    if (!panel) {
      selectedPromptCards.clear();
      mergeSelection.clear();
      mergeMode = false;
      viewMode = requestedView(options.view);
      activeUsage = "";
      activeContentType = options.view === "templates" ? "template" : "";
      activeSemanticClass = "";
      searchText = "";
      activeCategoryId = options.categoryId || null;
      resetCurrentItems();
      panel = document.createElement("div");
      panel.id = PANEL_ID;
      panel.innerHTML = `
        <div class="tb-spm-head">
          <div class="tb-spm-heading"><div class="tb-spm-title">资料库</div><small>搜索 · 筛选 · 复用</small></div>
          <input class="tb-spm-search" aria-label="搜索当前资料库与筛选范围" placeholder="在当前资料库筛选中搜索…">
          <button class="tb-spm-small-btn" data-action="clear-filter">清空筛选</button>
          <button class="tb-spm-small-btn" data-action="refresh">刷新列表</button>
          <button class="tb-spm-small-btn" data-action="close">关闭</button>
        </div>
        <div class="tb-spm-target" role="status"><span class="tb-spm-target-status"></span><span class="tb-spm-target-actions"></span></div>
        <div class="tb-spm-views" role="tablist" aria-label="资料视图">
          <button class="tb-spm-small-btn" role="tab" data-view="all">全部资料</button>
          <button class="tb-spm-small-btn" role="tab" data-view="favorites">收藏</button>
          <button class="tb-spm-small-btn" role="tab" data-view="recent">最近使用</button>
          <button class="tb-spm-small-btn" role="tab" data-view="plans">我的方案</button>
        </div>
        <div class="tb-spm-filters">
          <label>分组<select data-action="collection-filter" aria-label="分组筛选"><option value="">全部分组</option></select></label>
          <label class="tb-spm-legacy-filter">主题<select data-action="semantic-class" aria-label="主题筛选"><option value="">全部主题</option></select></label>
          <label class="tb-spm-legacy-filter" hidden>细分类<select data-action="subcategory" aria-label="细分类筛选"><option value="">全部细分类</option></select></label>
          <div class="tb-spm-subchips tb-spm-legacy-filter" data-action="subcategory-chips" role="group" aria-label="细分类筛选"></div>
          <label>来源<select data-action="source-category" aria-label="资源来源筛选"><option value="">全部来源</option></select></label>
          <label class="tb-spm-source-filter">筛选来源<input class="tb-spm-cat-filter" data-action="source-filter" aria-label="筛选来源分类" placeholder="关键词…"></label>
          <label>用途<select data-action="usage-filter" aria-label="用途筛选"><option value="">不限用途</option><option value="positive">正向</option><option value="negative">负向</option><option value="mixed">含正负向分段</option><option value="unknown">未确认</option></select></label>
          <label>形式<select data-action="form-filter" aria-label="形式筛选"><option value="">不限形式</option><option value="atomic_tag">单一概念</option><option value="fragment">片段</option><option value="template">组合段</option><option value="model_reference">模型引用</option></select></label>
        </div>
        <details class="tb-spm-pool-wrap">
          <summary title="点击名称筛选，箭头／右键展开细分">筛选池 · 已选 0 项</summary>
          <div class="tb-spm-pool" data-action="filter-pool"></div>
        </details>
        <div class="tb-spm-view-hint"></div>
        <details class="tb-spm-management"><summary>管理资料</summary>
        <button class="tb-spm-small-btn primary" data-action="add">新建资料</button>
        <button class="tb-spm-small-btn" data-action="import">导入资料</button>
        <button class="tb-spm-small-btn" data-action="collections">管理分组</button>
        <button class="tb-spm-small-btn" data-action="merge-mode" aria-pressed="false">整理重复资料</button>
        <button class="tb-spm-small-btn" data-action="review">待核查</button>
        <div class="tb-spm-bulk-metadata">
          <div class="tb-spm-bulk-preview" data-action="bulk-meta-count">已选 0 条（在列表里双击资料加入选择）</div>
          <button class="tb-spm-small-btn" data-action="bulk-favorite">批量收藏</button>
          <button class="tb-spm-small-btn" data-action="bulk-unfavorite">取消收藏</button>
          <button class="tb-spm-small-btn" data-action="bulk-group-add">加入分组…</button>
          <button class="tb-spm-small-btn" data-action="bulk-group-remove">移出分组…</button>
          <button class="tb-spm-small-btn" data-action="bulk-notes">设置备注…</button>
          <button class="tb-spm-small-btn" data-action="bulk-clear">清空选择</button>
          <div class="tb-spm-bulk-editor" data-action="bulk-meta-editor" hidden>
            <div data-action="bulk-meta-title"></div>
            <div data-action="bulk-meta-choices"></div>
            <input data-action="bulk-meta-notes" placeholder="批量备注（留空表示清除）" hidden>
            <button class="tb-spm-small-btn primary" data-action="bulk-meta-save">保存</button>
            <button class="tb-spm-small-btn" data-action="bulk-meta-cancel">取消</button>
          </div>
          <div class="tb-spm-save-status" data-action="bulk-meta-status" data-tone="muted"></div>
        </div>
        </details>
        <div class="tb-spm-merge-tools" hidden>
          <span>选中需要整理的资料，再核对正文、用途和来源。</span>
          <button class="tb-spm-small-btn primary" data-action="merge" disabled>查看合并对照（0）</button>
          <button class="tb-spm-small-btn" data-action="merge-results">合并结果（按编号）</button>
          <button class="tb-spm-small-btn" data-action="merge-exit">退出整理</button>
        </div>
        <div class="tb-spm-body">
          <div class="tb-spm-list"><div class="tb-spm-status">加载中...</div></div>
        </div>`;
      const advancedFilters = document.createElement('details'); advancedFilters.className = 'tb-spm-advanced-filters';
      const advancedTitle = document.createElement('summary'); advancedTitle.textContent = '更多筛选'; advancedFilters.append(advancedTitle);
      rememberFilterDisclosure(advancedFilters, 'advanced');
      rememberFilterDisclosure(panel.querySelector('.tb-spm-pool-wrap'), 'pool');
      const advancedFields = document.createElement('div'); advancedFilters.append(advancedFields);
      for (const key of ['source-category','source-filter','usage-filter','form-filter']) advancedFields.append(panel.querySelector(`[data-action="${key}"]`).closest('label'));
      panel.querySelector('.tb-spm-filters').append(advancedFilters);
      document.body.appendChild(panel);
      panel.querySelector('[data-action="merge"]').onclick = openMergeReview;
      panel.querySelector('[data-action="merge-results"]').onclick = () => openMergeResultsDialog('');
      panel.querySelector('[data-action="merge-mode"]').onclick = () => {
        mergeMode = !mergeMode;
        if (!mergeMode) mergeSelection.clear();
        updateMergeControls(panel);
      };
      panel.querySelector('[data-action="merge-exit"]').onclick = () => {
        mergeMode = false;
        mergeSelection.clear();
        updateMergeControls(panel);
      };
      const changeView = async (view) => {
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = null;
        viewMode = view;
        updateViewControls(panel);
        try { await loadItemPage(true, 15000); renderPanelContent({revealResults: true}); }
        catch (error) { showError(error); }
      };
      panel.querySelectorAll(".tb-spm-views [data-view]").forEach(button => {
        button.onclick = () => changeView(button.dataset.view);
      });
      // 主题、细分类、来源是三条互相独立的筛选轴，每个控件只动自己那一条：
      // 换主题会换掉细分类的词表，但不再顺带清掉来源，否则边栏与「更多筛选」
      // 会互相把对方的选中项吃掉（列表和侧边栏归属对不上）。
      panel.querySelector('[data-action="semantic-class"]').onchange = async (event) => {
        activeSemanticClass = event.target.value;
        activeSubcategory = "";
        try { await loadItemPage(true, 15000); renderPanelContent({revealResults: true}); }
        catch (error) { showError(error); }
      };
      panel.querySelector('[data-action="clear-filter"]').onclick = () => {
        activeSemanticClass = ""; activeSubcategory = ""; activeCategoryId = null; activeUsage = ""; activeContentType = ""; activeCollection = ""; searchText = "";
        poolFilters = []; poolMode = "any"; expandedPoolParents.clear();
        panel.querySelector(".tb-spm-search").value = "";
        return changeView(viewMode);
      };
      panel.querySelector('[data-action="review"]').onclick = () => changeView("review");
      // 同一条规则的反向：在「更多筛选 → 来源」里换来源不会清掉主题与细分类，
      // 侧边栏那个主题因此保持选中，列表按主题 + 细分类 + 来源共同筛选。
      panel.querySelector('[data-action="source-category"]').onchange = async event => {
        activeCategoryId = event.target.value || null;
        try { await loadItemPage(true, 15000); renderPanelContent({revealResults: true}); }
        catch (error) { showError(error); }
      };
      panel.querySelector('[data-action="source-filter"]').oninput = event => {
        sourceFilterText = event.target.value;
        updateViewControls(panel);
      };
      panel.querySelector('[data-action="source-filter"]').onkeydown = event => {
        if (event.key !== "Escape" || !event.target.value) return;
        event.stopPropagation();
        sourceFilterText = "";
        event.target.value = "";
        updateViewControls(panel);
      };
      for (const name of ["usage-filter", "form-filter"]) {
        panel.querySelector(`[data-action="${name}"]`).onchange = async event => {
          if (name === "usage-filter") activeUsage = event.target.value; else activeContentType = event.target.value;
          try { await loadItemPage(true, 15000); renderPanelContent({revealResults: true}); }
          catch (error) { showError(error); }
        };
      }
      panel.querySelector('[data-action="close"]').onclick = async () => {
        editorOpenVersion++;
        insertionVersion++;
        hideFloatingUndo();
        try {
          if (searchTimer) clearTimeout(searchTimer);
          disconnectPreviewObserver();
          for (const target of new Set([insertionTarget, ...insertionTargetChoices])) target?.onInsert?.dispose?.();
          resetCurrentItems();
          panel.__tbResizeCleanup?.();
          panel.remove();
          document.getElementById('tb-shared-merge-review')?.remove();
          document.getElementById('tb-shared-merge-results')?.remove();
          const restoreCaller = panel.__tbRestoreCaller;
          delete panel.__tbRestoreCaller;
          if (typeof restoreCaller === "function") restoreCaller();
        } catch (error) {
          alert("关闭前保存失败：" + (error?.message || String(error)));
        }
      };
      panel.querySelector('[data-action="collections"]').onclick = async () => {
        try { await openPanel({collectionsOnly:true, selectorKind:libraryData?.selector_class_kinds?.[activeSemanticClass]}); }
        catch (error) { showError(error); }
      };
      panel.querySelector('[data-action="import"]').onclick = async () => {
        try { await openPanel({importOnly:true}); } catch (error) { showError(error); }
      };
      panel.querySelector('[data-action="add"]').onclick = async () => {
        try {
          if (!libraryData) await loadData(false, 15000, false);
          openEditor("create", activeCategoryId, null);
        } catch (error) { showError(error); }
      };
      updateBulkMetadataCount(panel);
      panel.querySelector('[data-action="bulk-favorite"]').onclick = () => applyBulkMetadata(panel, { favorite: true }, "批量收藏").catch(() => {});
      panel.querySelector('[data-action="bulk-unfavorite"]').onclick = () => applyBulkMetadata(panel, { favorite: false }, "取消收藏").catch(() => {});
      const bulkEditorOpen = mode => openBulkMetadataEditor(panel, mode)
        .catch(error => setBulkMetadataStatus(panel, error?.message || String(error), "error"));
      panel.querySelector('[data-action="bulk-group-add"]').onclick = () => bulkEditorOpen("add");
      panel.querySelector('[data-action="bulk-group-remove"]').onclick = () => bulkEditorOpen("remove");
      panel.querySelector('[data-action="bulk-notes"]').onclick = () => bulkEditorOpen("notes");
      panel.querySelector('[data-action="bulk-clear"]').onclick = () => {
        selectedPromptCards.clear();
        panel.querySelectorAll(".tb-spm-card-selected").forEach(card => card.classList.remove("tb-spm-card-selected"));
        updateBulkMetadataCount(panel);
        setBulkMetadataStatus(panel, "已清空选择。");
      };
      panel.querySelector('[data-action="bulk-meta-cancel"]').onclick = () => {
        bulkMetadataNode(panel, "bulk-meta-editor").hidden = true;
        setBulkMetadataStatus(panel, "");
      };
      panel.querySelector('[data-action="bulk-meta-save"]').onclick = async () => {
        const editor = bulkMetadataNode(panel, "bulk-meta-editor");
        const button = bulkMetadataNode(panel, "bulk-meta-save");
        button.disabled = true;
        try {
          if (editor.dataset.mode === "notes") {
            await applyBulkMetadata(panel, { notes: bulkMetadataNode(panel, "bulk-meta-notes").value }, "设置备注");
          } else {
            const ids = [...panel.querySelectorAll('[data-action="bulk-meta-choices"] input:checked')].map(input => input.value);
            if (!ids.length) throw new Error("请选择至少一个收藏组。");
            const add = editor.dataset.mode === "add";
            await applyBulkMetadata(panel, add ? { collection_add: ids } : { collection_remove: ids },
                                    add ? "加入分组" : "移出分组");
          }
          editor.hidden = true;
        } catch (error) {
          setBulkMetadataStatus(panel, error?.message || String(error), "error");
        } finally {
          button.disabled = false;
        }
      };
      panel.querySelector('[data-action="refresh"]').onclick = async () => {
        const list = panel.querySelector('.tb-spm-list');
        const outer = panel.closest('.uw-main');
        const previousScroll = outer ? outer.scrollTop : list.scrollTop;
        list.setAttribute('aria-busy', 'true');
        try {
          await loadData(true);
          renderPanelContent();
          (outer || list).scrollTop = previousScroll;
        } catch (err) { showError(err); }
        finally { list.removeAttribute('aria-busy'); }
      };
      const searchInput = panel.querySelector(".tb-spm-search");
      const scheduleSearch = event => {
        if (searchTimer) clearTimeout(searchTimer);
        listController?.abort();
        const intent = ++listRequestToken;
        if (event?.isComposing || searchInput.dataset.composing === 'true') return;
        const previousQuery = searchText;
        searchText = searchInput.value || "";
        const list = panel.querySelector('.tb-spm-list');
        list.setAttribute('aria-busy', 'true');
        list.inert = true;
        searchTimer = setTimeout(async () => {
          searchTimer = null;
          if (intent !== listRequestToken || !panel.isConnected || panel.hidden) return;
          const request = loadItemPage(true, 15000), token = listRequestToken;
          try {
            await request;
            if (token === listRequestToken) renderPanelContent({revealResults: searchText !== previousQuery});
          } catch (error) {
            if (token === listRequestToken) showError(error);
          } finally {
            if (token === listRequestToken) { list.removeAttribute('aria-busy'); list.inert = false; }
          }
        }, SEARCH_DEBOUNCE_MS);
      };
      searchInput.oninput = scheduleSearch;
      searchInput.onkeydown = event => {
        if (event.key !== 'Escape' || event.isComposing || searchInput.dataset.composing === 'true' || !searchInput.value) return;
        event.preventDefault();
        event.stopPropagation();
        searchInput.value = '';
        scheduleSearch();
      };
      searchInput.addEventListener('compositionstart', () => {searchInput.dataset.composing = 'true'; scheduleSearch();});
      searchInput.addEventListener('compositionend', () => {delete searchInput.dataset.composing; scheduleSearch();});
    }
    panel.__tbRestoreCaller = typeof options.onClose === "function" ? options.onClose : null;
    const mount = options.mount || document.body;
    if (panel.parentElement !== mount) mount.appendChild(panel);
    panel.classList.toggle("tb-spm-embedded", !!options.mount);
    watchEmbeddedResize(panel);
    if (options.view || options.categoryId || options.promptId || options.semanticClass) {
      if (options.view) viewMode = requestedView(options.view);
      activeUsage = "";
      activeContentType = options.view === "templates" ? "template" : "";
      activeCategoryId = options.categoryId || null;
      if (options.clearPool === true) { poolFilters = []; expandedPoolParents.clear(); }
      // 外壳/侧边栏传进来的主题当作"再加一条主题条件"（池子累积），不顶掉已有条件；
      // 回传的同一个主题（我们自己 dispatch 出去的）不重复加。
      const incomingTheme = options.semanticClass || "";
      if (incomingTheme) {
        activeSemanticClass = incomingTheme;
        if (!poolHas("theme", incomingTheme)) poolFilters.push({ axis: "theme", value: incomingTheme });
      }
      activeCollection = options.collectionId || '';
      // 细分类同样由筛选池负责，不再从外壳回灌，避免把池子里的多选压成单选。
      activeSubcategory = "";
      // 外壳明确要求移除某条主题时才删除，其余一律保留，避免误取消。
      if (options.removePoolTheme) {
        poolFilters = poolFilters.filter(item => !(item.axis === "theme" && item.value === options.removePoolTheme));
      }
      syncActiveTheme();
      searchText = "";
      if (searchTimer) { clearTimeout(searchTimer); searchTimer = null; }
      panel.querySelector(".tb-spm-search").value = "";
      resetCurrentItems();
    }
    if (typeof options.query === 'string') {
      searchText = options.query;
      panel.querySelector('.tb-spm-search').value = searchText;
      resetCurrentItems();
    }
    // 资料库从别处带着"来源区域"打开时（例如「标签 tags 串」里跳过来的整区），
    // 先把来源下拉缩到该区域，用户就能顺着原分类往下点。
    activeArea = typeof options.areaFilter === 'string' ? options.areaFilter : "";
    if (typeof options.sourceFilter === 'string') {
      sourceFilterText = options.sourceFilter;
      panel.querySelector('[data-action="source-filter"]').value = sourceFilterText;
    }
    updateViewControls(panel);
    const targetStatus = panel.querySelector(".tb-spm-target");
    const statusText = targetStatus.querySelector(".tb-spm-target-status");
    if (statusText) statusText.textContent = insertionTarget ? `插入到：${insertionTarget.label}` : options.browseOnlyReason || "仅浏览资料；请从目标提示词旁打开资料库后插入";
    targetStatus.querySelector(".tb-spm-target-actions")?.replaceChildren();
    if (insertionTargetChoices.length > 1) {
      const picker = document.createElement("select");
      picker.className = "tb-spm-target-picker";
      picker.setAttribute("aria-label", "资料库插入目标");
      insertionTargetChoices.forEach((choice, index) => {
        const option = document.createElement("option"); option.value = String(index); option.textContent = choice.label; picker.appendChild(option);
      });
      picker.onchange = () => {
        insertionVersion++;
        hideFloatingUndo();
        panel.querySelector('[data-action="undo-insert"]')?.setAttribute("hidden", "");
        insertionTarget = insertionTargetChoices[Number(picker.value)] || insertionTargetChoices[0];
        if (insertionTarget?.onInsert) insertionTarget.onInsert.onUndoInvalidated = () => {
          insertionVersion++;
          hideFloatingUndo();
          reportInsertion("目标或正文已变化，无法撤销旧操作。");
          panel?.querySelector?.('[data-action="undo-insert"]')?.setAttribute("hidden", "");
        };
        if (statusText) statusText.textContent = `插入到：${insertionTarget.label}`;
        renderPanelContent();
      };
      targetStatus.querySelector(".tb-spm-target-actions")?.appendChild(picker);
    }
    if ([insertionTarget, ...insertionTargetChoices].some(target => typeof target?.onInsert?.readCurrentText === "function")) {
      const saveCurrent = document.createElement("button");
      saveCurrent.className = "tb-spm-small-btn";
      saveCurrent.dataset.action = "save-current";
      saveCurrent.textContent = "保存为方案";
      saveCurrent.title = "将当前提示词保存为可复用方案，保存前可编辑";
      saveCurrent.onclick = () => {
        try {
          if (!libraryData) throw new Error("资料库尚未加载，请稍后重试。");
          const target = insertionTarget;
          if (typeof target?.onInsert?.readCurrentText !== "function") throw new Error("请从目标提示词旁重新打开资料库。");
          const text = target.onInsert.readCurrentText();
          if (!text.trim()) throw new Error("当前提示词为空，请先填写正文。");
          openEditor("create", activeCategoryId, null, {
            prompt: text, template: true, is_user_plan: true,
            _semantic: { primary_class: activeSemanticClass || "task_template", content_type: "template", usage: target.direction || "unknown" },
            sourceLabel: target.label
          });
        } catch (error) { if (statusText) statusText.textContent = error.message || String(error); }
      };
      targetStatus.querySelector(".tb-spm-target-actions")?.appendChild(saveCurrent);
    }
    if (typeof insertionTarget?.onInsert?.undoLast === "function" && !panel.querySelector('[data-action="undo-insert"]')) {
      const undoButton = document.createElement("button");
      undoButton.className = "tb-spm-small-btn";
      undoButton.dataset.action = "undo-insert";
      undoButton.textContent = "撤销本次插入";
      undoButton.hidden = true;
      undoButton.onclick = () => {
        const currentTarget = insertionTarget;
        insertionVersion++;
        if (currentTarget?.onInsert?.undoLast?.()) {
          hideFloatingUndo();
          reportInsertion(`已撤销：${currentTarget.label}`);
          undoButton.hidden = true;
          restoreInsertionFocus();
        } else {
          hideFloatingUndo();
          undoButton.hidden = true;
          reportInsertion("撤销不可用：目标或正文已变化");
          restoreInsertionFocus();
        }
      };
      targetStatus.querySelector(".tb-spm-target-actions")?.appendChild(undoButton);
    }
    try {
      if (options.promptId) {
        const token = listRequestToken;
        await loadData(true, 30000, false);
        const result = await fetchLibraryPrompt(options.promptId, 15000, false, true);
        if (token !== listRequestToken || !panel.isConnected) return false;
        const item = {...result.prompt, _categoryId: categoryIdentity(result.category), _categoryName: result.category.name};
        activeCategoryId = item._categoryId;
        viewMode = item._semantic?.manual_search_eligible ? "all" : "review";
        currentItems = [item];
        currentItemsTotal = 1;
        currentFilterCounts = null;
        if (!editing && result.revision) libraryRevision = result.revision;
        if (statusText) statusText.textContent = "已按原收藏 ID 定位当前资料；原收藏记录保留。";
      } else await loadData(false);
      renderPanelContent();
      if (options.editPrompt && options.promptId && currentItems[0]) openEditor('edit', currentItems[0]._categoryId, currentItems[0].id);
      return true;
    } catch (err) {
      showError(err); return false;
    }
  }
  window.tbOpenSharedPresetManager = openPanel;
  function updateViewControls(panel) {
    const sourcePicker = panel.querySelector('[data-action="source-category"]');
    const sourceFilter = panel.querySelector('[data-action="source-filter"]');
    const categories = libraryData?.categories || [];
    const builtin = categories.filter(category => String(category.id).startsWith("anima-builtin-"));
    const other = categories.filter(category => !String(category.id).startsWith("anima-builtin-"));
    // The codex tree has ~450 leaves; each top-level area becomes an optgroup and the
    // filter box trims the list, while the currently selected leaf stays listed so the
    // picker never disagrees with the active filter.
    const needle = sourceFilterText.trim().toLowerCase();
    // 只在"来源列表/关键词真的变了"时重建选项：这个下拉有 ~450 个叶子，
    // 原来每次重渲染都 replaceChildren()，用户正在下拉里拖动滚动条时会被清掉、
    // 松手就弹回原来的位置。
    const pickerSignature = needle + '|' + categories.map(category =>
      categoryIdentity(category) + ':' + (category.prompt_count || 0)).join('\u00a6');
    if (sourcePicker.dataset.buildSignature !== pickerSignature) {
    sourcePicker.dataset.buildSignature = pickerSignature;
    sourcePicker.replaceChildren();
    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = "全部来源（含原选择器）";
    sourcePicker.appendChild(allOption);
    const addOptions = (label, rows) => {
      const visible = rows.filter(category => !needle
        || String(category.name || "").toLowerCase().includes(needle)
        || categoryIdentity(category) === activeCategoryId);
      if (!visible.length) return;
      const group = document.createElement("optgroup");
      group.label = label;
      for (const category of visible) {
        const option = document.createElement("option");
        option.value = categoryIdentity(category);
        option.textContent = `${category.name} (${Number(category.prompt_count || 0)})`;
        group.appendChild(option);
      }
      sourcePicker.appendChild(group);
    };
    addOptions("原选择器内置资源", builtin);
    const buckets = new Map();
    for (const category of other) {
      const area = categoryArea(category.name);
      if (!buckets.has(area)) buckets.set(area, []);
      buckets.get(area).push(category);
    }
    for (const [area, rows] of buckets) addOptions(area, rows);
    }
    if (sourceFilter) {
      if (sourceFilter.value !== sourceFilterText) sourceFilter.value = sourceFilterText;
      sourceFilter.title = needle
        ? `匹配 ${Math.max(0, sourcePicker.options.length - 1)} / ${categories.length} 个来源`
        : "按关键词筛选来源分类";
    }
    sourcePicker.value = activeCategoryId || "";
    panel.dataset.view = viewMode;
    panel.querySelectorAll(".tb-spm-views [data-view]").forEach(button => {
      button.setAttribute("aria-selected", String(button.dataset.view === viewMode));
    });
    const hint = panel.querySelector(".tb-spm-view-hint");
    const classPicker = panel.querySelector('[data-action="semantic-class"]');
    const collectionPicker = panel.querySelector('[data-action="collection-filter"]');
    if (collectionPicker) {
      const groups = libraryData?.selector_groups?.resource || libraryData?.selector_groups?.pose || [];
      if (libraryData && activeCollection && !groups.some(group => group.id === activeCollection)) activeCollection = '';
      collectionPicker.innerHTML = '<option value="">全部分组</option>' + groups.map(group => `<option value="${escapeAttr(group.id)}">${escapeHtml(group.id==='default'?'默认分组':group.name)}</option>`).join('');
      collectionPicker.value = activeCollection;
      collectionPicker.onchange = async () => {
        activeCollection = collectionPicker.value;
        try { await loadItemPage(true, 15000); renderPanelContent(); } catch(error) { showError(error); }
      };
    }
    const subPicker = panel.querySelector('[data-action="subcategory"]');
    if (subPicker) {
      const values = activeSemanticClass==='style_quality'?[...new Set([...(libraryData?.semantic_subcategories?.style_medium||[]),...(libraryData?.semantic_subcategories?.quality_detail||[])])]:activeSemanticClass ? libraryData?.semantic_subcategories?.[activeSemanticClass] || [] : [];
      subPicker.innerHTML = '<option value="">全部细分类</option>' + values.map(label => `<option value="${escapeAttr(label)}">${escapeHtml(label)}</option>`).join('');
      subPicker.value = activeSubcategory;
      subPicker.disabled = !activeSemanticClass;
      subPicker.onchange = async () => {
        activeSubcategory = subPicker.value;
        try { await loadItemPage(true, 15000); renderPanelContent(); } catch(error) { showError(error); }
      };
      // 细分类不再用下拉，直接把选项铺成一行（点一下即筛选）
      const subChips = panel.querySelector('[data-action="subcategory-chips"]');
      if (subChips) {
        const keepScrollLeft = subChips.scrollLeft;
        subChips.replaceChildren();
        subChips.scrollLeft = keepScrollLeft;
        subChips.hidden = !activeSemanticClass;
        if (activeSemanticClass) {
          const addChip = (label, value) => {
            const chip = document.createElement('button');
            chip.className = 'tb-spm-small-btn' + ((activeSubcategory || '') === value ? ' primary' : '');
            chip.textContent = label;
            chip.setAttribute('aria-pressed', (activeSubcategory || '') === value ? 'true' : 'false');
            chip.onclick = () => { subPicker.value = value; subPicker.dispatchEvent(new Event('change', {bubbles:true})); };
            subChips.append(chip);
          };
          addChip('全部细分类', '');
          values.forEach(label => addChip(label, label));
        }
      }
    }
    renderFilterPool(panel);
    if (classPicker) {
      classPicker.innerHTML = '<option value="">全部主题</option>' + Object.entries(libraryData?.semantic_classes || {})
        .map(([id, label]) => `<option value="${escapeAttr(id)}">${escapeHtml(label)}</option>`).join("");
      classPicker.value = activeSemanticClass;
      classPicker.hidden = false;
    }
    for (const [name, value] of [["usage-filter", activeUsage], ["form-filter", activeContentType]]) {
      const picker = panel.querySelector(`[data-action="${name}"]`);
      if (picker) picker.value = value;
    }
    const add = panel.querySelector('[data-action="add"]');
    if (add) add.textContent = viewMode === "plans" ? "新建方案" : "新建资料";
    if (hint) {
      const labels = {all:"同一份资料，可按主题、用途和形式筛选",favorites:"只显示已收藏的资料",recent:"按最近使用时间排序",plans:"只显示你明确保存的方案；组合段不会自动成为方案",review:"待核查资料，编辑确认后可使用"};
      const shownTotal = displayedItemsTotal();
      hint.textContent = `${labels[viewMode]} · ${shownTotal} 条${activeArea ? ` · 区域：${activeArea}` : ""}${activeCategoryId ? ` · 分类筛选：${getCatById(activeCategoryId)?.name || activeCategoryId}` : ""}`;
    }
    const review = panel.querySelector('[data-action="review"]');
    if (review) review.textContent = `待核查（${(libraryData?.review_counts?.pending || 0) + (libraryData?.review_counts?.quarantined || 0)}）`;
    let chips=panel.querySelector('.tb-spm-filter-chips');if(!chips){chips=document.createElement('div');chips.className='tb-spm-filter-chips';hint?.before(chips);}chips.replaceChildren();
    for(const selector of ['collection-filter','source-category','usage-filter','form-filter']){
      const control=panel.querySelector(`[data-action="${selector}"]`);if(!control?.value)continue;
      const chip=document.createElement('button');chip.className='tb-spm-small-btn';chip.textContent=(control.selectedOptions[0]?.textContent||control.value)+' ×';chip.setAttribute('aria-label','清除筛选：'+(control.selectedOptions[0]?.textContent||control.value));chip.onclick=()=>{control.value='';control.dispatchEvent(new Event('change',{bubbles:true}));};chips.append(chip);
    }
    panel.dispatchEvent(new CustomEvent('shared-library-view',{bubbles:true,detail:{collection:activeCollection,theme:activeSemanticClass,selectedThemes:poolFilters.filter(item=>item.axis==='theme').map(item=>item.value),source:activeCategoryId||'',subcategory:'',query:searchText,view:viewMode,themes:[...(classPicker?.options||[])].filter(option=>option.value).map(option=>[option.value,option.textContent])}}));
  }

  function bindLibraryModal(root,onClose,initialFocus,returnFocus=document.activeElement){
    void import('/extensions/ComfyUI-Unified-Prompt-Workbench/modal_focus.js').then(({manageModal})=>{
      if(root.isConnected)manageModal(root,{onClose,initialFocus,returnFocus});
    });
  }
  function openCollections(options) {
    injectStyle();
    const labels = {pose:'姿势',clothing:'服装',background:'背景',character:'角色',artist:'画师',style_quality:'风格质量',tag:'Tag',model:'模型',image:'图库',resource:'资料'};
    const kinds = Object.keys(libraryData.selector_groups || {}).filter(kind => labels[kind]);
    if (!kinds.length) throw new Error('共享分组尚未就绪，请检查服务后重试。');
    const draft = {mode:'collections', baseRevision:libraryRevision, saving:false, onClose:options.onClose, returnFocus:document.activeElement};
    editing = draft;
    let kind = kinds.includes(options.selectorKind) ? options.selectorKind : kinds[0];
    let selectedId = options.collectionId || '', createId = uuid();
    const overlay = document.createElement('div'); overlay.id = EDITOR_ID;
    overlay.innerHTML = `<div class="tb-spm-editor-box">
      <div class="tb-spm-editor-head"><span>管理共享分组</span><button class="tb-spm-small-btn" data-ed="close">关闭</button></div>
      <div class="tb-spm-editor-form">
        <div style="display:none"><select data-ed="collection-kind">${kinds.map(key=>`<option value="${key}" ${key===kind?'selected':''}>${labels[key]}</option>`).join('')}</select></div>
        <p>分组供资料库、所有选择器、Tag、模型和图库共用。删除组保留资料与收藏；没有其他组的成员回到默认分组。</p>
        <div data-ed="collection-list" style="display:flex;flex-wrap:wrap;gap:6px"></div>
        <button class="tb-spm-small-btn" data-ed="new-collection">新建分组</button>
        <div class="tb-spm-field"><label>分组名称<input data-ed="collection-name" autocomplete="off"></label></div>
        <div data-ed="error" role="status" style="white-space:pre-wrap"></div>
      </div>
      <div class="tb-spm-editor-actions">
        <button class="tb-spm-small-btn" data-ed="cancel">完成并返回</button>
        <button class="tb-spm-small-btn" data-ed="reload" hidden>重新核对库版本</button>
        <button class="tb-spm-small-btn danger" data-ed="delete-collection" disabled>删除所选分组</button>
        <button class="tb-spm-small-btn primary" data-ed="save">创建分组</button>
      </div></div>`;
    document.body.appendChild(overlay);
    const picker=overlay.querySelector('[data-ed="collection-kind"]'), list=overlay.querySelector('[data-ed="collection-list"]');
    const name=overlay.querySelector('[data-ed="collection-name"]'), status=overlay.querySelector('[data-ed="error"]');
    const save=overlay.querySelector('[data-ed="save"]'), remove=overlay.querySelector('[data-ed="delete-collection"]'), reload=overlay.querySelector('[data-ed="reload"]');
    const selected = () => (libraryData.selector_groups[kind] || []).find(group=>group.id===selectedId);
    const render = (preserveName=false) => {
      const group=selected(), protectedGroup=group && (group.id==='default' || group.isSystem);
      list.replaceChildren();
      for (const item of libraryData.selector_groups[kind] || []) {
        const button=document.createElement('button');button.type='button';button.className='tb-spm-small-btn';
        button.textContent=item.name;button.dataset.collectionId=item.id;button.setAttribute('aria-pressed',String(item.id===selectedId));
        button.onclick=()=>{if(draft.saving)return;selectedId=item.id;status.textContent='';render();};
        list.appendChild(button);
      }
      if (!preserveName) name.value=group?.name || '';
      name.disabled=!!protectedGroup || draft.saving;
      save.textContent=selectedId?'保存名称':'创建分组';
      save.disabled=draft.saving || !!protectedGroup || !reload.hidden || (selectedId && !group);
      remove.disabled=draft.saving || !group || !!protectedGroup || !reload.hidden;
      if(protectedGroup)status.textContent='默认或系统分组保留，不能改名或删除。';
      else if(selectedId&&!group)status.textContent='该分组已不存在；当前输入已保留，可以点击“新建分组”重新创建。';
    };
    const close=async()=>{if(draft.saving)return;editing=null;overlay.remove();
      if (!(await returnToEditorCaller(draft)) && document.getElementById(PANEL_ID)) {
        try { await loadData(true,15000,true); renderPanelContent(); restoreEditorFocus(draft); }
        catch(error) { showError(error); }
      }
    };
    overlay.querySelector('[data-ed="close"]').onclick=close;
    overlay.querySelector('[data-ed="cancel"]').onclick=close;
    bindLibraryModal(overlay,close,name);
    overlay.onclick=event=>{if(event.target===overlay)close();};
    picker.onchange=()=>{kind=picker.value;selectedId='';createId=uuid();status.textContent='';render();};
    overlay.querySelector('[data-ed="new-collection"]').onclick=()=>{if(draft.saving)return;selectedId='';createId=uuid();status.textContent='';render();name.focus();};
    const commit=async operation=>{
      if(draft.saving)return;
      if(operation!=='delete'&&!name.value.trim()){status.textContent='请填写分组名称。';name.focus();return;}
      const groupId=selectedId||createId, submittedName=name.value.trim();
      draft.saving=true;picker.disabled=true;render(true);status.textContent='正在保存…';
      try {
        const response=await fetchLibraryWrite('/prompt_selector/collections/update',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({operation,kind,group_id:groupId,name:submittedName})});
        const result=await response.json();
        if(!response.ok||result.error)throw new Error(result.error||`HTTP ${response.status}`);
        draft.baseRevision=result.revision||libraryRevision;
        for(const type of Object.keys(libraryData.selector_groups))libraryData.selector_groups[type]=result.groups;
        if(operation==='delete'){selectedId='';createId=uuid();name.value='';}
        else selectedId=groupId;
        reload.hidden=true;
        status.textContent=operation==='delete'?'分组已删除，资料和收藏已保留。':'已保存到共享资料库。';
        window.dispatchEvent(new Event('anima-tools-shared-prompts-updated'));
      } catch(error) {
        status.textContent=error.isRevisionConflict?'资料库已在其他窗口更新。本次未保存，名称已保留；请重新核对版本。':error.message;
        reload.hidden=!error.isRevisionConflict;
      } finally {draft.saving=false;picker.disabled=false;render(true);}
    };
    save.onclick=()=>commit(selectedId?'rename':'create');
    remove.onclick=()=>commit('delete');
    reload.onclick=async()=>{
      if(draft.saving)return;
      reload.disabled=true;
      try{
        await loadData(true,30000,false);
        if(!libraryData.last_modified)throw new Error('未取得最新库版本，请重试。');
        draft.baseRevision=libraryRevision=libraryData.last_modified;
        reload.hidden=true;status.textContent='已读取最新版本；输入已保留，请核对后再保存。';render(true);
      }
      catch(error){status.textContent=error.message;}finally{reload.disabled=false;}
    };
    render();
    if(options.collectionAction==='delete'&&!remove.disabled)remove.focus();else if(!name.disabled)name.focus();
  }

  function openImport(onClose) {
    injectStyle();
    editing = {mode:'import', baseRevision:libraryRevision, saving:false, onClose};
    const draft = editing, overlay = document.createElement('div'); overlay.id = EDITOR_ID;
    overlay.innerHTML = `<div class="tb-spm-editor-box">
      <div class="tb-spm-editor-head"><span>导入共享资料</span><button class="tb-spm-small-btn" data-ed="close">关闭</button></div>
      <div class="tb-spm-editor-form">
        <p>选择 ZIP 和要导入的分类后核对预览。完全重复的记录跳过；内容变化保留为新版本，不覆盖原资料；异常字段进入待复核。</p>
        <label>资料包<input type="file" accept=".zip,application/zip" data-ed="file"></label>
        <div data-ed="categories"></div><div data-ed="preview" aria-live="polite"></div>
        <label><input type="checkbox" data-ed="confirm" disabled>已核对以上处理方式，按此预览导入</label>
        <div data-ed="error" role="status" style="white-space:pre-wrap"></div>
      </div>
      <div class="tb-spm-editor-actions"><button class="tb-spm-small-btn" data-ed="cancel">取消</button>
        <button class="tb-spm-small-btn" data-ed="export" hidden>导出预览清单</button>
        <button class="tb-spm-small-btn" data-ed="reload" hidden>重新预览</button>
        <button class="tb-spm-small-btn primary" data-ed="save" disabled>导入选中目录</button></div></div>`;
    document.body.appendChild(overlay);
    const get = key => overlay.querySelector(`[data-ed="${key}"]`);
    const fileInput=get('file'), save=get('save'), status=get('error'), categories=get('categories');
    const reload=get('reload'), preview=get('preview'), confirm=get('confirm'), exportButton=get('export');
    let file=null, previewToken=0, plan=null, operation=null, completed=false;
    const selectedNames=()=>Array.from(categories.querySelectorAll('input:checked'), el=>el.value);
    const sync=()=>{save.disabled=draft.saving || !plan || !confirm.checked || !selectedNames().length;};
    const cancel=async()=>{
      if(draft.saving){status.textContent='正在提交原子导入，请等待结果；此时关闭不能撤回服务器提交。';return;}
      previewToken++; editing=null; overlay.remove();
      if(!(await returnToEditorCaller(draft)) && completed){await loadData(true,30000,true);renderPanelContent();}
    };
    get('cancel').onclick=cancel;get('close').onclick=cancel;
    overlay.onclick=event=>{if(event.target===overlay)cancel();};confirm.onchange=sync;
    exportButton.onclick=()=>{
      const record=operation||plan;if(!record)return;
      const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'}));
      const link=document.createElement('a');link.href=url;link.download=operation?'import-operation.json':'import-preflight.json';link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    const readPreview=async(resetCategories=false)=>{
      const token=++previewToken, sourceFile=file, selection=selectedNames();
      plan=null;operation=null;confirm.checked=false;confirm.disabled=true;exportButton.hidden=true;exportButton.textContent='导出预览清单';reload.hidden=true;sync();
      preview.textContent='';status.textContent='正在核对资料包与当前资料库…';
      if(!sourceFile){status.textContent='请选择资料包。';return;}
      try{
        const form=new FormData();form.append('zip_file',sourceFile);
        if(!resetCategories)form.append('selected_categories',JSON.stringify(selection));
        const response=await fetchWithTimeout('/prompt_selector/pre_import',{method:'POST',body:form},30000);
        const result=await response.json();
        if(token!==previewToken || !overlay.isConnected)return;
        if(!response.ok||result.error)throw new Error(result.error||`HTTP ${response.status}`);
        if(!result.preflight_token||!result.counts||!result.base_revision)throw new Error('服务尚未提供完整导入预览，请更新服务后重试。');
        if(resetCategories){
          categories.replaceChildren();
          for(const name of [...new Set(result.categories||[])]){
            const label=document.createElement('label'), input=document.createElement('input');
            input.type='checkbox';input.value=String(name);input.checked=true;
            input.onchange=()=>{if(!draft.saving)readPreview();};
            label.append(input,document.createTextNode(String(name)));categories.appendChild(label);
          }
        }
        plan=result;draft.baseRevision=result.base_revision;
        const c=result.counts;
        preview.textContent=`新增 ${c.new}；更新（保留变体）${c.updated}；疑似重复（跳过）${c.suspected_duplicate}；不支持字段/待复核 ${c.unsupported}；版本冲突 ${c.version_conflicts}。共 ${c.total_records} 条，将写入 ${c.will_write} 条、跳过 ${c.will_skip} 条。待复核计数可与新增或更新重叠。`;
        status.textContent='预览完成，尚未写入。更改导入分类后会重新核对。';
        confirm.disabled=false;exportButton.hidden=false;sync();
      }catch(error){if(token===previewToken&&overlay.isConnected){status.textContent='预览失败：'+error.message;reload.hidden=false;}}
    };
    fileInput.onchange=()=>{if(draft.saving)return;file=fileInput.files?.[0]||null;categories.replaceChildren();readPreview(true);};
    reload.onclick=()=>{if(!draft.saving)readPreview(!categories.children.length);};
    save.onclick=async()=>{
      if(draft.saving||!file||!plan||!confirm.checked||!selectedNames().length)return;
      const submittedPlan=plan;
      draft.saving=true;sync();fileInput.disabled=true;confirm.disabled=true;reload.disabled=true;
      categories.querySelectorAll('input').forEach(input=>{input.disabled=true;});
      status.textContent=`正在提交 ${submittedPlan.counts.will_write} 条；整个导入成功后一次生效…`;
      try{
        const form=new FormData();form.append('zip_file',file);form.append('selected_categories',JSON.stringify(selectedNames()));
        form.append('preflight_token',submittedPlan.preflight_token);form.append('confirmed','true');
        const response=await fetchWithTimeout('/prompt_selector/import',{method:'POST',body:form,headers:{'If-Match':submittedPlan.base_revision}},120000);
        const result=await response.json();
        if(!response.ok||result.error){
          operation=result.operation||null;
          const error=new Error(result.error||`HTTP ${response.status}`);error.isRevisionConflict=response.status===409;
          error.knownNotCommitted=result.committed===0||result.conflict===true||result.plan_mismatch===true;throw error;
        }
        libraryRevision=responseRevision(response)||result.revision||libraryRevision;
        operation=result.operation||null;completed=true;plan=null;confirm.checked=false;
        status.textContent=operation?`导入完成：已提交 ${operation.committed} 条，未提交 ${operation.uncommitted} 条，跳过 ${operation.skipped} 条。可导出本次结果清单，再完成并返回。`:'导入完成。';
        get('cancel').textContent='完成并返回';exportButton.hidden=!operation;exportButton.textContent='导出结果清单';
      }catch(error){
        // Transport failure is not proof that the server did not commit.
        status.textContent=error.knownNotCommitted?`本次未提交；${operation?.uncommitted==null?'':`未提交 ${operation.uncommitted} 条。`}资料包和所选目录已保留，请导出失败清单或重新预览后重试。`:'尚未确认导入结果：'+error.message+'。请重新预览当前资料库后核对，避免重复提交。';
        plan=null;confirm.checked=false;exportButton.hidden=!operation;exportButton.textContent='导出失败清单';reload.hidden=false;
      }finally{
        draft.saving=false;fileInput.disabled=false;reload.disabled=false;confirm.disabled=!plan;
        categories.querySelectorAll('input').forEach(input=>{input.disabled=false;});sync();
      }
    };
  }

  function openEditor(mode, categoryId, promptId, prefill = null) {
    injectStyle();
    if (editing) return;
    editorOpenVersion++;
    const frozenPrompt = mode === "edit"
      ? prefill || currentItems.find(item => item.id === promptId)
      : null;
    editing = { mode, categoryId, promptId, draftId: uuid(), baseRevision: libraryRevision,
      originalCategoryId: categoryId, returnFocus: document.activeElement,
      promptSnapshot: frozenPrompt ? structuredClone(frozenPrompt) : null, saving: false };
    const old = document.getElementById(EDITOR_ID);
    if (old) old.remove();
    const cat = getCatById(categoryId) || (libraryData?.categories || [])[0] || null;
    const prompt = mode === "edit" ? editing.promptSnapshot : prefill;
    editing.collectionDrafts = structuredClone(prompt?._selector_favorites || {});
    editing.sharedCollectionDraft = structuredClone(prompt?._collection || null);
    const semantic = prompt?._semantic || prompt?._classification || {primary_class: activeSemanticClass || (viewMode === "plans" ? "task_template" : ""), usage: insertionTarget?.direction || "unknown"};
    const isPlan = prompt ? prompt.is_user_plan === true : viewMode === "plans";
    const overlay = document.createElement("div");
    overlay.id = EDITOR_ID;
    overlay.innerHTML = `
      <div class="tb-spm-editor-box">
        <div class="tb-spm-editor-head"><span id="tb-spm-editor-title">${mode === "edit" ? "编辑资料" : "新建资料"}</span><button class="tb-spm-small-btn" data-ed="close">关闭</button></div>
        <div class="tb-spm-editor-form">
          ${mode === "create" && prefill?.sourceLabel ? `<div class="tb-spm-draft-source">来自：${escapeHtml(prefill.sourceLabel)}；确认后另存为新资料</div>` : ""}
          <div class="tb-spm-field"><label for="tb-spm-editor-alias">名称</label><input id="tb-spm-editor-alias" data-field="alias" value="${escapeAttr(prompt?.alias || "")}" placeholder="便于查找的资料名称"></div>
          <div class="tb-spm-field"><label for="tb-spm-editor-prompt">正文</label><textarea id="tb-spm-editor-prompt" data-field="prompt" placeholder="实际插入的提示词正文">${escapeHtml(prompt?.prompt || "")}</textarea></div>
          <label><input type="checkbox" data-field="split_plan" ${prompt?.plan_sections?'checked':''}> 按正负向分别保存方案</label>
          <div data-ed="plan-sections" hidden>
            <div class="tb-spm-field"><label>方案正向</label><textarea data-field="plan_positive">${escapeHtml(prompt?.plan_sections?.positive || '')}</textarea></div>
            <div class="tb-spm-field"><label>方案负向</label><textarea data-field="plan_negative">${escapeHtml(prompt?.plan_sections?.negative || '')}</textarea></div>
            <p>允许留空一个方向。使用时分别选择目标，不把两个方向拼进同一个字段。</p>
          </div>
          <input type="hidden" data-field="template" value="${prompt?.template || (!prompt && viewMode === "plans") ? "true" : "false"}">
          <div class="tb-spm-grid2">
            <div class="tb-spm-field"><label>主题（随保存确认）</label><select data-field="primary_class" aria-label="资料主题"><option value="">主题未确认</option>${Object.entries(libraryData?.semantic_classes || {}).map(([id, label]) => `<option value="${escapeAttr(id)}" ${semantic.primary_class === id ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select></div>
            <div class="tb-spm-field"><label>细分类（逗号分隔，层级用 /）</label><input data-field="subcategories" aria-label="资料细分类" value="${escapeAttr((semantic.subcategories || []).join(', '))}" placeholder="例如：坐姿、持物与道具互动"></div>
            <div class="tb-spm-field"><label><input type="checkbox" data-field="random_pool_eligible" ${semantic.random_pool_eligible && semantic.strict_model_pool_eligible ? 'checked' : ''}> 允许 Anima 随机选用</label></div>
            <div class="tb-spm-field"><label>内容形式</label><select data-field="content_type" aria-label="内容形式">${[["atomic_tag","单一概念"],["fragment","片段"],["template","组合段"],["model_reference","模型引用"]].map(([id,label])=>`<option value="${id}" ${(semantic.content_type || (prompt?.template || (!prompt && viewMode === "plans") ? "template" : "fragment")) === id ? "selected" : ""}>${label}</option>`).join("")}</select></div>
          </div>
          <div class="tb-spm-field"><label>用途</label><select data-field="usage" aria-label="正负向用途">${[["positive","正向"],["negative","负向"],["mixed","含正负向分段"],["unknown","未确认"]].map(([id,label])=>`<option value="${id}" ${(semantic.declared_usage || semantic.usage || "unknown") === id ? "selected" : ""}>${label}</option>`).join("")}</select></div>
          <div class="tb-spm-field" data-ed="collections"></div>
          <label class="tb-spm-plan-choice"><input type="checkbox" data-field="is_user_plan" ${isPlan ? "checked" : ""}>保存到“我的方案”</label>
          <p class="tb-spm-plan-help">方案由你明确保存，用于整体复用；取消标记只会移出方案视图，资料仍保留。</p>
          <details class="tb-spm-editor-source"><summary>高级信息</summary>
          <div class="tb-spm-field"><label>描述</label><textarea data-field="description" style="min-height:60px">${escapeHtml(prompt?.description || "")}</textarea></div>
          <div class="tb-spm-grid2">
            <div class="tb-spm-field"><label>Tags（逗号分隔，仅用于搜索/分类）</label><input data-field="tags" value="${escapeAttr((prompt?.tags || []).join(", "))}"></div>
            <div class="tb-spm-field"><label>预览图链接</label><input data-field="preview_url" value="${escapeAttr(prompt?.preview_url || '')}" placeholder="https://..."></div>
            <div class="tb-spm-field"><label>预览图文件名（可保留旧图）</label><input data-field="image" value="${escapeAttr(prompt?.image || "")}"></div>
          </div>
          <div class="tb-spm-grid2">
            <div class="tb-spm-field"><label>上传/替换预览图</label><input data-field="image_file" type="file" accept="image/*"></div>
            <div class="tb-spm-field"><label>收藏</label><select data-field="favorite"><option value="false" ${prompt?.favorite ? "" : "selected"}>否</option><option value="true" ${prompt?.favorite ? "selected" : ""}>是</option></select></div>
          </div>
          </details>
        </div>
        <div class="tb-spm-editor-error" data-ed="error" role="alert" hidden style="white-space:pre-wrap;padding:10px;color:#ffb4b4"></div>
        <div class="tb-spm-editor-recovery" data-ed="recovery" hidden></div>
        <section class="tb-spm-editor-recovery" data-ed="discard-confirm" role="group" aria-labelledby="tb-spm-discard-title" aria-describedby="tb-spm-discard-message" hidden>
          <div id="tb-spm-discard-title" class="tb-spm-recovery-title">未保存的修改</div>
          <p id="tb-spm-discard-message" role="status">当前修改尚未保存。保留修改继续编辑，或放弃修改并关闭。</p>
          <div class="tb-spm-recovery-actions"><button type="button" class="tb-spm-small-btn" data-ed="keep-draft">保留修改</button><button type="button" class="tb-spm-small-btn" data-ed="discard-draft">放弃修改</button></div>
        </section>
        <div class="tb-spm-editor-actions">
          <button class="tb-spm-small-btn" data-ed="cancel">取消</button>
          <button class="tb-spm-small-btn primary" data-ed="save">${mode === "edit" ? "保存修改" : "另存为新资料"}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    if (mode === 'edit' && prompt?.id) {
      const links = document.createElement('div');
      overlay.querySelector('.tb-spm-editor-form').appendChild(links);
      const loadLinks = () => import('/extensions/ComfyUI-Unified-Prompt-Workbench/historical_links.js').then(module => {
        if (links.isConnected) return module.mountHistoricalLinks(links, {kind:'prompt', id:prompt.id});
      }).catch(() => {
        if (!links.isConnected) return;
        links.textContent = '历史关联暂不可读。';
        const retry = document.createElement('button'); retry.type='button'; retry.textContent='重试'; retry.onclick=loadLinks; links.appendChild(retry);
      });
      loadLinks();
    }
    const splitPlan=overlay.querySelector('[data-field="split_plan"]');
    const updatePlanSections=()=>{
      const enabled=splitPlan.checked,positive=overlay.querySelector('[data-field="plan_positive"]').value,negative=overlay.querySelector('[data-field="plan_negative"]').value;
      overlay.querySelector('[data-ed="plan-sections"]').hidden=!enabled;
      const body=overlay.querySelector('[data-field="prompt"]');body.readOnly=enabled;
      const usage=overlay.querySelector('[data-field="usage"]');usage.disabled=enabled;
      if(enabled){body.value=[positive.trim()?'[正向]\n'+positive:'',negative.trim()?'[负向]\n'+negative:''].filter(Boolean).join('\n\n');usage.value=positive.trim()&&negative.trim()?'mixed':negative.trim()?'negative':'positive';overlay.querySelector('[data-field="is_user_plan"]').checked=true;overlay.querySelector('[data-field="content_type"]').value='template';}
    };
    splitPlan.onchange=updatePlanSections;for(const name of ['plan_positive','plan_negative'])overlay.querySelector(`[data-field="${name}"]`).oninput=updatePlanSections;
    updatePlanSections();
    const classSelect = overlay.querySelector('[data-field="primary_class"]');
    const kind = libraryData?.selector_class_kinds?.[classSelect.value];
    if (kind && Array.isArray(prefill?.selector_group_ids)) editing.collectionDrafts[kind] = {groupIds:prefill.selector_group_ids};
    updateEditorCollections(overlay);
    classSelect.onchange = () => updateEditorCollections(overlay);
    const draft = editing;
    draft.readEditorSnapshot = () => JSON.stringify({
      fields: [...overlay.querySelectorAll('[data-field]')].map(control => [control.dataset.field,
        control.type === 'checkbox' ? control.checked : control.value]),
      collectionKind: draft.collectionKind,
      collection: Object.fromEntries(['groupIds', 'nickname', 'notes'].map(key =>
        [key, draft.collectionDrafts[draft.collectionKind]?.[key] || (key === 'groupIds' ? [] : '')])),
    });
    draft.initialEditorSnapshot = draft.readEditorSnapshot();
    let lastEditorField = overlay.querySelector('[data-field="alias"]');
    overlay.addEventListener('focusin', event => {
      if (event.target.matches('input,textarea,select')) lastEditorField = event.target;
    });
    const closeConfirmation = overlay.querySelector('[data-ed="discard-confirm"]');
    const keepDraft = overlay.querySelector('[data-ed="keep-draft"]');
    draft.clearCloseConfirmation = (restoreFocus = false) => {
      if (closeConfirmation.hidden) return;
      const focused = closeConfirmation.contains(document.activeElement);
      closeConfirmation.hidden = true;
      if (restoreFocus || focused) {
        const field = !lastEditorField?.disabled && editorElementVisible(lastEditorField) ? lastEditorField : overlay.querySelector('[data-field="alias"]');
        field?.focus({preventScroll:true});
      }
    };
    const keepEditing = () => {
      if (editing !== draft || draft.saving) return;
      draft.clearCloseConfirmation(true);
    };
    const closeEditor = async () => {
      if (editing !== draft || draft.saving) return;
      editing = null; overlay.remove();
      await returnToEditorCaller(draft);
    };
    const cancelEditing = async () => {
      if (editing !== draft || draft.saving) return;
      if (draft.readEditorSnapshot() === draft.initialEditorSnapshot) { await closeEditor(); return; }
      closeConfirmation.hidden = false;
      keepDraft.focus({preventScroll:true});
    };
    keepDraft.onclick = keepEditing;
    overlay.querySelector('[data-ed="discard-draft"]').onclick = closeEditor;
    const clearIfClean = () => {if (!closeConfirmation.hidden && draft.readEditorSnapshot() === draft.initialEditorSnapshot) draft.clearCloseConfirmation();};
    overlay.addEventListener('input', clearIfClean);
    overlay.addEventListener('change', clearIfClean);
    overlay.querySelector('[data-ed="close"]').onclick = cancelEditing;
    overlay.querySelector('[data-ed="cancel"]').onclick = cancelEditing;
    bindLibraryModal(overlay,cancelEditing,overlay.querySelector('[data-field="alias"]'));
    overlay.onclick = (e) => { if (e.target === overlay) cancelEditing(); };
    overlay.querySelector('[data-ed="save"]').onclick = saveEditor;
    const dialog = overlay.querySelector('.tb-spm-editor-box');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'tb-spm-editor-title');
    dialog.tabIndex = -1;
    for (const type of ['copy', 'cut', 'paste']) overlay.addEventListener(type, event => event.stopPropagation());
    overlay.addEventListener('keydown', event => {
      event.stopPropagation();
      if (event.defaultPrevented || event.isComposing) return;
      if (event.key === 'Escape') { event.preventDefault(); if (!closeConfirmation.hidden) keepEditing(); else void cancelEditing(); }
      if (event.key === 'Tab') {
        const items = [...dialog.querySelectorAll('button,input,select,textarea,summary,[tabindex]')]
          .filter(item => !item.disabled && item.tabIndex >= 0 && editorElementVisible(item));
        const first = items[0], last = items.at(-1), active = document.activeElement;
        if (editing?.saving || !items.length) { event.preventDefault(); dialog.focus(); }
        else if (!items.includes(active) || active === (event.shiftKey ? first : last)) {
          event.preventDefault(); (event.shiftKey ? last : first).focus();
        }
      }
    });
    overlay.querySelector('[data-field="alias"]').focus();
    return editing;
  }
  function editorElementVisible(element) {
    if (!element?.isConnected || element.closest('[hidden]') || !element.getClientRects().length || getComputedStyle(element).visibility === 'hidden') return false;
    for (let details = element.closest('details:not([open])'); details; details = details.parentElement?.closest('details:not([open])')) {
      if (!details.querySelector(':scope > summary')?.contains(element)) return false;
    }
    return true;
  }
  function restoreEditorFocus(draft) {
    if (!draft?.returnFocus || (document.activeElement !== document.body && editorElementVisible(document.activeElement))) return;
    const target = draft.returnFocus.closest('details:not([open])')?.querySelector('summary') || draft.returnFocus;
    if (!target.disabled && editorElementVisible(target)) target.focus({preventScroll:true});
    else {
      const panel = document.getElementById(PANEL_ID);
      const card = [...panel?.querySelectorAll('.tb-spm-card') || []].find(item => item.dataset.promptId === draft.promptId);
      const edit = card?.querySelector('[data-act="edit"]');
      const next = edit?.closest('details:not([open])')?.querySelector('summary') || edit;
      if (editorElementVisible(next)) next.focus({preventScroll:true});
      else [...panel?.querySelectorAll('input,button,summary') || []].find(item => !item.disabled && item.tabIndex >= 0 && editorElementVisible(item))?.focus();
    }
  }
  function updateEditorCollections(overlay) {
    const primaryClass = overlay.querySelector('[data-field="primary_class"]').value;
    const kind = libraryData?.selector_class_kinds?.[primaryClass] || 'resource';
    const previousKind = editing.collectionKind;
    if (previousKind && previousKind !== kind) editing.sharedCollectionDraft = structuredClone(editing.collectionDrafts[previousKind] || {});
    if (editing.sharedCollectionDraft) editing.collectionDrafts[kind] = structuredClone(editing.sharedCollectionDraft);
    else if (!editing.collectionDrafts[kind]) editing.collectionDrafts[kind] = {};
    editing.collectionKind = kind;
    editing.sharedCollectionDraft = null;
    const groups = libraryData?.selector_groups?.[kind] || [];
    const host = overlay.querySelector('[data-ed="collections"]');
    host.replaceChildren(); host.hidden = !groups.length;
    if (!groups.length) return;
    const label = document.createElement('label'); label.textContent = '分组'; host.appendChild(label);
    const selected = editing.collectionDrafts[kind]?.groupIds || ['default'];
    editing.collectionDrafts[kind] = {...editing.collectionDrafts[kind], groupIds:selected};
    renderCollectionChoices(host, groups, selected, groupIds => { editing.collectionDrafts[kind].groupIds = groupIds; });
    for (const [key, caption] of [['nickname','收藏别名'],['notes','收藏备注']]) {
      const label = document.createElement('label'); label.textContent = caption;
      const input = document.createElement(key === 'notes' ? 'textarea' : 'input');
      if (key === 'notes') input.style.minHeight = '70px';
      input.value = editing.collectionDrafts[kind][key] || ''; input.dataset.collectionField = key;
      input.oninput = () => { editing.collectionDrafts[kind][key] = input.value; };
      label.appendChild(input); host.appendChild(label);
    }
  }
  async function returnToEditorCaller(draft) {
    if (typeof draft?.onClose !== "function") { restoreEditorFocus(draft); return false; }
    if (document.getElementById(PANEL_ID)) {
      try { await loadData(true, 15000, true); renderPanelContent(); }
      catch (error) { showError(error); }
    }
    await draft.onClose();
    restoreEditorFocus(draft);
    return true;
  }
  function renderEditorRecovery(overlay, latest, revision, errorText, deleted = false) {
    const box = overlay?.querySelector('[data-ed="recovery"]');
    if (!box) return;
    const draft = editing;
    const prompt = latest?.prompt || {};
    box.hidden = false;
    box.innerHTML = `<div class="tb-spm-recovery-title">${deleted ? "资料已删除：当前草稿仍保留" : "保存冲突：资料已在其他窗口更新"}</div>
      <div class="tb-spm-recovery-error">${escapeHtml(errorText || "请先对照当前版本")}</div>
      <div class="tb-spm-recovery-compare"><strong>${escapeHtml(prompt.alias || "（当前版本不可用）")}</strong>${latest?.category ? `<div>当前分类：${escapeHtml(latest.category.name || latest.category.id || "")}</div>` : ""}<pre>${escapeHtml(prompt.prompt || "")}</pre></div>
      <div class="tb-spm-recovery-actions"><button class="tb-spm-small-btn" data-ed="accept-latest" ${latest?.prompt && revision ? "" : "disabled"}>采纳最新版</button><button class="tb-spm-small-btn primary" data-ed="save-draft-version" ${revision ? "" : "disabled"}>${deleted ? "另存为新资料（新身份）" : "基于此版本保存当前草稿"}</button><button class="tb-spm-small-btn" data-ed="retry-read">重新读取</button></div>`;
    box.querySelector('[data-ed="accept-latest"]').onclick = () => {
      const current = document.getElementById(EDITOR_ID);
      if (current !== overlay || editing !== draft || draft.saving || !revision || !latest?.prompt) return;
      const get = name => current.querySelector(`[data-field="${name}"]`);
      const p = latest.prompt || {};
      for (const [name, value] of [["alias", p.alias || ""], ["prompt", p.prompt || ""], ["description", p.description || ""], ["image", p.image || ""], ["tags", (p.tags || []).join(", ")]]) if (get(name)) get(name).value = value;
      if (get("favorite")) get("favorite").value = p.favorite ? "true" : "false";
      if (get("template")) get("template").value = p.template ? "true" : "false";
      const semantic = p._semantic || p._classification || {};
      get('subcategories').value = (semantic.subcategories || []).join(', ');
      get('preview_url').value = p.preview_url || '';
      get('random_pool_eligible').checked = semantic.random_pool_eligible === true && semantic.strict_model_pool_eligible === true;
      if (get("is_user_plan")) get("is_user_plan").checked = p.is_user_plan === true;
      get('split_plan').checked=!!p.plan_sections;get('plan_positive').value=p.plan_sections?.positive||'';get('plan_negative').value=p.plan_sections?.negative||'';get('split_plan').onchange();
      for (const name of ["primary_class", "content_type", "usage"]) if (get(name)) get(name).value = name === "usage" ? semantic.declared_usage || semantic.usage || "unknown" : semantic[name] || (name === "content_type" ? "fragment" : "");
      editing.promptSnapshot = structuredClone(p);
      editing.collectionDrafts = structuredClone(p._selector_favorites || {});
      editing.sharedCollectionDraft = structuredClone(p._collection || null);
      editing.collectionKind = null;
      updateEditorCollections(overlay);
      editing.mode = "edit";
      editing.promptId = p.id;
      editing.baseRevision = revision;
      get("image_file").value = "";
      box.hidden = true;
      draft.initialEditorSnapshot = draft.readEditorSnapshot();
      draft.clearCloseConfirmation?.();
      get("alias").focus();
    };
    box.querySelector('[data-ed="save-draft-version"]').onclick = async () => {
      if (editing !== draft || document.getElementById(EDITOR_ID) !== overlay || draft.saving || !revision) return;
      if (deleted) { editing.mode = "create"; editing.promptId = null; editing.draftId = uuid(); }
      else if (latest?.prompt) {
        editing.promptSnapshot = structuredClone(latest.prompt);
        editing.mode = "edit";
        editing.promptId = latest.prompt.id;
      }
      editing.baseRevision = revision;
      box.hidden = true;
      await saveEditor();
    };
    box.querySelector('[data-ed="retry-read"]').onclick = () => recoverEditorConflict("重新读取当前版本");
    if (!draft.saving) box.querySelector('button:not(:disabled)')?.focus();
  }
  async function recoverEditorConflict(errorText) {
    const overlay = document.getElementById(EDITOR_ID);
    const draft = editing;
    if (!overlay || !draft || (draft.mode === "edit" && !draft.promptId)) return;
    try {
      const latest = await fetchLibraryPrompt(draft.promptId || draft.draftId);
      if (editing !== draft || document.getElementById(EDITOR_ID) !== overlay) return;
      renderEditorRecovery(overlay, latest, latest.revision, errorText);
    } catch (error) {
      if (editing !== draft || document.getElementById(EDITOR_ID) !== overlay) return;
      const missing = error.status === 404 && error.deleted === true;
      const revision = missing ? error.revision || "" : "";
      const message = missing && draft.mode === "create" ? "资料库已更新；当前草稿尚未保存。" : `无法读取当前版本：${error?.message || error}`;
      renderEditorRecovery(overlay, null, revision, message, missing && draft.mode === "edit");
    }
  }
  async function saveEditor() {
    const overlay = document.getElementById(EDITOR_ID);
    if (!overlay || !editing || !libraryData || editing.saving) return;
    const draft = editing;
    draft.clearCloseConfirmation?.();
    const errorBox = overlay.querySelector('[data-ed="error"]');
    if (errorBox) { errorBox.hidden = true; errorBox.textContent = ""; }
    const reportError = message => {
      if (errorBox) { errorBox.textContent = message; errorBox.hidden = false; }
    };
    const get = (name) => overlay.querySelector(`[data-field="${name}"]`);
    const alias = get("alias").value.trim();
    const promptText = get("prompt").value;
    if (!alias && !promptText.trim()) { reportError("至少填写名称或正文。"); get("alias").focus(); return; }
    if (get("is_user_plan").checked && !get("primary_class").value) {
      reportError("请选择资料主题后再保存为方案。"); get("primary_class").focus(); return;
    }
    const targetCategoryId = draft.categoryId || draft.originalCategoryId;
    let imageName = get("image").value.trim();
    const file = get("image_file").files && get("image_file").files[0];
    const saveBtn = overlay.querySelector('[data-ed="save"]');
    const dialog = overlay.querySelector('.tb-spm-editor-box');
    const controls = [...overlay.querySelectorAll('input,select,textarea,button')].map(control => [control, control.disabled]);
    draft.saving = true;
    for (const [control] of controls) control.disabled = true;
    dialog.setAttribute('aria-busy', 'true');
    dialog.focus();
    saveBtn.textContent = "保存中...";
    try {
      if (file) imageName = await uploadPreview(file, alias || "preset");
      const existing = draft.promptSnapshot || (draft.mode === "edit" ? currentItems.find(item => item.id === draft.promptId) : null);
      const item = {
        ...structuredClone(existing || {}),
        id: draft.mode === "edit" ? existing?.id || draft.draftId : draft.draftId,
        alias,
        prompt: promptText,
        description: get("description").value,
        image: imageName,
        preview_url: get('preview_url').value.trim(),
        tags: get("tags").value.split(",").map(x => x.trim()).filter(Boolean),
        favorite: get("favorite").value === "true",
        is_user_plan: get("is_user_plan").checked,
        plan_sections: get('split_plan').checked?{positive:get('plan_positive').value,negative:get('plan_negative').value}:null,
        template: get("content_type").value === "template",
        usage_count: existing?.usage_count || 0,
        last_used: existing?.last_used || null,
        created_at: existing?.created_at || nowIso(),
      };
      delete item._categoryId;
      delete item._categoryName;
      delete item._semantic;
      const resp = await fetchLibraryWrite(PROMPT_UPSERT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: draft.mode,
          draft_id: draft.draftId,
          source_category_id: draft.categoryId,
          target_category_id: targetCategoryId,
          new_category_name: "",
          prompt: item,
          ...(editing.collectionKind ? {
            selector_group_ids:editing.collectionDrafts[editing.collectionKind]?.groupIds || [],
            selector_metadata:Object.fromEntries(['nickname','notes'].map(key=>[key,editing.collectionDrafts[editing.collectionKind]?.[key] || '']))
          } : {}),
          classification: get("primary_class")?.value ? {
            primary_class: get("primary_class").value,
            subcategories: get('subcategories').value.split(/[,，、]/).map(value => value.trim()).filter(Boolean),
            random_pool_eligible: get('random_pool_eligible').checked,
            content_type: get("content_type").value,
            usage: get("usage").value,
          } : null,
        }),
      }, 30000);
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok || json.error) throw new Error(json.error || `HTTP ${resp.status}`);
      editing = null;
      overlay.remove();
      if (await returnToEditorCaller(draft)) return;
      try { await loadData(true, 15000, true); renderPanelContent(); }
      catch (error) { showError(new Error("资料已保存，刷新列表失败：" + (error?.message || error))); }
      restoreEditorFocus(draft);
    } catch (err) {
      if (err?.isRevisionConflict) {
        await recoverEditorConflict(err.message);
      } else {
        reportError("保存失败，当前草稿仍保留：" + (err.message || String(err)));
      }
    } finally {
      draft.saving = false;
      for (const [control, disabled] of controls) control.disabled = disabled;
      dialog.removeAttribute('aria-busy');
      saveBtn.textContent = draft.mode === "edit" ? "保存修改" : "另存为新资料";
      if (overlay.isConnected && document.activeElement === dialog) {
        const recovery = overlay.querySelector('[data-ed="recovery"]');
        (!recovery.hidden && recovery.querySelector('button:not(:disabled)') || saveBtn).focus();
      }
    }
  }
  async function deletePrompt(categoryId, promptId, alias) {
    if (!libraryData) return;
    if (!confirm(`确认从共享库删除：${alias || promptId} ？\n\n注意：这会写入 PromptSelector 的 data.json。`)) return;
    try {
      const resp = await fetchLibraryWrite(PROMPT_DELETE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_id: promptId }),
      }, 30000);
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok || json.error) throw new Error(json.error || `HTTP ${resp.status}`);
      await loadData(true, 15000, true);
      renderPanelContent();
    }
    catch (err) { alert("删除失败：" + (err.message || String(err))); }
  }
  let weilinEditorSession = 0;
  let weilinActivePromptId = '';
  const weilinResourceEntries = new WeakMap();
  const weilinWriters = new Map();
  async function weilinInsertionTarget(root) {
    const {createTextInserter, captureSelection} = await import('/extensions/ComfyUI-Unified-Prompt-Workbench/prompt_target.js');
    const input = root.querySelector('textarea.input-area');
    const session = weilinEditorSession;
    const promptId = weilinActivePromptId;
    weilinWriters.get(root)?.dispose();
    const onInsert = createTextInserter({
      inputElement:input, selectionSnapshot:captureSelection(input), followSelection:true, commaSeparated:true,
      read:() => input.value,
      write:value => {input.value = value; input.dispatchEvent(new Event('input',{bubbles:true}));},
      settleWrite:() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))),
      equivalent:(actual,expected) => actual.replace(/[,\s]+$/, '') === expected.replace(/[,\s]+$/, ''),
      validate:() => !!input?.isConnected && !!input.getClientRects().length && session === weilinEditorSession && promptId === weilinActivePromptId,
    });
    weilinWriters.set(root, onInsert);
    return {onInsert,targetLabel:'WeiLin 当前提示词（正向）',targetDirection:'positive'};
  }
  function installWeiLinResourceEntry(root) {
    const container = root.querySelector(".tag-manager-container");
    if (!container || weilinResourceEntries.has(root)) return;
    const tabs = document.createElement("div");
    tabs.className = "tb-spm-resource-tabs";
    tabs.setAttribute("aria-label", "WeiLin 资源库");
    tabs.innerHTML = `<button class="tb-spm-btn" data-resource-view="shared">共享资料库</button>
      <button class="tb-spm-btn" data-theme="clothing_accessory">服装</button>
      <button class="tb-spm-btn" data-theme="pose_action">姿势</button>
      <button class="tb-spm-btn" data-theme="background_environment">背景</button>
      <button class="tb-spm-btn" data-theme="identity">角色</button>
      <button class="tb-spm-btn" data-theme="artist_style">画师</button>
      <button class="tb-spm-btn" data-resource-view="tags">基础 Tag</button>
      <small>与 Anima 选择器共用资源、分类和修改</small>`;
    const host = document.createElement("div");
    host.className = "tb-spm-resource-host";
    container.prepend(tabs);
    container.appendChild(host);
    const setView = shared => {
      container.classList.add("tb-spm-show-shared");
      tabs.querySelector('[data-resource-view="shared"]').setAttribute("aria-pressed", String(shared));
      tabs.querySelector('[data-resource-view="tags"]').setAttribute("aria-pressed", String(!shared));
    };
    const showShared = async (semanticClass = "") => {
      const {closeTagManager} = await import('/extensions/ComfyUI-Unified-Prompt-Workbench/tag_manager.js');
      if (!closeTagManager()) return;
      setView(true);
      await openPanel({view: "all", semanticClass, mount: host, ...await weilinInsertionTarget(root), onClose: () => showTags()});
    };
    tabs.querySelector('[data-resource-view="shared"]').onclick = () => showShared();
    tabs.querySelectorAll("[data-theme]").forEach(button => { button.onclick = () => showShared(button.dataset.theme); });
    const showTags = async () => {
      const {openTagManager} = await import('/extensions/ComfyUI-Unified-Prompt-Workbench/tag_manager.js');
      setView(true);
      tabs.querySelector('[data-resource-view="shared"]').setAttribute('aria-pressed', 'false');
      tabs.querySelector('[data-resource-view="tags"]').setAttribute('aria-pressed', 'true');
      await openTagManager({mount:host,...await weilinInsertionTarget(root),onClose:()=>showShared()});
    };
    tabs.querySelector('[data-resource-view="tags"]').onclick = showTags;
    const heading = container.parentElement.querySelector(".section-title");
    if (heading) heading.textContent = "资源库";
    weilinResourceEntries.set(root, {showShared, host});
    setView(true);
    if (!document.getElementById(PANEL_ID)) void showShared();
  }
  window.addEventListener("message", event => {
    if (event.source !== window) return;
    if (event.data?.type === 'weilin_prompt_ui_open_global_prompt_box') {
      weilinEditorSession += 1;
      weilinActivePromptId = '';
      for (const writer of weilinWriters.values()) {
        writer.dispose();
        if (insertionTarget?.onInsert === writer) insertionTarget = null;
      }
      weilinWriters.clear();
      return;
    }
    if (event.data?.type !== "weilin_prompt_ui_openPromptBox") return;
    weilinEditorSession += 1;
    weilinActivePromptId = event.data.id;
    requestAnimationFrame(() => {
      document.querySelectorAll(".weilin_prompt_ui_prompt-box").forEach(root => {
        const entry = weilinResourceEntries.get(root);
        if (entry?.host.contains(document.getElementById(PANEL_ID))) void entry.showShared();
      });
    });
  });
  document.addEventListener('input', event => {
    const input = event.target;
    if (!weilinActivePromptId || !input.matches?.('.weilin_prompt_ui_prompt-box textarea.input-area')) return;
    window.dispatchEvent(new MessageEvent('message', {data:{
      type:'weilin_prompt_ui_prompt_write_prompt_' + weilinActivePromptId,
      prompt:input.value,
    }}));
  });
  function addToolbarButton() {
    injectStyle();
    document.querySelectorAll(".weilin_prompt_ui_prompt-box").forEach(installWeiLinResourceEntry);
    document.querySelectorAll(".weilin_prompt_ui_prompt-box .center-container").forEach((toolbar) => {
      if (toolbar.querySelector(".tb-shared-preset-action")) return;
      const wrapper = document.createElement("div");
      wrapper.className = "action-item tb-shared-preset-action";
      const btn = document.createElement("button");
      btn.className = "tb-spm-btn";
      btn.title = "在当前提示词窗口查看和编辑共用资源";
      btn.innerHTML = `<span>资源库</span>`;
      btn.onclick = async () => {
        const entry = weilinResourceEntries.get(toolbar.closest(".weilin_prompt_ui_prompt-box"));
        if (entry) {
          await entry.showShared();
          entry.host.scrollIntoView({behavior: "smooth", block: "start"});
        }
      };
      wrapper.appendChild(btn);
      toolbar.appendChild(wrapper);
    });
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest?.('.weilin_prompt_ui_prompt-box .center-container button');
    if (!button) return;
    const label = button.textContent.trim();
    const action = {'标签管理':'tags','Tag Manager':'tags','Lora管理':'loras','LoRA Manager':'loras','Danbooru管理器':'gallery'}[label];
    if (!action) return;
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      if (action === 'tags') {
        const {openTagManager} = await import('/extensions/ComfyUI-Unified-Prompt-Workbench/tag_manager.js');
        await openTagManager({...await weilinInsertionTarget(button.closest('.weilin_prompt_ui_prompt-box'))});
      } else { await window.unifiedOpenWorkbench(); window.unifiedWorkbenchOpenProvider(action); }
    } catch (error) { alert(error.message); }
  }, true);
  let toolbarRefreshScheduled = false;
  function scheduleToolbarRefresh() {
    if (toolbarRefreshScheduled) return;
    toolbarRefreshScheduled = true;
    requestAnimationFrame(() => {
      toolbarRefreshScheduled = false;
      addToolbarButton();
    });
  }
  const observer = new MutationObserver(records => {
    const selector = '.weilin_prompt_ui_prompt-box,.center-container,.tag-manager-container';
    if (records.some(record => [...record.removedNodes].some(node =>
      node.nodeType === 1 && (node.matches('.weilin_prompt_ui_prompt-box,.weilin_prompt_ui_draggable-window') || node.querySelector('.weilin_prompt_ui_prompt-box'))
    ))) {
      for (const [root, writer] of weilinWriters) {
        if (root.isConnected) continue;
        writer.dispose();
        weilinWriters.delete(root);
        if (insertionTarget?.onInsert === writer) insertionTarget = null;
      }
      if (!document.querySelector('.weilin_prompt_ui_prompt-box')) weilinActivePromptId = '';
    }
    if (records.some(record => [...record.addedNodes].some(node =>
      node.nodeType === 1 && (node.matches(selector) || node.querySelector(selector))
    ))) scheduleToolbarRefresh();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addToolbarButton);
  else addToolbarButton();
})();
