// Resolve ComfyUI's browser extension URL while running the existing ESM tests in Node.
const prefix = '/extensions/ComfyUI-Unified-Prompt-Workbench/';

export async function resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(prefix)) {
        const file = specifier.slice(prefix.length);
        if (!file || file.includes('/') || file.includes('\\')) throw new Error(`Unexpected extension import: ${specifier}`);
        return {
            url: new URL(`../../ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/${file}`, import.meta.url).href,
            shortCircuit: true,
        };
    }
    return nextResolve(specifier, context);
}
