import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {JSDOM} from '../../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const base=path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench');
const dom=new JSDOM('',{url:'http://localhost/'}),d=dom.window.document,root=d.documentElement;
const sheets=['web/anime.css','web/ui_identity.css','web/studio.css','modules/comfyui-lora-manager/static/css/workbench.css'].map(name=>{
    const style=d.createElement('style');style.textContent=fs.readFileSync(path.join(base,name),'utf8');d.head.append(style);return style.sheet;
});
function palette(theme,dark){
    root.dataset.uwTheme=theme;root.classList.toggle('dark-theme',dark);
    const values={};
    for(const sheet of sheets)for(const rule of sheet.cssRules){
        if(!rule.selectorText?.startsWith(':root')||rule.selectorText.includes(' ')||!root.matches(rule.selectorText))continue;
        for(let i=0;i<rule.style.length;i++)values[rule.style[i]]=rule.style.getPropertyValue(rule.style[i]).trim();
    }
    return values;
}
const day=palette('light',false),night=palette('dark',true),colorDay=palette('anime',false),colorNight=palette('anime',true);
for(const p of [night,colorDay,colorNight]){
    for(const key of ['--uw-art-studio','--uw-art-library','--uw-radius'])assert.equal(p[key],day[key],key+' must remain shared');
}
assert.equal(day['--uw-scheme'],'light');assert.equal(night['--uw-scheme'],'dark');
assert.equal(colorDay['--uw-scheme'],'light');assert.equal(colorNight['--uw-scheme'],'dark');
assert.notEqual(day['--uw-bg'],night['--uw-bg']);assert.notEqual(night['--uw-panel'],colorNight['--uw-panel']);
assert.notEqual(night['--uw-art-filter'],day['--uw-art-filter']);
for(const theme of ['dark','light'])assert.deepEqual(palette(theme,true),palette(theme,false));

function inspect(rules){
    for(const rule of rules){
        if(rule.cssRules)inspect(rule.cssRules);
        if(!/data-uw-theme\s*=/.test(rule.selectorText||''))continue;
        for(let i=0;i<rule.style.length;i++){
            const name=rule.style[i];
            assert(name.startsWith('--uw-'),'theme-specific component geometry: '+rule.selectorText+' / '+name);
            assert(!/radius|width|height|gap|font|padding|margin/.test(name),'geometry token changes per theme: '+name);
        }
    }
}
for(const sheet of sheets)inspect(sheet.cssRules);
const sharedRules=[...sheets[0].cssRules].filter(rule=>rule.selectorText?.startsWith(':root[data-uw-theme] body'));
assert(sharedRules.some(rule=>rule.selectorText.endsWith('.uw-anime-intro')&&rule.style.display==='flex'));
assert(sharedRules.some(rule=>rule.selectorText.endsWith('#uap-workbench-nav')));
assert(sharedRules.some(rule=>rule.selectorText.includes('.uw-selector-panel')));

const luminance=color=>color.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
const ratios=[];
for(const [theme,p] of Object.entries({day,night,colorDay,colorNight})){
    for(const [fg,bg] of [['text','anime-hero'],['muted','anime-hero'],['on-accent','accent-end']]){
        const values=[luminance(p['--uw-'+fg]),luminance(p['--uw-'+bg])].sort((a,b)=>b-a),ratio=(values[0]+.05)/(values[1]+.05);
        assert(ratio>=4.5,theme+' '+fg+'/'+bg+' contrast '+ratio);ratios.push({theme,fg,bg,ratio:Number(ratio.toFixed(2))});
    }
}
const checks=['day, night and both color appearances use exactly the same illustration URLs and radius', 'variants keep expected light/dark behavior and distinct palettes', 'variant-specific rules cannot change component layout, spacing or font geometry', 'illustrated headers, UAP navigation and selectors share the same component rules', '12 hero-text and gradient-button color pairs meet 4.5:1'];
fs.writeFileSync(new URL('./variants_results.json',import.meta.url),JSON.stringify({passed:true,checks,ratios,visualAcceptance:'CSS and palette contract checks only; browser layout remains unverified'},null,2));
console.log(checks.join('\n'));dom.window.close();
