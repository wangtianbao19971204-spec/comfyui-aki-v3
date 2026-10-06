const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
(async () => {
const root = path.resolve(__dirname, '..');
const modules = 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/';
const lm = modules + 'comfyui-lora-manager/';
const daily = modules + 'ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js';
const source = file => fs.readFileSync(path.join(root, file), 'utf8');
const strip = text => text.replace(/^import\s[\s\S]*?;\s*$/gm, '').replaceAll('export ', '');
let extension;
const events = [];
const first = {id: 1, mode: 0, comfyClass: 'Lora Loader (LoraManager)'};
const second = {id: 2, mode: 0, comfyClass: 'Lora Loader (LoraManager)'};
const graph = {extra:{uap_workbench:{activeBranch:'a1',branches:[{id:'a1',nodeIds:[1]},{id:'a29',nodeIds:[2]}]}},
  getNodeById: id => id === 1 ? first : second,
  beforeChange: () => events.push('before'), afterChange: () => events.push('after'), setDirtyCanvas: () => events.push('dirty')};
const app = {graph, registerExtension: ext => extension = ext};
const context = vm.createContext({app, console, URL, URLSearchParams, crypto:require('node:crypto').webcrypto,
  getNodeReference:node=>({node_id:node.id,graph_id:'root'}), getNodeFromGraph:(_,id)=>graph.getNodeById(id),
  getAllGraphNodes:()=>[first,second].map(node=>({node})),
  window:{location:{origin:'http://localhost:8188',search:''},open:()=>{},dispatchEvent:()=>{}}, CustomEvent:class {},
  document:{readyState:'loading',addEventListener:()=>{}}});
vm.runInContext(strip(source(lm+'web/comfyui/workflow_targets.js')), context);
assert.equal(context.isWorkflowTargetEnabled(first), true);
assert.equal(context.isWorkflowTargetEnabled(second), false, 'Inactive branch rejected even if node mode is 0');
first.mode = 2;
assert.equal(context.isWorkflowTargetEnabled(first), false);
first.mode = 0;
assert.equal(context.getTargetToken(first), context.getTargetToken(first));
assert.notEqual(context.getTargetToken(first), context.getTargetToken({id:1}));
assert.equal(context.getTargetToken(new Proxy(first, {})), context.getTargetToken(first), 'Reactive proxies share one runtime token');
const utils = source(lm+'web/comfyui/utils.js');
const merge = utils.slice(utils.indexOf('export function mergeLoras('), utils.indexOf('/**',utils.indexOf('export function mergeLoras(')));
vm.runInContext('const LORA_PATTERN=/<lora:([^:]+):([-\\d\\.]+)(?::([-\\d\\.]+))?>/g;\n'+strip(merge), context);
vm.runInContext(strip(source(lm+'web/comfyui/lora_loader.js')), context);
first.lorasWidget={value:[{name:'old',strength:0.5,clipStrength:0.5,active:false,locked:true}]};
first.inputWidget={value:'<lora:old:0.5>',callback(value){first.lorasWidget.value=context.mergeLoras(value,first.lorasWidget.value)}};
extension.updateNodeLoraCode(first,'<lora:old:0.9:0> <lora:new:1>','replace');
assert.equal(first.lorasWidget.value.length,2);
assert.equal(first.lorasWidget.value[0].strength,0.9,'Replace updates same-name strength');
assert.equal(first.lorasWidget.value[0].clipStrength,0,'Zero CLIP strength survives parsing');
assert.equal(first.lorasWidget.value[0].active,true);
first.lorasWidget.value[0].locked=true;
extension.updateNodeLoraCode(first,'<lora:third:0.8>','append');
assert.equal(first.lorasWidget.value.length,3);
assert.equal(first.lorasWidget.value[0].locked,true,'Append preserves locks and existing state');
extension.updateNodeLoraCode(first,'<lora:new:0.7>','replace');
assert.equal(first.lorasWidget.value.length,1,'Replace removes old entries');
extension.updateNodeLoraCode(first,'','replace');
assert.equal(first.lorasWidget.value.length,0);
extension.handleLoraCodeUpdate({id:-1,lora_code:'<lora:broadcast:1>'});
assert.equal(first.lorasWidget.value[0].name,'broadcast');
assert.equal(second.inputWidget,undefined,'Broadcast does not touch inactive branches');
assert.deepEqual(events.slice(-3),['before','after','dirty']);
const broadcastSnapshot=JSON.stringify(first.lorasWidget.value);
const broadcastEventCount=events.length;
first.mode=2;
extension.handleLoraCodeUpdate({id:-1,lora_code:'<lora:zero-candidate:1>'});
assert.equal(JSON.stringify(first.lorasWidget.value),broadcastSnapshot,'UAP zero enabled targets must reject broadcast');
assert.equal(events.length,broadcastEventCount);
first.mode=0;
graph.extra.uap_workbench.branches[0].nodeIds.push(2);
extension.handleLoraCodeUpdate({id:-1,lora_code:'<lora:ambiguous:1>'});
assert.equal(JSON.stringify(first.lorasWidget.value),broadcastSnapshot,'UAP multiple enabled targets must reject broadcast');
assert.equal(second.inputWidget,undefined);
assert.equal(events.length,broadcastEventCount);
graph.extra.uap_workbench.branches[0].nodeIds.pop();
const uapConfig=graph.extra.uap_workbench;
delete graph.extra.uap_workbench;
second.lorasWidget={value:[]};
second.inputWidget={value:'',callback(value){second.lorasWidget.value=context.mergeLoras(value,second.lorasWidget.value)}};
extension.handleLoraCodeUpdate({id:-1,lora_code:'<lora:ordinary-broadcast:1>'});
assert(first.lorasWidget.value.some(item=>item.name==='ordinary-broadcast'));
assert(second.lorasWidget.value.some(item=>item.name==='ordinary-broadcast'),'Ordinary non-UAP broadcast remains compatible');
const secondSnapshot=JSON.stringify(second.lorasWidget.value);
second.mode=2;
extension.handleLoraCodeUpdate({id:-1,lora_code:'<lora:disabled-preserved:1>'});
assert.equal(JSON.stringify(second.lorasWidget.value),secondSnapshot,'Disabled ordinary target must be preserved');
second.mode=0;
graph.extra.uap_workbench=uapConfig;
vm.runInContext(strip(source(lm+'static/js/utils/workflowTarget.js')), context);
const nodes={'root:1':{unique_id:'root:1',capabilities:{target_token:'one'}},'root:2':{capabilities:{target_token:'two'}}};
assert.equal(Object.keys(context.filterBrowserTargets(nodes,{key:'root:1',token:'one'})).length,1);
assert.equal(Object.keys(context.filterBrowserTargets(nodes,{key:'root:1',token:'stale'})).length,0);
assert.equal(Object.keys(context.filterBrowserTargets(nodes,{key:'root:1'})).length,0);
assert.equal(Object.keys(context.filterBrowserTargets(nodes,{key:null})).length,2,'Ordinary browser remains compatible');
vm.runInContext(strip(source(daily)),context);
assert.equal(context.resolveLocalLoraName('style/a.safetensors',['style/a.safetensors'],'full'),'style/a');
assert.equal(context.resolveLocalLoraName('style/a.safetensors',['style/a.safetensors'],'legacy'),'a');
assert.throws(()=>context.resolveLocalLoraName('a',['one/a.safetensors','two/a.safetensors'],'full'),/同名/);
assert.throws(()=>context.resolveLocalLoraName('one/a.safetensors',['one/a.safetensors','two/a.safetensors'],'legacy'),/完整路径/);
assert.equal(context.resolveLocalLoraName('one/a.safetensors',['one/a.safetensors','two/a.safetensors'],'full'),'one/a');
const promptWidget={value:'blue sky'};
first.widgets=[promptWidget];first.graph=graph;
vm.runInContext(strip(source('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/prompt_target.js')),context);
const insert=context.createPromptInserter({node:first,widget:promptWidget},'a1');
await insert('soft light');
assert.equal(promptWidget.value,'blue sky, soft light');
graph.extra.uap_workbench.activeBranch='a29';
await assert.rejects(()=>insert('must not write'),/分支.*变化/);
assert.equal(promptWidget.value,'blue sky, soft light');
graph.extra.uap_workbench.activeBranch='a1';
app.graph={...graph,getNodeById:()=>({id:1})};
await assert.rejects(()=>insert('must not write'),/工作流/);
const widgetSource = source(lm+'web/comfyui/loras_widget.js');
const setter = widgetSource.slice(widgetSource.indexOf('setValue: function(v) {') + 'setValue: '.length, widgetSource.indexOf('    hideOnZoom: true', widgetSource.indexOf('setValue: function(v) {'))).trim().replace(/,$/, '');
vm.runInContext(`let widgetValue, widget = {}, selectedLora; function renderLoras() {} const setLoraValue = ${setter}; globalThis.checkZeroClip = () => { setLoraValue([{name:'zero', strength:0.7, clipStrength:0}]); return widgetValue[0]; };`, context);
assert.equal(context.checkZeroClip().clipStrength,0,'Native widget setter must preserve zero CLIP strength');
console.log('PASS: target scopes/tokens, replacement/append/zero/locks, UAP zero/multiple/unique broadcast targets, ordinary broadcasts, disabled preservation, path ambiguity, async prompt writes and stale-target guards.');

// Exercise the actual lazy-loader function with completed local script events.
const weilin = source(modules + 'WeiLin-Comfyui-Tools-V52-FullPromptSelector/js_node/weilin_prompt_ui_node.js');
const assets = [];
const lazy = vm.createContext({console, WEILIN_VERSION:'test', document:{
  createElement:()=>({}), head:{appendChild:node=>assets.push(node)},
  getElementById:()=>({children:[{}]})}});
vm.runInContext(weilin.slice(weilin.indexOf('let resourcesLoaded ='), weilin.indexOf('// 不再自动加载资源')), lazy);
const firstLoad = lazy.loadResourcesOnDemand();
assert.equal(lazy.loadResourcesOnDemand(), firstLoad, 'Concurrent opens must wait on the same promise');
assert.equal(assets.length,4);
assets.forEach(asset=>asset.onload());
firstLoad.then(async()=>{
  await lazy.loadResourcesOnDemand();
  assert.equal(assets.length,4,'Reopening must not load a second editor bundle');
  console.log('PASS: WeiLin concurrent/repeated lazy loading uses one resource set.');
}).catch(error=>{console.error(error);process.exitCode=1;});
})().catch(error=>{console.error(error);process.exitCode=1;});
