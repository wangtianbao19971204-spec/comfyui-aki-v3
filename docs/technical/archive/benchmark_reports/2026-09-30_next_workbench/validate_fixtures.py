"""Validate only the generated candidate database and refresh its manifest hash."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import hashlib
import json
import sqlite3

report = Path(__file__).resolve().parent
candidate = report / 'candidate_data'
db = candidate / 'tags.db'
module_path = (report.parent.parent / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/'
               'modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector/tag_library.py')
spec = spec_from_file_location('candidate_tag_library', module_path)
module = module_from_spec(spec)
spec.loader.exec_module(module)
library = module.TagLibrary(db)

first = library.page(query='QA193', limit=80)
second = library.page(query='QA193', offset=80, limit=80)
third = library.page(query='QA193', offset=160, limit=80)
ids = [row['resource_id'] for part in (first, second, third) for row in part['items']]
assert [len(first['items']), len(first['items']) + len(second['items']), len(ids)] == [80, 160, 193]
assert first['total'] == second['total'] == third['total'] == 193
assert len(set(ids)) == 193
with sqlite3.connect(db) as conn:
    assert conn.execute("SELECT count(*) FROM tag_tags WHERE text LIKE 'QA193%'").fetchone()[0] == 193

manifest_path = candidate / 'manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
for entry in manifest['files']:
    path = candidate / entry['file']
    entry.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print({'passed': True, 'native_pages': [80, 160, 193], 'candidate_only': str(db)})
