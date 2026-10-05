from pathlib import Path
import sys, json, hashlib
from datetime import datetime

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREV = HERE.with_name('2026-09-27_codex_exclusion_review')
UPDATE = HERE.with_name('2026-09-27_codex_update')
sys.path.insert(0, str(PREV))
from review import load_rows, digest
from update_common import PROD, DATA, PROJECTION, DB, T, P, R, norm, content, sources, source_key, sha

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def now():
    return datetime.now().astimezone().isoformat()
