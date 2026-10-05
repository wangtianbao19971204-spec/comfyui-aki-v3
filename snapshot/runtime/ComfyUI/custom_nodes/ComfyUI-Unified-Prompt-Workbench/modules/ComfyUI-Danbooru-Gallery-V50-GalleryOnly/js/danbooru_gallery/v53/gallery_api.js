import {
  canonicalQueryJson,
  createCanonicalQueryKey,
  createClientRequestId,
  normalizeQueryKeyInput,
} from "./query_contract.js";

export const V2_API_ROOT = "/danbooru_gallery/v2";
export const V2_ROUTES = Object.freeze(["providers", "browse", "facets", "autocomplete"]);
export const GALLERY_SOURCES = Object.freeze(["danbooru", "gelbooru", "yandere", "civitai"]);
export const GALLERY_VIEWS = Object.freeze(["latest", "ranking", "category", "search", "favorites"]);

function aliased(input, camelName, snakeName) {
  const camelValue = input[camelName];
  const snakeValue = input[snakeName];
  if (camelValue !== undefined && snakeValue !== undefined && camelValue !== snakeValue) {
    throw new TypeError(`${camelName} and ${snakeName} disagree`);
  }
  return camelValue !== undefined ? camelValue : snakeValue;
}

function normalizeRoute(value) {
  const route = String(value || "browse").trim().toLowerCase();
  if (!V2_ROUTES.includes(route)) throw new RangeError(`unsupported V2 route: ${route}`);
  return route;
}

function normalizeSource(value, { optional = false } = {}) {
  if ((value === undefined || value === null || value === "") && optional) return null;
  const source = String(value || "").trim().toLowerCase();
  if (!GALLERY_SOURCES.includes(source)) throw new RangeError(`unsupported gallery source: ${source}`);
  return source;
}

function normalizeView(value) {
  const view = String(value || "").trim().toLowerCase();
  if (!GALLERY_VIEWS.includes(view)) throw new RangeError(`unsupported gallery view: ${view}`);
  return view;
}

function normalizeCursor(value) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "string") throw new TypeError("cursor must be an opaque string or null");
  return value;
}

function normalizeBasePath(value) {
  const basePath = String(value || V2_API_ROOT).replace(/\/+$/, "");
  if (!basePath.startsWith("/") || basePath.includes("?") || basePath.includes("#")) {
    throw new TypeError("basePath must be a relative absolute-path without query or fragment");
  }
  return basePath;
}

function appendOptional(params, name, value) {
  if (value !== null && value !== undefined && value !== "") params.set(name, String(value));
}

function makeCanonicalInput(input, route, source) {
  const requestedView = aliased(input, "view", "view");
  const view = route === "facets"
    ? "category"
    : route === "autocomplete"
      ? "search"
      : normalizeView(requestedView);
  return normalizeQueryKeyInput({
    source,
    view,
    query: input.query,
    metric: input.metric,
    period: input.period,
    anchorDate: aliased(input, "anchorDate", "anchor_date"),
    facetKind: aliased(input, "facetKind", "facet_kind"),
    facetId: aliased(input, "facetId", "facet_id"),
    safetyProfile: aliased(input, "safetyProfile", "safety_profile"),
    pageSize: aliased(input, "pageSize", "page_size"),
    allowApprox: aliased(input, "allowApprox", "allow_approx"),
  });
}

/**
 * Build one normalized V2 GET request. `route` defaults to browse; facets and
 * autocomplete use category/search respectively as their stable query-key view.
 */
export async function buildGalleryRequest(input, options = {}) {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new TypeError("request input must be an object");
  }
  const route = normalizeRoute(input.route);
  const basePath = normalizeBasePath(options.basePath);
  const source = normalizeSource(input.source, { optional: route === "providers" });
  const path = `${basePath}/${route}`;
  const params = new URLSearchParams();

  if (source) params.set("source", source);
  if (route === "providers") {
    return Object.freeze({
      method: "GET",
      route,
      path,
      url: params.size ? `${path}?${params}` : path,
      query: Object.freeze(Object.fromEntries(params)),
      clientRequestId: null,
      clientQueryKey: null,
      canonicalQuery: null,
      canonicalJson: null,
    });
  }

  const canonicalQuery = makeCanonicalInput(input, route, source);
  const clientRequestId = createClientRequestId(options.idFactory);
  const clientQueryKey = await createCanonicalQueryKey(canonicalQuery);
  const cursor = normalizeCursor(input.cursor);

  if (route === "browse") {
    params.set("view", canonicalQuery.view);
    appendOptional(params, "query", canonicalQuery.query);
    appendOptional(params, "metric", canonicalQuery.metric);
    appendOptional(params, "period", canonicalQuery.period);
    appendOptional(params, "anchor_date", canonicalQuery.anchorDate);
    appendOptional(params, "facet_kind", canonicalQuery.facetKind);
    appendOptional(params, "facet_id", canonicalQuery.facetId);
    appendOptional(params, "safety_profile", canonicalQuery.safetyProfile);
    params.set("page_size", String(canonicalQuery.pageSize));
    appendOptional(params, "cursor", cursor);
    if (input.allowApprox !== undefined || input.allow_approx !== undefined) {
      params.set("allow_approx", String(canonicalQuery.allowApprox));
    }
  } else if (route === "facets") {
    if (!canonicalQuery.facetKind) throw new TypeError("facetKind is required for facets requests");
    params.set("facet_kind", canonicalQuery.facetKind);
    appendOptional(params, "query", canonicalQuery.query);
    params.set("page_size", String(canonicalQuery.pageSize));
    appendOptional(params, "cursor", cursor);
  } else {
    if (!canonicalQuery.query) throw new TypeError("query is required for autocomplete requests");
    params.set("query", canonicalQuery.query);
    appendOptional(params, "facet_kind", canonicalQuery.facetKind);
    params.set("page_size", String(canonicalQuery.pageSize));
  }

  params.set("client_request_id", clientRequestId);
  params.set("client_query_key", clientQueryKey);
  const query = Object.freeze(Object.fromEntries(params));
  return Object.freeze({
    method: "GET",
    route,
    path,
    url: `${path}?${params}`,
    query,
    clientRequestId,
    clientQueryKey,
    queryKey: clientQueryKey,
    canonicalQuery: Object.freeze({ ...canonicalQuery }),
    canonicalJson: canonicalQueryJson(canonicalQuery),
  });
}
