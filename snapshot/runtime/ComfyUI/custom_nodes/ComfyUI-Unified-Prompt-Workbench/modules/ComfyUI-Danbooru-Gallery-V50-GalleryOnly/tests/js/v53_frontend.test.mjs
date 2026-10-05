import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  GalleryStore,
  RequestLaneCoordinator,
  availableFallbackViews,
  buildGalleryRequest,
  canonicalQueryJson,
  createCanonicalQueryKey,
  createMinimalProviderCapabilities,
  galleryNewUiEnabled,
  loadGalleryFeatureFlags,
  normalizeGalleryFeatureFlags,
  sha256Hex,
  sha256HexPortable,
} from "../../js/danbooru_gallery/v53/index.js";

const UUIDS = Object.freeze([
  "00000000-0000-4000-8000-000000000001",
  "00000000-0000-4000-8000-000000000002",
  "00000000-0000-4000-8000-000000000003",
  "00000000-0000-4000-8000-000000000004",
]);

const KEY_A = "a".repeat(64);
const KEY_B = "b".repeat(64);
const KEY_C = "c".repeat(64);

const RANK_QUERY = Object.freeze({
  source: "civitai",
  view: "ranking",
  query: "portrait",
  metric: "reactions",
  period: "week",
  anchorDate: null,
  facetKind: "model",
  facetId: 42,
  safetyProfile: "general",
  pageSize: 20,
  allowApprox: false,
});

test("feature gate requires both backend V2 and the new UI", async () => {
  const payload = {
    featureFlags: {
      v2_routes_enabled: true,
      gallery_new_ui_enabled: true,
      provider_danbooru_v2: true,
    },
  };
  const flags = normalizeGalleryFeatureFlags(payload);
  assert.equal(galleryNewUiEnabled(flags), true);
  assert.equal(galleryNewUiEnabled({ ...flags, gallery_new_ui_enabled: false }), false);

  let request = null;
  const loaded = await loadGalleryFeatureFlags({
    fetchImpl: async (url, options) => {
      request = { url, options };
      return { ok: true, status: 200, json: async () => payload };
    },
  });
  assert.equal(loaded.provider_danbooru_v2, true);
  assert.equal(request.url, "/danbooru_gallery/features");
  assert.equal(request.options.cache, "no-store");

  assert.throws(
    () => normalizeGalleryFeatureFlags({ featureFlags: { v2_routes_enabled: true } }),
    /gallery_new_ui_enabled/,
  );
});

test("canonical query JSON fixes field defaults/order and SHA-256 is stable", async () => {
  const expectedJson = "{\"allowApprox\":false,\"anchorDate\":null,\"facetId\":\"42\",\"facetKind\":\"model\",\"metric\":\"reactions\",\"pageSize\":20,\"period\":\"week\",\"query\":\"portrait\",\"safetyProfile\":\"general\",\"source\":\"civitai\",\"view\":\"ranking\"}";
  assert.equal(canonicalQueryJson(RANK_QUERY), expectedJson);
  assert.equal(
    await createCanonicalQueryKey(RANK_QUERY),
    "00394aa2212a1cbadaa55b1a6e1c9a381563a88358724a02a05c2c2a09d601eb",
  );
  assert.equal(
    await createCanonicalQueryKey({ cursor: "ignored", forceRefresh: true, ...RANK_QUERY }),
    await createCanonicalQueryKey({ ...RANK_QUERY, clientRequestId: UUIDS[0] }),
  );
  assert.notEqual(
    await createCanonicalQueryKey(RANK_QUERY),
    await createCanonicalQueryKey({ ...RANK_QUERY, period: "month" }),
  );
});

test("portable SHA-256 matches the standard vector without SubtleCrypto", async () => {
  const expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
  assert.equal(sha256HexPortable("abc"), expected);
  assert.equal(await sha256Hex("abc", { subtle: null }), expected);
});

