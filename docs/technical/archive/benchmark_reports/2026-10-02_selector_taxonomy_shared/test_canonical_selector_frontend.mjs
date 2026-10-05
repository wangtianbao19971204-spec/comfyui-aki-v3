import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {JSDOM} from '../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const report = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(report, '../..');
const sourcePath = path.join(root, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-anima-tools/js/anima_shared_prompt_data.js');
const backendPath = path.join(root, 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-anima-tools/nodes.py');
const source = fs.readFileSync(sourcePath, 'utf8');
const digest = value => crypto.createHash('sha256').update(value).digest('hex');
const sourceSha = digest(fs.readFileSync(sourcePath));
const indexBody = fs.readFileSync(path.join(report, 'library_index_body.json'));
const libraryIndex = JSON.parse(indexBody);
const checks = [], failures = [], warnings = [];
const clone = value => JSON.parse(JSON.stringify(value));
const response = (body, status = 200) => ({ok:status === 200, status, json:async () => clone(body)});
const tick = () => new Promise(resolve => setImmediate(resolve));

function item(id, sourceId, subcategories, owners, themes, primary = themes[0]) {
  return {id, name:id, tags:'  exact_(tag),\noriginal  ', shared:true, source_category_id:sourceId,
    source_category:'同名来源', shared_category_paths:[{levels:['WeiLin / 旧名称', '目录'],
      parent:'WeiLin / 旧名称', source:'目录', source_category_id:sourceId, source_full:'同名来源'}],
    _semantic:{binding:'binding:' + id, disposition:'reviewed', manual_search_eligible:true,
      usage:'positive', content_type:'fragment', primary_class:primary,
      theme_ids:themes, subcategories, subcategory_owners:owners}};
}
const clothingA = item('clothing-A', 'source:A', ['服装材质与剪裁'], {'服装材质与剪裁':'clothing_accessory'}, ['clothing_accessory']);
const clothingB = item('clothing-B', 'source:B', ['裙装与礼服'], {'裙装与礼服':'clothing_accessory'}, ['clothing_accessory']);
const mixed = item('mixed', 'source:A', ['服装材质与剪裁', '作品角色'],
  {'服装材质与剪裁':'clothing_accessory', '作品角色':'identity'}, ['identity', 'clothing_accessory']);
const nested = item('nested', 'source:B', ['作品角色/初音'], {'作品角色/初音':'identity'}, ['identity']);
const wrongOwner = item('wrong-owner', 'source:A', ['服装材质与剪裁'], {'服装材质与剪裁':'artist_style'}, ['artist_style']);
const fixtureItems = [clothingA, clothingB, mixed, nested, wrongOwner];
const sharedPayload = (items = fixtureItems, revision = 'fixture-source-v1') => ({enabled:true, items,
  source_sha256:revision, source_last_modified:revision, taxonomy_version:'shared-selector-library-v2'});

async function harness(fetchImpl) {
  const dom = new JSDOM('', {url:'http://127.0.0.1:8188/', runScripts:'outside-only'});
  const win = dom.window, context = dom.getInternalVMContext(), requests = [];
  win.console.warn = (...args) => warnings.push(args.map(String).join(' '));
  win.fetch = (url, options) => {
    const entry = {url:new URL(url, win.location.href), options};
    requests.push(entry);
    if (fetchImpl) return fetchImpl(entry);
    return new Promise((resolve, reject) => Object.assign(entry, {resolve, reject}));
  };
  const ui = new vm.SyntheticModule(['installSelectorExperience'], function () {
    this.setExport('installSelectorExperience', () => () => {});
  }, {context});
  const module = new vm.SourceTextModule(source, {context, identifier:sourcePath});
  await module.link(specifier => {
    assert.equal(specifier, './anima_selector_ui.js');
    return ui;
  });
  await module.evaluate();
  return {dom, win, api:module.namespace, requests, close:() => win.close()};
}

async function test(name, action) {
  try { await action(); checks.push(name); }
  catch (error) { failures.push({name, error:String(error.stack || error)}); }
}

await test('taxonomy finite-field cache, force after completion, revision and event invalidation', async () => {
  const h = await harness(async () => response(libraryIndex));
  try {
    const first = await h.api.loadSharedLibraryTaxonomy({revision:'v1'});
    assert.deepEqual(Object.keys(first).sort(), ['labels', 'subcategories', 'values']);
    assert.equal(await h.api.loadSharedLibraryTaxonomy({revision:'v1'}), first);
    assert.equal(h.requests.length, 1);
    await h.api.loadSharedLibraryTaxonomy({revision:'v1', force:true});
    assert.equal(h.requests.length, 2);
    await h.api.loadSharedLibraryTaxonomy({revision:'v2'});
    assert.equal(h.requests.length, 3);
    h.win.dispatchEvent(new h.win.Event('anima-tools-shared-prompts-updated'));
    await h.api.loadSharedLibraryTaxonomy({revision:'v2'});
    assert.equal(h.requests.length, 4);
    assert(h.requests.every(entry => entry.options.cache === 'no-store'));
  } finally { h.close(); }
});

await test('taxonomy same-revision in-flight reads deduplicate', async () => {
  const h = await harness();
  try {
    const a = h.api.loadSharedLibraryTaxonomy({revision:'v1'});
    const b = h.api.loadSharedLibraryTaxonomy({revision:'v1'});
    assert.equal(h.requests.length, 1);
    h.requests[0].resolve(response(libraryIndex));
    assert.equal(await a, await b);
  } finally { h.close(); }
});

for (const mode of ['force', 'revision']) await test(`taxonomy ${mode} reads new bytes after an older in-flight request settles`, async () => {
  const h = await harness();
  try {
    const old = h.api.loadSharedLibraryTaxonomy({revision:'v1'}).then(value => ({value}), error => ({error}));
    const fresh = h.api.loadSharedLibraryTaxonomy(mode === 'force' ? {revision:'v1', force:true} : {revision:'v2'})
      .then(value => ({value}), error => ({error}));
    assert.equal(h.requests.length, 1, 'ordinary pending index reads settle before issuing a newer one');
    h.requests[0].resolve(response(libraryIndex));
    assert((await old).value);
    await tick();
    assert.equal(h.requests.length, 2, 'force/revision must then fetch a fresh index');
    const changedIndex = clone(libraryIndex);
    changedIndex.semantic_classes.identity = '角色与身份 · 新索引';
    h.requests[1].resolve(response(changedIndex));
    assert.equal((await fresh).value.labels.identity, '角色与身份 · 新索引');
  } finally { h.close(); }
});

await test('event-invalidated taxonomy success cannot overwrite a newer index', async () => {
  const h = await harness();
  try {
    const old = h.api.loadSharedLibraryTaxonomy({revision:'v1'}).then(value => ({value}), error => ({error}));
    h.win.dispatchEvent(new h.win.Event('anima-tools-shared-prompts-updated'));
    const fresh = h.api.loadSharedLibraryTaxonomy({revision:'v2'});
    assert.equal(h.requests.length, 2);
    h.requests[1].resolve(response(libraryIndex)); await fresh;
    h.requests[0].resolve(response({semantic_classes:{appearance:'旧标签'}, filter_pool:{subcategory:{}}}));
    assert.equal((await old).error?.code, 'STALE_SHARED_PROMPTS');
    assert.equal((await h.api.loadSharedLibraryTaxonomy({revision:'v2'})).labels.appearance, '外观与身体');
    assert.equal(h.requests.length, 2);
  } finally { h.close(); }
});

await test('taxonomy missing contract and HTTP errors reject without local fallback', async () => {
  let body = response({categories:[]});
  const h = await harness(async () => body);
  try {
    await assert.rejects(() => h.api.loadSharedLibraryTaxonomy({revision:'v1'}), /分类未就绪/);
    body = response(libraryIndex, 503);
    await assert.rejects(() => h.api.loadSharedLibraryTaxonomy({revision:'v1'}), /HTTP 503/);
    body = response(libraryIndex);
    assert.equal((await h.api.loadSharedLibraryTaxonomy({revision:'v1'})).labels.identity, '角色与身份');
  } finally { h.close(); }
});

await test('actual shared loader rechecks payload, caches finite taxonomy by source and schema', async () => {
  let revision = 'v1';
  const h = await harness(async entry => response(entry.url.pathname.endsWith('/index') ? libraryIndex : sharedPayload(fixtureItems, revision)));
  try {
    assert.equal((await h.api.loadSharedPromptItems('clothing')).length, 5);
    assert.equal((await h.api.loadSharedPromptItems('clothing')).length, 5);
    assert.equal(h.requests.filter(entry => entry.url.pathname.endsWith('/index')).length, 1);
    assert.equal(h.requests.filter(entry => entry.url.pathname.endsWith('/shared-prompts')).length, 2);
    revision = 'v2'; await h.api.loadSharedPromptItems('clothing');
    assert.equal(h.requests.filter(entry => entry.url.pathname.endsWith('/index')).length, 2);
    await h.api.loadSharedPromptIndexItems('clothing', {force:true});
    const shared = h.requests.filter(entry => entry.url.pathname.endsWith('/shared-prompts')).at(-1);
    assert.equal(shared.url.searchParams.get('index'), '1');
    assert(shared.url.searchParams.has('refresh'));
    assert.equal(h.requests.filter(entry => entry.url.pathname.endsWith('/index')).length, 3);
  } finally { h.close(); }
});

await test('payload projection revision invalidates taxonomy with unchanged source bytes', async () => {
  let projectionRevision = 'projection-v1';
  const h = await harness(async entry => response(entry.url.pathname.endsWith('/index') ? libraryIndex
    : {...sharedPayload(fixtureItems, 'unchanged-source'), revision:projectionRevision}));
  try {
    await h.api.loadSharedPromptItems('character');
    await h.api.loadSharedPromptItems('character');
    assert.equal(h.requests.filter(entry => entry.url.pathname.endsWith('/index')).length, 1);
    projectionRevision = 'projection-v2';
    await h.api.loadSharedPromptItems('character');
    assert.equal(h.requests.filter(entry => entry.url.pathname.endsWith('/index')).length, 2);
  } finally { h.close(); }
});

await test('shared loader safely rejects disabled data and filters revoked eligibility', async () => {
  let payload = {enabled:false, items:fixtureItems};
  const h = await harness(async entry => response(entry.url.pathname.endsWith('/index') ? libraryIndex : payload));
  try {
    await assert.rejects(() => h.api.loadMergedPromptItems('clothing', [{id:'local', tags:'fallback'}]), /共享资料库不可用/);
    payload = sharedPayload([clothingA, {...clothingB, _semantic:{...clothingB._semantic, manual_search_eligible:false}}]);
    const items = await h.api.loadSharedPromptItems('clothing');
    assert.deepEqual(Array.from(items, entry => entry.id), ['clothing-A']);
    assert.equal(items[0].tags, clothingA.tags);
  } finally { h.close(); }
});

await test('late shared success after an event and replacement cannot update stats', async () => {
  const h = await harness();
  try {
    const old = h.api.loadSharedPromptItems('character').then(value => ({value}), error => ({error}));
    h.win.dispatchEvent(new h.win.Event('anima-tools-shared-prompts-updated'));
    const fresh = h.api.loadSharedPromptItems('character');
    h.requests[1].resolve(response(sharedPayload([nested], 'v2'))); await tick();
    h.requests[2].resolve(response(libraryIndex)); await fresh;
    h.requests[0].resolve(response(sharedPayload(fixtureItems, 'v1')));
    assert.equal((await old).error?.code, 'STALE_SHARED_PROMPTS');
    assert.equal(h.win.animaSharedPromptStats.character.count, 1);
  } finally { h.close(); }
});

await test('shared invalidation while awaiting taxonomy rejects its late classification', async () => {
  const h = await harness();
  try {
    const old = h.api.loadSharedPromptItems('character').then(value => ({value}), error => ({error}));
    h.requests[0].resolve(response(sharedPayload(fixtureItems, 'v1'))); await tick();
    assert.equal(h.requests[1].url.pathname, '/prompt_selector/library/index');
    h.win.dispatchEvent(new h.win.Event('anima-tools-shared-prompts-updated'));
    const fresh = h.api.loadSharedPromptItems('character');
    h.requests[2].resolve(response(sharedPayload([nested], 'v2'))); await tick();
    h.requests[3].resolve(response(libraryIndex)); await fresh;
    h.requests[1].resolve(response(libraryIndex));
    assert.equal((await old).error?.code, 'STALE_SHARED_PROMPTS');
    assert.equal(h.win.animaSharedPromptStats.character.count, 1);
  } finally { h.close(); }
});

await test('canonical paths preserve labels, nested aliases and standard owner boundaries', async () => {
  const h = await harness(async () => response(libraryIndex));
  try {
    await h.api.loadSharedLibraryTaxonomy({revision:'v1'});
    const paths = h.api.getSharedCategoryPaths(nested);
    assert.equal(paths[0].levels.join('/'), '角色与身份/作品角色');
    assert.equal(paths[0].keys[1], 'shared-sub:作品角色');
    const wrongPaths = h.api.getSharedCategoryPaths(wrongOwner);
    assert(!wrongPaths.some(entry => entry.levels.includes('服装材质与剪裁')));
    const roots = h.api.buildSharedCategoryTree([clothingA, {...clothingA}, clothingB, mixed, nested]);
    const clothing = roots.find(entry => entry.key === 'shared-theme:clothing_accessory');
    assert.equal(clothing.label, '服装与配饰'); assert.equal(clothing.count, 3);
    assert.equal(clothing.children.find(entry => entry.key === 'shared-sub:服装材质与剪裁').count, 2);
    assert.equal(roots.find(entry => entry.key === 'shared-theme:identity').count, 2);
    assert(!roots.some(entry => entry.label.includes('WeiLin') || entry.label.includes('同名来源')));
  } finally { h.close(); }
});

const filterCases = [[], ['shared-theme:identity', 'shared-theme:clothing_accessory'],
  ['shared-sub:裙装与礼服', 'shared-sub:服装材质与剪裁'],
  ['shared-sub:作品角色', 'shared-sub:服装材质与剪裁'],
  ['shared-theme:identity', 'shared-sub:服装材质与剪裁'],
  ['shared-source:source:B', 'shared-sub:作品角色'],
  ['shared-source:同名来源'], ['shared-source:source'],
  ['shared-sub:identity::作品角色'], ['shared-sub:clothing_accessory::作品角色'],
  ['shared-path:WeiLin / 旧名称\u001f目录', 'shared-source:source:A']];

await test('frontend and actual backend agree on grouped semantic filters and exact sources', async () => {
  const h = await harness(async () => response(libraryIndex));
  try {
    await h.api.loadSharedLibraryTaxonomy({revision:'v1'});
    const actual = filterCases.map(filters => fixtureItems.map(entry => h.api.itemMatchesCategoryFilters(entry, new Set(filters))));
    const python = String.raw`import ast,json,sys
from pathlib import Path
data=json.load(sys.stdin)
source=Path(data['backend'])
tree=ast.parse(source.read_text(encoding='utf-8-sig'))
names={'_shared_prompt_item_matches_filters','_shared_prompt_category_paths_match_filter','_normalize_shared_category_filter_value'}
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
ctx={'_SHARED_PROMPT_PARENT_FILTER_PREFIX':'shared-parent:','_SHARED_PROMPT_CHILD_FILTER_PREFIX':'shared-child:','_SHARED_PROMPT_PATH_FILTER_PREFIX':'shared-path:','_SHARED_PROMPT_CATEGORY_SEPARATOR':'\x1f'}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),ctx)
owners={label:owner for owner,children in data['index']['filter_pool']['subcategory'].items() for label in children}
print(json.dumps([[ctx['_shared_prompt_item_matches_filters'](item,filters,owners) for item in data['items']] for filters in data['filters']]))`;
    const backend = spawnSync(path.join(root, 'python/python.exe'), ['-X', 'utf8', '-c', python], {
      input:JSON.stringify({backend:backendPath,index:libraryIndex,items:fixtureItems,filters:filterCases}), encoding:'utf8'});
    assert.equal(backend.status, 0, backend.stderr);
    assert.deepEqual(actual, JSON.parse(backend.stdout));
    assert.equal(h.api.itemMatchesCategoryFilters(nested, new Set(['shared-sub:作品角色'])), true);
    assert.equal(h.api.itemMatchesCategoryFilters(clothingA, new Set(['shared-source:source:B', 'shared-theme:clothing_accessory'])), false);
    assert.equal(JSON.parse(h.api.getSharedCategoryRequestFilter(new Set(filterCases[5])).slice('shared-filters:'.length)).length, 2);
  } finally { h.close(); }
});

await test('same-name sources stay independent and navigation retains source selection', async () => {
  const h = await harness(async () => response(libraryIndex));
  try {
    await h.api.loadSharedLibraryTaxonomy({revision:'v1'});
    const sources = h.api.buildSharedSourceOptions([clothingA, {...clothingA}, clothingB, mixed, nested]);
    assert.deepEqual(Array.from(sources, entry => [entry.id, entry.count]), [['source:A', 2], ['source:B', 2]]);
    assert.equal(new Set(sources.map(entry => entry.label)).size, 1);
    const selected = new Set(['shared-sub:服装材质与剪裁', 'shared-source:source:A']);
    h.api.activateSharedCategoryNavigationFilter(selected, 'shared-theme:identity');
    assert.deepEqual([...selected].sort(), ['shared-source:source:A', 'shared-theme:identity']);
    h.api.activateSharedCategoryNavigationFilter(selected, '');
    assert.deepEqual([...selected], ['shared-source:source:A']);
    selected.add('shared-path:WeiLin / 旧名称\u001f目录');
    h.api.normalizeSharedCategoryNavigationFilters(selected, fixtureItems);
    assert(selected.has('shared-source:source:A'));
    assert(![...selected].some(value => value.startsWith('shared-path:')));
  } finally { h.close(); }
});

await test('renderer disclosure, Enter/Space navigation, source clearing and persistence', async () => {
  const h = await harness(async () => response(libraryIndex));
  try {
    await h.api.loadSharedLibraryTaxonomy({revision:'v1'});
    const sidebar = h.win.document.createElement('div'); h.win.document.body.append(sidebar);
    const selected = new Set(['shared-source:source:A']); let changed = 0;
    const render = () => {
      sidebar.replaceChildren();
      h.api.appendSharedCategoryTree({sidebar, items:fixtureItems, selectedFilters:selected,
        storageKey:'canonical-fixture-collapse', onFilterChange:() => changed++});
    };
    render();
    const row = sidebar.querySelector('[data-shared-category-path="shared-theme:clothing_accessory"]');
    const children = row.parentElement.children[1], arrow = row.querySelector('button');
    assert.equal(row.getAttribute('role'), 'button'); assert.equal(row.tabIndex, 0);
    assert.equal(children.style.display, 'none'); arrow.click();
    assert.equal(children.style.display, 'flex'); assert.equal(changed, 0);
    assert.equal(JSON.parse(h.win.localStorage.getItem('canonical-fixture-collapse'))['shared-theme:clothing_accessory'], false);
    row.dispatchEvent(new h.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true, cancelable:true}));
    assert(selected.has('shared-theme:clothing_accessory') && selected.has('shared-source:source:A'));
    assert.equal(changed, 1);
    const identity = sidebar.querySelector('[data-shared-category-path="shared-theme:identity"]');
    identity.dispatchEvent(new h.win.KeyboardEvent('keydown', {key:' ', bubbles:true, cancelable:true}));
    assert(selected.has('shared-theme:identity') && !selected.has('shared-theme:clothing_accessory'));
    assert.equal(changed, 2);
    const picker = sidebar.querySelector('select[aria-label="来源筛选"]');
    assert.equal(picker.value, 'source:A'); assert.equal(sidebar.querySelector('details').open, true);
    picker.value = 'source:B'; picker.dispatchEvent(new h.win.Event('change'));
    assert(selected.has('shared-source:source:B') && selected.has('shared-theme:identity'));
    picker.value = ''; picker.dispatchEvent(new h.win.Event('change'));
    assert.deepEqual([...selected], ['shared-theme:identity']);
    render();
    assert.equal(sidebar.querySelector('[data-shared-category-path="shared-theme:clothing_accessory"]').parentElement.children[1].style.display, 'flex');
    selected.clear(); selected.add('shared-sub:作品角色');
    h.win.localStorage.setItem('canonical-fixture-collapse', JSON.stringify({'shared-theme:identity':true}));
    render();
    assert.equal(sidebar.querySelector('[data-shared-category-path="shared-theme:identity"]').parentElement.children[1].style.display, 'flex');
  } finally { h.close(); }
});

