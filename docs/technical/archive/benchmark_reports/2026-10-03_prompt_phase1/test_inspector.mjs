import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('./staged/prompt_inspector.js', import.meta.url), 'utf8').replace(/^import .*\r?\n/, '');
const {inspectPrompt, containsTrigger, modelNote} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
let passed = 0;
function test(name, fn) { fn(); ++passed; console.log('PASS', name); }
const base = () => ({
    '1': {class_type: 'WeiLinPromptUI', inputs: {positive: 'adult traveler, blue coat', auto_random: false, lora_str: ''}},
    '2': {class_type: 'CLIPTextEncode', inputs: {text: ['1', 0], clip: ['6', 1]}},
    '3': {class_type: 'CLIPTextEncode', inputs: {text: 'blurry', clip: ['5', 0]}},
    '4': {class_type: 'UNETLoader', inputs: {unet_name: 'krea2/travel.safetensors'}},
    '5': {class_type: 'CLIPLoader', inputs: {clip_name: 'clip.safetensors'}},
    '6': {class_type: 'Lora Loader (LoraManager)', inputs: {model: ['4', 0], clip: ['5', 0], lora_stack: ['7', 0], loras: {__value__: []}}},
    '7': {class_type: 'Lora Stacker (LoraManager)', inputs: {loras: [{name: 'coat_v2', strength: 0.8, active: true}, {name: 'disabled', strength: 1, active: false}, {name: 'zero', strength: 0, clipStrength: 0, active: true}]}},
    '8': {class_type: 'KSampler', inputs: {positive: ['2', 0], negative: ['3', 0], model: ['6', 0], cfg: 1, sampler_name: 'euler'}},
    '9': {class_type: 'Lora Stacker (LoraManager)', inputs: {loras: [{name: 'unconnected', strength: 1, active: true}]}},
});
test('traces actual encoder text and model, ignores disconnected and disabled LoRAs', () => {
    const result = inspectPrompt(base(), '8');
    assert.equal(result.positive.text, 'adult traveler, blue coat');
    assert.deepEqual(result.positive.source, {id: '1', widget: 'positive'});
    assert.deepEqual(result.loras.map(r => r.name), ['coat_v2']);
    assert.equal(result.models[0].file, 'krea2/travel.safetensors');
    assert.match(result.cfgNote, /负向不参与/);
});
test('random WeiLin is unresolved', () => { const api = base(); api[1].inputs.auto_random = true; assert.equal(inspectPrompt(api, '8').positive.text, undefined); });
test('opt_text remains runtime', () => { const api = base(); api[1].inputs.opt_text = ['99', 0]; assert.equal(inspectPrompt(api, '8').positive.text, undefined); });
test('embedded wlr stays runtime', () => { const api = base(); api[1].inputs.positive = '<wlr:coat:1:1>'; assert.equal(inspectPrompt(api, '8').positive.text, undefined); });
test('JSON prompt stays runtime', () => { const api = base(); api[1].inputs.positive = '{"prompt":"hiker"}'; assert.equal(inspectPrompt(api, '8').positive.text, undefined); });
test('cleaner output is not fabricated', () => { const api = base(); api[1].class_type = 'PromptCleaningMaid'; assert.match(inspectPrompt(api, '8').positive.reason, /运行时/); });
test('conditioning transforms stay unresolved', () => { const api = base(); api[2].class_type = 'ConditioningCombine'; assert.equal(inspectPrompt(api, '8').positive.text, undefined); });
test('cycles cannot recurse indefinitely', () => { const api = base(); api[2].inputs.text = ['2', 0]; assert.match(inspectPrompt(api, '8').positive.reason, /循环/); });
test('CFG > 1 reports negative path', () => { const api = base(); api[8].inputs.cfg = 3.5; assert.match(inspectPrompt(api, '8').cfgNote, /会使用负向/); });
test('linked CFG is unknown', () => { const api = base(); api[8].inputs.cfg = ['99', 0]; assert.match(inspectPrompt(api, '8').cfgNote, /运行时/); });
test('custom patch qualifies CFG conclusion', () => { const api = base(); api[6].class_type = 'CustomGuidance'; assert.match(inspectPrompt(api, '8').cfgNote, /最终作用需/); });
test('CFG++ sampler qualifies CFG conclusion', () => { const api = base(); api[8].inputs.sampler_name = 'euler_cfg_pp'; assert.match(inspectPrompt(api, '8').cfgNote, /最终作用需/); });
test('trigger boundaries preserve identifiers', () => {
    assert(containsTrigger('(coat_v2:1.2), travel', 'coat_v2'));
    assert(!containsTrigger('coat_v20', 'coat_v2'));
    assert(!containsTrigger('rainbow', 'bow'));
    assert(containsTrigger('A+B, traveler', 'A+B'));
    assert(!containsTrigger('coat v2', 'coat_v2'));
});
test('model identity hints use file name', () => {
    assert.match(modelNote('Anima/animayume_v15Base.safetensors'), /AnimaYume v1.5/);
    assert.match(modelNote('Anima-2.9B/anima29B_v10_bf16.safetensors'), /40 层/);
});
test('linked LoRA strength stays unresolved', () => {
    const api = base(); api[6] = {class_type: 'LoraLoader', inputs: {model: ['4', 0], clip: ['5', 0], lora_name: 'coat', strength_model: ['99', 0], strength_clip: 0}};
    const report = inspectPrompt(api, '8'); assert.equal(report.loras.length, 0); assert.match(report.unknown.join(''), /强度需运行时/);
});
test('invalid manager strength does not become an enabled LoRA', () => {
    const api = base(); api[7].inputs.loras[0].strength = 'unknown';
    const report = inspectPrompt(api, '8'); assert.equal(report.loras.length, 0); assert.match(report.unknown.join(''), /配置需运行时/);
});
fs.writeFileSync(new URL('./inspector_tests.json', import.meta.url), JSON.stringify({passed, method: 'staged production source, neutral API graph fixtures'}));
