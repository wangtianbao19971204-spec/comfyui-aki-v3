// Node-only mapping for the two production browser imports used by selectors.
// Node 20.6+ supports module.register; no browser source or installed tree changes.
const web = new URL('../../../web/', import.meta.url);
const extensions = new Map([
    ['/extensions/ComfyUI-Unified-Prompt-Workbench/ui_identity.js', new URL('ui_identity.js', web).href],
    ['/extensions/ComfyUI-Unified-Prompt-Workbench/prompt_target.js', new URL('prompt_target.js', web).href],
]);

export function resolve(specifier, context, nextResolve) {
    const target = extensions.get(specifier);
    if (target) return {url: target, shortCircuit: true};
    return nextResolve(specifier, context);
}
