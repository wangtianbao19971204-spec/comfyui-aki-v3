from update_common import *
import urllib.request,urllib.parse,sqlite3

def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8188'+path,timeout=900) as r:return json.loads(r.read())
data=read(STAGE/'data.json');records={p['id']:(c,p) for c in data['categories'] for p in c['prompts']};ops=read(HERE/'operations.json')
index=get('/prompt_selector/library/index');expected=read(HERE/'stage_index.json')
save(HERE/'live_index.json',index);assert index==expected,'Full live index differs from independently rebuilt staging index'
revision=get('/prompt_selector/library/revision');assert revision.get('revision')==data['last_modified'],revision
samples={o['id'] for o in ops if 'upstream_body_update' in o['action'] or o['store']=='library' and 'preview_update' in o['action']}
bydataset=defaultdict(list)
for o in ops:
    if o['store']=='library' and 'add' in o['action']:bydataset[o['source'].split(':',1)[0]].append(o['id'])
for ids in bydataset.values():samples.update(ids[:2]+ids[-1:])
samples.update(x['id'] for x in read(HERE/'classification_adjudication.json')['changes'] if 'parents' in x)
samples.update(x['id'] for x in read(HERE/'classification_review.json') if x['reason']=='preserved_local_body_divergence')
images=set();checks=[]
for pid in sorted(samples):
    c,p=records[pid];row=get('/prompt_selector/library/prompt?'+urllib.parse.urlencode({'prompt_id':pid,'include_semantic':1}))['prompt']
    assert row['prompt']==p['prompt'] and row['image']==p['image'],pid
    assert row['_semantic']['primary_class']==p['_classification']['primary_class'],pid
    assert set(row['_semantic']['subcategories'])==set(P.selector_subcategories(p['_classification'],p)),pid
    if row.get('image'):images.add(row['image'])
    checks.append({'store':'library','id':pid,'passed':True})
with sqlite3.connect(STAGE/'tags.db') as db:
    bydataset=defaultdict(list);samples={o['id'] for o in ops if 'paired_body_update' in o['action']}
    for o in ops:
        if o['store']=='tags' and 'add' in o['action']:bydataset[o['source'].split(':',1)[0]].append(o['id'])
    for ids in bydataset.values():samples.update(ids[:2]+ids[-1:])
    for uid in sorted(samples):
        row=get('/prompt_selector/tags/item?'+urllib.parse.urlencode({'id':'tag:'+uid}))['item']
        text=db.execute('select text from tag_tags where t_uuid=?',(uid,)).fetchone()[0]
        assert row['text']==text,uid
        meta=json.loads(db.execute('select data from workbench_tag_meta where tag_uuid=?',(uid,)).fetchone()[0])
        if meta.get('preview'):assert row.get('preview')==meta['preview'],(uid,list(row));images.add(meta['preview'])
        checks.append({'store':'tags','id':uid,'passed':True})
for name in sorted(images):
    with urllib.request.urlopen('http://127.0.0.1:8188/prompt_selector/preview/'+urllib.parse.quote(name),timeout=60) as r:
        raw=r.read();assert hashlib.sha256(raw).hexdigest()==sha(PROD/'user_data/prompt_selector/preview'/name),name
state=get('/unified-workbench/status');assert state['nodes']==71 and not state['degraded'],state
q=get('/queue');assert not q['queue_running'] and not q['queue_pending']
save(HERE/'live_acceptance.json',{'passed':True,'created_at':now(),'index_equal_to_staged_rebuild':True,'library_revision':revision,'checks':checks,'preview_http_checks':len(images),'workbench':state,'queue_empty':True})
print('LIVE_ACCEPTANCE_PASS','RECORDS',len(checks),'PREVIEWS',len(images),flush=True)
