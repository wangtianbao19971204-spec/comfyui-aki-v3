"""Start ComfyUI with an explicit plugin profile; keep the original launcher intact."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('profile',choices=['production','diagnostic','maintenance','lean','anima','krea','legacy'],nargs='?',default='production')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--port',type=int,default=8188)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--stop',action='store_true')
    parser.add_argument('--memory-mode',choices=['single-gpu','no-pin','original'],default='no-pin',help='single-gpu restricts CUDA to device 0; no-pin disables pinned memory.')
    parser.add_argument('--preview-method',choices=['none','auto','latent2rgb','taesd'])
    parser.add_argument('--reserve-vram',type=float)
    parser.add_argument('--cuda-malloc',action='store_true')
    args=parser.parse_args();root=args.root.resolve();comfy=root/'ComfyUI';python=root/'python/python.exe'
    config=json.loads((Path(__file__).parent/'profiles.json').read_text(encoding='utf8'))
    names=config[args.profile]
    for name in names:
        if not (comfy/'custom_nodes'/name).is_dir():raise FileNotFoundError(name)
    flags=['-X','utf8','-B','-s','main.py','--listen','127.0.0.1','--port',str(args.port),'--disable-auto-launch','--disable-all-custom-nodes','--whitelist-custom-nodes',*names]
    # A non-default validation port gets its own SQLite file, so a lean/diagnostic
    # smoke server can coexist with the production UI without locking its DB.
    if args.port != 8188:
        flags += ['--database-url', f"sqlite:///{(comfy / 'user' / f'comfyui_{args.port}.db').as_posix()}"]
    if args.memory_mode=='no-pin':flags+=['--disable-pinned-memory']
    if args.memory_mode=='single-gpu':flags+=['--cuda-device','0']
    if args.preview_method:flags+=['--preview-method',args.preview_method]
    if args.reserve_vram is not None:
        if args.reserve_vram<0:parser.error('--reserve-vram must be non-negative')
        flags+=['--reserve-vram',str(args.reserve_vram)]
    if args.cuda_malloc:flags+=['--cuda-malloc']
    state_dir=root/'production_tools/state';state=state_dir/f'server_{args.port}.json'
    if args.dry_run:
        print(json.dumps(dict(executable=str(python),cwd=str(comfy),args=flags),ensure_ascii=False,indent=2));return
    if args.stop:
        import psutil
        receipt=json.loads(state.read_text(encoding='utf8'));process=psutil.Process(receipt['pid'])
        if Path(process.exe()).resolve()!=python.resolve() or process.create_time()!=receipt['create_time']:raise RuntimeError('Saved process identity no longer matches; no process was stopped.')
        queue=json.load(urllib.request.urlopen(f'http://127.0.0.1:{args.port}/queue',timeout=5))
        if queue.get('queue_running') or queue.get('queue_pending'):raise RuntimeError('Queue is not empty; finish or cancel jobs before stopping.')
        process.terminate();process.wait(timeout=30);print('ComfyUI stopped.');return
    import socket
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',args.port))==0:raise RuntimeError(f'Port {args.port} already in use. Existing server was left running.')
    stamp=time.strftime('%Y%m%d_%H%M%S');logdir=root/'production_tools/logs';logdir.mkdir(parents=True,exist_ok=True);state_dir.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    with (logdir/f'{stamp}_{args.profile}.stdout.log').open('w',encoding='utf8') as stdout,(logdir/f'{stamp}_{args.profile}.stderr.log').open('w',encoding='utf8') as stderr:
        process=subprocess.Popen([str(python),*flags],cwd=comfy,env=env,stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    import psutil
    receipt=dict(pid=process.pid,create_time=psutil.Process(process.pid).create_time(),root=str(root),port=args.port,profile=args.profile,memory_mode=args.memory_mode,args=flags)
    state.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf8')
    print(f'ComfyUI {args.profile}: PID {process.pid}; http://127.0.0.1:{args.port}; logs: {logdir}')


if __name__=='__main__':main()
