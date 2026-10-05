import ast
import asyncio
import gzip
import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
from pathlib import Path

RUN = Path(__file__).resolve().parent
PROD = Path('G:/ComfyUI-aki-v3/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench')
DATA = PROD / 'modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data/prompt_selector/data.json'
NODES = PROD / 'modules/comfyui-anima-tools/nodes.py'
TAXONOMY = NODES.parent / 'data/weilin_category_taxonomy.json'


class Routes:
    def get(self, *args):
        return lambda f: f

    post = get


class Server:
    instance = type('Instance', (), {'routes': Routes()})()


def load(path, cache_dir):
    tree = ast.parse(path.read_text('utf-8'))
    assignments = {t.id: n.lineno for n in tree.body if isinstance(n, ast.Assign)
                   for t in n.targets if isinstance(t, ast.Name)}
    start, end = assignments['_SHARED_PROMPT_KINDS'], assignments['ANIMADEX_CHARACTER_SEARCH_API']
    ns = dict(os=os, re=re, json=json, hashlib=hashlib, threading=threading,
              urllib=urllib, gzip=gzip, asyncio=asyncio, PromptServer=Server, __file__=str(path))
    exec(compile(ast.Module(body=[n for n in tree.body if start <= n.lineno < end], type_ignores=[]), str(path), 'exec'), ns)
    ns['_find_weilin_prompt_selector_data'] = lambda: str(DATA)
    ns['_SHARED_PROMPT_TAXONOMY_PATH'] = str(TAXONOMY)
    ns['_SHARED_PROMPT_CACHE_DIR'] = str(cache_dir)
    return ns


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    baseline = json.loads((RUN.parent / '2026-10-03_selector_topics/BASELINE.json').read_text('utf-8'))
    paths = set(baseline['files']) | {str(NODES), str(DATA.with_name('semantic_projection.json'))}
    helper_dir = PROD / 'modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector'
    paths.update(str(helper_dir / name) for name in ['semantic_projection.py', 'semantic_taxonomy.py'])
    guard = {p:sha(p) for p in sorted(paths)}
    assert sha(NODES) == sha(RUN / 'before/nodes.py')
    (RUN / 'BASELINE.json').write_text(json.dumps({'files':guard, 'changed_source':str(NODES)}, ensure_ascii=False, indent=2), 'utf-8')
    (RUN / 'run.lock').write_text(json.dumps({'thread_id':'01a1008c-e0bd-7a60-a649-9745f690f6b1', 'scope':'selector_catalog_initial_load_performance_only'}, indent=2), 'utf-8')
    source_bytes = DATA.read_bytes()
    data = json.loads(source_bytes)
    digest = hashlib.sha256(source_bytes).hexdigest()
    old = load(RUN / 'before/nodes.py', RUN / 'unused')
    t = time.perf_counter()
    expected = old['_build_shared_prompt_payloads'](str(DATA), DATA.stat().st_mtime_ns, kinds=None, source_data=data, source_sha256=digest)
    before_build_ms = (time.perf_counter()-t)*1000
    candidate = load(RUN / 'candidate/nodes.py', RUN / 'generated_cache')
    t = time.perf_counter()
    candidate['get_shared_prompt_payload']('clothing')
    build_ms = (time.perf_counter()-t)*1000
    cases = []
    for kind, payload in expected.items():
        payload.update(category_filter='', summary_only=False)
        actual = candidate['get_shared_prompt_payload'](kind)
        assert {k:v for k,v in actual.items() if k != 'revision'} == payload, kind
        cold = load(RUN / 'candidate/nodes.py', RUN / 'generated_cache')
        def forbidden(*args, **kwargs):
            raise AssertionError('Cache hit unexpectedly rebuilt the catalog')
        cold['_build_shared_prompt_payloads'] = forbidden
        t = time.perf_counter()
        cached = cold['get_shared_prompt_payload'](kind)
        cold_ms = (time.perf_counter()-t)*1000
        assert cached == actual
        assert cold['_SHARED_PROMPT_DATA_CACHE']['source_data'] is None
        t = time.perf_counter()
        assert cold['get_shared_prompt_payload'](kind) is cached
        warm_ms = (time.perf_counter()-t)*1000
        cases.append({'kind':kind, 'count':actual['count'], 'exact_parity_except_revision':True, 'cold_cache_ms':round(cold_ms,1), 'warm_ms':round(warm_ms,1)})
        print(json.dumps(cases[-1]), flush=True)

    # Exercise invalidation without changing any real library files.
    fixture = RUN / 'fixture'
    fixture.mkdir(exist_ok=True)
    sample = fixture / 'data.json'
    projection = fixture / 'semantic_projection.json'
    sample.write_text('{"sample":1}', 'utf-8')
    projection.write_text('{"version":1}', 'utf-8')
    contract = load(RUN / 'candidate/nodes.py', fixture / 'cache')
    contract['_find_weilin_prompt_selector_data'] = lambda: str(sample)
    version = ['code-v1']
    contract['_shared_prompt_runtime_hash'] = lambda _: version[0]
    builds = []
    def build(*args, **kwargs):
        builds.append(kwargs)
        return {'pose':{'success':True,'enabled':True,'kind':'pose','items':[], 'count':0}}
    contract['_build_shared_prompt_payloads'] = build
    contract['get_shared_prompt_payload']('pose')
    contract['_SHARED_PROMPT_DATA_CACHE']['payloads'].clear()
    contract['get_shared_prompt_payload']('pose')
    assert len(builds) == 1
    sample.write_text('{"sample":22}', 'utf-8')
    contract['get_shared_prompt_payload']('pose')
    assert len(builds) == 2
    projection.write_text('{"version":2}', 'utf-8')
    contract['get_shared_prompt_payload']('pose')
    assert len(builds) == 3
    version[0] = 'code-v2'
    contract['get_shared_prompt_payload']('pose')
    assert len(builds) == 4
    contract['get_shared_prompt_payload']('pose', force_refresh=True)
    assert len(builds) == 5
    contract['_SHARED_PROMPT_DATA_CACHE']['payloads'].clear()
    (fixture / 'cache/pose.json.gz').write_bytes(b'broken gzip')
    contract['get_shared_prompt_payload']('pose')
    assert len(builds) == 6
    contract['get_shared_prompt_payload']('pose', summary_only=True)
    contract['get_shared_prompt_payload']('pose', category_filter='shared-theme:pose_action')
    assert len(builds) == 8 and builds[-2]['summary_only'] and builds[-1]['category_filter']
    assert all(sha(p) == h for p,h in guard.items())
    report = {'passed':True, 'source_sha256':sha(RUN/'candidate/nodes.py'), 'guarded_files':len(guard),
              'old_projection_build_ms':round(before_build_ms,1), 'initial_build_and_cache_write_ms':round(build_ms,1),
              'cases':cases, 'invalidation':['source','projection','runtime code','force refresh','corrupt gzip'],
              'uncached_paths':['filtered','summary'], 'production_writes':0}
    (RUN / 'candidate_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'cases'}),flush=True)


if __name__ == '__main__':
    main()
