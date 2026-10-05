import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
    activateSharedCategoryNavigationFilter,
    appendSharedCategoryTree,
    buildSharedCategoryTree,
    getCharacterItemKey,
    getSharedCategoryPaths,
    getSharedCodexDirectoryLevels,
    hasSharedCategoryFilters,
    isSharedCategoryFilter,
    getSharedPromptSyncMessage,
    getSharedPromptSyncStats,
    itemMatchesCategoryFilters,
    loadMergedPromptItems,
    makeSharedChildFilterKey,
    makeSharedParentFilterKey,
    makeSharedPathFilterKey,
    mergeCharacterPromptItems,
    mergePromptItems,
    normalizeSharedCategoryNavigationFilters,
    pruneSharedCategoryFilters,
    removeSharedCategoryFilters,
    refreshMergedPromptItems,
} from "../js/anima_shared_prompt_data.js";


const localItem = {
    id: "local-1",
    name: "Wave",
    tags: "waving, smile",
};
const exactDuplicate = {
    id: "shared-duplicate",
    name: "挥手",
    tags: " waving , smile ",
    shared: true,
};
const sameNameDifferentPrompt = {
    id: "shared-name-collision",
    name: "Wave",
    tags: "hand up, looking at viewer",
    shared: true,
};
const uniqueSharedItem = {
    id: "shared-unique",
    name: "Running",
    tags: "running, motion lines",
    shared: true,
    categories: ["WeiLin / 成人动作"],
    shared_category_paths: [{
        levels: ["WeiLin / 成人动作", "体位", "后入", "背身位"],
        parent: "WeiLin / 成人动作",
        source: "背身位",
        source_full: "测试/后入／背身位",
    }],
};
const sourceDirectorySharedItem = {
    id: "shared-source-directory",
    name: "Source directory pose",
    tags: "source directory pose",
    shared: true,
    shared_category_paths: [{
        levels: ["WeiLin / 成人互动", "体位", "后入", "背身位"],
        parent: "WeiLin / 成人互动",
        source: "背身位",
        source_full: "所长色色NovelAI个人法典(上)/后入/背后位",
    }],
};

assert.deepEqual(
    getSharedCodexDirectoryLevels(
        "所长色色NovelAI个人法典(上)/后入/背后位",
    ),
    ["WeiLin / 后入", "背后位"],
);
assert.deepEqual(
    getSharedCodexDirectoryLevels(
        "所长色色NovelAI个人法典(上)/口交（类口交／颜射）",
    ),
    ["WeiLin / 口交（类口交／颜射）"],
);
assert.deepEqual(getSharedCodexDirectoryLevels("默认/角色"), []);
assert.deepEqual(
    getSharedCategoryPaths(sourceDirectorySharedItem)[0].levels,
    ["WeiLin / 后入", "背后位"],
);

const merged = mergePromptItems(
    [localItem],
    [exactDuplicate, sameNameDifferentPrompt, uniqueSharedItem],
);

assert.deepEqual(
    merged.map(item => item.id),
    ["local-1", "shared-name-collision", "shared-unique"],
);
assert.equal(merged[0], localItem);

const mergedCharacters = mergeCharacterPromptItems(
    [{ name: "test hero", copyright: "local", post_count: 10 }],
    [{
        name: "Test Hero",
        name_zh: "test hero",
        trigger: "test_hero, silver hair",
        tags: "test_hero, silver hair",
        preview: "/prompt_selector/preview/hero.png?v=2",
        shared: true,
    }],
);
assert.equal(mergedCharacters.length, 1);
assert.equal(mergedCharacters[0].name, "test hero");
assert.equal(mergedCharacters[0].trigger, "test_hero, silver hair");
assert.equal(mergedCharacters[0].shared, true);

