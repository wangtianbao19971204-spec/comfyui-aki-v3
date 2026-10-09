const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const { test } = require('node:test');

async function harness() {
  const requests = [], notices = [], elements = [], listeners = new Map();
  let extension, changes = 0;
  const app = { registerExtension: value => extension = value,
    graph: { change() { changes++; } },
    extensionManager: { toast: { add(value) { notices.push(value.detail); } } } };
  const api = { async fetchApi(url, options = {}) {
    requests.push({ url, ...options, body: options.body && JSON.parse(options.body) });
    return { ok: true, async json() { return url.endsWith('/studio') ?
      { session: 'a'.repeat(32), url: '/stocking_texture/studio/' + 'a'.repeat(32) + '/' } : { ok: true }; } };
  } };
  const document = { body: { append() {} }, createElement(tag) {
    const element = { tag, style: {}, contentWindow: { replies: [], postMessage(value) { this.replies.push(value); } },
      append() {}, setAttribute() {}, addEventListener() {}, showModal() {}, focus() {},
      remove() { this.removed = true; } };
    elements.push(element); return element;
  } };
  const window = { addEventListener(type, fn) { listeners.set(type, fn); },
    removeEventListener(type) { listeners.delete(type); } };
  const context = vm.createContext({ app, api, document, window, crypto: webcrypto,
    TextEncoder, Uint8Array, location: { origin: 'http://localhost:8197' } });
  const source = fs.readFileSync(path.resolve(__dirname, '../web/stocking_studio.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '');
  vm.runInContext(source + '\nglobalThis.testing = { openStudio, projectHash };', context);
  class Node {
    constructor() { this.widgets = [{ name: 'project_json', value: '{}', element: { style: {} } }]; this.graph = {}; this.inputs = []; }
    addWidget(type, name, value, callback, options) { this.widgets.push({ type, name, value, callback, options }); }
    setDirtyCanvas() {}
  }
  await extension.beforeRegisterNodeDef(Node, { name: 'StockingTextureStudio' });
  const node = new Node(); node.onNodeCreated();
  const open = () => context.testing.openStudio(node);
  const emit = (data, overrides = {}) => listeners.get('message')?.({
    origin: 'http://localhost:8197', source: elements.find(e => e.tag === 'iframe').contentWindow,
    data: { session: 'a'.repeat(32), type: 'stocking-studio-apply', ticket: 'b'.repeat(32), ...data }, ...overrides });
  return { node, open, emit, requests, elements, notices, context, changes: () => changes };
}

test('execution metadata cannot replace a manually changed workflow', async () => {
  const h = await harness();
  const source_hash = await h.context.testing.projectHash('{}');
  h.node.onExecuted({ stocking_studio: [{ project: { image_sha256: 'old' }, source_hash }] });
  h.node.widgets[0].value = '{"image_sha256":"new","schema":2}';
  await h.open();
  assert.equal(h.requests[0].body.project.image_sha256, 'new');
  h.node.onRemoved();
});

test('a current connected-image preview opens, applies, and acknowledges the serialized widget', async () => {
  const h = await harness();
  h.node.inputs = [{ name: 'image', link: 42 }];
  h.node.onExecuted({ stocking_studio: [{ project: { image_sha256: 'image' },
    source_hash: await h.context.testing.projectHash('{}') }] });
  await h.open();
  await h.emit({ project: { image_sha256: 'image', schema: 2, name: 'edited' } });
  assert.equal(JSON.parse(h.node.widgets[0].value).name, 'edited');
  assert.equal(h.node.widgets[0].element.value, h.node.widgets[0].value);
  assert.equal(h.changes(), 1);
  assert.equal(h.requests.at(-1).url.endsWith('/apply/ack'), true);
  assert.equal(h.elements.find(e => e.tag === 'iframe').contentWindow.replies.at(-1).ok, true);
  h.node.onRemoved();
});

test('stale apply and another window cannot mutate or acknowledge the workflow', async () => {
  const h = await harness(); await h.open();
  await h.emit({ project: { schema: 2 } }, { origin: 'https://foreign.invalid' });
  assert.equal(h.node.widgets[0].value, '{}');
  h.node.widgets[0].value = '{"changed":true}';
  await h.emit({ project: { schema: 2 } });
  assert.equal(h.node.widgets[0].value, '{"changed":true}');
  assert.equal(h.requests.some(r => r.url.endsWith('/apply/ack')), false);
  assert.equal(h.elements.find(e => e.tag === 'iframe').contentWindow.replies.at(-1).ok, false);
  h.node.onRemoved();
});

test('connected image replacement or rewiring requires opening a fresh editor', async () => {
  const h = await harness(); h.node.inputs = [{ name: 'image', link: 42 }];
  h.node.onExecuted({ stocking_studio: [{ project: { image_sha256: 'image' },
    source_hash: await h.context.testing.projectHash('{}') }] });
  await h.open();
  await h.emit({ project: { image_sha256: 'different' } });
  assert.equal(h.node.widgets[0].value, '{}');
  h.node.inputs[0].link = 43;
  await h.emit({ project: { image_sha256: 'image' } });
  assert.equal(h.node.widgets[0].value, '{}');
  h.node.onRemoved();
});

test('reload clears stale execution state and closes the session; clones own independent drafts', async () => {
  const h = await harness(); await h.open();
  const before = h.node.properties.stockingStudioDraft;
  h.node.onClone(); assert.notEqual(h.node.properties.stockingStudioDraft, before);
  h.node.onConfigure();
  assert.equal(h.node._stockingStudio.preview, null);
  assert.equal(h.node._stockingStudio.panel, null);
  assert.equal(h.requests.at(-1).url.endsWith('/api/close'), true);
  h.node.onRemoved(); assert.equal(h.node._stockingStudio, null);
});

test('connected image without a current execution preview never opens stale content', async () => {
  const h = await harness(); h.node.inputs = [{ name: 'image', link: 1 }];
  await h.open();
  assert.equal(h.requests.length, 0);
  assert.match(h.notices[0], /运行一次/);
  assert.equal(h.node._stockingStudio.opening, false);
});
