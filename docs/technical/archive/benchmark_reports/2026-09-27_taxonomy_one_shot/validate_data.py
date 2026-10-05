from common import *
import copy, collections, os, shutil

baseline=read(HERE/'backup/data.json');candidate=read(HERE/'stage/data.json')
changes=[];edits={e['id']:e for e in read(HERE/'parent_edits.json')}
assert baseline.keys()==candidate.keys()
for k in baseline:
    if k!='categories':assert baseline[k]==candidate[k],k
assert len(baseline['categories'])==len(candidate['categories'])
total=0
for before,after in zip(baseline['categories'],candidate['categories']):
    assert {k:v for k,v in before.items() if k!='prompts'}=={k:v for k,v in after.items() if k!='prompts'}
    assert len(before['prompts'])==len(after['prompts'])
    for b,a in zip(before['prompts'],after['prompts']):
        total+=1
        if b==a:continue
        assert b['id']==a['id'] and b['id'] in edits
        expected=copy.deepcopy(b);expected['_classification']['subcategories'].remove('首饰与随身配饰')
        assert expected==a,b['id']
        changes.append(b['id'])
assert set(changes)==set(edits)
del baseline,candidate
projection=read(HERE/'stage/semantic_projection.json')
assert dict(collections.Counter(x['disposition'] for x in projection['decisions'].values()))==projection['counts']
assert sha(HERE/'stage/semantic_projection.json')==sha(HERE/'backup/semantic_projection.json')
# Rehearse failure after partial replacement in an isolated directory, then
# restore every file through the same fsync + atomic-replace primitive.
def replace(src,dst):
    tmp=dst.with_name(dst.name+'.replacing')
    with Path(src).open('rb') as i,tmp.open('wb') as o:
        shutil.copyfileobj(i,o,1024*1024);o.flush();os.fsync(o.fileno())
    os.replace(tmp,dst)
drill=HERE/'rollback_drill';drill.mkdir(exist_ok=True)
names=['data.json','semantic_projection.json','semantic_refinements.py']
for name in names:replace(HERE/'backup'/name,drill/name)
replace(HERE/'stage/data.json',drill/'data.json')
assert sha(drill/'data.json')!=sha(HERE/'backup/data.json')
for name in names:replace(HERE/'backup'/name,drill/name)
assert all(sha(drill/name)==sha(HERE/'backup'/name) for name in names)
save(HERE/'data_invariants_and_rollback.json',{'passed':True,'raw_records':total,'changed_ids':changes,'only_field_changed':'_classification.subcategories; remove 首饰与随身配饰','projection_regenerated_identically':True,'rollback_partial_replacement_drill_passed':True,'data_sha256':sha(HERE/'stage/data.json'),'projection_sha256':sha(HERE/'stage/semantic_projection.json'),'engine_sha256':sha(STAGE/'semantic_refinements.py')})
print('DATA_INVARIANTS_AND_ROLLBACK_OK',total,len(changes))
