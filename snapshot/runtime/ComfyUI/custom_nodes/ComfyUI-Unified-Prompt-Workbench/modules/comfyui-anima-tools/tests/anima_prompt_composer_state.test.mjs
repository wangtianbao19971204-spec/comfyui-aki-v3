import assert from "node:assert/strict";
import {
    COMPOSER_SECTION_ORDER,
    configureComposerNodeWithMigration,
    migrateComposerWidgetValues,
} from "../js/anima_prompt_composer_state.js";


assert.deepEqual(COMPOSER_SECTION_ORDER, [
    "style_quality",
    "artist",
    "character",
    "clothing",
    "pose",
    "background",
]);

const legacyConfig = {
    widgets_values: [
        true,
        false,
        true,
        false,
        true,
        "trigger_tags",
        1234,
        "randomize",
        2,
        false,
        "old prompt",
        null,
    ],
};
assert.equal(migrateComposerWidgetValues(legacyConfig), true);
assert.deepEqual(legacyConfig.widgets_values, [
    true,
    true,
    false,
    true,
    true,
    false,
    "trigger_tags",
    1234,
    "randomize",
    2,
    false,
    "old prompt",
    null,
]);

const currentConfig = {
    widgets_values: [
        false,
        true,
        true,
        true,
        true,
        true,
        "trigger",
    ],
};
assert.equal(migrateComposerWidgetValues(currentConfig), false);
assert.equal(currentConfig.widgets_values.length, 7);

const lifecycleConfig = {
    widgets_values: [
        false,
        true,
        false,
        true,
        false,
        "trigger_tags",
        9876,
        "randomize",
        3,
        true,
        "persisted prompt",
        null,
    ],
};
let valuesSeenByBaseConfigure = null;
const lifecycleResult = configureComposerNodeWithMigration(
    function (config) {
        valuesSeenByBaseConfigure = [...config.widgets_values];
        return "configured";
    },
    {},
    [lifecycleConfig],
);
assert.equal(lifecycleResult, "configured");
assert.deepEqual(valuesSeenByBaseConfigure, [
    true,
    false,
    true,
    false,
    false,
    true,
    "trigger_tags",
    9876,
    "randomize",
    3,
    true,
    "persisted prompt",
    null,
]);

console.log("anima_prompt_composer_state tests passed");
