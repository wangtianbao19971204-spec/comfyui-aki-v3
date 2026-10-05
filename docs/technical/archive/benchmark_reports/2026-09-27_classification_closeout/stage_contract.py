from common import *
import ast, importlib.util, types
from collections import Counter

stage=HERE/'stage'; source=stage/'prompt_selector'
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod

generator=ROOT/'benchmark_reports/2026-09-25_taxonomy_convergence/reviewer_backend_v3/verify_g6.py'
tree=ast.parse(generator.read_text(encoding='utf-8'));function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_73_fixture')
for node in ast.walk(function):
    if isinstance(node,ast.Return) and isinstance(node.value,ast.Dict):node.value.keys.append(ast.Constant('harness'));node.value.values.append(ast.Name('ns',ast.Load()))
ast.fix_missing_locations(function)
helper={'Path':Path,'ROOT':ROOT,'CAND':source,'prod':source,'sha':sha,'types':types,'importlib':importlib,'sys':sys}
exec(compile(ast.Module([function],type_ignores=[]),str(generator),'exec'),helper)
fixture=helper['run_73_fixture'](source);harness=fixture['harness'];ns=harness['ns'];scope=harness['scope']
library=scope['scope']['load']('selector_library')
ns.update(COLLECTION_KINDS=library.COLLECTION_KINDS,CLASS_ROUTES=library.CLASS_ROUTES,collection_groups=library.collection_groups,prompt_collection=library.prompt_collection)
projection=scope['projection'];refinements=scope['refinements'];entry=ns['_library_entry']
data=read(stage/'data.json');doc=projection.read_projection(stage/'semantic_projection.json');counts=Counter();view={**data,'categories':[],'_semantic_class_labels':{**projection.CLASS_LABELS}}
for i,category in enumerate(data['categories']):
    prompts=[]
    for p in category['prompts']:
        decision=projection.decision_for(doc,category,p);counts[decision['disposition']]+=1
        if decision['disposition'] in ('reviewed','classified') and decision['manual_search_eligible']:prompts.append(entry(doc,category,p))
    view['categories'].append({**category,'prompts':prompts})
    if i%200==0:print('REBUILT_FOLDERS',i,flush=True)
view['_review_counts']=dict(counts);installed=harness['install'](view);installed['views'][False]=view;installed['index']=None
ns['_reviewed_library_data']=lambda pending=False:view if not pending else ns['_library_view_locked'](installed,pending)
query=harness['query'];initial=query();rebuilt=ns['_library_index_payload']()
save(HERE/'stage_index.json',rebuilt)
gate=load(ROOT/'benchmark_reports/2026-09-25_full_coverage/release_gate.py','verified_gate')
olddata=read(HERE/'backup/data.json');olddoc=read(HERE/'backup/semantic_projection.json')
before={p['id']:(c,p) for c in olddata['categories'] for p in c['prompts']};after={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
changed={o['id'] for o in read(HERE/'operations.json')}
delta={k:Counter() for k in ('theme','subcategory','detail','count')};mapping={'theme':'theme_ids','subcategory':'subcategories','detail':'refinements','count':'count_markers'};per_record=[]
for pid in sorted(changed):
    oldsemantic=entry(olddoc,*before[pid])['_semantic'];semantic=entry(doc,*after[pid])['_semantic'];changes={}
    for kind,field in mapping.items():
        oldset=set(oldsemantic.get(field,[]));newset=set(semantic.get(field,[]))
        delta[kind].update(newset-oldset);delta[kind].subtract(oldset-newset)
        changes[kind]={'add':sorted(newset-oldset),'remove':sorted(oldset-newset)}
    per_record.append({'id':pid,'changes':changes})
baseline=read(HERE/'baseline_query.json')
for kind in mapping:
    expected=Counter(baseline['filter_counts'][kind]);expected.update(delta[kind]);expected={k:v for k,v in expected.items() if v}
    actual={k:v for k,v in initial['filter_counts'][kind].items() if v}
    assert actual==expected,(kind,{k:(expected.get(k),actual.get(k)) for k in set(expected)|set(actual) if expected.get(k)!=actual.get(k)})
assert initial['total']==baseline['total']==324887
assert all(initial['filter_counts']['detail'].get(n['id'],0)==n['count'] for children in rebuilt['filter_pool']['refinements'].values() for n in children)
gate.SOURCES=source;gate.DATA=stage/'data.json';gate.PROJECTION=stage/'semantic_projection.json'
replay=gate.run_replay(projection,refinements,T,152,entry)
save(HERE/'historical_replay.json',replay)
# The previous accepted publisher-body amendments remain bound to their exact hashes.
prior=read(UPDATE/'historical_compatibility.json'); prior_failure=prior['staged_replay_before_revision_adjudication']
assert set(replay['binding_failures'])==set(prior_failure['binding_failures'])
assert replay['failures']==prior_failure['failures']==2 and all(x['kind']=='ledger_body_hash_mismatch' for x in replay['failure_sample'])
for revision in prior['approved_source_revisions']:
    pid=revision['id']; assert pid not in changed
    assert digest(after[pid][1]['prompt'])==revision['new_body_sha256']
    semantic=entry(doc,*after[pid])['_semantic']
    for check in revision['checks']:
        values=semantic['refinements'] if check['operation'].endswith('nodes') else semantic['subcategories']
        assert (check['target'] in values)==(not check['operation'].startswith('remove'))
save(HERE/'historical_compatibility.json',{'passed':True,'checks':replay['checks'],'unexplained_failures':0,'retained_hash_bound_publisher_amendments':prior['approved_source_revisions'],'prior_receipt_sha256':sha(UPDATE/'historical_compatibility.json')})
cases=[{}, {'pool_filters':'detail:hair.long'},{'pool_filters':'detail:hair.long;detail:hair.very_long','pool_mode':'all'},{'query':'twintails'},{'view':'favorites'},{'usage':'positive','content_type':'atomic_tag'},{'pool_filters':'count:1girl;detail:hair.long'},{'pool_filters':'sub:光影效果'}]
checks=[]
for params in cases:
    first=query(**params); assert first==query(**params);checks.append({'params':params,'total':first['total'],'deterministic':True})
save(HERE/'declared_data_delta.json',{'changed_ids':sorted(changed),'deltas':{k:{key:v for key,v in d.items() if v} for k,d in delta.items()},'per_record':per_record})
save(HERE/'stage_contract.json',{'passed':True,'created_at':now(),'data_sha256':sha(stage/'data.json'),'projection_sha256':sha(stage/'semantic_projection.json'),'engine_sha256':sha(source/'semantic_refinements.py'),'index_sha256':sha(HERE/'stage_index.json'),'indexed_records':initial['total'],'fixture_checks':fixture['count'],'historical_checks':replay['checks'],'query_checks':checks,'full_exact_count_delta':True,'unexplained_replay_failures':0})
print('STAGE_CONTRACT_PASS',initial['total'],'FIXTURES',fixture['count'],'HISTORY',replay['checks'],flush=True)
