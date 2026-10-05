from pathlib import Path
import sys, json, hashlib, importlib, importlib.util, types
from datetime import datetime
sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=ROOT/'benchmark_reports/2026-09-25_full_coverage'
AUDIT=ROOT/'benchmark_reports/2026-09-27_taxonomy_progress_audit'
PROD=ROOT/'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector'
SOURCES=PROD/'prompt_selector'
STAGE=HERE/'stage/prompt_selector'
DATA=PROD/'user_data/prompt_selector/data.json'
PROJECTION=DATA.with_name('semantic_projection.json')
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def load_script(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def runtime(path,name):
    pkg=types.ModuleType(name);pkg.__path__=[str(path)];sys.modules[name]=pkg
    return tuple(importlib.import_module(name+'.'+n) for n in ('semantic_projection','semantic_refinements','semantic_taxonomy'))
def now():return datetime.now().astimezone().isoformat()
