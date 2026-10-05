import { GALLERY_SOURCES, GALLERY_VIEWS } from "./gallery_api.js";

const BOORU_SOURCES = new Set(["danbooru", "gelbooru", "yandere"]);

function viewCapability(source, id) {
  const booruEnabled = BOORU_SOURCES.has(source) && (id === "latest" || id === "search");
  const civitaiEnabled = source === "civitai" && (id === "latest" || id === "favorites");
  const supported = booruEnabled || civitaiEnabled;
  let reasonCode = null;
  if (!supported) {
    reasonCode = source === "civitai" && id === "search"
      ? "public_free_text_unavailable"
      : "capabilities_unavailable";
  }
  return {
    id,
    state: supported ? "supported" : "unsupported",
    reasonCode,
    requiresAuth: false,
    scope: id === "favorites" ? "local" : "public_api",
  };
}

function safetyKind(source) {
  if (source === "civitai") return "civitai_browsing_level";
  if (source === "yandere") return "yandere_rating";
  return "booru_four_level";
}

export function createMinimalProviderCapabilities(source, { schemaVersion = 1 } = {}) {
  const normalizedSource = String(source || "").trim().toLowerCase();
  if (!GALLERY_SOURCES.includes(normalizedSource)) {
    throw new RangeError(`unsupported gallery source: ${normalizedSource}`);
  }
  if (!Number.isSafeInteger(schemaVersion) || schemaVersion < 1) {
    throw new TypeError("schemaVersion must be a positive integer");
  }
  const enabledFilters = normalizedSource === "civitai"
    ? { latest: ["safetyProfile"], favorites: ["safetyProfile"] }
    : { latest: ["safetyProfile"], search: ["safetyProfile"] };
  return {
    schemaVersion,
    source: normalizedSource,
    features: {
      views: GALLERY_VIEWS.map((view) => viewCapability(normalizedSource, view)),
      ranking: [],
      facets: [],
      compatibleFiltersByView: enabledFilters,
      pagination: { kind: "opaque_cursor" },
      safety: { kind: safetyKind(normalizedSource) },
    },
    availability: { state: "degraded", reason: "capabilities_unavailable" },
    auth: { required: false, configured: false },
    limits: {
      maxPageSize: normalizedSource === "danbooru" || normalizedSource === "civitai" ? 200 : 100,
      publishedRate: null,
    },
  };
}

export function availableFallbackViews(capabilities) {
  const views = capabilities?.features?.views;
  if (!Array.isArray(views)) return [];
  return views.filter((view) => view?.state === "supported").map((view) => view.id);
}
