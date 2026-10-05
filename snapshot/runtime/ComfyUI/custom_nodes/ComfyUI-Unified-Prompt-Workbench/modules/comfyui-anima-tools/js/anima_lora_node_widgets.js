const CONTROL_HEIGHT = 28;
const SIDE_MARGIN = 14;
const SWITCH_WIDTH = 34;
const SWITCH_HEIGHT = 18;
const CLOSE_SIZE = 22;
const CLOSE_RIGHT_INSET = 6;

function getLoraBaseName(name) {
    let displayName = String(name || "");
    if (displayName.endsWith(".safetensors")) {
        displayName = displayName.slice(0, -12);
    }
    const lastSlash = Math.max(displayName.lastIndexOf("/"), displayName.lastIndexOf("\\"));
    if (lastSlash !== -1) {
        displayName = displayName.substring(lastSlash + 1);
    }
    return displayName || "LoRA";
}

function truncateForWidth(text, maxChars) {
    if (text.length <= maxChars) return text;
    if (maxChars <= 8) return text.slice(0, Math.max(1, maxChars - 1)) + "...";
    const head = Math.ceil((maxChars - 3) * 0.68);
    const tail = Math.max(0, maxChars - 3 - head);
    return `${text.slice(0, head)}...${tail > 0 ? text.slice(-tail) : ""}`;
}

export function getAdaptiveLoraName(name, nodeWidth) {
    const fullName = getLoraBaseName(name);
    const width = Math.max(180, Number(nodeWidth || 240));
    const maxChars = Math.max(12, Math.floor((width - 112) / 7));
    return truncateForWidth(fullName, maxChars);
}

function roundedRect(ctx, x, y, width, height, radius) {
    const r = Math.max(0, Math.min(radius, width / 2, height / 2));
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, width, height, r);
        return;
    }
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + width - r, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + r);
    ctx.lineTo(x + width, y + height - r);
    ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    ctx.lineTo(x + r, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
}

function isPrimaryPointerEvent(event) {
    if (!event?.type) return true;
    return event.type === "pointerdown" || event.type === "mousedown";
}

export function createLoraControlWidget({
    loraName,
    enabled = true,
    onToggle,
    onRemove,
}) {
    let displayEnabled = enabled !== false;
    const widget = {
        type: "custom",
        name: `anima_lora_control:${loraName}`,
        value: displayEnabled,
        options: {},
        serialize: false,
        computedHeight: CONTROL_HEIGHT,
        __animaWidgetType: "lora_control",
        __animaLoraName: loraName,
        __animaDisplayName: getLoraBaseName(loraName),
        tooltip: loraName,

        computeSize(width) {
            return [width || 240, CONTROL_HEIGHT];
        },

        draw(ctx, node, width, y, height) {
            const rowHeight = Math.min(CONTROL_HEIGHT, Math.max(24, height || CONTROL_HEIGHT));
            const rowY = y + Math.max(0, ((height || CONTROL_HEIGHT) - rowHeight) / 2);
            const rowWidth = Math.max(120, width - SIDE_MARGIN * 2);
            const isEnabled = displayEnabled;
            // LiteGraph still uses last_y/width for custom-widget hit testing.
            widget.last_y = y;
            widget.width = width;
            widget.__animaDrawWidth = width;
            widget.__animaDrawY = y;

            ctx.save();
            roundedRect(ctx, SIDE_MARGIN, rowY, rowWidth, rowHeight, 8);
            ctx.fillStyle = isEnabled ? "rgba(11, 140, 233, 0.10)" : "rgba(255, 255, 255, 0.035)";
            ctx.fill();
            ctx.strokeStyle = isEnabled ? "rgba(11, 140, 233, 0.34)" : "rgba(255, 255, 255, 0.10)";
            ctx.lineWidth = 1;
            ctx.stroke();

            const switchX = SIDE_MARGIN + 7;
            const switchY = rowY + (rowHeight - SWITCH_HEIGHT) / 2;
            roundedRect(ctx, switchX, switchY, SWITCH_WIDTH, SWITCH_HEIGHT, SWITCH_HEIGHT / 2);
            ctx.fillStyle = isEnabled ? "#0b8ce9" : "#4b5563";
            ctx.fill();

            ctx.beginPath();
            ctx.arc(
                isEnabled ? switchX + SWITCH_WIDTH - 9 : switchX + 9,
                switchY + SWITCH_HEIGHT / 2,
                6.5,
                0,
                Math.PI * 2,
            );
            ctx.fillStyle = "#ffffff";
            ctx.fill();

            const closeX = width - SIDE_MARGIN - CLOSE_SIZE - CLOSE_RIGHT_INSET;
            const closeY = rowY + (rowHeight - CLOSE_SIZE) / 2;
            roundedRect(ctx, closeX, closeY, CLOSE_SIZE, CLOSE_SIZE, 6);
            ctx.fillStyle = "rgba(239, 68, 68, 0.10)";
            ctx.fill();
            ctx.strokeStyle = "rgba(239, 68, 68, 0.28)";
            ctx.stroke();
            ctx.fillStyle = "#f87171";
            ctx.font = "600 17px Arial";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("×", closeX + CLOSE_SIZE / 2, closeY + CLOSE_SIZE / 2 + 0.5);

            const textX = switchX + SWITCH_WIDTH + 10;
            const textRight = closeX - 9;
            ctx.beginPath();
            ctx.rect(textX, rowY, Math.max(0, textRight - textX), rowHeight);
            ctx.clip();
            ctx.fillStyle = isEnabled ? "#e5f4ff" : "#8b94a3";
            ctx.font = isEnabled ? "600 12px Arial" : "500 12px Arial";
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillText(widget.__animaDisplayName, textX, rowY + rowHeight / 2 + 0.5);
            ctx.restore();
        },

        mouse(event, pointerOffset, node) {
            if (!isPrimaryPointerEvent(event)) return false;
            const width = widget.__animaDrawWidth || node?.size?.[0] || 240;
            const x = Number(pointerOffset?.[0] || 0);
            const y = Number(pointerOffset?.[1] || 0);
            const widgetY = Number(widget.last_y ?? widget.y ?? widget.__animaDrawY ?? 0);
            if (y < widgetY || y > widgetY + CONTROL_HEIGHT) return false;

            const switchRight = SIDE_MARGIN + 7 + SWITCH_WIDTH;
            const closeLeft = width - SIDE_MARGIN - CLOSE_SIZE - CLOSE_RIGHT_INSET;
            if (x >= SIDE_MARGIN && x <= switchRight + 5) {
                displayEnabled = !displayEnabled;
                widget.value = displayEnabled;
                widget.triggerDraw?.();
                onToggle?.(displayEnabled, widget, node);
                return true;
            }
            if (x >= closeLeft - 4 && x <= closeLeft + CLOSE_SIZE + 4) {
                onRemove?.(widget, node);
                return true;
            }
            return false;
        },
    };
    return widget;
}
