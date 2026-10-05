"""Independent read-only, hash-bound full selector index comparison."""
from __future__ import annotations
import ast, copy, hashlib, importlib.util, json, sys, time, types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CYCLE = ROOT / 'benchmark_reports/2026-09-25_taxonomy_convergence/cycle_01'
CAND = CYCLE / 'candidate_v3/prompt_selector'
MANIFEST = CYCLE / 'candidate_freeze_manifest_003.json'
BASELINE = CYCLE / 'baseline.json'
GEN = 'g6_20260925_001'
OUTS = [HERE / f'{GEN}_{n}.json' for n in ('receipt','baseline_index','candidate_index','diff','counts')]
for p in OUTS:
    if p.exists(): raise FileExistsError(p)

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump_new(p, obj):
    with p.open('x', encoding='utf-8', newline='\n') as f: json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))

manifest=json.loads(MANIFEST.read_text(encoding='utf-8')); base=json.loads(BASELINE.read_text(encoding='utf-8'))
assert sha(MANIFEST)=='08f6429cf7a4071c7d6d38dae0fd732e3d4590a6fed95cbf5b7f573ff6ed733e'
assert sha(BASELINE)=='aa8b8eadd8e09de9bdd50797f44d7491826b319149bc07754398450ac160142d'
for name, item in manifest['candidate_sources'].items(): assert sha(Path(item['path']))==item['sha256'], name
prod=ROOT/'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector'
data_path=prod.parent/'user_data/prompt_selector/data.json'; projection_path=prod.parent/'user_data/prompt_selector/semantic_projection.json'
assert sha(data_path)==base['expected_sha256']['data']
assert sha(prod/'semantic_refinements.py')==base['expected_sha256']['semantic']
assert sha(projection_path)==base['actual_sha256']['projection']
data=json.loads(data_path.read_text(encoding='utf-8')); doc=json.loads(projection_path.read_text(encoding='utf-8'))

def run_73_fixture(selector_path):
    low_path=ROOT/'benchmark_reports/2026-09-20_taxonomy_audit/verify_filter_pool.py'
    mid_path=ROOT/'benchmark_reports/2026-09-20_topic_drilldown/verify_backend.py'
    high_path=ROOT/'benchmark_reports/2026-09-23_consecutive_backlog_wave1/verify_linkage_backend.py'
    low=low_path.read_text(encoding='utf-8').split("result = {'checks': checks")[0]
    package_name='pool_verification_candidate' if Path(selector_path)==CAND else 'pool_verification_baseline'
    low=low.replace("spec = importlib.util.spec_from_file_location('pool_verification.' + name, SELECTOR / (name + '.py'))",
      "module_path = SELECTOR / (name + '.py')\n    if not module_path.exists(): module_path = PRODUCTION_SELECTOR / (name + '.py')\n    spec = importlib.util.spec_from_file_location('pool_verification.' + name, module_path)")
    low=low.replace("package = types.ModuleType('pool_verification')",f"package = types.ModuleType('{package_name}')")
    low=low.replace("'pool_verification.' + name",f"'{package_name}.' + name")
    old_selector="SELECTOR = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector'"
    low=low.replace(old_selector, f"SELECTOR = Path(r'{selector_path}')\nPRODUCTION_SELECTOR = Path(r'{prod}')")
    if Path(selector_path)==CAND:
        low=low.replace("'selector_subcategories': projection.selector_subcategories,",
          "'selector_subcategories': projection.selector_subcategories, 'soft_light_modifier_cue_allowed': projection.soft_light_modifier_cue_allowed,")
    mid=mid_path.read_text(encoding='utf-8').split("result = {'passed': len(checks)")[0]
    mid=mid.replace('source = old_suite.read_text(encoding=\'utf-8\').split("result = {\'checks\': checks")[0]', f'source = {low!r}')
    high=high_path.read_text(encoding='utf-8').split("result = {'checks': checks")[0]
    old_exec="exec(compile(previous.read_text(encoding='utf-8').split(\"result = {'passed': len(checks)\")[0], str(previous), 'exec'), scope)"
    high=high.replace(old_exec,"exec(compile(middle_source, str(previous), 'exec'), scope)")
    ns={'__file__':str(high_path),'middle_source':mid}
    exec(compile(high,str(high_path),'exec'),ns)
    backend_ns=ns['ns']; entry=backend_ns['_library_entry']
    assert entry.__code__.co_filename==str(Path(selector_path)/'prompt_selector.py')
    if Path(selector_path)==CAND:
        wired=entry.__globals__.get('soft_light_modifier_cue_allowed') is ns['scope']['projection'].soft_light_modifier_cue_allowed
    else:
        wired=entry.__globals__.get('decision_for') is ns['scope']['projection'].decision_for
    ns['check']('source_faithful_entry_uses_selected_projection_helpers',wired)
    assert len(ns['checks'])==73, f"candidate fixture count {len(ns['checks'])} != 73"
    return {'checks':ns['checks'],'count':len(ns['checks']), 'harness_sha256':{str(p):sha(p) for p in (low_path,mid_path,high_path)}}

