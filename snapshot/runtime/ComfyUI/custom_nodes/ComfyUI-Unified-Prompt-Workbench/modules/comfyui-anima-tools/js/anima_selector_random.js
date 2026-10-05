import { t } from "./i18n.js";

export const SELECTOR_RANDOM_PROPERTY = "anima_selector_random";
export const ANIMA_PROMPT_PLUS_NODE_NAMES = new Set([
    "AnimaPromptPlus",
    "AnimaPromptPlusClipEncode",
]);

export function isAnimaPromptPlusNode(nodeName) {
    return ANIMA_PROMPT_PLUS_NODE_NAMES.has(nodeName);
}

function getRandomState(node) {
    node.properties = node.properties || {};
    const state = node.properties[SELECTOR_RANDOM_PROPERTY];
    if (state && typeof state === "object" && !Array.isArray(state)) {
        return state;
    }
    node.properties[SELECTOR_RANDOM_PROPERTY] = {};
    return node.properties[SELECTOR_RANDOM_PROPERTY];
}

function normalizeBoolean(value) {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value !== 0;
    const text = String(value ?? "").trim().toLowerCase();
    return text === "true" || text === "1" || text === "yes" || text === "on";
}

function isRandomEnabled(node, section) {
    return normalizeBoolean(getRandomState(node)[section]);
}

function setRandomEnabled(node, section, enabled) {
    const state = getRandomState(node);
    state[section] = Boolean(enabled);
    refreshNode(node);
}

function refreshNode(node) {
    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
    window?.app?.graph?.setDirtyCanvas?.(true, true);
}

function refreshSelectorActionRows(node) {
    const rows = node?._animaSelectorActionRows;
    if (!rows || typeof rows !== "object") return;
    Object.values(rows).forEach(row => row?.__animaSelectorRefresh?.());
}

function getWidget(node, name) {
    return node?.widgets?.find(widget => widget?.name === name);
}

function setWidgetValue(node, name, value) {
    const widget = getWidget(node, name);
    if (!widget) return;
    const text = String(value ?? "");
    widget.value = text;
    if (widget.inputEl) {
        widget.inputEl.value = text;
        widget.inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    }
    widget.callback?.(text);
}

export function applySelectorWidgetValues(node, values) {
    if (!node || !values || typeof values !== "object") return;
    for (const [name, value] of Object.entries(values)) {
        setWidgetValue(node, name, value);
    }
    refreshNode(node);
}

function extractSelectorTagsPayload(message) {
    const candidates = [
        message?.anima_selector_tags,
        message?.output?.anima_selector_tags,
        message?.ui?.anima_selector_tags,
    ];
    for (const candidate of candidates) {
        if (Array.isArray(candidate) && candidate[0] && typeof candidate[0] === "object") {
            return candidate[0];
        }
        if (candidate && typeof candidate === "object") {
            return candidate;
        }
    }
    return null;
}

function syncSelectorTagsFromExecution(node, message) {
    const payload = extractSelectorTagsPayload(message);
    if (!payload) return;
    applySelectorWidgetValues(node, payload);
}

export function installSelectorExecutionSync(nodeType) {
    if (!nodeType?.prototype || nodeType.prototype.__animaSelectorExecutionSyncInstalled) return;
    nodeType.prototype.__animaSelectorExecutionSyncInstalled = true;

    const origOnConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
        const result = origOnConfigure?.apply(this, arguments);
        setTimeout(() => {
            refreshSelectorActionRows(this);
            refreshNode(this);
        }, 0);
        return result;
    };

    const origOnExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
        const result = origOnExecuted?.apply(this, arguments);
        syncSelectorTagsFromExecution(this, message);
        refreshSelectorActionRows(this);
        return result;
    };
}

function stopNodeDrag(event) {
    event.preventDefault();
    event.stopPropagation();
}

function baseButtonStyle() {
    return `
        height: 28px;
        border-radius: 7px;
        border: 1px solid rgba(255,255,255,0.12);
        color: #e5e7eb;
        font-size: 12px;
        font-weight: 700;
        line-height: 1;
        cursor: pointer;
        pointer-events: auto;
        transition: background 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
    `;
}

function styleToggle(button, enabled) {
    button.textContent = enabled ? t("Random On") : t("Random Off");
    button.title = t("Auto randomize this selector when the workflow runs.");
    button.style.cssText = `
        ${baseButtonStyle()}
        flex: 0 0 92px;
        background: ${enabled ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.045)"};
        border-color: ${enabled ? "rgba(255,255,255,0.24)" : "rgba(255,255,255,0.10)"};
        color: ${enabled ? "#f3f4f6" : "#9ca3af"};
        box-shadow: none;
    `;
}

