import hashlib
import json
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(r'G:\ComfyUI-aki-v3')
OUT = Path(__file__).resolve().parent
PLAN = OUT.parent.parent
THREAD = '01a101d1-7e14-79c2-ad99-ed8e4b40ccb9'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read(path):
    return json.loads(path.read_text('utf8'))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')


def get(route):
    with urllib.request.urlopen('http://127.0.0.1:8188' + route, timeout=30) as response:
        return response.read()


def live():
    owners = []
    for c in psutil.net_connections('tcp'):
        if c.status == 'LISTEN' and c.laddr.port == 8188:
            p = psutil.Process(c.pid)
            owners.append(dict(pid=p.pid, created=p.create_time(), exe=p.exe(), cwd=p.cwd(), cmdline=p.cmdline()))
    assert len(owners) == 1 and Path(owners[0]['cwd']) == ROOT / 'ComfyUI'
    assert Path(owners[0]['exe']) == ROOT / 'python/python.exe'
    queue = json.loads(get('/queue'))
    modules = json.loads(get('/unified-workbench/status'))
    assert all(m['ready'] for m in modules['modules'])
    served = []
    prior = read(PLAN / 'runs/20261004_0805_m5_latency/final_guard.json')
    for entry in prior['served']:
        disk = sha(Path(entry['path']))
        remote = hashlib.sha256(get(entry['route'])).hexdigest()
        assert disk == remote
        served.append(dict(path=entry['path'], route=entry['route'], disk=disk, served=remote))
    return dict(at=datetime.now().astimezone().isoformat(), owners=owners, queue=queue, modules=modules, served=served)


if __name__ == '__main__':
    action = sys.argv[1]
    current = live()
    state = read(PLAN / 'STATE.json')
    base = read(PLAN / 'CURRENT_BASELINE.json')
    files = {p: sha(Path(p)) for p in base['files']}
    assert files == base['files']
    if action == 'start':
        assert not list((ROOT / 'benchmark_reports').rglob('run.lock'))
        assert state['active_run'] is None and state['current_phase'] == 'M6'
        targets = [str(ROOT / 'production_tools' / p) for p in ['plugin_disposition.json', '插件处置表.md']]
        lock = dict(owner_thread=THREAD, scope='M6 plugin dependency audit and stale maintenance inventory correction', target_files=targets, started_at=current['at'], active_run=str(OUT))
        with (PLAN / 'run.lock').open('x', encoding='utf8') as f:
            json.dump(lock, f, ensure_ascii=False, indent=2)
        (OUT / 'before').mkdir()
        for name in ['PLAN.json', 'STATE.json', 'CONTINUATION.txt', 'ACCEPTED_BASELINE.json', 'CURRENT_BASELINE.json']:
            shutil.copy2(PLAN / name, OUT / 'before' / name)
        for p in targets:
            files[p] = sha(Path(p))
            shutil.copy2(p, OUT / 'before' / Path(p).name)
        write(OUT / 'baseline.json', dict(files=files, live=current, concurrency='Current owner active; library and previous optimization threads notLoaded; no run.lock found.'))
        state.update(status='in_progress', active_run=str(OUT), next_action='Audit M6 actual registrations, nested workflow dependencies and current production startup; correct only proven stale maintenance records.')
        write(PLAN / 'STATE.json', state)
    else:
        baseline = read(OUT / 'baseline.json')
        assert current['owners'] == baseline['live']['owners']
        expected = dict(baseline['files'])
        if (OUT / 'release.json').exists():
            expected.update(read(OUT / 'release.json')['after'])
        assert {p: sha(Path(p)) for p in expected} == expected
        write(OUT / 'final_guard.json', dict(at=current['at'], guard_count=len(expected), drift=[], live=current, production_runtime_changes=[], documentation_changes=read(OUT / 'release.json')['after'] if (OUT / 'release.json').exists() else {}))
    print(json.dumps(dict(action=action, guard_count=len(files), pid=current['owners'][0]['pid'], queue=current['queue'], served=len(current['served'])), ensure_ascii=False))
