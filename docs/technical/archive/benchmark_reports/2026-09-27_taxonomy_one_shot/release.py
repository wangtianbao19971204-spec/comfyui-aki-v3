"""Single combined release; rollback all production files on any failed acceptance."""
from common import *
import os, shutil, time, subprocess, urllib.request, psutil

PYTHON=ROOT/'python/python.exe';COMFY=ROOT/'ComfyUI'
TARGETS={'data.json':DATA,'semantic_projection.json':PROJECTION,'semantic_refinements.py':SOURCES/'semantic_refinements.py'}
STAGED={'data.json':HERE/'stage/data.json','semantic_projection.json':HERE/'stage/semantic_projection.json','semantic_refinements.py':STAGE/'semantic_refinements.py'}
receipt={'created_at':now(),'phase':'job_0','applied':False,'passed':False,'events':[]}
child=None
service_ready=False
def checkpoint(phase,**fields):
    receipt.update(phase=phase,**fields);receipt['events'].append({'phase':phase,'at':now()})
    save(HERE/'release_receipt.json',receipt)
    save(HERE/'EXECUTION_STATE.json',{'status':phase,'production_mutated':receipt['applied'],'acceptance_protocol':'User-authorized single consolidated release and total acceptance; no new sampling rounds.','receipt':'release_receipt.json','updated_at':now()})
    print(phase,flush=True)
def get(path,timeout=240):
    with urllib.request.urlopen('http://127.0.0.1:8188'+path,timeout=timeout) as response:return json.loads(response.read())
def listeners():return sorted({c.pid for c in psutil.net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN and c.laddr and c.laddr.port==8188})
def queue_empty():
    q=get('/queue',20)
    assert 'queue_running' in q and 'queue_pending' in q and not q['queue_running'] and not q['queue_pending'],q
    return q
def replace(src,dst):
    tmp=dst.with_name(dst.name+'.one-shot-replacing')
    with Path(src).open('rb') as i,tmp.open('wb') as o:
        shutil.copyfileobj(i,o,1024*1024);o.flush();os.fsync(o.fileno())
    os.replace(tmp,dst)
    assert sha(src)==sha(dst)
def verify_owner(proc):
    assert Path(proc.exe()).resolve()==PYTHON.resolve()
    assert str(COMFY/'main.py') in proc.cmdline()
def stop(proc,creation):
    verify_owner(proc);assert abs(proc.create_time()-creation)<0.01
    proc.terminate();proc.wait(timeout=45)
    assert not listeners(),'Port has another owner; will not stop another process.'
def start(label):
    assert not listeners()
    command=[str(PYTHON),str(COMFY/'main.py'),'--preview-method','auto','--cuda-malloc','--reserve-vram','4','--listen','127.0.0.1']
    with (HERE/(label+'.out.log')).open('ab') as out,(HERE/(label+'.err.log')).open('ab') as err:
        process=subprocess.Popen(command,cwd=COMFY,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP,close_fds=True)
    info=psutil.Process(process.pid);verify_owner(info)
    identity={'pid':info.pid,'create_time':info.create_time(),'command':command}
    receipt[label]=identity;checkpoint(label+'_starting')
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Controlled service exited during startup')
        try:
            queue_empty()
            assert listeners()==[process.pid]
            status=get('/unified-workbench/status',30)
            if status['nodes']!=71 or status['degraded']:
                raise RuntimeError('Workbench startup is degraded: '+json.dumps(status,ensure_ascii=False))
            receipt[label]['workbench']=status
            return info
        except (OSError,ValueError,AssertionError):time.sleep(5)
    raise RuntimeError('Service readiness timeout')
def run(script,*args):
    subprocess.run([str(PYTHON),'-X','utf8',str(script),*args],cwd=ROOT,check=True)

pre=read(HERE/'preflight.json');assert pre['passed']
for relative,digest in pre['bound_files'].items():assert sha(ROOT/relative)==digest,relative
for name,dst in TARGETS.items():assert sha(dst)==sha(HERE/'backup'/name)
assert {n:sha(p) for n,p in STAGED.items()}==pre['stage_sha256']
receipt['preflight_sha256']=sha(HERE/'preflight.json');receipt['before_sha256']={n:sha(p) for n,p in TARGETS.items()}
receipt['queue_before']=queue_empty()
assert listeners()==[6272]
old=psutil.Process(6272);verify_owner(old);assert abs(old.create_time()-1790471970.4194696)<0.01
checkpoint('job_0_passed')
try:
    stop(old,1790471970.4194696);checkpoint('service_stopped')
    receipt['applied']=True;checkpoint('replacing_files')
    for name,dst in TARGETS.items():replace(STAGED[name],dst)
    receipt['installed_sha256']={n:sha(p) for n,p in TARGETS.items()}
    child=start('production')
    service_ready=True
    checkpoint('live_acceptance')
    run(OLD/'release_live_verification.py','--expect-version','2026-09-27.01','--expect-leaf','15212','--label','one_shot_live')
    run(HERE/'live_cases.py')
    run(OLD/'g6_current_source_contract.py','--label','one_shot_query_contract')
    run(HERE/'scan_stage.py','scan_live_final')
    live_scan=read(HERE/'scan_live_final/scan_summary.json');stage_scan=read(HERE/'scan_stage_final/scan_summary.json')
    assert live_scan['index_sha256']==stage_scan['index_sha256']
    assert all(sha(dst)==pre['stage_sha256'][name] for name,dst in TARGETS.items())
    for relative,digest in pre['frozen_hashes'].items():assert sha(ROOT/relative)==digest,relative
    queue_empty();assert listeners()==[child.pid]
    receipt['sole_listener_ok']=True
    checkpoint('accepted',passed=True,completed_at=now())
except BaseException as exc:
    checkpoint('rollback_required',failure=repr(exc))
    # Only the child we created may be stopped. Never kill an unexpected owner.
    if child is None and receipt.get('production'):
        identity=receipt['production']
        if psutil.pid_exists(identity['pid']):child=psutil.Process(identity['pid'])
    if child is not None and child.is_running():
        try:queue_empty()
        except (OSError,ValueError):
            if service_ready:raise
        stop(child,receipt['production']['create_time'])
    assert not listeners(),'Unexpected live owner blocks safe rollback; receipts preserve exact state.'
    for name,dst in TARGETS.items():replace(HERE/'backup'/name,dst)
    receipt['applied']=False
    recovered=start('recovery')
    run(OLD/'release_live_verification.py','--expect-version','2026-09-25.25','--expect-leaf','15212','--label','one_shot_rollback_live')
    checkpoint('rolled_back',rollback_verified=True)
    raise
