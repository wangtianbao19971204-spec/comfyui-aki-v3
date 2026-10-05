import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {JSDOM} from '../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const run = path.dirname(fileURLToPath(import.meta.url));
const filename = path.join(run, 'candidate/anima_shared_prompt_data.js');
const source = fs.readFileSync(filename, 'utf8');
const dom = new JSDOM('<!doctype html><body></body>', {url:'http://127.0.0.1:8188', runScripts:'outside-only'});
dom.window.fetch = url => fetch('http://127.0.0.1:8188' + url);
dom.window.eval(source.replace(/^import .*;\r?\n/, '').replaceAll('export ', '') + `
window.testApi = {loadSharedLibraryTaxonomy, getSharedTopicSummary, getSharedCategoryPaths,
buildSharedCategoryTree, appendSharedCategoryTree, itemMatchesCategoryFilters, appendSharedResourceEditor};`);
const api = dom.window.testApi;
const taxonomy = await api.loadSharedLibraryTaxonomy();
const cases = [];
for (const [kind, theme] of Object.entries({pose:'pose_action',clothing:'clothing_accessory',background:'background_environment',character:'identity',artist:'artist_style',style_quality:'style_medium'})) {
    const response = await fetch(`http://127.0.0.1:8188/anima-tools/shared-prompts?kind=${kind}&index=1`);
    assert.ok(response.ok);
    const {items} = await response.json();
    const host = dom.window.document.createElement('aside');
    dom.window.document.body.replaceChildren(host);
    const selected = new Set();
    let changes = 0;
    api.appendSharedCategoryTree({sidebar:host, items, kind, selectedFilters:selected, storageKey:'test-'+kind, onFilterChange:() => changes++});
    const first = host.querySelector('[data-shared-category-path]');
    assert.equal(first.dataset.sharedCategoryPath, 'shared-theme:'+theme);
    assert.equal(first.nextElementSibling.style.display, 'flex');
    const child = first.nextElementSibling.querySelector('[data-shared-category-path]');
    assert.ok(child);
    const key = child.dataset.sharedCategoryPath;
    child.click();
    assert.ok(selected.has(key));
    assert.equal(changes, 1);
    const matches = items.filter(item => api.itemMatchesCategoryFilters(item, selected));
    const count = Number(child.lastElementChild.textContent);
    assert.equal(matches.length, count);
    assert.ok(matches.length > 0);
    for (const root of api.buildSharedCategoryTree(items)) {
        const parent = root.key.slice('shared-theme:'.length);
        assert.equal(root.label, taxonomy.labels[parent]);
        for (const leaf of root.children) assert.ok(Object.hasOwn(taxonomy.subcategories[parent], leaf.label));
    }
    const item = matches[0];
    const card = dom.window.document.createElement('div');
    const info = dom.window.document.createElement('div');
    card.append(info);
    api.appendSharedResourceEditor(card, item, () => {}, info);
    const label = card.querySelector('.anima-shared-resource-taxonomy');
    assert.ok(label.textContent.includes(' · '));
    assert.ok(!label.textContent.startsWith('WeiLin'));
    assert.ok(label.title.includes(taxonomy.labels[theme]));
    assert.equal(card.querySelector('.anima-shared-resource-edit').dataset.promptId, item.source_prompt_id);
    first.querySelector('button').click();
    assert.equal(first.nextElementSibling.style.display, 'none');
    cases.push({kind, total:items.length, firstTheme:theme, firstSubtopic:key, count, label:label.textContent, passed:true});
}
const report = {passed:true, mode:'candidate JS in isolated jsdom; current read-only HTTP data; no production writes', sha256:crypto.createHash('sha256').update(source).digest('hex'), cases};
fs.writeFileSync(path.join(run, 'candidate_checks.json'), JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
dom.window.close();
