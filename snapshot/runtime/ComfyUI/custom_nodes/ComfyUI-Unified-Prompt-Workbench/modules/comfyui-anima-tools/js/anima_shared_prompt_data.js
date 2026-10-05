import {installSelectorExperience} from './anima_selector_ui.js';

const sharedPromptCache = new Map();
const sharedPromptSnapshots = new Map();
const SHARED_PARENT_FILTER_PREFIX = "shared-parent:";
const SHARED_CHILD_FILTER_PREFIX = "shared-child:";
const SHARED_PATH_FILTER_PREFIX = "shared-path:";
const SHARED_THEME_FILTER_PREFIX = "shared-theme:";
const SHARED_SUB_FILTER_PREFIX = "shared-sub:";
const SHARED_SOURCE_FILTER_PREFIX = "shared-source:";
const SHARED_CATEGORY_SEPARATOR = "\u001f";
let sharedLibraryTaxonomy;
let sharedLibraryTaxonomyRequest;
let sharedLibraryTaxonomyRequestRevision = "";
let sharedLibraryTaxonomyRequestForced = false;
let sharedLibraryTaxonomyRevision = "";

if (
    typeof window !== "undefined"
    && !window.__animaSharedPromptCacheInvalidationInstalled
) {
    window.__animaSharedPromptCacheInvalidationInstalled = true;
    window.addEventListener("anima-tools-shared-prompts-updated", () => {
        sharedPromptCache.clear();
        sharedLibraryTaxonomy = null;
        sharedLibraryTaxonomyRequest = null;
        sharedLibraryTaxonomyRevision = "";
    });
}

export async function loadSharedLibraryTaxonomy({ revision = "", force = false } = {}) {
    if (!force && sharedLibraryTaxonomy && sharedLibraryTaxonomyRevision === revision) return sharedLibraryTaxonomy;
    if (sharedLibraryTaxonomyRequest) {
        if (sharedLibraryTaxonomyRequestRevision === revision && (!force || sharedLibraryTaxonomyRequestForced)) return sharedLibraryTaxonomyRequest;
        try { await sharedLibraryTaxonomyRequest; } catch (_) { /* The caller requests a fresh revision. */ }
        return loadSharedLibraryTaxonomy({revision, force});
    }
    const request = fetch('/prompt_selector/library/index', {cache:'no-store'})
        .then(async response => {
            if (!response.ok) throw new Error(`资料库分类读取失败（HTTP ${response.status}）`);
            const index = await response.json();
            if (sharedLibraryTaxonomyRequest !== request) {
                const error = new Error('资料库分类已更新，请重新打开选择器。');
                error.code = 'STALE_SHARED_PROMPTS';
                throw error;
            }
            if (!index.semantic_classes || !index.filter_pool?.subcategory) throw new Error('资料库分类未就绪，请重试。');
            sharedLibraryTaxonomy = {
                labels:index.semantic_classes,
                subcategories:index.filter_pool.subcategory,
                values:index.filter_pool.subcategory_values || {},
            };
            sharedLibraryTaxonomyRevision = revision;
            return sharedLibraryTaxonomy;
        }).finally(() => { if (sharedLibraryTaxonomyRequest === request) sharedLibraryTaxonomyRequest = null; });
    sharedLibraryTaxonomyRequest = request;
    sharedLibraryTaxonomyRequestRevision = revision;
    sharedLibraryTaxonomyRequestForced = force;
    return request;
}

function canonicalPrompt(value) {
    return String(value || "")
        .toLowerCase()
        .replace(/\r?\n/g, " ")
        .replace(/\s+/g, " ")
        .replace(/\s*,\s*/g, ",")
        .replace(/^[\s,]+|[\s,]+$/g, "");
}

function canonicalName(value) {
    return String(value || "")
        .toLowerCase()
        .replace(/[\s_\-–—/\\]+/g, "")
        .trim();
}

// Rank display names separately from insertable text. This never rewrites a token or path.
export function getPromptSearchRank(item, query, extraAliases = []) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return 0;
    const terms = values => values.flat(Infinity)
        .filter(value => typeof value === "string" && value.trim())
        .map(value => value.trim().toLowerCase());
    const names = terms([item?.name, item?.name_zh, item?.alias, item?.aliases,
        item?.nickname, extraAliases]);
    if (names.some(name => name === q)) return 0;
    if (names.some(name => name.startsWith(q))) return 1;
    const body = terms([item?.prompt, item?.tags, item?.tags_zh, item?.trigger,
        item?.customContent, item?.description, item?.traits]);
    if ([...names, ...body].some(value => value.includes(q))) return 2;
    const source = terms([String(item?.id ?? ""), item?.copyright, item?.categories,
        item?.source_category, item?.shared_parent_category, item?.shared_source_category,
        ...(Array.isArray(item?.shared_category_paths) ? item.shared_category_paths.flatMap(path => [
            path?.levels, path?.parent, path?.source, path?.source_full,
        ]) : [])]);
    return source.some(value => value.includes(q)) ? 3 : Infinity;
}

export function rankPromptSearchResults(items, query, aliasesForItem = () => []) {
    if (!String(query || "").trim()) return items;
    return items.map((item, index) => ({ item, index,
        rank: getPromptSearchRank(item, query, aliasesForItem(item)) }))
        .sort((a, b) => a.rank - b.rank || a.index - b.index)
        .map(entry => entry.item);
}

export function createStablePromptShuffle(keyForItem) {
    const priorities = new Map();
    return items => items.map((item, index) => {
        const key = keyForItem(item) || item;
        if (!priorities.has(key)) priorities.set(key, Math.random());
        return {item, index, rank: priorities.get(key)};
    }).sort((a, b) => a.rank - b.rank || a.index - b.index).map(entry => entry.item);
}

