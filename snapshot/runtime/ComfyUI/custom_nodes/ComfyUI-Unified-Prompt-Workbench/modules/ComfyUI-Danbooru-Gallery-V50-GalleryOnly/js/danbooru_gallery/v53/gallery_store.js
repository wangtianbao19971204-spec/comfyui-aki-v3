import { GALLERY_SOURCES, GALLERY_VIEWS } from "./gallery_api.js";

function clone(value) {
  if (value === undefined) return undefined;
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function normalizeSource(value) {
  const source = String(value || "").trim().toLowerCase();
  if (!GALLERY_SOURCES.includes(source)) throw new RangeError(`unsupported gallery source: ${source}`);
  return source;
}

function normalizeQueryKey(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new TypeError("queryKey must be a 64-character lowercase SHA-256 hex string");
  }
  return value;
}

function normalizeScrollTop(value) {
  const scrollTop = Number(value ?? 0);
  if (!Number.isFinite(scrollTop) || scrollTop < 0) throw new RangeError("scrollTop must be non-negative");
  return scrollTop;
}

function normalizeCursor(value, field) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "string") throw new TypeError(`${field} must be an opaque string or null`);
  return value;
}

function defaultDraft() {
  return {
    mode: "latest",
    terms: "",
    facet: { kind: null, id: null, label: null },
    sort: { metric: null, period: null, anchorDate: null, allowApprox: false },
    filters: { safetyProfile: null },
    pageSize: 20,
    viewMemory: { queryKey: null, scrollTop: 0 },
  };
}

function mergeDraft(current, patch = {}) {
  if (!patch || typeof patch !== "object" || Array.isArray(patch)) {
    throw new TypeError("draft patch must be an object");
  }
  const next = clone(current);
  if (patch.mode !== undefined) {
    const mode = String(patch.mode).trim().toLowerCase();
    if (!GALLERY_VIEWS.includes(mode)) throw new RangeError(`unsupported gallery mode: ${mode}`);
    next.mode = mode;
  }
  if (patch.terms !== undefined) next.terms = String(patch.terms ?? "");
  if (patch.facet !== undefined) next.facet = { ...next.facet, ...clone(patch.facet) };
  if (patch.sort !== undefined) next.sort = { ...next.sort, ...clone(patch.sort) };
  if (patch.filters !== undefined) next.filters = { ...next.filters, ...clone(patch.filters) };
  if (patch.pageSize !== undefined) {
    const pageSize = Number(patch.pageSize);
    if (!Number.isSafeInteger(pageSize) || pageSize < 1 || pageSize > 200) {
      throw new RangeError("pageSize must be an integer between 1 and 200");
    }
    next.pageSize = pageSize;
  }
  if (patch.viewMemory !== undefined) {
    next.viewMemory = { ...next.viewMemory, ...clone(patch.viewMemory) };
    if (next.viewMemory.queryKey !== null) normalizeQueryKey(next.viewMemory.queryKey);
    next.viewMemory.scrollTop = normalizeScrollTop(next.viewMemory.scrollTop);
  }
  return next;
}

function itemIdentity(item, source, fallbackIndex) {
  if (item && typeof item === "object" && item.id !== undefined && item.id !== null) {
    return `${item.sourceSite || source}:${String(item.id)}`;
  }
  return `__anonymous__:${fallbackIndex}`;
}

function visibleItems(session) {
  const result = [];
  const seen = new Set();
  let anonymousIndex = 0;
  for (const page of session.pages.slice(0, session.pageIndex + 1)) {
    for (const item of page.items) {
      const key = itemIdentity(item, session.source, anonymousIndex++);
      if (!seen.has(key)) {
        seen.add(key);
        result.push(clone(item));
      }
    }
  }
  return result;
}

function newSession(source, queryKey, access) {
  return {
    source,
    queryKey,
    items: [],
    pages: [],
    pageIndex: -1,
    warnings: [],
    applied: {},
    initialError: null,
    loadMoreError: null,
    cursorExpired: false,
    lastAccess: access,
  };
}

