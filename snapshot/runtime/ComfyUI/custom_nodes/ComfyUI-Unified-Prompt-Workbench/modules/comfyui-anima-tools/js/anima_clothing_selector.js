import { capturePromptTarget, appendUnresolvedPromptFavorites } from "./anima_prompt_identity.js";
import { app } from "../../scripts/app.js";
import { t } from "./i18n.js";
import { getPersistentImageUrl, markImageLoaded, isImageLoaded } from "./anima_image_utils.js";
import {
    appendSharedCategoryTree,
    buildSharedSourceOptions,
    appendSharedResourceEditor, appendSharedResourceActions, watchSharedLibrary,
    getSharedPromptSyncMessage,
    hasSharedCategoryFilters,
    itemMatchesCategoryFilters,
    loadMergedPromptItems,
    validateSharedPromptSelection,
    normalizeSharedCategoryNavigationFilters,
    pruneSharedCategoryFilters,
    removeSharedCategoryFilters,
    refreshMergedPromptItems,
    getPromptSearchRank,
    rankPromptSearchResults,
    createStablePromptShuffle,
} from "./anima_shared_prompt_data.js";
import { createPromoLinks } from "./anima_promo_links.js";
import { assignPromptSelectorKeys, getPromptItemKey, getPromptFavoriteSourceKey, resolvePromptFavorites } from "./anima_prompt_identity.js";
import { recoverFavoritesConflict } from "./anima_favorites_recovery.js";
import { addSelectorActionRow, installSelectorExecutionSync, isAnimaPromptPlusNode } from "./anima_selector_random.js";
import {
    copyText,
    installSelectorDialog,
    reopenSelector,
    captureSelectorFavoriteFocus,
    createEl,
    createGallerySelectorStyleSheet,
    createModalButtons,
    createModalShell as createSharedModalShell,
    escapeHtml,
    normalizePromptToken,
    showToast as showSharedToast,
    splitPromptTokens,
    mountSelectorInsertionActions,
} from "./anima_selector_ui.js";

const THEME = {
    accent: "var(--uw-accent)",
    accentSoft: "var(--uw-accent-bg)",
    accentBorder: "var(--uw-accent)",
    accentText: "var(--uw-accent)",
};

const CATEGORY_LIST = [
    "Dress & Gown",
    "Casual & Daily",
    "Uniform & Suit",
    "Swimsuit & Lingerie",
    "Fantasy & Cosplay",
    "Revealing",
];

const TRAITS_TRANSLATION = {};

function getAdditionalClothingTraits(item) {
    const sourceNames = new Set([
        item?.source_category,
        ...(Array.isArray(item?.shared_category_paths) ? item.shared_category_paths.map(path => path?.source_full) : []),
    ].filter(value => typeof value === "string").flatMap(value => [value.trim(), ...value.split("/").map(part => part.trim())]));
    return (Array.isArray(item?.traits) ? item.traits : []).filter(trait =>
        typeof trait === "string" && trait.trim() && !sourceNames.has(trait.trim()));
}

app.registerExtension({
    name: "AnimaClothingTagSelector.extension",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "AnimaClothingTagSelector" || nodeData.name === "AnimaClothingTagSelectorPlus" || isAnimaPromptPlusNode(nodeData.name)) {
            installSelectorExecutionSync(nodeType);
            const origOnCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                origOnCreated?.apply(this, arguments);

                const clothingTagsWidget = this.widgets.find(w => w.name === "clothing_tags");
                if (!clothingTagsWidget) return;
                addSelectorActionRow(this, {
                    section: "clothing",
                    label: t("Open Clothing Selector"),
                    accent: THEME.accent,
                    accentText: THEME.accentText,
                    onOpen: async () => {
                        await openClothingSelectorModal(this, clothingTagsWidget);
                    },
                });
            };
        }
    }
});

function normalizeCategoryValue(category) {
    const text = String(category || "").trim();
    if (CATEGORY_LIST.includes(text)) return text;
    const englishPart = text.match(/\(([^)]+)\)$/)?.[1];
    if (englishPart && CATEGORY_LIST.includes(englishPart)) return englishPart;
    return text;
}

function getItemKey(item) {
    return getPromptItemKey(item);
}

function formatDisplayName(item, displayLang) {
    if (!item) return "";
    if (item.isCustom) return item.nickname || item.name || "";
    if (displayLang === "bilingual" && item.name_zh) return item.name_zh;
    return item.name || "";
}

function getCategoryLabel(category, displayLang) {
    return category.match(/\(([^)]+)\)/)?.[1] || category;
}

function getTraitZh(trait, data) {
    const key = String(trait || "").toLowerCase().trim();
    if (TRAITS_TRANSLATION[key]) return TRAITS_TRANSLATION[key];
    for (const item of data || []) {
        const enList = splitPromptTokens(item.tags).map(normalizePromptToken);
        const zhList = splitPromptTokens(item.tags_zh);
        const idx = enList.indexOf(key);
        if (idx !== -1 && zhList[idx]) return zhList[idx];
    }
    return trait;
}

