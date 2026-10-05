import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { t } from "./i18n.js";
import {
    applySelectorWidgetValues,
    isAnimaPromptPlusNode,
} from "./anima_selector_random.js";

const CLIP_ENCODE_NODE_NAME = "AnimaPromptPlusClipEncode";

app.registerExtension({
    name: "AnimaPromptPlus.extension",

    async setup() {
        api.addEventListener("anima.prompt_plus_resolved", ({ detail }) => {
            const updates = detail?.nodes;
            if (!updates || typeof updates !== "object") return;
            for (const [nodeId, values] of Object.entries(updates)) {
                const node = app.graph?.getNodeById?.(Number(nodeId))
                    || app.graph?.getNodeById?.(nodeId);
                if (!node || node.type !== CLIP_ENCODE_NODE_NAME) continue;
                applySelectorWidgetValues(node, values);
                removeInternalTextControls(node);
            }
        });
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!isAnimaPromptPlusNode(nodeData.name)) return;

        const origOnCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origOnCreated?.apply(this, arguments);
            setTimeout(() => {
                reorderSelectorButtons(this);
                if (nodeData.name === CLIP_ENCODE_NODE_NAME) removeInternalTextControls(this);
            }, 0);
        };

        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = origOnConfigure?.apply(this, arguments);
            setTimeout(() => {
                reorderSelectorButtons(this);
                if (nodeData.name === CLIP_ENCODE_NODE_NAME) removeInternalTextControls(this);
            }, 0);
            return result;
        };
    }
});

function removeInternalTextControls(node) {
    if (!node) return;

    const widgetIndex = node.widgets?.findIndex(item => item?.name === "text") ?? -1;
    if (widgetIndex >= 0) {
        const [widget] = node.widgets.splice(widgetIndex, 1);
        [widget?.element, widget?.inputEl, widget?.el, widget?.container].forEach(element => {
            element?.remove?.();
        });
    }

    const inputIndex = node.inputs?.findIndex(input => input?.name === "text") ?? -1;
    if (inputIndex >= 0) {
        node.removeInput?.(inputIndex);
    }

    const currentWidth = node.size?.[0];
    const computedSize = node.computeSize?.();
    if (Number.isFinite(currentWidth) && Number.isFinite(computedSize?.[1])) {
        node.setSize?.([currentWidth, computedSize[1]]);
    }
    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
}

function reorderSelectorButtons(node) {
    if (!node?.widgets?.length) return;

    const sectionOrder = new Map([
        ["artist", 0],
        ["character", 1],
        ["clothing", 2],
        ["pose", 3],
        ["background", 4],
    ]);
    const labelOrder = new Map([
        [t("Open Artist Selector"), 0],
        [t("Open Character Selector"), 1],
        [t("Open Clothing Selector"), 2],
        [t("Open Pose Selector"), 3],
        [t("Open Background Selector"), 4],
    ]);

    const indexed = node.widgets
        .map((widget, index) => ({
            widget,
            index,
            rank: sectionOrder.get(widget?.__animaSelectorActionSection) ?? labelOrder.get(widget?.name),
        }))
        .filter(item => item.rank !== undefined);

    if (indexed.length < 2) return;

    const firstIndex = Math.min(...indexed.map(item => item.index));
    const buttonSet = new Set(indexed.map(item => item.widget));
    const sortedButtons = indexed
        .sort((a, b) => a.rank - b.rank)
        .map(item => item.widget);

    node.widgets = [
        ...node.widgets.slice(0, firstIndex).filter(widget => !buttonSet.has(widget)),
        ...sortedButtons,
        ...node.widgets.slice(firstIndex).filter(widget => !buttonSet.has(widget)),
    ];

    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
}
