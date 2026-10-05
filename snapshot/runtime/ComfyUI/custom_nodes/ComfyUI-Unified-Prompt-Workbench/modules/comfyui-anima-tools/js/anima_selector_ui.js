/**
 * Shared frontend primitives for Anima visual selectors.
 *
 * This module deliberately contains no selector business state. It provides
 * behavior-compatible DOM helpers and the common gallery selector stylesheet.
 */

import {mountFunctionCard} from '/extensions/ComfyUI-Unified-Prompt-Workbench/ui_identity.js';
import {createWidgetInserter, mountInsertionActions} from '/extensions/ComfyUI-Unified-Prompt-Workbench/prompt_target.js';
import {capturePromptTarget} from './anima_prompt_identity.js';

export const ANIMA_UI_TOKENS = Object.freeze({
    surface: "var(--uw-panel, #1d2330)",
    surfaceRaised: "var(--uw-raised, #252d3b)",
    border: "var(--uw-border, #394456)",
    text: "var(--uw-text, #edf1f9)",
    overlay: "var(--uw-overlay, rgba(0,0,0,0.6))",
    shadow: "var(--uw-shadow, 0 18px 45px rgba(0,0,0,0.52))",
    radius: 12,
    layerModal: 100000,
});

export function createEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.innerText = text;
    return el;
}

export function mountSelectorInsertionActions(host, {app, node, widget, resolveText, kind, getSelectedItems}) {
    const assertTarget = capturePromptTarget(node, widget, () => app.graph);
    const writer = createWidgetInserter(app, {node, widget}, {commaSeparated: true,
        fragmentKind: ['character','clothing','pose'].includes(kind) ? kind : null, validate: () => {
        try { assertTarget(); return true; }
        catch { return false; }
    }});
    writer.defaultAction = 'append_end';
    host.style.flexWrap = 'wrap';
    host.style.minWidth = '0';
    const actions = createEl('div', 'anima-selector-insertion');
    actions.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;gap:8px;min-width:0;max-width:640px';
    host.appendChild(actions);
    const status = createEl('div', 'anima-selector-insertion-status', writer.supportsActions.includes('replace_fragment')
        ? '同类替换仅作用于本页工具上次写入的片段；手改后停止替换。替换前可预览，写入后可撤销。'
        : '追加会保留原文；替换前可预览，写入后可撤销。');
    status.setAttribute('role', 'status');
    status.style.cssText = 'flex-basis:100%;font-size:12px;overflow-wrap:anywhere;color:var(--uw-muted,var(--uw-text))';
    const controls = mountInsertionActions(actions, writer, async () => {
        writer.readCurrentText();
        const text = await resolveText();
        if (!String(text || '').trim()) throw new Error('请先选择至少一条资料。');
        return text;
    }, message => { status.textContent = message; }, () => node.triggerSlot?.(0));
    const queue = createEl('button', 'anima-selector-queue', '加入待用');
    queue.type = 'button';
    queue.onclick = async () => {
        try {
            const selected = getSelectedItems?.() || [];
            if (!selected.length) throw new Error('请先选择至少一条资料。');
            if (selected.some(item => !item?.shared || !item.id || !item._semantic?.binding)) {
                throw new Error('待用列表目前只支持有稳定来源的共享词条；请取消自定义项后重试。');
            }
            const resources = selected.map(item => ({
                provider: 'anima', id: `${kind}:${item.id}`, kind, sourceId: String(item.id),
                sourceBinding: item._semantic.binding,
                title: item.name_zh || item.name || String(item.id),
                text: item.tags,
                usage: 'positive',
            }));
            if (typeof window.unifiedQueuePrompts !== 'function') throw new Error('统一工作台尚未就绪，请刷新页面后重试。');
            const result = await window.unifiedQueuePrompts(resources);
            status.textContent = result.added
                ? `已加入 ${result.added} 条待用${result.duplicate ? `；${result.duplicate} 条已存在，未重复加入` : ''}。应用前会复核原资料。`
                : `${result.duplicate} 条资料已在待用列表，未重复加入。`;
        } catch (error) { status.textContent = error.message || String(error); }
    };
    actions.appendChild(queue);
    for (const control of [controls.picker, controls.apply, controls.cancelPreview, controls.undo, queue]) {
        control.style.cssText = 'border:1px solid var(--uw-border);border-radius:7px;padding:8px 10px;background:var(--uw-raised,var(--uw-panel));color:var(--uw-text);font:inherit;max-width:100%';
    }
    actions.appendChild(status);
    return {...controls, queue, dispose: () => writer.dispose()};
}

