import assert from "node:assert/strict";
import fs from "node:fs";


const source = fs.readFileSync(
    new URL("../js/anima_lora_selector.js", import.meta.url),
    "utf8",
);

function extractFunction(name) {
    const start = source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `${name} is missing`);
    const bodyStart = source.indexOf("{", start);
    let depth = 0;
    for (let index = bodyStart; index < source.length; index += 1) {
        if (source[index] === "{") depth += 1;
        if (source[index] === "}") depth -= 1;
        if (depth === 0) return source.slice(start, index + 1);
    }
    throw new Error(`Unable to extract ${name}`);
}

const getOptimizedImageUrl = new Function(
    "LORA_CARD_PREVIEW_WIDTH",
    `${extractFunction("getOptimizedImageUrl")}; return getOptimizedImageUrl;`,
)(450);

const sourceUrl = [
    "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA",
    "2a9f6f60-468b-455e-9be6-017035903327",
    "original=true/141100370.jpeg",
].join("/");

assert.equal(
    getOptimizedImageUrl(sourceUrl, 450),
    sourceUrl.replace("/original=true/", "/width=450/"),
);
assert.equal(
    getOptimizedImageUrl(sourceUrl.replace("/original=true/", "/width=320/"), 512),
    sourceUrl.replace("/original=true/", "/width=512/"),
);
assert.ok(!getOptimizedImageUrl(sourceUrl, 450).includes("image-b2.civitai.com"));

console.log("anima_lora_preview_url tests passed");
