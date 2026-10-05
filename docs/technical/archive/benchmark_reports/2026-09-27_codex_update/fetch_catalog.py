"""Fetch every published catalogue in one pinned site release."""
from pathlib import Path
import concurrent.futures, hashlib,json,urllib.request
from urllib.parse import urlparse

HERE=Path(__file__).resolve().parent
OUT=HERE/'sources/web'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
config=read(OUT/'data-source.json');current=read(OUT/'current.json');manifest=read(OUT/'manifest.json');catalog=read(OUT/'codexes.json')
base=config['baseUrl'].rstrip('/')+'/releases/'+current['release']
names=[m['id']+'.json' for m in catalog]+['media.json','updates.json']

def fetch(name):
    target=OUT/name;spec=manifest['files'][name]
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=spec['sha256']:
        with urllib.request.urlopen(urllib.request.Request(base+'/'+name,headers={'User-Agent':'Mozilla/5.0'}),timeout=120) as response:
            raw=response.read()
        assert len(raw)==spec['size'] and hashlib.sha256(raw).hexdigest()==spec['sha256'],name
        json.loads(raw)
        target.write_bytes(raw)
    value=read(target)
    result={'name':name,'sha256':spec['sha256'],'bytes':spec['size'],'manifest_verified':True,'url':base+'/'+name}
    if isinstance(value,dict):result['entries']=len(value.get('entries',[]))
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results=list(pool.map(fetch,names))
for meta in catalog:
    if not meta.get('dataUrl'):continue
    url=meta['dataUrl'];assert urlparse(url).hostname=='prompt-vault-gallery.pages.dev'
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=120) as response:raw=response.read()
        value=json.loads(raw);name=meta['id']+'.external.json';(OUT/name).write_bytes(raw)
        results.append({'name':name,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'external_current':True})
        print('EXTERNAL',name,len(raw),flush=True)
    except Exception as e:
        results.append({'name':meta['id'],'url':url,'external_error':str(e),'fallback':meta['id']+'.json'})
        print('EXTERNAL_ERROR',str(e),flush=True)
(OUT/'catalog_receipts.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
