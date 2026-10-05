from common import *
import os, shutil, time, subprocess, requests, psutil

PYTHON=ROOT/'python/python.exe';COMFY=ROOT/'ComfyUI';backup=HERE/'backup';stage=HERE/'stage'
targets={'data.json':DATA,'semantic_projection.json':PROJECTION}
pre=read(HERE/'preflight.json');assert pre['passed']
receipt={'created_at':now(),'phase':'job_0','applied':False,'passed':False,'events':[]};child=None;ready=False
def checkpoint(phase,**fields):
    receipt.update(phase=phase,**fields);receipt['events'].append({'phase':phase,'at':now()});save(HERE/'release_receipt.json',receipt)
    save(HERE/'EXECUTION_STATE.json',{'status':phase,'production_mutated':receipt['applied'],'receipt':'release_receipt.json','updated_at':now()});print(phase,flush=True)
def get(path):
    r=requests.get('http://127.0.0.1:8188'+path,timeout=60);r.raise_for_status();return r.json()
def listeners():return sorted({c.pid for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==8188})
def queue_empty():
    q=get('/queue');assert not q['queue_running'] and not q['queue_pending'];return q
def replace(src,dst):
    tmp=dst.with_name(dst.name+'.verified-classification')
    with Path(src).open('rb') as inp,tmp.open('wb') as out:shutil.copyfileobj(inp,out,1024*1024);out.flush();os.fsync(out.fileno())
    os.replace(tmp,dst);assert sha(src)==sha(dst)
def owner(proc):
    assert Path(proc.exe()).resolve()==PYTHON.resolve();assert str(COMFY/'main.py') in proc.cmdline()
def stop(proc,created):
    owner(proc);assert abs(proc.create_time()-created)<0.01;proc.terminate()
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        if not psutil.pid_exists(proc.pid):break
        try:
            if psutil.Process(proc.pid).create_time()!=created:break
        except psutil.NoSuchProcess:break
        time.sleep(0.5)
    else:raise RuntimeError('Exact owned service did not stop within 45 seconds')
    assert not listeners()
def start(label):
    assert not listeners();cmd=pre['owner']['command']
    with (HERE/(label+'.out.log')).open('ab') as out,(HERE/(label+'.err.log')).open('ab') as err:
        p=subprocess.Popen(cmd,cwd=COMFY,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP,close_fds=True)
    proc=psutil.Process(p.pid);owner(proc);receipt[label]={'pid':p.pid,'create_time':proc.create_time(),'command':cmd};checkpoint(label+'_starting')
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        if p.poll() is not None:raise RuntimeError('Service exited during startup')
        try:
            queue_empty();assert listeners()==[p.pid];status=get('/unified-workbench/status')
            assert status['nodes']==71 and not status['degraded'];return proc
        except (requests.RequestException,ValueError,AssertionError):time.sleep(5)
    raise RuntimeError('Service startup timeout')
def run(name):
    with (HERE/(name+'.log')).open('wb') as log:subprocess.run([str(PYTHON),'-X','utf8',str(HERE/(name+'.py'))],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
for relative,h in pre['bound_files'].items():assert sha(ROOT/relative)==h,relative
for name,h in pre['source_hashes'].items():assert sha(PROD/'prompt_selector'/name)==h,name
for name,path in targets.items():assert sha(path)==sha(backup/name) and sha(stage/name)==pre['stage_sha256'][name]
queue_empty();assert listeners()==[pre['owner']['pid']]
old=psutil.Process(pre['owner']['pid']);owner(old);checkpoint('job_0_passed')
try:
    stop(old,pre['owner']['create_time']);checkpoint('service_stopped')
    # Recheck after shutdown: no edit can land between baseline comparison and replacement.
    for name,path in targets.items():assert sha(path)==sha(backup/name),name
    receipt['applied']=True;checkpoint('replacing_classification_files')
    for name,path in targets.items():replace(stage/name,path)
    child=start('production');ready=True;checkpoint('live_acceptance')
    run('live_acceptance');run('live_contract')
    for name,path in targets.items():assert sha(path)==pre['stage_sha256'][name]
    for relative,h in pre['frozen_hashes'].items():assert sha(ROOT/relative)==h
    assert sha(DATA.with_name('shared_pairs.json'))==pre['untouched_hashes']['shared_pairs.json']
    assert sha(PROD/'prompt_selector/semantic_refinements.py')==pre['untouched_hashes']['semantic_refinements.py']
    for relative,h in pre['untouched_image_hashes'].items():assert sha(ROOT/relative)==h
    for name,h in pre['source_hashes'].items():assert sha(PROD/'prompt_selector'/name)==h,name
    queue_empty();assert listeners()==[child.pid]
    receipt['sole_listener_ok']=True;checkpoint('accepted',passed=True,completed_at=now())
except BaseException as exc:
    checkpoint('rollback_required',failure=repr(exc))
    if child is None and receipt.get('production') and psutil.pid_exists(receipt['production']['pid']):child=psutil.Process(receipt['production']['pid'])
    if child is not None and child.is_running():
        try:queue_empty()
        except (requests.RequestException,ValueError):
            if ready:raise
        stop(child,receipt['production']['create_time'])
    assert not listeners(),'Unexpected listener blocks restoration'
    if receipt['applied']:
        for name,path in targets.items():replace(backup/name,path)
    receipt['applied']=False;recovered=start('recovery')
    assert get('/prompt_selector/library/index')==read(HERE/'baseline_index.json')
    queue_empty();assert listeners()==[recovered.pid]
    checkpoint('rolled_back',rollback_verified=True);raise
