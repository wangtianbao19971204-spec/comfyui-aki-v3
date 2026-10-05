import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {JSDOM,VirtualConsole} from '../../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';
const root=path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web');
const checks=[],errors=[];
const virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',e=>errors.push(e.message));
const html=fs.readFileSync(path.join(root,'anime_preview.html'),'utf8');
const dom=new JSDOM(html,{url:'http://127.0.0.1:8188/extensions/ComfyUI-Unified-Prompt-Workbench/anime_preview.html?page=library#identities',runScripts:'outside-only',virtualConsole});
const context=dom.getInternalVMContext(),w=dom.window,d=w.document,modules=new Map();
async function load(name){
 if(modules.has(name))return modules.get(name);
 const source=name==='preview'?d.querySelector('script[type=module]').textContent:fs.readFileSync(path.join(root,name),'utf8');
 const module=new vm.SourceTextModule(source,{context,identifier:name});modules.set(name,module);
 await module.link(spec=>load(path.basename(spec)));return module;
}
w.localStorage.setItem('uw-ui-theme','light');
let scrolled;w.HTMLElement.prototype.scrollIntoView=function(){scrolled=this.id;};
const preview=await load('preview');await preview.evaluate();
const identity=modules.get('ui_identity.js').namespace;
assert.equal(d.documentElement.dataset.uwTheme,'light');
assert.equal(w.localStorage.getItem('uw-ui-theme'),'light');
assert(!d.querySelector('#unified-workbench').hidden);
assert.equal(d.querySelector('#unified-workbench').dataset.page,'library');
assert.equal(d.activeElement.id,'identities');assert.equal(scrolled,'identities');
assert.equal(d.querySelectorAll('#preview-identities .uw-function-card').length,7);
assert.equal(d.querySelectorAll('#preview-selectors .uw-function-card').length,6);
const displayedKinds=[...d.querySelectorAll('#preview-identities .uw-function-card,#preview-selectors .uw-function-card')].map(card=>card.dataset.functionKind);
assert.deepEqual(displayedKinds.sort(),Object.keys(identity.toolIdentity).sort());
d.querySelector('#close-workbench-preview').click();assert(d.querySelector('#unified-workbench').hidden);assert.equal(d.activeElement.id,'open-workbench-preview');
d.querySelector('#open-identities-preview').click();assert(!d.querySelector('#unified-workbench').hidden);assert.equal(d.activeElement.id,'identities');
d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape'}));assert(d.querySelector('#unified-workbench').hidden);assert.equal(d.activeElement.id,'open-identities-preview');
d.querySelector('#open-console-preview').click();assert(!d.querySelector('#unified-workbench').hidden);
d.querySelector('#show-identities-preview').click();assert.equal(d.querySelector('#unified-workbench').dataset.page,'library');
const themeBefore=d.documentElement.dataset.uwTheme;
for(const value of ['light','dark']) {const picker=d.querySelector('#canvas-tone');picker.value=value;picker.dispatchEvent(new w.Event('change'));assert.equal(d.documentElement.classList.contains('dark-theme'),value==='dark');assert.equal(d.documentElement.dataset.uwTheme,themeBefore);}
checks.push('preview preserves saved theme, opens the workbench, links directly to all 13 identities, and returns keyboard focus on close');
for(const [kind,info] of Object.entries(identity.toolIdentity)){
 const host=d.createElement('section');const card=identity.mountFunctionCard(host,kind);
 assert.equal(card.querySelector('strong').textContent,info.title);
 assert.equal(card.querySelector('p').textContent,info.purpose);
 assert.equal(card.querySelector('img').getAttribute('aria-hidden'),'true');
 assert.equal(card.querySelector('button,a,input,[tabindex]'),null);
 assert(fs.existsSync(path.join(root,'assets/functions',kind+'.svg')));
}
assert.equal(Object.keys(identity.toolIdentity).length,13);
checks.push('13 tools have distinct function artwork, a visible name and purpose; decorative cards are not controls');
for(const page of ['workspace','library','models','gallery']){
 d.querySelector(`.uw-nav button[data-page=${page}]`).click();
 assert.equal(d.querySelector('#unified-workbench').dataset.page,page);
 assert.equal(d.querySelector('#preview-purpose .uw-function-card').dataset.functionKind,page);
 assert.equal(d.querySelector('.uw-anime-copy h2').textContent,identity.toolIdentity[page].title);
 assert.equal(d.querySelectorAll('.uw-page:not([hidden])').length,1);
 assert.equal(d.querySelector('#preview-'+page).hidden,false);
}
checks.push('preview navigation switches actual purpose, heading and distinct content for all four pages');
const picker=d.querySelector('[data-uw-theme-toggle]');
assert.deepEqual([...picker.options].map(option=>option.textContent),['☼ 白天','☾ 夜间','✦ 多色']);
const cards=[...d.querySelectorAll('#preview-identities .uw-function-card,#preview-selectors .uw-function-card')];
const artwork=cards.map(card=>card.querySelector('img').src);
for(const value of ['dark','light','anime']){picker.value=value;picker.dispatchEvent(new w.Event('change'));assert.equal(d.documentElement.dataset.uwTheme,value);assert.equal(d.querySelectorAll('#preview-selectors .uw-function-card').length,6);assert.deepEqual([...d.querySelectorAll('#preview-identities .uw-function-card,#preview-selectors .uw-function-card')],cards);assert.deepEqual(cards.map(card=>card.querySelector('img').src),artwork);}
checks.push('day/night/color switch keeps the same 13 card elements, artwork files and functional names');
const selectorModule=await load('../modules/comfyui-anima-tools/js/anima_selector_ui.js');await selectorModule.evaluate();
const overlay=d.createElement('div');overlay.innerHTML='<div><aside></aside><input type="search"></div>';d.body.append(overlay);
const release=selectorModule.namespace.installSelectorExperience(overlay,'pose'),sidebar=overlay.querySelector('aside');
for(let i=0;i<2;i++){sidebar.replaceChildren(d.createElement('button'));await new Promise(resolve=>setTimeout(resolve,0));assert.equal(sidebar.querySelectorAll('.uw-function-card').length,1);assert.equal(sidebar.querySelectorAll('button').length,1);}
release();sidebar.replaceChildren();await new Promise(resolve=>setTimeout(resolve,0));assert.equal(sidebar.childElementCount,0);overlay.remove();
checks.push('category refresh keeps exactly one purpose card; disposal stops decoration from reappearing');
// The integration suite exercises real selectors; this suite covers the preview and shared style.
const style=d.createElement('style');style.textContent=fs.readFileSync(path.join(root,'ui_identity.css'),'utf8');d.head.append(style);
assert(style.sheet.cssRules.length>20);assert.deepEqual(errors,[]);
checks.push('shared identity styles parse');
fs.writeFileSync(new URL('./identity_results.json',import.meta.url),JSON.stringify({passed:true,checks,visualAcceptance:'SVG artwork reviewed; browser page layout not covered by DOM checks'},null,2));
console.log(checks.join('\n'));w.close();