export class GalleryStore {
  constructor({ persisted, sources = GALLERY_SOURCES, maxSessionsPerSource = 8 } = {}) {
    if (!Array.isArray(sources) || !sources.length) throw new TypeError("sources must be a non-empty array");
    this.sources = Object.freeze(sources.map(normalizeSource));
    if (new Set(this.sources).size !== this.sources.length) throw new TypeError("sources must be unique");
    if (!Number.isSafeInteger(maxSessionsPerSource) || maxSessionsPerSource < 1) {
      throw new RangeError("maxSessionsPerSource must be a positive integer");
    }
    this.maxSessionsPerSource = maxSessionsPerSource;
    this._clock = 0;
    this._sessions = new Map(this.sources.map((source) => [source, new Map()]));
    const requestedActiveSource = persisted?.activeSource;
    const activeSource = this.sources.includes(String(requestedActiveSource || "").toLowerCase())
      ? String(requestedActiveSource).toLowerCase()
      : this.sources[0];
    this.persisted = {
      schemaVersion: 2,
      activeSource,
      sourceDrafts: {},
      outputSettings: clone(persisted?.outputSettings || {}),
      legacyMigrationDone: Boolean(persisted?.legacyMigrationDone),
    };
    for (const source of this.sources) {
      this.persisted.sourceDrafts[source] = mergeDraft(defaultDraft(), persisted?.sourceDrafts?.[source]);
    }
    this.activeSession = null;
  }

  _sourceSessions(source) {
    const normalizedSource = normalizeSource(source);
    const sessions = this._sessions.get(normalizedSource);
    if (!sessions) throw new RangeError(`source is not configured in this store: ${normalizedSource}`);
    return sessions;
  }

  _touch(session) {
    session.lastAccess = ++this._clock;
  }

  _evict(source, protectedKey) {
    const sessions = this._sourceSessions(source);
    while (sessions.size > this.maxSessionsPerSource) {
      const candidates = Array.from(sessions.values()).filter((session) => session.queryKey !== protectedKey);
      if (!candidates.length) break;
      candidates.sort((left, right) => left.lastAccess - right.lastAccess);
      sessions.delete(candidates[0].queryKey);
    }
  }

  serialize() {
    return clone(this.persisted);
  }

  getDraft(source = this.persisted.activeSource) {
    const normalizedSource = normalizeSource(source);
    return clone(this.persisted.sourceDrafts[normalizedSource]);
  }

  updateDraft(source, patch) {
    const normalizedSource = normalizeSource(source);
    const draft = mergeDraft(this.persisted.sourceDrafts[normalizedSource], patch);
    this.persisted.sourceDrafts[normalizedSource] = draft;
    return clone(draft);
  }

  setActiveSource(source) {
    const normalizedSource = normalizeSource(source);
    this._sourceSessions(normalizedSource);
    this.persisted.activeSource = normalizedSource;
    const rememberedKey = this.persisted.sourceDrafts[normalizedSource].viewMemory.queryKey;
    this.activeSession = rememberedKey && this._sourceSessions(normalizedSource).has(rememberedKey)
      ? { source: normalizedSource, queryKey: rememberedKey }
      : null;
    if (this.activeSession) this._touch(this._sourceSessions(normalizedSource).get(rememberedKey));
    return this.getDraft(normalizedSource);
  }

  activateSession(source, queryKey) {
    const normalizedSource = normalizeSource(source);
    const normalizedKey = normalizeQueryKey(queryKey);
    const sessions = this._sourceSessions(normalizedSource);
    let session = sessions.get(normalizedKey);
    if (!session) {
      session = newSession(normalizedSource, normalizedKey, ++this._clock);
      sessions.set(normalizedKey, session);
    } else {
      this._touch(session);
    }
    this.persisted.activeSource = normalizedSource;
    this.persisted.sourceDrafts[normalizedSource].viewMemory.queryKey = normalizedKey;
    this.activeSession = { source: normalizedSource, queryKey: normalizedKey };
    this._evict(normalizedSource, normalizedKey);
    return clone(session);
  }

  hasSession(source, queryKey) {
    return this._sourceSessions(source).has(normalizeQueryKey(queryKey));
  }

  getSession(source, queryKey) {
    const session = this._sourceSessions(source).get(normalizeQueryKey(queryKey));
    if (!session) return null;
    this._touch(session);
    return clone(session);
  }

  listSessionKeys(source) {
    return Array.from(this._sourceSessions(source).values())
      .sort((left, right) => left.lastAccess - right.lastAccess)
      .map((session) => session.queryKey);
  }

