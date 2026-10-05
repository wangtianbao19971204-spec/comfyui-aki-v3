"""Restart only the verified idle production ComfyUI listener to load Python changes."""
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
import json
import socket
import subprocess
import time
import psutil

report = Path(__file__).resolve().parent
root = report.parents[1]
comfy = root / 'ComfyUI'
python = root / 'python/python.exe'
receipt_path = report / 'restart_receipt.json'
if receipt_path.exists():
    raise SystemExit('Restart receipt already exists; refusing a second restart.')

def listeners():
    return sorted({item.pid for item in psutil.net_connections('tcp')
                   if item.status == 'LISTEN' and item.laddr.port == 8188})

def fetch(path):
    with urlopen('http://127.0.0.1:8188' + path, timeout=8) as response:
        return json.load(response)

owners = listeners()
if len(owners) != 1:
    raise RuntimeError(f'Expected one 8188 listener, got {owners}')
old = psutil.Process(owners[0])
args, cwd, executable = old.cmdline(), Path(old.cwd()), Path(old.exe())
if executable.resolve() != python.resolve() or cwd.resolve() != comfy.resolve() or args[1] != str(comfy / 'main.py'):
    raise RuntimeError('8188 listener is not the expected ComfyUI process')
queue = fetch('/queue')
if queue['queue_running'] or queue['queue_pending']:
    raise RuntimeError('ComfyUI queue is not empty; restart refused')
receipt = {'started_at': datetime.now().astimezone().isoformat(), 'previous_pid': old.pid,
           'executable': str(executable), 'cwd': str(cwd), 'args': args,
           'queue_before': {'running': 0, 'pending': 0}}
receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')

old.terminate()
old.wait(timeout=20)
with socket.socket() as connection:
    connection.settimeout(2)
    if connection.connect_ex(('127.0.0.1', 8188)) == 0:
        raise RuntimeError('Port 8188 remained open; duplicate launch refused')
with (report / 'restart_stdout.log').open('wb') as stdout, (report / 'restart_stderr.log').open('wb') as stderr:
    child = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP |
                             subprocess.CREATE_NO_WINDOW)
receipt['new_pid'] = child.pid
receipt['relaunched_at'] = datetime.now().astimezone().isoformat()
receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'old_pid': old.pid, 'new_pid': child.pid, 'queue_before': [0, 0]}), flush=True)

for _ in range(90):
    if child.poll() is not None:
        raise RuntimeError(f'Restarted ComfyUI exited with code {child.returncode}')
    try:
        status = fetch('/unified-workbench/status')
        if listeners() == [child.pid] and all(item.get('ready') for item in status['modules']):
            receipt['verified_at'] = datetime.now().astimezone().isoformat()
            receipt['status'] = 'ready'
            receipt['nodes'] = status.get('nodes')
            receipt['modules_ready'] = len(status['modules'])
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'ready': True, 'pid': child.pid, 'nodes': receipt['nodes'],
                              'modules_ready': receipt['modules_ready']}), flush=True)
            break
    except Exception:
        pass
    time.sleep(2)
else:
    raise RuntimeError('ComfyUI restart did not become ready within 180 seconds')
