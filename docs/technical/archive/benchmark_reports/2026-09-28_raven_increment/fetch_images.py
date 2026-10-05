"""Copy or download only planned source previews; inspect file integrity, not content."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.parse import urlparse
import hashlib,json,shutil,threading,urllib.request
from PIL import Image
HERE=Path(__file__).resolve().parent
OUT=HERE/'stage/images';OUT.mkdir(exist_ok=True)
rows=json.loads((HERE/'image_plan.json').read_text(encoding='utf-8'))
allowed={'assets.quicktagcloud.com','prompt-vault-gallery.pages.dev'}
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def get(row):
    target=OUT/row['filename'];assert target.resolve().is_relative_to(OUT.resolve())
    try:
        how='staged_cache'
        if not target.exists():
            if row.get('reuse_cache'):
                shutil.copy2(row['reuse_cache'],target);how='verified_source_cache'
            else:
                assert urlparse(row['url']).hostname in allowed
                error=None
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(urllib.request.Request(row['url'],headers={'User-Agent':'Mozilla/5.0'}),timeout=35) as response:
                            assert urlparse(response.url).hostname in allowed
                            raw=response.read(32*1024*1024+1)
                        assert 0<len(raw)<=32*1024*1024
                        target.write_bytes(raw);error=None;break
                    except Exception as exc:error=exc
                if error:raise error
                how='downloaded'
        with Image.open(target) as im:
            size=im.size;fmt=im.format;im.verify()
        return {**row,'status':'ok','method':how,'bytes':target.stat().st_size,'sha256':digest(target),'size':size,'format':fmt}
    except Exception as exc:return {**row,'status':'failed','error':repr(exc)}
results=[]
with ThreadPoolExecutor(max_workers=16) as pool:
    futures=[pool.submit(get,row) for row in rows]
    for future in as_completed(futures):
        results.append(future.result())
        if len(results)%200==0:print('IMAGES',len(results),'/',len(rows),'failed',sum(x['status']!='ok' for x in results),flush=True)
        if len(results)%1000==0:(HERE/'image_receipts_partial.json').write_text(json.dumps(results,ensure_ascii=False),encoding='utf-8')
(HERE/'image_receipts.json').write_text(json.dumps(results,ensure_ascii=False,indent=1),encoding='utf-8')
failures=[x for x in results if x['status']!='ok']
print('COMPLETE',len(results),'FAILED',len(failures),'BYTES',sum(x.get('bytes',0) for x in results),flush=True)
if failures:print(json.dumps(failures[:8],ensure_ascii=False));raise SystemExit(1)