const sameNameSharedCharacters = mergeCharacterPromptItems([], [
    {
        id: "weilin:character:same-a",
        name: "同名角色",
        tags: "same_name_variant_a",
        shared: true,
    },
    {
        id: "weilin:character:same-b",
        name: "同名角色",
        tags: "same_name_variant_b",
        shared: true,
    },
]);
assert.equal(sameNameSharedCharacters.length, 2);
assert.deepEqual(
    sameNameSharedCharacters.map(item => item.tags),
    ["same_name_variant_a", "same_name_variant_b"],
);
assert.notEqual(
    getCharacterItemKey(sameNameSharedCharacters[0]),
    getCharacterItemKey(sameNameSharedCharacters[1]),
);

const tree = buildSharedCategoryTree(merged);
assert.deepEqual(tree, [{
    name: "WeiLin / 成人动作",
    label: "成人动作",
    count: 1,
    children: [{
        name: "体位",
        label: "体位",
        count: 1,
        children: [{
            name: "后入",
            label: "后入",
            count: 1,
            children: [{
                name: "背身位",
                label: "背身位",
                count: 1,
                children: [],
            }],
        }],
    }],
}]);

assert.equal(
    itemMatchesCategoryFilters(
        uniqueSharedItem,
        new Set([makeSharedParentFilterKey("WeiLin / 成人动作")]),
    ),
    true,
);

const mixedSourceFilters = new Set([
    "Dress & Gown",
    makeSharedPathFilterKey(["WeiLin / 成人动作", "体位"]),
]);
assert.equal(hasSharedCategoryFilters(mixedSourceFilters), true);
assert.equal(
    isSharedCategoryFilter(
        makeSharedPathFilterKey(["WeiLin / 成人动作", "体位"]),
    ),
    true,
);
assert.equal(removeSharedCategoryFilters(mixedSourceFilters), true);
assert.deepEqual([...mixedSourceFilters], ["Dress & Gown"]);

const navigationFilters = new Set([
    "Dress & Gown",
    makeSharedPathFilterKey(["WeiLin / 成人动作", "体位"]),
    makeSharedPathFilterKey(["WeiLin / 成人动作", "体位", "后入"]),
]);
assert.equal(normalizeSharedCategoryNavigationFilters(navigationFilters), true);
assert.deepEqual(
    [...navigationFilters],
    [makeSharedPathFilterKey(["WeiLin / 成人动作", "体位", "后入"])],
);
const nextNavigationFilter = makeSharedPathFilterKey([
    "WeiLin / 成人动作",
    "体位",
    "后入",
    "背身位",
]);
assert.equal(
    activateSharedCategoryNavigationFilter(
        navigationFilters,
        nextNavigationFilter,
    ),
    true,
);
assert.deepEqual([...navigationFilters], [nextNavigationFilter]);
assert.equal(
    activateSharedCategoryNavigationFilter(
        navigationFilters,
        nextNavigationFilter,
    ),
    false,
);
const localOnlyNavigationFilters = new Set(["Dress & Gown", "Uniform & Suit"]);
assert.equal(
    normalizeSharedCategoryNavigationFilters(localOnlyNavigationFilters),
    false,
);
assert.deepEqual(
    [...localOnlyNavigationFilters],
    ["Dress & Gown", "Uniform & Suit"],
);
const legacyParentNavigationFilters = new Set([
    "Dress & Gown",
    makeSharedParentFilterKey("WeiLin / 成人动作"),
]);
assert.equal(
    normalizeSharedCategoryNavigationFilters(
        legacyParentNavigationFilters,
        [uniqueSharedItem],
    ),
    true,
);
assert.deepEqual(
    [...legacyParentNavigationFilters],
    [makeSharedPathFilterKey(["WeiLin / 成人动作"])],
);
const legacyChildNavigationFilters = new Set([
    makeSharedChildFilterKey("WeiLin / 成人动作", "背身位"),
]);
assert.equal(
    normalizeSharedCategoryNavigationFilters(
        legacyChildNavigationFilters,
        [uniqueSharedItem],
    ),
    true,
);
assert.deepEqual(
    [...legacyChildNavigationFilters],
    [nextNavigationFilter],
);
assert.equal(
    itemMatchesCategoryFilters(
        uniqueSharedItem,
        new Set([makeSharedChildFilterKey("WeiLin / 成人动作", "背身位")]),
    ),
    true,
);

