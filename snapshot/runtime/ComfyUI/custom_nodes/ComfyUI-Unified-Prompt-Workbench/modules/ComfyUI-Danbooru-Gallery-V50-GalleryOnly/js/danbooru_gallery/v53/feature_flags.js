export const GALLERY_FEATURE_API_PATH = "/danbooru_gallery/features";

const REQUIRED_FLAGS = Object.freeze([
  "v2_routes_enabled",
  "gallery_new_ui_enabled",
]);

export function normalizeGalleryFeatureFlags(payload) {
  const flags = payload?.featureFlags;
  if (!flags || typeof flags !== "object" || Array.isArray(flags)) {
    throw new TypeError("feature response is missing featureFlags");
  }
  for (const name of REQUIRED_FLAGS) {
    if (typeof flags[name] !== "boolean") {
      throw new TypeError(`feature flag ${name} must be boolean`);
    }
  }
  return Object.freeze({ ...flags });
}

export function galleryNewUiEnabled(flags) {
  return flags?.v2_routes_enabled === true && flags?.gallery_new_ui_enabled === true;
}

export async function loadGalleryFeatureFlags({ fetchImpl = globalThis.fetch, signal } = {}) {
  if (typeof fetchImpl !== "function") throw new TypeError("fetch implementation is required");
  const response = await fetchImpl(GALLERY_FEATURE_API_PATH, {
    method: "GET",
    cache: "no-store",
    signal,
  });
  if (!response?.ok) throw new Error(`feature endpoint returned HTTP ${response?.status ?? "unknown"}`);
  return normalizeGalleryFeatureFlags(await response.json());
}

