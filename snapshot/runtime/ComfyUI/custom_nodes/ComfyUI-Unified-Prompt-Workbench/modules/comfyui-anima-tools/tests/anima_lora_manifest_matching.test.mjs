import assert from "node:assert/strict";
import fs from "node:fs";


const source = fs.readFileSync(
    new URL("../js/anima_lora_selector.js", import.meta.url),
    "utf8",
);

function extractFunction(name) {
    const start = source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `${name} is missing`);
    const bodyStart = source.indexOf("{", start);
    let depth = 0;
    for (let index = bodyStart; index < source.length; index += 1) {
        if (source[index] === "{") depth += 1;
        if (source[index] === "}") depth -= 1;
        if (depth === 0) return source.slice(start, index + 1);
    }
    throw new Error(`Unable to extract ${name}`);
}

function extractAsyncFunction(name) {
    return `async ${extractFunction(name)}`;
}

const matchingFactory = new Function(
    "loraManifestItems",
    "loraManifestByVersionId",
    "loraManifestByModelId",
    "activeBaseModelProfile",
    "LORA_BASE_MODEL_PROFILES",
    [
        extractFunction("getLoraBaseModelProfile"),
        extractFunction("normalizeLoraPath"),
        extractFunction("getLoraBasename"),
        extractFunction("findLocalManifestItem"),
        "return { normalizeLoraPath, findLocalManifestItem };",
    ].join("\n"),
);

const localItem = {
    filename: "character/example/renamed-local.safetensors",
    source: "custom",
    base_model_profile: "anima",
    meta_summary: { version_id: 456, model_id: 123 },
};
const kreaItem = {
    filename: "character/example/renamed-local.safetensors",
    source: "custom",
    base_model_profile: "krea2",
    meta_summary: { version_id: 456, model_id: 123 },
};
const basenameItem = {
    filename: "style/SharedName.safetensors",
    source: "custom",
    base_model_profile: "anima",
    meta_summary: {},
};
const helpers = matchingFactory(
    [localItem, kreaItem, basenameItem],
    new Map([
        ["anima:456", localItem],
        ["krea2:456", kreaItem],
    ]),
    new Map([
        ["anima:123", localItem],
        ["krea2:123", kreaItem],
    ]),
    { id: "anima", label: "Anima", apiBaseModel: "Anima" },
    {
        anima: { id: "anima", label: "Anima", apiBaseModel: "Anima" },
        krea2: { id: "krea2", label: "Krea 2", apiBaseModel: "Krea 2" },
    },
);

assert.equal(
    helpers.findLocalManifestItem("different-remote-name.safetensors", 456, 123),
    localItem,
);
assert.equal(
    helpers.findLocalManifestItem("different-remote-name.safetensors", 456, 123, "krea2"),
    kreaItem,
);
assert.equal(
    helpers.findLocalManifestItem("sharedname.safetensors"),
    basenameItem,
);
assert.equal(
    helpers.normalizeLoraPath("Character\\Example\\Model.safetensors"),
    "character/example/model.safetensors",
);
assert.equal(
    helpers.findLocalManifestItem("missing.safetensors", 999, 998),
    null,
);

const profileFactory = new Function(
    "LORA_BASE_MODEL_PROFILES",
    `${extractFunction("getLoraBaseModelProfile")}; return getLoraBaseModelProfile;`,
);
const getProfile = profileFactory({
    anima: { id: "anima", label: "Anima", apiBaseModel: "Anima" },
    krea2: { id: "krea2", label: "Krea 2", apiBaseModel: "Krea 2" },
});
assert.equal(getProfile("Krea 2").apiBaseModel, "Krea 2");
assert.equal(getProfile("krea-2").id, "krea2");
assert.equal(getProfile("unknown").id, "anima");

