"""Develop in this Git checkout; make explicit, non-deployed source revisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from snapshot import (REPO, digest, is_link, now, payload_relative,
                      private_config, safe_path, save, supported_source_payload, verify, walk)
from security_guard import blocked_path


def source_entries(repo):
    snapshot = repo / 'snapshot'
    runtime = snapshot / 'runtime'
    entries = []
    for directory, folders, files in os.walk(runtime, followlinks=False):
        for name in folders + files:
            path = Path(directory, name)
            if name == '.git' or is_link(path):
                raise ValueError('Nested Git or linked source is not allowed: ' + str(path.relative_to(repo)))
    for file in walk(runtime, set()):
        relative = file.relative_to(runtime).as_posix()
        if file.name == '.gitattributes.upstream':
            relative = relative.removesuffix('.upstream')
        if private_config(relative):
            raise ValueError('Private configuration must stay outside Git: ' + relative)
        if blocked_path('snapshot/' + file.relative_to(snapshot).as_posix()):
            raise ValueError('Runtime data or external assets must stay outside Git: ' + relative)
        if payload_relative(relative) != file.relative_to(snapshot).as_posix():
            raise ValueError('Store upstream attributes as .gitattributes.upstream: ' + relative)
        if not supported_source_payload(relative):
            raise ValueError('Unsupported source payload; keep generated data outside the checkout: ' + relative)
        if file.stat().st_size > 50 * 1024 * 1024:
            raise ValueError('Source file exceeds 50 MiB: ' + relative)
        entries.append({'source': relative, 'path': file.relative_to(snapshot).as_posix(),
                        'sha256': digest(file), 'bytes': file.stat().st_size, 'kind': 'file'})
    return sorted(entries, key=lambda row: row['source'])


def source_changes(previous, current):
    old = {entry['source']: entry['sha256'] for entry in previous if entry['kind'] == 'file'}
    new = {entry['source']: entry['sha256'] for entry in current}
    return {'added': sorted(new.keys() - old.keys()),
            'removed': sorted(old.keys() - new.keys()),
            'changed': sorted(key for key in old.keys() & new.keys() if old[key] != new[key])}


def status(repo=REPO):
    manifest = json.loads((repo / 'snapshot/manifest.json').read_text(encoding='utf-8'))
    return source_changes(manifest['files'], source_entries(repo))


def seal(note, repo=REPO):
    """Refresh source hashes only; existing library/SQL payloads must verify unchanged."""
    if not note.strip():
        raise ValueError('A short change description is required')
    root = repo / 'snapshot'
    manifest_file = root / 'manifest.json'
    original = manifest_file.read_bytes()
    manifest = json.loads(original.decode('utf-8'))
    current = source_entries(repo)
    changes = source_changes(manifest['files'], current)
    if not any(changes.values()):
        if not verify(root)['pass']:
            raise RuntimeError('Snapshot integrity failed; a no-op seal cannot accept damaged data')
        return {'updated': False, 'changes': changes, 'production_modified': False}
    previous_sources = {entry['source']: entry for entry in manifest['files'] if entry['kind'] == 'file'}
    removed = {entry['source']: entry for entry in manifest.get('development_revision', {}).get('removed_sources', [])}
    for source in changes['removed']:
        removed[source] = {'source': source, 'previous_sha256': previous_sources[source]['sha256']}
    for entry in current:
        removed.pop(entry['source'], None)
    # Real library bytes are not re-hashed into a new truth after arbitrary edits.
    manifest['files'] = current + [entry for entry in manifest['files'] if entry['kind'] != 'file']
    manifest['created_at'] = now()
    manifest['runtime_before'] = None
    manifest['runtime_after'] = None
    manifest['development_revision'] = {
        'note': note, 'previous_manifest_sha256': hashlib.sha256(original).hexdigest(),
        'source_changes': changes, 'live_deployed': False,
        'removed_sources': [removed[key] for key in sorted(removed)],
    }
    previous = repo / 'local/source-seals' / (hashlib.sha256(original).hexdigest() + '.json')
    previous.parent.mkdir(parents=True, exist_ok=True)
    if not previous.exists():
        previous.write_bytes(original)
    try:
        save(manifest_file, manifest)
        result = verify(root)
        if not result['pass']:
            raise RuntimeError('Source seal rejected: ' + json.dumps(result['failures'], ensure_ascii=False))
        save(root / 'verification.json', result)
    except BaseException:
        manifest_file.write_bytes(original)
        raise
    return {'updated': True, 'changes': changes, 'production_modified': False,
            'live_deployed': False, 'previous_manifest': str(previous)}


def deploy_plan(runtime, repo=REPO):
    """Read-only source diff; workflows and all data require separate explicit review."""
    runtime = runtime.resolve()
    if runtime == repo.resolve() or runtime.is_relative_to(repo.resolve()):
        raise ValueError('Runtime must be outside the source checkout')
    manifest = json.loads((repo / 'snapshot/manifest.json').read_text(encoding='utf-8'))
    if not verify(repo / 'snapshot')['pass']:
        raise RuntimeError('Seal and verify the current Git sources before building a deployment plan')
    changes = []
    for entry in manifest['files']:
        if entry['kind'] != 'file':
            continue
        target = safe_path(runtime, entry['source'])
        before = digest(target) if target.is_file() else None
        if before != entry['sha256']:
            relative = entry['source']
            changes.append({'source': relative, 'operation': 'add' if before is None else 'replace', 'runtime_sha256': before, 'git_source_sha256': entry['sha256'],
                            'requires_data_review': '/user/' in relative or '/user_data/' in relative or '/templates/' in relative})
    for entry in manifest.get('development_revision', {}).get('removed_sources', []):
        target = safe_path(runtime, entry['source'])
        if target.is_file():
            changes.append({'source': entry['source'], 'operation': 'delete_requires_review',
                            'runtime_sha256': digest(target), 'previous_git_sha256': entry['previous_sha256'],
                            'git_source_sha256': None, 'requires_data_review': True})
    return {'mode': 'READ_ONLY_PLAN', 'changes': changes, 'production_modified': False,
            'warning': 'This plan does not authorize deployment, workflow replacement, or database writes.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    seal_parser = commands.add_parser('seal')
    seal_parser.add_argument('--note', required=True)
    plan = commands.add_parser('deploy-plan')
    plan.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'status':
        result = status()
    elif args.command == 'seal':
        result = seal(args.note)
    else:
        result = deploy_plan(args.runtime)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