await test('renderer prunes conflicting dynamic keys and wrong-owner inventory from supplied artist tree', async () => {
  const h = await harness(async () => response(libraryIndex));
  try {
    await h.api.loadSharedLibraryTaxonomy({revision:'artist-revision'});
    const sidebar = h.win.document.createElement('div'); h.win.document.body.append(sidebar);
    const leaf = (name, key) => ({name, label:'旧显示名称', key, count:1, children:[]});
    const tree = [
      {key:'shared-theme:artist_style', name:'WeiLin / 旧画师名称', label:'旧画师名称', count:3,
        children:[leaf('画师标签', 'shared-sub:identity::画师标签'),
          leaf('冲突动态小主题', 'shared-sub:artist_style::冲突动态小主题'),
          leaf('服装材质与剪裁', 'shared-sub:服装材质与剪裁')]},
      {key:'shared-theme:clothing_accessory', name:'旧服装名称', label:'旧服装名称', count:2,
        children:[leaf('服装材质与剪裁', 'shared-sub:服装材质与剪裁'),
          leaf('冲突动态小主题', 'shared-sub:clothing_accessory::冲突动态小主题')]},
      {key:'shared-theme:unknown', name:'unknown', label:'unknown', count:1, children:[]},
    ];
    const original = JSON.stringify(tree);
    h.api.appendSharedCategoryTree({sidebar, tree, sourceOptions:[], selectedFilters:new Set(),
      storageKey:'canonical-fixture-input-tree', onFilterChange:() => {}});
    const rows = [...sidebar.querySelectorAll('[data-shared-category-path]')];
    assert.deepEqual(rows.map(row => row.dataset.sharedCategoryPath), ['shared-theme:clothing_accessory',
      'shared-sub:服装材质与剪裁', 'shared-theme:artist_style', 'shared-sub:画师标签']);
    assert(rows.find(row => row.dataset.sharedCategoryPath === 'shared-theme:artist_style').textContent.includes('画师与作者'));
    assert(!sidebar.textContent.includes('冲突动态小主题'));
    assert.equal(JSON.stringify(tree), original, 'renderer must not mutate cached backend tree');
  } finally { h.close(); }
});

const receipt = {verified_at:new Date().toISOString(), passed:failures.length === 0,
  source_path:sourcePath, source_sha256:sourceSha, source_unchanged_during_test:digest(fs.readFileSync(sourcePath)) === sourceSha,
  backend_sha256:digest(fs.readFileSync(backendPath)), index_response_sha256:digest(indexBody),
  checks, check_count:checks.length, failures, expected_failure_warnings:warnings,
  method:'Actual unmodified shared JS loaded as a VM ESM with only its selector UI import and local fetch mocked; real jsdom DOM; canonical vocabulary from captured live index; actual backend predicates isolated through AST.',
  production_writes:0, live_http_requests:0, browser_actions:0, service_restarts:0,
  limits:['Synthetic shared records and jsdom acceptance only; no full-library scan or visual GUI certification.']};
fs.writeFileSync(path.join(report, 'frontend_canonical_contract.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify({passed:receipt.passed, checks:checks.length, failures:failures.map(entry => ({name:entry.name,error:entry.error.split('\n').slice(0,3).join('\n')})), source_sha256:sourceSha, source_unchanged:receipt.source_unchanged_during_test}));
if (!receipt.passed) process.exitCode = 1;
