const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {JSDOM} = require('G:/ComfyUI-aki-v3/benchmark_reports/2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js');
const root = 'G:/ComfyUI-aki-v3';
const plugin = path.join(root, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench');
const sourcePaths = {
    selector: path.join(plugin, 'web/selector_tools.js'),
    daily: path.join(plugin, 'modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js'),
    workbenchCSS: path.join(plugin, 'web/workbench.css'),
    studioCSS: path.join(plugin, 'web/studio.css'),
    shell: path.join(plugin, 'web/workbench_shell.js'),
};
const sources = Object.fromEntries(Object.entries(sourcePaths).map(([key,file]) => [key,fs.readFileSync(file,'utf8')]));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const hashes = Object.fromEntries(Object.entries(sourcePaths).map(([key,file]) => [key,hash(file)]));
const tests = [];
const pass = name => tests.push({name,status:'pass'});
const target = (id,direction) => ({node:{id},widget:{name:'text',value:'neutral prompt'},direction,label:`target ${id} ${direction}`});

(async () => {
    const moduleSource = sources.selector.replace(/^import[^\n]+\n/, '');
    const {mountSelectorTools,SELECTOR_TOOLS} = await import('data:text/javascript;base64,' + Buffer.from(moduleSource).toString('base64'));
    const dom = new JSDOM('<!doctype html><body><main id="unified-workbench"><div id="tools"></div></main><aside id="uap-daily-desk"><div class="plugin-tools" hidden></div></aside></body>');
    const {document} = dom.window;
    const helperContext = vm.createContext({document});
    const elementSource = sources.shell.match(/^function element\([^\n]+/m)?.[0];
    assert.ok(elementSource);
    vm.runInContext(elementSource + '\nthis.element=element;',helperContext);
    const element = helperContext.element;
    const button = (label,key,callback,parent) => {
        const control=element('button',label,parent,{type:'button'});
        control.dataset.uw=key;
        control.onclick=async(...args)=>{try{return await callback(...args);}catch(error){reports.push(String(error.message||error));}};
        return control;
    };
    const positive = target(1,'positive'), negative = target(2,'negative');
    let targets=[],selected=null,openCalls=0,resolveOpen,selectCalls=0;
    const reports=[];
    const tools=mountSelectorTools(document.querySelector('#tools'),{
        element,button,getTargets:()=>targets,getTarget:()=>selected,
        selectTarget:value=>{selected=value;selectCalls++;tools.refresh();},
        open:async(tool,value)=>{assert.equal(value,positive);openCalls++;await new Promise(resolve=>{resolveOpen=resolve;});},
        report:message=>reports.push(message),
    });
    const row=document.querySelector('#tools .uw-toolbar');
    const picker=row.querySelector('select');
    const buttons=[...row.querySelectorAll('button')];
    assert.equal(buttons.length,6);
    tools.refresh();
    assert.equal(row.hidden,true);
    assert.equal(picker.disabled,true);
    assert.ok(buttons.every(item=>item.disabled));
    assert.match(document.querySelector('#tools small').textContent,/当前没有可编辑的正向提示词目标/);
    pass('no-target hides row and disables picker and six native entries');

    targets=[positive,negative];selected=positive;tools.refresh();
    assert.equal(row.hidden,false);assert.equal(picker.value,'0');assert.equal(picker.disabled,false);
    assert.ok(buttons.every(item=>!item.disabled));assert.equal(picker.options.length,2);
    pass('positive target restores row with only positive option and six enabled entries');

    selected=negative;tools.refresh();
    assert.equal(row.hidden,false);assert.equal(picker.value,'');assert.ok(buttons.every(item=>item.disabled));
    await buttons[0].onclick();assert.equal(openCalls,0);assert.equal(document.activeElement,picker);
    assert.match(reports.at(-1),/请先选择正向/);
    pass('negative selection disables all six entries and direct callback refuses open');

    picker.value='0';picker.onchange();
    assert.equal(selected,positive);assert.equal(selectCalls,1);assert.equal(picker.value,'0');
    pass('target picker synchronizes positive selection once without recursion');

    const pending=buttons[0].onclick();
    assert.equal(openCalls,1);assert.equal(picker.disabled,true);assert.ok(buttons.every(item=>item.disabled));
    await buttons[1].onclick();assert.equal(openCalls,1);
    pass('pending native opening locks controls and rejects duplicate callback');

    targets=[];selected=null;tools.refresh();
    assert.equal(row.hidden,true);assert.equal(picker.disabled,true);assert.ok(buttons.every(item=>item.disabled));
    resolveOpen();await pending;
    assert.equal(row.hidden,true);assert.equal(picker.disabled,true);assert.ok(buttons.every(item=>item.disabled));
    pass('targets removed during open remain hidden and disabled after completion');

    targets=[positive,negative];selected=positive;tools.refresh();
    assert.equal(row.hidden,false);assert.equal(picker.disabled,false);assert.ok(buttons.every(item=>!item.disabled));
    targets=[negative];selected=negative;tools.refresh();
    assert.equal(row.hidden,true);assert.equal(picker.disabled,true);assert.ok(buttons.every(item=>item.disabled));
    targets=[positive];selected=positive;tools.refresh();
    assert.equal(row.hidden,false);assert.equal(picker.value,'0');assert.ok(buttons.every(item=>!item.disabled));
    assert.equal(positive.widget.value,'neutral prompt');assert.equal(negative.widget.value,'neutral prompt');
    pass('negative-only hides row; restored positive target re-enables entries without widget writes');

    const hint=document.querySelector('#tools small');
    const rowObserver=new dom.window.MutationObserver(()=>{});
    const hintObserver=new dom.window.MutationObserver(()=>{});
    rowObserver.observe(row,{attributes:true,attributeFilter:['hidden']});
    hintObserver.observe(hint,{subtree:true,childList:true,characterData:true});
    const stableRefreshMutations=[];
    const observeStable=state=>{
        for(let index=0;index<100;index++)tools.refresh();
        const hiddenRecords=rowObserver.takeRecords(),hintRecords=hintObserver.takeRecords();
        assert.equal(hiddenRecords.length,0,`${state}: repeated hidden assignment`);
        assert.equal(hintRecords.length,0,`${state}: repeated hint text assignment`);
        stableRefreshMutations.push({state,refreshCalls:100,hiddenMutations:0,hintMutations:0});
    };
    observeStable('positive target unchanged');
    targets=[];selected=null;tools.refresh();
    assert.equal(rowObserver.takeRecords().length,1);
    assert.equal(hintObserver.takeRecords().length,1);
    observeStable('no target unchanged');
    targets=[positive];selected=positive;tools.refresh();
    assert.equal(rowObserver.takeRecords().length,1);
    assert.equal(hintObserver.takeRecords().length,1);
    observeStable('restored positive target unchanged');
    rowObserver.disconnect();hintObserver.disconnect();
    pass('300 stable refresh calls cause zero hidden or hint mutations; each real transition updates once');

    const cssLines=[
        sources.workbenchCSS.split(/\r?\n/).find(line=>line.includes('#unified-workbench [hidden],')),
        sources.workbenchCSS.split(/\r?\n/).find(line=>line.includes('#unified-workbench .uw-header,#unified-workbench .uw-nav,#unified-workbench .uw-toolbar,')),
        sources.studioCSS.split(/\r?\n/).find(line=>line.includes('[hidden] { display: none !important; }')),
        sources.daily.split(/\r?\n/).find(line=>line.includes('#uap-daily-desk .plugin-tools{')),
    ];
    assert.ok(cssLines.every(Boolean));
    const style=document.createElement('style');style.textContent=cssLines.join('\n');document.head.append(style);
    const rules=[...style.sheet.cssRules];
    row.hidden=true;
    const dailyTools=document.querySelector('#uap-daily-desk .plugin-tools');
    const hiddenContracts=[row,dailyTools].map(node=>{
        const matches=rules.filter(rule=>rule.selectorText&&node.matches(rule.selectorText));
        const guards=matches.filter(rule=>rule.style.getPropertyValue('display')==='none'&&rule.style.getPropertyPriority('display')==='important');
        assert.ok(guards.length>0);
        assert.equal(matches.some(rule=>rule.style.getPropertyValue('display')==='flex'&&rule.style.getPropertyPriority('display')==='important'),false);
        return {node:node===row?'selector toolbar':'daily prompt actions',matchingImportantHideSelectors:guards.map(rule=>rule.selectorText)};
    });
    pass('actual CSSOM has matching important hidden guards and no competing important flex declarations');

    const controlDom=new JSDOM('<div id="x"><div class="row" hidden></div></div>');
    const controlStyle=controlDom.window.document.createElement('style');
    controlStyle.textContent='#x [hidden]{display:none!important} #x .row{display:flex}';
    controlDom.window.document.head.append(controlStyle);
    const jsdomControl={
        css:'#x [hidden]{display:none!important} #x .row{display:flex}',
        computedDisplay:controlDom.window.getComputedStyle(controlDom.window.document.querySelector('.row')).display,
        cssomHiddenPriority:controlStyle.sheet.cssRules[0].style.getPropertyPriority('display'),
        expectedBrowserDisplay:'none',
    };

    const dailyStart=sources.daily.indexOf('        const bindInsertionTarget =');
    const dailyEnd=sources.daily.indexOf('        const selectorNode =',dailyStart);
    assert.ok(dailyStart>=0&&dailyEnd>dailyStart);
    const dailySnippet=sources.daily.slice(dailyStart,dailyEnd);
    const elSource=sources.daily.slice(sources.daily.indexOf('const el ='),sources.daily.indexOf('export function widgetSource'));
    const actionSource=sources.daily.slice(sources.daily.indexOf('        const action ='),sources.daily.indexOf('        action("编辑提示词"'));
    async function runDaily(name,hasPositive,hasNegative,hasTextarea=true){
        const d=new JSDOM('<body><div id="box"></div></body>');
        const doc=d.window.document;
        const textBox=doc.querySelector('#box'),pluginTools=doc.createElement('div'),pluginStatus=doc.createElement('div'),promptTarget=doc.createElement('select'),libraryShortcut=doc.createElement('button');
        textBox.append(pluginTools,pluginStatus,promptTarget,libraryShortcut);
        const positiveSource=hasPositive?target(11,'positive'):null,negativeSource=hasNegative?target(12,'negative'):null;
        const positiveTextArea=hasPositive&&hasTextarea?doc.createElement('textarea'):null,negativeTextArea=hasNegative?doc.createElement('textarea'):null;
        if(positiveTextArea)textBox.append(positiveTextArea);if(negativeTextArea)textBox.append(negativeTextArea);
        const opens=[];
        const context=vm.createContext({document:doc,window:{weilinOpenSharedPresets:()=>{}},textBox,pluginTools,pluginStatus,promptTarget,libraryShortcut,positiveSource,negativeSource,positiveTextArea,negativeTextArea,SELECTOR_TOOLS,app:{graph:{extra:{uap_workbench:{activeBranch:'test'}}}},branch:{id:'test',label:'neutral'},isCurrent:()=>true,openWorkbench:async options=>opens.push(options),openPromptSelector:()=>{throw new Error('native module must not run in a state-only test');}});
        vm.runInContext(elSource+'\n'+actionSource+'\n'+dailySnippet,context);
        const entries=[...textBox.querySelectorAll('.desk-selector-action')];
        assert.equal(pluginTools.hidden,!hasPositive&&!hasNegative);
        assert.equal(entries.length,hasPositive&&hasTextarea?6:0);
        await libraryShortcut.onclick();assert.equal(opens.length,1);assert.equal(opens[0].page,'library');
        if(!hasPositive&&!hasNegative){assert.equal('target' in opens[0],false);assert.equal(libraryShortcut.title,'浏览资料库');}
        else{assert.equal(opens[0].target.direction,hasPositive?'positive':'negative');assert.equal(opens[0].target.node.id,hasPositive?11:12);}
        if(hasPositive&&hasTextarea){
            for(let index=0;index<entries.length;index++){
                await entries[index].onclick();
                const opened=opens.at(-1);
                assert.equal(opened.target.node,positiveSource.node);assert.equal(opened.target.widget,positiveSource.widget);
                assert.equal(opened.target.direction,'positive');assert.equal(opened.selector.section,SELECTOR_TOOLS[index].kind);assert.equal(opened.openSelector,true);
            }
        }
        assert.equal(pluginStatus.textContent,'');
        if(positiveSource)assert.equal(positiveSource.widget.value,'neutral prompt');if(negativeSource)assert.equal(negativeSource.widget.value,'neutral prompt');
        pass(name);
        return {name,positive:hasPositive,negative:hasNegative,textarea:hasTextarea,entries:entries.length,promptActionsHidden:pluginTools.hidden,libraryDirection:opens[0].target?.direction||null};
    }
    const dailyCases=[];
    dailyCases.push(await runDaily('daily no-source hides prompt actions, builds no selectors, and browses library',false,false));
    dailyCases.push(await runDaily('daily negative-only retains negative library target and builds no positive selectors',false,true));
    dailyCases.push(await runDaily('daily positive-and-negative creates six entries all routed to positive source',true,true));
    dailyCases.push(await runDaily('daily positive source without textarea creates no selector entries',true,false,false));
    Object.entries(sourcePaths).forEach(([key,file])=>assert.equal(hash(file),hashes[key],`source changed while testing: ${key}`));
    const receipt={
        at:new Date().toISOString(),status:'PASS',testCount:tests.length,
        scope:'Actual mountSelectorTools module and extracted actual daily insertion/selector construction source run over neutral in-memory DOM objects. No browser, API, widget, workflow, source or data writes. Only this test and receipt are evidence files.',
        source_sha256:Object.fromEntries(Object.entries(sourcePaths).map(([key,file])=>[path.relative(root,file).replaceAll('\\','/'),hashes[key]])),
        tests,dailyCases,stableRefreshMutations,hiddenCSSContracts:hiddenContracts,jsdomCascadeControl:jsdomControl,
        limits:['jsdom computed style ignores earlier !important display in the control case; hidden verification here checks actual matching CSSOM declarations and DOM hidden state only. Real-browser rendered hiding belongs to root browser acceptance.','Native dynamic imports and model generation were not executed. Opening callbacks are controlled promises.','Daily test uses the actual extracted changed block with neutral host objects; it does not certify the entire createDailyControls lifecycle.'],
    };
    const receiptPath=path.join(root,'benchmark_reports/2026-10-01_workflow_matrix/selector_tools_visibility_vm_final.json');
    fs.writeFileSync(receiptPath,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
    console.log(JSON.stringify({status:receipt.status,testCount:receipt.testCount,receipt:receiptPath,source_sha256:receipt.source_sha256,jsdomCascadeControl:jsdomControl}));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