export async function openClothingSelectorModal(node, tagsWidget, restoredSelection = null) {
    const assertPromptTarget = capturePromptTarget(node, tagsWidget, () => app.graph);
    const clothingData = await loadMergedPromptItems(
        "clothing",
        Array.isArray(window.clothingData) ? window.clothingData : [],
    );
    assignPromptSelectorKeys(clothingData);
    const dataById = new Map(clothingData.map(item => [getItemKey(item), item]));
    const sourceLabels = new Map(buildSharedSourceOptions(clothingData).map(source => [source.id, source.label]));
    const currentTokens = new Set(splitPromptTokens(tagsWidget?.value || "").map(normalizePromptToken));
    const selectedClothing = restoredSelection instanceof Set
        ? new Set(restoredSelection)
        : new Set();

    if (!(restoredSelection instanceof Set)) {
        clothingData.forEach(item => {
            const tokens = splitPromptTokens(item.tags).map(normalizePromptToken);
            if (tokens.length > 0 && tokens.every(token => currentTokens.has(token))) {
                selectedClothing.add(getItemKey(item));
            }
        });
    }

    let favoritesEtag = null;
    let favoritesSaveInFlight = false;
    let favoritesConfig = {
        clothing: {
            groups: [{ id: "default", name: t("My Favorites"), isSystem: true }],
            items: [],
        }
    };

    try {
        const response = await fetch("/anima-tools/favorites");
        if (response.ok) {
            favoritesConfig = await response.json();
            favoritesEtag = response.headers.get("ETag") || null;
        }
    } catch (e) {
        console.error("[Anima Tools] Failed to load clothing favorites", e);
    }

    if (!favoritesConfig.clothing) {
        favoritesConfig.clothing = {
            groups: [{ id: "default", name: t("My Favorites"), isSystem: true }],
            items: [],
        };
    }

    let groups = Array.isArray(favoritesConfig.clothing.groups) && favoritesConfig.clothing.groups.length
        ? favoritesConfig.clothing.groups
        : [{ id: "default", name: t("My Favorites"), isSystem: true }];
    if (!groups.some(group => group.id === "default")) {
        groups = [{ id: "default", name: t("My Favorites"), isSystem: true }, ...groups];
    }

    let favoriteItems = Array.isArray(favoritesConfig.clothing.items) ? favoritesConfig.clothing.items : [];
    favoriteItems.forEach(item => {
        if (item.isCustom) {
            const customTokens = splitPromptTokens(item.customContent).map(normalizePromptToken);
            if (customTokens.length > 0 && customTokens.every(token => currentTokens.has(token))) selectedClothing.add(getItemKey(item));
        }
    });
    const resolvedFavorites = resolvePromptFavorites(clothingData, favoriteItems);
    const favoriteMap = resolvedFavorites.map;
    const favoriteSet = resolvedFavorites.set;
    const unresolvedFavoriteItems = resolvedFavorites.unresolved;
    const validSelectionKeys = new Set([
        ...clothingData.map(getItemKey),
        ...favoriteItems.filter(item => item.isCustom).map(getItemKey),
    ]);
    for (const key of Array.from(selectedClothing)) {
        if (!validSelectionKeys.has(key)) selectedClothing.delete(key);
    }

    const SORT_STORAGE_KEY = "anima-clothing-selector-active-sort";
    const PAGE_STORAGE_KEY = "anima-clothing-selector-active-page";
    const SCROLL_STORAGE_KEY = "anima-clothing-selector-active-scroll";
    const SIDEBAR_SCROLL_STORAGE_KEY = "anima-clothing-selector-sidebar-scroll";
    const DISPLAY_LANG_STORAGE_KEY = "anima-clothing-selector-display-lang";
    const FILTER_STORAGE_KEY = "anima-clothing-selector-filters";
    const SHARED_PATH_STORAGE_VERSION = 2;
    const COLLECTIONS_COLLAPSE_STORAGE_KEY = "anima-clothing-selector-collections-collapsed";
    const TRAITS_COLLAPSE_STORAGE_KEY = "anima-clothing-selector-traits-collapsed";
    const SHARED_CATEGORIES_COLLAPSE_STORAGE_KEY = "anima-clothing-selector-shared-categories-collapsed-v2";

    let activeSort = localStorage.getItem(SORT_STORAGE_KEY) || "id-asc";
    let displayLang = localStorage.getItem(DISPLAY_LANG_STORAGE_KEY) || "en";
    let currentPage = parseInt(localStorage.getItem(PAGE_STORAGE_KEY), 10) || 1;
    let showSelectedOnly = false;
    let filteredData = [];
    let totalPages = 1;
    let lastScrollTop = parseInt(localStorage.getItem(SCROLL_STORAGE_KEY), 10) || 0;
    let lastSidebarScrollTop = parseInt(localStorage.getItem(SIDEBAR_SCROLL_STORAGE_KEY), 10) || 0;
    let collectionsCollapsed = localStorage.getItem(COLLECTIONS_COLLAPSE_STORAGE_KEY) === "true";
    let traitsCollapsed = localStorage.getItem(TRAITS_COLLAPSE_STORAGE_KEY) !== "false";

    const activeFilters = {
        categories: new Set(),
        traits: new Set(),
        collection: "all",
    };

    let migratedSharedClothingStorage = false;
    try {
        const saved = JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY) || "{}");
        if (Array.isArray(saved.categories)) saved.categories.forEach(v => activeFilters.categories.add(normalizeCategoryValue(v)));
        if (Array.isArray(saved.traits)) saved.traits.forEach(v => activeFilters.traits.add(v));
        if (saved.collection) activeFilters.collection = saved.collection;
        if (
            Number(saved.sharedPathVersion || 0) !== SHARED_PATH_STORAGE_VERSION
            && hasSharedCategoryFilters(activeFilters.categories)
        ) {
            removeSharedCategoryFilters(activeFilters.categories);
            migratedSharedClothingStorage = true;
        }
    } catch (e) {
        console.warn("[Anima Tools] Failed to restore clothing filters", e);
    }
    const validCollectionIds = new Set([
        "all",
        "weilin",
        "default",
        ...groups.map(group => String(group.id || "")).filter(Boolean),
    ]);
    if (!validCollectionIds.has(activeFilters.collection)) {
        activeFilters.collection = "all";
    }
    const prunedSharedClothingFilters = pruneSharedCategoryFilters(
        clothingData,
        activeFilters.categories,
        normalizeCategoryValue,
    );
    const normalizedSharedClothingFilters = normalizeSharedCategoryNavigationFilters(
        activeFilters.categories,
        clothingData,
    );
    const reconciledSharedClothingState = (
        hasSharedCategoryFilters(activeFilters.categories)
        && activeFilters.collection !== "weilin"
    );
    if (hasSharedCategoryFilters(activeFilters.categories)) {
        activeFilters.collection = "weilin";
    } else if (activeFilters.collection === "weilin") {
        activeFilters.collection = "all";
        persistFilters();
    }
    if (
        prunedSharedClothingFilters
        || normalizedSharedClothingFilters
        || reconciledSharedClothingState
        || migratedSharedClothingStorage
    ) {
        persistFilters();
    }

    for (const category of [...activeFilters.categories]) { if (!String(category).startsWith("shared-")) activeFilters.categories.delete(category); }
    const allTraits = Array.from(clothingData.reduce((map, item) => {
        getAdditionalClothingTraits(item).forEach(trait => {
            map.set(trait, (map.get(trait) || 0) + 1);
        });
        return map;
    }, new Map()).entries())
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    const validTraitNames = new Set(allTraits.map(trait => trait.name));
    let prunedInvalidTraits = false;
    for (const trait of Array.from(activeFilters.traits)) {
        if (validTraitNames.has(trait)) continue;
        activeFilters.traits.delete(trait);
        prunedInvalidTraits = true;
    }
    if (prunedInvalidTraits) persistFilters();

    async function saveFavorites() {
        if (favoritesSaveInFlight) return false;
        const restoreFavoriteFocus = captureSelectorFavoriteFocus(overlay);
        let favoritesSaved = false;
        favoritesSaveInFlight = true;
        const saveOwner = typeof document === "undefined" ? null : document.activeElement?.closest?.("[data-anima-favorites-editor]");
        const interactionOwners = [...new Set([overlay, saveOwner].filter(Boolean))];
        const previousInert = interactionOwners.map(element => element.inert);
        interactionOwners.forEach(element => { element.inert = true; });
        try {
            const nextItems = favoriteItems.filter(item => item.isCustom);
        favoriteMap.forEach((value, key) => {
            if (favoriteSet.has(key)) nextItems.push(value);
        });
        unresolvedFavoriteItems.forEach(item => nextItems.push(item));

        favoriteItems = nextItems;
        favoritesConfig.clothing.groups = groups;
        favoritesConfig.clothing.items = favoriteItems;

            const response = await fetch("/anima-tools/favorites", {
                method: "POST",
                headers: { "Content-Type": "application/json", "If-Match": favoritesEtag || "" },
                body: JSON.stringify(favoritesConfig),
            });
            if (!response.ok) {
                const error = new Error(await response.text());
                error.status = response.status;
                throw error;
            }
            favoritesEtag = response.headers.get("ETag") || favoritesEtag;
            favoritesSaveInFlight = false;
            favoritesSaved = true;
            return true;
        } catch (e) {
            console.error("[Anima Tools] Failed to save clothing favorites", e);
            try { return await offerFavoritesConflictRecovery(e.status || 0, saveOwner); }
            finally { favoritesSaveInFlight = false; }
        } finally {
            interactionOwners.forEach((element, index) => { element.inert = previousInert[index]; });
            restoreFavoriteFocus(favoritesSaved);
        }
    }

    async function offerFavoritesConflictRecovery(initialStatus, saveOwner) {
        const draftSection = JSON.parse(JSON.stringify(favoritesConfig.clothing || {}));
        return recoverFavoritesConflict({ partition: "clothing", draftSection, currentConfig: favoritesConfig, currentEtag: favoritesEtag, initialStatus, isActive: () => overlay.isConnected && (!saveOwner || saveOwner.isConnected), fetchLatest: () => fetch("/anima-tools/favorites"),
            submit: async (config, etag) => { const r = await fetch("/anima-tools/favorites", { method: "POST", headers: { "Content-Type": "application/json", "If-Match": etag || "" }, body: JSON.stringify(config) }); return { ok: r.ok, status: r.status, etag: r.headers.get("ETag") || etag }; },
            commit: (config, etag) => { favoritesConfig = config; favoritesEtag = etag; groups = config.clothing.groups || groups; favoriteItems = config.clothing.items || favoriteItems; }, t });
    }

    function persistFilters() {
        localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify({
            categories: Array.from(activeFilters.categories),
            traits: Array.from(activeFilters.traits),
            collection: activeFilters.collection,
            sharedPathVersion: SHARED_PATH_STORAGE_VERSION,
        }));
    }

    const styleSheet = createGallerySelectorStyleSheet("clothing");
    document.head.appendChild(styleSheet);

    const overlay = createEl("div");
    overlay.id = "anima-clothing-selector-overlay";
    overlay.unifiedClose=()=>closeModal();
    overlay.style.cssText = `
        position: fixed;
        inset: 0;
        z-index: 99999;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--uw-panel);
        backdrop-filter: blur(15px);
        -webkit-backdrop-filter: blur(15px);
        color: var(--uw-text);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    `;

    const container = createEl("div");
    container.style.cssText = `
        width: 94vw;
        max-width: 1360px;
        height: 91vh;
        background: var(--uw-bg);
        border: 1px solid var(--uw-border);
        border-radius: 24px;
        overflow: hidden;
        box-shadow: 0 25px 60px rgba(0,0,0,0.58);
        display: flex;
        flex-direction: column;
        animation: animaClothingFadeIn 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    `;

    overlay.onclick = (event) => {
        if (event.target === overlay) closeModal();
    };

    const header = createEl("div");
    header.style.cssText = `
        padding: 20px 26px 16px;
        border-bottom: 1px solid var(--uw-border);
        background: linear-gradient(180deg, var(--uw-accent-bg), rgba(23,23,24,0));
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 18px;
    `;

    const titleWrap = createEl("div");
    titleWrap.style.cssText = "min-width: 240px;";
    const title = createEl("div", null, t("Anima Clothing Tag Selector"));
    title.style.cssText = "font-size: 20px; font-weight: 850; color: #fff; line-height: 1.2;";
    const subtitle = createEl("div", null, t("Browse and select outfit prompt tags with 2:3 visual preview cards."));
    subtitle.style.cssText = "font-size: 12.5px; color: var(--uw-muted); margin-top: 5px;";
    titleWrap.appendChild(title);
    titleWrap.appendChild(subtitle);
    appendUnresolvedPromptFavorites(titleWrap, unresolvedFavoriteItems);

    const searchInput = createEl("input", "anima-clothing-input");
    searchInput.type = "search";
    searchInput.placeholder = t("Search clothing or tags...");
    searchInput.value = "";
    searchInput.style.cssText += "flex: 1; min-width: 260px;";

    const closeBtn = createEl("button", "anima-clothing-btn", t("Cancel"));
    closeBtn.onclick = () => closeModal();

    const headerActions = createEl("div");
    headerActions.style.cssText = "display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex: 0 0 auto;";
    headerActions.appendChild(createPromoLinks({ accentColor: THEME.accentText }));
    headerActions.appendChild(closeBtn);

    header.appendChild(titleWrap);
    header.appendChild(searchInput);
    header.appendChild(headerActions);
    container.appendChild(header);

    const toolbar = createEl("div");
    toolbar.style.cssText = `
        padding: 14px 26px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        border-bottom: 1px solid var(--uw-border);
        background: var(--uw-panel);
    `;

    const filterControls = createEl("div");
    filterControls.style.cssText = "display: flex; align-items: center; gap: 10px; min-width: 0; flex-wrap: wrap;";

    const sortSelect = createEl("select", "anima-clothing-select");
    sortSelect.innerHTML = `
        <option value="id-desc">${t("Latest")}</option>
        <option value="id-asc">${t("Oldest")}</option>
        <option value="name-asc">${t("Name A-Z")}</option>
        <option value="name-desc">${t("Name Z-A")}</option>
        <option value="favorite-desc">${t("Favorites First ★")}</option>
        <option value="random">${t("Random")}</option>
    `;
    sortSelect.value = activeSort;
    sortSelect.onchange = () => {
        activeSort = sortSelect.value;
        localStorage.setItem(SORT_STORAGE_KEY, activeSort);
        currentPage = 1;
        triggerFilter();
    };

    const langSelect = createEl("select", "anima-clothing-select");
    langSelect.innerHTML = `
        <option value="bilingual">${t("Bilingual")}</option>
        <option value="en">${t("English Only")}</option>
    `;
    langSelect.value = displayLang;
    langSelect.onchange = () => {
        displayLang = langSelect.value;
        localStorage.setItem(DISPLAY_LANG_STORAGE_KEY, displayLang);
        renderSidebar();
        renderCurrentPage();
    };

    filterControls.appendChild(sortSelect);
    filterControls.appendChild(langSelect);

    const actionControls = createEl("div");
    actionControls.style.cssText = "display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end;";

    const syncWeiLinBtn = createEl("button", "anima-clothing-btn", "同步 WeiLin");
    syncWeiLinBtn.title = "立即读取 WeiLin 的新增、修改、删除、分类和预览变化";
    syncWeiLinBtn.onclick = async () => {
        syncWeiLinBtn.disabled = true;
        syncWeiLinBtn.innerText = "同步中…";
        try {
            await refreshMergedPromptItems(
                "clothing",
                Array.isArray(window.clothingData) ? window.clothingData : [],
            );
            if (isClosed) return;
            const selection = new Set(selectedClothing);
            await reopenSelector(overlay, () => openClothingSelectorModal(node, tagsWidget, selection));
            showSharedToast(getSharedPromptSyncMessage("clothing", "服装 Tags"));
        } catch (error) {
            if (isClosed) return;
            console.error("[Anima Tools] WeiLin clothing sync failed", error);
            syncWeiLinBtn.disabled = false;
            syncWeiLinBtn.innerText = "同步 WeiLin";
            alert(`WeiLin 同步失败：${error?.message || error}`);
        }
    };

    const copySelectedBtn = createEl("button", "anima-clothing-btn");
    copySelectedBtn.innerHTML = `${copyIcon()} ${t("Copy Selected")}`;
    copySelectedBtn.onclick = () => {
        const text = buildSelectedText();
        if (!text) {
            alert(t("Please select at least one clothing item first."));
            return;
        }
        copyText(text, () => showToast(t("Copied Successfully")));
    };

    const showSelectedOnlyBtn = createEl("button", "anima-clothing-btn", t("Show Selected"));
    showSelectedOnlyBtn.onclick = () => {
        showSelectedOnly = !showSelectedOnly;
        showSelectedOnlyBtn.classList.toggle("active", showSelectedOnly);
        currentPage = 1;
        triggerFilter();
    };

    const clearSelectedBtn = createEl("button", "anima-clothing-btn danger");
    clearSelectedBtn.innerHTML = `${trashIcon()} ${t("Clear Selected")}`;
    clearSelectedBtn.onclick = () => {
        if (selectedClothing.size === 0) return;
        selectedClothing.clear();
        updateCountLabel();
        renderCurrentPage();
    };

    actionControls.appendChild(syncWeiLinBtn);
    actionControls.appendChild(copySelectedBtn);
    actionControls.appendChild(showSelectedOnlyBtn);
    actionControls.appendChild(clearSelectedBtn);
    toolbar.appendChild(filterControls);
    toolbar.appendChild(actionControls);
    container.appendChild(toolbar);

    const main = createEl("div");
    main.style.cssText = "display: flex; flex: 1; min-height: 0; background: var(--uw-panel);";

    const sidebar = createEl("aside", "anima-clothing-scrollbar");
    sidebar.style.cssText = `
        width: 280px;
        flex: 0 0 280px;
        overflow-y: auto;
        padding: 18px 12px 18px 16px;
        border-right: 1px solid var(--uw-border);
        background: var(--uw-panel);
        box-sizing: border-box;
    `;
    sidebar.onscroll = () => localStorage.setItem(SIDEBAR_SCROLL_STORAGE_KEY, sidebar.scrollTop);

    const gridArea = createEl("div");
    gridArea.style.cssText = "flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0;";

    const activeFilterSummary = createEl("div", "anima-clothing-active-filters");
    activeFilterSummary.setAttribute("role", "group");
    activeFilterSummary.setAttribute("aria-label", "生效中的筛选条件");
    activeFilterSummary.style.cssText = "flex:0 0 auto;padding:10px 16px;border-bottom:1px solid var(--uw-border);font-size:12px;max-height:120px;overflow:auto;";
    activeFilterSummary.hidden = true;
    gridArea.appendChild(activeFilterSummary);

    const listContainer = createEl("div", "anima-clothing-scrollbar");
    listContainer.style.cssText = `
        flex: 1;
        overflow-y: auto;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        grid-auto-rows: 340px;
        justify-content: stretch;
        gap: 20px;
        align-content: start;
        padding: 24px 28px;
        min-height: 0;
    `;
    listContainer.onscroll = () => localStorage.setItem(SCROLL_STORAGE_KEY, listContainer.scrollTop);

    const imageObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const img = entry.target;
            if (img.dataset.lazySrc) {
                img.src = img.dataset.lazySrc;
                delete img.dataset.lazySrc;
            }
            imageObserver.unobserve(img);
        });
    }, { root: listContainer, rootMargin: "320px" });

    const pagination = createEl("div", "anima-clothing-pagination");

    const pageStats = createEl("div", "anima-clothing-pagination-stats");

    const pageControls = createEl("div", "anima-clothing-pagination-controls");

    const firstBtn = createEl("button", "anima-clothing-page-btn", t("First"));
    const prevBtn = createEl("button", "anima-clothing-page-btn", t("Prev"));
    const nextBtn = createEl("button", "anima-clothing-page-btn", t("Next"));
    const lastBtn = createEl("button", "anima-clothing-page-btn", t("Last"));
    const pageNumContainer = createEl("div", "anima-clothing-page-number");
    const pageInput = createEl("input", "anima-clothing-page-input");
    pageInput.type = "text";
    pageInput.setAttribute("aria-label", t("Page number"));
    const totalPagesLabel = createEl("span");

    firstBtn.onclick = () => goToPage(1);
    prevBtn.onclick = () => goToPage(currentPage - 1);
    nextBtn.onclick = () => goToPage(currentPage + 1);
    lastBtn.onclick = () => goToPage(totalPages);
    pageInput.onkeydown = (event) => {
        if (event.key !== "Enter") return;
        const page = parseInt(pageInput.value, 10);
        if (!isNaN(page)) goToPage(page);
    };

    pageControls.appendChild(firstBtn);
    pageControls.appendChild(prevBtn);
    pageNumContainer.appendChild(pageInput);
    pageNumContainer.appendChild(totalPagesLabel);
    pageControls.appendChild(pageNumContainer);
    pageControls.appendChild(nextBtn);
    pageControls.appendChild(lastBtn);
    pagination.appendChild(pageStats);
    pagination.appendChild(pageControls);

    gridArea.appendChild(listContainer);
    gridArea.appendChild(pagination);
    main.appendChild(sidebar);
    main.appendChild(gridArea);
    container.appendChild(main);

    const footer = createEl("div");
    footer.style.cssText = `
        padding: 18px 26px;
        border-top: 1px solid var(--uw-border);
        background: var(--uw-panel);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
    `;

    const countLabel = createEl("button", "anima-clothing-btn active");
    countLabel.onclick = () => showSelectedOnlyBtn.click();

    const footerBtns = createEl("div");
    footerBtns.style.cssText = "display: flex; align-items: center; gap: 10px;";
    const cancelFooterBtn = createEl("button", "anima-clothing-btn", "关闭");
    cancelFooterBtn.onclick = () => closeModal();
    footerBtns.appendChild(cancelFooterBtn);
    const insertionControls = mountSelectorInsertionActions(footerBtns, {app, node, widget: tagsWidget, resolveText: buildValidatedSelection,
        kind: 'clothing', getSelectedItems: () => [...selectedClothing].map(key => key.startsWith('custom:')
            ? favoriteItems.find(item => item.isCustom && getItemKey(item) === key) : dataById.get(key))});
    footer.style.flexWrap = 'wrap';
    footer.appendChild(countLabel);
    footer.appendChild(footerBtns);
    container.appendChild(footer);

    overlay.appendChild(container);
    document.body.appendChild(overlay);
    const sharedResourceActions = appendSharedResourceActions(headerActions, {overlay:overlay, kind:'clothing',
        getCollection:() => groups.some(group => group.id === activeFilters.collection) ? activeFilters.collection : null,
        reopen:async () => { await reopenSelector(overlay, () => openClothingSelectorModal(node, tagsWidget, selectedClothing)); } });
    const stopLibrarySync = watchSharedLibrary(overlay, 'clothing', async () => { await reopenSelector(overlay, () => openClothingSelectorModal(node, tagsWidget, selectedClothing)); }, () => favoritesSaveInFlight || insertionControls.apply.disabled);

    let searchTimer;
    searchInput.addEventListener("input", () => {
        clearTimeout(searchTimer);
        updateClearFiltersButtonState();
        searchTimer = setTimeout(() => {
            if (isClosed) return;
            currentPage = 1;
            triggerFilter();
        }, 140);
    });

    function renderSidebar() {
        sidebar.innerHTML = "";
        const clearFiltersBtn = createEl("button", "anima-clothing-clear-filters-btn");
        clearFiltersBtn.type = "button";
        clearFiltersBtn.innerHTML = `
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
            <span>${t("Clear Filters")}</span>
        `;
        clearFiltersBtn.disabled = !hasActiveSidebarFilters();
        clearFiltersBtn.onclick = clearSidebarFilters;
        sidebar.appendChild(clearFiltersBtn);

        sidebar.appendChild(collectionsSectionHeader());

        const collectionsContent = createEl("div");
        collectionsContent.style.cssText = collectionsCollapsed ? "display: none;" : "display: flex; flex-direction: column;";
        if (!collectionsCollapsed) {
            const allItem = sidebarItem(t("All Clothing"), (activeFilters.collection === "all" || activeFilters.collection === "weilin") && activeFilters.categories.size === 0, clothingData.length);
            allItem.onclick = () => switchCollection("all");
            collectionsContent.appendChild(allItem);

            const defaultCount = favoriteItems.filter(item => item.groupIds?.includes("default")).length;
            const defaultItem = sidebarItem(t("My Favorites"), activeFilters.collection === "default", defaultCount);
            defaultItem.onclick = () => switchCollection("default");
            collectionsContent.appendChild(defaultItem);

            groups.filter(group => group.id !== "default").forEach(group => {
                const groupCount = favoriteItems.filter(item => item.groupIds?.includes(group.id)).length;
                const row = sidebarItem(group.name, activeFilters.collection === group.id, groupCount);
                row.onclick = () => switchCollection(group.id);
                const tools = createEl("span");
                tools.style.cssText = "display: inline-flex; gap: 5px;";
                const rename = createEl("button");
                rename.title = t("Rename Group");
                rename.innerHTML = editIcon();
                rename.style.cssText = miniToolStyle();
                rename.onclick = event => { event.stopPropagation(); sharedResourceActions.collections({groupId:group.id, action:'rename'}); };
                const del = createEl("button");
                del.title = t("Delete Group");
                del.innerHTML = trashIcon(12);
                del.style.cssText = miniToolStyle("var(--uw-danger)");
                del.onclick = event => { event.stopPropagation(); sharedResourceActions.collections({groupId:group.id, action:'delete'}); };
                tools.appendChild(rename);
                tools.appendChild(del);
                row.appendChild(tools);
                collectionsContent.appendChild(row);
            });
        }
        sidebar.appendChild(collectionsContent);

        appendSharedCategoryTree({
            kind: 'clothing',
            sidebar,
            items: clothingData,
            selectedFilters: activeFilters.categories,
            rowClass: "anima-clothing-sidebar-item",
            storageKey: SHARED_CATEGORIES_COLLAPSE_STORAGE_KEY,
            onFilterChange: () => {
                activeFilters.collection = "weilin";
                showSelectedOnly = false;
                showSelectedOnlyBtn.classList.remove("active");
                currentPage = 1;
                persistFilters();
                updateClearFiltersButtonState();
                renderSidebar();
                triggerFilter();
            },
        });

        if (allTraits.length > 0) {
            const traitSection = createEl("details", "anima-clothing-traits-section");
            traitSection.open = !traitsCollapsed;
            const traitHeader = createEl("summary", "anima-clothing-section-header foldable");
            const traitTitle = createEl("span", "anima-clothing-section-title", "附加标签");
            const traitCount = createEl("span", null, activeFilters.traits.size > 0 ? `${activeFilters.traits.size} / ${allTraits.length}` : String(allTraits.length));
            traitCount.style.cssText = "margin-left:auto;color:var(--uw-muted);font-size:11px;";
            traitHeader.appendChild(traitTitle);
            traitHeader.appendChild(traitCount);
            traitSection.appendChild(traitHeader);
            traitSection.ontoggle = () => {
                traitsCollapsed = !traitSection.open;
                localStorage.setItem(TRAITS_COLLAPSE_STORAGE_KEY, String(traitsCollapsed));
            };
            allTraits.forEach(trait => {
                const zh = displayLang === "bilingual" ? getTraitZh(trait.name, clothingData) : "";
                const label = displayLang === "bilingual" && zh ? `${trait.name} (${zh})` : trait.name;
                const row = createEl("label", "anima-clothing-check-row");
                row.innerHTML = `
                    <input type="checkbox" ${activeFilters.traits.has(trait.name) ? "checked" : ""}>
                    <span style="min-width:0;">${escapeHtml(label)} <span style="color:var(--uw-muted);">${trait.count}</span></span>
                `;
                row.querySelector("input").onchange = (event) => {
                    if (event.target.checked) {
                        if (activeFilters.collection !== "weilin") activeFilters.collection = "all";
                        activeFilters.traits.add(trait.name);
                    } else {
                        activeFilters.traits.delete(trait.name);
                    }
                    currentPage = 1;
                    persistFilters();
                    updateClearFiltersButtonState();
                    renderSidebar();
                    triggerFilter();
                };
                traitSection.appendChild(row);
            });
            sidebar.appendChild(traitSection);
        }

        if (lastSidebarScrollTop > 0) {
            sidebar.scrollTop = lastSidebarScrollTop;
            setTimeout(() => sidebar.scrollTop = lastSidebarScrollTop, 60);
        }
    }

    function collectionsSectionHeader() {
        const header = createEl("div", "anima-clothing-section-header foldable");
        const title = createEl("span", "anima-clothing-section-title", t("Collections"));
        const spacer = createEl("span", "anima-clothing-section-spacer");
        const addBtn = createEl("button", "anima-clothing-section-icon-btn");
        addBtn.type = "button";
        addBtn.title = t("Create Group");
        addBtn.innerHTML = "+";
        const arrow = createEl("span", `anima-clothing-section-arrow${collectionsCollapsed ? " collapsed" : ""}`);
        arrow.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`;

        addBtn.onclick = (event) => {
            event.stopPropagation();
            sharedResourceActions.collections({action:'create'});
        };
        header.onclick = () => {
            collectionsCollapsed = !collectionsCollapsed;
            localStorage.setItem(COLLECTIONS_COLLAPSE_STORAGE_KEY, String(collectionsCollapsed));
            renderSidebar();
        };

        header.appendChild(title);
        header.appendChild(spacer);
        header.appendChild(addBtn);
        header.appendChild(arrow);
        return header;
    }


    function sidebarItem(label, active, count) {
        const row = createEl("div", `anima-clothing-sidebar-item${active ? " active" : ""}`);
        const nameSpan = createEl("span", null, label);
        nameSpan.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;";
        const countSpan = createEl("span", null, String(count || 0));
        countSpan.style.cssText = "color:var(--uw-muted);font-size:11px;flex:0 0 auto;";
        row.appendChild(nameSpan);
        row.appendChild(countSpan);
        return row;
    }

    function switchCollection(collection) {
        activeFilters.collection = collection;
        removeSharedCategoryFilters(activeFilters.categories);
        currentPage = 1;
        listContainer.scrollTop = 0;
        persistFilters();
        renderSidebar();
        triggerFilter();
    }

    function hasActiveSidebarFilters() {
        return searchInput.value.trim() !== "" ||
            activeFilters.collection !== "all" ||
            activeFilters.categories.size > 0 ||
            activeFilters.traits.size > 0;
    }

    function updateClearFiltersButtonState() {
        const clearFiltersBtn = sidebar.querySelector(".anima-clothing-clear-filters-btn");
        if (clearFiltersBtn) {
            clearFiltersBtn.disabled = !hasActiveSidebarFilters();
        }
    }

    function clearSidebarFilters() {
        if (!hasActiveSidebarFilters()) return;
        clearTimeout(searchTimer);
        searchInput.value = "";
        activeFilters.collection = "all";
        activeFilters.categories.clear();
        activeFilters.traits.clear();
        currentPage = 1;
        listContainer.scrollTop = 0;
        persistFilters();
        renderSidebar();
        triggerFilter();
        searchInput.focus();
    }

    function renderActiveFilterSummary() {
        activeFilterSummary.replaceChildren();
        const query = searchInput.value.trim();
        const sources = Array.from(activeFilters.categories).filter(value => value.startsWith("shared-source:"));
        const categoryFilters = new Set(Array.from(activeFilters.categories).filter(value => !value.startsWith("shared-source:")));
        activeFilterSummary.hidden = showSelectedOnly || (!query && !sources.length && !activeFilters.traits.size);
        if (activeFilterSummary.hidden) return;

        const categoryTotal = categoryFilters.size
            ? clothingData.filter(item => itemMatchesCategoryFilters(item, categoryFilters, normalizeCategoryValue)).length
            : null;
        const status = createEl("div", null, categoryTotal === null
            ? `额外筛选 · 当前 ${filteredData.length} 条`
            : `分类共 ${categoryTotal} 条 · 筛选后 ${filteredData.length} 条`);
        status.style.cssText = "color:var(--uw-muted);margin-bottom:6px;";
        activeFilterSummary.appendChild(status);
        const controls = createEl("div");
        controls.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:6px;";
        activeFilterSummary.appendChild(controls);

        const removeFilter = action => {
            action();
            currentPage = 1;
            listContainer.scrollTop = 0;
            persistFilters();
            renderSidebar();
            triggerFilter();
            searchInput.focus();
        };
        const addFilter = (label, action) => {
            const control = createEl("button", "anima-clothing-btn", `${label} ×`);
            control.type = "button";
            control.setAttribute("aria-label", `移除${label}筛选`);
            control.title = `移除${label}筛选`;
            control.style.cssText = "max-width:100%;white-space:normal;overflow-wrap:anywhere;text-align:left;";
            control.onclick = () => removeFilter(action);
            controls.appendChild(control);
        };
        if (query) addFilter(`搜索：${query}`, () => { clearTimeout(searchTimer); searchInput.value = ""; });
        sources.forEach(value => addFilter(`来源：${sourceLabels.get(value.slice("shared-source:".length)) || value.slice("shared-source:".length)}`, () => activeFilters.categories.delete(value)));
        activeFilters.traits.forEach(trait => addFilter(`附加标签：${trait}`, () => activeFilters.traits.delete(trait)));
        if (categoryFilters.size) {
            const browseCategory = createEl("button", "anima-clothing-btn", "只看当前分类");
            browseCategory.type = "button";
            browseCategory.title = "保留当前主题或小主题，解除搜索、来源和附加标签限制";
            browseCategory.onclick = () => removeFilter(() => {
                clearTimeout(searchTimer);
                searchInput.value = "";
                sources.forEach(value => activeFilters.categories.delete(value));
                activeFilters.traits.clear();
            });
            controls.appendChild(browseCategory);
        }
    }

    const stableRandomOrder = createStablePromptShuffle(getItemKey);

    function triggerFilter() {
        if (isClosed) return;
        const query = searchInput.value.toLowerCase().trim();
        const searchAliases = item => [favoriteMap.get(getItemKey(item))?.nickname];
        const aliases = {};
        let queryList = query ? [query] : [];
        for (const [key, values] of Object.entries(aliases)) {
            if (query.includes(key)) queryList = queryList.concat(values);
        }

        let items = [];
        let customItems = [];
        if (showSelectedOnly) {
            customItems = favoriteItems.filter(item => item.isCustom && selectedClothing.has(getItemKey(item)));
            items = clothingData.filter(item => selectedClothing.has(getItemKey(item)));
        } else {
            const groupIds = new Set();
            if (activeFilters.collection !== "all" && activeFilters.collection !== "weilin") {
                favoriteItems.forEach(item => {
                    if (item.groupIds?.includes(activeFilters.collection) && !item.isCustom) {
                        groupIds.add(getItemKey(item));
                    }
                });
            }

            items = clothingData.filter(item => {
                if (activeFilters.collection === "weilin" && !item?.shared) return false;
                if (activeFilters.collection !== "all" &&
                    activeFilters.collection !== "weilin" &&
                    !groupIds.has(getItemKey(item))) return false;

                if (queryList.length > 0) {
                    if (!queryList.some(q => Number.isFinite(getPromptSearchRank(item, q, searchAliases(item))))) return false;
                }

                if (activeFilters.categories.size > 0) {
                    if (!itemMatchesCategoryFilters(item, activeFilters.categories, normalizeCategoryValue)) return false;
                }

                if (activeFilters.traits.size > 0) {
                    const traits = getAdditionalClothingTraits(item);
                    if (!Array.from(activeFilters.traits).every(trait => traits.includes(trait))) return false;
                }

                return true;
            });

            if (activeFilters.collection === "weilin") {
                customItems = [];
            } else if (activeFilters.collection !== "all") {
                customItems = favoriteItems.filter(item => item.isCustom && item.groupIds?.includes(activeFilters.collection));
            } else {
                customItems = favoriteItems.filter(item => item.isCustom);
            }

            if (queryList.length > 0) {
                customItems = customItems.filter(item => {
                    return queryList.some(q => Number.isFinite(getPromptSearchRank(item, q, searchAliases(item))));
                });
            }
        }

        if (activeSort === "id-desc") {
            items.sort((a, b) => getItemKey(b).localeCompare(getItemKey(a)));
        } else if (activeSort === "id-asc") {
            items.sort((a, b) => getItemKey(a).localeCompare(getItemKey(b)));
        } else if (activeSort === "name-asc") {
            items.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
        } else if (activeSort === "name-desc") {
            items.sort((a, b) => String(b.name || "").localeCompare(String(a.name || "")));
        } else if (activeSort === "favorite-desc") {
            items.sort((a, b) => Number(favoriteSet.has(getItemKey(b))) - Number(favoriteSet.has(getItemKey(a))) || String(a.name || "").localeCompare(String(b.name || "")));
        } else if (activeSort === "random") {
            items = stableRandomOrder(items);
        }

        filteredData = rankPromptSearchResults([...customItems, ...items], showSelectedOnly ? "" : query, searchAliases);
        totalPages = Math.max(1, Math.ceil(filteredData.length / 48));
        currentPage = Math.max(1, Math.min(currentPage, totalPages));
        localStorage.setItem(PAGE_STORAGE_KEY, currentPage);
        renderActiveFilterSummary();
        updatePaginationBar();
        renderCurrentPage();
    }

    function updatePaginationBar() {
        const total = filteredData.length;
        const start = total === 0 ? 0 : (currentPage - 1) * 48 + 1;
        const end = Math.min(currentPage * 48, total);
        pageStats.innerText = t("Total {total} clothing items | Showing {start}-{end}", { total, start, end });
        pageInput.value = String(currentPage);
        totalPagesLabel.innerText = `/ ${totalPages}`;
        firstBtn.disabled = currentPage <= 1;
        prevBtn.disabled = currentPage <= 1;
        nextBtn.disabled = currentPage >= totalPages;
        lastBtn.disabled = currentPage >= totalPages;
    }

    function goToPage(page) {
        if (page < 1 || page > totalPages) {
            pageInput.value = String(currentPage);
            return;
        }
        currentPage = page;
        localStorage.setItem(PAGE_STORAGE_KEY, currentPage);
        lastScrollTop = 0;
        listContainer.scrollTop = 0;
        localStorage.setItem(SCROLL_STORAGE_KEY, 0);
        updatePaginationBar();
        renderCurrentPage();
    }

    function renderCurrentPage() {
        if (isClosed) return;
        imageObserver.disconnect();
        listContainer.innerHTML = "";
        const isCustomGroup = !showSelectedOnly &&
            activeFilters.collection !== "all" &&
            activeFilters.collection !== "default" &&
            activeFilters.collection !== "weilin";

        if (filteredData.length === 0 && !isCustomGroup) {
            const empty = createEl("div");
            empty.style.cssText = "grid-column:1/-1; padding:70px 20px; text-align:center; color:var(--uw-muted);";
            empty.innerHTML = `
                <div style="font-size:38px;font-weight:900;color:${THEME.accentText};margin-bottom:12px;">0</div>
                <div style="font-size:16px;font-weight:800;color:#fff;">${escapeHtml(t("No matching clothing items found"))}</div>
                <div style="font-size:13px;margin-top:8px;">${escapeHtml(activeFilterSummary.hidden ? t("Try another search or clear filters.") : "上方列出了仍在生效的筛选条件，可逐项解除。")}</div>
            `;
            if (hasActiveSidebarFilters()) {
                const clearBtn = createEl("button", "anima-clothing-btn", t("Clear Filters"));
                clearBtn.type = "button";
                clearBtn.style.marginTop = "16px";
                clearBtn.onclick = clearSidebarFilters;
                empty.appendChild(clearBtn);
            }
            listContainer.appendChild(empty);
            updateCountLabel();
            return;
        }

        const fragment = document.createDocumentFragment();
        const pageItems = filteredData.slice((currentPage - 1) * 48, currentPage * 48);
        if (isCustomGroup && currentPage === 1) {
            fragment.appendChild(createCustomPlaceholderCard());
        }
        pageItems.forEach((item, index) => fragment.appendChild(createCard(item, index)));
        listContainer.appendChild(fragment);

        if (lastScrollTop > 0) {
            listContainer.scrollTop = lastScrollTop;
            setTimeout(() => listContainer.scrollTop = lastScrollTop, 50);
            lastScrollTop = 0;
        }
        updateCountLabel();
    }

    function createCustomPlaceholderCard() {
        const card = createEl("article", "anima-clothing-create-card");
        const content = createEl("div", "anima-clothing-create-card-content");
        content.innerHTML = `
            <div style="font-size:46px;line-height:1;font-weight:300;">+</div>
            <div style="font-size:13.5px;font-weight:800;">${escapeHtml(t("Create Custom Item"))}</div>
        `;
        card.appendChild(content);
        card.onclick = event => {
            event.stopPropagation();
            sharedResourceActions.create();
        };
        return card;
    }

    function createCard(item, index = 0) {
        const key = getItemKey(item);
        const isSelected = selectedClothing.has(key);
        const isFavorite = !item.isCustom && favoriteSet.has(key);
        const favInfo = item.isCustom ? item : favoriteMap.get(key);
        const nickname = favInfo?.nickname || "";

        const card = createEl("article", `anima-clothing-card${isSelected ? " selected" : ""}`);
        card.dataset.key = key;

        const clip = createEl("div", "anima-clothing-card-clip");
        card.appendChild(clip);

        const placeholder = createEl("div", "anima-clothing-placeholder");
        placeholder.innerText = item.isCustom ? "T" : (formatDisplayName(item, displayLang).trim().charAt(0).toUpperCase() || "?");
        clip.appendChild(placeholder);

        let loader = null;
        if (item.isCustom) {
            placeholder.innerHTML = `
                <div style="display:flex;flex-direction:column;align-items:center;gap:8px;">
                    <div style="font-size:42px;">T</div>
                    <div style="font-size:11px;font-weight:850;color:var(--uw-accent);background:var(--uw-accent-bg);border:1px solid var(--uw-accent-bg);border-radius:999px;padding:3px 9px;">CUSTOM</div>
                </div>
            `;
        } else if (item.preview) {
            const img = document.createElement("img");
            img.alt = item.name || "";
            const eagerPreview = index < 12;
            img.loading = eagerPreview ? "eager" : "lazy";
            img.decoding = "async";
            const imgUrl = getPersistentImageUrl(item.preview);
            if (eagerPreview || isImageLoaded(imgUrl)) {
                img.src = imgUrl;
                img.style.opacity = "1";
            } else {
                img.dataset.lazySrc = imgUrl;
                loader = createEl("div", "anima-clothing-shimmer");
                const spinner = createEl("div", "anima-clothing-spinner");
                loader.appendChild(spinner);
                clip.appendChild(loader);
            }
            img.onload = () => {
                img.style.opacity = "1";
                placeholder.style.opacity = "0";
                loader?.remove();
                markImageLoaded(imgUrl);
            };
            img.onerror = () => {
                img.remove();
                loader?.remove();
                placeholder.style.opacity = "1";
            };
            clip.appendChild(img);
            imageObserver.observe(img);
        }

        const selectedMark = createEl("div", "anima-clothing-selected-mark");
        selectedMark.innerHTML = isSelected ? checkIcon() : "";
        card.appendChild(selectedMark);

        if (item.isCustom) {
            const deleteBtn = iconButton(9, trashIcon(14), t("Delete Custom Item"));
            deleteBtn.onclick = async (event) => {
                event.stopPropagation();
                if (!confirm(t("Are you sure you want to delete this custom item?"))) return;
                favoriteItems = favoriteItems.filter(existing => existing.name !== item.name);
                selectedClothing.delete(key);
                if (!(await saveFavorites())) return;
                renderSidebar();
                triggerFilter();
            };
            card.appendChild(deleteBtn);
        } else {
            const favBtn = iconButton(9, heartIcon(isFavorite), `${t(isFavorite ? "Remove from Favorites" : "Add to Favorites")}: ${item.name}`);
            favBtn.classList.add("anima-favorite-btn");
            favBtn.setAttribute("aria-pressed", String(isFavorite));
            favBtn.dataset.favoriteSourceKey = getPromptFavoriteSourceKey(item, clothingData);
            favBtn.onclick = async (event) => {
                event.stopPropagation();
                toggleFavorite(item);
                if (!(await saveFavorites())) return;
                renderSidebar();
                if (activeFilters.collection !== "all" || activeSort === "favorite-desc") triggerFilter();
                else renderCurrentPage();
            };
            card.appendChild(favBtn);
        }


        const mask = createEl("div", "anima-clothing-card-mask");
        clip.appendChild(mask);

        const tagsOverlay = createEl("div", "anima-clothing-tags-overlay");
        const promptTags = splitPromptTokens(item.isCustom ? item.customContent : item.tags);
        const promptTagsZh = splitPromptTokens(item.tags_zh);
        const titleBtn = createEl("button", "anima-clothing-tags-title");
        titleBtn.innerHTML = `
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(t("Prompt Tags"))} · ${promptTags.length}</span>
            <span style="font-size:10px;color:var(--uw-accent);flex:0 0 auto;">${escapeHtml(t("Copy"))}</span>
        `;
        titleBtn.onclick = (event) => {
            event.stopPropagation();
            const text = promptTags.length ? `${promptTags.join(", ")}, ` : "";
            if (text) copyText(text, () => showToast(t("Copied Successfully")));
        };
        tagsOverlay.appendChild(titleBtn);

        const tagsList = createEl("div", "anima-clothing-tags-list");
        promptTags.forEach((tag, index) => {
            const zh = promptTagsZh[index] || "";
            const displayTag = displayLang === "bilingual" && zh ? `${tag} (${zh})` : tag;
            const pill = createEl("span", "anima-clothing-tag-pill", displayTag);
            pill.title = displayTag;
            pill.onclick = (event) => {
                event.stopPropagation();
                copyText(tag, () => showToast(t("Copied: {text}", { text: tag })));
            };
            tagsList.appendChild(pill);
        });
        tagsOverlay.appendChild(tagsList);
        clip.appendChild(tagsOverlay);

        const info = createEl("div", "anima-clothing-card-info");
        const titleEl = createEl("div", "anima-clothing-card-title");
        const displayName = formatDisplayName(item, displayLang);
        titleEl.innerText = displayName;
        titleEl.title = item.isCustom ? item.customContent || "" : `${item.name_zh || ""}${item.name_zh ? " / " : ""}${item.name || ""}`;
        const subEl = createEl("div", "anima-clothing-card-sub");
        if (item.isCustom) {
            subEl.innerText = t("Custom");
        } else if (item.shared) {
            const sourceLabel = item.shared_source_category || item.source_category || "";
            subEl.innerText = sourceLabel ? `WeiLin · ${sourceLabel}` : "WeiLin";
        } else if (displayLang === "bilingual" && item.name_zh) {
            subEl.innerText = item.name || "";
        } else {
            const firstCategory = Array.isArray(item.categories) && item.categories.length > 0 ? item.categories[0] : "";
            subEl.innerText = firstCategory ? getCategoryLabel(firstCategory, "en") : String(item.id || "");
        }

        if (nickname && !item.isCustom) {
            const note = createEl("div", "anima-clothing-card-sub", nickname);
            note.style.color = THEME.accentText;
            info.appendChild(titleEl);
            info.appendChild(note);
        } else {
            info.appendChild(titleEl);
        }
        if (!item.shared) info.appendChild(subEl);
        appendSharedResourceEditor(card, item, async () => {
            await reopenSelector(overlay, () => openClothingSelectorModal(node, tagsWidget, selectedClothing));
        }, info);

        clip.appendChild(info);

        card.onclick = () => {
            if (selectedClothing.has(key)) selectedClothing.delete(key);
            else selectedClothing.add(key);
            updateCardSelection(card, selectedClothing.has(key));
            updateCountLabel();
        };

        return card;
    }

    function updateCardSelection(card, selected) {
        card.classList.toggle("selected", selected);
        const mark = card.querySelector(".anima-clothing-selected-mark");
        if (mark) mark.innerHTML = selected ? checkIcon() : "";
    }

    function badge(text) {
        const el = createEl("span", "anima-clothing-badge", text);
        el.title = text;
        return el;
    }

    function iconButton(top, html, titleText) {
        const btn = createEl("button", "anima-clothing-icon-btn");
        btn.type = "button";
        btn.style.top = `${top}px`;
        btn.innerHTML = html;
        btn.title = titleText;
        btn.setAttribute("aria-label", titleText);
        return btn;
    }

    function toggleFavorite(item) {
        const key = getItemKey(item);
        if (favoriteSet.has(key)) {
            favoriteSet.delete(key);
            const fav = favoriteMap.get(key);
            if (fav) fav.groupIds = [];
        } else {
            favoriteSet.add(key);
            let fav = favoriteMap.get(key);
            if (!fav) {
                fav = { id: item.id, name: item.name, selectorKey: key, nickname: "", groupIds: ["default"], isCustom: false };
                favoriteMap.set(key, fav);
            } else if (!Array.isArray(fav.groupIds) || fav.groupIds.length === 0) {
                fav.groupIds = ["default"];
            }
        }
    }




    function createModalShell(maxWidth = 400) {
        return createSharedModalShell({
            maxWidth,
            animationName: "animaClothingFadeIn",
        });
    }

    function modalButtons(dialog, onConfirm, confirmText = t("OK")) {
        return createModalButtons({
            dialog,
            onConfirm,
            cancelText: t("Cancel"),
            confirmText,
            buttonClass: "anima-clothing-btn",
        });
    }

    function buildSelectedText(frozenItems = null) {
        const selectedItems = frozenItems || [...selectedClothing].map(key => key.startsWith("custom:")
            ? favoriteItems.find(item => item.isCustom && getItemKey(item) === key)
            : dataById.get(key));
        if (selectedItems.some(item => item?.shared)) {
            return selectedItems.map(item => item?.shared ? item.tags
                : splitPromptTokens(item?.customContent || item?.tags || "").join(", ")).join("\n");
        }
        const tags = [];
        selectedClothing.forEach(key => {
            if (key.startsWith("custom:")) {
                const item = favoriteItems.find(fav => fav.isCustom && getItemKey(fav) === key);
                splitPromptTokens(item?.customContent || "").forEach(tag => tags.push(tag));
                return;
            }
            const item = dataById.get(key);
            splitPromptTokens(item?.tags || "").forEach(tag => tags.push(tag));
        });
        return tags.length ? `${tags.join(", ")}, ` : "";
    }

    let isClosed = false;
    async function buildValidatedSelection() {
        if (isClosed) throw new Error("选择器已关闭，请重新打开。");
        const previousText = tagsWidget?.value;
        const keys = [...selectedClothing];
        const selectedItems = keys.map(key => key.startsWith("custom:")
            ? favoriteItems.find(item => item.isCustom && getItemKey(item) === key)
            : dataById.get(key)).map(item => item ? structuredClone(item) : item);
        assertPromptTarget();
        if (selectedItems.some(item => !item)) throw new Error("所选资料已不可用，请重新选择。");
        await validateSharedPromptSelection('clothing', selectedItems);
        if (isClosed) throw new Error("选择器已关闭，请重新打开。");
        assertPromptTarget();
        if (JSON.stringify(keys) !== JSON.stringify([...selectedClothing])) {
            throw new Error("选择已变化，请再次点击应用。");
        }
        if (tagsWidget?.value !== previousText) {
            throw new Error("目标正文已变化，请确认当前内容后再次应用。");
        }
        return buildSelectedText(selectedItems);
    }

    function updateCountLabel() {
        countLabel.innerHTML = `${checkIcon()} <span>${t("Selected: {count} clothing items", { count: selectedClothing.size })}</span>`;
    }

    function closeModal() {
        if (isClosed) return;
        clearTimeout(searchTimer);
        stopLibrarySync();
        isClosed = true;
        insertionControls.dispose();
        imageObserver.disconnect();
        document.getElementById("anima-clothing-group-popover")?.remove();
        overlay.remove();
        disposeDialog();
        styleSheet.remove();
    }

    function showToast(message) {
        return showSharedToast(message, {
            borderColor: "var(--uw-accent)",
        });
    }

    function miniToolStyle(color = "var(--uw-text)") {
        return `border:0;background:transparent;color:${color};padding:2px;cursor:pointer;line-height:0;`;
    }

    function checkIcon(size = 14) {
        return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    }

    function heartIcon(filled) {
        return `<svg width="15" height="15" viewBox="0 0 24 24" fill="${filled ? THEME.accent : "none"}" stroke="${filled ? THEME.accent : "currentColor"}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 0 0 0-7.78z"></path></svg>`;
    }

    function editIcon(size = 14) {
        return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"></path></svg>`;
    }

    function folderIcon(size = 14) {
        return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>`;
    }

    function trashIcon(size = 14) {
        return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"></path><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>`;
    }

    function copyIcon(size = 14) {
        return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;
    }

    renderSidebar();
    triggerFilter();
    updateCountLabel();
    const disposeDialog = installSelectorDialog(overlay, {label:t("Anima Clothing Tag Selector"), initialFocus:searchInput, close:closeModal});
    overlay.unifiedFocus();
}