export function getCharacterItemKey(item) {
    if (!item || typeof item !== "object") return "";
    if (item.selectorKey) return String(item.selectorKey);
    if (item.isCustom) {
        return `custom:${String(item.id || item.name || "")}`;
    }
    if (item.shared) {
        return `shared:${String(item.id || item.name || "")}`;
    }
    return `local:${String(item.id || item.name || "")}:${String(item.copyright || "")}`;
}

export function isReviewedSharedFragment(item, { random = false } = {}) {
    if (!item?.shared) return true;
    const decision = item._semantic;
    return ["reviewed", "classified"].includes(decision?.disposition)
        && decision.manual_search_eligible === true
        && decision.usage === "positive"
        && ["atomic_tag", "fragment"].includes(decision.content_type)
        && (!random || (decision.random_pool_eligible === true && decision.strict_model_pool_eligible === true));
}

export function mergePromptItems(localItems, sharedItems) {
    const merged = [];
    const seenIdentities = new Set();
    const append = item => {
        const identity = mergeIdentity(item);
        if (!identity) {
            if (item && typeof item === "object" && (item.id || item.name || item.name_zh || item.tags)) merged.push(item);
            return;
        }
        if (seenIdentities.has(identity)) return;
        merged.push(item);
        seenIdentities.add(identity);
    };
    (Array.isArray(localItems) ? localItems : []).forEach(item => append(item));
    (Array.isArray(sharedItems) ? sharedItems : []).forEach(item => append(item));
    return merged;
}

export function mergeCharacterPromptItems(localItems, sharedItems) {
    const merged = [];
    const seenIdentities = new Set();
    const append = item => {
        const identity = mergeIdentity(item);
        if (!identity) {
            if (item && typeof item === "object" && (item.id || item.name || item.name_zh || item.tags)) merged.push({ ...item });
            return;
        }
        if (seenIdentities.has(identity)) return;
        merged.push({ ...item });
        seenIdentities.add(identity);
    };
    (Array.isArray(localItems) ? localItems : []).forEach(append);
    (Array.isArray(sharedItems) ? sharedItems : []).forEach(append);
    return merged;
}

function mergeIdentity(item) {
    if (!item || typeof item !== "object") return "";
    const hasPayload = item.id || item.name || item.name_zh || item.tags
        || (Array.isArray(item.source_prompt_ids) && item.source_prompt_ids.length);
    if (!hasPayload) return "";
    const origin = String(item.source_namespace || item.origin || (item.isCustom ? "custom" : item.shared ? "shared" : "local"));
    const stableId = item.id ? `id:${String(item.id)}` : (Array.isArray(item.source_prompt_ids) && item.source_prompt_ids.length ? `source:${item.source_prompt_ids.map(String).sort().join("\u001f")}` : "");
    if (!stableId) return null;
    const compatibility = JSON.stringify(item, (_key, value) => value && typeof value === "object" && !Array.isArray(value) ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))) : value);
    return JSON.stringify([origin, stableId, compatibility]);
}

function normalizeSharedCategoryName(value) {
    return String(value || "")
        .replace(/／/g, "/")
        .replace(/\s+/g, " ")
        .trim();
}

export function getSharedCodexDirectoryLevels(sourceCategory) {
    const parts = String(sourceCategory || "")
        .split("/")
        .map(part => part.trim())
        .filter(Boolean);
    if (parts.length < 2) return [];
    const root = parts[0]
        .normalize("NFKC")
        .replace(/\s+/g, "")
        .toLowerCase();
    if (!root.includes("novelai个人法典")) return [];
    return [
        `WeiLin / ${parts[1]}`,
        ...parts.slice(2),
    ];
}

export function getSharedCategoryPaths(item) {
    if (!sharedLibraryTaxonomy || !item?.shared) return [];
    const semantic = item._semantic || {};
    const {labels, subcategories, values} = sharedLibraryTaxonomy;
    const themes = new Set(semantic.theme_ids || [semantic.primary_class, ...(semantic.alternative_classes || [])]);
    const children = Array.from(new Set(semantic.subcategories || []));
    const paths = [];
    for (const [theme, label] of Object.entries(labels)) {
        const owned = Object.keys(subcategories[theme] || {}).filter(label => children.some(child => (child === label || child.startsWith(label + '/'))
            && semantic.subcategory_owners?.[child] === theme));
        if (!themes.has(theme) && !owned.length) continue;
        const rootKey = SHARED_THEME_FILTER_PREFIX + theme;
        if (!owned.length) paths.push({levels:[label], keys:[rootKey], parent:label, source:label});
        for (const child of owned) paths.push({levels:[label, child], keys:[rootKey, SHARED_SUB_FILTER_PREFIX + (values[child] || child)],
            parent:label, source:child});
    }
    return paths;
}

export function getSharedTopicSummary(item) {
    const groups = new Map();
    const paths = getSharedCategoryPaths(item);
    const primary = SHARED_THEME_FILTER_PREFIX + item?._semantic?.primary_class;
    for (const path of [...paths.filter(path => path.keys[0] === primary), ...paths.filter(path => path.keys[0] !== primary)]) {
        const [theme, child] = path.levels;
        if (!groups.has(theme)) groups.set(theme, new Set());
        if (child) groups.get(theme).add(child);
    }
    return Array.from(groups, ([theme, children]) => theme + (children.size ? ' · ' + [...children].join('、') : ''));
}

export function makeSharedParentFilterKey(parent) {
    return `${SHARED_PARENT_FILTER_PREFIX}${normalizeSharedCategoryName(parent)}`;
}

function getSharedFilterPaths(item) {
    return (item?.shared_category_paths || []).flatMap(path => [path, ...(path.legacy_paths || []).map(levels => ({
        levels, parent:levels[0], source:levels[levels.length - 1],
    }))]);
}

export function makeSharedChildFilterKey(parent, source) {
    return `${SHARED_CHILD_FILTER_PREFIX}${normalizeSharedCategoryName(parent)}${SHARED_CATEGORY_SEPARATOR}${normalizeSharedCategoryName(source)}`;
}

