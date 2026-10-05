import process from "node:process";
import { buildGalleryRequest } from "../js/danbooru_gallery/v53/gallery_api.js";

const baseUrl = String(process.argv[2] || "").replace(/\/+$/, "");
const mode = String(process.argv[3] || "fixture").toLowerCase();
const requestedSites = String(process.argv[4] || "danbooru,gelbooru,yandere,civitai")
  .split(",")
  .map((value) => value.trim().toLowerCase())
  .filter(Boolean);
const requestTimeoutMs = Number(process.env.DANBOORU_GALLERY_PROBE_TIMEOUT_MS || 30000);

const phase4CharacterTranslations = Object.freeze({
  "kei_(blue_archive)": "凯伊（蔚蓝档案）",
  "kei_(robot)_(blue_archive)": "凯伊（机器人）（蔚蓝档案）",
  "kei_(student)_(blue_archive)": "凯伊（学生）（蔚蓝档案）",
  "kasane_teto_(utau)": "重音Teto（UTAU）",
  "dan_heng_(imbibitor_lunae)_(honkai:_star_rail)": "丹恒·饮月（崩坏：星穹铁道）",
  "nyaan_(gundam_gquuuuuux)": "尼娅安（机动战士Gundam GQuuuuuuX）",
});

if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(baseUrl)) {
  throw new Error("api_probe only accepts an explicit 127.0.0.1 HTTP origin");
}
if (!new Set(["fixture", "live"]).has(mode)) throw new Error("mode must be fixture or live");
if (!Number.isInteger(requestTimeoutMs) || requestTimeoutMs < 50 || requestTimeoutMs > 120000) {
  throw new Error("DANBOORU_GALLERY_PROBE_TIMEOUT_MS must be an integer between 50 and 120000");
}

async function jsonRequest(path, {
  scenario = "success",
  method = "GET",
  jsonBody = null,
} = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    const headers = { "X-Gallery-Test-Scenario": scenario };
    if (jsonBody !== null) headers["Content-Type"] = "application/json";
    const response = await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      body: jsonBody === null ? undefined : JSON.stringify(jsonBody),
      signal: controller.signal,
    });
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    return { response, payload, timedOut: false };
  } catch (error) {
    if (!controller.signal.aborted) throw error;
    return {
      response: { ok: false, status: 0, headers: new Headers() },
      payload: {
        error: {
          code: "probe_timeout",
          httpStatus: 0,
          retryable: true,
          message: `probe request exceeded ${requestTimeoutMs}ms`,
        },
      },
      timedOut: true,
    };
  } finally {
    clearTimeout(timeout);
  }
}

function providersFrom(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.providers)) return payload.providers;
  if (Array.isArray(payload?.items)) return payload.items;
  if (payload?.source && payload?.features) return [payload];
  return [];
}

function supportedRanking(provider) {
  return (provider?.features?.ranking || []).find((item) => item?.state === "supported");
}

function supportedFacet(provider) {
  return (provider?.features?.facets || []).find(
    (item) => ["supported", "degraded"].includes(item?.state) && item?.listable !== false,
  );
}

function supportedSearch(provider) {
  return (provider?.features?.views || []).find(
    (item) => item?.id === "search" && ["supported", "degraded"].includes(item?.state),
  );
}

function resultRow(site, operation, state, details = {}) {
  return { site, operation, state, ...details };
}

function isLiveEnvironmentBlock(response, error) {
  const code = String(error?.code || "");
  if (["auth_required", "auth_invalid", "forbidden"].includes(code)) {
    return [401, 403].includes(response.status);
  }
  if (code === "rate_limited") return response.status === 429;
  if (code === "network_unavailable") {
    return [502, 503, 504].includes(response.status);
  }
  if (code === "pagination_limit") return response.status === 429;
  return false;
}

