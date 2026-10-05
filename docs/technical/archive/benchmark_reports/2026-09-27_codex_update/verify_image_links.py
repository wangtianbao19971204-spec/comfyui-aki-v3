from update_common import *
import sqlite3
preview=PROD/'user_data/prompt_selector/preview'
available={p.name for p in preview.iterdir() if p.is_file()}|{p.name for p in (STAGE/'images').iterdir() if p.is_file()}
data=read(STAGE/'data.json');prompts={p['id']:p for c in data['categories'] for p in c['prompts']}
with sqlite3.connect(STAGE/'tags.db') as db:meta={uid:json.loads(s) for uid,s in db.execute('select tag_uuid,data from workbench_tag_meta')}
web={source_key(m,e):e for m,e in sources()};results=[]
for row in read(HERE/'source_registry.json'):
    e=web[row['source']]
    if not e.get('image') or row['disposition'] in ('excluded','no_prompt_content'):continue
    if row['disposition'].startswith('tag'):name=meta.get(row['target_id'],{}).get('preview')
    else:name=prompts[row['target_id']].get('image')
    assert name and (name in available or (preview/name).is_file()),row['source']
    results.append({'source':row['source'],'image':name})
save(HERE/'image_link_validation.json',{'passed':True,'data_sha256':sha(STAGE/'data.json'),'db_sha256':sha(STAGE/'tags.db'),'source_rows_with_verified_preview':len(results),'unique_bound_previews':len({r['image'] for r in results}),'downloaded_preview_files':len(read(HERE/'image_receipts.json')),'failures':0})
print('IMAGE_LINKS_PASS','SOURCE_ROWS',len(results),'UNIQUE_IMAGES',len({r['image'] for r in results}))