export function makeSharedPathFilterKey(levels) {
    const normalizedLevels = (Array.isArray(levels) ? levels : [levels])
        .map(normalizeSharedCategoryName)
        .filter(Boolean);
    return `${SHARED_PATH_FILTER_PREFIX}${normalizedLevels.join(SHARED_CATEGORY_SEPARATOR)}`;
}

export function isSharedCategoryFilter(filter) {
    const value = String(filter || "");
    return (
        value.startsWith(SHARED_PARENT_FILTER_PREFIX)
        || value.startsWith(SHARED_CHILD_FILTER_PREFIX)
        || value.startsWith(SHARED_PATH_FILTER_PREFIX)
        || value.startsWith(SHARED_THEME_FILTER_PREFIX)
        || value.startsWith(SHARED_SUB_FILTER_PREFIX)
        || value.startsWith(SHARED_SOURCE_FILTER_PREFIX)
    );
}

export function getSharedCategoryRequestFilter(selectedFilters) {
    const filters = Array.from(selectedFilters || []).filter(isSharedCategoryFilter);
    return filters.length ? 'shared-filters:' + JSON.stringify(filters) : '';
}

function sharedSourceId(item) {
    return String(item?.source_category_id || item?.shared_category_paths?.find(path => path.source_category_id)?.source_category_id || '');
}

function sharedSubcategoryValue(item, child) {
    const owner = item?._semantic?.subcategory_owners?.[child];
    const value = sharedLibraryTaxonomy?.values[child] || child;
    return value.includes('::') && owner ? owner + '::' + child : value;
}

export function hasSharedCategoryFilters(selectedFilters) {
    if (!selectedFilters) return false;
    return Array.from(selectedFilters).some(isSharedCategoryFilter);
}

export function removeSharedCategoryFilters(selectedFilters) {
    if (!selectedFilters) return false;
    let changed = false;
    for (const filter of Array.from(selectedFilters)) {
        if (!isSharedCategoryFilter(filter)) continue;
        selectedFilters.delete(filter);
        changed = true;
    }
    return changed;
}

export function normalizeSharedCategoryNavigationFilters(selectedFilters, items = []) {
    if (!selectedFilters) return false;
    const filters = Array.from(selectedFilters).filter(isSharedCategoryFilter);
    if (!filters.length) return false;
    const source = filters.filter(value => value.startsWith(SHARED_SOURCE_FILTER_PREFIX)).at(-1);
    let active = filters.filter(value => !value.startsWith(SHARED_SOURCE_FILTER_PREFIX)).at(-1);
    if (active && !active.startsWith(SHARED_THEME_FILTER_PREFIX) && !active.startsWith(SHARED_SUB_FILTER_PREFIX)) {
        const match = items.find(item => itemMatchesCategoryFilters(item, new Set([active])));
        const child = active.startsWith(SHARED_CHILD_FILTER_PREFIX)
            ? active.slice(SHARED_CHILD_FILTER_PREFIX.length).split(SHARED_CATEGORY_SEPARATOR).slice(1).join('/')
            : active.startsWith(SHARED_PATH_FILTER_PREFIX)
                ? active.slice(SHARED_PATH_FILTER_PREFIX.length).split(SHARED_CATEGORY_SEPARATOR).slice(1).join('/') : '';
        active = child && match?._semantic?.subcategories?.some(value => value === child || value.startsWith(child + '/'))
            ? SHARED_SUB_FILTER_PREFIX + sharedSubcategoryValue(match, child)
            : !child && sharedLibraryTaxonomy?.labels[match?._semantic?.primary_class]
                ? SHARED_THEME_FILTER_PREFIX + match._semantic.primary_class : '';
    }
    const next = [active, source].filter(Boolean);
    if (selectedFilters.size === next.length && next.every(value => selectedFilters.has(value))) return false;
    selectedFilters.clear();
    next.forEach(value => selectedFilters.add(value));
    return true;
}

export function activateSharedCategoryNavigationFilter(selectedFilters, filter) {
    if (!selectedFilters) return false;
    const activeFilter = String(filter || "");
    const current = Array.from(selectedFilters).filter(value => !String(value).startsWith(SHARED_SOURCE_FILTER_PREFIX));
    if (current.length === 1 && current[0] === activeFilter) return false;
    current.forEach(value => selectedFilters.delete(value));
    if (activeFilter) selectedFilters.add(activeFilter);
    return true;
}

export function buildSharedCategoryTree(items) {
    const roots = new Map();
    for (const item of Array.isArray(items) ? items : []) {
        if (!item?.shared) continue;
        const itemKey = String(item.id || canonicalPrompt(item.tags) || item.name || "");
        for (const path of getSharedCategoryPaths(item)) {
            let children = roots;
            for (const [depth, level] of path.levels.entries()) {
                const key = path.keys[depth];
                if (!children.has(key)) {
                    children.set(key, {
                        key,
                        name: level,
                        itemKeys: new Set(),
                        children: new Map(),
                    });
                }
                const node = children.get(key);
                node.itemKeys.add(itemKey);
                children = node.children;
            }
        }
    }

    const serialize = (nodes, depth = 0) => Array.from(nodes.values())
        .map(node => ({
            key: node.key,
            name: node.name,
            label: node.name,
            count: node.itemKeys.size,
            children: serialize(node.children, depth + 1),
        }));
    return serialize(roots);
}

