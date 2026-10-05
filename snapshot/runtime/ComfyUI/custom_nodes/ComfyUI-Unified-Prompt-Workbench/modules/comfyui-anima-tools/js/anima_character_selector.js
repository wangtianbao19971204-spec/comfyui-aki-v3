import { capturePromptTarget, appendUnresolvedPromptFavorites, getPromptFavoriteSourceKey } from "./anima_prompt_identity.js";
import { app } from "../../scripts/app.js";
import { t } from "./i18n.js";
import { getPersistentImageUrl, markImageLoaded, isImageLoaded } from "./anima_image_utils.js";
import {
    appendSharedCategoryTree,
    appendSharedResourceEditor, appendSharedResourceActions, watchSharedLibrary,
    getCharacterItemKey,
    getSharedPromptSyncMessage,
    itemMatchesCategoryFilters,
    loadMergedPromptItems,
    validateSharedPromptSelection,
    normalizeSharedCategoryNavigationFilters,
    pruneSharedCategoryFilters,
    refreshMergedPromptItems,
    getPromptSearchRank,
    rankPromptSearchResults,
} from "./anima_shared_prompt_data.js";
import { createPromoLinks } from "./anima_promo_links.js";
import { addSelectorActionRow, installSelectorExecutionSync, isAnimaPromptPlusNode } from "./anima_selector_random.js";
import { showToast as showSharedToast, mountSelectorInsertionActions, reopenSelector, captureSelectorFavoriteFocus } from "./anima_selector_ui.js";
import { recoverFavoritesConflict } from "./anima_favorites_recovery.js";

let characterOfficialDataPromise = null;

async function ensureCharacterOfficialData() {
    if (window.characterOfficialData) {
        return window.characterOfficialData;
    }
    if (!characterOfficialDataPromise) {
        const dataUrl = new URL("./character_official_data.json", import.meta.url);
        characterOfficialDataPromise = fetch(dataUrl)
            .then(response => response.ok ? response.json() : null)
            .then(data => {
                if (data && typeof data === "object") {
                    window.characterOfficialData = data;
                    return data;
                }
                return null;
            })
            .catch(err => {
                console.warn("[Anima Tools] Failed to load local official character tags", err);
                return null;
            });
    }
    return characterOfficialDataPromise;
}

app.registerExtension({
    name: "AnimaCharacterTagSelector.extension",

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "AnimaCharacterTagSelector" || nodeData.name === "AnimaCharacterTagSelectorPlus" || isAnimaPromptPlusNode(nodeData.name)) {
            installSelectorExecutionSync(nodeType);
            const origOnCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                origOnCreated?.apply(this, arguments);

                // 找到 character_tags widget
                const characterTagsWidget = this.widgets.find(w => w.name === "character_tags");
                if (!characterTagsWidget) return;
                
                addSelectorActionRow(this, {
                    section: "character",
                    label: t("Open Character Selector"),
                    accent: "var(--uw-accent)",
                    accentText: "var(--uw-accent)",
                    onOpen: async () => {
                        ensureCharacterOfficialData();
                        await openCharacterSelectorModal(this, characterTagsWidget);
                    },
                });
            };
        }
    }
});

function splitPromptTokens(value) {
    if (Array.isArray(value)) {
        return value.flatMap(splitPromptTokens);
    }
    return String(value || "")
        .split(",")
        .map(part => part.replace(/^_raw_:/, "").trim())
        .filter(Boolean);
}

function normalizePromptToken(value) {
    return String(value || "").replace(/^_raw_:/, "").trim().toLowerCase();
}

function pushUniquePromptTokens(target, seen, value) {
    splitPromptTokens(value).forEach(token => {
        const key = normalizePromptToken(token);
        if (key && !seen.has(key)) {
            seen.add(key);
            target.push(token);
        }
    });
}

function getCharacterTrigger(item) {
    if (!item) return "";
    if (item.isCustom) return item.customContent || item.name || "";
    const source = item._officialData || item;
    if (source.trigger) return source.trigger;
    if (item.copyright) return `${item.name}, ${item.copyright}`;
    return item.name || "";
}

function getExplicitCharacterTags(item) {
    if (item?.shared) return splitPromptTokens(item.tags);
    const tags = [];
    const seen = new Set();
    if (!item || item.isCustom) return tags;
    const source = item._officialData || item;

    pushUniquePromptTokens(tags, seen, source.tags);
    pushUniquePromptTokens(tags, seen, source.core_tags);
    pushUniquePromptTokens(tags, seen, source.coreTags);

    return tags;
}

function getCharacterTags(item) {
    const tags = getExplicitCharacterTags(item);
    const seen = new Set(tags.map(normalizePromptToken));
    if (!item || item.isCustom) return tags;

    if (tags.length === 0) {
        pushUniquePromptTokens(tags, seen, item.gender);
        if (item.hair) pushUniquePromptTokens(tags, seen, `${item.hair} hair`);
        if (item.eye) pushUniquePromptTokens(tags, seen, `${item.eye} eyes`);
    }

    return tags;
}

function getCharacterDisplayTags(item) {
    if (!item?.shared && !item?.isCustom) return getExplicitCharacterTags(item);
    const tags = [], seen = new Set();
    pushUniquePromptTokens(tags, seen, item.shared ? item.tags : getCharacterTrigger(item));
    return tags;
}

function getCharacterPromptParts(item) {
    const parts = [];
    const seen = new Set();
    pushUniquePromptTokens(parts, seen, getCharacterTrigger(item));
    return parts;
}

function formatCharacterDisplayName(item) {
    if (!item) return "";
    if (item.isCustom) return item.nickname || item.name || "";
    return String(item.name || "")
        .split(" ")
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
}

function characterVariantKey(item) {
    const canonical = value => Array.isArray(value)
        ? value.map(canonical)
        : value && typeof value === "object"
            ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, val]) => [key, canonical(val)]))
            : value;
    const { selectorKey, ...sourceItem } = item;
    const raw = JSON.stringify(canonical(sourceItem));
    return `${getCharacterItemKey(item)}:variant:${encodeURIComponent(raw)}`;
}

function assignCharacterSelectorKeys(items) {
    const counts = new Map();
    items.forEach(item => {
        const key = getCharacterItemKey(item);
        counts.set(key, (counts.get(key) || 0) + 1);
    });
    items.forEach(item => {
        const key = getCharacterItemKey(item);
        if ((counts.get(key) || 0) > 1 && !item.selectorKey) item.selectorKey = characterVariantKey(item);
    });
    return items;
}

