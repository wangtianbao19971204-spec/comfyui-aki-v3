from audit_matching import *
import difflib

web=HERE/'sources/web';entries=[];bybody=defaultdict(list);bytitle=defaultdict(list)
for meta in read(web/'codexes.json'):
    file=web/(meta['id']+'.external.json')
    if not file.exists():file=web/(meta['id']+'.json')
    for e in read(file)['entries']:
        e={**e,'dataset':meta['id']};entries.append(e)
        bybody[norm(content(e))].append(e)
        if meta['id'].startswith('suozhang'):bytitle[norm(e['title'])].append(e)
data=read(PROD/'user_data/prompt_selector/data.json')
local=defaultdict(list)
for c in data['categories']:
    for p in c['prompts']:local[norm(p['prompt'])].append(p['id'])
with sqlite3.connect('file:'+(PROD/'user_data/userdatas_zh_CN_tags.db').as_posix()+'?mode=ro',uri=True) as conn:
    for uid,text in conn.execute('SELECT t_uuid,text FROM tag_tags'):local[norm(text)].append('tag:'+uid)
rows=[];counts=Counter()
for d in read(HERE/'sources/docx/entries.json'):
    k=norm(d['tags']);exact=bybody.get(k,[])
    item={**d,'web_matches':[e['dataset']+':'+e['id'] for e in exact],'local_matches':local.get(k,[])}
    if exact:kind='web_exact'
    elif item['local_matches']:kind='local_exact'
    else:
        candidates=bytitle.get(norm(d['title']),[])
        same_path=[e for e in candidates if e.get('path')==d.get('path')]
        if same_path:candidates=same_path
        if candidates:
            best=max(candidates,key=lambda e:difflib.SequenceMatcher(None,k,norm(content(e)),autojunk=False).ratio())
            ratio=difflib.SequenceMatcher(None,k,norm(content(best)),autojunk=False).ratio()
            item['candidate']={'dataset':best['dataset'],'id':best['id'],'similarity':round(ratio,4),'source_len':len(d['tags']),'web_len':len(content(best))}
            kind='near_web' if ratio>=.90 else 'different_web'
        else:kind='doc_only'
    item['status']=kind;counts[kind]+=1;rows.append(item)
(HERE/'document_comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=1),encoding='utf-8')
print('COUNTS',dict(counts))
for kind in ('doc_only','different_web','near_web'):
    subset=[x for x in rows if x['status']==kind]
    print(kind,len(subset))
    for x in subset[:20]:print(json.dumps({k:x[k] for k in ('title','path','source_file','candidate') if k in x},ensure_ascii=False))
