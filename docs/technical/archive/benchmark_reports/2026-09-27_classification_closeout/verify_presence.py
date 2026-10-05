from common import *
from collections import Counter, defaultdict
from contextlib import closing
import sqlite3

prior=HERE.with_name('2026-09-27_llama_verified_writeback')
assert sha(DATA)==read(HERE/'baseline_runtime.json')['data_sha256']
remaining=read(HERE/'inventory.json')
reconciled={r['source']:r for r in read(prior/'reconciliation.json')}
raw={source_key(m,e):content(e) for m,e in sources() if source_key(m,e) in {r['source'] for r in remaining}}
data=read(DATA);byid={p['id']:p for c in data['categories'] for p in c['prompts']}
expected=defaultdict(list)
for row in remaining:
    if row['id']:
        assert row['id'] in byid
        assert digest(byid[row['id']]['prompt'])==reconciled[row['source']]['local_body_sha256']
    else:expected[norm(raw[row['source']])].append(row['source'])
matches=defaultdict(list)
with closing(sqlite3.connect('file:'+DB.as_posix()+'?mode=ro',uri=True)) as conn:
    cursor=conn.execute('SELECT t_uuid,text FROM tag_tags')
    for uid,body in cursor:
        for source in expected.get(norm(body),[]):matches[source].append(uid)
verified=[]
for row in remaining:
    source=row['source']
    presence='already_in_resource' if row['id'] else 'already_in_tag_only' if matches[source] else 'absent_from_both'
    assert presence==reconciled[source]['prior_presence'],(source,presence,reconciled[source]['prior_presence'])
    verified.append({'source':source,'id':row['id'],'presence':presence,'tag_ids':matches[source] if not row['id'] else [],'source_body_sha256':digest(raw[source]),'local_body_sha256':row.get('local_body_sha256')})
assert len(verified)==2395
assert Counter(r['presence'] for r in verified)=={'already_in_resource':2283,'already_in_tag_only':7,'absent_from_both':105}
save(HERE/'presence_verification.json',{'passed':True,'created_at':now(),'sources':len(verified),'counts':dict(Counter(r['presence'] for r in verified)),'data_sha256':sha(DATA),'read_only_tag_database':True,'rows':verified})
print('PRESENCE_VERIFIED',len(verified),dict(Counter(r['presence'] for r in verified)),flush=True)
