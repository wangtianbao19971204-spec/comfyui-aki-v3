import fs from 'node:fs';
import assert from 'node:assert/strict';

const folder = process.argv[2] || 'candidate';
const source = fs.readFileSync(new URL(`./${folder}/prompt_inspector.js`, import.meta.url), 'utf8').replace(/^import .*\r?\n/, '');
const {inspectPrompt} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const checks = [];
function test(name, fn) { try { fn(); checks.push({name, passed:true}); } catch(e) { checks.push({name, passed:false, error:e.message}); } }
const fixture = () => ({
    1:{class_type:'UNETLoader',inputs:{unet_name:'sampler-model.safetensors'}},
    2:{class_type:'CheckpointLoaderSimple',inputs:{ckpt_name:'encoder-associated.safetensors'}},
    3:{class_type:'CLIPTextEncode',inputs:{clip:['2',1],text:'neutral landscape'}},
    4:{class_type:'KSampler',inputs:{model:['1',0],positive:['3',0],negative:['3',0],cfg:7}}
});
test('different CLIP checkpoint is not claimed as sampler model',()=>{
    const r=inspectPrompt(fixture(),'4');
    assert.deepEqual(r.models.map(m=>[m.id,m.via]),[['1',['model']],['2',['clip']]]);
});
test('unresolved switch does not promote CLIP checkpoint to confirmed model',()=>{
    const api=fixture(); api[4].inputs.model=['5',0];api[5]={class_type:'DazzleSwitch',inputs:{mode:'priority',input_01:['1',0]}};
    const r=inspectPrompt(api,'4');assert.equal(r.models.length,1);assert.deepEqual(r.models[0].via,['clip']);assert.match(r.unknown.join(''),/DazzleSwitch/);
});
test('shared checkpoint keeps both origins without duplicate rows',()=>{
    const api=fixture();api[4].inputs.model=['2',0]; const r=inspectPrompt(api,'4');
    assert.equal(r.models.length,1);assert.deepEqual(r.models[0].via,['model','clip']);
});
test('model loader reachable through a LoRA CLIP port stays CLIP associated',()=>{
    const api=fixture();api[5]={class_type:'LoraLoader',inputs:{model:['1',0],clip:['2',1],lora_name:'neutral',strength_model:1,strength_clip:1}};api[4].inputs.model=['5',0];api[3].inputs.clip=['5',1];
    const r=inspectPrompt(api,'4');assert.deepEqual(r.models.find(m=>m.id==='1').via,['model','clip']);assert.deepEqual(r.models.find(m=>m.id==='2').via,['clip']);assert.equal(r.loras.length,1);
});
test('cycles terminate per origin and unknown rows stay unique',()=>{
    const api=fixture();api[5]={class_type:'CustomPatch',inputs:{model:['5',0],clip:['2',1]}};api[4].inputs.model=['5',0];api[3].inputs.clip=['5',1];
    const r=inspectPrompt(api,'4');assert.equal(r.unknown.filter(x=>x.includes('#5')).length,1);assert.deepEqual(r.models[0].via,['clip']);
});
const audit=JSON.parse(fs.readFileSync(new URL('./browser_graph_audit.json',import.meta.url),'utf8'));
const replay=[];
for(const row of audit.reports) {
    test(`${row.branch}: graphToPrompt left graph unchanged`,()=>assert.equal(row.graphUnchanged,true));
    for(const s of row.samplers) {
        const r=inspectPrompt(row.api,s.id);replay.push({branch:row.branch,sampler:s.id,models:r.models,unknown:r.unknown,positive:r.positive.path,negative:r.negative.path});
        test(`${row.branch}: prompt, LoRA and model filenames unchanged`,()=>{
            assert.deepEqual(r.positive,s.report.positive);assert.deepEqual(r.negative,s.report.negative);assert.deepEqual(r.loras,s.report.loras);
            assert.deepEqual(r.models.map(({via,...m})=>m),s.report.models);
        });
        test(`${row.branch}: truthful model origin`,()=>{
            const primary=['a1','a29','k2'].includes(row.branch)||row.branch.startsWith('生产套件_');
            assert.equal(r.models.some(m=>m.via.includes('model')),!primary);
        });
    }
}
const result={passed:checks.every(c=>c.passed),folder,checks,replay};
fs.writeFileSync(new URL(folder==='before'?'./reproduction.json':'./tests.json',import.meta.url),JSON.stringify(result,null,2));
console.log(JSON.stringify({passed:result.passed,total:checks.length,failed:checks.filter(c=>!c.passed).map(c=>c.name)}));
if(folder!=='before'&&!result.passed)process.exitCode=1;
