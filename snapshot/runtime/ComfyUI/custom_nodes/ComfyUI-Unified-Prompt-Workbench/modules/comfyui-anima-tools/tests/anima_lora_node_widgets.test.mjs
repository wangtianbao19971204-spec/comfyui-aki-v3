import assert from "node:assert/strict";
import {
    createLoraControlWidget,
    getAdaptiveLoraName,
} from "../js/anima_lora_node_widgets.js";

assert.equal(getAdaptiveLoraName("folder/example.safetensors", 320), "example");
assert.match(getAdaptiveLoraName("a-very-long-lora-model-name-for-testing.safetensors", 180), /\.\.\./);

let toggledValue = null;
let removed = false;
let redrawCount = 0;
const widget = createLoraControlWidget({
    loraName: "folder/example.safetensors",
    enabled: true,
    onToggle: value => {
        toggledValue = value;
    },
    onRemove: () => {
        removed = true;
    },
});

const drawnText = [];
const ctx = {
    beginPath() {},
    roundRect() {},
    moveTo() {},
    lineTo() {},
    quadraticCurveTo() {},
    fill() {},
    stroke() {},
    save() {},
    restore() {},
    arc() {},
    rect() {},
    clip() {},
    fillText(text) {
        drawnText.push(text);
    },
};

widget.y = 40;
widget.triggerDraw = () => {
    redrawCount += 1;
};
widget.draw(ctx, { size: [260, 200] }, 260, 40, 28);
assert.equal(widget.last_y, 40);
assert.equal(widget.width, 260);
assert.ok(drawnText.includes("×"));
assert.ok(drawnText.includes("example"));

assert.equal(widget.mouse({ type: "pointerdown" }, [24, 52], { size: [260, 200] }), true);
assert.equal(widget.value, false);
assert.equal(toggledValue, false);
assert.equal(redrawCount, 1);

drawnText.length = 0;
widget.draw(ctx, { size: [260, 200] }, 260, 40, 28);
assert.ok(drawnText.includes("example"));

assert.equal(widget.mouse({ type: "pointerdown" }, [230, 52], { size: [260, 200] }), true);
assert.equal(removed, true);

assert.equal(widget.mouse({ type: "pointermove" }, [24, 52], { size: [260, 200] }), false);
assert.equal(widget.serialize, false);

console.log("anima_lora_node_widgets tests passed");
