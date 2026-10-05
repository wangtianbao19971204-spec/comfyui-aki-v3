from audit_remaining import *

rows=read(HERE/'remaining_metadata_candidates.json')
raw={r['source']:r for r in load_rows()}
start=int(sys.argv[1]); end=int(sys.argv[2])
for i in range(start,min(end,len(rows))):
    row=rows[i]; record=raw[row['source']]['record']
    print(json.dumps({'index':i,'source':row['source'],'id':row['id'],'age_cues':row['age_cues'],'context_cues':row['source_context_cues'],'title':record['title'],'path':record['source_path'],'full_positive_body':record['positive_prompt']},ensure_ascii=False))
