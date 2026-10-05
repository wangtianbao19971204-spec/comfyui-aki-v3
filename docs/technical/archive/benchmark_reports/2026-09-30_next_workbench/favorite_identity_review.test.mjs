import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve('benchmark_reports/2026-09-30_next_workbench');
const stage = path.join(root,'isolated_selector_favorites/identity_stage/anima_prompt_identity.js');
const source = fs.readFileSync(stage,'utf8').replaceAll('export function','function');
const {resolvePromptFavorites,assignPromptSelectorKeys,getPromptFavoriteSourceKey,getPromptItemVariantKey,getPromptItemKey} = new Function(
    source+'\nreturn {resolvePromptFavorites,assignPromptSelectorKeys,getPromptFavoriteSourceKey,getPromptItemVariantKey,getPromptItemKey};'
)();
const base = 'shared:weilin:pose:review-1';
const item = {id:'weilin:pose:review-1',name:'Review Pose',shared:true,tags:'standing, hands up'};
const record = {id:item.id,name:item.name,selectorKey:base,nickname:'保留备注',groupIds:['default','personal'],extra:{keep:true}};
const cases = [];
function check(name,available,favorite,expectedResolved) {
    const result=resolvePromptFavorites(available,[favorite]);
    const resolved=result.map.size===1;
    cases.push({name,resolved,expectedResolved,sourceKey:getPromptFavoriteSourceKey(available[0],available),
        availableKeys:available.map(getPromptItemKey),map:[...result.map],unresolved:result.unresolved});
    if(!resolved)assert.deepEqual(result.unresolved,[favorite],'Unresolved metadata preserved');
}
const unique={...item,selectorKey:getPromptItemVariantKey(item)};
check('unique full variant binds canonical favorite',[unique],record,true);
const different={...item,tags:'sitting, hands down'};
check('same id distinct unkeyed bodies remain ambiguous',assignPromptSelectorKeys([{...item},{...different}]),record,false);
check('same id canonical plus distinct variant remains ambiguous',assignPromptSelectorKeys([{...item,selectorKey:base},{...different}]),record,false);
check('same id two explicit canonical different bodies remains ambiguous',[{...item,selectorKey:base},{...different,selectorKey:base}],record,false);
const oldVariant={...record,selectorKey:getPromptItemVariantKey(item)};
check('stale variant body not rebound to fresh unique source',[{...different,selectorKey:getPromptItemVariantKey(different)}],oldVariant,false);
check('unknown source preserved',[unique],{...record,selectorKey:'shared:weilin:pose:missing'},false);

const sharedSource=fs.readFileSync(path.resolve('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-anima-tools/js/anima_shared_prompt_data.js'),'utf8').replace(/\r\n/g,'\n');
const mergeStart=sharedSource.indexOf('export function mergePromptItems('),mergeEnd=sharedSource.indexOf('\n}',mergeStart);
const identityStart=sharedSource.indexOf('function mergeIdentity('),identityEnd=sharedSource.indexOf('\n}',identityStart);
const mergePromptItems=new Function(sharedSource.slice(identityStart,identityEnd+2)+'\n'+sharedSource.slice(mergeStart,mergeEnd+2).replace('export ','')+'\nreturn mergePromptItems;')();
const artistSource=fs.readFileSync(path.join(path.dirname(stage),'anima_artist_selector.js'),'utf8').replace(/\r\n/g,'\n');
const rememberStart=artistSource.indexOf('    const rememberArtistItems = items =>'),rememberEnd=artistSource.indexOf('\n    rememberArtistItems([...initialCatalog.items',rememberStart);
const remembered=new Map();
const identity= new Function(source+'\nreturn {getPromptItemBaseKey,getPromptItemVariantKey};')();
const remember=new Function('artistItemsByKey','assignPromptSelectorKeys','getPromptItemKey','mergePromptItems','getPromptItemBaseKey','getPromptItemVariantKey',artistSource.slice(rememberStart,rememberEnd)+'\nreturn rememberArtistItems;')(remembered,assignPromptSelectorKeys,getPromptItemKey,mergePromptItems,identity.getPromptItemBaseKey,identity.getPromptItemVariantKey);
const artistA={id:'weilin:artist:review-a',name:'Same Artist',shared:true,tags:'artist red'};
const artistB={...artistA,tags:'artist blue'};
remember([artistA]);remember([artistB]);
cases.push({name:'artist cross-page distinct body is retained',resolved:remembered.size===2,expectedResolved:true,retainedCount:remembered.size,retainedBodies:[...remembered.values()].map(value=>value.tags)});
const failures=cases.filter(result=>result.resolved!==result.expectedResolved);
const receiptPath=path.join(root,'favorite_identity_review_2026-10-01.json');
if(fs.existsSync(receiptPath)){
    const previous=JSON.parse(fs.readFileSync(receiptPath,'utf8'));
    if(!previous.passed)fs.writeFileSync(path.join(root,`favorite_identity_review_failure_${previous.cases.length}_cases_2026-10-01.json`),JSON.stringify(previous,null,2));
}
fs.writeFileSync(receiptPath,JSON.stringify({passed:!failures.length,scope:'Read-only staged identity module execution, no browser or production changes',cases,failures},null,2));
console.log(JSON.stringify({passed:!failures.length,cases:cases.length,failures:failures.map(({name,resolved,sourceKey})=>({name,resolved,sourceKey}))}));
if(failures.length)process.exitCode=1;
