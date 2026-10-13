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
    const listeners=new Map();
    const context = vm.createContext({document,URLSearchParams,FormData:class{append(){}},mountControlSwitches:()=>({sync(){},dispose(){}}),api:{addEventListener:(event,fn)=>listeners.set(event,fn),removeEventListener:event=>listeners.delete(event),apiURL:path=>path,fetchApi:()=>new Promise(resolve=>{fetchResolve=resolve;})},commitWidget:(_,node,widget,value)=>{widget.value=value;changes.push(widget.name);}});
    vm.runInContext(fs.readFileSync(path.join(web,'anima_control.js'),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,''),context);
    const panel = context.mountAnimaControl(host,app,branch,[owner],()=>true);
    return {host,app,graph,branch,owner,advanced,apply,reference,preprocessor,panel,context,changes,listeners,
        input:label=>all(host).find(e=>e.attributes['aria-label']===label),
        resolveUpload:()=>fetchResolve({ok:true,json:async()=>({name:'uploaded.png'})})};
}

async function main() {
    const taskContext=vm.createContext({});
    vm.runInContext(fs.readFileSync(path.join(web,'task_activity.js'),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,''),taskContext);
    const control={id:1,mode:0,properties:{uap_anima_control:1,anima_control_roles:{preview:7},uap_layout_group:'SW-05'},subgraph:{_nodes:[
        {id:7,type:'PreviewImage',mode:0},{id:8,type:'SaveImage',mode:0},{id:9,type:'PreviewImage',mode:0}]}};
    const delivery={id:10,type:'SaveImage',mode:0,properties:{uap_layout_group:'03 delivery'}};
    const taskApp={graph:{_nodes:[control,delivery],extra:{uap_workbench:{activeBranch:'a29',branches:[{id:'a29',nodeIds:[1,10]}]}}}};
    assert.deepEqual(Array.from(taskContext.taskPlan(taskApp,'generate').queueNodeIds),['10','1:7'],'Generation includes only the designated final control preview, not mask/export outputs');
    control.mode=2;
    assert.deepEqual(Array.from(taskContext.taskPlan(taskApp,'generate').queueNodeIds),['10'],'Disabled control cannot enqueue its preview');
    control.mode=0;control.subgraph._nodes[0].mode=2;
    assert.deepEqual(Array.from(taskContext.taskPlan(taskApp,'generate').queueNodeIds),['10'],'Muted preview remains muted');
    const h = harness();
    h.owner.subgraph.id='control-graph';
    h.app.nodeOutputs={'control-graph:7':{images:[{filename:'control preview.png',subfolder:'',type:'temp'}]}};
    h.listeners.get('execution_success')();
    const image=all(h.host).find(e=>e.tagName==='img');
    assert.equal(image.hidden,false,'Native subgraph cache displays the preview even before the canvas draws the child');
    assert.equal(image.src,'/view?filename=control+preview.png&subfolder=&type=temp');
    const choice=h.input('控制方式'); choice.value='HEDPreprocessor'; choice.onchange();
    assert.equal(h.preprocessor.widgets[0].value,'HEDPreprocessor');
    const strength=h.input('控制强度'); strength.value='0.8'; strength.onchange(); assert.equal(h.apply.widgets[0].value,0.8);
    strength.value=''; strength.onchange(); assert.equal(h.apply.widgets[0].value,0.8,'Empty input cannot overwrite a valid strength');
    h.apply.inputs.push({name:'strength',link:1}); strength.value='0.2'; strength.onchange(); assert.equal(h.apply.widgets[0].value,0.8,'Linked widget cannot be edited');
    const upload=all(h.host).find(e=>e.type==='file'); upload.files=[{name:'fixture.png'}];
    const pending=upload.onchange(); h.graph.extra.uap_workbench.activeBranch='a1'; h.resolveUpload(); await pending;
    assert.equal(h.reference.widgets[0].value,'reference.png','Delayed upload cannot change another branch');
    assert.match(all(h.host).find(e=>e.attributes.role==='status').textContent,/工作流已切换/);
    h.graph.extra.uap_workbench.activeBranch='a29';h.panel.dispose();strength.value='0.4';strength.onchange();assert.equal(h.apply.widgets[0].value,0.8);
    assert.equal(h.listeners.size,0,'Disposed panel removes its execution listener');
    console.log('PASS: control parameters, native preview, linked inputs, stale upload, branch switch and disposed handlers. Switch behavior is covered by test_control_switches.cjs.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
