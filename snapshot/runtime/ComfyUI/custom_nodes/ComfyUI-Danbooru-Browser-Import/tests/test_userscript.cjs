'use strict';

// Execute the shipped userscript in a small, observable browser fixture.
// Fixture selectors stand for explicit page metadata, never a body-text scrape.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'aki_tags_bridge.user.js'), 'utf8');

class Element {
  constructor(tag = 'div', text = '') {
    this.tagName = tag.toUpperCase(); this._text = text; this.children = [];
    this.attributes = {}; this.dataset = {}; this.style = {}; this.listeners = {};
    this.selectors = new Map(); this.value = ''; this.disabled = false;
    this.className = ''; this.id = ''; this.parentNode = null;
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  get parentElement() { return this.parentNode; }
  set textContent(value) { this._text = String(value); this.children = []; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); this.parentNode = null; }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'id') this.id = String(value); }
  getAttribute(name) { return name === 'class' ? this.className : this.attributes[name] ?? null; }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  focus() { this.focused = true; }
  contains(child) { return this === child || this.children.some(item => item.contains(child)); }
  register(selector, elements) { this.selectors.set(selector, Array.isArray(elements) ? elements : [elements]); return this; }
  querySelectorAll(selector) {
    if (selector === '*') throw new Error('Unbounded DOM scan');
    if (this.selectors.has(selector)) return this.selectors.get(selector);
    const found = [];
    const matches = element => selector.split(',').some(part => {
      const item = part.trim();
      if (item.startsWith('#')) return element.id === item.slice(1);
      if (/^[a-z]+$/i.test(item)) return element.tagName.toLowerCase() === item.toLowerCase();
      const attribute = item.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/);
      if (attribute) return element.getAttribute(attribute[1]) != null && (attribute[2] == null || element.getAttribute(attribute[1]) === attribute[2]);
      return false;
    });
    const visit = element => { for (const child of element.children) { if (matches(child)) found.push(child); visit(child); } };
    visit(this); return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  async trigger(type, detail = {}) {
    const event = {target: this, shiftKey: false, preventDefault() {}, stopPropagation() {}, ...detail};
    for (const handler of this.listeners[type] || []) await handler(event);
    if (typeof this['on' + type] === 'function') await this['on' + type](event);
  }
}

function browser({url = 'https://danbooru.donmai.us/posts/123?tags=private#fragment', selection = '', values = {}, readyState = 'complete', probeCache = false} = {}) {
  const body = new Element('body');
  Object.defineProperty(body, 'innerText', {get() { throw new Error('Whole-page text scrape'); }});
  const document = new Element('document'); document.body = body; document.readyState = readyState;
  document.appendChild(body); document.createElement = tag => new Element(tag);
  document.getElementById = id => document.querySelector('#' + id);
  Object.defineProperty(document, 'scripts', {get() { throw new Error('Arbitrary script traversal'); }});
  const requests = [], menus = new Map(), logs = [], timerCalls = [], prompts = [];
  const fetchCalls = [], fetchReplies = [], fetchPromises = [], xhrCalls = [];
  let cloneReads = 0;
  class XHR {
    constructor() { this.listeners = {}; this.status = 200; this.responseType = ''; }
    open(...args) { xhrCalls.push(['open', ...args]); return 'open-result'; }
    send(...args) { xhrCalls.push(['send', ...args]); return 'send-result'; }
    addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
    finish(value) { this.responseText = JSON.stringify(value); this.response = value; for (const callback of this.listeners.load || []) callback(); }
  }
  const context = {
    document, location: new URL(url), URL, Date, JSON, Set, Map, Object, Array, String, Number,
    console: Object.fromEntries(['log', 'warn', 'error'].map(key => [key, (...args) => logs.push(args)])),
    getSelection: () => ({toString: () => selection}),
    fetch: function (...args) {
      fetchCalls.push({args, receiver: this});
      const value = fetchReplies.shift() || {};
      const response = {ok: true, headers: {get: () => null}, clone() { cloneReads++; return {text: async () => typeof value === 'string' ? value : JSON.stringify(value)}; }};
      const pending = Promise.resolve(response); fetchPromises.push(pending); return pending;
    },
    XMLHttpRequest: XHR,
    GM_getValue: (key, fallback) => Object.hasOwn(values, key) ? values[key] : fallback,
    GM_setValue: (key, value) => { values[key] = value; },
    GM_registerMenuCommand: (title, action) => { menus.set(title, action); },
    GM_xmlhttpRequest: options => { requests.push(options); return {abort() {}}; },
    prompt: () => prompts.shift() ?? null,
    alert() { throw new Error('Blocking alert'); },
    setTimeout: (...args) => { timerCalls.push(args); return timerCalls.length; },
    clearTimeout() {},
    setInterval() { throw new Error('Idle polling'); },
    MutationObserver: class { constructor() { throw new Error('Idle mutation observer'); } },
  };
  context.window = context; context.globalThis = context;
  return {document, body, context, requests, menus, logs, timerCalls, prompts, values,
    fetchCalls, fetchReplies, fetchPromises, xhrCalls,
    get cloneReads() { return cloneReads; },
    run() { vm.runInNewContext(probeCache ? source.replace('const cache = [];', 'const cache = globalThis.__testCache = [];') : source, context, {timeout: 1000}); return this; },
    navigate(url) { context.location = new URL(url); },
    select(value) { selection = value; },
    button() { return document.getElementById('uw-browser-send'); },
    status() { return document.getElementById('uw-browser-status')?.textContent || ''; },
    editor() { return document.getElementById('uw-browser-editor'); },
    respond(status = 200, data = {ok: true, import_id: 'fixture-import-1'}) { requests.at(-1).onload({status, responseText: JSON.stringify(data)}); },
  };
}

