from common import *
import time, collections, copy

label=sys.argv[1]
out=HERE/label;out.mkdir(exist_ok=False)
gate=load_script(OLD/'release_gate.py','measure_gate')
bp,br,bt=runtime(SOURCES,'baseline_runtime')
sp,sr,st=runtime(STAGE,'stage_runtime')
bc=gate.load_caller(bp,bt,br)
gate.SOURCES=STAGE
sc=gate.load_caller(sp,st,sr)
doc=sp.read_projection(HERE/'stage/semantic_projection.json')
data=read(HERE/'stage/data.json')
edits={e['id']:e for e in read(HERE/'parent_edits.json')}
baseline_counts={k:collections.Counter() for k in ('subcategories','refinements','theme_ids')}
candidate_counts={k:collections.Counter() for k in baseline_counts}
changes=[];total=0;start=time.time();cases={r['id']:r for r in read(HERE/'review_decisions.json')};checks=[]
with (out/'index.jsonl').open('w',encoding='utf-8',newline='\n') as stream:
    for cat in data['categories']:
        for row in cat.get('prompts',[]):
            if not isinstance(row.get('_classification'),dict):continue
            total+=1
            old=copy.deepcopy(row) if row['id'] in edits else row
            if row['id'] in edits:old['_classification']=edits[row['id']]['before_classification']
            b=bc(doc,cat,old)['_semantic'];s=sc(doc,cat,row)['_semantic']
            diff={}
            for k in baseline_counts:
                bv=set(b.get(k) or []);sv=set(s.get(k) or [])
                baseline_counts[k].update(bv);candidate_counts[k].update(sv)
                if bv!=sv:diff[k]={'add':sorted(sv-bv),'remove':sorted(bv-sv)}
            index={'id':row['id'],'subcategories':s['subcategories'],'refinements':s['refinements'],'theme_ids':s.get('theme_ids',[])}
            stream.write(json.dumps(index,ensure_ascii=False)+'\n')
            if diff:changes.append({'id':row['id'],'category':cat['name'],'prompt_sha256':hashlib.sha256(row.get('prompt','').encode()).hexdigest(),'diff':diff,'prompt':row.get('prompt','')})
            if row['id'] in cases:
                j=cases[row['id']];collection=s['subcategories'] if 'parent' in j['flag']['kind'] else s['refinements']
                checks.append({'n':j['n'],'id':row['id'],'target':j['flag']['target'],'passed':(j['flag']['target'] in collection)==j['expected_present']})
            if total%25000==0:print(total,round(time.time()-start,1),flush=True)
save(out/'changes.json',changes)
save(out/'focused.json',{'checks':checks,'failures':[x for x in checks if not x['passed']]})
delta={k:{n:candidate_counts[k][n]-baseline_counts[k][n] for n in sorted(baseline_counts[k].keys()|candidate_counts[k].keys()) if candidate_counts[k][n]!=baseline_counts[k][n]} for k in baseline_counts}
save(out/'summary.json',{'total':total,'changed_records':len(changes),'delta':delta,'elapsed':time.time()-start,'baseline_counts':baseline_counts,'candidate_counts':candidate_counts,'source_sha256':sha(STAGE/'semantic_refinements.py'),'data_sha256':sha(HERE/'stage/data.json'),'index_sha256':sha(out/'index.jsonl')})
print(json.dumps({'total':total,'changed':len(changes),'delta':delta,'focused_failures':[x for x in checks if not x['passed']]},ensure_ascii=False),flush=True)
