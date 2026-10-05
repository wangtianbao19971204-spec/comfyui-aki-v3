"""Read-only preflight by default; explicit --apply restores exactly five JS files and nodes.py."""
import argparse
import contextlib
import ctypes
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from snapshot_contract import BACKEND, FRONTEND_RESTORE, PRODUCTION, RESTORE, WORKSPACE, contained, digest, formal_checks, load, require, service_state, sha

PACKAGE = Path(__file__).resolve().parent


def manifest():
    body = (PACKAGE / 'manifest.json').read_bytes()
    require((PACKAGE / 'manifest.sha256').read_text(encoding='ascii').split() == [digest(body), 'manifest.json'], 'Manifest checksum mismatch')
    info = json.loads(body)
    require(Path(info['production_root']).resolve() == PRODUCTION and Path(info['snapshot_root']).resolve() == PACKAGE, 'Manifest root mismatch')
    for name, checksum in info['tool_sha256'].items():
        require(name in ('rollback.py', 'snapshot_contract.py') and sha(PACKAGE / name) == checksum, 'Packaged tool checksum mismatch')
    require(set(info['tool_sha256']) == {'rollback.py', 'snapshot_contract.py'}, 'Unexpected rollback tools')
    evidence = {}
    for key, reference in info['evidence'].items():
        value = contained(PACKAGE, reference['snapshot_path']).read_bytes()
        require(digest(value) == reference['sha256'], 'Bound evidence changed: ' + key)
        evidence[key] = json.loads(value)
    guard = evidence['final_guard']
    require(guard.get('passed') is True and not guard.get('errors'), 'Bound final guard did not pass')
    browser = evidence['browser']
    require(browser.get('passed') is True and not browser.get('errors'), 'Bound browser acceptance did not pass')
    baseline = {row['relative_path']: row for row in evidence['baseline']['sources']}
    prior = {row['relative_path']: row for row in evidence['previous_manifest']['sources']}
    resources = {row['relative_path']: row for row in guard['resources']}
    require(len(baseline) == len(prior) == len(resources) == 22 and set(baseline) == set(prior) == set(resources), 'Expected exactly twenty-two mapped resources')
    rows = info['sources']
    require(len(rows) == 23 and len({row['relative_path'] for row in rows}) == 23
            and {row['relative_path'] for row in rows} == set(baseline) | {BACKEND}, 'Unexpected source set')
    require({row['relative_path'] for row in rows if row['rollback']['action'] == 'restore'} == RESTORE, 'Restore plan differs from the declared files')
    require(info['formal_files'] == evidence['live_before']['formal_files'], 'Formal-file reference mismatch')
    for row in rows:
        relative = row['relative_path']
        require(Path(row['production_path']).resolve() == contained(PRODUCTION, relative), 'Production path mismatch')
        require(row['snapshot_path'] == 'sources/' + relative and row['before_path'] == 'before/' + relative, 'Snapshot path mismatch')
        action = row['rollback']['action']
        require(action == ('restore' if relative in RESTORE else 'keep'), 'Unexpected rollback action')
        require(guard['source_hashes'][relative] == row['sha256'], 'Source differs from final guard')
        if relative == BACKEND:
            require(row['route'] is None and row['before_sha256'] == evidence['nodes_before']['sha256'], 'Backend provenance mismatch')
            require(guard['backend_source']['sha256'] == row['sha256'] and guard['backend_source']['before_sha256'] == row['before_sha256'], 'Backend guard mismatch')
        else:
            reference = resources[relative]
            require(row['route'] == baseline[relative]['route'] == reference['route'], 'Route mismatch')
            require(reference.get('served_matches_disk') is True and reference['disk_sha256'] == reference['served_sha256'] == row['sha256'], 'Served source differs from final guard')
            require(row['before_sha256'] == baseline[relative]['sha256'] == prior[relative]['sha256'], 'Before source differs from previous accepted snapshot')
        require((row['before_sha256'] != row['sha256']) == (relative in RESTORE), 'Declared change set mismatch')
    return info