export function installSelectorDialog(overlay, {label, initialFocus, close}) {
    const previousFocus = document.activeElement;
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", label);
    overlay.tabIndex = -1;
    overlay.unifiedFocus = () => (initialFocus || overlay).focus();
    const stopClipboard = event => event.stopPropagation();
    for (const type of ["copy", "cut", "paste"]) overlay.addEventListener(type, stopClipboard);
    const onKey = event => {
        const embedded = overlay.dataset.unifiedEmbedded === "true";
        if (event.key !== "Tab" || !embedded) event.stopPropagation();
        if (event.defaultPrevented || event.isComposing) return;
        if (event.key === "Escape") {
            event.preventDefault();
            close();
        } else if (event.key === "Tab" && !embedded) {
            const items = [...overlay.querySelectorAll('button,input,select,textarea,a[href],summary,[tabindex],[contenteditable=true]')].filter(item => {
                if (item.disabled || item.tabIndex < 0 || !item.getClientRects().length || item.closest('[hidden],[inert]')) return false;
                for (let parent = item; parent && parent !== overlay; parent = parent.parentElement) {
                    const style = getComputedStyle(parent);
                    if (style.display === "none" || style.visibility === "hidden") return false;
                    if (parent.tagName === "DETAILS" && !parent.open && !parent.querySelector("summary")?.contains(item)) return false;
                }
                return true;
            });
            const edge = event.shiftKey ? items[0] : items.at(-1);
            if (!items.length || document.activeElement === edge || document.activeElement === overlay) {
                event.preventDefault();
                (event.shiftKey ? items.at(-1) : items[0])?.focus();
            }
        }
    };
    overlay.addEventListener("keydown", onKey);
    return () => {
        overlay.removeEventListener("keydown", onKey);
        for (const type of ["copy", "cut", "paste"]) overlay.removeEventListener(type, stopClipboard);
        if (overlay.dataset.unifiedEmbedded !== "true" && previousFocus?.isConnected &&
            (document.activeElement === document.body || overlay.contains(document.activeElement))) previousFocus.focus?.();
    };
}

export async function reopenSelector(overlay, reopen) {
    const restoreFavoriteFocus = captureSelectorFavoriteFocus(overlay);
    let reopened = false;
    try {
        let result;
        if (overlay.unifiedReopen) result = await overlay.unifiedReopen(reopen);
        else {
            overlay.unifiedClose();
            result = await reopen();
        }
        reopened = true;
        return result;
    } finally { restoreFavoriteFocus(reopened, true); }
}

export function captureSelectorFavoriteFocus(overlay) {
    const button = document.activeElement;
    const card = button?.closest?.('[data-selector-key], [data-key]');
    const key = card?.dataset.selectorKey || card?.dataset.key;
    const sourceKey = button?.dataset.favoriteSourceKey || "";
    if (!overlay.contains(button) || !button?.matches('.anima-favorite-btn') || !key) return () => {};
    let interrupted = false, finished = false;
    const onInteraction = () => { interrupted = true; };
    document.addEventListener('pointerdown', onInteraction, true);
    document.addEventListener('keydown', onInteraction, true);
    const release = () => {
        document.removeEventListener('pointerdown', onInteraction, true);
        document.removeEventListener('keydown', onInteraction, true);
    };
    return (saved, reopened = false) => {
        if (finished) return;
        finished = true;
        if (!saved || interrupted) { release(); return; }
        requestAnimationFrame(() => {
            try {
                if (interrupted) return;
                const selector = reopened ? document.getElementById(overlay.id) : overlay;
                if (!selector?.isConnected || selector.closest('[inert],[hidden]') || selector.inert ||
                    !selector.getClientRects().length || getComputedStyle(selector).visibility === 'hidden') return;
                const active = document.activeElement;
                const initialFocus = reopened ? selector.querySelector('input[type=search],input[placeholder]') : null;
                if (active !== button && active !== document.body && active !== selector && active !== initialFocus) return;
                const buttons = [...selector.querySelectorAll('.anima-favorite-btn')];
                let replacement = buttons.find(candidate => {
                    const card = candidate.closest('[data-selector-key], [data-key]');
                    return (card?.dataset.selectorKey || card?.dataset.key) === key;
                });
                if (!replacement && sourceKey) {
                    const matches = buttons.filter(candidate => candidate.dataset.favoriteSourceKey === sourceKey);
                    if (matches.length === 1) replacement = matches[0];
                }
                if (replacement && !replacement.disabled && !replacement.closest('[inert],[hidden]') && replacement.getClientRects().length) {
                    replacement.focus({preventScroll:true});
                }
            } finally { release(); }
        });
    };
}

