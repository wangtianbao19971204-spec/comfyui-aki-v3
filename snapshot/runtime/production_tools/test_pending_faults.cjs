// Pending draft/cache/library failures only; browser receipt tests run separately.
const assert = require('node:assert/strict');
const {harness} = require('./test_browser_pending.cjs');
const entry = overrides => ({provider: 'library', id: 'library-fixture', text: 'library text', usage: 'positive', weight: 1, enabled: true, modified: false, ...overrides});
const response = (data, overrides = {}) => ({ok: true, status: 200, headers: {get: () => 'revision-fixture'}, json: async () => data, ...overrides});
const deferred = () => {let resolve; const promise = new Promise(yes => {resolve = yes;}); return {promise, resolve};};
const libraryResponse = text => response({prompt: {prompt: text, _semantic: {usage: 'positive', manual_search_eligible: true}}});
const browserEntry = () => ({provider: 'browser', id: '11111111-1111-4111-8111-111111111111', source_url: 'https://example.org/posts/12', usage: 'positive', text: 'browser text'});
const applyAt = async (h, host) => {await host.querySelector('.uw-use-actions').children.find(node => ['应用到目标', '确认替换', '预览替换'].includes(node.textContent)).onclick(); await h.settle();};
function commitBoundaryHarness(callback) {
    const h = harness();
    const writer = request => {const operation = h.writer(request); callback(h); return operation;};
    Object.assign(writer, {supportsActions: h.writer.supportsActions, preview: h.writer.preview, undoLast: h.writer.undoLast});
    Object.defineProperty(writer, 'onUndoInvalidated', {set: value => {h.writer.onUndoInvalidated = value;}});
    const element = (tag, text, parent, props = {}) => {const node = Object.assign(h.context.document.createElement(tag), props); if(text != null)node.textContent = text; parent?.append(node); return node;};
    const button = (text, key, onclick, parent) => {const node = element('button', text, parent); node.dataset.uw = key; node.onclick = onclick; return node;};
    h.pending = h.context.createPendingPrompts({element, button, report: message => h.messages.push(message), onCount() {}, insertionOptions: () => ({onInsert: writer, targetLabel: 'fixture target', targetDirection: h.target.direction})});
    h.render = async () => {h.pending.render(h.host); await h.settle();};
    return h;
}
let cases = 0;
async function test(name, callback) {await callback(); cases++; console.log('PASS: ' + name);}
async function main() {
    await test('corrupt cached entries cannot crash rendering or discard valid neighbors', async () => {
        for (const malformed of [null, 'bad entry', [], entry({text: null}), entry({text: {body: 'bad'}}), entry({weight: -1}), entry({weight: 4}), entry({weight: null}), entry({id: {bad: true}}), entry({splitDraft: {positive: 'draft', negative: null}})]) {
            const h = harness(JSON.stringify([malformed, entry({provider: 'tag', id: 'valid', text: 'valid neighbor', usage: 'target'})]));
            await h.render();
            assert.equal(h.pending.items.length, 1, 'Only the corrupt cached record is rejected');
            assert.equal(h.pending.items[0].text, 'valid neighbor'); assert.equal(h.target.text, 'base');
            assert(h.messages.some(message => String(message).includes('无效')));
        }
    });
    await test('unfinished empty edit and legacy missing optional flags survive cache restore', async () => {
        const h = harness(JSON.stringify([{provider: 'library', id: 'old', text: '', usage: 'positive'}]));
        await h.render(); assert.equal(h.pending.items.length, 1); assert.equal(h.pending.items[0].text, ''); assert.equal(h.target.text, 'base');
        await h.apply(); assert.equal(h.target.text, 'base'); assert(h.messages.some(message => String(message).includes('空白')));
    });
    await test('malformed cache container or unreadable session storage stays usable', async () => {
        for (const saved of ['{broken json', '{}', 'null', '17']) {
            const h = harness(saved); await h.render(); assert.equal(h.pending.items.length, 0); assert.equal(h.target.text, 'base');
            assert(h.messages.some(message => /草稿/.test(String(message)))); h.pending.add(browserEntry()); await h.render(); await h.apply();
            assert.equal(h.target.text, 'base, browser text');
        }
        const h = harness(); h.context.sessionStorage.getItem = () => {throw new Error('fixture blocked storage');};
        const pending = h.context.createPendingPrompts({element() {}, button() {}, insertionOptions() {}, report: message => h.messages.push(message), onCount() {}});
        assert.equal(pending.items.length, 0); assert(h.messages.some(message => String(message).includes('无法读取')));
        pending.add(browserEntry()); assert.equal(pending.compose(), 'browser text');
    });
    await test('session save failure preserves current memory and editable rendered draft', async () => {
        const h = harness(); h.context.sessionStorage.setItem = () => {throw new Error('fixture quota exceeded');};
        h.pending.add(browserEntry()); await h.render();
        const input = h.host.querySelector('[aria-label="仅本次使用的正文"]'); input.value = 'retained despite quota'; input.oninput(); await h.settle();
        assert.equal(h.pending.items[0].text, 'retained despite quota'); assert.equal(h.pending.compose(), 'retained despite quota');
        assert.equal(h.host.querySelector('[aria-label="仅本次使用的正文"]').value, 'retained despite quota');
        assert.equal(h.host.querySelector('.uw-pending-preview').textContent, 'retained despite quota'); assert.equal(h.target.text, 'base');
        assert(h.messages.some(message => String(message).includes('当前页面内的内容仍然保留')));
        await h.apply(); assert.equal(h.target.text, 'base, retained despite quota');
    });
    await test('malformed fresh library/tag payload never corrupts cached draft or target', async () => {
        for (const provider of ['library', 'tag']) for (const invalid of [null, {nested: 'bad'}, 17]) {
            const original = entry({provider, usage: provider === 'tag' ? 'target' : 'positive'});
            const h = harness(null, async () => response(provider === 'library' ? {prompt: {prompt: invalid}} : {item: {text: invalid}}));
            h.pending.add(original); await h.render(); await h.apply();
            assert.equal(h.target.text, 'base'); assert.equal(h.pending.items[0].text, original.text);
            assert.equal(JSON.parse(h.storage())[0].text, original.text);
        }
    });
    await test('HTTP/JSON/network failure keeps draft and never applies stale saved text', async () => {
        for (const fault of ['http', 'json', 'network']) {
            const h = harness(null, async () => {
                if (fault === 'network') throw new Error('fixture offline');
                if (fault === 'json') return response({}, {json: async () => {throw new Error('fixture invalid JSON');}});
                return response({error: 'fixture missing resource'}, {ok: false, status: 404});
            });
            h.pending.add(entry()); await h.render(); await h.apply(); assert.equal(h.target.text, 'base'); assert.equal(h.pending.items[0].text, 'library text');
        }
    });
    await test('missing/null/array response bodies retain every valid draft entry atomically', async () => {
        for (const payload of [null, [], {}, {prompt: null}, {prompt: []}]) {
            const h = harness(null, async url => url.includes('good') ? libraryResponse('updated good neighbor') : response(payload));
            h.pending.add(entry({id: 'good'})); h.pending.add(entry({id: 'bad'})); await h.render(); const saved = h.storage();
            await h.apply(); assert.equal(h.target.text, 'base'); assert(h.pending.items.every(item => item.text === 'library text')); assert.equal(h.storage(), saved);
        }
    });
    await test('library source update refreshes preview first and preserves temporary edit', async () => {
        for (const edited of [false, true]) {
            const h = harness(null, async url => url.includes('/library/prompt?') ? libraryResponse('fresh source') : response({revision: 'revision-fixture'}));
            h.pending.add(entry()); await h.render();
            if (edited) {const input = h.host.querySelector('[aria-label="仅本次使用的正文"]'); input.value = 'temporary edit'; input.oninput(); await h.settle();}
            await h.apply(); assert.equal(h.target.text, 'base');
            assert.equal(h.pending.items[0].text, edited ? 'temporary edit' : 'fresh source');
            await h.apply(); assert.equal(h.target.text, 'base, ' + (edited ? 'temporary edit' : 'fresh source'));
        }
    });
    await test('editing draft while authoritative lookup is pending rejects old lookup', async () => {
        const gate = deferred(); const h = harness(null, () => gate.promise); h.pending.add(entry()); await h.render();
        const applying = h.apply(); await Promise.resolve();
        const input = h.host.querySelector('[aria-label="仅本次使用的正文"]'); input.value = 'new edit'; input.oninput();
        gate.resolve(libraryResponse('library text')); await applying;
        assert.equal(h.target.text, 'base'); assert.equal(h.pending.items[0].text, 'new edit');
        assert(h.messages.some(message => String(message).includes('已变化')));
    });
    await test('repeated source changes require a stable reread without losing temporary edits', async () => {
        for (const edited of [false, true]) {
            let fresh = 'first fresh source';
            const h = harness(null, async url => url.includes('/library/prompt?') ? libraryResponse(fresh) : response({revision: 'revision-fixture'}));
            h.pending.add(entry()); await h.render();
            if(edited){const input = h.host.querySelector('[aria-label="仅本次使用的正文"]'); input.value = 'temporary retained'; input.oninput(); await h.settle();}
            await h.apply(); assert.equal(h.target.text, 'base'); fresh = 'second fresh source';
            await h.apply(); assert.equal(h.target.text, 'base');
            assert.equal(h.pending.items[0].text, edited ? 'temporary retained' : fresh);
            if(edited)assert.equal(h.pending.items[0].sourceText, fresh);
            await h.apply(); assert.equal(h.target.text, 'base, ' + (edited ? 'temporary retained' : fresh));
        }
    });
    await test('detached, remounted or retargeted panel rejects late lookups without changing draft/cache', async () => {
        for (const mode of ['detach', 'remount', 'retarget']) {
            const gate = deferred(); let reads = 0;
            const h = harness(null, async url => url.includes('/library/prompt?') ? (++reads === 1 ? gate.promise : libraryResponse('library text')) : response({revision: 'revision-fixture'}));
            h.pending.add(entry()); await h.render(); const saved = h.storage(); const applying = h.apply(); await Promise.resolve();
            let liveHost = h.host;
            if(mode === 'detach')h.host.remove();
            if(mode === 'remount'){liveHost = h.context.document.createElement('div'); h.context.document.body.append(liveHost); h.pending.render(liveHost);}
            if(mode === 'retarget')h.pending.refreshTarget();
            gate.resolve(libraryResponse('late changed source')); await applying;
            assert.equal(h.target.text, 'base'); assert.equal(h.pending.items[0].text, 'library text'); assert.equal(h.storage(), saved);
            assert(h.messages.some(message => String(message).includes('面板已关闭或切换')));
            if(mode === 'detach'){h.context.document.body.append(h.host); h.pending.render(h.host);}
            await h.settle(); await applyAt(h, liveHost); assert.equal(h.target.text, 'base, library text');
        }
    });
    await test('already detached actions stop before lookup and stale undo cannot alter the target', async () => {
        const unopened = harness(); unopened.pending.add(entry()); await unopened.render(); unopened.host.remove(); await unopened.apply();
        assert.equal(unopened.fetches.length, 0); assert.equal(unopened.target.text, 'base');
        const h = harness(); h.pending.add(browserEntry()); await h.render(); await h.apply(); assert.equal(h.target.text, 'base, browser text');
        const undo = h.host.querySelector('.uw-use-actions').children.find(node => node.textContent === '撤销本次写入');
        h.host.remove(); undo.onclick(); assert.equal(h.target.text, 'base, browser text');
    });
    await test('native writer microtask checks panel and edited-draft identity before committing', async () => {
        for (const mode of ['detach', 'retarget', 'edit']) {
            let changes = 0;
            const h = commitBoundaryHarness(current => {
                if(changes++)return;
                if(mode === 'detach')current.host.remove();
                if(mode === 'retarget')current.pending.refreshTarget();
                if(mode === 'edit'){const input = current.host.querySelector('[aria-label="仅本次使用的正文"]'); input.value = 'new boundary edit'; input.oninput();}
            });
            h.pending.add(browserEntry()); await h.render(); await h.apply(); assert.equal(changes, 1); assert.equal(h.target.text, 'base');
            assert.equal(h.pending.items[0].text, mode === 'edit' ? 'new boundary edit' : 'browser text');
            assert(h.messages.some(message => /面板已关闭或切换|待用内容或方向已变化/.test(String(message))));
            if(mode === 'detach'){h.context.document.body.append(h.host); h.pending.render(h.host); await h.settle();}
            await h.apply(); assert.equal(h.target.text, 'base, ' + (mode === 'edit' ? 'new boundary edit' : 'browser text'));
        }
    });
    await test('optional writer guard leaves legacy calls unchanged and also protects preview', async () => {
        const h = harness(); assert.equal((await h.writer('legacy fixture')).status, 'inserted'); assert.equal(h.target.text, 'base, legacy fixture');
        const guard = () => {throw new Error('fixture stale lifecycle');};
        await assert.rejects(() => h.writer({text: 'blocked', validateCurrent: guard}), /stale lifecycle/);
        await assert.rejects(() => h.writer.preview({text: 'blocked', validateCurrent: guard}), /stale lifecycle/);
        assert.equal(h.target.text, 'base, legacy fixture');
    });
    await test('recent-use conflict retries boundedly without inserting text a second time', async () => {
        let revisions = 0, writes = 0;
        const h = harness(null, async url => {
            if (url.includes('/library/prompt?')) return libraryResponse('library text');
            if (url.includes('/library/index')) return response({revision: 'r' + ++revisions}, {headers: {get: () => null}});
            writes++; return response({error: 'fixture conflict'}, {ok: false, status: 409});
        });
        h.pending.add(entry()); await h.render(); await h.apply();
        assert.equal(h.target.text, 'base, library text'); assert.equal(writes, 3); assert.equal(revisions, 3);
        assert(h.messages.some(message => String(message).includes('部分最近使用记录未保存')));
        await h.apply(); assert.equal(h.target.text, 'base, library text'); assert.equal(writes, 3);
    });
    console.log(`PASS: ${cases} pending cache/library failure scenarios; mock-only local APIs, no online database writes.`);
}
main().catch(error => {console.error(error); process.exitCode = 1;});
