from common import *
import time

gate=load_script(OLD/'release_gate.py','final_gate');gate.SOURCES=STAGE;gate.DATA=HERE/'stage/data.json';gate.PROJECTION=HERE/'stage/semantic_projection.json'
p,r,t=runtime(STAGE,'final_gate_runtime');caller=gate.load_caller(p,t,r)
old=read(OLD/'release_gate_batch91_final_001.json')['contract']
measured=read(HERE/'measure_002/summary.json')['delta']
expected={key:dict(old[field]) for key,field in [('refinements','declared_delta'),('subcategories','declared_parent_delta'),('theme_ids','declared_theme_delta')]}
for axis,deltas in measured.items():
    for k,v in deltas.items():expected[axis][k]=expected[axis].get(k,0)+v
expected['refinements']['fabric.leather']-=1
start=time.time()
receipt={'created_at':now(),'source_sha256':{n:sha(STAGE/n) for n in gate.SOURCES_SHA},'data_sha256':sha(gate.DATA),'projection_sha256':sha(gate.PROJECTION),'declared':expected}
receipt['replay']=gate.run_replay(p,r,t,152,caller)
print('REPLAY',receipt['replay']['checks'],receipt['replay']['failures'],flush=True)
receipt['contract']=gate.run_contract(p,r,t,expected['refinements'],caller,expected['subcategories'],expected['theme_ids'])
receipt['passed']=receipt['replay']['failures']==0 and receipt['contract']['passed'];receipt['elapsed']=time.time()-start
save(HERE/'final_gate.json',receipt)
print(json.dumps({'passed':receipt['passed'],'elapsed':receipt['elapsed'],'unexplained_details':receipt['contract']['unexplained_detail_deltas'],'declared_mismatches':receipt['contract']['declared_mismatches']},ensure_ascii=False))
sys.exit(0 if receipt['passed'] else 1)