function fallbackCopy(text, callback) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
    callback?.();
}

export function copyText(text, callback) {
    if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text)
            .then(() => callback?.())
            .catch(() => fallbackCopy(text, callback));
        return;
    }
    fallbackCopy(text, callback);
}

export function debounce(fn, ms) {
    let timer = null;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), ms);
    };
}

export function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
    }[character]));
}

export function splitPromptTokens(value) {
    return String(value || "")
        .split(",")
        .map(part => part.replace(/^_raw_:/, "").trim())
        .filter(Boolean);
}

export function normalizePromptToken(value) {
    return String(value || "").replace(/^_raw_:/, "").trim().toLowerCase();
}

export function createModalShell({
    maxWidth = 400,
    animationName = "animaUiFadeIn",
} = {}) {
    const dialog = createEl("div");
    dialog.style.cssText = `
        position: fixed;
        inset: 0;
        z-index: ${ANIMA_UI_TOKENS.layerModal};
        background: ${ANIMA_UI_TOKENS.overlay};

        display: flex;
        align-items: center;
        justify-content: center;
    `;

    const content = createEl("div");
    content.style.cssText = `
        width: 90%;
        max-width: ${maxWidth}px;
        background: ${ANIMA_UI_TOKENS.surface};
        border: 1px solid ${ANIMA_UI_TOKENS.border};
        border-radius: ${ANIMA_UI_TOKENS.radius}px;
        padding: 22px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        box-shadow: ${ANIMA_UI_TOKENS.shadow};
        animation: ${animationName} 0.18s ease forwards;
    `;

    dialog.appendChild(content);
    dialog.onclick = event => {
        if (event.target === dialog) dialog.remove();
    };
    return dialog;
}

export function createModalButtons({
    dialog,
    onConfirm,
    cancelText,
    confirmText,
    buttonClass,
}) {
    const row = createEl("div");
    row.style.cssText = "display:flex;justify-content:flex-end;gap:10px;margin-top:6px;";

    const cancel = createEl("button", buttonClass, cancelText);
    cancel.onclick = () => dialog.remove();

    const confirm = createEl("button", `${buttonClass} primary`, confirmText);
    confirm.onclick = async () => {
        dialog.querySelector('.uw-dialog-error')?.remove();
        confirm.disabled = true;
        cancel.disabled = true;
        try {
            const shouldClose = await onConfirm();
            if (shouldClose !== false) dialog.remove();
        } catch (error) {
            let message = dialog.querySelector('.uw-dialog-error');
            if (!message) {
                message = createEl('p', 'uw-dialog-error');
                message.setAttribute('role', 'alert');
                row.before(message);
            }
            message.textContent = error.message || '保存失败，请重试。';
        } finally {
            confirm.disabled = false;
            cancel.disabled = false;
        }
    };

    row.appendChild(cancel);
    row.appendChild(confirm);
    return row;
}