export function itemMatchesCategoryFilters(item, selectedFilters, normalizeLocalCategory = value => value) {
    if (!selectedFilters || selectedFilters.size === 0) return true;
    const filters = Array.from(selectedFilters).map(String);
    const sources = filters.filter(value => value.startsWith(SHARED_SOURCE_FILTER_PREFIX));
    if (sources.length && !sources.includes(SHARED_SOURCE_FILTER_PREFIX + sharedSourceId(item))) return false;
    const themes = filters.filter(value => value.startsWith(SHARED_THEME_FILTER_PREFIX));
    const semantic = item?._semantic || {};
    const themeIds = semantic.theme_ids || [semantic.primary_class, ...(semantic.alternative_classes || [])];
    if (themes.length && !themes.some(value => themeIds.includes(value.slice(SHARED_THEME_FILTER_PREFIX.length)))) return false;
    const subGroups = new Map();
    for (const filter of filters.filter(value => value.startsWith(SHARED_SUB_FILTER_PREFIX))) {
        const value = filter.slice(SHARED_SUB_FILTER_PREFIX.length);
        const owner = value.includes('::') ? value.split('::', 1)[0]
            : Object.entries(sharedLibraryTaxonomy?.subcategories || {}).find(([, children]) => Object.keys(children).some(label => label === value || label.startsWith(value + '/')))?.[0] || value;
        if (!subGroups.has(owner)) subGroups.set(owner, []);
        subGroups.get(owner).push(value);
    }
    for (const values of subGroups.values()) {
        if (!values.some(value => {
            const separator = value.indexOf('::');
            const owner = separator >= 0 ? value.slice(0, separator) : '';
            const label = separator >= 0 ? value.slice(separator + 2) : value;
            return (semantic.subcategories || []).some(child => (child === label || child.startsWith(label + '/'))
                && (!owner || semantic.subcategory_owners?.[child] === owner));
        })) return false;
    }
    const legacyFilters = filters.filter(value => !value.startsWith(SHARED_THEME_FILTER_PREFIX)
        && !value.startsWith(SHARED_SUB_FILTER_PREFIX) && !value.startsWith(SHARED_SOURCE_FILTER_PREFIX));
    if (!legacyFilters.length) return true;
    const sharedPaths = getSharedFilterPaths(item);
    const localCategories = (Array.isArray(item?.categories) ? item.categories : [])
        .map(normalizeLocalCategory);

    for (const filter of legacyFilters) {
        const filterValue = String(filter || "");
        if (filterValue.startsWith(SHARED_PARENT_FILTER_PREFIX)) {
            const parent = normalizeSharedCategoryName(filterValue.slice(SHARED_PARENT_FILTER_PREFIX.length));
            if (sharedPaths.some(path => path.parent === parent)) return true;
            continue;
        }
        if (filterValue.startsWith(SHARED_CHILD_FILTER_PREFIX)) {
            const [parent, source] = filterValue
                .slice(SHARED_CHILD_FILTER_PREFIX.length)
                .split(SHARED_CATEGORY_SEPARATOR);
            if (sharedPaths.some(path => path.parent === parent && path.source === source)) return true;
            continue;
        }
        if (filterValue.startsWith(SHARED_PATH_FILTER_PREFIX)) {
            const levels = filterValue
                .slice(SHARED_PATH_FILTER_PREFIX.length)
                .split(SHARED_CATEGORY_SEPARATOR)
                .map(normalizeSharedCategoryName)
                .filter(Boolean);
            if (sharedPaths.some(path => (
                levels.every((level, index) => path.levels[index] === level)
            ))) return true;
            continue;
        }
        if (localCategories.includes(normalizeLocalCategory(filterValue))) return true;
    }
    return false;
}

export function pruneSharedCategoryFilters(
    items,
    selectedFilters,
    normalizeLocalCategory = value => value,
) {
    if (!selectedFilters || selectedFilters.size === 0) return false;
    let changed = false;
    for (const filter of Array.from(selectedFilters)) {
        const value = String(filter || "");
        if (!isSharedCategoryFilter(value)) continue;
        const singleFilter = new Set([filter]);
        const stillExists = (Array.isArray(items) ? items : []).some(
            item => itemMatchesCategoryFilters(
                item,
                singleFilter,
                normalizeLocalCategory,
            ),
        );
        if (!stillExists) {
            selectedFilters.delete(filter);
            changed = true;
        }
    }
    return changed;
}

export function buildSharedSourceOptions(items) {
    const sources = new Map();
    for (const item of items || []) {
        if (!item?.shared) continue;
        const id = sharedSourceId(item);
        if (!id) continue;
        if (!sources.has(id)) sources.set(id, {id, label:item.source_category || item.shared_category_paths?.find(path => path.source_full)?.source_full || id, items:new Set()});
        sources.get(id).items.add(item.id);
    }
    return Array.from(sources.values(), ({id, label, items}) => ({id, label, count:items.size}))
        .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
}

