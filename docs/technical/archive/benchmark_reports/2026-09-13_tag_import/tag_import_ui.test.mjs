import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { JSDOM } from 'file:///G:/ComfyUI-aki-v3/benchmark_reports/2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const sourcePath = process.argv[2] || 'G:/ComfyUI-aki-v3/_codex_validation/2026-09-06_plugin_optimization/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/tag_manager.js';
const source = fs.readFileSync(sourcePath, 'utf8');
const dom = new JSDOM('<div id="host"><button id="outside">outside</button></div>', {
  url: 'http://localhost/',
  runScripts: 'outside-only',
  pretendToBeVisual: true
});
const { window: w } = dom;
w.structuredClone = structuredClone;
const { document: d } = w;
w.HTMLElement.prototype.getClientRects = function () {
  return this.isConnected && !this.closest('[hidden]') ? [{}] : [];
};

const groups = [{ p_uuid: 'p', name: 'Main', groups: [{ g_uuid: 'g', p_uuid: 'p', name: 'Sub', count: 3 }] }];
const collections = [{ id: 'default', name: 'Default' }, { id: 'existing', name: 'Existing' }];
const catalog = () => ({ groups, collections, revision: 'catalog-r1', collection_revision: 'collections-r1' });
const item = { resource_id: 'tag:one', text: 'one', desc: 'desc', g_uuid: 'g', collection_ids: ['default'], favorite: false };
const checks = [];
const writes = [];
const preflights = [];
const plans = [];
let latestOperation;
let updateGate = null;
let preflightMode = 'committable';
let updateMode = 'success';
let updateResult = null;
let pageRevision = 'page-r1';
let updateCount = 0;
let indexCount = 0;

const response = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => structuredClone(body)
});

w.fetch = async (url, options = {}) => {
  const u = new URL(url, 'http://localhost');
  if (u.pathname.endsWith('/index')) {
    indexCount++;
    return response(catalog());
  }
  if (u.pathname.endsWith('/page')) {
    return response({ items: [item], total: 1, revision: pageRevision });
  }
  if (u.pathname.endsWith('/item')) {
    return response({ item, collections, revision: pageRevision, collection_revision: 'collections-r1' });
  }
  if (u.pathname.endsWith('/pre_import')) {
    const body = JSON.parse(options.body);
    preflights.push({ body, options });
    if (body.bundle.items.some(x => x.collection_ids?.includes('missing'))) {
      throw new Error('preflight received an untransformed missing collection');
    }
    const blocked = preflightMode === 'blocked';
    const plan = {
      contract: 'tag-import-preflight-v1',
      preflight_token: blocked ? 'blocked-token' : 'token-' + preflights.length,
      base_revision: 'base-r' + preflights.length,
      collection_revision: 'base-c' + preflights.length,
      committable: !blocked,
      blocked_reason: blocked ? '覆盖策略冲突' : undefined,
      counts: { new: 2, updated: 3, suspected_duplicate: 4, unsupported: 1, version_conflicts: 5, total_records: 15, will_write: 8, will_skip: 7 },
      category_counts: {
        groups: { new: 1, updated: 1, suspected_duplicate: 1, unsupported: 0, version_conflicts: 1 },
        subgroups: { new: 1, updated: 2, suspected_duplicate: 3, unsupported: 1, version_conflicts: 4 }
      }
    };
    plans.push(plan); return response(plan);
  }
  if (u.pathname.endsWith('/update')) {
    const payload = JSON.parse(options.body);
    writes.push({ payload, headers: options.headers });
    updateCount++;
    if (updateGate) await updateGate;
    if (updateMode === 'known-failure') {
      return response({ error: '服务器拒绝导入', operation: updateResult }, 409);
    }
    if (updateMode === 'unknown-failure') return response({ error: '连接中断' }, 503);
    if (payload.operation === 'import') {
      return response({
        revision: 'after-import-r2',
        collection_revision: 'after-import-c2',
        operation: latestOperation = updateResult || {
          contract: 'weilin-tag-import-operation-v1',
          committed: 8,
          uncommitted: 2,
          skipped: 5,
          category_counts: { groups: { new: 1 }, subgroups: { updated: 2 } },
          detail: [{ resource_id: 'tag:a', operation: 'create' }]
        }
      });
    }
    return response({ revision: 'ordinary-r2', success: true });
  }
  throw new Error('Unexpected fetch: ' + u.pathname);
};