async function executeBuilt(site, operation, request) {
  const { response, payload } = await jsonRequest(request.url);
  const responseError = payload?.error || null;
  if (!response.ok || responseError) {
    const environmentBlocked = mode === "live" && isLiveEnvironmentBlock(response, responseError);
    const row = resultRow(site, operation, environmentBlocked ? "ENV_BLOCKED" : "FAIL", {
      httpStatus: response.status,
      errorCode: responseError?.code || "invalid_response",
    });
    return { row, payload: null };
  }
  if (!Array.isArray(payload?.items) || payload?.error !== null) {
    return {
      row: resultRow(site, operation, "FAIL", {
        httpStatus: response.status,
        errorCode: "invalid_success_envelope",
      }),
      payload: null,
    };
  }
  if (payload.clientRequestId !== request.clientRequestId || payload.queryKey !== request.clientQueryKey) {
    return {
      row: resultRow(site, operation, "FAIL", {
        httpStatus: response.status,
        errorCode: "request_identity_mismatch",
      }),
      payload: null,
    };
  }
  return {
    row: resultRow(site, operation, "PASS", {
      httpStatus: response.status,
      itemCount: payload.items.length,
      hasNext: payload?.pageInfo?.hasNext ?? null,
      fidelity: payload?.ranking?.fidelity ?? null,
    }),
    payload,
  };
}

async function verifyFixtureSecondPage(site, requestInput, firstResult) {
  if (firstResult.row.state !== "PASS" || !firstResult.payload) {
    return resultRow(site, "pagination_next_cursor", "FAIL", {
      errorCode: "first_page_failed",
    });
  }
  const firstPageInfo = firstResult.payload.pageInfo;
  const nextCursor = firstPageInfo?.nextCursor;
  if (firstPageInfo?.hasNext !== true || typeof nextCursor !== "string" || !nextCursor) {
    return resultRow(site, "pagination_next_cursor", "FAIL", {
      errorCode: "next_cursor_missing",
    });
  }

  const secondRequest = await buildGalleryRequest({ ...requestInput, cursor: nextCursor });
  const secondResult = await executeBuilt(site, "pagination_next_cursor", secondRequest);
  if (secondResult.row.state !== "PASS" || !secondResult.payload) return secondResult.row;

  const secondPageInfo = secondResult.payload.pageInfo;
  const pageKeysDiffer = typeof firstPageInfo?.pageKey === "string"
    && firstPageInfo.pageKey.length > 0
    && typeof secondPageInfo?.pageKey === "string"
    && secondPageInfo.pageKey.length > 0
    && secondPageInfo.pageKey !== firstPageInfo.pageKey;
  const passed = secondPageInfo?.hasNext === false
    && secondPageInfo?.nextCursor === null
    && pageKeysDiffer;
  return resultRow(site, "pagination_next_cursor", passed ? "PASS" : "FAIL", {
    httpStatus: secondResult.row.httpStatus,
    itemCount: secondResult.row.itemCount,
    hasNext: secondPageInfo?.hasNext ?? null,
    pageKeysDiffer,
    errorCode: passed ? null : "invalid_second_page",
  });
}

async function verifyDistinctSecondPage(site, operation, requestInput, firstResult) {
  if (firstResult.row.state !== "PASS" || !firstResult.payload) {
    return resultRow(site, operation, "FAIL", { errorCode: "first_page_failed" });
  }
  const nextCursor = firstResult.payload?.pageInfo?.nextCursor;
  if (firstResult.payload?.pageInfo?.hasNext !== true || typeof nextCursor !== "string" || !nextCursor) {
    return resultRow(site, operation, "FAIL", { errorCode: "next_cursor_missing" });
  }

  const secondRequest = await buildGalleryRequest({ ...requestInput, cursor: nextCursor });
  const secondResult = await executeBuilt(site, operation, secondRequest);
  if (secondResult.row.state !== "PASS" || !secondResult.payload) return secondResult.row;

  const identity = (item) => String(item?.id ?? item?.post_id ?? item?.file_url ?? "");
  const firstIds = new Set(firstResult.payload.items.map(identity).filter(Boolean));
  const secondIds = secondResult.payload.items.map(identity).filter(Boolean);
  const overlapCount = secondIds.filter((id) => firstIds.has(id)).length;
  const pageKeysDiffer = firstResult.payload?.pageInfo?.pageKey
    !== secondResult.payload?.pageInfo?.pageKey;
  const passed = secondIds.length > 0 && overlapCount === 0 && pageKeysDiffer;
  return resultRow(site, operation, passed ? "PASS" : "FAIL", {
    httpStatus: secondResult.row.httpStatus,
    itemCount: secondIds.length,
    overlapCount,
    pageKeysDiffer,
    errorCode: passed ? null : "second_page_not_distinct",
  });
}

