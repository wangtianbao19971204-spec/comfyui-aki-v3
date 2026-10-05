from common import *
import copy, shutil
from collections import Counter

stage=HERE/'stage'; stage.mkdir(exist_ok=True)
backup=HERE/'backup'
assert sha(DATA)==sha(backup/'data.json')
assert sha(PROJECTION)==sha(backup/'semantic_projection.json')
data=read(backup/'data.json'); doc=read(backup/'semantic_projection.json')
original=copy.deepcopy(data); original_doc=copy.deepcopy(doc)
byid={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
approved=read(HERE/'approved_classifications.json')
assert approved['passed'] and approved['decisions']
operations=[]
inverse={v:k for k,v in T.FACET_CLASS_MAP.items()}
for row in approved['decisions']:
    c,p=byid[row['id']]; old=P.decision_for(doc,c,p)
    assert digest(p['prompt'])==row['body_sha256']
    assert old.get('semantic_review_status')!='user_confirmed'
    assert old.get('manual_search_eligible')
    assert row['primary_class'] in T.CLASS_LABELS
    assert set(row['subcategories'])<=set(T.SUBCATEGORY_PARENTS)
    owners={T.SUBCATEGORY_PARENTS[s] for s in row['subcategories']}
    assert row['primary_class'] in owners or row['primary_class']=='person_count'
    new=copy.deepcopy(old)
    new.update(primary_class=row['primary_class'],subcategories=sorted(set(row['subcategories'])),alternative_classes=sorted(owners-{row['primary_class'],'person_count'}),classification_uncertain=False)
    new['themes']=sorted({inverse.get(owner,owner) for owner in owners|{row['primary_class']} if owner!='person_count'}|({'count'} if old.get('count_markers') else set()))
    fields=('primary_class','subcategories','alternative_classes','classification_uncertain','themes')
    if all(old.get(f)==new.get(f) for f in fields):continue
    new['semantic_review_status']='independently_verified_2026_09_27'
    new['binding']=P.binding(c,p)
    p['_classification']=new
    if p['id'] in doc['decisions']:doc['decisions'][p['id']]=copy.deepcopy(new)
    operations.append({'id':p['id'],'sources':row['sources'],'body_sha256':row['body_sha256'],'binding':new['binding'],'before':{f:old.get(f) for f in fields},'after':{f:new.get(f) for f in fields},'review':row['review']})
assert operations
data['last_modified']=datetime.now().isoformat()
save(stage/'data.json',data);save(stage/'semantic_projection.json',doc)
source=stage/'prompt_selector';source.mkdir(exist_ok=True)
for path in (PROD/'prompt_selector').glob('*.py'):shutil.copy2(path,source/path.name)
changed={o['id'] for o in operations}
old_byid={p['id']:(c,p) for c in original['categories'] for p in c['prompts']}
assert set(byid)==set(old_byid)
for c,oc in zip(data['categories'],original['categories']):
    assert {k:v for k,v in c.items() if k!='prompts'}=={k:v for k,v in oc.items() if k!='prompts'}
for pid,(c,p) in byid.items():
    oc,op=old_byid[pid]
    assert {k:v for k,v in p.items() if k!='_classification'}=={k:v for k,v in op.items() if k!='_classification'},pid
    if pid not in changed:assert p==op,pid
    old=P.decision_for(original_doc,oc,op); new=P.decision_for(doc,c,p)
    for field in ('disposition','content_type','usage','declared_usage','model_scope','manual_search_eligible','random_pool_eligible','strict_model_pool_eligible','count_markers','note','note_kind'):
        assert old.get(field)==new.get(field),(pid,field)
    if pid in changed:
        assert new['binding']==P.binding(c,p)
        assert new['subcategories']==p['_classification']['subcategories']
assert {k:v for k,v in data.items() if k not in ('last_modified','categories')}=={k:v for k,v in original.items() if k not in ('last_modified','categories')}
for pid,d in original_doc['decisions'].items():
    if pid not in changed:assert doc['decisions'][pid]==d
assert {k:v for k,v in doc.items() if k!='decisions'}=={k:v for k,v in original_doc.items() if k!='decisions'}
save(HERE/'operations.json',operations)
save(HERE/'data_validation.json',{'passed':True,'created_at':now(),'data_sha256':sha(stage/'data.json'),'projection_sha256':sha(stage/'semantic_projection.json'),'raw_records_checked':len(byid),'changed_records':len(changed),'unchanged_bodies_images_favorites_notes_and_eligibility':True,'new_or_removed_resources':0,'tag_store_mutated':False,'manual_confirmations_preserved':True})
save(HERE/'EXECUTION_STATE.json',{'status':'staged_not_applied','production_mutated':False,'changed_records':len(changed),'updated_at':now()})
print('STAGE_VALIDATED',len(changed),'OF',len(byid),flush=True)