test("V2 browse request contains the full normalized contract", async () => {
  const request = await buildGalleryRequest({
    route: "browse",
    ...RANK_QUERY,
    anchorDate: "2026-07-19",
    cursor: "opaque+/cursor==",
    allowApprox: true,
  }, { idFactory: () => UUIDS[0] });
  assert.equal(request.method, "GET");
  assert.equal(request.path, "/danbooru_gallery/v2/browse");
  assert.deepEqual(request.query, {
    source: "civitai",
    view: "ranking",
    query: "portrait",
    metric: "reactions",
    period: "week",
    anchor_date: "2026-07-19",
    facet_kind: "model",
    facet_id: "42",
    safety_profile: "general",
    page_size: "20",
    cursor: "opaque+/cursor==",
    allow_approx: "true",
    client_request_id: UUIDS[0],
    client_query_key: request.clientQueryKey,
  });
  assert.match(request.clientQueryKey, /^[0-9a-f]{64}$/);
  assert.equal(new URL(request.url, "http://localhost").searchParams.get("cursor"), "opaque+/cursor==");
});

test("browser query keys match the Python browse/facet golden vectors", async () => {
  const browse = await buildGalleryRequest({
    route: "browse",
    source: "civitai",
    view: "ranking",
    query: null,
    metric: "reactions",
    period: "week",
    anchorDate: null,
    facetKind: "model",
    facetId: "42",
    safetyProfile: "general",
    pageSize: 20,
    allowApprox: false,
  }, { idFactory: () => UUIDS[0] });
  assert.equal(
    browse.clientQueryKey,
    "5736adc97e7115d8e08edc8c4b284cf2e9cbe7133835b6250f952d5f6f11674f",
  );

  const facets = await buildGalleryRequest({
    route: "facets",
    source: "civitai",
    facetKind: "model_taxonomy",
    query: "portrait",
    pageSize: 20,
  }, { idFactory: () => UUIDS[1] });
  assert.equal(
    facets.clientQueryKey,
    "af293ed181baa698fcef415682db1b4bb9d96310be69849aa241042360286d05",
  );
  assert.equal(
    facets.canonicalJson,
    "{\"allowApprox\":false,\"anchorDate\":null,\"facetId\":null,\"facetKind\":\"model_taxonomy\",\"metric\":null,\"pageSize\":20,\"period\":null,\"query\":\"portrait\",\"safetyProfile\":null,\"source\":\"civitai\",\"view\":\"category\"}",
  );
});

test("V2 facets/providers builders enforce route-specific parameters", async () => {
  const facetRequest = await buildGalleryRequest({
    route: "facets",
    source: "danbooru",
    facetKind: "character",
    query: "hakurei",
    pageSize: 40,
    cursor: "facet-next",
  }, { idFactory: () => UUIDS[1] });
  assert.deepEqual(facetRequest.query, {
    source: "danbooru",
    facet_kind: "character",
    query: "hakurei",
    page_size: "40",
    cursor: "facet-next",
    client_request_id: UUIDS[1],
    client_query_key: facetRequest.clientQueryKey,
  });
  await assert.rejects(
    buildGalleryRequest({ route: "facets", source: "danbooru" }, { idFactory: () => UUIDS[0] }),
    /facetKind is required/,
  );
  const providers = await buildGalleryRequest({ route: "providers", source: "civitai" });
  assert.equal(providers.url, "/danbooru_gallery/v2/providers?source=civitai");
  assert.equal(providers.clientQueryKey, null);
});

