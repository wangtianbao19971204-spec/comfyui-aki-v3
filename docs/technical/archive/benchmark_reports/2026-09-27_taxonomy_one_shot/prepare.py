from pathlib import Path
import sys, json, hashlib, shutil, importlib.util
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'benchmark_reports/2026-09-25_full_coverage'
AUDIT = ROOT/'benchmark_reports/2026-09-27_taxonomy_progress_audit'
PROD = ROOT/'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector'
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()
def save(name,d):
    (HERE/name).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
assert sha(PROD/'prompt_selector/semantic_refinements.py')=='244b641f6058f51008fac8efb90f39c2bbdc7c0dcb9f7246fb53f01401eb20ab'
assert sha(PROD/'user_data/prompt_selector/data.json')=='7c3ef7dd6de55c1d3ff84d6ddc23abbad1b6e2d4dfcd90efc6c84229c6da1871'
stage=HERE/'stage/prompt_selector';stage.mkdir(parents=True,exist_ok=True)
for f in (PROD/'prompt_selector').glob('*.py'):shutil.copy2(f,stage/f.name)
backup=HERE/'backup';backup.mkdir(exist_ok=True)
paths=[PROD/'prompt_selector/semantic_refinements.py',PROD/'user_data/prompt_selector/data.json',PROD/'user_data/prompt_selector/semantic_projection.json',OLD/'release_gate.py']
for p in paths:shutil.copy2(p,backup/p.name)
save('baseline.json',{'created_at':datetime.now().astimezone().isoformat(),'files':{str(p.relative_to(ROOT)):sha(p) for p in paths},'source_sha256':{p.name:sha(p) for p in stage.glob('*.py')},'batch':91,'version':'2026-09-25.25'})
data=json.loads((PROD/'user_data/prompt_selector/data.json').read_bytes())
records={p['id']:(c,p) for c in data['categories'] for p in c.get('prompts',[])}
residual=json.loads((AUDIT/'residual_flags.json').read_text(encoding='utf-8'))
cases=[]
for i,row in enumerate(residual,1):
    c,p=records[row['id']]
    assert hashlib.sha256(p['prompt'].encode()).hexdigest()==row['prompt_sha256']
    cases.append(dict(row,n=i,prompt=p['prompt'],classification=p.get('_classification'),stored_row=p))
for rid in ['krea2-d6a4fe28b5c6c50d311010f8','krea2-6701f4a68c0ca79f49ef4f00','krea2-7bc8bfd6059ed48bb411d5c7']:
    c,p=records[rid]
    cases.append({'n':len(cases)+1,'id':rid,'category_id':c['id'],'category':c['name'],'prompt':p['prompt'],'prompt_sha256':hashlib.sha256(p['prompt'].encode()).hexdigest(),'classification':p.get('_classification'),'historical_review':True})
save('review_cases.json',cases)
for name,items in [('parents',[x for x in cases if x.get('flags',[{}])[0].get('kind')=='false_positive_parent']),('leather',[x for x in cases if x.get('flags',[{}])[0].get('cue')=='fabric_leather_furniture_guard']),('other',[x for x in cases if x.get('historical_review') or (x.get('flags',[{}])[0].get('cue')!='fabric_leather_furniture_guard' and x.get('flags',[{}])[0].get('kind')!='false_positive_parent')])]:
    (HERE/f'review_{name}.txt').write_text('\n\n'.join(f"#{x['n']} {x['id']}\n{json.dumps(x.get('flags',[]),ensure_ascii=False)}\nPARENTS: {json.dumps(x.get('parents',x.get('classification')),ensure_ascii=False)}\nLEAVES: {json.dumps(x.get('leaves'),ensure_ascii=False)}\n{x['prompt']}" for x in items),encoding='utf-8')
save('EXECUTION_STATE.json',{'status':'review_and_staging','production_mutated':False,'acceptance_protocol':'single consolidated release and total acceptance; three new clean rounds explicitly removed by user on 2026-09-27','scope':'76 residual flags; strict historical replay amendments; relevant engine mechanisms; data corrections; progress reconciliation','next_action':'Review all cases and freeze exact judgments before candidate measurement.'})
print(json.dumps({'cases':len(cases),'stage':str(stage),'backup':str(backup)},ensure_ascii=False))