export function installSelectorExperience(overlay, kind) {
    overlay.classList.add('uw-selector');
    overlay.dataset.selectorKind = kind;
    overlay.firstElementChild?.classList.add('uw-selector-panel');
    const sidebar = overlay.querySelector('aside, .anima-scrollbar');
    let identityObserver;
    if (sidebar) {
        sidebar.classList.add('uw-selector-sidebar');
        const card = mountFunctionCard(sidebar, kind);
        // Category refreshes replace the sidebar's children; keep its purpose card attached.
        if (card) {
            identityObserver = new MutationObserver(() => {
                if (card.parentNode !== sidebar) sidebar.prepend(card);
            });
            identityObserver.observe(sidebar, {childList:true});
        }
    }
    const search = overlay.querySelector('input[type=search],input[placeholder]');
    if (search) {
        search.setAttribute('aria-label', search.placeholder || '搜索资料');
        search.setAttribute('aria-keyshortcuts', 'Control+f Meta+f');
        search.title = 'Ctrl+F 搜索；Esc 清空；方向键浏览卡片，Enter 或空格选择';
        search.addEventListener('compositionstart', () => { search.dataset.composing = 'true'; });
        search.addEventListener('compositionend', () => { delete search.dataset.composing; search.dispatchEvent(new Event('input', {bubbles:true})); });
    }
    // Character and artist selectors predate the shared dialog implementation.
    const releaseDialog = ['character', 'artist'].includes(kind)
        ? installSelectorDialog(overlay, {label:kind==='character'?'角色选择器':'画师选择器',initialFocus:search,close:()=>overlay.unifiedClose()})
        : () => {};
    const composingInput = event => {if(event.isComposing || event.target.dataset.composing==='true')event.stopImmediatePropagation();};
    overlay.addEventListener('input',composingInput,true);
    const keyboard = event => {
        if(event.defaultPrevented || event.isComposing)return;
        if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='f'&&search){
            event.preventDefault();event.stopImmediatePropagation();search.focus();search.select();return;
        }
        if(event.key==='Escape'&&event.target===search&&search.value){
            event.preventDefault();event.stopImmediatePropagation();search.value='';search.dispatchEvent(new Event('input',{bubbles:true}));return;
        }
        if(event.target.matches('.anima-shared-resource-card')&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)){
            const card=event.target, cards=[...card.parentElement.querySelectorAll(':scope > .anima-shared-resource-card')];
            const index=cards.indexOf(card), columns=Math.max(1,getComputedStyle(card.parentElement).gridTemplateColumns.split(' ').length);
            const offset={ArrowLeft:-1,ArrowRight:1,ArrowUp:-columns,ArrowDown:columns};
            const next=event.key==='Home'?0:event.key==='End'?cards.length-1:Math.max(0,Math.min(cards.length-1,index+offset[event.key]));
            if(index>=0){event.preventDefault();event.stopImmediatePropagation();cards[next]?.focus();}
        }
        if(event.target.matches('.anima-shared-resource-card')&&['Enter',' '].includes(event.key)){
            event.preventDefault();event.stopImmediatePropagation();event.target.click();
        }
    };
    overlay.addEventListener('keydown',keyboard,true);
    return ()=>{identityObserver?.disconnect();overlay.removeEventListener('input',composingInput,true);overlay.removeEventListener('keydown',keyboard,true);releaseDialog();};
}

export function showToast(message, {
    borderColor = "var(--uw-accent)",
    visibleMs = 1300,
} = {}) {
    const toast = createEl("div", null, message);
    toast.style.cssText = `
        position: fixed;
        right: 30px;
        bottom: 30px;
        z-index: ${ANIMA_UI_TOKENS.layerModal};
        background: ${ANIMA_UI_TOKENS.surfaceRaised};
        border: 1px solid ${borderColor};
        color: ${ANIMA_UI_TOKENS.text};
        padding: 10px 18px;
        border-radius: 12px;
        box-shadow: 0 12px 28px rgba(0,0,0,0.5);
        font-size: 13px;
        font-weight: 700;
        pointer-events: none;
    `;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.transition = "opacity 0.25s ease";
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 260);
    }, visibleMs);
    return toast;
}

