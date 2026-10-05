import { capturePromptTarget, appendUnresolvedPromptFavorites } from "./anima_prompt_identity.js";
import { app } from "../../scripts/app.js";
import { t } from "./i18n.js";
import { getPersistentImageUrl, markImageLoaded, isImageLoaded } from "./anima_image_utils.js";
import {
    appendSharedCategoryTree,
    appendSharedResourceEditor, appendSharedResourceActions, watchSharedLibrary,
    getSharedPromptSyncMessage,
    hasSharedCategoryFilters,
    isSharedCategoryFilter,
    itemMatchesCategoryFilters,
    loadMergedPromptItems,
    loadSharedPromptIndexItems,
    loadSharedPromptItems,
    validateSharedPromptSelection,
    mergePromptItems,
    normalizeSharedCategoryNavigationFilters,
    pruneSharedCategoryFilters,
    removeSharedCategoryFilters,
    refreshMergedPromptItems,
    getPromptSearchRank,
    rankPromptSearchResults,
    createStablePromptShuffle,
} from "./anima_shared_prompt_data.js";
import { createPromoLinks } from "./anima_promo_links.js";
import { assignPromptSelectorKeys, getPromptItemBaseKey, getPromptItemKey, getPromptItemVariantKey, getPromptFavoriteSourceKey, resolvePromptFavorites } from "./anima_prompt_identity.js";
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
    "Gestures & Arms",
    "Standing & Dynamic",
    "Sitting Poses",
    "Lying & Prone",
    "Adjusting & Dressing",
    "Props & Holding",
    "Duo & Interaction",
    "Daily & Miscellaneous",
];

const POSE_SELECTOR_CONFIG = {
    kind: "pose",
    favoritesKey: "pose",
    storagePrefix: "anima-pose-selector",
    categories: [],
    getLocalData: () => [],
    loadAllOnOpen: true,
    title: "Anima Pose Tag Selector",
    subtitle: "Browse and select pose prompt tags with visual preview cards.",
    searchPlaceholder: "Search pose or tags...",
    allItemsLabel: "All Poses",
    selectedCountLabel: "Selected: {count} poses",
    totalLabel: "Total {total} poses | Showing {start}-{end}",
    emptyLabel: "No matching poses found",
    selectionRequiredLabel: "Please select at least one pose first.",
    syncLabel: "动作 Tags",
};

const STYLE_QUALITY_SELECTOR_CONFIG = {
    kind: "style_quality",
    favoritesKey: "style_quality",
    storagePrefix: "anima-style-quality-selector",
    categories: [],
    getLocalData: () => [],
    loadAllOnOpen: true,
    title: "Anima Style / Quality Selector",
    subtitle: "Browse and select WeiLin style, quality and camera prompt tags.",
    searchPlaceholder: "Search style, quality or camera tags...",
    allItemsLabel: "All Style / Quality Tags",
    selectedCountLabel: "Selected: {count} tags",
    totalLabel: "Total {total} tags | Showing {start}-{end}",
    emptyLabel: "No matching style / quality tags found",
    selectionRequiredLabel: "Please select at least one style / quality item first.",
    syncLabel: "画风/质量 Tags",
};

app.registerExtension({
    name: "AnimaPoseTagSelector.extension",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        const isStyleQualitySelector = (
            nodeData.name === "AnimaStyleQualitySelector"
            || nodeData.name === "AnimaStyleQualitySelectorPlus"
        );
        const isPoseSelector = (
            nodeData.name === "AnimaPoseTagSelector"
            || nodeData.name === "AnimaPoseTagSelectorPlus"
            || isAnimaPromptPlusNode(nodeData.name)
        );
        if (isPoseSelector || isStyleQualitySelector) {
            installSelectorExecutionSync(nodeType);
            const origOnCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                origOnCreated?.apply(this, arguments);

                const selectorConfig = isStyleQualitySelector
                    ? STYLE_QUALITY_SELECTOR_CONFIG
                    : POSE_SELECTOR_CONFIG;
                const tagsWidgetName = isStyleQualitySelector
                    ? "style_quality_tags"
                    : "pose_tags";
                const tagsWidget = this.widgets.find(w => w.name === tagsWidgetName);
                if (!tagsWidget) return;
                addSelectorActionRow(this, {
                    section: selectorConfig.kind,
                    label: t(isStyleQualitySelector ? "Open Style / Quality Selector" : "Open Pose Selector"),
                    accent: THEME.accent,
                    accentText: THEME.accentText,
                    onOpen: async () => {
                        await openPoseSelectorModal(this, tagsWidget, null, selectorConfig);
                    },
                });
            };
        }
    }
});

function normalizeCategoryValue(category, categories = CATEGORY_LIST) {
    const text = String(category || "").trim();
    if (categories.includes(text)) return text;
    const englishPart = text.match(/\(([^)]+)\)$/)?.[1];
    if (englishPart && categories.includes(englishPart)) return englishPart;
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

export function openStyleQualitySelectorModal(node, tagsWidget) {
    return openPoseSelectorModal(node, tagsWidget, null, STYLE_QUALITY_SELECTOR_CONFIG);
}

