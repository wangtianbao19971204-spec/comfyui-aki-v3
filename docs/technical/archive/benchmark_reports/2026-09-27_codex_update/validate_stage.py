from update_common import *
import sqlite3, shutil

ops=read(HERE/'operations.json');summary=read(HERE/'stage_summary.json')
old=read(BACKUP/'data.json');new=read(STAGE/'data.json')
oldcat={c['id']:c for c in old['categories']};newcat={c['id']:c for c in new['categories']}
before={p['id']:(c,p) for c in old['categories'] for p in c['prompts']}
after={p['id']:(c,p) for c in new['categories'] for p in c['prompts']}
assert len(after)==sum(len(c['prompts']) for c in new['categories'])
assert not set(before)-set(after)
allowed={o['id'] for o in ops if o['store']=='library'}
add={o['id'] for o in ops if o['store']=='library' and 'add' in o['action']}
updates={o['id'] for o in ops if 'upstream_body_update' in o['action']}
assert set(after)-set(before)==add
changes=[]
personal_preserved=0
for pid,(c,p) in before.items():
    nc,np=after[pid];assert c['id']==nc['id']
    if pid not in allowed:assert p==np,pid
    else:
        fields=[k for k in set(p)|set(np) if p.get(k)!=np.get(k)]
        assert set(fields)<={'prompt','image','updated_at','description','_external_source','_classification'},(pid,fields)
        if pid in updates:
            for f in ('primary_class','manual_search_eligible','random_pool_eligible','strict_model_pool_eligible','model_scope','semantic_review_status'):
                assert p['_classification'].get(f)==np['_classification'].get(f),(pid,f)
        changes.append({'id':pid,'changed_fields':fields})
    personal_preserved+=1
for cid,c in oldcat.items():assert {k:v for k,v in c.items() if k!='prompts'}=={k:v for k,v in newcat[cid].items() if k!='prompts'}
assert {k:v for k,v in old.items() if k not in ('categories','last_modified')}=={k:v for k,v in new.items() if k not in ('categories','last_modified')}
assert new['last_modified']>old['last_modified']
assert sha(PROJECTION)==sha(STAGE/'semantic_projection.json')==sha(BACKUP/'semantic_projection.json')
projection=read(STAGE/'semantic_projection.json');statuses=Counter()
for pid,(c,p) in after.items():
    d=P.decision_for(projection,c,p);statuses[d['disposition']]+=1
    if pid in add|updates:
        assert d.get('primary_class') in T.CLASS_LABELS,pid
        assert not set(d.get('subcategories',[]))-set(T.SUBCATEGORY_PARENTS),pid
        assert d.get('binding')==P.binding(c,p),pid
assert statuses['pending']==4 and not statuses['quarantined'],statuses
bodies=defaultdict(list)
for pid,(c,p) in after.items():bodies[norm(p['prompt'])].append(pid)
duplicates=[ids for ids in bodies.values() if len(ids)>1 and set(ids)&add]
assert not duplicates,duplicates[:5]

def rows(conn,table,key):
    conn.row_factory=sqlite3.Row
    return {r[key]:dict(r) for r in conn.execute('select * from '+table)}
