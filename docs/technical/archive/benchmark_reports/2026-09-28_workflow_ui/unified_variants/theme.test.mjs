import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import path from 'node:path';
import {JSDOM,VirtualConsole} from '../../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';
const root=path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench');
const source=fs.readFileSync(path.join(root,'web/ui_theme.js'),'utf8');
const css=fs.readFileSync(path.join(root,'web/studio.css'),'utf8');
const animeCss=fs.readFileSync(path.join(root,'web/anime.css'),'utf8');
const choose=(w,control,value)=>{control.value=value;control.dispatchEvent(new w.Event('change',{bubbles:true}));};
const checks=[];
async function setup(saved,blocked=false){
    const dom=new JSDOM('<main></main>',{url:'http://localhost/',runScripts:'outside-only'});
    if(saved)dom.window.localStorage.setItem('uw-ui-theme',saved);
    if(blocked)Object.defineProperty(dom.window,'localStorage',{get(){throw Error('storage disabled');}});
    const module=new vm.SourceTextModule(source,{context:dom.getInternalVMContext()});
    await module.link(()=>{});await module.evaluate();return {dom,w:dom.window,d:dom.window.document,api:module.namespace};
}
{
    const {dom,w,d,api}=await setup();
    api.installUiTheme();api.installUiTheme();assert.equal(api.getUiTheme(),'dark');
    assert.equal(d.querySelectorAll('#uw-studio-style').length,1);
    const one=api.mountThemeToggle(d.body),two=api.mountThemeToggle(d.body);
    const input=d.createElement('textarea');input.value='keep draft';d.body.append(input);input.focus();input.setSelectionRange(2,6);
    choose(w,one,'light');assert.equal(api.getUiTheme(),'light');assert.equal(w.localStorage.getItem('uw-ui-theme'),'light');
    assert.equal(one.value,two.value);assert.equal(d.activeElement,input);assert.equal(input.value,'keep draft');assert.equal(input.selectionStart,2);
    two.remove();const replacement=api.mountThemeToggle(d.body);assert.equal(replacement.value,one.value);
    choose(w,replacement,'dark');assert.equal(api.getUiTheme(),'dark');assert.equal(one.value,replacement.value);
    choose(w,replacement,'anime');assert.equal(api.getUiTheme(),'anime');assert.equal(one.value,'anime');assert.equal(w.localStorage.getItem('uw-ui-theme'),'anime');assert.equal(one.options.length,3);assert.equal(d.activeElement,input);assert.equal(input.value,'keep draft');assert.equal(input.selectionStart,2);
    api.setUiTheme('dark');api.setUiTheme('invalid');assert.equal(api.getUiTheme(),'dark');
    checks.push('default, idempotent install, all theme pickers, rerender, persistence and draft/focus preservation');
    w.dispatchEvent(new w.StorageEvent('storage',{key:'uw-ui-theme',newValue:'light'}));assert.equal(api.getUiTheme(),'light');
    w.dispatchEvent(new w.StorageEvent('storage',{key:'unrelated',newValue:'dark'}));assert.equal(api.getUiTheme(),'light');
    w.dispatchEvent(new w.StorageEvent('storage',{key:null,newValue:null}));assert.equal(api.getUiTheme(),'dark');
    checks.push('other tabs synchronize theme changes; unrelated settings do not change it');dom.window.close();
}
for(const [saved,blocked,expected] of [['anime',false,'anime'],['light',false,'light'],['corrupt',false,'dark'],[null,true,'dark']]){
    const {dom,api}=await setup(saved,blocked);api.installUiTheme();assert.equal(api.getUiTheme(),expected);api.setUiTheme('light');assert.equal(api.getUiTheme(),'light');dom.window.close();
}
checks.push('saved light/anime theme survives reload; invalid or unavailable storage remains usable');