const filtersToPrune = new Set([
    makeSharedPathFilterKey(["WeiLin / 成人动作", "体位", "后入"]),
    makeSharedPathFilterKey(["WeiLin / 成人动作", "已删除路径"]),
]);
assert.equal(pruneSharedCategoryFilters([uniqueSharedItem], filtersToPrune), true);
assert.deepEqual(
    [...filtersToPrune],
    [makeSharedPathFilterKey(["WeiLin / 成人动作", "体位", "后入"])],
);
assert.equal(
    itemMatchesCategoryFilters(
        uniqueSharedItem,
        new Set([makeSharedChildFilterKey("WeiLin / 成人动作", "正身位")]),
    ),
    false,
);
assert.equal(
    itemMatchesCategoryFilters(
        uniqueSharedItem,
        new Set([makeSharedPathFilterKey(["WeiLin / 成人动作", "体位"])]),
    ),
    true,
);
assert.equal(
    itemMatchesCategoryFilters(
        uniqueSharedItem,
        new Set([makeSharedPathFilterKey(["WeiLin / 成人动作", "束缚"])]),
    ),
    false,
);

globalThis.localStorage = {
    values: new Map(),
    getItem(key) {
        return this.values.get(key) ?? null;
    },
    setItem(key, value) {
        this.values.set(key, String(value));
    },
};
globalThis.document = {
    createElement(tag) {
        return {
            tag,
            children: [],
            dataset: {},
            attributes: {},
            style: { cssText: "" },
            appendChild(child) {
                this.children.push(child);
                return child;
            },
            setAttribute(name, value) {
                this.attributes[name] = String(value);
            },
        };
    },
};
const sidebar = document.createElement("aside");
const renderedNavigationFilters = new Set();
let renderedNavigationChanges = 0;
appendSharedCategoryTree({
    sidebar,
    items: [uniqueSharedItem],
    selectedFilters: renderedNavigationFilters,
    rowClass: "test-row",
    storageKey: "shared-tree-test",
    onFilterChange() {
        renderedNavigationChanges += 1;
    },
});
const renderedGroup = sidebar.children[1];
const renderedRootRow = renderedGroup.children[0];
const renderedChildren = renderedGroup.children[1];
assert.match(renderedRootRow.className, /test-row/);
assert.equal(renderedRootRow.attributes.role, "button");
assert.equal(renderedRootRow.attributes["aria-pressed"], "false");
assert.equal(renderedRootRow.children[0].children[0].tag, "button");
assert.equal(
    JSON.stringify(sidebar).includes('"tag":"input"'),
    false,
);
assert.match(renderedChildren.style.cssText, /^display:flex;/);
const renderedNestedGroup = renderedChildren.children[0];
const renderedNestedChildren = renderedNestedGroup.children[1];
assert.match(renderedNestedChildren.style.cssText, /^display:none;/);
renderedRootRow.onclick();
assert.deepEqual(
    [...renderedNavigationFilters],
    [makeSharedPathFilterKey(["WeiLin / 成人动作"])],
);
assert.equal(renderedNavigationChanges, 1);

const selectedSidebar = document.createElement("aside");
appendSharedCategoryTree({
    sidebar: selectedSidebar,
    items: [uniqueSharedItem],
    selectedFilters: renderedNavigationFilters,
    rowClass: "test-row",
    storageKey: "shared-tree-test-selected",
    onFilterChange() {},
});
const selectedRootRow = selectedSidebar.children[1].children[0];
assert.match(selectedRootRow.className, /\bactive\b/);
assert.equal(selectedRootRow.attributes["aria-pressed"], "true");

const deepSelectedSidebar = document.createElement("aside");
appendSharedCategoryTree({
    sidebar: deepSelectedSidebar,
    items: [uniqueSharedItem],
    selectedFilters: new Set([nextNavigationFilter]),
    rowClass: "test-row",
    storageKey: "shared-tree-test-deep-selected",
    onFilterChange() {},
});
const deepRootGroup = deepSelectedSidebar.children[1];
const deepLevelOneGroup = deepRootGroup.children[1].children[0];
const deepLevelTwoGroup = deepLevelOneGroup.children[1].children[0];
const deepLeafGroup = deepLevelTwoGroup.children[1].children[0];
assert.match(deepRootGroup.children[1].style.cssText, /^display:flex;/);
assert.match(deepLevelOneGroup.children[1].style.cssText, /^display:flex;/);
assert.match(deepLevelTwoGroup.children[1].style.cssText, /^display:flex;/);
assert.match(deepLeafGroup.children[0].className, /\bactive\b/);