test("four request lanes abort and commit independently", () => {
  let idIndex = 0;
  const coordinator = new RequestLaneCoordinator({ idFactory: () => UUIDS[idIndex++] });
  const browse1 = coordinator.begin("browse", KEY_A, { status: "initialLoading" });
  const facets = coordinator.begin("facets", KEY_B);
  assert.equal(browse1.signal.aborted, false);
  assert.equal(facets.signal.aborted, false);

  const browse2 = coordinator.begin("browse", KEY_C, { status: "loadingMore" });
  assert.equal(browse1.signal.aborted, true);
  assert.equal(facets.signal.aborted, false);
  assert.equal(coordinator.canCommit(browse1), false);
  assert.equal(coordinator.canCommit(browse2, {
    clientRequestId: "00000000-0000-4000-8000-000000000099",
    queryKey: KEY_C,
  }), false);

  let committed = null;
  assert.equal(coordinator.commit(browse2, {
    clientRequestId: browse2.clientRequestId,
    queryKey: KEY_C,
    items: [{ id: 1 }],
  }, (response) => { committed = response.items; }), true);
  assert.deepEqual(committed, [{ id: 1 }]);
  assert.equal(coordinator.snapshot().browse.active, false);
  assert.equal(coordinator.snapshot().facets.active, true);

  const autocomplete = coordinator.begin("autocomplete", KEY_A);
  assert.equal(coordinator.abortAll("source_changed"), 2);
  assert.equal(facets.signal.aborted, true);
  assert.equal(autocomplete.signal.aborted, true);
});

test("capabilities lane uses its closure token when the endpoint has no echoed identity", () => {
  const coordinator = new RequestLaneCoordinator({ idFactory: () => UUIDS[0] });
  const token = coordinator.begin("capabilities", KEY_A);
  let schemaVersion = null;
  assert.equal(coordinator.commit(token, { schemaVersion: 1, source: "danbooru" }, (response) => {
    schemaVersion = response.schemaVersion;
  }), true);
  assert.equal(schemaVersion, 1);

  const autocomplete = coordinator.begin("autocomplete", KEY_B, { clientRequestId: UUIDS[1] });
  assert.equal(coordinator.canCommit(autocomplete, { items: [] }), false);
});

test("per-source drafts and cursor sessions restore without cross-site state", () => {
  const store = new GalleryStore({ maxSessionsPerSource: 3 });
  store.updateDraft("danbooru", { terms: "reimu", mode: "search" });
  store.updateDraft("civitai", { terms: "", mode: "favorites" });
  assert.equal(store.getDraft("danbooru").terms, "reimu");
  assert.equal(store.getDraft("civitai").terms, "");

  store.activateSession("danbooru", KEY_A);
  assert.equal(store.forwardAction("danbooru", KEY_A).cursor, null);
  store.recordPage("danbooru", KEY_A, {
    requestCursor: null,
    nextCursor: "next-1",
    pageKey: "page-1",
    items: [{ id: 1 }, { id: 2 }],
    scrollTop: 120,
  });
  assert.deepEqual(store.forwardAction("danbooru", KEY_A), { type: "request", cursor: "next-1" });
  store.recordPage("danbooru", KEY_A, {
    requestCursor: "next-1",
    nextCursor: null,
    pageKey: "page-2",
    items: [{ id: 2 }, { id: 3 }],
    scrollTop: 640,
  });
  assert.deepEqual(store.getSession("danbooru", KEY_A).items.map((item) => item.id), [1, 2, 3]);
  assert.equal(store.recordPage("danbooru", KEY_A, {
    requestCursor: "next-1",
    nextCursor: null,
    pageKey: "page-2-duplicate",
    items: [{ id: 3 }],
  }).added, false);
  assert.equal(store.goBack("danbooru", KEY_A).pageIndex, 0);
  assert.equal(store.getDraft("danbooru").viewMemory.scrollTop, 120);
  assert.equal(store.goForward("danbooru", KEY_A).pageIndex, 1);

  store.activateSession("civitai", KEY_B);
  store.recordPage("civitai", KEY_B, {
    requestCursor: null,
    nextCursor: "c-next",
    pageKey: "c-page-1",
    items: [{ id: 99, sourceSite: "civitai" }],
    scrollTop: 44,
  });
  store.setActiveSource("danbooru");
  assert.equal(store.activeSession.queryKey, KEY_A);
  assert.equal(store.getDraft("danbooru").viewMemory.scrollTop, 640);
  assert.equal(store.getSession("civitai", KEY_B).items[0].id, 99);
});

