const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.resolve(__dirname, '../ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web');
class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.style = {}; this.value = ''; }
    append(item) { this.children.push(item); }
    setAttribute(name, value) { this.attributes[name] = value; }
    get options() { return this.children; }
    checkValidity() { return this.type !== 'number' || (this.value !== '' && Number.isFinite(Number(this.value)) && Number(this.value) >= Number(this.min ?? -Infinity) && Number(this.value) <= Number(this.max ?? Infinity)); }
}
const all = root => [root, ...root.children.flatMap(all)];
function harness() {
    const host = new Element('div'), changes = [];
    const document = {createElement: tag => new Element(tag)};
    const make = (id, values) => ({id, mode: 0, properties: {}, inputs: [], widgets: Object.entries(values).map(([name,value]) => ({name,value,options: typeof value === 'string' ? {values:[value]} : {min:0,max:10,step:1}}))});
    const reference = make(2,{image:'reference.png'}), preprocessor = make(3,{preprocessor:'DepthAnythingV2Preprocessor',resolution:1024});
    const apply = make(4,{strength:1,start_percent:0,end_percent:1}), loader = make(5,{lllite_name:'anima.safetensors'});
    const advanced = make(6,{}); advanced.subgraph = {_nodes:[make(8,{}),make(9,{})]}; advanced.subgraph._nodes[1].mode=4;
    const preview = make(7,{});
    const owner = {id:1,mode:2,properties:{uap_anima_control:1,anima_control_roles:{reference:2,preprocessor:3,apply:4,loader:5,advanced:6,preview:7}},subgraph:{_nodes:[reference,preprocessor,apply,loader,advanced,preview]}};
    const graph = {extra:{uap_workbench:{activeBranch:'a29'}},getNodeById:id => id===1 ? owner : null,beforeChange(){changes.push('before');},afterChange(){changes.push('after');},setDirtyCanvas(){}};
    const app = {graph,canvas:{openSubgraph(value){app.opened=value;}}}, branch = {id:'a29',modes:{1:2}};
    let fetchResolve;
    const context = vm.createContext({document,FormData:class{append(){}},api:{fetchApi:()=>new Promise(resolve=>{fetchResolve=resolve;})},commitWidget:(_,node,widget,value)=>{widget.value=value;changes.push(widget.name);}});
    vm.runInContext(fs.readFileSync(path.join(web,'anima_control.js'),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,''),context);
    const panel = context.mountAnimaControl(host,app,branch,[owner],()=>true);
    return {host,app,graph,branch,owner,advanced,apply,reference,preprocessor,panel,context,changes,
        input:label=>all(host).find(e=>e.attributes['aria-label']===label),
        resolveUpload:()=>fetchResolve({ok:true,json:async()=>({name:'uploaded.png'})})};
}

async function main() {
    const h = harness();
    const enable = h.input('启用姿态与构图控制'); enable.checked=true; enable.onchange();
    assert.equal(h.owner.mode,0); assert.equal(h.branch.modes[1],0);
    const choice=h.input('控制方式'); choice.value='HEDPreprocessor'; choice.onchange();
    assert.equal(h.preprocessor.widgets[0].value,'HEDPreprocessor');
    const strength=h.input('控制强度'); strength.value='0.8'; strength.onchange(); assert.equal(h.apply.widgets[0].value,0.8);
    strength.value=''; strength.onchange(); assert.equal(h.apply.widgets[0].value,0.8,'Empty input cannot overwrite a valid strength');
    h.apply.inputs.push({name:'strength',link:1}); strength.value='0.2'; strength.onchange(); assert.equal(h.apply.widgets[0].value,0.8,'Linked widget cannot be edited');
    const erase=h.input('使用原擦线遮罩'); erase.checked=false; erase.onchange();
    assert.equal(h.advanced.mode,4); assert.deepEqual(h.advanced.subgraph._nodes.map(n=>n.mode),[2,2]);
    const saved=JSON.parse(JSON.stringify(h.advanced));
    h.context.setEraseMode(saved,false); h.context.setEraseMode(saved,true);
    assert.deepEqual(saved.subgraph._nodes.map(n=>n.mode),[0,4],'Save/reload preserves prior child modes across repeated bypass');
    erase.checked=true;erase.onchange();assert.deepEqual(h.advanced.subgraph._nodes.map(n=>n.mode),[0,4]);
    const upload=all(h.host).find(e=>e.type==='file'); upload.files=[{name:'fixture.png'}];
    const pending=upload.onchange(); h.graph.extra.uap_workbench.activeBranch='a1'; h.resolveUpload(); await pending;
    assert.equal(h.reference.widgets[0].value,'reference.png','Delayed upload cannot change another branch');
    assert.match(all(h.host).find(e=>e.attributes.role==='status').textContent,/工作流已切换/);
    const snapshot=JSON.stringify(h.owner); enable.checked=false;enable.onchange();assert.equal(JSON.stringify(h.owner),snapshot);
    h.graph.extra.uap_workbench.activeBranch='a29';h.panel.dispose();strength.value='0.4';strength.onchange();assert.equal(h.apply.widgets[0].value,0.8);
    console.log('PASS: panel bindings, mode persistence, linked inputs, stale upload, branch switch and disposed handlers.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