globalThis.window = {};
const sharedResponses = [
    {
        items: [
            { id: "weilin:pose:a", tags: "pose a", shared: true },
            { id: "weilin:pose:b", tags: "pose b", shared: true },
        ],
        enabled: true,
        source_category_count: 200,
        mapped_source_categories: 198,
        audited_source_categories: 200,
        unmapped_category_count: 0,
        pending_prompt_count: 0,
        quarantined_prompt_count: 472,
        taxonomy_source_matches: true,
    },
    {
        items: [
            { id: "weilin:pose:b", tags: "pose b changed", shared: true },
            { id: "weilin:pose:c", tags: "pose c", shared: true },
        ],
        enabled: true,
        source_category_count: 200,
        mapped_source_categories: 198,
        audited_source_categories: 200,
        unmapped_category_count: 0,
        pending_prompt_count: 0,
        quarantined_prompt_count: 472,
        taxonomy_source_matches: true,
    },
];
globalThis.fetch = async () => ({
    ok: true,
    async json() {
        return sharedResponses.shift();
    },
});
await loadMergedPromptItems("pose", []);
await refreshMergedPromptItems("pose", []);
assert.deepEqual(getSharedPromptSyncStats("pose").changes, {
    added: 1,
    updated: 1,
    removed: 1,
    unchanged: 0,
    baseline: false,
});
assert.match(
    getSharedPromptSyncMessage("pose", "动作 Tags"),
    /新增 1 \/ 更新 1 \/ 删除 1.*分类审计 200\/200.*未映射 0.*待复核 0.*安全隔离 472 条/,
);

const clothingSelectorSource = await readFile(
    new URL("../js/anima_clothing_selector.js", import.meta.url),
    "utf8",
);
assert.match(clothingSelectorSource, /WeiLin 共享服装 Tags/);
assert.match(clothingSelectorSource, /activeFilters\.collection === "weilin" && !item\?\.shared/);
assert.match(clothingSelectorSource, /clearedIncompatibleTraits/);
assert.match(clothingSelectorSource, /activeFilters\.traits\.clear\(\)/);
assert.match(clothingSelectorSource, /hasSharedCategoryFilters/);
assert.match(clothingSelectorSource, /else\s*\{\s*removeSharedCategoryFilters\(activeFilters\.categories\)/);
assert.match(clothingSelectorSource, /subEl\.innerText = sourceLabel \? `WeiLin · \$\{sourceLabel\}` : "WeiLin"/);

for (const selectorFile of [
    "anima_pose_selector.js",
    "anima_background_selector.js",
    "anima_clothing_selector.js",
    "anima_character_selector.js",
]) {
    const selectorSource = await readFile(
        new URL(`../js/${selectorFile}`, import.meta.url),
        "utf8",
    );
    assert.match(selectorSource, /同步 WeiLin/);
    assert.match(selectorSource, /refreshMergedPromptItems/);
}

for (const [selectorFile, rowClass] of Object.entries({
    "anima_pose_selector.js": "anima-pose-sidebar-item",
    "anima_background_selector.js": "anima-background-sidebar-item",
    "anima_clothing_selector.js": "anima-clothing-sidebar-item",
    "anima_character_selector.js": "sidebar-item",
})) {
    const selectorSource = await readFile(
        new URL(`../js/${selectorFile}`, import.meta.url),
        "utf8",
    );
    assert.match(
        selectorSource,
        new RegExp(`rowClass:\\s*"${rowClass}"`),
    );
    assert.match(selectorSource, /normalizeSharedCategoryNavigationFilters/);
}

console.log("anima_shared_prompt_data tests passed");
