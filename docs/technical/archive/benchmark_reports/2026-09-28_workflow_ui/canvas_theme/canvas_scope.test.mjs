import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {JSDOM} from '../../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const base=path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web');
const dom=new JSDOM('<html><head></head><body><div class="danbooru-gallery"></div><section id="unified-workbench"></section></body></html>',{url:'http://localhost/'});
const d=dom.window.document,root=d.documentElement;
const sheets=['anime.css','ui_identity.css','studio.css'].map(name=>{
    const style=d.createElement('style');style.textContent=fs.readFileSync(path.join(base,name),'utf8');d.head.append(style);return style.sheet;
});
// Check the palette declarations selected by ComfyUI's real theme class.
function palette(theme,dark){
    root.dataset.uwTheme=theme;root.classList.toggle('dark-theme',dark);
    const values={};
    for(const sheet of sheets)for(const rule of sheet.cssRules){
        if(!rule.selectorText?.startsWith(':root')||rule.selectorText.includes(' ')||!root.matches(rule.selectorText))continue;
        for(let i=0;i<rule.style.length;i++){
            const key=rule.style[i];if(key.startsWith('--'))values[key]=rule.style.getPropertyValue(key).trim();
        }
    }
    return values;
}
const night=palette('anime',true),day=palette('anime',false);
assert.equal(night['--uw-scheme'],'dark');assert.equal(day['--uw-scheme'],'light');
assert.equal(night['--uw-bg'],'#202126');assert.equal(day['--uw-bg'],'#f5f6fc');
assert.notEqual(night['--uw-anime-header'],day['--uw-anime-header']);
for(const theme of ['dark','light'])assert.deepEqual(palette(theme,true),palette(theme,false));
for(const tokens of [night,day])for(const key of ['--bg-color','--comfy-menu-bg','--border-color'])assert(!(key in tokens),'native graph variables must remain owned by ComfyUI');

root.dataset.uwTheme='anime';root.classList.add('dark-theme');
const gallery=d.querySelector('.danbooru-gallery');
const matchedSurfaceRules=()=>sheets.flatMap(sheet=>[...sheet.cssRules]).filter(rule=>rule.selectorText?.includes('body .danbooru-gallery')&&gallery.matches(rule.selectorText)&&rule.style.getPropertyValue('background')).map(rule=>rule.style.getPropertyValue('background'));
const onCanvas=matchedSurfaceRules();
d.querySelector('#unified-workbench').append(gallery);gallery.classList.add('danbooru-gallery-embedded');
assert.deepEqual(matchedSurfaceRules(),onCanvas,'moving gallery into the workbench must retain the shared palette');
assert(onCanvas.includes('var(--uw-bg)'));

// A hard-coded paper background was the reported regression. All large anime
// surfaces now refer to a theme token, while art and the primary action may differ.
const animeSheet=sheets[0];
for(const rule of animeSheet.cssRules){
    if(!rule.selectorText||rule.selectorText.includes('::')||rule.selectorText.includes('[data-uw=run]'))continue;
    const background=rule.style.getPropertyValue('background');
    if(background)assert(!/#[a-f\d]{3,8}/i.test(background),rule.selectorText+' has a fixed surface color');
}
const checks=['native dark class selects anime night palette and removing it selects daylight', 'explicit dark/light themes do not depend on native canvas brightness', 'native graph palette remains untouched', 'gallery retains its palette when moved into the workbench', 'large anime surfaces contain no fixed paper backgrounds'];
fs.writeFileSync(new URL('./canvas_scope_results.json',import.meta.url),JSON.stringify({passed:true,checks,visualAcceptance:'selector and palette contract checks only; no browser rendering'},null,2));
console.log(checks.join('\n'));dom.window.close();