const downloadFolderFactory = new Function(
    "LORA_BASE_MODEL_PROFILES",
    "DOWNLOAD_SUBFOLDER_STORAGE_KEY_PREFIX",
    "LEGACY_DOWNLOAD_SUBFOLDER_STORAGE_KEY",
    [
        extractFunction("getLoraBaseModelProfile"),
        extractFunction("getLoraDownloadSubfolderStorageKey"),
        extractFunction("readLoraDownloadSubfolder"),
        extractFunction("writeLoraDownloadSubfolder"),
        "return { readLoraDownloadSubfolder, writeLoraDownloadSubfolder };",
    ].join("\n"),
);
const downloadFolderHelpers = downloadFolderFactory(
    {
        anima: { id: "anima", label: "Anima", apiBaseModel: "Anima" },
        krea2: { id: "krea2", label: "Krea 2", apiBaseModel: "Krea 2" },
    },
    "anima-lora-download-subfolder",
    "anima-lora-download-subfolder",
);
const folderStorageValues = new Map([
    ["anima-lora-download-subfolder", "legacy/anima"],
]);
const folderStorage = {
    getItem: key => folderStorageValues.has(key) ? folderStorageValues.get(key) : null,
    setItem: (key, value) => folderStorageValues.set(key, value),
};
assert.equal(
    downloadFolderHelpers.readLoraDownloadSubfolder(folderStorage, "anima"),
    "legacy/anima",
);
assert.equal(
    downloadFolderHelpers.readLoraDownloadSubfolder(folderStorage, "krea2"),
    "",
);
downloadFolderHelpers.writeLoraDownloadSubfolder(folderStorage, "anima", "characters/anima");
downloadFolderHelpers.writeLoraDownloadSubfolder(folderStorage, "krea2", "characters/krea2");
assert.equal(
    downloadFolderHelpers.readLoraDownloadSubfolder(folderStorage, "anima"),
    "characters/anima",
);
assert.equal(
    downloadFolderHelpers.readLoraDownloadSubfolder(folderStorage, "krea2"),
    "characters/krea2",
);

const downloadTrackingFactory = new Function(
    [
        extractFunction("partitionLoraDownloadJobs"),
        extractFunction("collectUnseenTerminalDownloadJobs"),
        "return { partitionLoraDownloadJobs, collectUnseenTerminalDownloadJobs };",
    ].join("\n"),
);
const downloadTracking = downloadTrackingFactory();
const pendingJob = { status: "pending", progress: 0, total: 10 };
const downloadingJob = { status: "downloading", progress: 5, total: 10 };
const completedJob = { status: "completed", save_path: "cloth/model.safetensors" };
const failedJob = { status: "failed", error: "network" };
const downloadSnapshot = downloadTracking.partitionLoraDownloadJobs({
    101: pendingJob,
    102: downloadingJob,
    103: completedJob,
    104: failedJob,
    105: { status: "unknown" },
});
assert.deepEqual(downloadSnapshot.active, {
    101: pendingJob,
    102: downloadingJob,
});
assert.deepEqual(downloadSnapshot.terminal, [
    ["103", completedJob],
    ["104", failedJob],
]);

const handledTerminalIds = new Set(["103"]);
assert.deepEqual(
    downloadTracking.collectUnseenTerminalDownloadJobs(
        downloadSnapshot.terminal,
        handledTerminalIds,
    ),
    [["104", failedJob]],
);
assert.deepEqual(
    downloadTracking.collectUnseenTerminalDownloadJobs(
        downloadSnapshot.terminal,
        handledTerminalIds,
    ),
    [],
);

