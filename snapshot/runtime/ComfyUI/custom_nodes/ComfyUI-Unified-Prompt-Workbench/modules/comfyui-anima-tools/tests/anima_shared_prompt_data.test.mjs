import assert from "node:assert/strict";
import { register } from "node:module";

register('./browser_extension_loader.mjs', import.meta.url);
const events = new Map();
globalThis.window = {addEventListener: (name, handler) => events.set(name, handler)};
const shared = await import("../js/anima_shared_prompt_data.js");
let checks = 0;
const check = (actual, expected, message) => {assert.deepEqual(actual, expected, message); checks++;};
const taxonomy = {
    semantic_classes: {pose_action: '动作与姿势', clothing_accessory: '服装与配饰'},
    filter_pool: {subcategory: {pose_action: {'手势与肢体动作': 2}, clothing_accessory: {'裙装与礼服': 1}},
                  subcategory_values: {'手势与肢体动作': 'pose_action::手势与肢体动作', '裙装与礼服': 'clothing_accessory::裙装与礼服'}},
};
const decision = (changes = {}) => ({disposition: 'reviewed', manual_search_eligible: true,
    random_pool_eligible: true, strict_model_pool_eligible: true, usage: 'positive',
    content_type: 'fragment', primary_class: 'pose_action', theme_ids: ['pose_action'],
    subcategories: ['手势与肢体动作'], subcategory_owners: {'手势与肢体动作': 'pose_action'},
    binding: 'fixture-binding-a', ...changes});
const item = (id, changes = {}) => ({id, name: 'Wave', tags: ' waving , smile ', shared: true,
    source_category_id: 'source-a', source_category: 'Fixture/source', favorite: true,
    shared_category_paths: [{levels: ['WeiLin / 动作与姿势', '手势与肢体动作'], parent: 'WeiLin / 动作与姿势',
                            source: '手势与肢体动作', source_category_id: 'source-a'}],
    _semantic: decision(), ...changes});
const local = {id:'local-a', name:'Wave', tags:' waving , smile ', favorite:false};
const a = item('shared-a');
const b = item('shared-b');
check(shared.getSharedCategoryPaths(a), [], 'Categories require the current taxonomy, not stale source paths');
let requestLog = [];
let payload = {enabled:true, revision:'fixture-r1', items:[a,b], source_category_count:1,
               pending_prompt_count:2, quarantined_prompt_count:1, taxonomy_source_matches:false};
globalThis.fetch = async (url, options) => {
    requestLog.push({url, options});
    assert(url === '/prompt_selector/library/index' || url.startsWith('/anima-tools/shared-prompts?'));
    assert.equal(options.cache, 'no-store');
    await Promise.resolve();
    return {ok:true, json:async()=>url === '/prompt_selector/library/index' ? taxonomy : structuredClone(payload)};
};
await shared.loadSharedLibraryTaxonomy({revision:'fixture-r1'});
check(shared.getSharedCategoryPaths(a), [{levels:['动作与姿势','手势与肢体动作'],
    keys:['shared-theme:pose_action','shared-sub:pose_action::手势与肢体动作'], parent:'动作与姿势',source:'手势与肢体动作'}]);
check(shared.getSharedTopicSummary(a), ['动作与姿势 · 手势与肢体动作']);
check(shared.buildSharedCategoryTree([a,a,b,local]), [{key:'shared-theme:pose_action',name:'动作与姿势',label:'动作与姿势',count:2,
    children:[{key:'shared-sub:pose_action::手势与肢体动作',name:'手势与肢体动作',label:'手势与肢体动作',count:2,children:[]}]}]);
check(shared.mergePromptItems([local], [a,b,structuredClone(a)]).map(value=>value.id), ['local-a','shared-a','shared-b'], 'Only identical identity/payload repetitions collapse');
check(shared.mergePromptItems([], [a,{...a,tags:'edited same identity'}]).length, 2, 'Conflicting same-ID payloads survive review');
check(shared.mergePromptItems([], [a,{...a,source_namespace:'other-source'}]).length, 2, 'Origin namespaces remain distinct');
check(shared.mergeCharacterPromptItems([{name:'Same',copyright:'local'}], [{...a,name:'Same'}, {...b,name:'Same'}]).length, 3, 'Display-name equality never merges identities');
check(shared.getCharacterItemKey(a), 'shared:shared-a');
check(shared.getCharacterItemKey(local), 'local:local-a:');
check(shared.getCharacterItemKey({...local,isCustom:true}), 'custom:local-a');
check(shared.getCharacterItemKey(null), '');
check(shared.isReviewedSharedFragment(a), true);
for (const invalid of [{disposition:'pending'}, {manual_search_eligible:false}, {usage:'negative'}, {content_type:'template'}])
    check(shared.isReviewedSharedFragment({...a,_semantic:decision(invalid)}),false);