export function appendSharedCategoryTree({
    sidebar,
    items,
    tree = buildSharedCategoryTree(items),
    selectedFilters,
    rowClass,
    storageKey,
    onFilterChange,
    sourceOptions = buildSharedSourceOptions(items),
    kind,
}) {
    const preferredThemes = {
        character: ['identity'], clothing: ['clothing_accessory'], pose: ['pose_action'],
        background: ['background_environment'], artist: ['artist_style'],
        style_quality: ['style_medium', 'quality_detail', 'composition_camera', 'lighting_color'],
    }[kind] || [];
    if (sharedLibraryTaxonomy) {
        tree = Object.entries(sharedLibraryTaxonomy.labels).flatMap(([id, label]) => {
            const root = tree.find(node => node.key === SHARED_THEME_FILTER_PREFIX + id);
            if (!root) return [];
            const inventory = sharedLibraryTaxonomy.subcategories[id] || {};
            return [{...root, name:label, label, children:Object.keys(inventory).flatMap(name => {
                const child = root.children.find(child => child.name === name);
                return child ? [{...child, key:SHARED_SUB_FILTER_PREFIX + (sharedLibraryTaxonomy.values[name] || name), label:name}] : [];
            })}];
        });
    }
    tree = [...preferredThemes.flatMap(theme => tree.filter(node => node.key === SHARED_THEME_FILTER_PREFIX + theme)),
        ...tree.filter(node => !preferredThemes.includes(node.key.slice(SHARED_THEME_FILTER_PREFIX.length)))];
    if (!tree.length && !sourceOptions.length) return;

    const title = document.createElement("div");
    title.textContent = "主题与小主题";
    title.style.cssText = "margin:14px 8px 7px;font-size:11px;font-weight:800;letter-spacing:.05em;color:var(--uw-muted);text-transform:uppercase;";
    sidebar.appendChild(title);

    let collapsed = {};
    try {
        collapsed = JSON.parse(localStorage.getItem(storageKey + "-topics-v3") || "{}");
    } catch (_) {
        collapsed = {};
    }

    const isPrefix = (prefix, levels) => (
        prefix.length <= levels.length
        && prefix.every((level, index) => levels[index] === level)
    );
    const activeSharedFilter = Array.from(selectedFilters)
        .filter(value => isSharedCategoryFilter(value) && !String(value).startsWith(SHARED_SOURCE_FILTER_PREFIX))
        .at(-1) || "";
    const activePathLevels = activeSharedFilter.startsWith(SHARED_PATH_FILTER_PREFIX)
        ? activeSharedFilter
            .slice(SHARED_PATH_FILTER_PREFIX.length)
            .split(SHARED_CATEGORY_SEPARATOR)
            .map(normalizeSharedCategoryName)
            .filter(Boolean)
        : [];

    const appendNode = (node, parentElement, path, depth) => {
        const nodePath = [...path, node.name];
        const nodeKey = node.key || makeSharedPathFilterKey(nodePath);
        const legacyParentKey = depth === 0 ? makeSharedParentFilterKey(node.name) : "";
        const legacyChildKey = depth > 0
            ? makeSharedChildFilterKey(nodePath[0], node.name)
            : "";
        const group = document.createElement("div");
        group.style.cssText = `${depth === 0 ? "margin:2px 0 5px;" : "margin:1px 0;"}border-left:1px solid var(--uw-border);`;

        const isSelected = (
            selectedFilters.has(nodeKey)
            || (legacyParentKey && selectedFilters.has(legacyParentKey))
            || (legacyChildKey && selectedFilters.has(legacyChildKey))
        );
        const row = document.createElement("div");
        row.className = `${rowClass || ""} anima-shared-category-nav-item${isSelected ? " active" : ""}`.trim();
        row.style.cssText = "margin:1px 4px;min-height:36px;padding:7px 6px;gap:6px;";
        row.dataset.sharedCategoryPath = nodeKey;
        row.dataset.sharedCategoryActive = isSelected ? "true" : "false";
        row.tabIndex = 0;
        row.setAttribute("role", "button");
        row.setAttribute("aria-pressed", isSelected ? "true" : "false");
        row.title = `浏览 ${node.label}`;

        const left = document.createElement("div");
        left.style.cssText = "display:flex;align-items:center;gap:6px;min-width:0;flex:1;";

        const arrow = document.createElement("button");
        arrow.type = "button";
        const collapseKey = node.key || nodePath.join(SHARED_CATEGORY_SEPARATOR);
        const hasStoredCollapseState = Object.prototype.hasOwnProperty.call(
            collapsed,
            collapseKey,
        );
        const hasActiveChild = child => selectedFilters.has(child.key) || child.children.some(hasActiveChild);
        const containsActivePath = node.children.some(hasActiveChild) || (
            activePathLevels.length > nodePath.length
            && isPrefix(nodePath, activePathLevels)
        );
        const isCollapsed = containsActivePath
            ? false
            : (
                hasStoredCollapseState
                    ? collapsed[collapseKey] === true
                    : !preferredThemes.includes(nodeKey.slice(SHARED_THEME_FILTER_PREFIX.length))
            );
        arrow.textContent = node.children.length ? (isCollapsed ? "›" : "⌄") : "";
        arrow.title = node.children.length ? (isCollapsed ? "展开分类" : "收起分类") : "";
        arrow.style.cssText = "width:20px;min-width:20px;height:20px;min-height:0;padding:0;border:0;background:transparent;color:var(--uw-muted);cursor:pointer;font-size:17px;line-height:18px;";
        arrow.disabled = node.children.length === 0;

        const text = document.createElement("span");
        text.style.cssText = `min-width:0;white-space:normal;overflow-wrap:anywhere;line-height:1.5;font-size:12px;font-weight:${depth === 0 ? "700" : "500"};`;
        text.textContent = node.label;
        const count = document.createElement("span");
        count.style.cssText = `color:${isSelected ? "var(--uw-accent)" : "var(--uw-muted)"};font-size:11px;flex:0 0 auto;`;
        count.textContent = String(node.count);

        if (node.children.length) left.appendChild(arrow);
        left.appendChild(text);
        row.appendChild(left);
        row.appendChild(count);
        group.appendChild(row);

        const children = document.createElement("div");
        children.style.cssText = `${isCollapsed ? "display:none;" : "display:flex;"}flex-direction:column;padding-left:13px;`;
        for (const child of node.children) appendNode(child, children, nodePath, depth + 1);

        arrow.onclick = event => {
            event.stopPropagation();
            if (!node.children.length) return;
            const nextCollapsed = children.style.display !== "none";
            children.style.display = nextCollapsed ? "none" : "flex";
            arrow.textContent = nextCollapsed ? "›" : "⌄";
            arrow.title = nextCollapsed ? "展开分类" : "收起分类";
            collapsed[collapseKey] = nextCollapsed;
            localStorage.setItem(storageKey + "-topics-v3", JSON.stringify(collapsed));
        };
        const activateNode = () => {
            if (!activateSharedCategoryNavigationFilter(selectedFilters, nodeKey)) return;
            onFilterChange();
        };
        row.onclick = activateNode;
        row.onkeydown = event => {
            if (event.target !== row) return;
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            activateNode();
        };

        if (node.children.length) group.appendChild(children);
        parentElement.appendChild(group);
    };

    for (const root of tree) appendNode(root, sidebar, [], 0);
    if (sourceOptions.length) {
        const source = document.createElement('details');
        source.className = 'anima-shared-source-filter';
        source.style.cssText = 'margin:12px 8px;padding-top:8px;border-top:1px solid var(--uw-border);font-size:12px;';
        const summary = document.createElement('summary');
        const activeSource = Array.from(selectedFilters).find(value => String(value).startsWith(SHARED_SOURCE_FILTER_PREFIX));
        const current = activeSource?.slice(SHARED_SOURCE_FILTER_PREFIX.length) || '';
        summary.textContent = current ? '资料来源 · 已筛选' : '资料来源（可选）';
        summary.style.cursor = 'pointer';
        source.open = !!current;
        const picker = document.createElement('select');
        picker.setAttribute('aria-label', '来源筛选');
        picker.style.cssText = 'width:100%;max-width:100%;margin-top:8px;';
        for (const entry of [{id:'', label:'全部来源'}, ...sourceOptions]) {
            const option = document.createElement('option');
            option.value = entry.id;
            option.textContent = entry.label + (entry.count === undefined ? '' : ` (${entry.count})`);
            picker.appendChild(option);
        }
        picker.value = current;
        picker.title = picker.selectedOptions[0]?.textContent || '全部来源';
        picker.onchange = () => {
            for (const value of Array.from(selectedFilters)) if (String(value).startsWith(SHARED_SOURCE_FILTER_PREFIX)) selectedFilters.delete(value);
            if (picker.value) selectedFilters.add(SHARED_SOURCE_FILTER_PREFIX + picker.value);
            onFilterChange();
        };
        source.append(summary, picker);
        sidebar.appendChild(source);
    }
}

