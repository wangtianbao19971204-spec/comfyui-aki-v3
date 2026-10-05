import copy,hashlib,json,os,pathlib,shutil,sys,urllib.request
from datetime import datetime
import psutil

ROOT=pathlib.Path(r'G:\ComfyUI-aki-v3')
OUT=pathlib.Path(__file__).parent
OWNER='01a101d1-7e14-79c2-ad99-ed8e4b40ccb9'
BASE='http://127.0.0.1:8188'
def sha(p):
    if not p.exists():return None
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()
def save(name,data):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
def get(route):
    with urllib.request.urlopen(BASE+route,timeout=30) as r:return json.load(r)
def live():
    owners=[]
    for c in psutil.net_connections('tcp'):
        if c.status=='LISTEN' and c.laddr.port==8188:
            p=psutil.Process(c.pid);owners.append({'pid':p.pid,'created':p.create_time(),'cmdline':p.cmdline()})
    return {'at':datetime.now().astimezone().isoformat(),'owners':owners,'queue':get('/queue'),'modules':get('/unified-workbench/status')}
def workflow_paths():
    for directory in ['ComfyUI/user/default/workflows','production_tools/templates']:
        for p in (ROOT/directory).glob('*.json'):
            if p.name=='UAP统一生产工作台_v2.json' or p.name.startswith(('生产套件_01_','生产套件_02_','生产套件_03_','生产扩展_')):yield p
def changed_workflow(before):
    after=copy.deepcopy(before)
    for n in after['nodes']:
        if n['type']=='VRAMCleanup':
            assert n.get('widgets_values') in ([True,True],[False,False])
            assert not any(i.get('link') is not None for i in n.get('inputs',[]) if i['name'] in ['offload_model','offload_cache'])
            n['widgets_values']=[False,False]
            n['title']='[12] 可选显存释放（默认保留模型）' if n.get('title','').startswith('[12]') else '可选显存释放（默认保留模型）'
            if 'widgets_values_named' in n:
                for name in ['offload_model','offload_cache']:
                    if name in n['widgets_values_named']:n['widgets_values_named'][name]=False
    suite=after.get('extra',{}).get('production_suite',{})
    if 'embedded_cleanup_default' in suite:suite['embedded_cleanup_default']=False
    return after
def guard():
    b=json.loads((OUT/'baseline.json').read_text('utf8'));r=json.loads((OUT/'release.json').read_text('utf8'))
    for p,h in r['sources'].items():assert sha(pathlib.Path(p))==h,p
    for p,h in b['sources'].items():assert sha(OUT/'before'/pathlib.Path(p).relative_to(ROOT))==h,p+' backup'
    drift=[p for p,h in b['guards'].items() if sha(pathlib.Path(p))!=h]
    state=live();assert len(state['owners'])==1
    assert state['owners']==b['live']['owners'],'Backend identity changed'
    receipt={'live':state,'drift':drift,'guard_count':len(b['guards']),'rollback_preflight':True}
    save('final_guard.json',receipt);assert not drift,drift
    return receipt
def main(action):
    if action=='stage':
        assert not (OUT/'baseline.json').exists()
        save('run.lock',{'owner':OWNER,'scope':'opt-in cleanup defaults and isolated 24-image prompt comparison'})
        paths=list(workflow_paths())+[ROOT/'production_tools/README.md']
        previous=json.loads((ROOT/'benchmark_reports/2026-10-03_runtime_phase2/baseline.json').read_text('utf8'))
        protected=set(previous['guards'])
        protected.update(str(p) for p in (ROOT/'ComfyUI/user/default/workflows').glob('*.json'))
        protected.update(str(p) for p in (ROOT/'production_tools/templates').glob('*.json'))
        protected.update(str(ROOT/p) for p in ['production_tools/launch.py','启动_ComfyUI_生产.cmd','production_tools/工作流状态表.md','ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/runtime_controls.js','ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js'])
        protected-=set(map(str,paths))
        state=live();assert len(state['owners'])==1
        assert not state['queue']['queue_running'] and not state['queue']['queue_pending']
        save('baseline.json',{'live':state,'sources':{str(p):sha(p) for p in paths},'guards':{p:sha(pathlib.Path(p)) for p in sorted(protected)}})
        changes=[]
        for p in paths:
            rel=p.relative_to(ROOT);backup=OUT/'before'/rel;staged=OUT/'staged'/rel
            backup.parent.mkdir(parents=True,exist_ok=True);staged.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,backup)
            if p.suffix=='.json':
                original=p.read_text('utf8');before=json.loads(original);after=changed_workflow(before)
                for old,new in zip(before['nodes'],after['nodes']):
                    if old!=new:changes.append({'path':str(p),'id':old['id'],'old_flags':old['widgets_values'],'new_flags':new['widgets_values']})
                staged.write_text(json.dumps(after,ensure_ascii=False,indent=2) if '\n' in original else json.dumps(after,ensure_ascii=False,separators=(',',':')),encoding='utf8')
            else:
                text=p.read_text('utf8')
                old='当前只将实测过的 AnimaYume 日常分支（UAP a1 及生产套件 01）默认改为保留模型；2.9B、Krea2 和其他扩展保持原默认。'
                assert text.count(old)==1
                staged.write_text(text.replace(old,'UAP v2 全部分支、生产套件 01–03 和扩展 04–09 均默认保留模型；出图后释放为可选项。需要释放时选择“单张完成 · 释放模型和缓存”，或使用立即释放按钮 / 专用 99 释放工作流。'),encoding='utf8')
        save('defaults_changes.json',{'files':len(paths),'nodes':changes,'dedicated_cleanup_preserved':True,'historical_v1_preserved':True})
        save('STATE.json',{'status':'staged','next':'release and browser acceptance; isolated prompt comparison'})
    elif action=='release':
        b=json.loads((OUT/'baseline.json').read_text('utf8'))
        for p,h in b['sources'].items():assert sha(pathlib.Path(p))==h,p
        for path in b['sources']:
            p=pathlib.Path(path);staged=OUT/'staged'/p.relative_to(ROOT)
            if p.suffix=='.json':assert json.loads(staged.read_text('utf8'))==changed_workflow(json.loads(p.read_text('utf8')))
        for path in b['sources']:
            p=pathlib.Path(path);shutil.copyfile(OUT/'staged'/p.relative_to(ROOT),p)
        save('release.json',{'sources':{p:sha(pathlib.Path(p)) for p in b['sources']}})
        save('STATE.json',{'status':'released_pending_acceptance'})
    elif action=='rollback':
        guard();b=json.loads((OUT/'baseline.json').read_text('utf8'))
        for path in b['sources']:
            p=pathlib.Path(path);shutil.copyfile(OUT/'before'/p.relative_to(ROOT),p)
        save('STATE.json',{'status':'rolled_back'})
    elif action=='guard':print(json.dumps(guard(),ensure_ascii=False))
    print(action+' OK')
if __name__=='__main__':main(sys.argv[1])
