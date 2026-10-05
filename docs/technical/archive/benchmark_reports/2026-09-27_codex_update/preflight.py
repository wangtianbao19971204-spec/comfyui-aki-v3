from update_common import *
from db_fingerprint import fingerprint
import psutil
from PIL import Image

for name in ('data_validation.json','stage_contract.json','document_coverage_receipt.json','scan_adjudication.json','engine_boundary.json','historical_compatibility.json','image_link_validation.json'):
    r=read(HERE/name);assert r['passed'],name
    if 'data_sha256' in r:assert r['data_sha256']==sha(STAGE/'data.json'),name
    if 'engine_sha256' in r:assert r['engine_sha256']==sha(STAGE/'prompt_selector/semantic_refinements.py'),name
assert sha(DATA)==sha(BACKUP/'data.json')
assert sha(PROJECTION)==sha(BACKUP/'semantic_projection.json')
assert sha(PROD/'prompt_selector/semantic_refinements.py')==sha(BACKUP/'semantic_refinements.py')
assert sha(DATA.with_name('shared_pairs.json'))==sha(BACKUP/'shared_pairs.json')
db_before=fingerprint(BACKUP/'tags.db');assert fingerprint(DB)==db_before,'Live tag data changed since baseline'
db_after=fingerprint(STAGE/'tags.db')
receipts=read(HERE/'image_receipts.json');plan=read(HERE/'image_plan.json')
assert len(receipts)==len(plan)==8562
byimage={r['filename']:r for r in receipts};assert set(byimage)=={r['filename'] for r in plan}
for name,r in byimage.items():
    assert r['status']=='ok' and sha(STAGE/'images'/name)==r['sha256'],name
    with Image.open(STAGE/'images'/name) as im:im.verify()
    target=PROD/'user_data/prompt_selector/preview'/name
    if target.exists():assert sha(target)==r['sha256'],'Collision with existing preview'
frozen={str(f.relative_to(ROOT)):sha(f) for f in (ROOT/'benchmark_reports/2026-09-20_consecutive_extension').glob('round_*') if f.is_file() and f.suffix in ('.json','.jsonl')}
prior=read(ROOT/'benchmark_reports/2026-09-27_taxonomy_one_shot/preflight.json')['frozen_hashes']
assert frozen==prior
listeners=sorted({c.pid for c in psutil.net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN and c.laddr and c.laddr.port==8188})
assert listeners==[31012],listeners
proc=psutil.Process(31012);assert abs(proc.create_time()-1790483183.7679129)<0.01
owner={'pid':proc.pid,'create_time':proc.create_time(),'command':proc.cmdline()}
stagefiles={name:STAGE/name for name in ('data.json','semantic_projection.json','tags.db','shared_pairs.json')};stagefiles['semantic_refinements.py']=STAGE/'prompt_selector/semantic_refinements.py'
files=[*HERE.glob('*.py'),HERE/'operations.json',HERE/'source_registry.json',HERE/'image_receipts.json',HERE/'image_link_validation.json',HERE/'stage_contract.json',HERE/'stage_index.json',HERE/'data_validation.json',HERE/'document_coverage_receipt.json',HERE/'scan_adjudication.json',HERE/'engine_boundary.json',HERE/'historical_compatibility.json',HERE/'declared_data_delta.json',HERE/'scan_stage_final/scan_summary.json',HERE/'scan_stage_final/coverage_index.jsonl']
save(HERE/'preflight.json',{'passed':True,'created_at':now(),'stage_sha256':{n:sha(p) for n,p in stagefiles.items()},'bound_files':{str(p.relative_to(ROOT)):sha(p) for p in files},'frozen_hashes':frozen,'db_before':db_before,'db_after':db_after,'owner':owner,'images':len(receipts),'image_bytes':sum(r['bytes'] for r in receipts),'authorization':'User authorized execution and specified every collection on the entire website; one combined release with backup, rollback, and live acceptance.'})
print('PREFLIGHT_PASS','FROZEN',len(frozen),'IMAGES',len(receipts),flush=True)
