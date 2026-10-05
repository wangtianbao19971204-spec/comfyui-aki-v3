import hashlib,json,pathlib,shutil,sys,urllib.request
from datetime import datetime
ROOT=pathlib.Path(r'G:\ComfyUI-aki-v3')
OUT=pathlib.Path(__file__).parent
PLUGIN=ROOT/'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'
FILES={
 'launch.py':ROOT/'production_tools/launch.py',
 '启动_ComfyUI_生产.cmd':ROOT/'启动_ComfyUI_生产.cmd',
 '工作流状态表.md':ROOT/'production_tools/工作流状态表.md',
 'README.md':ROOT/'production_tools/README.md',
 'uap_daily_controls.js':PLUGIN/'modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js',
 'runtime_controls.js':PLUGIN/'web/runtime_controls.js',
}
for p in (ROOT/'ComfyUI/user/default/workflows').glob('*v2.json'):
 if p.name.startswith(('UAP','生产套件_01_','生产套件_02_','生产套件_03_')):FILES[p.name]=p
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
def save(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
def get(route):
 with urllib.request.urlopen('http://127.0.0.1:8188'+route,timeout=30) as r:return json.load(r)
def live():
 import psutil
 owners=[]
 for c in psutil.net_connections('tcp'):
  if c.status=='LISTEN' and c.laddr.port==8188:
   p=psutil.Process(c.pid);owners.append(dict(pid=p.pid,created=p.create_time(),exe=p.exe(),cwd=p.cwd(),cmdline=p.cmdline()))
 return dict(at=datetime.now().astimezone().isoformat(),owners=owners,queue=get('/queue'),status=get('/unified-workbench/status'))
def main(action):
 if action=='baseline':
  assert not (OUT/'baseline.json').exists()
  for directory in ['before','staged']:
   (OUT/directory).mkdir(exist_ok=True)
   for name,p in FILES.items():
    if p.exists():shutil.copy2(p,OUT/directory/name)
  prev=json.loads((ROOT/'benchmark_reports/2026-10-03_prompt_phase2/baseline.json').read_text('utf8'))
  protected=set(prev['formal'])|set(prev['other_sources'])
  protected|={str(p) for p in PLUGIN.rglob('*') if p.suffix in {'.js','.css','.py'} and p.is_file()}
  protected|={str(ROOT/'production_tools/profiles.json')}
  protected-=set(str(p) for p in FILES.values())
  save('baseline.json',{'live':live(),'sources':{name:sha(p) for name,p in FILES.items()},'guards':{p:sha(pathlib.Path(p)) for p in sorted(protected)}})
  save('object_info_before.json',get('/object_info'));save('extensions_before.json',get('/extensions'))
  save('run.lock',{'owner':'01a101d1-7e14-79c2-ad99-ed8e4b40ccb9','scope':'runtime profile, residency controls and measurements'})
  save('STATE.json',{'status':'staging'})
 elif action=='release':
  b=json.loads((OUT/'baseline.json').read_text('utf8'))
  for name,p in FILES.items():assert sha(p)==b['sources'][name],name
  for name,p in FILES.items():shutil.copyfile(OUT/'staged'/name,p)
  save('release.json',{'sources':{name:sha(p) for name,p in FILES.items()}})
  save('STATE.json',{'status':'released_pending_acceptance'})
 else:
  b=json.loads((OUT/'baseline.json').read_text('utf8'));r=json.loads((OUT/'release.json').read_text('utf8'))
  for name,p in FILES.items():
   assert sha(p)==r['sources'][name],name
   assert sha(OUT/'before'/name)==b['sources'][name],name+' backup'
  if action=='rollback':
   for name,p in FILES.items():
    if b['sources'][name] is None:p.unlink()
    else:shutil.copyfile(OUT/'before'/name,p)
   save('STATE.json',{'status':'files_rolled_back','runtime':'use restart.py rollback to restore original service arguments'})
  else:
   observed=[p for p,h in b['guards'].items() if sha(pathlib.Path(p))!=h]
   concurrent={};amendment=OUT/'concurrent_changes.json'
   if amendment.exists():
    verified=json.loads(amendment.read_text('utf8'))
    assert verified['baseline_sha256']==sha(OUT/'baseline.json'),'Baseline binding changed'
    for evidence,h in verified['evidence'].items():assert sha(pathlib.Path(evidence))==h,evidence
    assert set(verified['changes']).isdisjoint(map(str,FILES.values())),'Concurrent source overlap'
    for p,entry in verified['changes'].items():
     assert b['guards'][p]==entry['before_sha256'],p+' concurrent preimage'
     assert sha(pathlib.Path(p))==entry['after_sha256'],p+' concurrent source drift'
     concurrent[p]=entry
   drift=[p for p in observed if p not in concurrent]
   data={'live':live(),'drift':drift,'observed_changes':observed,'concurrent_other_scope_changes':concurrent,'guard_count':len(b['guards']),'unchanged_guard_count':len(b['guards'])-len(observed),'rollback_preflight':True}
   save('final_guard.json',data);assert not drift,drift;print(json.dumps(data,ensure_ascii=False))
 print(action+' OK')
if __name__=='__main__':main(sys.argv[1])