const palette=selector=>Object.fromEntries([...css.match(new RegExp(selector+' \\{([\\s\\S]*?)\\n\\}'))[1].matchAll(/--uw-([\w-]+):\s*(#[\da-f]{6})/g)].map(m=>[m[1],m[2]]));
const palettes={animeDark:palette(':root\\.dark-theme\\[data-uw-theme=anime\\]'),dark:palette(':root'),light:palette(':root\\[data-uw-theme=light\\]'),anime:palette(':root\\[data-uw-theme=anime\\]')};
const luminance=color=>{const rgb=color.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;};
const contrast=(a,b)=>{const l=[luminance(a),luminance(b)].sort((a,b)=>b-a);return (l[0]+.05)/(l[1]+.05);};
const ratios=[];
for(const [theme,p] of Object.entries(palettes)){
    for(const [fg,bg] of [['text','bg'],['text','panel'],['text','input'],['muted','bg'],['muted','panel'],['accent-text','accent-bg'],['on-accent','accent-strong'],['danger','panel']]){
        const ratio=contrast(p[fg],p[bg]);assert(ratio>=4.5,`${theme}: ${fg}/${bg} = ${ratio}`);ratios.push({theme,fg,bg,ratio:Number(ratio.toFixed(2))});
    }
}
checks.push('32 main text/background pairs meet 4.5:1 across dark, light and both anime appearances');
{
    const errors=[],virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',e=>errors.push(e.message));
    const dom=new JSDOM('',{virtualConsole,url:'http://localhost/'});const style=dom.window.document.createElement('style');style.textContent=css;dom.window.document.head.append(style);
    assert(style.sheet.cssRules.length>150);const animeStyle=dom.window.document.createElement('style');animeStyle.textContent=animeCss;dom.window.document.head.append(animeStyle);assert(animeStyle.sheet.cssRules.length>30);assert.deepEqual(errors,[]);dom.window.close();
}
checks.push('shared stylesheet parses with all three palettes and responsive rules');
{
    const dom=new JSDOM('<section id="unified-workbench" data-density="compact"></section><iframe data-uw="model-frame" src="http://localhost/loras?uw_embed=1"></iframe>',{url:'http://localhost/',runScripts:'outside-only'});
    const w=dom.window,d=w.document,frame=d.querySelector('iframe'),child=frame.contentWindow;
    child.document.write('<html><head></head><body></body></html>');child.document.close();
    w.getComputedStyle=()=>({getPropertyValue:key=>{const theme=d.documentElement.dataset.uwTheme||'dark';const isDark=theme==='dark'||(theme==='anime'&&d.documentElement.classList.contains('dark-theme'));return key==='--uw-scheme'?(isDark?'dark':'light'):palettes[theme==='anime'&&isDark?'animeDark':theme][key.replace('--uw-','')]||'';}});
    const code=fs.readFileSync(path.join(root,'modules/comfyui-lora-manager/static/js/components/workbench.js'),'utf8');
    child.eval(code.replace(/^export /gm,''));child.installWorkbenchPanel();
    assert.equal(child.document.documentElement.dataset.theme,'dark');
    d.documentElement.dataset.uwTheme='light';await new Promise(r=>setTimeout(r,0));
    assert.equal(child.document.documentElement.dataset.theme,'light');assert.equal(child.document.body.dataset.theme,'light');
    assert.equal(child.document.documentElement.style.getPropertyValue('--uw-text'),palettes.light.text);
    const helpers=fs.readFileSync(path.join(root,'modules/comfyui-lora-manager/static/js/utils/uiHelpers.js'),'utf8');
    child.eval(helpers.slice(helpers.indexOf('export function initTheme()'),helpers.indexOf('export function toggleTheme()')).replace('export ',''));
    child.initTheme();assert.equal(child.document.documentElement.dataset.theme,'light');
    d.documentElement.dataset.uwTheme='anime';await new Promise(r=>setTimeout(r,0));assert.equal(child.document.documentElement.dataset.uwTheme,'anime');assert.equal(child.document.documentElement.dataset.theme,'light');assert.equal(child.document.documentElement.style.getPropertyValue('--uw-text'),palettes.anime.text);
    d.documentElement.classList.add('dark-theme');await new Promise(r=>setTimeout(r,0));
    assert.equal(child.document.documentElement.dataset.theme,'dark');assert.equal(child.document.body.dataset.theme,'dark');
    assert.equal(child.document.documentElement.style.getPropertyValue('--uw-text'),palettes.animeDark.text);
    d.documentElement.classList.remove('dark-theme');await new Promise(r=>setTimeout(r,0));
    assert.equal(child.document.documentElement.dataset.theme,'light');assert.equal(child.document.documentElement.style.getPropertyValue('--uw-text'),palettes.anime.text);
    child.dispatchEvent(new child.Event('pagehide'));d.documentElement.dataset.uwTheme='dark';await new Promise(r=>setTimeout(r,0));
    assert.equal(child.document.documentElement.dataset.theme,'light');dom.window.close();
}
checks.push('model iframe follows theme and native canvas dark/light changes, preserves native startup guard and releases observer');
fs.writeFileSync(new URL('./theme_results.json',import.meta.url),JSON.stringify({passed:true,checks,ratios,visualAcceptance:'not covered by DOM and palette tests'},null,2));
console.log('Anime theme: '+checks.length+' groups passed');
