"""Read-only final guard after root-owned selector GUI acceptance."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from snapshot_contract import BACKEND, FRONTEND_RESTORE, PREVIOUS, PRODUCTION, REPORT, digest, formal_checks, get, load, require, service_state, sha, tree_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-receipt', required=True, type=Path)
    parser.add_argument('--preparation', type=Path, default=REPORT / 'snapshot_tools_preparation.json')
    parser.add_argument('--output', type=Path, default=REPORT / 'final_live_guard.json')
    args = parser.parse_args()
    output, browser_path, preparation_path = args.output.resolve(), args.browser_receipt.resolve(), args.preparation.resolve()
    require(output.parent == REPORT and not output.exists(), 'Preserve completed final guards; use a new filename')
    require(browser_path.parent == REPORT and preparation_path.parent == REPORT, 'Receipts must be in this report directory')
    preparation = load(preparation_path)
    require(preparation.get('passed') is True, 'Preparation did not pass')
    for name, checksum in preparation['tool_sha256'].items():
        require(sha(REPORT / name) == checksum, 'Report tool changed after preparation: ' + name)
    for key in ('baseline_reference', 'live_before_reference', 'nodes_before_reference', 'previous_manifest_reference'):
        require(sha(Path(preparation[key]['path'])) == preparation[key]['sha256'], 'Preparation reference changed: ' + key)
    baseline = load(REPORT / 'baseline.json')
    live = load(REPORT / 'live_before.json')
    browser = load(browser_path)
    require(browser.get('passed') is True and not browser.get('errors'), 'Browser receipt must declare passed=true and no errors')
    browser_sha = sha(browser_path)
    previous_tree = tree_hashes(PREVIOUS)
    started = datetime.now().astimezone().isoformat()
    before_service = service_state()
    before_sources = {relative: sha(PRODUCTION / relative) for relative in preparation['source_sha256']}
    require(before_sources == preparation['source_sha256'], 'Production changed after preparation; bind a new preparation receipt')
    errors, resources = [], []
    for row in baseline['sources']:
        relative = row['relative_path']
        target = PRODUCTION / relative
        result = {'relative_path': relative, 'route': row['route'], 'disk_sha256': before_sources[relative], 'bytes': target.stat().st_size}
        try:
            result['served_sha256'] = digest(get(row['route']))
            result['served_matches_disk'] = result['served_sha256'] == result['disk_sha256']
            if not result['served_matches_disk']:
                errors.append('Served resource differs: ' + relative)
        except Exception as error:
            result.update(served_matches_disk=False, error=str(error))
            errors.append('Served resource unavailable: ' + relative)
        resources.append(result)
    workflows, data = formal_checks(live['formal_files'])
    for row in [*workflows.values(), *data.values()]:
        if not row['unchanged']:
            errors.append('Formal workflow/data changed')
    after_sources = {relative: sha(PRODUCTION / relative) for relative in before_sources}
    if after_sources != before_sources:
        errors.append('Source changed during final guard')
    after_service = service_state()
    if before_service['listener_pids'] != after_service['listener_pids']:
        errors.append('Service listener changed during guard')
    if tree_hashes(PREVIOUS) != previous_tree or sha(browser_path) != browser_sha:
        errors.append('Previous frozen package or browser receipt changed during guard')
    changes = [{'relative_path': row['relative_path'], 'before_sha256': row['sha256'], 'after_sha256': before_sources[row['relative_path']]}
               for row in baseline['sources'] if row['sha256'] != before_sources[row['relative_path']]]
    if {row['relative_path'] for row in changes} != FRONTEND_RESTORE:
        errors.append('Changed frontend files differ from the declared restore set')
    nodes_before = load(REPORT / 'nodes_before_receipt.json')
    backend = {'relative_path': BACKEND, 'sha256': before_sources[BACKEND], 'bytes': (PRODUCTION / BACKEND).stat().st_size,
               'before_sha256': nodes_before['sha256'], 'before_bytes': nodes_before['bytes']}
    restart = load(REPORT / 'restart_receipt.json')
    if after_service['listener_pids'] != [restart['new_pid']]:
        errors.append('Current service differs from the bound restart receipt')
    result = {'started_at': started, 'verified_at': datetime.now().astimezone().isoformat(), 'phase': 'final_selector_taxonomy_shared',
              'passed': not errors, 'errors': errors, 'resource_count': 22, 'source_count': 23, 'resources': resources,
              'source_hashes': after_sources, 'source_hashes_stable_during_guard': after_sources == before_sources,
              'frontend_changes': changes, 'backend_source': backend, 'formal_workflow_count': 18,
              'formal_workflows': workflows, 'formal_data': data, 'service': after_service,
              'previous_final_snapshot_reference': preparation['previous_manifest_reference'],
              'previous_final_package_unchanged': tree_hashes(PREVIOUS) == previous_tree,
              'preparation_reference': {'path': str(preparation_path), 'sha256': sha(preparation_path)},
              'browser_receipt_reference': {'path': str(browser_path), 'sha256': browser_sha},
              'restart_receipt_reference': {'path': str(REPORT / 'restart_receipt.json'), 'sha256': sha(REPORT / 'restart_receipt.json')},
              'writes': {'production': 0, 'workflow': 0, 'formal_data': 0, 'browser': 0, 'queue': 0},
              'limits': ['GUI claims belong to the bound browser receipt. This guard checks current source/served bytes, preserved files and idle service.',
                         'No prompt insertion, undo, GPU generation or performance certification is implied by source equality.']}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'output': str(output), 'served_matches': sum(row['served_matches_disk'] for row in resources),
                      'formal_unchanged': sum(row['unchanged'] for row in [*workflows.values(), *data.values()]), 'errors': errors}, ensure_ascii=False))
    return 0 if result['passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