const insertion = new vm.SourceTextModule('export function mountInsertionActions(host, actions) { host.dataset.mounted = "yes"; return { picker: { value: "append_end" }, undo: { disabled: true }, dispose() {} }; }', { context: dom.getInternalVMContext() });
await insertion.link(() => {});
await insertion.evaluate();
const module = new vm.SourceTextModule(source, { context: dom.getInternalVMContext() });
await module.link(() => insertion);
await module.evaluate();
const openTagManager = module.namespace.openTagManager;
const closeTagManager = module.namespace.closeTagManager;

const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const settle = async () => { await tick(); await tick(); await tick(); };
const q = selector => d.querySelector(selector);
const buttons = text => [...d.querySelectorAll('button')].filter(button => button.textContent === text);
const action = text => buttons(text).at(-1);
const field = label => [...d.querySelectorAll('.ut-form label')].find(x => x.firstChild?.textContent === label)?.querySelector('input,textarea,select');
const chooseFile = async (json, name = 'import.json', textDelay = 0) => {
  const file = {
    name,
    type: 'application/json',
    async text() { if (textDelay) await new Promise(resolve => setTimeout(resolve, textDelay)); return JSON.stringify(json); }
  };
  const input = field('Tag 数据文件');
  Object.defineProperty(input, 'files', { configurable: true, value: [file] });
  input.dispatchEvent(new w.Event('change', { bubbles: true }));
  return file;
};
const importBundle = {
  format: 'weilin-tags-v1',
  items: [{ resource_id: 'tag:new', text: 'new text', collection_ids: ['missing'] }, { resource_id: 'tag:old', text: 'old text', collection_ids: ['default'] }]
};
const openImport = async () => {
  await openTagManager({ mount: q('#host') });
  action('导入 JSON').click();
  await settle();
};
const closeRoot = () => { if (q('.ut-form')) buttons('取消').at(-1).click(); assert.equal(closeTagManager(), true); };

await openImport();
const importForm = q('.ut-form');
assert(importForm, 'import modal should be rendered by the real manager');
const fileInput = field('Tag 数据文件');
assert.equal(fileInput.accept, '.json,application/json');
const firstFile = await chooseFile(importBundle);
await settle();
assert.match(q('.ut-form [role=status]').textContent, /本机没有的分组/);
assert.equal(preflights.length, 0, 'unknown collection IDs must block preflight until fallback is selected');

const fallback = field('文件中不存在于本机的分组归入默认分组');
fallback.checked = true;
fallback.dispatchEvent(new w.Event('change', { bubbles: true }));
await settle();
assert.equal(preflights.length, 1);
assert.deepEqual(preflights[0].body.bundle.items[0].collection_ids, ['default']);
assert.deepEqual(JSON.parse(await firstFile.text()).items[0].collection_ids, ['missing'], 'fallback must not mutate the source file data');
assert.match(q('.ut-form').textContent, /新增：2/);
assert.match(q('.ut-form').textContent, /更新：3/);
assert.match(q('.ut-form').textContent, /疑似重复：4/);
assert.match(q('.ut-form').textContent, /不支持：1/);
assert.match(q('.ut-form').textContent, /版本冲突：5/);
assert.match(q('.ut-form').textContent, /主分类/);
assert.match(q('.ut-form').textContent, /子分类/);
checks.push('new JSON performs readonly preflight with five counts and category counts');

