import argparse
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

LAB = Path(__file__).resolve().parent
PYTHON = LAB.parent / 'python/python.exe'
STATE = LAB / 'server.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status', 'unload'], nargs='?', default='start')
    args = parser.parse_args()
    if args.action in ['status', 'stop', 'unload']:
        if not STATE.exists():
            print('Lab has not been started.')
            return
        saved = json.loads(STATE.read_text(encoding='utf-8'))
        if not psutil.pid_exists(saved['pid']):
            print('Lab is stopped.')
            return
        process = psutil.Process(saved['pid'])
        if process.create_time() != saved['create_time'] or str(LAB / 'boot.py') not in process.cmdline():
            raise RuntimeError('Saved process identity changed.')
        if args.action == 'status':
            print(json.dumps(saved, ensure_ascii=False, indent=2))
            return
        with urllib.request.urlopen('http://127.0.0.1:8189/queue', timeout=10) as response:
            queue = json.load(response)
        if queue['queue_running'] or queue['queue_pending']:
            raise RuntimeError('Lab queue is busy; no process was stopped.')
        if args.action == 'unload':
            request = urllib.request.Request('http://127.0.0.1:8189/free',
                data=json.dumps({'unload_models': True, 'free_memory': True}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=15) as response:
                print('Lab model unload requested:', response.status)
            return
        process.terminate()
        process.wait(timeout=30)
        print('Lab stopped.')
        return
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 8189)) == 0:
            print('Port 8189 is already listening; existing service was preserved.')
            return
    logs = LAB / 'logs'
    logs.mkdir(exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    with (logs / f'{stamp}.stdout.log').open('w', encoding='utf-8') as out, (logs / f'{stamp}.stderr.log').open('w', encoding='utf-8') as err:
        process = subprocess.Popen([str(PYTHON), '-X', 'utf8', '-B', '-s', str(LAB / 'boot.py')],
            cwd=LAB, env=env, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
    saved = {'pid': process.pid, 'create_time': psutil.Process(process.pid).create_time(),
             'url': 'http://127.0.0.1:8189', 'log_prefix': str(logs / stamp)}
    STATE.write_text(json.dumps(saved, indent=2), encoding='utf-8')
    print(json.dumps(saved, indent=2))


if __name__ == '__main__':
    main()
