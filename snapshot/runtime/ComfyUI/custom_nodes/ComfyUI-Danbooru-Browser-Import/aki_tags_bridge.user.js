// ==UserScript==
// @name         Aki D/C/PixAI/Yande/Gelbooru Tags Bridge
// @namespace    aki-tags-bridge
// @version      2.9
// @description  Click to send the current public artwork prompt to the local workbench; Shift-click to edit first.
// @match        https://danbooru.donmai.us/*
// @match        https://*.donmai.us/*
// @match        https://civitai.com/*
// @match        https://*.civitai.com/*
// @match        https://civitai.red/*
// @match        https://*.civitai.red/*
// @match        https://pixai.art/*
// @match        https://*.pixai.art/*
// @match        https://yande.re/*
// @match        https://*.yande.re/*
// @match        https://gelbooru.com/*
// @match        https://*.gelbooru.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-start
// ==/UserScript==

(() => {
  'use strict';
  const DEFAULT_ENDPOINT = 'http://127.0.0.1:8188/unified-workbench/browser-import';
  const ENDPOINT_KEY = 'aki-tags-bridge-local-endpoint';
  const MAX_POSITIVE = 65536;
  const MAX_NEGATIVE = 16384;
  const MAX_JSON = 2 * 1024 * 1024;
  const cache = [];
  let busy = false, button, status, editor;
  const str = value => typeof value === 'string' ? value : '';
  // Keep one excess codepoint so oversized data is refused, never sent truncated.
  const text = (value, limit = MAX_POSITIVE) => Array.from(str(value)).slice(0, limit + 1).join('');
  const idOf = value => /^\d{1,30}$/.test(String(value ?? '')) ? String(value) : '';
  const within = (host, domain) => host === domain || host.endsWith('.' + domain);
  const site = within(location.hostname, 'donmai.us') ? 'danbooru'
    : within(location.hostname, 'civitai.com') || within(location.hostname, 'civitai.red') ? 'civitai'
    : within(location.hostname, 'pixai.art') ? 'pixai'
    : within(location.hostname, 'yande.re') ? 'yandere'
    : within(location.hostname, 'gelbooru.com') ? 'gelbooru' : '';
  if (!site) return;

  function publicUrl(value, image = false) {
    try {
      const url = new URL(value, location.href);
      if (url.protocol !== 'https:' || url.port && url.port !== '443' || url.username || url.password) return '';
      if (image) {
        const known = within(url.hostname, 'donmai.us') || within(url.hostname, 'gelbooru.com')
          || ['image.civitai.com', 'images-ng.pixai.art', 'imagedelivery.net', 'files.yande.re', 'assets.yande.re'].includes(url.hostname);
        const path = decodeURIComponent(url.pathname);
        if (!known || path === '/' || path.startsWith('//') || /^\/(?:api\/|login|auth\/|account)/i.test(path)
          || path.split('/').some(part => part === '.' || part === '..') || /[\s\x00-\x1f\\]/.test(path)) return '';
      }
      url.search = ''; url.hash = '';
      return url.href.length <= 2048 ? url.href : '';
    } catch { return ''; }
  }
  function current() {
    const url = new URL(location.href);
    let match;
    if (site === 'civitai') match = url.pathname.match(/^\/images\/(\d+)(?:\/|$)/);
    else if (site === 'pixai') match = url.pathname.match(/\/artwork\/(\d+)(?:\/|$)/);
    else if (site === 'danbooru') match = url.pathname.match(/^\/posts\/(\d+)(?:\/|$)/);
    else if (site === 'yandere') match = url.pathname.match(/^\/post\/show\/(\d+)(?:\/|$)/);
    else if (url.searchParams.get('page') === 'post' && url.searchParams.get('s') === 'view') {
      match = ['', idOf(url.searchParams.get('id'))];
    }
    let id = idOf(match?.[1]);
    if (site === 'pixai' && !id) {
      const previews = Array.from(document.querySelectorAll('[role="dialog"][data-artwork-id], [data-artwork-id][data-current="true"], [data-artwork-id][aria-current="true"]')).slice(0, 8)
        .filter(visible).map(element => idOf(element.getAttribute('data-artwork-id'))).filter(Boolean);
      const unique = Array.from(new Set(previews));
      if (unique.length === 1) id = unique[0];
    }
    let source = publicUrl(url.href);
    if (source && site === 'civitai' && id) source = url.origin + '/images/' + id;
    if (source && site === 'danbooru' && id) source = url.origin + '/posts/' + id;
    if (source && site === 'yandere' && id) source = url.origin + '/post/show/' + id;
    if (source && site === 'pixai' && id) source = url.origin + '/artwork/' + id;
    if (site === 'gelbooru' && id && source) source += '?page=post&s=view&id=' + id;
    return {id, source};
  }
  function json(value) {
    if (typeof value !== 'string' || value.length > MAX_JSON) return null;
    try { return JSON.parse(value); } catch { return null; }
  }
  function normalize(value, kind, expected = '') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const id = idOf(value.id);
    if (!id || (expected && id !== expected)) return null;
    const positive = kind === 'pixai' ? text(value.prompts) || text(value.extra?.naturalPrompts) : text(value.meta?.prompt);
    const negative = kind === 'pixai' ? text(value.negativePrompts, MAX_NEGATIVE) || text(value.extra?.negativePrompts, MAX_NEGATIVE) : text(value.meta?.negativePrompt, MAX_NEGATIVE);
    const media = kind === 'pixai' ? value.media || value.videoMedia : null;
    const first = Array.isArray(media) ? media[0] : media;
    const image = kind === 'pixai' ? first?.publicUrl || first?.url || first?.thumbnailUrl : value.url;
    return {site: kind, id, positive, negative, title: Array.from(str(value.title)).slice(0, 256).join(''), image_url: image ? publicUrl(image, true) : ''};
  }
  function remember(value, tagsOnly = false) {
    if (!value || (!value.positive && !value.negative && !value.tags?.length)) return;
    const old = cache.findIndex(item => item.site === value.site && item.id === value.id);
    if (old >= 0) {
      value = tagsOnly ? {...cache[old], tags: value.tags} : {...value, tags: cache[old].tags || []};
      cache.splice(old, 1);
    }
    cache.unshift(value);
    if (cache.length > 8) cache.length = 8;
  }
  function unwrap(value) { return value?.result?.data?.json ?? value; }
  function detailSpec(raw, body) {
    try {
      const url = new URL(raw, location.href);
      if (site === 'civitai' && (within(url.hostname, 'civitai.com') || within(url.hostname, 'civitai.red'))) {
        // Only one exact image detail procedure; no batched or arbitrary tRPC calls.
        if (!/^\/api\/trpc\/(?:image\.(?:get|getMetadata)|tag\.getVotableTags)$/.test(url.pathname)) return null;
        const input = json(url.searchParams.get('input') || '') || json(body || '');
        const id = idOf(input?.json?.id ?? input?.id);
        const tags = url.pathname.endsWith('/tag.getVotableTags');
        if (tags && (input?.json?.type ?? input?.type) !== 'image') return null;
        return id ? {site, id, tags} : null;
      }
      if (site === 'pixai' && within(url.hostname, 'pixai.art')) {
        if (/\/(?:api\/)?getArtworkWithTaskDetail\/?$/.test(url.pathname)) return {site, id: ''};
        if (url.pathname !== '/graphql' && url.pathname !== '/api/graphql') return null;
        const input = json(body || '');
        if (input?.operationName !== 'getArtworkWithTaskDetail') return null;
        return {site, id: idOf(input.variables?.id ?? input.variables?.artworkId)};
      }
    } catch {}
    return null;
  }
  function xhrSpec(method, raw) {
    if (!/^(GET|POST)$/.test(String(method).toUpperCase())) return null;
    const spec = detailSpec(raw);
    if (spec) return spec;
    try {
      const url = new URL(raw, location.href);
      if (site === 'pixai' && within(url.hostname, 'pixai.art') && ['/graphql', '/api/graphql'].includes(url.pathname)) return {graphql: true};
    } catch {}
    return null;
  }
  function capture(spec, value) {
    if (!spec) return;
    if (spec.tags) {
      const data = unwrap(value);
      const candidates = Array.isArray(data) ? data : data?.tags;
      if (!Array.isArray(candidates)) return;
      const names = [], seen = new Set();
      for (const item of candidates.slice(0, 160)) {
        if (!item || item.needsReview === true || item.modelId || item.modelVersionId || item.model || item.modelName || item.versionName || item.modelVersion) continue;
        if (!['score', 'upVotes', 'downVotes', 'lastUpvote', 'automated', 'concrete', 'needsReview'].some(key => item[key] !== undefined)) continue;
        if (Number.isFinite(Number(item.score)) && Number(item.score) < 0) continue;
        const name = str(item.name).replace(/\s+/g, ' ').trim();
        if (!name || name.length > 120 || navTags.has(name.toLowerCase()) || /^[!?.\d\s]+$/.test(name) || seen.has(name.toLowerCase())) continue;
        names.push(name); seen.add(name.toLowerCase());
        if (names.length === 80) break;
      }
      remember({site: spec.site, id: spec.id, positive: '', negative: '', title: '', image_url: '', tags: names}, true);
      return;
    }
    const detail = spec.site === 'pixai' ? value?.data?.artwork : unwrap(value);
    remember(normalize(detail?.image ?? detail, spec.site, spec.id));
  }
  function hookDetails() {
    if (site !== 'civitai' && site !== 'pixai') return;
    const page = typeof unsafeWindow === 'undefined' ? window : unsafeWindow;
    if (typeof page.fetch === 'function') {
      const original = page.fetch;
      page.fetch = function (...args) {
        const spec = detailSpec(typeof args[0] === 'string' ? args[0] : args[0]?.url, args[1]?.body);
        const pending = original.apply(this, args);
        if (spec) pending.then(response => {
          try {
            if (!response.ok || Number(response.headers?.get('content-length')) > MAX_JSON) return;
            response.clone().text().then(body => capture(spec, json(body))).catch(() => {});
          } catch {}
        }, () => {});
        return pending;
      };
    }
    const prototype = page.XMLHttpRequest?.prototype;
    if (prototype) {
      const open = prototype.open, send = prototype.send;
      const requests = new WeakMap();
      prototype.open = function (method, url, ...rest) {
        requests.set(this, xhrSpec(method, url));
        return open.call(this, method, url, ...rest);
      };
      prototype.send = function (...args) {
        const request = requests.get(this);
        const spec = request?.graphql ? detailSpec(location.origin + '/graphql', args[0]) : request;
        requests.delete(this);
        if (spec) this.addEventListener('load', () => {
          try {
            if (this.status < 200 || this.status >= 300) return;
            capture(spec, this.responseType === 'json' ? this.response : json(this.responseText));
          } catch {}
        }, {once: true});
        return send.apply(this, args);
      };
    }
  }
  hookDetails();

  function inlineDetail(id) {
    const script = document.getElementById('__NEXT_DATA__');
    const data = json(script?.textContent);
    const props = data?.props?.pageProps;
    const direct = normalize(site === 'pixai' ? props?.artwork : props?.image, site, id);
    if (direct) return direct;
    if (site !== 'civitai') return null;
    const queries = props?.trpcState?.json?.queries;
    if (!Array.isArray(queries) || queries.length > 64) return null;
    for (const query of queries) {
      const key = query?.queryKey;
      if (!Array.isArray(key) || !Array.isArray(key[0]) || key[0].join('.') !== 'image.get') continue;
      if (idOf(key[1]?.input?.id) !== id) continue;
      const detail = normalize(query.state?.data, site, id);
      if (detail) return detail;
    }
    return null;
  }
  function visible(element) {
    if (!element || element.hidden || element.getAttribute('aria-hidden') === 'true') return false;
    return typeof element.getClientRects !== 'function' || element.getClientRects().length > 0;
  }
  function scopedDetail(id) {
    const attribute = site === 'pixai' ? 'data-artwork-id' : 'data-image-id';
    const roots = document.querySelectorAll('[' + attribute + '="' + id + '"]');
    for (const root of Array.from(roots).slice(0, 8)) {
      if (!visible(root)) continue;
      const positive = root.querySelector('[data-prompt], [data-testid="prompt"]');
      const negative = root.querySelector('[data-negative-prompt], [data-testid="negative-prompt"]');
      if (visible(positive)) return {positive: text(positive.value || positive.textContent), negative: visible(negative) ? text(negative.value || negative.textContent, MAX_NEGATIVE) : '', title: '', image_url: ''};
    }
    return null;
  }
  function scopedCivitaiTags(id) {
    const root = Array.from(document.querySelectorAll('[data-image-id="' + id + '"]')).slice(0, 8).find(visible);
    if (!root) return [];
    const names = [], seen = new Set();
    for (const anchor of Array.from(root.querySelectorAll('a[href*="images?tags="]')).slice(0, 80)) {
      const name = str(anchor.textContent).replace(/\s+/g, ' ').trim();
      if (!visible(anchor) || !name || name.length > 80 || /^\d|^[👍❤️😂😢]/.test(name) || /^(?:image|images|prompt|negative prompt|generation data|model|none)$/i.test(name) || seen.has(name.toLowerCase())) continue;
      names.push(name); seen.add(name.toLowerCase());
    }
    return names;
  }
  const navTags = new Set(['all', 'posts', 'post', 'tags', 'tag', 'notes', 'note', 'history', 'statistics', 'options', 'up', 'down', 'vote_up', 'vote_down', 'edit', 'delete', 'flag_for_deletion', 'add_to_favorites', 'add_favorite', 'add_note', 'add_to_pool', 'tag_merge', 'original_image', 'fit_image_to_window', 'source', 'score', 'rating', 'id', 'posted', 'uploader', 'size', 'add', 'remove', 'search', 'wiki', 'artist', 'copyright', 'character', 'general', 'metadata', 'meta']);
  function cleanTag(raw) {
    let tag = str(raw).replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim()
      .replace(/^#/, '').replace(/^,+|,+$/g, '').replace(/^\((.*)\)$/, '$1').trim()
      .replace(/\s+\(?\d+(?:\.\d+)?[kKmM]?\)?$/, '').trim().replace(/\s+/g, '_');
    return tag && tag.length <= 120 && !/^[-+?.]+$/.test(tag) && !/^\d+(?:\.\d+)?[kKmM]?$/.test(tag) && !navTags.has(tag.toLowerCase()) ? tag : '';
  }
  function category(anchor) {
    for (let item = anchor, depth = 0; item && depth < 6; item = item.parentElement || item.parentNode, depth++) {
      const number = item.getAttribute?.('data-tag-category') ?? item.getAttribute?.('data-category');
      if (/^[012345]$/.test(String(number))) return Number(number) === 2 ? 0 : Number(number);
      const names = (String(item.className || '') + ' ' + String(item.id || '')).toLowerCase();
      const numeric = names.match(/(?:^|\s)(?:category-|tag-type-|tag-category-)([0-5])(?:\s|$)/);
      if (numeric) return Number(numeric[1]) === 2 ? 0 : Number(numeric[1]);
      for (const [name, number] of [['artist', 1], ['copyright', 3], ['character', 4], ['meta', 5], ['general', 0]]) {
        if (new RegExp('category-' + number + '|tag-type-' + name + '|tag-category-' + name + '|tag-' + name + '|' + name + '-tags?').test(names)) return number;
      }
      if (/metadata/.test(names)) return 5;
    }
    return 0;
  }
  function tagContext(anchor) {
    for (let item = anchor, depth = 0; item && depth < 8; item = item.parentElement || item.parentNode, depth++) {
      if (item.getAttribute?.('data-tag-category') != null || item.getAttribute?.('data-category') != null) return true;
      const names = (String(item.className || '') + ' ' + String(item.id || '')).toLowerCase();
      if (/tag-type-(?:[0-5]|artist|copyright|character|general|meta|metadata)|tag-category-(?:[0-5]|artist|copyright|character|general|meta)|category-[0-5]|tag-(?:artist|copyright|character|general|meta)|(?:artist|copyright|character|general|meta|metadata)-tags?|search-tag|tag-link|tag-name/.test(names)) return true;
    }
    return false;
  }
  function booruDetail() {
    const buckets = new Map([[1, []], [3, []], [4, []], [0, []]]);
    const selectors = '#tag-list a, ul.tag-list a, #tag-sidebar a, a.search-tag, a.tag-link, a.tag-name, [class*="tag-type"] a[href*="tags="], [class*="category-"] a[href*="tags="], [data-tag-category] a[href*="tags="]';
    for (const anchor of Array.from(document.querySelectorAll(selectors)).slice(0, 1200)) {
      if (!visible(anchor)) continue;
      try {
        const url = new URL(anchor.getAttribute('href') || anchor.href, location.href);
        if (url.hostname !== location.hostname) continue;
        const queryTag = url.searchParams.get('tags');
        const pathTag = decodeURIComponent(url.pathname).match(/^\/tags\/([^/]+)$/)?.[1];
        const valid = site === 'gelbooru' ? queryTag && url.searchParams.get('page') === 'post' && (!url.searchParams.get('s') || url.searchParams.get('s') === 'list')
          : site === 'yandere' ? queryTag && /^\/post\/?$/.test(url.pathname)
          : (queryTag && /^\/posts?\/?$/.test(url.pathname)) || pathTag;
        if (!valid || (!tagContext(anchor) && !(site === 'danbooru' && pathTag))) continue;
        const tag = cleanTag(queryTag ? queryTag.split(/\s+/)[0] : pathTag);
        const bucket = buckets.get(category(anchor));
        if (tag && bucket) bucket.push(tag);
      } catch {}
    }
    const seen = new Set(), tags = [];
    for (const bucket of buckets.values()) for (const tag of bucket) {
      if (!seen.has(tag.toLowerCase())) { tags.push(tag); seen.add(tag.toLowerCase()); }
    }
    const image = document.querySelector('#image, #gelcomVideoPlayer source, a#highres');
    return {positive: tags.join(', '), negative: '', title: '', image_url: image ? publicUrl(image.currentSrc || image.src || image.href || image.getAttribute('src') || '', true) : ''};
  }
  function extract(preferSelection = false) {
    const page = current();
    let detail = {};
    if (page.id) {
      if (site === 'civitai' || site === 'pixai') {
        const cached = cache.find(item => item.site === site && item.id === page.id);
        const choices = [scopedDetail(page.id), inlineDetail(page.id), cached].filter(Boolean);
        detail = choices.find(item => item.positive) || choices[0] || {};
        if (!detail.positive && site === 'civitai') {
          const tags = scopedCivitaiTags(page.id);
          detail = {...detail, positive: (tags.length ? tags : cached?.tags || []).join(', ')};
        }
      } else detail = booruDetail();
    }
    const selected = text(String(window.getSelection?.() || ''));
    return {positive: (preferSelection && selected) || detail.positive || selected || '', negative: detail.negative || '', source_url: page.source, title: detail.title || '', post_id: page.id, image_url: detail.image_url || ''};
  }
  function message(value) { if (status) status.textContent = value; }
  function endpoint(value) {
    try {
      if (!/^http:\/\/(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?\/unified-workbench\/browser-import$/i.test(value)) return '';
      const url = new URL(value);
      if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) || url.username || url.password || url.search || url.hash || url.pathname !== '/unified-workbench/browser-import') return '';
      if (url.port && (Number(url.port) < 1 || Number(url.port) > 65535)) return '';
      return url.href;
    } catch { return ''; }
  }
  function send(payload) {
    if (busy) return;
    if (!payload.post_id) { message('请打开作品详情页。'); return; }
    if (!payload.source_url) { message('当前页面地址无效。'); return; }
    if (!payload.positive.trim()) { message('请选择提示词或手工填写。'); return; }
    if (Array.from(payload.positive).length > MAX_POSITIVE || Array.from(payload.negative).length > MAX_NEGATIVE) { message('提示词过长，请缩短后发送。'); return; }
    const target = endpoint(typeof GM_getValue === 'function' ? GM_getValue(ENDPOINT_KEY, DEFAULT_ENDPOINT) : DEFAULT_ENDPOINT);
    if (!target) { message('本地地址无效，请在脚本菜单修改。'); return; }
    if (typeof GM_xmlhttpRequest !== 'function') { message('脚本管理器请求不可用。'); return; }
    busy = true; button.disabled = true; message('正在发送…');
    const finish = value => { busy = false; button.disabled = false; message(value); };
    try {
      GM_xmlhttpRequest({method: 'POST', url: target, anonymous: true,
        headers: {'Content-Type': 'application/json'}, data: JSON.stringify(payload), timeout: 10000,
        onload: response => {
          const result = json(response.responseText);
          finish(response.status >= 200 && response.status < 300 && result?.ok === true ? '服务已保存；工作台待接纳。' : '发送失败，请稍后手工重试。');
        }, onerror: () => finish('无法连接本地服务。'), ontimeout: () => finish('本地服务响应超时。')});
    } catch { finish('无法连接本地服务。'); }
  }
  function openEditor() {
    if (busy) return;
    if (!current().id) { message('请打开作品详情页。'); return; }
    editor?.remove();
    const payload = extract(true);
    editor = document.createElement('div'); editor.id = 'uw-browser-editor';
    editor.style.cssText = 'position:fixed;right:12px;bottom:52px;width:320px;max-width:90vw;padding:10px;background:#202126;color:#fff;z-index:2147483647;border:1px solid #777;border-radius:8px;font:13px sans-serif';
    const heading = document.createElement('div'); heading.textContent = '当前页提示词 · 发送后到工作台待接纳';
    const positive = document.createElement('textarea'); positive.id = 'uw-browser-positive'; positive.value = payload.positive; positive.setAttribute('aria-label', '正向提示词');
    const negative = document.createElement('textarea'); negative.id = 'uw-browser-negative'; negative.value = payload.negative; negative.setAttribute('aria-label', '负向提示词');
    for (const field of [positive, negative]) field.style.cssText = 'display:block;box-sizing:border-box;width:100%;height:96px;margin:8px 0;background:#111;color:#fff';
    const submit = document.createElement('button'); submit.textContent = '发送'; submit.id = 'uw-browser-editor-send';
    submit.addEventListener('click', () => {
      if (current().source !== payload.source_url || current().id !== payload.post_id) { message('页面已切换，请重新打开编辑。'); return; }
      send({...payload, positive: positive.value, negative: negative.value});
    });
    const close = document.createElement('button'); close.textContent = '关闭'; close.addEventListener('click', () => editor.remove());
    editor.append(heading, positive, negative, submit, close); document.body.appendChild(editor); positive.focus();
    if (!payload.positive) message('请选择提示词或手工填写。');
  }
  function boot() {
    if (!document.body || button) return;
    const box = document.createElement('div');
    box.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:2147483647;font:12px sans-serif';
    button = document.createElement('button'); button.id = 'uw-browser-send'; button.textContent = '发到工作台'; button.title = '点击发送当前页；Shift 点击编辑正向/负向提示词';
    status = document.createElement('span'); status.id = 'uw-browser-status'; status.style.cssText = 'margin-left:8px;padding:3px;background:#202126;color:#fff';
    button.addEventListener('click', event => {
      if (busy) return;
      if (!current().id) { message('请打开作品详情页。'); return; }
      if (event.shiftKey) return openEditor();
      const payload = extract();
      if (!payload.positive.trim()) return openEditor();
      send(payload);
    });
    box.append(button, status); document.body.appendChild(box);
    if (typeof GM_registerMenuCommand === 'function') {
      GM_registerMenuCommand('编辑并发送当前页', openEditor);
      GM_registerMenuCommand('设置本地工作台地址', () => {
        const value = window.prompt('本地工作台地址', DEFAULT_ENDPOINT);
        if (value === null) return;
        const target = endpoint(value);
        if (!target) { message('仅支持 localhost 或 127.0.0.1 的本地工作台地址。'); return; }
        if (typeof GM_setValue === 'function') GM_setValue(ENDPOINT_KEY, target);
        message('本地地址已保存。');
      });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once: true});
  else boot();
})();
