const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),assert=require('node:assert/strict');
const RUN=__dirname,WEB='ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web';
const source=(folder,name)=>fs.readFileSync(path.join(RUN,folder,WEB,name),'utf8').replace(/\r\n/g,'\n');
const checks=[];
function test(name,fn){try{const result=fn();checks.push({name,pass:true,result});}catch(error){checks.push({name,pass:false,error:error.message});}}
const css=source('candidate','studio.css'),identity=source('candidate','ui_identity.css');
for(const name of ['ui_identity.js','ui_theme.js']){
 test(name+' syntax',()=>cp.execFileSync(process.execPath,['--input-type=module','--check'],{input:source('candidate',name),encoding:'utf8'}));
 test(name+' only asset cache version changed',()=>assert.equal(source('candidate',name).replaceAll('?v=20261005-stickers',name==='ui_theme.js'?'?v=20261005-semantic':''),source('before',name)));
}
test('13 safe square SVG files parse as XML',()=>{
 const dir=path.join(RUN,'candidate',WEB,'assets/functions');
 const files=fs.readdirSync(dir).filter(n=>n.endsWith('.svg'));assert.equal(files.length,13);
 for(const file of files){const s=fs.readFileSync(path.join(dir,file),'utf8');assert.match(s,/viewBox="0 0 48 48"/);assert.match(s,/stroke="#55577f"/);assert(!/<(?:script|image|foreignObject|animate|style)\b|\bon\w+=|(?:href|src)=/i.test(s),file);assert(s.length<3500,file);}
 const command="Get-ChildItem -LiteralPath '"+dir.replaceAll("'","''")+"' -Filter '*.svg' | ForEach-Object { [xml]$iconDocument = Get-Content -LiteralPath $_.FullName -Raw; if ($iconDocument.svg.viewBox -ne '0 0 48 48') { throw $_.Name } }; 'SVG_XML_OK'";
 assert.match(cp.execFileSync('powershell.exe',['-NoProfile','-Command',command],{encoding:'utf8'}),/SVG_XML_OK/);return {files:files.length};
});
test('all identity icon URLs versioned',()=>assert(!/\.svg['"]/.test(identity)));
test('semantic model/prompt/refinement icons override imported rules',()=>{for(const kind of ['models','prompts','refinement'])assert(css.includes('[data-desk-area='+kind+'] > h3::before'));});
test('existing no-motion rule preserved',()=>assert(css.includes('@media(prefers-reduced-motion:reduce)')));
test('no added animation or external dependency',()=>{for(const name of ['studio.css','ui_identity.css']){const s=source('candidate',name),b=source('before',name);assert.equal((s.match(/@import/g)||[]).length,(b.match(/@import/g)||[]).length);assert.equal((s.match(/@keyframes|animation:/g)||[]).length,(b.match(/@keyframes|animation:/g)||[]).length);assert(!/https?:\/\//.test(s));}});
const palettes={};let defaults;
for(const selector of [':root',':root[data-uw-theme=light]',':root[data-uw-theme=anime]',':root.dark-theme[data-uw-theme=anime]']){
 const start=css.indexOf(selector+' {');assert(start>=0,selector);
 const body=css.slice(start,css.indexOf('}',start)),vars=Object.fromEntries([...body.matchAll(/--uw-([\w-]+):\s*(#[a-f\d]{6}|\d+%)/gi)].map(m=>[m[1],m[2]]));
 if(selector===':root')defaults=vars;
 palettes[selector]={...defaults,...(selector.includes('dark-theme')?palettes[':root[data-uw-theme=anime]']:{}),...vars};
}
const rgb=hex=>hex.slice(1).match(/../g).map(x=>parseInt(x,16));
const mix=(a,b,t)=>a.map((n,i)=>n*t+b[i]*(1-t));
function luminance(c){const x=c.map(n=>{n/=255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4;});return x[0]*.2126+x[1]*.7152+x[2]*.0722;}
function contrast(a,b){const x=[luminance(a),luminance(b)].sort((a,b)=>b-a);return (x[0]+.05)/(x[1]+.05);}
for(const [theme,p] of Object.entries(palettes)){
 for(const part of ['prompts','models','switches','refinement','parameters','output']){
  test(theme+' '+part+' text on tinted heading',()=>{const ratio=contrast(rgb(p[part]),mix(rgb(p[part]),rgb(p.panel),parseInt(p.tint)/100));assert(ratio>=4.5,ratio);return {ratio:+ratio.toFixed(2)};});
 }
 for(const part of ['text','muted'])for(const surface of ['bg','panel','raised','input','sidebar']){
  test(theme+' '+part+' on '+surface,()=>{const ratio=contrast(rgb(p[part]),rgb(p[surface]));assert(ratio>=4.5,ratio);return {ratio:+ratio.toFixed(2)};});
 }
}
for(const brightness of [1,1.04])test('run gradient white contrast brightness '+brightness,()=>{
 const ratios=Array.from({length:21},(_,i)=>contrast([255,255,255],mix(rgb(defaults['run-start']),rgb(defaults['run-end']),i/20).map(n=>Math.min(n*brightness,255))));
 assert(Math.min(...ratios)>=4.5,Math.min(...ratios));return {minimum:+Math.min(...ratios).toFixed(2)};
});
const receipt={time:new Date().toISOString(),passed:checks.every(c=>c.pass),total:checks.length,checks};
fs.writeFileSync(path.join(RUN,'unit_results.json'),JSON.stringify(receipt,null,2));
console.log(JSON.stringify({passed:receipt.passed,total:checks.length,failed:checks.filter(c=>!c.pass)}));if(!receipt.passed)process.exitCode=1;
