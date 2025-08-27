/**
 * @typedef {{ status: "success",
 *   options: string[],
 *   mapping: Record<string,string>,
 *   meta: Record<string,{ placeholders: string[] }>,
 *   extras: Array<{ label: string, text?: string, header?: boolean }>,
 *   files: { prompts: string, extras: string|null }
 * }} PresetsResponseSuccess
 *
 * @typedef {{ status: "error", message?: string }} PresetsResponseError
 *
 * @returns {Promise<PresetsResponseSuccess | PresetsResponseError>}
 */
export async function fetchPresets() {
  const r = await fetch("/olm/api/joycaption/prompts");
  return r.json();
}

/** @returns {Promise<{status:string, cache_info?:string, message?:string, cached_models_count?:number}>} */
export async function getCacheStatus() {
  const r = await fetch("/olm/api/joycaption/cache_status");
  return r.json();
}

/** @returns {Promise<{status:string, message?:string, previous_cache?:string}>} */
export async function clearCache() {
  const r = await fetch("/olm/api/joycaption/clear_cache", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return r.json();
}
