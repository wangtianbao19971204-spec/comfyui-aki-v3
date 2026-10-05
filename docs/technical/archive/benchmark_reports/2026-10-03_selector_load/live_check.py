import gzip
import json
import time
import urllib.request
from pathlib import Path
from verify import RUN, NODES, sha


def get(route):
    started = time.perf_counter()
    request = urllib.request.Request('http://127.0.0.1:8188' + route, headers={'Accept-Encoding': 'gzip'})
    with urllib.request.urlopen(request, timeout=90) as response:
        ttfb = (time.perf_counter() - started) * 1000
        body = response.read()
        total = (time.perf_counter() - started) * 1000
        raw = gzip.decompress(body) if response.headers.get('Content-Encoding') == 'gzip' else body
    return json.loads(raw), {'route': route, 'ttfb_ms': round(ttfb, 1), 'total_ms': round(total, 1),
                            'wire_bytes': len(body), 'decoded_bytes': len(raw)}


metrics = []
cache_stats = {p.name: {'sha256': sha(p), 'mtime_ns': p.stat().st_mtime_ns}
               for p in (NODES.parent / 'data/shared_prompt_cache').glob('*.json.gz')}
for kind in ['clothing', 'pose', 'background', 'character', 'style_quality', 'artist']:
    payload, metric = get('/anima-tools/shared-prompts?kind=' + kind)
    with gzip.open(RUN / 'generated_cache' / (kind + '.json.gz'), 'rt', encoding='utf-8') as stream:
        expected = json.load(stream)['payload']
    assert payload == expected, kind
    metric.update(kind=kind, count=payload['count'], exact_staged_parity=True)
    metrics.append(metric)
    print(json.dumps(metric), flush=True)
for route in ['/anima-tools/shared-prompts?kind=clothing', '/prompt_selector/library/index', '/anima-tools/favorites']:
    payload, metric = get(route)
    metrics.append(metric)
    print(json.dumps(metric), flush=True)
assert cache_stats == {p.name: {'sha256': sha(p), 'mtime_ns': p.stat().st_mtime_ns}
                       for p in (NODES.parent / 'data/shared_prompt_cache').glob('*.json.gz')}, 'Cache unexpectedly rebuilt'
baseline = json.loads((RUN / 'BASELINE.json').read_text('utf-8'))
changed = {p: {'before': digest, 'after': sha(p)} for p, digest in baseline['files'].items() if sha(p) != digest}
status, _ = get('/unified-workbench/status')
queue, _ = get('/queue')
report = {'metrics': metrics, 'cache_files_unchanged_during_requests': True,
          'guard_changes': changed, 'queue': queue, 'status': status}
(RUN / 'live_check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
print(json.dumps({'changed_files': list(changed), 'queue': queue}), flush=True)
