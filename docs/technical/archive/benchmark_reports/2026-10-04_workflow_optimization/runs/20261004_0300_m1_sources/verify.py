import hashlib
import json
from pathlib import Path
import urllib.request
from datetime import datetime
import psutil

ROOT = Path(r'G:\ComfyUI-aki-v3')
OUT = Path(__file__).parent
PLUGIN = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'
def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
def get(route, body=None):
    request = urllib.request.Request('http://127.0.0.1:8188'+route, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type':'application/json'} if body is not None else {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

baseline = json.loads((OUT/'baseline.json').read_text('utf8'))
current = {p:sha(Path(p)) for p in baseline['files']}
drift = [p for p in current if current[p] != baseline['files'][p]]
assert not drift, drift
owners = []
for c in psutil.net_connections('tcp'):
    if c.status == 'LISTEN' and c.laddr.port == 8188:
        process=psutil.Process(c.pid)
        owners.append({'pid':process.pid,'created':process.create_time()})
queue,status=get('/queue'),get('/unified-workbench/status')
assert owners == baseline['live']['owners']
assert not queue['queue_running'] and not queue['queue_pending']
assert all(m['ready'] for m in status['modules'])
served={}
routes=get('/extensions')
for name in ['pending_prompts.js','prompt_target.js','selector_tools.js','anima_selector_ui.js','anima_shared_prompt_data.js',
             'anima_character_selector.js','anima_clothing_selector.js','anima_pose_selector.js','anima_background_selector.js','anima_artist_selector.js']:
    matches=[r for r in routes if r.endswith('/'+name)]
    assert len(matches)==1,(name,matches)
    path=PLUGIN/('modules/comfyui-anima-tools/js' if name.startswith('anima_') else 'web')/name
    with urllib.request.urlopen('http://127.0.0.1:8188'+matches[0],timeout=30) as response:
        served_sha=hashlib.sha256(response.read()).hexdigest()
    assert served_sha==sha(path),name
    served[name]={'sha256':served_sha,'matches_disk':True}

api=[]
for kind in ['character','clothing','pose','background','artist','style_quality']:
    if kind=='artist':
        data=get('/anima-tools/artist-page',{'offset':0,'limit':2})
        assert data['success']
        items=data['items'];total=data['catalog_count']
    else:
        data=get('/anima-tools/shared-prompts?kind='+kind)
        items=data['items'];total=len(items)
    def eligible(item):
        semantic=item.get('_semantic',{})
        return bool(item.get('id') and item.get('shared') and str(item.get('tags','')).strip() and semantic.get('binding')
                    and semantic.get('disposition') in ['reviewed','classified'] and semantic.get('manual_search_eligible') is True
                    and semantic.get('usage')=='positive' and semantic.get('content_type') in ['atomic_tag','fragment'])
    count=sum(eligible(item) for item in items)
    api.append({'kind':kind,'catalog_count':total,'checked':len(items),'eligible':count,'sample_only':kind=='artist'})
    assert items and count==len(items),(kind,count,len(items))
save('live_source_contract.json',{'passed':True,'checks':api,'read_only':True,'note':'Artist POST is a read-only catalog query; other sources checked via GET. Bodies are not copied into this report.'})

phase2=json.loads((ROOT/'benchmark_reports/2026-10-03_prompt_phase2/FINAL_DELIVERY.json').read_text('utf8'))
reused={}
for filename in ['prompt_target.js']:
    matches=[(p,h) for p,h in phase2['changed_files'].items() if Path(p).name==filename]
    assert len(matches)==1
    path,h=matches[0];assert sha(Path(path))==h
    reused[filename]=h
save('reused_evidence.json',{'phase2_same_kind_replacement':'2026-10-03_prompt_phase2/FINAL_DELIVERY.json',
     'unchanged_source_hashes':reused,'M1a_cycle':'20261004_0205_m1_pending_cycle/FINAL_DELIVERY.json',
     'selector_bridge':'Later selector sources differ from phase2; current source_tests.json and browser_acceptance.json provide fresh ingress and replacement-bridge coverage.',
     'M1a_source_sha_matches':served['pending_prompts.js']['sha256']=='997705203ac780111155751b983b1938682bf0c9487fb6684d5faabfa83fa0fa'})
receipt={'at':datetime.now().astimezone().isoformat(),'guard_count':len(current),'drift':drift,'served':served,
         'owners':owners,'queue':queue,'modules_ready':len(status['modules']),'production_changes':False,'rollback':'not needed: no production changes'}
save('final_guard.json',receipt)
print(json.dumps({'guards':len(current),'drift':drift,'served_count':len(served),'api':api},ensure_ascii=False))