candidate_fixture=run_73_fixture(CAND)
baseline_fixture=run_73_fixture(prod)

# Reuse the established read-only backend namespace and compile exact source functions.
template=ROOT/'benchmark_reports/2026-09-20_taxonomy_audit/verify_filter_pool.py'
source=template.read_text(encoding='utf-8').split("result = {'checks': checks")[0]
source=source.replace("projection = load('semantic_projection')", "projection = load('semantic_projection')\nrefinements = load('semantic_refinements')")
source=source.replace("'Counter': Counter,", "'REFINEMENT_NODES': refinements.REFINEMENT_NODES, 'REFINEMENT_VERSION': refinements.REFINEMENT_VERSION, 'extract_refinements': refinements.extract_refinements, 'Counter': Counter,")
scope={'__file__':str(template)}; exec(compile(source,str(template),'exec'),scope)
base_ns=dict(scope['namespace']); taxonomy=scope['taxonomy']; checks=[]
library=scope['load']('selector_library')
for environment in (base_ns,):
    environment.update(COLLECTION_KINDS=library.COLLECTION_KINDS, CLASS_ROUTES=library.CLASS_ROUTES,
      collection_groups=library.collection_groups, prompt_collection=library.prompt_collection)

def load_candidate(name):
    pkg='review_g6_candidate'; package=sys.modules.get(pkg)
    if package is None: package=types.ModuleType(pkg); package.__path__=[str(CAND)]; sys.modules[pkg]=package
    spec=importlib.util.spec_from_file_location(pkg+'.'+name,CAND/(name+'.py'))
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod
cp=load_candidate('semantic_projection'); cr=load_candidate('semantic_refinements')
ns=dict(base_ns)
tree=ast.parse((CAND/'prompt_selector.py').read_text(encoding='utf-8'))
funcnames={'_library_entry','_library_index_payload'}
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in funcnames]
exec(compile(ast.Module(nodes,type_ignores=[]),str(CAND/'prompt_selector.py'),'exec'),ns)
ns.update(decision_for=cp.decision_for, selector_subcategories=cp.selector_subcategories,
          semantic_themes=cp.semantic_themes, soft_light_modifier_cue_allowed=cp.soft_light_modifier_cue_allowed,
          extract_refinements=cr.extract_refinements, REFINEMENT_NODES=cr.REFINEMENT_NODES,
          REFINEMENT_VERSION=cr.REFINEMENT_VERSION)
ns.update(COLLECTION_KINDS=library.COLLECTION_KINDS, CLASS_ROUTES=library.CLASS_ROUTES,
          collection_groups=library.collection_groups, prompt_collection=library.prompt_collection)
assert ns['_library_entry'].__code__.co_filename==str(CAND/'prompt_selector.py')
assert base_ns['decision_for'] is scope['projection'].decision_for and base_ns['extract_refinements'] is scope['refinements'].extract_refinements
assert ns['decision_for'] is cp.decision_for and ns['extract_refinements'] is cr.extract_refinements

