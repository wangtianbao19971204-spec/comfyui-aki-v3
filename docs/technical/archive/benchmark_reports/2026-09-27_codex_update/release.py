from update_common import *
from db_fingerprint import fingerprint
import os,shutil,time,subprocess,urllib.request,psutil,sqlite3

PYTHON=ROOT/'python/python.exe';COMFY=ROOT/'ComfyUI'
targets={'data.json':DATA,'semantic_projection.json':PROJECTION,'tags.db':DB,'shared_pairs.json':DATA.with_name('shared_pairs.json'),'semantic_refinements.py':PROD/'prompt_selector/semantic_refinements.py'}
staged={n:STAGE/n for n in targets};staged['semantic_refinements.py']=STAGE/'prompt_selector/semantic_refinements.py'
receipt={'created_at':now(),'phase':'job_0','applied':False,'passed':False,'events':[]};child=None;ready=False
def checkpoint(phase,**fields):
    receipt.update(phase=phase,**fields);receipt['events'].append({'phase':phase,'at':now()});save(HERE/'release_receipt.json',receipt)
    save(HERE/'EXECUTION_STATE.json',{'status':phase,'production_mutated':receipt['applied'],'receipt':'release_receipt.json','updated_at':now()});print(phase,flush=True)
def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8188'+path,timeout=60) as r:return json.loads(r.read())
def listeners():return sorted({c.pid for c in psutil.net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN and c.laddr and c.laddr.port==8188})
def queue_empty():
    q=get('/queue');assert not q['queue_running'] and not q['queue_pending'];return q
def replace(src,dst):
    tmp=dst.with_name(dst.name+'.codex-source-update')
    with Path(src).open('rb') as i,tmp.open('wb') as o:shutil.copyfileobj(i,o,1024*1024);o.flush();os.fsync(o.fileno())
    os.replace(tmp,dst);assert sha(src)==sha(dst)
def owner(proc):
    assert Path(proc.exe()).resolve()==PYTHON.resolve();assert str(COMFY/'main.py') in proc.cmdline()
def stop(proc,created):
    owner(proc);assert abs(proc.create_time()-created)<0.01;proc.terminate();proc.wait(45);assert not listeners()
def start(label):
    assert not listeners();cmd=pre['owner']['command']
    with (HERE/(label+'.out.log')).open('ab') as out,(HERE/(label+'.err.log')).open('ab') as err:
        p=subprocess.Popen(cmd,cwd=COMFY,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP,close_fds=True)
    proc=psutil.Process(p.pid);owner(proc);receipt[label]={'pid':p.pid,'create_time':proc.create_time(),'command':cmd};checkpoint(label+'_starting')
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        if p.poll() is not None:raise RuntimeError('Service exited during startup')
        try:
            queue_empty();assert listeners()==[p.pid];state=get('/unified-workbench/status')
            if state['nodes']!=71 or state['degraded']:raise RuntimeError('Workbench degraded: '+json.dumps(state))
            receipt[label]['workbench']=state;return proc
        except (OSError,ValueError,AssertionError):time.sleep(5)
    raise RuntimeError('Service startup timeout')
def run(name):
    with (HERE/(name+'.log')).open('wb') as log:subprocess.run([str(PYTHON),'-X','utf8',str(HERE/(name+'.py'))],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)

pre=read(HERE/'preflight.json');assert pre['passed']
for relative,digest in pre['bound_files'].items():assert sha(ROOT/relative)==digest,relative
for n,p in staged.items():assert sha(p)==pre['stage_sha256'][n],n
for n,p in targets.items():
    if n!='tags.db':assert sha(p)==sha(BACKUP/n),n
assert fingerprint(DB)==pre['db_before']
receipt['preflight_sha256']=sha(HERE/'preflight.json');receipt['queue_before']=queue_empty()
assert listeners()==[pre['owner']['pid']];old=psutil.Process(pre['owner']['pid']);owner(old)
checkpoint('job_0_passed')
# Previews are additive and content-addressed. Copy before downtime; the store
# transaction is not started until every planned preview is verified installed.
for r in read(HERE/'image_receipts.json'):
    dst=PROD/'user_data/prompt_selector/preview'/r['filename'];src=STAGE/'images'/r['filename']
    if not dst.exists():replace(src,dst)
    assert sha(dst)==r['sha256']
receipt['previews_installed']=pre['images'];checkpoint('previews_ready')
queue_empty()
try:
    stop(old,pre['owner']['create_time']);checkpoint('service_stopped')
    db=sqlite3.connect(DB)
    try:assert db.execute('pragma wal_checkpoint(TRUNCATE)').fetchone()[0]==0
    finally:db.close()
    assert fingerprint(DB)==pre['db_before']
    receipt['applied']=True;checkpoint('replacing_files')
    for name,dst in targets.items():replace(staged[name],dst)
    child=start('production');ready=True;checkpoint('live_acceptance')
    run('live_acceptance');run('live_contract')
    for name,dst in targets.items():
        if name!='tags.db':assert sha(dst)==pre['stage_sha256'][name],name
    assert fingerprint(DB)==pre['db_after']
    for relative,digest in pre['frozen_hashes'].items():assert sha(ROOT/relative)==digest
    queue_empty();assert listeners()==[child.pid]
    receipt['sole_listener_ok']=True;checkpoint('accepted',passed=True,completed_at=now())
except BaseException as exc:
    checkpoint('rollback_required',failure=repr(exc))
    if child is None and receipt.get('production') and psutil.pid_exists(receipt['production']['pid']):child=psutil.Process(receipt['production']['pid'])
    if child is not None and child.is_running():
        try:queue_empty()
        except (OSError,ValueError):
            if ready:raise
        stop(child,receipt['production']['create_time'])
    assert not listeners(),'Unexpected listener blocks restoration'
    for name,dst in targets.items():replace(BACKUP/name,dst)
    receipt['applied']=False;recovered=start('recovery')
    assert get('/prompt_selector/library/index')==read(HERE/'baseline_index.json')
    assert fingerprint(DB)==pre['db_before'];queue_empty();assert listeners()==[recovered.pid]
    checkpoint('rolled_back',rollback_verified=True);raise