const report = {
  schemaVersion: 1,
  mode,
  origin: baseUrl,
  requestTimeoutMs,
  generatedAt: new Date().toISOString(),
  results: [],
};

const health = await jsonRequest("/system_stats");
report.results.push(resultRow("comfyui", "system_stats", health.response.ok ? "PASS" : "FAIL", {
  httpStatus: health.response.status,
  errorCode: health.timedOut ? "probe_timeout" : null,
}));
const objectInfo = await jsonRequest("/object_info/DanbooruGalleryNode");
report.results.push(resultRow("plugin", "node_registration", objectInfo.response.ok && objectInfo.payload?.DanbooruGalleryNode ? "PASS" : "FAIL", {
  httpStatus: objectInfo.response.status,
  errorCode: objectInfo.timedOut ? "probe_timeout" : null,
}));

const providersResponse = await jsonRequest("/danbooru_gallery/v2/providers");
const providers = providersFrom(providersResponse.payload);
report.results.push(resultRow("plugin", "providers", providersResponse.response.ok && providers.length ? "PASS" : "FAIL", {
  httpStatus: providersResponse.response.status,
  providerCount: providers.length,
  errorCode: providersResponse.timedOut ? "probe_timeout" : null,
}));

const artistTranslation = await jsonRequest(
  "/danbooru_gallery/translate_tag?tag=alphonse_mucha",
);
const artistMasked = artistTranslation.response.ok
  && artistTranslation.payload?.success === true
  && artistTranslation.payload?.tag === "alphonse_mucha"
  && artistTranslation.payload?.translation === null;
report.results.push(resultRow("plugin", "artist_translation_mask", artistMasked ? "PASS" : "FAIL", {
  httpStatus: artistTranslation.response.status,
  errorCode: artistTranslation.timedOut ? "probe_timeout" : (artistMasked ? null : "artist_translation_visible"),
}));

const translationBatch = await jsonRequest("/danbooru_gallery/translate_tags_batch", {
  method: "POST",
  jsonBody: { tags: ["alphonse_mucha", "hatsune_miku", "high_res"] },
});
const translations = translationBatch.payload?.translations || {};
const characterTranslation = typeof translations.hatsune_miku === "string"
  ? translations.hatsune_miku.trim()
  : "";
const aliasTranslation = typeof translations.high_res === "string"
  ? translations.high_res.trim()
  : "";
const batchSafe = translationBatch.response.ok
  && translationBatch.payload?.success === true
  && !Object.prototype.hasOwnProperty.call(translations, "alphonse_mucha")
  && characterTranslation.length > 0
  && aliasTranslation.length > 0;
report.results.push(resultRow("plugin", "translation_batch_categories", batchSafe ? "PASS" : "FAIL", {
  httpStatus: translationBatch.response.status,
  artistOmitted: !Object.prototype.hasOwnProperty.call(translations, "alphonse_mucha"),
  characterTranslated: characterTranslation.length > 0,
  aliasTranslated: aliasTranslation.length > 0,
  errorCode: translationBatch.timedOut ? "probe_timeout" : (batchSafe ? null : "translation_batch_invalid"),
}));