preflightMode = 'blocked';
const overwrite = field('覆盖相同 ID 的已有内容');
overwrite.checked = true;
overwrite.dispatchEvent(new w.Event('change', { bubbles: true }));
await settle();
const save = buttons('导入').at(-1);
const confirm = [...d.querySelectorAll('.ut-form input[type=checkbox]')].find(x => !x.dataset.collectionId && x !== fallback && x !== overwrite);
assert(confirm, 'explicit confirmation checkbox should exist');
assert.equal(save.disabled, true, 'policy conflict must remain non-committable');
confirm.checked = true;
confirm.dispatchEvent(new w.Event('change', { bubbles: true }));
assert.equal(save.disabled, true, 'manual confirmation cannot override committable=false');
const writesBeforeBlockedSubmit = writes.length;
await save.onclick();
assert.equal(writes.length, writesBeforeBlockedSubmit, 'forced invocation cannot submit a blocked plan');
const blockedRequest = preflights.at(-1).body;
preflightMode = 'committable';
overwrite.checked = false;
overwrite.dispatchEvent(new w.Event('change', { bubbles: true }));
await settle();
assert.notDeepEqual(preflights.at(-1).body, blockedRequest, 'changing overwrite must re-preview the transformed bundle');
assert.equal(confirm.checked, false, 'changing options must cancel confirmation');
assert.equal(save.disabled, true);
confirm.checked = true;
confirm.dispatchEvent(new w.Event('change', { bubbles: true }));
assert.equal(save.disabled, false);
checks.push('policy conflict blocks manual onclick and option changes invalidate confirmation');

let releaseUpdate;
updateGate = new Promise(resolve => { releaseUpdate = resolve; });
const beforeSubmit = writes.length;
const submitBundle = preflights.at(-1).body.bundle;
const submitClick = save.onclick();
save.onclick();
await tick();
assert.equal(writes.length, beforeSubmit + 1, 'reentrant import clicks send one request');
assert.equal(closeTagManager(), false, 'root close cannot dismiss pending import');
buttons('取消').at(-1).onclick();
assert(q('.ut-form'), 'direct cancel cannot dismiss pending import');
assert.equal(q('.ut-dialog'), importForm.closest('.ut-dialog'), 'submit must not close modal while request is pending');
assert.deepEqual(writes.at(-1).payload.bundle, submitBundle);
assert.equal(writes.at(-1).payload.preflight_token, plans.at(-1).preflight_token);
assert.equal(writes.at(-1).payload.collection_revision, plans.at(-1).collection_revision);
assert.equal(writes.at(-1).headers['If-Match'], plans.at(-1).base_revision);
assert.equal(writes.at(-1).payload.confirmed, true);
releaseUpdate();
await submitClick;
await settle();
assert.match(q('.ut-form').textContent, /导入完成：已提交 8 条/);
assert(!q('.ut-form').textContent.includes('"contract"'), 'success result must be human-readable rather than raw JSON');
assert.equal(buttons('完成并返回列表').at(-1).hidden, false);
checks.push('submit binds exact preview bundle, revisions, token, confirmation and preserves readable success result');

let exportedBlob = null;
w.URL.createObjectURL = blob => { exportedBlob = blob; return 'blob:test-operation'; };
w.URL.revokeObjectURL = () => {};
const oldAnchorClick = w.HTMLAnchorElement.prototype.click;
w.HTMLAnchorElement.prototype.click = function () { this.dataset.clicked = 'yes'; };
buttons('导出操作 JSON').at(-1).click();
assert(exportedBlob instanceof w.Blob);
const exportedText = await new Promise((resolve, reject) => {
  const reader = new w.FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = reject;
  reader.readAsText(exportedBlob);
});
assert.deepEqual(JSON.parse(exportedText), latestOperation);
checks.push('successful import exports the exact operation Blob');

const list = q('.ut-list');
list.scrollTop = 317;
// 2026-09-15: rows are .ut-row in list mode and .ut-card in the default card grid.
const selected = q('.ut-list input[type=checkbox]');
selected.checked = true;
selected.dispatchEvent(new w.Event('change', { bubbles: true }));
const oldIndexCount = indexCount;
buttons('完成并返回列表').at(-1).onclick();
await settle();
assert.equal(q('.ut-dialog'), null, 'complete closes the import modal once');
assert(q('.ut-list'));
assert.equal(q('.ut-list').scrollTop, 317);
assert.equal(q('.ut-list input[type=checkbox]').checked, true);
assert(indexCount > oldIndexCount);
checks.push('complete refreshes catalog/list while preserving scroll and selection');

