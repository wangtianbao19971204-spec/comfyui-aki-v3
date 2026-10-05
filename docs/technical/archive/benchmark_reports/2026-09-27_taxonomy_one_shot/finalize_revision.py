"""Advance the library revision after the accepted classification transaction."""
from common import *
import os, shutil, urllib.request, urllib.error, psutil, subprocess

release=read(HERE/'release_receipt.json');assert release['passed'] and release['phase']=='accepted'
pre=read(HERE/'preflight.json');before_sha=pre['stage_sha256']['data.json']
assert sha(DATA)==before_sha and sha(SOURCES/'semantic_refinements.py')==pre['stage_sha256']['semantic_refinements.py']
def get(path,timeout=600):
    with urllib.request.urlopen('http://127.0.0.1:8188'+path,timeout=timeout) as response:return json.loads(response.read())
def queue_empty():
    q=get('/queue',20);assert not q['queue_running'] and not q['queue_pending']
def listeners():return sorted({c.pid for c in psutil.net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN and c.laddr and c.laddr.port==8188})
assert listeners()==[release['production']['pid']]
queue_empty();old_index=get('/prompt_selector/library/index');old_revision=get('/prompt_selector/library/revision')['revision']
work=HERE/'revision_finalize';work.mkdir(exist_ok=False)
payload=read(DATA);assert payload['last_modified']==old_revision
shutil.copy2(DATA,work/'data_before.json')
writer=load_script(OLD/'parent_correction_stage.py','revision_writer').deployed_writer()
new_revision=datetime.now().isoformat();payload['last_modified']=new_revision
new_file=work/'data_after.json';new_file.write_bytes(writer(payload))
payload['last_modified']=old_revision
assert writer(payload)==(work/'data_before.json').read_bytes()
del payload
new_sha=sha(new_file)
receipt={'created_at':now(),'phase':'prepared','passed':False,'before_data_sha256':before_sha,'final_data_sha256':new_sha,'old_revision':old_revision,'new_revision':new_revision,'only_change':'top-level last_modified','records_and_classifications_byte_equivalent':True,'engine_sha256':sha(SOURCES/'semantic_refinements.py'),'no_restart':True}
save(work/'receipt.json',receipt)
state=read(HERE/'EXECUTION_STATE.json');state.update(status='revision_cache_finalization',production_mutated=True);save(HERE/'EXECUTION_STATE.json',state)
queue_empty();assert sha(DATA)==before_sha
tmp=DATA.with_name('data.json.revision-replacing')
with new_file.open('rb') as src,tmp.open('wb') as dst:
    shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
assert sha(DATA)==before_sha
os.replace(tmp,DATA)
receipt['phase']='revision_applied';save(work/'receipt.json',receipt)
assert sha(DATA)==new_sha
assert get('/prompt_selector/library/revision',60)['revision']==new_revision
request=urllib.request.Request('http://127.0.0.1:8188/prompt_selector/collections/update',data=b'{}',headers={'Content-Type':'application/json','If-Match':old_revision},method='POST')
try:
    urllib.request.urlopen(request,timeout=60)
    raise AssertionError('Stale revision was not rejected')
except urllib.error.HTTPError as error:
    assert error.code==409,error.code
    receipt['stale_revision_rejected']=json.loads(error.read())
print('REVISION_UPDATED_AND_STALE_WRITE_REJECTED',flush=True)
# File identity invalidation must rebuild the live index. Its sole expected
# difference from the independently rebuilt accepted index is the new revision.
new_index=get('/prompt_selector/library/index')
assert old_index['last_modified']==old_revision and new_index['last_modified']==new_revision
expected={**old_index,'last_modified':new_revision}
assert new_index==expected,'Unexpected index change beyond revision'
assert sha(DATA)==new_sha and listeners()==[release['production']['pid']]
queue_empty()
receipt.update(phase='accepted',passed=True,accepted_at=now(),live_index_matches_accepted_rebuild_except_revision=True,
               new_index_sha256=hashlib.sha256(json.dumps(new_index,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),nodes=get('/unified-workbench/status')['nodes'])
assert receipt['nodes']==71
subprocess.run([str(ROOT/'python/python.exe'),'-X','utf8',str(OLD/'release_live_verification.py'),'--expect-version','2026-09-27.01','--expect-leaf','15212','--label','one_shot_revision_live'],cwd=ROOT,check=True)
receipt['live_receipt']='../2026-09-25_full_coverage/one_shot_revision_live.json'
save(work/'receipt.json',receipt)
release['revision_finalization']={'receipt':'revision_finalize/receipt.json','sha256':sha(work/'receipt.json'),'final_data_sha256':new_sha,'new_revision':new_revision}
release['completed_at']=now();save(HERE/'release_receipt.json',release)
state.update(status='accepted',final_data_sha256=new_sha,revision=new_revision);save(HERE/'EXECUTION_STATE.json',state)
print('REVISION_AND_CACHE_ACCEPTED',new_revision,new_sha,flush=True)
