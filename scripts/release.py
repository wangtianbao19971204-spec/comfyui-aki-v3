"""Explicit maintenance-package release preparation and local annotated tags.

No commit, push, deployment, rollback execution, or upstream version changes.
Preparation is not publication. Tagging always uses the complete history gate.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

import security_guard
import snapshot

REPO = Path(__file__).resolve().parents[1]
VERSION_PATH = 'governance/version.json'
PREFIX = 'comfyui-v'
SEMVER = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')
OID = re.compile(r'[0-9a-f]{40}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')


class ReleaseStateError(RuntimeError):
    def __init__(self, state, message):
        super().__init__(message)
        self.state = state


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace_file(path, data):
    """Atomic same-directory replacement; never expose a half-written counter."""
    descriptor, temporary = tempfile.mkstemp(prefix='.release-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def environment(repo):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    settings = [('safe.directory', Path(repo).resolve().as_posix()), ('core.fsmonitor', 'false'),
                ('core.hooksPath', os.devnull)]
    env.update({'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0',
                'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': str(len(settings))})
    for index, (key, value) in enumerate(settings):
        env[f'GIT_CONFIG_KEY_{index}'] = key
        env[f'GIT_CONFIG_VALUE_{index}'] = value
    return env


def git(repo, *args, data=None, allowed=(0,)):
    result = subprocess.run(['git', '-C', str(repo), *args], input=data, capture_output=True, env=environment(repo))
    if result.returncode not in allowed:
        raise RuntimeError('Git command failed; command output withheld')
    return result


def read_plain(path, limit=2 * 1024 * 1024):
    path = Path(path)
    for item in [path, *path.parents]:
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked release input or ancestor refused')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
        raise ValueError('Release input must be a bounded ordinary file')
    return path.read_bytes()


def version(value):
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise ValueError('Expected an unprefixed major.minor.patch maintenance version')
    numbers = tuple(map(int, value.split('.')))
    if any(number > 999999999 for number in numbers):
        raise ValueError('Version component exceeds supported range')
    return numbers


def bump(current, kind):
    major, minor, patch = version(current)
    if kind == 'major':
        result = f'{major + 1}.0.0'
    elif kind == 'minor':
        result = f'{major}.{minor + 1}.0'
    elif kind == 'patch':
        result = f'{major}.{minor}.{patch + 1}'
    else:
        raise ValueError('Bump must be patch, minor, or major')
    version(result)
    return result


def validate_version(value):
    required = {'schema', 'package', 'version', 'state', 'tag_prefix', 'prepared'}
    if not isinstance(value, dict) or set(value) != required or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Invalid maintenance version schema')
    version(value['version'])
    if value['package'] != 'comfyui' or value['tag_prefix'] != PREFIX:
        raise ValueError('Invalid maintenance package identity')
    if value['state'] == 'unreleased-baseline':
        if value['version'] != '0.0.0' or value['prepared'] is not None:
            raise ValueError('Unreleased baseline must be the unnumbered 0.0.0 counter')
    elif value['state'] == 'prepared':
        item = value['prepared']
        keys = {'base_commit', 'previous_version', 'bump', 'notes_path', 'notes_sha256',
                'snapshot_manifest_sha256', 'review_sha256', 'rollback_receipt_sha256'}
        if (not isinstance(item, dict) or set(item) != keys or not isinstance(item['base_commit'], str)
                or not OID.fullmatch(item['base_commit'])):
            raise ValueError('Invalid prepared release metadata')
        if bump(item['previous_version'], item['bump']) != value['version']:
            raise ValueError('Version does not match the declared increment')
        if item['notes_path'] != f'docs/releases/{PREFIX}{value["version"]}.json':
            raise ValueError('Release note path must be the exact versioned path')
        if any(not isinstance(item[key], str) or not SHA.fullmatch(item[key]) for key in
               ['notes_sha256', 'snapshot_manifest_sha256', 'review_sha256', 'rollback_receipt_sha256']):
            raise ValueError('Invalid release evidence digest')
    else:
        raise ValueError('Unknown release metadata state')
    return value


def read_version(repo):
    raw = read_plain(Path(repo) / VERSION_PATH)
    return validate_version(json.loads(raw)), raw


def assert_clean(repo, expected_head):
    if not isinstance(expected_head, str) or not OID.fullmatch(expected_head):
        raise ValueError('An exact expected main HEAD is required')
    top = Path(git(repo, 'rev-parse', '--show-toplevel').stdout.decode().strip()).resolve()
    if top != Path(repo).resolve():
        raise ValueError('Release command must target the repository root')
    branch = git(repo, 'symbolic-ref', '-q', 'HEAD').stdout.decode().strip()
    actual = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    if branch != 'refs/heads/main' or actual != expected_head:
        raise RuntimeError('Expected main HEAD changed or checkout is not on main')
    if git(repo, 'status', '--porcelain', '--untracked-files=all').stdout:
        raise RuntimeError('Release requires a clean tracked and untracked worktree')


def refs(repo):
    return git(repo, 'for-each-ref', '--format=%(objectname) %(refname)').stdout


@contextmanager
def release_lock(repo):
    git_dir = Path(git(repo, 'rev-parse', '--absolute-git-dir').stdout.decode().strip())
    path = git_dir / 'comfyui-release.lock'
    try:
        handle = path.open('x', encoding='ascii')
    except FileExistsError:
        raise RuntimeError('Another release owner holds the lock; no reclamation attempted') from None
    try:
        handle.write(str(os.getpid())); handle.flush()
        yield
    finally:
        handle.close()
        path.unlink()


def technical_check(repo):
    script = Path(repo) / 'scripts/technical_catalog.py'
    if not script.is_file():
        raise RuntimeError('Technical catalogue gate is not installed')
    result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(script), 'check'],
                            cwd=repo, capture_output=True, env=environment(repo))
    if result.returncode:
        raise RuntimeError('Technical catalogue gate failed; output withheld')
    return {'pass': True, 'stdout_sha256': sha(result.stdout)}


def reject_secrets(raw):
    scanner = security_guard.StreamScanner()
    scanner.feed(raw)
    if scanner.findings:
        raise ValueError('Release notes or tag metadata contain a credential signature; values withheld')


def string_list(value):
    return isinstance(value, list) and 0 < len(value) <= 100 and all(isinstance(x, str) and 0 < len(x.strip()) <= 4000 for x in value)


def review_notes(repo, path, expected_sha, rollback_receipt, expected_head):
    raw = read_plain(path, 128 * 1024)
    if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha) or sha(raw) != expected_sha:
        raise ValueError('Release-note review digest is missing or stale')
    reject_secrets(raw)
    notes = json.loads(raw)
    keys = {'schema', 'summary', 'components', 'changes', 'tests', 'rollback'}
    if not isinstance(notes, dict) or set(notes) != keys or type(notes['schema']) is not int or notes['schema'] != 1:
        raise ValueError('Invalid reviewed release-note schema')
    if not isinstance(notes['summary'], str) or not 0 < len(notes['summary'].strip()) <= 2000:
        raise ValueError('A bounded release summary is required')
    if not all(string_list(notes[key]) for key in ['components', 'changes', 'tests']):
        raise ValueError('Components, changes, and actual test evidence descriptions are required')
    rollback = notes['rollback']
    keys = {'target_commit', 'receipt_id', 'receipt_sha256', 'scope', 'limitations'}
    if not isinstance(rollback, dict) or set(rollback) != keys:
        raise ValueError('A complete rollback reference is required')
    if not isinstance(rollback['target_commit'], str) or not OID.fullmatch(rollback['target_commit']):
        raise ValueError('Rollback needs an exact maintenance commit')
    if not isinstance(rollback['receipt_id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', rollback['receipt_id']):
        raise ValueError('Rollback receipt ID must be portable and contain no machine path')
    if not string_list(rollback['scope']) or not string_list(rollback['limitations']):
        raise ValueError('Rollback scope and limitations are required')
    if not isinstance(rollback['receipt_sha256'], str) or not SHA.fullmatch(rollback['receipt_sha256']):
        raise ValueError('Rollback receipt hash is required')
    if sha(read_plain(rollback_receipt)) != rollback['receipt_sha256']:
        raise ValueError('Rollback receipt bytes do not match the reviewed reference')
    if git(repo, 'merge-base', '--is-ancestor', rollback['target_commit'], expected_head, allowed=(0, 1)).returncode:
        raise ValueError('Rollback target must be an ancestor of the prepared source')
    git(repo, 'cat-file', '-e', rollback['target_commit'] + ':snapshot/manifest.json')
    return notes


def prepare(*, expected_head, expected_version, increment, notes_path, review_sha256, rollback_receipt, repo=REPO):
    repo = Path(repo).resolve()
    with release_lock(repo):
        assert_clean(repo, expected_head)
        current, original = read_version(repo)
        if current['version'] != expected_version:
            raise RuntimeError('Expected maintenance version changed')
        before_refs = refs(repo)
        if current['state'] == 'prepared':
            previous_tag = 'refs/tags/' + PREFIX + current['version']
            target = git(repo, 'rev-parse', '--verify', previous_tag + '^{commit}').stdout.decode().strip()
            if git(repo, 'merge-base', '--is-ancestor', target, expected_head, allowed=(0, 1)).returncode:
                raise RuntimeError('Previous prepared version has no ancestor release tag')
        upcoming = bump(current['version'], increment)
        if git(repo, 'show-ref', '--verify', '--quiet', 'refs/tags/' + PREFIX + upcoming, allowed=(0, 1)).returncode == 0:
            raise RuntimeError('Next maintenance tag already exists')
        notes = review_notes(repo, notes_path, review_sha256, rollback_receipt, expected_head)
        manifest_raw = read_plain(repo / 'snapshot/manifest.json', 32 * 1024 * 1024)
        technical_check(repo)
        record = {'schema': 1, 'package': 'comfyui', 'version': upcoming, 'base_commit': expected_head,
                  'snapshot_manifest_sha256': sha(manifest_raw), 'review_sha256': review_sha256,
                  'reviewed_notes': notes, 'runtime_deployed': False}
        record_raw = encoded(record)
        relative = f'docs/releases/{PREFIX}{upcoming}.json'
        destination = repo / relative
        if destination.exists() or destination.is_symlink():
            raise FileExistsError('Versioned release notes already exist; no overwrite permitted')
        # Also reject linked destination ancestors before mkdir/open.
        for ancestor in destination.parents:
            if ancestor.exists():
                info = ancestor.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Linked release destination refused')
        result = {'schema': 1, 'package': 'comfyui', 'version': upcoming, 'state': 'prepared',
                  'tag_prefix': PREFIX, 'prepared': {'base_commit': expected_head, 'previous_version': current['version'],
                  'bump': increment, 'notes_path': relative, 'notes_sha256': sha(record_raw),
                  'snapshot_manifest_sha256': sha(manifest_raw), 'review_sha256': review_sha256,
                  'rollback_receipt_sha256': notes['rollback']['receipt_sha256']}}
        validate_version(result)
        assert_clean(repo, expected_head)
        if (refs(repo) != before_refs or read_plain(repo / VERSION_PATH) != original
                or read_plain(repo / 'snapshot/manifest.json', 32 * 1024 * 1024) != manifest_raw
                or sha(read_plain(notes_path, 128 * 1024)) != review_sha256
                or sha(read_plain(rollback_receipt)) != notes['rollback']['receipt_sha256']):
            raise RuntimeError('Release inputs changed during preparation')
        destination.parent.mkdir(parents=True, exist_ok=True)
        created = False
        next_raw = encoded(result)
        try:
            with destination.open('xb') as handle:
                handle.write(record_raw)
            created = True
            if read_plain(repo / VERSION_PATH) != original or refs(repo) != before_refs:
                raise RuntimeError('Version or refs changed immediately before preparation write')
            replace_file(repo / VERSION_PATH, next_raw)
            dirty_paths = {line[3:] for line in git(repo, 'status', '--porcelain', '--untracked-files=all').stdout.decode().splitlines()}
            if (refs(repo) != before_refs or not dirty_paths <= {VERSION_PATH, relative}
                    or read_plain(repo / VERSION_PATH) != next_raw
                    or read_plain(repo / 'snapshot/manifest.json', 32 * 1024 * 1024) != manifest_raw):
                raise RuntimeError('Parallel changes appeared during preparation; owned metadata rolled back when unchanged')
        except BaseException as exc:
            if created and refs(repo) != before_refs:
                raise ReleaseStateError('prepare_partial_state_retained',
                                        'Refs changed after metadata writes; do not undo a concurrent commit') from exc
            if read_plain(repo / VERSION_PATH) == next_raw:
                replace_file(repo / VERSION_PATH, original)
            if created and destination.read_bytes() == record_raw:
                destination.unlink()
            raise
        return {'prepared': True, 'version': upcoming, 'base_commit': expected_head, 'notes_path': relative,
                'notes_sha256': sha(record_raw), 'committed': False, 'tag_created': False,
                'full_history_gate_run': False, 'production_modified': False,
                'next_step': 'Review and explicitly commit the release metadata and changelog, then invoke tag with the new expected HEAD.'}


def full_gates(repo):
    technical = technical_check(repo)
    integrity = snapshot.verify(Path(repo) / 'snapshot')
    if not integrity.get('pass'):
        raise RuntimeError('Snapshot integrity gate failed')
    # These readers use subprocesses; scope the sanitized environment for them too.
    saved = {key: value for key, value in os.environ.items() if key.upper().startswith('GIT_')}
    try:
        for key in saved:
            del os.environ[key]
        os.environ.update({key: value for key, value in environment(repo).items() if key.upper().startswith('GIT_')})
        security = security_guard.run(repo)
    finally:
        for key in list(os.environ):
            if key.upper().startswith('GIT_'):
                del os.environ[key]
        os.environ.update(saved)
    if (not security.get('pass') or security.get('mode') != 'all-history' or security.get('content_only')
            or security.get('findings')):
        raise RuntimeError('Complete history publication gate failed')
    git(repo, 'fsck', '--full', '--strict')
    return {'technical_catalogue': technical, 'snapshot_pass': True, 'full_history_pass': True,
            'scanned_objects': security['scanned_objects'], 'scanned_bytes': security['scanned_bytes']}


def tag(*, expected_head, expected_version, repo=REPO):
    repo = Path(repo).resolve()
    with release_lock(repo):
        assert_clean(repo, expected_head)
        current, raw_version = read_version(repo)
        if current['version'] != expected_version or current['state'] != 'prepared':
            raise RuntimeError('Expected prepared maintenance version changed')
        info = current['prepared']
        note_raw = read_plain(repo / info['notes_path'], 256 * 1024)
        manifest_raw = read_plain(repo / 'snapshot/manifest.json', 32 * 1024 * 1024)
        if sha(note_raw) != info['notes_sha256'] or sha(manifest_raw) != info['snapshot_manifest_sha256']:
            raise RuntimeError('Prepared notes or source manifest changed')
        reject_secrets(note_raw)
        record = json.loads(note_raw)
        if (record.get('schema') != 1 or record.get('package') != 'comfyui' or record.get('version') != expected_version
                or record.get('base_commit') != info['base_commit'] or record.get('runtime_deployed') is not False
                or record.get('snapshot_manifest_sha256') != info['snapshot_manifest_sha256']
                or record.get('review_sha256') != info['review_sha256']
                or record.get('reviewed_notes', {}).get('rollback', {}).get('receipt_sha256') != info['rollback_receipt_sha256']):
            raise RuntimeError('Version metadata and reviewed release record disagree')
        base_version = validate_version(json.loads(git(repo, 'show', info['base_commit'] + ':' + VERSION_PATH).stdout))
        if base_version['version'] != info['previous_version']:
            raise RuntimeError('Prepared previous version differs from the source commit')
        if git(repo, 'merge-base', '--is-ancestor', info['base_commit'], expected_head, allowed=(0, 1)).returncode:
            raise RuntimeError('Prepared source is not an ancestor of release HEAD')
        changed = set(git(repo, 'diff', '--name-only', info['base_commit'], expected_head).stdout.decode().splitlines())
        allowed = {VERSION_PATH, info['notes_path'], 'CHANGELOG.md'}
        if not {VERSION_PATH, info['notes_path']} <= changed or not changed <= allowed:
            raise RuntimeError('Source changed after preparation; prepare and review a new release plan')
        tag_ref = 'refs/tags/' + PREFIX + expected_version
        if git(repo, 'show-ref', '--verify', '--quiet', tag_ref, allowed=(0, 1)).returncode == 0:
            raise RuntimeError('Release tag already exists; it is never overwritten')
        before_refs = refs(repo)
        evidence = full_gates(repo)
        assert_clean(repo, expected_head)
        if (refs(repo) != before_refs or read_plain(repo / VERSION_PATH) != raw_version
                or read_plain(repo / info['notes_path'], 256 * 1024) != note_raw
                or read_plain(repo / 'snapshot/manifest.json', 32 * 1024 * 1024) != manifest_raw):
            raise RuntimeError('Release inputs changed during gates')
        identity = git(repo, 'var', 'GIT_COMMITTER_IDENT').stdout.strip()
        payload = (f'object {expected_head}\ntype commit\ntag {PREFIX}{expected_version}\n'.encode()
                   + b'tagger ' + identity + b'\n\n'
                   + f'ComfyUI maintenance package {expected_version}\nSource: {info["base_commit"]}\nNotes-SHA256: {info["notes_sha256"]}\nManifest-SHA256: {info["snapshot_manifest_sha256"]}\n'.encode())
        reject_secrets(payload)
        tag_oid = git(repo, 'mktag', data=payload).stdout.decode().strip()
        # Compare-and-create closes the HEAD race and never moves an existing tag.
        transaction = (f'start\nverify refs/heads/main {expected_head}\ncreate {tag_ref} {tag_oid}\nprepare\ncommit\n').encode()
        git(repo, 'update-ref', '--stdin', data=transaction)
        try:
            assert_clean(repo, expected_head)
        except Exception as exc:
            raise ReleaseStateError('tag_created_postcheck_failed',
                                    'Tag was created, but post-tag worktree drift prevents certification; tag retained for review') from exc
        return {'tag_created': True, 'tag': tag_ref, 'tag_object': tag_oid, 'head': expected_head,
                'version': expected_version, 'gates': evidence, 'committed': False, 'pushed': False,
                'production_modified': False, 'runtime_deployed': False,
                'note': 'Local release identity only. Bundle creation and frozen-clone acceptance remain separate required gates.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    prepare_parser = commands.add_parser('prepare')
    prepare_parser.add_argument('--expected-head', required=True)
    prepare_parser.add_argument('--expected-version', required=True)
    prepare_parser.add_argument('--bump', choices=['patch', 'minor', 'major'], required=True)
    prepare_parser.add_argument('--notes', type=Path, required=True)
    prepare_parser.add_argument('--review-sha256', required=True)
    prepare_parser.add_argument('--rollback-receipt', type=Path, required=True)
    tag_parser = commands.add_parser('tag')
    tag_parser.add_argument('--expected-head', required=True)
    tag_parser.add_argument('--expected-version', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'status':
            current, _ = read_version(REPO)
            result = {'metadata': current, 'production_modified': False}
        elif args.command == 'prepare':
            result = prepare(expected_head=args.expected_head, expected_version=args.expected_version,
                             increment=args.bump, notes_path=args.notes, review_sha256=args.review_sha256,
                             rollback_receipt=args.rollback_receipt)
        else:
            result = tag(expected_head=args.expected_head, expected_version=args.expected_version)
    except Exception as exc:
        # Raw Git errors or malformed documents may contain secrets; never echo them.
        state = getattr(exc, 'state', 'no_release_certified')
        print(json.dumps({'pass': False, 'error': type(exc).__name__, 'rule': 'release_failed_closed',
                          'state': state, 'tag_created': state == 'tag_created_postcheck_failed'}))
        return 1
    print(json.dumps({'pass': True, **result}, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
