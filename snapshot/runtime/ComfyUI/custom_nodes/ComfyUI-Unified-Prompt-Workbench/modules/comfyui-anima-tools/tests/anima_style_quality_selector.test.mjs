import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";


const source = await readFile(
    new URL("../js/anima_pose_selector.js", import.meta.url),
    "utf8",
);

assert.match(source, /AnimaStyleQualitySelector/);
assert.match(source, /kind: "style_quality"/);
assert.match(source, /storagePrefix: "anima-style-quality-selector"/);
assert.match(source, /loadAllOnOpen: true/);
assert.match(source, /loadSharedPromptItems\(sharedKind\)/);
assert.match(source, /style_quality_tags/);
assert.match(source, /Open Style \/ Quality Selector/);
assert.match(source, /openPoseSelectorModal\(this, tagsWidget, null, selectorConfig\)/);

console.log("anima_style_quality_selector tests passed");
