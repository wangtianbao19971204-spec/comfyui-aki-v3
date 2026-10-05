from pathlib import Path
import sys, json, re
from collections import Counter

HERE = Path(__file__).resolve().parent
PREV = HERE.with_name('2026-09-27_llama_verified_writeback')
sys.path.insert(0, str(PREV))
from common import DATA, PROJECTION, PROD, DB, T, P, sha, read, now, digest, load_rows
from independent_review import CONTEXT
from update_common import YOUTH, EXPLICIT
import psutil, requests

def save(name, value):
    (HERE/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

accepted = read(PREV/'EXECUTION_STATE.json')
assert sha(DATA) == accepted['data_sha256']
assert sha(PROJECTION) == accepted['projection_sha256']
owners = sorted({c.pid for c in psutil.net_connections('tcp') if c.status == 'LISTEN' and c.laddr.port == 8188})
assert len(owners) == 1
assert not any(c.status == 'LISTEN' and c.laddr.port == 8081 for c in psutil.net_connections('tcp'))
proc = psutil.Process(owners[0])
runtime = {'created_at': now(), 'owner': {'pid': proc.pid, 'create_time': proc.create_time(), 'command': proc.cmdline()}, 'data_sha256': sha(DATA), 'projection_sha256': sha(PROJECTION), 'engine_sha256': sha(PROD/'prompt_selector/semantic_refinements.py'), 'queue': requests.get('http://127.0.0.1:8188/queue', timeout=30).json(), 'workbench': requests.get('http://127.0.0.1:8188/unified-workbench/status', timeout=30).json()}
save('baseline_runtime.json', runtime)
data = read(DATA); doc = read(PROJECTION)
byid = {p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
raw = {r['source']:r for r in load_rows()}
reconciled = {r['source']:r for r in read(PREV/'reconciliation.json')}
old_reviews = read(PREV/'manual_reviews.json')
holds = read(PREV/'approved_classifications.json')['write_dispositions']
counts = Counter(); queue = []; seen = set(); records = []
for hold in holds:
    for source in hold['sources']:
        r = reconciled[source]; pid = r['id']
        item = {'source':source, 'id':pid, 'prior_hold':hold['reason'], 'same_body_normalized':r.get('same_body_normalized')}
        counts['remaining_sources'] += 1
        if not pid:
            item['next_action'] = 'no_local_resource'
        else:
            c,p = byid[pid]; d = P.decision_for(doc,c,p)
            body = T.strip_nonpositive_nai_weights(p['prompt']).replace('_', ' ')
            item.update(body_sha256=digest(p['prompt']), local_age_cue=bool(YOUTH.search(body)), local_explicit_cue=bool(EXPLICIT.search(body)), local_context_cue=bool(CONTEXT.search(body)))
            if pid in old_reviews:
                item['next_action'] = 'prior_direct_hold'
            elif d.get('semantic_review_status') == 'user_confirmed':
                item['next_action'] = 'manual_confirmation_preserved'
            elif not d.get('manual_search_eligible'):
                item['next_action'] = 'eligibility_preserved'
            elif item['local_explicit_cue'] or item['local_context_cue']:
                item['next_action'] = 'retain_context_hold_pending_evidence'
            else:
                item['next_action'] = 'direct_review_candidate'
                if pid not in seen:
                    seen.add(pid)
                    queue.append({'index':len(queue), 'id':pid, 'source':source, 'body_sha256':digest(p['prompt']), 'body':body, 'classification':d, 'prior_hold':hold['reason'], 'source_flags':raw[source]['flags'], 'same_body_normalized':r['same_body_normalized']})
        counts[item['next_action']] += 1
        records.append(item)
assert counts['remaining_sources'] == 2395
save('inventory.json', records)
save('direct_review_queue.json', queue)
summary = {'created_at':now(), 'source_counts':dict(counts), 'candidate_unique_resources':len(queue), 'prior_reason_counts':dict(Counter(r['prior_hold'] for r in records)), 'candidate_characters':sum(len(r['body']) for r in queue), 'local_model_used':False, 'production_mutated':False}
save('inventory_summary.json', summary)
print(json.dumps(summary, ensure_ascii=False))