export async function openCharacterSelectorModal(node, tagsWidget, restoredSelection = null) {
    const assertPromptTarget = capturePromptTarget(node, tagsWidget, () => app.graph);
    const characterData = assignCharacterSelectorKeys(await loadMergedPromptItems(
        "character",
        Array.isArray(window.characterData) ? window.characterData : [],
    ));
    const hasOnlySharedCharacters = characterData.every(item => item?.shared);
    // Selection is intentionally one-way: only clicks inside this selector mark cards as selected.
    // Existing node text is not reverse-synced into checked cards.
    const selectedCharacters = restoredSelection instanceof Set
        ? new Set(restoredSelection)
        : new Set();

    // 加载后端持久化配置
    let favoritesEtag = null;
    let favoritesSaveInFlight = false;
    let favoritesConfig = {
        character: {
            groups: [{ id: "default", name: t("My Favorites"), isSystem: true }],
            items: []
        }
    };
    try {
        const response = await fetch("/anima-tools/favorites");
        if (response.ok) {
            favoritesConfig = await response.json();
            favoritesEtag = response.headers.get("ETag") || null;
        }
    } catch (e) {
        console.error("Failed to load favorites", e);
    }
    
    let groups = favoritesConfig.character.groups || [{ id: "default", name: t("My Favorites"), isSystem: true }];
    let favoriteItems = favoritesConfig.character.items || [];
    let favoriteMap = new Map();
    const unresolvedFavoriteItems = [];
    favoriteItems.forEach(fi => {
        if (!fi.isCustom) {
            if (fi.selectorKey) {
                if (characterData.some(item => getCharacterItemKey(item) === String(fi.selectorKey)) && !favoriteMap.has(String(fi.selectorKey))) {
                    favoriteMap.set(String(fi.selectorKey), { ...fi, selectorKey: String(fi.selectorKey) });
                } else {
                    unresolvedFavoriteItems.push({ ...fi });
                }
                return;
            }
            const legacyMatches = characterData.filter(item => item.name === fi.name);
            if (legacyMatches.length === 1) {
                const selectorKey = getCharacterItemKey(legacyMatches[0]);
                if (favoriteMap.has(selectorKey)) unresolvedFavoriteItems.push({ ...fi });
                else favoriteMap.set(selectorKey, { ...fi, selectorKey });
            } else {
                unresolvedFavoriteItems.push({ ...fi });
            }
        }
    });
    let favoriteSet = new Set(favoriteMap.keys());
    const validSelectionKeys = new Set([
        ...characterData.map(getCharacterItemKey),
        ...favoriteItems.filter(item => item.isCustom).map(getCharacterItemKey),
    ]);
    for (const key of Array.from(selectedCharacters)) {
        if (!validSelectionKeys.has(key)) selectedCharacters.delete(key);
    }

    // 记忆排序、页数、侧边栏分类和滚动位置配置
    const SORT_STORAGE_KEY = "anima-char-selector-active-sort";
    const PAGE_STORAGE_KEY = "anima-char-selector-active-page";
    const SCROLL_STORAGE_KEY = "anima-char-selector-active-scroll";
    const SIDEBAR_STORAGE_KEY = "anima-char-selector-active-sidebar-category";
    const SIDEBAR_SCROLL_STORAGE_KEY = "anima-char-selector-sidebar-scroll";
    const SHARED_FILTERS_STORAGE_KEY = "anima-char-selector-shared-category-filters-v2";

    let activeSort = localStorage.getItem(SORT_STORAGE_KEY) || "works-desc";
    
    let activeFilters = { type: "all" };
    const selectedSharedCharacterFilters = new Set();
    try {
        const savedSharedFilters = JSON.parse(
            localStorage.getItem(SHARED_FILTERS_STORAGE_KEY) || "[]",
        );
        if (Array.isArray(savedSharedFilters)) {
            savedSharedFilters
                .filter(value => typeof value === "string")
                .forEach(value => selectedSharedCharacterFilters.add(value));
        }
    } catch (e) {
        console.warn("[Anima Tools] Failed to restore character shared filters", e);
    }
    const prunedSharedCharacterFilters = pruneSharedCategoryFilters(
        characterData,
        selectedSharedCharacterFilters,
    );
    const normalizedSharedCharacterFilters = normalizeSharedCategoryNavigationFilters(
        selectedSharedCharacterFilters,
        characterData,
    );
    if (prunedSharedCharacterFilters || normalizedSharedCharacterFilters) {
        localStorage.setItem(
            SHARED_FILTERS_STORAGE_KEY,
            JSON.stringify(Array.from(selectedSharedCharacterFilters)),
        );
    }

    try {
        const saved = localStorage.getItem(SIDEBAR_STORAGE_KEY);
        if (saved) {
            const restoredType = saved.startsWith("{") ? JSON.parse(saved)?.type : saved;
            const type = restoredType === "favorites" ? "default" : restoredType;
            if (["all", "weilin", "default"].includes(type) || groups.some(group => group.id === type)) {
                activeFilters.type = type;
            }
        }
    } catch (e) {
        console.error("Failed to load active filters", e);
    }
    
    if (activeFilters.type === "weilin" && hasOnlySharedCharacters) {
        activeFilters.type = "all";
    }
    if (selectedSharedCharacterFilters.size > 0) {
        activeFilters.type = "weilin";
    }
    localStorage.setItem(SIDEBAR_STORAGE_KEY, JSON.stringify(activeFilters));

    function persistSharedCharacterFilters() {
        localStorage.setItem(
            SHARED_FILTERS_STORAGE_KEY,
            JSON.stringify(Array.from(selectedSharedCharacterFilters)),
        );
    }

    function favoriteInfoForItem(item) {
        return favoriteMap.get(getCharacterItemKey(item));
    }

    function makeFavoriteRecord(item, overrides = {}) {
        return {
            name: item.name,
            selectorKey: getCharacterItemKey(item),
            nickname: "",
            groupIds: [],
            isCustom: false,
            ...overrides,
        };
    }

    function getSelectedCharacterItems() {
        const byKey = new Map(characterData.map(item => [
            getCharacterItemKey(item),
            item,
        ]));
        favoriteItems
            .filter(item => item.isCustom)
            .forEach(item => byKey.set(getCharacterItemKey(item), item));
        return Array.from(selectedCharacters)
            .map(key => byKey.get(key))
            .filter(Boolean);
    }

    async function saveFavorites() {
        if (favoritesSaveInFlight) return false;
        const restoreFavoriteFocus = captureSelectorFavoriteFocus(modalOverlay);
        let favoritesSaved = false;
        favoritesSaveInFlight = true;
        const saveOwner = typeof document === "undefined" ? null : document.activeElement?.closest?.("[data-anima-favorites-editor]");
        const interactionOwners = [...new Set([modalOverlay, saveOwner].filter(Boolean))];
        const previousInert = interactionOwners.map(element => element.inert);
        interactionOwners.forEach(element => { element.inert = true; });
        try {
            const nextItems = [];
        favoriteItems.forEach(fi => {
            if (fi.isCustom) {
                nextItems.push(fi);
            }
        });
        favoriteMap.forEach((val, key) => {
            if (favoriteSet.has(key)) {
                nextItems.push(val);
            }
        });
        unresolvedFavoriteItems.forEach(item => nextItems.push(item));
        
        favoriteItems = nextItems;
        favoritesConfig.character.groups = groups;
        favoritesConfig.character.items = favoriteItems;
        
            const response = await fetch("/anima-tools/favorites", {
                method: "POST",
                headers: { "Content-Type": "application/json", "If-Match": favoritesEtag || "" },
                body: JSON.stringify(favoritesConfig)
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
            console.error("Failed to save favorites", e);
            try { return await offerFavoritesConflictRecovery(e.status || 0, saveOwner); }
            finally { favoritesSaveInFlight = false; }
        } finally {
            interactionOwners.forEach((element, index) => { element.inert = previousInert[index]; });
            restoreFavoriteFocus(favoritesSaved);
        }
    }

    async function offerFavoritesConflictRecovery(initialStatus, saveOwner) {
        const draftSection = JSON.parse(JSON.stringify(favoritesConfig.character || {}));
        return recoverFavoritesConflict({ partition: "character", draftSection, currentConfig: favoritesConfig, currentEtag: favoritesEtag, initialStatus, isActive: () => modalOverlay.isConnected && (!saveOwner || saveOwner.isConnected), fetchLatest: () => fetch("/anima-tools/favorites"),
            submit: async (config, etag) => { const r = await fetch("/anima-tools/favorites", { method: "POST", headers: { "Content-Type": "application/json", "If-Match": etag || "" }, body: JSON.stringify(config) }); return { ok: r.ok, status: r.status, etag: r.headers.get("ETag") || etag }; },
            commit: (config, etag) => { favoritesConfig = config; favoritesEtag = etag; groups = config.character.groups || groups; favoriteItems = config.character.items || favoriteItems; }, t });
    }

    // 弹窗与弹出菜单辅助函数 (粉色主题)


    
    


    let lastScrollTop = parseInt(localStorage.getItem(SCROLL_STORAGE_KEY)) || 0;
    let lastSidebarScrollTop = parseInt(localStorage.getItem(SIDEBAR_SCROLL_STORAGE_KEY)) || 0;
    let isFirstRender = true;

    // 拼接 Animadex.net 官方 thumbs 图片 URL
    function getImgUrl(name, copyright) {
        const rawName = copyright ? `${name}, ${copyright}` : name;
        return `https://blobs.animadex.net/Outputs/thumbs/${encodeURIComponent(rawName)}.webp`;
    }

    const officialCharacterCache = new Map();
    const officialCharacterPending = new Map();
    let activeCharacterTagsTooltip = null;

    function getCharacterCacheKey(item) {
        return `${normalizePromptToken(item?.name)}||${normalizePromptToken(item?.copyright)}`;
    }

    function getLocalOfficialCharacterData(item) {
        if (!item || item.isCustom || !window.characterOfficialData) return null;
        const key = getCharacterCacheKey(item);
        return window.characterOfficialData[key] || null;
    }

    function hideCharacterTagsTooltip() {
        if (activeCharacterTagsTooltip) {
            activeCharacterTagsTooltip.classList.remove("is-visible");
            activeCharacterTagsTooltip = null;
        }
    }

    async function fetchOfficialCharacterData(item) {
        if (!item || item.isCustom || getExplicitCharacterTags(item).length > 0) {
            return item?._officialData || item || null;
        }
        if (!window.characterOfficialData) {
            await ensureCharacterOfficialData();
        }
        const localOfficial = getLocalOfficialCharacterData(item);
        if (localOfficial) {
            item._officialData = localOfficial;
            return localOfficial;
        }
        const key = getCharacterCacheKey(item);
        if (officialCharacterCache.has(key)) {
            item._officialData = officialCharacterCache.get(key);
            return item._officialData;
        }
        if (officialCharacterPending.has(key)) {
            return officialCharacterPending.get(key);
        }

        const query = new URLSearchParams({
            name: item.name || "",
            copyright: item.copyright || ""
        });
        const request = fetch(`/anima-tools/character/official?${query.toString()}`)
            .then(response => response.ok ? response.json() : null)
            .then(payload => {
                if (payload?.success && payload.item) {
                    const official = {
                        ...payload.item,
                        tags: Array.isArray(payload.item.tags) ? payload.item.tags : splitPromptTokens(payload.item.tags)
                    };
                    officialCharacterCache.set(key, official);
                    item._officialData = official;
                    return official;
                }
                return null;
            })
            .catch(err => {
                console.warn("[Anima Tools] Failed to load official character tags", item.name, err);
                return null;
            })
            .finally(() => {
                officialCharacterPending.delete(key);
            });
        officialCharacterPending.set(key, request);
        return request;
    }

    function showCharacterTagToast(message) {
        const toast = document.createElement("div");
        toast.style.cssText = `
            position: fixed !important;
            bottom: 30px !important;
            right: 30px !important;
            background: var(--uw-panel) !important;
            border: 1px solid var(--uw-accent) !important;
            color: var(--uw-text) !important;
            padding: 10px 20px !important;
            border-radius: 12px !important;
            font-size: 13px !important;
            z-index: 100000 !important;
            box-shadow: 0 10px 25px rgba(0,0,0,0.6) !important;
            backdrop-filter: blur(10px) !important;
            -webkit-backdrop-filter: blur(10px) !important;
            pointer-events: none !important;
            animation: animaFadeIn 0.2s ease forwards !important;
        `;
        toast.innerText = message;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.transition = "opacity 0.3s ease";
            toast.style.opacity = "0";
            setTimeout(() => toast.remove(), 300);
        }, 1500);
    }

    function fallbackCopyCharacterText(text, callback) {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        textArea.style.opacity = "0";
        document.body.appendChild(textArea);
        textArea.select();
        try {
            document.execCommand("copy");
            callback?.();
        } catch (err) {
            console.error("Fallback copy failed", err);
        }
        textArea.remove();
    }

    function copyCharacterText(text, callback) {
        if (!text) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(() => callback?.()).catch(() => fallbackCopyCharacterText(text, callback));
        } else {
            fallbackCopyCharacterText(text, callback);
        }
    }

    function createCharacterTagsOverlay(item) {
        const overlay = document.createElement("div");
        overlay.className = "anima-character-card-tags";
        overlay.innerHTML = `
            <div class="anima-character-card-tags-header"></div>
            <div class="anima-character-card-tags-chips"></div>
        `;
        renderCharacterTagsOverlay(item, overlay, "idle");
        return overlay;
    }

    function renderCharacterTagsOverlay(item, overlay, state = "idle") {
        const headerEl = overlay.querySelector(".anima-character-card-tags-header");
        const chipsEl = overlay.querySelector(".anima-character-card-tags-chips");
        const explicitTags = getCharacterDisplayTags(item);
        const tags = explicitTags.length > 0 ? explicitTags : state === "error" ? getCharacterTags(item) : [];

        const renderHeader = (labelText, copyTags = []) => {
            headerEl.innerHTML = "";
            headerEl.onclick = null;

            const label = document.createElement("span");
            label.className = "anima-character-card-tags-label";
            label.innerText = labelText;
            headerEl.appendChild(label);

            if (copyTags.length > 0) {
                const copy = document.createElement("span");
                copy.className = "anima-character-card-tags-copy";
                copy.innerText = t("Copy");
                headerEl.appendChild(copy);
                headerEl.onclick = (event) => {
                    event.stopPropagation();
                    copyCharacterText(`${copyTags.join(", ")}, `, () => showCharacterTagToast(t("Copied Successfully")));
                };
            }
        };

        chipsEl.innerHTML = "";

        if (state === "loading" && explicitTags.length === 0) {
            renderHeader(t("Loading official tags..."));
            const empty = document.createElement("span");
            empty.className = "anima-character-card-tags-empty";
            empty.innerText = t("Loading official tags...");
            chipsEl.appendChild(empty);
            return;
        }

        const headerText = state === "error" && explicitTags.length === 0
            ? `${t("Official tags unavailable")} · ${tags.length}`
            : `${t("Tags")} · ${tags.length}`;
        renderHeader(headerText, tags);
        if (tags.length > 0) {
            tags.forEach(tagText => {
                const chip = document.createElement("span");
                chip.className = "anima-character-card-tag-chip";
                chip.innerText = tagText;
                chip.title = tagText;
                chip.onclick = (event) => {
                    event.stopPropagation();
                    copyCharacterText(tagText, () => showCharacterTagToast(t("Copied: {text}", { text: tagText })));
                };
                chipsEl.appendChild(chip);
            });
        } else {
            const empty = document.createElement("span");
            empty.className = "anima-character-card-tags-empty";
            empty.innerText = state === "error" ? t("Official tags unavailable") : t("No tags available");
            chipsEl.appendChild(empty);
        }
    }

    // 保存收藏列表到本地
    function saveFavoritesLocal() {
        localStorage.setItem("anima-character-favorites-list", JSON.stringify(Array.from(favoriteSet)));
    }

    // 3. 创建 Modal DOM
    const modalOverlay = document.createElement("div");
    modalOverlay.id = "anima-char-selector-overlay";
    modalOverlay.unifiedClose=()=>closeModal();
    modalOverlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: rgba(8, 8, 12, 0.8);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        z-index: 99999;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--uw-text);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    `;

    const modalContainer = document.createElement("div");
    modalContainer.id = "anima-char-selector-container";
    modalContainer.style.cssText = `
        width: 92%;
        max-width: 1320px;
        height: 90%;
        background: var(--uw-bg) !important;
        border: 1px solid var(--uw-border);
        border-radius: 28px;
        box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.8), 0 0 40px var(--uw-accent-bg);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        animation: animaFadeIn 0.35s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    `;

    // 点击外侧只关闭；写入仅由明确的应用按钮触发。
    modalOverlay.onclick = (e) => {
        if (e.target === modalOverlay) {
            closeModal();
        }
    };

    // 4. 构建 Header (更精致美观的渐变色)
    const header = document.createElement("div");
    header.style.cssText = `
        padding: 22px 28px;
        border-bottom: 1px solid var(--uw-border);
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: var(--uw-panel);
    `;
    
    const titleContainer = document.createElement("div");
    titleContainer.style.cssText = "display: flex; flex-direction: column; gap: 4px;";
    const title = document.createElement("h2");
    title.innerText = t("Anima Character Tag Selector");
    title.style.cssText = "margin: 0; font-size: 22px; font-weight: 800; background: linear-gradient(135deg, var(--uw-accent), var(--uw-accent), var(--uw-accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: -0.5px;";
    
    const subtitle = document.createElement("span");
    subtitle.innerText = t("Browse and select your favorite character tags, with 3:4 clear preview cards and precise pagination.");
    subtitle.style.cssText = "font-size: 12.5px; color: var(--uw-muted); font-weight: 500;";
    titleContainer.appendChild(title);
    titleContainer.appendChild(subtitle);
    appendUnresolvedPromptFavorites(titleContainer, unresolvedFavoriteItems);

    const closeBtn = document.createElement("button");
    closeBtn.setAttribute("aria-label", t("Close selector"));
    closeBtn.innerHTML = `
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
    `;
    closeBtn.style.cssText = "background: none; border: none; color: var(--uw-muted); cursor: pointer; transition: all 0.25s ease; display: flex; align-items: center; justify-content: center; padding: 6px; border-radius: 50%; background: var(--uw-raised);";
    closeBtn.onclick = () => closeModal();
    closeBtn.onmouseover = () => {
        closeBtn.style.color = "var(--uw-text)";
        closeBtn.style.background = "rgba(239, 68, 68, 0.2)";
        closeBtn.style.transform = "rotate(90deg)";
    };
    closeBtn.onmouseout = () => {
        closeBtn.style.color = "var(--uw-muted)";
        closeBtn.style.background = "rgba(255,255,255,0.03)";
        closeBtn.style.transform = "rotate(0deg)";
    };

    const headerActions = document.createElement("div");
    headerActions.style.cssText = "display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex: 0 0 auto;";
    headerActions.appendChild(createPromoLinks({ accentColor: "var(--uw-accent)" }));
    headerActions.appendChild(closeBtn);

    header.appendChild(titleContainer);
    header.appendChild(headerActions);
    modalContainer.appendChild(header);

    // 5. 注入动画样式及极致 UI 美化样式
    const styleSheet = document.createElement("style");
    styleSheet.textContent = `
        @keyframes animaFadeIn {
            from { opacity: 0; transform: scale(0.96) translateY(12px); }
            to { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes animaPopoverFadeIn {
            from { opacity: 0; transform: translate(-50%, 0) scale(0.95); }
            to { opacity: 1; transform: translate(-50%, 10px) scale(1); }
        }
        @keyframes animaShimmer {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
        }
        .anima-shimmer {
            position: absolute !important;
            top: 0 !important;
            left: 0 !important;
            width: 100% !important;
            height: 100% !important;
            background: linear-gradient(90deg, rgba(20, 20, 30, 0.8) 25%, var(--uw-accent-bg) 50%, rgba(20, 20, 30, 0.8) 75%) !important;
            background-size: 200% 100% !important;
            animation: animaShimmer 1.5s infinite linear !important;
            z-index: 2 !important;
            border-radius: 0 !important;
            pointer-events: none !important;
        }
        @keyframes animaSpin {
            0% { transform: translate(-50%, -50%) rotate(0deg); }
            100% { transform: translate(-50%, -50%) rotate(360deg); }
        }
        .anima-spinner {
            position: absolute !important;
            top: 50% !important;
            left: 50% !important;
            width: 26px !important;
            height: 26px !important;
            border: 2.5px solid var(--uw-accent-bg) !important;
            border-top: 2.5px solid var(--uw-accent) !important;
            border-radius: 50% !important;
            animation: animaSpin 0.85s infinite linear !important;
            z-index: 3 !important;
        }
        .anima-scrollbar::-webkit-scrollbar {
            width: 6px;
        }
        .anima-scrollbar::-webkit-scrollbar-track {
            background: transparent;
        }
        .anima-scrollbar::-webkit-scrollbar-thumb {
            background: var(--uw-raised);
            border-radius: 10px;
        }
        .anima-scrollbar::-webkit-scrollbar-thumb:hover {
            background: var(--uw-raised);
        }
        
        /* 极致奢华的按钮与微动效 */
        .anima-btn {
            padding: 9px 18px;
            border-radius: 14px;
            font-size: 13.5px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            border: 1px solid var(--uw-border);
            background: var(--uw-raised);
            color: var(--uw-text);
            display: inline-flex;
            align-items: center;
            gap: 8px;
            user-select: none;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .anima-btn:hover:not(:disabled) {
            background: var(--uw-raised);
            color: white;
            border-color: var(--uw-border);
        }
        .anima-btn:disabled {
            opacity: 0.35;
            cursor: not-allowed;
        }
        .anima-btn-primary {
            background: linear-gradient(135deg, var(--uw-accent), var(--uw-accent-strong));
            border-color: var(--uw-accent);
            color: white;
            box-shadow: 0 4px 14px var(--uw-accent);
        }
        .anima-btn-primary:hover:not(:disabled) {
            background: linear-gradient(135deg, var(--uw-accent), var(--uw-accent-strong));
            box-shadow: 0 6px 20px var(--uw-accent);
            border-color: var(--uw-accent);
        }
        .anima-btn-danger {
            background: rgba(239, 68, 68, 0.08);
            border: 1px solid rgba(239, 68, 68, 0.2);
            color: var(--uw-danger);
        }
        .anima-btn-danger:hover:not(:disabled) {
            background: rgba(239, 68, 68, 0.18);
            border-color: rgba(239, 68, 68, 0.35);
            color: var(--uw-danger);
        }
        
        /* 侧边栏按钮高级样式 */
        .sidebar-item {
            padding: 12px 16px;
            border-radius: 12px;
            font-size: 13.5px;
            font-weight: 500;
            color: var(--uw-muted);
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            align-items: center;
            justify-content: space-between;
            border: 1px solid transparent;
            margin-bottom: 4px;
        }
        .sidebar-item:hover {
            background: var(--uw-raised);
            color: var(--uw-text);
        }
        .sidebar-item.active {
            background: linear-gradient(135deg, var(--uw-accent-bg), var(--uw-accent-bg)) !important;
            border-color: var(--uw-accent) !important;
            color: var(--uw-accent) !important;
            font-weight: 700 !important;
        }
        .sidebar-clear-filters-btn {
            width: calc(100% - 16px);
            margin: 0 8px 12px;
            padding: 9px 12px;
            border-radius: 10px;
            border: 1px solid var(--uw-border);
            background: var(--uw-raised);
            color: var(--uw-muted);
            font-size: 12.5px;
            font-weight: 750;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 7px;
            transition: all 0.18s ease;
        }
        .sidebar-clear-filters-btn:hover:not(:disabled) {
            background: var(--uw-accent-bg);
            border-color: var(--uw-accent);
            color: var(--uw-accent);
        }
        .sidebar-clear-filters-btn:disabled {
            opacity: 0.42;
            cursor: not-allowed;
        }
        
        /* 分页器按钮样式 */
        .anima-pagination {
            padding: 14px 24px;
            background: linear-gradient(180deg, rgba(18,18,24,0.2), rgba(18,18,24,0.62));
            border-top: 1px solid var(--uw-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            flex-wrap: wrap;
            box-shadow: 0 -12px 32px rgba(0,0,0,0.18);
        }
        .anima-pagination-stats {
            min-height: 36px;
            padding: 0 14px;
            border-radius: 999px;
            background: var(--uw-raised);
            border: 1px solid var(--uw-border);
            color: var(--uw-text);
            font-size: 12.5px;
            font-weight: 750;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            white-space: nowrap;
            max-width: min(460px, 100%);
            overflow: hidden;
            text-overflow: ellipsis;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
        }
        .anima-pagination-stats::before {
            content: "";
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: var(--uw-accent);
            box-shadow: 0 0 14px var(--uw-accent);
            flex: 0 0 auto;
        }
        .anima-pagination-controls {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 8px;
            flex-wrap: wrap;
            margin-left: auto;
        }
        .anima-page-number {
            min-height: 36px;
            padding: 0;
            border-radius: 0;
            background: transparent;
            border: none;
            color: var(--uw-text);
            display: inline-flex;
            align-items: center;
            gap: 7px;
            box-shadow: none;
        }
        .anima-page-btn {
            min-height: 36px;
            padding: 0 13px;
            background: var(--uw-raised);
            border: 1px solid var(--uw-border);
            border-radius: 999px;
            color: var(--uw-text);
            font-size: 12.5px;
            font-weight: 750;
            cursor: pointer;
            transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.18s ease;
        }
        .anima-page-btn:hover:not(:disabled) {
            background: var(--uw-accent-bg);
            color: white;
            border-color: var(--uw-accent);
            transform: translateY(-1px);
        }
        .anima-page-btn:disabled {
            opacity: 0.35;
            cursor: not-allowed;
        }
        .anima-page-input {
            width: 48px;
            padding: 6px 4px;
            background: transparent;
            border: none;
            border-bottom: 1px solid var(--uw-border);
            border-radius: 0;
            color: #fff;
            font-size: 13px;
            font-weight: 800;
            text-align: center;
            outline: none;
            transition: border-color 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
        }
        .anima-page-input:focus {
            background: transparent;
            border-bottom-color: var(--uw-accent);
            box-shadow: none;
        }
        
        /* 折叠过渡动画样式 */
        .sidebar-section-content {
            transition: max-height 0.22s cubic-bezier(0.25, 1, 0.5, 1), opacity 0.18s ease-out;
            overflow: hidden;
        }
        .sidebar-section-header {
            cursor: pointer;
            user-select: none;
            transition: color 0.2s ease;
        }
        .sidebar-section-header:hover {
            color: var(--uw-accent) !important;
        }
        .sidebar-section-arrow {
            margin-left: auto;
            transition: transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1); /* 具有轻度弹性回弹的动画 */
        }
        .sidebar-section-arrow.collapsed {
            transform: rotate(-90deg);
        }
        .anima-character-card {
            position: relative;
            width: 100%;
            height: 100%;
            min-height: 0;
            min-width: 0;
            overflow: hidden;
            box-sizing: border-box;
            border-radius: 16px;
            isolation: isolate;
            background: var(--uw-raised);
            border: 2px solid var(--uw-border);
            box-shadow: 0 5px 18px rgba(0,0,0,0.25);
            cursor: pointer;
            transition: border-color 0.18s ease, box-shadow 0.18s ease;
        }
        .anima-character-card:hover {
            border-color: var(--uw-accent);
            box-shadow: 0 12px 30px rgba(0,0,0,0.38), 0 0 18px var(--uw-accent-bg);
        }
        .anima-character-card.selected {
            border-color: var(--uw-accent);
            box-shadow: 0 12px 30px rgba(0,0,0,0.36), 0 0 24px var(--uw-accent-bg);
        }
        .anima-character-card-clip {
            position: absolute;
            inset: 2px;
            z-index: 0;
            overflow: hidden;
            border-radius: 13px;
            clip-path: inset(0 round 13px);
            background: #0a0a10;
        }
        .anima-character-card-info {
            position: absolute;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 4;
            padding: 13px 12px;
            display: flex;
            flex-direction: column;
            gap: 5px;
            min-width: 0;
            transition: opacity 0.2s ease;
            pointer-events: none;
        }
        .anima-character-card:hover .anima-character-card-info { opacity: 0; }
        .anima-character-card-title {
            color: #fff;
            font-size: 13.5px;
            font-weight: 850;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            text-shadow: 0 2px 8px rgba(0,0,0,0.72);
        }
        .anima-character-card-sub {
            color: var(--uw-text);
            font-size: 10.5px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            opacity: 0.9;
        }
        .anima-character-card-badges {
            display: flex;
            gap: 5px;
            min-width: 0;
            overflow: hidden;
            align-items: center;
            justify-content: space-between;
        }
        .anima-character-badge {
            color: var(--uw-accent);
            background: var(--uw-accent-bg);
            border: 1px solid var(--uw-accent-bg);
            border-radius: 999px;
            padding: 2px 7px;
            font-size: 10px;
            font-weight: 750;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .anima-character-card-tags {
            position: absolute;
            inset: 0;
            z-index: 5;
            padding: 42px 12px 14px;
            box-sizing: border-box;
            opacity: 0;
            pointer-events: none;
            background: rgba(7, 7, 14, 0.76);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            transition: opacity 0.2s ease;
            display: flex;
            flex-direction: column;
            gap: 10px;
            overflow: hidden;
        }
        .anima-character-card-tags.is-visible {
            opacity: 1;
            pointer-events: auto;
        }
        .anima-character-card-tags-header {
            border: 1px solid var(--uw-accent);
            background: var(--uw-accent-bg);
            color: #fce7f3;
            border-radius: 999px;
            padding: 6px 9px;
            font-size: 11px;
            font-weight: 850;
            line-height: 1.2;
            width: 100%;
            min-width: 0;
            box-sizing: border-box;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            cursor: pointer;
        }
        .anima-character-card-tags-label {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            min-width: 0;
        }
        .anima-character-card-tags-copy {
            color: var(--uw-accent);
            font-size: 10.5px;
            font-weight: 850;
            flex: 0 0 auto;
        }
        .anima-character-card-tags-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            align-content: flex-start;
            overflow-y: auto;
            min-height: 0;
            padding-right: 2px;
            scrollbar-width: none;
            -ms-overflow-style: none;
        }
        .anima-character-card-tags-chips::-webkit-scrollbar { display: none; }
        .anima-character-card-tag-chip {
            max-width: 100%;
            color: var(--uw-text);
            background: var(--uw-raised);
            border: 1px solid var(--uw-border);
            border-radius: 999px;
            padding: 5px 8px;
            font-size: 11.5px;
            font-weight: 650;
            line-height: 1.15;
            cursor: pointer;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            box-sizing: border-box;
        }
        .anima-character-card-tag-chip:hover {
            border-color: var(--uw-accent);
            color: #fff;
            background: var(--uw-accent-bg);
        }
        .anima-character-card-tags-empty {
            color: var(--uw-muted);
            font-size: 11px;
            line-height: 1.35;
        }
    `;
    document.head.appendChild(styleSheet);

    // 6. 构建 Toolbar / 检索控制区 (更宽敞、更 premium)
    const toolbar = document.createElement("div");
    toolbar.style.cssText = `
        padding: 16px 28px;
        background: rgba(25, 25, 35, 0.15);
        border-bottom: 1px solid var(--uw-border);
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        align-items: center;
        justify-content: space-between;
    `;

    // 左侧：搜索和筛选控制
    const filterControls = document.createElement("div");
    filterControls.style.cssText = "display: flex; gap: 14px; align-items: center; flex: 1; min-width: 300px;";

    const searchInputWrapper = document.createElement("div");
    searchInputWrapper.style.cssText = "position: relative; flex: 1; max-width: 320px;";
    
    const searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.placeholder = t("Search character name...");
    searchInput.style.cssText = `
        width: 100%;
        padding: 11px 18px;
        padding-right: 42px;
        background: var(--uw-panel);
        border: 1px solid var(--uw-border);
        border-radius: 14px;
        color: white;
        font-size: 14px;
        font-weight: 500;
        outline: none;
        transition: all 0.25s ease;
        box-shadow: inset 0 2px 4px rgba(0,0,0,0.2);
    `;
    searchInput.onfocus = () => {
        searchInput.style.borderColor = "var(--uw-accent)";
        searchInput.style.boxShadow = "0 0 14px var(--uw-accent-bg), inset 0 2px 4px rgba(0,0,0,0.2)";
    };
    searchInput.onblur = () => {
        searchInput.style.borderColor = "rgba(255, 255, 255, 0.08)";
        searchInput.style.boxShadow = "none";
    };

    const clearSearchBtn = document.createElement("span");
    clearSearchBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
    `;
    clearSearchBtn.style.cssText = `
        position: absolute;
        right: 14px;
        top: 50%;
        transform: translateY(-50%);
        color: var(--uw-muted);
        cursor: pointer;
        display: none;
        line-height: 1;
        transition: color 0.15s ease;
    `;
    clearSearchBtn.onmouseover = () => clearSearchBtn.style.color = "var(--uw-text)";
    clearSearchBtn.onmouseout = () => clearSearchBtn.style.color = "var(--uw-muted)";

    clearSearchBtn.onclick = () => {
        searchInput.value = "";
        clearSearchBtn.style.display = "none";
        currentPage = 1;
        localStorage.setItem(PAGE_STORAGE_KEY, 1);
        lastScrollTop = 0;
        localStorage.setItem(SCROLL_STORAGE_KEY, 0);
        triggerFilter();
    };

    searchInput.oninput = () => {
        clearSearchBtn.style.display = searchInput.value ? "block" : "none";
        currentPage = 1; 
        localStorage.setItem(PAGE_STORAGE_KEY, 1);
        lastScrollTop = 0;
        localStorage.setItem(SCROLL_STORAGE_KEY, 0);
        triggerFilter();
    };

    searchInputWrapper.appendChild(searchInput);
    searchInputWrapper.appendChild(clearSearchBtn);
    filterControls.appendChild(searchInputWrapper);

    // 排序下拉菜单
    const sortSelect = document.createElement("select");
    sortSelect.style.cssText = `
        padding: 11px 18px;
        background: var(--uw-panel);
        border: 1px solid var(--uw-border);
        border-radius: 14px;
        color: var(--uw-text);
        font-size: 14px;
        font-weight: 600;
        outline: none;
        cursor: pointer;
        transition: all 0.25s ease;
        box-shadow: 0 2px 4px rgba(0,0,0,0.15);
    `;
    sortSelect.innerHTML = `
        <option value="works-desc">${t("Illustrations Count ⬇")}</option>
        <option value="works-asc">${t("Illustrations Count ⬆")}</option>
        <option value="fav-first">${t("Favorites First ★")}</option>
        <option value="name-asc">${t("Name A-Z")}</option>
        <option value="name-desc">${t("Name Z-A")}</option>
        <option value="copyright-asc">${t("Series A-Z")}</option>
    `;
    sortSelect.value = activeSort; 
    sortSelect.onchange = () => {
        currentPage = 1; 
        localStorage.setItem(PAGE_STORAGE_KEY, 1);
        lastScrollTop = 0;
        localStorage.setItem(SCROLL_STORAGE_KEY, 0);
        localStorage.setItem(SORT_STORAGE_KEY, sortSelect.value); 
        triggerFilter();
    };
    filterControls.appendChild(sortSelect);

    filterControls.appendChild(sortSelect);

    // 右侧：功能按钮
    const actionControls = document.createElement("div");
    actionControls.style.cssText = "display: flex; gap: 12px; align-items: center;";

    const syncWeiLinBtn = document.createElement("button");
    syncWeiLinBtn.className = "anima-btn";
    syncWeiLinBtn.innerText = "同步 WeiLin";
    syncWeiLinBtn.title = "立即读取 WeiLin 的新增、修改、删除、角色分类和预览变化";
    syncWeiLinBtn.onclick = async () => {
        syncWeiLinBtn.disabled = true;
        syncWeiLinBtn.innerText = "同步中…";
        try {
            await refreshMergedPromptItems(
                "character",
                Array.isArray(window.characterData) ? window.characterData : [],
            );
            const selection = new Set(selectedCharacters);
            await reopenSelector(modalOverlay, () => openCharacterSelectorModal(node, tagsWidget, selection));
            showSharedToast(getSharedPromptSyncMessage("character", "角色 Tags"));
        } catch (error) {
            console.error("[Anima Tools] WeiLin character sync failed", error);
            syncWeiLinBtn.disabled = false;
            syncWeiLinBtn.innerText = "同步 WeiLin";
            alert(`WeiLin 同步失败：${error?.message || error}`);
        }
    };
    actionControls.appendChild(syncWeiLinBtn);

    const copySelectedBtn = document.createElement("button");
    copySelectedBtn.className = "anima-btn";
    copySelectedBtn.innerHTML = `
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
        </svg>
        ${t("Copy Selected")}
    `;
    copySelectedBtn.onclick = () => {
        if (selectedCharacters.size === 0) {
            alert(t("Please select at least one character first."));
            return;
        }
        const textToCopy = getSelectedCharacterItems()
            .map(getCharacterTrigger)
            .filter(Boolean)
            .join(", ") + ", ";
        
        const performCopy = () => {
            const toast = document.createElement("div");
            toast.style.cssText = `
                position: fixed !important;
                bottom: 30px !important;
                right: 30px !important;
                background: var(--uw-panel) !important;
                border: 1px solid var(--uw-accent) !important;
                color: var(--uw-text) !important;
                padding: 10px 20px !important;
                border-radius: 12px !important;
                font-size: 13px !important;
                z-index: 100000 !important;
                box-shadow: 0 10px 25px rgba(0,0,0,0.6) !important;
                backdrop-filter: blur(10px) !important;
                -webkit-backdrop-filter: blur(10px) !important;
                pointer-events: none !important;
                animation: animaFadeIn 0.2s ease forwards !important;
            `;
            toast.innerText = t("Copied Successfully");
            document.body.appendChild(toast);
            setTimeout(() => {
                toast.style.transition = "opacity 0.3s ease";
                toast.style.opacity = "0";
                setTimeout(() => toast.remove(), 300);
            }, 1500);
        };
        
        const fallbackCopyChar = (text, cb) => {
            const textArea = document.createElement("textarea");
            textArea.value = text;
            textArea.style.position = "fixed"; 
            textArea.style.opacity = "0";
            document.body.appendChild(textArea);
            textArea.select();
            try {
                document.execCommand("copy");
                cb();
            } catch (err) {
                console.error("Fallback copy failed", err);
            }
            textArea.remove();
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(textToCopy).then(performCopy).catch(() => {
                fallbackCopyChar(textToCopy, performCopy);
            });
        } else {
            fallbackCopyChar(textToCopy, performCopy);
        }
    };
    actionControls.appendChild(copySelectedBtn);

    const showSelectedOnlyBtn = document.createElement("button");
    showSelectedOnlyBtn.className = "anima-btn";
    showSelectedOnlyBtn.innerHTML = t("Show Selected");
    let showSelectedOnly = false;
    showSelectedOnlyBtn.onclick = () => {
        showSelectedOnly = !showSelectedOnly;
        if (showSelectedOnly) {
            showSelectedOnlyBtn.classList.add("anima-btn-active");
            showSelectedOnlyBtn.style.cssText += `
                background: var(--uw-accent-bg) !important;
                border-color: var(--uw-accent) !important;
                color: var(--uw-accent) !important;
            `;
        } else {
            showSelectedOnlyBtn.classList.remove("anima-btn-active");
            showSelectedOnlyBtn.style.cssText = "";
        }
        currentPage = 1;
        triggerFilter();
    };
    actionControls.appendChild(showSelectedOnlyBtn);

    const clearAllBtn = document.createElement("button");
    clearAllBtn.className = "anima-btn anima-btn-danger";
    clearAllBtn.innerHTML = `
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
        ${t("Clear Selected")}
    `;
    clearAllBtn.onclick = () => {
        if (selectedCharacters.size === 0) return;
        selectedCharacters.clear();
        updateCountLabel();
        renderCurrentPage();
    };
    actionControls.appendChild(clearAllBtn);

    toolbar.appendChild(filterControls);
    toolbar.appendChild(actionControls);
    modalContainer.appendChild(toolbar);

    // 7. 构建主展示区：水平分栏 (左侧侧边栏 + 右侧卡片网格与分页)
    const mainSection = document.createElement("div");
    mainSection.className = "anima-character-body";
    mainSection.style.cssText = "display: flex; flex: 1; overflow: hidden; background: var(--uw-panel);";

    // 7A. 左侧侧边栏 - 分类与收藏
    const sidebar = document.createElement("div");
    sidebar.className = "anima-scrollbar";
    sidebar.style.cssText = `
        width: 250px;
        background: var(--uw-panel);
        border-right: 1px solid var(--uw-border);
        display: flex;
        flex-direction: column;
        overflow-y: auto;
        scrollbar-gutter: stable;
        padding: 20px 12px 20px 16px;
        box-sizing: border-box;
    `;
    sidebar.onscroll = () => {
        localStorage.setItem(SIDEBAR_SCROLL_STORAGE_KEY, sidebar.scrollTop);
    };

    // 侧边栏主标题
    const sidebarTitle = document.createElement("div");
    sidebarTitle.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--uw-accent);">
            <rect x="3" y="3" width="7" height="9"></rect>
            <rect x="14" y="3" width="7" height="5"></rect>
            <rect x="14" y="12" width="7" height="9"></rect>
            <rect x="3" y="16" width="7" height="5"></rect>
        </svg>
        <span>${t("Browse Categories")}</span>
    `;
    sidebarTitle.style.cssText = "font-size: 12px; font-weight: 800; color: var(--uw-muted); text-transform: uppercase; letter-spacing: 1px; display: flex; align-items: center; gap: 8px; margin-bottom: 12px; padding-left: 8px;";
    sidebar.appendChild(sidebarTitle);

    // 侧边栏列表容器
    const sidebarList = document.createElement("div");
    sidebarList.style.cssText = "display: flex; flex-direction: column;";
    sidebar.appendChild(sidebarList);

    mainSection.appendChild(sidebar);

    // 7B. 右侧展示区 (网格列表 + 分页控制)
    const gridArea = document.createElement("div");
    gridArea.className = "anima-character-grid-area";
    gridArea.style.cssText = "flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative;";

    // 卡片网格容器
    const listContainer = document.createElement("div");
    listContainer.className = "anima-scrollbar anima-character-list";
    listContainer.style.cssText = `
        flex: 1;
        overflow-y: auto;
        padding: 24px 28px;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        grid-auto-rows: 340px;
        gap: 20px;
        align-content: start;
    `;
    listContainer.onscroll = () => {
        hideCharacterTagsTooltip();
        localStorage.setItem(SCROLL_STORAGE_KEY, listContainer.scrollTop);
    };
    gridArea.appendChild(listContainer);

    // 创建图片懒加载观察器（绑定到 list 滚动容器）
    const charImageObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const el = entry.target;
                if (el.dataset.lazySrc) {
                    el.src = el.dataset.lazySrc;
                    delete el.dataset.lazySrc;
                }
                charImageObserver.unobserve(el);
            }
        });
    }, { root: listContainer, rootMargin: "300px" });

    // 分页控制栏 (Pagination Bar - 嵌入在网格区底部)
    const paginationBar = document.createElement("div");
    paginationBar.className = "anima-pagination";
    
    const pageStats = document.createElement("div");
    pageStats.className = "anima-pagination-stats";
    pageStats.innerText = t("Total {total} characters | Showing {start}-{end}", { total: 0, start: 0, end: 0 });

    const pageControls = document.createElement("div");
    pageControls.className = "anima-pagination-controls";

    const firstPageBtn = document.createElement("button");
    firstPageBtn.className = "anima-page-btn";
    firstPageBtn.innerText = t("First");
    firstPageBtn.onclick = () => goToPage(1);

    const prevPageBtn = document.createElement("button");
    prevPageBtn.className = "anima-page-btn";
    prevPageBtn.innerText = t("Prev");
    prevPageBtn.onclick = () => goToPage(currentPage - 1);

    const pageNumContainer = document.createElement("div");
    pageNumContainer.className = "anima-page-number";
    
    const pageInput = document.createElement("input");
    pageInput.className = "anima-page-input";
    pageInput.type = "text";
    pageInput.setAttribute("aria-label", t("Page number"));
    pageInput.value = "1";
    pageInput.onkeydown = (e) => {
        if (e.key === "Enter") {
            const val = parseInt(pageInput.value);
            if (!isNaN(val) && val >= 1 && val <= totalPages) {
                goToPage(val);
            } else {
                pageInput.value = currentPage;
            }
        }
    };

    const totalPagesLabel = document.createElement("span");
    totalPagesLabel.innerText = "/ 1 页";
    
    pageNumContainer.appendChild(pageInput);
    pageNumContainer.appendChild(totalPagesLabel);

    const nextPageBtn = document.createElement("button");
    nextPageBtn.className = "anima-page-btn";
    nextPageBtn.innerText = t("Next");
    nextPageBtn.onclick = () => goToPage(currentPage + 1);

    const lastPageBtn = document.createElement("button");
    lastPageBtn.className = "anima-page-btn";
    lastPageBtn.innerText = t("Last");
    lastPageBtn.onclick = () => goToPage(totalPages);

    pageControls.appendChild(firstPageBtn);
    pageControls.appendChild(prevPageBtn);
    pageControls.appendChild(pageNumContainer);
    pageControls.appendChild(nextPageBtn);
    pageControls.appendChild(lastPageBtn);

    paginationBar.appendChild(pageStats);
    paginationBar.appendChild(pageControls);
    gridArea.appendChild(paginationBar);

    mainSection.appendChild(gridArea);
    modalContainer.appendChild(mainSection);

    // 8. 构建 Footer / 底部操作栏
    const footer = document.createElement("div");
    footer.style.cssText = `
        padding: 20px 28px;
        border-top: 1px solid var(--uw-border);
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: var(--uw-panel);
    `;

    const countLabel = document.createElement("div");
    countLabel.style.cssText = "font-size: 14.5px; color: var(--uw-accent); font-weight: 700; display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; transition: opacity 0.2s ease;";
    countLabel.onmouseenter = () => {
        countLabel.style.opacity = "0.75";
    };
    countLabel.onmouseleave = () => {
        countLabel.style.opacity = "1";
    };
    countLabel.onclick = () => {
        showSelectedOnlyBtn.click();
    };
    
    function updateCountLabel() {
        countLabel.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--uw-accent);">
                <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            <span>${t("Selected: {count} characters", { count: selectedCharacters.size })}</span>
        `;
    }
    updateCountLabel();

    const footerButtons = document.createElement("div");
    footerButtons.style.cssText = "display: flex; gap: 12px;";

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "anima-btn";
    cancelBtn.innerText = "关闭";
    cancelBtn.onclick = () => closeModal();

    footerButtons.appendChild(cancelBtn);
    const insertionControls = mountSelectorInsertionActions(footerButtons, {app, node, widget: tagsWidget,
        resolveText: buildValidatedSelection,
        kind: 'character', getSelectedItems: getSelectedCharacterItems});

    let isClosed = false;
    async function buildValidatedSelection() {
        if (isClosed) throw new Error("选择器已关闭，请重新打开。");
        const selectedItems = getSelectedCharacterItems().map(item => item.shared ? structuredClone(item) : item);
        const keys = [...selectedCharacters];
        if (selectedItems.length !== keys.length) {
            throw new Error("所选资料已不可用，请重新选择。");
        }
        const previousText = tagsWidget.value;
        assertPromptTarget();
        await Promise.all(selectedItems.filter(item => !item.shared).map(item => fetchOfficialCharacterData(item)));
        await validateSharedPromptSelection("character", selectedItems);
        if (isClosed) throw new Error("选择器已关闭，请重新打开。");
        assertPromptTarget();
        if (JSON.stringify(keys) !== JSON.stringify([...selectedCharacters])) {
            throw new Error("选择已变化，请再次点击应用。");
        }
        if (tagsWidget.value !== previousText) {
            throw new Error("目标正文已变化，请确认当前内容后再次应用。");
        }
        if (selectedItems.some(item => item.shared)) {
            return selectedItems.map(item => item.shared ? item.tags
                : getCharacterPromptParts(item).join(", ")).join("\n");
        }
        const resultTags = [];
        const seen = new Set();
        selectedItems.forEach(item => {
            getCharacterPromptParts(item).forEach(tag => pushUniquePromptTokens(resultTags, seen, tag));
        });
        return resultTags.length ? resultTags.join(", ") + ", " : "";
    }
    footer.style.flexWrap = 'wrap';
    footer.appendChild(countLabel);
    footer.appendChild(footerButtons);
    modalContainer.appendChild(footer);

    modalOverlay.appendChild(modalContainer);
    document.body.appendChild(modalOverlay);
    const sharedResourceActions = appendSharedResourceActions(headerActions, {overlay:modalOverlay, kind:'character',
        getCollection:() => groups.some(group => group.id === activeFilters.type) ? activeFilters.type : null,
        reopen:async () => { await reopenSelector(modalOverlay, () => openCharacterSelectorModal(node, tagsWidget, selectedCharacters)); } });
    const stopLibrarySync = watchSharedLibrary(modalOverlay, 'character', async () => { await reopenSelector(modalOverlay, () => openCharacterSelectorModal(node, tagsWidget, selectedCharacters)); }, () => favoritesSaveInFlight || insertionControls.apply.disabled);

    // --- 数据筛选、分页与侧边栏渲染的实现 ---
    
    let filteredData = []; 
    let currentPage = parseInt(localStorage.getItem(PAGE_STORAGE_KEY)) || 1;   
    const pageSize = 60;   
    let totalPages = 1;    

    // 渲染侧边栏菜单 (包含性别、发色、瞳色、热门系列等多维特征过滤)
    function renderSidebar() {
        sidebarList.innerHTML = "";

        const clearFiltersBtn = document.createElement("button");
        clearFiltersBtn.type = "button";
        clearFiltersBtn.className = "sidebar-clear-filters-btn";
        clearFiltersBtn.innerHTML = `
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
            <span>${t("Clear Filters")}</span>
        `;
        clearFiltersBtn.disabled = !hasActiveSidebarFilters();
        clearFiltersBtn.onclick = clearSidebarFilters;
        sidebarList.appendChild(clearFiltersBtn);

        const isAllActive = (activeFilters.type === "all" || (activeFilters.type === "weilin" && hasOnlySharedCharacters))
            && selectedSharedCharacterFilters.size === 0;

        const allItem = document.createElement("div");
        allItem.className = `sidebar-item ${isAllActive ? "active" : ""}`;
        allItem.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;">
                <span style="font-size:15px;">✦</span>
                <span>${t("All Characters")}</span>
            </div>
            <span style="font-size:11px;opacity:0.6;background:var(--uw-raised);padding:2px 6px;border-radius:20px;">${characterData.length}</span>
        `;
        allItem.onclick = () => switchCategory("all");
        sidebarList.appendChild(allItem);

        const sharedCharacterCount = characterData.filter(item => item?.shared).length;
        if (sharedCharacterCount > 0) {
            if (sharedCharacterCount < characterData.length) {
                const sharedItem = document.createElement("div");
                sharedItem.className = `sidebar-item ${activeFilters.type === "weilin" && selectedSharedCharacterFilters.size === 0 ? "active" : ""}`;
                sharedItem.innerHTML = `
                    <div style="display:flex;align-items:center;gap:10px;">
                        <span style="font-size:15px;">↻</span>
                        <span>WeiLin 共享角色</span>
                    </div>
                    <span style="font-size:11px;opacity:0.8;background:var(--uw-accent-bg);color:var(--uw-accent);padding:2px 6px;border-radius:20px;font-weight:700;">${sharedCharacterCount}</span>
                `;
                sharedItem.onclick = () => switchCategory("weilin");
                sidebarList.appendChild(sharedItem);
            }

            appendSharedCategoryTree({
                kind: 'character',
                sidebar: sidebarList,
                items: characterData,
                selectedFilters: selectedSharedCharacterFilters,
                rowClass: "sidebar-item",
                storageKey: "anima-character-selector-shared-categories-collapsed-v2",
                onFilterChange: () => {
                    activeFilters.type = "weilin";
                    currentPage = 1;
                    localStorage.setItem(PAGE_STORAGE_KEY, 1);
                    localStorage.setItem(
                        SIDEBAR_STORAGE_KEY,
                        JSON.stringify(activeFilters),
                    );
                    persistSharedCharacterFilters();
                    renderSidebar();
                    triggerFilter();
                },
            });
        }

        // 2. 我的收藏标题与新建按钮
        const collectionsHeader = document.createElement("div");
        collectionsHeader.style.cssText = "font-size: 11px; font-weight: 700; color: var(--uw-muted); padding: 16px 10px 8px 10px; text-transform: uppercase; letter-spacing: 0.05em; display: flex; align-items: center; justify-content: space-between;";
        collectionsHeader.innerHTML = `
            <span>${t("My Collections")}</span>
            <span id="add-group-btn" style="cursor:pointer; font-size:16px; font-weight:bold; color:var(--uw-accent); opacity:0.8; border-radius: 4px; background: var(--uw-accent-bg); display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; line-height: 1 !important; padding: 0 !important; box-sizing: border-box !important; transition: all 0.2s ease;" title="${t("Create Group")}">+</span>
        `;
        sidebarList.appendChild(collectionsHeader);
        
        const addBtn = collectionsHeader.querySelector("#add-group-btn");
        addBtn.onmouseover = () => {
            addBtn.style.opacity = "1";
            addBtn.style.background = "var(--uw-accent-bg)";
            addBtn.style.transform = "scale(1.15)";
        };
        addBtn.onmouseout = () => {
            addBtn.style.opacity = "0.8";
            addBtn.style.background = "var(--uw-accent-bg)";
            addBtn.style.transform = "scale(1)";
        };
        addBtn.onclick = (e) => {
            e.stopPropagation();
            sharedResourceActions.collections({action:'create'});
        };

        // 3. 循环渲染分组列表 (粉色主题)
        groups.forEach(g => {
            const count = favoriteItems.filter(fi => fi.groupIds && fi.groupIds.includes(g.id)).length;
            const item = document.createElement("div");
            
            const isGroupActive = activeFilters.type === g.id;

            item.className = `sidebar-item ${isGroupActive ? "active" : ""}`;
            item.style.cssText = "position: relative;";
            
            const isDefault = g.id === "default";
            
            item.innerHTML = `
                <div style="display:flex;align-items:center;gap:10px; max-width: 60%; overflow:hidden;">
                    <span style="font-size:14px;">${isDefault ? '❤️' : '📁'}</span>
                    <span class="group-name-text" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"></span>
                </div>
                <div style="display:flex; align-items:center; gap: 8px;">
                    <span style="font-size:11px;opacity:0.8;background:${isDefault ? 'var(--uw-accent-bg)' : 'rgba(255,255,255,0.06)'};color:${isDefault ? 'var(--uw-accent)' : 'var(--uw-muted)'};padding:2px 6px;border-radius:20px;font-weight:700;">${count}</span>
                    ${!isDefault ? `
                        <div class="group-actions" style="display:flex; gap:6px; align-items:center; overflow:hidden; max-width:0; opacity:0; transform:translateX(10px); transition:all 0.25s cubic-bezier(0.4, 0, 0.2, 1);">
                            <span class="group-edit-btn" style="cursor:pointer; opacity:0.6; color:#e2e8f0; transition:opacity 0.2s; display:flex; align-items:center;" title="Rename">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                    <path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4Z"></path>
                                </svg>
                            </span>
                            <span class="group-del-btn" style="cursor:pointer; opacity:0.6; color:var(--uw-danger); transition:opacity 0.2s; display:flex; align-items:center;" title="Delete">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="3 6 5 6 21 6"></polyline>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                            </span>
                        </div>
                    ` : ''}
                </div>
            `;
            
            item.querySelector('.group-name-text').textContent = g.name;
            item.onclick = () => switchCategory(g.id);
            
            if (!isDefault) {
                const actionsContainer = item.querySelector(".group-actions");
                const editBtn = item.querySelector(".group-edit-btn");
                const delBtn = item.querySelector(".group-del-btn");
                
                item.onmouseenter = () => {
                    actionsContainer.style.maxWidth = "50px";
                    actionsContainer.style.opacity = "1";
                    actionsContainer.style.transform = "translateX(0)";
                };
                item.onmouseleave = () => {
                    actionsContainer.style.maxWidth = "0";
                    actionsContainer.style.opacity = "0";
                    actionsContainer.style.transform = "translateX(10px)";
                };
                
                editBtn.onmouseenter = () => editBtn.style.opacity = "1";
                editBtn.onmouseleave = () => editBtn.style.opacity = "0.6";
                editBtn.onclick = e => { e.stopPropagation(); sharedResourceActions.collections({groupId:g.id, action:'rename'}); };
                
                delBtn.onmouseenter = () => delBtn.style.opacity = "1";
                delBtn.onmouseleave = () => delBtn.style.opacity = "0.5";
                delBtn.onclick = e => { e.stopPropagation(); sharedResourceActions.collections({groupId:g.id, action:'delete'}); };
            }
            
            sidebarList.appendChild(item);
        });

    }

    function hasActiveSidebarFilters() {
        return (activeFilters.type !== "all" && (activeFilters.type !== "weilin" || !hasOnlySharedCharacters))
            || selectedSharedCharacterFilters.size > 0;
    }

    function clearSidebarFilters() {
        if (!hasActiveSidebarFilters()) return;
        activeFilters = { type: "all" };
        selectedSharedCharacterFilters.clear();
        persistSharedCharacterFilters();
        localStorage.setItem(SIDEBAR_STORAGE_KEY, JSON.stringify(activeFilters));
        currentPage = 1;
        localStorage.setItem(PAGE_STORAGE_KEY, 1);
        lastScrollTop = 0;
        localStorage.setItem(SCROLL_STORAGE_KEY, 0);
        renderSidebar();
        triggerFilter();
        listContainer.scrollTop = 0;
    }

    function switchCategory(category) {
        selectedSharedCharacterFilters.clear();
        persistSharedCharacterFilters();
        if (category === "all" || category === "weilin") {
            activeFilters.type = category;
        } else if (category === "favorites") {
            activeFilters.type = activeFilters.type === "default" ? "all" : "default";
        } else if (category === "default" || groups.some(group => group.id === category)) {
            activeFilters.type = activeFilters.type === category ? "all" : category;
        }
        localStorage.setItem(SIDEBAR_STORAGE_KEY, JSON.stringify(activeFilters));
        currentPage = 1;
        localStorage.setItem(PAGE_STORAGE_KEY, 1);
        lastScrollTop = 0;
        localStorage.setItem(SCROLL_STORAGE_KEY, 0);
        renderSidebar();
        triggerFilter();
        listContainer.scrollTop = 0;
    }

    function triggerFilter() {
        const query = searchInput.value.toLowerCase().trim();
        const searchAliases = item => [favoriteMap.get(getCharacterItemKey(item))?.nickname];
        const sortVal = sortSelect.value;

        // “已选择”视图直接使用全量已选，不与当前筛选条件取交集
        let items = [];
        if (showSelectedOnly) {
            const customItems = favoriteItems.filter(
                fi => fi.isCustom && selectedCharacters.has(getCharacterItemKey(fi)),
            );
            const normalItems = characterData.filter(
                item => selectedCharacters.has(getCharacterItemKey(item)),
            );
            items = [...customItems, ...normalItems];
        } else {
            items = characterData.slice();
            if (activeFilters.type === "weilin") {
                items = items.filter(item => item?.shared);
            }
            const isGroup = activeFilters.type === "default" || activeFilters.type.startsWith("group_");
            
            if (isGroup) {
                const groupItemKeys = new Set(
                    Array.from(favoriteMap.entries())
                        .filter(([, favorite]) => (
                            favorite.groupIds
                            && favorite.groupIds.includes(activeFilters.type)
                        ))
                        .map(([key]) => key),
                );
                items = items.filter(item => (
                    groupItemKeys.has(getCharacterItemKey(item))
                ));
                
                const customItems = favoriteItems.filter(fi => fi.isCustom && fi.groupIds && fi.groupIds.includes(activeFilters.type));
                items = [...customItems, ...items];
            }

            if (selectedSharedCharacterFilters.size > 0) {
                items = items.filter(item => itemMatchesCategoryFilters(
                    item,
                    selectedSharedCharacterFilters,
                ));
            }

            // B. 搜索关键词过滤
            if (query) {
                items = items.filter(item => {
                    return Number.isFinite(getPromptSearchRank(item, query, searchAliases(item)));
                });
            }
        }

        // C. 排序数据 (自定义项目置顶)
        if (sortVal === "works-desc") {
            items.sort((a, b) => {
                if (a.isCustom && b.isCustom) return 0;
                if (a.isCustom) return -1;
                if (b.isCustom) return 1;
                return b.post_count - a.post_count;
            });
        } else if (sortVal === "works-asc") {
            items.sort((a, b) => {
                if (a.isCustom && b.isCustom) return 0;
                if (a.isCustom) return -1;
                if (b.isCustom) return 1;
                return a.post_count - b.post_count;
            });
        } else if (sortVal === "fav-first") {
            items.sort((a, b) => {
                if (a.isCustom && b.isCustom) return 0;
                if (a.isCustom) return -1;
                if (b.isCustom) return 1;
                const aFav = favoriteSet.has(getCharacterItemKey(a)) ? 1 : 0;
                const bFav = favoriteSet.has(getCharacterItemKey(b)) ? 1 : 0;
                if (aFav !== bFav) return bFav - aFav;
                return b.post_count - a.post_count;
            });
        } else if (sortVal === "name-asc") {
            items.sort((a, b) => {
                const nameA = a.isCustom ? (a.nickname || a.name) : a.name;
                const nameB = b.isCustom ? (b.nickname || b.name) : b.name;
                if (a.isCustom && !b.isCustom) return -1;
                if (!a.isCustom && b.isCustom) return 1;
                return nameA.localeCompare(nameB);
            });
        } else if (sortVal === "name-desc") {
            items.sort((a, b) => {
                const nameA = a.isCustom ? (a.nickname || a.name) : a.name;
                const nameB = b.isCustom ? (b.nickname || b.name) : b.name;
                if (a.isCustom && !b.isCustom) return -1;
                if (!a.isCustom && b.isCustom) return 1;
                return nameB.localeCompare(nameA);
            });
        } else if (sortVal === "copyright-asc") {
            items.sort((a, b) => {
                if (a.isCustom && b.isCustom) return 0;
                if (a.isCustom) return -1;
                if (b.isCustom) return 1;
                const aCopy = a.copyright || "";
                const bCopy = b.copyright || "";
                if (aCopy !== bCopy) return aCopy.localeCompare(bCopy);
                return b.post_count - a.post_count;
            });
        }

        filteredData = rankPromptSearchResults(items, showSelectedOnly ? "" : query, searchAliases);
        
        totalPages = Math.ceil(filteredData.length / pageSize);
        if (totalPages === 0) totalPages = 1;
        
        if (currentPage > totalPages) currentPage = totalPages;
        if (currentPage < 1) currentPage = 1;

        updatePaginationBar();
        renderCurrentPage();
    }

    // 更新分页栏的交互状态
    function getPlaceholderGradient(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            hash = str.charCodeAt(i) + ((hash << 5) - hash);
        }
        const h1 = Math.abs(hash % 360);
        const h2 = (h1 + 45) % 360;
        return `linear-gradient(135deg, hsl(${h1}, 65%, 42%), hsl(${h2}, 60%, 26%))`;
    }

    function updatePaginationBar() {
        const totalItems = filteredData.length;
        const startIdx = totalItems === 0 ? 0 : (currentPage - 1) * pageSize + 1;
        const endIdx = Math.min(currentPage * pageSize, totalItems);
        
        pageStats.innerText = t("Total {total} characters | Showing {start}-{end}", { total: totalItems, start: startIdx, end: endIdx });
        
        pageInput.value = currentPage;
        totalPagesLabel.innerText = `/ ${totalPages} 页`;
        
        firstPageBtn.disabled = (currentPage === 1);
        prevPageBtn.disabled = (currentPage === 1);
        nextPageBtn.disabled = (currentPage === totalPages);
        lastPageBtn.disabled = (currentPage === totalPages);
    }

    function goToPage(pageNum) {
        if (pageNum < 1 || pageNum > totalPages) return;
        currentPage = pageNum;
        localStorage.setItem(PAGE_STORAGE_KEY, currentPage); 

        lastScrollTop = 0;
        localStorage.setItem(SCROLL_STORAGE_KEY, 0);

        updatePaginationBar();
        renderCurrentPage();
        listContainer.scrollTop = 0; 
    }

    function renderCurrentPage() {
        charImageObserver.disconnect();
        hideCharacterTagsTooltip();
        listContainer.innerHTML = "";
        
        const isCustomGroup = !showSelectedOnly && activeFilters.type.startsWith("group_");
        
        if (filteredData.length === 0 && !isCustomGroup) {
            const noResult = document.createElement("div");
            noResult.style.cssText = "grid-column: 1 / -1; padding: 60px; text-align: center; color: var(--uw-muted); font-size: 16px; font-weight: 500;";
            noResult.innerText = t("No matching characters found");
            listContainer.appendChild(noResult);
            return;
        }

        const currentPageData = filteredData.slice((currentPage - 1) * pageSize, currentPage * pageSize);
        const fragment = document.createDocumentFragment();
        
        // 如果是自定义分组，且当前在第一页，在最前面添加“新建自定义项”虚线卡片
        if (isCustomGroup && currentPage === 1) {
            const createCard = document.createElement("div");
            createCard.style.cssText = `
                background: var(--uw-raised) !important;
                border: 2px dashed var(--uw-accent) !important;
                border-radius: 16px !important;
                overflow: hidden !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: center !important;
                justify-content: center !important;
                width: 100% !important;
                height: 100% !important;
                min-height: 0 !important;
                cursor: pointer !important;
                transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important; 
                position: relative !important;
                user-select: none !important;
                box-sizing: border-box !important;
            `;
            
            const contentWrap = document.createElement("div");
            contentWrap.style.cssText = `
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 12px;
                box-sizing: border-box;
                padding: 16px;
                color: var(--uw-accent);
                transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), color 0.25s ease !important;
            `;
            
            contentWrap.innerHTML = `
                <div style="font-size: 44px; line-height: 1; font-weight: 300;">+</div>
                <div style="font-size: 13.5px; font-weight: 700; text-align: center;">${t("Create Custom Item")}</div>
            `;
            createCard.appendChild(contentWrap);
            
            createCard.onmouseenter = () => {
                createCard.style.setProperty("background", "var(--uw-accent-bg)", "important");
                createCard.style.setProperty("border-color", "var(--uw-accent)", "important");
                contentWrap.style.color = "var(--uw-text)";
                contentWrap.style.transform = "scale(1.08)";
            };
            createCard.onmouseleave = () => {
                createCard.style.setProperty("background", "var(--uw-raised)", "important");
                createCard.style.setProperty("border-color", "var(--uw-accent)", "important");
                contentWrap.style.color = "var(--uw-accent)";
                contentWrap.style.transform = "scale(1)";
            };
            
            createCard.onclick = (e) => {
                e.stopPropagation();
                sharedResourceActions.create();
            };
            
            fragment.appendChild(createCard);
        }
        
        currentPageData.forEach((item, index) => {
            const itemKey = getCharacterItemKey(item);
            const isSelected = selectedCharacters.has(itemKey);
            const isFavorite = item.isCustom ? true : favoriteSet.has(itemKey);
            
            const card = document.createElement("div");
            card.className = `anima-character-card${isSelected ? " selected" : ""}`;
            card.dataset.name = item.name;
            card.dataset.selectorKey = itemKey;
            
            card.style.cssText = `
                width: 100% !important;
                height: 100% !important;
                user-select: none !important;
            `;
            const cardClip = document.createElement("div");
            cardClip.className = "anima-character-card-clip";
            card.appendChild(cardClip);

            const tagsOverlay = createCharacterTagsOverlay(item);
            cardClip.appendChild(tagsOverlay);
            card.addEventListener("mouseenter", async () => {
                hideCharacterTagsTooltip();
                activeCharacterTagsTooltip = tagsOverlay;
                tagsOverlay.classList.add("is-visible");
                if (getExplicitCharacterTags(item).length === 0 && !item.isCustom && !item.shared) {
                    renderCharacterTagsOverlay(item, tagsOverlay, "loading");
                    const official = await fetchOfficialCharacterData(item);
                    if (activeCharacterTagsTooltip === tagsOverlay) {
                        renderCharacterTagsOverlay(item, tagsOverlay, official ? "idle" : "error");
                    }
                } else {
                    renderCharacterTagsOverlay(item, tagsOverlay, "idle");
                }
            });
            card.addEventListener("mouseleave", hideCharacterTagsTooltip);
            
            const checkbox = document.createElement("div");
            checkbox.style.cssText = `
                position: absolute;
                top: 12px;
                left: 12px;
                width: 22px;
                height: 22px;
                border-radius: 50%;
                background: ${isSelected ? 'var(--uw-accent-strong)' : 'var(--uw-raised)'};
                border: 1.5px solid ${isSelected ? 'var(--uw-accent)' : 'var(--uw-border)'};
                z-index: 10;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.2s ease;
                box-shadow: 0 2px 5px rgba(0,0,0,0.4);
            `;
            checkbox.innerHTML = isSelected ? `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            ` : '';
            card.appendChild(checkbox);

            const favIcon = document.createElement("button");
            favIcon.type = "button";
            favIcon.className = item.isCustom ? "anima-delete-btn" : "anima-favorite-btn";
            favIcon.title = `${t(item.isCustom ? "Delete Custom Item" : isFavorite ? "Remove from Favorites" : "Add to Favorites")}: ${item.name}`;
            favIcon.setAttribute("aria-label", favIcon.title);
            if (!item.isCustom) {
                favIcon.setAttribute("aria-pressed", String(isFavorite));
                favIcon.dataset.favoriteSourceKey = getPromptFavoriteSourceKey(item, characterData);
            }
            favIcon.style.cssText = `
                position: absolute;
                top: 10px;
                right: 10px;
                padding: 6px;
                z-index: 10;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.2s ease;
                cursor: pointer;
                border-radius: 50%;
                background: var(--uw-panel);
                backdrop-filter: blur(5px);
                -webkit-backdrop-filter: blur(5px);
                border: 1px solid var(--uw-border);
            `;
            
            if (item.isCustom) {
                favIcon.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--uw-danger)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                `;
                favIcon.onmouseover = (e) => {
                    e.stopPropagation();
                    favIcon.style.transform = "scale(1.15)";
                    favIcon.style.background = "rgba(239, 68, 68, 0.2)";
                };
                favIcon.onmouseout = (e) => {
                    e.stopPropagation();
                    favIcon.style.transform = "scale(1)";
                    favIcon.style.background = "rgba(10, 10, 15, 0.4)";
                };
                favIcon.onclick = async (e) => {
                    e.stopPropagation();
                    if (confirm(t("Are you sure you want to delete this custom item?"))) {
                        favoriteItems = favoriteItems.filter(
                            fi => getCharacterItemKey(fi) !== itemKey,
                        );
                        selectedCharacters.delete(itemKey);
                        if (!(await saveFavorites())) return;
                        triggerFilter();
                        renderSidebar();
                    }
                };
            } else {
                favIcon.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="${isFavorite ? 'var(--uw-accent)' : 'none'}" stroke="${isFavorite ? 'var(--uw-accent)' : 'var(--uw-text)'}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="transition: transform 0.2s ease;">
                        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
                    </svg>
                `;
                favIcon.onmouseover = (e) => {
                    e.stopPropagation();
                    favIcon.style.transform = "scale(1.15)";
                    favIcon.style.background = "rgba(10, 10, 15, 0.7)";
                    const svg = favIcon.querySelector('svg');
                    if (!favoriteSet.has(itemKey)) svg.setAttribute('stroke', 'var(--uw-accent)');
                };
                favIcon.onmouseout = (e) => {
                    e.stopPropagation();
                    favIcon.style.transform = "scale(1)";
                    favIcon.style.background = "rgba(10, 10, 15, 0.4)";
                    const svg = favIcon.querySelector('svg');
                    if (!favoriteSet.has(itemKey)) svg.setAttribute('stroke', 'var(--uw-text)');
                };
                favIcon.onclick = async (e) => {
                    e.stopPropagation();
                    if (favoriteSet.has(itemKey)) {
                        favoriteSet.delete(itemKey);
                        const svg = favIcon.querySelector('svg');
                        svg.setAttribute('fill', 'none');
                        svg.setAttribute('stroke', 'var(--uw-text)');
                    } else {
                        favoriteSet.add(itemKey);
                        const svg = favIcon.querySelector('svg');
                        svg.setAttribute('fill', 'var(--uw-accent)');
                        svg.setAttribute('stroke', 'var(--uw-accent)');
                        favIcon.style.transform = "scale(1.3) rotate(-10deg)";
                        setTimeout(() => favIcon.style.transform = "scale(1)", 200);
                        
                        let fav = favoriteMap.get(itemKey);
                        if (!fav) {
                            fav = makeFavoriteRecord(item, { groupIds: ["default"] });
                            favoriteMap.set(itemKey, fav);
                        } else if (!fav.groupIds.includes("default")) {
                            fav.groupIds.push("default");
                        }
                    }
                    favIcon.title = `${t(favoriteSet.has(itemKey) ? "Remove from Favorites" : "Add to Favorites")}: ${item.name}`;
                    favIcon.setAttribute("aria-label", favIcon.title);
                    favIcon.setAttribute("aria-pressed", String(favoriteSet.has(itemKey)));
                    if (!(await saveFavorites())) return;
                    renderSidebar(); 
                    if (activeFilters.type === "favorites" || activeFilters.type === "default" || activeFilters.type.startsWith("group_")) {
                        triggerFilter();
                    }
                };
            }
            card.appendChild(favIcon);


            const placeholder = document.createElement("div");
            placeholder.className = "anima-card-placeholder";
            
            let img = null;

            if (item.isCustom) {
                placeholder.style.cssText = `
                    position: absolute !important;
                    top: 0 !important;
                    left: 0 !important;
                    width: 100% !important;
                    height: 100% !important;
                    display: flex !important;
                    flex-direction: column !important;
                    align-items: center !important;
                    justify-content: center !important;
                    background: linear-gradient(135deg, #1e293b, #0f172a) !important;
                    z-index: 1 !important;
                    opacity: 1 !important;
                    text-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
                    box-sizing: border-box;
                    padding: 20px;
                `;
                placeholder.innerHTML = `
                    <div style="font-size: 48px; margin-bottom: 8px;">📄</div>
                    <div style="font-size: 11px; font-weight: 700; color: var(--uw-accent); background: var(--uw-accent-bg); border: 1px solid var(--uw-accent); padding: 2px 8px; border-radius: 20px; text-transform: uppercase;">Custom</div>
                `;
                cardClip.appendChild(placeholder);
            } else {
                placeholder.style.cssText = `
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background: ${getPlaceholderGradient(item.name)};
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    z-index: 1;
                    opacity: 0;
                    transition: opacity 0.25s ease;
                `;
                
                const initialLetter = document.createElement("span");
                initialLetter.innerText = item.name ? item.name.charAt(0).toUpperCase() : '?';
                initialLetter.style.cssText = "font-size: 56px; font-weight: 900; color: rgba(255,255,255,0.7); text-shadow: 0 4px 12px rgba(0,0,0,0.3);";
                placeholder.appendChild(initialLetter);
                cardClip.appendChild(placeholder);

                img = document.createElement("img");
                img.style.cssText = `
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                    z-index: 2;
                    opacity: 0;
                    transition: opacity 0.3s cubic-bezier(0.4, 0, 0.2, 1), transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                `;
                const eagerPreview = index < 12;
                img.loading = eagerPreview ? "eager" : "lazy";
                const imgUrl = getPersistentImageUrl(
                    item.preview || getImgUrl(item.name, item.copyright),
                );
                
                let loader = null;
                if (eagerPreview || isImageLoaded(imgUrl)) {
                    // 缓存命中：直接显示，跳过 spinner
                    img.src = imgUrl;
                    img.style.opacity = "1";
                } else {
                    // 未缓存：懒加载
                    img.dataset.lazySrc = imgUrl;
                    loader = document.createElement("div");
                    loader.className = "anima-shimmer";
                    const spinner = document.createElement("div");
                    spinner.className = "anima-spinner";
                    loader.appendChild(spinner);
                    cardClip.appendChild(loader);
                }
                
                img.onload = () => {
                    img.style.opacity = "1";
                    loader?.remove();
                    markImageLoaded(imgUrl);
                };
                img.onerror = () => {
                    img.style.display = "none";
                    loader?.remove();
                    placeholder.style.opacity = "1";
                };
                cardClip.appendChild(img);
                charImageObserver.observe(img);
            }

            const mask = document.createElement("div");
            mask.style.cssText = `
                position: absolute;
                inset: 0;
                background: linear-gradient(to top, rgba(10,10,16,0.99) 0%, rgba(10,10,16,0.72) 42%, rgba(10,10,16,0.16) 100%);
                z-index: 3;
                pointer-events: none;
            `;
            cardClip.appendChild(mask);

            const infoPanel = document.createElement("div");
            infoPanel.className = "anima-character-card-info";

            const nameEl = document.createElement("div");
            nameEl.className = "anima-character-card-title";
            
            const favInfo = item.isCustom ? item : favoriteMap.get(itemKey);
            const nickname = favInfo ? favInfo.nickname : "";
            let noteEl = null;

            if (item.isCustom) {
                nameEl.innerText = item.nickname || item.name;
            } else {
                const nameFormatted = item.name.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                if (nickname) {
                    nameEl.innerText = nameFormatted;
                    noteEl = document.createElement("div");
                    noteEl.className = "anima-character-card-sub";
                    noteEl.style.color = "var(--uw-accent)";
                    noteEl.innerText = nickname;
                } else {
                    nameEl.innerText = nameFormatted;
                }
            }
            
            const copyrightContainer = document.createElement("div");
            copyrightContainer.className = "anima-character-card-badges";
            
            if (!item.isCustom && item.copyright !== item.source_category) {
                const copyEl = document.createElement("span");
                copyEl.className = "anima-character-badge";
                copyEl.innerText = item.copyright || "";
                copyEl.title = item.copyright || "";
                copyEl.style.maxWidth = "150px";
                copyrightContainer.appendChild(copyEl);
            }

            const numEl = document.createElement("span");
            const postCountFormatted = item.post_count >= 1000 
                ? (item.post_count / 1000).toFixed(1).replace(/\.0$/, '') + 'k' 
                : item.post_count;
            numEl.innerText = item.shared ? `${getCharacterDisplayTags(item).length} Tags` : postCountFormatted;
            numEl.title = item.shared ? '主提示词的标签数量' : '作品数量';
            numEl.style.cssText = `
                font-size: 10.5px;
                color: var(--uw-muted);
                font-weight: 700;
                opacity: 0.9;
                white-space: nowrap;
                background: var(--uw-raised);
                border: 1px solid var(--uw-border);
                padding: 2px 6px;
                border-radius: 6px;
            `;
            copyrightContainer.appendChild(numEl);

            infoPanel.appendChild(nameEl);
            if (noteEl) infoPanel.appendChild(noteEl);
            infoPanel.appendChild(copyrightContainer);
            cardClip.appendChild(infoPanel);

            card.onclick = () => {
                if (selectedCharacters.has(itemKey)) {
                    selectedCharacters.delete(itemKey);
                    card.classList.remove("selected");
                    checkbox.style.background = "var(--uw-raised)";
                    checkbox.style.borderColor = "var(--uw-border-strong)";
                    checkbox.innerHTML = "";
                } else {
                    selectedCharacters.add(itemKey);
                    card.classList.add("selected");
                    checkbox.style.background = "var(--uw-accent-strong)";
                    checkbox.style.borderColor = "var(--uw-accent)";
                    checkbox.innerHTML = `
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                    `;
                }
                updateCountLabel();
            };

            appendSharedResourceEditor(card, item, async () => { await reopenSelector(modalOverlay, () => openCharacterSelectorModal(node, tagsWidget, selectedCharacters)); }, infoPanel);
            fragment.appendChild(card);
        });

        listContainer.appendChild(fragment);

        if (isFirstRender && lastScrollTop > 0) {
            listContainer.scrollTop = lastScrollTop;
            setTimeout(() => {
                listContainer.scrollTop = lastScrollTop;
            }, 30);
            setTimeout(() => {
                listContainer.scrollTop = lastScrollTop;
            }, 100);
            setTimeout(() => {
                listContainer.scrollTop = lastScrollTop;
            }, 250);
        }
    }

    // 隐藏/关闭弹窗
    function closeModal() {
        stopLibrarySync();
        isClosed = true;
        insertionControls.dispose();
        hideCharacterTagsTooltip();
        charImageObserver.disconnect();
        modalOverlay.remove();
        styleSheet.remove();
    }

    // 初始化渲染侧边栏和数据流
    renderSidebar();
    triggerFilter();
    
    // 恢复侧边栏滚动高度
    if (lastSidebarScrollTop > 0) {
        sidebar.scrollTop = lastSidebarScrollTop;
        setTimeout(() => {
            sidebar.scrollTop = lastSidebarScrollTop;
        }, 50);
        setTimeout(() => {
            sidebar.scrollTop = lastSidebarScrollTop;
        }, 150);
    }

    // 标记首次渲染结束
    isFirstRender = false;
}
