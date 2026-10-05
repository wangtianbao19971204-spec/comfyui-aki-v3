"""Full rescan, using the hash-bound previous full index as a comparison cache."""
from common import *
import time, collections

prior=read(HERE/'measure_002/summary.json')
assert sha(HERE/'measure_002/index.jsonl')==prior['index_sha256']
out=HERE/'measure_final';out.mkdir(exist_ok=False)
previous={r['id']:r for r in (json.loads(line) for line in (HERE/'measure_002/index.jsonl').open(encoding='utf-8'))}
old_changes=read(HERE/'measure_002/changes.json')
for x in old_changes:
    for k,d in x['diff'].items():previous[x['id']][k]=sorted((set(previous[x['id']][k])-set(d['add']))|set(d['remove']))
gate=load_script(OLD/'release_gate.py','final_measure_gate');gate.SOURCES=STAGE
p,r,t=runtime(STAGE,'final_measure_runtime');caller=gate.load_caller(p,t,r)
doc=p.read_projection(HERE/'stage/semantic_projection.json');data=read(HERE/'stage/data.json')
bc={k:collections.Counter() for k in ('subcategories','refinements','theme_ids')};sc={k:collections.Counter() for k in bc}
changes=[];total=0;start=time.time()
with (out/'index.jsonl').open('w',encoding='utf-8',newline='\n') as stream:
    for cat in data['categories']:
        for row in cat.get('prompts',[]):
            if not isinstance(row.get('_classification'),dict):continue
            total+=1;b=previous.pop(row['id']);s=caller(doc,cat,row)['_semantic'];diff={}
            for k in bc:
                bv=set(b[k]);sv=set(s.get(k) or []);bc[k].update(bv);sc[k].update(sv)
                if bv!=sv:diff[k]={'add':sorted(sv-bv),'remove':sorted(bv-sv)}
            stream.write(json.dumps({'id':row['id'],**{k:s.get(k,[]) for k in bc}},ensure_ascii=False)+'\n')
            if diff:changes.append({'id':row['id'],'category':cat['name'],'prompt_sha256':hashlib.sha256(row.get('prompt','').encode()).hexdigest(),'diff':diff,'prompt':row.get('prompt','')})
            if total%50000==0:print(total,round(time.time()-start,1),flush=True)
assert not previous and bc==prior['baseline_counts']
delta={k:{n:sc[k][n]-bc[k][n] for n in sorted(bc[k].keys()|sc[k].keys()) if sc[k][n]!=bc[k][n]} for k in bc}
save(out/'changes.json',changes)
save(out/'summary.json',{'total':total,'changed_records':len(changes),'delta':delta,'elapsed':time.time()-start,'baseline_counts':bc,'candidate_counts':sc,'source_sha256':sha(STAGE/'semantic_refinements.py'),'data_sha256':sha(HERE/'stage/data.json'),'index_sha256':sha(out/'index.jsonl'),'comparison_cache_source_sha256':prior['source_sha256']})
print(json.dumps({'total':total,'changed':len(changes),'delta':delta},ensure_ascii=False),flush=True)
