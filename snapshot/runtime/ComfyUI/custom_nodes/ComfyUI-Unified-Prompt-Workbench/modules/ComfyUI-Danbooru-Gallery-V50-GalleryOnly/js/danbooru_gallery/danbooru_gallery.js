import {mountGalleryDialog} from './gallery_dialog.js';
import {openReferenceCollections} from '/extensions/ComfyUI-Unified-Prompt-Workbench/shared_collections.js';
import {openPromptUse} from '/extensions/ComfyUI-Unified-Prompt-Workbench/resource_actions.js';
import {queuePromptResource} from '/extensions/ComfyUI-Unified-Prompt-Workbench/prompt_resource.js';
import {commitWidget as sharedCommitWidget} from '/extensions/ComfyUI-Unified-Prompt-Workbench/prompt_target.js';
import { app } from "/scripts/app.js";
import { $el } from "/scripts/ui.js";
import { globalAutocompleteCache } from "../global/autocomplete_cache.js";
import { AutocompleteUI } from "../global/autocomplete_ui.js";
import { toastManagerProxy } from "../global/toast_manager.js";
import { globalMultiLanguageManager } from "../global/multi_language.js";
import { galleryErrorGuidance } from './v53/error_guidance.js';
import {
    GalleryStore,
    RequestLaneCoordinator,
    buildGalleryRequest,
    createMinimalProviderCapabilities,
    galleryNewUiEnabled,
    loadGalleryFeatureFlags,
} from "./v53/index.js";

import { createLogger, loggerClient } from '../global/logger_client.js';

// 创建logger实例
const logger = createLogger('danbooru_gallery');
let galleryInstanceSequence = 0;

app.registerExtension({
    name: "Comfy.DanbooruGallery",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "DanbooruGalleryNode") {
            // 使用全局多语言系统（danbooru命名空间）
            const t = (key) => globalMultiLanguageManager.t(`danbooru.${key}`);

            // 本地存储函数
            const saveToLocalStorage = (key, value) => {
                try {
                    localStorage.setItem(`danbooru_gallery_${key}`, JSON.stringify(value));
                } catch (e) {
                    logger.warn(`[Danbooru Gallery] Failed to save to localStorage: ${key}`, e);
                }
            };

            const loadFromLocalStorage = (key, defaultValue) => {
                try {
                    const item = localStorage.getItem(`danbooru_gallery_${key}`);
                    return item ? JSON.parse(item) : defaultValue;
                } catch (e) {
                    logger.warn(`[Danbooru Gallery] Failed to load from localStorage: ${key}`, e);
                    return defaultValue;
                }
            };

            // 比较两个标签字符串是否相同（忽略标签顺序）
            const compareTagStrings = (str1, str2) => {
                // 处理null、undefined和空字符串的情况
                if (!str1 && !str2) return true;
                if (!str1 || !str2) return false;

                // 分割、排序、比较
                const tags1 = str1.trim().split(/\s+/).filter(t => t).sort();
                const tags2 = str2.trim().split(/\s+/).filter(t => t).sort();

                // 数量不同直接返回false
                if (tags1.length !== tags2.length) return false;

                // 逐个比较标签
                return tags1.every((tag, index) => tag === tags2[index]);
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);
                this.setSize([780, 938]);

                // 保存节点实例引用
                const nodeInstance = this;
                const galleryDialogs = new Set();

                // 存储每张图片的原始标签数据，用于重置和编辑状态判断
                const originalPostCache = {};

                // 创建隐藏的 selection_data widget
                const selectionWidget = this.addWidget("text", "selection_data", JSON.stringify({}), () => { }, {
                    serialize: true // 确保序列化
                });

                // 确保widget不可见
                if (selectionWidget) {
                    selectionWidget.computeSize = () => [0, -4]; // 返回0宽度和负高度来隐藏
                    selectionWidget.draw = () => { }; // 覆盖draw方法，不绘制任何内容
                    selectionWidget.type = "hidden"; // 设置为隐藏类型
                    Object.defineProperty(selectionWidget, 'hidden', { value: true, writable: false }); // 标记为隐藏
                }

                // 创建隐藏的 filter_data widget
                const filterWidget = this.addWidget("text", "filter_data", JSON.stringify({ startTime: null, endTime: null, startPage: null }), () => { }, {
                    serialize: true // 确保序列化
                });

                // 确保widget不可见
                if (filterWidget) {
                    filterWidget.computeSize = () => [0, -4];
                    filterWidget.draw = () => { };
                    filterWidget.type = "hidden";
                    Object.defineProperty(filterWidget, 'hidden', { value: true, writable: false });
                }

                // V53 query/navigation state belongs to this node and travels with the workflow.
                // localStorage remains reserved for shared presentation/output preferences.
                const initialGalleryState = {
                    schemaVersion: 2,
                    activeSource: "gelbooru",
                    sourceDrafts: {},
                    outputSettings: {},
                    legacyMigrationDone: false,
                };
                const galleryStateWidget = this.addWidget(
                    "text",
                    "gallery_state",
                    JSON.stringify(initialGalleryState),
                    () => { },
                    { serialize: true }
                );
                if (galleryStateWidget) {
                    galleryStateWidget.computeSize = () => [0, -4];
                    galleryStateWidget.draw = () => { };
                    galleryStateWidget.type = "hidden";
                    Object.defineProperty(galleryStateWidget, 'hidden', { value: true, writable: false });
                }


                const normalizeSelectionPayload = (payload) => {
                    if (!payload) return { selections: [] };
                    if (Array.isArray(payload)) return { selections: payload.filter(x => x && typeof x === 'object') };
                    if (payload.selections && Array.isArray(payload.selections)) return { selections: payload.selections.filter(x => x && typeof x === 'object') };
                    if (payload.prompt !== undefined || payload.image_url || payload.file_url) return { selections: [payload] };
                    return { selections: [] };
                };

                const commitSelectionData = (payload) => {
                    const normalized = normalizeSelectionPayload(payload);
                    try {
                        if (selectionWidget) {
                            sharedCommitWidget(app, nodeInstance, selectionWidget, JSON.stringify(normalized));
                        }
                        nodeInstance?.setDirtyCanvas?.(true, true);
                        app?.graph?.setDirtyCanvas?.(true, true);
                    } catch (e) {
                        logger.warn("[Danbooru Gallery] 更新 selection_data widget 失败:", e);
                    }
                    try {
                        fetch('/danbooru_gallery/selection_state', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                node_id: String(nodeInstance?.id ?? ''),
                                selection_data: normalized
                            })
                        }).catch(() => {});
                    } catch {}
                    return normalized;
                };

                const v53InstanceId = `danbooru-gallery-${++galleryInstanceSequence}`;
                const container = $el("div.danbooru-gallery", {
                    role: "region",
                    "aria-label": "多站点画廊",
                    "data-testid": "gallery-root",
                });
                // ComfyUI's current $el helper assigns ordinary properties but
                // does not materialize hyphenated data-* keys as DOM attributes.
                // Set stable delivery-test selectors explicitly.
                container.setAttribute("data-testid", "gallery-root");
                container.dataset.danbooruGalleryVersion = "v53-capability-browser";
                container.dataset.galleryInstanceId = v53InstanceId;
                let imageGrid = null;
                let galleryDomWidget = null;
                let embedded = false;

                // 添加错误显示区域
                const errorDisplay = $el("div.danbooru-error-display", {
                    style: {
                        display: "none",
                        color: "#dc3545",
                        marginBottom: "10px",
                        padding: "8px 12px",
                        border: "1px solid #dc3545",
                        borderRadius: "4px",
                        backgroundColor: "rgba(220, 53, 69, 0.1)",
                        fontSize: "14px",
                        fontWeight: "500"
                    }
                });
                container.appendChild(errorDisplay);

                // 添加tag提示显示区域
                const tagHintDisplay = $el("div.danbooru-tag-hint-display", {
                    style: {
                        display: "none",
                        color: "#17a2b8",
                        marginBottom: "5px",
                        padding: "6px 10px",
                        border: "1px solid #17a2b8",
                        borderRadius: "4px",
                        backgroundColor: "rgba(23, 162, 184, 0.1)",
                        fontSize: "13px",
                        fontWeight: "500"
                    }
                });
                container.appendChild(tagHintDisplay);

                // 显示错误信息的函数
                const showError = (message, persistent = false, anchorElement = null) => {
                    showToast(message, 'error');
                };

                // 清除错误信息的函数
                const clearError = () => {
                    errorDisplay.style.display = "none";
                };

                // 显示tag提示信息的函数
                const showTagHint = (message, persistent = false) => {
                    tagHintDisplay.textContent = message;
                    tagHintDisplay.style.display = "block";
                    if (!persistent) {
                        // 3秒后自动隐藏
                        setTimeout(() => {
                            tagHintDisplay.style.display = "none";
                        }, 3000);
                    }
                };

                // 清除tag提示信息的函数
                const clearTagHint = () => {
                    tagHintDisplay.style.display = "none";
                };

                // 检查网络连接状态
                const checkNetworkStatus = async () => {
                    // v21: Civitai 的实际搜索 API 已有错误处理和 fallback。不要让轻量网络预检
                    // 把 C站误判成“无网络”，否则会在真正 /api/v1/images 请求前就被前端拦截。
                    if (currentSource === "civitai") {
                        networkStatus.connected = true;
                        networkStatus.lastChecked = Date.now();
                        return true;
                    }
                    try {
                        const response = await fetch(`/danbooru_gallery/check_network?source=${encodeURIComponent(currentSource)}`);
                        const data = await response.json();
                        const isConnected = data.success && data.connected;
                        const now = Date.now();

                        // 更新网络状态
                        networkStatus.connected = isConnected;
                        networkStatus.lastChecked = now;

                        return isConnected;
                    } catch (e) {
                        logger.warn('网络检测失败:', e);
                        networkStatus.connected = false;
                        networkStatus.lastChecked = Date.now();
                        return false;
                    }
                };


                let danbooruDiagnoseButton = null;
                let civitaiDiagnoseButton = null;
                let danbooruBrowserDiagnoseButton = null;
                let danbooruExportLogsButton = null;
                let lastDanbooruDiagnosticText = loadFromLocalStorage('last_diagnostic_text', '');
                let lastDanbooruDiagnosticKind = loadFromLocalStorage('last_diagnostic_kind', 'snapshot');
                let lastBackendDiagnosticText = loadFromLocalStorage('last_backend_diagnostic_text', '');
                let lastBrowserDiagnosticText = loadFromLocalStorage('last_browser_diagnostic_text', '');
                let lastBackendDiagnosticAt = loadFromLocalStorage('last_backend_diagnostic_at', '');
                let lastBrowserDiagnosticAt = loadFromLocalStorage('last_browser_diagnostic_at', '');
                let lastCivitaiFavoritesDiagnosticText = loadFromLocalStorage('last_civitai_favorites_diagnostic_text', '');
                let lastCivitaiFavoritesDiagnosticAt = loadFromLocalStorage('last_civitai_favorites_diagnostic_at', '');
                let lastGalleryFetchStats = null;
                const imageLoadFailureRecords = [];
                window.__danbooruGalleryImageLoadFailures = imageLoadFailureRecords;

                const collectCurrentPageRenderDiagnostics = () => {
                    const wrappers = Array.from(imageGrid?.querySelectorAll?.('.danbooru-image-wrapper') || []);
                    const cards = wrappers.map((wrapper, idx) => {
                        const img = wrapper.querySelector('img');
                        const cs = window.getComputedStyle(wrapper);
                        const imgCs = img ? window.getComputedStyle(img) : null;
                        const rect = wrapper.getBoundingClientRect();
                        const imgRect = img ? img.getBoundingClientRect() : null;
                        return {
                            index: idx,
                            post_id: wrapper.dataset.postId || '',
                            class_name: wrapper.className || '',
                            candidate_count: Number(wrapper.dataset.imageCandidateCount || 0),
                            candidate_index: wrapper.dataset.imageCandidateIndex || '',
                            image_status: wrapper.dataset.imageLoadStatus || '',
                            image_error: wrapper.dataset.imageLoadError || '',
                            current_image_url: wrapper.dataset.currentImageUrl || '',
                            proxy_src: img?.getAttribute('src') || '',
                            current_src: img?.currentSrc || '',
                            img_complete: !!img?.complete,
                            natural_width: img?.naturalWidth || 0,
                            natural_height: img?.naturalHeight || 0,
                            wrapper_w: Math.round(rect.width || 0),
                            wrapper_h: Math.round(rect.height || 0),
                            img_w: Math.round(imgRect?.width || 0),
                            img_h: Math.round(imgRect?.height || 0),
                            wrapper_display: cs.display,
                            wrapper_visibility: cs.visibility,
                            wrapper_opacity: cs.opacity,
                            img_display: imgCs?.display || '',
                            img_visibility: imgCs?.visibility || '',
                            has_error_badge: !!wrapper.querySelector('.danbooru-image-load-error'),
                        };
                    });
                    const statusCounts = {};
                    for (const c of cards) statusCounts[c.image_status || '(empty)'] = (statusCounts[c.image_status || '(empty)'] || 0) + 1;
                    const notLoaded = cards.filter(c => c.image_status !== 'loaded' || !c.img_complete || !c.natural_width || !c.natural_height);
                    return {
                        at: new Date().toISOString(),
                        wrapper_count: wrappers.length,
                        img_count: wrappers.filter(w => !!w.querySelector('img')).length,
                        status_counts: statusCounts,
                        not_loaded_count: notLoaded.length,
                        not_loaded_sample: notLoaded.slice(0, 30),
                        cards: cards.slice(0, 120),
                    };
                };
                window.__danbooruGalleryCollectRenderDiagnostics = collectCurrentPageRenderDiagnostics;


                // 兼容 v7-v9 只保存一个 last_diagnostic_text 的旧数据。
                if (!lastBackendDiagnosticText && lastDanbooruDiagnosticKind === 'backend' && lastDanbooruDiagnosticText) {
                    lastBackendDiagnosticText = lastDanbooruDiagnosticText;
                }
                if (!lastBrowserDiagnosticText && lastDanbooruDiagnosticKind === 'browser' && lastDanbooruDiagnosticText) {
                    lastBrowserDiagnosticText = lastDanbooruDiagnosticText;
                }

                const setLastDanbooruDiagnostic = (text, kind = 'danbooru') => {
                    const normalizedText = String(text || '');
                    const normalizedKind = kind || 'danbooru';
                    const now = new Date().toISOString();
                    lastDanbooruDiagnosticText = normalizedText;
                    lastDanbooruDiagnosticKind = normalizedKind;
                    saveToLocalStorage('last_diagnostic_text', lastDanbooruDiagnosticText);
                    saveToLocalStorage('last_diagnostic_kind', lastDanbooruDiagnosticKind);

                    if (normalizedKind === 'backend') {
                        lastBackendDiagnosticText = normalizedText;
                        lastBackendDiagnosticAt = now;
                        saveToLocalStorage('last_backend_diagnostic_text', lastBackendDiagnosticText);
                        saveToLocalStorage('last_backend_diagnostic_at', lastBackendDiagnosticAt);
                    } else if (normalizedKind === 'browser') {
                        lastBrowserDiagnosticText = normalizedText;
                        lastBrowserDiagnosticAt = now;
                        saveToLocalStorage('last_browser_diagnostic_text', lastBrowserDiagnosticText);
                        saveToLocalStorage('last_browser_diagnostic_at', lastBrowserDiagnosticAt);
                    } else if (normalizedKind === 'civitai_favorites') {
                        lastCivitaiFavoritesDiagnosticText = normalizedText;
                        lastCivitaiFavoritesDiagnosticAt = now;
                        saveToLocalStorage('last_civitai_favorites_diagnostic_text', lastCivitaiFavoritesDiagnosticText);
                        saveToLocalStorage('last_civitai_favorites_diagnostic_at', lastCivitaiFavoritesDiagnosticAt);
                    }
                };

                const buildDiagnosticSnapshot = () => {
                    const lines = [];
                    lines.push('Danbooru Gallery 日志快照');
                    lines.push(`时间：${new Date().toLocaleString()}`);
                    lines.push(`source=${currentSource || ''}`);
                    lines.push(`search=${searchInput?.value || ''}`);
                    lines.push(`danbooru_auth=${userAuth?.has_auth ? 'configured' : 'empty'}`);
                    lines.push(`gelbooru_auth=${gelbooruAuth?.has_auth ? 'configured' : 'empty'}`);
                    lines.push(`last_diagnostic_kind=${lastDanbooruDiagnosticKind || ''}`);
                    lines.push(`last_backend_diagnostic=${lastBackendDiagnosticText ? 'present' : 'empty'} at=${lastBackendDiagnosticAt || ''}`);
                    lines.push(`last_browser_diagnostic=${lastBrowserDiagnosticText ? 'present' : 'empty'} at=${lastBrowserDiagnosticAt || ''}`);
                    lines.push(`last_civitai_favorites_diagnostic=${lastCivitaiFavoritesDiagnosticText ? 'present' : 'empty'} at=${lastCivitaiFavoritesDiagnosticAt || ''}`);
                    if (lastGalleryFetchStats) lines.push(`last_gallery_fetch=${JSON.stringify(lastGalleryFetchStats)}`);
                    if (imageLoadFailureRecords.length) lines.push(`frontend_image_failures=${imageLoadFailureRecords.length}`);
                    return lines.join('\n');
                };

                const buildDiagnosticsForLogExport = () => {
                    return {
                        exported_at: new Date().toISOString(),
                        page_url: location.href,
                        source: currentSource || '',
                        search: searchInput?.value || '',
                        snapshot: buildDiagnosticSnapshot(),
                        backend: {
                            generated_at: lastBackendDiagnosticAt || '',
                            text: lastBackendDiagnosticText || ''
                        },
                        browser: {
                            generated_at: lastBrowserDiagnosticAt || '',
                            text: lastBrowserDiagnosticText || ''
                        },
                        last: {
                            kind: lastDanbooruDiagnosticKind || '',
                            text: lastDanbooruDiagnosticText || ''
                        },
                        civitai_favorites: {
                            generated_at: lastCivitaiFavoritesDiagnosticAt || '',
                            text: lastCivitaiFavoritesDiagnosticText || ''
                        },
                        frontend_gallery: {
                            last_fetch_stats: lastGalleryFetchStats || {},
                            image_failures: imageLoadFailureRecords.slice(-80),
                            current_render: collectCurrentPageRenderDiagnostics()
                        }
                    };
                };

                const downloadTextFile = (filename, text) => {
                    const blob = new Blob([String(text || '')], { type: 'text/plain;charset=utf-8' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    setTimeout(() => URL.revokeObjectURL(url), 1000);
                };

                const downloadBlobFile = (filename, blob) => {
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename || `danbooru_gallery_logs_${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    setTimeout(() => URL.revokeObjectURL(url), 1000);
                };

                const filenameFromContentDisposition = (disposition) => {
                    const raw = String(disposition || '');
                    const starMatch = raw.match(/filename\*=UTF-8''([^;]+)/i);
                    if (starMatch) {
                        try { return decodeURIComponent(starMatch[1].replace(/"/g, '').trim()); } catch (_) { return starMatch[1].replace(/"/g, '').trim(); }
                    }
                    const match = raw.match(/filename="?([^";]+)"?/i);
                    return match ? match[1].trim() : '';
                };


                const setDiagnosticMode = (enabled) => {
                    if (!imageGrid) return;
                    imageGrid.classList.toggle('danbooru-diagnostic-mode', !!enabled);
                    if (enabled) {
                        // Do not let the masonry grid-auto-rows collapse diagnostics into a 1px item.
                        imageGrid.style.display = 'block';
                        imageGrid.style.gridTemplateColumns = 'none';
                        imageGrid.style.gridAutoRows = 'auto';
                        imageGrid.style.overflowY = 'auto';
                        imageGrid.style.overflowX = 'hidden';
                    } else {
                        imageGrid.style.display = '';
                        imageGrid.style.gridTemplateColumns = '';
                        imageGrid.style.gridAutoRows = '';
                        imageGrid.style.overflowY = '';
                        imageGrid.style.overflowX = '';
                    }
                };

                const normalizeDiagnosticPanelLayout = (panel) => {
                    if (!panel) return;
                    panel.style.display = 'flex';
                    panel.style.flexDirection = 'column';
                    panel.style.width = 'calc(100% - 16px)';
                    panel.style.maxWidth = 'calc(100% - 16px)';
                    panel.style.height = 'calc(100% - 16px)';
                    panel.style.minHeight = '220px';
                    panel.style.maxHeight = 'none';
                    panel.style.margin = '8px';
                    panel.style.overflow = 'hidden';
                    panel.style.boxSizing = 'border-box';
                    const actions = panel.querySelector('.danbooru-diagnostic-actions');
                    if (actions) {
                        actions.style.flex = '0 0 auto';
                        actions.style.position = 'sticky';
                        actions.style.top = '0';
                        actions.style.zIndex = '3';
                        actions.style.background = 'var(--comfy-input-bg)';
                        actions.style.padding = '6px 0 10px 0';
                    }
                    const pre = panel.querySelector('.danbooru-diagnostic-pre');
                    if (pre) {
                        pre.style.flex = '1 1 auto';
                        pre.style.minHeight = '140px';
                        pre.style.maxHeight = 'none';
                        pre.style.overflow = 'auto';
                        pre.style.whiteSpace = 'pre-wrap';
                        pre.style.wordBreak = 'break-word';
                        pre.style.overflowWrap = 'anywhere';
                        pre.style.userSelect = 'text';
                        pre.style.margin = '0';
                        pre.tabIndex = 0;
                    }
                };

                const showDiagnosticPanel = (panel) => {
                    if (!imageGrid) return;
                    setDiagnosticMode(true);
                    normalizeDiagnosticPanelLayout(panel);
                    imageGrid.innerHTML = '';
                    imageGrid.appendChild(panel);
                    imageGrid.scrollTop = 0;
                    const pre = panel.querySelector('.danbooru-diagnostic-pre');
                    if (pre) pre.scrollTop = 0;
                    requestAnimationFrame(() => {
                        normalizeDiagnosticPanelLayout(panel);
                        this.onResize?.(this.size);
                    });
                };

                const setDiagnosticLoading = (message) => {
                    if (!imageGrid) return;
                    setDiagnosticMode(true);
                    imageGrid.innerHTML = `<p class="danbooru-status danbooru-loading">${message}</p>`;
                    imageGrid.scrollTop = 0;
                };

                const exportDiagnosticReport = (text, kind = 'danbooru') => {
                    const safeKind = String(kind || 'danbooru').replace(/[^a-z0-9_-]/gi, '_');
                    const ts = new Date().toISOString().replace(/[:.]/g, '-');
                    downloadTextFile(`danbooru_gallery_${safeKind}_diagnostic_${ts}.txt`, String(text || '').trim() || buildDiagnosticSnapshot());
                    showToast('诊断报告已导出', 'success');
                };

                const exportFullPluginLogs = async () => {
                    const oldText = danbooruExportLogsButton?.textContent;
                    try {
                        if (danbooruExportLogsButton) {
                            danbooruExportLogsButton.disabled = true;
                            danbooruExportLogsButton.textContent = '导出中';
                        }
                        logger.info('用户请求导出 Danbooru Gallery 日志（含当前诊断快照）');
                        await loggerClient?.flush?.();

                        const response = await fetch(`/danbooru_gallery/export_logs?t=${Date.now()}`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ frontend_diagnostics: buildDiagnosticsForLogExport() }),
                            cache: 'no-store'
                        });
                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status}: ${await response.text()}`);
                        }
                        const blob = await response.blob();
                        const filename = filenameFromContentDisposition(response.headers.get('Content-Disposition')) || `danbooru_gallery_logs_${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
                        downloadBlobFile(filename, blob);
                        showToast('日志已导出，包含当前前端/后端诊断', 'success');
                    } catch (e) {
                        logger.error('导出日志失败:', e);
                        try {
                            // 兼容兜底：如果 POST 被旧后端拒绝，至少仍导出后端日志。
                            const url = `/danbooru_gallery/export_logs?t=${Date.now()}&fallback_get=1`;
                            const a = document.createElement('a');
                            a.href = url;
                            a.download = '';
                            document.body.appendChild(a);
                            a.click();
                            a.remove();
                            showToast('完整日志 POST 导出失败，已改用旧式日志导出', 'warning');
                        } catch (_) {
                            const fallback = [buildDiagnosticSnapshot(), lastBackendDiagnosticText, lastBrowserDiagnosticText, lastDanbooruDiagnosticText].filter(Boolean).join('\n\n');
                            exportDiagnosticReport(fallback, lastDanbooruDiagnosticKind || 'snapshot');
                        }
                    } finally {
                        if (danbooruExportLogsButton) {
                            danbooruExportLogsButton.disabled = false;
                            danbooruExportLogsButton.textContent = oldText || '导出日志';
                        }
                    }
                };

                const makeDiagnosticActions = (text, kind, copyLabel = '复制诊断报告') => {
                    const actions = $el('div.danbooru-diagnostic-actions');
                    const copyBtn = $el('button.danbooru-diagnostic-action', {
                        textContent: copyLabel,
                        onclick: async () => {
                            try {
                                await navigator.clipboard.writeText(text);
                                showToast('诊断报告已复制', 'success');
                            } catch (e) {
                                console.warn('复制失败:', e);
                                showToast('复制失败，请手动选择文本', 'error');
                            }
                        }
                    });
                    const exportReportBtn = $el('button.danbooru-diagnostic-action', {
                        textContent: '导出报告',
                        title: '导出当前诊断报告为 txt 文件',
                        onclick: () => exportDiagnosticReport(text, kind)
                    });
                    const exportLogBtn = $el('button.danbooru-diagnostic-action', {
                        textContent: '导出完整日志',
                        title: '导出插件后端日志，并附带当前 D站后端诊断 / D浏览器诊断；敏感字段会脱敏',
                        onclick: () => exportFullPluginLogs()
                    });
                    actions.append(copyBtn, exportReportBtn, exportLogBtn);
                    return actions;
                };

                const formatDanbooruDiagnosticReport = (diag) => {
                    const lines = [];
                    lines.push(`D站诊断结果：${diag.status || 'unknown'}`);
                    lines.push(`结论：${diag.summary || ''}`);
                    lines.push(`时间：${diag.generated_at || ''}`);
                    lines.push(`诊断版本：${diag.plugin_diagnostic_version || ''}`);
                    lines.push('');
                    const settings = diag.settings || {};
                    lines.push('设置：');
                    lines.push(`- auth: ${settings.has_auth ? '已配置' : '未配置'} login=${settings.login_masked || ''} api_key_len=${settings.api_key_length || 0}`);
                    lines.push(`- proxy_enabled: ${settings.proxy_enabled}`);
                    lines.push(`- resolved_proxy: ${settings.resolved_proxy || '<none>'}`);
                    lines.push(`- tested_tags: ${settings.tested_tags || ''}`);
                    if (settings.tested_tags_raw && settings.tested_tags_raw !== settings.tested_tags) lines.push(`- tested_tags_raw: ${settings.tested_tags_raw}`);
                    lines.push(`- curl_cffi_available: ${settings.curl_cffi_available ? 'true' : 'false'}`);
                    if (settings.danbooru_cookie_enabled !== undefined) {
                        lines.push(`- danbooru_cookie: enabled=${settings.danbooru_cookie_enabled ? 'true' : 'false'} present=${settings.danbooru_cookie_present ? 'true' : 'false'} cf_clearance=${settings.danbooru_cookie_has_cf_clearance ? 'true' : 'false'}`);
                    }
                    if (settings.danbooru_browser_headers_enabled !== undefined) {
                        lines.push(`- browser_headers: enabled=${settings.danbooru_browser_headers_enabled ? 'true' : 'false'} present=${settings.danbooru_browser_headers_present ? 'true' : 'false'} cookie=${settings.danbooru_browser_headers_has_cookie ? 'true' : 'false'} cf_clearance=${settings.danbooru_browser_headers_has_cf_clearance ? 'true' : 'false'} ua=${settings.danbooru_browser_headers_has_user_agent ? 'true' : 'false'}`);
                    }
                    if (settings.curl_cffi_import_error) lines.push(`- curl_cffi_import_error: ${settings.curl_cffi_import_error}`);
                    lines.push('');
                    lines.push('测试明细：');
                    for (const t of (diag.tests || [])) {
                        lines.push(`- ${t.label || ''}`);
                        lines.push(`  mode=${t.mode || ''} ua=${t.ua_label || ''} auth=${t.auth_method || ''} status=${t.status_code ?? ''} category=${t.category || ''} ok=${t.ok ? 'true' : 'false'} elapsed=${t.elapsed_ms ?? ''}ms`);
                        if (t.cookie_mode) lines.push(`  cookie=${t.cookie_mode} cf_clearance=${t.cookie_has_cf_clearance ? 'true' : 'false'}`);
                        if (t.browser_headers_mode) lines.push(`  browser_headers=${t.browser_headers_mode} cookie=${t.browser_headers_has_cookie ? 'true' : 'false'} cf_clearance=${t.browser_headers_has_cf_clearance ? 'true' : 'false'} ua=${t.browser_headers_has_user_agent ? 'true' : 'false'}`);
                        if (t.proxy) lines.push(`  proxy=${t.proxy}`);
                        if (t.impersonate) lines.push(`  impersonate=${t.impersonate}`);
                        if (t.resolved_addresses && t.resolved_addresses.length) lines.push(`  resolved=${t.resolved_addresses.join(', ')}`);
                        if (t.tls_version || t.tls_cipher) lines.push(`  tls=${t.tls_version || ''} ${t.tls_cipher || ''}`.trim());
                        if (t.headers) {
                            const h = t.headers;
                            const headerBits = [];
                            if (h.server) headerBits.push(`server=${h.server}`);
                            if (h.content_type) headerBits.push(`content-type=${h.content_type}`);
                            if (h.cf_mitigated) headerBits.push(`cf-mitigated=${h.cf_mitigated}`);
                            if (h.cf_ray) headerBits.push(`cf-ray=${h.cf_ray}`);
                            if (h.retry_after) headerBits.push(`retry-after=${h.retry_after}`);
                            if (h.www_authenticate) headerBits.push(`www-authenticate=${h.www_authenticate}`);
                            if (headerBits.length) lines.push(`  headers: ${headerBits.join('; ')}`);
                        }
                        if (t.error) lines.push(`  error=${t.error}`);
                        if (t.body_snippet) lines.push(`  body=${t.body_snippet}`);
                    }
                    if (diag.notes && diag.notes.length) {
                        lines.push('');
                        lines.push('备注：');
                        for (const n of diag.notes) lines.push(`- ${n}`);
                    }
                    return lines.join('\n');
                };

                const runDanbooruDiagnostic = async () => {
                    const oldHTML = danbooruDiagnoseButton?.innerHTML;
                    try {
                        if (danbooruDiagnoseButton) {
                            danbooruDiagnoseButton.disabled = true;
                            danbooruDiagnoseButton.textContent = '诊断中';
                        }
                        const rawTags = searchInput?.value?.trim() || 'rating:general';
                        const tags = (typeof convertTagsToApiFormat === 'function') ? convertTagsToApiFormat(rawTags) : rawTags;
                        setDiagnosticLoading('正在诊断 Danbooru，请稍等...');
                        const response = await fetch(`/danbooru_gallery/diagnose_danbooru?tags=${encodeURIComponent(tags)}&include_direct=1`);
                        const diag = await response.json();
                        const text = formatDanbooruDiagnosticReport(diag);
                        setLastDanbooruDiagnostic(text, 'backend');
                        const panel = $el('div.danbooru-diagnostic-panel');
                        const title = $el('div.danbooru-diagnostic-title', { textContent: `D站诊断：${diag.status || 'unknown'}` });
                        const summary = $el('div.danbooru-diagnostic-summary', { textContent: diag.summary || '' });
                        const actions = makeDiagnosticActions(text, 'backend', '复制诊断报告');
                        const pre = $el('pre.danbooru-diagnostic-pre', { textContent: text });
                        panel.appendChild(title);
                        panel.appendChild(summary);
                        panel.appendChild(actions);
                        panel.appendChild(pre);
                        showDiagnosticPanel(panel);
                    } catch (e) {
                        logger.error('D站诊断失败:', e);
                        setDiagnosticLoading(`D站诊断接口失败：${String(e?.message || e)}`);
                        imageGrid.querySelector('.danbooru-status')?.classList.add('error');
                    } finally {
                        if (danbooruDiagnoseButton) {
                            danbooruDiagnoseButton.disabled = false;
                            danbooruDiagnoseButton.innerHTML = oldHTML || 'D诊断';
                        }
                    }
                };

                const formatCivitaiDiagnosticReport = (diag) => {
                    const lines = [];
                    lines.push(`C站诊断结果：${diag.summary || 'unknown'}`);
                    lines.push(`时间：${diag.generated_at || ''}`);
                    lines.push(`primary=${diag.primary_base || ''}`);
                    lines.push(`fallback=${diag.fallback_base || ''}`);
                    lines.push(`input=${diag.input_tags || ''}`);
                    lines.push(`actual_node_search_count=${diag.actual_node_search_count ?? ''}`);
                    lines.push('');
                    lines.push('解析计划：');
                    lines.push(JSON.stringify(diag.parsed_plan || {}, null, 2));
                    if (diag.last_search_debug) {
                        lines.push('');
                        lines.push('实际检索 debug：');
                        lines.push(JSON.stringify(diag.last_search_debug, null, 2));
                    }
                    lines.push('');
                    lines.push('测试明细：');
                    for (const t of (diag.tests || [])) {
                        lines.push(`- ${t.name || ''}`);
                        lines.push(`  base=${t.base || ''} path=${t.path || ''} status=${t.status ?? ''} category=${t.category || ''} ok=${t.ok ? 'true' : 'false'} elapsed=${t.elapsed_ms ?? ''}ms items=${t.items ?? ''}`);
                        if (t.params) lines.push(`  params=${JSON.stringify(t.params)}`);
                        if (t.has_next_cursor !== undefined || t.has_next_page !== undefined) lines.push(`  nextCursor=${t.has_next_cursor ? 'true' : 'false'} nextPage=${t.has_next_page ? 'true' : 'false'}`);
                        if (t.first_id || t.first_name || t.first_url_host) lines.push(`  first=${t.first_id || ''} ${t.first_name || ''} host=${t.first_url_host || ''} nsfw=${t.first_nsfw ?? ''} level=${t.first_nsfwLevel ?? ''}`);
                        if (t.error) lines.push(`  error=${t.error}`);
                        if (t.body_head) lines.push(`  body=${t.body_head}`);
                    }
                    if (diag.notes && diag.notes.length) {
                        lines.push('');
                        lines.push('备注：');
                        for (const n of diag.notes) lines.push(`- ${n}`);
                    }
                    return lines.join('\n');
                };

                const runCivitaiDiagnostic = async () => {
                    const oldHTML = civitaiDiagnoseButton?.innerHTML;
                    try {
                        if (civitaiDiagnoseButton) {
                            civitaiDiagnoseButton.disabled = true;
                            civitaiDiagnoseButton.textContent = 'C诊断中';
                        }
                        const rawTags = searchInput?.value?.trim() || '';
                        const tags = (typeof convertTagsToApiFormat === 'function') ? convertTagsToApiFormat(rawTags) : rawTags;
                        const selectedRatings = typeof getSelectedRatings === 'function' ? getSelectedRatings() : [];
                        const sendAll = !selectedRatings.length || selectedRatings.length === RATING_VALUES.length;
                        const ratingForServer = sendAll ? '' : selectedRatings.join(',');
                        setDiagnosticLoading('正在诊断 Civitai.red / Civitai.com API，请稍等...');
                        const response = await fetch(`/danbooru_gallery/diagnose_civitai?tags=${encodeURIComponent(tags)}&rating=${encodeURIComponent(ratingForServer)}`);
                        const diag = await response.json();
                        const text = formatCivitaiDiagnosticReport(diag);
                        setLastDanbooruDiagnostic(text, 'civitai');
                        const panel = $el('div.danbooru-diagnostic-panel');
                        const title = $el('div.danbooru-diagnostic-title', { textContent: `C站诊断：${diag.summary || 'unknown'}` });
                        const summary = $el('div.danbooru-diagnostic-summary', { textContent: `实际检索返回 ${diag.actual_node_search_count ?? 0} 条；详见 debug。` });
                        const actions = makeDiagnosticActions(text, 'civitai', '复制 C站诊断报告');
                        const pre = $el('pre.danbooru-diagnostic-pre', { textContent: text });
                        panel.appendChild(title);
                        panel.appendChild(summary);
                        panel.appendChild(actions);
                        panel.appendChild(pre);
                        showDiagnosticPanel(panel);
                    } catch (e) {
                        logger.error('C站诊断失败:', e);
                        setDiagnosticLoading(`C站诊断接口失败：${String(e?.message || e)}`);
                        imageGrid.querySelector('.danbooru-status')?.classList.add('error');
                    } finally {
                        if (civitaiDiagnoseButton) {
                            civitaiDiagnoseButton.disabled = false;
                            civitaiDiagnoseButton.innerHTML = oldHTML || 'C诊断';
                        }
                    }
                };


                const formatCivitaiFavoritesDiagnosticReport = (diag) => {
                    const lines = [];
                    lines.push(`C站收藏诊断结果：${diag.summary || 'unknown'}`);
                    lines.push(`时间：${diag.generated_at || ''}`);
                    lines.push(`search=${diag.input?.search || ''}`);
                    lines.push(`limit=${diag.input?.limit ?? ''} probe=${diag.input?.probe ? 'true' : 'false'}`);
                    lines.push('');
                    lines.push('收藏认证/设置：');
                    const s = diag.settings || {};
                    lines.push(`- remote_enabled=${s.remote_enabled ? 'true' : 'false'}`);
                    lines.push(`- collection_headers_present=${s.collection_headers_present ? 'true' : 'false'} parsed=${s.collection_headers_parsed_count ?? 0} cookie=${s.collection_has_cookie ? 'true' : 'false'} ua=${s.collection_has_user_agent ? 'true' : 'false'}`);
                    lines.push(`- search_headers_present=${s.search_headers_present ? 'true' : 'false'} parsed=${s.search_headers_parsed_count ?? 0} authorization=${s.search_has_authorization ? 'true' : 'false'}`);
                    lines.push(`- default_collection_id=${s.default_collection_id || ''}`);
                    lines.push(`- local_favorites_count=${s.local_favorites_count ?? 0}`);
                    lines.push('');
                    lines.push('实际收藏请求：');
                    const f = diag.favorites_fetch || {};
                    lines.push(`- ok=${f.ok ? 'true' : 'false'} source=${f.source || ''} count=${f.count ?? 0} elapsed=${f.elapsed_ms ?? ''}ms`);
                    if (f.error) lines.push(`- error=${f.error}`);
                    if (diag.last_search_debug) { lines.push('- last_search_debug:'); lines.push(JSON.stringify(diag.last_search_debug, null, 2)); }
                    lines.push('');
                    lines.push('图片字段汇总：');
                    const a = diag.analysis || {};
                    lines.push(`- posts=${a.total_posts ?? 0} has_any_candidate=${a.has_any_candidate ?? 0} missing_candidates=${a.missing_candidates ?? 0}`);
                    lines.push(`- ext_ok=${a.ext_ok ?? 0} ext_missing=${a.ext_missing ?? 0} ext_suspicious=${a.ext_suspicious ?? 0}`);
                    lines.push(`- host_counts=${JSON.stringify(a.host_counts || {})}`);
                    lines.push('');
                    lines.push('图片代理探测（最多抽样）：');
                    for (const p of (diag.samples || [])) {
                        lines.push(`\n[post ${p.id}] candidates=${p.candidate_count} file_ext=${p.file_ext || ''} url=${p.civitai_url || ''}`);
                        if (p.reason) lines.push(`  reason=${p.reason}`);
                        for (const probe of (p.probes || [])) {
                            lines.push(`  - ${probe.label || ''} ok=${probe.ok ? 'true' : 'false'} category=${probe.category || ''} status=${probe.status ?? ''} type=${probe.content_type || ''} bytes=${probe.bytes ?? ''} elapsed=${probe.elapsed_ms ?? ''}ms`);
                            lines.push(`    host=${probe.host || ''}`);
                            lines.push(`    url=${probe.url || ''}`);
                            if (probe.error) lines.push(`    error=${probe.error}`);
                        }
                    }
                    lines.push('');
                    lines.push('前端本次渲染统计：'); lines.push(JSON.stringify(lastGalleryFetchStats || {}, null, 2));
                    lines.push('');
                    lines.push('前端图片失败记录（最近 50）：'); lines.push(JSON.stringify(imageLoadFailureRecords.slice(-50), null, 2));
                    lines.push(''); lines.push('前端当前页面渲染/DOM诊断：'); lines.push(JSON.stringify(collectCurrentPageRenderDiagnostics(), null, 2));
                    if (diag.recommendations && diag.recommendations.length) { lines.push(''); lines.push('建议：'); for (const r of diag.recommendations) lines.push(`- ${r}`); }
                    lines.push(''); lines.push('原始诊断 JSON：'); lines.push(JSON.stringify(diag, null, 2));
                    return lines.join('\n');
                };

                const runCivitaiFavoritesDiagnostic = async (exportOnly = false) => {
                    try {
                        setDiagnosticLoading('正在诊断 Civitai 收藏与缩略图代理，请稍等...');
                        const rawSearch = searchInput?.value?.trim() || 'civitai:favorites';
                        const search = rawSearch.includes('civitai:favorites') ? rawSearch : 'civitai:favorites';
                        const url = `/danbooru_gallery/diagnose_civitai_favorites?search=${encodeURIComponent(search)}&limit=40&probe=1&probe_posts=40&probe_urls_per_post=3&t=${Date.now()}`;
                        const response = await fetch(url, { cache: 'no-store', headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' } });
                        const diag = await response.json();
                        const text = formatCivitaiFavoritesDiagnosticReport(diag);
                        setLastDanbooruDiagnostic(text, 'civitai_favorites');
                        if (exportOnly) { exportDiagnosticReport(text, 'civitai_favorites'); return; }
                        const panel = $el('div.danbooru-diagnostic-panel');
                        const title = $el('div.danbooru-diagnostic-title', { textContent: `C收藏诊断：${diag.summary || 'unknown'}` });
                        const summary = $el('div.danbooru-diagnostic-summary', { textContent: `收藏返回 ${diag.favorites_fetch?.count ?? 0} 条；无候选图 ${diag.analysis?.missing_candidates ?? 0} 条；详情见下方。` });
                        const actions = makeDiagnosticActions(text, 'civitai_favorites', '复制 C收藏诊断');
                        actions.appendChild($el('button.danbooru-diagnostic-action', { textContent: '重新诊断并导出', onclick: () => runCivitaiFavoritesDiagnostic(true) }));
                        const pre = $el('pre.danbooru-diagnostic-pre', { textContent: text });
                        panel.appendChild(title); panel.appendChild(summary); panel.appendChild(actions); panel.appendChild(pre);
                        showDiagnosticPanel(panel);
                    } catch (e) {
                        logger.error('C收藏诊断失败:', e);
                        setDiagnosticLoading(`C收藏诊断接口失败：${String(e?.message || e)}`);
                        imageGrid.querySelector('.danbooru-status')?.classList.add('error');
                    }
                };

                const maskDanbooruUrl = (url) => {
                    return String(url || '')
                        .replace(/([?&]login=)[^&]+/g, '$1<redacted>')
                        .replace(/([?&]api_key=)[^&]+/g, '$1<redacted>');
                };

                const sanitizeDiagBody = (text) => {
                    return String(text || '')
                        .replace(/api_key=[^&\s"']+/gi, 'api_key=<redacted>')
                        .replace(/login=[^&\s"']+/gi, 'login=<redacted>')
                        .slice(0, 800);
                };

                const browserDanbooruFetchTest = async (label, path, params, expect = 'json') => {
                    const url = new URL(`https://danbooru.donmai.us${path}`);
                    Object.entries(params || {}).forEach(([k, v]) => {
                        if (v !== undefined && v !== null && String(v) !== '') url.searchParams.set(k, String(v));
                    });
                    const result = {
                        label,
                        mode: 'browser_fetch',
                        url: maskDanbooruUrl(url.toString()),
                        expect,
                        ok: false,
                        category: 'unknown',
                        status: '',
                        elapsed_ms: '',
                        headers: {},
                        body: '',
                        error: ''
                    };
                    const controller = new AbortController();
                    const timeout = setTimeout(() => controller.abort(), 15000);
                    const start = performance.now();
                    try {
                        const response = await fetch(url.toString(), {
                            method: 'GET',
                            mode: 'cors',
                            credentials: 'omit',
                            cache: 'no-store',
                            signal: controller.signal,
                            headers: { 'Accept': expect === 'json' ? 'application/json,text/html;q=0.8,*/*;q=0.5' : '*/*' }
                        });
                        result.elapsed_ms = Math.round(performance.now() - start);
                        result.status = response.status;
                        result.headers = {
                            content_type: response.headers.get('content-type') || '',
                            cf_mitigated: response.headers.get('cf-mitigated') || '',
                            cf_ray: response.headers.get('cf-ray') || '',
                            server: response.headers.get('server') || ''
                        };
                        const text = await response.text();
                        if (result.headers.cf_mitigated === 'challenge' || /challenges\.cloudflare\.com|Just a moment/i.test(text)) {
                            result.category = 'cloudflare_challenge';
                            result.body = sanitizeDiagBody(text);
                        } else if (response.status === 401) {
                            result.category = 'auth_api_key';
                            result.body = sanitizeDiagBody(text);
                        } else if (response.status === 403) {
                            result.category = 'forbidden_permission_or_ip';
                            result.body = sanitizeDiagBody(text);
                        } else if (response.status === 429) {
                            result.category = 'rate_limited';
                            result.body = sanitizeDiagBody(text);
                        } else if (expect === 'json') {
                            try {
                                JSON.parse(text);
                                result.ok = response.ok;
                                result.category = response.ok ? 'ok_json' : 'http_error_json';
                            } catch (e) {
                                result.category = 'unexpected_non_json';
                                result.body = sanitizeDiagBody(text);
                            }
                        } else {
                            result.ok = response.ok;
                            result.category = response.ok ? 'ok_http' : 'http_error';
                            if (!response.ok) result.body = sanitizeDiagBody(text);
                        }
                    } catch (e) {
                        result.elapsed_ms = Math.round(performance.now() - start);
                        result.category = e?.name === 'AbortError' ? 'browser_timeout' : 'browser_cors_or_network_error';
                        result.error = String(e?.message || e || 'unknown');
                    } finally {
                        clearTimeout(timeout);
                    }
                    return result;
                };

                const formatBrowserDanbooruDiagnosticReport = (diag) => {
                    const lines = [];
                    lines.push(`D站浏览器诊断结果：${diag.status}`);
                    lines.push(`结论：${diag.summary}`);
                    lines.push(`时间：${diag.generated_at}`);
                    lines.push('');
                    lines.push('设置：');
                    lines.push(`- auth: ${diag.has_auth ? '已配置' : '未配置'} login=${diag.login_masked || ''} api_key_len=${diag.api_key_length || 0}`);
                    lines.push(`- tested_tags: ${diag.tested_tags || ''}`);
                    lines.push('');
                    lines.push('测试明细：');
                    for (const t of diag.tests || []) {
                        lines.push(`- ${t.label}`);
                        lines.push(`  mode=${t.mode} status=${t.status ?? ''} category=${t.category} ok=${t.ok ? 'true' : 'false'} elapsed=${t.elapsed_ms ?? ''}ms`);
                        lines.push(`  url=${t.url}`);
                        if (t.headers) {
                            const h = t.headers;
                            const headerBits = [];
                            if (h.server) headerBits.push(`server=${h.server}`);
                            if (h.content_type) headerBits.push(`content-type=${h.content_type}`);
                            if (h.cf_mitigated) headerBits.push(`cf-mitigated=${h.cf_mitigated}`);
                            if (h.cf_ray) headerBits.push(`cf-ray=${h.cf_ray}`);
                            if (headerBits.length) lines.push(`  headers: ${headerBits.join('; ')}`);
                        }
                        if (t.error) lines.push(`  error=${t.error}`);
                        if (t.body) lines.push(`  body=${t.body}`);
                    }
                    lines.push('');
                    lines.push('备注：');
                    lines.push('- 这是浏览器 fetch 诊断，不经过 ComfyUI Python 后端，也不使用插件代理设置。');
                    lines.push('- 如果这里成功而后端诊断失败，可以考虑做“浏览器直连搜索模式”。');
                    lines.push('- 如果这里显示 browser_cors_or_network_error，通常是 ComfyUI 页面跨域 fetch 被 CORS 拦截；这项不能单独判断 D站 API 是否可用。');
                    return lines.join('\n');
                };

                const runDanbooruBrowserDiagnostic = async () => {
                    const oldHTML = danbooruBrowserDiagnoseButton?.innerHTML;
                    try {
                        if (danbooruBrowserDiagnoseButton) {
                            danbooruBrowserDiagnoseButton.disabled = true;
                            danbooruBrowserDiagnoseButton.textContent = '浏览器诊断中';
                        }
                        await loadUserAuth();
                        const rawTags = searchInput?.value?.trim() || 'rating:general';
                        const tags = (typeof convertTagsToApiFormat === 'function') ? convertTagsToApiFormat(rawTags) : rawTags;
                        const authParams = (userAuth?.username && userAuth?.api_key) ? { login: userAuth.username, api_key: userAuth.api_key } : {};
                        const tests = [];
                        setDiagnosticLoading('正在做浏览器侧 Danbooru 诊断...');

                        if (authParams.login && authParams.api_key) {
                            tests.push(await browserDanbooruFetchTest('browser_profile_auth', '/profile.json', authParams, 'json'));
                        } else {
                            tests.push({ label: 'browser_profile_auth', mode: 'browser_fetch', ok: false, category: 'skipped_no_auth', status: '', elapsed_ms: '', url: 'https://danbooru.donmai.us/profile.json', headers: {}, error: '未配置 Danbooru login/api_key' });
                        }
                        tests.push(await browserDanbooruFetchTest('browser_posts_search', '/posts.json', { limit: 1, page: 1, tags, ...authParams }, 'json'));
                        tests.push(await browserDanbooruFetchTest('browser_posts_id_control', '/posts.json', { limit: 1, page: 1, tags: 'id:1', ...authParams }, 'json'));

                        let status = 'unknown';
                        let summary = '查看各项 category。';
                        const postsSearch = tests.find(t => t.label === 'browser_posts_search');
                        const postsId = tests.find(t => t.label === 'browser_posts_id_control');
                        if (postsSearch?.ok) {
                            status = 'browser_posts_ok';
                            summary = '浏览器侧 posts.json 可用；Python 后端失败时，可改成浏览器直连搜索模式。';
                        } else if (postsId?.ok) {
                            status = 'browser_id_ok_search_failed';
                            summary = '浏览器侧 id:1 控制查询可用，但当前搜索词失败；优先检查 tag 格式、tag 数量、评分筛选或 key 权限。';
                        } else if (tests.some(t => t.category === 'cloudflare_challenge')) {
                            status = 'browser_cloudflare_challenge';
                            summary = '浏览器 fetch 也被 Cloudflare challenge；这不是后端 requests 单独问题。';
                        } else if (tests.some(t => t.category === 'browser_cors_or_network_error')) {
                            status = 'browser_cors_or_network_error';
                            summary = '浏览器侧跨域读取 Danbooru API 被阻止；这通常是正常 CORS 限制，不代表浏览器地址栏打不开。D站可用性请以后端 D诊断/日志为准。';
                        } else if (tests.some(t => t.category === 'auth_api_key')) {
                            status = 'browser_auth_api_key_issue';
                            summary = '浏览器侧返回认证错误；检查 login/API key 以及 key 权限。';
                        }

                        const diag = {
                            status,
                            summary,
                            generated_at: new Date().toLocaleString(),
                            has_auth: !!(userAuth?.username && userAuth?.api_key),
                            login_masked: userAuth?.username ? `${String(userAuth.username).slice(0, 3)}…${String(userAuth.username).slice(-3)}` : '',
                            api_key_length: String(userAuth?.api_key || '').length,
                            tested_tags: tags,
                            tests
                        };
                        const text = formatBrowserDanbooruDiagnosticReport(diag);
                        setLastDanbooruDiagnostic(text, 'browser');
                        const panel = $el('div.danbooru-diagnostic-panel');
                        const title = $el('div.danbooru-diagnostic-title', { textContent: `D站浏览器诊断：${status}` });
                        const summaryNode = $el('div.danbooru-diagnostic-summary', { textContent: summary });
                        const actions = makeDiagnosticActions(text, 'browser', '复制浏览器诊断报告');
                        const pre = $el('pre.danbooru-diagnostic-pre', { textContent: text });
                        panel.appendChild(title);
                        panel.appendChild(summaryNode);
                        panel.appendChild(actions);
                        panel.appendChild(pre);
                        showDiagnosticPanel(panel);
                    } catch (e) {
                        logger.error('D站浏览器诊断失败:', e);
                        setDiagnosticLoading(`D站浏览器诊断失败：${String(e?.message || e)}`);
                        imageGrid.querySelector('.danbooru-status')?.classList.add('error');
                    } finally {
                        if (danbooruBrowserDiagnoseButton) {
                            danbooruBrowserDiagnoseButton.disabled = false;
                            danbooruBrowserDiagnoseButton.innerHTML = oldHTML || 'D浏览器诊断';
                        }
                    }
                };

                const getGalleryWidgetHeight = () => Math.max(180, Math.floor((nodeInstance.size?.[1] || 938) - 110));
                // The frontend attaches node-selection listeners to this element.
                // Embedded controls must not move the graph node to the front.
                for (const type of ['click', 'focus']) container.addEventListener(type, event => {
                    if (container.closest('#unified-workbench')) event.stopImmediatePropagation();
                });
                galleryDomWidget = this.addDOMWidget("danbooru_gallery_widget", "div", container, {
                    // Keep min height low. Returning node.size here can cause a feedback loop
                    // where the DOM widget asks the node to become taller every redraw.
                    getMinHeight: () => 160,
                    getHeight: () => getGalleryWidgetHeight(),
                    afterResize: () => {
                        requestAnimationFrame(() => nodeInstance.onResize?.(nodeInstance.size || [780, 938]));
                    },
                    onDraw: () => {
                        requestAnimationFrame(() => nodeInstance.onResize?.(nodeInstance.size || [780, 938]));
                    }
                });

                // Older ComfyUI builds can keep the DOM widget wrapper at its original
                // narrow width after the node is resized. Force the widget's virtual
                // size to follow node.size, then the actual DOM size is synchronized in
                // onResize below.
                if (galleryDomWidget) {
                    galleryDomWidget.computeSize = (width) => {
                        const nodeWidth = Math.max(240, (nodeInstance.size?.[0] || width || 780) - 24);
                        const nodeHeight = getGalleryWidgetHeight();
                        return [nodeWidth, nodeHeight];
                    };
                }


                // 确保在 widget 渲染后调整大小
                setTimeout(() => {
                    this.onResize(this.size);
                }, 10);

                let globalTooltip, globalTooltipTimeout;
                let currentTooltipId = 0; // 用于追踪当前活动的tooltip请求
                let posts = [], currentPage = 1, isLoading = false, endOfResults = false;
                let renderedPostKeys = new Set();
                let manualRefreshNonce = 0;
                let filterState = { startTime: null, endTime: null, startPage: null };

                const getPostCacheKey = (post) => {
                    if (!post || typeof post !== "object") return "invalid";
                    const id = post.id ?? post.post_id ?? post.image_id ?? post.civitai_id ?? "";
                    const url = post.file_url || post.large_file_url || post.preview_file_url || post.preview_url || "";
                    return `${currentSource}:${String(id)}:${String(url)}`;
                };

                const normalizeSource = (value) => (["danbooru", "gelbooru", "civitai", "yandere"].includes(String(value || "").toLowerCase()) ? String(value).toLowerCase() : "danbooru");
                let galleryStore = new GalleryStore({ persisted: initialGalleryState });
                const galleryRequests = new RequestLaneCoordinator();
                const providerCapabilities = new Map();
                const lastBrowseModeBySource = new Map();
                let v53BrowseIntentSequence = 0;
                let v53FacetIntentSequence = 0;
                let v53CapabilityIntentSequence = 0;
                let currentSource = "gelbooru";
                let v53UiReady = false;
                let v53FeatureFlags = null;
                let userAuth = { username: "", api_key: "", has_auth: false }; // Danbooru 用户认证信息
                let danbooruCookie = { enabled: false, cookie: "", has_cookie: false, has_cf_clearance: false, has_login_session: false }; // Danbooru 浏览器 Cookie fallback
                let danbooruBrowserHeaders = { enabled: false, headers: "", has_headers: false, parsed_count: 0, has_cookie: false, has_cf_clearance: false, has_user_agent: false }; // Danbooru 浏览器请求头/cURL fallback
                let gelbooruAuth = { user_id: "", api_key: "", has_auth: false }; // Gelbooru API 认证信息
                let civitaiAuth = { api_key: "", has_auth: false }; // Civitai API Key（可选）
                let civitaiRemoteFavorites = { enabled: false, headers: "", collection_headers: "", search_headers: "", has_headers: false, has_collection_headers: false, has_search_headers: false, has_cookie: false, has_civitai_token: false, has_authorization: false, default_collection_id: "", collections: [], selected_collection: null };
                let userFavorites = []; // Danbooru 收藏列表，确保字符串
                let networkStatus = { connected: true, lastChecked: 0 }; // 网络状态跟踪
                let previousSearchValue = ""; // 跟踪搜索框之前的值，用于检测清空操作
                let temporaryTagEdits = {}; // Keyed by post.id

                const hasDanbooruFavoriteAuth = () => !!(
                    userAuth.has_auth ||
                    (danbooruCookie.enabled && (danbooruCookie.has_login_session || danbooruCookie.has_cookie)) ||
                    (danbooruBrowserHeaders.enabled && danbooruBrowserHeaders.has_cookie)
                );

                // 用户认证管理功能
                const loadUserAuth = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/user_auth');
                        const data = await response.json();
                        if (data && data.success !== false) {
                            userAuth = {
                                username: data.username || "",
                                api_key: data.api_key || "",
                                has_auth: !!(data.username && data.api_key)
                            };
                        } else {
                            logger.warn("加载 Danbooru 认证信息失败，保留当前内存值:", data?.error || data);
                        }
                        return userAuth;
                    } catch (e) {
                        logger.warn("加载 Danbooru 认证信息失败，保留当前内存值:", e);
                        return userAuth;
                    }
                };

                const saveUserAuth = async (username, api_key, preserveIfEmpty = true) => {
                    try {
                        const response = await fetch('/danbooru_gallery/user_auth', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ username: username, api_key: api_key, preserve_if_empty: preserveIfEmpty })
                        });
                        const data = await response.json();
                        if (data.success) {
                            const savedUsername = data.username ?? username;
                            const savedApiKey = data.api_key ?? api_key;
                            userAuth = { username: savedUsername, api_key: savedApiKey, has_auth: !!(savedUsername && savedApiKey) };
                        }
                        return data;
                    } catch (e) {
                        logger.warn("保存 Danbooru 认证信息失败:", e);
                        return { success: false, error: "网络错误" };
                    }
                };

                const loadDanbooruCookie = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/danbooru_cookie');
                        const data = await response.json();
                        if (data && data.success !== false) {
                            danbooruCookie = {
                                enabled: !!data.enabled,
                                cookie: data.cookie || "",
                                has_cookie: !!data.has_cookie,
                                has_cf_clearance: !!data.has_cf_clearance,
                                has_login_session: !!data.has_login_session
                            };
                        } else {
                            logger.warn("加载 Danbooru Cookie 设置失败，保留当前内存值:", data?.error || data);
                        }
                        return danbooruCookie;
                    } catch (e) {
                        logger.warn("加载 Danbooru Cookie 设置失败，保留当前内存值:", e);
                        return danbooruCookie;
                    }
                };

                const saveDanbooruCookie = async (cookie, enabled, preserveIfEmpty = true) => {
                    try {
                        const response = await fetch('/danbooru_gallery/danbooru_cookie', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ cookie, enabled, preserve_if_empty: preserveIfEmpty })
                        });
                        const data = await response.json();
                        if (data.success) {
                            const savedCookie = data.cookie ?? cookie;
                            const savedEnabled = data.enabled ?? enabled;
                            danbooruCookie = {
                                enabled: !!savedEnabled,
                                cookie: savedCookie,
                                has_cookie: !!String(savedCookie || '').trim(),
                                has_cf_clearance: !!data.has_cf_clearance,
                                has_login_session: !!data.has_login_session
                            };
                        }
                        return data;
                    } catch (e) {
                        logger.warn("保存 Danbooru Cookie 设置失败:", e);
                        return { success: false, error: "网络错误" };
                    }
                };

                const openDanbooruCookieLogin = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/danbooru_cookie/open_login', { method: 'POST' });
                        const data = await response.json();
                        if (data.success) {
                            showToast('已打开/切到 Danbooru 登录页', 'success');
                        } else {
                            showToast(String(data.error || '打开 Danbooru 登录页失败').slice(0, 180), 'error');
                        }
                        return data;
                    } catch (e) {
                        showToast('打开 Danbooru 登录页网络错误', 'error');
                        return { success: false, error: '网络错误' };
                    }
                };

                const captureDanbooruCookieLogin = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/danbooru_cookie/capture_login', { method: 'POST' });
                        const data = await response.json();
                        if (data.success) {
                            danbooruCookie = {
                                enabled: !!data.enabled,
                                cookie: data.cookie || "",
                                has_cookie: !!data.has_cookie,
                                has_cf_clearance: !!data.has_cf_clearance,
                                has_login_session: !!data.has_login_session
                            };
                            danbooruBrowserHeaders = {
                                ...danbooruBrowserHeaders,
                                enabled: !!data.browser_headers_enabled,
                                headers: data.browser_headers || "",
                                has_headers: !!data.browser_headers,
                                parsed_count: parseInt(data.browser_headers_parsed_count || 0, 10),
                                has_cookie: !!data.browser_headers_has_cookie,
                                has_cf_clearance: !!data.browser_headers_has_cf_clearance,
                                has_user_agent: !!data.browser_headers_has_user_agent
                            };
                            showToast('已保存当前 Danbooru 登录态', 'success');
                        } else {
                            showToast(String(data.error || '保存 Danbooru 登录态失败').slice(0, 180), 'error');
                        }
                        return data;
                    } catch (e) {
                        showToast('保存 Danbooru 登录态网络错误', 'error');
                        return { success: false, error: '网络错误' };
                    }
                };

                const loadDanbooruBrowserHeaders = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/danbooru_browser_headers');
                        const data = await response.json();
                        if (data && data.success !== false) {
                            danbooruBrowserHeaders = {
                                enabled: !!data.enabled,
                                headers: data.headers || "",
                                has_headers: !!data.has_headers,
                                parsed_count: parseInt(data.parsed_count || 0, 10),
                                has_cookie: !!data.has_cookie,
                                has_cf_clearance: !!data.has_cf_clearance,
                                has_user_agent: !!data.has_user_agent,
                            };
                        } else {
                            logger.warn("加载 Danbooru 浏览器请求头设置失败，保留当前内存值:", data?.error || data);
                        }
                        return danbooruBrowserHeaders;
                    } catch (e) {
                        logger.warn("加载 Danbooru 浏览器请求头设置失败，保留当前内存值:", e);
                        return danbooruBrowserHeaders;
                    }
                };

                const saveDanbooruBrowserHeaders = async (headers, enabled, preserveIfEmpty = true) => {
                    try {
                        const response = await fetch('/danbooru_gallery/danbooru_browser_headers', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ headers, enabled, preserve_if_empty: preserveIfEmpty })
                        });
                        const data = await response.json();
                        if (data.success) {
                            const savedHeaders = data.headers ?? headers;
                            const savedEnabled = data.enabled ?? enabled;
                            danbooruBrowserHeaders = {
                                enabled: !!savedEnabled,
                                headers: savedHeaders,
                                has_headers: !!String(savedHeaders || '').trim(),
                                parsed_count: parseInt(data.parsed_count || 0, 10),
                                has_cookie: !!data.has_cookie,
                                has_cf_clearance: !!data.has_cf_clearance,
                                has_user_agent: !!data.has_user_agent,
                            };
                        }
                        return data;
                    } catch (e) {
                        logger.warn("保存 Danbooru 浏览器请求头设置失败:", e);
                        return { success: false, error: "网络错误" };
                    }
                };

                const loadGelbooruAuth = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/gelbooru_auth');
                        const data = await response.json();
                        if (data && data.success !== false) {
                            gelbooruAuth = {
                                user_id: data.user_id || "",
                                api_key: data.api_key || "",
                                has_auth: !!(data.user_id && data.api_key)
                            };
                        } else {
                            logger.warn("加载 Gelbooru 认证信息失败，保留当前内存值:", data?.error || data);
                        }
                        return gelbooruAuth;
                    } catch (e) {
                        logger.warn("加载 Gelbooru 认证信息失败，保留当前内存值:", e);
                        return gelbooruAuth;
                    }
                };

                const saveGelbooruAuth = async (user_id, api_key, preserveIfEmpty = true) => {
                    try {
                        const response = await fetch('/danbooru_gallery/gelbooru_auth', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ user_id, api_key, preserve_if_empty: preserveIfEmpty })
                        });
                        const data = await response.json();
                        if (data.success) {
                            const savedUserId = data.user_id ?? user_id;
                            const savedApiKey = data.api_key ?? api_key;
                            gelbooruAuth = { user_id: savedUserId, api_key: savedApiKey, has_auth: !!(savedUserId && savedApiKey) };
                        }
                        return data;
                    } catch (e) {
                        logger.warn("保存 Gelbooru 认证信息失败:", e);
                        return { success: false, error: "网络错误" };
                    }
                };

                const loadCivitaiAuth = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/civitai_auth');
                        const data = await response.json();
                        if (data && data.success !== false) {
                            civitaiAuth = { api_key: data.api_key || "", has_auth: !!data.api_key };
                        } else {
                            logger.warn("加载 Civitai API Key 失败，保留当前内存值:", data?.error || data);
                        }
                        return civitaiAuth;
                    } catch (e) {
                        logger.warn("加载 Civitai API Key 失败，保留当前内存值:", e);
                        return civitaiAuth;
                    }
                };

                const saveCivitaiAuth = async (api_key, preserveIfEmpty = true) => {
                    try {
                        const response = await fetch('/danbooru_gallery/civitai_auth', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ api_key, preserve_if_empty: preserveIfEmpty })
                        });
                        const data = await response.json();
                        if (data.success) {
                            const savedApiKey = data.api_key ?? api_key;
                            civitaiAuth = { api_key: savedApiKey, has_auth: !!savedApiKey };
                        }
                        return data;
                    } catch (e) {
                        logger.warn("保存 Civitai API Key 失败:", e);
                        return { success: false, error: "网络错误" };
                    }
                };


                const loadCivitaiRemoteFavorites = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/civitai_remote_favorites');
                        const data = await response.json();
                        if (data && data.success !== false) {
                            civitaiRemoteFavorites = {
                                enabled: !!data.enabled,
                                headers: data.headers || "",
                                collection_headers: data.collection_headers || "",
                                search_headers: data.search_headers || "",
                                has_headers: !!data.has_headers,
                                has_collection_headers: !!data.has_collection_headers,
                                has_search_headers: !!data.has_search_headers,
                                has_cookie: !!data.has_cookie,
                                has_civitai_token: !!data.has_civitai_token,
                                has_authorization: !!data.has_authorization,
                                parsed_count: data.parsed_count || 0,
                                default_collection_id: data.default_collection_id || "",
                                collections: Array.isArray(data.collections) ? data.collections : [],
                                selected_collection: data.selected_collection || null,
                                remote_error: data.remote_error || ""
                            };
                        }
                        return civitaiRemoteFavorites;
                    } catch (e) {
                        logger.warn("加载 Civitai 远端收藏设置失败:", e);
                        return civitaiRemoteFavorites;
                    }
                };

                const saveCivitaiRemoteFavorites = async (collectionHeaders, searchHeaders, enabled, defaultCollectionId = "", preserveIfEmpty = true) => {
                    try {
                        const response = await fetch('/danbooru_gallery/civitai_remote_favorites', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ collection_headers: collectionHeaders, search_headers: searchHeaders, enabled, default_collection_id: defaultCollectionId, preserve_if_empty: preserveIfEmpty })
                        });
                        const data = await response.json();
                        if (data.success) {
                            civitaiRemoteFavorites = {
                                ...civitaiRemoteFavorites,
                                enabled: !!data.enabled,
                                headers: data.headers || "",
                                collection_headers: data.collection_headers || collectionHeaders || "",
                                search_headers: data.search_headers || searchHeaders || "",
                                has_headers: !!data.has_headers,
                                has_collection_headers: !!data.has_collection_headers,
                                has_search_headers: !!data.has_search_headers,
                                has_cookie: !!data.has_cookie,
                                has_civitai_token: !!data.has_civitai_token,
                                has_authorization: !!data.has_authorization,
                                parsed_count: data.parsed_count || 0,
                                default_collection_id: data.default_collection_id || ""
                            };
                        }
                        return data;
                    } catch (e) {
                        logger.warn("保存 Civitai 远端收藏设置失败:", e);
                        return { success: false, error: "网络错误" };
                    }
                };

                const testCivitaiRemoteFavorites = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/civitai_remote_favorites/test', { method: 'POST' });
                        const data = await response.json();
                        if (data.success) {
                            civitaiRemoteFavorites.collections = Array.isArray(data.collections) ? data.collections : [];
                            civitaiRemoteFavorites.selected_collection = data.selected || null;
                            const selected = data.selected;
                            showToast(`Civitai 远端收藏可用：${civitaiRemoteFavorites.collections.length} 个收藏夹${selected?.name ? `，默认 ${selected.name}` : ''}`, 'success');
                        } else {
                            showToast(String(data.error || 'Civitai 远端收藏测试失败').slice(0, 180), 'error');
                        }
                        return data;
                    } catch (e) {
                        showToast('Civitai 远端收藏测试网络错误', 'error');
                        return { success: false, error: '网络错误' };
                    }
                };

                const openCivitaiRemoteLogin = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/civitai_remote_favorites/open_login', { method: 'POST' });
                        const data = await response.json();
                        if (data.success) {
                            showToast('已打开/切到 Civitai 登录页', 'success');
                        } else {
                            showToast(String(data.error || '打开 Civitai 登录页失败').slice(0, 180), 'error');
                        }
                        return data;
                    } catch (e) {
                        showToast('打开 Civitai 登录页网络错误', 'error');
                        return { success: false, error: '网络错误' };
                    }
                };

                const captureCivitaiRemoteLogin = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/civitai_remote_favorites/capture_login', { method: 'POST' });
                        const data = await response.json();
                        if (data.success) {
                            civitaiRemoteFavorites = {
                                ...civitaiRemoteFavorites,
                                enabled: !!data.enabled,
                                headers: data.headers || "",
                                collection_headers: data.collection_headers || "",
                                search_headers: data.search_headers || civitaiRemoteFavorites.search_headers || "",
                                has_headers: !!data.has_headers,
                                has_collection_headers: !!data.has_collection_headers,
                                has_search_headers: !!data.has_search_headers,
                                has_cookie: !!data.has_cookie,
                                has_civitai_token: !!data.has_civitai_token,
                                has_authorization: !!data.has_authorization,
                                parsed_count: data.parsed_count || 0,
                                default_collection_id: data.default_collection_id || civitaiRemoteFavorites.default_collection_id || ""
                            };
                            showToast('已保存当前 Civitai 登录态', 'success');
                        } else {
                            showToast(String(data.error || '保存 Civitai 登录态失败').slice(0, 180), 'error');
                        }
                        return data;
                    } catch (e) {
                        showToast('保存 Civitai 登录态网络错误', 'error');
                        return { success: false, error: '网络错误' };
                    }
                };

                // 显示提示消息功能
                const showToast = (message, type = 'info', anchorElement = null) => {
                    // 使用全局toast管理器，并根据类型设置对应的等级
                    const toastLevel = getToastLevel(type);
                    const options = anchorElement ? { targetElement: anchorElement } : {};

                    toastManagerProxy.showToast(message, toastLevel, 3000, options);
                };

                const getToastLevel = (type) => {
                    // 将toast类型映射到全局toast管理器的等级
                    const levelMap = {
                        'success': 'success',
                        'error': 'error',
                        'warning': 'warning',
                        'info': 'info'
                    };
                    return levelMap[type] || 'info';
                };

                // 收藏管理功能
                const addToFavorites = async (postId, button = null, source = "danbooru", postData = null) => {
                    if (source === "danbooru" && !hasDanbooruFavoriteAuth()) {
                        showToast(t('authRequired'), 'warning');
                        return { success: false, error: t('authRequired') };
                    }

                    // 显示加载状态
                    if (button) {
                        button.disabled = true;
                        const originalHTML = button.innerHTML;
                        button.innerHTML = '<div class="spinner"></div>';
                        button.dataset.originalHTML = originalHTML;
                    }

                    try {
                        const response = await fetch('/danbooru_gallery/favorites/add', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ post_id: postId, source, post_data: postData })
                        });
                        const data = await response.json();

                        // 恢复按钮状态
                        if (button) {
                            button.disabled = false;
                            if (data.success || data.message === "已收藏，无需重复操作") {
                                button.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="#DC3545" stroke="#DC3545" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
                                </svg>`;
                                button.title = t('unfavorite');
                                button.classList.add('favorited');
                                if (!userFavorites.includes(postId)) {
                                    userFavorites.push(String(postId));
                                }
                                // 显示收藏成功提示
                                showToast(t('favorite') + '成功', 'success', button);
                            } else {
                                button.innerHTML = button.dataset.originalHTML || originalHTML;
                            }
                            delete button.dataset.originalHTML;
                        }

                        if (!data.success) {
                            let errorMsg = data.error || "未知错误";
                            if (data.error.includes("网络错误")) {
                                showError(`${errorMsg} - 请检查网络连接`);
                            } else if (data.error.includes("认证") || data.error.includes("401")) {
                                errorMsg = `${errorMsg}\n\n${t('authRequired')}`;
                                if (confirm(errorMsg + "\n\n是否打开设置？")) {
                                    showSettingsDialog();
                                }
                            } else if (data.error.includes("Rate Limited") || data.error.includes("429")) {
                                showError(`${errorMsg} - 请稍后重试`);
                            } else {
                                showError(errorMsg);
                            }
                        }

                        return data;
                    } catch (e) {
                        logger.warn("添加收藏失败:", e);
                        showError(source === 'civitai' ? '网络错误 - 无法更新 Civitai 本地收藏' : '网络错误 - 无法连接到Danbooru服务器');
                        if (button) {
                            button.disabled = false;
                            button.innerHTML = button.dataset.originalHTML || '<svg>...</svg>';  // 恢复
                            delete button.dataset.originalHTML;
                        }
                        return { success: false, error: "网络错误" };
                    }
                };

                const removeFromFavorites = async (postId, button = null, source = "danbooru") => {
                    if (source === "danbooru" && !hasDanbooruFavoriteAuth()) {
                        showToast(t('authRequired'), 'warning');
                        return { success: false, error: t('authRequired') };
                    }

                    // 显示加载状态
                    if (button) {
                        button.disabled = true;
                        const originalHTML = button.innerHTML;
                        button.innerHTML = '<div class="spinner"></div>';
                        button.dataset.originalHTML = originalHTML;
                    }

                    try {
                        const response = await fetch('/danbooru_gallery/favorites/remove', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ post_id: postId, source })
                        });
                        let data;
                        if (response.status === 204) {
                            // 204 No Content 表示成功，但没有响应体
                            data = { success: true, message: "取消收藏成功" };
                        } else {
                            data = await response.json();
                        }

                        // 恢复按钮状态
                        if (button) {
                            button.disabled = false;
                            if (data.success) {
                                button.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
                                </svg>`;
                                button.title = t('favorite');
                                button.classList.remove('favorited');
                                const index = userFavorites.indexOf(String(postId));
                                if (index > -1) {
                                    userFavorites.splice(index, 1);
                                }
                                // 显示取消收藏成功提示
                                showToast(t('unfavorite') + '成功', 'success', button);
                            } else {
                                button.innerHTML = button.dataset.originalHTML || originalHTML;
                            }
                            delete button.dataset.originalHTML;
                        }

                        if (!data.success) {
                            let errorMsg = data.error || "未知错误";
                            if (data.error.includes("网络错误")) {
                                showError(`${errorMsg} - 请检查网络连接`);
                            } else if (data.error.includes("认证") || data.error.includes("401")) {
                                errorMsg = `${errorMsg}\n\n${t('authRequired')}`;
                                if (confirm(errorMsg + "\n\n是否打开设置？")) {
                                    showSettingsDialog();
                                }
                            } else if (data.error.includes("Rate Limited") || data.error.includes("429")) {
                                showError(`${errorMsg} - 请稍后重试`);
                            } else {
                                showError(errorMsg);
                            }
                        }

                        return data;
                    } catch (e) {
                        logger.warn("移除收藏失败:", e);
                        showError(source === 'civitai' ? '网络错误 - 无法更新 Civitai 本地收藏' : '网络错误 - 无法连接到Danbooru服务器');
                        if (button) {
                            button.disabled = false;
                            button.innerHTML = button.dataset.originalHTML || '<svg>...</svg>';
                            delete button.dataset.originalHTML;
                        }
                        return { success: false, error: "网络错误" };
                    }
                };

                const loadFavorites = async (source = currentSource) => {
                    try {
                        const response = await fetch(`/danbooru_gallery/favorites?source=${encodeURIComponent(source || 'danbooru')}&_=${Date.now()}`, { cache: 'no-store', headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' } });
                        const data = await response.json();
                        userFavorites = data.favorites || [];
                        return userFavorites;
                    } catch (e) {
                        logger.warn("加载收藏列表失败:", e);
                        userFavorites = [];
                        return userFavorites;
                    }
                };

                // 语言管理功能
                const loadLanguage = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/language');
                        const data = await response.json();
                        globalMultiLanguageManager.setLanguage(data.language || 'zh', true);
                    } catch (e) {
                        logger.warn("加载语言设置失败:", e);
                        globalMultiLanguageManager.setLanguage('zh', true);
                    }
                };

                const saveLanguage = async (language) => {
                    try {
                        const response = await fetch('/danbooru_gallery/language', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ language: language })
                        });
                        const data = await response.json();
                        return data.success;
                    } catch (e) {
                        logger.warn("保存语言设置失败:", e);
                        return false;
                    }
                };

                // 更新界面文本
                const updateInterfaceTexts = () => {
                    // 更新搜索框
                    searchInput.placeholder = t('searchPlaceholder');

                    // 更新按钮文本和提示
                    const categoryButton = categoryDropdown.querySelector('.danbooru-category-button');
                    if (categoryButton) {
                        categoryButton.innerHTML = `${t('categories')} <svg class="arrow-down" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`;
                        categoryButton.title = t('categoriestooltip');
                    }

                    const formattingButton = formattingDropdown.querySelector('.danbooru-category-button');
                    if (formattingButton) {
                        formattingButton.innerHTML = `${t('formatting')} <svg class="arrow-down" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`;
                        formattingButton.title = t('formattingTooltip');
                    }

                    const ratingButton = ratingSelect.querySelector('.danbooru-category-button');
                    if (ratingButton) {
                        ratingButton.title = t('ratingTooltip');
                        updateRatingButtonLabel();
                    }

                    // 更新分级选项
                    const ratingLabels = ratingSelect.querySelectorAll('.danbooru-category-item label');
                    ratingLabels.forEach((label) => {
                        const key = label.dataset.ratingKey;
                        if (key) {
                            label.textContent = t(key);
                        }
                    });

                    // 更新类别标签
                    const categoryItems = categoryDropdown.querySelectorAll('.danbooru-category-item label');
                    const categoryKeys = ['artist', 'copyright', 'character', 'general', 'meta'];
                    categoryItems.forEach((label, index) => {
                        if (categoryKeys[index]) {
                            label.textContent = t(categoryKeys[index]);
                        }
                    });

                    // 更新格式选项
                    const formatItems = formattingDropdown.querySelectorAll('.danbooru-category-item label');
                    if (formatItems.length >= 2) {
                        formatItems[0].textContent = t('escapeBrackets');
                        formatItems[1].textContent = t('replaceUnderscores');
                    }

                    // 更新按钮tooltip
                    rankingButton.title = t('rankingTooltip');
                    favoritesButton.title = t('favorites');
                    refreshButton.title = t('refreshTooltip');
                    settingsButton.title = t('settings');
                    filterButton.title = t('filterTooltip');

                    // 更新排行榜按钮文本
                    const rankingIcon = rankingButton.querySelector('.icon');
                    if (rankingIcon) {
                        rankingButton.innerHTML = rankingIcon.outerHTML + t('ranking');
                    }

                    // 更新收藏夹按钮文本
                    const favoritesIcon = favoritesButton.querySelector('.icon');
                    if (favoritesIcon) {
                        favoritesButton.innerHTML = favoritesIcon.outerHTML + t('favorites');
                    }

                    // 更新加载状态文本
                    const loadingElement = imageGrid.querySelector('.danbooru-loading');
                    if (loadingElement) {
                        loadingElement.textContent = t('loading');
                    }

                    // 更新侧边栏按钮文本（如果设置对话框已打开）
                    const sidebarButtons = document.querySelectorAll('.sidebar-button');
                    sidebarButtons.forEach(button => {
                        const key = button.dataset.key;
                        if (key) {
                            const titleSpan = button.querySelector('.sidebar-button-title');
                            if (titleSpan) {
                                titleSpan.textContent = t(key + 'Section');
                            }
                        }
                    });
                };

                const searchInput = $el("input.danbooru-search-input", {
                    type: "text",
                    placeholder: t('searchPlaceholder'),
                    title: t('searchPlaceholder'),
                    "aria-label": "搜索标签或关键词",
                    "data-testid": "gallery-search",
                });
                searchInput.setAttribute("data-testid", "gallery-search");
                let civitaiLooseMode = loadFromLocalStorage('civitaiLooseMode', 'false') === 'true';
                let urlExportMode = loadFromLocalStorage('urlExportMode', 'false') === 'true';
                const sourceSelect = $el("select.danbooru-source-select", {
                    title: "图库来源 / Source",
                    "aria-label": "图库来源",
                    "data-testid": "gallery-source",
                    style: {
                        height: "46px",
                        minWidth: "112px",
                        padding: "0 10px",
                        border: "1px solid var(--input-border-color)",
                        borderRadius: "6px",
                        backgroundColor: "var(--comfy-input-bg)",
                        color: "var(--comfy-input-text)",
                        fontSize: "13px",
                        cursor: "pointer"
                    }
                }, [
                    $el("option", { value: "danbooru", textContent: "Danbooru" }),
                    $el("option", { value: "gelbooru", textContent: "Gelbooru" }),
                    $el("option", { value: "civitai", textContent: "Civitai.red" }),
                    $el("option", { value: "yandere", textContent: "Yande.re" })
                ]);
                sourceSelect.value = currentSource;
                sourceSelect.addEventListener("change", async () => {
                    await handleV53SourceChange(normalizeSource(sourceSelect.value));
                });
                const RATING_VALUES = ["general", "sensitive", "questionable", "explicit"];
                const normalizePostRating = (rating) => {
                    const map = { g: "general", s: "sensitive", q: "questionable", e: "explicit" };
                    return map[rating] || rating;
                };
                const createRatingDropdown = () => {
                    const createRatingCheckbox = (name, checked = false) => {
                        const id = `danbooru-rating-${name}`;
                        const checkbox = $el("input", {
                            type: "checkbox",
                            id,
                            name,
                            checked,
                            className: "danbooru-category-checkbox danbooru-rating-checkbox"
                        });

                        return $el("div.danbooru-category-item", [
                            checkbox,
                            $el("label", { htmlFor: id, textContent: t(name), dataset: { ratingKey: name } })
                        ]);
                    };

                    const allId = "danbooru-rating-all";
                    const allCheckbox = $el("input", {
                        type: "checkbox",
                        id: allId,
                        name: "__all__",
                        checked: true,
                        className: "danbooru-category-checkbox danbooru-rating-checkbox danbooru-rating-all-checkbox"
                    });
                    const allItem = $el("div.danbooru-category-item", [
                        allCheckbox,
                        $el("label", { htmlFor: allId, textContent: t('all'), dataset: { ratingKey: 'all' } })
                    ]);

                    const listItems = [
                        allItem,
                        createRatingCheckbox("general"),
                        createRatingCheckbox("sensitive"),
                        createRatingCheckbox("questionable"),
                        createRatingCheckbox("explicit")
                    ];

                    const dropdown = $el("div.danbooru-rating-dropdown.danbooru-category-dropdown", [
                        $el("button.danbooru-category-button", {
                            innerHTML: `${t('all')} <svg class="arrow-down" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`,
                            title: t('ratingTooltip')
                        }),
                        $el("div.danbooru-category-list", {}, listItems)
                    ]);

                    return dropdown;
                };

                const ratingSelect = createRatingDropdown();
                const getSelectedRatings = () => {
                    return Array.from(ratingSelect.querySelectorAll(".danbooru-rating-checkbox:checked"))
                        .map(i => i.name)
                        .filter(name => name !== "__all__");
                };
                const updateRatingButtonLabel = () => {
                    const ratingButton = ratingSelect.querySelector('.danbooru-category-button');
                    if (!ratingButton) return;

                    const selectedRatings = getSelectedRatings();
                    let buttonText = t('all');
                    if (selectedRatings.length === 1) {
                        buttonText = t(selectedRatings[0]);
                    } else if (selectedRatings.length > 1 && selectedRatings.length < RATING_VALUES.length) {
                        buttonText = selectedRatings.map(r => t(r)).join(" / ");
                    }

                    ratingButton.dataset.values = JSON.stringify(selectedRatings);
                    ratingButton.innerHTML = `${buttonText} <svg class="arrow-down" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`;
                };
                const applySelectedRatings = (selectedRatings = RATING_VALUES) => {
                    const targetRatings = (Array.isArray(selectedRatings) && selectedRatings.length > 0)
                        ? selectedRatings.filter(v => RATING_VALUES.includes(v))
                        : [...RATING_VALUES];

                    const allCheckbox = ratingSelect.querySelector('.danbooru-rating-all-checkbox');
                    const ratingCheckboxes = ratingSelect.querySelectorAll('.danbooru-rating-checkbox:not(.danbooru-rating-all-checkbox)');
                    ratingCheckboxes.forEach((checkbox) => {
                        checkbox.checked = targetRatings.includes(checkbox.name);
                    });
                    if (allCheckbox) {
                        allCheckbox.checked = targetRatings.length === RATING_VALUES.length;
                    }
                    updateRatingButtonLabel();
                };
                const bindRatingDropdownEvents = () => {
                    const allCheckbox = ratingSelect.querySelector('.danbooru-rating-all-checkbox');
                    const ratingCheckboxes = ratingSelect.querySelectorAll('.danbooru-rating-checkbox:not(.danbooru-rating-all-checkbox)');

                    if (allCheckbox) {
                        allCheckbox.addEventListener('change', () => {
                            const checked = allCheckbox.checked;
                            ratingCheckboxes.forEach(cb => { cb.checked = checked; });
                            updateRatingButtonLabel();
                            ratingSelect.dispatchEvent(new Event('change'));
                        });
                    }

                    ratingCheckboxes.forEach((checkbox) => {
                        checkbox.addEventListener('change', () => {
                            const selectedRatings = getSelectedRatings();
                            if (allCheckbox) {
                                allCheckbox.checked = selectedRatings.length === RATING_VALUES.length;
                            }
                            updateRatingButtonLabel();
                            ratingSelect.dispatchEvent(new Event('change'));
                        });
                    });
                };
                bindRatingDropdownEvents();
                applySelectedRatings(RATING_VALUES);

                const createCategoryCheckbox = (name, checked = false) => { // Default to false, will be set later
                    const id = `danbooru-category-${name}`;
                    const checkbox = $el("input", { type: "checkbox", id, name, checked: checked, className: "danbooru-category-checkbox" });
                    checkbox.addEventListener('change', async () => {
                        const newSelectedCategories = Array.from(categoryDropdown.querySelectorAll("input:checked")).map(i => i.name);
                        uiSettings.selected_categories = newSelectedCategories;
                        saveToLocalStorage('selectedCategories', newSelectedCategories);
                        await saveUiSettings(uiSettings);
                    });
                    return $el("div.danbooru-category-item", [
                        checkbox,
                        $el("label", { htmlFor: id, textContent: t(name) })
                    ]);
                };

                const categoryDropdown = $el("div.danbooru-category-dropdown", [
                    $el("button.danbooru-category-button", {
                        innerHTML: `${t('categories')} <svg class="arrow-down" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`,
                        title: t('categoriestooltip')
                    }),
                    $el("div.danbooru-category-list", {}, [
                        createCategoryCheckbox("artist"),
                        createCategoryCheckbox("copyright"),
                        createCategoryCheckbox("character"),
                        createCategoryCheckbox("general"),
                        createCategoryCheckbox("meta")
                    ])
                ]);

                const createFormattingCheckbox = (name, label, checked = true) => {
                    const id = `danbooru-format-${name}`;
                    const checkbox = $el("input", { type: "checkbox", id, name, checked, className: "danbooru-format-checkbox" });
                    checkbox.addEventListener('change', async () => {
                        const newFormattingOptions = {
                            escapeBrackets: formattingDropdown.querySelector('[name="escapeBrackets"]').checked,
                            replaceUnderscores: formattingDropdown.querySelector('[name="replaceUnderscores"]').checked,
                        };
                        uiSettings.formatting = newFormattingOptions;
                        saveToLocalStorage('formatting', newFormattingOptions);
                        await saveUiSettings(uiSettings);
                    });
                    return $el("div.danbooru-category-item", [
                        checkbox,
                        $el("label", { htmlFor: id, textContent: label })
                    ]);
                };

                const formattingDropdown = $el("div.danbooru-formatting-dropdown.danbooru-category-dropdown", [
                    $el("button.danbooru-category-button", {
                        innerHTML: `${t('formatting')} <svg class="arrow-down" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`,
                        title: t('formattingTooltip')
                    }),
                    $el("div.danbooru-category-list", {}, [
                        createFormattingCheckbox("escapeBrackets", t('escapeBrackets')),
                        createFormattingCheckbox("replaceUnderscores", t('replaceUnderscores')),
                    ])
                ]);

                document.addEventListener("click", (e) => {
                    const dropdowns = [categoryDropdown, formattingDropdown, ratingSelect];
                    dropdowns.forEach(dropdown => {
                        const list = dropdown.querySelector(".danbooru-category-list");
                        const button = dropdown.querySelector(".danbooru-category-button");

                        if (!button || !list) return;

                        if (!dropdown.contains(e.target)) {
                            list.classList.remove("show");
                            button.classList.remove("open");
                        } else if (e.target.closest(".danbooru-category-button")) {
                            // Close other dropdowns
                            dropdowns.forEach(otherDropdown => {
                                if (otherDropdown !== dropdown) {
                                    otherDropdown.querySelector(".danbooru-category-list")?.classList.remove("show");
                                    const otherButton = otherDropdown.querySelector(".danbooru-category-button");
                                    otherButton?.classList.remove("open");
                                }
                            });
                            list.classList.toggle("show");
                            button.classList.toggle("open");
                        }
                    });
                });

                // 排行榜按钮
                const rankingButton = $el("button.danbooru-ranking-button", {
                    title: t('rankingTooltip')
                });
                rankingButton.innerHTML = `
                   <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon">
                       <path d="M16 6L19 9L16 12"></path>
                       <path d="M8 12L5 9L8 6"></path>
                       <path d="M12 2V22"></path>
                       <path d="M3 9H21"></path>
                   </svg>
                   ${t('ranking')}`;

                // 收藏夹按钮
                const favoritesButton = $el("button.danbooru-favorites-button", {
                    title: t('favorites')
                });
                favoritesButton.innerHTML = `
                   <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon">
                       <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
                   </svg>
                   ${t('favorites')}`;

                const favoriteStreamButton = $el("button.danbooru-favorite-stream-button", {
                    title: "D站全站最近收藏动态"
                });
                favoriteStreamButton.textContent = "收藏动态";

                // Civitai 宽松搜索按钮：不污染搜索框，发请求时临时注入 mode:loose。
                const civitaiLooseButton = $el("button.danbooru-civitai-loose-button", {
                    title: "Civitai 宽松搜索：关闭时多关键词默认严格 AND；开启时按相关度排序。"
                });
                const updateCivitaiLooseButtonState = () => {
                    const v53SearchActive = v53UiReady
                        && galleryStore.getDraft(currentSource)?.mode === "search";
                    civitaiLooseButton.style.display = currentSource === "civitai"
                        && (!v53UiReady || v53SearchActive) ? "flex" : "none";
                    civitaiLooseButton.classList.toggle('active', !!civitaiLooseMode);
                    civitaiLooseButton.textContent = civitaiLooseMode ? '宽松' : '严格';
                    civitaiLooseButton.title = civitaiLooseMode
                        ? 'Civitai 当前：宽松搜索。点击切回严格 AND。'
                        : 'Civitai 当前：严格 AND。点击切到宽松搜索。';
                };
                updateCivitaiLooseButtonState();
                civitaiLooseButton.addEventListener('click', () => {
                    if (currentSource !== 'civitai') return;
                    civitaiLooseMode = !civitaiLooseMode;
                    saveToLocalStorage('civitaiLooseMode', String(civitaiLooseMode));
                    updateCivitaiLooseButtonState();
                    fetchAndRender(true);
                });

                // 通用 URL 导出按钮：支持 Danbooru / Gelbooru / Civitai。
                // 默认不把 Creator/URL 混进 prompt；需要网址时手动开启。
                const urlExportButton = $el("button.danbooru-url-export-button", {
                    title: "网址导出：开启后选图只输出当前图的网页地址。"
                });
                const updateUrlExportButtonState = () => {
                    urlExportButton.style.display = "flex";
                    urlExportButton.classList.toggle('active', !!urlExportMode);
                    urlExportButton.textContent = urlExportMode ? '网址开' : '网址';
                    urlExportButton.title = urlExportMode
                        ? '当前：只导出网页地址。点击恢复提示词/tag 导出。'
                        : '当前：正常导出提示词/tag。点击改为只导出网页地址。';
                };
                updateUrlExportButtonState();
                urlExportButton.addEventListener('click', () => {
                    urlExportMode = !urlExportMode;
                    saveToLocalStorage('urlExportMode', String(urlExportMode));
                    updateUrlExportButtonState();
                    updateSelectionData();
                });

                // 导出设置：v9.1 起直接从后端持久配置导出，确保包含 D/G 两站 API 和 Danbooru Cookie。
                const exportSettings = async () => {
                    try {
                        await Promise.allSettled([loadUserAuth(), loadDanbooruCookie(), loadDanbooruBrowserHeaders(), loadGelbooruAuth(), loadCivitaiAuth(), loadCivitaiRemoteFavorites()]);
                        const response = await fetch('/danbooru_gallery/settings_full');
                        const data = await response.json();
                        if (!data || !data.success || !data.export) {
                            throw new Error(data?.error || '完整设置导出接口失败');
                        }
                        const exportPayload = data.export;
                        exportPayload.frontend_state = {
                            source: currentSource,
                            exported_from: 'settings_dialog',
                            note: '此文件包含 API key/Cookie。不要上传到公开位置，不要发给别人。'
                        };
                        const blob = new Blob([JSON.stringify(exportPayload, null, 2)], { type: 'application/json' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
                        a.download = `danbooru_gallery_settings_full_${ts}.json`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                        showToast('完整设置已导出：包含 D站/G站 API 和 Cookie，请勿外发', 'success');
                    } catch (e) {
                        logger.error('完整设置导出失败:', e);
                        showToast(`导出设置失败：${e.message || e}`, 'error');
                    }
                };

                // 导入设置：支持完整恢复 API key/Cookie，同时兼容旧版导出文件。
                const importSettings = (dialog) => {
                    const input = document.createElement('input');
                    input.type = 'file';
                    input.accept = '.json';
                    input.onchange = (e) => {
                        const file = e.target.files[0];
                        if (!file) return;
                        const reader = new FileReader();
                        reader.onload = async (event) => {
                            try {
                                const s = JSON.parse(event.target.result);
                                if (s.contains_sensitive_secrets || s.contains_sensitive_auth || s.auth || s.settings?.danbooru_api_key || s.settings?.danbooru_cookie || s.settings?.gelbooru_api_key) {
                                    const ok = confirm('这个设置文件可能包含 API key / Cookie。确认只从你自己的备份导入？');
                                    if (!ok) return;
                                }
                                const response = await fetch('/danbooru_gallery/settings_full', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify(s)
                                });
                                const result = await response.json();
                                if (!result.success) {
                                    showToast(result.error || t('saveFailed'), 'error');
                                    return;
                                }
                                await Promise.allSettled([
                                    loadLanguage(), loadBlacklist(), loadFilterTags(), loadUiSettings(),
                                    loadUserAuth(), loadDanbooruCookie(), loadDanbooruBrowserHeaders(), loadGelbooruAuth(), loadCivitaiAuth(), loadCivitaiRemoteFavorites()
                                ]);
                                showToast('设置已导入，包含的 API/Cookie 已恢复', 'success');
                                dialog.unifiedClose();
                                await initializeApp();
                                await showSettingsDialog();
                            } catch (error) {
                                logger.error("Failed to import settings:", error);
                                showToast(t('importError'), 'error');
                            }
                        };
                        reader.readAsText(file);
                    };
                    input.click();
                };

                // 创建设置页面对话框
                const showSettingsDialog = async (initialState = {}) => {
                    // v11: 不再阻塞等待认证/Cookie接口，先立即打开设置窗口，再后台刷新输入框。
                    // 这样 Danbooru 网络/代理卡住时，点齿轮不会长时间没反应。
                    const shouldRefreshCredentialsInBackground = !initialState.__preserveInputs;
                    let refreshCredentialsPromise = Promise.resolve([]);
                    const dialog = $el("div.danbooru-settings-dialog", {
                        style: {
                            position: "fixed",
                            top: "0",
                            left: "0",
                            width: "100%",
                            height: "100%",
                            backgroundColor: "rgba(0, 0, 0, 0.7)",
                            zIndex: "10000",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center"
                        }
                    });

                    const dialogContent = $el("div.danbooru-settings-dialog-content", {
                        style: {
                            backgroundColor: "var(--comfy-menu-bg)",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "12px",
                            padding: "24px",
                            width: "800px",
                            maxWidth: "90vw",
                            height: "600px",
                            maxHeight: "90vh",
                            boxShadow: "0 8px 32px rgba(0, 0, 0, 0.3)",
                            display: "flex",
                            flexDirection: "column"
                        }
                    });

                    const mainContainer = $el("div", {
                        style: {
                            display: "flex",
                            flex: "1",
                            gap: "20px",
                            overflow: "hidden"
                        }
                    });


                    const sidebar = $el("div.danbooru-settings-sidebar", {
                        style: {
                            width: "180px",
                            flexShrink: "0",
                            borderRight: "1px solid var(--input-border-color)"
                        }
                    });


                    const scrollContainer = $el("div.danbooru-settings-scroll-container", {
                        style: {
                            flex: "1",
                            overflowY: "auto",
                            padding: "0 16px"
                        }
                    });

                    const title = $el("h2", {
                        textContent: t('settings'),
                        style: {
                            margin: "0 0 20px 0",
                            color: "var(--comfy-input-text)",
                            fontSize: "1.5em",
                            fontWeight: "600",
                            borderBottom: "2px solid var(--input-border-color)",
                            paddingBottom: "12px"
                        }
                    });

                    // 语言设置部分
                    const languageSection = $el("div.danbooru-settings-section", {
                        style: {
                            marginBottom: "20px",
                            padding: "16px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "8px",
                            backgroundColor: "var(--comfy-input-bg)"
                        }
                    });

                    const languageTitle = $el("h3", {
                        textContent: t('languageSettings'),
                        style: {
                            margin: "0 0 12px 0",
                            color: "var(--comfy-input-text)",
                            fontSize: "1.1em",
                            fontWeight: "500",
                            display: "flex",
                            alignItems: "center",
                            gap: "8px"
                        }
                    });

                    const languageIcon = $el("span", {
                        innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="2" y1="12" x2="22" y2="12"></line>
                            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                        </svg>`
                    });

                    languageTitle.insertBefore(languageIcon, languageTitle.firstChild);

                    const languageOptions = $el("div", {
                        style: {
                            display: "flex",
                            gap: "12px"
                        }
                    });

                    const createLanguageButton = (lang, text) => {
                        const isActive = globalMultiLanguageManager.getLanguage() === lang;
                        const button = $el("button", {
                            textContent: text,
                            className: `danbooru-language-select-button ${isActive ? 'active' : ''}`,
                            dataset: { lang: lang } // Store lang in dataset
                        });
                        return button;
                    };

                    const zhButton = createLanguageButton('zh', '中文');
                    const enButton = createLanguageButton('en', 'English');

                    languageOptions.appendChild(zhButton);
                    languageOptions.appendChild(enButton);


                    languageSection.appendChild(languageTitle);
                    languageSection.appendChild(languageOptions);


                    // 黑名单设置部分
                    const blacklistSection = $el("div.danbooru-settings-section", {
                        style: {
                            marginBottom: "20px",
                            padding: "16px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "8px",
                            backgroundColor: "var(--comfy-input-bg)"
                        }
                    });

                    const blacklistTitle = $el("h3", {
                        textContent: t('blacklistSettings'),
                        style: {
                            margin: "0 0 8px 0",
                            color: "var(--comfy-input-text)",
                            fontSize: "1.1em",
                            fontWeight: "500",
                            display: "flex",
                            alignItems: "center",
                            gap: "8px"
                        }
                    });

                    const blacklistIcon = $el("span", {
                        innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M3 6h18l-1.5 14H4.5L3 6z"></path>
                            <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            <line x1="10" y1="11" x2="10" y2="17"></line>
                            <line x1="14" y1="11" x2="14" y2="17"></line>
                        </svg>`
                    });

                    blacklistTitle.insertBefore(blacklistIcon, blacklistTitle.firstChild);

                    const blacklistDescription = $el("p", {
                        textContent: t('blacklistDescription'),
                        style: {
                            margin: "0 0 12px 0",
                            color: "#888",
                            fontSize: "0.9em"
                        }
                    });

                    const blacklistTextarea = $el("textarea", {
                        placeholder: t('blacklistPlaceholder'),
                        value: initialState.blacklist ?? currentBlacklist.join('\n'),
                        style: {
                            width: "100%",
                            height: "120px",
                            padding: "12px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            fontSize: "14px",
                            resize: "vertical",
                            fontFamily: "monospace",
                            lineHeight: "1.4"
                        }
                    });

                    blacklistSection.appendChild(blacklistTitle);
                    blacklistSection.appendChild(blacklistDescription);
                    blacklistSection.appendChild(blacklistTextarea);

                    // 提示词过滤设置部分
                    const filterSection = $el("div.danbooru-settings-section", {
                        style: {
                            marginBottom: "20px",
                            padding: "16px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "8px",
                            backgroundColor: "var(--comfy-input-bg)"
                        }
                    });

                    const filterTitle = $el("h3", {
                        textContent: t('promptFilterSettings'),
                        style: {
                            margin: "0 0 8px 0",
                            color: "var(--comfy-input-text)",
                            fontSize: "1.1em",
                            fontWeight: "500",
                            display: "flex",
                            alignItems: "center",
                            gap: "8px"
                        }
                    });

                    const filterIcon = $el("span", {
                        innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
                        </svg>`
                    });

                    filterTitle.insertBefore(filterIcon, filterTitle.firstChild);

                    const filterEnableDiv = $el("div", {
                        style: {
                            marginBottom: "12px",
                            display: "flex",
                            alignItems: "center",
                            gap: "8px"
                        }
                    });

                    const filterEnableCheckbox = $el("input", {
                        type: "checkbox",
                        id: "filterEnableCheckbox",
                        checked: initialState.filterEnabled ?? filterEnabled,
                        style: {
                            width: "16px",
                            height: "16px"
                        }
                    });

                    const filterEnableLabel = $el("label", {
                        htmlFor: "filterEnableCheckbox",
                        textContent: t('promptFilterEnable'),
                        style: {
                            cursor: "pointer",
                            color: "var(--comfy-input-text)",
                            fontSize: "0.9em",
                            fontWeight: "500"
                        }
                    });

                    filterEnableDiv.appendChild(filterEnableCheckbox);
                    filterEnableDiv.appendChild(filterEnableLabel);

                    const filterDescription = $el("p", {
                        textContent: t('promptFilterDescription'),
                        style: {
                            margin: "0 0 12px 0",
                            color: "#888",
                            fontSize: "0.9em"
                        }
                    });

                    const filterTextarea = $el("textarea", {
                        placeholder: t('promptFilterPlaceholder'),
                        value: initialState.filterTags ?? currentFilterTags.join('\n'),
                        style: {
                            width: "100%",
                            height: "120px",
                            padding: "12px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            fontSize: "14px",
                            resize: "vertical",
                            fontFamily: "monospace",
                            lineHeight: "1.4"
                        }
                    });

                    filterSection.appendChild(filterTitle);
                    filterSection.appendChild(filterEnableDiv);
                    filterSection.appendChild(filterDescription);
                    filterSection.appendChild(filterTextarea);

                    // 用户认证设置部分
                    const authSection = $el("div.danbooru-settings-section", {
                        style: {
                            marginBottom: "20px",
                            padding: "16px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "8px",
                            backgroundColor: "var(--comfy-input-bg)"
                        }
                    });

                    const authTitle = $el("h3", {
                        textContent: t('userAuth'),
                        style: {
                            margin: "0 0 8px 0",
                            color: "var(--comfy-input-text)",
                            fontSize: "1.1em",
                            fontWeight: "500",
                            display: "flex",
                            alignItems: "center",
                            gap: "8px"
                        }
                    });

                    const authIcon = $el("span", {
                        innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M9 12l2 2 4-4"></path>
                            <path d="M21 12c-1 0-3-1-3-3s2-3 3-3 3 1 3 3-2 3-3 3"></path>
                            <path d="M3 12c1 0 3-1 3-3s-2-3-3-3-3 1-3 3 2 3 3 3"></path>
                            <path d="M12 3v6m0 6v6"></path>
                        </svg>`
                    });

                    authTitle.insertBefore(authIcon, authTitle.firstChild);

                    const authDescription = $el("p", {
                        textContent: t('authDescription'),
                        style: {
                            margin: "0 0 12px 0",
                            color: "#888",
                            fontSize: "0.9em"
                        }
                    });

                    const usernameInput = $el("input", {
                        type: "text",
                        placeholder: t('authPlaceholderUsername'),
                        value: (initialState.username ?? userAuth.username) || "",
                        style: {
                            width: "100%",
                            padding: "8px 12px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            fontSize: "14px",
                            marginBottom: "8px"
                        }
                    });

                    const apiKeyInput = $el("input", {
                        type: "password",
                        placeholder: t('authPlaceholderApiKey'),
                        value: (initialState.apiKey ?? userAuth.api_key) || "",
                        style: {
                            width: "100%",
                            padding: "8px 12px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            fontSize: "14px",
                            marginBottom: "8px"
                        }
                    });

                    const apiKeyHelpButton = $el("button", {
                        textContent: t('apiKeyHelp'),
                        title: t('apiKeyTooltip'),
                        style: {
                            padding: "6px 12px",
                            border: "1px solid #5865F2",
                            borderRadius: "4px",
                            backgroundColor: "transparent",
                            color: "#5865F2",
                            cursor: "pointer",
                            fontSize: "12px",
                            fontWeight: "500",
                            transition: "all 0.2s ease"
                        },
                        onclick: () => {
                            window.open('https://danbooru.donmai.us/profile', '_blank');
                        }
                    });

                    const cookieFallbackTitle = $el("h4", { textContent: "Danbooru Cookie fallback（可选，手动 Cookie 模式）", style: { margin: "18px 0 8px 0", color: "var(--comfy-input-text)", fontSize: "1em" } });
                    const cookieFallbackDesc = $el("p", {
                        textContent: "什么时候用：D诊断显示 Cloudflare challenge，或 D 收藏需要登录态时使用。\n推荐流程：点“打开/切到 D 登录”，在桥接 Chrome 里登录 Danbooru 并确认个人页可打开；然后点“保存当前登录态”。插件会自动保存 Danbooru Cookie fallback，并同步保存带 User-Agent 的浏览器请求头模式。Cookie 会过期，下次失效后再手动点按钮续期。\n注意：Cookie 等同登录/验证凭据，只能本机使用，不要外发。",
                        style: { margin: "0 0 8px 0", color: "#888", fontSize: "0.9em", lineHeight: "1.45", whiteSpace: "pre-line" }
                    });
                    const cookieEnableCheckbox = $el("input", {
                        type: "checkbox",
                        id: "danbooruCookieEnableCheckbox",
                        checked: initialState.danbooruCookieEnabled ?? danbooruCookie.enabled,
                        style: { width: "16px", height: "16px" }
                    });
                    const cookieEnableLabel = $el("label", {
                        htmlFor: "danbooruCookieEnableCheckbox",
                        textContent: "启用 Danbooru Cookie fallback",
                        style: { cursor: "pointer", color: "var(--comfy-input-text)", fontSize: "0.95em", fontWeight: "500" }
                    });
                    const cookieEnableDiv = $el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" } }, [cookieEnableCheckbox, cookieEnableLabel]);
                    const cookieInput = $el("textarea", {
                        placeholder: "点“保存当前登录态”会自动写入；也可手动填 cf_clearance=...; danbooru2_session=...",
                        value: (initialState.danbooruCookieValue ?? danbooruCookie.cookie) || "",
                        spellcheck: false,
                        style: {
                            width: "100%",
                            height: "74px",
                            padding: "8px 12px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            fontSize: "12px",
                            resize: "vertical",
                            fontFamily: "monospace",
                            marginBottom: "8px"
                        }
                    });
                    const openDanbooruButton = $el("button", {
                        textContent: "打开/切到 D 登录",
                        style: {
                            padding: "6px 12px",
                            border: "1px solid #5865F2",
                            borderRadius: "4px",
                            backgroundColor: "transparent",
                            color: "#5865F2",
                            cursor: "pointer",
                            fontSize: "12px",
                            fontWeight: "500",
                            transition: "all 0.2s ease",
                            marginBottom: "8px"
                        },
                        onclick: async () => {
                            await openDanbooruCookieLogin();
                        }
                    });
                    const captureDanbooruButton = $el("button", {
                        textContent: "保存当前登录态",
                        style: {
                            padding: "6px 12px",
                            border: "1px solid #22a06b",
                            borderRadius: "4px",
                            backgroundColor: "transparent",
                            color: "#22a06b",
                            cursor: "pointer",
                            fontSize: "12px",
                            fontWeight: "500",
                            transition: "all 0.2s ease",
                            marginBottom: "8px"
                        },
                        onclick: async () => {
                            const data = await captureDanbooruCookieLogin();
                            if (data?.success) {
                                cookieInput.value = danbooruCookie.cookie || "";
                                cookieEnableCheckbox.checked = !!danbooruCookie.enabled;
                                browserHeadersInput.value = danbooruBrowserHeaders.headers || "";
                                browserHeadersEnableCheckbox.checked = !!danbooruBrowserHeaders.enabled;
                                cookieInput.dataset.userEdited = '1';
                                browserHeadersInput.dataset.userEdited = '1';
                                cookieEnableCheckbox.dataset.userEdited = '1';
                                browserHeadersEnableCheckbox.dataset.userEdited = '1';
                                browserHeadersStatus.textContent = `当前：${danbooruBrowserHeaders.has_headers ? '已保存' : '未保存'}；Cookie=${danbooruBrowserHeaders.has_cookie ? '有' : '无'}；cf_clearance=${danbooruBrowserHeaders.has_cf_clearance ? '有' : '无'}；UA=${danbooruBrowserHeaders.has_user_agent ? '有' : '无'}`;
                            }
                        }
                    });

                    const browserHeadersTitle = $el("h4", { textContent: "Danbooru 浏览器请求头模式（推荐，可选，实验）", style: { margin: "18px 0 8px 0", color: "var(--comfy-input-text)", fontSize: "1em" } });
                    const browserHeadersDesc = $el("p", {
                        textContent: "推荐优先用这个：不用手动找 cf_clearance，直接复制整条浏览器请求/cURL，里面通常会带 Cookie、cf_clearance、User-Agent。\n获取步骤：1）打开 https://danbooru.donmai.us/posts.json?limit=1，并确认页面显示 JSON；2）按 F12 打开 DevTools；3）切到 Network；4）刷新当前页面；5）点击 Name 里 posts.json?limit=1 / danbooru.donmai.us 这条请求；6）右键该请求 -> Copy -> Copy as cURL (bash)，或者在 Headers -> Request Headers 复制整块请求头；7）把整段内容粘到下方，勾选启用并保存；8）保存后状态最好显示 Cookie=有、cf_clearance=有、UA=有。\n注意：这段内容包含 Cookie，等同登录/验证凭据，只能本机使用，不要外发。",
                        style: { margin: "0 0 8px 0", color: "#888", fontSize: "0.9em", lineHeight: "1.45", whiteSpace: "pre-line" }
                    });
                    const browserHeadersEnableCheckbox = $el("input", {
                        type: "checkbox",
                        id: "danbooruBrowserHeadersEnableCheckbox",
                        checked: initialState.danbooruBrowserHeadersEnabled ?? danbooruBrowserHeaders.enabled,
                        style: { width: "16px", height: "16px" }
                    });
                    const browserHeadersEnableLabel = $el("label", {
                        htmlFor: "danbooruBrowserHeadersEnableCheckbox",
                        textContent: "启用 Danbooru 浏览器请求头/cURL fallback",
                        style: { cursor: "pointer", color: "var(--comfy-input-text)", fontSize: "0.95em", fontWeight: "500" }
                    });
                    const browserHeadersEnableDiv = $el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" } }, [browserHeadersEnableCheckbox, browserHeadersEnableLabel]);
                    const browserHeadersInput = $el("textarea", {
                        placeholder: "推荐：Network -> 右键 posts.json?limit=1 请求 -> Copy -> Copy as cURL (bash)，整段粘贴到这里；或粘贴 Headers -> Request Headers 整块。",
                        value: (initialState.danbooruBrowserHeadersValue ?? danbooruBrowserHeaders.headers) || "",
                        spellcheck: false,
                        style: {
                            width: "100%",
                            height: "96px",
                            padding: "8px 12px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            fontSize: "12px",
                            resize: "vertical",
                            fontFamily: "monospace",
                            marginBottom: "8px"
                        }
                    });
                    const browserHeadersStatus = $el("p", {
                        textContent: `当前：${danbooruBrowserHeaders.has_headers ? '已保存' : '未保存'}；Cookie=${danbooruBrowserHeaders.has_cookie ? '有' : '无'}；cf_clearance=${danbooruBrowserHeaders.has_cf_clearance ? '有' : '无'}；UA=${danbooruBrowserHeaders.has_user_agent ? '有' : '无'}`,
                        style: { margin: "0 0 8px 0", color: "#aaa", fontSize: "0.85em", lineHeight: "1.4" }
                    });

                    const gelbooruTitle = $el("h4", { textContent: "Gelbooru API", style: { margin: "18px 0 8px 0", color: "var(--comfy-input-text)", fontSize: "1em" } });
                    const gelbooruDesc = $el("p", { textContent: "Gelbooru 搜索通常需要 user_id + api_key；留空时会尝试匿名请求。", style: { margin: "0 0 12px 0", color: "#888", fontSize: "0.9em" } });
                    const gelbooruUserIdInput = $el("input", {
                        type: "text",
                        placeholder: "Gelbooru user_id",
                        value: (initialState.gelbooruUserId ?? gelbooruAuth.user_id) || "",
                        style: {
                            width: "100%",
                            padding: "8px 12px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            fontSize: "14px",
                            marginBottom: "8px"
                        }
                    });
                    const gelbooruApiKeyInput = $el("input", {
                        type: "password",
                        placeholder: "Gelbooru api_key",
                        value: (initialState.gelbooruApiKey ?? gelbooruAuth.api_key) || "",
                        style: {
                            width: "100%",
                            padding: "8px 12px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            fontSize: "14px",
                            marginBottom: "8px"
                        }
                    });
                    const gelbooruHelpButton = $el("button", {
                        textContent: "打开 Gelbooru 账号页",
                        style: {
                            padding: "6px 12px",
                            border: "1px solid #5865F2",
                            borderRadius: "4px",
                            backgroundColor: "transparent",
                            color: "#5865F2",
                            cursor: "pointer",
                            fontSize: "12px",
                            fontWeight: "500",
                            transition: "all 0.2s ease"
                        },
                        onclick: () => {
                            window.open('https://gelbooru.com/index.php?page=account&s=options', '_blank');
                        }
                    });

                    const civitaiTitle = $el("h4", { textContent: "Civitai.red API（可选）", style: { margin: "18px 0 8px 0", color: "var(--comfy-input-text)", fontSize: "1em" } });
                    const civitaiDesc = $el("p", { textContent: "C站图片搜索走 Civitai 网页索引 multi-search/images_v6，需要在下方保存 SearchAuth；可检索 prompt/tagNames。多关键词默认严格，只有 loose/mode:loose 才宽松。远端收藏为实验功能。", style: { margin: "0 0 12px 0", color: "#888", fontSize: "0.9em", lineHeight: "1.4" } });
                    const civitaiApiKeyInput = $el("input", {
                        type: "password",
                        placeholder: "Civitai API Key（可留空）",
                        value: (initialState.civitaiApiKey ?? civitaiAuth.api_key) || "",
                        style: {
                            width: "100%",
                            padding: "8px 12px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            fontSize: "14px",
                            marginBottom: "8px"
                        }
                    });
                    const civitaiRemoteEnableCheckbox = $el("input", {
                        type: "checkbox",
                        checked: !!civitaiRemoteFavorites.enabled,
                        style: { marginRight: "8px" }
                    });
                    const civitaiRemoteEnableLabel = $el("label", {
                        style: { display: "flex", alignItems: "center", gap: "6px", color: "var(--comfy-input-text)", fontSize: "13px", margin: "8px 0" }
                    }, [civitaiRemoteEnableCheckbox, $el("span", { textContent: "启用 Civitai 远端收藏（实验）" })]);
                    const civitaiCollectionHeadersLabel = $el("div", { textContent: "① Civitai.red 收藏/collection Cookie（可点下方按钮从桥接 Chrome 保存）", style: { color: "#aaa", fontSize: "12px", margin: "8px 0 4px 0" } });
                    const civitaiCollectionHeadersInput = $el("textarea", {
                        placeholder: "点“保存当前登录态”会自动写入；也可手动粘 collection.getAllUser / collection.saveItem 的 Copy as cURL。不要发给别人。",
                        value: civitaiRemoteFavorites.collection_headers || civitaiRemoteFavorites.headers || "",
                        style: {
                            width: "100%", minHeight: "72px", padding: "8px 12px",
                            border: "1px solid var(--input-border-color)", borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)", color: "var(--comfy-input-text)",
                            fontSize: "12px", marginBottom: "8px", resize: "vertical"
                        }
                    });
                    const civitaiOpenLoginButton = $el("button", {
                        textContent: "打开/切到 C 登录",
                        style: {
                            padding: "6px 12px", border: "1px solid #5865F2", borderRadius: "4px",
                            backgroundColor: "transparent", color: "#5865F2", cursor: "pointer", fontSize: "12px",
                            marginRight: "8px"
                        },
                        onclick: async () => {
                            await openCivitaiRemoteLogin();
                        }
                    });
                    const civitaiCaptureLoginButton = $el("button", {
                        textContent: "保存当前登录态",
                        style: {
                            padding: "6px 12px", border: "1px solid #22a06b", borderRadius: "4px",
                            backgroundColor: "transparent", color: "#22a06b", cursor: "pointer", fontSize: "12px",
                            marginRight: "8px"
                        },
                        onclick: async () => {
                            const data = await captureCivitaiRemoteLogin();
                            if (data?.success) {
                                civitaiCollectionHeadersInput.value = civitaiRemoteFavorites.collection_headers || "";
                                civitaiRemoteEnableCheckbox.checked = !!civitaiRemoteFavorites.enabled;
                                civitaiCollectionHeadersInput.dataset.userEdited = '1';
                                populateCivitaiRemoteCollections(civitaiRemoteFavorites.default_collection_id || civitaiRemoteFavorites.selected_collection?.id || '');
                                updateFavoritesButtonState();
                            }
                        }
                    });
                    const civitaiSearchHeadersLabel = $el("div", { textContent: "② search-new.civitai.com 搜索授权（粘 multi-search 的 Copy as cURL）", style: { color: "#aaa", fontSize: "12px", margin: "8px 0 4px 0" } });
                    const civitaiSearchHeadersInput = $el("textarea", {
                        placeholder: "只粘 multi-search 的 Copy as cURL；这里应包含 Authorization 或 X-Meili-API-Key。不要发给别人。",
                        value: civitaiRemoteFavorites.search_headers || "",
                        style: {
                            width: "100%", minHeight: "72px", padding: "8px 12px",
                            border: "1px solid var(--input-border-color)", borderRadius: "6px",
                            backgroundColor: "var(--comfy-menu-bg)", color: "var(--comfy-input-text)",
                            fontSize: "12px", marginBottom: "8px", resize: "vertical"
                        }
                    });
                    const civitaiRemoteCollectionIdInput = $el("input", {
                        type: "text",
                        placeholder: "默认收藏夹 ID（可留空，自动用第一个可写 Image 收藏夹）",
                        value: civitaiRemoteFavorites.default_collection_id || "",
                        style: {
                            width: "100%", padding: "8px 12px", border: "1px solid var(--input-border-color)",
                            borderRadius: "6px", backgroundColor: "var(--comfy-menu-bg)", color: "var(--comfy-input-text)",
                            fontSize: "13px", marginBottom: "8px"
                        }
                    });
                    const civitaiRemoteTestButton = $el("button", {
                        textContent: "测试远端收藏",
                        style: {
                            padding: "6px 12px", border: "1px solid #5865F2", borderRadius: "4px",
                            backgroundColor: "transparent", color: "#5865F2", cursor: "pointer", fontSize: "12px",
                            marginRight: "8px"
                        },
                        onclick: async () => {
                            const saveRes = await saveCivitaiRemoteFavorites(civitaiCollectionHeadersInput.value.trim(), civitaiSearchHeadersInput.value.trim(), civitaiRemoteEnableCheckbox.checked, civitaiRemoteCollectionIdInput.value.trim(), true);
                            if (!saveRes.success) { showToast(saveRes.error || '保存远端收藏设置失败', 'error'); return; }
                            const testRes = await testCivitaiRemoteFavorites();
                            if (testRes?.success) {
                                populateCivitaiRemoteCollections(testRes?.selected?.id || civitaiRemoteCollectionIdInput.value.trim());
                                updateFavoritesButtonState();
                            }
                        }
                    });

                    const civitaiRemoteCollectionsStatus = $el("p", {
                        textContent: '',
                        style: { margin: "0 0 8px 0", color: "#aaa", fontSize: "0.85em", lineHeight: "1.4" }
                    });
                    const civitaiRemoteCollectionSelect = $el("select", {
                        style: {
                            width: "100%", padding: "8px 12px", border: "1px solid var(--input-border-color)",
                            borderRadius: "6px", backgroundColor: "var(--comfy-menu-bg)", color: "var(--comfy-input-text)",
                            fontSize: "13px", marginBottom: "8px"
                        }
                    });
                    const updateCivitaiRemoteCollectionsStatus = () => {
                        const cols = Array.isArray(civitaiRemoteFavorites.collections) ? civitaiRemoteFavorites.collections : [];
                        const selectedId = String(civitaiRemoteCollectionIdInput.value.trim() || civitaiRemoteFavorites.default_collection_id || '');
                        const selected = cols.find(c => String(c?.id || '') === selectedId) || civitaiRemoteFavorites.selected_collection || cols[0];
                        civitaiRemoteCollectionsStatus.textContent = `当前：${civitaiRemoteFavorites.has_headers ? '已保存请求头' : '未保存请求头'}；Cookie=${civitaiRemoteFavorites.has_cookie ? '有' : '无'}；CivitaiToken=${civitaiRemoteFavorites.has_civitai_token ? '有' : '无'}；SearchAuth=${civitaiRemoteFavorites.has_authorization ? '有' : '无'}；收藏Cookie=${civitaiRemoteFavorites.has_collection_headers ? '有' : '无'}；搜索授权=${civitaiRemoteFavorites.has_search_headers ? '有' : '无'}；收藏夹=${cols.length} 个${selected ? `；默认=${selected.name || selected.id} (${selected.id})` : ''}${civitaiRemoteFavorites.remote_error ? `；错误=${String(civitaiRemoteFavorites.remote_error).slice(0, 80)}` : ''}`;
                    };
                    const populateCivitaiRemoteCollections = (selectedId = '') => {
                        const cols = Array.isArray(civitaiRemoteFavorites.collections) ? civitaiRemoteFavorites.collections : [];
                        civitaiRemoteCollectionSelect.innerHTML = '';
                        const placeholderOpt = document.createElement('option');
                        placeholderOpt.value = '';
                        placeholderOpt.textContent = cols.length ? '自动使用第一个可写收藏夹' : '暂无远端收藏夹（先点测试远端收藏）';
                        civitaiRemoteCollectionSelect.appendChild(placeholderOpt);
                        cols.forEach(col => {
                            const opt = document.createElement('option');
                            opt.value = String(col?.id || '');
                            opt.textContent = `${col?.name || col?.id} (${col?.id})`;
                            civitaiRemoteCollectionSelect.appendChild(opt);
                        });
                        const finalSelected = String(selectedId || civitaiRemoteCollectionIdInput.value.trim() || civitaiRemoteFavorites.default_collection_id || civitaiRemoteFavorites.selected_collection?.id || '');
                        civitaiRemoteCollectionSelect.value = finalSelected;
                        if (!civitaiRemoteCollectionSelect.value) civitaiRemoteCollectionSelect.value = '';
                        updateCivitaiRemoteCollectionsStatus();
                    };
                    civitaiRemoteCollectionSelect.addEventListener('change', () => {
                        civitaiRemoteCollectionIdInput.value = civitaiRemoteCollectionSelect.value || '';
                        civitaiRemoteCollectionIdInput.dataset.userEdited = '1';
                        updateCivitaiRemoteCollectionsStatus();
                    });
                    civitaiRemoteCollectionIdInput.addEventListener('input', () => {
                        const val = civitaiRemoteCollectionIdInput.value.trim();
                        civitaiRemoteCollectionSelect.value = val;
                        updateCivitaiRemoteCollectionsStatus();
                    });
                    populateCivitaiRemoteCollections(civitaiRemoteFavorites.default_collection_id || civitaiRemoteFavorites.selected_collection?.id || '');

                    const civitaiHelpButton = $el("button", {
                        textContent: "打开 Civitai.red",
                        style: {
                            padding: "6px 12px",
                            border: "1px solid #5865F2",
                            borderRadius: "4px",
                            backgroundColor: "transparent",
                            color: "#5865F2",
                            cursor: "pointer",
                            fontSize: "12px",
                            fontWeight: "500",
                            transition: "all 0.2s ease"
                        },
                        onclick: () => window.open('https://civitai.red/', '_blank')
                    });

                    const credentialInputs = [usernameInput, apiKeyInput, cookieInput, browserHeadersInput, gelbooruUserIdInput, gelbooruApiKeyInput, civitaiApiKeyInput, civitaiCollectionHeadersInput, civitaiSearchHeadersInput, civitaiRemoteCollectionIdInput];
                    credentialInputs.forEach(input => {
                        input.addEventListener('input', () => { input.dataset.userEdited = '1'; });
                    });
                    cookieEnableCheckbox.addEventListener('change', () => { cookieEnableCheckbox.dataset.userEdited = '1'; });
                    browserHeadersEnableCheckbox.addEventListener('change', () => { browserHeadersEnableCheckbox.dataset.userEdited = '1'; });
                    civitaiRemoteEnableCheckbox.addEventListener('change', () => { civitaiRemoteEnableCheckbox.dataset.userEdited = '1'; });

                    const syncCredentialInputsFromMemory = () => {
                        if (!dialog.isConnected) return;
                        const syncInput = (input, value) => {
                            if (input.dataset.userEdited === '1') return;
                            if (document.activeElement === input) return;
                            input.value = value || '';
                        };
                        syncInput(usernameInput, userAuth.username);
                        syncInput(apiKeyInput, userAuth.api_key);
                        syncInput(cookieInput, danbooruCookie.cookie);
                        syncInput(browserHeadersInput, danbooruBrowserHeaders.headers);
                        syncInput(gelbooruUserIdInput, gelbooruAuth.user_id);
                        syncInput(gelbooruApiKeyInput, gelbooruAuth.api_key);
                        syncInput(civitaiApiKeyInput, civitaiAuth.api_key);
                        syncInput(civitaiCollectionHeadersInput, civitaiRemoteFavorites.collection_headers || civitaiRemoteFavorites.headers);
                        syncInput(civitaiSearchHeadersInput, civitaiRemoteFavorites.search_headers);
                        syncInput(civitaiRemoteCollectionIdInput, civitaiRemoteFavorites.default_collection_id);
                        if (civitaiRemoteEnableCheckbox.dataset.userEdited !== '1') {
                            civitaiRemoteEnableCheckbox.checked = !!civitaiRemoteFavorites.enabled;
                        }
                        populateCivitaiRemoteCollections(civitaiRemoteFavorites.default_collection_id || civitaiRemoteFavorites.selected_collection?.id || '');
                        if (cookieEnableCheckbox.dataset.userEdited !== '1') {
                            cookieEnableCheckbox.checked = !!danbooruCookie.enabled;
                        }
                        if (browserHeadersEnableCheckbox.dataset.userEdited !== '1') {
                            browserHeadersEnableCheckbox.checked = !!danbooruBrowserHeaders.enabled;
                        }
                        browserHeadersStatus.textContent = `当前：${danbooruBrowserHeaders.has_headers ? '已保存' : '未保存'}；Cookie=${danbooruBrowserHeaders.has_cookie ? '有' : '无'}；cf_clearance=${danbooruBrowserHeaders.has_cf_clearance ? '有' : '无'}；UA=${danbooruBrowserHeaders.has_user_agent ? '有' : '无'}`;
                    };

                    if (shouldRefreshCredentialsInBackground) {
                        // Wait until the dialog has rendered before any backend request starts.
                        // This keeps the gear button responsive even if a local API call stalls.
                        requestAnimationFrame(() => {
                            setTimeout(() => {
                                refreshCredentialsPromise = Promise.allSettled([loadUserAuth(), loadDanbooruCookie(), loadDanbooruBrowserHeaders(), loadGelbooruAuth(), loadCivitaiAuth(), loadCivitaiRemoteFavorites()]);
                                refreshCredentialsPromise.then(syncCredentialInputsFromMemory)
                                    .catch((e) => logger.warn('设置窗口后台刷新认证信息失败:', e));
                            }, 0);
                        });
                    }

                    authSection.appendChild(authTitle);
                    authSection.appendChild(authDescription);
                    authSection.appendChild($el("p", {
                        textContent: "v9 起 API/Cookie 会保存到 ComfyUI/user 下的持久配置；v10 起导出日志会附带诊断；v11 修复诊断面板；v14 回滚到稳定 UI，并增加 Danbooru 浏览器请求头/cURL fallback。",
                        style: { margin: "0 0 12px 0", color: "#aaa", fontSize: "0.85em", lineHeight: "1.4" }
                    }));
                    authSection.appendChild($el("h4", { textContent: "Danbooru API", style: { margin: "4px 0 8px 0", color: "var(--comfy-input-text)", fontSize: "1em" } }));
                    authSection.appendChild(usernameInput);
                    authSection.appendChild(apiKeyInput);
                    authSection.appendChild(apiKeyHelpButton);
                    authSection.appendChild(cookieFallbackTitle);
                    authSection.appendChild(cookieFallbackDesc);
                    authSection.appendChild(cookieEnableDiv);
                    authSection.appendChild(cookieInput);
                    authSection.appendChild($el("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "8px" } }, [openDanbooruButton, captureDanbooruButton]));
                    authSection.appendChild(browserHeadersTitle);
                    authSection.appendChild(browserHeadersDesc);
                    authSection.appendChild(browserHeadersEnableDiv);
                    authSection.appendChild(browserHeadersInput);
                    authSection.appendChild(browserHeadersStatus);
                    authSection.appendChild(gelbooruTitle);
                    authSection.appendChild(gelbooruDesc);
                    authSection.appendChild(gelbooruUserIdInput);
                    authSection.appendChild(gelbooruApiKeyInput);
                    authSection.appendChild(gelbooruHelpButton);
                    authSection.appendChild(civitaiTitle);
                    authSection.appendChild(civitaiDesc);
                    authSection.appendChild(civitaiApiKeyInput);
                    authSection.appendChild(civitaiRemoteEnableLabel);
                    authSection.appendChild(civitaiCollectionHeadersLabel);
                    authSection.appendChild(civitaiCollectionHeadersInput);
                    authSection.appendChild(civitaiSearchHeadersLabel);
                    authSection.appendChild(civitaiSearchHeadersInput);
                    authSection.appendChild(civitaiRemoteCollectionIdInput);
                    authSection.appendChild(civitaiRemoteCollectionSelect);
                    authSection.appendChild(civitaiRemoteCollectionsStatus);
                    authSection.appendChild($el("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "8px" } }, [civitaiOpenLoginButton, civitaiCaptureLoginButton, civitaiRemoteTestButton, civitaiHelpButton]));

                    // 自动补全设置
                    const autocompleteSection = $el("div.danbooru-settings-section", { style: { marginBottom: "20px", padding: "16px", border: "1px solid var(--input-border-color)", borderRadius: "8px", backgroundColor: "var(--comfy-input-bg)" } });
                    const autocompleteTitle = $el("h3", { textContent: t('autocompleteSettings'), style: { margin: "0 0 8px 0", color: "var(--comfy-input-text)", fontSize: "1.1em", fontWeight: "500" } });
                    const autocompleteDesc = $el("p", { textContent: t('autocompleteEnableDescription'), style: { margin: "0 0 12px 0", color: "#888", fontSize: "0.9em" } });
                    const autocompleteEnableCheckbox = $el("input", { type: "checkbox", id: "autocompleteEnableCheckbox", checked: initialState.autocompleteEnabled ?? uiSettings.autocomplete_enabled, style: { width: "16px", height: "16px" } });
                    autocompleteEnableCheckbox.onchange = (e) => { /* 用户界面中的临时状态，无需处理 */ };
                    const autocompleteEnableLabel = $el("label", { htmlFor: "autocompleteEnableCheckbox", textContent: t('autocompleteEnable'), style: { cursor: "pointer", color: "var(--comfy-input-text)", fontSize: "1em", fontWeight: "500" } });
                    const autocompleteEnableDiv = $el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" } }, [autocompleteEnableCheckbox, autocompleteEnableLabel]);

                    // 新增：最大补全数量
                    const autocompleteMaxResultsLabel = $el("label", { htmlFor: "autocompleteMaxResultsInput", textContent: t('autocompleteMaxResults'), style: { color: "var(--comfy-input-text)", fontSize: "0.9em", fontWeight: "500" } });
                    const autocompleteMaxResultsInput = $el("input", {
                        type: "number",
                        id: "autocompleteMaxResultsInput",
                        title: t('autocompleteEnableDescription'),
                        value: (initialState.autocompleteMaxResults ?? uiSettings.autocomplete_max_results) || 20,
                        min: "1",
                        max: "50",
                        style: { width: "60px", padding: '4px', marginLeft: '8px', backgroundColor: 'var(--comfy-menu-bg)', color: 'var(--comfy-input-text)', border: '1px solid var(--input-border-color)', borderRadius: '4px' }
                    });
                    const autocompleteMaxResultsDiv = $el("div", { style: { display: "flex", alignItems: "center" } }, [autocompleteMaxResultsLabel, autocompleteMaxResultsInput]);

                    autocompleteSection.appendChild(autocompleteTitle);
                    autocompleteSection.appendChild(autocompleteDesc);
                    autocompleteSection.appendChild(autocompleteEnableDiv);
                    autocompleteSection.appendChild(autocompleteMaxResultsDiv);

                    // 悬浮提示设置
                    const tooltipSection = $el("div.danbooru-settings-section", { style: { marginBottom: "20px", padding: "16px", border: "1px solid var(--input-border-color)", borderRadius: "8px", backgroundColor: "var(--comfy-input-bg)" } });
                    const tooltipTitle = $el("h3", { textContent: t('tooltipSettings'), style: { margin: "0 0 8px 0", color: "var(--comfy-input-text)", fontSize: "1.1em", fontWeight: "500" } });
                    const tooltipDesc = $el("p", { textContent: t('tooltipEnableDescription'), style: { margin: "0 0 12px 0", color: "#888", fontSize: "0.9em" } });
                    const tooltipEnableCheckbox = $el("input", { type: "checkbox", id: "tooltipEnableCheckbox", checked: initialState.tooltipEnabled ?? uiSettings.tooltip_enabled, style: { width: "16px", height: "16px" } });
                    tooltipEnableCheckbox.onchange = (e) => { /* 用户界面中的临时状态，无需处理 */ };
                    const tooltipEnableLabel = $el("label", { htmlFor: "tooltipEnableCheckbox", textContent: t('tooltipEnable'), style: { cursor: "pointer", color: "var(--comfy-input-text)", fontSize: "1em", fontWeight: "500" } });
                    const tooltipEnableDiv = $el("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, [tooltipEnableCheckbox, tooltipEnableLabel]);
                    tooltipSection.appendChild(tooltipTitle);
                    tooltipSection.appendChild(tooltipDesc);
                    tooltipSection.appendChild(tooltipEnableDiv);

                    // 多选模式设置
                    const selectionModeSection = $el("div.danbooru-settings-section", { style: { marginBottom: "20px", padding: "16px", border: "1px solid var(--input-border-color)", borderRadius: "8px", backgroundColor: "var(--comfy-input-bg)" } });
                    const selectionModeTitle = $el("h3", { textContent: t('selectionModeSettings'), style: { margin: "0 0 8px 0", color: "var(--comfy-input-text)", fontSize: "1.1em", fontWeight: "500" } });
                    const selectionModeDesc = $el("p", { textContent: t('selectionModeDescription'), style: { margin: "0 0 12px 0", color: "#888", fontSize: "0.9em" } });
                    const multiSelectCheckbox = $el("input", { type: "checkbox", id: "multiSelectCheckbox", checked: initialState.multiSelectEnabled ?? uiSettings.multi_select_enabled ?? false, style: { width: "16px", height: "16px" } });
                    multiSelectCheckbox.onchange = (e) => { /* 用户界面中的临时状态，无需处理 */ };
                    const multiSelectLabel = $el("label", { htmlFor: "multiSelectCheckbox", textContent: t('multiSelectEnable'), style: { cursor: "pointer", color: "var(--comfy-input-text)", fontSize: "1em", fontWeight: "500" } });
                    const multiSelectDiv = $el("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, [multiSelectCheckbox, multiSelectLabel]);
                    selectionModeSection.appendChild(selectionModeTitle);
                    selectionModeSection.appendChild(selectionModeDesc);
                    selectionModeSection.appendChild(multiSelectDiv);

                    // 创建侧边栏按钮和内容区域的映射
                    const sections = {
                        'general': { title: t('generalSection'), icon: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path><circle cx="12" cy="12" r="3"></circle></svg>', elements: [languageSection] },
                        'user': { title: t('userSection'), icon: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>', elements: [authSection] },
                        'content': { title: t('contentSection'), icon: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18l-1.5 14H4.5L3 6z"></path><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>', elements: [blacklistSection] },
                        'prompt': { title: t('promptSection'), icon: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon></svg>', elements: [filterSection] },
                        'ui': { title: t('uiSection'), icon: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>', elements: [autocompleteSection, tooltipSection, selectionModeSection] },
                    };

                    const setActiveSection = (key) => {
                        // 更新按钮样式
                        sidebar.querySelectorAll('.sidebar-button').forEach(btn => {
                            if (btn.dataset.key === key) {
                                btn.classList.add('active');
                            } else {
                                btn.classList.remove('active');
                            }
                        });


                        // 显示对应的内容
                        scrollContainer.innerHTML = '';
                        if (sections[key] && sections[key].elements.length > 0) {
                            sections[key].elements.forEach(el => scrollContainer.appendChild(el));
                        }
                    };

                    // 创建侧边栏按钮
                    Object.keys(sections).forEach(key => {
                        const section = sections[key];
                        const button = $el("button.sidebar-button", {
                            dataset: { key: key },
                            onclick: () => setActiveSection(key),
                        });
                        button.appendChild($el("div.sidebar-button-icon", { innerHTML: section.icon }));
                        button.appendChild($el("span.sidebar-button-title", { textContent: section.title }));
                        sidebar.appendChild(button);
                    });

                    // 设置初始活动区域
                    setActiveSection(sections[initialState.section] ? initialState.section : 'general');

                    // 社交按钮
                    const githubButton = $el("button", {
                        innerHTML: `
                            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"></path>
                            </svg>
                            <span style="margin-left: 8px;">GitHub</span>
                        `,
                        title: t('githubTooltip'),
                        style: {
                            padding: "10px 16px",
                            border: "1px solid #24292e",
                            borderRadius: "6px",
                            backgroundColor: "#24292e",
                            color: "white",
                            cursor: "pointer",
                            fontSize: "14px",
                            fontWeight: "500",
                            transition: "all 0.2s ease",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            minWidth: "80px"
                        },
                        onclick: () => {
                            window.open('https://github.com/Aaalice233/ComfyUI-Danbooru-Gallery', '_blank');
                        }
                    });

                    const discordButton = $el("button", {
                        innerHTML: `
                            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.196.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.30z"></path>
                            </svg>
                            <span style="margin-left: 8px;">Discord</span>
                        `,
                        title: t('discordTooltip'),
                        style: {
                            padding: "10px 16px",
                            border: "1px solid #5865F2",
                            borderRadius: "6px",
                            backgroundColor: "#5865F2",
                            color: "white",
                            cursor: "pointer",
                            fontSize: "14px",
                            fontWeight: "500",
                            transition: "all 0.2s ease",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            minWidth: "80px"
                        },
                        onclick: () => {
                            window.open('https://discord.gg/aaalice', '_blank');
                        }
                    });

                    // 按钮区域
                    const buttonContainer = $el("div", {
                        style: {
                            display: "flex",
                            gap: "12px",
                            marginTop: "24px",
                            justifyContent: "space-between",
                            alignItems: "center"
                        }
                    });

                    // 左侧社交按钮容器
                    const socialButtonsContainer = $el("div", {
                        style: {
                            display: "flex",
                            gap: "8px"
                        }
                    });

                    socialButtonsContainer.appendChild(githubButton);
                    socialButtonsContainer.appendChild(discordButton);

                    // 右侧主要按钮容器
                    const mainButtonsContainer = $el("div", {
                        style: {
                            display: "flex",
                            gap: "12px"
                        }
                    });

                    const importExportButtonStyle = {
                        padding: "10px 20px",
                        border: "1px solid var(--input-border-color)",
                        borderRadius: "6px",
                        backgroundColor: "var(--comfy-input-bg)",
                        color: "var(--comfy-input-text)",
                        cursor: "pointer",
                        fontSize: "14px",
                        fontWeight: "500",
                        transition: "all 0.2s ease"
                    };

                    const importButton = $el("button", {
                        textContent: t('importSettings'),
                        style: importExportButtonStyle,
                        onclick: () => importSettings(dialog)
                    });

                    const exportButton = $el("button", {
                        textContent: t('exportSettings'),
                        style: importExportButtonStyle,
                        onclick: () => exportSettings()
                    });

                    const cancelButton = $el("button", {
                        textContent: t('cancel'),
                        style: {
                            padding: "10px 20px",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "6px",
                            backgroundColor: "var(--comfy-input-bg)",
                            color: "var(--comfy-input-text)",
                            cursor: "pointer",
                            fontSize: "14px",
                            fontWeight: "500",
                            transition: "all 0.2s ease"
                        },
                        onclick: () => dialog.unifiedClose()
                    });

                    const saveButton = $el("button", {
                        textContent: t('save'),
                        style: {
                            padding: "10px 20px",
                            border: "2px solid #7B68EE",
                            borderRadius: "6px",
                            backgroundColor: "#7B68EE",
                            color: "white",
                            cursor: "pointer",
                            fontSize: "14px",
                            fontWeight: "600",
                            transition: "all 0.2s ease"
                        },
                        onclick: async () => {
                            const blacklistText = blacklistTextarea.value.trim();
                            const newBlacklist = blacklistText ? blacklistText.split('\n').map(tag => tag.trim()).filter(tag => tag) : [];

                            const filterText = filterTextarea.value.trim();
                            const newFilterTags = filterText ? filterText.split('\n').map(tag => tag.trim()).filter(tag => tag) : [];
                            const newFilterEnabled = filterEnableCheckbox.checked;

                            // 保存用户认证信息
                            const newUsername = usernameInput.value.trim();
                            const newApiKey = apiKeyInput.value.trim();
                            let authSuccess = true;
                            if (newUsername !== userAuth.username || newApiKey !== userAuth.api_key) {
                                const authResult = await saveUserAuth(newUsername, newApiKey, true);
                                authSuccess = authResult.success;
                                if (authSuccess) {
                                    await loadFavorites(); // 登录成功后重新加载收藏夹
                                } else {
                                    showToast(authResult.error || "保存 Danbooru 认证信息失败", 'error');
                                    return;
                                }
                            }

                            const newCookieValue = cookieInput.value.trim();
                            const newCookieEnabled = cookieEnableCheckbox.checked;
                            let danbooruCookieSuccess = true;
                            if (newCookieValue !== danbooruCookie.cookie || newCookieEnabled !== danbooruCookie.enabled) {
                                const cookieResult = await saveDanbooruCookie(newCookieValue, newCookieEnabled, true);
                                danbooruCookieSuccess = cookieResult.success;
                                if (!danbooruCookieSuccess) {
                                    showToast(cookieResult.error || "保存 Danbooru Cookie 设置失败", 'error');
                                    return;
                                }
                            }

                            const newBrowserHeadersValue = browserHeadersInput.value.trim();
                            const newBrowserHeadersEnabled = browserHeadersEnableCheckbox.checked;
                            let danbooruBrowserHeadersSuccess = true;
                            if (newBrowserHeadersValue !== danbooruBrowserHeaders.headers || newBrowserHeadersEnabled !== danbooruBrowserHeaders.enabled) {
                                const browserHeadersResult = await saveDanbooruBrowserHeaders(newBrowserHeadersValue, newBrowserHeadersEnabled, true);
                                danbooruBrowserHeadersSuccess = browserHeadersResult.success;
                                if (!danbooruBrowserHeadersSuccess) {
                                    showToast(browserHeadersResult.error || "保存 Danbooru 浏览器请求头失败", 'error');
                                    return;
                                }
                            }

                            const newGelbooruUserId = gelbooruUserIdInput.value.trim();
                            const newGelbooruApiKey = gelbooruApiKeyInput.value.trim();
                            let gelbooruAuthSuccess = true;
                            if (newGelbooruUserId !== gelbooruAuth.user_id || newGelbooruApiKey !== gelbooruAuth.api_key) {
                                const gelbooruResult = await saveGelbooruAuth(newGelbooruUserId, newGelbooruApiKey, true);
                                gelbooruAuthSuccess = gelbooruResult.success;
                                if (!gelbooruAuthSuccess) {
                                    showToast(gelbooruResult.error || "保存 Gelbooru 认证信息失败", 'error');
                                    return;
                                }
                            }

                            const newCivitaiApiKey = civitaiApiKeyInput.value.trim();
                            let civitaiAuthSuccess = true;
                            if (newCivitaiApiKey !== civitaiAuth.api_key) {
                                const civitaiResult = await saveCivitaiAuth(newCivitaiApiKey, true);
                                civitaiAuthSuccess = civitaiResult.success;
                                if (!civitaiAuthSuccess) {
                                    showToast(civitaiResult.error || "保存 Civitai API Key 失败", 'error');
                                    return;
                                }
                            }

                            const newCivitaiCollectionHeaders = civitaiCollectionHeadersInput.value.trim();
                            const newCivitaiSearchHeaders = civitaiSearchHeadersInput.value.trim();
                            const newCivitaiRemoteEnabled = civitaiRemoteEnableCheckbox.checked;
                            const newCivitaiRemoteCollectionId = civitaiRemoteCollectionIdInput.value.trim();
                            let civitaiRemoteSuccess = true;
                            if (newCivitaiCollectionHeaders !== civitaiRemoteFavorites.collection_headers || newCivitaiSearchHeaders !== civitaiRemoteFavorites.search_headers || newCivitaiRemoteEnabled !== civitaiRemoteFavorites.enabled || newCivitaiRemoteCollectionId !== civitaiRemoteFavorites.default_collection_id) {
                                const remoteResult = await saveCivitaiRemoteFavorites(newCivitaiCollectionHeaders, newCivitaiSearchHeaders, newCivitaiRemoteEnabled, newCivitaiRemoteCollectionId, true);
                                civitaiRemoteSuccess = remoteResult.success;
                                if (!civitaiRemoteSuccess) {
                                    showToast(remoteResult.error || "保存 Civitai 远端收藏设置失败", 'error');
                                    return;
                                }
                                await loadCivitaiRemoteFavorites();
                                populateCivitaiRemoteCollections(newCivitaiRemoteCollectionId);
                                updateFavoritesButtonState();
                            }

                            const newAutocompleteEnabled = autocompleteEnableCheckbox.checked;
                            const newTooltipEnabled = tooltipEnableCheckbox.checked;
                            const newAutocompleteMaxResults = parseInt(autocompleteMaxResultsInput.value, 10);
                            const newSelectedCategories = Array.from(categoryDropdown.querySelectorAll("input:checked")).map(i => i.name);
                            const newMultiSelectEnabled = multiSelectCheckbox.checked;

                            // 保存所有设置
                            const [blacklistSuccess, filterSuccess, uiSettingsSuccess] = await Promise.all([
                                saveBlacklist(newBlacklist),
                                saveFilterTags(newFilterTags, newFilterEnabled),
                                saveUiSettings({
                                    autocomplete_enabled: newAutocompleteEnabled,
                                    tooltip_enabled: newTooltipEnabled,
                                    autocomplete_max_results: newAutocompleteMaxResults,
                                    selected_categories: newSelectedCategories,
                                    multi_select_enabled: newMultiSelectEnabled,
                                    formatting: {
                                        escapeBrackets: formattingDropdown.querySelector('[name="escapeBrackets"]')?.checked ?? true,
                                        replaceUnderscores: formattingDropdown.querySelector('[name="replaceUnderscores"]')?.checked ?? true
                                    }
                                })
                            ]);

                            if (blacklistSuccess && filterSuccess && authSuccess && danbooruCookieSuccess && danbooruBrowserHeadersSuccess && gelbooruAuthSuccess && civitaiAuthSuccess && civitaiRemoteSuccess && uiSettingsSuccess) {
                                // 同步本地状态
                                currentBlacklist = newBlacklist;
                                currentFilterTags = newFilterTags;
                                filterEnabled = newFilterEnabled;
                                uiSettings.autocomplete_enabled = newAutocompleteEnabled;
                                uiSettings.tooltip_enabled = newTooltipEnabled;
                                uiSettings.autocomplete_max_results = newAutocompleteMaxResults;
                                uiSettings.selected_categories = newSelectedCategories;
                                uiSettings.multi_select_enabled = newMultiSelectEnabled;
                                await Promise.all([loadUserAuth(), loadDanbooruCookie(), loadDanbooruBrowserHeaders(), loadGelbooruAuth(), loadCivitaiAuth(), loadCivitaiRemoteFavorites()]);

                                dialog.unifiedClose();
                                showToast(t('saveSuccess'), 'success');

                                // 重新过滤当前已加载的帖子
                                const filteredPosts = posts.filter(post => !isPostFiltered(post));
                                imageGrid.innerHTML = "";
                                filteredPosts.forEach(renderPost);

                                // 如果过滤后帖子太少，自动加载更多
                                if (filteredPosts.length < 20) {
                                    fetchAndRender(false);
                                }
                            } else {
                                showToast(t('saveFailed'), 'error');
                            }
                        }
                    });

                    mainButtonsContainer.appendChild(importButton);
                    mainButtonsContainer.appendChild(exportButton);
                    mainButtonsContainer.appendChild(cancelButton);
                    mainButtonsContainer.appendChild(saveButton);

                    buttonContainer.appendChild(socialButtonsContainer);
                    buttonContainer.appendChild(mainButtonsContainer);

                    dialogContent.appendChild(title);
                    mainContainer.appendChild(sidebar);
                    mainContainer.appendChild(scrollContainer);
                    dialogContent.appendChild(mainContainer);
                    dialogContent.appendChild(buttonContainer);

                    dialog.appendChild(dialogContent);
                    dialog.dataset.source = initialState.source || currentSource;

                    document.body.appendChild(dialog);
                    mountGalleryDialog(dialog, { dialogs: galleryDialogs });
                    if (initialState.section === 'user') {
                        const sourceInput = {danbooru:usernameInput,gelbooru:gelbooruUserIdInput,civitai:civitaiApiKeyInput}[initialState.source || currentSource];
                        sourceInput?.focus({preventScroll:true});
                        sourceInput?.scrollIntoView({block:'center'});
                    }

                    // Add event listeners after all elements are defined
                    dialog.querySelectorAll('.danbooru-language-select-button').forEach(button => {
                        button.onclick = async () => {
                            const lang = button.dataset.lang;
                            if (globalMultiLanguageManager.getLanguage() === lang) return;

                            // Preserve state
                            const currentState = {
                                blacklist: blacklistTextarea.value,
                                filterTags: filterTextarea.value,
                                filterEnabled: filterEnableCheckbox.checked,
                                username: usernameInput.value,
                                apiKey: apiKeyInput.value,
                                danbooruCookieEnabled: cookieEnableCheckbox.checked,
                                danbooruCookieValue: cookieInput.value,
                                gelbooruUserId: gelbooruUserIdInput.value,
                                gelbooruApiKey: gelbooruApiKeyInput.value,
                                civitaiApiKey: civitaiApiKeyInput.value,
                                __preserveInputs: true,
                                autocompleteEnabled: autocompleteEnableCheckbox.checked,
                                tooltipEnabled: tooltipEnableCheckbox.checked,
                                autocompleteMaxResults: autocompleteMaxResultsInput.value,
                            };

                            const success = await saveLanguage(lang);
                            if (success) {
                                globalMultiLanguageManager.setLanguage(lang);
                                updateInterfaceTexts(); // Update main UI
                                dialog.unifiedClose(); // Close current dialog
                                showSettingsDialog(currentState); // Re-open with new language and preserved state
                            } else {
                                showToast('Failed to save language setting.', 'error');
                            }
                        };
                    });
                };

                const showTagCatalogDialog = async () => {
                    const dialog = $el("div.danbooru-tag-catalog-dialog", {
                        "data-testid": "tag-catalog-dialog",
                        style: {
                            position: "fixed",
                            inset: "0",
                            backgroundColor: "rgba(0, 0, 0, 0.72)",
                            zIndex: "10020",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            padding: "20px"
                        }
                    });
                    const content = $el("section.danbooru-tag-catalog-content", {
                        style: {
                            width: "min(1040px, 94vw)",
                            height: "min(760px, 90vh)",
                            backgroundColor: "var(--comfy-menu-bg)",
                            color: "var(--comfy-input-text)",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "12px",
                            boxShadow: "0 12px 42px rgba(0,0,0,.45)",
                            display: "flex",
                            flexDirection: "column",
                            overflow: "hidden"
                        }
                    });
                    const closeButton = $el("button", {
                        type: "button",
                        textContent: "关闭",
                        title: "关闭 WeiLin 分类词库",
                        style: { padding: "6px 12px", cursor: "pointer" }
                    });
                    const heading = $el("div", {
                        style: {
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: "16px",
                            padding: "16px 18px",
                            borderBottom: "1px solid var(--input-border-color)"
                        }
                    }, [
                        $el("div", {}, [
                            $el("h2", { textContent: "Gallery × WeiLin 分类词库", style: { margin: "0 0 4px", fontSize: "18px" } }),
                            $el("div", {
                                textContent: "短 tag 可加入站点筛选；长提示词逐字保留，只复制、不发送给 Booru API。",
                                style: { opacity: ".78", fontSize: "12px" }
                            })
                        ]),
                        closeButton
                    ]);

                    const queryInput = $el("input", {
                        type: "search",
                        placeholder: "搜索英文 tag、中文说明或长提示词…",
                        "data-testid": "tag-catalog-search",
                        style: { minWidth: "220px", flex: "1", padding: "8px 10px" }
                    });
                    const groupSelect = $el("select", {
                        title: "WeiLin 一级分类",
                        "data-testid": "tag-catalog-group",
                        style: { minWidth: "130px", padding: "8px" }
                    });
                    const subgroupSelect = $el("select", {
                        title: "WeiLin 子分类",
                        "data-testid": "tag-catalog-subgroup",
                        style: { minWidth: "150px", padding: "8px" }
                    });
                    const kindSelect = $el("select", {
                        title: "条目类型",
                        "data-testid": "tag-catalog-kind",
                        style: { minWidth: "120px", padding: "8px" }
                    }, [
                        $el("option", { value: "all", textContent: "全部类型" }),
                        $el("option", { value: "atomic_tag", textContent: "短 tag" }),
                        $el("option", { value: "prompt_phrase", textContent: "完整长提示词" })
                    ]);
                    const searchButton = $el("button", {
                        type: "button",
                        textContent: "搜索",
                        style: { padding: "8px 14px", cursor: "pointer" }
                    });
                    const controls = $el("div", {
                        style: {
                            display: "flex",
                            gap: "8px",
                            flexWrap: "wrap",
                            padding: "12px 18px",
                            borderBottom: "1px solid var(--input-border-color)"
                        }
                    }, [queryInput, groupSelect, subgroupSelect, kindSelect, searchButton]);
                    const status = $el("div", {
                        "data-testid": "tag-catalog-status",
                        style: { padding: "8px 18px", fontSize: "12px", opacity: ".8" }
                    });
                    const results = $el("div", {
                        "data-testid": "tag-catalog-results",
                        style: {
                            flex: "1",
                            overflowY: "auto",
                            padding: "0 18px 16px",
                            display: "grid",
                            alignContent: "start",
                            gap: "10px"
                        }
                    });
                    const previousButton = $el("button", { type: "button", textContent: "上一页", style: { padding: "7px 14px", cursor: "pointer" } });
                    const pageLabel = $el("span", { textContent: "第 1 页", style: { minWidth: "72px", textAlign: "center" } });
                    const nextButton = $el("button", { type: "button", textContent: "下一页", style: { padding: "7px 14px", cursor: "pointer" } });
                    const pager = $el("div", {
                        style: {
                            display: "flex",
                            justifyContent: "center",
                            alignItems: "center",
                            gap: "10px",
                            padding: "12px",
                            borderTop: "1px solid var(--input-border-color)"
                        }
                    }, [previousButton, pageLabel, nextButton]);
                    content.append(heading, controls, status, results, pager);
                    dialog.appendChild(content);
                    document.body.appendChild(dialog);

                    const requestController = new AbortController();
                    let groups = [];
                    let page = 1;
                    let hasMore = false;
                    let currentCursor = null;
                    let nextCursor = null;
                    let cursorHistory = [null];
                    let closed = false;
                    let searchSequence = 0;
                    const resetCatalogPaging = () => {
                        page = 1;
                        hasMore = false;
                        currentCursor = null;
                        nextCursor = null;
                        cursorHistory = [null];
                    };
                    mountGalleryDialog(dialog, {
                        dialogs: galleryDialogs,
                        initialFocus: queryInput,
                        onClose: () => { closed = true; requestController.abort(); }
                    });
                    const closeDialog = () => dialog.unifiedClose();
                    closeButton.addEventListener("click", closeDialog);

                    const replaceOptions = (select, options) => {
                        select.replaceChildren(...options.map(({ value, label }) => $el("option", { value, textContent: label })));
                    };
                    const populateSubgroups = () => {
                        const selected = groups.find((entry) => String(entry.id) === groupSelect.value);
                        const options = [{ value: "", label: "全部子分类" }];
                        for (const subgroup of selected?.subgroups || []) {
                            options.push({ value: String(subgroup.id), label: `${subgroup.name} (${subgroup.item_count})` });
                        }
                        replaceOptions(subgroupSelect, options);
                    };
                    const copyExactText = async (text) => {
                        try {
                            await navigator.clipboard.writeText(String(text ?? ""));
                            showToast("已复制完整原文，未拆分、未截断", "success");
                        } catch (error) {
                            logger.error("复制 WeiLin 提示词失败:", error);
                            showToast("复制失败，请检查剪贴板权限", "error");
                        }
                    };
                    const addGalleryTag = (tag) => {
                        const canonical = String(tag || "").trim();
                        if (!canonical) return;
                        const tokens = searchInput.value.trim().split(/\s+/).filter(Boolean);
                        if (!tokens.includes(canonical)) tokens.push(canonical);
                        searchInput.value = tokens.join(" ");
                        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
                        syncV53DraftFromControls({ mode: "search" });
                        showToast(`已加入站点筛选：${canonical}`, "success");
                        closeDialog();
                        searchInput.focus();
                    };
                    const renderItem = (item) => {
                        const label = item.kind === "prompt_phrase" ? "完整长提示词" : "短 tag";
                        const badge = $el("span", {
                            textContent: label,
                            style: {
                                padding: "2px 7px",
                                borderRadius: "999px",
                                fontSize: "11px",
                                backgroundColor: item.kind === "prompt_phrase" ? "#6d4c9b" : "#236b55",
                                color: "white"
                            }
                        });
                        const meta = $el("div", {
                            style: { display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap", fontSize: "12px", opacity: ".82" }
                        }, [
                            badge,
                            $el("span", { textContent: `${item.group?.name || "未分类"} / ${item.subgroup?.name || "未分类"}` }),
                            item.gallery_translation ? $el("span", { textContent: `Gallery：${item.gallery_translation}` }) : null
                        ].filter(Boolean));
                        const rawText = $el("div", {
                            textContent: item.raw_text || "",
                            title: "WeiLin 原始文本",
                            style: {
                                whiteSpace: "pre-wrap",
                                overflowWrap: "anywhere",
                                maxHeight: "170px",
                                overflowY: "auto",
                                padding: "8px",
                                borderRadius: "6px",
                                backgroundColor: "var(--comfy-input-bg)",
                                fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
                                fontSize: "12px"
                            }
                        });
                        const description = $el("div", {
                            textContent: item.raw_desc || "",
                            style: { fontSize: "12px", opacity: ".86", overflowWrap: "anywhere" }
                        });
                        const actions = $el("div", { style: { display: "flex", gap: "8px", justifyContent: "flex-end" } });
                        actions.appendChild($el("button", {
                            type: "button",
                            textContent: "复制完整原文",
                            onclick: () => copyExactText(item.copy_text ?? item.raw_text),
                            style: { padding: "6px 10px", cursor: "pointer" }
                        }));
                        if (item.t_uuid) actions.appendChild($el("button", {
                            type: "button", textContent: "编辑共享 Tag",
                            onclick: async () => {
                                const previousDisplay = dialog.style.display;
                                dialog.style.display = "none";
                                try {
                                    const {openTagManager} = await import('/extensions/ComfyUI-Unified-Prompt-Workbench/tag_manager.js');
                                    await openTagManager({editTagId:item.t_uuid,onClose:async () => {
                                        if (!closed) { dialog.style.display = previousDisplay; resetCatalogPaging(); await loadCategories(); dialog.unifiedFocus(); }
                                    }});
                                } catch (error) { dialog.style.display = previousDisplay; status.textContent = error.message; dialog.unifiedFocus(); }
                            }, style: {padding:"6px 10px",cursor:"pointer"}
                        }));
                        if (item.site_filterable && item.gallery_tag) {
                            actions.appendChild($el("button", {
                                type: "button",
                                textContent: "加入画廊筛选",
                                "data-testid": "tag-catalog-apply-tag",
                                onclick: () => addGalleryTag(item.gallery_tag),
                                style: { padding: "6px 10px", cursor: "pointer", backgroundColor: "#236b55", color: "white" }
                            }));
                        }
                        return $el("article.danbooru-tag-catalog-item", {
                            style: {
                                display: "grid",
                                gap: "7px",
                                padding: "12px",
                                border: "1px solid var(--input-border-color)",
                                borderRadius: "8px"
                            }
                        }, [meta, description, rawText, actions]);
                    };
                    const loadResults = async () => {
                        const thisSearch = ++searchSequence;
                        status.textContent = "正在读取 WeiLin 只读词库…";
                        results.replaceChildren();
                        searchButton.disabled = true;
                        previousButton.disabled = true;
                        nextButton.disabled = true;
                        const params = new URLSearchParams({
                            query: queryInput.value.trim(),
                            kind: kindSelect.value,
                            page: String(page),
                            limit: "30"
                        });
                        if (currentCursor) params.set("cursor", currentCursor);
                        if (groupSelect.value) params.set("group_id", groupSelect.value);
                        if (subgroupSelect.value) params.set("subgroup_id", subgroupSelect.value);
                        try {
                            const response = await fetch(`/danbooru_gallery/tag_catalog/search?${params}`, { signal: requestController.signal });
                            const data = await response.json();
                            if (!response.ok || !data.success) throw new Error(data.error || "词库搜索失败");
                            if (closed || thisSearch !== searchSequence) return;
                            hasMore = !!data.has_more;
                            nextCursor = typeof data.next_cursor === "string" && data.next_cursor
                                ? data.next_cursor
                                : null;
                            if (hasMore && !nextCursor) throw new Error("词库分页游标缺失");
                            for (const item of data.items || []) results.appendChild(renderItem(item));
                            if (!data.items?.length) {
                                results.appendChild($el("div", { textContent: "没有匹配项。画师条目会按策略自动排除。", style: { padding: "24px", textAlign: "center", opacity: ".7" } }));
                            }
                            status.textContent = `WeiLin · 第 ${data.page} 页 · ${data.items?.length || 0} 项；长提示词保持原文。`;
                            pageLabel.textContent = `第 ${data.page} 页`;
                            previousButton.disabled = page <= 1;
                            nextButton.disabled = !hasMore;
                        } catch (error) {
                            if (error?.name === "AbortError") return;
                            if (thisSearch !== searchSequence) return;
                            status.textContent = `词库读取失败：${error.message || error}`;
                            results.appendChild($el("div", { textContent: "请确认 WeiLin 插件及其 user_data 数据库仍在。", style: { padding: "24px", textAlign: "center" } }));
                        } finally {
                            if (!closed && thisSearch === searchSequence) searchButton.disabled = false;
                        }
                    };

                    searchButton.addEventListener("click", () => { resetCatalogPaging(); loadResults(); });
                    queryInput.addEventListener("keydown", (event) => {
                        if (event.isComposing || event.keyCode === 229) return;
                        if (event.key === "Enter") { event.preventDefault(); resetCatalogPaging(); loadResults(); }
                    });
                    groupSelect.addEventListener("change", () => { populateSubgroups(); resetCatalogPaging(); loadResults(); });
                    subgroupSelect.addEventListener("change", () => { resetCatalogPaging(); loadResults(); });
                    kindSelect.addEventListener("change", () => { resetCatalogPaging(); loadResults(); });
                    previousButton.addEventListener("click", () => {
                        if (page <= 1) return;
                        page -= 1;
                        currentCursor = cursorHistory[page - 1] || null;
                        loadResults();
                    });
                    nextButton.addEventListener("click", () => {
                        if (!hasMore || !nextCursor) return;
                        cursorHistory[page] = nextCursor;
                        currentCursor = nextCursor;
                        page += 1;
                        loadResults();
                    });

                    const loadCategories = async () => { try {
                        const response = await fetch("/danbooru_gallery/tag_catalog/categories", { signal: requestController.signal });
                        const data = await response.json();
                        if (!response.ok || !data.success || !data.available) throw new Error(data.error || "WeiLin 词库不可用");
                        groups = Array.isArray(data.groups) ? data.groups : [];
                        replaceOptions(groupSelect, [
                            { value: "", label: "全部一级分类" },
                            ...groups.map((group) => ({ value: String(group.id), label: `${group.name} (${group.item_count})` }))
                        ]);
                        populateSubgroups();
                        await loadResults();
                        queryInput.focus();
                    } catch (error) {
                        if (error?.name === "AbortError") return;
                        status.textContent = `WeiLin 词库不可用：${error.message || error}`;
                        results.appendChild($el("div", {
                            textContent: "分类入口保持隔离，不会回退到未核验的批量导入。",
                            style: { padding: "24px", textAlign: "center" }
                        }));
                        searchButton.disabled = true;
                    }};
                    await loadCategories();
                };

                const tagCatalogButton = $el("button.danbooru-tag-catalog-button", {
                    type: "button",
                    textContent: "词库",
                    title: "浏览 Gallery × WeiLin 分类词库（长提示词原样保留）",
                    "data-testid": "gallery-tag-catalog-button",
                    onclick: () => showTagCatalogDialog(),
                    style: { padding: "5px 10px", cursor: "pointer", whiteSpace: "nowrap" }
                });

                // 创建设置按钮
                const settingsButton = $el("button.danbooru-settings-button", {
                    innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon">
                        <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path>
                        <circle cx="12" cy="12" r="3"></circle>
                    </svg>`,
                    title: t('settings'),
                    onclick: async () => {
                        settingsButton.disabled = true;
                        try {
                            await showSettingsDialog();
                        } finally {
                            settingsButton.disabled = false;
                        }
                    }
                });
                sourceSelect.setAttribute("data-testid", "gallery-source");

                // 创建筛选按钮
                const filterButton = $el("button.danbooru-filter-button", {
                    innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon">
                        <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
                    </svg>`,
                    title: t('filterTooltip'),
                    onclick: () => {
                        showFilterDialog();
                    }
                });

                const refreshButton = $el("button.danbooru-refresh-button", {
                    title: t('refreshTooltip')
                });
                refreshButton.innerHTML = `
                   <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon">
                       <polyline points="23 4 23 10 17 10"></polyline>
                       <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                   </svg>`;


                danbooruDiagnoseButton = $el("button.danbooru-diagnose-button", {
                    textContent: "D诊断",
                    title: "D站后端诊断：区分 Cloudflare / API Key / 代理 / 图片CDN",
                    onclick: () => runDanbooruDiagnostic()
                });

                civitaiDiagnoseButton = $el("button.civitai-diagnose-button", {
                    textContent: "C诊断",
                    title: "C站诊断：显示 Civitai.red/com API、Tags/Models/Images 检索计划和返回数量",
                    onclick: () => runCivitaiDiagnostic()
                });

                danbooruBrowserDiagnoseButton = $el("button.danbooru-browser-diagnose-button", {
                    textContent: "D浏览器诊断",
                    title: "D站浏览器侧 fetch 诊断：不经过 Python 后端/插件代理",
                    onclick: () => runDanbooruBrowserDiagnostic()
                });

                danbooruExportLogsButton = $el("button.danbooru-export-logs-button", {
                    textContent: "导出日志",
                    title: "导出插件后端日志，并附带最近一次 D站后端诊断和 D浏览器诊断；敏感字段会脱敏",
                    onclick: () => exportFullPluginLogs()
                });

                const diagnosticsMenuButton = document.createElement('select');
                diagnosticsMenuButton.className = 'danbooru-diagnostics-menu';
                diagnosticsMenuButton.title = '诊断 / 导出';
                diagnosticsMenuButton.style.padding = '5px 8px';
                diagnosticsMenuButton.style.borderRadius = '4px';
                diagnosticsMenuButton.style.backgroundColor = 'var(--comfy-input-bg)';
                diagnosticsMenuButton.style.color = 'var(--comfy-input-text)';
                diagnosticsMenuButton.style.border = '1px solid var(--input-border-color)';
                diagnosticsMenuButton.style.cursor = 'pointer';
                diagnosticsMenuButton.style.fontSize = '12px';
                const diagDefaultOpt = document.createElement('option');
                diagDefaultOpt.value = '';
                diagDefaultOpt.textContent = '诊断/导出';
                const diagDOpt = document.createElement('option');
                diagDOpt.value = 'danbooru';
                diagDOpt.textContent = 'D站后端诊断';
                const diagCOpt = document.createElement('option');
                diagCOpt.value = 'civitai';
                diagCOpt.textContent = 'C站诊断';
                const diagBrowserOpt = document.createElement('option');
                diagBrowserOpt.value = 'browser';
                diagBrowserOpt.textContent = 'D浏览器诊断';
                const diagCFavOpt = document.createElement('option');
                diagCFavOpt.value = 'civitai_favorites';
                diagCFavOpt.textContent = 'C收藏/缩略图诊断';
                                const diagRenderExportOpt = document.createElement('option');
                diagRenderExportOpt.value = 'frontend_render_export';
                diagRenderExportOpt.textContent = '导出当前页渲染诊断';
const diagCFavExportOpt = document.createElement('option');
                diagCFavExportOpt.value = 'civitai_favorites_export';
                diagCFavExportOpt.textContent = '导出C收藏诊断';
                const diagExportOpt = document.createElement('option');
                diagExportOpt.value = 'export';
                diagExportOpt.textContent = '导出完整日志';
                diagnosticsMenuButton.append(diagDefaultOpt, diagDOpt, diagCOpt, diagCFavOpt, diagCFavExportOpt, diagRenderExportOpt, diagBrowserOpt, diagExportOpt);
                diagnosticsMenuButton.addEventListener('change', async () => {
                    const action = diagnosticsMenuButton.value;
                    diagnosticsMenuButton.value = '';
                    if (!action) return;
                    if (action === 'danbooru') return runDanbooruDiagnostic();
                    if (action === 'civitai') return runCivitaiDiagnostic();
                    if (action === 'civitai_favorites') return runCivitaiFavoritesDiagnostic(false);
                    if (action === 'civitai_favorites_export') return runCivitaiFavoritesDiagnostic(true);
                    if (action === 'frontend_render_export') return exportDiagnosticReport(JSON.stringify(collectCurrentPageRenderDiagnostics(), null, 2), 'frontend_render');
                    if (action === 'browser') return runDanbooruBrowserDiagnostic();
                    if (action === 'export') return exportFullPluginLogs();
                });

                imageGrid = $el("div.danbooru-image-grid", {
                    id: `${v53InstanceId}-grid`,
                    role: "feed",
                    "aria-label": "画廊结果",
                    "aria-busy": "false",
                    "data-testid": "gallery-grid",
                    tabIndex: 0,
                });
                imageGrid.setAttribute("data-testid", "gallery-grid");

                // 创建筛选对话框
                const showFilterDialog = () => {
                    const dialog = $el("div.danbooru-settings-dialog", {
                        style: {
                            position: "absolute",
                            top: "0",
                            left: "0",
                            width: "100%",
                            height: "100%",
                            backgroundColor: "rgba(0, 0, 0, 0.7)",
                            zIndex: "1000",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center"
                        },
                    });

                    const content = $el("div.danbooru-settings-dialog-content", {
                        style: {
                            width: "420px",
                            padding: "20px",
                            backgroundColor: "var(--comfy-menu-bg)",
                            border: "1px solid var(--input-border-color)",
                            borderRadius: "12px",
                            boxShadow: "0 8px 32px rgba(0, 0, 0, 0.3)",
                            display: "flex",
                            flexDirection: "column",
                            gap: "20px",
                            position: "relative", // 确保内容在对话框内
                            zIndex: "1001", // 确保内容在背景之上
                        }
                    });

                    const title = $el("h2", {
                        textContent: t('filter'),
                        style: {
                            margin: "0",
                            color: "var(--comfy-input-text)",
                            fontSize: "1.3em",
                            borderBottom: "1px solid var(--input-border-color)",
                            paddingBottom: "15px"
                        }
                    });

                    const body = $el("div", { style: { display: "flex", flexDirection: "column", gap: "20px" } });

                    // 筛选类型选择
                    const filterType = filterState.startPage ? 'page' : 'time';

                    const createRadio = (name, value, label, checked) => {
                        const radioId = `filter-type-${value}`;
                        const radio = $el("input", { type: "radio", name, value, id: radioId, checked, style: { accentColor: '#7B68EE' } });
                        const indicator = $el("span.danbooru-radio-indicator", { hidden: true });
                        const radioLabel = $el("label.danbooru-radio-label", {
                            htmlFor: radioId,
                            className: checked ? 'checked' : ''
                        }, [
                            indicator,
                            $el("span", { textContent: label, style: { zIndex: '1', position: 'relative' } })
                        ]);

                        // Set initial styles for checked state
                        // The container now IS the label, which contains the hidden radio button.
                        const container = $el("div.danbooru-radio-button-wrapper", {}, [radio, radioLabel]);

                        return container;
                    };

                    const timeRadio = createRadio("filter-type", "time", t('filterByTime'), filterType === 'time');
                    const pageRadio = createRadio("filter-type", "page", t('filterByPage'), filterType === 'page');

                    const radioGroup = $el("div", {
                        className: "danbooru-radio-group",
                        style: {
                            display: "flex",
                            justifyContent: "center",
                            alignItems: "center",
                            gap: "20px",
                            margin: "10px 0"
                        }
                    }, [timeRadio, pageRadio]);


                    // 时间范围筛选
                    const timeSection = $el("div.danbooru-settings-section");
                    const createInputRow = (label, input) => {
                        const row = $el("div.danbooru-input-row", {}, [
                            $el("label", { textContent: label, style: { color: "#ccc", fontSize: "0.9em", userSelect: "none" } }),
                            input
                        ]);
                        // Make the whole row clickable to open the date/time picker
                        row.addEventListener('click', () => {
                            try {
                                input.showPicker();
                            } catch (e) {
                                logger.warn("input.showPicker() is not supported on this browser.", e);
                            }
                        });
                        return row;
                    };

                    const startTimeInput = $el("input", { type: "datetime-local", id: "startTime", value: filterState.startTime || '' });
                    const endTimeInput = $el("input", { type: "datetime-local", id: "endTime", value: filterState.endTime || '' });

                    timeSection.append(
                        $el("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } }, [
                            createInputRow(t('startTime'), startTimeInput),
                            createInputRow(t('endTime'), endTimeInput)
                        ])
                    );

                    // 起始页码筛选
                    const pageSection = $el("div.danbooru-settings-section");
                    const startPageInput = $el("input", { type: "number", id: "startPage", min: "1", placeholder: "1", value: filterState.startPage || '' });
                    pageSection.append(
                        createInputRow(t('startPage'), startPageInput)
                    );

                    body.append(radioGroup, timeSection, pageSection);

                    const toggleSections = (type) => {
                        if (type === 'time') {
                            timeSection.style.display = 'block';
                            pageSection.style.display = 'none';
                        } else {
                            timeSection.style.display = 'none';
                            pageSection.style.display = 'block';
                        }
                    };

                    toggleSections(filterType);

                    radioGroup.addEventListener('change', (e) => {
                        if (e.target.name === 'filter-type') {

                            // New robust logic: Iterate through radios and update their labels
                            radioGroup.querySelectorAll('input[type="radio"]').forEach(radio => {
                                const label = radioGroup.querySelector(`label[for="${radio.id}"]`);
                                if (label) {
                                    const indicator = label.querySelector('.danbooru-radio-indicator');

                                    if (radio.checked) {
                                        label.classList.add('checked');
                                        // FORCE INLINE STYLES FOR DEBUGGING
                                        label.style.setProperty('border-color', '#7B68EE', 'important');
                                        if (indicator) {
                                            indicator.style.setProperty('background-color', '#7B68EE', 'important');
                                            indicator.style.setProperty('border-color', '#7B68EE', 'important');
                                        }
                                    } else {
                                        label.classList.remove('checked');
                                        // CLEAR INLINE STYLES
                                        label.style.borderColor = '';
                                        if (indicator) {
                                            indicator.style.backgroundColor = '';
                                            indicator.style.borderColor = '';
                                        }
                                    }

                                    // Use a timeout to allow the browser to apply styles before we log them
                                    setTimeout(() => {
                                        if (indicator) {
                                        }
                                    }, 0);

                                } else {
                                }
                            });

                            const selectedValue = e.target.value;
                            toggleSections(selectedValue);
                        }
                    });

                    // 按钮
                    const footer = $el("div", { style: { display: "flex", justifyContent: "flex-end", gap: "12px", paddingTop: "15px", borderTop: "1px solid var(--input-border-color)" } });

                    const cancelButton = $el("button.danbooru-dialog-button--secondary", {
                        textContent: t('cancel'),
                        onclick: () => dialog.unifiedClose()
                    });

                    const resetButton = $el("button.danbooru-dialog-button--secondary", {
                        textContent: t('reset'),
                        onclick: () => {
                            filterState = { startTime: null, endTime: null, startPage: null };
                            filterWidget.value = JSON.stringify(filterState);
                            filterButton.classList.remove('active');
                            dialog.unifiedClose();
                            fetchAndRender(true);
                        }
                    });
                    const applyButton = $el("button.danbooru-dialog-button--primary", {
                        textContent: t('apply'),
                        onclick: () => {
                            const selectedType = radioGroup.querySelector('input[name="filter-type"]:checked').value;

                            if (selectedType === 'time') {
                                const startTime = startTimeInput.value;
                                const endTime = endTimeInput.value;
                                if (startTime && endTime && new Date(startTime) > new Date(endTime)) {
                                    showError("结束时间不能早于开始时间。");
                                    return;
                                }
                                filterState.startTime = startTime || null;
                                filterState.endTime = endTime || null;
                                filterState.startPage = null;
                            } else { // page
                                const startPage = parseInt(startPageInput.value, 10);
                                if (startPageInput.value && (isNaN(startPage) || startPage < 1)) {
                                    showError("起始页码必须是大于0的整数。");
                                    return;
                                }
                                filterState.startTime = null;
                                filterState.endTime = null;
                                filterState.startPage = isNaN(startPage) ? null : startPage;
                            }
                            filterWidget.value = JSON.stringify(filterState);

                            if (filterState.startTime || filterState.endTime || filterState.startPage) {
                                filterButton.classList.add('active');
                            } else {
                                filterButton.classList.remove('active');
                            }

                            dialog.unifiedClose();
                            fetchAndRender(true);
                        }
                    });
                    footer.append(cancelButton, resetButton, applyButton);

                    content.append(title, body, footer);
                    dialog.append(content);
                    container.appendChild(dialog);
                    mountGalleryDialog(dialog, { dialogs: galleryDialogs });

                    // Manually trigger change event to set initial visual state
                    const initialCheckedRadio = radioGroup.querySelector('input[type="radio"]:checked');
                    if (initialCheckedRadio) {
                        initialCheckedRadio.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                };

                // 黑名单功能
                let currentBlacklist = [];

                // 提示词过滤功能
                let currentFilterTags = [];
                let filterEnabled = true; // 默认开启过滤功能
                let uiSettings = {
                    autocomplete_enabled: true,
                    tooltip_enabled: true,
                    autocomplete_max_results: 20,
                    selected_categories: ["copyright", "character", "general"],
                    multi_select_enabled: false,
                    formatting: {
                        escapeBrackets: true,
                        replaceUnderscores: true,
                    }
                };

                const loadUiSettings = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/ui_settings');
                        const data = await response.json();
                        if (data.success) {
                            uiSettings = {
                                autocomplete_enabled: data.settings.autocomplete_enabled,
                                tooltip_enabled: data.settings.tooltip_enabled,
                                autocomplete_max_results: data.settings.autocomplete_max_results || 20,
                                selected_categories: data.settings.selected_categories || ["copyright", "character", "general"],
                                multi_select_enabled: data.settings.multi_select_enabled || false,
                                formatting: data.settings.formatting || { escapeBrackets: true, replaceUnderscores: true }
                            };
                        }
                    } catch (e) {
                        logger.warn("加载UI设置失败:", e);
                    }
                };

                const saveUiSettings = async (settings) => {
                    try {
                        const response = await fetch('/danbooru_gallery/ui_settings', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(settings)
                        });
                        const data = await response.json();
                        return data.success;
                    } catch (e) {
                        logger.warn("保存UI设置失败:", e);
                        return false;
                    }
                };

                const loadBlacklist = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/blacklist');
                        const data = await response.json();
                        currentBlacklist = data.blacklist || [];
                    } catch (e) {
                        logger.warn("加载黑名单失败:", e);
                        currentBlacklist = [];
                    }
                };

                const saveBlacklist = async (blacklistItems) => {
                    try {
                        const response = await fetch('/danbooru_gallery/blacklist', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ blacklist: blacklistItems })
                        });
                        const data = await response.json();
                        return data.success;
                    } catch (e) {
                        logger.warn("保存黑名单失败:", e);
                        return false;
                    }
                };

                const loadFilterTags = async () => {
                    try {
                        const response = await fetch('/danbooru_gallery/filter_tags');
                        const data = await response.json();
                        currentFilterTags = data.filter_tags || [];
                        filterEnabled = data.filter_enabled !== undefined ? data.filter_enabled : true;
                    } catch (e) {
                        logger.warn("加载提示词过滤设置失败:", e);
                        currentFilterTags = [];
                        filterEnabled = true; // 默认开启
                    }
                };

                const saveFilterTags = async (filterTags, enabled) => {
                    try {
                        const response = await fetch('/danbooru_gallery/filter_tags', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ filter_tags: filterTags, filter_enabled: enabled })
                        });
                        const data = await response.json();
                        return data.success;
                    } catch (e) {
                        logger.warn("保存提示词过滤设置失败:", e);
                        return false;
                    }
                };


                // 文件类型过滤函数 - 只允许静态图像。
                // V23：Civitai 收藏经常没有可靠 file_ext，或 file_url 是无扩展的 CDN transform URL；
                // 不能只因为 file_ext 缺失就把卡片静默过滤掉，否则用户看不到“为什么没图”。
                const isValidImageType = (post) => {
                    const allowedImageExtensions = ['jpg', 'jpeg', 'png', 'webp', 'bmp', 'tiff', 'tif', 'avif'];
                    const sourceForPost = normalizeSource(post?.source_site || post?.source || currentSource || '');
                    const urls = [post?.file_url, post?.large_file_url, post?.preview_file_url, post?.image_url, post?.thumbnailUrl, post?.preview_url, post?.sample_url]
                        .map(v => String(v || '').trim()).filter(Boolean);
                    const extFromUrl = (url) => {
                        const m = String(url || '').toLowerCase().match(/\.([a-z0-9]+)(?:[?#].*)?$/);
                        return m ? m[1] : '';
                    };
                    const fileExt = String(post?.file_ext || '').toLowerCase().trim();
                    if (fileExt && allowedImageExtensions.includes(fileExt)) return true;
                    if (urls.some(u => allowedImageExtensions.includes(extFromUrl(u)))) return true;
                    // Civitai 的 image.civitai.com transform URL 经常没有传统扩展，但仍然是图片。
                    if ((sourceForPost === 'civitai' || sourceForPost === 'yandere') && urls.some(u => /^https?:\/\//i.test(u))) return true;
                    return false;
                };

                // 本地黑名单过滤函数
                const isPostBlacklisted = (post) => {
                    if (!currentBlacklist || currentBlacklist.length === 0) {
                        return false;
                    }

                    // 获取帖子的所有标签
                    const allTags = [];
                    if (post.tag_string) allTags.push(...post.tag_string.split(' '));
                    if (post.tag_string_artist) allTags.push(...post.tag_string_artist.split(' '));
                    if (post.tag_string_copyright) allTags.push(...post.tag_string_copyright.split(' '));
                    if (post.tag_string_character) allTags.push(...post.tag_string_character.split(' '));
                    if (post.tag_string_general) allTags.push(...post.tag_string_general.split(' '));
                    if (post.tag_string_meta) allTags.push(...post.tag_string_meta.split(' '));

                    // 检查是否包含黑名单中的任何标签
                    for (const blacklistTag of currentBlacklist) {
                        const normalizedBlacklistTag = blacklistTag.trim().toLowerCase();
                        if (normalizedBlacklistTag && allTags.some(tag => tag.toLowerCase() === normalizedBlacklistTag)) {
                            return true;
                        }
                    }
                    return false;
                };

                // 综合过滤函数 - 检查文件类型和黑名单
                const isPostFiltered = (post) => {
                    // 首先检查是否为有效的图像类型
                    if (!isValidImageType(post)) {
                        return true; // 如果不是有效图像类型，则过滤掉
                    }

                    // 然后检查黑名单
                    return isPostBlacklisted(post);
                };

                // 获取单个帖子的原始数据
                const fetchOriginalPost = async (postId) => {
                    try {
                        const response = await fetch(`/danbooru_gallery/posts?source=${encodeURIComponent(currentSource)}&search[id]=${encodeURIComponent(postId)}&limit=1`);
                        const data = await response.json();
                        if (data && data.length > 0) {
                            return data[0];
                        }
                        return null;
                    } catch (error) {
                        logger.error("Failed to fetch original post data:", error);
                        return null;
                    }
                };

                // 反向转换函数：将显示格式的标签转换回Danbooru API格式
                const convertTagsToApiFormat = (tagsString) => {
                    if (!tagsString) return "";

                    // 只按逗号分割标签，保持空格作为标签名称的一部分
                    const tags = tagsString.split(',').filter(tag => tag.trim() !== '');

                    return tags.map(tag => {
                        let convertedTag = tag.trim();

                        // 1. 反转义括号：\( -> (, \) -> )
                        convertedTag = convertedTag.replace(/\\([()])/g, '$1');

                        // 2. 空格转换为下划线（如果包含空格且不是特殊tag）
                        // 特殊tag通常以冒号开头（如 order:rank, ordfav:username）
                        if (!convertedTag.includes(':')) {
                            convertedTag = convertedTag.replace(/\s+/g, '_');
                        }

                        return convertedTag;
                    }).join(' ');
                };

                const V53_BROWSE_MODES = new Set(["latest", "ranking", "category"]);
                const V53_USABLE_STATES = new Set(["supported", "degraded"]);
                const v53Label = (value) => ({
                    latest: "最新",
                    ranking: "排行",
                    category: "分类",
                    search: "搜索",
                    favorites: "收藏",
                    favorite_stream: "收藏动态",
                    score: "评分",
                    popular: "热门度",
                    score_approx: "近期评分（近似）",
                    score_period: "周期评分",
                    favorites_count: "收藏数",
                    reactions: "反应数",
                    comments: "评论数",
                    collected: "收藏量",
                    day: "日榜",
                    week: "周榜",
                    month: "月榜",
                    year: "年榜",
                    all_time: "总榜",
                    tag: "标签",
                    tag_cumulative: "热门标签",
                    related_tag: "相关标签",
                    general: "通用标签",
                    meta: "元标签",
                    artist: "画师",
                    copyright: "作品",
                    character: "角色",
                    model: "模型",
                    creator: "创作者",
                    model_taxonomy: "模型标签",
                    model_version: "模型版本",
                    base_model: "基础模型",
                    known_image_tag_id: "图片标签",
                }[value] || String(value || ""));

                const persistGalleryState = () => {
                    if (!galleryStateWidget) return;
                    try {
                        galleryStateWidget.value = JSON.stringify(galleryStore.serialize());
                        nodeInstance?.setDirtyCanvas?.(true, true);
                        app?.graph?.setDirtyCanvas?.(true, true);
                    } catch (error) {
                        logger.warn("[Danbooru Gallery V53] Failed to persist gallery_state", error);
                    }
                };

                const hydrateGalleryState = () => {
                    let persisted = initialGalleryState;
                    try {
                        const rawState = galleryStateWidget?.value;
                        const parsed = typeof rawState === "string" ? JSON.parse(rawState) : rawState;
                        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) persisted = parsed;
                    } catch (error) {
                        logger.warn("[Danbooru Gallery V53] Invalid gallery_state; using defaults", error);
                    }
                    try {
                        galleryStore = new GalleryStore({ persisted });
                    } catch (error) {
                        logger.warn("[Danbooru Gallery V53] gallery_state schema is invalid; resetting safely", error);
                        galleryStore = new GalleryStore({ persisted: initialGalleryState });
                    }
                    if (!galleryStore.persisted.legacyMigrationDone) {
                        const legacySource = normalizeSource(loadFromLocalStorage("source", "gelbooru"));
                        const rawTerms = String(loadFromLocalStorage("searchValue", "") || "").trim();
                        let mode = rawTerms ? "search" : "latest";
                        if (/\border:rank\b/i.test(rawTerms)) mode = "ranking";
                        if (/\bcivitai:favorites\b/i.test(rawTerms) || /\bordfav:[^\s,]+/i.test(rawTerms)) mode = "favorites";
                        const terms = rawTerms
                            .replace(/\border:rank\b/gi, "")
                            .replace(/\bcivitai:favorites\b/gi, "")
                            .replace(/\bordfav:[^\s,]+/gi, "")
                            .replace(/,\s*,/g, ",")
                            .replace(/^\s*,|,\s*$/g, "")
                            .trim();
                        const legacyRatings = loadFromLocalStorage("ratingValues", null);
                        const safetyProfile = Array.isArray(legacyRatings) && legacyRatings.length === 1
                            ? legacyRatings[0]
                            : null;
                        galleryStore.updateDraft(legacySource, {
                            mode,
                            terms,
                            filters: { safetyProfile },
                            pageSize: 40,
                        });
                        galleryStore.setActiveSource(legacySource);
                        galleryStore.persisted.legacyMigrationDone = true;
                    }

                    currentSource = galleryStore.persisted.activeSource;
                    const draft = galleryStore.setActiveSource(currentSource);
                    sourceSelect.value = currentSource;
                    searchInput.value = draft.terms || "";
                    applySelectedRatings(draft.filters?.safetyProfile ? [draft.filters.safetyProfile] : RATING_VALUES);
                    if (V53_BROWSE_MODES.has(draft.mode)) lastBrowseModeBySource.set(currentSource, draft.mode);
                    persistGalleryState();
                    return draft;
                };

                const getV53Capabilities = (source = currentSource) => (
                    providerCapabilities.get(source) || createMinimalProviderCapabilities(source)
                );
                const isV53ProviderEnabled = (source = currentSource) => (
                    v53FeatureFlags?.[`provider_${source}_v2`] !== false
                );
                const getV53ViewCapability = (mode, capabilities = getV53Capabilities()) => (
                    capabilities?.features?.views?.find((entry) => entry?.id === mode) || null
                );
                const isV53Usable = (entry) => V53_USABLE_STATES.has(entry?.state);
                const getV53RankingCapability = (metric, period, capabilities = getV53Capabilities()) => (
                    capabilities?.features?.ranking?.find((entry) => (
                        entry?.metric === metric
                        && (!period || (Array.isArray(entry.periods) && entry.periods.includes(period)))
                        && isV53Usable(entry)
                    )) || null
                );

                const showV53Status = (message, state = "info", details = "") => {
                    if (!v53StatusPanel) return;
                    v53StatusPanel.dataset.state = state;
                    v53StatusPanel.replaceChildren();
                    const text = $el("span.v53-status-message", { textContent: String(message || "") });
                    v53StatusPanel.appendChild(text);
                    if (details) v53StatusPanel.appendChild($el("span.v53-status-details", { textContent: String(details) }));
                };

                const v53ErrorFromResponse = async (response) => {
                    let payload = null;
                    try {
                        payload = await response.json();
                    } catch {
                        payload = null;
                    }
                    if (response.ok && payload && !payload.error) return payload;
                    const detail = payload?.error || {};
                    const error = new Error(detail.message || `V2 请求失败（HTTP ${response.status}）`);
                    error.code = detail.code || "http_error";
                    error.httpStatus = detail.httpStatus || response.status;
                    error.retryable = Boolean(detail.retryable);
                    error.retryAfterSeconds = detail.retryAfterSeconds
                        ?? Number(response.headers.get("Retry-After") || 0)
                        ?? null;
                    error.responsePayload = payload;
                    throw error;
                };

                const formatV53Error = (error) => {
                    const status = error?.httpStatus ? `HTTP ${error.httpStatus}` : "请求错误";
                    const code = error?.code ? ` / ${error.code}` : "";
                    const retry = error?.retryAfterSeconds ? `，${error.retryAfterSeconds} 秒后可重试` : "";
                    return `${status}${code}: ${error?.message || "未知错误"}${retry}`;
                };

                const renderV53RequestError = (error, { reset, retry }) => {
                    const failedSource = currentSource;
                    const guidance = galleryErrorGuidance(error, failedSource);
                    showV53Status(guidance.message, "error");
                    if (reset || posts.length === 0) imageGrid.replaceChildren();
                    imageGrid.querySelector(".v53-inline-error")?.remove();
                    const retryButton = $el("button.v53-retry-button", {
                        type: "button",
                        textContent: "重试",
                        "data-testid": "gallery-retry",
                        onclick: retry,
                    });
                    retryButton.setAttribute("data-testid", "gallery-retry");
                    const inlineError = $el("div.danbooru-status.error.v53-inline-error", {
                        role: "alert",
                        "data-testid": "gallery-error",
                    }, [$el("span", { textContent: guidance.message })]);
                    inlineError.setAttribute("data-testid", "gallery-error");
                    if (guidance.action === 'settings') inlineError.appendChild($el('button', {type:'button',textContent:'打开当前来源设置',onclick:()=>showSettingsDialog({section:'user',source:failedSource})}));
                    if (guidance.action === 'browse') inlineError.appendChild($el('button', {type:'button',textContent:'返回浏览',onclick:()=>setV53Mode('browse')}));
                    inlineError.appendChild(retryButton);
                    const details = $el('details.v53-error-details', {}, [$el('summary', {textContent:'查看错误详情'}),$el('pre', {textContent:formatV53Error(error)})]);
                    inlineError.appendChild(details);
                    imageGrid.appendChild(inlineError);
                };

                const extractProviderCapabilities = (payload, source) => {
                    const candidates = Array.isArray(payload)
                        ? payload
                        : Array.isArray(payload?.providers)
                            ? payload.providers
                            : Array.isArray(payload?.items)
                                ? payload.items
                                : Array.isArray(payload?.data)
                                    ? payload.data
                                    : [payload?.capabilities || payload?.provider || payload?.data || payload];
                    return candidates.find((entry) => entry?.source === source) || null;
                };

                const loadV53Capabilities = async (source = currentSource) => {
                    const intentSequence = ++v53CapabilityIntentSequence;
                    const identity = await buildGalleryRequest({
                        route: "browse",
                        source,
                        view: "latest",
                        pageSize: 20,
                    });
                    const request = await buildGalleryRequest({ route: "providers", source });
                    if (intentSequence !== v53CapabilityIntentSequence || source !== currentSource) return null;
                    const token = galleryRequests.begin("capabilities", identity.clientQueryKey, {
                        clientRequestId: identity.clientRequestId,
                    });
                    try {
                        const response = await fetch(request.url, { signal: token.signal, cache: "no-store" });
                        const payload = await v53ErrorFromResponse(response);
                        const capabilities = extractProviderCapabilities(payload, source);
                        if (!capabilities?.features?.views) throw new Error("能力表响应缺少 features.views");
                        galleryRequests.commit(token, undefined, () => {
                            providerCapabilities.set(source, capabilities);
                            if (source === currentSource) refreshV53CapabilityControls(capabilities);
                        });
                        return capabilities;
                    } catch (error) {
                        if (error?.name === "AbortError" || !galleryRequests.canCommit(token)) return null;
                        const fallback = createMinimalProviderCapabilities(source);
                        fallback.__fallback = true;
                        fallback.__fallbackReason = error?.message || "capabilities_unavailable";
                        galleryRequests.finish(token, "error");
                        providerCapabilities.set(source, fallback);
                        if (source === currentSource) {
                            refreshV53CapabilityControls(fallback);
                            showV53Status("能力表加载失败，已启用该站点的最小安全功能", "warning", formatV53Error(error));
                        }
                        return fallback;
                    }
                };

                const tagsToString = (value) => {
                    if (Array.isArray(value)) return value.filter(Boolean).join(" ");
                    return typeof value === "string" ? value : "";
                };

                const adaptV53GalleryItem = (item) => {
                    const declaredSource = item?.sourceSite || item?.source_site;
                    const legacySource = ["danbooru", "gelbooru", "civitai", "yandere"].includes(String(item?.source || "").toLowerCase())
                        ? item.source
                        : currentSource;
                    const sourceSite = normalizeSource(declaredSource || legacySource);
                    const tags = item?.tags && typeof item.tags === "object" ? item.tags : {};
                    const metrics = item?.metrics && typeof item.metrics === "object" ? item.metrics : {};
                    const previewUrl = item?.previewUrl || item?.preview_file_url || item?.preview_url || item?.thumbnailUrl || "";
                    const sampleUrl = item?.sampleUrl || item?.large_file_url || item?.sample_url || "";
                    const fileUrl = item?.fileUrl || item?.file_url || item?.image_url || sampleUrl || previewUrl;
                    let fileExt = item?.file_ext || "";
                    if (!fileExt && fileUrl) {
                        try {
                            const extension = new URL(fileUrl).pathname.match(/\.([a-z0-9]+)$/i)?.[1];
                            fileExt = extension ? extension.toLowerCase() : "";
                        } catch { }
                    }
                    if (!fileExt && /^image\//i.test(String(item?.mediaType || ""))) {
                        fileExt = String(item.mediaType).split("/")[1].toLowerCase().replace("jpeg", "jpg");
                    }
                    const rawTags = tagsToString(tags.raw) || item?.tag_string || tagsToString(tags.general);
                    const detailUrl = item?.detailUrl || item?.post_url || item?.civitai_url || item?.danbooru_url || item?.gelbooru_url || item?.yandere_url || "";
                    return {
                        ...item,
                        id: item?.id,
                        source_site: sourceSite,
                        preview_file_url: previewUrl,
                        preview_url: previewUrl,
                        large_file_url: sampleUrl || fileUrl,
                        sample_url: sampleUrl,
                        file_url: fileUrl,
                        image_width: item?.width ?? item?.image_width,
                        image_height: item?.height ?? item?.image_height,
                        file_ext: fileExt,
                        rating: item?.rating,
                        created_at: item?.createdAt || item?.created_at,
                        tag_string: rawTags,
                        tag_string_general: tagsToString(tags.general) || item?.tag_string_general || rawTags,
                        tag_string_artist: tagsToString(tags.artist) || item?.tag_string_artist || "",
                        tag_string_copyright: tagsToString(tags.copyright) || item?.tag_string_copyright || "",
                        tag_string_character: tagsToString(tags.character) || item?.tag_string_character || "",
                        tag_string_meta: tagsToString(tags.meta) || item?.tag_string_meta || "",
                        score: metrics.score ?? item?.score,
                        fav_count: metrics.favorites ?? item?.fav_count,
                        civitai_prompt: sourceSite === "civitai" ? (item?.prompt || item?.civitai_prompt || "") : item?.civitai_prompt,
                        civitai_negative_prompt: sourceSite === "civitai" ? (item?.negativePrompt || item?.civitai_negative_prompt || "") : item?.civitai_negative_prompt,
                        civitai_content_tags: sourceSite === "civitai" ? (tagsToString(tags.general) || item?.civitai_content_tags || rawTags) : item?.civitai_content_tags,
                        post_url: detailUrl,
                        [`${sourceSite}_url`]: detailUrl,
                        ranking_position: item?.ranking?.displayPosition ?? item?.ranking_position,
                    };
                };

                const currentV53SafetyProfile = (capabilities, view) => {
                    const selected = getSelectedRatings();
                    const compatible = capabilities?.features?.compatibleFiltersByView?.[view] || [];
                    const profiles = capabilities?.features?.safety?.profiles || [];
                    return selected.length === 1 && compatible.includes("safetyProfile") && profiles.includes(selected[0])
                        ? selected[0]
                        : null;
                };

                const syncV53DraftFromControls = (patch = {}) => {
                    const draft = galleryStore.getDraft(currentSource);
                    const mode = patch.mode || draft.mode;
                    const capabilities = getV53Capabilities();
                    const ranking = getV53RankingCapability(v53MetricSelect?.value, v53PeriodSelect?.value, capabilities);
                    const next = galleryStore.updateDraft(currentSource, {
                        terms: searchInput.value.trim(),
                        facet: {
                            kind: v53FacetKindSelect?.value || null,
                            id: v53FacetValueSelect?.value || null,
                            label: v53FacetValueSelect?.selectedOptions?.[0]?.textContent || null,
                        },
                        sort: {
                            metric: v53MetricSelect?.value || null,
                            period: v53PeriodSelect?.value || null,
                            anchorDate: ranking?.supportsAnchorDate && v53PeriodSelect?.value !== "all_time"
                                ? (draft.sort?.anchorDate || new Date().toISOString().slice(0, 10))
                                : null,
                            allowApprox: ranking?.fidelity === "client_approx",
                        },
                        filters: { safetyProfile: currentV53SafetyProfile(capabilities, mode) },
                        pageSize: Math.min(40, Number(capabilities?.limits?.maxPageSize || 40)),
                        ...patch,
                    });
                    if (V53_BROWSE_MODES.has(next.mode)) lastBrowseModeBySource.set(currentSource, next.mode);
                    persistGalleryState();
                    return next;
                };

                const replaceSelectOptions = (select, options, selectedValue) => {
                    select.replaceChildren(...options.map((option) => $el("option", {
                        value: String(option.value ?? ""),
                        textContent: String(option.label ?? option.value ?? ""),
                        disabled: Boolean(option.disabled),
                    })));
                    const requested = selectedValue === null || selectedValue === undefined ? "" : String(selectedValue);
                    if (Array.from(select.options).some((option) => option.value === requested)) select.value = requested;
                    else if (select.options.length) select.selectedIndex = 0;
                };

                const updateV53TabState = () => {
                    const mode = galleryStore.getDraft(currentSource).mode;
                    const primaryMode = V53_BROWSE_MODES.has(mode) ? "browse" : mode;
                    container.dataset.gallerySource = currentSource;
                    container.dataset.galleryMode = mode;
                    Object.entries(v53PrimaryTabs).forEach(([id, button]) => {
                        const selected = id === primaryMode;
                        button.setAttribute("aria-selected", String(selected));
                        button.tabIndex = selected ? 0 : -1;
                        button.classList.toggle("active", selected);
                    });
                    Object.entries(v53BrowseTabs).forEach(([id, button]) => {
                        const selected = id === mode;
                        button.setAttribute("aria-selected", String(selected));
                        button.tabIndex = selected ? 0 : -1;
                        button.classList.toggle("active", selected);
                    });
                    v53BrowseTabList.hidden = primaryMode !== "browse";
                    searchContainer.hidden = mode !== "search";
                    v53RankingControls.hidden = mode !== "ranking";
                    v53FacetControls.hidden = mode !== "category";
                    updateRankingButtonState();
                    updateFavoritesButtonState();
                    updateFavoriteStreamButtonState();
                    updateCivitaiLooseButtonState();
                };

                const refreshV53CapabilityControls = (capabilities = getV53Capabilities()) => {
                    const draft = galleryStore.getDraft(currentSource);
                    const viewUsable = (mode) => isV53Usable(getV53ViewCapability(mode, capabilities));
                    Object.entries(v53BrowseTabs).forEach(([mode, button]) => {
                        const capability = getV53ViewCapability(mode, capabilities);
                        button.disabled = !isV53Usable(capability);
                        button.setAttribute("aria-disabled", String(button.disabled));
                        button.title = button.disabled ? (capability?.reasonCode || "当前站点不支持") : v53Label(mode);
                    });
                    for (const mode of ["search", "favorites", "favorite_stream"]) {
                        const capability = getV53ViewCapability(mode, capabilities);
                        const button = v53PrimaryTabs[mode];
                        button.disabled = !isV53Usable(capability);
                        button.setAttribute("aria-disabled", String(button.disabled));
                        button.title = button.disabled ? (capability?.reasonCode || "当前站点不支持") : v53Label(mode);
                    }
                    v53PrimaryTabs.browse.disabled = !["latest", "ranking", "category"].some(viewUsable);
                    v53PrimaryTabs.browse.setAttribute("aria-disabled", String(v53PrimaryTabs.browse.disabled));

                    let effectiveMode = draft.mode;
                    if (!viewUsable(effectiveMode)) {
                        effectiveMode = ["latest", "ranking", "category", "search", "favorites", "favorite_stream"].find(viewUsable) || "latest";
                        galleryStore.updateDraft(currentSource, { mode: effectiveMode });
                        if (V53_BROWSE_MODES.has(effectiveMode)) lastBrowseModeBySource.set(currentSource, effectiveMode);
                        persistGalleryState();
                    }

                    const rankingEntries = (capabilities?.features?.ranking || []).filter(isV53Usable);
                    const metrics = new Map();
                    for (const entry of rankingEntries) {
                        if (!metrics.has(entry.metric)) metrics.set(entry.metric, new Set());
                        for (const period of entry.periods || []) metrics.get(entry.metric).add(period);
                    }
                    replaceSelectOptions(
                        v53MetricSelect,
                        Array.from(metrics.keys()).map((metric) => ({ value: metric, label: v53Label(metric) })),
                        draft.sort?.metric
                    );
                    const activeMetric = v53MetricSelect.value;
                    replaceSelectOptions(
                        v53PeriodSelect,
                        Array.from(metrics.get(activeMetric) || []).map((period) => ({ value: period, label: v53Label(period) })),
                        draft.sort?.period
                    );
                    v53RankingControls.dataset.available = String(metrics.size > 0);

                    const facets = (capabilities?.features?.facets || []).filter((entry) => (
                        isV53Usable(entry) && entry.listable !== false && entry.filterable !== false
                    ));
                    replaceSelectOptions(
                        v53FacetKindSelect,
                        facets.map((entry) => ({ value: entry.kind, label: v53Label(entry.kind) })),
                        draft.facet?.kind
                    );
                    replaceSelectOptions(v53FacetValueSelect, [{ value: "", label: facets.length ? "加载分类项…" : "无可用分类", disabled: true }], "");
                    v53FacetControls.dataset.available = String(facets.length > 0);
                    updateV53TabState();

                    const availability = capabilities?.availability?.state || "available";
                    if (!capabilities.__fallback) {
                        const capabilityEntries = [
                            ...(capabilities?.features?.views || []),
                            ...(capabilities?.features?.ranking || []),
                            ...(capabilities?.features?.facets || []),
                        ];
                        const degraded = availability !== "available"
                            || capabilityEntries.some((entry) => entry?.state === "degraded");
                        showV53Status(
                            degraded ? `已加载 ${currentSource} 能力表（部分功能可能降级）` : `已加载 ${currentSource} 能力表`,
                            degraded ? "warning" : "ready",
                            capabilities?.availability?.reason || ""
                        );
                    }
                };

                const loadV53FacetValues = async () => {
                    const intentSequence = ++v53FacetIntentSequence;
                    const sourceAtStart = currentSource;
                    const capabilities = getV53Capabilities();
                    const kind = v53FacetKindSelect.value;
                    const facetCapability = capabilities?.features?.facets?.find((entry) => entry?.kind === kind);
                    if (
                        !kind
                        || !isV53Usable(facetCapability)
                        || facetCapability?.listable === false
                        || facetCapability?.filterable === false
                    ) {
                        showV53Status("当前站点没有可浏览的分类项", "warning");
                        return false;
                    }
                    const draft = galleryStore.getDraft(currentSource);
                    const request = await buildGalleryRequest({
                        route: "facets",
                        source: currentSource,
                        facetKind: kind,
                        query: null,
                        pageSize: Math.min(40, Number(capabilities?.limits?.maxPageSize || 40)),
                    });
                    if (intentSequence !== v53FacetIntentSequence || sourceAtStart !== currentSource) return false;
                    const token = galleryRequests.begin("facets", request.clientQueryKey, {
                        clientRequestId: request.clientRequestId,
                    });
                    v53FacetKindSelect.disabled = true;
                    v53FacetValueSelect.disabled = true;
                    showV53Status(`正在加载“${v53Label(kind)}”分类…`, "loading");
                    try {
                        const response = await fetch(request.url, { signal: token.signal, cache: "no-store" });
                        const payload = await v53ErrorFromResponse(response);
                        if (!Array.isArray(payload?.items)) throw new Error("分类响应缺少 items 数组");
                        if (!galleryRequests.canCommit(token, payload)) {
                            if (galleryRequests.canCommit(token)) {
                                const identityError = new Error("分类响应的 clientRequestId/queryKey 与当前请求不匹配");
                                identityError.code = "response_identity_mismatch";
                                throw identityError;
                            }
                            return false;
                        }
                        let populated = false;
                        galleryRequests.commit(token, payload, () => {
                            const options = payload.items.map((item) => {
                                const id = item?.id ?? item?.value ?? item?.name;
                                const label = item?.label ?? item?.name ?? id;
                                const count = item?.count ?? item?.postCount;
                                return { value: id, label: count === undefined ? label : `${label} (${count})` };
                            }).filter((item) => item.value !== null && item.value !== undefined && item.value !== "");
                            replaceSelectOptions(
                                v53FacetValueSelect,
                                options.length ? options : [{ value: "", label: "没有分类项", disabled: true }],
                                draft.facet?.kind === kind ? draft.facet?.id : null
                            );
                            v53FacetValueSelect.disabled = options.length === 0;
                            populated = options.length > 0;
                            if (populated) {
                                syncV53DraftFromControls();
                                const warnings = (payload.warnings || []).map((entry) => entry?.message || entry?.code).filter(Boolean).join("；");
                                showV53Status(`已加载 ${options.length} 个分类项`, warnings ? "warning" : "ready", warnings);
                            } else {
                                showV53Status("该分类没有可用条目", "empty");
                            }
                        });
                        return populated;
                    } catch (error) {
                        if (intentSequence !== v53FacetIntentSequence || sourceAtStart !== currentSource) return false;
                        if (error?.name === "AbortError" || !galleryRequests.canCommit(token)) return false;
                        galleryRequests.finish(token, "error");
                        showV53Status(formatV53Error(error), "error");
                        replaceSelectOptions(v53FacetValueSelect, [{ value: "", label: "分类加载失败", disabled: true }], "");
                        return false;
                    } finally {
                        if (currentSource === request.canonicalQuery.source) v53FacetKindSelect.disabled = false;
                    }
                };

                const makeV53BrowseRequest = async (draft, cursor = null) => {
                    const capabilities = getV53Capabilities();
                    const view = draft.mode;
                    const viewCapability = getV53ViewCapability(view, capabilities);
                    if (!isV53Usable(viewCapability)) throw new Error(`当前站点不支持“${v53Label(view)}”视图`);
                    if (view === "search" && !draft.terms.trim()) throw new Error("请输入搜索词后按 Enter");

                    let searchQuery = view === "search" ? draft.terms.trim() : null;
                    if (
                        currentSource === "civitai"
                        && searchQuery
                        && civitaiLooseMode
                        && !/\b(?:loose|strict|mode\s*:\s*(?:loose|strict))\b/i.test(searchQuery)
                    ) {
                        searchQuery = `mode:loose ${searchQuery}`;
                    }
                    const input = {
                        route: "browse",
                        source: currentSource,
                        view,
                        query: searchQuery,
                        safetyProfile: currentV53SafetyProfile(capabilities, view),
                        pageSize: Math.min(Number(draft.pageSize || 40), Number(capabilities?.limits?.maxPageSize || 40)),
                        cursor,
                    };
                    if (view === "ranking") {
                        const ranking = getV53RankingCapability(draft.sort?.metric, draft.sort?.period, capabilities);
                        if (!ranking) throw new Error("请选择当前站点支持的排行指标与周期");
                        input.metric = ranking.metric;
                        input.period = draft.sort.period;
                        input.anchorDate = ranking.supportsAnchorDate && draft.sort.period !== "all_time"
                            ? (draft.sort.anchorDate || new Date().toISOString().slice(0, 10))
                            : null;
                        input.allowApprox = ranking.fidelity === "client_approx";
                    }
                    if (view === "category") {
                        if (!draft.facet?.kind || !draft.facet?.id) throw new Error("请先选择一个分类项");
                        input.facetKind = draft.facet.kind;
                        input.facetId = draft.facet.id;
                    }
                    return buildGalleryRequest(input);
                };

                const renderV53Session = (session) => {
                    imageGrid.replaceChildren();
                    posts = [];
                    renderedPostKeys = new Set();
                    for (const post of session?.items || []) {
                        if (!isValidImageType(post) || isPostBlacklisted(post)) continue;
                        const key = getPostCacheKey(post);
                        if (renderedPostKeys.has(key)) continue;
                        renderedPostKeys.add(key);
                        posts.push(post);
                        renderPost(post);
                    }
                    const page = session?.pages?.[session.pageIndex];
                    endOfResults = !page?.nextCursor;
                    imageGrid.scrollTop = Number(page?.scrollTop || 0);
                    if (!posts.length) imageGrid.appendChild($el("p.danbooru-status", { textContent: t("noResults") }));
                    requestAnimationFrame(() => { updateGridLayout(); resizeGrid(); });
                };

                const fetchAndRenderV53 = async (reset = false) => {
                    if (reset && galleryRequests.snapshot().browse.active) {
                        galleryRequests.abort("browse", "query_changed");
                        isLoading = false;
                    }
                    if (isLoading || (endOfResults && !reset)) return;
                    const intentSequence = ++v53BrowseIntentSequence;
                    const sourceAtStart = currentSource;
                    setDiagnosticMode(false);
                    const draft = syncV53DraftFromControls();
                    let request = null;
                    let token = null;
                    let requestCursor = null;
                    let restoreScrollTop = 0;
                    try {
                        const firstRequest = await makeV53BrowseRequest(draft, null);
                        if (intentSequence !== v53BrowseIntentSequence || sourceAtStart !== currentSource) return;
                        request = firstRequest;
                        if (reset) {
                            restoreScrollTop = draft.viewMemory?.queryKey === firstRequest.clientQueryKey
                                ? Number(draft.viewMemory?.scrollTop || 0)
                                : 0;
                            galleryStore.activateSession(currentSource, firstRequest.clientQueryKey);
                            galleryStore.restartSession(currentSource, firstRequest.clientQueryKey);
                        } else {
                            if (!galleryStore.hasSession(currentSource, firstRequest.clientQueryKey)) {
                                galleryStore.activateSession(currentSource, firstRequest.clientQueryKey);
                            }
                            const action = galleryStore.forwardAction(currentSource, firstRequest.clientQueryKey);
                            if (action.type === "end") {
                                endOfResults = true;
                                showV53Status(`已到“${v53Label(draft.mode)}”结果末尾`, "ready");
                                return;
                            }
                            if (action.type === "cached") {
                                const session = galleryStore.goForward(currentSource, firstRequest.clientQueryKey);
                                renderV53Session(session);
                                persistGalleryState();
                                return;
                            }
                            requestCursor = action.cursor;
                            if (requestCursor) {
                                request = await makeV53BrowseRequest(draft, requestCursor);
                                if (intentSequence !== v53BrowseIntentSequence || sourceAtStart !== currentSource) return;
                            }
                        }

                        token = galleryRequests.begin("browse", request.clientQueryKey, {
                            clientRequestId: request.clientRequestId,
                        });
                        isLoading = true;
                        endOfResults = false;
                        imageGrid.setAttribute("aria-busy", "true");
                        refreshButton.classList.add("loading");
                        refreshButton.disabled = true;
                        if (reset) {
                            posts = [];
                            renderedPostKeys = new Set();
                            imageGrid.scrollTop = 0;
                            imageGrid.replaceChildren();
                        }
                        imageGrid.querySelector(".v53-inline-error")?.remove();
                        imageGrid.appendChild($el("p.danbooru-status.danbooru-loading", { textContent: t("loading") }));
                        showV53Status(`正在加载“${v53Label(draft.mode)}”…`, "loading");

                        const response = await fetch(request.url, { signal: token.signal, cache: "no-store" });
                        const payload = await v53ErrorFromResponse(response);
                        if (!Array.isArray(payload?.items) || !payload?.pageInfo) throw new Error("V2 响应缺少 items/pageInfo");
                        if (!galleryRequests.canCommit(token, payload)) {
                            if (galleryRequests.canCommit(token)) {
                                const identityError = new Error("浏览响应的 clientRequestId/queryKey 与当前请求不匹配");
                                identityError.code = "response_identity_mismatch";
                                throw identityError;
                            }
                            return;
                        }
                        galleryRequests.commit(token, payload, () => {
                            imageGrid.querySelector(".danbooru-loading")?.remove();
                            const mappedItems = payload.items.map(adaptV53GalleryItem);
                            const recorded = galleryStore.recordPage(currentSource, request.clientQueryKey, {
                                requestCursor,
                                nextCursor: payload.pageInfo.nextCursor ?? null,
                                pageKey: payload.pageInfo.pageKey || `${request.clientQueryKey}:${requestCursor || "first"}`,
                                items: mappedItems,
                                scrollTop: reset ? restoreScrollTop : imageGrid.scrollTop,
                                warnings: payload.warnings || [],
                                applied: payload.applied || {},
                            });
                            if (reset) {
                                imageGrid.replaceChildren();
                                posts = [];
                                renderedPostKeys = new Set();
                            }
                            const invalidTypePosts = [];
                            const blacklistedPosts = [];
                            const filteredPosts = [];
                            for (const post of mappedItems) {
                                if (!isValidImageType(post)) { invalidTypePosts.push(post); continue; }
                                if (isPostBlacklisted(post)) { blacklistedPosts.push(post); continue; }
                                const key = getPostCacheKey(post);
                                if (renderedPostKeys.has(key)) continue;
                                renderedPostKeys.add(key);
                                filteredPosts.push(post);
                            }
                            posts.push(...filteredPosts);
                            filteredPosts.forEach(renderPost);
                            endOfResults = payload.pageInfo.hasNext === false || !payload.pageInfo.nextCursor;
                            currentPage = recorded.pageIndex + 2;
                            lastGalleryFetchStats = {
                                at: new Date().toISOString(),
                                source: currentSource,
                                mode: draft.mode,
                                query_key: request.clientQueryKey,
                                raw_count: payload.items.length,
                                rendered_count: filteredPosts.length,
                                filtered_invalid_type: invalidTypePosts.length,
                                filtered_blacklist: blacklistedPosts.length,
                                has_next: !endOfResults,
                            };
                            window.__danbooruGalleryLastFetchStats = lastGalleryFetchStats;
                            if (!posts.length && endOfResults) {
                                imageGrid.appendChild($el("p.danbooru-status", { textContent: t("noResults") }));
                            }
                            const warnings = (payload.warnings || []).map((entry) => entry?.message || entry?.code).filter(Boolean).join("；");
                            showV53Status(
                                `已加载 ${posts.length} 项${endOfResults ? " · 已到末页" : " · 向下滚动继续"}`,
                                warnings ? "warning" : "ready",
                                warnings
                            );
                            if (reset && restoreScrollTop > 0) requestAnimationFrame(() => { imageGrid.scrollTop = restoreScrollTop; });
                            persistGalleryState();
                            requestAnimationFrame(() => { updateGridLayout(); resizeGrid(); });
                        });
                    } catch (error) {
                        if (intentSequence !== v53BrowseIntentSequence || sourceAtStart !== currentSource) return;
                        if (error?.name === "AbortError") return;
                        if (token && !galleryRequests.canCommit(token)) return;
                        if (token) {
                            if (!reset && request?.clientQueryKey) {
                                galleryStore.setLoadMoreError(currentSource, request.clientQueryKey, {
                                    code: error?.code || "request_failed",
                                    message: error?.message || "请求失败",
                                });
                                if (error?.code === "cursor_expired") galleryStore.markCursorExpired(currentSource, request.clientQueryKey);
                            }
                            galleryRequests.finish(token, "error");
                        }
                        renderV53RequestError(error, { reset, retry: () => fetchAndRenderV53(reset) });
                    } finally {
                        const browseLane = galleryRequests.snapshot().browse;
                        if (!token || browseLane.clientRequestId === token.clientRequestId) {
                            isLoading = false;
                            imageGrid.setAttribute("aria-busy", "false");
                            refreshButton.classList.remove("loading");
                            refreshButton.disabled = false;
                            imageGrid.querySelector(".danbooru-loading")?.remove();
                        }
                    }
                };

                const setV53Mode = async (requestedMode, { fetchNow = true } = {}) => {
                    const mode = requestedMode === "browse"
                        ? (lastBrowseModeBySource.get(currentSource) || "latest")
                        : requestedMode;
                    const capability = getV53ViewCapability(mode);
                    if (!isV53Usable(capability)) {
                        const guidance = galleryErrorGuidance({reasonCode:capability?.reasonCode || 'unsupported'},currentSource);
                        showV53Status(guidance.message, "warning");
                        const action = guidance.action === 'settings'
                            ? $el('button',{type:'button',textContent:'打开当前来源设置',onclick:()=>showSettingsDialog({section:'user',source:currentSource})})
                            : $el('button',{type:'button',textContent:'返回浏览',onclick:()=>setV53Mode('browse')});
                        v53StatusPanel?.appendChild(action);
                        return false;
                    }
                    galleryRequests.abort("browse", "mode_changed");
                    v53BrowseIntentSequence += 1;
                    if (mode !== "category") galleryRequests.abort("facets", "mode_changed");
                    isLoading = false;
                    syncV53DraftFromControls({ mode });
                    updateV53TabState();
                    if (!fetchNow) return true;
                    if (mode === "category") {
                        const populated = await loadV53FacetValues();
                        if (!populated) return false;
                    }
                    await fetchAndRenderV53(true);
                    return true;
                };

                const handleV53SourceChange = async (nextSource) => {
                    if (nextSource === currentSource && v53UiReady) return;
                    const active = galleryStore.activeSession;
                    if (active) galleryStore.setScrollTop(active.source, active.queryKey, imageGrid.scrollTop);
                    syncV53DraftFromControls();
                    galleryRequests.abortAll("source_changed");
                    v53BrowseIntentSequence += 1;
                    v53FacetIntentSequence += 1;
                    v53CapabilityIntentSequence += 1;
                    isLoading = false;
                    currentSource = nextSource;
                    sourceSelect.value = currentSource;
                    const draft = galleryStore.setActiveSource(currentSource);
                    searchInput.value = draft.terms || "";
                    applySelectedRatings(draft.filters?.safetyProfile ? [draft.filters.safetyProfile] : RATING_VALUES);
                    if (V53_BROWSE_MODES.has(draft.mode)) lastBrowseModeBySource.set(currentSource, draft.mode);
                    posts = [];
                    renderedPostKeys = new Set();
                    endOfResults = false;
                    imageGrid.replaceChildren($el("p.danbooru-status.danbooru-loading", { textContent: t("loading") }));
                    searchAutocomplete.lastQuery = "";
                    updateFavoritesButtonState();
                    updateCivitaiLooseButtonState();
                    updateUrlExportButtonState();
                    persistGalleryState();
                    if (!v53UiReady) {
                        sourceSelect.disabled = false;
                        await fetchAndRender(true);
                        return;
                    }
                    sourceSelect.disabled = true;
                    const capabilities = await loadV53Capabilities(currentSource);
                    if (!capabilities || nextSource !== currentSource) return;
                    sourceSelect.disabled = false;
                    if (isV53ProviderEnabled() && galleryStore.getDraft(currentSource).mode === "category") {
                        const populated = await loadV53FacetValues();
                        if (!populated) return;
                    }
                    await fetchAndRender(true);
                };

                const fetchAndRender = async (reset = false) => {
                    if (v53UiReady && isV53ProviderEnabled()) return fetchAndRenderV53(reset);
                    if (isLoading) {
                        return;
                    }
                    if (endOfResults && !reset) {
                        return;
                    }
                    setDiagnosticMode(false);
                    isLoading = true;
                    refreshButton.classList.add("loading");
                    refreshButton.disabled = true;

                    const loadingIndicator = imageGrid.querySelector('.danbooru-loading');
                    if (!loadingIndicator) {
                        imageGrid.insertAdjacentHTML('beforeend', `<p class="danbooru-status danbooru-loading">${t('loading')}</p>`);
                    }

                    if (reset) {
                        currentPage = filterState.startPage || 1;
                        posts = [];
                        renderedPostKeys = new Set();
                        endOfResults = false;
                        imageGrid.innerHTML = "";
                        imageGrid.scrollTop = 0;
                        imageGrid.insertAdjacentHTML('beforeend', `<p class="danbooru-status danbooru-loading">${t('loading')}</p>`);
                    }

                    // 检查网络连接状态
                    const isNetworkConnected = await checkNetworkStatus();

                    if (!isNetworkConnected) {
                        // 网络连接失败，隐藏持久错误提示 - 本小姐才不想看到这些烦人的提示呢！
                        // showError('网络连接失败 - 无法连接到Danbooru服务器，请检查网络连接', true);
                        console.log("网络错误已隐藏: 网络连接失败 - 无法连接到Danbooru服务器，请检查网络连接");  // 仅在控制台记录
                        imageGrid.innerHTML = `<p class="danbooru-status error">${currentSource === "civitai" ? "Civitai API 请求失败，请点 C诊断查看真实错误" : "网络连接失败，请检查网络连接后重试"}</p>`;
                        isLoading = false;
                        refreshButton.classList.remove("loading");
                        refreshButton.disabled = false;
                        const indicator = imageGrid.querySelector('.danbooru-loading');
                        if (indicator) {
                            indicator.remove();
                        }
                        return;
                    } else {
                        // 网络连接恢复，清除之前的错误提示
                        clearError();
                    }

                    if (currentSource === "civitai" || (currentSource === "danbooru" && hasDanbooruFavoriteAuth())) {
                        await loadFavorites(currentSource);
                    }

                    try {
                        // 检测tag数量
                        const searchValue = searchInput.value.trim();
                        const tags = searchValue.split(',').filter(tag => tag.trim() !== '');
                        const tagCount = tags.length;

                        // Danbooru 普通搜索 tag 数有限；Gelbooru 不做该提示。
                        if (currentSource === "danbooru" && tagCount > 2) {
                            showTagHint('Danbooru 搜索只考虑前两个tag，第三个及后续tag将被忽略', false);
                        } else if (currentSource === "civitai") {
                            showTagHint('Civitai.red v30：普通词优先走网页 multi-search/images_v6；不写 sfw/nsfw 默认 any；多关键词默认严格，loose/mode:loose 才宽松；支持 tag/model/version/post/user、sort、period；收藏夹可远端。', false);
                        } else {
                            // 清除之前的提示
                            clearTagHint();
                        }

                        // 将搜索框中的标签转换为API格式。
                        // Civitai 不走 Danbooru 的空格转下划线规则；否则 `2girls sex` 会变成单个 `2girls_sex`。
                        let apiFormattedTags = currentSource === "civitai" ? searchValue : convertTagsToApiFormat(searchValue);
                        if (currentSource === "civitai" && civitaiLooseMode && apiFormattedTags && !/\b(loose|mode\s*:\s*loose|mode\s*:\s*strict|strict)\b/i.test(apiFormattedTags)) {
                            apiFormattedTags = `mode:loose ${apiFormattedTags}`;
                        }

                        // 添加日期筛选
                        if (filterState.startTime || filterState.endTime) {
                            const start = filterState.startTime ? new Date(filterState.startTime).toISOString().split('T')[0] : '';
                            const end = filterState.endTime ? new Date(filterState.endTime).toISOString().split('T')[0] : '';
                            apiFormattedTags += ` date:${start}..${end}`;
                        }

                        const selectedRatings = getSelectedRatings();
                        const sendAll = selectedRatings.length === 0 || selectedRatings.length === RATING_VALUES.length;
                        const ratingForServer = sendAll ? "" : selectedRatings.join(",");
                        const params = new URLSearchParams({
                            source: currentSource,
                            "search[tags]": apiFormattedTags.trim(),
                            "search[rating]": ratingForServer,
                            limit: "40",
                            page: currentPage,
                        });
                        if (reset && manualRefreshNonce) {
                            params.set("force_refresh", "1");
                            params.set("_refresh", String(manualRefreshNonce));
                        }

                        const response = await fetch(`/danbooru_gallery/posts?${params}`, {
                            cache: "no-store",
                            headers: { "Cache-Control": "no-cache", "Pragma": "no-cache" }
                        });
                        let newPosts = await response.json();

                        if (!Array.isArray(newPosts)) throw new Error("API did not return a valid list of posts.");

                        // 评分过滤已交给服务端，本地只做文件类型/黑名单过滤；额外做一次前端去重，防止后端游标缺失时同一页被重复 append。
                        const invalidTypePosts = [];
                        const blacklistedPosts = [];
                        const validPosts = [];
                        for (const post of newPosts) {
                            if (!isValidImageType(post)) invalidTypePosts.push(post);
                            else if (isPostBlacklisted(post)) blacklistedPosts.push(post);
                            else validPosts.push(post);
                        }
                        const filteredPosts = [];
                        let duplicateCount = 0;
                        for (const post of validPosts) {
                            const key = getPostCacheKey(post);
                            if (renderedPostKeys.has(key)) { duplicateCount += 1; continue; }
                            renderedPostKeys.add(key);
                            filteredPosts.push(post);
                        }

                        const filteredCount = newPosts.length - validPosts.length;
                        lastGalleryFetchStats = {
                            at: new Date().toISOString(), source: currentSource, search: searchValue, page: currentPage, reset: !!reset,
                            raw_count: newPosts.length, valid_count: validPosts.length, rendered_count: filteredPosts.length,
                            filtered_invalid_type: invalidTypePosts.length, filtered_blacklist: blacklistedPosts.length, duplicate_count: duplicateCount,
                            sample_invalid_type: invalidTypePosts.slice(0, 5).map(p => ({ id: p.id, file_ext: p.file_ext || '', file_url: p.file_url || '', preview_file_url: p.preview_file_url || '', large_file_url: p.large_file_url || '' })),
                        };
                        window.__danbooruGalleryLastFetchStats = lastGalleryFetchStats;

                        // API returned nothing → no more pages. Flag it so scroll events stop
                        // triggering fetches; otherwise the bottom-proximity check would keep
                        // firing and walk off the end of the result set indefinitely.
                        if (newPosts.length === 0) {
                            endOfResults = true;
                            if (reset) {
                                imageGrid.innerHTML = `<p class="danbooru-status">${t('noResults')}</p>`;
                            }
                            return;
                        }

                        if (validPosts.length > 0 && filteredPosts.length === 0 && !reset) {
                            endOfResults = true;
                            console.warn("[DanbooruGallery] 当前页全部为已渲染重复项，停止继续翻页，避免无限下滚循环。", { currentPage, source: currentSource });
                            return;
                        }

                        if (filteredPosts.length === 0 && reset) {
                            imageGrid.innerHTML = `<p class="danbooru-status">${t('noResults')}</p>`;
                            return;
                        }

                        currentPage++;
                        posts.push(...filteredPosts);
                        filteredPosts.forEach(renderPost);

                        // Filter-cascade guard: if the blacklist/rating filter dropped every
                        // post on this page, the grid didn't grow — the user's scroll is still
                        // within the 400px bottom threshold, so the scroll listener would
                        // re-fire immediately. Hold isLoading for ~1.5s (still inside the try
                        // block, before the finally clears it) to space out these "auto-skip"
                        // fetches.
                        if (filteredPosts.length === 0 && !reset) {
                            await new Promise(r => setTimeout(r, 1500));
                        }

                    } catch (e) {
                        imageGrid.innerHTML = `<p class="danbooru-status error">${e.message}</p>`;
                    } finally {
                        isLoading = false;
                        refreshButton.classList.remove("loading");
                        refreshButton.disabled = false;
                        const indicator = imageGrid.querySelector('.danbooru-loading');
                        if (indicator) {
                            indicator.remove();
                        }
                    }
                };

                const resizeGrid = () => {
                    const rowGap = parseInt(window.getComputedStyle(imageGrid).getPropertyValue('grid-row-gap'));
                    const rowHeight = parseInt(window.getComputedStyle(imageGrid).getPropertyValue('grid-auto-rows'));

                    Array.from(imageGrid.children).forEach((wrapper) => {
                        const img = wrapper.querySelector('img');
                        if (img && img.clientHeight > 0) {
                            const style = window.getComputedStyle(wrapper);
                            const borderHeight = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
                            const cardHeight = Math.max(img.clientHeight + borderHeight, parseFloat(style.minHeight) || 0);
                            const spans = Math.ceil((cardHeight + rowGap) / (rowHeight + rowGap));
                            wrapper.style.gridRowEnd = `span ${spans}`;
                        }
                    });
                }

                // Pre-reserve grid space from post dimensions so rate-limited async loads
                // don't cause the waterfall to jump every time an image arrives.
                let cachedColumnWidth = 0;
                let cachedColumnCount = 1;
                const updateGridLayout = () => {
                    if (!imageGrid) return;
                    const cs = window.getComputedStyle(imageGrid);
                    const colGap = parseInt(cs.columnGap) || parseInt(cs.gridColumnGap) || parseInt(cs.gridGap) || 5;
                    const paddingLeft = parseInt(cs.paddingLeft) || 0;
                    const paddingRight = parseInt(cs.paddingRight) || 0;
                    const forcedWidth = parseFloat(imageGrid.dataset.layoutWidth || "") || 0;
                    const nodeWidth = Math.max(0, (nodeInstance.size?.[0] || 0) - 28);
                    const measuredWidth = imageGrid.clientWidth || imageGrid.offsetWidth || 0;
                    const layoutWidth = embedded ? Math.max(measuredWidth, 120) : Math.max(forcedWidth, nodeWidth, measuredWidth, 120);
                    const availableWidth = Math.max(120, layoutWidth - paddingLeft - paddingRight);

                    // Let the gallery truly respond to node width instead of relying only on
                    // CSS auto-fill. This prevents the long-standing issue where the node grows
                    // wider but thumbnails still stay stuck in a single narrow column.
                    let preferredThumbWidth = 170;
                    if (availableWidth >= 1100) preferredThumbWidth = 210;
                    else if (availableWidth >= 900) preferredThumbWidth = 190;
                    else if (availableWidth >= 700) preferredThumbWidth = 175;
                    else if (availableWidth <= 420) preferredThumbWidth = 145;

                    const cols = Math.max(1, Math.floor((availableWidth + colGap) / (preferredThumbWidth + colGap)));
                    const columnWidth = Math.max(100, Math.floor((availableWidth - (colGap * (cols - 1))) / cols));

                    cachedColumnCount = cols;
                    cachedColumnWidth = columnWidth;
                    imageGrid.style.gridTemplateColumns = `repeat(${cols}, minmax(${columnWidth}px, 1fr))`;
                };
                const getColumnWidth = () => {
                    if (cachedColumnWidth > 0) return cachedColumnWidth;
                    const firstWrapper = imageGrid.querySelector('.danbooru-image-wrapper');
                    if (firstWrapper && firstWrapper.clientWidth > 0) {
                        cachedColumnWidth = firstWrapper.clientWidth;
                        return cachedColumnWidth;
                    }
                    const cols = window.getComputedStyle(imageGrid).gridTemplateColumns.split(' ');
                    const px = parseFloat(cols[0]);
                    if (px > 0) cachedColumnWidth = px;
                    return cachedColumnWidth;
                };
                const computeSpanFromDims = (imgW, imgH) => {
                    const colW = getColumnWidth();
                    if (!colW || !imgW || !imgH) return 0;
                    const cs = window.getComputedStyle(imageGrid);
                    const rowGap = parseInt(cs.gridRowGap) || parseInt(cs.rowGap) || 5;
                    const rowHeight = parseInt(cs.gridAutoRows) || 1;
                    const maxHeight = parseFloat(cs.getPropertyValue('--danbooru-thumb-max-height')) || 320;
                    const renderedH = Math.max(120, Math.min(maxHeight, Math.max(0, colW - 4) * (imgH / imgW)) + 4);
                    return Math.ceil((renderedH + rowGap) / (rowHeight + rowGap));
                };
                // Coalesce rapid onload calls (rate-limited loads fire 200ms apart; batching
                // to one reflow per frame avoids N² layout work as the page fills in).
                let resizeGridTimer = null;
                const scheduleResizeGrid = () => {
                    if (resizeGridTimer) return;
                    resizeGridTimer = requestAnimationFrame(() => {
                        resizeGridTimer = null;
                        resizeGrid();
                    });
                };

                const showEditPanel = (post) => {
                    // 在打开编辑面板时，检查当前图像是否被选中
                    // 强制将当前编辑的图像设置为选中状态，并更新 selectionWidget
                    const currentSelectedElement = imageGrid.querySelector('.danbooru-image-wrapper.selected');
                    if (currentSelectedElement && currentSelectedElement.dataset.postId && currentSelectedElement.dataset.postId != post.id) { // 检查 dataset.postId 是否存在
                        currentSelectedElement.classList.remove('selected');

                    }
                    const targetWrapper = imageGrid.querySelector(`.danbooru-image-wrapper[data-post-id="${post.id}"]`);
                    if (targetWrapper) {
                        targetWrapper.classList.add('selected');
                        // 触发一次点击事件来更新 selectionWidget
                        // 注意：这里直接调用 onclick 可能会导致事件冒泡问题，
                        // 更好的方式是直接更新 selectionWidget 的值
                        // targetWrapper.querySelector('img').click();
                        // 而是直接更新 selectionWidget
                        const imageUrl = post.file_url || post.large_file_url;
                        const selectedCategories = Array.from(categoryDropdown.querySelectorAll("input:checked")).map(i => i.name);
                        const postToUse = temporaryTagEdits[post.id] || post;
                        let output_tags = [];
                        selectedCategories.forEach(category => {
                            const tags = postToUse[`tag_string_${category}`];
                            if (tags) {
                                output_tags.push(...tags.split(' '));
                            }
                        });
                        let tagsToProcess = (output_tags.length > 0) ? output_tags : (postToUse.tag_string || '').split(' ');
                        if (filterEnabled && currentFilterTags.length > 0) {
                            const filterTagsLower = currentFilterTags.map(tag => tag.toLowerCase().trim());
                            tagsToProcess = tagsToProcess.filter(tag => {
                                const tagLower = tag.toLowerCase().trim();
                                return !filterTagsLower.includes(tagLower);
                            });
                        }
                        const escapeBrackets = formattingDropdown.querySelector('[name="escapeBrackets"]').checked;
                        const replaceUnderscores = formattingDropdown.querySelector('[name="replaceUnderscores"]').checked;
                        const processedTags = tagsToProcess.map(tag => {
                            let processedTag = tag;
                            if (replaceUnderscores) {
                                processedTag = processedTag.replace(/_/g, ' ');
                            }
                            if (escapeBrackets) {
                                processedTag = processedTag.replaceAll('(', '\\(').replaceAll(')', '\\)');
                            }
                            return processedTag;
                        });
                        const prompt = processedTags.join(', ');
                        const selection = {
                            prompt: prompt,
                            image_url: imageUrl,
                        };
                        if (nodeInstance && nodeInstance.widgets) {
                            const selectionWidget = nodeInstance.widgets.find(w => w.name === "selection_data");
                            if (selectionWidget) {
                                commitSelectionData(selection);
                                selectionWidget.callback();

                            }
                        }
                    }
                    const isPostCurrentlySelected = true; // 因为我们已经强制选中了


                    if (!temporaryTagEdits[post.id] || normalizeSource(temporaryTagEdits[post.id].source_site||temporaryTagEdits[post.id].source||currentSource)!==normalizeSource(post.source_site||post.source||currentSource)) {
                        // Create a deep copy for editing if it doesn't exist
                        temporaryTagEdits[post.id] = JSON.parse(JSON.stringify(post));
                    }
                    const editablePost = temporaryTagEdits[post.id];

                    // Panel container
                    const panel = $el("div.danbooru-edit-panel", {
                        style: {
                            position: "fixed", top: "0", left: "0", width: "100%", height: "100%",
                            backgroundColor: "rgba(0, 0, 0, 0.7)", zIndex: "10001",
                            display: "flex", alignItems: "center", justifyContent: "center"
                        }
                    });

                    // Panel content
                    const content = $el("div.danbooru-edit-panel-content", {
                        style: {
                            backgroundColor: "var(--comfy-menu-bg)", border: "1px solid var(--input-border-color)",
                            borderRadius: "12px", padding: "20px", width: "700px", maxWidth: "90vw",
                            maxHeight: "80vh", display: "flex", flexDirection: "column",
                            boxShadow: "0 8px 32px rgba(0, 0, 0, 0.3)"
                        }
                    });

                    // Title
                    const titleBar = $el("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "15px" } }, [
                        $el("h2", { textContent: t('editPanelTitle'), style: { margin: "0", color: "var(--comfy-input-text)", fontSize: "1.3em" } }),
                        $el("button.danbooru-edit-panel-close-button", {
                            innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`,
                            title: t('close'),
                            onclick: () => closePanel(isPostCurrentlySelected) // 将捕获到的选中状态传递给 closePanel
                        })
                    ]);

                    const tagsContainer = $el("div.danbooru-edit-tags-container", { style: { overflowY: "auto", flex: "1", paddingRight: "10px" } });

                    const closePanel = (wasSelectedOnOpen) => { // 接收打开面板时的选中状态
                        panel.remove();
                        const currentPostInArray = posts.find(p => p.id == post.id); // 获取posts数组中最新的post数据
                        if (!currentPostInArray) {
                            return;
                        }

                        // 准备数据，如果被编辑过则使用临时数据
                        let postDataToRender = temporaryTagEdits[post.id];

                        // 获取原始数据，用于比较
                        const originalPost = originalPostCache[post.id];

                        // 检查是否有实际编辑
                        let hasActualEdits = false;
                        if (postDataToRender && originalPost) {
                            const categories = ["artist", "copyright", "character", "general", "meta"];
                            for (const category of categories) {
                                if (!compareTagStrings(originalPost[`tag_string_${category}`], postDataToRender[`tag_string_${category}`])) {
                                    hasActualEdits = true;
                                    break;
                                }
                            }
                            if (!hasActualEdits && !compareTagStrings(originalPost.tag_string, postDataToRender.tag_string)) {
                                hasActualEdits = true;
                            }
                        }

                        if (hasActualEdits) {
                            // 如果有实际编辑，用编辑后的数据更新posts数组
                            const postIndex = posts.findIndex(p => p.id == post.id);
                            if (postIndex !== -1) {
                                posts[postIndex] = JSON.parse(JSON.stringify(postDataToRender)); // 确保深拷贝
                            }
                        } else {
                            // 如果没有实际编辑，清理临时副本
                            temporaryTagEdits[post.id] = undefined;
                            postDataToRender = currentPostInArray; // 确保渲染时使用 posts 数组中的当前数据
                        }

                        // 重新渲染该post
                        const oldPostElement = imageGrid.querySelector(`.danbooru-image-wrapper[data-post-id="${post.id}"]`);

                        const postIndex = posts.findIndex(p => p.id == post.id);
                        const newPostElement = createPostElement(posts[postIndex]); // 使用 posts 数组中的最新数据
                        if (newPostElement) {
                            if (oldPostElement && oldPostElement.parentNode) {
                                oldPostElement.parentNode.replaceChild(newPostElement, oldPostElement);
                            } else {
                                imageGrid.prepend(newPostElement);
                            }
                            resizeGrid();
                        } else {
                            if (oldPostElement) {
                                oldPostElement.remove();
                            }
                        }

                        // 无论是否编辑，如果打开面板时是选中状态，都强制更新selectionWidget和选中样式
                        if (wasSelectedOnOpen) {
                            const postToUpdate = posts[postIndex] || currentPostInArray;
                            const imageUrl = postToUpdate.file_url || postToUpdate.large_file_url;
                            const selectedCategories = Array.from(categoryDropdown.querySelectorAll("input:checked")).map(i => i.name);

                            let output_tags = [];
                            selectedCategories.forEach(category => {
                                const tags = postToUpdate[`tag_string_${category}`];
                                if (tags) {
                                    output_tags.push(...tags.split(' '));
                                }
                            });

                            let tagsToProcess = (output_tags.length > 0) ? output_tags : (postToUpdate.tag_string || '').split(' ');

                            // 应用提示词过滤
                            if (filterEnabled && currentFilterTags.length > 0) {
                                const filterTagsLower = currentFilterTags.map(tag => tag.toLowerCase().trim());
                                tagsToProcess = tagsToProcess.filter(tag => {
                                    const tagLower = tag.toLowerCase().trim();
                                    return !filterTagsLower.includes(tagLower);
                                });
                            }

                            const escapeBrackets = formattingDropdown.querySelector('[name="escapeBrackets"]').checked;
                            const replaceUnderscores = formattingDropdown.querySelector('[name="replaceUnderscores"]').checked;

                            // 格式化处理
                            const processedTags = tagsToProcess.map(tag => {
                                let processedTag = tag;
                                if (replaceUnderscores) {
                                    processedTag = processedTag.replace(/_/g, ' ');
                                }
                                if (escapeBrackets) {
                                    processedTag = processedTag.replaceAll('(', '\\(').replaceAll(')', '\\)');
                                }
                                return processedTag;
                            });

                            const prompt = processedTags.join(', ');

                            const selection = {
                                prompt: prompt,
                                image_url: imageUrl,
                            };

                            if (nodeInstance && nodeInstance.widgets) {
                                const selectionWidget = nodeInstance.widgets.find(w => w.name === "selection_data");
                                if (selectionWidget) {
                                    commitSelectionData(selection);
                                    selectionWidget.callback(); // 触发回调，通知ComfyUI值已更新
                                }
                            }
                            // 重新给新元素添加选中状态
                            if (newPostElement) {
                                newPostElement.classList.add('selected');

                            }
                        } else { // 如果打开面板时未选中，则清除所有选中的图像和提示词

                            imageGrid.querySelectorAll('.danbooru-image-wrapper.selected').forEach(w => {

                                w.classList.remove('selected');
                            });
                            if (nodeInstance && nodeInstance.widgets) {
                                const selectionWidget = nodeInstance.widgets.find(w => w.name === "selection_data");
                                if (selectionWidget) {
                                    commitSelectionData({});
                                    selectionWidget.callback();

                                }
                            }
                        }

                        // 重新计算 isTrulyEdited 状态并更新指示器 (这里调用 updateEditedStatus 会基于新的逻辑进行判断)
                        // 注意：这里不再需要手动删除 temporaryTagEdits，因为 updateEditedStatus 会在判断为未编辑时将其设置为 undefined
                        let indicator = newPostElement ? newPostElement.querySelector('.danbooru-edited-indicator') : null;
                        if (newPostElement) {
                            // 确保 newPostElement 已经添加到 DOM 中，updateEditedStatus 才能找到 indicator
                            // 或者直接传递 isTrulyEdited 状态
                            updateEditedStatus(newPostElement, post.id); // 调用更新函数
                        }
                    };

                    content.appendChild(titleBar);
                    content.appendChild(tagsContainer);

                    // Add a footer for action buttons
                    const editPanelFooter = $el("div", {
                        style: {
                            display: "flex",
                            justifyContent: "flex-end", // Changed to align items to the end (right)
                            alignItems: "center",
                            marginTop: "15px",
                            paddingTop: "15px",
                            borderTop: "1px solid var(--input-border-color)",
                            gap: "10px", // Add some gap between buttons
                        }
                    });

                    // "Copy Tags to Clipboard" button
                    const copyTagsButton = $el("button", {
                        innerHTML: `📋 ${t('copyTags')}`,
                        style: {
                            padding: "8px 15px",
                            border: "1px solid #7B68EE",
                            borderRadius: "6px",
                            backgroundColor: "transparent",
                            color: "#7B68EE",
                            cursor: "pointer",
                            fontSize: "14px",
                            fontWeight: "500",
                            transition: "all 0.2s ease"
                        },
                        onclick: async () => {
                            const tagsToCopy = [];
                            // Collect selected categories from checkboxes
                            const selectedCategoriesCheckboxes = panel.querySelectorAll('.danbooru-edit-category-checkbox:checked');
                            const selectedCategoriesToCopy = Array.from(selectedCategoriesCheckboxes).map(cb => cb.name);

                            // Collect tags from the editable post, respecting selected categories
                            const categories = ["artist", "copyright", "character", "general", "meta"];
                            const postToCopy = temporaryTagEdits[post.id] || post;

                            categories.forEach(category => {
                                if (selectedCategoriesToCopy.includes(category)) { // Only include if category is selected
                                    const tags = postToCopy[`tag_string_${category}`];
                                    if (tags) {
                                        tagsToCopy.push(...tags.split(' '));
                                    }
                                }
                            });

                            if (tagsToCopy.length > 0) {
                                // 获取格式化选项
                                const escapeBrackets = formattingDropdown.querySelector('[name="escapeBrackets"]').checked;
                                const replaceUnderscores = formattingDropdown.querySelector('[name="replaceUnderscores"]').checked;

                                // 格式化标签
                                const processedTags = tagsToCopy.map(tag => {
                                    let processedTag = tag;
                                    if (replaceUnderscores) {
                                        processedTag = processedTag.replace(/_/g, ' ');
                                    }
                                    if (escapeBrackets) {
                                        processedTag = processedTag.replaceAll('(', '\\(').replaceAll(')', '\\)');
                                    }
                                    return processedTag;
                                });

                                const formattedTags = processedTags.join(', ');

                                try {
                                    await navigator.clipboard.writeText(formattedTags);
                                    showToast(t('copyTagsSuccess'), 'success', copyTagsButton);
                                } catch (err) {
                                    showToast(t('copyTagsFail'), 'error', copyTagsButton);
                                    logger.error('Failed to copy: ', err);
                                }
                            } else {
                                showToast(t('noTagsToCopy'), 'info', copyTagsButton);
                            }
                        }
                    });
                    editPanelFooter.appendChild(copyTagsButton);

                    // "Reset Tags" button (moved and restyled)
                    const resetTagsButton = $el("button.danbooru-reset-tags-button", {
                        innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg> ${t('resetTags')}`,
                        title: t('resetTags'),
                        onclick: async () => {
                            // 1. 从缓存中获取原始post数据
                            const originalPostData = originalPostCache[post.id];

                            if (originalPostData) {
                                // 2. Update posts array with original data
                                const postIndex = posts.findIndex(p => p.id === post.id);
                                if (postIndex !== -1) {
                                    posts[postIndex] = JSON.parse(JSON.stringify(originalPostData)); // 确保深拷贝
                                }

                                // 3. Clear temporaryTagEdits for this post
                                temporaryTagEdits[post.id] = undefined;

                                // 4. Re-render tags in the panel with the original data
                                renderTagsInPanel(tagsContainer, originalPostData, panel);

                                // 5. Update "edited" indicator on the main grid item
                                const wrapperElement = imageGrid.querySelector(`.danbooru-image-wrapper[data-post-id="${post.id}"]`);
                                if (wrapperElement) {
                                    updateEditedStatus(wrapperElement, originalPostData.id);
                                }

                                // 6. Update selectionWidget if the post is currently selected
                                if (isPostCurrentlySelected) {
                                    const imageUrl = originalPostData.file_url || originalPostData.large_file_url;
                                    const selectedCategories = Array.from(categoryDropdown.querySelectorAll("input:checked")).map(i => i.name);
                                    let output_tags = [];
                                    selectedCategories.forEach(category => {
                                        const tags = originalPostData[`tag_string_${category}`];
                                        if (tags) {
                                            output_tags.push(...tags.split(' '));
                                        }
                                    });
                                    let tagsToProcess = (output_tags.length > 0) ? output_tags : (originalPostData.tag_string || '').split(' ');
                                    if (filterEnabled && currentFilterTags.length > 0) {
                                        const filterTagsLower = currentFilterTags.map(tag => tag.toLowerCase().trim());
                                        tagsToProcess = tagsToProcess.filter(tag => {
                                            const tagLower = tag.toLowerCase().trim();
                                            return !filterTagsLower.includes(tagLower);
                                        });
                                    }
                                    const escapeBrackets = formattingDropdown.querySelector('[name="escapeBrackets"]').checked;
                                    const replaceUnderscores = formattingDropdown.querySelector('[name="replaceUnderscores"]').checked;
                                    const processedTags = tagsToProcess.map(tag => {
                                        let processedTag = tag;
                                        if (replaceUnderscores) {
                                            processedTag = processedTag.replace(/_/g, ' ');
                                        }
                                        if (escapeBrackets) {
                                            processedTag = processedTag.replaceAll('(', '\\(').replaceAll(')', '\\)');
                                        }
                                        return processedTag;
                                    });
                                    const prompt = processedTags.join(', ');
                                    const selection = {
                                        prompt: prompt,
                                        image_url: imageUrl,
                                    };
                                    if (nodeInstance && nodeInstance.widgets) {
                                        const selectionWidget = nodeInstance.widgets.find(w => w.name === "selection_data");
                                        if (selectionWidget) {
                                            commitSelectionData(selection);
                                            selectionWidget.callback();

                                        }
                                    }
                                }
                                showToast(t('resetTags') + '成功', 'success', resetTagsButton);
                            } else {
                                // 如果缓存中没有原始数据，尝试从服务器获取一次
                                const fetchedOriginalPost = await fetchOriginalPost(post.id);
                                if (fetchedOriginalPost) {
                                    originalPostCache[post.id] = JSON.parse(JSON.stringify(fetchedOriginalPost)); // 缓存获取到的数据
                                    // 再次调用自身，以使用缓存中的数据进行重置
                                    showToast('已从服务器获取原始标签，请再次点击重置。', 'info', resetTagsButton);
                                    // 重新渲染面板
                                    renderTagsInPanel(tagsContainer, originalPostCache[post.id], panel);
                                } else {
                                    showError('未能获取原始标签，请检查网络或稍后重试。', false, resetTagsButton);
                                }
                            }
                        }
                    });
                    editPanelFooter.appendChild(resetTagsButton);

                    content.appendChild(editPanelFooter);
                    panel.appendChild(content);

                    // Close panel when clicking background
                    panel.addEventListener('click', (e) => {
                        if (e.target === panel) {
                            closePanel();
                        }
                    });

                    document.body.appendChild(panel);

                    renderTagsInPanel(tagsContainer, editablePost, panel);
                };

                const renderTagsInPanel = async (tagsContainer, postData, panel) => {
                    tagsContainer.innerHTML = ''; // Clear existing tags

                    const createClickableTagSpan = (tag, category, translation = null) => {
                        const displayText = translation ? `${tag} [${translation}]` : tag;
                        const span = $el("span", {
                            textContent: displayText,
                            className: `danbooru-tooltip-tag danbooru-clickable-tag tag-category-${category}`,
                        });

                        const removeExistingMenus = () => {
                            document.querySelectorAll('.danbooru-tag-context-menu').forEach(menu => menu.remove());
                        };

                        span.addEventListener('click', (e) => {
                            e.stopPropagation();
                            removeExistingMenus();

                            const menu = $el("div.danbooru-tag-context-menu", {
                                style: {
                                    position: 'absolute',
                                    zIndex: '10002',
                                    backgroundColor: 'var(--comfy-menu-bg)',
                                    border: '1px solid var(--input-border-color)',
                                    borderRadius: '6px',
                                    boxShadow: '0 2px 10px rgba(0,0,0,0.3)',
                                    padding: '5px',
                                }
                            });

                            const searchOption = $el("div.danbooru-context-menu-item", {
                                textContent: '🔍 ' + t('search'),
                                onclick: () => {
                                    const currentVal = searchInput.value.trim();
                                    const apiTag = tag.replace(/\s+/g, '_');
                                    let newValue;
                                    if (currentVal && !/,\s*$/.test(currentVal)) {
                                        newValue = `${currentVal}, ${apiTag}, `;
                                    } else if (currentVal) {
                                        newValue = `${currentVal} ${apiTag}, `;
                                    } else {
                                        newValue = `${apiTag}, `;
                                    }
                                    searchInput.value = newValue;
                                    searchInput.dispatchEvent(new Event('input'));
                                    fetchAndRender(true);
                                    menu.remove();
                                }
                            });

                            const deleteOption = $el("div.danbooru-context-menu-item", {
                                textContent: '🗑️ ' + t('delete'),
                                onclick: () => {
                                    if (postData[`tag_string_${category}`]) {
                                        const tags = postData[`tag_string_${category}`].split(' ');
                                        const index = tags.indexOf(tag);
                                        if (index > -1) {
                                            tags.splice(index, 1);
                                            postData[`tag_string_${category}`] = tags.join(' ');
                                        }
                                    }
                                    // 强制重新渲染以更新状态
                                    renderTagsInPanel(tagsContainer, temporaryTagEdits[postData.id] || postData, panel);
                                    menu.remove();
                                }
                            });

                            menu.appendChild(searchOption);
                            menu.appendChild(deleteOption);

                            document.body.appendChild(menu);

                            const rect = span.getBoundingClientRect();
                            menu.style.left = `${rect.left}px`;
                            menu.style.top = `${rect.bottom + 5}px`;

                            const closeMenuHandler = (event) => {
                                if (!menu.contains(event.target)) {
                                    menu.remove();
                                    document.removeEventListener('click', closeMenuHandler, true);
                                }
                            };
                            document.addEventListener('click', closeMenuHandler, true);
                        });

                        return span;
                    };

                    const categoryOrder = ["artist", "copyright", "character", "general", "meta"];
                    const categorizedTags = { artist: new Set(), copyright: new Set(), character: new Set(), general: new Set(), meta: new Set() };

                    if (postData.tag_string_artist) postData.tag_string_artist.split(' ').forEach(t => categorizedTags.artist.add(t));
                    if (postData.tag_string_copyright) postData.tag_string_copyright.split(' ').forEach(t => categorizedTags.copyright.add(t));
                    if (postData.tag_string_character) postData.tag_string_character.split(' ').forEach(t => categorizedTags.character.add(t));
                    if (postData.tag_string_general) postData.tag_string_general.split(' ').forEach(t => categorizedTags.general.add(t));
                    if (postData.tag_string_meta) postData.tag_string_meta.split(' ').forEach(t => categorizedTags.meta.add(t));

                    if (Object.values(categorizedTags).every(s => s.size === 0) && postData.tag_string) {
                        postData.tag_string.split(' ').forEach(t => categorizedTags.general.add(t));
                    }

                    const allTags = Array.from(new Set(categoryOrder.flatMap(cat => Array.from(categorizedTags[cat])))).filter(Boolean);

                    let translations = {};
                    if (globalMultiLanguageManager.getLanguage() === 'zh' && allTags.length > 0) {
                        try {
                            const response = await fetch('/danbooru_gallery/translate_tags_batch', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ tags: allTags })
                            });
                            const data = await response.json();
                            if (data.success) translations = data.translations;
                        } catch (error) { logger.warn("Tag translation failed for edit panel:", error); }
                    }

                    categoryOrder.forEach(categoryName => {
                        const tags = categorizedTags[categoryName];
                        if (tags.size > 0) {
                            const section = $el("div.danbooru-edit-panel-section"); // Changed class name for clarity

                            // Add a checkbox for each category in the edit panel
                            const categoryCheckboxId = `edit-panel-category-${categoryName}`;
                            const categoryCheckbox = $el("input", {
                                type: "checkbox",
                                id: categoryCheckboxId,
                                name: categoryName,
                                checked: categoryName === 'copyright' || categoryName === 'character' || categoryName === 'general', // Default to checked only for copyright, character, and general
                                className: "danbooru-edit-category-checkbox"
                            });
                            const categoryLabel = $el("label", {
                                htmlFor: categoryCheckboxId,
                                textContent: t(categoryName),
                                style: { marginLeft: "5px", fontWeight: "600", color: "#b0b3b8" } // Style to match header
                            });

                            const categoryHeader = $el("div", { style: { display: "flex", alignItems: "center", marginBottom: "4px" } }, [categoryCheckbox, categoryLabel]);
                            section.appendChild(categoryHeader);
                            const tagsWrapper = $el("div.danbooru-tooltip-tags-wrapper");
                            tags.forEach(tag => {
                                if (!tag) return;
                                const translation = translations[tag];
                                tagsWrapper.appendChild(createClickableTagSpan(tag, categoryName, translation));
                            });

                            // Add "+" button for adding new tags
                            const addButton = $el("button.danbooru-add-tag-button", {
                                textContent: "+",
                                title: t('addTag'),
                                onclick: (e) => {
                                    e.stopPropagation();
                                    addButton.style.display = 'none'; // Hide the add button

                                    const inputContainer = $el("div.danbooru-add-tag-container");
                                    const input = $el("input.danbooru-add-tag-input", { type: "text", placeholder: t('addTag') + "..." });

                                    inputContainer.appendChild(input);
                                    tagsWrapper.appendChild(inputContainer);

                                    input.focus();

                                    // 创建智能补全实例
                                    const tagAutocomplete = new AutocompleteUI({
                                        inputElement: input,
                                        language: globalMultiLanguageManager.getLanguage(),
                                        sourceProvider: () => currentSource,
                                        maxSuggestions: uiSettings.autocomplete_max_results || 20,
                                        customClass: 'danbooru-tag-editor-autocomplete',
                                        formatTag: (tag) => {
                                            // 应用格式化设置
                                            let processedTag = tag;
                                            if (uiSettings.formatting && uiSettings.formatting.replaceUnderscores) {
                                                processedTag = processedTag.replace(/_/g, ' ');
                                            }
                                            if (uiSettings.formatting && uiSettings.formatting.escapeBrackets) {
                                                processedTag = processedTag.replaceAll('(', '\\(').replaceAll(')', '\\)');
                                            }
                                            return processedTag;
                                        },
                                        onSelect: (selectedTag) => {
                                            const newTag = selectedTag.trim().replace(/\s/g, '_');
                                            if (newTag) {
                                                const tagStringKey = `tag_string_${categoryName}`;
                                                const currentTags = postData[tagStringKey] ? postData[tagStringKey].split(' ') : [];
                                                if (!currentTags.includes(newTag)) {
                                                    currentTags.push(newTag);
                                                    postData[tagStringKey] = currentTags.join(' ');
                                                }
                                                // 强制重新渲染以更新状态
                                                renderTagsInPanel(tagsContainer, temporaryTagEdits[postData.id] || postData, panel);
                                            }
                                            tagAutocomplete.destroy();
                                            inputContainer.remove();
                                            addButton.style.display = 'inline-flex';
                                        }
                                    });

                                    input.addEventListener('keydown', (e) => {
                                        if (e.key === 'Enter' && input.value.trim()) {
                                            const newTag = input.value.trim().replace(/\s/g, '_');
                                            if (newTag) {
                                                const tagStringKey = `tag_string_${categoryName}`;
                                                const currentTags = postData[tagStringKey] ? postData[tagStringKey].split(' ') : [];
                                                if (!currentTags.includes(newTag)) {
                                                    currentTags.push(newTag);
                                                    postData[tagStringKey] = currentTags.join(' ');
                                                }
                                                renderTagsInPanel(tagsContainer, temporaryTagEdits[postData.id] || postData, panel);
                                            }
                                            tagAutocomplete.destroy();
                                            inputContainer.remove();
                                            addButton.style.display = 'inline-flex';
                                        } else if (e.key === 'Escape') {
                                            tagAutocomplete.destroy();
                                            inputContainer.remove();
                                            addButton.style.display = 'inline-flex';
                                        }
                                    });

                                    const blurHandler = () => {
                                        // 延迟以便点击建议能够注册
                                        setTimeout(() => {
                                            if (!inputContainer.contains(document.activeElement)) {
                                                tagAutocomplete.destroy();
                                                inputContainer.remove();
                                                addButton.style.display = 'inline-flex';
                                            }
                                        }, 200);
                                    };
                                    input.addEventListener('blur', blurHandler);
                                }
                            });
                            tagsWrapper.appendChild(addButton);

                            section.appendChild(tagsWrapper);
                            tagsContainer.appendChild(section);
                        }
                    });

                    // After rendering, check if the post is edited and update the main grid item
                    const postElement = imageGrid.querySelector(`.danbooru-image-wrapper[data-post-id="${postData.id}"]`);
                    if (postElement) {
                        updateEditedStatus(postElement, postData.id);
                    }
                };

                // V52: Civitai detail resolution is shared by hover, selection and export.
                // Keep a page-level cache and one in-flight Promise per image so repeated UI events
                // never send duplicate requests or stack success toasts.
                const civitaiPromptResolveCache = new Map();
                const civitaiPromptResolveInflight = new Map();
                const CIVITAI_RESOLVE_SUCCESS_TTL = 6 * 60 * 60 * 1000;
                const CIVITAI_RESOLVE_FAILURE_TTL = 60 * 1000;

                const getCivitaiResolveKey = (postData) => {
                    if (!postData) return '';
                    const imageUrl = postData.file_url || postData.large_file_url || postData.preview_file_url || '';
                    return String(
                        postData.civitai_image_id ||
                        postData.id ||
                        postData.civitai_post_id ||
                        imageUrl ||
                        ''
                    ).trim();
                };

                const applyCivitaiResolvePatch = (postData, patch) => {
                    if (!postData || !patch || typeof patch !== 'object') return;
                    if (patch.civitai_prompt) postData.civitai_prompt = patch.civitai_prompt;
                    if (patch.civitai_negative_prompt) postData.civitai_negative_prompt = patch.civitai_negative_prompt;
                    if (patch.civitai_prompt_source) postData.civitai_prompt_source = patch.civitai_prompt_source;
                    if (patch.civitai_meta && !postData.civitai_meta) postData.civitai_meta = patch.civitai_meta;
                    if (patch.civitai_image_id && !postData.civitai_image_id) postData.civitai_image_id = patch.civitai_image_id;
                    if (patch.civitai_post_id && !postData.civitai_post_id) postData.civitai_post_id = patch.civitai_post_id;

                    const tagKeys = [
                        'tag_string', 'tag_string_artist', 'tag_string_copyright',
                        'tag_string_character', 'tag_string_general', 'tag_string_meta',
                        'civitai_content_tags'
                    ];
                    tagKeys.forEach((key) => {
                        if ((patch[key] || '').trim()) postData[key] = patch[key];
                    });
                    if (typeof patch.civitai_has_content_tags === 'boolean') {
                        postData.civitai_has_content_tags = patch.civitai_has_content_tags;
                    }
                    if (Array.isArray(patch.civitai_tag_names)) {
                        postData.civitai_tag_names = patch.civitai_tag_names;
                    }

                    if (originalPostCache[postData.id]) {
                        Object.assign(originalPostCache[postData.id], {
                            civitai_prompt: postData.civitai_prompt,
                            civitai_negative_prompt: postData.civitai_negative_prompt,
                            civitai_prompt_source: postData.civitai_prompt_source,
                            civitai_meta: postData.civitai_meta,
                            civitai_image_id: postData.civitai_image_id,
                            civitai_post_id: postData.civitai_post_id,
                            civitai_has_content_tags: postData.civitai_has_content_tags,
                            civitai_tag_names: postData.civitai_tag_names,
                            ...Object.fromEntries(tagKeys.map((key) => [key, postData[key]])),
                        });
                    }
                };

                const resolveCivitaiPromptIfMissing = async (postData) => {
                    if (!postData || !(postData.source_site === "civitai" || postData.source === "civitai")) return postData;

                    const hasPrompt = Boolean((postData.civitai_prompt || "").trim() || (postData.civitai_negative_prompt || "").trim());
                    const hasContentTags = postData.civitai_has_content_tags === true || Boolean((postData.civitai_content_tags || "").trim());
                    if (hasPrompt && hasContentTags && postData.civitai_prompt_source !== "filename_fallback") return postData;

                    const resolveKey = getCivitaiResolveKey(postData);
                    if (!resolveKey) return postData;

                    const now = Date.now();
                    const cached = civitaiPromptResolveCache.get(resolveKey);
                    if (cached && cached.expiresAt > now) {
                        postData._civitaiPromptResolveTried = true;
                        if (cached.success && cached.post) applyCivitaiResolvePatch(postData, cached.post);
                        return postData;
                    }
                    if (cached) civitaiPromptResolveCache.delete(resolveKey);

                    // A new render can create a new post object for the same image. The Map is keyed
                    // by the real image id, so all such objects await the same network operation.
                    let requestPromise = civitaiPromptResolveInflight.get(resolveKey);
                    if (!requestPromise) {
                        const params = new URLSearchParams();
                        if (postData.id) params.set('id', postData.id);
                        if (postData.civitai_image_id) params.set('image_id', postData.civitai_image_id);
                        if (postData.civitai_post_id) params.set('post_id', postData.civitai_post_id);
                        const imageUrl = postData.file_url || postData.large_file_url || postData.preview_file_url || '';
                        if (imageUrl) params.set('image_url', imageUrl);
                        if (postData.civitai_remote_favorited || postData.civitai_remote_collection_id) {
                            params.set('favorite', '1');
                        }

                        requestPromise = (async () => {
                            const controller = new AbortController();
                            const timeoutId = setTimeout(() => controller.abort(), 25000);
                            try {
                                const resp = await fetch(`/danbooru_gallery/civitai_prompt?${params.toString()}`, {
                                    signal: controller.signal,
                                });
                                const data = await resp.json();
                                return data;
                            } finally {
                                clearTimeout(timeoutId);
                            }
                        })();
                        civitaiPromptResolveInflight.set(resolveKey, requestPromise);
                        requestPromise.finally(() => {
                            if (civitaiPromptResolveInflight.get(resolveKey) === requestPromise) {
                                civitaiPromptResolveInflight.delete(resolveKey);
                            }
                        }).catch(() => {});
                    }

                    postData._civitaiPromptResolving = true;
                    try {
                        const data = await requestPromise;
                        postData._civitaiPromptResolveTried = true;
                        if (data?.success && data?.post) {
                            applyCivitaiResolvePatch(postData, data.post);
                            civitaiPromptResolveCache.set(resolveKey, {
                                success: true,
                                post: data.post,
                                source: data.source || '',
                                expiresAt: Date.now() + CIVITAI_RESOLVE_SUCCESS_TTL,
                            });
                            // Background metadata resolution is deliberately silent. Hovering or
                            // selecting several cards should not produce a stream of success toasts.
                            logger.debug?.('C站提示词/Tags已解析:', data.source || 'unknown', data.cached ? '(cache)' : '');
                        } else {
                            civitaiPromptResolveCache.set(resolveKey, {
                                success: false,
                                post: null,
                                expiresAt: Date.now() + CIVITAI_RESOLVE_FAILURE_TTL,
                            });
                            logger.debug?.('C站图片没有可公开解析的 prompt/Tags');
                        }
                    } catch (e) {
                        postData._civitaiPromptResolveTried = true;
                        civitaiPromptResolveCache.set(resolveKey, {
                            success: false,
                            post: null,
                            expiresAt: Date.now() + CIVITAI_RESOLVE_FAILURE_TTL,
                        });
                        if (e?.name !== 'AbortError') logger.warn('C站提示词懒加载失败:', e);
                    } finally {
                        postData._civitaiPromptResolving = false;
                    }
                    return postData;
                };

                const buildPageUrlForPost = (post) => {
                    const src = normalizeSource(post.source_site || post.source || currentSource);
                    const id = post.id || post.post_id;
                    if (src === 'civitai') {
                        return (post.civitai_url || (id ? `https://civitai.red/images/${id}` : '') || '').trim();
                    }
                    if (src === 'gelbooru') {
                        return (post.gelbooru_url || (id ? `https://gelbooru.com/index.php?page=post&s=view&id=${id}` : '') || '').trim();
                    }
                    if (src === 'yandere') {
                        return (post.yandere_url || (id ? `https://yande.re/post/show/${id}` : '') || '').trim();
                    }
                    return (post.danbooru_url || (id ? `https://danbooru.donmai.us/posts/${id}` : '') || '').trim();
                };

                // 辅助函数：为单个帖子构建提示词
                const buildPromptForPost = (postData) => {
                    const selectedCategories = Array.from(categoryDropdown.querySelectorAll("input:checked")).map(i => i.name);
                    const temporary=temporaryTagEdits[postData.id];
                    const postToUse = temporary&&normalizeSource(temporary.source_site||temporary.source||currentSource)===normalizeSource(postData.source_site||postData.source||currentSource)?temporary:postData;

                    if (urlExportMode) {
                        return buildPageUrlForPost(postToUse) || postToUse.source || postToUse.file_url || postToUse.large_file_url || postToUse.preview_file_url || '';
                    }

                    // Civitai 有完整生成 prompt 时保留原文；收藏接口经常只返回内容 Tags，
                    // 此时不能被模型/采样器信息提前截断，必须继续进入通用 Tags 导出链路。
                    const isCivitaiPost = postToUse.source_site === "civitai" || postToUse.source === "civitai";
                    let civitaiMetaFallback = '';
                    let civitaiPrompt = '';
                    if (isCivitaiPost) {
                        civitaiPrompt = (postToUse.civitai_prompt || "").trim();
                        const metaLines = [];
                        if (postToUse.civitai_model) metaLines.push(`Model: ${postToUse.civitai_model}`);
                        if (postToUse.civitai_model_version) metaLines.push(`Model version: ${postToUse.civitai_model_version}`);
                        if (postToUse.civitai_seed) metaLines.push(`Seed: ${postToUse.civitai_seed}`);
                        if (postToUse.civitai_sampler) metaLines.push(`Sampler: ${postToUse.civitai_sampler}`);
                        if (postToUse.civitai_steps) metaLines.push(`Steps: ${postToUse.civitai_steps}`);
                        if (postToUse.civitai_cfg) metaLines.push(`CFG: ${postToUse.civitai_cfg}`);
                        civitaiMetaFallback = metaLines.join('\n');
                        if (civitaiPrompt) {
                            const parts = [civitaiPrompt];
                            if (civitaiMetaFallback) parts.push(civitaiMetaFallback);
                            return parts.join('\n\n');
                        }
                    }

                    let output_tags = [];
                    selectedCategories.forEach(category => {
                        let tags = postToUse[`tag_string_${category}`];
                        // Civitai general 字段还混有模型/版本资源名。收藏图没有 prompt 时，
                        // 优先导出后端标记的纯内容 Tags。
                        if (isCivitaiPost && !civitaiPrompt && category === 'general' && (postToUse.civitai_content_tags || '').trim()) {
                            tags = postToUse.civitai_content_tags;
                        }
                        if (tags) {
                            output_tags.push(...tags.split(' '));
                        }
                    });

                    const civitaiContentFallback = isCivitaiPost ? (postToUse.civitai_content_tags || '').trim() : '';
                    let tagsToProcess = (output_tags.length > 0)
                        ? output_tags
                        : (civitaiContentFallback || postToUse.tag_string || '').split(' ');

                    // 应用提示词过滤
                    if (filterEnabled && currentFilterTags.length > 0) {
                        const filterTagsLower = currentFilterTags.map(tag => tag.toLowerCase().trim());
                        tagsToProcess = tagsToProcess.filter(tag => {
                            const tagLower = tag.toLowerCase().trim();
                            return !filterTagsLower.includes(tagLower);
                        });
                    }

                    const escapeBrackets = formattingDropdown.querySelector('[name="escapeBrackets"]').checked;
                    const replaceUnderscores = formattingDropdown.querySelector('[name="replaceUnderscores"]').checked;

                    // 格式化处理
                    const processedTags = tagsToProcess.map(tag => {
                        let processedTag = tag;
                        if (replaceUnderscores) {
                            processedTag = processedTag.replace(/_/g, ' ');
                        }
                        if (escapeBrackets) {
                            processedTag = processedTag.replaceAll('(', '\\(').replaceAll(')', '\\)');
                        }
                        return processedTag;
                    });

                    const tagOutput = processedTags.filter(Boolean).join(', ');
                    if (tagOutput) return tagOutput;
                    // Preserve the previous metadata-only fallback only when neither
                    // a prompt nor any actual content Tags could be resolved.
                    if (isCivitaiPost && civitaiMetaFallback) return civitaiMetaFallback;
                    return '';
                };

                // 辅助函数：收集所有选中图片的数据并更新 widget
                const updateSelectionData = () => {
                    const selectedWrappers = imageGrid.querySelectorAll('.danbooru-image-wrapper.selected');
                    const selections = [];

                    selectedWrappers.forEach(wrapper => {
                        const postId = wrapper.dataset.postId;
                        const postData = posts.find(p => p.id == postId) || temporaryTagEdits[postId];
                        if (postData) {
                            const imageUrl = postData.file_url || postData.large_file_url || postData.preview_file_url;
                            const prompt = buildPromptForPost(postData);
                            selections.push({
                                post_id: postId,
                                prompt: prompt,
                                image_url: imageUrl
                            });
                        }
                    });

                    const selectionData = { selections: selections };

                    // 更新 widget，并同步到后端兜底缓存，避免 Queue 时 selection_data 为空。
                    commitSelectionData(selectionData);

                    // 更新选中计数显示
                    updateSelectionCount(selections.length);
                };

                // 辅助函数：更新选中计数显示
                const updateSelectionCount = (count) => {
                    const countBadge = document.querySelector('.danbooru-selection-count');
                    if (countBadge) {
                        if (count > 0 && uiSettings.multi_select_enabled) {
                            countBadge.textContent = t('selectedCount').replace('{count}', count);
                            countBadge.style.display = 'inline-block';
                        } else {
                            countBadge.style.display = 'none';
                        }
                    }
                };

                // 辅助函数：清除所有选中
                const clearAllSelections = () => {
                    imageGrid.querySelectorAll('.danbooru-image-wrapper.selected').forEach(w => {
                        w.classList.remove('selected');
                    });
                    updateSelectionData();
                };


                // V22.1: image loading is a separate pipeline from /posts.
                // Do not mutate the upstream image URL for cache-busting; put the
                // cache-bust token on our proxy URL, otherwise Civitai CDN signed/
                // transformed URLs can fail.
                const getPostImageCandidates = (post) => {
                    if (!post || typeof post !== "object") return [];
                    const raw = [
                        post.preview_file_url,
                        post.preview_url,
                        post.thumbnailUrl,
                        post.large_file_url,
                        post.sample_url,
                        post.file_url,
                        post.image_url,
                    ];
                    const seen = new Set();
                    const urls = [];
                    for (const value of raw) {
                        const url = String(value || "").trim();
                        if (!/^https?:\/\//i.test(url)) continue;
                        if (seen.has(url)) continue;
                        seen.add(url);
                        urls.push(url);
                    }
                    return urls;
                };

                const toImageProxyUrl = (imageUrl, post, index = 0) => {
                    const u = new URL("/danbooru_gallery/image_proxy", window.location.origin);
                    u.searchParams.set("url", imageUrl);
                    u.searchParams.set("source", post?.source_site || currentSource || "");
                    u.searchParams.set("_", `${post?.md5 || post?.id || Date.now()}_${index}`);
                    return u.pathname + u.search;
                };

                const isYanderePost = (post) => {
                    const s = String(post?.source_site || post?.source || currentSource || "").toLowerCase();
                    return s === "yandere" || s === "yande.re";
                };

                const isCivitaiPost = (post) => {
                    const s = String(post?.source_site || post?.source || currentSource || "").toLowerCase();
                    return s === "civitai" || s === "civitai.red" || s === "civitai.com";
                };

                const isLegacyBooruPost = (post) => {
                    const s = String(post?.source_site || post?.source || currentSource || "").toLowerCase();
                    return s === "danbooru" || s === "donmai" || s === "gelbooru";
                };

                const toLegacyBooruProxyUrl = (imageUrl, post) => {
                    let url = String(imageUrl || "").trim();
                    if (!url) return "";
                    if (url.startsWith("//")) url = "https:" + url;
                    if (!/^https?:\/\//i.test(url)) return "";
                    const v = encodeURIComponent(post?.md5 || post?.id || Date.now());
                    const upstream = url + (url.includes("?") ? "&" : "?") + "v=" + v;
                    return `/danbooru_gallery/image_proxy?url=${encodeURIComponent(upstream)}`;
                };

                const getImageLoadCandidates = (post) => {
                    const upstreams = getPostImageCandidates(post);
                    const out = [];

                    // V45-DG-RESTORE:
                    // D/G use the exact old working pipeline: preview_file_url -> image_proxy.
                    // Do not direct-load D/G and do not use the newer multi-source candidate tree.
                    if (isLegacyBooruPost(post)) {
                        const src = toLegacyBooruProxyUrl(post.preview_file_url || upstreams[0], post);
                        if (src) out.push({ upstream: post.preview_file_url || upstreams[0], src, mode: "legacy_dg_proxy" });
                        return out;
                    }

                    upstreams.forEach((url, i) => {
                        // Civitai/Yande.re keep browser direct first, because this is what worked
                        // in the user's environment. Proxy is only fallback.
                        if (isYanderePost(post) || isCivitaiPost(post)) {
                            out.push({ upstream: url, src: url, mode: "direct" });
                            out.push({ upstream: url, src: toImageProxyUrl(url, post, i), mode: "proxy" });
                        } else {
                            out.push({ upstream: url, src: toImageProxyUrl(url, post, i), mode: "proxy" });
                        }
                    });
                    return out;
                };

                const recordImageLoadFailure = (post, candidates, lastUrl, reason = 'all_candidates_failed') => {
                    const record = {
                        at: new Date().toISOString(),
                        reason,
                        source: post?.source_site || currentSource || '',
                        id: post?.id || '',
                        post_url: post?.civitai_url || post?.post_url || '',
                        file_ext: post?.file_ext || '',
                        candidate_count: candidates?.length || 0,
                        candidates: (candidates || []).slice(0, 8),
                        last_url: lastUrl || '',
                    };
                    imageLoadFailureRecords.push(record);
                    if (imageLoadFailureRecords.length > 200) imageLoadFailureRecords.splice(0, imageLoadFailureRecords.length - 200);
                    return record;
                };

                const showImageLoadFailure = (wrapper, post, lastUrl, reason = 'all_candidates_failed', candidates = []) => {
                    wrapper.classList.add("danbooru-image-load-failed");
                    wrapper.dataset.imageLoadError = "1";
                    wrapper.style.position = wrapper.style.position || "relative";
                    wrapper.style.minHeight = wrapper.style.minHeight || "160px";
                    wrapper.style.background = wrapper.style.background || "rgba(80, 40, 40, 0.28)";
                    const record = recordImageLoadFailure(post, candidates, lastUrl, reason);
                    if (!wrapper.querySelector(".danbooru-image-load-error")) {
                        const badge = document.createElement("div");
                        badge.className = "danbooru-image-load-error";
                        badge.textContent = reason === 'no_image_candidates' ? "无可用图片URL" : "缩略图加载失败";
                        badge.title = `post=${post?.id || ""}
原因=${reason}
候选=${record.candidate_count}
最后失败URL：${lastUrl || ""}
请点 诊断/导出 -> C收藏诊断 查看后端 HTTP 细节`;
                        badge.style.cssText = [
                            "position:absolute", "left:6px", "right:6px", "bottom:6px", "z-index:6",
                            "padding:4px 6px", "border-radius:6px", "font-size:11px", "line-height:1.25",
                            "color:#fff", "background:rgba(180,40,40,.92)", "pointer-events:none", "text-align:center"
                        ].join(";");
                        wrapper.appendChild(badge);
                    }
                    scheduleResizeGrid();
                };

                const installImageFallbackLoader = (img, wrapper, post) => {
                    const upstreamCandidates = getPostImageCandidates(post);
                    const candidates = getImageLoadCandidates(post);
                    const LOAD_TIMEOUT_MS = isYanderePost(post) ? 20000 : 12000;
                    wrapper.dataset.imageCandidateCount = String(upstreamCandidates.length);
                    wrapper.dataset.imageLoadAttemptCount = String(candidates.length);
                    wrapper.dataset.imageLoadStatus = candidates.length ? "queued" : "no_candidates";
                    if (!candidates.length) {
                        showImageLoadFailure(wrapper, post, "", 'no_image_candidates', upstreamCandidates);
                        return;
                    }

                    let index = 0;
                    let finished = false;
                    const clearTimer = () => {
                        if (wrapper.__imageLoadTimer) {
                            clearTimeout(wrapper.__imageLoadTimer);
                            wrapper.__imageLoadTimer = null;
                        }
                    };
                    const failCurrent = (reason) => {
                        if (finished) return;
                        clearTimer();
                        const failed = candidates[index] || {};
                        recordImageLoadFailure(post, upstreamCandidates, failed.upstream || failed.src || '', reason || 'candidate_failed');
                        index += 1;
                        if (index < candidates.length) {
                            tryLoad(reason || 'fallback');
                        } else {
                            finished = true;
                            img.removeAttribute("src");
                            const last = candidates[candidates.length - 1] || {};
                            showImageLoadFailure(wrapper, post, last.upstream || last.src || '', reason === 'timeout' ? 'all_candidates_timeout_or_failed' : 'all_candidates_failed', upstreamCandidates);
                        }
                    };
                    const tryLoad = (fromReason = '') => {
                        clearTimer();
                        const candidate = candidates[index];
                        const upstreamUrl = candidate.upstream || candidate.src;
                        wrapper.dataset.imageCandidateIndex = String(index);
                        wrapper.dataset.currentImageUrl = upstreamUrl;
                        wrapper.dataset.currentImageSrcMode = candidate.mode || "proxy";
                        wrapper.dataset.imageLoadStatus = fromReason ? `fallback_after_${fromReason}` : "loading";
                        img.removeAttribute("src");
                        if ((candidate.mode || "") === "direct") {
                            img.referrerPolicy = "no-referrer";
                        } else {
                            img.removeAttribute("referrerpolicy");
                        }
                        img.src = candidate.src;
                        wrapper.__imageLoadTimer = setTimeout(() => {
                            // Some ComfyUI/Electron webviews leave <img> requests pending forever
                            // (especially with lazy loading in scroll containers). Treat that as a
                            // real failure so diagnostics and placeholders appear.
                            if (!img.complete || !img.naturalWidth || !img.naturalHeight) {
                                wrapper.dataset.imageLoadStatus = "timeout";
                                failCurrent('timeout');
                            }
                        }, LOAD_TIMEOUT_MS);
                    };

                    img.onerror = () => {
                        wrapper.dataset.imageLoadStatus = "error";
                        failCurrent('error');
                    };

                    tryLoad();
                };

                const createPostElement = (post) => {
                    if (!post.id) return null;

                    const wrapper = $el("div.danbooru-image-wrapper");
                    wrapper.dataset.postId = post.id; // 显式设置 data-post-id
                    wrapper.style.minHeight = "120px";

                    // Reserve grid space up-front from the post's real dimensions so the
                    // waterfall is stable before thumbnails finish loading.
                    if (post.image_width && post.image_height) {
                        const spans = computeSpanFromDims(post.image_width, post.image_height);
                        if (spans > 0) wrapper.style.gridRowEnd = `span ${spans}`;
                    } else {
                        wrapper.style.gridRowEnd = `span ${computeSpanFromDims(1, 1) || 28}`;
                    }

                    // 首次创建post元素时，将原始post数据添加到 originalPostCache
                    if (!originalPostCache[post.id]) {
                        originalPostCache[post.id] = JSON.parse(JSON.stringify(post));
                    }

                    // Check and apply edited status on creation
                    updateEditedStatus(wrapper, post.id);

                    const img = $el("img", {
                        loading: "eager",
                        decoding: "async",
                        onload: () => {
                            if (wrapper.__imageLoadTimer) { clearTimeout(wrapper.__imageLoadTimer); wrapper.__imageLoadTimer = null; }
                            wrapper.dataset.imageLoadStatus = "loaded";
                            wrapper.classList.remove("danbooru-image-load-failed");
                            const oldBadge = wrapper.querySelector(".danbooru-image-load-error");
                            if (oldBadge) oldBadge.remove();
                            scheduleResizeGrid();
                        },
                        onclick: async (e) => {
                            e.stopPropagation(); // Prevent event from bubbling up and potentially causing issues
                            const isSelected = wrapper.classList.contains('selected');
                            const isMultiSelectMode = uiSettings.multi_select_enabled;

                            // 单选模式下，先清除所有其他图像的选中状态
                            if (!isMultiSelectMode) {
                                imageGrid.querySelectorAll('.danbooru-image-wrapper').forEach(w => {
                                    if (w !== wrapper) {
                                        w.classList.remove('selected');
                                    }
                                });
                            }

                            // 切换当前图像的选中状态
                            if (!isSelected) {
                                wrapper.classList.add('selected');
                                await resolveCivitaiPromptIfMissing(post);
                            } else {
                                wrapper.classList.remove('selected');
                            }

                            // 收集所有选中图片的数据并更新 widget
                            updateSelectionData();
                        },
                    });

                    installImageFallbackLoader(img, wrapper, post);

                    // 创建下载按钮
                    const downloadButton = $el("button.danbooru-download-button", {
                        innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                        </svg>`,
                        title: t('download'),
                        onclick: async (e) => {
                            e.stopPropagation(); // 阻止事件冒泡，避免触发图片选择

                            try {
                                const imageUrl = post.file_url || post.large_file_url;
                                if (!imageUrl) {
                                    return;
                                }

                                // 获取图片文件扩展名
                                const fileExt = post.file_ext || 'jpg';
                                const fileName = `${(post.source_site || currentSource || 'danbooru')}_${post.id}.${fileExt}`;

                                // 通过后端代理下载，避免被 Cloudflare 按 cross-site referer 拦截
                                const proxyUrl = `/danbooru_gallery/image_proxy?url=${encodeURIComponent(imageUrl)}`;
                                const response = await fetch(proxyUrl);
                                const blob = await response.blob();
                                const url = window.URL.createObjectURL(blob);

                                const a = document.createElement('a');
                                a.href = url;
                                a.download = fileName;
                                document.body.appendChild(a);
                                a.click();
                                document.body.removeChild(a);
                                window.URL.revokeObjectURL(url);
                            } catch (error) {
                                // 下载失败，静默处理
                            }
                        }
                    });

                    // 使用全局tooltip实例
                    if (!globalTooltip) {
                        globalTooltip = $el("div.danbooru-tag-tooltip", { style: { display: "none", position: "absolute", zIndex: "1000" } });
                        const tagsContainer = $el("div", { className: "danbooru-tooltip-tags" });
                        globalTooltip.appendChild(tagsContainer);
                        document.body.appendChild(globalTooltip);
                    }

                    const createTagSpan = (tag, category, translation = null) => {
                        const displayText = translation ? `${tag} [${translation}]` : tag;
                        return $el("span", {
                            textContent: displayText,
                            className: `danbooru-tooltip-tag tag-category-${category}`,
                        });
                    };

                    let currentClickHandler = null;

                    wrapper.addEventListener("mouseenter", async (e) => {
                        if (!uiSettings.tooltip_enabled) return;

                        // 生成新的tooltip ID，使之前的异步请求失效
                        currentTooltipId++;
                        const thisTooltipId = currentTooltipId;

                        clearTimeout(globalTooltipTimeout);

                        const tagsContainer = globalTooltip.querySelector('.danbooru-tooltip-tags');
                        tagsContainer.innerHTML = '';

                        // Details Section
                        const detailsSection = $el("div.danbooru-tooltip-section");
                        detailsSection.appendChild($el("div.danbooru-tooltip-category-header", { textContent: t('details') }));
                        if (post.created_at) {
                            const date = new Date(post.created_at);
                            const formattedDate = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
                            detailsSection.appendChild($el("div", { textContent: `${t('uploaded')}: ${formattedDate}`, className: "danbooru-tooltip-upload-date" }));
                        }
                        if (post.image_width && post.image_height) {
                            detailsSection.appendChild($el("div", { textContent: `${t('resolution')}: ${post.image_width}×${post.image_height}`, className: "danbooru-tooltip-upload-date" }));
                        }
                        tagsContainer.appendChild(detailsSection);

                        // Civitai search hits may omit tags. Resolve the public image detail lazily
                        // before constructing the tooltip instead of waiting for an image click.
                        const isCivitaiPost = post.source_site === "civitai" || post.source === "civitai";
                        const hasContentTags = post.civitai_has_content_tags === true || Boolean((post.civitai_content_tags || "").trim());
                        if (isCivitaiPost && !hasContentTags) {
                            // Do not start a remote detail request while the mouse is merely
                            // sweeping across the grid. A short dwell eliminates most accidental
                            // Civitai calls without making an intentional tooltip feel delayed.
                            await new Promise((resolve) => setTimeout(resolve, 180));
                            if (thisTooltipId !== currentTooltipId || !wrapper.matches(':hover')) return;
                            await resolveCivitaiPromptIfMissing(post);
                            if (thisTooltipId !== currentTooltipId) return;
                        }

                        // Tags Processing
                        const categoryOrder = ["artist", "copyright", "character", "general", "meta"];
                        const categorizedTags = {
                            artist: new Set(),
                            copyright: new Set(),
                            character: new Set(),
                            general: new Set(),
                            meta: new Set()
                        };

                        if (post.tag_string_artist) post.tag_string_artist.split(' ').forEach(t => categorizedTags.artist.add(t));
                        if (post.tag_string_copyright) post.tag_string_copyright.split(' ').forEach(t => categorizedTags.copyright.add(t));
                        if (post.tag_string_character) post.tag_string_character.split(' ').forEach(t => categorizedTags.character.add(t));
                        if (post.tag_string_general) post.tag_string_general.split(' ').forEach(t => categorizedTags.general.add(t));
                        if (post.tag_string_meta) post.tag_string_meta.split(' ').forEach(t => categorizedTags.meta.add(t));

                        // Fallback for older posts or different tag string formats
                        if (Object.values(categorizedTags).every(s => s.size === 0) && post.tag_string) {
                            post.tag_string.split(' ').forEach(t => categorizedTags.general.add(t));
                        }

                        // 收集所有tags用于批量翻译
                        const allTags = [];
                        categoryOrder.forEach(categoryName => {
                            if (categorizedTags[categoryName].size > 0) {
                                allTags.push(...Array.from(categorizedTags[categoryName]));
                            }
                        });

                        // 批量获取翻译（仅在中文模式下）
                        let translations = {};
                        if (globalMultiLanguageManager.getLanguage() === 'zh') {
                            try {
                                if (allTags.length > 0) {
                                    const response = await fetch('/danbooru_gallery/translate_tags_batch', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({ tags: allTags })
                                    });
                                    const data = await response.json();
                                    if (data.success) {
                                        translations = data.translations;
                                    }
                                }
                            } catch (error) {
                                // 翻译获取失败，继续显示英文标签
                            }
                        }

                        // 检查tooltip ID是否仍然有效（防止快速切换时显示过期的tooltip）
                        if (thisTooltipId !== currentTooltipId) {
                            return; // 用户已经移动到另一张图片，放弃显示此tooltip
                        }

                        // Render all tag categories with translations
                        categoryOrder.forEach(categoryName => {
                            if (categorizedTags[categoryName].size > 0) {
                                const section = $el("div.danbooru-tooltip-section");
                                section.appendChild($el("div.danbooru-tooltip-category-header", { textContent: t(categoryName) }));
                                const tagsWrapper = $el("div.danbooru-tooltip-tags-wrapper");
                                categorizedTags[categoryName].forEach(tag => {
                                    const translation = translations[tag];
                                    tagsWrapper.appendChild(createTagSpan(tag, categoryName, translation));
                                });
                                section.appendChild(tagsWrapper);
                                tagsContainer.appendChild(section);
                            }
                        });

                        globalTooltip.style.display = "block";

                        // 添加点击其他地方隐藏tooltip的保护机制
                        currentClickHandler = (e) => {
                            if (!wrapper.contains(e.target) && globalTooltip.style.display !== 'none') {
                                globalTooltip.style.display = "none";
                                document.removeEventListener('click', currentClickHandler);
                                currentClickHandler = null;
                            }
                        };

                        // 延迟添加点击监听器，避免立即触发
                        setTimeout(() => {
                            if (currentClickHandler) {
                                document.addEventListener('click', currentClickHandler);
                            }
                        }, 10);
                    });

                    wrapper.addEventListener("mouseleave", () => {
                        // 增加tooltip ID，使当前的异步请求失效
                        currentTooltipId++;

                        // 鼠标离开图像时立即隐藏tooltip
                        globalTooltip.style.display = "none";

                        // 移除点击监听器
                        if (currentClickHandler) {
                            document.removeEventListener('click', currentClickHandler);
                            currentClickHandler = null;
                        }
                    });

                    wrapper.addEventListener("mousemove", (e) => {
                        if (globalTooltip.style.display !== 'block') return;
                        const rect = globalTooltip.getBoundingClientRect();
                        const buffer = 15;
                        let newLeft = e.clientX + buffer, newTop = e.clientY + buffer;
                        if (newLeft + rect.width > window.innerWidth) newLeft = e.clientX - rect.width - buffer;
                        if (newTop + rect.height > window.innerHeight) newTop = e.clientY - rect.height - buffer;
                        globalTooltip.style.left = `${newLeft + window.scrollX}px`;
                        globalTooltip.style.top = `${newTop + window.scrollY}px`;
                    });

                    // 总是创建收藏按钮，无论用户是否登录；Gelbooru 暂不接 Danbooru 收藏 API。
                    const currentSearch = searchInput.value.trim();
                    const sourceForPost = normalizeSource(post.source_site || post.source || currentSource);
                    const canUseDanbooruFavorites = sourceForPost === "danbooru";
                    const canUseCivitaiFavorites = sourceForPost === "civitai";
                    const canUseFavorites = canUseDanbooruFavorites || canUseCivitaiFavorites;
                    const v53FavoritesMode = v53UiReady && galleryStore.getDraft(currentSource).mode === "favorites";
                    const inDanbooruFavoritesQuery = !!userAuth.username && currentSearch.includes(`ordfav:${userAuth.username}`);
                    const inFavoritesMode = canUseDanbooruFavorites && hasDanbooruFavoriteAuth() && (v53FavoritesMode || inDanbooruFavoritesQuery);
                    const inCivitaiFavoritesMode = canUseCivitaiFavorites && (v53FavoritesMode || currentSearch.includes(`civitai:favorites`));
                    const isFavorited = canUseFavorites && (inFavoritesMode || inCivitaiFavoritesMode || userFavorites.includes(String(post.id)));
                    const favoriteButton = $el("button.danbooru-favorite-button", {
                        "data-post-id": post.id,
                        innerHTML: isFavorited ?
                            `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="#DC3545" stroke="#DC3545" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
                            </svg>` :
                            `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
                            </svg>`,
                        title: !canUseFavorites ? '当前来源暂不支持插件内收藏' : (isFavorited ? t('unfavorite') : t('favorite')),
                        className: isFavorited ? 'favorited' : '',
                        onclick: async (e) => {
                            e.stopPropagation(); // 阻止事件冒泡，避免触发图片选择

                            if (!canUseFavorites) {
                                showToast('当前来源暂不支持插件内收藏。', 'warning');
                                return;
                            }

                            // Danbooru 云收藏需要登录；Civitai 使用本地收藏快照，不强制 API Key。
                            if (canUseDanbooruFavorites && !hasDanbooruFavoriteAuth()) {
                                showToast(t('authRequired'), 'warning');
                                return;
                            }

                            // 在操作收藏前验证用户名和API Key的有效性

                            const currentlyFavorited = userFavorites.includes(String(post.id)) || inFavoritesMode || inCivitaiFavoritesMode;
                            let result;

                            if (currentlyFavorited) {
                                // 取消收藏
                                result = await removeFromFavorites(post.id, favoriteButton, sourceForPost);
                                if (result.success) {
                                    // 如果在收藏夹视图中，直接移除元素
                                    const currentSearch = searchInput.value.trim();
                                    const danbooruFavoritesQueryActive = !!userAuth.username && currentSearch.includes(`ordfav:${userAuth.username}`);
                                    if (v53FavoritesMode || danbooruFavoritesQueryActive || currentSearch.includes(`civitai:favorites`)) {
                                        wrapper.remove();
                                    }
                                }
                            } else {
                                // 添加收藏
                                result = await addToFavorites(post.id, favoriteButton, sourceForPost, post);
                            }

                            // 错误已在函数内处理
                        }
                    });

                    // 创建按钮容器
                    const buttonsContainer = $el("div.danbooru-image-buttons");

                    // 创建编辑模式按钮
                    const editButton = $el("button.danbooru-edit-button", {
                        innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>`,
                        title: t('editMode'),
                        onclick: (e) => {
                            e.stopPropagation();
                            showEditPanel(post);
                        }
                    });

                    const viewImageButton = $el("button.danbooru-view-image-button", {
                        innerHTML: `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>`,
                        title: '打开原图（优先原始尺寸，可另存为）',
                        ariaLabel: '打开原图',
                        onclick: (e) => {
                            e.stopPropagation();
                            const imageUrl = post.file_url || post.large_file_url;
                            if (/^https?:\/\//i.test(imageUrl || '')) {
                                window.open(imageUrl, '_blank', 'noopener,noreferrer');
                            }
                        }
                    });

                    const sourceLink = $el('a.danbooru-source-link', {
                        innerHTML: '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/></svg>',
                        title: '访问原网页（可在原站查看和保存高清图片）',
                        ariaLabel: '访问原网页',
                        target: '_blank',
                        rel: 'noopener noreferrer',
                        onclick: event => event.stopPropagation(),
                    });
                    const pageUrl = buildPageUrlForPost(post);
                    if (/^https?:\/\//i.test(pageUrl)) sourceLink.href = pageUrl;

                    const sharedGroupButton=$el('button',{textContent:'共享分组',title:'与资料库、Tag 和模型共用分组'});
                    const usePromptButton=$el('button',{textContent:'使用提示词',title:'选择提示词目标并追加、替换或撤销'});
                    for(const button of [sharedGroupButton,usePromptButton]) {
                        button.addEventListener('pointerdown',event=>event.stopPropagation());
                        button.addEventListener('mouseenter',()=>{globalTooltip.style.display='none';currentTooltipId++;});
                    }
                    sharedGroupButton.onclick=async event=>{event.stopPropagation();try{await openReferenceCollections({provider:sourceForPost,resource:String(post.id)},{title:`${sourceForPost} #${post.id}`});}catch(error){showToast(error.message,'error',sharedGroupButton);}};
                    usePromptButton.onclick=async event=>{event.stopPropagation();try{await openPromptUse({title:`${sourceForPost} #${post.id}`,resolveText:()=>{
                        if(app.graph.getNodeById(nodeInstance.id)!==nodeInstance)throw new Error('图库节点已变化，请重新打开。');
                        const listed=posts.find(item=>String(item.id)===String(post.id)&&normalizeSource(item.source_site||item.source||currentSource)===sourceForPost);
                        const current=(listed&&sourceForPost===normalizeSource(currentSource)?temporaryTagEdits[post.id]:null)||listed||(post._uwReference?post:null);
                        if(!current)throw new Error('图片已离开当前列表，请刷新后重新选择。');
                        return buildPromptForPost(current);
                    }});}catch(error){showToast(error.message,'error',usePromptButton);}};
                    const sharedButtons=$el('div.uw-gallery-actions');
                    sharedButtons.style.cssText='position:absolute;left:4px;right:4px;bottom:4px;display:flex;gap:4px;z-index:5';
                    for(const button of [sharedGroupButton,usePromptButton])button.style.cssText='flex:1;min-width:0;padding:5px 3px;font:12px system-ui;line-height:18px;color:#fff;background:#202632ee;border:1px solid #8d9bb0;border-radius:5px;cursor:pointer';
                    sharedButtons.append(sharedGroupButton,usePromptButton);wrapper.appendChild(sharedButtons);
                    if (sourceLink.href) buttonsContainer.appendChild(sourceLink);
                    buttonsContainer.appendChild(viewImageButton);
                    buttonsContainer.appendChild(editButton);
                    buttonsContainer.appendChild(downloadButton);
                    // Danbooru 用云收藏；Civitai 用本地收藏快照。Gelbooru 暂不支持收藏。
                    if (canUseFavorites) {
                        buttonsContainer.appendChild(favoriteButton);
                    }
                    buttonsContainer.addEventListener('pointerdown', event => event.stopPropagation());
                    buttonsContainer.addEventListener('mouseenter', () => { globalTooltip.style.display = 'none'; currentTooltipId++; });

                    wrapper.appendChild(img);
                    wrapper.appendChild(buttonsContainer);

                    return wrapper;
                };

                const renderPost = (post) => {
                    const element = createPostElement(post);
                    if (element) {
                        imageGrid.appendChild(element);
                    }
                };

                const observer = new ResizeObserver(() => {
                    cachedColumnWidth = 0;
                    updateGridLayout();
                    resizeGrid();
                });
                observer.observe(imageGrid);

                let scrollTimeout;
                imageGrid.addEventListener("scroll", () => {
                    if (!isLoading && !endOfResults && imageGrid.scrollHeight - imageGrid.scrollTop - imageGrid.clientHeight < 400) {
                        fetchAndRender(false);
                    }

                    // Debounced scroll logic for page indicator
                    clearTimeout(scrollTimeout);
                    scrollTimeout = setTimeout(() => {
                        updateCurrentPageIndicator();
                        if (v53UiReady && galleryStore.activeSession) {
                            galleryStore.setScrollTop(
                                galleryStore.activeSession.source,
                                galleryStore.activeSession.queryKey,
                                imageGrid.scrollTop
                            );
                            persistGalleryState();
                        }
                    }, 150);
                });

                searchInput.addEventListener("keydown", (e) => {
                    if (e.key === "Enter") {
                        e.preventDefault();
                        syncV53DraftFromControls({ mode: "search" });
                        setV53Mode("search");
                    }
                });
                ratingSelect.addEventListener("change", () => {
                    if (globalTooltip) {
                        globalTooltip.style.display = 'none';
                    }
                    if (v53UiReady) syncV53DraftFromControls();
                    fetchAndRender(true); // 保留，因为改变评分需要重新加载
                });
                // 检查和更新排行榜按钮状态的函数
                const updateRankingButtonState = () => {
                    const active = galleryStore.getDraft(currentSource).mode === "ranking";
                    rankingButton.classList.toggle('active', active);
                };

                // 排行榜按钮点击事件
                rankingButton.addEventListener("click", () => {
                    // V53 ranking is a first-class browse view. Never mutate the search query.
                    setV53Mode("ranking");
                });

                // 监听搜索框变化，更新排行榜按钮状态
                // 更新收藏夹按钮状态
                const updateFavoritesButtonState = () => {
                    if (currentSource !== "danbooru" && currentSource !== "civitai") {
                        favoritesButton.style.display = 'none';
                        favoritesButton.classList.remove('active');
                        favoritesButton.title = '当前来源暂不支持插件内收藏';
                        return;
                    }
                    favoritesButton.style.display = 'flex';
                    if (currentSource === 'civitai') {
                        const remoteCollections = Array.isArray(civitaiRemoteFavorites.collections) ? civitaiRemoteFavorites.collections : [];
                        const remoteSelected = remoteCollections.find(c => String(c?.id || '') === String(civitaiRemoteFavorites.default_collection_id || '')) || civitaiRemoteFavorites.selected_collection || remoteCollections[0];
                        favoritesButton.title = (civitaiRemoteFavorites.enabled && remoteSelected)
                            ? `Civitai 远端收藏夹：${remoteSelected.name || remoteSelected.id}`
                            : 'Civitai 本地收藏夹';
                    } else {
                        favoritesButton.title = t('favorites');
                    }

                    const inFavoritesView = galleryStore.getDraft(currentSource).mode === "favorites";
                    if (currentSource === 'civitai') {
                        favoritesButton.classList.toggle('active', inFavoritesView);
                        return;
                    }

                    if (!hasDanbooruFavoriteAuth()) {
                        favoritesButton.classList.remove('active');
                        return;
                    }

                    favoritesButton.classList.toggle('active', inFavoritesView);
                };

                const updateFavoriteStreamButtonState = () => {
                    const capability = getV53ViewCapability("favorite_stream");
                    const available = currentSource === "danbooru" && isV53Usable(capability);
                    favoriteStreamButton.style.display = available ? "flex" : "none";
                    favoriteStreamButton.disabled = !available;
                    favoriteStreamButton.classList.toggle("active", galleryStore.getDraft(currentSource).mode === "favorite_stream");
                    favoriteStreamButton.title = available ? "D站全站最近收藏动态" : "当前来源不支持全站收藏动态";
                };

                // 统一的搜索框输入处理函数
                const handleSearchInput = () => {
                    const currentValue = searchInput.value.trim();
                    if (v53UiReady) syncV53DraftFromControls({ terms: currentValue });
                    previousSearchValue = currentValue;
                    updateRankingButtonState();
                    updateFavoritesButtonState();
                    updateFavoriteStreamButtonState();
                    updateCivitaiLooseButtonState();

                    const clearButton = searchContainer.querySelector('.danbooru-clear-search-button');
                    if (clearButton) {
                        clearButton.style.display = currentValue ? 'block' : 'none';
                    }
                };

                searchInput.addEventListener("input", handleSearchInput);

                // 收藏夹按钮点击事件
                favoritesButton.addEventListener("click", async () => {
                    if (currentSource !== "danbooru" && currentSource !== "civitai") {
                        showToast('当前来源暂不支持插件内收藏。', 'warning');
                        return;
                    }
                    if (currentSource === 'danbooru' && !hasDanbooruFavoriteAuth()) {
                        showToast(t('authRequired'), 'warning');
                        return;
                    }

                    await setV53Mode("favorites");
                });

                favoriteStreamButton.addEventListener("click", async () => {
                    if (currentSource !== "danbooru") {
                        showToast("当前来源不支持全站收藏动态。", "warning");
                        return;
                    }
                    await setV53Mode("favorite_stream");
                });

                refreshButton.addEventListener("click", () => {
                    // 手动刷新只做一件事：清掉当前前端页状态，并强制后端绕过帖子缓存重新拉取第一页。
                    manualRefreshNonce = Date.now();
                    renderedPostKeys = new Set();
                    fetchAndRender(true);
                });

                const searchContainer = $el("div.danbooru-search-container");
                const clearButton = $el("button.danbooru-clear-search-button", {
                    innerHTML: '×',
                    title: t('clearSearch'),
                    style: {
                        display: 'none'
                    },
                    onclick: () => {
                        searchInput.value = '';
                        searchInput.dispatchEvent(new Event('input'));
                        setV53Mode("search");
                    }
                });
                searchContainer.appendChild(searchInput);
                searchContainer.appendChild(clearButton);

                const createV53Tab = (id, label, testId, onActivate) => {
                    const tab = $el("button.v53-gallery-tab", {
                        id: `${v53InstanceId}-${id}`,
                        type: "button",
                        role: "tab",
                        textContent: label,
                        "aria-controls": imageGrid.id,
                        "aria-selected": "false",
                        tabIndex: -1,
                        "data-testid": testId,
                        onclick: onActivate,
                    });
                    tab.setAttribute("data-testid", testId);
                    return tab;
                };
                const v53PrimaryTabs = {
                    browse: createV53Tab("mode-browse", "浏览", "gallery-mode-browse", () => setV53Mode("browse")),
                    search: createV53Tab("mode-search", "搜索", "gallery-mode-search", () => setV53Mode("search")),
                    favorites: createV53Tab("mode-favorites", "收藏", "gallery-mode-favorites", () => setV53Mode("favorites")),
                    favorite_stream: createV53Tab("mode-favorite-stream", "收藏动态", "gallery-mode-favorite-stream", () => setV53Mode("favorite_stream")),
                };
                const v53BrowseTabs = {
                    latest: createV53Tab("browse-latest", "最新", "gallery-browse-latest", () => setV53Mode("latest")),
                    ranking: createV53Tab("browse-ranking", "排行", "gallery-browse-ranking", () => setV53Mode("ranking")),
                    category: createV53Tab("browse-category", "分类", "gallery-browse-category", () => setV53Mode("category")),
                };
                const v53PrimaryTabList = $el("div.v53-gallery-tablist.v53-gallery-primary-tabs", {
                    role: "tablist",
                    "aria-label": "画廊模式",
                    "data-testid": "gallery-primary-tabs",
                }, Object.values(v53PrimaryTabs));
                const v53BrowseTabList = $el("div.v53-gallery-tablist.v53-gallery-browse-tabs", {
                    role: "tablist",
                    "aria-label": "浏览方式",
                    "data-testid": "gallery-browse-tabs",
                }, Object.values(v53BrowseTabs));
                v53PrimaryTabList.setAttribute("data-testid", "gallery-primary-tabs");
                v53BrowseTabList.setAttribute("data-testid", "gallery-browse-tabs");
                const bindV53TabKeyboard = (tabList) => {
                    tabList.addEventListener("keydown", (event) => {
                        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                        const tabs = Array.from(tabList.querySelectorAll('[role="tab"]:not(:disabled)'));
                        const index = tabs.indexOf(document.activeElement);
                        if (index < 0 || tabs.length < 2) return;
                        event.preventDefault();
                        const direction = event.key === "ArrowRight" ? 1 : -1;
                        const next = tabs[(index + direction + tabs.length) % tabs.length];
                        next.focus();
                        next.click();
                    });
                };
                bindV53TabKeyboard(v53PrimaryTabList);
                bindV53TabKeyboard(v53BrowseTabList);

                const v53MetricSelect = $el("select.v53-gallery-select", {
                    "aria-label": "排行指标",
                    "data-testid": "gallery-ranking-metric",
                });
                const v53PeriodSelect = $el("select.v53-gallery-select", {
                    "aria-label": "排行周期",
                    "data-testid": "gallery-ranking-period",
                });
                const v53FacetKindSelect = $el("select.v53-gallery-select", {
                    "aria-label": "分类类型",
                    "data-testid": "gallery-facet-kind",
                });
                const v53FacetValueSelect = $el("select.v53-gallery-select.v53-gallery-facet-value", {
                    "aria-label": "分类项",
                    "data-testid": "gallery-facet-value",
                });
                v53MetricSelect.setAttribute("data-testid", "gallery-ranking-metric");
                v53PeriodSelect.setAttribute("data-testid", "gallery-ranking-period");
                v53FacetKindSelect.setAttribute("data-testid", "gallery-facet-kind");
                v53FacetValueSelect.setAttribute("data-testid", "gallery-facet-value");
                const v53RankingControls = $el("div.v53-gallery-context-group", {
                    "data-testid": "gallery-ranking-controls",
                }, [
                    $el("label", { textContent: "指标", htmlFor: `${v53InstanceId}-metric` }),
                    v53MetricSelect,
                    $el("label", { textContent: "周期", htmlFor: `${v53InstanceId}-period` }),
                    v53PeriodSelect,
                ]);
                v53RankingControls.setAttribute("data-testid", "gallery-ranking-controls");
                v53MetricSelect.id = `${v53InstanceId}-metric`;
                v53PeriodSelect.id = `${v53InstanceId}-period`;
                const v53FacetControls = $el("div.v53-gallery-context-group", {
                    "data-testid": "gallery-facet-controls",
                }, [
                    $el("label", { textContent: "分类", htmlFor: `${v53InstanceId}-facet-kind` }),
                    v53FacetKindSelect,
                    $el("label", { textContent: "条目", htmlFor: `${v53InstanceId}-facet-value` }),
                    v53FacetValueSelect,
                ]);
                v53FacetControls.setAttribute("data-testid", "gallery-facet-controls");
                v53FacetKindSelect.id = `${v53InstanceId}-facet-kind`;
                v53FacetValueSelect.id = `${v53InstanceId}-facet-value`;
                const v53StatusPanel = $el("div.v53-gallery-status", {
                    role: "status",
                    "aria-live": "polite",
                    "data-testid": "gallery-status",
                    dataset: { state: "idle" },
                }, [$el("span.v53-status-message", { textContent: "正在初始化多站点画廊…" })]);
                v53StatusPanel.setAttribute("data-testid", "gallery-status");

                const populateV53PeriodsForMetric = () => {
                    const capabilities = getV53Capabilities();
                    const periods = new Set();
                    for (const entry of capabilities?.features?.ranking || []) {
                        if (entry?.metric !== v53MetricSelect.value || !isV53Usable(entry)) continue;
                        for (const period of entry.periods || []) periods.add(period);
                    }
                    const previous = galleryStore.getDraft(currentSource).sort?.period;
                    replaceSelectOptions(
                        v53PeriodSelect,
                        Array.from(periods).map((period) => ({ value: period, label: v53Label(period) })),
                        previous
                    );
                };
                v53MetricSelect.addEventListener("change", async () => {
                    populateV53PeriodsForMetric();
                    syncV53DraftFromControls({ sort: { metric: v53MetricSelect.value, period: v53PeriodSelect.value || null } });
                    if (galleryStore.getDraft(currentSource).mode === "ranking") await fetchAndRenderV53(true);
                });
                v53PeriodSelect.addEventListener("change", async () => {
                    syncV53DraftFromControls();
                    if (galleryStore.getDraft(currentSource).mode === "ranking") await fetchAndRenderV53(true);
                });
                v53FacetKindSelect.addEventListener("change", async () => {
                    galleryRequests.abort("browse", "facet_changed");
                    v53BrowseIntentSequence += 1;
                    isLoading = false;
                    galleryStore.updateDraft(currentSource, {
                        facet: { kind: v53FacetKindSelect.value || null, id: null, label: null },
                    });
                    persistGalleryState();
                    const populated = await loadV53FacetValues();
                    if (populated && galleryStore.getDraft(currentSource).mode === "category") await fetchAndRenderV53(true);
                });
                v53FacetValueSelect.addEventListener("change", async () => {
                    syncV53DraftFromControls();
                    if (galleryStore.getDraft(currentSource).mode === "category") await fetchAndRenderV53(true);
                });

                const v53Navigation = $el("section.v53-gallery-navigation", {
                    "aria-label": "画廊浏览导航",
                    "data-testid": "gallery-navigation",
                }, [
                    $el("div.v53-gallery-primary-row", [sourceSelect, v53PrimaryTabList]),
                    v53BrowseTabList,
                    $el("div.v53-gallery-context-controls", [searchContainer, v53RankingControls, v53FacetControls]),
                    v53StatusPanel,
                ]);
                v53Navigation.setAttribute("data-testid", "gallery-navigation");
                const applyV53UiGate = (enabled) => {
                    const active = enabled === true;
                    container.dataset.galleryV53Enabled = active ? "true" : "false";
                    // Rollback keeps the legacy source/search controls usable while
                    // removing only the V53 tabs, status and contextual controls.
                    v53Navigation.hidden = false;
                    v53PrimaryTabList.hidden = !active;
                    v53BrowseTabList.hidden = !active;
                    v53StatusPanel.hidden = !active;
                    v53RankingControls.hidden = !active;
                    v53FacetControls.hidden = !active;
                    searchContainer.hidden = false;
                };

                // 选中计数徽章（多选模式时显示，移至底部状态栏）
                const selectionCountBadge = $el("span.danbooru-selection-count", {
                    style: {
                        display: 'none',
                        padding: '4px 8px',
                        backgroundColor: 'rgba(0, 0, 0, 0.7)',
                        color: 'white',
                        fontSize: '12px',
                        borderRadius: '4px',
                        backdropFilter: 'blur(5px)',
                        whiteSpace: 'nowrap'
                    }
                });

                // 清除全选按钮（多选模式时显示）
                const clearSelectionButton = $el("button.danbooru-clear-selection", {
                    textContent: t('clearAllSelection'),
                    title: t('clearAllSelection'),
                    style: {
                        display: uiSettings.multi_select_enabled ? 'inline-block' : 'none',
                        padding: '5px 10px',
                        borderRadius: '4px',
                        backgroundColor: 'var(--comfy-input-bg)',
                        border: '1px solid var(--input-border-color)',
                        color: 'var(--comfy-input-text)',
                        cursor: 'pointer',
                        fontSize: '12px'
                    },
                    onclick: () => {
                        clearAllSelections();
                    }
                });

                // V53 navigation owns source/query/ranking/facet controls; legacy controls below
                // keep output formatting, diagnostics, card behavior and settings compatible.
                nodeInstance.unifiedGalleryActions = {
                    root:container,
                    setEmbedded(value){
                        embedded = value;
                        container.classList.toggle('danbooru-gallery-embedded', embedded);
                        if (!embedded) { nodeInstance.onResize?.(nodeInstance.size); return; }
                        for (const element of [container, imageGrid]) {
                            for (const property of ['width', 'max-width', 'min-width', 'height', 'max-height', 'min-height']) element.style.removeProperty(property);
                        }
                        for (const property of ['position', 'top', 'left', 'transform', 'overflow']) container.style.removeProperty(property);
                        delete imageGrid.dataset.layoutWidth;
                        imageGrid.style.removeProperty('--danbooru-thumb-max-height');
                        cachedColumnWidth = 0;
                        requestAnimationFrame(() => { updateGridLayout(); resizeGrid(); });
                    },
                    search:async(value)=>{searchInput.value=String(value);syncV53DraftFromControls({mode:'search'});await setV53Mode('search');},
                    showFavorites:()=>setV53Mode('favorites'),
                    showSettings:()=>settingsButton.click(),
                    showReference:async(reference,host)=>{
                        const response=await fetch('/danbooru_gallery/posts?'+new URLSearchParams({'search[id]':reference.resource,source:reference.provider,limit:1}),{cache:'no-store'});
                        const data=await response.json();if(!response.ok)throw new Error(data.error?.message||data.error||'这张图片暂时不可读，请重试。');
                        const post=data.find(item=>String(item.id)===String(reference.resource));if(!post)throw new Error('来源未返回这个图片 ID。');
                        if(!host.isConnected)return;post.source_site=reference.provider;post._uwReference=true;const card=createPostElement(post);if(card){card.style.cssText+=';width:min(420px,100%);position:relative';host.append(card);}
                    },
                    readPrompt:()=>{
                        if(app.graph.getNodeById(nodeInstance.id)!==nodeInstance)throw new Error('图库节点已变化，请重新打开。');
                        const selection=normalizeSelectionPayload(JSON.parse(selectionWidget.value || '{}'));
                        if(!selection.selections.length)throw new Error('请先在图库选择图片。');
                        return selection.selections.map(item=>item.prompt || '').filter(Boolean).join('\n');
                    },
                    useSelection:()=>openPromptUse({title:'图库所选提示词',resolveText:()=>nodeInstance.unifiedGalleryActions.readPrompt()}),
                    queueSelection:async()=>{
                        const snapshot=selectionWidget.value,text=nodeInstance.unifiedGalleryActions.readPrompt();
                        const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(snapshot));
                        const id=String(nodeInstance.id)+':'+Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
                        return queuePromptResource({provider:'gallery',id,title:'图库所选提示词',text,usage:'target',resolveText:()=>{
                            if(selectionWidget.value!==snapshot)throw new Error('图库选择已变化，请重新选取并加入待用列表。');
                            return nodeInstance.unifiedGalleryActions.readPrompt();
                        }});
                    },
                };
                const useSelectedPrompt=$el('button',{textContent:'使用所选提示词'});
                useSelectedPrompt.onclick=()=>nodeInstance.unifiedGalleryActions.useSelection().catch(error=>showToast(error.message,'error',useSelectedPrompt));
                container.appendChild(useSelectedPrompt);
                const queueSelectedPrompt=$el('button',{textContent:'加入待用列表'});
                queueSelectedPrompt.onclick=()=>nodeInstance.unifiedGalleryActions.queueSelection().catch(error=>showToast(error.message,'error',queueSelectedPrompt));
                container.appendChild(queueSelectedPrompt);
                container.appendChild(v53Navigation);
                container.appendChild($el("div.danbooru-controls", [civitaiLooseButton, favoriteStreamButton, urlExportButton, ratingSelect, categoryDropdown, formattingDropdown, tagCatalogButton, filterButton, clearSelectionButton, settingsButton, diagnosticsMenuButton, refreshButton]));

                // 🔧 重要：在 searchInput 被添加到 DOM 之后才创建智能补全实例
                // 这样 AutocompleteUI 才能正确获取父元素并将建议容器添加到 DOM
                const searchAutocomplete = new AutocompleteUI({
                    inputElement: searchInput,
                    language: globalMultiLanguageManager.getLanguage(),
                    sourceProvider: () => currentSource,
                    maxSuggestions: uiSettings.autocomplete_max_results || 20,
                    customClass: 'danbooru-gallery-autocomplete',
                    formatTag: (tag) => {
                        // 应用格式化设置
                        let processedTag = tag;
                        if (uiSettings.formatting && uiSettings.formatting.replaceUnderscores) {
                            processedTag = processedTag.replace(/_/g, ' ');
                        }
                        if (uiSettings.formatting && uiSettings.formatting.escapeBrackets) {
                            processedTag = processedTag.replaceAll('(', '\\(').replaceAll(')', '\\)');
                        }
                        return processedTag;
                    },
                    onSelect: (tag) => {
                        syncV53DraftFromControls({ mode: "search" });
                    }
                });
                container.appendChild(imageGrid);
                requestAnimationFrame(() => {
                    updateGridLayout();
                    resizeGrid();
                });

                // 创建底部状态栏容器
                const bottomStatusBar = $el("div.danbooru-bottom-status", {
                    style: {
                        position: 'absolute',
                        bottom: '10px',
                        left: '10px',
                        zIndex: '20',
                        display: 'flex',
                        gap: '8px',
                        alignItems: 'center'
                    }
                });

                // 添加页码指示器
                const pageIndicator = $el("div.danbooru-page-indicator", {
                    style: {
                        display: 'none', // Initially hidden
                        padding: '4px 8px',
                        backgroundColor: 'rgba(0, 0, 0, 0.7)',
                        color: 'white',
                        fontSize: '12px',
                        borderRadius: '4px',
                        backdropFilter: 'blur(5px)'
                    }
                });

                // 将页码指示器和选择计数器添加到底部状态栏
                bottomStatusBar.appendChild(pageIndicator);
                bottomStatusBar.appendChild(selectionCountBadge);
                container.appendChild(bottomStatusBar);

                const insertNewPost = (post) => {
                    const newElement = createPostElement(post);
                    if (newElement) {
                        imageGrid.prepend(newElement);
                        newElement.classList.add('new-item');
                        newElement.addEventListener('animationend', () => newElement.classList.remove('new-item'));
                        resizeGrid();
                    }
                };

                const updateEditedStatus = (wrapperElement, postId) => {
                    const originalPost = originalPostCache[postId]; // 从缓存中获取原始数据
                    const editedPost = temporaryTagEdits[postId];

                    let isTrulyEdited = false;
                    if (editedPost && originalPost) {
                        const categories = ["artist", "copyright", "character", "general", "meta"];
                        const hasCategoryTags = categories.some(cat => originalPost.hasOwnProperty(`tag_string_${cat}`) || editedPost.hasOwnProperty(`tag_string_${cat}`));

                        if (hasCategoryTags) {
                            for (const category of categories) {
                                if (!compareTagStrings(originalPost[`tag_string_${category}`], editedPost[`tag_string_${category}`])) {
                                    isTrulyEdited = true;
                                    break;
                                }
                            }
                        } else {
                            // 如果没有分类标签，检查tag_string是否被编辑
                            if (!compareTagStrings(originalPost.tag_string, editedPost.tag_string)) {
                                isTrulyEdited = true;
                            }
                        }
                    }

                    const indicator = wrapperElement.querySelector('.danbooru-edited-indicator');

                    if (isTrulyEdited) {
                        if (!indicator) {
                            const newIndicator = $el("div.danbooru-edited-indicator", { textContent: t('edited') });
                            wrapperElement.appendChild(newIndicator);
                        }
                    } else {
                        if (indicator) {
                            indicator.remove();
                        }
                    }
                    return isTrulyEdited;
                };
                // 初始化功能
                const initializeApp = async () => {
                    try {
                        // LiteGraph restores widgets_values after onNodeCreated returns.
                        // Yield once so gallery_state/filter_data are the workflow values,
                        // not the constructor defaults.
                        await new Promise((resolve) => setTimeout(resolve, 0));
                        // Try to load filter state from the widget right before we need it
                        try {
                            if (filterWidget.value) {
                                filterState = JSON.parse(filterWidget.value);
                            }
                        } catch (e) {
                            logger.warn("Danbooru Gallery: Could not parse filter state, using default.", e);
                            filterState = { startTime: null, endTime: null, startPage: null };
                        }

                        // Workflow state is authoritative. A legacy localStorage query is read
                        // exactly once by hydrateGalleryState and then marked migrated.
                        hydrateGalleryState();


                        // 先加载本地设置/凭据，再做网络检测。网络检测可能被 Danbooru Cloudflare 拖慢，
                        // 如果先检测再加载，设置窗口会短暂显示空 API/Cookie，用户保存时就会误清空。
                        await loadLanguage();
                        await Promise.all([loadUserAuth(), loadDanbooruCookie(), loadDanbooruBrowserHeaders(), loadGelbooruAuth()]);

                        let networkConnected = true;

                        // 检测当前所选图站连接状态。v21: Civitai 不做前置网络预检，避免误判；实际搜索请求会给出真实错误。
                        if (currentSource !== "civitai") {
                            try {
                                const networkResponse = await fetch(`/danbooru_gallery/check_network?source=${encodeURIComponent(currentSource)}`);
                                const networkData = await networkResponse.json();
                                if (!networkData.success || !networkData.connected) {
                                    networkConnected = false;
                                    // 注释掉网络错误toast提示 - 本小姐才不想看到这些烦人的提示呢！
                                    // showError('网络连接失败 - 无法连接到Danbooru服务器，请检查网络连接', true);
                                    console.log("网络错误已隐藏: 网络连接失败 - 无法连接到Danbooru服务器，请检查网络连接");  // 仅在控制台记录
                                }
                            } catch (e) {
                                logger.error('网络检测失败:', e);
                                networkConnected = false;
                                // 注释掉网络错误toast提示 - 本小姐才不想看到这些烦人的提示呢！
                                // showError('网络检测失败 - 请检查网络连接', true);
                                console.log("网络错误已隐藏: 网络检测失败 - 请检查网络连接");  // 仅在控制台记录
                            }
                        }

                        if (networkConnected && (currentSource === "civitai" || (hasDanbooruFavoriteAuth() && currentSource === "danbooru"))) {
                            await loadFavorites(currentSource);
                        }

                        // 更新界面文本
                        updateInterfaceTexts();

                        // 更新收藏夹按钮状态
                        updateFavoritesButtonState();

                        // 加载黑名单
                        await loadBlacklist();

                        // 加载提示词过滤设置
                        await loadFilterTags();

                        // 加载UI设置
                        await loadUiSettings();


                        const savedCategories = loadFromLocalStorage('selectedCategories', null);
                        if (savedCategories) {
                            uiSettings.selected_categories = savedCategories;
                        }
                        const categoryCheckboxes = categoryDropdown.querySelectorAll('.danbooru-category-checkbox');
                        categoryCheckboxes.forEach(checkbox => {
                            checkbox.checked = uiSettings.selected_categories.includes(checkbox.name);
                        });

                        const savedFormatting = loadFromLocalStorage('formatting', null);
                        if (savedFormatting) {
                            uiSettings.formatting = savedFormatting;
                        }
                        const escapeBracketsCheckbox = formattingDropdown.querySelector('[name="escapeBrackets"]');
                        const replaceUnderscoresCheckbox = formattingDropdown.querySelector('[name="replaceUnderscores"]');
                        if (escapeBracketsCheckbox && uiSettings.formatting) {
                            escapeBracketsCheckbox.checked = uiSettings.formatting.escapeBrackets;
                        }
                        if (replaceUnderscoresCheckbox && uiSettings.formatting) {
                            replaceUnderscoresCheckbox.checked = uiSettings.formatting.replaceUnderscores;
                        }

                        // 初始化排行榜按钮状态
                        updateRankingButtonState();

                        // 根据加载的 filterState 更新筛选按钮状态
                        if (filterState.startTime || filterState.endTime || filterState.startPage) {
                            filterButton.classList.add('active');
                        } else {
                            filterButton.classList.remove('active');
                        }

                        // Read the independent rollout gate before touching a V2 route.
                        // A missing/disabled gate safely retains the functional legacy UI.
                        try {
                            v53FeatureFlags = await loadGalleryFeatureFlags();
                        } catch (featureError) {
                            v53FeatureFlags = null;
                            logger.warn("V53 功能状态不可用，已回退旧界面:", featureError);
                        }
                        v53UiReady = galleryNewUiEnabled(v53FeatureFlags);
                        applyV53UiGate(v53UiReady);
                        updateCivitaiLooseButtonState();
                        if (v53UiReady) {
                            const capabilities = await loadV53Capabilities(currentSource);
                            if (capabilities && galleryStore.getDraft(currentSource).mode === "category") {
                                await loadV53FacetValues();
                            }
                        }
                        await fetchAndRender(true);

                    } catch (error) {
                        logger.error("Danbooru Gallery initialization failed:", error);
                        showError("图库初始化失败，请检查控制台日志。", true);
                    }
                };

                const updateCurrentPageIndicator = () => {
                    if (posts.length === 0) {
                        pageIndicator.style.display = 'none';
                        return;
                    }

                    if (v53UiReady && galleryStore.activeSession) {
                        const session = galleryStore.getSession(
                            galleryStore.activeSession.source,
                            galleryStore.activeSession.queryKey
                        );
                        pageIndicator.textContent = `${t('currentPage')}: ${Math.max(1, Number(session?.pageIndex ?? 0) + 1)}`;
                        pageIndicator.style.display = 'block';
                        return;
                    }

                    const itemsPerPage = 100;

                    // Find the first visible element in the grid
                    const firstVisibleChild = Array.from(imageGrid.children).find(child => {
                        const rect = child.getBoundingClientRect();
                        const gridRect = imageGrid.getBoundingClientRect();
                        return rect.bottom > gridRect.top && rect.top < gridRect.bottom;
                    });

                    if (firstVisibleChild) {
                        const postId = firstVisibleChild.dataset.postId;
                        const postIndex = posts.findIndex(p => String(p.id) === postId);

                        if (postIndex !== -1) {
                            const currentPageInView = Math.floor(postIndex / itemsPerPage) + (filterState.startPage || 1);
                            pageIndicator.textContent = `${t('currentPage')}: ${currentPageInView}`;
                            pageIndicator.style.display = 'block';
                        } else {
                            pageIndicator.style.display = 'none';
                        }
                    } else {
                        pageIndicator.style.display = 'none';
                    }
                };

                // 启动应用
                initializeApp();

                this.onResize = (size) => {
                    // The workbench owns the available space while the gallery is embedded.
                    if (!imageGrid || embedded) return;
                    const [width, height] = size || this.size || [780, 938];
                    const nodeWidth = Math.max(240, Math.floor(width || 780));
                    const nodeHeight = Math.max(260, Math.floor(height || 938));
                    const layoutWidth = Math.max(220, nodeWidth - 24);
                    const widgetHeight = getGalleryWidgetHeight();

                    // Important: in some ComfyUI versions the DOM widget's wrapper does not
                    // inherit the resized node width. Set pixel sizes directly, but keep height
                    // clamped to the user's node size so loaded thumbnails/diagnostics cannot
                    // push the node longer by content height.
                    const widthPx = `${layoutWidth}px`;
                    const heightPx = `${widgetHeight}px`;
                    container.style.width = widthPx;
                    container.style.maxWidth = widthPx;
                    container.style.minWidth = widthPx;
                    container.style.height = heightPx;
                    container.style.maxHeight = heightPx;
                    container.style.minHeight = '0';
                    container.style.overflow = 'hidden';
                    container.style.boxSizing = 'border-box';

                    const parent = container.parentElement;
                    if (parent && parent !== document.body && parent !== document.documentElement) {
                        parent.style.width = widthPx;
                        parent.style.maxWidth = widthPx;
                        parent.style.minWidth = widthPx;
                        parent.style.height = heightPx;
                        parent.style.maxHeight = heightPx;
                        parent.style.minHeight = '0';
                        parent.style.overflow = 'hidden';
                        parent.style.boxSizing = 'border-box';
                    }

                    imageGrid.style.width = widthPx;
                    imageGrid.style.maxWidth = widthPx;
                    imageGrid.style.minWidth = '0';
                    imageGrid.dataset.layoutWidth = String(layoutWidth);

                    const controlsHeight = (container.querySelector('.v53-gallery-navigation')?.offsetHeight || 0)
                        + (container.querySelector('.danbooru-controls')?.offsetHeight || 0);
                    const bottomHeight = container.querySelector('.danbooru-bottom-status')?.offsetHeight || 0;
                    const gridHeight = Math.max(120, widgetHeight - controlsHeight - bottomHeight - 18);
                    imageGrid.style.height = `${gridHeight}px`;
                    imageGrid.style.maxHeight = `${gridHeight}px`;
                    imageGrid.style.setProperty('--danbooru-thumb-max-height', `${Math.max(160, Math.min(320, Math.floor(gridHeight * 0.72)))}px`);

                    cachedColumnWidth = 0;
                    requestAnimationFrame(() => {
                        cachedColumnWidth = 0;
                        updateGridLayout();
                        resizeGrid();
                    });
                }

                this.__danbooruGalleryV53Cleanup = () => {
                    for (const dialog of [...galleryDialogs]) dialog.unifiedClose();
                    clearTimeout(scrollTimeout);
                    galleryRequests.destroy("node_removed");
                    observer.disconnect();
                    searchAutocomplete?.destroy?.();
                    if (globalTooltip?.isConnected) globalTooltip.remove();
                };
            };

            const onRemoved = nodeType.prototype.onRemoved;
            nodeType.prototype.onRemoved = function () {
                this.__danbooruGalleryV53Cleanup?.();
                // 移除所有可能由该节点创建的全局UI元素
                const elementsToRemove = document.querySelectorAll(
                    ".danbooru-edit-panel, .danbooru-tag-tooltip, .danbooru-tag-context-menu, .danbooru-toast"
                );
                elementsToRemove.forEach(el => el.remove());

                // 调用原始的 onRemoved 方法
                onRemoved?.apply(this, arguments);
            };
        }
    },
});

$el("style", {
    textContent: `
    .v53-gallery-navigation {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin-bottom: 6px;
        padding: 7px;
        border: 1px solid var(--input-border-color);
        border-radius: 8px;
        background: color-mix(in srgb, var(--comfy-input-bg) 90%, transparent);
        box-sizing: border-box;
    }
    .v53-gallery-primary-row,
    .v53-gallery-context-controls,
    .v53-gallery-context-group {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
    }
    .v53-gallery-primary-row { flex-wrap: wrap; }
    .v53-gallery-tablist {
        display: inline-flex;
        gap: 3px;
        padding: 3px;
        border-radius: 7px;
        background: rgba(0, 0, 0, 0.16);
        min-width: 0;
    }
    .v53-gallery-primary-tabs { flex: 1 1 250px; }
    .v53-gallery-browse-tabs { align-self: flex-start; }
    .v53-gallery-tab {
        min-height: 32px;
        padding: 5px 13px;
        border: 1px solid transparent;
        border-radius: 5px;
        background: transparent;
        color: var(--comfy-input-text);
        cursor: pointer;
        font-size: 13px;
        line-height: 1;
    }
    .v53-gallery-tab:hover:not(:disabled) { background: rgba(123, 104, 238, 0.18); }
    .v53-gallery-tab.active,
    .v53-gallery-tab[aria-selected="true"] {
        color: #fff;
        background: #6f5bd3;
        border-color: rgba(255, 255, 255, 0.2);
    }
    .v53-gallery-tab:focus-visible { outline: 2px solid #9a8cff; outline-offset: 1px; }
    .v53-gallery-tab:disabled { opacity: 0.38; cursor: not-allowed; }
    .v53-gallery-context-controls { flex-wrap: wrap; }
    .v53-gallery-context-controls > .danbooru-search-container { flex: 1 1 320px; }
    .v53-gallery-context-group { flex: 1 1 360px; flex-wrap: wrap; }
    .v53-gallery-context-group label { font-size: 11px; opacity: 0.78; }
    .v53-gallery-select {
        min-width: 110px;
        min-height: 32px;
        padding: 4px 7px;
        border: 1px solid var(--input-border-color);
        border-radius: 5px;
        color: var(--comfy-input-text);
        background: var(--comfy-input-bg);
    }
    .v53-gallery-facet-value { flex: 1 1 180px; min-width: 150px; }
    .v53-gallery-status {
        display: flex;
        align-items: baseline;
        gap: 8px;
        min-height: 20px;
        padding: 4px 7px;
        border-radius: 5px;
        font-size: 11px;
        line-height: 1.3;
        color: var(--comfy-input-text);
        background: rgba(255, 255, 255, 0.04);
        overflow-wrap: anywhere;
    }
    .v53-gallery-status[data-state="loading"] { color: #8cc8ff; }
    .v53-gallery-status[data-state="warning"] { color: #ffd166; background: rgba(255, 193, 7, 0.08); }
    .v53-gallery-status[data-state="error"] { color: #ff8f99; background: rgba(220, 53, 69, 0.1); }
    .v53-status-details { opacity: 0.72; }
    .v53-inline-error { display: flex; flex-direction: column; align-items: center; gap: 8px; }
    .v53-retry-button {
        padding: 5px 12px;
        border: 1px solid currentColor;
        border-radius: 5px;
        color: inherit;
        background: transparent;
        cursor: pointer;
    }
    .v53-gallery-navigation [hidden] { display: none !important; }

    /* 搜索容器，用于定位建议面板 */
    .danbooru-search-container {
        position: relative;
        flex-grow: 1;
        display: flex;
        align-items: center;
    }

    .danbooru-search-input {
        /* padding-right: 28px !important; */ /* 为清空按钮留出空间, 已被新的flex布局取代 */
    }

    .danbooru-clear-search-button {
        position: absolute;
        right: 5px;
        top: 50%;
        transform: translateY(-50%);
        background: transparent;
        border: none;
        color: #999;
        cursor: pointer;
        font-size: 20px;
        line-height: 1;
        padding: 0 5px;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 22px;
        height: 22px;
        border-radius: 50%;
        transition: all 0.2s;
    }
    .danbooru-clear-search-button:hover {
        background-color: rgba(255, 255, 255, 0.1);
        color: white;
    }

    /* 自动补全建议面板 */
    .danbooru-suggestions-panel {
        display: none;
        position: absolute;
        top: 100%;
        left: 0;
        min-width: 100%;
        max-width: 600px;
        width: auto;
        background-color: var(--comfy-menu-bg);
        border: 1px solid var(--input-border-color);
        border-top: none;
        border-radius: 0 0 6px 6px;
        z-index: 1002;
        max-height: 400px;
        overflow-y: auto;
        overflow-x: hidden;
        box-shadow: 0 8px 16px rgba(0,0,0,0.3);
        white-space: nowrap;
    }

    .danbooru-suggestion-item {
        padding: 8px 12px;
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: background-color 0.2s;
        min-width: fit-content;
    }

    .danbooru-suggestion-item:hover,
    .danbooru-suggestion-item.selected {
        background-color: rgba(123, 104, 238, 0.3);
    }

    .danbooru-suggestion-name {
        color: var(--comfy-input-text);
        font-weight: 500;
        flex: 1;
        text-overflow: ellipsis;
        overflow: hidden;
        margin-right: 8px;
    }

    .danbooru-suggestion-count {
        color: #888;
        font-size: 0.9em;
        flex-shrink: 0;
    }

    /* 中文搜索建议面板 */
    .danbooru-chinese-suggestions-panel {
        display: none;
        position: absolute;
        top: 100%;
        left: 0;
        min-width: 100%;
        max-width: 500px;
        width: auto;
        background-color: var(--comfy-menu-bg);
        border: 1px solid var(--input-border-color);
        border-top: none;
        border-radius: 0 0 6px 6px;
        z-index: 1003;
        max-height: 300px;
        overflow-y: auto;
        overflow-x: hidden;
        box-shadow: 0 8px 16px rgba(0,0,0,0.3);
        white-space: nowrap;
    }

    .danbooru-chinese-suggestion-item {
        padding: 8px 12px;
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: background-color 0.2s;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        min-width: fit-content;
    }

    .danbooru-chinese-suggestion-item:last-child {
        border-bottom: none;
    }

    .danbooru-chinese-suggestion-item:hover,
    .danbooru-chinese-suggestion-item.selected {
        background-color: rgba(123, 104, 238, 0.3);
    }

    .danbooru-suggestion-chinese {
        color: var(--comfy-input-text);
        font-weight: 600;
        font-size: 0.95em;
        margin-right: 8px;
        flex-shrink: 0;
    }

    .danbooru-suggestion-english {
        color: #888;
        font-size: 0.85em;
        font-style: italic;
        flex-shrink: 0;
    }

    /* Category Dropdown Styles */
    .danbooru-category-dropdown { position: relative; display: inline-block; }
    
    /* Spinner for buttons */
    .spinner {
        width: 10px;
        height: 10px;
        border: 1px solid currentColor;
        border-top: 1px solid transparent;
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }
   
   .danbooru-category-button {
       background-color: var(--comfy-input-bg);
       color: var(--comfy-input-text);
       padding: 5px 10px;
       border: 1px solid var(--input-border-color);
       border-radius: 4px;
       cursor: pointer;
       height: 100%;
       display: flex;
       align-items: center;
       gap: 5px;
       transition: background-color 0.2s;
   }
   .danbooru-category-button:hover { background-color: var(--comfy-menu-bg); }
   .danbooru-category-button .arrow-down { transition: transform 0.2s ease-in-out; }
   .danbooru-category-button.open .arrow-down { transform: rotate(180deg); }

   .danbooru-category-list {
       visibility: hidden;
       opacity: 0;
       transform: translateY(-10px);
       transition: visibility 0.2s, opacity 0.2s, transform 0.2s ease-out;
       position: absolute;
       background-color: var(--comfy-menu-bg);
       border: 1px solid var(--input-border-color);
       border-radius: 6px;
       z-index: 1001;
       min-width: 160px;
       box-shadow: 0 5px 15px rgba(0,0,0,0.3);
       padding: 6px;
       backdrop-filter: blur(5px);
   }
   .danbooru-category-list.show {
       visibility: visible;
       opacity: 1;
       transform: translateY(0);
   }

   .danbooru-category-item {
       display: flex;
       align-items: center;
       padding: 6px 10px;
       color: var(--comfy-input-text);
       border-radius: 4px;
       transition: background-color 0.2s;
   }
   .danbooru-category-item:hover { background-color: rgba(255, 255, 255, 0.1); }
   .danbooru-rating-dropdown .danbooru-category-item { cursor: pointer; }
   .danbooru-category-item label { margin-left: 10px; cursor: pointer; user-select: none; }
   
   .danbooru-category-checkbox {
       appearance: none;
       -webkit-appearance: none;
       width: 16px;
       height: 16px;
       border-radius: 4px;
       border: 2px solid #555;
       cursor: pointer;
       position: relative;
       transition: background-color 0.2s, border-color 0.2s;
   }
   .danbooru-category-checkbox:checked {
       background-color: #7B68EE;
       border-color: #7B68EE;
   }
   .danbooru-category-checkbox:checked::before {
       content: '✔';
       font-size: 12px;
       color: white;
       position: absolute;
       top: 50%;
       left: 50%;
       transform: translate(-50%, -50%);
   }

    .danbooru-gallery { width: 100%; display: flex; flex-direction: column; min-height: 0; box-sizing: border-box; overflow: hidden; }
    .danbooru-gallery.danbooru-gallery-embedded { position: relative; transform: none; flex: 1 1 0; width: 100%; max-width: none; min-width: 0; height: 100%; max-height: none; min-height: 0; overflow: auto; }
    .danbooru-gallery-embedded > :not(.danbooru-image-grid) { flex-shrink: 0; }
    .danbooru-gallery-embedded > .danbooru-image-grid { flex: 1 1 0; width: 100%; max-width: none; min-width: 0; height: 0; max-height: none; min-height: 160px; }
    .danbooru-gallery-embedded > .danbooru-bottom-status { position: static !important; padding: 6px; }
    .danbooru-controls { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 5px; align-items: stretch; }
    .danbooru-auth-controls { display: flex; gap: 5px; }
    .danbooru-controls > button, .danbooru-controls > div { padding: 5px; border-radius: 4px; border: 1px solid var(--input-border-color); background-color: var(--comfy-input-bg); color: var(--comfy-input-text); }
    .danbooru-controls > .danbooru-search-container > .danbooru-search-input { background: var(--comfy-input-bg); border: 1px solid var(--input-border-color); padding: 5px 10px; border-radius: 4px; }
    .danbooru-controls .danbooru-search-input { flex-grow: 1; min-width: 150px; }
    .danbooru-controls > select { min-width: 100px; }
    .danbooru-image-wrapper.new-item { animation: fadeInUp 0.5s ease-out; }
    @keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
    .danbooru-settings-button {
        flex-grow: 0;
        width: 40px;
        height: 40px;
        aspect-ratio: 1;
        padding: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: background-color 0.2s, transform 0.2s;
        background-color: var(--comfy-input-bg);
        color: var(--comfy-input-text);
        border: 1px solid var(--input-border-color);
        border-radius: 6px;
    }
    .danbooru-settings-button:hover { background-color: var(--comfy-menu-bg); transform: scale(1.1); }
    .danbooru-settings-button .icon { width: 24px; height: 24px; }
    .danbooru-refresh-button { flex-grow: 0; width: 40px; height: 40px; aspect-ratio: 1; padding: 8px; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: background-color 0.2s, transform 0.2s; border-radius: 6px; }
    .danbooru-refresh-button:hover { background-color: var(--comfy-menu-bg); transform: scale(1.1); }
    .danbooru-refresh-button.loading { cursor: not-allowed; }
    .danbooru-filter-button { flex-grow: 0; width: 40px; height: 40px; aspect-ratio: 1; padding: 8px; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: background-color 0.2s, transform 0.2s, color 0.2s, border-color 0.2s; border-radius: 6px; }
    .danbooru-filter-button:hover { background-color: var(--comfy-menu-bg); transform: scale(1.1); }
    .danbooru-filter-button.active { background-color: #7B68EE; color: white; border-color: #7B68EE; }
    .danbooru-refresh-button.loading .icon { animation: spin 1s linear infinite; }
    .danbooru-diagnose-button { flex-grow: 0; min-width: 54px; height: 40px; padding: 0 8px; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: background-color 0.2s, transform 0.2s; border-radius: 6px; font-size: 12px; white-space: nowrap; }
    .danbooru-diagnose-button:hover { background-color: var(--comfy-menu-bg); transform: scale(1.04); }
    .danbooru-diagnose-button:disabled { opacity: 0.6; cursor: not-allowed; }
    .danbooru-diagnostic-panel { padding: 12px; margin: 8px; border: 1px solid var(--input-border-color); border-radius: 8px; background: var(--comfy-input-bg); color: var(--comfy-input-text); }
    .danbooru-diagnostic-title { font-weight: 700; margin-bottom: 6px; font-size: 14px; }
    .danbooru-diagnostic-summary { margin-bottom: 10px; color: #ffcc66; line-height: 1.45; }
    .danbooru-export-logs-button { flex-grow: 0; min-width: 68px; height: 40px; padding: 0 8px; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: background-color 0.2s, transform 0.2s; border-radius: 6px; font-size: 12px; white-space: nowrap; }
    .danbooru-export-logs-button:hover { background-color: var(--comfy-menu-bg); transform: scale(1.04); }
    .danbooru-diagnostic-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
    .danbooru-diagnostic-action, .danbooru-diagnostic-copy { padding: 6px 10px; border: 1px solid var(--input-border-color); border-radius: 4px; background: var(--comfy-menu-bg); color: var(--comfy-input-text); cursor: pointer; }
    .danbooru-diagnostic-action:hover, .danbooru-diagnostic-copy:hover { filter: brightness(1.12); }
    .danbooru-diagnostic-pre { white-space: pre-wrap; word-break: break-word; max-height: 520px; overflow: auto; padding: 10px; border-radius: 6px; background: rgba(0,0,0,0.28); font-size: 12px; line-height: 1.45; }
    .danbooru-image-wrapper[data-image-load-status="loading"],
    .danbooru-image-wrapper[data-image-load-status="queued"],
    .danbooru-image-wrapper[data-image-load-status^="fallback_after_"] { background: rgba(120, 120, 120, 0.08); }
    .danbooru-image-load-failed { min-height: 160px; background: rgba(96, 35, 35, 0.30); border: 1px solid rgba(255, 120, 120, 0.35); }
    .danbooru-image-load-failed img:not([src]) { display: none; }
    .danbooru-image-load-error { box-shadow: 0 2px 8px rgba(0,0,0,.35); }
    .danbooru-diagnostics-menu { min-width: 96px; max-width: 150px; }

    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    .danbooru-ranking-button {
        flex-grow: 0;
        width: auto;
        padding: 5px 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
        cursor: pointer;
        transition: background-color 0.2s, transform 0.2s;
        font-size: 12px;
        white-space: nowrap;
    }
    .danbooru-ranking-button:hover { background-color: var(--comfy-menu-bg); transform: scale(1.05); }
    .danbooru-ranking-button.active {
        background-color: #7B68EE;
        color: white;
        border-color: #7B68EE;
    }
    .danbooru-ranking-button .icon { width: 16px; height: 16px; }
    
    /* 收藏夹按钮样式 */
    .danbooru-favorites-button {
        flex-grow: 0;
        width: auto;
        padding: 5px 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
        cursor: pointer;
        transition: background-color 0.2s, transform 0.2s;
        font-size: 12px;
        white-space: nowrap;
    }
    .danbooru-favorites-button:hover { background-color: var(--comfy-menu-bg); transform: scale(1.05); }
    .danbooru-favorites-button.active {
        background-color: #DC3545; /* Bootstrap's danger color */
        color: white;
        border-color: #DC3545;
    }
    .danbooru-favorites-button .icon { width: 16px; height: 16px; }
    .danbooru-civitai-loose-button, .danbooru-url-export-button { display: flex; align-items: center; justify-content: center; min-width: 44px; padding: 5px 10px; cursor: pointer; font-size: 12px; }
    .danbooru-civitai-loose-button.active, .danbooru-url-export-button.active { background-color: #5865F2 !important; color: white !important; border-color: #5865F2 !important; }
    .danbooru-image-grid { display: grid; grid-template-columns: repeat(1, minmax(150px, 1fr)); grid-gap: 5px; grid-auto-rows: 1px; overflow-y: auto; overflow-x: hidden; align-content: start; justify-content: stretch; background-color: var(--comfy-input-bg); padding: 5px 30px 5px 5px; scrollbar-gutter: stable; border-radius: 4px; flex: 1 1 auto; min-height: 0; height: 0; width: 100%; max-width: none; box-sizing: border-box; }
    .danbooru-image-wrapper {
        grid-row-start: auto;
        border: 2px solid transparent;
        transition: border-color 0.2s, transform 0.2s ease-out, box-shadow 0.2s ease-out;
        border-radius: 6px;
        overflow: visible !important;
        position: relative !important; /* Add relative positioning */
        display: block !important;
        width: 100%;
        box-sizing: border-box;
    }
    .danbooru-image-wrapper:hover {
        box-shadow: 0 0 15px rgba(88, 101, 242, 0.7); /* 泛光效果 */
        z-index: 10;
        position: relative;
    }
    .danbooru-image-wrapper.selected {
        border-color: #7B68EE; /* A more vibrant purple */
        box-shadow: 0 0 20px rgba(123, 104, 238, 0.8); /* Stronger glow */
        z-index: 11;
    }

    .danbooru-image-wrapper.selected::after {
        content: "✓";
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        color: white;
        font-size: 50px;
        font-weight: bold;
        text-shadow: 0 0 10px rgba(0, 0, 0, 0.7);
        z-index: 12;
        pointer-events: none;
    }
    
    .danbooru-image-wrapper.selected::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: rgba(123, 104, 238, 0.3); /* Semi-transparent overlay */
        z-index: 11;
        pointer-events: none;
    }
    
    /* 按钮容器，位于右上角 */
    .danbooru-image-buttons {
        position: absolute;
        top: 3px;
        right: 6px;
        left: 6px;
        display: flex;
        justify-content: flex-end;
        flex-wrap: wrap;
        gap: 2px;
        opacity: 0;
        transform: scale(0.9);
        transition: all 0.2s ease !important;
        z-index: 15;
    }
    
    .danbooru-image-wrapper:hover .danbooru-image-buttons,
    .danbooru-image-wrapper:focus-within .danbooru-image-buttons {
        opacity: 1;
        transform: scale(1);
    }

    /* 通用按钮样式 */
    .danbooru-image-buttons :is(button, a) {
        background-color: rgba(0, 0, 0, 0.8) !important;
        color: white !important;
        border: none !important;
        border-radius: 50% !important;
        width: 20px !important;
        min-width: 20px !important;
        height: 20px !important;
        min-height: 20px !important;
        flex: 0 0 20px;
        box-sizing: border-box;
        text-decoration: none;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        cursor: pointer !important;
        transition: all 0.2s ease !important;
        backdrop-filter: blur(5px) !important;
        -webkit-backdrop-filter: blur(5px) !important;
        padding: 0 !important;
        margin: 0 !important;
    }

    .danbooru-image-buttons :is(button, a):hover {
        transform: scale(1.1) !important;
        background-color: rgba(123, 104, 238, 0.9) !important; /* 统一使用紫色悬浮效果 */
    }

    /* 收藏按钮特定样式 */
    .danbooru-favorite-button.favorited {
        background-color: rgba(220, 53, 69, 0.9) !important; /* DC3545 in rgba */
        color: white !important;
    }

    .danbooru-favorite-button.favorited:hover {
        background-color: rgba(123, 104, 238, 0.9) !important; /* 统一使用紫色悬浮效果 */
    }

    /* 统一所有按钮的悬浮样式 */
    .danbooru-download-button:hover,
    .danbooru-edit-button:hover,
    .danbooru-view-image-button:hover {
        background-color: rgba(123, 104, 238, 0.9) !important; /* 统一使用紫色悬浮效果 */
    }

    /* 可点击的tag样式 */
    .danbooru-clickable-tag {
        cursor: pointer !important;
        transition: transform 0.1s, filter 0.1s !important;
    }
    .danbooru-clickable-tag:hover {
        transform: scale(1.05) !important;
        filter: brightness(1.2) !important;
    }

    /* 旧的、独立的按钮样式将被上面的新规则取代或覆盖，为了清晰起见，我将删除它们 */
    /* 收藏按钮样式 - 位于右上角最右侧 (旧) */
    .danbooru-gallery .danbooru-image-grid .danbooru-image-wrapper .danbooru-favorite-button-old {
        position: absolute !important;
        top: 3px !important;
        right: 3px !important;
        bottom: auto !important;
        left: auto !important;
        border: none !important;
        /* Keep this empty or remove it. The styles are now in .danbooru-image-buttons button */
    }
    
    /* All button styles are now handled by .danbooru-image-buttons and its children. */
    /* The individual hover/visibility rules are replaced by the container's hover effect. */
    
    .danbooru-image-grid img {
        width: 100%;
        height: auto;
        max-height: var(--danbooru-thumb-max-height, 320px);
        object-fit: cover;
        cursor: pointer;
        display: block;
    }
    .danbooru-image-grid.danbooru-diagnostic-mode {
        display: block;
        overflow-y: auto;
        overflow-x: hidden;
        grid-template-columns: none !important;
        grid-auto-rows: auto !important;
    }
    .danbooru-image-grid.danbooru-diagnostic-mode .danbooru-status {
        display: block;
        width: auto;
        margin: 12px;
        text-align: left;
        white-space: normal;
    }
    .danbooru-diagnostic-panel {
        display: flex;
        flex-direction: column;
        width: calc(100% - 16px);
        max-width: calc(100% - 16px);
        min-height: 220px;
        height: calc(100% - 16px);
        margin: 8px;
        overflow: hidden;
        box-sizing: border-box;
    }
    .danbooru-diagnostic-pre {
        flex: 1 1 auto;
        min-height: 150px;
        max-height: none;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
        overflow-wrap: anywhere;
    }
    .danbooru-status { text-align: center; width: 100%; margin: 10px 0; color: #ccc; }
    .danbooru-status.error { color: #f55; }
    
        /* New Tooltip Styles */
        @keyframes danbooru-tooltip-fade-in {
            from { opacity: 0; transform: scale(0.95); }
            to { opacity: 1; transform: scale(1); }
        }
    
        .danbooru-tag-tooltip {
            background-color: rgba(28, 29, 31, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.6);
            padding: 8px;
            max-width: 600px;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            animation: danbooru-tooltip-fade-in 0.15s ease-out;
            transition: opacity 0.15s, transform 0.15s;
            pointer-events: none; /* Disable mouse interaction */
        }

        .danbooru-tooltip-tags {
            display: flex;
            flex-direction: column;
            gap: 8px; /* Space between sections */
        }

        .danbooru-tooltip-section {
            display: flex;
            flex-direction: column;
        }

        .danbooru-tooltip-upload-date {
            color: #a0a3a8;
            font-size: 0.8em;
            margin-top: 2px;
        }

        .danbooru-tooltip-category-header {
            font-size: 0.85em;
            font-weight: 600;
            color: #b0b3b8;
            margin-bottom: 4px;
        }

        .danbooru-tooltip-tags-wrapper {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
        }
    
        .danbooru-tooltip-tag {
            font-size: 0.8em;
            font-weight: 500;
            color: white;
            padding: 2px 6px;
            border-radius: 4px;
            cursor: default; /* Change cursor to default */
            transition: none; /* Remove transitions */
        }
    
        .danbooru-tooltip-tag:hover {
            transform: none; /* Remove hover effect */
            filter: none; /* Remove hover effect */
        }
    
        .danbooru-tooltip-tag.copied {
            animation: danbooru-tag-copied-animation 0.6s ease-out;
        }
    
        @keyframes danbooru-tag-copied-animation {
            0% { transform: scale(1); }
            50% { transform: scale(1.1); background-color: #ffffff; color: #000000; }
            100% { transform: scale(1); }
        }
        
        /* Tag Colors */
        /* Tag Colors based on new categories */
        .danbooru-tooltip-tag.tag-category-artist { background-color: #FFF3CD; color: #664D03; } /* Artist: Light Yellow */
        .danbooru-tooltip-tag.tag-category-copyright { background-color: #F8D7DA; color: #58151D; } /* Copyright: Light Pink */
        .danbooru-tooltip-tag.tag-category-character { background-color: #D4EDDA; color: #155724; } /* Character: Light Green */
        .danbooru-tooltip-tag.tag-category-general { background-color: #D1ECF1; color: #0C5460; } /* General: Light Blue */
        .danbooru-tooltip-tag.tag-category-meta { background-color: #F8F9FA; color: #383D41; border: 1px solid #DFE2E5; } /* Meta: Light Grey */
        
        /* 黑名单对话框样式 */
        .danbooru-blacklist-dialog * { box-sizing: border-box; }
        .danbooru-blacklist-dialog textarea:focus { outline: 2px solid #7B68EE; }
        .danbooru-blacklist-dialog button:hover { opacity: 0.9; }
        
        /* 语言切换按钮样式 */
        .danbooru-language-button {
            flex-grow: 0;
            width: auto;
            aspect-ratio: 1;
            padding: 5px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: background-color 0.2s, transform 0.2s;
        }
        .danbooru-language-button:hover {
            background-color: var(--comfy-menu-bg);
            transform: scale(1.1);
        }
        .danbooru-language-button .icon {
            width: 16px;
            height: 16px;
        }
        .danbooru-language-select-button {
            padding: 8px 16px;
            border: 2px solid var(--input-border-color);
            border-radius: 6px;
            background-color: var(--comfy-input-bg);
            color: var(--comfy-input-text);
            cursor: pointer;
            font-size: 14px;
            font-weight: normal;
            transition: all 0.2s ease;
        }
        .danbooru-language-select-button.active {
            border-color: #7B68EE;
            background-color: #7B68EE;
            color: white;
            font-weight: 600;
        }
        .danbooru-language-select-button:hover:not(.active) {
            border-color: #9a8ee8;
            background-color: rgba(123, 104, 238, 0.1);
        }
        /* 设置对话框样式 */
        .danbooru-settings-dialog * {
            box-sizing: border-box;
        }
        
        .danbooru-settings-dialog {
            /* backdrop-filter: blur(3px); */
            /* -webkit-backdrop-filter: blur(3px); */
        }
        
        .danbooru-settings-dialog-content {
            animation: fadeInScale 0.3s ease-out;
        }
        
        @keyframes fadeInScale {
            from {
                opacity: 0;
                transform: scale(0.9);
            }
            to {
                opacity: 1;
                transform: scale(1);
            }
        }
        
        .danbooru-settings-dialog-content h2 {
            padding: 0 10px 12px 10px !important;
        }

        .danbooru-settings-section {
            transition: all 0.2s ease;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 24px !important;
        }
        
        .danbooru-settings-section:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }
        
        .danbooru-settings-dialog button:hover {
            opacity: 0.9;
            transform: translateY(-1px);
        }
        
        .danbooru-settings-dialog button:focus {
            outline: 2px solid #7B68EE;
            outline-offset: 2px;
        }
        
        .danbooru-settings-dialog textarea:focus {
            outline: 2px solid #7B68EE;
            outline-offset: 1px;
        }
        
        .danbooru-settings-sidebar {
            display: flex;
            flex-direction: column;
            gap: 5px;
            padding-right: 15px;
            border-right: 1px solid var(--input-border-color);
            flex-shrink: 0;
            width: 180px;
            box-sizing: border-box;
            overflow: visible;
        }

        .sidebar-button {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 15px;
            border-radius: 8px;
            cursor: pointer;
            background-color: transparent;
            color: var(--comfy-input-text);
            text-align: left;
            font-size: 14px;
            font-weight: 500;
            transition: background-color 0.2s, color 0.2s;
            width: 100%;
            border: none;
            box-sizing: border-box;
            justify-content: flex-start;
        }

        .sidebar-button.active {
            background-color: rgba(123, 104, 238, 0.2) !important;
            color: #E0E0E0 !important;
            font-weight: 600 !important;
            border: none !important;
            outline: none !important;
        }

        .sidebar-button:hover {
            background-color: rgba(255, 255, 255, 0.1);
        }

        .sidebar-button-icon {
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .sidebar-button svg {
            stroke-width: 2;
        }

        .sidebar-button:focus {
            outline: none;
        }

        /* 设置对话框滚动容器样式 */
        .danbooru-settings-scroll-container {
            scrollbar-width: thin;
            scrollbar-color: rgba(123, 104, 238, 0.6) transparent;
        }
        
        .danbooru-settings-scroll-container::-webkit-scrollbar {
            width: 8px;
        }
        
        .danbooru-settings-scroll-container::-webkit-scrollbar-track {
            background: transparent;
            border-radius: 4px;
        }
        
        .danbooru-settings-scroll-container::-webkit-scrollbar-thumb {
            background: rgba(123, 104, 238, 0.6);
            border-radius: 4px;
            transition: background 0.2s ease;
        }
        
        .danbooru-settings-scroll-container::-webkit-scrollbar-thumb:hover {
            background: rgba(123, 104, 238, 0.8);
        }
        
        /* 社交链接按钮样式 */
        .danbooru-settings-dialog button[title*="GitHub"]:hover {
            background-color: #1c2128 !important;
            border-color: #1c2128 !important;
            transform: translateY(-1px);
        }

        .danbooru-settings-dialog button[title*="Discord"]:hover {
            background-color: #4752c4 !important;
            border-color: #4752c4 !important;
            transform: translateY(-1px);
        }

        .danbooru-settings-dialog button[title*="GitHub"]:hover svg,
        .danbooru-settings-dialog button[title*="Discord"]:hover svg {
            transform: scale(1.1);
        }

        /* 移除社交链接按钮的focus效果 */
        .danbooru-settings-dialog button[title*="GitHub"]:focus,
        .danbooru-settings-dialog button[title*="Discord"]:focus {
            outline: none !important;
        }

        .danbooru-settings-dialog button svg {
            flex-shrink: 0;
            transition: transform 0.2s ease;
        }

        /* Toast提示样式 */
        #danbooru-gallery-toast-container {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 999999;
            display: flex;
            flex-direction: column;
            gap: 8px;
            align-items: flex-end;
        }
        .danbooru-toast {
            padding: 12px 20px;
            border-radius: 6px;
            color: white;
            font-size: 14px;
            font-weight: 500;
            max-width: 300px;
            word-wrap: break-word;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            opacity: 0;
            transform: translateX(100%);
            transition: opacity 0.3s ease-out, transform 0.3s ease-out;
        }
        .danbooru-toast.show {
            opacity: 1;
            transform: translateX(0);
        }

        .danbooru-toast-success {
            background-color: #28a745;
            border-left: 4px solid #1e7e34;
        }

        .danbooru-toast-error {
            background-color: #dc3545;
            border-left: 4px solid #bd2130;
        }

        .danbooru-toast-info {
            background-color: #17a2b8;
            border-left: 4px solid #117a8b;
        }

        @keyframes toastSlideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }

        .danbooru-toast.fade-out {
            animation: toastFadeOut 0.3s ease-out forwards;
        }

        @keyframes toastFadeOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }
        `,
    parent: document.head,
});

$el("style", {
    textContent: `
    /* 编辑面板样式 */
    .danbooru-edit-panel-content {
        position: relative;
    }
    .danbooru-edit-panel-close-button {
        background: transparent;
        border: none;
        color: var(--comfy-input-text);
        cursor: pointer;
        padding: 5px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background-color 0.2s, transform 0.2s;
    }
    .danbooru-edit-panel-close-button:hover {
        background-color: rgba(255, 255, 255, 0.15);
        transform: rotate(90deg);
    }
    /* Styles for the new copy and reset buttons */
    .danbooru-edit-panel-content button {
        transition: background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
    }
    .danbooru-edit-panel-content button:hover {
        background-color: rgba(123, 104, 238, 0.2); /* 统一紫色悬浮效果，增强视觉强度 */
        border-color: #7B68EE;
        color: white; /* 悬浮时文字改为白色，提高对比度 */
        transform: translateY(-2px);
    }
    .danbooru-edit-panel-content button:active {
        background-color: rgba(123, 104, 238, 0.3); /* 点击时进一步加深 */
        transform: translateY(0);
    }
    .danbooru-edit-tags-container {
        scrollbar-width: thin;
        scrollbar-color: #555 #333;
    }
    .danbooru-edit-tags-container::-webkit-scrollbar {
        width: 6px;
    }
    .danbooru-edit-tags-container::-webkit-scrollbar-track {
        background: #333;
        border-radius: 3px;
    }
    .danbooru-edit-tags-container::-webkit-scrollbar-thumb {
        background: #555;
        border-radius: 3px;
    }
    .danbooru-edit-tags-container::-webkit-scrollbar-thumb:hover {
        background: #777;
    }
    .danbooru-view-image-button:hover {
        background-color: rgba(23, 162, 184, 0.9) !important;
    }
    `,
    parent: document.head
});

$el("style", {
    textContent: `
    .danbooru-tag-context-menu {
        /* Styles are set in JS, but we can add basics here */
    }
    .danbooru-context-menu-item {
        padding: 8px 12px;
        cursor: pointer;
        font-size: 14px;
        border-radius: 4px;
        transition: background-color 0.2s;
    }
    .danbooru-context-menu-item:hover {
        background-color: rgba(123, 104, 238, 0.3);
    }
    .danbooru-add-tag-button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 22px;
        height: 22px;
        border-radius: 50%;
        border: 1px dashed #888;
        color: #888;
        background-color: transparent;
        cursor: pointer;
        font-size: 16px;
        margin-left: 5px;
        transition: all 0.2s;
    }
    .danbooru-add-tag-button:hover {
        background-color: rgba(123, 104, 238, 0.3);
        color: white;
        border-style: solid;
        border-color: #7B68EE;
    }
    .danbooru-add-tag-input {
        background-color: var(--comfy-input-bg);
        border: 1px solid #7B68EE;
        color: var(--comfy-input-text);
        border-radius: 4px;
        padding: 2px 6px;
        font-size: 0.8em;
        margin-left: 5px;
        outline: none;
    }
    .danbooru-reset-tags-button {
        padding: 8px 15px;
        border: 1px solid #7B68EE;
        border-radius: 6px;
        background-color: transparent;
        color: #7B68EE;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        transition: all 0.2s ease;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .danbooru-reset-tags-button:hover {
        background-color: rgba(123, 104, 238, 0.2);
        border-color: #7B68EE;
        color: white;
        transform: translateY(-2px);
    }
    .danbooru-add-tag-container {
        position: relative;
        display: inline-block;
    }
    .danbooru-add-tag-input {
        background-color: var(--comfy-input-bg);
        border: 1px solid #7B68EE;
        color: var(--comfy-input-text);
        border-radius: 4px;
        padding: 2px 6px;
        font-size: 0.8em;
        outline: none;
        width: 120px;
    }
    /* These panels are now attached to body, so they need absolute positioning relative to viewport */
    .danbooru-add-tag-container .danbooru-suggestions-panel,
    .danbooru-add-tag-container .danbooru-chinese-suggestions-panel,
    .danbooru-suggestions-panel, /* Add rule for when it's a direct child of body */
    .danbooru-chinese-suggestions-panel {
        position: absolute; /* Changed from relative to absolute */
        z-index: 10003; /* Ensure it's on top of the edit panel */
        width: auto;
        min-width: 150px; /* Set a minimum width */
        max-width: 450px; /* Allow it to be wider */
        max-height: 300px;
        overflow-y: auto;
    }
    `,
    parent: document.head
});

$el("style", {
    textContent: `
    .danbooru-settings-section {
        padding: 16px;
        border: 1px solid var(--input-border-color);
        border-radius: 8px;
        background-color: var(--comfy-input-bg);
    }
    .danbooru-settings-dialog input[type="datetime-local"],
    .danbooru-settings-dialog input[type="number"] {
        background-color: var(--comfy-menu-bg);
        color: var(--comfy-input-text);
        border: 1px solid var(--input-border-color);
        border-radius: 4px;
        padding: 8px;
        user-select: none;
    }
    .danbooru-primary-button {
        padding: 10px 20px;
        border: 2px solid #7B68EE;
        border-radius: 6px;
        background-color: #7B68EE;
        color: white;
        cursor: pointer;
        font-size: 14px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    .danbooru-radio-group {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 20px;
        margin: 10px 0;
    }
    .danbooru-radio-button-wrapper {
        flex: 0 0 auto;
        min-width: 140px;
    }
    .danbooru-radio-label {
        padding: 12px 20px;
        cursor: pointer;
        transition: all 0.3s ease;
        background-color: var(--comfy-input-bg);
        color: var(--comfy-input-text);
        border: 2px solid var(--input-border-color);
        border-radius: 8px;
        text-align: center;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        font-weight: 500;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        transform: translateY(0);
        position: relative;
        overflow: hidden;
    }
    .danbooru-radio-label:hover {
        background-color: rgba(123, 104, 238, 0.1);
        border-color: #7B68EE;
        color: #7B68EE;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(123, 104, 238, 0.3);
    }
    .danbooru-settings-dialog .danbooru-radio-label.checked {
        background-color: transparent;
        color: white;
        border-color: #7B68EE;
        box-shadow: 0 4px 12px rgba(123, 104, 238, 0.4);
        transform: translateY(-1px);
        font-weight: 600;
    }
    .danbooru-settings-dialog .danbooru-radio-label.checked::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: #7B68EE;
        z-index: 0;
        transition: transform 0.4s ease;
        transform: scaleX(1);
        transform-origin: left;
    }
    .danbooru-radio-label::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: #7B68EE;
        z-index: 0;
        transition: transform 0.4s ease;
        transform: scaleX(0);
        transform-origin: right;
    }
    .danbooru-radio-label:hover::before {
        transform: scaleX(1);
        transform-origin: left;
    }
    .danbooru-settings-dialog .danbooru-radio-label.checked:hover::before {
        transform: scaleX(1);
    }
    .danbooru-settings-dialog .danbooru-radio-label.checked:hover {
        background-color: transparent;
        color: white;
        border-color: #9a8ee8;
        transform: translateY(-3px);
        box-shadow: 0 6px 16px rgba(123, 104, 238, 0.5);
    }
    .danbooru-settings-dialog .danbooru-radio-label.checked:hover::before {
        background-color: #9a8ee8;
    }
    .danbooru-radio-indicator {
        display: inline-block;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        border: 2px solid #888;
        margin-right: 10px;
        transition: all 0.2s;
        flex-shrink: 0;
        z-index: 1;
        position: relative;
    }
    .danbooru-radio-label:hover .danbooru-radio-indicator {
        border-color: #7B68EE;
    }
    .danbooru-settings-dialog .danbooru-radio-label.checked .danbooru-radio-indicator {
        background-color: #7B68EE;
        border-color: #7B68EE;
        position: relative;
    }
    .danbooru-settings-dialog .danbooru-radio-label.checked .danbooru-radio-indicator::before {
        content: "";
        position: absolute;
        top: 50%;
        left: 50%;
        width: 8px;
        height: 8px;
        background-color: white;
        border-radius: 50%;
        transform: translate(-50%, -50%);
        z-index: 1;
    }
   .danbooru-input-row {
       display: flex;
       justify-content: space-between;
       align-items: center;
       width: 100%;
       padding: 8px;
       border-radius: 6px;
       transition: background-color 0.2s ease;
       cursor: pointer;
       user-select: none;
   }
   .danbooru-input-row:hover {
       background-color: rgba(255, 255, 255, 0.1);
   }
   .danbooru-input-row input {
       cursor: pointer;
   }
    .danbooru-dialog-button--secondary {
       padding: 8px 16px;
       border: 1px solid var(--input-border-color);
       border-radius: 6px;
       background-color: var(--comfy-input-bg);
       color: var(--comfy-input-text);
       cursor: pointer;
       transition: all 0.2s ease;
   }
   .danbooru-dialog-button--secondary:hover {
       background-color: var(--comfy-menu-bg);
       border-color: #999;
       transform: translateY(-2px);
       box-shadow: 0 2px 4px rgba(0,0,0,0.2);
   }

   .danbooru-dialog-button--primary {
       padding: 8px 16px;
       border: 1px solid #7B68EE;
       border-radius: 6px;
       background-color: #7B68EE;
       color: white;
       cursor: pointer;
       font-weight: 600;
       transition: all 0.2s ease;
   }
   .danbooru-dialog-button--primary:hover {
       background-color: #9a8ee8;
       border-color: #9a8ee8;
       transform: translateY(-2px);
       box-shadow: 0 4px 8px rgba(123, 104, 238, 0.3);
   }
    `,
    parent: document.head,
});


$el("style", {
    textContent: `
    /* v11: force diagnostics out of the masonry grid so report text is readable and copy buttons stay visible. */
    .danbooru-image-grid.danbooru-diagnostic-mode {
        display: block !important;
        grid-template-columns: none !important;
        grid-auto-rows: auto !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        align-content: stretch !important;
        justify-content: stretch !important;
    }
    .danbooru-image-grid.danbooru-diagnostic-mode .danbooru-diagnostic-panel {
        display: flex !important;
        flex-direction: column !important;
        width: calc(100% - 16px) !important;
        max-width: calc(100% - 16px) !important;
        height: calc(100% - 16px) !important;
        min-height: 220px !important;
        max-height: none !important;
        margin: 8px !important;
        overflow: hidden !important;
        box-sizing: border-box !important;
    }
    .danbooru-image-grid.danbooru-diagnostic-mode .danbooru-diagnostic-title,
    .danbooru-image-grid.danbooru-diagnostic-mode .danbooru-diagnostic-summary,
    .danbooru-image-grid.danbooru-diagnostic-mode .danbooru-diagnostic-actions {
        flex: 0 0 auto !important;
    }
    .danbooru-image-grid.danbooru-diagnostic-mode .danbooru-diagnostic-actions {
        position: sticky !important;
        top: 0 !important;
        z-index: 3 !important;
        background: var(--comfy-input-bg) !important;
        padding: 6px 0 10px 0 !important;
    }
    .danbooru-image-grid.danbooru-diagnostic-mode .danbooru-diagnostic-pre {
        flex: 1 1 auto !important;
        min-height: 140px !important;
        max-height: none !important;
        overflow: auto !important;
        white-space: pre-wrap !important;
        word-break: break-word !important;
        overflow-wrap: anywhere !important;
        user-select: text !important;
        margin: 0 !important;
    }
    `,
    parent: document.head
});


$el("style", {
    textContent: `
    /* "已编辑" 提示样式 */
    .danbooru-edited-indicator {
        position: absolute;
        top: 5px;
        left: 5px;
        background-color: rgba(123, 104, 238, 0.9); /* 紫色背景 */
        color: white;
        padding: 3px 8px;
        font-size: 10px;
        font-weight: bold;
        border-radius: 8px;
        z-index: 15;
        pointer-events: none;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
        animation: fadeInDown 0.3s ease-out;
        border: 1px solid rgba(255, 255, 255, 0.2);
    }

    @keyframes fadeInDown {
        from {
            opacity: 0;
            transform: translateY(-10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    `,
    parent: document.head
});
