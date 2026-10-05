import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

OUT = Path(__file__).resolve().parent
PREVIOUS = OUT.parent / '2026-10-02_character_selector_audit/final_live_guard.json'
ROOT = OUT.parents[1]
PLUGIN = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def get(route):
    with urlopen('http://127.0.0.1:8188' + route, timeout=45) as response:
        return json.load(response)

expected = json.loads(PREVIOUS.read_text(encoding='utf-8'))
formal = {}
for path, row in expected['formal_workflows'].items():
    actual = sha(Path(path))
    assert actual == row['sha256']
    formal[path] = actual
for rel, row in expected['formal_data'].items():
    actual = sha(PLUGIN / rel)
    assert actual == row['sha256']
    formal[str(PLUGIN / rel)] = actual
queue = get('/queue')
assert not queue['queue_running'] and not queue['queue_pending']
rows = {}
for kind in ('character', 'artist', 'clothing', 'pose', 'background', 'style_quality'):
    data = get('/anima-tools/shared-prompts?kind=' + kind + '&index=1')
    assert data['enabled'] is True
    ids = [item['id'] for item in data['items']]
    rows[kind] = {'count':len(ids), 'ordered_ids_sha256':hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
                  'taxonomy_version':data['taxonomy_version'], 'source_sha256':data['source_sha256']}
    print(json.dumps({'kind':kind, 'count':len(ids)}), flush=True)
result = {'at':datetime.now().astimezone().isoformat(), 'formal_files':formal, 'kind_indices':rows,
          'queue':{'running':0,'pending':0}, 'production_writes':0}
(OUT / 'live_before.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('LIVE_BEFORE_PASS', flush=True)