export function addSelectorActionRow(node, config) {
    const {
        section,
        label,
        onOpen,
    } = config || {};

    if (!node || !section || typeof onOpen !== "function") return null;
    const sharedThemes={pose:'pose_action',clothing:'clothing_accessory',background:'background_environment',character:'identity',artist:'artist_style',style_quality:'style_quality'};
    const open = async () => {
        const widget=node.widgets?.find(item=>item.name===section+'_tags');
        if(sharedThemes[section]&&widget&&window.unifiedOpenWorkbench){
            return window.unifiedOpenWorkbench({page:'library',type:'prompts',theme:sharedThemes[section],view:'all',reset:true,
                target:{node,widget,direction:'positive',label:`${node.title||node.type} #${node.id} / ${widget.name}`},
                selector:{node,section,label,native:onOpen}});
        }
        return onOpen();
    };
    // Expose the same action to workflow toolbars without relying on DOM labels.
    node.animaSelectorActions = node.animaSelectorActions || {};
    node.animaSelectorActions[section] = open;
    node._animaSelectorActionRows = node._animaSelectorActionRows || {};
    const existingRow = node._animaSelectorActionRows[section];
    if (existingRow && node.widgets?.includes(existingRow)) {
        existingRow.__animaSelectorRefresh?.();
        return existingRow;
    }
    if (existingRow) {
        delete node._animaSelectorActionRows[section];
    }

    if (typeof node.addDOMWidget !== "function") {
        const openWidget = node.addWidget("button", label, null, open);
        const toggleWidget = node.addWidget("button", isRandomEnabled(node, section) ? t("Random On") : t("Random Off"), null, () => {
            setRandomEnabled(node, section, !isRandomEnabled(node, section));
            toggleWidget.__animaSelectorRefresh?.();
        });
        toggleWidget.__animaSelectorActionSection = section;
        toggleWidget.__animaSelectorRefresh = () => {
            toggleWidget.name = isRandomEnabled(node, section) ? t("Random On") : t("Random Off");
        };
        toggleWidget.__animaSelectorRefresh();
        node._animaSelectorActionRows[section] = toggleWidget;
        return toggleWidget;
    }

    const row = document.createElement("div");
    row.className = "anima-selector-action-row";
    row.style.cssText = `
        display: flex;
        align-items: center;
        gap: 6px;
        width: 100%;
        height: 30px;
        box-sizing: border-box;
        padding: 1px 0;
        pointer-events: none;
    `;

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.textContent = label;
    openButton.style.cssText = `
        ${baseButtonStyle()}
        flex: 1 1 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        background: rgba(255,255,255,0.055);
        border-color: rgba(255,255,255,0.12);
        color: #e5e7eb;
    `;
    openButton.onmouseenter = () => {
        openButton.style.boxShadow = "none";
        openButton.style.borderColor = "rgba(255,255,255,0.22)";
        openButton.style.background = "rgba(255,255,255,0.09)";
    };
    openButton.onmouseleave = () => {
        openButton.style.boxShadow = "none";
        openButton.style.borderColor = "rgba(255,255,255,0.12)";
        openButton.style.background = "rgba(255,255,255,0.055)";
    };
    openButton.addEventListener("pointerdown", stopNodeDrag);
    openButton.addEventListener("mousedown", stopNodeDrag);
    openButton.addEventListener("click", async event => {
        stopNodeDrag(event);
        openButton.focus({preventScroll: true});
        await open();
    });

    const toggleButton = document.createElement("button");
    toggleButton.type = "button";
    const updateToggle = () => styleToggle(toggleButton, isRandomEnabled(node, section));
    updateToggle();
    toggleButton.addEventListener("pointerdown", stopNodeDrag);
    toggleButton.addEventListener("mousedown", stopNodeDrag);
    toggleButton.addEventListener("click", event => {
        stopNodeDrag(event);
        setRandomEnabled(node, section, !isRandomEnabled(node, section));
        updateToggle();
    });

    row.appendChild(openButton);
    row.appendChild(toggleButton);

    const widget = node.addDOMWidget(`anima_${section}_selector_actions`, "div", row, {
        serialize: false,
        hideOnZoom: false,
        getValue: () => "",
        setValue: () => {},
    });
    widget.__animaSelectorActionSection = section;
    widget.__animaSelectorRefresh = updateToggle;
    widget.serialize = false;
    widget.computeSize = (width) => [width, 32];
    widget.computedHeight = 32;

    node._animaSelectorActionRows[section] = widget;
    return widget;
}