  recordPage(source, queryKey, page) {
    if (!page || typeof page !== "object" || Array.isArray(page)) throw new TypeError("page must be an object");
    const normalizedSource = normalizeSource(source);
    const normalizedKey = normalizeQueryKey(queryKey);
    const sessions = this._sourceSessions(normalizedSource);
    const session = sessions.get(normalizedKey);
    if (!session) throw new Error("activateSession must be called before recordPage");
    const requestCursor = normalizeCursor(page.requestCursor, "requestCursor");
    const nextCursor = normalizeCursor(page.nextCursor, "nextCursor");
    if (typeof page.pageKey !== "string" || !page.pageKey) throw new TypeError("pageKey is required");
    if (!Array.isArray(page.items)) throw new TypeError("page.items must be an array");

    const existingIndex = session.pages.findIndex((entry) => entry.requestCursor === requestCursor);
    if (existingIndex >= 0) {
      session.pageIndex = existingIndex;
      session.items = visibleItems(session);
      this._touch(session);
      this._rememberScroll(session);
      return { added: false, pageIndex: existingIndex, session: clone(session) };
    }

    if (!session.pages.length && requestCursor !== null) {
      throw new Error("the first page must use a null requestCursor");
    }
    if (session.pages.length) {
      if (session.pageIndex < session.pages.length - 1) session.pages.splice(session.pageIndex + 1);
      const expectedCursor = session.pages[session.pageIndex].nextCursor;
      if (expectedCursor === null) throw new Error("cannot append after a terminal page");
      if (requestCursor !== expectedCursor) throw new Error("requestCursor does not match the previous nextCursor");
    }

    session.pages.push({
      requestCursor,
      nextCursor,
      pageKey: page.pageKey,
      items: clone(page.items),
      scrollTop: normalizeScrollTop(page.scrollTop),
    });
    session.pageIndex = session.pages.length - 1;
    session.items = visibleItems(session);
    session.warnings = clone(page.warnings || session.warnings);
    session.applied = clone(page.applied || session.applied);
    session.initialError = null;
    session.loadMoreError = null;
    session.cursorExpired = false;
    this._touch(session);
    this._rememberScroll(session);
    return { added: true, pageIndex: session.pageIndex, session: clone(session) };
  }

  _rememberScroll(session) {
    const page = session.pages[session.pageIndex];
    const draft = this.persisted.sourceDrafts[session.source];
    draft.viewMemory = {
      queryKey: session.queryKey,
      scrollTop: page ? page.scrollTop : 0,
    };
  }

  forwardAction(source, queryKey) {
    const session = this._sourceSessions(source).get(normalizeQueryKey(queryKey));
    if (!session || !session.pages.length) return { type: "request", cursor: null };
    if (session.pageIndex < session.pages.length - 1) {
      return { type: "cached", pageIndex: session.pageIndex + 1 };
    }
    const cursor = session.pages[session.pageIndex].nextCursor;
    return cursor === null ? { type: "end" } : { type: "request", cursor };
  }

  goForward(source, queryKey) {
    const session = this._sourceSessions(source).get(normalizeQueryKey(queryKey));
    if (!session || session.pageIndex >= session.pages.length - 1) return null;
    session.pageIndex += 1;
    session.items = visibleItems(session);
    this._touch(session);
    this._rememberScroll(session);
    return clone(session);
  }

  goBack(source, queryKey) {
    const session = this._sourceSessions(source).get(normalizeQueryKey(queryKey));
    if (!session || session.pageIndex <= 0) return null;
    session.pageIndex -= 1;
    session.items = visibleItems(session);
    this._touch(session);
    this._rememberScroll(session);
    return clone(session);
  }

  setScrollTop(source, queryKey, scrollTop) {
    const session = this._sourceSessions(source).get(normalizeQueryKey(queryKey));
    if (!session || session.pageIndex < 0) return false;
    session.pages[session.pageIndex].scrollTop = normalizeScrollTop(scrollTop);
    this._touch(session);
    this._rememberScroll(session);
    return true;
  }

  setLoadMoreError(source, queryKey, error) {
    const session = this._sourceSessions(source).get(normalizeQueryKey(queryKey));
    if (!session) return false;
    session.loadMoreError = clone(error);
    this._touch(session);
    return true;
  }

  markCursorExpired(source, queryKey, error = { code: "cursor_expired" }) {
    const session = this._sourceSessions(source).get(normalizeQueryKey(queryKey));
    if (!session) return false;
    session.cursorExpired = true;
    session.loadMoreError = clone(error);
    this._touch(session);
    return true;
  }

  restartSession(source, queryKey) {
    const session = this._sourceSessions(source).get(normalizeQueryKey(queryKey));
    if (!session) return false;
    Object.assign(session, {
      items: [],
      pages: [],
      pageIndex: -1,
      warnings: [],
      applied: {},
      initialError: null,
      loadMoreError: null,
      cursorExpired: false,
    });
    this._touch(session);
    this._rememberScroll(session);
    return true;
  }
}
