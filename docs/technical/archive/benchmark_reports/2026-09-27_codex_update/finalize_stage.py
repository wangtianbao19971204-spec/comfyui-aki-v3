from update_common import *
import sqlite3, shutil

data=read(STAGE/'data.json'); old=read(BACKUP/'data.json')
before={p['id']:(c,p) for c in old['categories'] for p in c['prompts']}
after={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
ops=read(HERE/'operations.json'); edits=[]
for op in ops:
    if 'upstream_body_update' not in op['action']:continue
    c,p=after[op['id']];bc,bp=before[op['id']]
    decision=copy.deepcopy(bp['_classification'])
    # A source revision does not withdraw confirmed eligibility, primary focus,
    # or broad parents that the narrower leaf vocabulary cannot recognize.
    additions=set(p['_classification']['subcategories'])-set(decision['subcategories'])
    decision['subcategories']=list(decision['subcategories'])+sorted(additions)
    decision['count_markers']=T.original_count_markers(p['prompt'])
    decision['alternative_classes']=sorted(set(decision.get('alternative_classes',[]))|{T.SUBCATEGORY_PARENTS[x] for x in additions}-{decision['primary_class']})
    decision['binding']=P.binding(c,p);p['_classification']=decision
    edits.append({'id':p['id'],'reason':'preserve_existing_classification_and_eligibility_on_source_revision','primary':decision['primary_class'],'added_parents':sorted(additions)})

reviewed={
 'codex-suozhang-5236':('pose_action',['战斗与施法','文字与图形'],'Positive body explicitly says fighting and a screen health bar; no specific combat leaf inferred.'),
 'codex-suozhang-0611':('object_prop',[],'Standalone gemstones and precious metals; retain broad object theme without guessing wearable jewelry.'),
 'codex-suozhang_nai5-0073':('style_medium',['三维与数字渲染','作品角色'],'Explicit Minecraft block-body style and the named work; no additional character traits inferred.'),
 'codex-suozhang_nai5_r18-0161':('composition_camera',['多格与连续画面','布局与画面结构','视角与透视','室内空间','惊讶与紧张','视线方向'],'Complete Chinese body explicitly specifies two panels, rear view, a restroom, looking and a surprised face.'),
}
for pid,(primary,parents,reason) in reviewed.items():
    c,p=after[pid];d=p['_classification'];d.update(primary_class=primary,subcategories=parents,classification_uncertain=False,alternative_classes=sorted({T.SUBCATEGORY_PARENTS[s] for s in parents}-{primary}),note=reason)
    d['binding']=P.binding(c,p);edits.append({'id':pid,'reason':reason,'primary':primary,'parents':parents})

# Full-body review of the new scan findings: existing vocabulary supplies these
# broad parents even where no narrow leaf has been registered.
for finding in read(HERE/'new_scan_findings.json'):
    if finding['id'] not in after:continue
    c,p=after[finding['id']]
    assert hashlib.sha256(p['prompt'].encode()).hexdigest()==finding['prompt_sha256']
    for flag in finding['flags']:
        if flag['kind']!='missing_parent':continue
        parent=flag['target'];d=p['_classification']
        if parent not in d['subcategories']:d['subcategories'].append(parent)
        d['alternative_classes']=sorted(set(d['alternative_classes'])|({T.SUBCATEGORY_PARENTS[parent]}-{d['primary_class']}))
        edits.append({'id':p['id'],'prompt_sha256':finding['prompt_sha256'],'added_parent':parent,'reason':'Full positive body directly depicts the named garment cut, headwear, or prison interior.'})
    p['_classification']['binding']=P.binding(c,p)

# Refresh only derived pair identities. Changed bodies must no longer retain a
# stale reverse link to an old Tag body; this step does not edit either body.
shared=importlib.import_module('codex_update_runtime.shared_sync')
pairpath=DATA.with_name('shared_pairs.json')
if not (BACKUP/'shared_pairs.json').exists():shutil.copy2(pairpath,BACKUP/'shared_pairs.json')
with sqlite3.connect(STAGE/'tags.db') as db:
    previous_pairs=read(BACKUP/'shared_pairs.json')['pairs'];mirrored=[]
    for op in list(ops):
        if 'upstream_body_update' not in op['action']:continue
        uid=previous_pairs.get(op['id'])
        if not uid:continue
        current=db.execute('select text from tag_tags where t_uuid=?',(uid,)).fetchone()
        c,p=after[op['id']];bc,bp=before[op['id']]
        assert current and norm(current[0]) in (norm(bp['prompt']),norm(p['prompt']))
        if current[0]!=p['prompt']:db.execute('update tag_tags set text=? where t_uuid=?',(p['prompt'],uid))
        mirrored.append({'store':'tags','id':uid,'action':['paired_body_update'],'library_id':p['id'],'source':op['source']})
    ops=[o for o in ops if 'paired_body_update' not in o['action']]+mirrored
    save(HERE/'operations.json',ops)
    pairs=shared.build_pairs(db.execute('select t_uuid,text from tag_tags'),((p['id'],p['prompt']) for c,p in after.values()))
save(STAGE/'shared_pairs.json',{'version':shared.PAIR_VERSION,'generated_at':now(),'library_revision':data['last_modified'],**pairs})
with (STAGE/'data.json').open('w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,separators=(',',':'))
save(HERE/'classification_adjudication.json',{'passed':True,'changes':edits,'old_primary_and_eligibility_preserved':46,'new_unclassified_resolved':4,'new_record_method':'Current deployed phrase/context rules with explicit per-record broad-parent review; not a claim of exhaustive manual semantic review.'})
summary=read(HERE/'stage_summary.json');summary['stats']['paired_tag_body_updates']=len(mirrored);summary.update(stage_data_sha256=sha(STAGE/'data.json'),stage_db_sha256=sha(STAGE/'tags.db'),stage_pairs_sha256=sha(STAGE/'shared_pairs.json'))
save(HERE/'stage_summary.json',summary)
print('FINALIZED',len(edits),'PAIRS',len(pairs['pairs']),flush=True)
