"""Single read-only 8188 listener/RSS + queue sample. No source or formal data scans."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
import psutil

run = Path(__file__).resolve().parent
cycle = int(sys.argv[1])
if cycle not in (0, 5, 10):
    raise SystemExit('Use lifecycle_service_sample.py 0|5|10')
destination = run / f'lifecycle_service_{cycle:02d}.json'
if destination.exists():
    raise SystemExit(f'Preserving existing sample: {destination}')
start = datetime.now(timezone.utc).isoformat()
pids = sorted({connection.pid for connection in psutil.net_connections(kind='tcp')
               if connection.laddr and connection.laddr.port == 8188 and connection.status == 'LISTEN'})
if len(pids) != 1 or pids[0] is None:
    raise SystemExit(f'Expected one identified 8188 listener, found {pids}')
process = psutil.Process(pids[0])
baseline = json.loads((run / 'before_guard.json').read_text(encoding='utf-8-sig'))
expected = [(p['pid'], p['create_time']) for p in baseline['listeners']]
identity = (process.pid, process.create_time())
if [identity] != expected:
    raise SystemExit('8188 listener identity differs from this run baseline')
rss_sample_at = datetime.now(timezone.utc).isoformat()
memory = process.memory_info()
with urlopen('http://127.0.0.1:8188/queue', timeout=10) as response:
    queue = json.load(response)
result = {
    'cycle': cycle, 'started_at': start, 'rss_sampled_at': rss_sample_at,
    'completed_at': datetime.now(timezone.utc).isoformat(),
    'pid': process.pid, 'create_time': process.create_time(), 'exe': process.exe(),
    'rss_bytes': memory.rss, 'vms_bytes': memory.vms,
    'queue_running': len(queue['queue_running']), 'queue_pending': len(queue['queue_pending']),
    'listener_identity_matches_run_baseline': True,
    'scope': 'ComfyUI 8188 service process; not browser renderer or GPU memory',
    'timing_boundary': 'Companion sample immediately after browser checkpoint; correlate timestamps, not simultaneous atomic measurement'
}
destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