test("session LRU is bounded independently for each source", () => {
  const store = new GalleryStore({ maxSessionsPerSource: 2 });
  store.activateSession("danbooru", KEY_A);
  store.activateSession("danbooru", KEY_B);
  store.getSession("danbooru", KEY_A);
  store.activateSession("danbooru", KEY_C);
  assert.equal(store.hasSession("danbooru", KEY_A), true);
  assert.equal(store.hasSession("danbooru", KEY_B), false);
  assert.equal(store.hasSession("danbooru", KEY_C), true);
  store.activateSession("civitai", KEY_B);
  assert.equal(store.hasSession("civitai", KEY_B), true);
});

test("minimal capability fallback never leaks booru search into public Civitai", () => {
  for (const source of ["danbooru", "gelbooru", "yandere"]) {
    assert.deepEqual(availableFallbackViews(createMinimalProviderCapabilities(source)), ["latest", "search"]);
  }
  const civitai = createMinimalProviderCapabilities("civitai");
  assert.deepEqual(availableFallbackViews(civitai), ["latest", "favorites"]);
  assert.equal(civitai.features.views.find((view) => view.id === "search").reasonCode, "public_free_text_unavailable");
  assert.equal(civitai.features.ranking.length, 0);
  assert.equal(civitai.features.facets.length, 0);
});

test("main node wires V53 navigation/state without legacy query injection", () => {
  const source = readFileSync(
    new URL("../../js/danbooru_gallery/danbooru_gallery.js", import.meta.url),
    "utf8",
  );
  for (const marker of [
    '"gallery_state"',
    '"gallery-primary-tabs"',
    '"gallery-browse-tabs"',
    '"gallery-ranking-metric"',
    '"gallery-ranking-period"',
    '"gallery-facet-kind"',
    '"gallery-facet-value"',
    '"gallery-status"',
    'galleryRequests.abortAll("source_changed")',
    'return fetchAndRenderV53(reset)',
    'loadGalleryFeatureFlags()',
    'v53UiReady && isV53ProviderEnabled()',
  ]) assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));

  assert.match(source, /entry\.listable !== false && entry\.filterable !== false/);
  assert.match(source, /v53SearchActive/);
  assert.match(source, /searchQuery = `mode:loose \$\{searchQuery\}`/);
  assert.equal(source.includes("\u0008"), false, "gallery source contains a backspace control character");

  const rankingHandler = source.match(/rankingButton\.addEventListener\("click", \(\) => \{([\s\S]*?)\n\s*\}\);/);
  assert.ok(rankingHandler, "ranking click handler is present");
  assert.match(rankingHandler[1], /setV53Mode\("ranking"\)/);
  assert.doesNotMatch(rankingHandler[1], /order:rank|searchInput\.value\s*=/);
  assert.doesNotMatch(source, /saveToLocalStorage\(['"](?:source|searchValue|ratingValues|ratingValue|filterData)['"]/);
});

test("WeiLin catalog UI preserves prompt text and gates site filtering", () => {
  const source = readFileSync(
    new URL("../../js/danbooru_gallery/danbooru_gallery.js", import.meta.url),
    "utf8",
  );
  for (const marker of [
    '"gallery-tag-catalog-button"',
    '"tag-catalog-dialog"',
    '"tag-catalog-search"',
    '"tag-catalog-results"',
    '"/danbooru_gallery/tag_catalog/categories"',
    '/danbooru_gallery/tag_catalog/search?${params}',
    'item.site_filterable && item.gallery_tag',
    'item.copy_text ?? item.raw_text',
    'textContent: item.raw_text || ""',
    'params.set("cursor", currentCursor)',
    'nextCursor = typeof data.next_cursor === "string"',
    'cursorHistory[page] = nextCursor',
    'currentCursor = cursorHistory[page - 1] || null',
  ]) assert.ok(source.includes(marker), `missing WeiLin catalog marker: ${marker}`);

  assert.doesNotMatch(source, /innerHTML\s*:\s*item\.(?:raw_text|raw_desc|copy_text)/);
  assert.match(source, /长提示词逐字保留，只复制、不发送给 Booru API/);
});
