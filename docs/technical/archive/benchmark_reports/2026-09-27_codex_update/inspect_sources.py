from pathlib import Path
from collections import Counter
import json,hashlib,sqlite3
HERE=Path(__file__).resolve().parent
PROD=HERE.parents[1]/'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
web=HERE/'sources/web'
for meta in read(web/'codexes.json'):
    file=web/(meta['id']+'.json')
    if not file.exists():continue
    data=read(file);entries=data.get('entries',[])
    print('WEB',meta['id'],len(entries),'top',list(data),'entry_keys',dict(Counter(k for e in entries for k in e)))
    if not meta.get('nsfw'):
        print('SAMPLE',json.dumps(entries[0],ensure_ascii=False)[:1800])
data_file=PROD/'user_data/prompt_selector/data.json'
data=read(data_file)
stats=Counter();samples=[];fields=Counter();cats=[]
for c in data['categories']:
    if len(cats)<5:cats.append({k:v for k,v in c.items() if k!='prompts'})
    for p in c['prompts']:
        stats['total']+=1;stats['image']+=bool(p.get('image'))
        for k in p:fields[k]+=1
        prefix=p['id'].split('-')[0];stats['prefix_'+prefix]+=1
        if p['id'].startswith(('codex-suozhang-','codex-suozhang_nai5-','docx-n5-')) and len(samples)<4:
            samples.append({'category':{k:v for k,v in c.items() if k!='prompts'},'prompt':p})
print('LIVE_KEYS',list(data));print('LIVE_FIELDS',dict(fields));print('LIVE_STATS',dict(stats));print('LIVE_SAMPLES',json.dumps(samples,ensure_ascii=False)[:8500])
(HERE/'live_inventory.json').write_text(json.dumps({'data_sha256':hashlib.sha256(data_file.read_bytes()).hexdigest(),'revision':data.get('last_modified'),'stats':dict(stats),'fields':dict(fields),'categories':len(data['categories'])},ensure_ascii=False,indent=2),encoding='utf-8')
db=PROD/'user_data/userdatas_zh_CN_tags.db'
with sqlite3.connect('file:'+db.as_posix()+'?mode=ro',uri=True) as conn:
    print('DB_TABLES',conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
    print('DB_TAGS',conn.execute('SELECT COUNT(*) FROM tag_tags').fetchone())
    print('DB_META',conn.execute('SELECT * FROM workbench_tag_meta LIMIT 1').fetchone())
