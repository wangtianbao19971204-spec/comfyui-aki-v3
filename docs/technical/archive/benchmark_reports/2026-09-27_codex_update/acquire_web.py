"""Archive the publisher's current release, without touching the live library."""
from pathlib import Path
import hashlib, json, re, sys, urllib.request
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
OUT = HERE / 'sources/web'
OUT.mkdir(parents=True, exist_ok=True)
receipts = []
opener = urllib.request.build_opener()
if '--proxy' in sys.argv:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': 'http://127.0.0.1:10081'}))

def get(url, name):
    assert urlparse(url).hostname in {'novelai.quicktagcloud.com', 'assets.quicktagcloud.com'}
    target = OUT / name
    assert target.resolve().is_relative_to(OUT.resolve())
    with opener.open(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=90) as response:
        body = response.read()
    value = json.loads(body)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    receipts.append({'url':url, 'file':name, 'bytes':len(body), 'sha256':hashlib.sha256(body).hexdigest()})
    (OUT/'fetch_receipts.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,len(body),flush=True)
    return value

config = get('https://novelai.quicktagcloud.com/data-source.json', 'data-source.json')
base = config['baseUrl'].rstrip('/')
pointer = get(base+'/'+config.get('pointer','current.json'), 'current.json')
release = pointer['release']
assert re.fullmatch(r'r-[0-9a-f]{20}',release)
release_base = base+'/releases/'+release
manifest = pointer.get('manifest')
if manifest:
    get(manifest if manifest.startswith('https:') else base+'/'+manifest.lstrip('/'),'manifest.json')
catalog = get(release_base+'/codexes.json','codexes.json')
print('CATALOG',json.dumps(catalog,ensure_ascii=False),flush=True)
