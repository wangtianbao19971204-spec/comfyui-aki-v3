const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.resolve(__dirname, '../ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web');
const id = '11111111-1111-4111-8111-111111111111';
const nextId = '22222222-2222-4222-8222-222222222222';
const sourceUrl = 'https://example.org/posts/12';
let checks = 0;
const check = (condition, message) => { assert(condition, message); checks++; };

class Element {
    constructor(tag, ownerDocument) {
        this.tagName = tag.toUpperCase(); this.ownerDocument = ownerDocument;
        this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = new Map();
        this.className = ''; this.classList = {add: (...names) => {this.className += ' ' + names.join(' ');}};
    }
    get isConnected() { return this === this.ownerDocument.body || !!this.parentNode?.isConnected; }
    get value() { return this._value ?? (this.tagName === 'SELECT' ? this.children[0]?.value : '') ?? ''; }
    set value(value) { this._value = String(value); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    addEventListener(name, callback) {
        if(!this.listeners.has(name))this.listeners.set(name, []);
        this.listeners.get(name).push(callback);
    }
    removeEventListener(name, callback) {
        this.listeners.set(name, (this.listeners.get(name) || []).filter(value => value !== callback));
    }
    dispatchEvent(event) {
        event.target ||= this;
        this['on' + event.type]?.(event);
        for(const callback of this.listeners.get(event.type) || [])callback(event);
    }
    append(...children) { for(const child of children){child.parentNode = this; this.children.push(child);} }
    replaceChildren(...children) { for(const child of this.children)child.parentNode = null; this.children = []; this.append(...children); }
    remove() { if(this.parentNode)this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; }
    focus() { this.ownerDocument.activeElement = this; }
    matches(selector) {
        if(selector.startsWith('.'))return this.className.split(/\s+/).includes(selector.slice(1));
        const attribute = selector.match(/^\[([^=]+)="([^"]+)"\](?::not\(\[disabled\]\))?$/);
        if(attribute){
            const value = attribute[1].startsWith('data-') ? this.dataset[attribute[1].slice(5).replace(/-([a-z])/g, (_,c) => c.toUpperCase())] : this.attributes[attribute[1]];
            return value === attribute[2] && (!selector.includes(':not') || !this.disabled);
        }
        return this.tagName === selector.toUpperCase();
    }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest(selector) || null; }
}

function harness(saved = null, fetchImpl = null) {
    const document = {listeners: new Map()};
    document.createElement = tag => new Element(tag, document);
    document.body = document.createElement('body');
    document.addEventListener = Element.prototype.addEventListener.bind(document);
    document.removeEventListener = Element.prototype.removeEventListener.bind(document);
    let storage = saved;
    const messages = [], fetches = [], counts = [], sourceOpens = [];
    const context = vm.createContext({URL, URLSearchParams, console, setTimeout, clearTimeout, document,
        Event: class {constructor(type){this.type = type;}},
        sessionStorage: {getItem: () => storage, setItem: (_, value) => {storage = value;}},
        fetch: async (...args) => {fetches.push(args); if(fetchImpl)return fetchImpl(...args); throw new Error('Unexpected fetch');},
        readModelPrompt: async () => {throw new Error('Unexpected model lookup');}, manageModal() {}
    });
    for(const name of ['prompt_target.js', 'pending_prompts.js']) {
        const source = fs.readFileSync(path.join(web, name), 'utf8').replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
        vm.runInContext(source, context, {filename: name});
    }
    const element = (tag, text, parent, props = {}) => {
        const node = Object.assign(document.createElement(tag), props);
        if(text != null)node.textContent = text;
        parent?.append(node); return node;
    };
    const button = (label, key, callback, parent) => {
        const node = element('button', label, parent); node.dataset.uw = key; node.onclick = callback; return node;
    };
    const target = {text: 'base', direction: 'positive'};
    const writer = context.createTextInserter({read: () => target.text, write: text => {target.text = text;}, validate: () => true, commaSeparated: true});
    const pending = context.createPendingPrompts({element, button, report: message => messages.push(message), onCount: count => counts.push(count),
        openSource: item => sourceOpens.push(item), insertionOptions: () => ({onInsert: writer, targetLabel: 'fixture target', targetDirection: target.direction})});
    const host = element('div', null, document.body);
    const settle = async () => { for(let count = 0; count < 6; count++)await new Promise(resolve => setTimeout(resolve, 0)); };
    const render = async () => {pending.render(host); await settle();};
    const setScope = async direction => {
        const picker = host.querySelector('[aria-label="待用列表方向"]');picker.value = direction;picker.onchange();await settle();
    };
    const apply = async () => {
        const actions = host.querySelector('.uw-use-actions');
        await actions.children.find(node => node.textContent === '应用到目标' || node.textContent === '确认替换' || node.textContent === '预览替换').onclick();
        await settle();
    };
    return {pending, host, target, writer, context, messages, fetches, counts, sourceOpens, render, setScope, apply, settle, storage: () => storage};
}

