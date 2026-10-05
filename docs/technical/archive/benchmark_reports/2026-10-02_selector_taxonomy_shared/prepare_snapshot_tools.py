"""Compile report tools and bind current source hashes without changing production."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from snapshot_contract import BACKEND, FRONTEND_RESTORE, PREVIOUS, PRODUCTION, REPORT, RESTORE, digest, formal_checks, load, require, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPORT / 'snapshot_tools_preparation.json')
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.parent == REPORT and not output.exists(), 'Preserve preparation receipts; use a new filename')
    baseline_path = REPORT / 'baseline.json'
    live_path = REPORT / 'live_before.json'
    nodes_path = REPORT / 'nodes_before_receipt.json'
    baseline, live, nodes = load(baseline_path), load(live_path), load(nodes_path)
    prior_path = PREVIOUS / 'manifest.json'
    prior = load(prior_path)
    require((PREVIOUS / 'manifest.sha256').read_text(encoding='ascii').split() == [sha(prior_path), 'manifest.json'], 'Previous manifest checksum mismatch')
    previous_sources = {row['relative_path']: row for row in prior['sources']}
    rows = baseline['sources']
    require(len(rows) == 22 and {row['relative_path'] for row in rows} == set(previous_sources), 'Baseline must contain twenty-two distinct previous sources')
    sources = {}
    changed = set()
    for row in rows:
        relative = row['relative_path']
        require(sha(REPORT / 'before' / relative) == row['sha256'] == previous_sources[relative]['sha256'], 'Baseline bytes differ from previous snapshot: ' + relative)
        require(sha(PREVIOUS / previous_sources[relative]['snapshot_path']) == row['sha256'], 'Previous frozen source changed: ' + relative)
        sources[relative] = sha(PRODUCTION / relative)
        if sources[relative] != row['sha256']:
            changed.add(relative)
    require(changed == FRONTEND_RESTORE, 'Frontend changes differ from the declared restore set')
    require(sha(REPORT / 'before/nodes.py') == nodes['sha256'], 'Backend before bytes do not match capture receipt')
    sources[BACKEND] = sha(PRODUCTION / BACKEND)
    require(sources[BACKEND] != nodes['sha256'], 'Declared backend source has no change')
    workflows, data = formal_checks(live['formal_files'])
    require(all(row['unchanged'] for row in [*workflows.values(), *data.values()]), 'Formal files changed')
    tools = ['snapshot_contract.py', 'prepare_snapshot_tools.py', 'verify_selector_final_guard.py', 'freeze_source_snapshot_final.py', 'rollback.template.py']
    for name in tools:
        path = REPORT / name
        compile(path.read_bytes(), str(path), 'exec')
    result = {'prepared_at': datetime.now().astimezone().isoformat(), 'passed': True,
              'source_sha256': sources, 'tool_sha256': {name: sha(REPORT / name) for name in tools},
              'baseline_reference': {'path': str(baseline_path), 'sha256': sha(baseline_path)},
              'live_before_reference': {'path': str(live_path), 'sha256': sha(live_path)},
              'nodes_before_reference': {'path': str(nodes_path), 'sha256': sha(nodes_path)},
              'previous_manifest_reference': {'path': str(prior_path), 'sha256': sha(prior_path)},
              'served_resources': 22, 'source_files': 23, 'restore_files': len(RESTORE), 'keep_files': 23 - len(RESTORE),
              'formal_workflows': 18, 'formal_data': 3, 'production_writes': 0,
              'final_guard_executed': False, 'freeze_executed': False, 'rollback_apply_executed': False}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'receipt': str(output), 'source_files': 23, 'production_writes': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