check(shared.isReviewedSharedFragment({...a,_semantic:decision({strict_model_pool_eligible:false})}),true);
check(shared.isReviewedSharedFragment({...a,_semantic:decision({strict_model_pool_eligible:false})},{random:true}),false);
check(shared.isReviewedSharedFragment(local),true);
check(shared.getPromptSearchRank(a,'Wave'),0);
check(shared.getPromptSearchRank(a,'Wa'),1);
check(shared.getPromptSearchRank(a,'smile'),2);
check(shared.getPromptSearchRank(a,'Fixture'),3);
check(shared.getPromptSearchRank(a,'absent'),Infinity);
check(shared.rankPromptSearchResults([{id:'body',tags:'Wave'},a],'wave').map(value=>value.id),['shared-a','body']);
const shuffled = shared.createStablePromptShuffle(value=>value.id);
check(shuffled([a,b]).map(value=>value.id),shuffled([b,a]).map(value=>value.id),'Shuffle priorities survive changed input order');
const matches = filters => shared.itemMatchesCategoryFilters(a,new Set(filters));
check(matches(['shared-theme:pose_action']),true);
check(matches(['shared-theme:clothing_accessory']),false);
check(matches(['shared-theme:pose_action','shared-source:source-a']),true);
check(matches(['shared-theme:pose_action','shared-source:source-b']),false,'Source intersects topic');
check(matches(['shared-sub:pose_action::手势与肢体动作']),true);
check(matches(['shared-sub:clothing_accessory::手势与肢体动作']),false,'Same label cannot cross semantic ownership');
check(matches(['shared-sub:pose_action::手势与肢体动作','shared-sub:clothing_accessory::裙装与礼服']),false,'Different-owner filters intersect');
check(matches([shared.makeSharedParentFilterKey('WeiLin / 动作与姿势')]),true);
check(matches([shared.makeSharedPathFilterKey(['WeiLin / 动作与姿势','手势与肢体动作'])]),true);
check(matches([shared.makeSharedChildFilterKey('WeiLin / 动作与姿势','手势与肢体动作')]),true);
const filters = new Set(['Dress','shared-theme:pose_action','shared-source:source-a']);
check(shared.hasSharedCategoryFilters(filters),true);
check(shared.normalizeSharedCategoryNavigationFilters(filters),true);
check([...filters],['shared-theme:pose_action','shared-source:source-a']);
check(shared.activateSharedCategoryNavigationFilter(filters,'shared-sub:pose_action::手势与肢体动作'),true);
check([...filters],['shared-source:source-a','shared-sub:pose_action::手势与肢体动作']);
check(shared.activateSharedCategoryNavigationFilter(filters,'shared-sub:pose_action::手势与肢体动作'),false);
check(shared.getSharedCategoryRequestFilter(filters),'shared-filters:["shared-source:source-a","shared-sub:pose_action::手势与肢体动作"]');
check(shared.pruneSharedCategoryFilters([a],new Set(['shared-theme:absent'])),true);
filters.add('Dress');
check(shared.removeSharedCategoryFilters(filters),true);
check([...filters],['Dress']);
check(shared.buildSharedSourceOptions([a,a,b,local]),[{id:'source-a',label:'Fixture/source',count:2}]);
check(shared.getSharedCodexDirectoryLevels('默认/角色'),[]);
requestLog=[];
const concurrent = await Promise.all([shared.loadMergedPromptItems('pose',[local]),shared.loadMergedPromptItems('pose',[local])]);
check(concurrent[0].map(value=>value.id),['shared-a','shared-b'],'Retired local arrays are not current shared authority');
check(concurrent[1],concurrent[0]);
check(requestLog.filter(value=>value.url.startsWith('/anima-tools')).length,1,'Concurrent requests share one in-flight read');
check(shared.getSharedPromptSyncStats('pose').changes,{added:0,updated:0,removed:0,unchanged:2,baseline:true});
await shared.loadMergedPromptItems('pose',[]);
check(requestLog.filter(value=>value.url.startsWith('/anima-tools')).length,2,'A later open rechecks revision');
payload={...payload,revision:'fixture-r2',items:[{...a,tags:'edited body'},item('shared-c')]};
const refreshed=await shared.refreshMergedPromptItems('pose',[]);
check(refreshed.map(value=>value.id),['shared-a','shared-c']);
check(shared.getSharedPromptSyncStats('pose').changes,{added:1,updated:1,removed:1,unchanged:0,baseline:false});
check(shared.getSharedPromptSyncMessage('pose').includes('新增 1 / 更新 1 / 删除 1'),true);
check(shared.getSharedPromptSyncMessage('pose').includes('待复核 2'),true);
check(shared.getSharedPromptSyncMessage('pose').includes('安全隔离 1'),true);
await shared.validateSharedPromptSelection('pose',refreshed);
await assert.rejects(()=>shared.validateSharedPromptSelection('pose',[a]),/资料已变更/);checks++;
payload={...payload,items:[{...refreshed[0],_semantic:decision({binding:'new-binding'})}]};
await assert.rejects(()=>shared.validateSharedPromptSelection('pose',[refreshed[0]]),/资料已变更/);checks++;
payload={...payload,items:[a,item('unreviewed',{_semantic:decision({disposition:'pending'})}),item('negative',{_semantic:decision({usage:'negative'})})]};
check((await shared.loadMergedPromptItems('pose',[])).map(value=>value.id),['shared-a']);
payload={enabled:false,revision:'unavailable',items:[]};
await assert.rejects(()=>shared.loadMergedPromptItems('pose',[]),/共享资料库不可用/);checks++;
payload={enabled:true,revision:'fixture-r3',items:[a]};
check((await shared.loadMergedPromptItems('pose',[])).map(value=>value.id),['shared-a'],'Failed reads do not poison later recovery');
events.get('anima-tools-shared-prompts-updated')();
check(shared.getSharedCategoryPaths(a),[],'Invalidation clears old taxonomy');
console.log(`PASS: ${checks} current shared prompt checks; stable identity, exact bodies, review eligibility, topic/source intersection, owned subcategories, concurrent reads, revision refresh, stale selection and recovery.`);
