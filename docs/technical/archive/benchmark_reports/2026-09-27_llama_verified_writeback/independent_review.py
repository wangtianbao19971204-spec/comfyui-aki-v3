from common import *
from collections import Counter
import re

# This is a conservative write hold, not a content category or a clearance rule.
CONTEXT=re.compile(r'\b(?:lolicon|mesugaki|bdsm|bondage|gag(?:ged)?|frogtie|arousal|aroused|orgasm\w*|seductive|sensual|provocative|erotic|undress\w*|panties|underwear|bra|lingerie|spread legs|legs apart|leg apart|between (?:her |his |the )?legs|thigh gap|breast press|breasts on|see[- ]through (?:shirt|clothes)|cleavage|cameltoe|ass focus|crotch|groin|bulge|breasts? focus|licking|pantyshot|upskirt|suggestive)\b',re.I)

def build():
    groups=read(HERE/'verification_manifest.json')
    raw={r['source']:r for r in load_rows()}
    reconciliation={r['source']:r for r in read(HERE/'reconciliation.json')}
    proposals={r['source']:r for r in read(PREV/'classification_results.json')}
    data=read(DATA);byid={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
    queue=[];held=[]
    for job in groups:
        reason=None
        if any(any(raw[s]['flags'][k] for k in ('age_positive','age_title','age_path')) and any(raw[s]['flags'][k] for k in ('explicit_positive','explicit_title')) for s in job['sources']):reason='existing_source_exclusion_retained'
        elif not job['ids']:reason='no_existing_resource_target'
        elif any(reconciliation[s].get('user_confirmed') for s in job['sources']):reason='user_confirmed_preserved'
        elif any(not reconciliation[s].get('classification',{}).get('manual_search_eligible') for s in job['sources'] if reconciliation[s]['id']):reason='eligibility_preserved'
        elif any(CONTEXT.search(raw[s]['record']['positive_prompt']) for s in job['sources']):reason='age_context_requires_retaining_exclusion'
        if reason:
            held.append({'key':job['key'],'sources':job['sources'],'ids':job['ids'],'reason':reason});continue
        for pid in job['ids']:
            c,p=byid[pid];positive=T.strip_nonpositive_nai_weights(p['prompt']).replace('_',' ')
            assert digest(positive)==job['key']
            if CONTEXT.search(positive):
                held.append({'key':job['key'],'sources':job['sources'],'ids':[pid],'reason':'local_context_requires_retaining_exclusion'});continue
            queue.append({'key':job['key'],'id':pid,'sources':job['sources'],'body_sha256':digest(p['prompt']),'body':positive,'raw_body':p['prompt'],'original_proposal':{k:proposals[job['sources'][0]][k] for k in ('primary_class','subcategories')},'current_classification':P.decision_for(read(PROJECTION),c,p) if False else reconciliation[job['sources'][0]]['classification']})
    save(HERE/'independent_review_queue.json',queue);save(HERE/'independent_write_holds.json',held)
    print(json.dumps({'full_source_coverage':sum(len(j['sources']) for j in groups),'direct_review_records':len(queue),'held_groups':dict(Counter(r['reason'] for r in held))},ensure_ascii=False))

if __name__=='__main__':build()
