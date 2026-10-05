import hashlib
import json
import pathlib
import shutil
import sys
import urllib.request
from datetime import datetime

ROOT = pathlib.Path(r'G:\ComfyUI-aki-v3')
OUT = pathlib.Path(__file__).parent
PLUGIN = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'
FILES = {p.name: p for p in [
    PLUGIN / 'modules/comfyui-anima-tools/js/anima_character_selector.js',
    PLUGIN / 'modules/comfyui-anima-tools/js/anima_selector_ui.js',
    PLUGIN / 'web/prompt_target.js',
    PLUGIN / 'modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js',
]}
for p in (ROOT / 'ComfyUI/user/default/workflows').glob('*v2.json'):
    if p.name.startswith(('UAP', '生产套件_01_', '生产套件_02_', '生产套件_03_')):
        FILES[p.name] = p

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')

def get(route):
    with urllib.request.urlopen('http://127.0.0.1:8188' + route, timeout=30) as r:
        return json.load(r)

def live():
    import psutil
    listeners = []
    for c in psutil.net_connections('tcp'):
        if c.status == 'LISTEN' and c.laddr.port == 8188:
            p = psutil.Process(c.pid)
            listeners.append({'pid':p.pid, 'created':p.create_time(), 'cmdline':p.cmdline()})
    return {'at':datetime.now().astimezone().isoformat(), 'listeners':listeners, 'queue':get('/queue'), 'status':get('/unified-workbench/status')}

def main(action):
    if action == 'baseline':
        assert not (OUT / 'baseline.json').exists()
        for directory in ['before','staged']:
            (OUT / directory).mkdir(exist_ok=True)
            for name,p in FILES.items():shutil.copy2(p,OUT / directory / name)
        previous = json.loads((ROOT / 'benchmark_reports/2026-10-03_prompt_phase1/baseline.json').read_text('utf8'))
        formal = {p:sha(pathlib.Path(p)) for p in previous['formal'] if pathlib.Path(p) not in FILES.values()}
        sources = {str(p):sha(p) for p in PLUGIN.rglob('*') if p.is_file() and p.suffix in {'.js','.py','.css'} and p not in FILES.values()}
        save('baseline.json', {'live':live(),'sources':{name:sha(p) for name,p in FILES.items()},'formal':formal,'other_sources':sources})
        save('run.lock', {'owner':'01a101d1-7e14-79c2-ad99-ed8e4b40ccb9','scope':list(FILES)})
        save('STATE.json', {'status':'staging'})
    elif action == 'release':
        b=json.loads((OUT / 'baseline.json').read_text('utf8'))
        for name,p in FILES.items():assert sha(p)==b['sources'][name],name
        for name,p in FILES.items():shutil.copyfile(OUT / 'staged' / name,p)
        save('release.json',{'at':datetime.now().astimezone().isoformat(),'sources':{name:sha(p) for name,p in FILES.items()}})
        save('STATE.json',{'status':'released_pending_acceptance'})
    else:
        b=json.loads((OUT / 'baseline.json').read_text('utf8'))
        r=json.loads((OUT / 'release.json').read_text('utf8'))
        for name,p in FILES.items():
            assert sha(p)==r['sources'][name],name
            assert sha(OUT / 'before' / name)==b['sources'][name],name+' backup'
        if action=='rollback':
            for name,p in FILES.items():shutil.copyfile(OUT / 'before' / name,p)
            save('STATE.json',{'status':'rolled_back'})
        else:
            drift={kind:[p for p,h in b[kind].items() if sha(pathlib.Path(p))!=h] for kind in ['formal','other_sources']}
            extensions=get('/extensions'); served={}
            for name,p in FILES.items():
                if p.suffix!='.js':continue
                routes=[route for route in extensions if route.endswith('/'+name)]
                if not routes:routes=['/extensions/ComfyUI-Unified-Prompt-Workbench/'+name]
                assert len(routes)==1,(name,routes)
                with urllib.request.urlopen('http://127.0.0.1:8188'+routes[0]) as response:served[name]=hashlib.sha256(response.read()).hexdigest()==sha(p)
            result={'drift':drift,'guard_counts':{k:len(b[k]) for k in drift},'served':served,'live':live(),'rollback_preflight':True}
            save('final_guard.json',result)
            assert not any(drift.values()) and all(served.values()),result
            print(json.dumps(result,ensure_ascii=False))
    print(action+' OK')

if __name__=='__main__':main(sys.argv[1])
