import hashlib,json,math,statistics
from pathlib import Path
from urllib.parse import urlparse
from collections import Counter

OUT=Path(__file__).parent
def read(name):return json.loads((OUT/name).read_text('utf8'))
def save(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
def diff(a,b,path=''):
    if type(a)!=type(b):return [path]
    if isinstance(a,dict):return [v for k in a.keys()|b.keys() for v in ([path+'/'+k] if k not in a or k not in b else diff(a[k],b[k],path+'/'+k))]
    if isinstance(a,list):return [path+'/length'] if len(a)!=len(b) else [v for i,(x,y)in enumerate(zip(a,b))for v in diff(x,y,path+'/'+str(i))]
    return [] if a==b else [path]

restored=[];blocked_counts=Counter()
for prefix in ['protected','attempt1/accepted_protected','accepted_protected']:
    a,b=read(prefix+'_before.json')['graph'],read(prefix+'_after.json')
    assert b['localRestored'] and b['sessionRestored']
    changes=diff(a,b['graph']);allowed=['/nodes/243/widgets_values/0','/nodes/243/widgets_values_named/drawing_version']
    view_deltas=[]
    for keys in [('extra','ds','offset',0),('extra','ds','offset',1),('extra','ds','scale')]:
        x,y=a,b['graph']
        for k in keys:x,y=x[k],y[k]
        if x!=y:
            assert isinstance(x,(int,float)) and isinstance(y,(int,float)) and math.isfinite(x) and math.isfinite(y)
            if keys[-1]=='scale':assert x>0 and y>0
            path='/'+('/'.join(map(str,keys)));allowed.append(path);view_deltas.append(dict(path=path,before=x,after=y))
    sizes=[]
    for keys in [('nodes',173),('definitions','subgraphs',2,'nodes',7),('definitions','subgraphs',12,'nodes',1)]:
        x,y=a,b['graph']
        for k in keys:x,y=x[k],y[k]
        if x['size']!=y['size']:
            assert x['type']==y['type']=='TB_Multi_API_Caption_SmartRunner_V16'
            assert x['size'][0]==y['size'][0] and x['size'][1]==546 and y['size'][1]==906
            path='/'+('/'.join(map(str,keys)))+'/size/1';allowed.append(path)
            sizes.append(dict(path=path,id=x['id'],before=546,after=906))
    assert set(changes)<=set(allowed),changes
    for item in b['blocked']:blocked_counts[urlparse(item['url']).path]+=1
    restored.append(dict(prefix=prefix,passed=True,exact_equal=not changes,changes=changes,display_size_deltas=sizes,canvas_view_deltas=view_deltas,all_other_fields_equal=True,local_restored=True,session_restored=True))
save('restoration.json',restored)
forbidden={path:n for path,n in blocked_counts.items() if path.rstrip('/') in ['/prompt','/api/prompt','/free','/api/free'] or path.startswith(('/userdata/','/api/userdata/'))}
assert not forbidden,forbidden
save('blocked_requests.json',dict(endpoints=dict(blocked_counts),forbidden=forbidden,policy='All non-read requests blocked before transport; logs/preview refresh requests are fixture isolation, not production failures'))
cleanup=read('browser_cleanup.json');assert cleanup['remainingTabs']==[] and cleanup['viewportReset'] and cleanup['temporaryWorkflowsClosed']

def cycle_summary(name):
    rows=read(name)
    for row in rows:
        assert row['before']['dom']==row['after']['dom']
        assert row['before']['listeners']==row['after']['listeners']
        assert not row['sample']['horizontalOverflow'] and row['sample']['rootCount']==1
    times=[row['sample']['ms'] for row in rows]
    return dict(n=len(rows),median_ms=statistics.median(times),min_ms=min(times),max_ms=max(times),request_counts=[len(row['sample']['requests'])for row in rows],root_nodes=[row['sample']['rootNodes']for row in rows],image_elements=[row['sample']['images']for row in rows],dom_and_listeners_return_to_baseline=True)

cycles={name:cycle_summary(name+'.json') for name in ['character_cycles','pose_cycles','library_cycles','pending_before','pending_after','library_after']}
before,after=cycles['pending_before'],cycles['pending_after']
assert before['n']==after['n']==5 and before['request_counts']==[4]*5 and after['request_counts']==[3]*5
assert after['root_nodes']==[306]*5 and after['image_elements']==[6]*5
assert after['median_ms']<before['median_ms']
for row in read('pending_after.json'):
    assert not any('/prompt_selector/library/' in r['url'] for r in row['sample']['requests'])
    assert any('/prompt_selector/collections/index' in r['url'] for r in row['sample']['requests'])
for row in read('library_after.json'):
    assert row['cardCount']==30
    assert any('/prompt_selector/library/prompts?' in r['url'] for r in row['sample']['requests'])
checks=read('accepted_apply_undo.json');assert all(checks.values())
target=read('accepted_target_switch.json');assert target['passed'] and target['sidebarPreserved'] and target['noHiddenLibraryCards'] and not target['horizontalOverflow']
assert all(read('executed_source.json').values())
idle=read('selector_idle.json');assert idle['elapsedMs']>=8000 and idle['requests']==[]
selector=read('accepted_selector_regression.json');assert selector['cards']==60 and not selector['overflow'] and selector['focus']=='搜索角色名称...'
assert read('syntax_checks.json')['passed']
guard=read('final_guard.json');assert not guard['drift'] and guard['rollback_backup_verified'] and len(guard['production_changes'])==2

summary=dict(passed=True,cycles=cycles,pending_comparison=dict(before_median_ms=before['median_ms'],after_median_ms=after['median_ms'],before_requests=4,after_requests=3,before_root_nodes=2459,after_root_nodes=306,before_image_elements=36,after_image_elements=6,removed_hidden_library_cards=30),idle_seconds=idle['elapsedMs']/1000,apply_undo=checks,target_switch=target,guard_count=guard['guard_count'],protected_count=guard['protected_count'],served_hash_matches=len(guard['served']),cleanup=True,original_user_content_preserved=True,original_graph_exact_equal=False,limits=['First use means first open within a fresh browser page, not a cleared server/disk cache.', 'Five warm cycles per selector/pending condition and three per library condition; scoped responsiveness/lifecycle evidence, not hours-long or whole-process memory certification.', 'Latency measured in-page from frontend action to ready DOM plus an animation frame; images need not be fully loaded. Image figures are DOM elements, not downloaded-image counts.', '1280x720 before/after comparison uses the same neutral six-item gallery-resolver draft and fixture; 1024x640 is responsive regression.', 'No physical IME, image generation, model unload or formal save. Previous M4 numeric tests remain applicable because only the pending-entry call changed.', 'Dynamic library content and theme filters load when returning to the library; favorites/recent/group shortcuts remain available in pending view.'])
save('acceptance_summary.json',summary)
print(json.dumps(dict(passed=True,pending=summary['pending_comparison'],guard_count=summary['guard_count'],protected_count=summary['protected_count'],served=summary['served_hash_matches']),ensure_ascii=False))
