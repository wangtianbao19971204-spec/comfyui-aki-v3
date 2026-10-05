import { mergePromptItems, getPromptSearchRank, appendSharedResourceEditor, appendSharedResourceActions, watchSharedLibrary, appendSharedCategoryTree, getSharedCategoryRequestFilter, loadSharedLibraryTaxonomy } from "./anima_shared_prompt_data.js";
import { showToast as showSharedToast, mountSelectorInsertionActions, reopenSelector, captureSelectorFavoriteFocus, installSelectorDialog } from "./anima_selector_ui.js";
import { capturePromptTarget, appendUnresolvedPromptFavorites } from "./anima_prompt_identity.js";
import { app } from "../../scripts/app.js";
import { t } from "./i18n.js";
import { getPersistentImageUrl, markImageLoaded, isImageLoaded } from "./anima_image_utils.js";
import { createPromoLinks } from "./anima_promo_links.js";
import { addSelectorActionRow, installSelectorExecutionSync, isAnimaPromptPlusNode } from "./anima_selector_random.js";
import { assignPromptSelectorKeys, getPromptItemBaseKey, getPromptItemVariantKey, getPromptItemKey, getPromptFavoriteSourceKey, resolvePromptFavorites } from "./anima_prompt_identity.js";
import { recoverFavoritesConflict } from "./anima_favorites_recovery.js";

app.registerExtension({
    name: "AnimaArtistTagSelector.extension",

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "AnimaArtistTagSelector" || nodeData.name === "AnimaArtistTagSelectorPlus" || isAnimaPromptPlusNode(nodeData.name)) {
            installSelectorExecutionSync(nodeType);
            const origOnCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                origOnCreated?.apply(this, arguments);

                // 找到 artist_tags widget
                const artistTagsWidget = this.widgets.find(w => w.name === "artist_tags");
                if (!artistTagsWidget) return;
                
                addSelectorActionRow(this, {
                    section: "artist",
                    label: t("Open Artist Selector"),
                    accent: "var(--uw-accent, #a3b2ff)",
                    accentText: "var(--uw-accent)",
                    onOpen: async () => {
                        await openArtistSelectorModal(this, artistTagsWidget);
                    },
                });
            };
        }
    }
});

