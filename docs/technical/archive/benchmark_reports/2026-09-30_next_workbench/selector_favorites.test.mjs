import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {JSDOM} from '../2026-09-07_prompt_library_integration/candidate/test_runtime/node_modules/jsdom/lib/api.js';

const root = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.resolve(root, '../../ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-anima-tools/js');
const backupRoot = path.join(root, 'before_selector_favorites_2026-10-01/modules/comfyui-anima-tools/js');
const kinds = ['character', 'artist', 'clothing', 'background', 'pose', 'style_quality'];
const results = [];
const hashes = {};

function read(base, name) {
    return fs.readFileSync(path.join(base, name), 'utf8').replace(/\r\n/g, '\n');
}

function functionSource(source, name) {
    const start = source.indexOf(`    function ${name}(`) >= 0
        ? source.indexOf(`    function ${name}(`) : source.indexOf(`    async function ${name}(`);
    const end = source.indexOf('\n    }', start);
    assert.ok(start >= 0 && end > start, `Production function ${name} must be present`);
    return source.slice(start, end + '\n    }'.length);
}

function buttonSource(source, legacy) {
    const variable = legacy ? 'favIcon' : 'favBtn';
    const start = source.indexOf(`const ${variable} = `);
    const marker = `card.appendChild(${variable});`;
    const end = source.indexOf(marker, start);
    assert.ok(start > 0 && end > start, `Production ${variable} must be present`);
    return source.slice(start, end + marker.length);
}

const uiSource = read(sourceRoot, 'anima_selector_ui.js');
const focusStart = uiSource.indexOf('export function captureSelectorFavoriteFocus(');
const focusEnd = uiSource.indexOf('\n}', focusStart);
const captureFocusSource = uiSource.slice(focusStart, focusEnd + 2).replace('export function', 'function');
const identitySource=read(sourceRoot,'anima_prompt_identity.js');
const favoriteSourceHelper=identitySource.includes('export function getPromptFavoriteSourceKey(')
    ? new Function(identitySource.replaceAll('export function','function')+'\nreturn getPromptFavoriteSourceKey;')() : () => '';

const translationSource = read(sourceRoot, 'i18n.js').replace(/^import .*\n/, '').replace('export function t', 'function t');
function translator(locale) {
    return new Function('app', `${translationSource}\nreturn t;`)({ui:{settings:{getSettingValue:() => locale}}});
}
const translate = translator('zh');
assert.equal(translate('Add to Favorites'), '收藏');
assert.equal(translate('Remove from Favorites'), '取消收藏');
assert.equal(translator('en')('Remove from Favorites'), 'Remove from Favorites');

