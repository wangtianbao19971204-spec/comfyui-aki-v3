from common import *

scan=read(HERE/'scan_stage/scan_summary.json')
assert scan['data_sha256']==sha(HERE/'stage/data.json')
assert scan['projection_sha256']==sha(HERE/'stage/semantic_projection.json')
assert scan['source_sha256']['semantic_refinements.py']==sha(PROD/'prompt_selector/semantic_refinements.py')
def flags(path):
    return {r['id']:r for r in (json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()) if r['flags']}
before=flags(UPDATE/'scan_stage_final/coverage_index.jsonl');after=flags(HERE/'scan_stage/coverage_index.jsonl')
assert set(before)==set(after) and len(after)==15
for pid,row in after.items():
    assert row['flags']==before[pid]['flags'] and row['prompt_sha256']==before[pid]['prompt_sha256'],pid
save(HERE/'scan_adjudication.json',{'passed':True,'created_at':now(),'data_sha256':scan['data_sha256'],'projection_sha256':scan['projection_sha256'],'engine_sha256':scan['source_sha256']['semantic_refinements.py'],'scope':scan['totals'],'raw_flags':15,'unchanged_previously_adjudicated':15,'new_unresolved_flags':0,'prior_adjudication_sha256':sha(UPDATE/'scan_adjudication.json'),'scope_note':'Full structural and identity validation covers 324891 records; the unchanged semantic cue scanner covers only its declared 73869-record scope. This does not certify every excluded or unreviewed prompt.'})
print('FULL_SCAN_NO_NEW_FLAGS',scan['totals']['records'],'CUE_SCOPE',scan['totals']['in_scope'],flush=True)
