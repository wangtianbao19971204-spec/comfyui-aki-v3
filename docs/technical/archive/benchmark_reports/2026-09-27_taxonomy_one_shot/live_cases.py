from common import *
import urllib.request, urllib.parse

def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8188'+path,timeout=240) as response:return json.loads(response.read())
cases={x['id']:x for x in read(HERE/'review_cases.json')}
results=[]
for j in read(HERE/'review_decisions.json'):
    c=cases[j['id']];q=c['prompt'][:100]
    page=get('/prompt_selector/library/prompts?'+urllib.parse.urlencode({'category_id':c['category_id'],'q':q,'limit':200,'offset':0}))
    matches=[row for row in page.get('items',[]) if row['id']==c['id']]
    if not matches:
        matches=[get('/prompt_selector/library/prompt?'+urllib.parse.urlencode({'prompt_id':c['id'],'category_id':c['category_id'],'include_semantic':1}))['prompt']]
    row=matches[0];s=row['_semantic'];values=s['subcategories'] if 'parent' in j['flag']['kind'] else s['refinements']
    results.append({'id':c['id'],'n':j['n'],'target':j['flag']['target'],'expected':j['expected_present'],'passed':(j['flag']['target'] in values)==j['expected_present']})
    if len(results)%10==0:print('LIVE_CASES',len(results),flush=True)
historical=read(HERE/'historical116_material_amendment.json')
row=get('/prompt_selector/library/prompt?'+urllib.parse.urlencode({'prompt_id':historical['id'],'include_semantic':1}))['prompt']
assert hashlib.sha256(row['prompt'].encode()).hexdigest()==historical['prompt_sha256']
results.append({'id':historical['id'],'round':116,'target':'fabric.leather','expected':False,'passed':'fabric.leather' not in row['_semantic']['refinements']})
save(HERE/'live_cases.json',{'created_at':now(),'checks':results,'passed':all(x['passed'] for x in results),'data_sha256':sha(DATA),'engine_sha256':sha(SOURCES/'semantic_refinements.py')})
print(json.dumps({'checks':len(results),'failures':[x for x in results if not x['passed']]},ensure_ascii=False))
sys.exit(0 if all(x['passed'] for x in results) else 1)
