const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {harness} = require('./test_browser_pending.cjs');
const route = '/unified-workbench/browser-import';
const eventName = 'unified-workbench-browser-prompt';
const uuid = value => `${String(value).padStart(8,'0')}-1111-4111-8111-111111111111`;
const payload = (value, overrides = {}) => ({import_id: uuid(value), destination: 'workbench', positive: `positive ${value}`, negative: `negative ${value}`,
    source_url: `https://example.org/posts/${value}`, title: `post ${value}`, post_id: String(value), image_url: '', ...overrides});
const clone = value => JSON.parse(JSON.stringify(value));
let checks = 0;
const check = (condition, message) => {assert(condition, message);checks++;};

function server(initial = []) {
    const inbox = new Map(initial.map(item => [item.import_id, item])), accepted = new Set(), leases = new Map(), calls = [];
    const failures = {claim: 0, ack: 0, release: 0, get: 0};let token = 100, now = Date.now();
    const response = (status, data) => ({status, ok: status >= 200 && status < 300, json: async () => clone(data)});
    const request = async (url, options = {}) => {
        assert(url.startsWith(route), 'Receiver only contacts its local service routes');
        const action = url.slice(route.length).slice(1) || 'get', body = options.body ? JSON.parse(options.body) : null;
        calls.push({action, body});
        if(failures[action] > 0){failures[action]--;throw new Error('isolated network failure');}
        if(action === 'get')return response(200, {ok: true, items: [...inbox.values()], latest: [...inbox.values()].at(-1) || null});
        if(action === 'claim'){
            if(accepted.has(body.import_id))return response(200, {ok: true, delivery: 'accepted', import_id: body.import_id});
            if(!inbox.has(body.import_id))return response(404, {ok: false, error: 'unknown_import'});
            let lease = leases.get(body.import_id);
            if(lease && lease.expires > now && lease.receiver !== body.receiver_id)return response(409, {ok: false, error: 'already_claimed', retry_after_ms: lease.expires - now});
            if(!lease || lease.expires <= now){lease = {receiver: body.receiver_id, token: uuid(token++), expires: now + 60000};leases.set(body.import_id, lease);}
            return response(200, {ok: true, delivery: 'claimed', payload: inbox.get(body.import_id), claim_token: lease.token, claim_expires_at: lease.expires / 1000});
        }
        const lease = leases.get(body.import_id);
        if(action === 'ack' && accepted.has(body.import_id))return response(200, {ok: true, delivery: 'accepted'});
        if(!lease || lease.receiver !== body.receiver_id || lease.token !== body.claim_token || lease.expires <= now)return response(409, {ok: false, error: 'claim_mismatch'});
        if(action === 'release'){leases.delete(body.import_id);return response(200, {ok: true, delivery: 'released'});}
        if(action === 'ack'){accepted.add(body.import_id);inbox.delete(body.import_id);leases.delete(body.import_id);return response(200, {ok: true, delivery: 'accepted'});}
        throw new Error('Unexpected receiver action: ' + action);
    };
    return {request, inbox, accepted, leases, calls, failures, add: item => inbox.set(item.import_id, item), expire: () => {now += 61000;}};
}

function receiver(service, number, saved = null, options = {}) {
    const h = harness(saved), listeners = new Map(), timers = new Map();let timerId = 0, opens = 0, shows = 0;
    const api = {addEventListener(name, fn){if(!listeners.has(name))listeners.set(name, new Set());listeners.get(name).add(fn);},
        removeEventListener(name, fn){listeners.get(name)?.delete(fn);}, emit(name, detail){for(const fn of listeners.get(name) || [])fn({detail});}};
    h.context.AbortController = AbortController;
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/browser_import.js'), 'utf8')
        .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, ''), h.context, {filename: 'browser_import.js'});
    const storage = options.storage || h.context.sessionStorage;
    h.context.sessionStorage = storage;
    const owner = {addPending: resource => h.pending.add(resource), showPending: async () => {shows++;}};
    const instance = h.context.createBrowserImportReceiver({api, request: service.request, storage, makeUuid: () => uuid(number), report: message => h.messages.push(message),
        openWorkbench: async () => {opens++;if(options.openGate)await options.openGate;return owner;},
        setTimer: (fn, delay) => {timers.set(++timerId, {fn, delay});return timerId;}, clearTimer: id => timers.delete(id)});
    const runRetries = async () => {const scheduled = [...timers.entries()].filter(([,timer]) => timer.delay !== 10000);for(const [id,timer] of scheduled){timers.delete(id);timer.fn();}await instance.whenIdle();};
    return {...h, api, instance, timers, runRetries, opens: () => opens, shows: () => shows};
}

