from pathlib import Path
import sys, json, re
from collections import Counter

HERE = Path(__file__).resolve().parent
PREV = HERE.with_name('2026-09-27_llama_verified_writeback')
RECHECK = HERE.with_name('2026-09-27_remaining_classification')
sys.path.insert(0, str(PREV))
from common import read, save, sha, digest, now, load_rows, DATA, PROJECTION, PROD, T, P
from independent_review import CONTEXT
from update_common import YOUTH, EXPLICIT
import psutil, requests

def main():
    accepted = read(PREV/'EXECUTION_STATE.json')
    assert sha(DATA)==accepted['data_sha256'] and sha(PROJECTION)==accepted['projection_sha256']
    ports = psutil.net_connections('tcp')
    owners = sorted({c.pid for c in ports if c.status=='LISTEN' and c.laddr.port==8188})
    assert len(owners)==1
    assert not any(c.status=='LISTEN' and c.laddr.port==8081 for c in ports)
    proc=psutil.Process(owners[0])
    save(HERE/'baseline_runtime.json', {'created_at':now(),'data_sha256':sha(DATA),'projection_sha256':sha(PROJECTION),'engine_sha256':sha(PROD/'prompt_selector/semantic_refinements.py'),'owner':{'pid':proc.pid,'create_time':proc.create_time(),'command':proc.cmdline()},'queue':requests.get('http://127.0.0.1:8188/queue',timeout=30).json()})
    remaining = read(RECHECK/'remaining_dispositions.json')
    raw = {r['source']:r for r in load_rows()}
    previous_reviews = read(PREV/'manual_reviews.json')
    source_reviews = {r['source']:r for r in read(RECHECK/'source_context_decisions.json')}
    data=read(DATA); projection=read(PROJECTION)
    byid={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
    out=[]; candidates=[]; contexts=Counter()
    for r in remaining:
        src=raw[r['source']]; rec=src['record']; f=src['flags']
        item={'source':r['source'],'id':r['id'],'source_sha256':src['source_sha256'],'prior_next_action':r['next_action'],'already_direct_local_review':r['id'] in previous_reviews,'already_direct_source_review':r['source'] in source_reviews,'source_explicit_cue':bool(f['explicit_positive'] or f['explicit_title']),'source_context_cues':sorted({m.group(0).lower() for m in CONTEXT.finditer(rec['positive_prompt'])}), 'age_cues':sorted({m.group(0).lower() for m in YOUTH.finditer(rec['positive_prompt']+' '+rec['title']+' '+' / '.join(rec['source_path']))})}
        if item['id']:
            c,p=byid[item['id']]; d=P.decision_for(projection,c,p)
            item.update(local_body_sha256=digest(p['prompt']),user_confirmed=d.get('semantic_review_status')=='user_confirmed',eligible=bool(d.get('manual_search_eligible')),image_exists=bool(p.get('image')) and (PROD/'user_data/prompt_selector/preview'/p['image']).exists())
        if not item['source_explicit_cue'] and not item['already_direct_source_review'] and not item['already_direct_local_review']:
            candidates.append(item)
            contexts.update(item['source_context_cues'])
        out.append(item)
    assert len(out)==len({r['source'] for r in out})==2395
    save(HERE/'inventory.json',out)
    save(HERE/'remaining_metadata_candidates.json',candidates)
    summary={'created_at':now(),'remaining_sources':len(out),'new_source_context_candidates':len(candidates),'candidate_context_counts':dict(contexts),'candidate_presence':dict(Counter('local_resource' if r['id'] else 'missing_resource' for r in candidates)),'production_mutated':False,'local_model_used':False}
    save(HERE/'inventory_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':main()