export function setup(kind, source, initialFavorite = false, custom = false, options = {}) {
    const dom = new JSDOM('<!doctype html><body></body>');
    const document = dom.window.document;
    const card = document.createElement('div');
    const overlay = document.createElement('div');
    overlay.id = `anima-${kind}-selector-overlay`;
    overlay.getClientRects = () => overlay.style.display === 'none' ? [] : [{}];
    overlay.inert = false;
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    const item = {id:`weilin:${kind}:fixture`,name:`隔离${kind}资料`,shared:true,isCustom:custom,...options.item};
    const key = options.selectionKey || `shared:${item.id}`;
    card.dataset[kind === 'character' ? 'selectorKey' : 'key'] = key;
    const record = {id:item.id,name:item.name,selectorKey:key,nickname:'',groupIds:['default'],isCustom:false};
    const favoriteSet = new Set(initialFavorite ? [key] : []);
    const favoriteMap = new Map(initialFavorite ? [[key,record]] : []);
    const favoritesConfig = Object.fromEntries(kinds.map(kind => [kind, {groups:[],items:[]} ]));
    const selected = new Set(['previous-selection']);
    const posts = [];
    const frames = [];
    const legacy = kind === 'character' || kind === 'artist';
    const createEl = (tag, className) => {
        const element = document.createElement(tag);
        if (className) element.className = className;
        return element;
    };
    const bindings = {
        document, card, overlay, modalOverlay:overlay, item, itemKey:key, key,
        requestAnimationFrame:callback => frames.push(callback), getComputedStyle:element => dom.window.getComputedStyle(element),
        isFavorite:initialFavorite, favoriteSet, favoriteMap, favoritesConfig,
        groups:[{id:'default',name:'隔离默认收藏',isSystem:true}], unresolvedFavoriteItems:[],
        getCharacterItemKey:() => key, getPromptItemKey:() => key, getItemKey:() => key,
        getPromptFavoriteSourceKey:options.getPromptFavoriteSourceKey || favoriteSourceHelper,
        characterData:options.sourceData || [item], clothingData:options.sourceData || [item],
        backgroundData:options.sourceData || [item], poseData:options.sourceData || [item],
        artistItemsByKey:new Map((options.sourceData || [item]).map((value,index)=>[index,value])),
        selectedCharacters:selected, selectedArtists:selected, selectedClothing:selected,
        selectedBackground:selected, selectedPose:selected,
        t:translate, createEl, heartIcon:favorite => `<svg fill="${favorite ? 'accent' : 'none'}"></svg>`,
        setTimeout:() => 0, confirm:() => false, activeCategory:'all',
        activeFilters:{type:'all',collection:'all'}, activeSort:'name-asc',
        renderSidebar:() => {}, triggerFilter:() => {},
        renderCurrentPage:() => options.onRender?.({document,card,overlay}),
        favoritesKey:kind, sharedKind:kind,
        offerFavoritesConflictRecovery:() => { throw new Error('Unexpected recovery path'); },
        fetch:async (url, options) => {
            assert.equal(url, '/anima-tools/favorites');
            assert.equal(options.method, 'POST');
            posts.push({...options,payload:JSON.parse(options.body)});
            await bindings.onFetch?.({document,card,overlay});
            return {ok:true,status:200,headers:{get:name => name === 'ETag' ? '"fixture-etag-next"' : null},text:async () => ''};
        },
    };
    bindings.onFetch = options.onFetch;
    const functions = [functionSource(source, 'saveFavorites')];
    if (kind === 'character') functions.push(functionSource(source, 'makeFavoriteRecord'));
    if (!legacy) functions.push(functionSource(source, 'iconButton'),functionSource(source, 'toggleFavorite'));
    const focusUi=options.sourceUi || uiSource;
    const helperStart=focusUi.indexOf('export function captureSelectorFavoriteFocus('),helperEnd=focusUi.indexOf('\n}',helperStart);
    const focusSource=focusUi.slice(helperStart,helperEnd+2).replace('export function','function');
    const factory = new Function(...Object.keys(bindings), `
        let favoriteItems = [];
        let favoritesSaveInFlight = false;
        let favoritesEtag = '"fixture-etag-before"';
        ${focusSource}
        ${functions.join('\n')}
        ${buttonSource(source, legacy)}
        return {button:${legacy ? 'favIcon' : 'favBtn'}, etag:() => favoritesEtag};
    `);
    const {button,etag} = factory(...Object.values(bindings));
    button.getClientRects = () => [{}];
    return {dom,button,posts,item,key,favoriteSet,selected,overlay,etag,frames,card};
}

export async function click(fixture) {
    const event = new fixture.dom.window.MouseEvent('click', {bubbles:true});
    await fixture.button.onclick(event);
    assert.equal(event.cancelBubble, true, 'Favorite handler stops card selection propagation');
    assert.deepEqual([...fixture.selected], ['previous-selection']);
    assert.equal(fixture.overlay.inert, false, 'Save restores selector interactivity');
}