async function main() {
    const service = server([payload(1)]), one = receiver(service, 201), two = receiver(service, 202);
    await Promise.all([one.instance.ready, two.instance.ready]);
    const winner = one.pending.items.length ? one : two, loser = winner === one ? two : one;
    check(winner.pending.items.length === 2 && loser.pending.items.length === 0, 'Atomic service claims put both directions in only one receiver');
    check(service.accepted.has(uuid(1)) && winner.shows() === 1 && loser.shows() === 0, 'Only the persisted receiver opens its pending display and acknowledges receipt');
    check(one.target.text === 'base' && two.target.text === 'base', 'Reception never applies text to workflow targets');
    check(service.calls.filter(call => call.action === 'ack').every(call => call.body.claim_token), 'Acknowledgment is bound to the exact lease token');
    winner.api.emit(eventName, payload(1));await winner.instance.whenIdle();
    check(winner.pending.items.length === 2 && winner.shows() === 1, 'Duplicate events after acknowledgment do not reopen or append');
    const before = service.calls.length;winner.api.emit('status', {});await winner.instance.whenIdle();
    check(service.calls.length === before, 'Normal status events never poll the inbox');

    const overlapService = server(), overlap = receiver(overlapService, 203);await overlap.instance.ready;
    overlapService.add(payload(2));overlap.api.emit(eventName, payload(2));overlap.api.emit('reconnected');await overlap.instance.whenIdle();
    check(overlap.pending.items.length === 2 && overlapService.calls.filter(call => call.action === 'ack').length === 1, 'A live event overlapping reconnect backfill is serialized and acknowledged once');
    overlapService.add(payload(3));overlapService.add(payload(4));await overlap.instance.backfill();
    check(overlap.pending.items.length === 6 && [2,3,4].every(value => overlapService.accepted.has(uuid(value))), 'Multiple inbox messages append to the complete local draft without replacing earlier receipts');
    const groups = overlap.pending.items;
    check(groups.filter(item => item.usage === 'positive').map(item => item.sourceText).join('|') === 'positive 2|positive 3|positive 4' &&
        groups.filter(item => item.usage === 'negative').map(item => item.sourceText).join('|') === 'negative 2|negative 3|negative 4', 'Directions and receipt identities remain isolated across consecutive messages');
    overlap.context.document.hidden = true;overlapService.add(payload(19));overlap.api.emit(eventName,payload(19));await overlap.instance.whenIdle();
    check(overlapService.accepted.has(uuid(19)) && overlap.pending.items.length === 8 && overlap.target.text === 'base', 'A hidden ComfyUI page can receive to its pending list without applying or generating');

    const claimService = server([payload(5)]);claimService.failures.claim = 1;
    const failedClaim = receiver(claimService, 204);await failedClaim.instance.ready;
    check(failedClaim.pending.items.length === 0 && failedClaim.opens() === 0 && !claimService.accepted.size, 'A failed claim never opens or claims application success');
    await failedClaim.instance.backfill();check(failedClaim.pending.items.length === 2 && claimService.accepted.has(uuid(5)), 'A failed claim remains recoverable by explicit backfill');

    const ackService = server([payload(6)]);ackService.failures.ack = 1;
    const ackRetry = receiver(ackService, 205);await ackRetry.instance.ready;
    const ackBodies = ackService.calls.filter(call => call.action === 'ack').map(call => call.body);
    check(ackService.accepted.has(uuid(6)) && ackBodies.length === 2 && ackBodies[0].claim_token === ackBodies[1].claim_token, 'A transient acknowledgment failure retries once with the same lease token');
    const retainedService = server([payload(7)]);retainedService.failures.ack = 2;
    const retained = receiver(retainedService, 206);await retained.instance.ready;
    check(retained.pending.items.length === 2 && !retainedService.accepted.size && !retainedService.calls.some(call => call.action === 'release'), 'Unconfirmed but saved drafts retain their lease instead of immediately handing the receipt to another page');
    check(retained.messages.some(message => message.includes('服务尚未确认接收')) && retained.timers.size === 1, 'Persistent acknowledgment failure is truthful and schedules one bounded recovery');
    await retained.instance.backfill();
    check(retained.pending.items.length === 2 && retainedService.accepted.has(uuid(7)) && retained.timers.size === 0, 'Recovery acknowledges the saved receipt without duplicating sections');

    const reloadService = server([payload(8)]);reloadService.failures.ack = 2;
    const previous = receiver(reloadService, 207);await previous.instance.ready;
    await previous.render();const edit = previous.host.querySelectorAll('[aria-label="仅本次使用的正文"]')[0];edit.value = 'edited before reload';edit.oninput();
    previous.instance.dispose();
    const reloaded = receiver(reloadService, 208, previous.storage());await reloaded.instance.ready;
    check(reloaded.pending.items.length === 2 && reloaded.pending.items[0].text === 'edited before reload' && reloaded.opens() === 0, 'A new document keeps saved edits while an old page lease is still busy');
    reloadService.expire();await reloaded.runRetries();
    check(reloadService.accepted.has(uuid(8)) && reloaded.pending.items.length === 2 && reloaded.pending.items[0].text === 'edited before reload' && reloaded.pending.items[0].sourceText === 'positive 8', 'One lease-expiry backfill claims and acknowledges restored original provenance without swallowing edits');
    check(reloaded.instance.receiverId !== previous.instance.receiverId, 'A reload uses a fresh document receiver identity');

    const writeService = server([payload(9)]);
    const unavailable = {getItem(){return null;},setItem(){throw new Error('isolated storage unavailable');}};
    const failedWrite = receiver(writeService, 209, null, {storage: unavailable});await failedWrite.instance.ready;
    check(!writeService.accepted.size && writeService.calls.some(call => call.action === 'release') && writeService.inbox.has(uuid(9)), 'An incomplete persisted draft releases its claim and stays pending on the service');
    const other = receiver(writeService, 210);await other.instance.ready;
    check(other.pending.items.length === 2 && writeService.accepted.has(uuid(9)), 'Another receiver can safely recover a released storage failure');
    const repairService = server([payload(17)]);let blocked = true, stored = null;
    const repairStorage = {getItem: () => stored, setItem: (_,value) => {if(blocked)throw new Error('isolated quota failure');stored = value;}};
    const repair = receiver(repairService, 214, null, {storage:repairStorage});await repair.instance.ready;
    check(repair.pending.items.length === 2 && stored === null && !repairService.accepted.size, 'A native pending persistence failure retains only an unacknowledged in-memory draft');
    blocked = false;await repair.instance.backfill();
    check(repairService.accepted.has(uuid(17)) && repair.pending.items.length === 2 && JSON.parse(stored).length === 2, 'Retry after storage recovery persists existing in-memory sections without duplicating or swallowing them');
    const partialService = server([payload(20)]);let partialRaw = null;
    const partialStorage = {getItem: () => partialRaw, setItem: (_,value) => {partialRaw = JSON.stringify(JSON.parse(value).filter(item=>item.usage!=='negative'));}};
    const partial = receiver(partialService,216,null,{storage:partialStorage});await partial.instance.ready;
    check(!partialService.accepted.size && partialService.calls.some(call=>call.action==='release'), 'Persistence proof rejects a missing direction even when the positive body was saved');
    const badSourceService = server([payload(21)]);let changedRaw = null;
    const changedStorage = {getItem: () => changedRaw, setItem: (_,value) => {changedRaw = JSON.stringify(JSON.parse(value).map(item=>({...item,sourceText:'altered source'})));}};
    const changed = receiver(badSourceService,217,null,{storage:changedStorage});await changed.instance.ready;
    check(!badSourceService.accepted.size && badSourceService.calls.some(call=>call.action==='release'), 'Persistence proof rejects altered original provenance rather than acknowledging the receipt');

    const invalidService = server(), invalid = receiver(invalidService, 211);await invalid.instance.ready;
    const invalids = [payload(10,{source_url:'https://example.org/posts/10?token=fixture'}),payload(11,{positive:'p'.repeat(65537)}),
        payload(12,{negative:'n'.repeat(16385)}),payload(13,{destination:'other'}),payload(14,{import_id:'bad-uuid'}),payload(22,{negative:' '.repeat(16385)})];
    for(const item of invalids){invalid.api.emit(eventName,item);await invalid.instance.whenIdle();}
    check(invalidService.calls.every(call => call.action === 'get') && invalid.opens() === 0, 'Invalid sources, oversized directions, wrong destination and malformed UUID fail before claiming or opening');
    const conflictingService = server(), conflict = receiver(conflictingService, 212);await conflict.instance.ready;
    conflictingService.add(payload(15));conflict.api.emit(eventName,payload(15,{positive:'stale event body'}));await conflict.instance.whenIdle();
    check(conflict.pending.items[0].sourceText === 'positive 15', 'The authoritative service claim payload supplies original provenance rather than a differing event body');
    const lostService = server([payload(18)]), lostRequest = lostService.request;let loseAck = true;
    lostService.request = async (...args) => {const result = await lostRequest(...args);if(args[0].endsWith('/ack')&&loseAck){loseAck=false;throw new Error('accepted response lost');}return result;};
    const lost = receiver(lostService,215);await lost.instance.ready;
    check(lostService.accepted.has(uuid(18)) && lost.pending.items.length === 2 && lostService.calls.filter(call=>call.action==='ack').length===2, 'A server-accepted but lost acknowledgment reply is recovered by an idempotent retry');

    const busyService = server([payload(16)]);
    busyService.leases.set(uuid(16),{receiver:uuid(999),token:uuid(888),expires:Date.now()+120000});
    const busy = receiver(busyService,213);await busy.instance.ready;await busy.runRetries();
    check(busy.opens() === 0 && busy.timers.size === 0 && busy.messages.at(-1).includes('稍后重试'), 'A busy lease receives at most one bounded retry and never becomes a polling loop');
    const all = [one,two,overlap,failedClaim,ackRetry,retained,reloaded,failedWrite,other,repair,partial,changed,invalid,conflict,lost,busy];
    for(const page of all)page.instance.dispose();
    check(all.every(page => page.timers.size === 0), 'Disposal clears receiver recovery timers');
    console.log(`PASS: ${checks} browser receiver checks; atomic claims, overlapping recovery, multiple drafts, storage proof, lease tokens, acknowledgment failures, reload, direction isolation, no target writes.`);
}
main().catch(error => {console.error(error);process.exitCode=1;});