closeRoot();
updateMode = 'known-failure';
updateResult = { contract: 'weilin-tag-import-operation-v1', committed: 0, uncommitted: 3, skipped: 2, category_counts: { groups: {}, subgroups: {} } };
await openImport();
await chooseFile({ format: 'weilin-tags-v1', items: [{ resource_id: 'tag:x', text: 'x', collection_ids: ['default'] }] });
await settle();
const knownFile = field('Tag 数据文件');
const knownFallback = field('文件中不存在于本机的分组归入默认分组');
assert.equal(knownFallback.checked, false);
const knownConfirm = [...d.querySelectorAll('.ut-form input[type=checkbox]')].find(x => !x.dataset.collectionId && x !== knownFallback && x !== field('覆盖相同 ID 的已有内容'));
knownConfirm.checked = true;
knownConfirm.dispatchEvent(new w.Event('change', { bubbles: true }));
buttons('导入').at(-1).click();
await settle();
assert.equal(knownFile.disabled, false, 'known failure retains file/options');
assert(q('.ut-form').textContent.includes('可导出操作结果'));
assert.equal(buttons('导出操作 JSON').at(-1).hidden, false);
assert.equal(knownConfirm.checked, false, 'known failure invalidates confirmation');
checks.push('known server failure retains inputs and permits exact manifest export');

closeRoot();
updateMode = 'unknown-failure';
await openImport();
await chooseFile({ format: 'weilin-tags-v1', items: [{ resource_id: 'tag:y', text: 'y', collection_ids: ['default'] }] });
await settle();
const unknownConfirm = [...d.querySelectorAll('.ut-form input[type=checkbox]')].find(x => !x.dataset.collectionId && x !== field('文件中不存在于本机的分组归入默认分组') && x !== field('覆盖相同 ID 的已有内容'));
unknownConfirm.checked = true;
unknownConfirm.dispatchEvent(new w.Event('change', { bubbles: true }));
buttons('导入').at(-1).click();
await settle();
assert.match(q('.ut-form').textContent, /无法确定导入结果/);
assert(!q('.ut-form').textContent.includes('已提交 0 条'));
assert.equal(buttons('导出操作 JSON').at(-1).hidden, true, 'unknown result must not expose a stale operation manifest');
checks.push('unknown network result never claims zero committed or exposes an old manifest');

closeRoot();
updateMode = 'success';
let staleRelease;
const staleFile = { format: 'weilin-tags-v1', items: [{ resource_id: 'tag:stale', text: 'stale', collection_ids: ['default'] }] };
const freshFile = { format: 'weilin-tags-v1', items: [{ resource_id: 'tag:fresh', text: 'fresh', collection_ids: ['default'] }] };
await openImport();
const slow = { name: 'slow.json', async text() { await new Promise(resolve => { staleRelease = resolve; }); return JSON.stringify(staleFile); } };
const input = field('Tag 数据文件');
Object.defineProperty(input, 'files', { configurable: true, value: [slow] });
input.dispatchEvent(new w.Event('change', { bubbles: true }));
await tick();
await chooseFile(freshFile, 'fresh.json');
await settle();
staleRelease();
await settle();
assert.equal(preflights.at(-1).body.bundle.items[0].text, 'fresh');
closeRoot();
assert.equal(q('#unified-tag-manager'), null);
checks.push('stale file reads cannot replace a newer preview; modal closes through original lifecycle');

let ordinaryRelease;
await openTagManager({ mount: q('#host') });
action('新建 Tag').click();
await settle();
const ordinarySave = buttons('保存').at(-1);
field('Tag 正文').value = 'ordinary neutral fixture';
updateGate = new Promise(resolve => { ordinaryRelease = resolve; });
ordinarySave.click();
await tick();
assert(q('.ut-dialog'), 'ordinary edit modal remains open while saving');
assert.equal(closeTagManager(), false, 'ordinary modal still honors setBusy and cannot close during save');
ordinaryRelease();
await settle();
updateGate = null;
assert.equal(q('.ut-dialog'), null);
closeTagManager();
checks.push('ordinary edit modal remains compatible with setBusy busy-state hook');

w.HTMLAnchorElement.prototype.click = oldAnchorClick;
console.log(JSON.stringify({ passed: true, sourcePath, checks, preflights: preflights.length, writes: writes.length }, null, 2));
