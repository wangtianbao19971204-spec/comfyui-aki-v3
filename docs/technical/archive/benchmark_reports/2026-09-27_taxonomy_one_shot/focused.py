from common import *
gate=load_script(OLD/'release_gate.py','focused_gate');gate.SOURCES=STAGE
p,r,t=runtime(STAGE,'focused_runtime');caller=gate.load_caller(p,t,r)
doc=p.read_projection(HERE/'stage/semantic_projection.json')
data=read(HERE/'stage/data.json');rows={v['id']:(c,v) for c in data['categories'] for v in c.get('prompts',[])}
checks=[]
for j in read(HERE/'review_decisions.json'):
    c,v=rows[j['id']];s=caller(doc,c,v)['_semantic'];collection=s['subcategories'] if 'parent' in j['flag']['kind'] else s['refinements']
    checks.append({'n':j['n'],'target':j['flag']['target'],'passed':(j['flag']['target'] in collection)==j['expected_present']})
print(json.dumps({'checks':len(checks),'failures':[x for x in checks if not x['passed']]},ensure_ascii=False))
save(HERE/'focused_latest.json',{'checks':checks,'passed':all(x['passed'] for x in checks),'source_sha256':sha(STAGE/'semantic_refinements.py'),'data_sha256':sha(HERE/'stage/data.json')})
if len(sys.argv)>1:
    for rid in sys.argv[1:]:
        c,v=rows[rid];print(json.dumps({'id':rid,'prompt':v['prompt'],'semantic':caller(doc,c,v)['_semantic']},ensure_ascii=False))
