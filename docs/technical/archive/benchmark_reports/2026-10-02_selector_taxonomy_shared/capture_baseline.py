import hashlib
import json
from pathlib import Path

ROOT = Path(r'G:\ComfyUI-aki-v3')
OUT = Path(__file__).resolve().parent
PREVIOUS = ROOT / 'benchmark_reports/2026-10-02_character_selector_audit/source_snapshot_final'
PLUGIN = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'

def sha(body):
    return hashlib.sha256(body).hexdigest()

manifest = json.loads((PREVIOUS / 'manifest.json').read_text(encoding='utf-8'))
rows = []
for row in manifest['sources']:
    body = (PREVIOUS / row['snapshot_path']).read_bytes()
    assert sha(body) == row['sha256']
    target = OUT / 'before' / row['relative_path']
    if target.exists():
        assert target.read_bytes() == body
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    rows.append({'relative_path': row['relative_path'], 'sha256': sha(body),
                 'route': row['route'], 'before': str(target)})
receipt = {'previous_snapshot': str(PREVIOUS), 'source_count': len(rows), 'sources': rows,
           'bound_previous_guard': manifest['bound_final_guard'], 'production_writes': 0}
(OUT / 'baseline.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'source_count': len(rows), 'output': str(OUT / 'baseline.json')}))