const phase4Tags = Object.keys(phase4CharacterTranslations);
const phase4Batch = await jsonRequest("/danbooru_gallery/translate_tags_batch", {
  method: "POST",
  jsonBody: { tags: phase4Tags },
});
const phase4BatchValues = phase4Batch.payload?.translations || {};
const phase4BatchMatched = phase4Tags.filter(
  (tag) => phase4BatchValues[tag] === phase4CharacterTranslations[tag],
);
const phase4BatchSafe = phase4Batch.response.ok
  && phase4Batch.payload?.success === true
  && phase4BatchMatched.length === phase4Tags.length;
report.results.push(resultRow(
  "plugin",
  "phase4_character_translation_batch",
  phase4BatchSafe ? "PASS" : "FAIL",
  {
    httpStatus: phase4Batch.response.status,
    expectedCount: phase4Tags.length,
    matchedCount: phase4BatchMatched.length,
    errorCode: phase4Batch.timedOut
      ? "probe_timeout"
      : (phase4BatchSafe ? null : "phase4_translation_mismatch"),
  },
));

const phase4AutocompleteResponses = await Promise.all(phase4Tags.map((tag) => jsonRequest(
  `/danbooru_gallery/autocomplete_with_translation?query=${encodeURIComponent(tag)}&source=danbooru&limit=20`,
)));
const phase4AutocompleteMatched = phase4Tags.filter((tag, index) => {
  const response = phase4AutocompleteResponses[index];
  return response.response.ok
    && Array.isArray(response.payload)
    && response.payload.some(
      (item) => item?.name === tag && item?.translation === phase4CharacterTranslations[tag],
    );
});
const phase4AutocompleteSafe = phase4AutocompleteMatched.length === phase4Tags.length;
report.results.push(resultRow(
  "plugin",
  "phase4_character_autocomplete",
  phase4AutocompleteSafe ? "PASS" : "FAIL",
  {
    expectedCount: phase4Tags.length,
    matchedCount: phase4AutocompleteMatched.length,
    errorCode: phase4AutocompleteResponses.some((response) => response.timedOut)
      ? "probe_timeout"
      : (phase4AutocompleteSafe ? null : "phase4_autocomplete_mismatch"),
  },
));

const phase4ReverseCases = [
  { query: "凯伊", tag: "kei_(blue_archive)" },
  { query: "丹恒", tag: "dan_heng_(imbibitor_lunae)_(honkai:_star_rail)" },
  { query: "尼娅安", tag: "nyaan_(gundam_gquuuuuux)" },
  { query: "重音Teto", tag: "kasane_teto_(utau)" },
];
const phase4ReverseResponses = await Promise.all(phase4ReverseCases.map(({ query }) => jsonRequest(
  `/danbooru_gallery/search_chinese?query=${encodeURIComponent(query)}&limit=20`,
)));
const phase4ReverseMatched = phase4ReverseCases.filter(({ tag }, index) => {
  const response = phase4ReverseResponses[index];
  const items = Array.isArray(response.payload?.results) ? response.payload.results : [];
  return response.response.ok
    && response.payload?.success === true
    && items.some(
      (item) => (item?.tag === tag || item?.english === tag)
        && Number(item?.match_score || 0) >= 5,
    );
});
const phase4ReverseSafe = phase4ReverseMatched.length === phase4ReverseCases.length;
report.results.push(resultRow(
  "plugin",
  "phase4_character_reverse_lookup",
  phase4ReverseSafe ? "PASS" : "FAIL",
  {
    expectedCount: phase4ReverseCases.length,
    matchedCount: phase4ReverseMatched.length,
    errorCode: phase4ReverseResponses.some((response) => response.timedOut)
      ? "probe_timeout"
      : (phase4ReverseSafe ? null : "phase4_reverse_lookup_mismatch"),
  },
));

const aliasAutocomplete = await jsonRequest(
  "/danbooru_gallery/autocomplete_with_translation?query=high_res&source=danbooru&limit=5",
);
const aliasItem = Array.isArray(aliasAutocomplete.payload)
  ? aliasAutocomplete.payload.find((item) => item?.name === "highres")
  : null;
const aliasResolved = aliasAutocomplete.response.ok
  && aliasItem?.matched_alias === "high_res"
  && typeof aliasItem?.translation === "string"
  && aliasItem.translation.trim().length > 0;
