"""Freeze the passing guard into a new package and run only read-only rollback preflight."""
import argparse
from datetime import datetime
import difflib
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
from snapshot_contract import BACKEND, PREVIOUS, PRODUCTION, REPORT, RESTORE, contained, digest, formal_checks, load, require, service_state, sha, tree_hashes

SNAPSHOT = REPORT / 'source_snapshot_final'


def build(guard_path):
    require(guard_path.parent == REPORT and guard_path.is_file(), 'Guard must be an existing file in this report directory')
    require(not SNAPSHOT.exists(), 'Preserve the completed snapshot; it cannot be overwritten')
    previous_before = tree_hashes(PREVIOUS)
    guard_body = guard_path.read_bytes()
    guard = json.loads(guard_body)
    require(guard.get('passed') is True and not guard.get('errors'), 'Final guard did not pass')
    require(guard['resource_count'] == 22 and guard['source_count'] == 23, 'Final guard source counts differ')
    preparation_path = Path(guard['preparation_reference']['path']).resolve()
    require(preparation_path.parent == REPORT and sha(preparation_path) == guard['preparation_reference']['sha256'], 'Preparation reference changed')
    preparation = load(preparation_path)
    require(guard['source_hashes'] == preparation['source_sha256'], 'Guard differs from prepared source hashes')
    for name, checksum in preparation['tool_sha256'].items():
        require(sha(REPORT / name) == checksum, 'Report tool changed after preparation: ' + name)
    baseline_path, live_path, nodes_path = REPORT / 'baseline.json', REPORT / 'live_before.json', REPORT / 'nodes_before_receipt.json'
    baseline, live, nodes = load(baseline_path), load(live_path), load(nodes_path)
    prior_path = PREVIOUS / 'manifest.json'
    require(sha(prior_path) == guard['previous_final_snapshot_reference']['sha256'], 'Previous manifest changed')
    resources = {row['relative_path']: row for row in guard['resources']}
    expected_before = {row['relative_path']: row['sha256'] for row in baseline['sources']}
    expected_before[BACKEND] = nodes['sha256']
    require(set(guard['source_hashes']) == set(expected_before) and len(resources) == 22, 'Unexpected source set')
    rows, after_bodies, before_bodies = [], {}, {}
    for relative, before_sha in expected_before.items():
        target = contained(PRODUCTION, relative)
        current = target.read_bytes()
        old_path = REPORT / 'before/nodes.py' if relative == BACKEND else contained(REPORT, 'before/' + relative)
        old = old_path.read_bytes()
        require(digest(current) == guard['source_hashes'][relative], 'Production differs from guarded source: ' + relative)
        require(digest(old) == before_sha, 'Before bytes differ from baseline: ' + relative)
        require((digest(old) != digest(current)) == (relative in RESTORE), 'Unexpected change set: ' + relative)
        route = None
        if relative != BACKEND:
            reference = resources[relative]
            route = reference['route']
            require(reference.get('served_matches_disk') is True and reference['disk_sha256'] == reference['served_sha256'] == digest(current)
                    and reference['bytes'] == len(current), 'Served resource guard mismatch: ' + relative)
        after_bodies[relative], before_bodies[relative] = current, old
        rows.append({'relative_path': relative, 'production_path': str(target), 'route': route,
                     'snapshot_path': 'sources/' + relative, 'before_path': 'before/' + relative,
                     'sha256': digest(current), 'bytes': len(current), 'before_sha256': digest(old), 'before_bytes': len(old),
                     'rollback': {'action': 'restore' if relative in RESTORE else 'keep'}})
    workflows, data = formal_checks(live['formal_files'])
    require(all(row['unchanged'] for row in [*workflows.values(), *data.values()]), 'Formal files changed before freeze')
    idle = service_state()
    require(idle['listener_pids'] == guard['service']['listener_pids'], 'Service changed after final guard')
    evidence_paths = {'baseline': baseline_path, 'live_before': live_path, 'nodes_before': nodes_path,
                      'previous_manifest': prior_path, 'preparation': preparation_path, 'final_guard': guard_path,
                      'browser': Path(guard['browser_receipt_reference']['path']).resolve(),
                      'restart': Path(guard['restart_receipt_reference']['path']).resolve()}
    require(evidence_paths['browser'].parent == REPORT and sha(evidence_paths['browser']) == guard['browser_receipt_reference']['sha256'], 'Browser receipt changed')
    require(sha(evidence_paths['restart']) == guard['restart_receipt_reference']['sha256'], 'Restart receipt changed')
    evidence_bodies = {key: path.read_bytes() for key, path in evidence_paths.items()}
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    staging = REPORT / ('source_snapshot_final_preparing_' + stamp)
    require(staging.resolve().is_relative_to(REPORT) and SNAPSHOT.resolve().is_relative_to(REPORT), 'Snapshot paths escaped report directory')
    staging.mkdir()
    for collection, prefix in ((after_bodies, 'sources/'), (before_bodies, 'before/')):
        for relative, body in collection.items():
            target = contained(staging, prefix + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
    diffs = []
    for relative in sorted(RESTORE):
        text = '\n'.join(difflib.unified_diff(before_bodies[relative].decode('utf-8').splitlines(), after_bodies[relative].decode('utf-8').splitlines(),
                                             fromfile='before/' + relative, tofile='sources/' + relative, lineterm='')) + '\n'
        target = contained(staging, 'diff/' + relative + '.diff')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        diffs.append({'relative_path': relative, 'snapshot_path': target.relative_to(staging).as_posix(), 'sha256': sha(target)})
    (staging / 'evidence').mkdir()
    references = {}
    for key, body in evidence_bodies.items():
        relative = 'evidence/' + key + '.json'
        contained(staging, relative).write_bytes(body)
        references[key] = {'path': str(evidence_paths[key]), 'snapshot_path': relative, 'sha256': digest(body)}
    (staging / 'rollback.py').write_bytes((REPORT / 'rollback.template.py').read_bytes())
    (staging / 'snapshot_contract.py').write_bytes((REPORT / 'snapshot_contract.py').read_bytes())
    (staging / 'README.txt').write_text(
        'This package freezes 22 served frontend resources plus nodes.py.\n'
        'Default: G:\\ComfyUI-aki-v3\\python\\python.exe -B rollback.py (read-only preflight).\n'
        'Explicit restore: add --apply; only five JS files and nodes.py are restored.\n'
        'The script requires unchanged source/formal hashes and an idle owned service.\n'
        'Apply performs no restart, queue action, workflow save, data write or deletion.\n'
        'After apply, restart ComfyUI under an idle-service guard, refresh the browser and rerun acceptance.\n'
        'Multi-file restore is not fully crash-transactional. Before and after bytes are retained.\n', encoding='utf-8')
    info = {'frozen_at': datetime.now().astimezone().isoformat(), 'production_root': str(PRODUCTION), 'snapshot_root': str(SNAPSHOT),
            'scope': 'Five JS files and nodes.py changed; seventeen frontend resources kept; formal files preserved.',
            'source_count': 23, 'served_resource_count': 22, 'restore_source_count': len(RESTORE), 'keep_source_count': 23 - len(RESTORE),
            'sources': rows, 'diffs': diffs, 'formal_files': live['formal_files'], 'evidence': references,
            'tool_sha256': {name: sha(staging / name) for name in ('rollback.py', 'snapshot_contract.py')},
            'previous_final_package_reference': {'path': str(PREVIOUS), 'tree_sha256': previous_before},
            'production_writes': 0, 'rollback_apply_executed': False, 'deleted_files_on_rollback': 0,
            'limits': ['Frozen bytes and read-only preflight do not prove an executed rollback.',
                       'Backend restoration requires a controlled restart and fresh browser acceptance.']}
    manifest_path = staging / 'manifest.json'
    manifest_path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (staging / 'manifest.sha256').write_text(sha(manifest_path) + '  manifest.json\n', encoding='ascii')
    for relative, body in after_bodies.items():
        require(contained(PRODUCTION, relative).read_bytes() == body, 'Production changed during freeze')
    for key, body in evidence_bodies.items():
        require(evidence_paths[key].read_bytes() == body, 'Evidence changed during freeze: ' + key)
    require(tree_hashes(PREVIOUS) == previous_before, 'Previous frozen package changed during freeze')
    workflows, data = formal_checks(live['formal_files'])
    require(all(row['unchanged'] for row in [*workflows.values(), *data.values()]), 'Formal files changed during freeze')
    require(service_state()['listener_pids'] == idle['listener_pids'], 'Service changed during freeze')
    require(not SNAPSHOT.exists(), 'Final snapshot appeared during freeze; preserve staging')
    staging.rename(SNAPSHOT)
    checked = subprocess.run([sys.executable, '-B', str(SNAPSHOT / 'rollback.py')], capture_output=True, text=True, encoding='utf-8')
    require(checked.returncode == 0, 'Read-only packaged rollback preflight failed: ' + checked.stdout + checked.stderr)
    preflight = json.loads(checked.stdout)
    require(preflight['passed'] is True and preflight['production_writes'] == 0, 'Rollback preflight was not read-only')
    receipt = {'completed_at': datetime.now().astimezone().isoformat(), 'passed': True, 'snapshot_path': str(SNAPSHOT),
               'manifest_sha256': sha(SNAPSHOT / 'manifest.json'), 'source_files': 23, 'before_files': 23, 'diff_files': len(RESTORE),
               'restore_files': len(RESTORE), 'keep_files': 23 - len(RESTORE), 'previous_final_package_unchanged': tree_hashes(PREVIOUS) == previous_before,
               'production_writes': 0, 'rollback_apply_executed': False, 'rollback_preflight': preflight}
    path = REPORT / ('source_snapshot_final_receipt_' + stamp + '.json')
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guard', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.guard.resolve()), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({'passed': False, 'errors': [str(error)], 'production_writes': 0, 'rollback_apply_executed': False,
                          'limits': 'Any preparing or completed package is retained; nothing is overwritten or recursively removed.'}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