assert.match(source, /addLoraToNode\(\s*resolvedLocalFilename,/);
assert.match(source, /subfolder:\s*downloadSubfolder/);
assert.match(source, /base_model:\s*activeBaseModelProfile\.apiBaseModel/);
assert.match(source, /krea2_lora_dir:\s*krea2DirVal/);
assert.match(source, /base_model:\s*activeBaseModelProfile\.apiBaseModel/);
assert.match(source, /switchBaseModelProfile\(profile\.id\)/);
assert.match(source, /_base_model_profile:\s*activeBaseModelProfile\.id/);
assert.match(source, /Download folder · \$\{activeBaseModelProfile\.label\}/);

assert.match(source, /fetchFastestCivitaiSearch\(searchUrl,\s*forceRefresh\)/);
assert.match(source, /const CIVITAI_SEARCH_CACHE_VERSION = "v9-preview-original-fallback"/);
assert.match(source, /const CIVITAI_PRIMARY_ORIGIN = "https:\/\/civitai\.red"/);
assert.match(source, /const CIVITAI_FALLBACK_ORIGIN = "https:\/\/civitai\.com"/);
assert.match(source, /_search_source:\s*source/);
assert.match(source, /titleText\.href = `\$\{CIVITAI_PRIMARY_ORIGIN\}\/models\/\$\{modelId\}`/);
assert.match(source, /· 来源：\$\{label\}/);
assert.doesNotMatch(source, /fetch\(`https:\/\/civitai\.com\/api\/v1\/models/);

const civitaiRoutingFactory = new Function(
    "CIVITAI_PRIMARY_ORIGIN",
    "CIVITAI_FALLBACK_ORIGIN",
    "fetch",
    `${extractAsyncFunction("fetchCivitaiJsonWithFallback")}; return fetchCivitaiJsonWithFallback;`,
);
const redOnlyCalls = [];
const fetchRedFirst = civitaiRoutingFactory(
    "https://civitai.red",
    "https://civitai.com",
    async url => {
        redOnlyCalls.push(url);
        return {
            ok: true,
            status: 200,
            json: async () => ({ provider: "red" }),
        };
    },
);
assert.deepEqual(
    await fetchRedFirst("/api/v1/models?limit=1"),
    {
        data: { provider: "red" },
        source: "direct-browser-red",
        sourceHost: "civitai.red",
        sourceRole: "primary",
    },
);
assert.deepEqual(redOnlyCalls, ["https://civitai.red/api/v1/models?limit=1"]);

const fallbackCalls = [];
const fetchBlueFallback = civitaiRoutingFactory(
    "https://civitai.red",
    "https://civitai.com",
    async url => {
        fallbackCalls.push(url);
        if (url.startsWith("https://civitai.red")) {
            return { ok: false, status: 503, json: async () => ({}) };
        }
        return {
            ok: true,
            status: 200,
            json: async () => ({ provider: "blue" }),
        };
    },
);
assert.deepEqual(
    await fetchBlueFallback("/api/v1/models/123"),
    {
        data: { provider: "blue" },
        source: "direct-browser-blue-fallback",
        sourceHost: "civitai.com",
        sourceRole: "fallback",
    },
);
assert.deepEqual(fallbackCalls, [
    "https://civitai.red/api/v1/models/123",
    "https://civitai.com/api/v1/models/123",
]);

const timeoutCalls = [];
const fetchAfterRedTimeout = civitaiRoutingFactory(
    "https://civitai.red",
    "https://civitai.com",
    (url, options) => {
        timeoutCalls.push(url);
        if (url.startsWith("https://civitai.red")) {
            return new Promise((_resolve, reject) => {
                options.signal.addEventListener("abort", () => {
                    const error = new Error("timed out");
                    error.name = "AbortError";
                    reject(error);
                }, { once: true });
            });
        }
        return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ provider: "blue-after-timeout" }),
        });
    },
);
assert.deepEqual(
    await fetchAfterRedTimeout("/api/v1/models/456", { timeoutMs: 5 }),
    {
        data: { provider: "blue-after-timeout" },
        source: "direct-browser-blue-fallback",
        sourceHost: "civitai.com",
        sourceRole: "fallback",
    },
);
assert.deepEqual(timeoutCalls, [
    "https://civitai.red/api/v1/models/456",
    "https://civitai.com/api/v1/models/456",
]);

const backendSearchFactory = new Function(
    "fetch",
    `${extractAsyncFunction("fetchBackendCivitaiSearch")}; return fetchBackendCivitaiSearch;`,
);
const backendSearchCalls = [];
const fetchBackendAfterCacheMiss = backendSearchFactory(async url => {
    backendSearchCalls.push(url);
    if (url.includes("cache_only=1")) {
        return {
            ok: true,
            status: 204,
            json: async () => {
                throw new Error("A 204 response must not be parsed as JSON");
            },
        };
    }
    return {
        ok: true,
        status: 200,
        json: async () => ({ items: [{ id: 42 }], metadata: { source: "meili" } }),
    };
});
assert.deepEqual(
    await fetchBackendAfterCacheMiss(
        "/anima-tools/lora/search?category=character&cursor=page-2",
    ),
    { items: [{ id: 42 }], metadata: { source: "meili" } },
);
assert.deepEqual(backendSearchCalls, [
    "/anima-tools/lora/search?category=character&cursor=page-2&cache_only=1",
    "/anima-tools/lora/search?category=character&cursor=page-2",
]);

const modelDetailFactory = new Function(
    "fetchCivitaiJsonWithFallback",
    "fetch",
    `${extractAsyncFunction("fetchFastestCivitaiModelDetail")}; return fetchFastestCivitaiModelDetail;`,
);
const modelDetailCalls = [];
const fetchModelDetailAfterCacheMiss = modelDetailFactory(
    async () => {
        throw new Error("direct providers unavailable");
    },
    async url => {
        modelDetailCalls.push(url);
        if (url.includes("cache_only=1")) {
            return {
                ok: true,
                status: 204,
                json: async () => {
                    throw new Error("A 204 response must not be parsed as JSON");
                },
            };
        }
        return {
            ok: true,
            status: 200,
            json: async () => ({ success: true, model: { id: 99 } }),
        };
    },
);
assert.deepEqual(await fetchModelDetailAfterCacheMiss(99), { id: 99 });
assert.deepEqual(modelDetailCalls, [
    "/anima-tools/lora/model-detail?id=99&cache_only=1",
    "/anima-tools/lora/model-detail?id=99",
]);

const sourceLabelFactory = new Function(
    `${extractFunction("appendCivitaiSearchSource")}; return appendCivitaiSearchSource;`,
);
const appendSearchSource = sourceLabelFactory();
assert.equal(
    appendSearchSource("Found 40 models.", {
        source: "public-api",
        sourceHost: "civitai.red",
        sourceRole: "primary",
    }),
    "Found 40 models. · 来源：Civitai.red",
);
assert.equal(
    appendSearchSource("Found 40 models.", {
        source: "public-api",
        sourceHost: "civitai.com",
        sourceRole: "fallback",
    }),
    "Found 40 models. · 来源：Civitai.com 兜底",
);
assert.equal(
    appendSearchSource("Found 40 models.", { source: "public-api" }),
    "Found 40 models. · 来源：后端 API",
);
assert.equal(
    appendSearchSource("Found 40 models.", { source: "meili" }),
    "Found 40 models. · 来源：Civitai 共享索引",
);

const categoryFactory = new Function(
    [
        extractFunction("getLoraSearchCategory"),
        extractFunction("sanitizeLoraSearchResultForCategory"),
        "return { getLoraSearchCategory, sanitizeLoraSearchResultForCategory };",
    ].join("\n"),
);
const {
    getLoraSearchCategory: getSearchCategory,
    sanitizeLoraSearchResultForCategory: sanitizeSearchResult,
} = categoryFactory();
assert.equal(
    getSearchCategory("/anima-tools/lora/search?base_model=Anima&category=clothing"),
    "clothing",
);
assert.equal(
    getSearchCategory("/anima-tools/lora/search?base_model=Krea%202&category="),
    "",
);
const sanitizedCharacterResult = sanitizeSearchResult({
    items: [
        { id: 1, _category: "character" },
        { id: 2, _category: "style" },
        { id: 3 },
    ],
    metadata: { source: "public-tag-fallback" },
}, "/anima-tools/lora/search?base_model=Krea%202&category=character");
assert.deepEqual(
    sanitizedCharacterResult.items.map(item => item.id),
    [1],
);
assert.equal(
    sanitizedCharacterResult.metadata.frontendCategoryRejectedCount,
    2,
);
assert.equal(sanitizedCharacterResult.metadata.categoryStrict, true);
assert.match(source, /const category = getLoraSearchCategory\(searchUrl\)/);
assert.match(source, /if \(category\) \{\s*return sanitizeLoraSearchResultForCategory\(\s*await fetchBackendCivitaiSearch/);
assert.match(source, /await fetchDirectCivitaiSearch\(searchUrl, directController\.signal\)/);
assert.doesNotMatch(source, /firstSuccessful\(/);
assert.match(source, /getLoraBaseModelProfile\(item\.base_model\)\.id === activeBaseModelProfile\.id/);
assert.match(source, /getLoraBaseModelProfile\(l\.base_model\)\.id === localProfileId/);
assert.match(source, /fetchFastestCivitaiModelDetail\(id\)/);
assert.match(source, /model-detail\?id=\$\{encodeURIComponent\(id\)\}&cache_only=1/);
assert.match(source, /const handledTerminalDownloadTaskIds = new Set\(\)/);
assert.match(source, /requestModelDetailRender\(\)/);
assert.match(source, /detailPanel\.contains\(activeElement\)/);
assert.doesNotMatch(source, /localLoras\.includes\(filename\)/);

console.log("anima_lora_manifest_matching tests passed");