with sqlite3.connect(BACKUP/'tags.db') as a,sqlite3.connect(STAGE/'tags.db') as b:
    assert b.execute('pragma integrity_check').fetchone()[0]=='ok'
    assert not b.execute('pragma foreign_key_check').fetchall()
    at=rows(a,'tag_tags','t_uuid');bt=rows(b,'tag_tags','t_uuid')
    tagadds={o['id'] for o in ops if o['store']=='tags' and 'add' in o['action']}
    tagupdates={o['id'] for o in ops if 'paired_body_update' in o['action']}
    assert set(bt)-set(at)==tagadds and not set(at)-set(bt)
    for uid,t in at.items():
        if uid in tagupdates:assert {k:v for k,v in t.items() if k!='text'}=={k:v for k,v in bt[uid].items() if k!='text'}
        else:assert t==bt[uid],uid
    am={uid:json.loads(s) for uid,s in a.execute('select tag_uuid,data from workbench_tag_meta')}
    bm={uid:json.loads(s) for uid,s in b.execute('select tag_uuid,data from workbench_tag_meta')}
    previews={o['id'] for o in ops if o['store']=='tags' and 'preview_update' in o['action']}
    for uid,m in am.items():
        if uid in previews:assert {k:v for k,v in m.items() if k!='preview'}=={k:v for k,v in bm[uid].items() if k!='preview'}
        else:assert m==bm[uid],uid
    for table,key in [('tag_groups','p_uuid'),('tag_subgroups','g_uuid')]:
        ar=rows(a,table,key);br=rows(b,table,key)
        for k,v in ar.items():assert br[k]==v
    valid={r[0]:r[1] for r in b.execute('select id_index,g_uuid from tag_subgroups')}
    assert all(valid.get(bt[uid]['subgroup_id'])==bt[uid]['g_uuid'] for uid in tagadds)
    oldnorm={norm(t['text']) for t in at.values()};newnorm=[norm(bt[uid]['text']) for uid in tagadds]
    assert not oldnorm&set(newnorm) and len(newnorm)==len(set(newnorm))
    revisions={name:{'before':a.execute('select * from '+name).fetchall()[0][-1],'after':b.execute('select * from '+name).fetchall()[0][-1]} for name in ('workbench_tag_revision','workbench_tag_text_revision')}
    assert all(v['after']>v['before'] for v in revisions.values())

registry=read(HERE/'source_registry.json');sources_bykey={source_key(m,e):(m,e) for m,e in sources()}
assert len(registry)==len(sources_bykey)==40386
assert len({r['source'] for r in registry})==len(registry)
image_sources={r['source'] for r in read(HERE/'image_plan.json')}
for row in registry:
    m,e=sources_bykey[row['source']];reason=exclusion(m,e)
    if reason:
        assert row['disposition']=='excluded' and row['source'] not in image_sources
        assert not any(o['source']==row['source'] for o in ops)
    elif row['disposition']=='no_prompt_content':assert not content(e)
    else:
        target=row['target_id'];assert target in (bt if row['disposition'].startswith('tag') else after)
        details=row['source_details'];assert details['negative']==e.get('negative','') and details['character_prompts']==e.get('characterPrompts',[]) and details['images']==e.get('images',[])
    if row['disposition']=='library_added':assert after[row['target_id']][1]['prompt']==content(e)
    if row['disposition']=='tag_added':assert bt[row['target_id']]['text']==content(e)

pairs=read(STAGE/'shared_pairs.json')['pairs']
shared=importlib.import_module('codex_update_runtime.shared_sync')
assert len(pairs)==len(set(pairs.values()))
for pid,uid in pairs.items():assert shared.concept_key(after[pid][1]['prompt'])==shared.concept_key(bt[uid]['text'])
# Rehearse file replacement and restoration inside a contained scratch folder.
drill=HERE/'rollback_drill';drill.mkdir(exist_ok=True);restored={}
for filename in ('data.json','semantic_projection.json','tags.db','shared_pairs.json','semantic_refinements.py'):
    stage=STAGE/filename if filename!='semantic_refinements.py' else STAGE/'prompt_selector'/filename
    target=drill/filename;shutil.copy2(BACKUP/filename,target);shutil.copy2(stage,target);assert sha(target)==sha(stage)
    shutil.copy2(BACKUP/filename,target);assert sha(target)==sha(BACKUP/filename);restored[filename]=sha(target)
receipt={'passed':True,'created_at':now(),'data_sha256':sha(STAGE/'data.json'),'db_sha256':sha(STAGE/'tags.db'),'pairs_sha256':sha(STAGE/'shared_pairs.json'),'engine_sha256':sha(STAGE/'prompt_selector/semantic_refinements.py'),'library_before':len(before),'library_after':len(after),'library_added':len(add),'body_updates':len(updates),'existing_library_changes':changes,'tag_before':len(at),'tag_after':len(bt),'tag_added':len(tagadds),'paired_tag_body_updates':len(tagupdates),'existing_tag_previews':len(previews),'all_existing_personal_fields_preserved':personal_preserved,'new_duplicate_bodies':0,'review_counts':dict(statuses),'source_dispositions':dict(Counter(r['disposition'] for r in registry)),'tag_revisions':revisions,'shared_pairs':len(pairs),'rollback_restored':restored}
save(HERE/'data_validation.json',receipt)
print('DATA_VALIDATION_PASS',len(after),len(bt),dict(statuses),flush=True)
