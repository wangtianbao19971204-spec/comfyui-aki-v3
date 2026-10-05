import concurrent.futures
import hashlib
import html
import json
import pathlib
import re
import urllib.request
import urllib.parse

OUT = pathlib.Path(__file__).parent / 'references'
OUT.mkdir(exist_ok=True)
URLS = {
 'civitai_anima': 'https://civitai.com/api/v1/models?' + urllib.parse.urlencode({'query':'Anima','types':'Workflows','limit':12,'sort':'Most Downloaded','nsfw':'false'}),
 'civitai_krea2': 'https://civitai.com/api/v1/models?' + urllib.parse.urlencode({'query':'Krea','types':'Workflows','limit':8,'sort':'Most Downloaded','nsfw':'false'}),
 'anima_official': 'https://huggingface.co/circlestone-labs/Anima/raw/main/README.md',
 'krea_official': 'https://docs.krea.ai/developers/comfyui/krea2',
}
def fetch(item):
 name,url=item
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
  with urllib.request.urlopen(req,timeout=25) as r: raw=r.read();status=r.status
  (OUT/(name+'.txt')).write_bytes(raw)
  result={'name':name,'url':url,'status':status,'sha256':hashlib.sha256(raw).hexdigest()}
  if name.startswith('civitai'):
   doc=json.loads(raw)
   result['items']=[]
   for x in doc.get('items',[]):
    v=x.get('modelVersions',[{}])[0]
    result['items'].append({'id':x['id'],'name':x['name'],'creator':x.get('creator',{}).get('username'),'stats':x.get('stats'),'description':html.unescape(re.sub('<[^>]+>',' ',x.get('description') or '')),'version':{k:v.get(k) for k in ['id','name','baseModel','publishedAt','description','files']}})
  else:
   result['size']=len(raw)
  return result
 except Exception as e: return {'name':name,'url':url,'error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex: results=list(ex.map(fetch,URLS.items()))
(OUT/'index.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
for r in results:
 print(json.dumps({k:v for k,v in r.items() if k!='items'},ensure_ascii=False))
 for x in r.get('items',[]):
  print(json.dumps({'id':x['id'],'name':x['name'],'creator':x['creator'],'stats':x['stats'],'version':{k:v for k,v in x['version'].items() if k not in ['description','files']},'description':x['description'][:1400],'files':[{'name':f['name'],'sizeKB':f['sizeKB'],'url':f['downloadUrl']} for f in x['version'].get('files',[])]},ensure_ascii=False))
