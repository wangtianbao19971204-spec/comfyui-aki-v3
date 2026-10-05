from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,re,unicodedata,sqlite3

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PROD=ROOT/'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector'
OLD=ROOT/'benchmark_reports/2026-09-15_tag_folder_classification'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
def norm(s):
    s=unicodedata.normalize('NFKC',s or '').replace('_',' ').replace('\\','')
    s=re.sub(r'\s+',' ',s).strip().casefold()
    return re.sub(r'\s*([,:{}\[\]()])\s*',r'\1',s).strip(', ')

def content(e):
    text=str(e.get('tags') or '')
    for cp in e.get('characterPrompts') or []:
        body=cp.get('prompt') or ''
        if body: text+='\n'+str(cp.get('label') or 'character')+': '+body
    return text.strip()

def main():
    data=read(PROD/'user_data/prompt_selector/data.json')
    byid={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
    aliases=defaultdict(list);bodies=defaultdict(list)
    for pid,(c,p) in byid.items():
        aliases[norm(p.get('alias'))].append(pid)
        bodies[norm(p['prompt'])].append(pid)
    merged=data.get('_source_to_canonical',{})
    with sqlite3.connect('file:'+(PROD/'user_data/userdatas_zh_CN_tags.db').as_posix()+'?mode=ro',uri=True) as conn:
        tag_rows=conn.execute('SELECT t_uuid,text FROM tag_tags').fetchall()
        tag_meta={uid:json.loads(meta) for uid,meta in conn.execute('SELECT tag_uuid,data FROM workbench_tag_meta')}
    tag_bodies=defaultdict(list)
    for uid,body in tag_rows:tag_bodies[norm(body)].append(uid)
    print('MERGED_TYPE',type(merged).__name__,'SAMPLE',str(list(merged.items())[:2])[:650])
    old={}
    for file in [OLD/'r2_suozhang.json',OLD/'r2_suozhang_r18.json',OLD/'r2_nai45_community_pack.json',*(OLD/'official_data').glob('*.json')]:
        v=read(file)
        if isinstance(v,dict):
            for e in v.get('entries',[]):old[e['id']]=e
    original={e['id']:e for e in read(OLD/'phase2/official_entries_v2.json')}
    rows=[];summaries=[];web=HERE/'sources/web'
    for meta in read(web/'codexes.json'):
        name=meta['id'];file=web/(name+'.external.json')
        if not file.exists():file=web/(name+'.json')
        entries=read(file)['entries'];counts=Counter();examples=[]
        for e in entries:
            body=content(e);source_id=e['id'];pid='codex-'+source_id;method='id'
            seen=set()
            while pid not in byid and pid in merged and pid not in seen:
                seen.add(pid);m=merged[pid];pid=m if isinstance(m,str) else m.get('canonical_id',m.get('canonicalId',''));method='merged_id'
            if pid not in byid:
                matches=bodies.get(norm(body),[])
                if not matches and not e.get('characterPrompts'):matches=bodies.get(norm(e.get('tags')),[])
                if matches:pid=min(matches,key=lambda x:(not x.startswith('codex-'),x));method='body'
                else:
                    possible=[x for x in aliases.get(norm(e.get('title')),[]) if x.startswith(('codex-','docx-'))]
                    # Title alone is never an accepted identity; preserve it for review.
                    pid=None;method='unmatched'
            item={'dataset':name,'id':source_id,'title':e.get('title'),'path':e.get('path',[]),'target_id':pid,'match':method,'has_image':bool(e.get('image')),'body_sha256':hashlib.sha256(body.encode()).hexdigest()}
            if pid:
                c,p=byid[pid];current=p['prompt'];before=old.get(source_id,{})
                item.update(category=c['name'],same_body=norm(current)==norm(body),same_main=norm(current)==norm(e.get('tags')),local_image=bool(p.get('image')),user_confirmed=p.get('_classification',{}).get('semantic_review_status')=='user_confirmed',old_web_exists=bool(before),web_body_changed=bool(before) and norm(content(before))!=norm(body),local_matches_old=bool(before) and norm(current) in {norm(content(before)),norm(before.get('tags')),norm(original.get(source_id,{}).get('content'))})
                counts['same_body' if item['same_body'] else 'different_body']+=1
                if item['web_body_changed']:counts['upstream_body_changed']+=1
                if not item['local_image'] and item['has_image']:counts['missing_image']+=1
            else:
                item['title_candidates']=possible
                tag_matches=tag_bodies.get(norm(body),[])
                item['tag_matches']=tag_matches
                if tag_matches:counts['present_in_tags']+=1
                item['short']=len([p for p in re.split('[,，]',body) if p.strip()])<=4
                if len(examples)<8:examples.append({'title':e.get('title'),'path':e.get('path'),'title_candidates':len(possible)})
            counts[method]+=1;rows.append(item)
        summary={'dataset':name,'entries':len(entries),'counts':dict(counts),'unmatched_examples':examples};summaries.append(summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    (HERE/'matching.json').write_text(json.dumps(rows,ensure_ascii=False,indent=1),encoding='utf-8')
    (HERE/'matching_summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TOTAL',len(rows),dict(Counter(x['match'] for x in rows)))
if __name__=='__main__':main()