def build(projection, entry, source_data):
    view={**source_data, 'categories':[], '_semantic_class_labels':{**projection.CLASS_LABELS}}
    dispositions={}
    for cat in source_data.get('categories',[]):
        prompts=[]
        for prompt in cat.get('prompts',[]):
            dec=projection.decision_for(doc,cat,prompt); dispositions[dec.get('disposition','?')]=dispositions.get(dec.get('disposition','?'),0)+1
            if dec.get('disposition') in ('reviewed','classified') and dec.get('manual_search_eligible'):
                prompts.append(entry(doc,cat,prompt))
        view['categories'].append({**cat,'prompts':prompts})
    view['_review_counts']=dispositions
    ns['_LIBRARY_STATE']={'index':None,'views':{False:view}}
    ns['_reviewed_library_data']=lambda pending=False:view
    return ns['_library_index_payload'](), view

started=time.monotonic()
bp=scope['projection']; be=ns['_library_entry']
# Preserve original production entry from selector source, distinct from candidate implementation.
prod_tree=ast.parse((prod/'prompt_selector.py').read_text(encoding='utf-8'))
prod_entry=next(n for n in prod_tree.body if isinstance(n,ast.FunctionDef) and n.name=='_library_entry')
prod_ns=dict(base_ns); exec(compile(ast.Module([prod_entry],type_ignores=[]),str(prod/'prompt_selector.py'),'exec'),prod_ns)
# Existing index routine is used for baseline, candidate index routine for frozen source; same implementation contract.
prod_index=next(n for n in prod_tree.body if isinstance(n,ast.FunctionDef) and n.name=='_library_index_payload')
exec(compile(ast.Module([prod_index],type_ignores=[]),str(prod/'prompt_selector.py'),'exec'),prod_ns)
assert prod_ns['_library_entry'].__globals__['decision_for'] is bp.decision_for
assert prod_ns['_library_entry'].__globals__['extract_refinements'] is scope['refinements'].extract_refinements
prod_ns.update(COLLECTION_KINDS=library.COLLECTION_KINDS, CLASS_ROUTES=library.CLASS_ROUTES,
               collection_groups=library.collection_groups, prompt_collection=library.prompt_collection)

def build_ns(namespace, projection, entry, source_data):
    view={**source_data,'categories':[],'_semantic_class_labels':{**projection.CLASS_LABELS}}
    counts={}
    for cat in source_data.get('categories',[]):
        ps=[]
        for prompt in cat.get('prompts',[]):
            d=projection.decision_for(doc,cat,prompt); key=d.get('disposition','?'); counts[key]=counts.get(key,0)+1
            if key in ('reviewed','classified') and d.get('manual_search_eligible'): ps.append(entry(doc,cat,prompt))
        view['categories'].append({**cat,'prompts':ps})
    view['_review_counts']=counts
    namespace['_LIBRARY_STATE']={'index':None,'views':{False:view}}
    namespace['_reviewed_library_data']=lambda pending=False:view
    return namespace['_library_index_payload'](),view,counts

# Prove separate caller environments on one real eligible record before the full scan.
small=None
for category in data.get('categories',[]):
    for prompt in category.get('prompts',[]):
        decision=cp.decision_for(doc,category,prompt)
        if decision.get('disposition') in ('reviewed','classified') and decision.get('manual_search_eligible'):
            small={'categories':[{**category,'prompts':[prompt]}]}; break
    if small: break
assert small is not None
small_base,_,_=build_ns(prod_ns,bp,prod_ns['_library_entry'],small)
small_candidate,_,_=build_ns(ns,cp,ns['_library_entry'],small)
assert small_base['total_prompts']==small_candidate['total_prompts']==1
assert prod_ns['_library_entry'].__globals__['extract_refinements'] is scope['refinements'].extract_refinements
assert ns['_library_entry'].__globals__['extract_refinements'] is cr.extract_refinements

bi,bv,bc=build_ns(prod_ns,bp,prod_ns['_library_entry'],data)
ci,cv,cc=build_ns(ns,cp,ns['_library_entry'],data)
assert bi['total_prompts']==len([p for c in bv['categories'] for p in c['prompts']])
assert ci['total_prompts']==len([p for c in cv['categories'] for p in c['prompts']])
sys.path.insert(0,str(ROOT/'benchmark_reports/2026-09-23_consecutive_round135_batch2_expression_gaze_pose_release'))
import transaction_common as common
contract=common.assert_complete_index_contract(ci)
def nodes_by_prompt(view):
    out={}
    for cat in view['categories']:
        for p in cat['prompts']:
            sem=p['_semantic']; out[p['id']]={'category':cat['id'],'parent_ids':sorted(set(sem.get('subcategories',[]))),
              'node_ids':sorted(set(sem.get('refinements',[]))), 'prompt_sha256':hashlib.sha256(p.get('prompt','').encode()).hexdigest()}
    return out
