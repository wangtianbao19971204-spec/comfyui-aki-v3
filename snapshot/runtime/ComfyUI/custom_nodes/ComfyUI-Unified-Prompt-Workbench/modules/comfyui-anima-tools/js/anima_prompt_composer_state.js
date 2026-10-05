export const COMPOSER_SECTION_ORDER = Object.freeze([
    "style_quality",
    "artist",
    "character",
    "clothing",
    "pose",
    "background",
]);

export function migrateComposerWidgetValues(config) {
    const values = config?.widgets_values;
    if (!Array.isArray(values) || values.length < 6) return false;
    const legacyToggles = values.slice(0, 5);
    if (!legacyToggles.every(value => typeof value === "boolean")) return false;
    if (typeof values[5] === "boolean") return false;

    const [artist, character, clothing, background, pose] = legacyToggles;
    values.splice(
        0,
        5,
        true,
        artist,
        character,
        clothing,
        pose,
        background,
    );
    return true;
}

export function configureComposerNodeWithMigration(originalConfigure, node, args) {
    migrateComposerWidgetValues(args?.[0]);
    if (typeof originalConfigure !== "function") return undefined;
    return originalConfigure.apply(node, args);
}
