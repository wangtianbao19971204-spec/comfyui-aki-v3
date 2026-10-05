import assert from 'node:assert/strict';
import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const run = path.dirname(fileURLToPath(import.meta.url));
const project = path.resolve(run, '../../../..');
const modules = path.join(project, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-anima-tools/js');
const sourcePath = process.argv.find(arg => arg.startsWith('--source='))?.slice('--source='.length)
    || path.join(modules, 'anima_clothing_selector.js');
const source = readFileSync(sourcePath, 'utf8');
const uiSource = readFileSync(path.join(modules, 'anima_selector_ui.js'), 'utf8');
const expectUnoptimized = process.argv.includes('--expect-unoptimized');

function extractFunction(text, name) {
    const match = text.match(new RegExp(`(?:export )?function ${name}\\([^]*?\\n}`, 'm'));
    assert.ok(match, `Cannot find function ${name}`);
    return match[0].replace(/^export /, '');
}

const translationConstant = source.match(/^const TRAITS_TRANSLATION = [^]*?;/m)?.[0];
assert.ok(translationConstant, 'Missing translation constant');
const helperSource = [translationConstant,
    extractFunction(uiSource, 'splitPromptTokens'),
    extractFunction(uiSource, 'normalizePromptToken'),
    extractFunction(source, 'getTraitZh')].join('\n');
const realGetTraitZh = new Function(`${helperSource}\nreturn getTraitZh;`)();
const labelSource = source.match(/allTraits\.forEach\(trait => \{([^]*?)\n\s*const row = createEl\("label", "anima-clothing-check-row"\)/)?.[1];
assert.ok(labelSource?.includes('label'), 'Sidebar label prefix no longer matches; inspect rather than silently test a fallback');
let calls = 0;
const observedGetTraitZh = (trait, items) => { calls++; return realGetTraitZh(trait, items); };
const render = new Function('getTraitZh', `return (trait, displayLang, clothingData) => {${labelSource}\nreturn label;};`)(observedGetTraitZh);

const cases = [];
function check(id, callback) {
    try { const details = callback(); cases.push({id, passed: true, ...details}); }
    catch (error) { cases.push({id, passed: false, error: error.message}); }
}
function oldLabel(trait, displayLang, items) {
    const zh = realGetTraitZh(trait.name, items);
    return displayLang === 'bilingual' && zh ? `${trait.name} (${zh})` : trait.name;
}

check('english_exact_name_and_translation_call_count', () => {
    calls = 0;
    const trait = {name: 'Warm RED', count: 2};
    const items = [{tags: 'warm red', tags_zh: '暖红'}];
    const actual = render(trait, 'en', items);
    assert.equal(actual, 'Warm RED');
    assert.equal(actual, oldLabel(trait, 'en', items));
    assert.equal(calls, expectUnoptimized ? 1 : 0);
    return {actual, translation_calls: calls};
});

if (!expectUnoptimized) check('english_does_not_read_corpus_tokens', () => {
    calls = 0;
    const item = {};
    Object.defineProperty(item, 'tags', {get() { throw new Error('English sidebar scanned corpus tokens'); }});
    const actual = render({name: 'unchanged'}, 'en', [item]);
    assert.equal(actual, 'unchanged');
    assert.equal(calls, 0);
    return {actual, translation_calls: calls};
});

const bilingualCases = [
    {id: 'bilingual_raw_prefix_case_and_trim', name: 'red', items: [{tags: '_raw_:RED, cotton', tags_zh: ' 红色 , 棉 '}], expected: 'red (红色)'},
    {id: 'bilingual_first_valid_translation_wins', name: 'red', items: [{tags: 'red', tags_zh: '甲'}, {tags: 'red', tags_zh: '乙'}], expected: 'red (甲)'},
    {id: 'bilingual_skip_missing_parallel_translation', name: 'red', items: [{tags: 'cotton, red', tags_zh: '棉'}, {tags: 'red', tags_zh: '赤'}], expected: 'red (赤)'},
    {id: 'bilingual_unmatched_legacy_fallback', name: 'unlisted', items: [{tags: 'red', tags_zh: '红色'}], expected: 'unlisted (unlisted)'},
    {id: 'bilingual_empty_name_fallback', name: '', items: [], expected: ''},
];
for (const fixture of bilingualCases) check(fixture.id, () => {
    calls = 0;
    const trait = {name: fixture.name};
    const actual = render(trait, 'bilingual', fixture.items);
    assert.equal(actual, fixture.expected);
    assert.equal(actual, oldLabel(trait, 'bilingual', fixture.items));
    assert.equal(calls, 1);
    return {actual, translation_calls: calls};
});

check('non_bilingual_saved_mode_keeps_name', () => {
    calls = 0;
    const actual = render({name: 'red'}, 'unexpected-saved-value', [{tags: 'red', tags_zh: '红色'}]);
    assert.equal(actual, 'red');
    assert.equal(calls, expectUnoptimized ? 1 : 0);
    return {actual, translation_calls: calls};
});

check('language_switch_has_no_stale_label', () => {
    calls = 0;
    const trait = {name: 'red'}, items = [{tags: 'red', tags_zh: '红色'}];
    const labels = ['en', 'bilingual', 'en'].map(language => render(trait, language, items));
    assert.deepEqual(labels, ['red', 'red (红色)', 'red']);
    assert.equal(calls, expectUnoptimized ? 3 : 1);
    return {labels, translation_calls: calls};
});

const passed = cases.every(test => test.passed);
const report = {
    checked_at: new Date().toISOString(),
    mode: expectUnoptimized ? 'pre_fix_characterization' : 'post_fix_contract',
    source_path: sourcePath,
    source_sha256: createHash('sha256').update(source).digest('hex'),
    pass: passed,
    cases,
    label_source: labelSource.trim(),
    boundary: 'Offline execution of the actual source label prefix and actual token/translation helpers; no browser, full selector, network or production mutation.',
};
const reportPath = path.join(run, expectUnoptimized ? 'clothing_trait_checks_before.json' : 'clothing_trait_checks_after.json');
writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n', 'utf8');
console.log(JSON.stringify({mode: report.mode, pass: passed, cases: cases.length, source_sha256: report.source_sha256, report: reportPath, failures: cases.filter(test => !test.passed)}));
if (!passed) process.exitCode = 1;