report.results.push(resultRow("plugin", "official_alias_resolution", aliasResolved ? "PASS" : "FAIL", {
  httpStatus: aliasAutocomplete.response.status,
  canonicalTag: aliasItem?.name || null,
  matchedAlias: aliasItem?.matched_alias || null,
  errorCode: aliasAutocomplete.timedOut ? "probe_timeout" : (aliasResolved ? null : "alias_not_resolved"),
}));

const chineseReverse = characterTranslation
  ? await jsonRequest(`/danbooru_gallery/search_chinese?query=${encodeURIComponent(characterTranslation)}&limit=20`)
  : { response: { ok: false, status: 0 }, payload: null, timedOut: false };
const reverseItems = Array.isArray(chineseReverse.payload?.results)
  ? chineseReverse.payload.results
  : [];
const reverseResolved = chineseReverse.response.ok
  && chineseReverse.payload?.success === true
  && reverseItems.some((item) => item?.tag === "hatsune_miku" || item?.english === "hatsune_miku");
report.results.push(resultRow("plugin", "chinese_reverse_lookup", reverseResolved ? "PASS" : "FAIL", {
  httpStatus: chineseReverse.response.status,
  resultCount: reverseItems.length,
  errorCode: chineseReverse.timedOut ? "probe_timeout" : (reverseResolved ? null : "reverse_lookup_missing"),
}));

const catalogCategories = await jsonRequest("/danbooru_gallery/tag_catalog/categories");
const catalogGroups = Array.isArray(catalogCategories.payload?.groups)
  ? catalogCategories.payload.groups
  : [];
const catalogSubgroups = catalogGroups.flatMap((group) => group?.subgroups || []);
const artistBucketsHidden = !catalogSubgroups.some((subgroup) => [77, 493].includes(Number(subgroup?.id)));
const catalogCategoriesSafe = catalogCategories.response.ok
  && catalogCategories.payload?.success === true
  && catalogCategories.payload?.available === true
  && catalogGroups.length > 0
  && catalogCategories.payload?.preservation?.raw_text_unchanged === true
  && catalogCategories.payload?.preservation?.prompt_text_truncated === false
  && artistBucketsHidden;
report.results.push(resultRow("plugin", "weilin_catalog_categories", catalogCategoriesSafe ? "PASS" : "FAIL", {
  httpStatus: catalogCategories.response.status,
  groupCount: catalogGroups.length,
  artistBucketsHidden,
  errorCode: catalogCategories.timedOut ? "probe_timeout" : (catalogCategoriesSafe ? null : "catalog_categories_invalid"),
}));

const catalogAtomic = await jsonRequest(
  "/danbooru_gallery/tag_catalog/search?query=blue%20eyes&kind=atomic_tag&page=1&limit=5",
);
const atomicItems = Array.isArray(catalogAtomic.payload?.items) ? catalogAtomic.payload.items : [];
const blueEyes = atomicItems.find((item) => item?.gallery_tag === "blue_eyes");
const catalogAtomicSafe = catalogAtomic.response.ok
  && catalogAtomic.payload?.success === true
  && blueEyes?.kind === "atomic_tag"
  && blueEyes?.site_filterable === true;
report.results.push(resultRow("plugin", "weilin_atomic_gallery_link", catalogAtomicSafe ? "PASS" : "FAIL", {
  httpStatus: catalogAtomic.response.status,
  itemCount: atomicItems.length,
  galleryTag: blueEyes?.gallery_tag || null,
  errorCode: catalogAtomic.timedOut ? "probe_timeout" : (catalogAtomicSafe ? null : "catalog_atomic_link_missing"),
}));

const catalogLong = await jsonRequest(
  "/danbooru_gallery/tag_catalog/search?query=cinematic%20lighting&kind=prompt_phrase&page=1&limit=3",
);
const longItems = Array.isArray(catalogLong.payload?.items) ? catalogLong.payload.items : [];
const longItem = longItems.find((item) => item?.kind === "prompt_phrase" && item?.t_uuid);
const catalogItem = longItem
  ? await jsonRequest(`/danbooru_gallery/tag_catalog/item?t_uuid=${encodeURIComponent(longItem.t_uuid)}`)
  : { response: { ok: false, status: 0 }, payload: null, timedOut: false };