const GALLERY_SELECTOR_CSS = String.raw`
        @keyframes animaBackgroundFadeIn {
            from { opacity: 0; transform: scale(0.97) translateY(8px); }
            to { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes animaBackgroundSpin {
            to { transform: translate(-50%, -50%) rotate(360deg); }
        }
        @keyframes animaBackgroundShimmer {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
        }
        .anima-background-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
        .anima-background-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .anima-background-scrollbar::-webkit-scrollbar-thumb { background: var(--uw-raised); border-radius: 999px; }
        .anima-background-btn {
            border: 1px solid var(--uw-border);
            border-radius: 12px;
            background: var(--uw-raised);
            color: var(--uw-text);
            padding: 9px 14px;
            font-size: 13px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.18s ease;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            user-select: none;
            white-space: nowrap;
        }
        .anima-background-btn:hover:not(:disabled) {
            background: var(--uw-raised);
            border-color: var(--uw-border);
            color: #fff;
        }
        .anima-background-btn:disabled { opacity: 0.3; cursor: not-allowed; }
        .anima-background-btn.primary {
            background: linear-gradient(135deg, var(--uw-accent), var(--uw-accent-strong));
            border-color: var(--uw-accent);
            color: #fff;
            box-shadow: 0 8px 20px var(--uw-accent-bg);
        }
        .anima-background-btn.primary:hover:not(:disabled) {
            box-shadow: 0 10px 25px var(--uw-accent);
        }
        .anima-background-btn.danger {
            background: rgba(239,68,68,0.08);
            border-color: rgba(239,68,68,0.22);
            color: var(--uw-danger);
        }
        .anima-background-btn.active {
            background: var(--uw-accent-bg);
            border-color: var(--uw-accent);
            color: var(--uw-accent);
        }
        .anima-background-pagination {
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
        .anima-background-pagination-stats {
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
        .anima-background-pagination-stats::before {
            content: "";
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: var(--uw-accent);
            box-shadow: 0 0 14px var(--uw-accent);
            flex: 0 0 auto;
        }
        .anima-background-pagination-controls {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 8px;
            flex-wrap: wrap;
            margin-left: auto;
        }
        .anima-background-page-number {
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
        .anima-background-page-btn {
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
        .anima-background-page-btn:hover:not(:disabled) {
            background: var(--uw-accent-bg);
            color: #fff;
            border-color: var(--uw-accent);
            transform: translateY(-1px);
        }
        .anima-background-page-btn:disabled {
            opacity: 0.35;
            cursor: not-allowed;
        }
        .anima-background-page-input {
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
        .anima-background-page-input:focus {
            background: transparent;
            border-bottom-color: var(--uw-accent);
            box-shadow: none;
        }
        .anima-background-select, .anima-background-input {
            background: var(--uw-panel);
            border: 1px solid var(--uw-border);
            border-radius: 12px;
            color: var(--uw-text);
            outline: none;
            font-size: 13px;
            transition: border-color 0.18s ease, box-shadow 0.18s ease;
        }
        .anima-background-select { padding: 10px 13px; cursor: pointer; }
        .anima-background-input { padding: 11px 14px; }
        .anima-background-select:focus, .anima-background-input:focus {
            border-color: var(--uw-accent);
            box-shadow: 0 0 0 3px var(--uw-accent-bg);
        }
        .anima-background-sidebar-item {
            padding: 10px 12px;
            border-radius: 10px;
            color: var(--uw-muted);
            cursor: pointer;
            border: 1px solid transparent;
            transition: all 0.16s ease;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            font-size: 12.5px;
            font-weight: 650;
            user-select: none;
        }
        .anima-background-sidebar-item:hover {
            background: var(--uw-raised);
            color: #fff;
        }
        .anima-background-sidebar-item.active {
            background: var(--uw-accent-bg);
            border-color: var(--uw-accent);
            color: var(--uw-accent);
        }
        .anima-background-clear-filters-btn {
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
        .anima-background-clear-filters-btn:hover:not(:disabled) {
            background: var(--uw-accent-bg);
            border-color: var(--uw-accent);
            color: var(--uw-accent);
        }
        .anima-background-clear-filters-btn:disabled {
            opacity: 0.42;
            cursor: not-allowed;
        }
        .anima-background-section-header {
            color: var(--uw-muted);
            font-size: 11px;
            font-weight: 850;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin: 14px 8px 8px;
            display: flex;
            align-items: center;
            gap: 8px;
            user-select: none;
        }
        .anima-background-section-header.foldable {
            cursor: pointer;
        }
        .anima-background-section-header.foldable:hover {
            color: var(--uw-accent);
        }
        .anima-background-section-title {
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .anima-background-section-spacer {
            flex: 1;
        }
        .anima-background-section-icon-btn {
            width: 20px;
            height: 20px;
            border-radius: 6px;
            border: 1px solid var(--uw-accent-bg);
            background: var(--uw-accent-bg);
            color: var(--uw-accent);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.16s ease;
            padding: 0;
            flex: 0 0 auto;
        }
        .anima-background-section-icon-btn:hover {
            background: var(--uw-accent-bg);
            border-color: var(--uw-accent);
            color: #fff;
        }
        .anima-background-section-arrow {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            transition: transform 0.18s ease;
            flex: 0 0 auto;
        }
        .anima-background-section-arrow.collapsed {
            transform: rotate(-90deg);
        }
        .anima-background-check-row {
            display: flex;
            gap: 9px;
            align-items: flex-start;
            color: var(--uw-text);
            font-size: 12.5px;
            font-weight: 600;
            cursor: pointer;
            padding: 8px 9px;
            border-radius: 9px;
            line-height: 1.28;
            transition: background 0.15s ease;
        }
        .anima-background-check-row:hover { background: var(--uw-raised); }
        .anima-background-check-row input { margin-top: 2px; accent-color: var(--uw-accent); }
        .anima-background-card {
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
        .anima-background-card:hover {
            border-color: var(--uw-accent);
            box-shadow: 0 12px 30px rgba(0,0,0,0.38), 0 0 18px var(--uw-accent-bg);
        }
        .anima-background-card.selected {
            border-color: var(--uw-accent);
            box-shadow: 0 12px 30px rgba(0,0,0,0.36), 0 0 24px var(--uw-accent-bg);
        }
        .anima-background-card-clip {
            position: absolute;
            inset: 2px;
            z-index: 0;
            overflow: hidden;
            border-radius: 13px;
            clip-path: inset(0 round 13px);
            background: #0a0a10;
        }
        .anima-background-card img {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
            opacity: 0;
            transition: opacity 0.28s ease;
        }
        .anima-background-placeholder {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #2a1430, #101018);
            color: rgba(255,255,255,0.68);
            font-size: 46px;
            font-weight: 900;
            z-index: 1;
        }
        .anima-background-shimmer {
            position: absolute;
            inset: 0;
            background: linear-gradient(90deg, rgba(20,20,30,0.9) 25%, var(--uw-accent-bg) 50%, rgba(20,20,30,0.9) 75%);
            background-size: 200% 100%;
            animation: animaBackgroundShimmer 1.5s infinite linear;
            z-index: 2;
            pointer-events: none;
        }
        .anima-background-spinner {
            position: absolute;
            left: 50%;
            top: 50%;
            width: 26px;
            height: 26px;
            border: 2.5px solid var(--uw-accent-bg);
            border-top-color: var(--uw-accent);
            border-radius: 50%;
            animation: animaBackgroundSpin 0.85s infinite linear;
        }
        .anima-background-card-mask {
            position: absolute;
            inset: 0;
            background: linear-gradient(to top, rgba(10,10,16,0.99) 0%, rgba(10,10,16,0.72) 42%, rgba(10,10,16,0.16) 100%);
            z-index: 3;
            pointer-events: none;
        }
        .anima-background-card-info {
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
        .anima-background-card:hover .anima-background-card-info { opacity: 0; }
        .anima-background-card-title {
            color: #fff;
            font-size: 13.5px;
            font-weight: 850;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            text-shadow: 0 2px 8px rgba(0,0,0,0.72);
        }
        .anima-background-card-sub {
            color: var(--uw-text);
            font-size: 10.5px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            opacity: 0.9;
        }
        .anima-background-card-badges {
            display: flex;
            gap: 5px;
            min-width: 0;
            overflow: hidden;
        }
        .anima-background-badge {
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
        .anima-background-tags-overlay {
            position: absolute;
            inset: 0;
            z-index: 5;
            padding: 42px 12px 14px;
            box-sizing: border-box;
            opacity: 0;
            pointer-events: none;
            background: rgba(7, 7, 14, 0.76);
    
            -webkit-backdrop-filter: blur(10px);
            transition: opacity 0.2s ease;
            display: flex;
            flex-direction: column;
            gap: 10px;
            overflow: hidden;
        }
        .anima-background-card:hover .anima-background-tags-overlay {
            opacity: 1;
            pointer-events: auto;
        }
        .anima-background-tags-title {
            border: 1px solid var(--uw-accent);
            background: var(--uw-accent-bg);
            color: var(--uw-accent-text);
            border-radius: 999px;
            padding: 6px 9px;
            font-size: 11px;
            font-weight: 850;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            width: 100%;
            min-width: 0;
        }
        .anima-background-tags-list {
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
        .anima-background-tags-list::-webkit-scrollbar { display: none; }
        .anima-background-tag-pill {
            border: 1px solid var(--uw-border);
            background: var(--uw-raised);
            color: var(--uw-text);
            border-radius: 999px;
            padding: 4px 7px;
            font-size: 10.5px;
            font-weight: 650;
            line-height: 1.15;
            cursor: pointer;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .anima-background-tag-pill:hover {
            border-color: var(--uw-accent);
            color: #fff;
            background: var(--uw-accent-bg);
        }
        .anima-background-create-card {
            position: relative;
            width: 100%;
            height: 100%;
            box-sizing: border-box;
            border-radius: 16px;
            border: 2px dashed var(--uw-accent);
            background: var(--uw-raised);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            user-select: none;
            transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
        }
        .anima-background-create-card:hover {
            border-color: var(--uw-accent);
            background: var(--uw-accent-bg);
            box-shadow: 0 12px 30px rgba(0,0,0,0.32), 0 0 18px var(--uw-accent-bg);
        }
        .anima-background-create-card-content {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 12px;
            color: var(--uw-accent);
            padding: 18px;
            text-align: center;
            transition: transform 0.2s ease, color 0.2s ease;
        }
        .anima-background-create-card:hover .anima-background-create-card-content {
            color: var(--uw-accent-text);
            transform: scale(1.06);
        }
        .anima-background-icon-btn {
            position: absolute;
            right: 9px;
            z-index: 7;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            background: var(--uw-panel);
            border: 1px solid var(--uw-border);
            backdrop-filter: blur(5px);
            color: var(--uw-text);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: transform 0.15s ease, background 0.15s ease, color 0.15s ease;
        }
        .anima-background-icon-btn:hover {
            transform: scale(1.1);
            background: var(--uw-panel);
            color: var(--uw-accent);
        }
        .anima-background-selected-mark {
            position: absolute;
            top: 9px;
            left: 9px;
            z-index: 7;
            width: 24px;
            height: 24px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--uw-panel);
            border: 1px solid var(--uw-border);
            color: #fff;
            transition: all 0.15s ease;
        }
        .anima-background-card.selected .anima-background-selected-mark {
            background: var(--uw-accent-strong);
            border-color: var(--uw-accent);
        }
        .anima-background-popover {
            position: fixed;
            z-index: 1000000;
            min-width: 170px;
            max-height: 280px;
            overflow-y: auto;
            background: var(--uw-panel);
            border: 1px solid var(--uw-border);
            border-radius: 12px;
            padding: 10px;
            box-shadow: 0 14px 34px rgba(0,0,0,0.52);
        }
    `;

export function createGallerySelectorStyleSheet(kind) {
    const safeKind = String(kind || "").trim().toLowerCase();
    if (!/^[a-z][a-z0-9-]*$/.test(safeKind)) {
        throw new Error(`Invalid Anima selector kind: ${kind}`);
    }
    const styleSheet = document.createElement("style");
    styleSheet.dataset.animaSelectorStyle = safeKind;
    styleSheet.textContent = GALLERY_SELECTOR_CSS
        .replaceAll("anima-background", `anima-${safeKind}`)
        .replaceAll("animaBackground", `anima${safeKind[0].toUpperCase()}${safeKind.slice(1)}`);
    return styleSheet;
}