export async function openPoseSelectorModal(node, tagsWidget, restoredSelection = null, selectorConfig = POSE_SELECTOR_CONFIG) {
    const assertPromptTarget = capturePromptTarget(node, tagsWidget, () => app.graph);
    const config = { ...POSE_SELECTOR_CONFIG, ...selectorConfig };
    const selectorCategories = Array.isArray(config.categories) ? config.categories : [];
    const sharedKind = config.kind;
    const favoritesKey = config.favoritesKey;
    const normalizeSelectorCategoryValue = category => normalizeCategoryValue(category, selectorCategories);
    const localPoseData = config.getLocalData();
    let poseData = assignPromptSelectorKeys(localPoseData);
    let dataById = new Map(poseData.map(item => [getItemKey(item), item]));
    let sharedIndexItems = [];
    const sharedLoadedItems = new Map();
    const loadedSharedFilters = new Set();
    let loadingSharedFilter = "";
    const sharedPoseIndexPromise = (
        config.loadAllOnOpen
            ? loadSharedPromptItems(sharedKind)
            : loadSharedPromptIndexItems(sharedKind)
    )
        .catch(error => {
            console.warn(`[Anima Tools] Failed to load WeiLin ${sharedKind} data`, error);
            return [];
        });
    // Keep selection one-way: existing node text should not auto-check cards in the modal.
    const selectedPose = restoredSelection instanceof Set
        ? new Set(restoredSelection)
        : new Set();
    let isClosed = false;

    let favoritesEtag = null;
    let favoritesSaveInFlight = false;
    let favoritesConfig = {
        [favoritesKey]: {
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
        console.error(`[Anima Tools] Failed to load ${sharedKind} favorites`, e);
    }

    if (!favoritesConfig[favoritesKey]) {
        favoritesConfig[favoritesKey] = {
            groups: [{ id: "default", name: t("My Favorites"), isSystem: true }],
            items: [],
        };
    }

    let groups = Array.isArray(favoritesConfig[favoritesKey].groups) && favoritesConfig[favoritesKey].groups.length
        ? favoritesConfig[favoritesKey].groups
        : [{ id: "default", name: t("My Favorites"), isSystem: true }];
    if (!groups.some(group => group.id === "default")) {
        groups = [{ id: "default", name: t("My Favorites"), isSystem: true }, ...groups];
    }

    let favoriteItems = Array.isArray(favoritesConfig[favoritesKey].items) ? favoritesConfig[favoritesKey].items : [];
    const resolvedFavorites = resolvePromptFavorites(poseData, favoriteItems);
    const favoriteMap = resolvedFavorites.map;
    const favoriteSet = resolvedFavorites.set;
    const unresolvedFavoriteItems = resolvedFavorites.unresolved;
    const validSelectionKeys = new Set([
        ...poseData.map(getItemKey),
        ...favoriteItems.filter(item => item.isCustom).map(getItemKey),
    ]);
    for (const key of Array.from(selectedPose)) {
        if (!validSelectionKeys.has(key) && !String(key).startsWith("shared:weilin:") && !String(key).startsWith("weilin:")) selectedPose.delete(key);
    }

    const SORT_STORAGE_KEY = `${config.storagePrefix}-active-sort`;
    const PAGE_STORAGE_KEY = `${config.storagePrefix}-active-page`;
    const SCROLL_STORAGE_KEY = `${config.storagePrefix}-active-scroll`;
    const SIDEBAR_SCROLL_STORAGE_KEY = `${config.storagePrefix}-sidebar-scroll`;
    const DISPLAY_LANG_STORAGE_KEY = `${config.storagePrefix}-display-lang`;
    const FILTER_STORAGE_KEY = `${config.storagePrefix}-filters`;
    const SHARED_PATH_STORAGE_VERSION = 2;
    const COLLECTIONS_COLLAPSE_STORAGE_KEY = `${config.storagePrefix}-collections-collapsed`;
    const BUILTIN_CATEGORIES_COLLAPSE_STORAGE_KEY = `${config.storagePrefix}-builtin-categories-collapsed`;
    const SHARED_CATEGORIES_COLLAPSE_STORAGE_KEY = `${config.storagePrefix}-shared-categories-collapsed-v2`;

    let activeSort = localStorage.getItem(SORT_STORAGE_KEY) || "id-asc";
    let displayLang = localStorage.getItem(DISPLAY_LANG_STORAGE_KEY) || "en";
    let currentPage = parseInt(localStorage.getItem(PAGE_STORAGE_KEY), 10) || 1;
    let showSelectedOnly = false;
    let filteredData = [];
    let totalPages = 1;
    let lastScrollTop = parseInt(localStorage.getItem(SCROLL_STORAGE_KEY), 10) || 0;
    let lastSidebarScrollTop = parseInt(localStorage.getItem(SIDEBAR_SCROLL_STORAGE_KEY), 10) || 0;
    let collectionsCollapsed = localStorage.getItem(COLLECTIONS_COLLAPSE_STORAGE_KEY) === "true";
    let builtinCategoriesCollapsed = localStorage.getItem(BUILTIN_CATEGORIES_COLLAPSE_STORAGE_KEY) !== "false";

    const activeFilters = {
        categories: new Set(),
        traits: new Set(),
        collection: "all",
    };

    let migratedSharedPoseStorage = false;
    try {
        const saved = JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY) || "{}");
        if (Array.isArray(saved.categories)) saved.categories.forEach(v => activeFilters.categories.add(normalizeSelectorCategoryValue(v)));
        if (saved.collection) activeFilters.collection = saved.collection;
        if (
            Number(saved.sharedPathVersion || 0) !== SHARED_PATH_STORAGE_VERSION
            && hasSharedCategoryFilters(activeFilters.categories)
        ) {
            removeSharedCategoryFilters(activeFilters.categories);
            migratedSharedPoseStorage = true;
        }
    } catch (e) {
        console.warn("[Anima Tools] Failed to restore pose filters", e);
    }
    for (const category of [...activeFilters.categories]) {
        if (!String(category).startsWith('shared-')) {
            activeFilters.categories.delete(category);
            migratedSharedPoseStorage = true;
        }
    }
    if (selectorCategories.some(category => activeFilters.categories.has(category))) {
        builtinCategoriesCollapsed = false;
    }
    const canValidateSharedPoseFilters = poseData.some(item => item?.shared);
    const prunedSharedPoseFilters = canValidateSharedPoseFilters
        ? pruneSharedCategoryFilters(
            poseData,
            activeFilters.categories,
            normalizeSelectorCategoryValue,
        )
        : false;
    const normalizedSharedPoseFilters = canValidateSharedPoseFilters
        ? normalizeSharedCategoryNavigationFilters(
            activeFilters.categories,
            poseData,
        )
        : false;
    const reconciledSharedPoseState = (
        hasSharedCategoryFilters(activeFilters.categories)
        && activeFilters.collection !== "all"
    );
    if (hasSharedCategoryFilters(activeFilters.categories)) {
        activeFilters.collection = "all";
    }
    if (
        prunedSharedPoseFilters
        || normalizedSharedPoseFilters
        || reconciledSharedPoseState
        || migratedSharedPoseStorage
    ) {
        persistFilters();
    }

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
        favoritesConfig[favoritesKey].groups = groups;
        favoritesConfig[favoritesKey].items = favoriteItems;

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
            console.error(`[Anima Tools] Failed to save ${sharedKind} favorites`, e);
            try { return await offerFavoritesConflictRecovery(e.status || 0, saveOwner); }
            finally { favoritesSaveInFlight = false; }
        } finally {
            interactionOwners.forEach((element, index) => { element.inert = previousInert[index]; });
            restoreFavoriteFocus(favoritesSaved);
        }
    }

    async function offerFavoritesConflictRecovery(initialStatus, saveOwner) {
        const draftSection = JSON.parse(JSON.stringify(favoritesConfig[favoritesKey] || {}));
        return recoverFavoritesConflict({ partition: favoritesKey, draftSection, currentConfig: favoritesConfig, currentEtag: favoritesEtag, initialStatus, isActive: () => overlay.isConnected && (!saveOwner || saveOwner.isConnected), fetchLatest: () => fetch("/anima-tools/favorites"),
            submit: async (config, etag) => { const r = await fetch("/anima-tools/favorites", { method: "POST", headers: { "Content-Type": "application/json", "If-Match": etag || "" }, body: JSON.stringify(config) }); return { ok: r.ok, status: r.status, etag: r.headers.get("ETag") || etag }; },
            commit: (config, etag) => { favoritesConfig = config; favoritesEtag = etag; groups = config[favoritesKey].groups || groups; favoriteItems = config[favoritesKey].items || favoriteItems; }, t });
    }

    function persistFilters() {
        localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify({
            categories: Array.from(activeFilters.categories),
            traits: [],
            collection: activeFilters.collection,
            sharedPathVersion: SHARED_PATH_STORAGE_VERSION,
        }));
    }

    const styleSheet = createGallerySelectorStyleSheet("pose");
    document.head.appendChild(styleSheet);

    const overlay = createEl("div");
    overlay.id = "anima-pose-selector-overlay";
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
        animation: animaPoseFadeIn 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
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
    const title = createEl("div", null, t(config.title));
    title.style.cssText = "font-size: 20px; font-weight: 850; color: #fff; line-height: 1.2;";
    const subtitle = createEl("div", null, t(config.subtitle));
    subtitle.style.cssText = "font-size: 12.5px; color: var(--uw-muted); margin-top: 5px;";
    titleWrap.appendChild(title);
    titleWrap.appendChild(subtitle);
    appendUnresolvedPromptFavorites(titleWrap, unresolvedFavoriteItems);

    const searchInput = createEl("input", "anima-pose-input");
    searchInput.type = "search";
    searchInput.placeholder = t(config.searchPlaceholder);
    searchInput.value = "";
    searchInput.style.cssText += "flex: 1; min-width: 260px;";

    const closeBtn = createEl("button", "anima-pose-btn", t("Cancel"));
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

    const sortSelect = createEl("select", "anima-pose-select");
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

    const langSelect = createEl("select", "anima-pose-select");
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

    const syncWeiLinBtn = createEl("button", "anima-pose-btn", "同步 WeiLin");
    syncWeiLinBtn.title = "立即读取 WeiLin 的新增、修改、删除、分类和预览变化";
    syncWeiLinBtn.onclick = async () => {
        syncWeiLinBtn.disabled = true;
        syncWeiLinBtn.innerText = "同步中…";
        try {
            await refreshMergedPromptItems(
                sharedKind,
                config.getLocalData(),
            );
            if (isClosed) return;
            const selection = new Set(selectedPose);
            await reopenSelector(overlay, () => openPoseSelectorModal(node, tagsWidget, selection, config));
            showSharedToast(getSharedPromptSyncMessage(sharedKind, config.syncLabel));
        } catch (error) {
            if (isClosed) return;
            console.error(`[Anima Tools] WeiLin ${sharedKind} sync failed`, error);
            syncWeiLinBtn.disabled = false;
            syncWeiLinBtn.innerText = "同步 WeiLin";
            alert(`WeiLin 同步失败：${error?.message || error}`);
        }
    };

    const copySelectedBtn = createEl("button", "anima-pose-btn");
    copySelectedBtn.innerHTML = `${copyIcon()} ${t("Copy Selected")}`;
    copySelectedBtn.onclick = () => {
        const text = buildSelectedText();
        if (!text) {
            alert(t(config.selectionRequiredLabel));
            return;
        }
        copyText(text, () => showToast(t("Copied Successfully")));
    };

    const showSelectedOnlyBtn = createEl("button", "anima-pose-btn", t("Show Selected"));
    showSelectedOnlyBtn.onclick = () => {
        showSelectedOnly = !showSelectedOnly;
        showSelectedOnlyBtn.classList.toggle("active", showSelectedOnly);
        currentPage = 1;
        triggerFilter();
    };

    const clearSelectedBtn = createEl("button", "anima-pose-btn danger");
    clearSelectedBtn.innerHTML = `${trashIcon()} ${t("Clear Selected")}`;
    clearSelectedBtn.onclick = () => {
        if (selectedPose.size === 0) return;
        selectedPose.clear();
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

    const sidebar = createEl("aside", "anima-pose-scrollbar");
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

    const listContainer = createEl("div", "anima-pose-scrollbar");
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

    const pagination = createEl("div", "anima-pose-pagination");

    const pageStats = createEl("div", "anima-pose-pagination-stats");

    const pageControls = createEl("div", "anima-pose-pagination-controls");

    const firstBtn = createEl("button", "anima-pose-page-btn", t("First"));
    const prevBtn = createEl("button", "anima-pose-page-btn", t("Prev"));
    const nextBtn = createEl("button", "anima-pose-page-btn", t("Next"));
    const lastBtn = createEl("button", "anima-pose-page-btn", t("Last"));
    const pageNumContainer = createEl("div", "anima-pose-page-number");
    const pageInput = createEl("input", "anima-pose-page-input");
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

    const countLabel = createEl("button", "anima-pose-btn active");
    countLabel.onclick = () => showSelectedOnlyBtn.click();

    const footerBtns = createEl("div");
    footerBtns.style.cssText = "display: flex; align-items: center; gap: 10px;";
    const cancelFooterBtn = createEl("button", "anima-pose-btn", "关闭");
    cancelFooterBtn.onclick = () => closeModal();
    footerBtns.appendChild(cancelFooterBtn);
    const insertionControls = mountSelectorInsertionActions(footerBtns, {app, node, widget: tagsWidget, resolveText: buildValidatedSelection,
        kind: sharedKind, getSelectedItems: () => [...selectedPose].map(key => key.startsWith('custom:')
            ? favoriteItems.find(item => item.isCustom && getItemKey(item) === key) : dataById.get(key))});
    footer.style.flexWrap = 'wrap';
    footer.appendChild(countLabel);
    footer.appendChild(footerBtns);
    container.appendChild(footer);

    overlay.appendChild(container);
    document.body.appendChild(overlay);
    const sharedResourceActions = appendSharedResourceActions(headerActions, {overlay:overlay, kind:sharedKind,
        getCollection:() => groups.some(group => group.id === activeFilters.collection) ? activeFilters.collection : null,
        reopen:async () => { await reopenSelector(overlay, () => openPoseSelectorModal(node, tagsWidget, selectedPose, config)); } });
    const stopLibrarySync = watchSharedLibrary(overlay, sharedKind, async () => { await reopenSelector(overlay, () => openPoseSelectorModal(node, tagsWidget, selectedPose, config)); }, () => favoritesSaveInFlight || insertionControls.apply.disabled);

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
        const clearFiltersBtn = createEl("button", "anima-pose-clear-filters-btn");
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
            const allItem = sidebarItem(t(config.allItemsLabel), activeFilters.collection === "all", poseData.length);
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

        if (selectorCategories.length) {
            sidebar.appendChild(builtinCategoriesSectionHeader());
            const builtinCategoriesContent = createEl("div");
            builtinCategoriesContent.style.cssText = builtinCategoriesCollapsed ? "display: none;" : "display: flex; flex-direction: column;";
            if (!builtinCategoriesCollapsed) {
                selectorCategories.forEach(category => {
                    const row = createEl("label", "anima-pose-check-row");
                    row.style.paddingLeft = "22px";
                    row.innerHTML = `
                        <input type="checkbox" ${activeFilters.categories.has(category) ? "checked" : ""}>
                        <span>${escapeHtml(getCategoryLabel(category, displayLang))}</span>
                    `;
                    row.querySelector("input").onchange = (event) => {
                        if (event.target.checked) {
                            removeSharedCategoryFilters(activeFilters.categories);
                            activeFilters.categories.add(category);
                        } else {
                            activeFilters.categories.delete(category);
                        }
                        currentPage = 1;
                        persistFilters();
                        updateClearFiltersButtonState();
                        triggerFilter();
                    };
                    builtinCategoriesContent.appendChild(row);
                });
            }
            sidebar.appendChild(builtinCategoriesContent);
        }

        const sharedTreeItems = sharedIndexItems.length ? sharedIndexItems : poseData;
        appendSharedCategoryTree({
            kind: sharedKind,
            sidebar,
            items: sharedTreeItems,
            selectedFilters: activeFilters.categories,
            rowClass: "anima-pose-sidebar-item",
            storageKey: SHARED_CATEGORIES_COLLAPSE_STORAGE_KEY,
            onFilterChange: () => {
                activeFilters.collection = "all";
                showSelectedOnly = false;
                showSelectedOnlyBtn.classList.remove("active");
                currentPage = 1;
                persistFilters();
                updateClearFiltersButtonState();
                renderSidebar();
                triggerFilter();
                ensureActiveSharedCategoryLoaded();
            },
        });

        if (lastSidebarScrollTop > 0) {
            sidebar.scrollTop = lastSidebarScrollTop;
            setTimeout(() => sidebar.scrollTop = lastSidebarScrollTop, 60);
        }
    }

    function collectionsSectionHeader() {
        const header = createEl("div", "anima-pose-section-header foldable");
        const title = createEl("span", "anima-pose-section-title", t("Collections"));
        const spacer = createEl("span", "anima-pose-section-spacer");
        const addBtn = createEl("button", "anima-pose-section-icon-btn");
        addBtn.type = "button";
        addBtn.title = t("Create Group");
        addBtn.innerHTML = "+";
        const arrow = createEl("span", `anima-pose-section-arrow${collectionsCollapsed ? " collapsed" : ""}`);
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

    function builtinCategoriesSectionHeader() {
        const selectedCount = selectorCategories.filter(category => activeFilters.categories.has(category)).length;
        const header = createEl("div", "anima-pose-section-header foldable");
        const title = createEl("span", "anima-pose-section-title", displayLang === "bilingual" ? "Anima 内置分类" : "Anima Built-in Categories");
        const count = createEl("span", null, String(selectedCount || selectorCategories.length));
        count.style.cssText = `color:${selectedCount ? THEME.accentText : "var(--uw-muted)"};font-size:11px;margin-left:auto;margin-right:8px;`;
        const arrow = createEl("span", `anima-pose-section-arrow${builtinCategoriesCollapsed ? " collapsed" : ""}`);
        arrow.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`;

        header.onclick = () => {
            builtinCategoriesCollapsed = !builtinCategoriesCollapsed;
            localStorage.setItem(BUILTIN_CATEGORIES_COLLAPSE_STORAGE_KEY, String(builtinCategoriesCollapsed));
            renderSidebar();
        };

        header.appendChild(title);
        header.appendChild(count);
        header.appendChild(arrow);
        return header;
    }


    function sidebarItem(label, active, count) {
        const row = createEl("div", `anima-pose-sidebar-item${active ? " active" : ""}`);
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
            activeFilters.categories.size > 0;
    }

    function updateClearFiltersButtonState() {
        const clearFiltersBtn = sidebar.querySelector(".anima-pose-clear-filters-btn");
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
        currentPage = 1;
        listContainer.scrollTop = 0;
        persistFilters();
        renderSidebar();
        triggerFilter();
        searchInput.focus();
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
            customItems = favoriteItems.filter(item => item.isCustom && selectedPose.has(getItemKey(item)));
            items = poseData.filter(item => selectedPose.has(getItemKey(item)));
        } else {
            const groupIds = new Set();
            if (activeFilters.collection !== "all") {
                favoriteItems.forEach(item => {
                    if (item.groupIds?.includes(activeFilters.collection) && !item.isCustom) {
                        groupIds.add(getItemKey(item));
                    }
                });
            }

            items = poseData.filter(item => {
                if (activeFilters.collection !== "all" && !groupIds.has(getItemKey(item))) return false;

                if (queryList.length > 0) {
                    if (!queryList.some(q => Number.isFinite(getPromptSearchRank(item, q, searchAliases(item))))) return false;
                }

                if (activeFilters.categories.size > 0) {
                    if (!itemMatchesCategoryFilters(item, activeFilters.categories, normalizeSelectorCategoryValue)) return false;
                }

                return true;
            });

            if (activeFilters.collection !== "all") {
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
        updatePaginationBar();
        renderCurrentPage();
    }

    function activeSharedCategoryFilter() {
        return Array.from(activeFilters.categories).find(isSharedCategoryFilter) || "";
    }

    function rebuildPoseDataFromSharedItems() {
        poseData = mergePromptItems(localPoseData, Array.from(sharedLoadedItems.values()));
        assignPromptSelectorKeys(poseData);
        dataById = new Map(poseData.map(item => [getItemKey(item), item]));
    }

    function upsertSharedItems(items) {
        for (const rawItem of items || []) {
            if (!rawItem || typeof rawItem !== "object") continue;
            const item = { ...rawItem };
            const base = getPromptItemBaseKey(item);
            const isIndex = String(item.id || "").startsWith("weilin:index:");
            const previous = Array.from(sharedLoadedItems.entries()).find(([, old]) => (
                getPromptItemBaseKey(old) === base
                && String(old?.id || "").startsWith("weilin:index:")
                && !isIndex
            ));
            if (previous) {
                for (const [oldKey, old] of Array.from(sharedLoadedItems.entries())) {
                    if (getPromptItemBaseKey(old) === base && String(old?.id || "").startsWith("weilin:index:")) {
                        sharedLoadedItems.delete(oldKey);
                    }
                }
            }
            if (!item.selectorKey && isIndex) {
                // Index records are summaries and cannot identify a full
                // variant. Give each summary a temporary payload key so two
                // same-ID summaries are retained without claiming identity.
                const sameBase = Array.from(sharedLoadedItems.entries()).filter(([, old]) => getPromptItemBaseKey(old) === base);
                if (sameBase.length) {
                    for (const [oldKey, old] of sameBase) {
                        if (!old.selectorKey) {
                            old.selectorKey = getPromptItemVariantKey(old);
                            sharedLoadedItems.delete(oldKey);
                            sharedLoadedItems.set(getItemKey(old), old);
                        }
                    }
                }
                item.selectorKey = getPromptItemVariantKey(item);
            } else if (!item.selectorKey && !isIndex) {
                // Full records carry the complete payload, so their identity
                // must be order-independent and must never inherit the
                // temporary index key of whichever variant arrived first.
                item.selectorKey = getPromptItemVariantKey(item);
            }
            sharedLoadedItems.set(getItemKey(item), item);
        }
    }

    function applySharedPoseItems(items, filter) {
        if (!Array.isArray(items)) return;
        upsertSharedItems(items);
        if (filter) loadedSharedFilters.add(filter);
        rebuildPoseDataFromSharedItems();
        if (favoriteItems.some(item => !item.isCustom) || favoriteMap.size) {
            const currentFavorites = [
                ...Array.from(favoriteMap).filter(([key]) => favoriteSet.has(key)).map(([, value]) => value),
                ...unresolvedFavoriteItems,
            ];
            const restoredFavorites = resolvePromptFavorites(poseData, currentFavorites);
            favoriteMap.clear();
            restoredFavorites.map.forEach((value, key) => favoriteMap.set(key, value));
            favoriteSet.clear();
            restoredFavorites.set.forEach(key => favoriteSet.add(key));
            unresolvedFavoriteItems.splice(0, unresolvedFavoriteItems.length, ...restoredFavorites.unresolved);
            appendUnresolvedPromptFavorites(titleWrap, unresolvedFavoriteItems);
        }
        const nextValidSelectionKeys = new Set([
            ...poseData.map(getItemKey),
            ...favoriteItems.filter(item => item.isCustom).map(getItemKey),
        ]);
        for (const key of Array.from(selectedPose)) {
            if (!nextValidSelectionKeys.has(key)) selectedPose.delete(key);
        }

        const prunedFilters = pruneSharedCategoryFilters(
            poseData,
            activeFilters.categories,
            normalizeSelectorCategoryValue,
        );
        const normalizedFilters = normalizeSharedCategoryNavigationFilters(activeFilters.categories, poseData);
        if (prunedFilters || normalizedFilters) persistFilters();
        renderSidebar();
        triggerFilter();
    }

    async function ensureActiveSharedCategoryLoaded() {
        if (config.loadAllOnOpen) return;
        const filter = activeSharedCategoryFilter();
        if (!filter || loadedSharedFilters.has(filter) || loadingSharedFilter === filter) return;
        loadingSharedFilter = filter;
        updatePaginationBar();
        try {
            const items = await loadSharedPromptItems(sharedKind, { filter });
            if (isClosed) return;
            if (activeSharedCategoryFilter() !== filter) {
                loadedSharedFilters.add(filter);
                upsertSharedItems(items);
                return;
            }
            applySharedPoseItems(items, filter);
        } catch (error) {
            console.warn(`[Anima Tools] Failed to load WeiLin ${sharedKind} category`, error);
        } finally {
            if (loadingSharedFilter === filter) loadingSharedFilter = "";
            if (!isClosed) updatePaginationBar();
        }
    }

    function updatePaginationBar() {
        const total = filteredData.length;
        const start = total === 0 ? 0 : (currentPage - 1) * 48 + 1;
        const end = Math.min(currentPage * 48, total);
        const loadingText = loadingSharedFilter ? " · WeiLin loading..." : "";
        pageStats.innerText = `${t(config.totalLabel, { total, start, end })}${loadingText}`;
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
        const isCustomGroup = !showSelectedOnly && activeFilters.collection !== "all" && activeFilters.collection !== "default";

        if (filteredData.length === 0 && !isCustomGroup) {
            const empty = createEl("div");
            empty.style.cssText = "grid-column:1/-1; padding:70px 20px; text-align:center; color:var(--uw-muted);";
            empty.innerHTML = `
                <div style="font-size:38px;font-weight:900;color:${THEME.accentText};margin-bottom:12px;">0</div>
                <div style="font-size:16px;font-weight:800;color:#fff;">${escapeHtml(t(config.emptyLabel))}</div>
                <div style="font-size:13px;margin-top:8px;">${escapeHtml(t("Try another search or clear filters."))}</div>
            `;
            if (hasActiveSidebarFilters()) {
                const clearBtn = createEl("button", "anima-pose-btn", t("Clear Filters"));
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
        const card = createEl("article", "anima-pose-create-card");
        const content = createEl("div", "anima-pose-create-card-content");
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
        const isSelected = selectedPose.has(key);
        const isFavorite = !item.isCustom && favoriteSet.has(getItemKey(item));
        const favInfo = item.isCustom ? item : favoriteMap.get(getItemKey(item));
        const nickname = favInfo?.nickname || "";

        const card = createEl("article", `anima-pose-card${isSelected ? " selected" : ""}`);
        card.dataset.key = key;

        const clip = createEl("div", "anima-pose-card-clip");
        card.appendChild(clip);

        const placeholder = createEl("div", "anima-pose-placeholder");
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
                loader = createEl("div", "anima-pose-shimmer");
                const spinner = createEl("div", "anima-pose-spinner");
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

        const selectedMark = createEl("div", "anima-pose-selected-mark");
        selectedMark.innerHTML = isSelected ? checkIcon() : "";
        card.appendChild(selectedMark);

        if (item.isCustom) {
            const deleteBtn = iconButton(9, trashIcon(14), t("Delete Custom Item"));
            deleteBtn.onclick = async (event) => {
                event.stopPropagation();
                if (!confirm(t("Are you sure you want to delete this custom item?"))) return;
                favoriteItems = favoriteItems.filter(existing => existing.name !== item.name);
                selectedPose.delete(key);
                if (!(await saveFavorites())) return;
                renderSidebar();
                triggerFilter();
            };
            card.appendChild(deleteBtn);
        } else {
            const favBtn = iconButton(9, heartIcon(isFavorite), `${t(isFavorite ? "Remove from Favorites" : "Add to Favorites")}: ${item.name}`);
            favBtn.classList.add("anima-favorite-btn");
            favBtn.setAttribute("aria-pressed", String(isFavorite));
            favBtn.dataset.favoriteSourceKey = getPromptFavoriteSourceKey(item, poseData);
            favBtn.onclick = async (event) => {
                event.stopPropagation();
                if (!toggleFavorite(item)) return;
                if (!(await saveFavorites())) return;
                renderSidebar();
                if (activeFilters.collection !== "all" || activeSort === "favorite-desc") triggerFilter();
                else renderCurrentPage();
            };
            card.appendChild(favBtn);
        }


        const mask = createEl("div", "anima-pose-card-mask");
        clip.appendChild(mask);

        const tagsOverlay = createEl("div", "anima-pose-tags-overlay");
        const promptTags = splitPromptTokens(item.isCustom ? item.customContent : item.tags);
        const promptTagsZh = splitPromptTokens(item.tags_zh);
        const titleBtn = createEl("button", "anima-pose-tags-title");
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

        const tagsList = createEl("div", "anima-pose-tags-list");
        promptTags.forEach((tag, index) => {
            const zh = promptTagsZh[index] || "";
            const displayTag = displayLang === "bilingual" && zh ? `${tag} (${zh})` : tag;
            const pill = createEl("span", "anima-pose-tag-pill", displayTag);
            pill.title = displayTag;
            pill.onclick = (event) => {
                event.stopPropagation();
                copyText(tag, () => showToast(t("Copied: {text}", { text: tag })));
            };
            tagsList.appendChild(pill);
        });
        tagsOverlay.appendChild(tagsList);
        clip.appendChild(tagsOverlay);

        const info = createEl("div", "anima-pose-card-info");
        const titleEl = createEl("div", "anima-pose-card-title");
        const displayName = formatDisplayName(item, displayLang);
        titleEl.innerText = displayName;
        titleEl.title = item.isCustom ? item.customContent || "" : `${item.name_zh || ""}${item.name_zh ? " / " : ""}${item.name || ""}`;
        const subEl = createEl("div", "anima-pose-card-sub");
        if (item.isCustom) {
            subEl.innerText = t("Custom");
        } else if (displayLang === "bilingual" && item.name_zh) {
            subEl.innerText = item.name || "";
        } else {
            const firstCategory = Array.isArray(item.categories) && item.categories.length > 0 ? item.categories[0] : "";
            subEl.innerText = firstCategory ? getCategoryLabel(firstCategory, "en") : String(item.id || "");
        }

        if (nickname && !item.isCustom) {
            const note = createEl("div", "anima-pose-card-sub", nickname);
            note.style.color = THEME.accentText;
            info.appendChild(titleEl);
            info.appendChild(note);
        } else {
            info.appendChild(titleEl);
        }
        if (!item.shared) info.appendChild(subEl);
        appendSharedResourceEditor(card, item, async () => {
            await reopenSelector(overlay, () => openPoseSelectorModal(node, tagsWidget, selectedPose, config));
        }, info);

        clip.appendChild(info);

        card.onclick = () => {
            if (selectedPose.has(key)) selectedPose.delete(key);
            else selectedPose.add(key);
            updateCardSelection(card, selectedPose.has(key));
            updateCountLabel();
        };

        return card;
    }

    function updateCardSelection(card, selected) {
        card.classList.toggle("selected", selected);
        const mark = card.querySelector(".anima-pose-selected-mark");
        if (mark) mark.innerHTML = selected ? checkIcon() : "";
    }

    function badge(text) {
        const el = createEl("span", "anima-pose-badge", text);
        el.title = text;
        return el;
    }

    function iconButton(top, html, titleText) {
        const btn = createEl("button", "anima-pose-icon-btn");
        btn.type = "button";
        btn.style.top = `${top}px`;
        btn.innerHTML = html;
        btn.title = titleText;
        btn.setAttribute("aria-label", titleText);
        return btn;
    }

    function toggleFavorite(item) {
        const key = getItemKey(item);
        const sourceKey = getPromptFavoriteSourceKey(item, poseData);
        if (!favoriteSet.has(key) && !sourceKey) {
            showToast("该来源有不同正文变体，无法唯一绑定收藏；请核对资料后重试。");
            return false;
        }
        if (favoriteSet.has(key)) {
            favoriteSet.delete(key);
            const fav = favoriteMap.get(key);
            if (fav) fav.groupIds = [];
        } else {
            favoriteSet.add(key);
            let fav = favoriteMap.get(key);
            if (!fav) {
                fav = { id: item.id, name: item.name, selectorKey: sourceKey, nickname: "", groupIds: ["default"], isCustom: false };
                favoriteMap.set(key, fav);
            } else if (!Array.isArray(fav.groupIds) || fav.groupIds.length === 0) {
                fav.groupIds = ["default"];
            }
        }
        return true;
    }




    function createModalShell(maxWidth = 400) {
        return createSharedModalShell({
            maxWidth,
            animationName: "animaPoseFadeIn",
        });
    }

    function modalButtons(dialog, onConfirm, confirmText = t("OK")) {
        return createModalButtons({
            dialog,
            onConfirm,
            cancelText: t("Cancel"),
            confirmText,
            buttonClass: "anima-pose-btn",
        });
    }

    function buildSelectedText(frozenItems = null) {
        const selectedItems = frozenItems || [...selectedPose].map(key => key.startsWith("custom:")
            ? favoriteItems.find(item => item.isCustom && getItemKey(item) === key)
            : dataById.get(key));
        if (selectedItems.some(item => item?.shared)) {
            return selectedItems.map(item => item?.shared ? item.tags
                : splitPromptTokens(item?.customContent || item?.tags || "").join(", ")).join("\n");
        }
        const tags = [];
        selectedPose.forEach(key => {
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

    async function buildValidatedSelection() {
        if (isClosed) throw new Error("选择器已关闭，请重新打开。");
        const previousText = tagsWidget?.value;
        const keys = [...selectedPose];
        const selectedItems = keys.map(key => key.startsWith("custom:")
            ? favoriteItems.find(item => item.isCustom && getItemKey(item) === key)
            : dataById.get(key)).map(item => item ? structuredClone(item) : item);
        assertPromptTarget();
        if (selectedItems.some(item => !item)) throw new Error("所选资料已不可用，请重新选择。");
        await validateSharedPromptSelection(sharedKind, selectedItems);
        if (isClosed) throw new Error("选择器已关闭，请重新打开。");
        assertPromptTarget();
        if (JSON.stringify(keys) !== JSON.stringify([...selectedPose])) {
            throw new Error("选择已变化，请再次点击应用。");
        }
        if (tagsWidget?.value !== previousText) {
            throw new Error("目标正文已变化，请确认当前内容后再次应用。");
        }
        return buildSelectedText(selectedItems);
    }

    function updateCountLabel() {
        countLabel.innerHTML = `${checkIcon()} <span>${t(config.selectedCountLabel, { count: selectedPose.size })}</span>`;
    }

    function closeModal() {
        if (isClosed) return;
        clearTimeout(searchTimer);
        stopLibrarySync();
        isClosed = true;
        insertionControls.dispose();
        imageObserver.disconnect();
        document.getElementById("anima-pose-group-popover")?.remove();
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
    const disposeDialog = installSelectorDialog(overlay, {label:t(config.title), initialFocus:searchInput, close:closeModal});
    overlay.unifiedFocus();
    await sharedPoseIndexPromise
        .then(async indexItems => {
            if (isClosed) return;
            sharedIndexItems = Array.isArray(indexItems) ? indexItems : [];
            if (config.loadAllOnOpen) {
                applySharedPoseItems(sharedIndexItems, "");
            } else {
                renderSidebar();
                await ensureActiveSharedCategoryLoaded();
            }
        });
}