const longRaw = typeof longItem?.raw_text === "string" ? longItem.raw_text : "";
const fullRaw = typeof catalogItem.payload?.item?.raw_text === "string"
  ? catalogItem.payload.item.raw_text
  : "";
const longPreserved = catalogLong.response.ok
  && catalogLong.payload?.success === true
  && longItem?.site_filterable === false
  && longItem?.gallery_tag === null
  && longRaw.length > 120
  && catalogItem.response.ok
  && catalogItem.payload?.success === true
  && fullRaw === longRaw
  && catalogItem.payload?.preservation?.prompt_text_truncated === false;
report.results.push(resultRow("plugin", "weilin_long_prompt_roundtrip", longPreserved ? "PASS" : "FAIL", {
  httpStatus: catalogLong.response.status,
  itemHttpStatus: catalogItem.response.status,
  rawLength: longRaw.length,
  exactRoundtrip: fullRaw === longRaw,
  errorCode: catalogLong.timedOut || catalogItem.timedOut ? "probe_timeout" : (longPreserved ? null : "catalog_long_prompt_changed"),
}));

const catalogPageOne = await jsonRequest(
  "/danbooru_gallery/tag_catalog/search?group_id=1&kind=all&page=1&limit=2",
);
const catalogNextCursor = catalogPageOne.payload?.next_cursor;
const catalogPageTwo = typeof catalogNextCursor === "string" && catalogNextCursor
  ? await jsonRequest(
    `/danbooru_gallery/tag_catalog/search?group_id=1&kind=all&page=2&limit=2&cursor=${encodeURIComponent(catalogNextCursor)}`,
  )
  : { response: { ok: false, status: 0 }, payload: null, timedOut: false };
const firstIds = new Set((catalogPageOne.payload?.items || []).map((item) => item?.id));
const secondIds = (catalogPageTwo.payload?.items || []).map((item) => item?.id);
const catalogPaginationSafe = catalogPageOne.response.ok
  && catalogPageTwo.response.ok
  && catalogPageOne.payload?.success === true
  && catalogPageTwo.payload?.success === true
  && catalogPageOne.payload?.page === 1
  && catalogPageTwo.payload?.page === 2
  && catalogPageOne.payload?.has_more === true
  && typeof catalogNextCursor === "string"
  && catalogNextCursor.length > 0
  && secondIds.length > 0
  && secondIds.every((id) => !firstIds.has(id));
report.results.push(resultRow("plugin", "weilin_catalog_pagination", catalogPaginationSafe ? "PASS" : "FAIL", {
  httpStatus: catalogPageTwo.response.status,
  firstCount: firstIds.size,
  secondCount: secondIds.length,
  nextCursor: catalogNextCursor || null,
  errorCode: catalogPageOne.timedOut || catalogPageTwo.timedOut ? "probe_timeout" : (catalogPaginationSafe ? null : "catalog_pagination_invalid"),
}));