const resource = overrides => ({provider: 'browser', id, source_url: sourceUrl, usage: 'positive', text: ' original, text\n', ...overrides});

async function main() {
    const h = harness();
    h.pending.add(resource());
    check(h.pending.items[0].text === ' original, text\n' && h.pending.items[0].sourceText === ' original, text\n', 'Received body remains byte-for-byte text, including surrounding whitespace');
    h.pending.add(resource({id: id.toUpperCase()}));
    check(h.pending.items.length === 1, 'UUID casing cannot create duplicate received items');
    h.pending.add(resource({id: nextId}));
    check(h.pending.items.length === 2, 'A new UUID is a separate receipt even when the text is identical');
    assert.throws(() => h.pending.add(resource({text: 'changed receipt'})), /UUID/); checks++;
    const sourceCopy = h.pending.items[0];sourceCopy.sourceText = 'outside mutation';
    check(h.pending.items[0].sourceText === ' original, text\n', 'Returned item snapshots cannot mutate the received body');

    const invalid = [
        {id: 'not-a-uuid'}, {id: '11111111-1111-4111-1111-111111111111'},
        {source_url: 'http://example.org/posts/12'}, {source_url: 'https://user:example@example.org/posts/12'},
        {source_url: sourceUrl + '?token=fixture'}, {source_url: sourceUrl + '#fragment'},
        {source_url: 'https://127.0.0.1/posts/12'}, {source_url: 'https://localhost/posts/12'},
        {source_url: 'https://[::1]/posts/12'}, {source_url: 'https://example.local/posts/12'},
        {source_url: 'https://example.org:8443/posts/12'}, {source_url: 'https://EXAMPLE.org/posts/12'},
        {source_url: 'https://example.org/a/../posts/12'}, {source_url: 'https://example.org/posts/12\n'},
        {source_url: 'https://example.org//posts/12'}, {source_url: 'https://example.org/posts/%20secret'},
        {source_url: 'https://example.org/posts/%zz'}, {source_url: 'https://example.org/' + 'p'.repeat(2048)},
        {usage: 'target'}, {usage: 'unknown'}, {text: ''}, {text: ' \n'}, {text: 12},
        {text: 'p'.repeat(65537)}, {usage: 'negative', text: 'n'.repeat(16385)},
        {sourceText: 'different original'}, {sectionKey: 'negative'},
        {sections: {}}, {sections: {unknown: 'text'}}, {sections: {positive: 12}}, {usage: 'unknown', sections: {positive: 'text'}},
        {sections: {positive: 'valid', negative: ' '.repeat(16385)}}
    ];
    for(const override of invalid){const count = h.pending.items.length;assert.throws(() => h.pending.add(resource(override)));check(h.pending.items.length === count, 'Invalid resource is rejected without changing the draft');}
    const limits = harness();
    limits.pending.add(resource({text: '😀'.repeat(65536)}));
    limits.pending.add(resource({usage: 'negative', text: 'n'.repeat(16384)}));
    check(limits.pending.items.length === 2, 'Directional limits match backend Unicode code-point lengths');
    assert.throws(() => limits.pending.add(resource({id: nextId, text: '😀'.repeat(65537)})), /长度/); checks++;
    const atomic = harness();
    assert.throws(() => atomic.pending.add(resource({sections: {positive: 'valid', negative: 'n'.repeat(16385)}})), /长度/);
    check(atomic.pending.items.length === 0, 'Both sections validate before either is added');

    const draft = harness();
    draft.pending.add(resource({sections: {positive: '  positive original  ', negative: 'negative original'}}));
    check(draft.pending.items.length === 2 && draft.pending.items.map(item => item.sectionKey).join(',') === 'positive,negative', 'Directions from one receipt become independent stable items');
    draft.pending.add(resource({sections: {positive: '  positive original  ', negative: 'negative original'}}));
    check(draft.pending.items.length === 2, 'Both directions deduplicate independently');
    await draft.render();
    check(draft.host.querySelectorAll('[data-uw="pending-source"]').length === 0 && draft.sourceOpens.length === 0, 'Rendering external provenance cannot open or load a website through another provider');
    check(draft.host.querySelectorAll('summary').every(node => node.textContent === '接收到的原始正文'), 'The original body is available for comparison');
    check(draft.host.querySelectorAll('small').some(node => node.textContent === '来源：网页临时提示词'), 'The transient source has its own user-visible label');
    const edited = draft.host.querySelectorAll('[aria-label="仅本次使用的正文"]')[0];
    edited.value = 'positive edited';edited.oninput();await draft.settle();
    draft.pending.add(resource({sections: {positive: '  positive original  ', negative: 'negative original'}}));
    check(draft.pending.items[0].modified && draft.pending.items[0].text === 'positive edited' && draft.pending.items[0].sourceText === '  positive original  ', 'Duplicate receipts preserve edits and immutable source text');
    await draft.apply();
    check(draft.target.text === 'base' && draft.messages.some(message => message.includes('正负向')), 'Mixed directions cannot be applied to a positive target');
    await draft.setScope('positive');await draft.apply();
    check(draft.target.text === 'base, positive edited', 'Positive application uses the edited draft body');
    check(draft.writer.undoLast() && draft.target.text === 'base', 'Undo remains owned by the original shared writer');
    await draft.setScope('negative');await draft.apply();
    check(draft.target.text === 'base', 'A negative section cannot be applied to a positive target');
    draft.target.direction = 'negative';draft.pending.refreshTarget();await draft.settle();await draft.apply();
    check(draft.target.text === 'base, negative original', 'Negative application uses only its own section');
    check(draft.writer.undoLast() && draft.target.text === 'base', 'Negative writes retain shared-writer undo');
    check(draft.fetches.length === 0, 'Browser preparation and applied records make no network or library requests');

    const restored = harness(draft.storage());
    check(restored.pending.items.length === 2 && restored.pending.items[0].text === 'positive edited' && restored.pending.items[0].modified && restored.pending.items[0].sourceText === '  positive original  ', 'Session reload retains edited and original text independently');
    await restored.render();await restored.setScope('positive');await restored.apply();
    check(restored.target.text === 'base, positive edited' && restored.fetches.length === 0, 'Restored edits apply without rereading websites or providers');
    const missingFlag = JSON.parse(draft.storage());missingFlag[0].modified = false;
    check(harness(JSON.stringify(missingFlag)).pending.items[0].modified, 'Reload infers an edited draft from its distinct body even if the modified flag was absent');
    const restoredText = restored.host.querySelectorAll('[aria-label="仅本次使用的正文"]')[0];
    restoredText.value = '';restoredText.oninput();await restored.settle();
    const emptyReload = harness(restored.storage());
    check(emptyReload.pending.items[0].text === '' && emptyReload.pending.items[0].sourceText === '  positive original  ', 'An empty unfinished edit survives reload without replacing the original');
    await emptyReload.render();await emptyReload.setScope('positive');await emptyReload.apply();
    check(emptyReload.target.text === 'base', 'Empty editable text is blocked when applying');
    const oversized = emptyReload.host.querySelectorAll('[aria-label="仅本次使用的正文"]')[0];
    oversized.value = 'p'.repeat(65537);oversized.oninput();await emptyReload.settle();await emptyReload.apply();
    check(emptyReload.target.text === 'base' && emptyReload.messages.some(message => message.includes('长度上限')), 'Oversized edits are blocked when applying');
    const tampered = JSON.parse(draft.storage());tampered[0].source_url += '?token=fixture';delete tampered[1].sourceText;
    const rejected = harness(JSON.stringify(tampered));
    check(rejected.pending.items.length === 0 && rejected.messages.length === 2, 'Malformed restored browser records cannot synthesize an original or bypass URL validation');

    const legacyCalls = [];
    const legacy = harness(null, async (url, options) => {
        legacyCalls.push([url, options]);
        if(url.startsWith('/prompt_selector/library/prompt?'))return {ok: true, json: async () => ({prompt: {prompt: 'library text', _semantic: {manual_search_eligible: true, usage: 'positive'}}})};
        if(url === '/prompt_selector/library/index')return {ok: true, headers: {get: () => 'fixture-revision'}, json: async () => ({})};
        if(url === '/prompt_selector/prompts/mark_used')return {ok: true, headers: {get: () => 'fixture-next'}, json: async () => ({})};
        if(url.startsWith('/prompt_selector/tags/item?'))return {ok: true, json: async () => ({item: {text: 'tag text'}})};
        throw new Error('Unexpected legacy URL: ' + url);
    });
    legacy.pending.add({provider: 'library', id: 'fixture-library', text: 'library text', usage: 'positive'});
    await legacy.render();await legacy.apply();
    check(legacy.target.text === 'base, library text' && legacyCalls.some(([url]) => url === '/prompt_selector/prompts/mark_used'), 'Existing library provenance and applied records remain in effect');
    const tag = harness(null, async url => ({ok: true, json: async () => ({item: {text: 'tag text'}})}));
    tag.pending.add({provider: 'tag', id: 'fixture-tag', text: 'tag text'});
    await tag.render();await tag.apply();
    check(tag.target.text === 'base, tag text' && tag.fetches.length === 1 && tag.fetches[0][0].startsWith('/prompt_selector/tags/item?'), 'Existing tag reads remain unchanged');
    const gallery = harness();let galleryReads = 0;
    gallery.pending.add({provider: 'gallery', id: 'fixture-gallery', text: 'gallery text', resolveText: async () => {galleryReads++;return 'gallery text';}});
    await gallery.render();await gallery.apply();
    check(gallery.target.text === 'base, gallery text' && galleryReads === 1 && gallery.fetches.length === 0, 'Existing gallery callbacks remain responsible for reading their own prompt');
    const galleryReload = harness(gallery.storage());await galleryReload.render();await galleryReload.apply();
    check(galleryReload.target.text === 'base' && galleryReload.messages.some(message => message.includes('原图库重新选取')), 'Existing gallery reload still requests its original callback rather than treating stored text as a browser receipt');
    const gelbooru = harness();
    gelbooru.pending.add(resource({source_url: 'https://gelbooru.com/index.php?page=post&s=view&id=123'}));
    check(gelbooru.pending.items.length === 1, 'Gelbooru accepts its exact public canonical post identity query');
    assert.throws(() => gelbooru.pending.add(resource({id: nextId, source_url: 'https://gelbooru.com/index.php?page=post&s=view&id=123&token=fixture'})));checks++;
    console.log(`PASS: ${checks} browser pending checks; receipt validation, immutable originals, edits, reload, direction checks, shared undo, no browser fetch, legacy library/tag behavior.`);
}
module.exports = {harness};
if(require.main === module)main().catch(error => {console.error(error);process.exitCode = 1;});
