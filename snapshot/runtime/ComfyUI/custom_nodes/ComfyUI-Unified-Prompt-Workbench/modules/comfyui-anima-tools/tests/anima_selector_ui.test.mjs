import assert from "node:assert/strict";

function createFakeElement(tag) {
    return {
        tag,
        children: [],
        className: "",
        dataset: {},
        innerText: "",
        removed: false,
        style: { cssText: "" },
        appendChild(child) {
            this.children.push(child);
            return child;
        },
        remove() {
            this.removed = true;
        },
    };
}

globalThis.document = {
    createElement: createFakeElement,
};

const ui = await import("../js/anima_selector_ui.js");

assert.deepEqual(
    ui.splitPromptTokens("_raw_:one, two, , three "),
    ["one", "two", "three"],
);
assert.equal(ui.normalizePromptToken("_raw_:Hello World "), "hello world");
assert.equal(ui.escapeHtml(`<tag a="b">'&`), "&lt;tag a=&quot;b&quot;&gt;&#39;&amp;");

const element = ui.createEl("button", "sample", "Label");
assert.equal(element.className, "sample");
assert.equal(element.innerText, "Label");

const backgroundStyle = ui.createGallerySelectorStyleSheet("background");
assert.match(backgroundStyle.textContent, /\.anima-background-card/);
assert.match(backgroundStyle.textContent, /@keyframes animaBackgroundFadeIn/);

const poseStyle = ui.createGallerySelectorStyleSheet("pose");
assert.match(poseStyle.textContent, /\.anima-pose-card/);
assert.match(poseStyle.textContent, /@keyframes animaPoseFadeIn/);
assert.doesNotMatch(poseStyle.textContent, /anima-background/);

const clothingStyle = ui.createGallerySelectorStyleSheet("clothing");
assert.match(clothingStyle.textContent, /\.anima-clothing-card/);
assert.match(clothingStyle.textContent, /@keyframes animaClothingFadeIn/);
assert.doesNotMatch(clothingStyle.textContent, /anima-background/);
assert.throws(() => ui.createGallerySelectorStyleSheet("invalid kind"));

const dialog = ui.createModalShell({ maxWidth: 460, animationName: "animaPoseFadeIn" });
assert.equal(dialog.children.length, 1);
assert.match(dialog.children[0].style.cssText, /max-width: 460px/);
assert.match(dialog.children[0].style.cssText, /animation: animaPoseFadeIn/);

let confirmed = false;
const buttons = ui.createModalButtons({
    dialog,
    onConfirm: async () => {
        confirmed = true;
        return true;
    },
    cancelText: "Cancel",
    confirmText: "OK",
    buttonClass: "anima-pose-btn",
});
assert.equal(buttons.children.length, 2);
await buttons.children[1].onclick();
assert.equal(confirmed, true);
assert.equal(dialog.removed, true);

console.log("anima_selector_ui tests passed");
