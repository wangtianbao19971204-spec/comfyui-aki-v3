from common import *
import psutil, requests, shutil, os

stage=HERE/'stage';backup=HERE/'backup'
for name in ('data_validation.json','stage_contract.json','historical_compatibility.json','scan_adjudication.json','approved_classifications.json'):
    receipt=read(HERE/name);assert receipt['passed'],name
    if receipt.get('data_sha256'):assert receipt['data_sha256']==sha(stage/'data.json')
assert read(HERE/'presence_verification.json')['passed']
cue_checks=read(HERE/'cue_boundary_checks.json');assert cue_checks['passed']
assert cue_checks['rules_sha256']==sha(HERE/'review_cues.py')
assert cue_checks['source_correction_sha256']==sha(HERE/'corrected_cue_evidence.json')
approved=read(HERE/'approved_classifications.json')['decisions']
assert len(approved)==3 and all(r['review_method']=='assistant_direct_local_body_source_and_image_review' for r in approved)
approved_by_id={r['id']:r for r in approved}
image_hashes={}
for category in read(stage/'data.json')['categories']:
    for prompt in category['prompts']:
        if prompt['id'] in approved_by_id:
            path=PROD/'user_data/prompt_selector/preview'/prompt['image']
            assert sha(path)==approved_by_id[prompt['id']]['image_sha256']
            image_hashes[str(path.relative_to(ROOT))]=sha(path)
for name,path in {'data.json':DATA,'semantic_projection.json':PROJECTION}.items():assert sha(path)==sha(backup/name)
baseline=read(HERE/'baseline_runtime.json')
assert sha(DATA.with_name('shared_pairs.json'))==baseline['hashes']['shared_pairs.json']
assert sha(PROD/'prompt_selector/semantic_refinements.py')==baseline['hashes']['semantic_refinements.py']
source_hashes={path.name:sha(path) for path in (stage/'prompt_selector').glob('*.py')}
assert all(sha(PROD/'prompt_selector'/name)==h for name,h in source_hashes.items())
frozen={str(f.relative_to(ROOT)):sha(f) for f in (ROOT/'benchmark_reports/2026-09-20_consecutive_extension').glob('round_*') if f.is_file() and f.suffix in ('.json','.jsonl')}
assert frozen==read(UPDATE/'preflight.json')['frozen_hashes']
listeners=sorted({c.pid for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==8188})
assert listeners==[baseline['owner']['pid']]
proc=psutil.Process(listeners[0]);assert abs(proc.create_time()-baseline['owner']['create_time'])<0.01
queue=requests.get('http://127.0.0.1:8188/queue',timeout=20).json();assert not queue['queue_running'] and not queue['queue_pending']
# Exercise replacement and restoration on isolated copies, never the live files.
drill=HERE/'rollback_drill';drill.mkdir(exist_ok=True)
for name in ('data.json','semantic_projection.json'):
    dst=drill/name;shutil.copy2(backup/name,dst)
    shutil.copy2(stage/name,drill/(name+'.next'));os.replace(drill/(name+'.next'),dst);assert sha(dst)==sha(stage/name)
    shutil.copy2(backup/name,drill/(name+'.restore'));os.replace(drill/(name+'.restore'),dst);assert sha(dst)==sha(backup/name)
save(HERE/'rollback_drill.json',{'passed':True,'isolated_only':True,'created_at':now(),'files':['data.json','semantic_projection.json']})
files=[*HERE.glob('*.py'),HERE/'operations.json',HERE/'approved_classifications.json',HERE/'manual_reviews.json',HERE/'stage_contract.json',HERE/'stage_index.json',HERE/'data_validation.json',HERE/'historical_compatibility.json',HERE/'declared_data_delta.json',HERE/'scan_adjudication.json',HERE/'scan_stage/scan_summary.json',HERE/'scan_stage/coverage_index.jsonl',HERE/'rollback_drill.json',HERE/'source_reviews.json',HERE/'corrected_cue_evidence.json',HERE/'cue_boundary_checks.json',HERE/'presence_verification.json',HERE/'tag_db_baseline_fingerprint.json']
save(HERE/'preflight.json',{'passed':True,'created_at':now(),'stage_sha256':{name:sha(stage/name) for name in ('data.json','semantic_projection.json')},'bound_files':{str(p.relative_to(ROOT)):sha(p) for p in files},'frozen_hashes':frozen,'source_hashes':source_hashes,'owner':baseline['owner'],'untouched_hashes':{'shared_pairs.json':sha(DATA.with_name('shared_pairs.json')),'semantic_refinements.py':sha(PROD/'prompt_selector/semantic_refinements.py')},'authorization':'User explicitly requested accuracy verification followed by writeback; one combined release and full acceptance.'})
receipt=read(HERE/'preflight.json');receipt['untouched_image_hashes']=image_hashes;save(HERE/'preflight.json',receipt)
print('PREFLIGHT_PASSED',len(frozen),flush=True)
