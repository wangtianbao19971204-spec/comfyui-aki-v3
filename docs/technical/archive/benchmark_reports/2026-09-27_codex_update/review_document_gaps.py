from audit_matching import *
import difflib
web=HERE/'sources/web';entries=[]
for name in ('suozhang','suozhang_r18','suozhang_nai5','suozhang_nai5_r18'):
    for e in read(web/(name+'.json'))['entries']:entries.append({**e,'dataset':name,'key':norm(content(e))})
index={(e['dataset'],e['id']):e for e in entries}
reviews=[]
for row in read(HERE/'document_comparison.json'):
    if row['status'] in ('web_exact','local_exact'):continue
    k=norm(row['tags']);matches=[e for e in entries if k and k in e['key']]
    review={k:row[k] for k in ('title','path','source_file','source_entry','status')}
    if matches:
        review.update(disposition='body_is_contained_in_complete_web_entry',web_ids=[e['dataset']+':'+e['id'] for e in matches])
    elif row.get('candidate'):
        cand=row['candidate'];e=index[(cand['dataset'],cand['id'])];ops=[]
        for tag,i,j,a,b in difflib.SequenceMatcher(None,k,e['key'],autojunk=False).get_opcodes():
            if tag!='equal':ops.append({'op':tag,'doc':k[i:j],'web':e['key'][a:b]})
        review.update(disposition='inspect_difference',candidate=cand,differences=ops)
    else:
        review.update(disposition='inspect_split',body=row['tags'])
    reviews.append(review)
(HERE/'document_gap_review.json').write_text(json.dumps(reviews,ensure_ascii=False,indent=2),encoding='utf-8')
print(Counter(x['disposition'] for x in reviews))
seen=set()
for x in reviews:
    if x['disposition']=='body_is_contained_in_complete_web_entry':continue
    key=(x['title'],json.dumps(x.get('differences',x.get('body')),ensure_ascii=False))
    if key in seen:continue
    seen.add(key)
    print(json.dumps(x,ensure_ascii=False)[:2500])