function sharedItemSignature(item) {
    return JSON.stringify([
        item?.name || "",
        item?.name_zh || "",
        item?.tags || "",
        item?.tags_zh || "",
        item?.preview || "",
        item?.categories || [],
        item?.shared_category_paths || [],
        item?.source_prompt_ids || [],
        item?.shared_previews || [],
        item?._semantic || null,
    ]);
}

function diffSharedPromptItems(previousItems, nextItems) {
    if (!Array.isArray(previousItems)) {
        return { added: 0, updated: 0, removed: 0, unchanged: nextItems.length, baseline: true };
    }
    const previous = new Map(previousItems.map(item => [String(item?.id || ""), sharedItemSignature(item)]));
    const next = new Map(nextItems.map(item => [String(item?.id || ""), sharedItemSignature(item)]));
    let added = 0;
    let updated = 0;
    let unchanged = 0;
    for (const [id, signature] of next) {
        if (!previous.has(id)) added += 1;
        else if (previous.get(id) !== signature) updated += 1;
        else unchanged += 1;
    }
    let removed = 0;
    for (const id of previous.keys()) {
        if (!next.has(id)) removed += 1;
    }
    return { added, updated, removed, unchanged, baseline: false };
}

async function fetchSharedPromptItems(kind, { force = false, filter = "", index = false, refreshServer = force } = {}) {
    const normalizedKind = String(kind || "").trim().toLowerCase();
    const normalizedFilter = String(filter || "");
    const cacheKey = JSON.stringify([normalizedKind, normalizedFilter, index ? "index" : "items"]);
    if (force) {
        sharedPromptCache.delete(cacheKey);
    }
    if (sharedPromptCache.has(cacheKey)) {
        return sharedPromptCache.get(cacheKey);
    }

    const refreshQuery = refreshServer ? `&refresh=${Date.now()}` : "";
    const filterQuery = normalizedFilter ? `&filter=${encodeURIComponent(normalizedFilter)}` : "";
    const indexQuery = index ? "&index=1" : "";
    const request = fetch(
        `/anima-tools/shared-prompts?kind=${encodeURIComponent(normalizedKind)}${filterQuery}${indexQuery}${refreshQuery}`,
        { cache: "no-store" },
    )
        .then(async response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            if (payload?.enabled !== true) throw new Error('WeiLin 共享资料库不可用，请检查服务后重试。');
            if (sharedPromptCache.get(cacheKey) !== request) {
                const error = new Error("共享资料请求已失效，请使用当前刷新结果。");
                error.code = "STALE_SHARED_PROMPTS";
                throw error;
            }
            await loadSharedLibraryTaxonomy({revision:payload.revision || JSON.stringify([payload.source_sha256 || payload.source_last_modified, payload.taxonomy_version]), force});
            if (sharedPromptCache.get(cacheKey) !== request) {
                const error = new Error('共享资料请求已失效，请使用当前刷新结果。');
                error.code = 'STALE_SHARED_PROMPTS';
                throw error;
            }
            const items = (Array.isArray(payload?.items) ? payload.items : []).filter(item => isReviewedSharedFragment(item));
            const changes = diffSharedPromptItems(sharedPromptSnapshots.get(cacheKey), items);
            sharedPromptSnapshots.set(cacheKey, items);
            window.animaSharedPromptStats = {
                ...(window.animaSharedPromptStats || {}),
                [normalizedKind]: {
                    enabled: payload?.enabled === true,
                    count: items.length,
                    matchedSourceCategories: payload?.matched_source_categories || 0,
                    mappedSourceCategories: payload?.mapped_source_categories || 0,
                    auditedSourceCategories: payload?.audited_source_categories || 0,
                    sourceCategoryCount: payload?.source_category_count || 0,
                    unmappedCategoryCount: payload?.unmapped_category_count || 0,
                    unmappedCategories: Array.isArray(payload?.unmapped_categories)
                        ? payload.unmapped_categories
                        : [],
                    quarantinedCategoryCount: payload?.quarantined_category_count || 0,
                    quarantinedPromptCount: payload?.quarantined_prompt_count || 0,
                    pendingPromptCount: payload?.pending_prompt_count || 0,
                    taxonomyVersion: payload?.taxonomy_version || "",
                    taxonomySourceMatches: payload?.taxonomy_source_matches !== false,
                    sourceLastModified: payload?.source_last_modified || "",
                    changes,
                },
            };
            return items;
        })
        .catch(error => {
            if (error?.code === "STALE_SHARED_PROMPTS") throw error;
            console.warn(`[Anima Tools] WeiLin shared ${normalizedKind} prompts unavailable`, error);
            if (sharedPromptCache.get(cacheKey) === request) sharedPromptCache.delete(cacheKey);
            throw error;
        })
        .finally(() => {
            // Deduplicate in-flight reads only. A later open must recheck the
            // server's source/projection version even if an update event was missed.
            if (sharedPromptCache.get(cacheKey) === request) sharedPromptCache.delete(cacheKey);
        });

    sharedPromptCache.set(cacheKey, request);
    return request;
}