def preflight(info, locked=None):
    errors = []
    for row in info['sources']:
        relative = row['relative_path']
        try:
            require(sha(contained(PACKAGE, row['snapshot_path'])) == row['sha256'], 'Frozen after source checksum mismatch')
            old = contained(PACKAGE, row['before_path'])
            require(sha(old) == row['before_sha256'] and old.stat().st_size == row['before_bytes'], 'Frozen before source checksum/size mismatch')
            current = locked[relative] if locked is not None else contained(PRODUCTION, relative).read_bytes()
            require(digest(current) == row['sha256'] and len(current) == row['bytes'], 'Production changed after freeze; rollback refused')
        except (OSError, ValueError) as error:
            errors.append(relative + ': ' + str(error))
    service = None
    try:
        workflows, data = formal_checks(info['formal_files'])
        require(all(row['unchanged'] for row in [*workflows.values(), *data.values()]), 'Formal workflows/data changed after freeze')
        service = service_state()
    except Exception as error:
        errors.append(str(error))
    return {'mode': 'preflight', 'passed': not errors, 'errors': errors, 'served_resource_count': 22,
            'source_count': 23, 'restore_file_count': len(RESTORE), 'keep_file_count': 23 - len(RESTORE), 'formal_file_count': 21,
            'delete_file_count': 0, 'production_writes': 0, 'recursive_operations': 0, 'service': service,
            'limits': 'Byte/path/formal-file/idle-service checks only; no restore, restart, browser action or queue action.'}


def apply(info, expected_service):
    require(os.name == 'nt', 'Apply is limited to the original Windows host')
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    create.restype = ctypes.c_void_p
    close = kernel.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    close.restype = ctypes.c_int
    streams, originals, changed = {}, {}, []
    with contextlib.ExitStack() as stack:
        for row in sorted(info['sources'], key=lambda row: row['relative_path']):
            relative = row['relative_path']
            writable = relative in RESTORE
            handle = create(str(contained(PRODUCTION, relative)), 0x80000000 | (0x40000000 if writable else 0), 0, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise OSError(ctypes.get_last_error(), 'Cannot exclusively open ' + relative + '; nothing written')
            try:
                fd = msvcrt.open_osfhandle(handle, (os.O_RDWR if writable else os.O_RDONLY) | os.O_BINARY)
            except Exception:
                close(handle)
                raise
            stream = stack.enter_context(os.fdopen(fd, 'r+b' if writable else 'rb'))
            streams[relative] = stream
            originals[relative] = stream.read()
        checked = preflight(info, originals)
        require(checked['passed'], json.dumps(checked, ensure_ascii=False))
        require(checked['service']['listener_pids'] == expected_service['listener_pids'], 'Service changed before apply')
        try:
            for row in info['sources']:
                relative = row['relative_path']
                if relative not in RESTORE:
                    continue
                body = contained(PACKAGE, row['before_path']).read_bytes()
                require(digest(body) == row['before_sha256'], 'Before source changed during apply')
                changed.append(relative)
                stream = streams[relative]
                stream.seek(0)
                stream.write(body)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
                stream.seek(0)
                require(digest(stream.read()) == row['before_sha256'], 'Restored source verification failed')
        except Exception as error:
            recovery_errors = []
            for relative in reversed(changed):
                try:
                    stream = streams[relative]
                    stream.seek(0)
                    stream.write(originals[relative])
                    stream.truncate()
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.seek(0)
                    require(digest(stream.read()) == digest(originals[relative]), 'Candidate recovery verification failed')
                except Exception as recovery_error:
                    recovery_errors.append(relative + ': ' + str(recovery_error))
            raise RuntimeError(json.dumps({'apply_error': str(error), 'attempted_files': changed, 'candidate_recovery_errors': recovery_errors,
                                           'requires_source_verification': True}, ensure_ascii=False))
    for row in info['sources']:
        expected = row['before_sha256'] if row['relative_path'] in RESTORE else row['sha256']
        require(sha(contained(PRODUCTION, row['relative_path'])) == expected, 'Post-close source verification failed')
    workflows, data = formal_checks(info['formal_files'])
    require(all(row['unchanged'] for row in [*workflows.values(), *data.values()]), 'Formal files changed during apply')
    return {'mode': 'apply', 'passed': True, 'restored_files': sorted(RESTORE), 'production_writes': len(RESTORE),
            'keep_file_count': 23 - len(RESTORE), 'formal_file_writes': 0, 'deleted_files': [], 'recursive_operations': 0,
            'requires': 'Controlled idle service restart is required for restored nodes.py, followed by browser refresh and acceptance. This tool performs no restart or queue action.',
            'limits': 'Multi-file restore has recovery checks but is not fully crash-transactional.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Explicitly restore only the six declared sources while the service is idle')
    args = parser.parse_args()
    try:
        info = manifest()
        result = preflight(info)
        if args.apply and result['passed']:
            result = apply(info, result['service'])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['passed'] else 2
    except Exception as error:
        print(json.dumps({'passed': False, 'errors': [str(error)], 'production_writes': None if args.apply else 0,
                          'rollback_apply_requested': args.apply, 'requires_source_verification': args.apply}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
