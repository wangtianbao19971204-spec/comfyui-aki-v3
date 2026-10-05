from common import *
import shutil, requests

backup=HERE/'backup'; backup.mkdir(exist_ok=True)
baseline=read(HERE/'baseline_runtime.json')
for name,path in {'data.json':DATA,'semantic_projection.json':PROJECTION,'shared_pairs.json':DATA.with_name('shared_pairs.json')}.items():
    assert sha(path)==baseline['hashes'][name]
    if not (backup/name).exists():shutil.copy2(path,backup/name)
    assert sha(path)==sha(backup/name)
for endpoint,name in [('/prompt_selector/library/index','baseline_index.json'),('/prompt_selector/library/prompts?limit=1&include_filter_counts=1','baseline_query.json')]:
    save(HERE/name,requests.get('http://127.0.0.1:8188'+endpoint,timeout=240).json())
save(HERE/'snapshot_receipt.json',{'passed':True,'created_at':now(),'hashes':baseline['hashes'],'indexed_records':read(HERE/'baseline_query.json')['total']})
print('SNAPSHOT_PASSED',flush=True)