export async function loadSharedPromptItems(kind, options = {}) {
    return fetchSharedPromptItems(kind, options);
}

export async function validateSharedPromptSelection(kind, selectedItems) {
    const shared = selectedItems.filter(item => item?.shared);
    if (!shared.length) return;
    const current = new Map((await loadSharedPromptItems(kind, { force: true, refreshServer: false }))
        .map(item => [String(item.id), item]));
    for (const item of shared) {
        const fresh = current.get(String(item.id));
        if (!isReviewedSharedFragment(item) || !fresh
            || !item._semantic?.binding || fresh._semantic?.binding !== item._semantic.binding
            || fresh.tags !== item.tags) {
            throw new Error("资料已变更或不再可用，请刷新列表后重新选择。");
        }
    }
}

export async function loadSharedPromptIndexItems(kind, options = {}) {
    return fetchSharedPromptItems(kind, { ...options, index: true });
}

export async function loadMergedPromptItems(kind, localItems) {
    return fetchSharedPromptItems(kind);
}

export async function refreshMergedPromptItems(kind, localItems) {
    return fetchSharedPromptItems(kind, { force: true });
}

export async function openSharedResourceEditor(overlay, options, reopen) {
    const display = overlay?.style.display;
    const overlayId = overlay?.id;
    if (overlay) { overlay.style.display = 'none'; overlay.inert = true; }
    let restored = false;
    const restore = async (reload = true) => {
        if (restored || !overlay?.isConnected) return;
        restored = true;
        if (reload && reopen) {
            clearSharedPromptCache();
            await reopen();
            const selector = document.getElementById(overlayId);
            requestAnimationFrame(() => {
                if (!selector?.isConnected || selector.closest('[inert]') || !selector.getClientRects().length
                    || getComputedStyle(selector).visibility === 'hidden') return;
                const source = [...selector.querySelectorAll('.anima-shared-resource-edit')]
                    .find(button => button.dataset.promptId === String(options.promptId));
                (source?.closest('.anima-shared-resource-card') || selector.querySelector('input[type=search], input[placeholder]'))?.focus();
            });
        } else {
            overlay.style.display = display; overlay.inert = false;
        }
    };
    try {
        if (typeof window.weilinOpenSharedPresets !== 'function') throw new Error('共享资料编辑器尚未加载');
        const opened = await window.weilinOpenSharedPresets({...options, editorOnly:!options.importOnly && !options.collectionsOnly, onClose:restore});
        if (opened === false) await restore(false);
    } catch (error) {
        await restore(false);
        throw error;
    }
}

export function appendSharedResourceEditor(card, item, reopen, info) {
    if (!item?.shared || !item.source_prompt_id) return;
    if (!document.getElementById('anima-shared-resource-actions-style')) {
        const style = document.createElement('style');
        style.id = 'anima-shared-resource-actions-style';
        style.textContent = `
            .anima-shared-resource-card [class$="-card-info"] { bottom:42px !important; }
            .anima-shared-resource-card [class$="-tags-overlay"], .anima-shared-resource-card .anima-character-card-tags { bottom:44px; }
            .anima-shared-resource-edit { position:absolute;left:12px;right:12px;bottom:9px;z-index:12;pointer-events:auto;font:inherit;font-size:11px;min-height:30px;padding:5px 7px;border:1px solid var(--uw-border);border-radius:6px;background:var(--uw-panel);color:#eee;cursor:pointer; }
            .anima-shared-resource-edit:hover, .anima-shared-resource-edit:focus-visible { background:var(--uw-accent-bg);border-color:var(--uw-border-strong);outline:2px solid var(--uw-border-strong);outline-offset:1px; }
        `;
        document.head.appendChild(style);
    }
    const topics = getSharedTopicSummary(item);
    const taxonomy = document.createElement('div');
    taxonomy.className = 'anima-shared-resource-taxonomy';
    taxonomy.textContent = topics[0] || '主题待确认';
    taxonomy.title = topics.join('\n') || '主题待确认';
    taxonomy.setAttribute('aria-label', '资料库分类：' + (topics.join('；') || '主题待确认'));
    taxonomy.style.cssText = 'font-size:11px;line-height:1.5;color:var(--uw-muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;';
    info.appendChild(taxonomy);
    card.classList.add('anima-shared-resource-card');
    card.tabIndex = 0;
    card.setAttribute('role', 'group');
    card.setAttribute('aria-label', (item.name_zh || item.name || item.tags || '资料') + '，按 Enter 或空格切换选择');
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = '编辑共享资料';
    button.title = '编辑正文、分类、收藏组、收藏别名和备注';
    button.className = 'anima-shared-resource-edit';
    button.dataset.promptId = item.source_prompt_id;
    button.onclick = async event => {
        event.stopPropagation();
        if (button.disabled) return;
        button.disabled = true;
        try {
            await openSharedResourceEditor(card.closest('[id^="anima-"][id$="selector-overlay"]'),
                {view:'all', promptId:item.source_prompt_id, editPrompt:true}, reopen);
        } catch (error) {
            button.textContent = error.message;
        } finally {
            button.disabled = false;
        }
    };
    card.appendChild(button);
}

