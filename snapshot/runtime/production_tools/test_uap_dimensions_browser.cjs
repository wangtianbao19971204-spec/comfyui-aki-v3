// Isolated DOM acceptance: serve the real candidate JS/CSS, with unrelated services stubbed.
// Requires Playwright + Chrome (UAP_TEST_BROWSER_CHANNEL may select another installed channel).
// Never connects to ComfyUI or submits a generation task.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const wb = path.join(root, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench');
const daily = path.join(wb, 'modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js');
const prefix = '/extensions/ComfyUI-Unified-Prompt-Workbench/';
const stubControls = 'export const mountRuntimeControls=()=>({sync(){},dispose(){}}),mountRefinementControls=mountRuntimeControls,mountPromptInspector=mountRuntimeControls;export const legacyControlIssue=()=>"",refinementBatchIssue=legacyControlIssue,modelOptionIssue=legacyControlIssue;';
const html = `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="${prefix}studio.css"></head>
<body><main id="host"></main><script type="module">
const size={id:1,type:'EmptyLatentImage',mode:0,title:'尺寸',widgets:[
 {name:'width',value:1344,options:{min:16,max:16384,step:80,step2:8}},
 {name:'height',value:768,options:{min:16,max:16384,step:80,step2:8}},
 {name:'batch_size',value:1,options:{min:1,max:4096,step2:1}}]};
const sampler={id:2,type:'KSampler',mode:0,title:'采样',widgets:[{name:'seed',value:12345},{name:'steps',value:30},{name:'cfg',value:4.5},{name:'denoise',value:1}]};
const branch={id:'test',label:'隔离尺寸验收',nodeIds:[1,2]};
let depth=0,oldState;const undo=[];const state=()=>[...size.widgets,...sampler.widgets].map(w=>w.value);
const graph={links:{},extra:{uap_workbench:{branches:[branch],activeBranch:branch.id}},getNodeById:id=>[size,sampler].find(n=>n.id===id),
beforeChange(){if(depth++===0)oldState=state()},afterChange(){if(--depth===0&&JSON.stringify(state())!==JSON.stringify(oldState))undo.push(oldState)},setDirtyCanvas(){}};
globalThis.__testApp={graph,canvas:{},queuePrompt(){throw Error('Generation is forbidden in this fixture')}};
globalThis.fixture={size,sampler,branch,graph,undo,state,undoOnce(){const previous=undo.pop();[...size.widgets,...sampler.widgets].forEach((w,i)=>w.value=previous[i])}};
const {createDailyControls}=await import('/extensions/fixture/uap_daily_controls.js');
const controls=createDailyControls(()=>{});controls.mount(document.querySelector('#host'),branch,()=>{});controls.show(true);fixture.controls=controls;
document.documentElement.dataset.ready='true';
</script><style>body{margin:0;padding:16px;background:var(--uw-bg);color:var(--uw-text)}#host{max-width:1100px;margin:auto}</style></body></html>`;
const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost').pathname;
    const send = (type, content) => {res.writeHead(200, {'Content-Type':type,'Cache-Control':'no-store'});res.end(content);};
    if (url === '/') return send('text/html; charset=utf-8', html);
    if (url === '/extensions/fixture/uap_daily_controls.js') return send('text/javascript; charset=utf-8', fs.readFileSync(daily));
    if (url === '/scripts/app.js') return send('text/javascript', 'export const app=globalThis.__testApp;');
    if (url === '/scripts/api.js') return send('text/javascript', 'export const api=new EventTarget();');
    if (url === '/object_info/LoraLoader') return send('application/json', '{"LoraLoader":{"input":{"required":{"lora_name":[[]]}}}}');
    if (url === '/api/lm/settings') return send('application/json', '{"settings":{}}');
    if (url.startsWith(prefix)) {
        const name=url.slice(prefix.length);
        if (['runtime_controls.js','refinement_controls.js','prompt_inspector.js'].includes(name)) return send('text/javascript', stubControls);
        if (name==='resource_actions.js') return send('text/javascript', 'export const attachPromptAutocomplete=()=>{};');
        if (name==='ui_theme.js') return send('text/javascript', 'export const mountThemeToggle=()=>{};');
        if (name==='selector_tools.js') return send('text/javascript', 'export const SELECTOR_TOOLS=[],openPromptSelector=()=>{};');
        if (/^[\w.-]+\.(js|css)$/.test(name) && fs.existsSync(path.join(wb,'web',name))) return send(name.endsWith('.css')?'text/css':'text/javascript',fs.readFileSync(path.join(wb,'web',name)));
    }
    res.writeHead(404);res.end();
});
(async () => {
    let browser;
    try {
        await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
        const origin=`http://127.0.0.1:${server.address().port}`;
        browser=await chromium.launch({headless:true,channel:process.env.UAP_TEST_BROWSER_CHANNEL || 'chrome'});
        const page=await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
        page.on('pageerror',error=>errors.push(error.message));
        await page.goto(origin);await page.waitForSelector('html[data-ready=true]');
        for (const [url,file] of [['/extensions/fixture/uap_daily_controls.js',daily],[prefix+'studio.css',path.join(wb,'web/studio.css')]]) {
            const served=await (await page.request.get(origin+url)).body();
            assert.equal(crypto.createHash('sha256').update(served).digest('hex'),crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),'Served candidate bytes match disk');
        }
        const width=page.getByRole('spinbutton',{name:'宽度',exact:true}),height=page.getByRole('spinbutton',{name:'高度',exact:true}),swap=page.getByRole('button',{name:'互换宽度与高度',exact:true});
        assert.equal(await width.inputValue(),'1344');assert.equal(await height.inputValue(),'768');
        const unchanged=await page.evaluate(()=>fixture.state().slice(2));
        await swap.click();assert.equal(await width.inputValue(),'768');assert.equal(await height.inputValue(),'1344');
        assert.equal(await page.evaluate(()=>fixture.undo.length),1,'Swap uses one undo boundary');
        await page.evaluate(()=>fixture.undoOnce());await page.waitForFunction(()=>document.querySelector('[aria-label="宽度"]').value==='1344');
        assert.equal(await height.inputValue(),'768');
        await swap.click();await swap.click();assert.equal(await width.inputValue(),'1344');
        for (const control of [width,height]) {
            const label=await control.getAttribute('aria-label');
            const choices=page.getByRole('combobox',{name:label+'常用尺寸',exact:true});
            const options=await choices.evaluate(select=>Array.from(select.options,o=>Number(o.value)).slice(1));
            assert.deepEqual(options,[512,640,768,832,896,960,1024,1152,1216,1280,1344,1536,2048]);
            await choices.selectOption('1024');assert.equal(await control.inputValue(),'1024');
            assert.equal(await choices.inputValue(),'','Chooser resets without replacing manual input');
        }
        await width.fill('1408');await width.press('Tab');assert.equal(await page.evaluate(()=>fixture.size.widgets[0].value),1408,'Manual custom size works');
        await width.fill('1001');await width.press('Tab');assert.equal(await page.evaluate(()=>fixture.size.widgets[0].value),1408,'Step mismatch does not write');
        await width.fill('1408');await width.press('Tab');
        await width.focus();await page.keyboard.press('Tab');assert.equal(await swap.evaluate(button=>button===document.activeElement),true);
        await page.keyboard.press('Enter');assert.equal(await width.inputValue(),'1024');assert.equal(await height.inputValue(),'1408');
        await page.getByRole('button',{name:'竖图',exact:true}).click();assert.equal(await width.inputValue(),'832');assert.equal(await height.inputValue(),'1216');
        assert.deepEqual(await page.evaluate(()=>fixture.state().slice(2)),unchanged,'Batch/seed/sampling remain unchanged');
        const output=process.env.UAP_DIMENSIONS_EVIDENCE;
        if(output)fs.mkdirSync(output,{recursive:true});
        for (const theme of ['light','dark','color']) for (const viewport of [{width:1440,height:1000},{width:720,height:1000},{width:390,height:844}]) {
            await page.setViewportSize(viewport);await page.evaluate(theme=>document.documentElement.dataset.uwTheme=theme,theme);
            const bounds=await page.evaluate(()=>{const box=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}};return {w:box('[aria-label="宽度"]'),s:box('.desk-size-swap'),h:box('[aria-label="高度"]'),overflow:document.documentElement.scrollWidth>innerWidth}});
            assert.ok(bounds.w.right<=bounds.s.left&&bounds.s.right<=bounds.h.left,'Swap stays between dimensions');
            assert.equal(bounds.w.bottom,bounds.h.bottom);assert.equal(bounds.overflow,false);
            if(output)await page.locator('.desk-parameters').screenshot({path:path.join(output,`${theme}-${viewport.width}.png`)});
        }
        await page.evaluate(()=>fixture.size.widgets[0].options.max=1024);
        await page.waitForFunction(()=>!Array.from(document.querySelector('[aria-label="宽度常用尺寸"]').options,o=>o.value).includes('1344'));
        await page.evaluate(()=>fixture.graph.extra.uap_workbench.activeBranch='other');
        await swap.click({force:true});assert.equal(await page.evaluate(()=>fixture.size.widgets[0].value),832,'Inactive branch cannot write');
        assert.deepEqual(errors,[]);
        console.log('PASS: candidate byte hashes, initial values, swap/undo boundary, common choices, manual/invalid input, keyboard, 9 theme/viewport layouts, dynamic limits, branch guard; no generation.');
    } finally {await browser?.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1});
