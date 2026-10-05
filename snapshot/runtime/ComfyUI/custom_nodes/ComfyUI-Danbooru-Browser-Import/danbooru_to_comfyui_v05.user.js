// ==UserScript==
// @name         Danbooru to ComfyUI Browser Import v0.5
// @namespace    local.comfyui.danbooru.import
// @version      0.5.0
// @description  Extract tags from the current Danbooru page in the browser and send them to local ComfyUI.
// @match        https://danbooru.donmai.us/*
// @match        http://danbooru.donmai.us/*
// @match        https://*.donmai.us/*
// @match        http://*.donmai.us/*
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
  'use strict';

  const ENDPOINT = 'http://127.0.0.1:8188/danbooru_browser_import_v05';
  const LOG_PREFIX = '[Danbooru→ComfyUI v0.5]';
  console.log(LOG_PREFIX, 'userscript loaded on', location.href);

  function cleanText(x) {
    return (x || '').replace(/\s+/g, ' ').trim();
  }

  function uniq(arr) {
    const seen = new Set();
    const out = [];
    for (const x of arr) {
      const v = cleanText(String(x || '')).replace(/^#/, '');
      if (!v || seen.has(v)) continue;
      seen.add(v);
      out.push(v);
    }
    return out;
  }

  function findPostId() {
    const m = location.pathname.match(/\/posts\/(\d+)/);
    if (m) return m[1];
    const idText = document.body.innerText.match(/\bID:\s*(\d+)/i);
    return idText ? idText[1] : '';
  }

  function getImageUrl() {
    const selectors = [
      '#image',
      'img#image',
      'picture img',
      'section#image-container img',
      'article img',
      'img[src*="cdn.donmai.us"]'
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && (el.src || el.dataset?.largeFileUrl || el.dataset?.fileUrl)) {
        return el.dataset.largeFileUrl || el.dataset.fileUrl || el.src;
      }
    }
    const link = document.querySelector('a[href*="cdn.donmai.us/original"], a[href*="cdn.donmai.us/sample"], a[href*="cdn.donmai.us/preview"]');
    return link ? link.href : '';
  }

  function tagFromAnchor(a) {
    const candidates = [
      a.dataset?.tagName,
      a.getAttribute('data-tag-name'),
      a.getAttribute('data-tag'),
      a.getAttribute('title'),
      a.textContent,
    ];
    for (const c of candidates) {
      const t = cleanText(c);
      if (t && !/^\?+$/.test(t) && !/^\d+(\.\d+)?[kKmM]?$/.test(t)) return t.replace(/\s/g, '_');
    }
    return '';
  }

  function collectTags() {
    const buckets = { artist: [], character: [], copyright: [], general: [], meta: [] };
    const lis = Array.from(document.querySelectorAll('#tag-list li, li[class*="tag-type"], li[class*="category-"]'));

    for (const li of lis) {
      const cls = li.className || '';
      const a = li.querySelector('a.search-tag, a[href*="/posts?tags="], a[href*="tags="]');
      if (!a) continue;
      const tag = tagFromAnchor(a);
      if (!tag) continue;

      if (/artist|category-1|tag-type-1/.test(cls)) buckets.artist.push(tag);
      else if (/copyright|category-3|tag-type-3/.test(cls)) buckets.copyright.push(tag);
      else if (/character|category-4|tag-type-4/.test(cls)) buckets.character.push(tag);
      else if (/meta|category-5|tag-type-5/.test(cls)) buckets.meta.push(tag);
      else buckets.general.push(tag);
    }

    // Fallback: collect visible tag links from sidebar if class bucketing failed.
    if (Object.values(buckets).every(arr => arr.length === 0)) {
      const anchors = Array.from(document.querySelectorAll('a[href*="/posts?tags="]'));
      buckets.general = anchors.map(tagFromAnchor).filter(Boolean);
    }

    for (const k of Object.keys(buckets)) buckets[k] = uniq(buckets[k]);
    return buckets;
  }

  function extractPayload() {
    const tags = collectTags();
    const merged = uniq([
      ...tags.artist.map(t => '@' + t.replace(/^@/, '')),
      ...tags.character,
      ...tags.copyright,
      ...tags.general,
      ...tags.meta,
    ]);

    return {
      post_id: findPostId(),
      source_url: location.href,
      image_url: getImageUrl(),
      artist_tags: tags.artist.join(', '),
      character_tags: tags.character.join(', '),
      copyright_tags: tags.copyright.join(', '),
      general_tags: tags.general.join(', '),
      meta_tags: tags.meta.join(', '),
      merged_tags: merged.join(', '),
      user_agent_note: 'extracted in browser by Tampermonkey v0.5',
      extracted_at: new Date().toISOString(),
    };
  }

  function sendPayload() {
    const payload = extractPayload();
    console.log(LOG_PREFIX, 'payload', payload);

    GM_xmlhttpRequest({
      method: 'POST',
      url: ENDPOINT,
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify(payload),
      timeout: 10000,
      onload: function (res) {
        console.log(LOG_PREFIX, 'response', res.status, res.responseText);
        if (res.status >= 200 && res.status < 300) {
          alert('Sent to ComfyUI v0.5 OK\n' + res.responseText.slice(0, 500));
        } else {
          alert('ComfyUI v0.5 endpoint returned HTTP ' + res.status + '\n' + res.responseText.slice(0, 500));
        }
      },
      onerror: function (err) {
        console.error(LOG_PREFIX, 'request error', err);
        alert('Failed to reach ComfyUI v0.5 endpoint: ' + JSON.stringify(err));
      },
      ontimeout: function () {
        alert('Timed out calling ComfyUI v0.5 endpoint: ' + ENDPOINT);
      }
    });
  }

  function previewPayload() {
    const payload = extractPayload();
    console.log(LOG_PREFIX, 'preview', payload);
    alert(JSON.stringify(payload, null, 2).slice(0, 3000));
  }

  function injectPanel() {
    if (document.getElementById('danbooru-comfyui-import-v05')) return;
    const panel = document.createElement('div');
    panel.id = 'danbooru-comfyui-import-v05';
    panel.style.cssText = [
      'position:fixed', 'top:120px', 'right:20px', 'z-index:2147483647',
      'background:#111', 'color:#fff', 'border:2px solid #76d275',
      'border-radius:10px', 'padding:10px', 'font:13px Arial,sans-serif',
      'box-shadow:0 4px 20px rgba(0,0,0,.35)', 'min-width:220px'
    ].join(';');

    const title = document.createElement('div');
    title.textContent = 'Danbooru → ComfyUI v0.5';
    title.style.cssText = 'font-weight:bold;margin-bottom:8px;color:#9eff9e';

    const send = document.createElement('button');
    send.textContent = 'Send Tags to ComfyUI';
    send.style.cssText = 'display:block;width:100%;margin:4px 0;padding:7px;background:#2e7d32;color:white;border:0;border-radius:6px;cursor:pointer';
    send.addEventListener('click', sendPayload);

    const preview = document.createElement('button');
    preview.textContent = 'Preview Extract';
    preview.style.cssText = 'display:block;width:100%;margin:4px 0;padding:7px;background:#455a64;color:white;border:0;border-radius:6px;cursor:pointer';
    preview.addEventListener('click', previewPayload);

    const small = document.createElement('div');
    small.textContent = ENDPOINT;
    small.style.cssText = 'margin-top:6px;color:#bbb;font-size:10px;word-break:break-all';

    panel.appendChild(title);
    panel.appendChild(send);
    panel.appendChild(preview);
    panel.appendChild(small);
    document.body.appendChild(panel);
    console.log(LOG_PREFIX, 'panel injected');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectPanel);
  } else {
    injectPanel();
  }
  setTimeout(injectPanel, 1000);
})();