brows,crows=nodes_by_prompt(bv),nodes_by_prompt(cv)
diff=[]
for ident in sorted(set(brows)|set(crows)):
    b=brows.get(ident); c=crows.get(ident)
    if b!=c:
        src=next((p for cat in data['categories'] for p in cat.get('prompts',[]) if p.get('id')==ident),{})
        diff.append({'id':ident,'category':(c or b)['category'],'prompt_sha256':(c or b)['prompt_sha256'],
          'baseline_parent_ids':b['parent_ids'] if b else [],'candidate_parent_ids':c['parent_ids'] if c else [],
          'baseline_node_ids':b['node_ids'] if b else [],'candidate_node_ids':c['node_ids'] if c else [],
          'baseline_eligible':b is not None,'candidate_eligible':c is not None})
for item in diff:
    assert len(item['prompt_sha256'])==64
assert len({x['id'] for x in diff})==len(diff)
from collections import Counter
parent_counts=Counter(); node_counts=Counter()
for category in cv['categories']:
    for prompt in category['prompts']:
        sem=prompt['_semantic']; parent_counts.update(set(sem.get('subcategories',[]))); node_counts.update(set(sem.get('refinements',[])))
pool=ci['filter_pool']; actual_node_counts={n['id']:n['count'] for children in pool['refinements'].values() for n in children}
assert all(actual_node_counts.get(identity,0)==count for identity,count in node_counts.items())
assert all(count<=parent_counts.get(cr.REFINEMENT_NODES[identity]['parent'],0) for identity,count in node_counts.items())
counts_doc={'schema':'g6-dynamic-counts/v1','parent_counts':dict(sorted(parent_counts.items())),
 'node_counts':dict(sorted(node_counts.items())),'indexed_node_counts':dict(sorted(actual_node_counts.items())),
 'parent_count_total':len(parent_counts),'populated_node_count':len(node_counts)}
assert ns['_library_entry'].__globals__['extract_refinements'] is cr.extract_refinements
assert ns['_library_entry'].__globals__['decision_for'] is cp.decision_for
for path,obj in zip(OUTS[1:],(bi,ci,diff,counts_doc)): dump_new(path,obj)
receipt={'schema':'independent-g6-backend/v1','generation':GEN,'passed':True,'checks':[
 'freeze and baseline hashes match','candidate _library_entry compiled from frozen source','baseline and candidate complete indexes built from locked data/projection','unique changed record inventory uses ID and prompt hash only','no prompt body serialized'],
 'input_sha256':{'freeze_manifest':sha(MANIFEST),'baseline_lock':sha(BASELINE),'data':sha(data_path),'projection':sha(projection_path),
  'baseline_semantic':sha(prod/'semantic_refinements.py'),'candidate_sources':{n:sha(CAND/n) for n in ('semantic_projection.py','semantic_refinements.py','prompt_selector.py')}},
 'full_library':{'raw_records':sum(len(c.get('prompts',[])) for c in data['categories']),'baseline_indexed':bi['total_prompts'],'candidate_indexed':ci['total_prompts'],
  'baseline_dispositions':bc,'candidate_dispositions':cc,'elapsed_seconds':round(time.monotonic()-started,2)},
 'changed_records':len(diff),'changed_ids':sorted(x['id'] for x in diff),'baseline_index_sha256':hashlib.sha256(OUTS[1].read_bytes()).hexdigest(),
 'candidate_index_sha256':hashlib.sha256(OUTS[2].read_bytes()).hexdigest(),'diff_sha256':hashlib.sha256(OUTS[3].read_bytes()).hexdigest(),
 'counts_sha256':hashlib.sha256(OUTS[4].read_bytes()).hexdigest(),
 'approval_manifest':'pending; no approved operation set was supplied','production_mutated':False}
dump_new(OUTS[0],receipt)
print(json.dumps(receipt,ensure_ascii=False,indent=2))
