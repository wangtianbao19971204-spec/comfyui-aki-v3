"""Isolated negative guard probes; never invokes apply or writes production."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys

sys.dont_write_bytecode = True
from snapshot_contract import BACKEND, PRODUCTION, REPORT, RESTORE, contained, digest, load, require, sha


def main():
    template = REPORT / 'rollback.template.py'
    scope = {'__name__': 'rollback_guard_probe', '__file__': str(template)}
    exec(compile(template.read_bytes(), str(template), 'exec'), scope)
    baseline = load(REPORT / 'baseline.json')
    names = [row['relative_path'] for row in baseline['sources']] + [BACKEND]
    after, before = b'isolated candidate bytes', b'isolated before bytes'
    rows = [{'relative_path': name, 'snapshot_path': 'sources/' + name, 'before_path': 'before/' + name,
             'sha256': digest(after), 'bytes': len(after), 'before_sha256': digest(before), 'before_bytes': len(before)} for name in names]
    fixture = {'sources': rows, 'formal_files': {'fixture': 'isolated'}}
    class MemoryFile:
        def __init__(self, body):
            self.body = body
        def read_bytes(self):
            return self.body
        def stat(self):
            return SimpleNamespace(st_size=len(self.body))
    scope['contained'] = lambda root, relative: MemoryFile(before if relative.startswith('before/') else after)
    scope['sha'] = lambda file: digest(file.read_bytes())
    scope['formal_checks'] = lambda expected: ({'fixture': {'unchanged': True}}, {})
    scope['service_state'] = lambda: {'listener_pids': [123], 'ready': True, 'queue': {'running': 0, 'pending': 0}}
    scope['apply'] = lambda *args: (_ for _ in ()).throw(AssertionError('apply is forbidden in probe'))
    checks = []
    checked = scope['preflight'](fixture)
    require(checked['passed'] and checked['production_writes'] == 0, 'Default probe was not read-only')
    require(checked['restore_file_count'] == len(RESTORE) and checked['keep_file_count'] == 23 - len(RESTORE), 'Restore/keep count drift')
    checks.append({'name': 'isolated valid preflight', 'passed': True})
    def busy():
        raise ValueError('Service must be idle with an empty queue')
    scope['service_state'] = busy
    checked = scope['preflight'](fixture)
    require(not checked['passed'] and checked['production_writes'] == 0, 'Busy service was not refused')
    checks.append({'name': 'busy service refuses with zero writes', 'passed': True})
    scope['service_state'] = lambda: {'listener_pids': [123], 'ready': True, 'queue': {'running': 0, 'pending': 0}}
    locked = {name: after for name in names}
    locked[next(iter(RESTORE))] = b'changed after freeze'
    checked = scope['preflight'](fixture, locked)
    require(not checked['passed'] and len(checked['errors']) == 1 and checked['production_writes'] == 0, 'Source drift was not refused')
    checks.append({'name': 'source drift refuses with zero writes', 'passed': True})
    scope['formal_checks'] = lambda expected: ({'fixture': {'unchanged': False}}, {})
    checked = scope['preflight'](fixture)
    require(not checked['passed'] and checked['production_writes'] == 0, 'Formal drift was not refused')
    checks.append({'name': 'formal file drift refuses with zero writes', 'passed': True})
    for invalid in ('../escape.py', 'web/../../escape.py', 'C:/escape.py', '/escape.py', 'web\\escape.py'):
        try:
            contained(REPORT, invalid)
        except ValueError:
            continue
        raise AssertionError('Unsafe path accepted: ' + invalid)
    checks.append({'name': 'real containment helper rejects traversal and absolute paths', 'passed': True})
    preparation = load(REPORT / 'snapshot_tools_preparation_v3.json')
    require({name: sha(PRODUCTION / name) for name in preparation['source_sha256']} == preparation['source_sha256'], 'Production changed during probes')
    output = REPORT / 'snapshot_guard_probes_v3.json'
    require(not output.exists(), 'Preserve completed probe receipt')
    result = {'passed': True, 'checks': checks, 'production_writes': 0, 'apply_called': False,
              'limits': 'Negative probes use isolated in-memory source/formal/service fixtures. Live source hashes are checked separately; this does not certify frozen-package preflight.'}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