function danbooruTags(fixture, records) {
  const list = new Element('ul'); list.id = 'tag-list';
  const rows = records.map(([name, category]) => {
    const row = new Element('li'); row.dataset.tagName = name;
    row.setAttribute('data-tag-name', name); row.dataset.category = String(category);
    row.setAttribute('data-category', String(category)); row.className = 'tag-type-' + category;
    const anchor = new Element('a', name); anchor.dataset.tagName = name;
    anchor.setAttribute('data-tag-name', name); anchor.setAttribute('href', '/posts?tags=' + encodeURIComponent(name));
    row.appendChild(anchor); row.register('a.search-tag, a[data-tag-name], a[href*="/posts?tags="]', anchor);
    return row;
  });
  rows.forEach(row => list.appendChild(row));
  list.register('li', rows); list.register('li[data-tag-name]', rows);
  fixture.document.register('#tag-list a, ul.tag-list a, #tag-sidebar a, a.search-tag, a.tag-link, a.tag-name, [class*="tag-type"] a[href*="tags="], [class*="category-"] a[href*="tags="], [data-tag-category] a[href*="tags="]', rows.map(row => row.children[0]));
  fixture.body.appendChild(list); return fixture;
}

function civitaiData(fixture, data) {
  const script = new Element('script', typeof data === 'string' ? data : JSON.stringify(data));
  script.id = '__NEXT_DATA__'; fixture.body.appendChild(script); return fixture;
}

function booruLinks(fixture, records) {
  const anchors = records.map(([href, name, classes]) => {
    const row = new Element('li'); row.className = classes;
    const anchor = new Element('a', name); anchor.setAttribute('href', href); row.appendChild(anchor); fixture.body.appendChild(row);
    return anchor;
  });
  fixture.document.register('#tag-list a, ul.tag-list a, #tag-sidebar a, a.search-tag, a.tag-link, a.tag-name, [class*="tag-type"] a[href*="tags="], [class*="category-"] a[href*="tags="], [data-tag-category] a[href*="tags="]', anchors);
  return fixture;
}
function scoped(fixture, id, kind, positive = '', negative = '', tags = []) {
  const attribute = kind === 'pixai' ? 'data-artwork-id' : 'data-image-id';
  const root = new Element('article'); root.setAttribute(attribute, id);
  if (positive) root.register('[data-prompt], [data-testid="prompt"]', new Element('pre', positive));
  if (negative) root.register('[data-negative-prompt], [data-testid="negative-prompt"]', new Element('pre', negative));
  root.register('a[href*="images?tags="]', tags.map(name => new Element('a', name)));
  fixture.document.register('[' + attribute + '="' + id + '"]', root); fixture.body.appendChild(root); return root;
}
const flush = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
const payload = fixture => JSON.parse(fixture.requests.at(-1).data);
const trpc = value => ({result: {data: {json: value}}});
const imageUrl = (id, procedure = 'image.get', extra = {}) => '/api/trpc/' + procedure + '?input=' + encodeURIComponent(JSON.stringify({json: {id, ...extra}}));
async function capture(fixture, url, response, options) {
  fixture.fetchReplies.push(response); const returned = fixture.context.fetch.call(fixture.context, url, options);
  assert.strictEqual(returned, fixture.fetchPromises.at(-1), 'original fetch promise is preserved');
  await returned; await flush(); return returned;
}