if (mode === "fixture") {
  const semanticsRequest = await buildGalleryRequest({
    route: "browse",
    source: "danbooru",
    view: "latest",
    pageSize: 2,
  });
  const empty = await jsonRequest(semanticsRequest.url, { scenario: "empty" });
  const emptyPass = empty.response.status === 200
    && Array.isArray(empty.payload?.items)
    && empty.payload.items.length === 0
    && empty.payload?.error === null
    && empty.payload?.clientRequestId === semanticsRequest.clientRequestId
    && empty.payload?.queryKey === semanticsRequest.clientQueryKey;
  report.results.push(resultRow("plugin", "empty_result_semantics", emptyPass ? "PASS" : "FAIL", {
    httpStatus: empty.response.status,
    errorCode: empty.payload?.error?.code || null,
  }));

  const rateLimited = await jsonRequest(semanticsRequest.url, { scenario: "429" });
  const rateLimitPass = rateLimited.response.status === 429
    && Array.isArray(rateLimited.payload?.items)
    && rateLimited.payload.items.length === 0
    && rateLimited.payload?.error?.code === "rate_limited"
    && rateLimited.payload?.clientRequestId === semanticsRequest.clientRequestId
    && rateLimited.payload?.queryKey === semanticsRequest.clientQueryKey
    && rateLimited.response.headers.get("retry-after") === "2";
  report.results.push(resultRow("plugin", "rate_limit_envelope", rateLimitPass ? "PASS" : "FAIL", {
    httpStatus: rateLimited.response.status,
    errorCode: rateLimited.payload?.error?.code || null,
    retryAfter: rateLimited.response.headers.get("retry-after"),
  }));
}

for (const site of requestedSites) {
  const provider = providers.find((item) => item?.source === site);
  if (!provider) {
    report.results.push(resultRow(site, "capabilities", "FAIL", { errorCode: "provider_missing" }));
    continue;
  }
  report.results.push(resultRow(site, "capabilities", "PASS", {
    availability: provider?.availability?.state || "unknown",
  }));

  const latestInput = {
    route: "browse",
    source: site,
    view: "latest",
    pageSize: 4,
  };
  const latestRequest = await buildGalleryRequest(latestInput);
  const latestResult = await executeBuilt(site, "latest", latestRequest);
  report.results.push(latestResult.row);
  if (mode === "fixture") {
    report.results.push(await verifyFixtureSecondPage(site, latestInput, latestResult));
  }

  if (site === "civitai") {
    if (supportedSearch(provider)) {
      const searchInput = {
        route: "browse",
        source: site,
        view: "search",
        query: "portrait",
        pageSize: 4,
      };
      const searchResult = await executeBuilt(
        site,
        "search",
        await buildGalleryRequest(searchInput),
      );
      report.results.push(searchResult.row);
      report.results.push(await verifyDistinctSecondPage(
        site,
        "search_next_cursor",
        searchInput,
        searchResult,
      ));
    } else {
      report.results.push(resultRow(site, "search", "ENV_BLOCKED", {
        errorCode: "search_authorization_not_configured",
      }));
    }
  }

  const ranking = supportedRanking(provider);
  if (ranking) {
    const period = ranking.periods?.[0];
    const rankingRequest = await buildGalleryRequest({
      route: "browse",
      source: site,
      view: "ranking",
      metric: ranking.metric,
      period,
      anchorDate: ranking.supportsAnchorDate ? new Date().toISOString().slice(0, 10) : null,
      pageSize: 4,
      allowApprox: ranking.fidelity === "client_approx",
    });
    report.results.push((await executeBuilt(site, "ranking", rankingRequest)).row);
  } else {
    report.results.push(resultRow(site, "ranking", "ENV_BLOCKED", { errorCode: "no_supported_ranking" }));
  }

  const facet = supportedFacet(provider);
  if (facet) {
    const facetRequest = await buildGalleryRequest({
      route: "facets",
      source: site,
      facetKind: facet.kind,
      pageSize: 4,
    });
    const facetResult = await executeBuilt(site, "facets", facetRequest);
    report.results.push(facetResult.row);
    const firstFacet = facetResult.payload?.items?.[0];
    if (firstFacet && facet.filterable !== false) {
      const categoryRequest = await buildGalleryRequest({
        route: "browse",
        source: site,
        view: "category",
        facetKind: facet.kind,
        facetId: String(firstFacet.id),
        pageSize: 4,
      });
      report.results.push((await executeBuilt(site, "category", categoryRequest)).row);
    }
  } else {
    report.results.push(resultRow(site, "facets", "ENV_BLOCKED", { errorCode: "no_listable_facet" }));
  }
}

process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
const hardFailures = report.results.filter((item) => item.state === "FAIL");
if (hardFailures.length) process.exitCode = 1;