export function watchSharedLibrary(overlay, kind, reopen, busy = () => false) {
    const releaseExperience = installSelectorExperience(overlay, kind);
    let revision = window.animaSharedPromptStats?.[kind]?.sourceLastModified || '';
    let checking = false;
    let stopped = false;
    let lastCheckAt = 0;
    const stop = () => {
        if (stopped) return;
        stopped = true;
        window.removeEventListener('focus', checkRevision);
        document.removeEventListener('visibilitychange', checkRevision);
        releaseExperience();
    };
    const checkRevision = async () => {
        if (!overlay.isConnected) { stop(); return; }
        if (checking || document.hidden || overlay.inert || overlay.style.display === 'none' || busy()) return;
        const active = document.activeElement;
        if (overlay.contains(active) && active?.matches('input:not([type=checkbox]), textarea, select, [contenteditable=true]') && String(active.value || active.textContent || '').trim()) return;
        const now = Date.now();
        if (now - lastCheckAt < 1000) return;
        lastCheckAt = now;
        checking = true;
        try {
            const response = await fetch('/prompt_selector/library/revision', {cache:'no-store'});
            if (!response.ok) return;
            const latest = (await response.json()).revision;
            revision ||= window.animaSharedPromptStats?.[kind]?.sourceLastModified || '';
            if (revision && latest !== revision && overlay.isConnected && !overlay.inert && !busy()) {
                stop();
                clearSharedPromptCache(kind);
                await reopen();
            }
            revision = latest;
        } catch (error) { console.warn('[Anima Tools] Shared library refresh unavailable', error); }
        finally { checking = false; }
    };
    window.addEventListener('focus', checkRevision);
    document.addEventListener('visibilitychange', checkRevision);
    return stop;
}

export function getSharedPromptSyncStats(kind) {
    const normalizedKind = String(kind || "").trim().toLowerCase();
    return window.animaSharedPromptStats?.[normalizedKind] || null;
}

export function getSharedPromptSyncMessage(kind, label = "Tags") {
    const stats = getSharedPromptSyncStats(kind);
    if (!stats) return `WeiLin ${label} 已同步`;
    const changes = stats.changes || {};
    const changeText = `新增 ${changes.added || 0} / 更新 ${changes.updated || 0} / 删除 ${changes.removed || 0}`;
    const coverageText = stats.sourceCategoryCount
        ? `；分类审计 ${stats.auditedSourceCategories || stats.mappedSourceCategories}/${stats.sourceCategoryCount}`
        : "";
    const warningText = stats.unmappedCategoryCount
        ? `；⚠ 未映射 ${stats.unmappedCategoryCount} 类（已跳过）`
        : "；未映射 0";
    const quarantineText = stats.quarantinedPromptCount
        ? `；安全隔离 ${stats.quarantinedPromptCount} 条`
        : "";
    const pendingText = stats.pendingPromptCount
        ? `；⚠ 待复核 ${stats.pendingPromptCount} 条`
        : "；待复核 0";
    const versionText = stats.taxonomySourceMatches
        ? ""
        : "；源数据已变化";
    return `WeiLin ${label} 已同步：${changeText}${coverageText}${warningText}${pendingText}${quarantineText}${versionText}`;
}

export function clearSharedPromptCache(kind = "") {
    const normalizedKind = String(kind || "").trim().toLowerCase();
    if (normalizedKind) {
        for (const key of sharedPromptCache.keys()) {
            try {
                if (JSON.parse(key)?.[0] === normalizedKind) {
                    sharedPromptCache.delete(key);
                }
            } catch (_) {
                sharedPromptCache.delete(key);
            }
        }
    } else {
        sharedPromptCache.clear();
    }
}


export function appendSharedResourceActions(host, {overlay, kind, reopen, getCollection}) {
    const classes = {pose:'pose_action', clothing:'clothing_accessory', background:'background_environment',
        character:'identity', artist:'artist_style', style_quality:'style_medium'};
    const labels = {pose:'动作与姿势', clothing:'服装与配饰', background:'背景与环境',
        character:'角色与身份', artist:'画师与作者', style_quality:'风格与媒介'};
    const create = document.createElement('button');
    const importButton = document.createElement('button');
    const collections = document.createElement('button');
    let collectionOptions = {};
    for (const [button, label, action] of [[create, '新建共享资料', 'create'], [importButton, '导入共享资料', 'import'], [collections, '管理收藏组', 'collections']]) {
        button.type = 'button'; button.textContent = label;
        button.className = 'anima-shared-resource-action'; button.dataset.sharedAction = action;
        button.style.cssText = 'background:var(--uw-panel);color:#eee;border:1px solid var(--uw-border);border-radius:6px;padding:6px 10px;cursor:pointer;font:inherit;font-size:12px;';
        button.onclick = async event => {
            event?.stopPropagation();
            if (button.disabled) return;
            button.disabled = true;
            try {
                const group = getCollection?.();
                const options = action === 'collections' ? {collectionsOnly:true, selectorKind:kind,
                    collectionId:collectionOptions.groupId, collectionAction:collectionOptions.action}
                    : action === 'import' ? {importOnly:true} : {createPrompt:true,
                    prefill:{favorite:!!group, new_category_name:'Anima 自建/' + labels[kind],
                        selector_group_ids:group ? [group] : [],
                        _semantic:{primary_class:classes[kind], content_type:'fragment', usage:'positive'}}};
                await openSharedResourceEditor(overlay, options, reopen);
                button.textContent = label;
            } catch (error) { button.textContent = error.message; }
            finally { button.disabled = false; }
        };
        host.appendChild(button);
    }
    return {create:() => create.click(), collections:options => {
        collectionOptions = options || {};
        collections.click();
    }};
}