const tests = [];
const test = (name, action) => tests.push({name, action});

test('metadata preserves all five site families, original identity, and local grants', () => {
  assert.match(source, /@name\s+Aki D\/C\/PixAI\/Yande\/Gelbooru Tags Bridge/);
  assert.match(source, /@namespace\s+aki-tags-bridge/); assert.match(source, /@version\s+2\.9/);
  for (const domain of ['*.donmai.us', 'civitai.com', '*.civitai.com', 'civitai.red', '*.civitai.red', 'pixai.art', '*.pixai.art', 'yande.re', '*.yande.re', 'gelbooru.com', '*.gelbooru.com']) assert.ok(source.includes('https://' + domain + '/*'), domain);
  assert.ok(!source.includes('@connect      *'));
});
test('Danbooru exports artists first, cleans counts, deduplicates, and excludes meta', async () => {
  const fixture = danbooruTags(browser(), [['blue_hair', 0], ['#alice (21)', 4], ['series_name', 3], ['artist_name', 1], ['highres', 5], ['BLUE_HAIR', 0], ['edit', 0]]).run();
  await fixture.button().trigger('click');
  assert.equal(payload(fixture).positive, 'artist_name, series_name, alice, blue_hair');
  assert.equal(payload(fixture).source_url, 'https://danbooru.donmai.us/posts/123');
  assert.deepEqual(Object.keys(payload(fixture)).sort(), ['image_url', 'negative', 'positive', 'post_id', 'source_url', 'title']);
  fixture.respond(); assert.equal(fixture.status(), '服务已保存；工作台待接纳。');
});
test('yande.re category classes and current ID retain original tag behavior', async () => {
  const fixture = booruLinks(browser({url: 'https://yande.re/post/show/44?secret=hidden'}), [
    ['/post?tags=blue_hair', 'blue hair 120k', 'tag-type-general'], ['/post?tags=artist_a', 'artist a', 'tag-type-artist'],
    ['/post?tags=char_a', 'char a', 'tag-type-character'], ['/post?tags=highres', 'highres', 'tag-type-meta'],
    ['/post/show/43', 'previous', 'tag-type-general'], ['/wiki?tags=bad', 'bad', 'tag-type-general']]).run();
  await fixture.button().trigger('click');
  assert.equal(payload(fixture).positive, 'artist_a, char_a, blue_hair'); assert.equal(payload(fixture).post_id, '44');
  assert.equal(payload(fixture).source_url, 'https://yande.re/post/show/44');
});
test('Gelbooru retains only canonical post parameters and rejects sidebar actions', async () => {
  const fixture = booruLinks(browser({url: 'https://gelbooru.com/index.php?page=post&s=view&id=888&tags=secret#private'}), [
    ['/index.php?page=post&s=list&tags=artist_b', 'artist b', 'tag-type-artist'],
    ['/index.php?page=post&s=list&tags=long_hair', 'long hair 42', 'tag-type-general'],
    ['/index.php?page=post&s=view&id=888#', 'edit', 'tag-type-general'],
    ['/index.php?page=post&s=list&tags=source', 'source', 'tag-type-general'],
    ['/index.php?page=wiki&s=list&tags=bad', 'bad', 'tag-type-general'],
    ['/index.php?page=post&s=list&tags=highres', 'highres', 'tag-type-meta']]).run();
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, 'artist_b, long_hair');
  assert.equal(payload(fixture).source_url, 'https://gelbooru.com/index.php?page=post&s=view&id=888');
});
test('original numeric booru category classes preserve artist order and exclude numeric meta', async () => {
  for (const [url, href] of [
    ['https://danbooru.donmai.us/posts/1', '/posts?tags='],
    ['https://yande.re/post/show/1', '/post?tags='],
    ['https://gelbooru.com/index.php?page=post&s=view&id=1', '/index.php?page=post&s=list&tags='],
  ]) {
    const fixture = booruLinks(browser({url}), [
      [href + 'general', 'general', 'tag-type-0'], [href + 'numeric_artist', 'numeric_artist', 'tag-type-1'],
      [href + 'character', 'character', 'tag-type-4'], [href + 'numeric_character', 'numeric_character', 'tag-category-4'],
      [href + 'copyright', 'copyright', 'tag-type-3'], [href + 'numeric_copyright', 'numeric_copyright', 'tag-category-3'],
      [href + 'meta_one', 'meta_one', 'tag-type-5'], [href + 'meta_two', 'meta_two', 'tag-category-5'],
      [href + 'numeric_general', 'numeric_general', 'tag-type-2'],
    ]).run();
    await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, 'numeric_artist, numeric_copyright, numeric_character, numeric_general');
  }
});
test('each click freshly extracts the current booru page', async () => {
  const fixture = danbooruTags(browser(), [['old_tag', 0]]).run();
  await fixture.button().trigger('click'); fixture.respond(); fixture.navigate('https://danbooru.donmai.us/posts/999');
  danbooruTags(fixture, [['new_tag', 0]]); await fixture.button().trigger('click');
  assert.equal(payload(fixture).post_id, '999'); assert.equal(payload(fixture).positive, 'new_tag');
});
test('Civitai direct known inline image preserves natural text and weights verbatim', async () => {
  const positive = '  A girl, (blue hair:1.25),\n<lora:alice:0.7> — warm light.  ';
  const negative = 'bad hands, (extra fingers:1.4)\nblur';
  const fixture = civitaiData(browser({url: 'https://civitai.red/images/55?private=hidden#x'}), {props: {pageProps: {image: {id: 55, meta: {prompt: positive, negativePrompt: negative}, url: 'https://image.civitai.com/public.jpg?token=private#x', resources: [{apiKey: 'private'}]}}}}).run();
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, positive); assert.equal(payload(fixture).negative, negative);
  assert.equal(payload(fixture).source_url, 'https://civitai.red/images/55'); assert.equal(payload(fixture).image_url, 'https://image.civitai.com/public.jpg');
  assert.ok(!fixture.requests[0].data.includes('private'));
});
test('Civitai known image.get hydration query binds its exact input and image IDs', async () => {
  const fixture = civitaiData(browser({url: 'https://civitai.com/images/56'}), {props: {pageProps: {trpcState: {json: {queries: [
    {queryKey: [['image', 'get'], {input: {id: 999}}], state: {data: {id: 999, meta: {prompt: 'wrong'}}}},
    {queryKey: [['image', 'get'], {input: {id: 56}}], state: {data: {id: 56, meta: {prompt: '(correct:1.7)'}}}}
  ]}}}}}).run();
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, '(correct:1.7)');
});
test('SPA current image never reuses previous inline/cache image or arbitrary nested scripts', async () => {
  const fixture = civitaiData(browser({url: 'https://civitai.com/images/55'}), {props: {pageProps: {image: {id: 55, meta: {prompt: 'old prompt'}}, random: {id: 56, meta: {prompt: 'wrong nested guess'}}}}}).run();
  await capture(fixture, imageUrl(55), trpc({id: 55, meta: {prompt: 'cached old prompt'}}));
  fixture.navigate('https://civitai.com/images/56'); await fixture.button().trigger('click');
  assert.equal(fixture.requests.length, 0); assert.ok(fixture.editor()); assert.equal(fixture.document.getElementById('uw-browser-positive').value, '');
});
test('Civitai captures only exact whitelisted tRPC endpoints and matching response ID', async () => {
  const fixture = browser({url: 'https://civitai.com/images/10'}).run();
  await capture(fixture, imageUrl(10), trpc({id: 999, meta: {prompt: 'wrong id'}}));
  const before = fixture.cloneReads;
  await capture(fixture, imageUrl(10, 'image.getAll'), trpc({id: 10, meta: {prompt: 'broad endpoint'}}));
  await capture(fixture, 'https://evil.example/api/trpc/image.get?input=' + encodeURIComponent('{"json":{"id":10}}'), trpc({id: 10, meta: {prompt: 'external'}}));
  await capture(fixture, imageUrl(10, 'image.get,image.getAll'), trpc({id: 10, meta: {prompt: 'batch'}}));
  assert.equal(fixture.cloneReads, before);
  await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 0);
  await capture(fixture, imageUrl(10, 'image.getMetadata'), trpc({id: 10, meta: {prompt: '(correct:1.4)'}}));
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, '(correct:1.4)');
});
test('Civitai original exact tag.getVotableTags fallback filters resource/review/downvote data', async () => {
  const fixture = browser({url: 'https://civitai.com/images/11'}).run();
  await capture(fixture, imageUrl(11, 'tag.getVotableTags', {type: 'image', authed: true}), trpc([
    {name: 'blue hair', score: 5, type: 'UserGenerated'}, {name: 'review', score: 5, needsReview: true},
    {name: 'resource', score: 2, modelId: 1}, {name: 'downvote', score: -1}, {name: 'edit', score: 10},
    {name: 'Blue Hair', upVotes: 1}, {name: 'unshaped'}, {name: 'portrait', upVotes: 2},
  ]));
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, 'blue hair, portrait');
  fixture.respond(); fixture.navigate('https://civitai.com/images/12'); await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 1);
});
test('Civitai scoped visible tags precede exact network tags when no generation prompt', async () => {
  const fixture = browser({url: 'https://civitai.com/images/15'}); scoped(fixture, '15', 'civitai', '', '', ['visible tag', 'Prompt', '123 votes']); fixture.run();
  await capture(fixture, imageUrl(15, 'tag.getVotableTags', {type: 'image'}), trpc({tags: [{name: 'network tag', score: 1}]}));
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, 'visible tag');
});
test('network tags cannot replace an existing exact generation prompt or negative prompt', async () => {
  const fixture = browser({url: 'https://civitai.com/images/15'}).run();
  await capture(fixture, imageUrl(15), trpc({id: 15, meta: {prompt: 'natural, (weight:1.9)', negativePrompt: 'negative'}}));
  await capture(fixture, imageUrl(15, 'tag.getVotableTags', {type: 'image'}), trpc([{name: 'network tag', score: 1}]));
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, 'natural, (weight:1.9)'); assert.equal(payload(fixture).negative, 'negative');
});
test('PixAI original data.artwork structure keeps exact current artwork prompt/negative', async () => {
  const fixture = browser({url: 'https://pixai.art/en/artwork/1234?private=hidden#x'}).run();
  await capture(fixture, 'https://api.pixai.art/getArtworkWithTaskDetail?private=hidden', {data: {artwork: {id: '1234', prompts: '(alice:1.2), natural text.\nline two', negativePrompts: 'bad hands', media: {publicUrl: 'https://images-ng.pixai.art/image.jpg?private=hidden'}, private: 'secret', resources: ['resource']}}});
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, '(alice:1.2), natural text.\nline two'); assert.equal(payload(fixture).negative, 'bad hands');
  assert.equal(payload(fixture).source_url, 'https://pixai.art/artwork/1234');
  assert.equal(payload(fixture).image_url, 'https://images-ng.pixai.art/image.jpg'); assert.ok(!fixture.requests[0].data.includes('private'));
});
test('PixAI exact GraphQL operation captures extra.naturalPrompts, never other GraphQL', async () => {
  const fixture = browser({url: 'https://pixai.art/artwork/42'}).run();
  const art = {data: {artwork: {id: '42', extra: {naturalPrompts: 'A warm portrait, (eyes:1.4)', negativePrompts: 'blur'}}}};
  await capture(fixture, 'https://api.pixai.art/graphql', art, {method: 'POST', body: JSON.stringify({operationName: 'getArtworkList', variables: {id: '42'}})});
  assert.equal(fixture.cloneReads, 0);
  await capture(fixture, 'https://api.pixai.art/graphql', art, {method: 'POST', body: JSON.stringify({operationName: 'getArtworkWithTaskDetail', variables: {artworkId: '42'}})});
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, 'A warm portrait, (eyes:1.4)'); assert.equal(payload(fixture).negative, 'blur');
});
test('PixAI SPA navigation rejects stale prior artwork and wrong exact GraphQL response IDs', async () => {
  const fixture = browser({url: 'https://pixai.art/artwork/42'}).run();
  await capture(fixture, 'https://api.pixai.art/getArtworkWithTaskDetail', {data: {artwork: {id: '42', prompts: 'old'}}});
  fixture.navigate('https://pixai.art/artwork/43');
  await capture(fixture, 'https://api.pixai.art/graphql', {data: {artwork: {id: '42', prompts: 'wrong'}}}, {body: '{"operationName":"getArtworkWithTaskDetail","variables":{"id":"43"}}'});
  await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 0); assert.equal(fixture.document.getElementById('uw-browser-positive').value, '');
});
test('PixAI overview needs a unique explicitly current visible preview ID', async () => {
  const fixture = browser({url: 'https://pixai.art/en/'}).run();
  await capture(fixture, 'https://api.pixai.art/getArtworkWithTaskDetail', {data: {artwork: {id: '44', prompts: 'current'}}});
  await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 0); assert.equal(fixture.status(), '请打开作品详情页。');
  const preview = new Element('div'); preview.setAttribute('data-artwork-id', '44');
  const selector = '[role="dialog"][data-artwork-id], [data-artwork-id][data-current="true"], [data-artwork-id][aria-current="true"]';
  fixture.document.register(selector, [preview]); await fixture.button().trigger('click');
  assert.equal(payload(fixture).positive, 'current'); assert.equal(payload(fixture).source_url, 'https://pixai.art/artwork/44');
  fixture.respond(); const other = new Element('div'); other.setAttribute('data-artwork-id', '45');
  fixture.document.register(selector, [preview, other]); await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 1);
});
test('normalized cache is bounded to 8 and contains no raw JSON, credentials, resources, or request URLs', async () => {
  const fixture = browser({url: 'https://civitai.com/images/1', probeCache: true}).run();
  for (let id = 1; id <= 12; id++) await capture(fixture, imageUrl(id), trpc({id, meta: {prompt: 'prompt ' + id, negativePrompt: 'neg'}, apiKey: 'SECRET', raw: {token: 'SECRET'}, resources: [{modelId: 1}], url: 'https://image.civitai.com/public.jpg?token=SECRET'}));
  const stored = JSON.parse(JSON.stringify(fixture.context.__testCache));
  assert.equal(stored.length, 8); assert.equal(stored[0].id, '12'); assert.equal(stored.at(-1).id, '5');
  for (const item of stored) assert.deepEqual(Object.keys(item).sort(), ['id', 'image_url', 'negative', 'positive', 'site', 'title']);
  assert.ok(!JSON.stringify(stored).includes('SECRET')); assert.ok(!JSON.stringify(stored).includes('/api/trpc'));
  await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 0);
  fixture.navigate('https://civitai.com/images/12'); await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, 'prompt 12');
});
test('XHR narrow capture preserves original open/send return values and forwards their arguments', async () => {
  const fixture = browser({url: 'https://civitai.com/images/20'}).run();
  const xhr = new fixture.context.XMLHttpRequest();
  assert.equal(xhr.open('GET', imageUrl(20), true, 'user', 'password'), 'open-result');
  assert.equal(xhr.send(null), 'send-result'); xhr.finish(trpc({id: 20, meta: {prompt: 'xhr prompt'}}));
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, 'xhr prompt');
  assert.deepEqual(fixture.xhrCalls[0].slice(3), [true, 'user', 'password']); assert.deepEqual(fixture.xhrCalls[1], ['send', null]);
  fixture.respond(); const unrelated = new fixture.context.XMLHttpRequest(); unrelated.open('GET', imageUrl(20, 'account.get')); unrelated.send(); assert.equal((unrelated.listeners.load || []).length, 0);
});
test('missing site data opens editable blank prompts; error or instructions are never sent', async () => {
  const fixture = browser({url: 'https://pixai.art/artwork/99'}).run();
  await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 0); assert.ok(fixture.editor());
  assert.equal(fixture.document.getElementById('uw-browser-positive').value, ''); assert.equal(fixture.status(), '请选择提示词或手工填写。');
});
test('selection fallback and explicit positive/negative edits send verbatim', async () => {
  const fixture = browser({url: 'https://pixai.art/artwork/99', selection: '  selected (weight:1.7)\ntext  '}).run();
  await fixture.button().trigger('click', {shiftKey: true}); assert.equal(fixture.requests.length, 0);
  assert.equal(fixture.document.getElementById('uw-browser-positive').value, '  selected (weight:1.7)\ntext  ');
  fixture.document.getElementById('uw-browser-positive').value = '(manual:1.25),\nwith commas';
  fixture.document.getElementById('uw-browser-negative').value = '(bad fingers:1.6)';
  await fixture.document.getElementById('uw-browser-editor-send').trigger('click');
  assert.equal(payload(fixture).positive, '(manual:1.25),\nwith commas'); assert.equal(payload(fixture).negative, '(bad fingers:1.6)');
});
test('preview editor refuses a draft after SPA navigation', async () => {
  const fixture = browser({url: 'https://civitai.com/images/10', selection: 'manual prompt'}).run();
  await fixture.button().trigger('click', {shiftKey: true}); fixture.navigate('https://civitai.com/images/11');
  await fixture.document.getElementById('uw-browser-editor-send').trigger('click'); assert.equal(fixture.requests.length, 0); assert.equal(fixture.status(), '页面已切换，请重新打开编辑。');
});
test('GM menu opens fresh editable prompts and local endpoint configuration rejects unsafe targets', async () => {
  const fixture = browser({selection: 'selection'}).run();
  fixture.menus.get('编辑并发送当前页')(); assert.ok(fixture.editor());
  const configure = fixture.menus.get('设置本地工作台地址');
  for (const value of ['https://evil.example/unified-workbench/browser-import', 'http://127.0.0.1:8188/unified-workbench/browser-import?token=secret', 'http://user:example@localhost:8188/unified-workbench/browser-import', 'http://localhost:8188/other', 'http://localhost.evil:8188/unified-workbench/browser-import', 'http://127.0.0.1:99999/unified-workbench/browser-import', 'http://localhost:0/unified-workbench/browser-import', 'http://localhost:/unified-workbench/browser-import', 'http://localhost:-1/unified-workbench/browser-import']) {
    fixture.prompts.push(value); configure(); assert.equal(Object.keys(fixture.values).length, 0, value);
  }
  fixture.prompts.push('http://localhost:8189/unified-workbench/browser-import'); configure();
  await fixture.button().trigger('click'); assert.equal(fixture.requests[0].url, 'http://localhost:8189/unified-workbench/browser-import');
});
test('API text limits use codepoints, preserve accepted long prompts, and trim title to 256 codepoints', async () => {
  const positive = 'p'.repeat(65536), negative = '😀'.repeat(16384), title = '😀'.repeat(300);
  const fixture = civitaiData(browser({url: 'https://civitai.com/images/55'}), {props: {pageProps: {image: {id: 55, title, meta: {prompt: positive, negativePrompt: negative}}}}}).run();
  await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, positive); assert.equal(payload(fixture).negative, negative);
  assert.equal(payload(fixture).title, '😀'.repeat(256));
});
test('oversized negative is refused rather than silently dropped, from extracted data and manual edits', async () => {
  const negative = 'n'.repeat(16385);
  const fixture = civitaiData(browser({url: 'https://civitai.com/images/55'}), {props: {pageProps: {image: {id: 55, meta: {prompt: 'correct prompt', negativePrompt: negative}}}}}).run();
  await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 0); assert.equal(fixture.status(), '提示词过长，请缩短后发送。');
  await fixture.button().trigger('click', {shiftKey: true}); assert.equal(fixture.document.getElementById('uw-browser-negative').value, negative);
  fixture.document.getElementById('uw-browser-negative').value = '😀'.repeat(16385);
  await fixture.document.getElementById('uw-browser-editor-send').trigger('click'); assert.equal(fixture.requests.length, 0); assert.equal(fixture.status(), '提示词过长，请缩短后发送。');
  fixture.document.getElementById('uw-browser-negative').value = 'shortened (bad hands:1.3)';
  await fixture.document.getElementById('uw-browser-editor-send').trigger('click'); assert.equal(payload(fixture).negative, 'shortened (bad hands:1.3)');
});
test('oversized positive is refused at 65537 codepoints', async () => {
  const fixture = browser({selection: 'p'.repeat(65537)}).run();
  await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 0); assert.equal(fixture.status(), '提示词过长，请缩短后发送。');
});
test('unsafe optional image becomes empty while a valid prompt still sends', async () => {
  for (const image of ['http://image.civitai.com/photo.jpg', 'https://img.pixai.art/photo.jpg', 'https://evil.example/photo.jpg', 'https://user:example@image.civitai.com/photo.jpg', 'https://image.civitai.com:8188/photo.jpg', 'https://image.civitai.com/', 'https://image.civitai.com/api/private', 'https://image.civitai.com/login', 'https://image.civitai.com/%2e%2e%2fprivate', 'https://image.civitai.com/a%20b.jpg']) {
    const fixture = civitaiData(browser({url: 'https://civitai.com/images/55'}), {props: {pageProps: {image: {id: 55, url: image, meta: {prompt: '(correct:1.4)'}}}}}).run();
    await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, '(correct:1.4)'); assert.equal(payload(fixture).image_url, '', image);
  }
});
test('only API-approved optional image hosts keep HTTPS canonical links', async () => {
  for (const host of ['cdn.donmai.us', 'image.civitai.com', 'images-ng.pixai.art', 'imagedelivery.net', 'files.yande.re', 'assets.yande.re', 'img3.gelbooru.com']) {
    const fixture = civitaiData(browser({url: 'https://civitai.com/images/55'}), {props: {pageProps: {image: {id: 55, url: 'https://' + host + '/public.jpg?private=secret#x', meta: {prompt: 'correct'}}}}}).run();
    await fixture.button().trigger('click'); assert.equal(payload(fixture).image_url, 'https://' + host + '/public.jpg');
  }
});
test('homepage selection or manual editor request asks for artwork details without sending', async () => {
  for (const url of ['https://danbooru.donmai.us/', 'https://civitai.com/', 'https://pixai.art/', 'https://yande.re/', 'https://gelbooru.com/']) {
    const fixture = browser({url, selection: 'manual (prompt:1.4)'}).run();
    await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 0); assert.equal(fixture.status(), '请打开作品详情页。');
    await fixture.button().trigger('click', {shiftKey: true}); fixture.menus.get('编辑并发送当前页')();
    assert.equal(fixture.requests.length, 0); assert.equal(fixture.editor(), null); assert.equal(fixture.status(), '请打开作品详情页。');
  }
});
test('send is anonymous, header-minimal, duplicate-locked, and has no fetch fallback', async () => {
  const fixture = browser({selection: '(selected:1.2)'}).run();
  await fixture.button().trigger('click'); await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 1);
  const request = fixture.requests[0]; assert.equal(request.anonymous, true); assert.equal(request.method, 'POST'); assert.equal(request.timeout, 10000);
  assert.deepEqual(JSON.parse(JSON.stringify(request.headers)), {'Content-Type': 'application/json'});
  assert.equal(fixture.fetchCalls.length, 0); fixture.respond(202, {ok: true, delivery: 'stored', realtime_notified: false}); assert.equal(fixture.status(), '服务已保存；工作台待接纳。');
  fixture.context.GM_xmlhttpRequest = undefined; await fixture.button().trigger('click'); assert.equal(fixture.requests.length, 1); assert.equal(fixture.fetchCalls.length, 0); assert.equal(fixture.status(), '脚本管理器请求不可用。');
});
test('failures stay short, release duplicate lock, and never retry or expose response body', async () => {
  const fixture = browser({selection: 'text'}).run();
  await fixture.button().trigger('click'); fixture.respond(409, {ok: false, error: 'SECRET PRIVATE ERROR'});
  assert.equal(fixture.status(), '发送失败，请稍后手工重试。'); assert.equal(fixture.requests.length, 1); assert.equal(fixture.button().disabled, false);
  await fixture.button().trigger('click'); fixture.requests.at(-1).onerror({token: 'SECRET'}); assert.equal(fixture.status(), '无法连接本地服务。');
  await fixture.button().trigger('click'); fixture.requests.at(-1).ontimeout(); assert.equal(fixture.status(), '本地服务响应超时。'); assert.equal(fixture.requests.length, 3); assert.equal(fixture.timerCalls.length, 0);
});
test('idle boot has no polling, observers, logs, external requests, broad scrapes, or global debug API', async () => {
  for (const url of ['https://danbooru.donmai.us/posts/1', 'https://civitai.com/images/1', 'https://pixai.art/artwork/1', 'https://yande.re/post/show/1', 'https://gelbooru.com/index.php?page=post&s=view&id=1']) {
    const fixture = browser({url}).run(); await flush(); assert.ok(fixture.button());
    assert.equal(fixture.requests.length, 0); assert.equal(fixture.fetchCalls.length, 0); assert.equal(fixture.xhrCalls.length, 0); assert.equal(fixture.timerCalls.length, 0); assert.equal(fixture.logs.length, 0);
    assert.equal(fixture.context.__AKI_TAGS_BRIDGE__, undefined); assert.equal(fixture.context.__testCache, undefined);
  }
});
test('document-start installs hooks once and defers only the small UI until DOMContentLoaded', async () => {
  const fixture = browser({url: 'https://pixai.art/artwork/2', readyState: 'loading'}).run(); assert.equal(fixture.button(), null);
  await capture(fixture, '/getArtworkWithTaskDetail', {data: {artwork: {id: '2', prompts: 'captured before DOM'}}});
  await fixture.document.trigger('DOMContentLoaded'); await fixture.button().trigger('click'); assert.equal(payload(fixture).positive, 'captured before DOM');
});

(async () => {
  let passed = 0;
  for (const {name, action} of tests) { await action(); passed++; process.stdout.write('ok ' + passed + ' - ' + name + '\n'); }
  process.stdout.write(passed + ' userscript checks passed\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
