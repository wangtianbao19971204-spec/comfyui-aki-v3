from update_common import *

pkg=types.ModuleType('update_final_engine');pkg.__path__=[str(STAGE/'prompt_selector')];sys.modules[pkg.__name__]=pkg
engine=importlib.import_module(pkg.__name__+'.semantic_refinements')
cases=[('very long snow white hair',True),('1girl, very_long_snow_white_hair, smile',True),('-1::very long snow white hair::, short hair',False),('no very long snow white hair, short hair',False),('short hair, negative prompt: very long snow white hair',False),('snow white dress, long hair',False),('snow white hair',False)]
for body,expected in cases:assert ('hair.very_long' in engine.extract_refinements(body,['头发与发型']))==expected,body
save(HERE/'engine_boundary.json',{'passed':True,'engine_sha256':sha(STAGE/'prompt_selector/semantic_refinements.py'),'cases':[{'input':b,'expected_very_long':v} for b,v in cases]})
scan=read(HERE/'scan_stage_final/scan_summary.json')
assert scan['data_sha256']==sha(STAGE/'data.json') and scan['source_sha256']['semantic_refinements.py']==sha(STAGE/'prompt_selector/semantic_refinements.py')
base={r['id']:r for r in (json.loads(l) for l in (ROOT/'benchmark_reports/2026-09-27_taxonomy_one_shot/scan_live_final/coverage_index.jsonl').open(encoding='utf-8')) if r['flags']}
flags=[r for r in (json.loads(l) for l in (HERE/'scan_stage_final/coverage_index.jsonl').open(encoding='utf-8')) if r['flags']]
assert len(flags)==len(base)==15
for row in flags:
    previous=base[row['id']];assert row['prompt_sha256']==previous['prompt_sha256'] and row['flags']==previous['flags']
save(HERE/'scan_adjudication.json',{'passed':True,'data_sha256':scan['data_sha256'],'engine_sha256':scan['source_sha256']['semantic_refinements.py'],'scope':scan['totals'],'raw_flags':len(flags),'unchanged_previously_adjudicated':15,'new_unresolved_flags':0,'baseline_adjudication':'../2026-09-27_taxonomy_one_shot/residual_adjudication.json','scope_note':'Structural/source/store checks cover the complete library. Semantic cues retain the established length, source, and eligibility exclusions; this is not a proof of perfect semantics for every entry.'})
print('SCAN_PASS',scan['totals'],'NO_NEW_FLAGS',flush=True)
