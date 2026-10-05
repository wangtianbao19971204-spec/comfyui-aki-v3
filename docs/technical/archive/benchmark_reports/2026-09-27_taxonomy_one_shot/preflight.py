from common import *
import collections

build=read(HERE/'candidate_build.json');gate=read(HERE/'final_gate.json');measure=read(HERE/'measure_final/summary.json')
assert gate['passed'] and gate['replay']['amended_suppressed']==0 and not gate['replay']['round_wide_waivers']
assert gate['replay']['pending_rows']==0
source_sha=sha(STAGE/'semantic_refinements.py');data_sha=sha(HERE/'stage/data.json')
assert source_sha==build['source_sha256']==measure['source_sha256']==gate['source_sha256']['semantic_refinements.py']
assert data_sha==build['data_sha256']==measure['data_sha256']==gate['data_sha256']
assert read(HERE/'impact_review.json')['passed']
for name in ['boundary_tests_latest.json','focused_latest.json','stage_query_fixtures.json','data_invariants_and_rollback.json','strict_gate_tests.json','exact_contract_tests.json']:
    obj=read(HERE/name);assert obj['passed'],name
    if 'source_sha256' in obj:assert obj['source_sha256']==source_sha,name
    if 'engine_sha256' in obj:assert obj['engine_sha256']==source_sha,name
    if 'data_sha256' in obj:assert obj['data_sha256']==data_sha,name
base=read(HERE/'baseline.json')
for name,digest in base['source_sha256'].items():assert sha(SOURCES/name)==digest,name
for name in ['data.json','semantic_projection.json','semantic_refinements.py']:
    dst={'data.json':DATA,'semantic_projection.json':PROJECTION,'semantic_refinements.py':SOURCES/'semantic_refinements.py'}[name]
    assert sha(dst)==sha(HERE/'backup'/name)
for f in STAGE.glob('*.py'):compile(f.read_text(encoding='utf-8-sig'),str(f),'exec')
decisions={d['id']:d for d in read(HERE/'review_decisions.json')}
flags=[r for r in (json.loads(line) for line in (HERE/'scan_stage_final/coverage_index.jsonl').open(encoding='utf-8')) if r['flags']]
assert {r['id'] for r in flags}=={d['id'] for d in decisions.values() if d['decision']=='retain_current'}
for r in flags:
    d=decisions[r['id']];assert r['prompt_sha256']==d['prompt_sha256'] and r['flags']==[d['flag']]
scan=read(HERE/'scan_stage_final/scan_summary.json');assert scan['source_sha256']['semantic_refinements.py']==source_sha and scan['data_sha256']==data_sha
save(HERE/'residual_adjudication.json',{'raw_flags':len(flags),'accepted_current_classifications':[decisions[r['id']] for r in flags],'real_open_items':0,'scope':scan['totals'],'scanner_unchanged_from_audit':sha(OLD/'full_coverage_scan.py')==read(AUDIT/'before.json')['files'][str((OLD/'full_coverage_scan.py').relative_to(ROOT))]})
assert read(HERE/'residual_adjudication.json')['scanner_unchanged_from_audit']
frozen_dir=ROOT/'benchmark_reports/2026-09-20_consecutive_extension'
frozen={str(f.relative_to(ROOT)):sha(f) for f in frozen_dir.glob('round_*') if f.is_file() and f.suffix in ('.json','.jsonl')}
audit_before=read(AUDIT/'before.json')['files']
for relative,digest in frozen.items():
    if relative in audit_before:assert digest==audit_before[relative],relative
files=[*STAGE.glob('*.py'),HERE/'stage/data.json',HERE/'stage/semantic_projection.json',OLD/'release_gate.py',OLD/'strict_replay.py',OLD/'replay_amendments.json',OLD/'full_coverage_scan.py',HERE/'final_gate.json',HERE/'measure_final/summary.json',HERE/'measure_final/changes.json',HERE/'approved_operations.json',HERE/'impact_review.json',HERE/'residual_adjudication.json',HERE/'release.py',HERE/'live_cases.py',HERE/'scan_stage.py',HERE/'scan_stage_final/scan_summary.json',HERE/'scan_stage_final/coverage_index.jsonl']
strict=load_script(OLD/'strict_replay.py','preflight_strict')
strict.load_amendments(ROOT,OLD/'replay_amendments.json')
files.extend(ROOT/e['evidence']['path'] for e in read(OLD/'replay_amendments.json')['entries'])
assert read(HERE/'workbench_import_probe.json')['passed']
files.extend([HERE/'workbench_import_probe.json',HERE/'workbench_baseline_diagnostic.json'])
stage_sha={'data.json':data_sha,'semantic_projection.json':sha(HERE/'stage/semantic_projection.json'),'semantic_refinements.py':source_sha}
save(HERE/'preflight.json',{'created_at':now(),'passed':True,'stage_sha256':stage_sha,'bound_files':{str(f.relative_to(ROOT)):sha(f) for f in files},'frozen_hashes':frozen,'replay_checks':gate['replay']['checks'],'raw_flags':len(flags),'net_open':0,'changed_records':measure['changed_records'],'delta':measure['delta'],'user_authorization':'2026-09-27 user explicitly authorized one consolidated repair/release/total acceptance, replacing new-round stopping rule.'})
print(json.dumps({'passed':True,'bound_files':len(files),'frozen_files':len(frozen),'raw_flags':len(flags),'net_open':0,'delta':measure['delta']},ensure_ascii=False))
