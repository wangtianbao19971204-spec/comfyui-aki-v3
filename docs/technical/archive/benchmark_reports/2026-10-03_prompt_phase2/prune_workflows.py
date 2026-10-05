import copy
import json
from manage import FILES,OUT,save

counts=[]
for name,p in FILES.items():
    if p.suffix!='.json':continue
    before=json.loads((OUT/'before'/name).read_text('utf8'))
    after=copy.deepcopy(before)
    titles={g['title'] for g in before['groups'] if g['title'].startswith('SW-00B ')}
    allowed={'AnimaCharacterTagSelector','AnimaClothingTagSelector','AnimaPoseTagSelector','AnimaPoseTagSelectorPlus','AnimaBackgroundTagSelectorPlus','AnimaPromptComposer','ShowText|pysssss'}
    removed=set()
    for g in before['groups']:
        if g['title'] not in titles:continue
        x,y,w,h=g['bounding']
        for n in before['nodes']:
            if n['type'] in allowed and x<=n['pos'][0]<x+w and y<=n['pos'][1]<y+h:
                assert n.get('mode')==2,n['id']
                removed.add(n['id'])
    links=[l for l in before['links'] if l[1] in removed or l[3] in removed]
    assert all(l[1] in removed and l[3] in removed for l in links),'Connected to production'
    assert len(removed)==(16 if name.startswith('UAP') else 6 if '03_' in name else 5)
    after['nodes']=[n for n in after['nodes'] if n['id'] not in removed]
    after['links']=[l for l in after['links'] if l not in links]
    after['groups']=[g for g in after['groups'] if g['title'] not in titles]
    controllers=[]
    for n in after['nodes']:
        if 'Fast Groups' in n['type']:
            prop=n.get('properties',{})
            sort=prop.get('customSortAlphabet','')
            clean=','.join(v for v in sort.split(',') if v not in titles)
            if sort!=clean:prop['customSortAlphabet']=clean;controllers.append(n['id'])
    for b in after['extra'].get('uap_workbench',{}).get('branches',[]):
        b['nodeIds']=[i for i in b['nodeIds'] if i not in removed]
        for s in b.get('stages',[]):s['groups']=[t for t in s['groups'] if t not in titles]
    suite=after['extra'].get('production_suite',{})
    if 'safe_mute_groups' in suite:suite['safe_mute_groups']=[t for t in suite['safe_mute_groups'] if t not in titles]
    # Every retained node (including its prompt/model/widget payload) and every
    # retained connection is byte-equivalent as a JSON value, except controller ordering.
    prior={n['id']:n for n in before['nodes']}
    for n in after['nodes']:
        expected=copy.deepcopy(prior[n['id']])
        if n['id'] in controllers:expected['properties']['customSortAlphabet']=n['properties']['customSortAlphabet']
        assert n==expected,n['id']
    assert after['links']==[l for l in before['links'] if l not in links]
    assert len(after['nodes'])+len(removed)==len(before['nodes'])
    (OUT/'staged'/name).write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf8')
    counts.append({'file':name,'removed_nodes':sorted(removed),'removed_links':[l[0] for l in links],'removed_groups':sorted(titles),'controllers':controllers,'retained_nodes_and_links_unchanged':True})
save('workflow_pruning.json',counts)
print(json.dumps(counts,ensure_ascii=False))
