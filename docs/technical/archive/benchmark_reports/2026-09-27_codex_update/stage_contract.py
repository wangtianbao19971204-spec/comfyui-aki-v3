from update_common import *
import ast,importlib.util,urllib.request,urllib.parse,time

def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8188'+path,timeout=240) as r:return json.loads(r.read())
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
assert sha(DATA)==sha(BACKUP/'data.json')
baseline_index=get('/prompt_selector/library/index')
baseline_page=get('/prompt_selector/library/prompts?limit=1&include_filter_counts=1')
save(HERE/'baseline_index.json',baseline_index);save(HERE/'baseline_counts.json',baseline_page['filter_counts'])
source=STAGE/'prompt_selector';generator=ROOT/'benchmark_reports/2026-09-25_taxonomy_convergence/reviewer_backend_v3/verify_g6.py'
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
data=read(STAGE/'data.json');doc=projection.read_projection(STAGE/'semantic_projection.json');counts=Counter();view={**data,'categories':[],'_semantic_class_labels':{**projection.CLASS_LABELS}}
for i,category in enumerate(data['categories']):
    prompts=[]
    for p in category['prompts']:
        decision=projection.decision_for(doc,category,p);counts[decision['disposition']]+=1
        if decision['disposition'] in ('reviewed','classified') and decision['manual_search_eligible']:prompts.append(entry(doc,category,p))
    view['categories'].append({**category,'prompts':prompts})
    if i%150==0:print('REBUILD_FOLDERS',i,flush=True)
view['_review_counts']=dict(counts);installed=harness['install'](view);installed['views'][False]=view;installed['index']=None
ns['_reviewed_library_data']=lambda pending=False:view if not pending else ns['_library_view_locked'](installed,pending)
query=harness['query'];initial=query();rebuilt=ns['_library_index_payload']()
save(HERE/'stage_index.json',rebuilt)

# Declare the entire data delta by exact changed IDs; no broad count waiver.
gate=load(ROOT/'benchmark_reports/2026-09-25_full_coverage/release_gate.py','update_gate');oldentry=gate.load_caller(P,T,R)
olddata=read(BACKUP/'data.json');before={p['id']:(c,p) for c in olddata['categories'] for p in c['prompts']};after={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
changed={o['id'] for o in read(HERE/'operations.json') if o['store']=='library'}
assert not read(HERE/'engine_phrase_radius.json')['baseline_hits']
delta={k:Counter() for k in ('theme','subcategory','detail','count')}
mapping={'theme':'theme_ids','subcategory':'subcategories','detail':'refinements','count':'count_markers'}
per_record=[]
for pid in sorted(changed):
    oldsemantic=oldentry(doc,*before[pid])['_semantic'] if pid in before else {}
    semantic=entry(doc,*after[pid])['_semantic']
    changes={}
    for kind,field in mapping.items():
        oldset=set(oldsemantic.get(field,[]));newset=set(semantic.get(field,[]))
        delta[kind].update(newset-oldset);delta[kind].subtract(oldset-newset)
        changes[kind]={'add':sorted(newset-oldset),'remove':sorted(oldset-newset)}
    per_record.append({'id':pid,'changes':changes})
expected={}
for kind in mapping:
    expected[kind]=Counter(baseline_page['filter_counts'][kind]);expected[kind].update(delta[kind]);expected[kind]={k:v for k,v in expected[kind].items() if v}
    actual={k:v for k,v in initial['filter_counts'][kind].items() if v}
    assert actual==expected[kind],(kind,{k:(expected[kind].get(k),actual.get(k)) for k in set(expected[kind])|set(actual) if expected[kind].get(k)!=actual.get(k)})
assert initial['total']==baseline_page['total']+read(HERE/'stage_summary.json')['stats']['library_added']
assert all(initial['filter_counts']['detail'].get(n['id'],0)==n['count'] for children in rebuilt['filter_pool']['refinements'].values() for n in children)
cases=[{}, {'pool_filters':'detail:hair.long'}, {'pool_filters':'detail:hair.long;detail:hair.very_long','pool_mode':'all'}, {'query':'twintails'}, {'view':'favorites'}, {'usage':'positive','content_type':'atomic_tag'}, {'pool_filters':'count:1girl;detail:hair.long'}, {'pool_filters':'sub:光影效果'}, {'pool_filters':'detail:light_effect.soft'}, {'pool_filters':'sub:头饰与发饰;detail:hair.long'}]
checks=[]
for params in cases:
    first=query(**params);assert first==query(**params);checks.append({'params':params,'total':first['total'],'deterministic':True})
gate.SOURCES=source;gate.DATA=STAGE/'data.json';gate.PROJECTION=STAGE/'semantic_projection.json'
replay=gate.run_replay(projection,refinements,T,152,entry)
save(HERE/'historical_replay.json',replay)
from historical_compatibility import verify
compatibility=verify(gate,projection,refinements,T,entry,replay)
save(HERE/'declared_data_delta.json',{'changed_ids':sorted(changed),'deltas':{k:{key:v for key,v in d.items() if v} for k,d in delta.items()},'per_record':per_record})
save(HERE/'stage_contract.json',{'passed':True,'created_at':now(),'data_sha256':sha(STAGE/'data.json'),'engine_sha256':sha(source/'semantic_refinements.py'),'index_sha256':sha(HERE/'stage_index.json'),'indexed_records':initial['total'],'review_counts':dict(counts),'fixture_checks':fixture['count'],'historical_checks':compatibility['immutable_baseline_replay']['checks'],'query_checks':checks,'full_exact_count_delta':True,'unexplained_replay_failures':0,'publisher_revision_cases':2})
print('STAGE_CONTRACT_PASS',initial['total'],'FIXTURES',fixture['count'],'HISTORY',replay['checks'],flush=True)
