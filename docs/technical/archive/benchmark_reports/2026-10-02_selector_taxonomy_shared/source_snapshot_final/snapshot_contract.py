"""Local paths, checksums and idle-service checks for this report's snapshot tools."""
import hashlib
import json
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

import psutil

WORKSPACE = Path(r'G:\ComfyUI-aki-v3').resolve()
REPORT = WORKSPACE / 'benchmark_reports/2026-10-02_selector_taxonomy_shared'
PRODUCTION = WORKSPACE / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'
PREVIOUS = WORKSPACE / 'benchmark_reports/2026-10-02_character_selector_audit/source_snapshot_final'
BACKEND = 'modules/comfyui-anima-tools/nodes.py'
FRONTEND_RESTORE = {
    'modules/comfyui-anima-tools/js/anima_shared_prompt_data.js',
    'modules/comfyui-anima-tools/js/anima_character_selector.js',
    'modules/comfyui-anima-tools/js/anima_clothing_selector.js',
    'modules/comfyui-anima-tools/js/anima_artist_selector.js',
    'modules/comfyui-anima-tools/js/anima_background_selector.js',
}
RESTORE = FRONTEND_RESTORE | {BACKEND}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def sha(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def contained(root, relative):
    item = PurePosixPath(relative)
    require(not item.is_absolute() and bool(item.parts) and '..' not in item.parts
            and '\\' not in relative and ':' not in relative, 'Unsafe relative path: ' + relative)
    target = (root / relative).resolve()
    require(target.is_relative_to(root.resolve()), 'Path escaped expected root: ' + relative)
    return target


def tree_hashes(root):
    return {path.relative_to(root).as_posix(): sha(path) for path in root.rglob('*') if path.is_file()}


def get(route):
    with urlopen(Request('http://127.0.0.1:8188' + route, headers={'Cache-Control': 'no-cache'}), timeout=20) as response:
        return response.read()


def service_state():
    pids = sorted({row.pid for row in psutil.net_connections('tcp')
                   if row.status == 'LISTEN' and row.laddr.port == 8188})
    require(len(pids) == 1 and pids[0] is not None, 'Expected one owned 8188 listener')
    process = psutil.Process(pids[0])
    executable = Path(process.exe()).resolve()
    arguments = process.cmdline()
    require(executable == WORKSPACE / 'python/python.exe', 'Unexpected listener executable')
    require(any(Path(value).resolve() == WORKSPACE / 'ComfyUI/main.py' for value in arguments[1:]
                if not value.startswith('-')), 'Listener is not the expected ComfyUI main.py')
    cwd, cwd_reference = None, None
    try:
        cwd = Path(process.cwd()).resolve()
        require(cwd == WORKSPACE / 'ComfyUI', 'Unexpected listener working directory')
    except psutil.AccessDenied:
        receipt_path = REPORT / 'restart_receipt.json'
        receipt = load(receipt_path)
        require(receipt['new_pid'] == pids[0] and Path(receipt['cwd']).resolve() == WORKSPACE / 'ComfyUI', 'Unavailable current cwd and restart receipt does not match listener')
        require(receipt['args'] == arguments and Path(receipt['executable']).resolve() == executable, 'Listener command differs from controlled restart')
        cwd_reference = {'path': str(receipt_path), 'sha256': sha(receipt_path), 'recorded_cwd': receipt['cwd'], 'new_pid': receipt['new_pid']}
    status = json.loads(get('/unified-workbench/status'))
    queue = json.loads(get('/queue'))
    modules = status.get('modules', [])
    require(len(modules) == 5 and all(row.get('ready') for row in modules), 'Expected five ready modules')
    require(not queue['queue_running'] and not queue['queue_pending'], 'Service must be idle with an empty queue')
    return {'listener_pids': pids, 'executable': str(executable), 'cwd': str(cwd) if cwd is not None else None, 'args': arguments,
            'cwd_current_read_succeeded': cwd is not None, 'cwd_restart_auxiliary_reference': cwd_reference,
            'modules_ready': 5, 'nodes': status.get('nodes'), 'ready': True,
            'queue': {'running': 0, 'pending': 0}, 'process_created_at': process.create_time()}


def formal_checks(expected):
    require(len(expected) == 21, 'Expected eighteen workflows and three formal data files')
    workflows, data = {}, {}
    for name, checksum in expected.items():
        target = Path(name).resolve()
        if target.is_relative_to(WORKSPACE / 'ComfyUI/user/default/workflows'):
            output, key = workflows, str(target)
        else:
            require(target.is_relative_to(PRODUCTION), 'Formal file escaped expected roots')
            output, key = data, target.relative_to(PRODUCTION).as_posix()
        actual = sha(target)
        output[key] = {'expected_sha256': checksum, 'sha256': actual, 'unchanged': actual == checksum}
    require(len(workflows) == 18 and len(data) == 3, 'Unexpected formal file split')
    return workflows, data