for (const kind of kinds) {
    const fileKind = kind === 'style_quality' ? 'pose' : kind;
    const filename = `anima_${fileKind}_selector.js`;
    const source = read(sourceRoot, filename);
    hashes[filename] = crypto.createHash('sha256').update(fs.readFileSync(path.join(sourceRoot, filename))).digest('hex');
    if (kind === 'character' || kind === 'artist') {
        const before = read(backupRoot, filename);
        for (const initialFavorite of [false,true]) {
            const fixture = setup(kind, before, initialFavorite);
            await assert.rejects(click(fixture), {name:'ReferenceError',message:'memoBtn is not defined'});
            assert.equal(fixture.posts.length, 0);
            assert.equal(fixture.favoriteSet.has(fixture.key), !initialFavorite);
            results.push({kind,version:'before',operation:initialFavorite?'remove':'add',posts:0,error:'memoBtn is not defined',memoryChangedBeforeSave:true});
            fixture.dom.window.close();
        }
    }
    for (const initialFavorite of [false,true]) {
        const fixture = setup(kind, source, initialFavorite);
        const {button,item} = fixture;
        assert.equal(button.tagName, 'BUTTON');
        assert.equal(button.type, 'button');
        assert.equal(button.tabIndex, 0);
        assert.equal(button.classList.contains('anima-favorite-btn'), true);
        assert.equal(button.getAttribute('aria-pressed'), String(initialFavorite));
        assert.equal(button.getAttribute('aria-label'), `${initialFavorite?'取消收藏':'收藏'}: ${item.name}`);
        assert.equal(button.title, button.getAttribute('aria-label'));
        await click(fixture);
        assert.equal(fixture.posts.length, 1);
        assert.equal(fixture.posts[0].headers['If-Match'], '"fixture-etag-before"');
        assert.equal(fixture.etag(), '"fixture-etag-next"');
        const items = fixture.posts[0].payload[kind].items;
        assert.equal(items.length, initialFavorite ? 0 : 1);
        if (items.length) {
            assert.equal(items[0].name, item.name);
            assert.equal(items[0].selectorKey, fixture.key);
            assert.deepEqual(items[0].groupIds, ['default']);
        }
        if (kind === 'character' || kind === 'artist') {
            assert.equal(button.getAttribute('aria-pressed'), String(!initialFavorite));
            assert.equal(button.getAttribute('aria-label'), `${initialFavorite?'收藏':'取消收藏'}: ${item.name}`);
            button.onmouseout({stopPropagation(){}});
            const stroke = button.querySelector('svg').getAttribute('stroke');
            assert.equal(stroke.includes('--uw-accent'), !initialFavorite, 'Hover reads current favorite state');
            await click(fixture);
            assert.equal(fixture.posts.length, 2);
            assert.equal(fixture.posts[1].headers['If-Match'], '"fixture-etag-next"');
            assert.equal(button.getAttribute('aria-pressed'), String(initialFavorite));
        } else {
            const reopened = setup(kind, source, !initialFavorite);
            assert.equal(reopened.button.getAttribute('aria-pressed'), String(!initialFavorite));
            assert.equal(reopened.button.title, `${initialFavorite?'收藏':'取消收藏'}: ${item.name}`);
            reopened.dom.window.close();
        }
        results.push({kind,version:'current',operation:initialFavorite?'remove':'add',posts:fixture.posts.length,payloadCorrect:true,buttonAccessible:true,selectionUnchanged:true});
        fixture.dom.window.close();
    }
    if (kind === 'character' || kind === 'artist') {
        const fixture = setup(kind, source, false, true);
        assert.equal(fixture.button.title, `删除自定义项: ${fixture.item.name}`);
        assert.equal(fixture.button.getAttribute('aria-pressed'), null);
        assert.equal(fixture.button.classList.contains('anima-delete-btn'), true);
        await click(fixture);
        assert.equal(fixture.posts.length, 0, 'Canceled custom deletion does not save');
        fixture.dom.window.close();
    }
}
hashes['i18n.js'] = crypto.createHash('sha256').update(fs.readFileSync(path.join(sourceRoot, 'i18n.js'))).digest('hex');
const receipt = {passed:true,scope:'Production button creation, onclick, toggle and saveFavorites functions with jsdom and intercepted in-memory fetch; no browser or production-store writes',results,hashes};
fs.writeFileSync(path.join(root, 'selector_favorites_test_2026-10-01.json'), JSON.stringify(receipt,null,2));
console.log(JSON.stringify({passed:true,cases:results.length,scope:receipt.scope,receipt:path.join(root, 'selector_favorites_test_2026-10-01.json')}));
