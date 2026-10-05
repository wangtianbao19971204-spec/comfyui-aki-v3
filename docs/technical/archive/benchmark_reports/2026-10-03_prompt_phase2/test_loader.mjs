import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
registerHooks({resolve(specifier,context,next){
    if(specifier.startsWith('/extensions/ComfyUI-Unified-Prompt-Workbench/'))return next(pathToFileURL('G:/ComfyUI-aki-v3/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/'+specifier.split('/').at(-1)).href,context);
    return next(specifier,context);
}});
