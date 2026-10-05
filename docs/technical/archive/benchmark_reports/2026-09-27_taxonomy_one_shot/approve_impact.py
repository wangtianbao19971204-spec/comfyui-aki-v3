from common import *
from collections import Counter

first={x['id']:x for x in read(HERE/'measure_001/changes.json')}
second={x['id']:x for x in read(HERE/'measure_002/changes.json')}
parent_ids={x['id'] for x in read(HERE/'parent_edits.json')}
for rid,row in second.items():
    if rid in first:assert row['diff']==first[rid]['diff'],rid
    else:assert rid in parent_ids and row['diff']=={'subcategories':{'add':[],'remove':['首饰与随身配饰']}},rid
historical=read(HERE/'historical116_material_amendment.json')
expected={rid:x['diff'] for rid,x in second.items()}
assert historical['id'] not in expected
expected[historical['id']]={'refinements':{'add':[],'remove':['fabric.leather']}}
final=read(HERE/'measure_final/changes.json')
assert {x['id']:x['diff'] for x in final}==expected
assert len(final)==214
operations=[]
for x in final:
    for axis,delta in x['diff'].items():
        for operation,targets in delta.items():
            for target in targets:operations.append({'id':x['id'],'prompt_sha256':x['prompt_sha256'],'axis':axis,'operation':operation,'target':target})
assert len(operations)==218
save(HERE/'approved_operations.json',{'schema':'one-shot-approved-operations/v1','created_at':now(),'record_count':214,'operation_count':218,'source_sha256':sha(STAGE/'semantic_refinements.py'),'data_sha256':sha(HERE/'stage/data.json'),'operations':operations})
save(HERE/'impact_review.json',{'created_at':now(),'passed':True,'record_count':214,'operation_count':218,
    'review_method':'All original 76 bodies read. All 257 draft impact records reviewed using complete changed-material mentions and direct-light context windows; other changed-leaf bodies read. Narrowed final candidate is an exact subset with unchanged operations, plus two already-read headphone parent corrections and one completely-read round116 bag-material correction.',
    'material_review':'Every removed leather occurrence in the approved pattern radius refers to furniture/interior or anaphoric material; the body-bound round116 addition is tote bag material. Preserve garment/footwear material including suit, loafer, high-heel boots, mini skirt, moto jacket, patent-leather ensemble and leather-like dress.',
    'light_review':'New additions have explicit direct soft/even/diffused/gentle illumination. The broadened glow branch was withdrawn; taillight reflection and cup surface glow remain protected.',
    'other_review':'The first-draft full bodies for tree-man/pattern, numeric hair annotations, white very-long hair, no-text separator/from-above, hourglass body silhouette and nude-color heels were read and match exact approved leaf operations.',
    'conservative_withdrawals':'42 draft leather removals and 4 glow additions were withdrawn from the generic radius. One of those leather records (round116) is separately reviewed and repaired with its complete-body binding; the other withdrawn operations are not counted as repairs. This release does not claim global semantic completeness beyond the fixed scanner scope and individually approved changes.',
    'source_sha256':sha(STAGE/'semantic_refinements.py'),'measured_change_file_sha256':sha(HERE/'measure_final/changes.json'),'approved_operations_sha256':sha(HERE/'approved_operations.json')})
print('IMPACT_APPROVED',len(final),len(operations))
