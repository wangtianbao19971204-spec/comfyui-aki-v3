from common import *
import re

gate=load_script(OLD/'release_gate.py','impact_gate');gate.SOURCES=STAGE
p,r,t=runtime(STAGE,'impact_runtime');caller=gate.load_caller(p,t,r)
doc=p.read_projection(HERE/'stage/semantic_projection.json')
original=read(HERE/'measure_001/changes.json');wanted={x['id'] for x in original}
data=read(HERE/'stage/data.json');records={v['id']:(c,v) for c in data['categories'] for v in c.get('prompts',[]) if v['id'] in wanted}
out=[]
for i,x in enumerate(original,1):
    c,v=records[x['id']];s=caller(doc,c,v)['_semantic'];part=' '.join(r._positive_parts(v['prompt']))
    x=dict(x,n=i,current_leaves=s['refinements'],soft_matches=[part[max(0,m.start()-90):m.end()+110] for m in r._B90_SOFT_DIRECT.finditer(part)],leather_windows=[part[max(0,m.start()-95):m.end()+95] for m in re.finditer(r'\b(?:leather|suede)\b',part)])
    out.append(x)
save(HERE/'impact_contexts_002.json',out)
print('contexts',len(out))
mode=sys.argv[1] if len(sys.argv)>1 else ''
start=int(sys.argv[2]) if len(sys.argv)>2 else 0
end=int(sys.argv[3]) if len(sys.argv)>3 else 999
selected=[x for x in out if 'fabric.leather' in x['diff'].get('refinements',{}).get('remove',[]) and 'fabric.leather' not in x['current_leaves']] if mode=='leather' else [x for x in out if 'light_effect.soft' in x['diff'].get('refinements',{}).get('add',[])]
print('selected',len(selected))
for x in selected[start:end]:print(x['n'],x['id'],json.dumps(x['leather_windows'] if mode=='leather' else x['soft_matches'],ensure_ascii=False))