export async function openArtistSelectorModal(node, tagsWidget, restoredSelection = null) {
    const assertPromptTarget = capturePromptTarget(node, tagsWidget, () => app.graph);
    function showInitialLoadFailure(error, label) {
        const overlay = document.createElement("div");
        overlay.id = "anima-selector-overlay";
        overlay.style.cssText = "position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;background:rgba(8,10,18,.82);padding:20px;box-sizing:border-box;";
        const panel = document.createElement("div");
        panel.style.cssText = "width:min(440px,100%);padding:24px;border:1px solid var(--uw-border);border-radius:14px;background:var(--uw-panel,#202330);color:var(--uw-text,#fff);box-shadow:0 18px 50px rgba(0,0,0,.4);display:flex;align-items:center;";
        const content = document.createElement("div");
        content.style.cssText = "width:min(440px,100%);margin:auto;";
        const title = document.createElement("h2");
        title.textContent = `${label}加载失败`;
        title.style.cssText = "margin:0 0 10px;font-size:18px;";
        const message = document.createElement("p");
        message.textContent = error?.message || "请检查服务后重试。";
        message.setAttribute("role", "alert");
        message.style.cssText = "margin:0 0 20px;color:var(--uw-muted,#bbb);overflow-wrap:anywhere;";
        const actions = document.createElement("div");
        actions.style.cssText = "display:flex;gap:10px;flex-wrap:wrap;";
        const retry = document.createElement("button");
        retry.type = "button";
        retry.textContent = "重试加载";
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.textContent = "关闭";
        for (const button of [retry, cancel]) {
            button.style.cssText = "padding:9px 14px;border:1px solid var(--uw-border);border-radius:8px;background:var(--uw-raised,#303444);color:var(--uw-text,#fff);cursor:pointer;";
            actions.appendChild(button);
        }
        content.append(title, message, actions);
        panel.appendChild(content);
        overlay.appendChild(panel);
        document.body.appendChild(overlay);
        const disposeDialog = installSelectorDialog(overlay, {label: `${label}加载失败`, initialFocus: retry, close: () => overlay.unifiedClose()});
        overlay.unifiedClose = () => { overlay.remove(); disposeDialog(); };
        cancel.onclick = overlay.unifiedClose;
        retry.onclick = async () => {
            retry.disabled = true;
            retry.textContent = "正在重试…";
            await reopenSelector(overlay, () => openArtistSelectorModal(node, tagsWidget, restoredSelection));
        };
        overlay.unifiedFocus();
    }
    // 1. 解析当前节点中已经选中的 tags，兼容 @ 前缀和 by 前缀
    const currentTagsText = tagsWidget.value || "";
    const cleanArtistToken = (value) => {
        let clean = String(value || "").trim();
        if (clean.startsWith("@")) {
            clean = clean.substring(1).trim();
        } else if (clean.toLowerCase().startsWith("by ")) {
            clean = clean.substring(3).trim();
        }
        return clean;
    };
    const currentTokenSet = new Set(
        currentTagsText.split(",")
            .map(token => cleanArtistToken(token).toLowerCase())
            .filter(Boolean)
    );
    const selectedArtistNames = new Set(
        currentTagsText.split(",")
            .map(cleanArtistToken)
            .filter(t => t.length > 0)
    );

    const sharedCategoryFilters = new Set();
    const SORT_STORAGE_KEY = "anima-selector-active-sort";
    const PAGE_STORAGE_KEY = "anima-selector-active-page";
    const SCROLL_STORAGE_KEY = "anima-selector-active-scroll";
    const SIDEBAR_STORAGE_KEY = "anima-artist-active-sidebar-category";
    const SIDEBAR_SCROLL_STORAGE_KEY = "anima-artist-sidebar-scroll";
    let activeSort = localStorage.getItem(SORT_STORAGE_KEY) || "works-desc";
    let activeCategory = localStorage.getItem(SIDEBAR_STORAGE_KEY) || "all";
    if (activeCategory === "favorites") activeCategory = "default";
    const randomSeed = String(Math.random());

    async function requestArtistPage(options) {
        const response = await fetch("/anima-tools/artist-page", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(options), cache: "no-store",
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || `HTTP ${response.status}`);
        return result;
    }

    // 加载后端持久化配置
    let favoritesEtag = null;
    let favoritesSaveInFlight = false;
    let favoritesConfig = {
        artist: {
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
    
    let groups = favoritesConfig.artist.groups || [{ id: "default", name: t("My Favorites"), isSystem: true }];
    let favoriteItems = favoritesConfig.artist.items || [];
    const initialPage = Math.max(1, parseInt(localStorage.getItem(PAGE_STORAGE_KEY), 10) || 1);
    let initialCatalog;
    try {
        initialCatalog = await requestArtistPage({
            offset: (initialPage - 1) * 60, limit: 60, sort: activeSort, random_seed: randomSeed,
            include_tree: true,
            lookup_keys: [...(restoredSelection instanceof Set ? restoredSelection : []),
                ...favoriteItems.map(item => item.selectorKey || (item.id ? `shared:${item.id}` : ""))].filter(Boolean),
            lookup_names: [...selectedArtistNames, ...favoriteItems.filter(item => !item.selectorKey).map(item => item.name)].filter(Boolean),
        });
    } catch (error) { showInitialLoadFailure(error, "画师资料"); return; }
    let taxonomy;
    try { taxonomy = await loadSharedLibraryTaxonomy({ revision: initialCatalog.revision }); }
    catch (error) { showInitialLoadFailure(error, "画师分类"); return; }
    let catalogRevision = initialCatalog.revision;
    let allArtistCount = initialCatalog.catalog_count;
    const categoryTree = initialCatalog.tree || [];
    const artistItemsByKey = new Map();
    const rememberArtistItems = items => {
        const incoming = new Map();
        for (const item of items || []) {
            const base = getPromptItemBaseKey(item);
            if (!incoming.has(base)) incoming.set(base, []);
            incoming.get(base).push(item);
        }
        for (const [base, records] of incoming) {
            const previous = [...artistItemsByKey].filter(([, item]) => getPromptItemBaseKey(item) === base);
            const merged = mergePromptItems([], [...previous.map(([, item]) => item), ...records].map(item => {
                const {selectorKey, ...source} = item;
                return source;
            }));
            assignPromptSelectorKeys(merged);
            if (merged.length === 1 && previous.length === 1 && previous[0][1].selectorKey) {
                merged[0].selectorKey = previous[0][1].selectorKey;
            }
            previous.forEach(([key]) => artistItemsByKey.delete(key));
            merged.forEach(item => artistItemsByKey.set(getPromptItemKey(item), item));
            for (const item of records) {
                const variant = getPromptItemVariantKey(item);
                const match = merged.find(candidate => getPromptItemVariantKey(candidate) === variant);
                if (match?.selectorKey) item.selectorKey = match.selectorKey;
                else delete item.selectorKey;
            }
        }
    };
    rememberArtistItems([...initialCatalog.items, ...initialCatalog.lookup]);
    const selectedArtists = restoredSelection instanceof Set
        ? new Set([...restoredSelection].filter(key => artistItemsByKey.has(key)))
        : new Set([...artistItemsByKey.values()].filter(item => selectedArtistNames.has(item.name)).map(getPromptItemKey));
    const resolvedFavorites = resolvePromptFavorites([...artistItemsByKey.values()], favoriteItems);
    let favoriteMap = resolvedFavorites.map;
    let favoriteSet = resolvedFavorites.set;
    const unresolvedFavoriteItems = resolvedFavorites.unresolved;

    // 匹配已经勾选的自定义项
    favoriteItems.forEach(fi => {
        const customKeys = String(fi.customContent || "")
            .split(",")
            .map(token => cleanArtistToken(token).toLowerCase())
            .filter(Boolean);
        const isBareNumericCustom = customKeys.length === 1 && /^\d+$/.test(customKeys[0]);
        if (fi.isCustom && fi.customContent && customKeys.length > 0 && customKeys.every(key => currentTokenSet.has(key)) && !isBareNumericCustom) {
            selectedArtists.add(getPromptItemKey(fi));
        }
    });

    // CDN 镜像源配置 (保存在本地，下次自动读取)
    const CDN_STORAGE_KEY = "anima-selector-active-cdn";
    let activeCdn = localStorage.getItem(CDN_STORAGE_KEY) || "jsdelivr";

    // 记忆排序、页数和滚动位置配置 (本地持久化读取)

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
        // 保持自定义项
        favoriteItems.forEach(fi => {
            if (fi.isCustom) {
                nextItems.push(fi);
            }
        });
        // 保持系统项
        favoriteMap.forEach((val, key) => {
            if (favoriteSet.has(key)) {
                nextItems.push(val);
            }
        });
        unresolvedFavoriteItems.forEach(item => nextItems.push(item));
        
        favoriteItems = nextItems;
        favoritesConfig.artist.groups = groups;
        favoritesConfig.artist.items = favoriteItems;
        
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
        const draftSection = JSON.parse(JSON.stringify(favoritesConfig.artist || {}));
        try {
            return await recoverFavoritesConflict({ partition: "artist", draftSection, currentConfig: favoritesConfig, currentEtag: favoritesEtag, initialStatus, isActive: () => modalOverlay.isConnected && (!saveOwner || saveOwner.isConnected), fetchLatest: () => fetch("/anima-tools/favorites"),
                submit: async (config, etag) => { const r = await fetch("/anima-tools/favorites", { method: "POST", headers: { "Content-Type": "application/json", "If-Match": etag || "" }, body: JSON.stringify(config) }); return { ok: r.ok, status: r.status, etag: r.headers.get("ETag") || etag }; },
                commit: (config, etag) => { favoritesConfig = config; favoritesEtag = etag; groups = config.artist.groups || groups; favoriteItems = config.artist.items || favoriteItems; }, t });
        } catch (recoveryError) { console.error("Failed to recover favorites conflict", recoveryError); return false; }
    }



    
    


    
    let lastScrollTop = parseInt(localStorage.getItem(SCROLL_STORAGE_KEY)) || 0;
    let lastSidebarScrollTop = parseInt(localStorage.getItem(SIDEBAR_SCROLL_STORAGE_KEY)) || 0;
    let isFirstRender = true;

    function getImgUrl(partition, id) {
        if (activeCdn === "jsdelivr") {
            return `https://fastly.jsdelivr.net/gh/ThetaCursed/Anima-Assets@main/images/${partition}/${id}.webp`;
        } else if (activeCdn === "github") {
            return `https://raw.githubusercontent.com/ThetaCursed/Anima-Assets/main/images/${partition}/${id}.webp`;
        } else {
            return `https://cdn.statically.io/gh/ThetaCursed/Anima-Assets/main/images/${partition}/${id}.webp`;
        }
    }

    // 2. 创建 Modal DOM
    const modalOverlay = document.createElement("div");
    modalOverlay.id = "anima-selector-overlay";
    modalOverlay.unifiedClose=()=>closeModal();
    modalOverlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: var(--uw-panel);
        backdrop-filter: blur(15px);
        -webkit-backdrop-filter: blur(15px);
        z-index: 99999;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--uw-text);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    `;

    const modalContainer = document.createElement("div");
    modalContainer.id = "anima-selector-container";
    modalContainer.style.cssText = `
        width: 92%;
        max-width: 1320px;
        height: 90%;
        background: var(--uw-bg) !important;
        border: 1px solid var(--uw-border);
        border-radius: 24px;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        animation: animaFadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    `;

    // 点击外侧只关闭；写入仅由明确的应用按钮触发。
    modalOverlay.onclick = (e) => {
        if (e.target === modalOverlay) {
            closeModal();
        }
    };

    // 注入动画样式及 ComfyUI 原生经典蓝 var(--uw-accent, #a3b2ff) 强调色样式
    const styleSheet = document.createElement("style");
    styleSheet.textContent = `
        @keyframes animaFadeIn {
            from { opacity: 0; transform: scale(0.95) translateY(10px); }
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
            background: linear-gradient(90deg, rgba(20, 20, 30, 0.8) 25%, rgba(11, 140, 233, 0.12) 50%, rgba(20, 20, 30, 0.8) 75%) !important;
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
            border: 2.5px solid rgba(11, 140, 233, 0.15) !important;
            border-top: 2.5px solid var(--uw-accent, #a3b2ff) !important;
            border-radius: 50% !important;
            animation: animaSpin 0.85s infinite linear !important;
            z-index: 3 !important;
        }
        /* Custom Scrollbar */
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
        /* Buttons */
        .anima-btn {
            padding: 9px 18px;
            border-radius: 14px;
            font-size: 13.5px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            border: 1px solid var(--uw-border);
            background: var(--uw-raised);
            color: var(--uw-text);
            display: inline-flex;
            align-items: center;
            gap: 8px;
            user-select: none;
        }
        .anima-btn:hover:not(:disabled) {
            background: var(--uw-raised);
            color: white;
            border-color: var(--uw-border);
        }
        .anima-btn:disabled {
            opacity: 0.3;
            cursor: not-allowed;
        }
        .anima-btn-primary {
            background: linear-gradient(135deg, var(--uw-accent, #a3b2ff), var(--uw-accent));
            color: white;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(11, 140, 233, 0.3);
            border-color: rgba(11, 140, 233, 0.25);
        }
        .anima-btn-primary:hover:not(:disabled) {
            background: linear-gradient(135deg, var(--uw-accent), var(--uw-accent));
            box-shadow: 0 6px 16px rgba(11, 140, 233, 0.45);
        }
        .anima-btn-danger {
            background: rgba(239, 68, 68, 0.08);
            border: 1px solid rgba(239, 68, 68, 0.2);
            color: var(--uw-danger);
        }
        .anima-btn-danger:hover:not(:disabled) {
            background: rgba(239, 68, 68, 0.18);
            border-color: rgba(239, 68, 68, 0.35);
            color: white;
        }
        .anima-btn-active {
            background: rgba(11, 140, 233, 0.2) !important;
            border-color: rgba(11, 140, 233, 0.4) !important;
            color: var(--uw-accent) !important;
        }
        /* Pagination Bar */
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
            background: var(--uw-accent, #a3b2ff);
            box-shadow: 0 0 14px rgba(11,140,233,0.72);
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
            background: rgba(11,140,233,0.16);
            color: white;
            border-color: rgba(11,140,233,0.38);
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
            color: white;
            font-size: 13px;
            font-weight: 800;
            text-align: center;
            outline: none;
            transition: border-color 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
        }
        .anima-page-input:focus {
            background: transparent;
            border-bottom-color: rgba(11,140,233,0.72);
            box-shadow: none;
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
            user-select: none;
        }
        .sidebar-item:hover {
            background: var(--uw-raised);
            color: var(--uw-text);
        }
        .sidebar-item.active {
            background: linear-gradient(135deg, rgba(11, 140, 233, 0.15), rgba(2, 86, 145, 0.15)) !important;
            border-color: rgba(11, 140, 233, 0.3) !important;
            color: var(--uw-accent) !important;
            font-weight: 700 !important;
        }
        .anima-artist-card-clip {
            position: absolute;
            inset: 2.5px;
            z-index: 0;
            overflow: hidden;
            border-radius: 17px;
            clip-path: inset(0 round 17px);
            background: #0a0a10;
        }
        @media (max-width: 760px) {
            #anima-selector-overlay #anima-selector-container {
                width: 100% !important;
                height: 100% !important;
                border-radius: 0 !important;
            }
            #anima-selector-overlay .anima-artist-header { padding: 10px 12px !important; }
            #anima-selector-overlay .anima-artist-header h2 { font-size: 17px !important; }
            #anima-selector-overlay .anima-artist-header span,
            #anima-selector-overlay .anima-artist-promo { display: none !important; }
            #anima-selector-overlay .anima-artist-toolbar {
                padding: 8px 10px !important;
                gap: 7px !important;
            }
            #anima-selector-overlay .anima-artist-filters {
                min-width: 0 !important;
                width: 100%;
                flex-wrap: wrap;
                gap: 6px !important;
            }
            #anima-selector-overlay .anima-artist-search { min-width: 120px; max-width: none !important; }
            #anima-selector-overlay .anima-artist-filters select { min-width: 0; padding: 7px 8px !important; font-size: 12px !important; }
            #anima-selector-overlay .anima-artist-search input { padding: 7px 28px 7px 9px !important; }
            #anima-selector-overlay .anima-artist-actions { width: 100%; gap: 5px !important; flex-wrap: wrap; }
            #anima-selector-overlay .anima-artist-actions .anima-btn { padding: 6px 8px; font-size: 11px; }
            #anima-selector-overlay .anima-artist-category-toggle { display: inline-flex !important; }
            #anima-selector-overlay .anima-artist-main { min-height: 0; position: relative; }
            #anima-selector-overlay .anima-artist-sidebar { display: none !important; }
            #anima-selector-overlay .anima-artist-sidebar.mobile-open {
                display: flex !important;
                position: absolute;
                top: 0;
                bottom: 0;
                left: 0;
                z-index: 20;
                width: min(300px, 100%) !important;
                max-height: none;
                box-shadow: 12px 0 30px rgba(0,0,0,.45);
            }
            #anima-selector-overlay .anima-artist-grid { min-width: 0; }
            #anima-selector-overlay .anima-artist-list {
                padding: 10px !important;
                gap: 10px !important;
                grid-template-columns: repeat(auto-fill, minmax(135px, 1fr)) !important;
            }
            #anima-selector-overlay .anima-pagination { padding: 6px 8px; gap: 4px; }
            #anima-selector-overlay .anima-pagination-stats { min-height: 27px; padding: 0 7px; font-size: 11px; }
            #anima-selector-overlay .anima-pagination-controls { margin-left: 0; gap: 4px; }
            #anima-selector-overlay .anima-page-btn { min-height: 28px; padding: 0 7px; font-size: 11px; }
            #anima-selector-overlay .anima-page-input { width: 37px; }
            #anima-selector-overlay .anima-artist-footer { padding: 8px 10px !important; gap: 6px; }
            #anima-selector-overlay .anima-artist-footer .anima-btn { padding: 6px 8px; font-size: 11px; }
        }
        @media (max-width: 520px) {
            #unified-workbench #anima-selector-overlay {
                position: fixed !important;
                inset: 0 !important;
                width: 100vw !important;
                height: 100vh !important;
                z-index: 100000 !important;
            }
            #anima-selector-overlay .anima-artist-header { flex-wrap: wrap; gap: 5px; }
            #anima-selector-overlay .anima-artist-header-actions {
                width: 100%;
                justify-content: flex-start !important;
                overflow-x: auto;
            }
        }
    `;
    document.head.appendChild(styleSheet);

    // 3. 构建 Header
    const header = document.createElement("div");
    header.className = "anima-artist-header";
    header.style.cssText = `
        padding: 22px 28px;
        border-bottom: 1px solid var(--uw-border);
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: var(--uw-panel);
    `;
    
    const titleContainer = document.createElement("div");
    titleContainer.style.cssText = `
        display: flex;
        flex-direction: column;
        gap: 4px;
    `;
    const title = document.createElement("h2");
    title.innerText = t("Anima Artist Style Selector");
    title.style.cssText = "margin: 0; font-size: 22px; font-weight: 800; background: linear-gradient(135deg, var(--uw-accent), var(--uw-accent, #a3b2ff), var(--uw-accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: -0.5px;";
    
    const subtitle = document.createElement("span");
    subtitle.innerText = t("Browse and select your favorite artist styles, with 3:4 clear preview cards and precise pagination.");
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
    headerActions.className = "anima-artist-header-actions";
    headerActions.style.cssText = "display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex: 0 0 auto;";
    const promoLinks = createPromoLinks({ accentColor: "var(--uw-accent, #a3b2ff)" });
    promoLinks.classList.add("anima-artist-promo");
    headerActions.appendChild(promoLinks);
    headerActions.appendChild(closeBtn);

    header.appendChild(titleContainer);
    header.appendChild(headerActions);
    modalContainer.appendChild(header);

    // 4. 构建 Toolbar / 控制区
    const toolbar = document.createElement("div");
    toolbar.className = "anima-artist-toolbar";
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
    filterControls.className = "anima-artist-filters";
    filterControls.style.cssText = "display: flex; gap: 14px; align-items: center; flex: 1; min-width: 300px;";

    const searchInputWrapper = document.createElement("div");
    searchInputWrapper.className = "anima-artist-search";
    searchInputWrapper.style.cssText = "position: relative; flex: 1; max-width: 300px;";
    
    const searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.placeholder = t("Search artist name...");
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
        searchInput.style.borderColor = "var(--uw-accent, #a3b2ff)";
        searchInput.style.boxShadow = "0 0 14px rgba(11, 140, 233, 0.25), inset 0 2px 4px rgba(0,0,0,0.2)";
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
    let searchTimer = null;
    clearSearchBtn.onclick = () => {
        clearTimeout(searchTimer);
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
        ++filterGeneration;
        listContainer.inert = true;
        clearTimeout(searchTimer);
        if (!searchInput.composing) searchTimer = setTimeout(triggerFilter, 160);
    };
    searchInput.oncompositionstart = () => { searchInput.composing = true; clearTimeout(searchTimer); };
    searchInput.oncompositionend = () => { searchInput.composing = false; clearTimeout(searchTimer); triggerFilter(); };

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
        <option value="works-desc">${t("Works Count ⬇")}</option>
        <option value="works-asc">${t("Works Count ⬆")}</option>
        <option value="unique-desc">${t("Uniqueness Score ⬇")}</option>
        <option value="unique-asc">${t("Uniqueness Score ⬆")}</option>
        <option value="name-asc">${t("Name A-Z")}</option>
        <option value="name-desc">${t("Name Z-A")}</option>
        <option value="random">${t("Random")}</option>
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

    // 镜像源切换下拉菜单
    const cdnSelect = document.createElement("select");
    cdnSelect.style.cssText = `
        padding: 11px 18px;
        background: var(--uw-panel);
        border: 1px solid rgba(11, 140, 233, 0.2);
        border-radius: 14px;
        color: var(--uw-accent);
        font-size: 14px;
        font-weight: 600;
        outline: none;
        cursor: pointer;
        transition: all 0.25s ease;
    `;
    cdnSelect.innerHTML = `
        <option value="jsdelivr" ${activeCdn === "jsdelivr" ? "selected" : ""}>${t("CDN: JsDelivr (Recommended)")}</option>
        <option value="github" ${activeCdn === "github" ? "selected" : ""}>${t("CDN: GitHub Raw (Proxy)")}</option>
        <option value="statically" ${activeCdn === "statically" ? "selected" : ""}>${t("CDN: Statically")}</option>
    `;
    cdnSelect.onchange = () => {
        activeCdn = cdnSelect.value;
        localStorage.setItem(CDN_STORAGE_KEY, activeCdn);
        renderCurrentPage(); 
    };
    filterControls.appendChild(cdnSelect);



    // 右侧：功能按钮
    const actionControls = document.createElement("div");
    actionControls.className = "anima-artist-actions";
    actionControls.style.cssText = "display: flex; gap: 12px; align-items: center;";
    const sidebarToggle = document.createElement("button");
    sidebarToggle.className = "anima-btn anima-artist-category-toggle";
    sidebarToggle.style.display = "none";
    sidebarToggle.textContent = "分类";
    sidebarToggle.setAttribute("aria-expanded", "false");
    sidebarToggle.onclick = () => {
        const open = sidebar.classList.toggle("mobile-open");
        sidebarToggle.textContent = open ? "收起分类" : "分类";
        sidebarToggle.setAttribute("aria-expanded", String(open));
    };
    actionControls.appendChild(sidebarToggle);

    // 新加“复制已选”按钮
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
        if (selectedArtists.size === 0) {
            alert(t("Please select at least one artist first."));
            return;
        }
        const textToCopy = Array.from(selectedArtists).map(key => {
            const item = artistItemsByKey.get(key);
            const custom = favoriteItems.find(item => getPromptItemKey(item) === key);
            return item?.shared ? item.tags : custom?.isCustom ? custom.customContent : item?.name ? `@${item.name}` : '';
        }).filter(Boolean).join(", ");
        
        const performCopy = () => {
            showTemporaryToast(t("Copied Successfully"));
        };
        
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(textToCopy).then(performCopy).catch(() => {
                fallbackCopy(textToCopy, performCopy);
            });
        } else {
            fallbackCopy(textToCopy, performCopy);
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
                background: rgba(11, 140, 233, 0.2) !important;
                border-color: rgba(11, 140, 233, 0.4) !important;
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
        if (selectedArtists.size === 0) return;
        selectedArtists.clear();
        updateCountLabel();
        triggerFilter();
    };
    actionControls.appendChild(clearAllBtn);

    toolbar.appendChild(filterControls);
    toolbar.appendChild(actionControls);
    modalContainer.appendChild(toolbar);

    // 5. 构建主展示区：水平分栏 (左侧侧边栏 + 右侧卡片网格与分页)
    const mainSection = document.createElement("div");
    mainSection.className = "anima-artist-main";
    mainSection.style.cssText = "display: flex; flex: 1; overflow: hidden; background: var(--uw-panel);";

    // 5A. 左侧侧边栏 - 分类与收藏
    const sidebar = document.createElement("div");
    sidebar.className = "anima-scrollbar anima-artist-sidebar";
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
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--uw-accent, #a3b2ff);">
            <rect x="3" y="3" width="7" height="9"></rect>
            <rect x="14" y="3" width="7" height="5"></rect>
            <rect x="14" y="12" width="7" height="9"></rect>
            <rect x="3" y="16" width="7" height="5"></rect>
        </svg>
        <span>${t("Browse Categories")}</span>
    `;
    sidebarTitle.style.cssText = "font-size: 12px; font-weight: 800; color: var(--uw-muted); text-transform: uppercase; letter-spacing: 1px; display: flex; align-items: center; gap: 8px; margin-bottom: 12px; padding-left: 8px;";
    sidebar.appendChild(sidebarTitle);

    const sidebarList = document.createElement("div");
    sidebarList.style.cssText = "display: flex; flex-direction: column;";
    sidebar.appendChild(sidebarList);

    mainSection.appendChild(sidebar);

    // 5B. 右侧展示区 (网格列表 + 分页控制)
    const gridArea = document.createElement("div");
    gridArea.className = "anima-artist-grid";
    gridArea.style.cssText = "flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative;";

    // 画师卡片网格列表
    const listContainer = document.createElement("div");
    listContainer.className = "anima-scrollbar anima-artist-list";
    listContainer.style.cssText = `
        flex: 1;
        overflow-y: auto;
        padding: 24px 28px;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
        gap: 20px;
        align-content: start;
        background: rgba(15, 15, 20, 0.2);
    `;
    listContainer.onscroll = () => {
        localStorage.setItem(SCROLL_STORAGE_KEY, listContainer.scrollTop);
    };
    gridArea.appendChild(listContainer);

    // 创建图片懒加载观察器（绑定到 list 滚动容器）
    const artistImageObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const el = entry.target;
                if (el.dataset.lazySrc) {
                    el.src = el.dataset.lazySrc;
                    delete el.dataset.lazySrc;
                }
                artistImageObserver.unobserve(el);
            }
        });
    }, { root: listContainer, rootMargin: "300px" });

    // 6. 构建分页控制栏 (Pagination Bar - 嵌入在网格区底部)
    const paginationBar = document.createElement("div");
    paginationBar.className = "anima-pagination";
    
    const pageStats = document.createElement("div");
    pageStats.className = "anima-pagination-stats";
    pageStats.innerText = t("Total {total} artists | Showing {start}-{end}", { total: 0, start: 0, end: 0 });

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

    // 7. 构建 Footer / 底部操作栏
    const footer = document.createElement("div");
    footer.className = "anima-artist-footer";
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
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--uw-accent, #a3b2ff);">
                <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            <span>${t("Selected: {count} artist styles", { count: selectedArtists.size })}</span>
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
    const insertionControls = mountSelectorInsertionActions(footerButtons, {app, node, widget: tagsWidget, resolveText: buildValidatedSelection,
        kind: 'artist', getSelectedItems: () => [...selectedArtists].map(key => artistItemsByKey.get(key)
            || favoriteItems.find(item => item.isCustom && getPromptItemKey(item) === key))});

    async function buildValidatedSelection() {
        assertPromptTarget();
        const beforeText = tagsWidget.value;
        const beforeKeys = [...selectedArtists];
        const sharedKeys = beforeKeys.filter(key => artistItemsByKey.get(key)?.shared);
        if (sharedKeys.length) {
            const current = await requestArtistPage({revision: catalogRevision, lookup_keys: sharedKeys, limit: 1});
            const freshByKey = new Map(current.lookup.map(item => [getPromptItemKey(item), item]));
            for (const key of sharedKeys) {
                const old = artistItemsByKey.get(key);
                const fresh = freshByKey.get(key);
                if (!fresh || old.tags !== fresh.tags || old._semantic?.binding !== fresh._semantic?.binding) {
                    throw new Error("资料已变更或不再可用，请刷新列表后重新选择。");
                }
            }
        }
        if (!modalOverlay.isConnected || tagsWidget.value !== beforeText || JSON.stringify(beforeKeys) !== JSON.stringify([...selectedArtists])) throw new Error('目标或选择已变化，请重新应用。');
        assertPromptTarget();
        let resultTags = [];
        selectedArtists.forEach(selKey => {
            const custItem = favoriteItems.find(fi => fi.isCustom && getPromptItemKey(fi) === selKey);
            if (custItem) {
                const subTags = custItem.customContent.split(",");
                subTags.forEach(st => {
                    const stClean = st.strip ? st.strip() : st.trim();
                    if (stClean) {
                        resultTags.push(`_raw_:${stClean}`);
                    }
                });
            } else {
                const artist = artistItemsByKey.get(selKey);
                if (artist?.shared) resultTags.push(artist.tags);
                else if (artist?.name) resultTags.push(`@${artist.name}`);
            }
        });
        
        let resultString = resultTags.join(", ");
        if (resultString) {
            resultString += ", ";
        }
        return resultString;
    }
    footer.style.flexWrap = 'wrap';
    footer.appendChild(countLabel);
    footer.appendChild(footerButtons);
    modalContainer.appendChild(footer);

    modalOverlay.appendChild(modalContainer);
    document.body.appendChild(modalOverlay);
    const sharedResourceActions = appendSharedResourceActions(headerActions, {overlay:modalOverlay, kind:'artist',
        getCollection:() => groups.some(group => group.id === activeCategory) ? activeCategory : null,
        reopen:async () => { await reopenSelector(modalOverlay, () => openArtistSelectorModal(node, tagsWidget, selectedArtists)); } });
    const stopLibrarySync = watchSharedLibrary(modalOverlay, 'artist', async () => { await reopenSelector(modalOverlay, () => openArtistSelectorModal(node, tagsWidget, selectedArtists)); }, () => favoritesSaveInFlight || insertionControls.apply.disabled);

    // --- 数据筛选、分页与侧边栏渲染的实现 ---
    
    let filteredData = []; 
    let currentPage = parseInt(localStorage.getItem(PAGE_STORAGE_KEY)) || 1;   
    const pageSize = 60;   
    let totalPages = 1;    

    // 渲染侧边栏菜单
    // 渲染侧边栏菜单
    function renderSidebar() {
        sidebarList.innerHTML = "";

        // 1. 全部画师
        const allItem = document.createElement("div");
        allItem.className = `sidebar-item ${activeCategory === "all" ? "active" : ""}`;
        allItem.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;">
                <span style="font-size:15px;">✦</span>
                <span>${t("All Artists")}</span>
            </div>
            <span style="font-size:11px;opacity:0.6;background:var(--uw-raised);padding:2px 6px;border-radius:20px;">${allArtistCount}</span>
        `;
        allItem.onclick = () => switchCategory("all");
        sidebarList.appendChild(allItem);

        // 2. 我的收藏标题
        const collectionsHeader = document.createElement("div");
        collectionsHeader.style.cssText = "font-size: 11px; font-weight: 700; color: var(--uw-muted); padding: 16px 10px 8px 10px; text-transform: uppercase; letter-spacing: 0.05em; display: flex; align-items: center; justify-content: space-between;";
        collectionsHeader.innerHTML = `
            <span>${t("My Collections")}</span>
            <span id="add-group-btn" style="cursor:pointer; font-size:16px; font-weight:bold; color:var(--uw-accent, #a3b2ff); opacity:0.8; border-radius: 4px; background: rgba(11, 140, 233, 0.1); display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; line-height: 1 !important; padding: 0 !important; box-sizing: border-box !important; transition: all 0.2s ease;" title="${t("Create Group")}">+</span>
        `;
        sidebarList.appendChild(collectionsHeader);

        const addGroupBtn = collectionsHeader.querySelector("#add-group-btn");
        if (addGroupBtn) {
            addGroupBtn.onmouseenter = () => {
                addGroupBtn.style.opacity = "1";
                addGroupBtn.style.background = "rgba(11, 140, 233, 0.2)";
                addGroupBtn.style.transform = "scale(1.1)";
            };
            addGroupBtn.onmouseleave = () => {
                addGroupBtn.style.opacity = "0.8";
                addGroupBtn.style.background = "rgba(11, 140, 233, 0.1)";
                addGroupBtn.style.transform = "scale(1)";
            };
            addGroupBtn.onclick = (e) => {
                e.stopPropagation();
                sharedResourceActions.collections({action:'create'});
            };
        }

        // 3. 循环渲染分组列表
        groups.forEach(g => {
            const count = favoriteItems.filter(fi => fi.groupIds && fi.groupIds.includes(g.id)).length;
            const item = document.createElement("div");
            item.className = `sidebar-item ${activeCategory === g.id ? "active" : ""}`;
            item.style.cssText = "position: relative;";
            
            const isDefault = g.id === "default";
            
            item.innerHTML = `
                <div style="display:flex;align-items:center;gap:10px; max-width: 60%; overflow:hidden;">
                    <span style="font-size:14px;">${isDefault ? '❤️' : '📁'}</span>
                    <span class="group-name-text" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"></span>
                </div>
                <div style="display:flex; align-items:center; gap: 8px;">
                    <span style="font-size:11px;opacity:0.8;background:${isDefault ? 'rgba(11,140,233,0.15)' : 'rgba(255,255,255,0.06)'};color:${isDefault ? 'var(--uw-accent)' : 'var(--uw-muted)'};padding:2px 6px;border-radius:20px;font-weight:700;">${count}</span>
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
        appendSharedCategoryTree({kind:'artist', sidebar:sidebarList, tree:categoryTree, sourceOptions:initialCatalog.source_options || [], selectedFilters:sharedCategoryFilters,
            rowClass:'sidebar-item', storageKey:'anima-artist-unified-categories', onFilterChange:() => {
                sidebar.classList.remove('mobile-open'); sidebarToggle.textContent='分类'; sidebarToggle.setAttribute('aria-expanded','false');
                activeCategory='all'; currentPage=1; renderSidebar(); triggerFilter();
            }});
    }

    // 切换分类侧边栏
    function switchCategory(category) {
        sidebar.classList.remove('mobile-open'); sidebarToggle.textContent='分类'; sidebarToggle.setAttribute('aria-expanded','false');
        sharedCategoryFilters.clear();
        activeCategory = category;
        localStorage.setItem(SIDEBAR_STORAGE_KEY, category);
        
        const isCustomGroup = category !== "all" && category !== "default";
        
        currentPage = 1;
        localStorage.setItem(PAGE_STORAGE_KEY, 1);
        lastScrollTop = 0;
        localStorage.setItem(SCROLL_STORAGE_KEY, 0);

        renderSidebar();
        triggerFilter();
        listContainer.scrollTop = 0;
    }

    // 执行数据筛选与排序
    let totalItems = 0;
    let filterGeneration = 0;
    let initialCatalogUsed = false;
    const randomPriorities = new Map();
    const sortLocalItems = (items, sort) => {
        if (sort.startsWith("works-")) items.sort((a, b) => (sort.endsWith("desc") ? -1 : 1) * ((a.post_count || 0) - (b.post_count || 0)));
        else if (sort.startsWith("unique-")) items.sort((a, b) => {
            const ar = Number.isFinite(a.uniqueness_score), br = Number.isFinite(b.uniqueness_score);
            if (ar !== br) return Number(br) - Number(ar);
            return ar && br ? (sort.endsWith("desc") ? -1 : 1) * (a.uniqueness_score - b.uniqueness_score) : 0;
        });
        else if (sort.startsWith("name-")) items.sort((a, b) => (sort.endsWith("desc") ? -1 : 1) * String(a.nickname || a.name).localeCompare(String(b.nickname || b.name)));
        else if (sort === "random") items.sort((a, b) => {
            for (const item of [a, b]) if (!randomPriorities.has(getPromptItemKey(item))) randomPriorities.set(getPromptItemKey(item), Math.random());
            return randomPriorities.get(getPromptItemKey(a)) - randomPriorities.get(getPromptItemKey(b));
        });
        return items;
    };

    async function triggerFilter() {
        const generation = ++filterGeneration;
        const search = searchInput.value.toLowerCase().trim();
        const sort = sortSelect.value;
        const isGroup = activeCategory === "default" || activeCategory.startsWith("group_");
        if (showSelectedOnly) {
            listContainer.inert = false;
            const custom = favoriteItems.filter(item => item.isCustom && selectedArtists.has(getPromptItemKey(item)));
            const normal = [...artistItemsByKey.values()].filter(item => selectedArtists.has(getPromptItemKey(item)));
            const items = [...sortLocalItems(custom, sort), ...sortLocalItems(normal, sort)];
            totalItems = items.length;
            totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
            currentPage = Math.min(currentPage, totalPages);
            filteredData = items.slice((currentPage - 1) * pageSize, currentPage * pageSize);
            updatePaginationBar();
            renderCurrentPage();
            return;
        }

        const custom = isGroup ? favoriteItems.filter(item => item.isCustom && item.groupIds?.includes(activeCategory)
            && (!search || Number.isFinite(getPromptSearchRank(item, search)))) : [];
        sortLocalItems(custom, sort);
        const start = (currentPage - 1) * pageSize;
        const customPage = custom.slice(start, start + pageSize);
        const options = {
            revision: catalogRevision, search, sort, random_seed: randomSeed,
            filter: getSharedCategoryRequestFilter(sharedCategoryFilters),
            offset: Math.max(0, start - custom.length), limit: pageSize - customPage.length,
            aliases: Object.fromEntries([...favoriteMap].filter(([, item]) => item.nickname).map(([key, item]) => [key, item.nickname])),
        };
        if (isGroup) options.group_keys = [...favoriteMap].filter(([, item]) => item.groupIds?.includes(activeCategory)).map(([key]) => key);
        listContainer.inert = true;
        pageStats.innerText = "正在筛选画师…";
        try {
            const useInitial = !initialCatalogUsed && activeCategory === "all" && !search && !options.filter
                && currentPage === initialPage && sort === activeSort;
            initialCatalogUsed = true;
            const page = useInitial ? initialCatalog : await requestArtistPage(options);
            if (generation !== filterGeneration || !modalOverlay.isConnected) return;
            for (const key of artistItemsByKey.keys()) {
                if (!selectedArtists.has(key) && !favoriteSet.has(key)) artistItemsByKey.delete(key);
            }
            rememberArtistItems(page.items);
            if (favoriteMap.size || favoriteItems.some(item => !item.isCustom)) {
                const currentFavorites = [
                    ...Array.from(favoriteMap).filter(([key]) => favoriteSet.has(key)).map(([, value]) => value),
                    ...unresolvedFavoriteItems,
                ];
                const restoredFavorites = resolvePromptFavorites([...artistItemsByKey.values()], currentFavorites);
                favoriteMap.clear();
                restoredFavorites.map.forEach((value, key) => favoriteMap.set(key, value));
                favoriteSet.clear();
                restoredFavorites.set.forEach(key => favoriteSet.add(key));
                unresolvedFavoriteItems.splice(0, unresolvedFavoriteItems.length, ...restoredFavorites.unresolved);
                appendUnresolvedPromptFavorites(titleContainer, unresolvedFavoriteItems);
            }
            allArtistCount = page.catalog_count;
            totalItems = custom.length + page.total;
            totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
            if (currentPage > totalPages) { currentPage = totalPages; triggerFilter(); return; }
            filteredData = [...customPage, ...page.items.slice(0, pageSize - customPage.length)];
            updatePaginationBar();
            renderCurrentPage();
        } catch (error) {
            if (generation !== filterGeneration || !modalOverlay.isConnected) return;
            filteredData = [];
            const failure = document.createElement("div");
            failure.style.gridColumn = "1 / -1";
            failure.setAttribute("role", "alert");
            failure.textContent = error.message || "画师列表加载失败。";
            const retry = document.createElement("button");
            retry.type = "button";
            retry.className = "anima-page-btn anima-artist-retry-btn";
            retry.textContent = "重试加载";
            retry.style.marginTop = "12px";
            retry.style.display = "block";
            retry.onclick = async () => {
                const restoreFocus = document.activeElement === retry;
                await triggerFilter();
                if (restoreFocus && modalOverlay.isConnected && document.activeElement === document.body)
                    (listContainer.querySelector(".anima-artist-retry-btn") || searchInput).focus({preventScroll: true});
            };
            failure.appendChild(retry);
            listContainer.replaceChildren(failure);
            pageStats.innerText = "画师列表加载失败";
        } finally {
            if (generation === filterGeneration) listContainer.inert = false;
        }
    }

    // 更新分页栏的交互状态
    function updatePaginationBar() {
        const startIdx = totalItems === 0 ? 0 : (currentPage - 1) * pageSize + 1;
        const endIdx = Math.min(currentPage * pageSize, totalItems);
        
        pageStats.innerText = t("Total {total} artists | Showing {start}-{end}", { total: totalItems, start: startIdx, end: endIdx });
        
        pageInput.value = currentPage;
        totalPagesLabel.innerText = `/ ${totalPages} 页`;
        
        firstPageBtn.disabled = (currentPage === 1);
        prevPageBtn.disabled = (currentPage === 1);
        nextPageBtn.disabled = (currentPage === totalPages);
        lastPageBtn.disabled = (currentPage === totalPages);
    }

    // 翻页操作
    function goToPage(pageNum) {
        if (pageNum < 1 || pageNum > totalPages) return;
        currentPage = pageNum;
        localStorage.setItem(PAGE_STORAGE_KEY, currentPage); 

        lastScrollTop = 0;
        localStorage.setItem(SCROLL_STORAGE_KEY, 0);

        triggerFilter();
        listContainer.scrollTop = 0; 
    }

    // 复制通知提示框
    function showTemporaryToast(msg) {
        const toast = document.createElement("div");
        toast.className = "anima-toast-inline";
        toast.innerText = msg;
        toast.style.cssText = `
            position: fixed !important;
            bottom: 30px !important;
            right: 30px !important;
            background: var(--uw-panel) !important;
            border: 1px solid rgba(11, 140, 233, 0.45) !important;
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
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.transition = "opacity 0.3s ease";
            toast.style.opacity = "0";
            setTimeout(() => toast.remove(), 300);
        }, 1500);
    }

    // 备用文本复制
    function fallbackCopy(text, callback) {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed"; 
        textArea.style.opacity = "0";
        document.body.appendChild(textArea);
        textArea.select();
        try {
            document.execCommand("copy");
            callback();
        } catch (err) {
            console.error("Fallback copy failed", err);
        }
        textArea.remove();
    }

    // 渲染当前页的画师卡片
    function renderCurrentPage() {
        artistImageObserver.disconnect();
        listContainer.innerHTML = "";
        
        const isCustomGroup = !showSelectedOnly && activeCategory !== "all" && activeCategory !== "default";
        
        if (filteredData.length === 0 && !isCustomGroup) {
            const noResult = document.createElement("div");
            noResult.style.cssText = "grid-column: 1 / -1; padding: 60px; text-align: center; color: var(--uw-muted); font-size: 16px; font-weight: 500;";
            noResult.innerText = t("No matching artist styles found");
            listContainer.appendChild(noResult);
            return;
        }

        const currentPageData = filteredData;
        const fragment = document.createDocumentFragment();
        
        // 如果是自定义分组，且当前在第一页，在最前面添加“新建自定义项”虚线卡片
        if (isCustomGroup && currentPage === 1) {
            const createCard = document.createElement("div");
            createCard.style.cssText = `
                background: var(--uw-raised) !important;
                border: 2px dashed rgba(11, 140, 233, 0.4) !important;
                border-radius: var(--uw-radius, 12px) !important;
                overflow: hidden !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: center !important;
                justify-content: center !important;
                width: 100% !important;
                height: 0 !important;
                padding-bottom: 133.33% !important; 
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
                createCard.style.setProperty("background", "rgba(11, 140, 233, 0.05)", "important");
                createCard.style.setProperty("border-color", "rgba(11, 140, 233, 0.8)", "important");
                contentWrap.style.color = "var(--uw-text)";
                contentWrap.style.transform = "scale(1.08)";
            };
            createCard.onmouseleave = () => {
                createCard.style.setProperty("background", "var(--uw-raised)", "important");
                createCard.style.setProperty("border-color", "rgba(11, 140, 233, 0.4)", "important");
                contentWrap.style.color = "var(--uw-accent)";
                contentWrap.style.transform = "scale(1)";
            };
            
            createCard.onclick = (e) => {
                e.stopPropagation();
                sharedResourceActions.create();
            };
            
            fragment.appendChild(createCard);
        }
        
        currentPageData.forEach(item => {
            const isSelected = selectedArtists.has(getPromptItemKey(item));
            const isFavorite = item.isCustom ? true : favoriteSet.has(getPromptItemKey(item));
            
            const card = document.createElement("div");
            card.dataset.key = getPromptItemKey(item);
            card.classList.toggle('selected', isSelected);
            
            card.style.cssText = `
                background: var(--uw-panel, #1d2330) !important;
                border: ${isSelected ? '2.5px solid var(--uw-accent, #a3b2ff)' : '2.5px solid var(--uw-border)'} !important;
                border-radius: var(--uw-radius, 12px) !important;
                overflow: hidden !important;
                display: block !important;
                width: 100% !important;
                height: 0 !important;
                padding-bottom: 133.33% !important; 
                cursor: pointer !important;
                transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important; 
                position: relative !important;
                user-select: none !important;
                box-sizing: border-box !important;
                isolation: isolate !important;
                box-shadow: ${isSelected ? '0 10px 25px rgba(11, 140, 233, 0.35)' : '0 4px 12px rgba(0,0,0,0.15)'} !important;
            `;
            const cardClip = document.createElement("div");
            cardClip.className = "anima-artist-card-clip";
            card.appendChild(cardClip);
            
            // Checkbox overlay (放在左上角)
            const checkbox = document.createElement("div");
            checkbox.style.cssText = `
                position: absolute !important;
                top: 12px !important;
                left: 12px !important;
                width: 22px !important;
                height: 22px !important;
                border-radius: 50% !important;
                background: ${isSelected ? 'var(--uw-accent-strong)' : 'var(--uw-raised)'} !important;
                border: 1.5px solid ${isSelected ? 'var(--uw-accent, #a3b2ff)' : 'var(--uw-border)'} !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                z-index: 10 !important;
                transition: all 0.2s ease !important;
                box-shadow: 0 2px 5px rgba(0,0,0,0.4);
            `;
            checkbox.innerHTML = isSelected ? `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            ` : '';
            card.appendChild(checkbox);

            // ❤️ 收藏爱心图标 / 🗑️ 删除自定义项 (放在右上角)
            const favIcon = document.createElement("button");
            favIcon.type = "button";
            favIcon.className = item.isCustom ? "anima-delete-btn" : "anima-favorite-btn";
            favIcon.title = `${t(item.isCustom ? "Delete Custom Item" : isFavorite ? "Remove from Favorites" : "Add to Favorites")}: ${item.name}`;
            favIcon.setAttribute("aria-label", favIcon.title);
            if (!item.isCustom) {
                favIcon.setAttribute("aria-pressed", String(isFavorite));
                favIcon.dataset.favoriteSourceKey = getPromptFavoriteSourceKey(item, [...artistItemsByKey.values()]);
            }
            favIcon.style.cssText = `
                position: absolute !important;
                top: 10px !important;
                right: 10px !important;
                padding: 6px !important;
                z-index: 10 !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                transition: all 0.2s ease !important;
                cursor: pointer !important;
                border-radius: 50% !important;
                background: var(--uw-panel) !important;
                backdrop-filter: blur(5px) !important;
                -webkit-backdrop-filter: blur(5px) !important;
                border: 1px solid var(--uw-border) !important;
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
                        favoriteItems = favoriteItems.filter(fi => fi.name !== item.name);
                        selectedArtists.delete(getPromptItemKey(item));
                        if (!(await saveFavorites())) return;
                        triggerFilter();
                        renderSidebar();
                    }
                };
            } else {
                favIcon.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="${isFavorite ? 'var(--uw-accent, #a3b2ff)' : 'none'}" stroke="${isFavorite ? 'var(--uw-accent, #a3b2ff)' : 'var(--uw-text)'}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="transition: transform 0.2s ease;">
                        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
                    </svg>
                `;
                favIcon.onmouseover = (e) => {
                    e.stopPropagation();
                    favIcon.style.transform = "scale(1.15)";
                    favIcon.style.background = "rgba(10, 10, 15, 0.7)";
                    const svg = favIcon.querySelector('svg');
                    if (!favoriteSet.has(getPromptItemKey(item))) svg.setAttribute('stroke', 'var(--uw-accent, #a3b2ff)');
                };
                favIcon.onmouseout = (e) => {
                    e.stopPropagation();
                    favIcon.style.transform = "scale(1)";
                    favIcon.style.background = "rgba(10, 10, 15, 0.4)";
                    const svg = favIcon.querySelector('svg');
                    if (!favoriteSet.has(getPromptItemKey(item))) svg.setAttribute('stroke', 'var(--uw-text)');
                };
                favIcon.onclick = async (e) => {
                    e.stopPropagation();
                    const sourceKey = getPromptFavoriteSourceKey(item, [...artistItemsByKey.values()]);
                    if (!favoriteSet.has(getPromptItemKey(item)) && !sourceKey) {
                        showSharedToast("该来源有不同正文变体，无法唯一绑定收藏；请核对资料后重试。");
                        return;
                    }
                    if (favoriteSet.has(getPromptItemKey(item))) {
                        favoriteSet.delete(getPromptItemKey(item));
                        const svg = favIcon.querySelector('svg');
                        svg.setAttribute('fill', 'none');
                        svg.setAttribute('stroke', 'var(--uw-text)');
                    } else {
                        favoriteSet.add(getPromptItemKey(item));
                        const svg = favIcon.querySelector('svg');
                        svg.setAttribute('fill', 'var(--uw-accent, #a3b2ff)');
                        svg.setAttribute('stroke', 'var(--uw-accent, #a3b2ff)');
                        favIcon.style.transform = "scale(1.3) rotate(-10deg)";
                        setTimeout(() => favIcon.style.transform = "scale(1)", 200);
                        
                        let fav = favoriteMap.get(getPromptItemKey(item));
                        if (!fav) {
                            fav = { id: item.id, name: item.name, selectorKey: sourceKey, nickname: "", groupIds: ["default"], isCustom: false };
                            favoriteMap.set(getPromptItemKey(item), fav);
                        } else if (!fav.groupIds.includes("default")) {
                            fav.groupIds.push("default");
                        }
                    }
                    favIcon.title = `${t(favoriteSet.has(getPromptItemKey(item)) ? "Remove from Favorites" : "Add to Favorites")}: ${item.name}`;
                    favIcon.setAttribute("aria-label", favIcon.title);
                    favIcon.setAttribute("aria-pressed", String(favoriteSet.has(getPromptItemKey(item))));
                    if (!(await saveFavorites())) return;
                    renderSidebar(); 
                    if (activeCategory === "favorites" || activeCategory === "default" || activeCategory.startsWith("group_")) {
                        triggerFilter();
                    }
                };
            }
            card.appendChild(favIcon);

            // ✏️ 编辑备注按钮 (放在右上角心形按钮下方)

            // Image Element or Custom Placeholder
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
                let firstChar = "A";
                if (item.name) {
                    const cleanName = item.name.replace(/[^a-zA-Z]/g, "");
                    firstChar = cleanName.length > 0 ? cleanName[0].toUpperCase() : item.name[0].toUpperCase();
                }
                
                let hash = 0;
                for (let i = 0; i < item.name.length; i++) {
                    hash = item.name.charCodeAt(i) + ((hash << 5) - hash);
                }
                const hue = Math.abs(hash % 360);
                
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
                    font-size: 56px !important;
                    font-weight: 900 !important;
                    color: rgba(255,255,255,0.7) !important;
                    background: linear-gradient(135deg, hsl(${hue}, 45%, 32%), hsl(${(hue + 45) % 360}, 50%, 18%)) !important;
                    z-index: 1 !important;
                    opacity: 0 !important;
                    transition: opacity 0.25s ease !important;
                    text-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
                `;
                placeholder.innerText = firstChar;
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
                img.loading = "lazy";
                
                const partition = item.p || 1;
                const imgUrl = getPersistentImageUrl(item.preview || getImgUrl(partition, item.asset_id || item.id));
                
                let loader = null;
                if (isImageLoaded(imgUrl)) {
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
                artistImageObserver.observe(img);
            }

            const mask = document.createElement("div");
            mask.style.cssText = `
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: linear-gradient(to top, rgba(14, 14, 18, 0.98) 0%, rgba(14, 14, 18, 0.55) 45%, rgba(0, 0, 0, 0) 100%);
                z-index: 3;
            `;
            cardClip.appendChild(mask);

            // Info Section
            const infoPanel = document.createElement("div");
            infoPanel.className = "anima-artist-card-info";
            infoPanel.style.cssText = `
                position: absolute;
                bottom: 0;
                left: 0;
                width: 100%;
                padding: 16px 14px;
                box-sizing: border-box;
                z-index: 4;
                display: flex;
                flex-direction: column;
                gap: 5px;
            `;
            
            const nameEl = document.createElement("div");
            nameEl.style.cssText = "font-size: 14px; font-weight: 800; color: #ffffff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-shadow: 0 2px 4px rgba(0,0,0,0.6);";
            
            const favInfo = item.isCustom ? item : favoriteMap.get(getPromptItemKey(item));
            const nickname = favInfo ? favInfo.nickname : "";
            
            if (item.isCustom) {
                nameEl.innerText = item.nickname || item.name;
            } else {
                const displayName = item.name.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                if (nickname) {
                    nameEl.innerHTML = `${displayName} <span style="font-size:11px;color:#a7f3d0;font-weight:normal;display:block;margin-top:2px;overflow:hidden;text-overflow:ellipsis;">✏️ ${nickname}</span>`;
                } else {
                    nameEl.innerText = displayName;
                }
            }
            
            const statsContainer = document.createElement("div");
            statsContainer.style.cssText = "display: flex; align-items: center; justify-content: space-between; width: 100%; overflow: hidden; gap: 8px;";
            
            if (item.isCustom) {
                const customPreview = document.createElement("span");
                customPreview.innerText = item.customContent || "";
                customPreview.style.cssText = "font-size: 11px; color: var(--uw-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: monospace; max-width: 100%;";
                statsContainer.appendChild(customPreview);
            } else {
                const worksEl = document.createElement("span");
                worksEl.innerText = `${item.post_count} w`;
                worksEl.style.cssText = `
                    font-size: 10px;
                    font-weight: 700;
                    color: var(--uw-accent);
                    background: rgba(11, 140, 233, 0.15);
                    border: 1px solid rgba(11, 140, 233, 0.25);
                    padding: 2.5px 8px;
                    border-radius: 9999px;
                    white-space: nowrap;
                `;
                
                const uniqueEl = document.createElement("span");
                const hasScore = Number.isFinite(item.uniqueness_score);
                uniqueEl.innerText = hasScore
                    ? `${t("Uniqueness ")}${item.uniqueness_score.toFixed(1)}`
                    : "暂无评分";
                uniqueEl.style.cssText = `
                    font-size: 10.5px;
                    color: #fbbf24;
                    font-weight: 700;
                    white-space: nowrap;
                    background: rgba(251, 191, 36, 0.08);
                    border: 1px solid rgba(251, 191, 36, 0.15);
                    padding: 2px 6px;
                    border-radius: 6px;
                `;
                
                if (!hasScore) {
                    uniqueEl.style.color = "var(--uw-muted)";
                    uniqueEl.style.background = "var(--uw-raised)";
                    uniqueEl.style.borderColor = "var(--uw-border)";
                }
                if (Number.isFinite(item.post_count)) statsContainer.appendChild(worksEl);
                statsContainer.appendChild(uniqueEl);
            }
            
            infoPanel.appendChild(nameEl);
            infoPanel.appendChild(statsContainer);
            cardClip.appendChild(infoPanel);

            // 点击卡片选择
            card.onclick = () => {
                const name = card.dataset.key;
                card.classList.toggle('selected', !selectedArtists.has(name));
                if (selectedArtists.has(name)) {
                    selectedArtists.delete(name);
                    card.style.borderColor = "rgba(255, 255, 255, 0.04)";
                    card.style.boxShadow = "0 4px 12px rgba(0,0,0,0.15)";
                    checkbox.style.background = "var(--uw-raised)";
                    checkbox.style.borderColor = "var(--uw-border-strong)";
                    checkbox.innerHTML = "";
                } else {
                    selectedArtists.add(name);
                    card.style.borderColor = "var(--uw-accent, #a3b2ff)";
                    card.style.boxShadow = "0 10px 25px rgba(11, 140, 233, 0.35)";
                    checkbox.style.background = "var(--uw-accent-strong)";
                    checkbox.style.borderColor = "var(--uw-accent, #a3b2ff)";
                    checkbox.innerHTML = `
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                    `;
                }
                updateCountLabel();
                if (showSelectedOnly) triggerFilter();
            };

            card.onmouseenter = () => {
                if (!selectedArtists.has(card.dataset.key)) {
                    card.style.borderColor = "rgba(11, 140, 233, 0.4)";
                    card.style.boxShadow = "0 10px 25px rgba(0, 0, 0, 0.4), 0 0 15px rgba(11, 140, 233, 0.15)";
                }
                if (img) {
                    img.style.transform = "scale(1.08)";
                }
            };
            card.onmouseleave = () => {
                if (!selectedArtists.has(card.dataset.key)) {
                    card.style.borderColor = "rgba(255, 255, 255, 0.04)";
                    card.style.boxShadow = "0 4px 12px rgba(0,0,0,0.15)";
                } else {
                    card.style.boxShadow = "0 10px 25px rgba(11, 140, 233, 0.35)";
                }
                if (img) {
                    img.style.transform = "none";
                }
            };

            appendSharedResourceEditor(card, item, async () => { await reopenSelector(modalOverlay, () => openArtistSelectorModal(node, tagsWidget, selectedArtists)); }, infoPanel);
            fragment.appendChild(card);
        });

        listContainer.appendChild(fragment);

        // 首次加载复原大图滚动高度
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

    // 关闭弹窗
    function closeModal() {
        ++filterGeneration;
        clearTimeout(searchTimer);
        stopLibrarySync();
        insertionControls.dispose();
        artistImageObserver.disconnect();
        modalOverlay.remove();
        styleSheet.remove();
    }

    // 首次初始化渲染侧边栏和数据流
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
    modalOverlay.unifiedFocus?.();
}
