from common import *
import requests

def get(path,**params):
    response=requests.get('http://127.0.0.1:8188'+path,params=params,timeout=300);response.raise_for_status();return response.json()

data=read(HERE/'stage/data.json');doc=read(HERE/'stage/semantic_projection.json')
records={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
index=get('/prompt_selector/library/index');save(HERE/'live_index.json',index)
assert index==read(HERE/'stage_index.json'),'Live index differs from full offline rebuild'
revision=get('/prompt_selector/library/revision');assert revision['revision']==data['last_modified']
checks=[]
for operation in read(HERE/'operations.json'):
    pid=operation['id'];c,p=records[pid]
    served=get('/prompt_selector/library/prompt',prompt_id=pid,include_semantic=1)['prompt']
    for field in ('prompt','image','favorite','description','usage_count','last_used','alias'):
        assert served.get(field)==p.get(field),(pid,field)
    expected=P.decision_for(doc,c,p)
    assert served['_semantic']['primary_class']==expected['primary_class'],pid
    assert set(served['_semantic']['subcategories'])==set(P.selector_subcategories(expected,p)),pid
    assert set(served['_semantic']['theme_ids'])==T.semantic_themes(expected),pid
    checks.append({'id':pid,'passed':True})
workbench=get('/unified-workbench/status');assert workbench['nodes']==71 and not workbench['degraded']
queue=get('/queue');assert not queue['queue_running'] and not queue['queue_pending']
save(HERE/'live_acceptance.json',{'passed':True,'created_at':now(),'full_index_equality':True,'library_revision':revision,'all_changed_records_checked':len(checks),'checks':checks,'queue_empty':True,'workbench':workbench})
print('LIVE_ACCEPTANCE_PASS',len(checks),flush=True)
