"""Small daily entry point. No commit, deploy, backup, deletion or network calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

import security_guard as guard
import backup_status

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args, allowed=(0,)):
    result = subprocess.run(['git', '--no-optional-locks', '-C', str(repo), *args], capture_output=True)
    if result.returncode not in allowed:
        raise ValueError('Git status query failed')
    return result


def read_json(repo, relative, limit=4 * 1024 * 1024):
    path = repo / relative
    for item in [path, *path.parents]:
        if item == repo.parent:
            break
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Linked metadata')
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Missing or oversized metadata')
    data = json.loads(path.read_bytes())
    if not isinstance(data, dict):
        raise ValueError('Invalid metadata object')
    return data


def safe_text(value):
    scanner = guard.StreamScanner()
    scanner.feed(value.encode('utf-8', errors='surrogateescape'))
    return '<redacted:sha256:' + guard.name_digest(value) + '>' if scanner.findings else value


def changes(repo):
    pieces = iter(git(repo, 'status', '--porcelain=v1', '-z', '--untracked-files=normal').stdout.split(b'\0'))
    result = []
    for piece in pieces:
        if not piece:
            continue
        row = {'status': piece[:2].decode('ascii'), 'path': guard.safe_report_name(piece[3:].decode('utf-8', errors='surrogateescape'))}
        if 'R' in row['status'] or 'C' in row['status']:
            row['from'] = guard.safe_report_name(next(pieces).decode('utf-8', errors='surrogateescape'))
        result.append(row)
    return result


def policy(repo):
    value = read_json(repo, 'governance/retention-policy.json')
    if value.get('schema') != 1 or value.get('mode') != 'rules-only' or value.get('automatic_actions') is not False:
        raise ValueError('This tool supports rules only, not automatic cleanup')
    if value.get('backup_destination') is not None or value.get('independent_backup_verified') is not False:
        raise ValueError('A destination declaration is not a verified backup')
    categories = value.get('categories')
    required = {'original_history', 'release_bundles', 'deployment_backups', 'mutable_databases', 'private_configuration', 'unique_assets', 'temporary_validation'}
    if not isinstance(categories, dict) or set(categories) != required:
        raise ValueError('Invalid retention categories')
    if not value.get('cleanup_requires', {}).get('explicit_review') or not value.get('cleanup_requires', {}).get('no_active_users'):
        raise ValueError('Cleanup safeguards required')
    return value


def collect_status(repo=ROOT, backup_index=None):
    repo = Path(repo).absolute()
    head = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    version = read_json(repo, 'governance/version.json')
    number = version.get('version')
    if not isinstance(number, str) or not re.fullmatch(r'\d+\.\d+\.\d+', number):
        raise ValueError('Invalid maintenance version')
    ref = 'refs/tags/comfyui-v' + number
    found = git(repo, 'show-ref', '--verify', '--quiet', ref, allowed=(0, 1)).returncode == 0
    tag_type = git(repo, 'cat-file', '-t', ref).stdout.decode().strip() if found else None
    tag_commit = git(repo, 'rev-parse', ref + '^{commit}').stdout.decode().strip() if found else None
    ancestor = found and git(repo, 'merge-base', '--is-ancestor', tag_commit, head, allowed=(0, 1)).returncode == 0
    count = int(git(repo, 'rev-list', '--first-parent', '--count', tag_commit + '..HEAD').stdout) if ancestor else None
    hook = git(repo, 'config', '--local', '--get', 'core.hooksPath', allowed=(0, 1)).stdout.decode().strip()
    state = changes(repo)
    manifest = read_json(repo, 'snapshot/manifest.json')
    policy(repo)
    if backup_index is None:
        configured = git(repo, 'config', '--local', '--get', 'comfyui.backupIndex', allowed=(0, 1)).stdout.decode('utf-8').strip()
        backup_index = configured or None
    backup = backup_status.inspect(repo, backup_index, head, not state)
    return {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'repository': str(repo), 'branch': safe_text(git(repo, 'branch', '--show-current').stdout.decode().strip()),
        'head': head, 'working_tree_clean': not state, 'changes': state,
        'maintenance_version': number, 'version_metadata_state': version.get('state'),
        'local_release': {'tag': ref, 'exists': found, 'annotated': tag_type == 'tag',
                          'commit': tag_commit, 'is_ancestor_of_head': bool(ancestor),
                          'first_parent_commits_after_release': count},
        'hooks_configured': hook in {'.githooks', str(repo / '.githooks')},
        'runtime': {'checked_live': False, 'deployment_commit': None,
                    'manifest_captured_at': manifest.get('created_at'),
                    'recorded_bounded_deployments': len(manifest.get('accepted_runtime_deployments', [])),
                    'note': 'Recorded receipts are historical, bounded evidence; this status does not inspect or certify the running application.'},
        'backup': backup,
        'modified_production': False,
    }


def history(repo=ROOT, limit=10):
    if not 1 <= limit <= 50:
        raise ValueError('History limit must be 1 to 50')
    raw = git(repo, 'log', '--first-parent', '-n', str(limit), '--format=%h %s').stdout.decode('utf-8', errors='replace')
    return [safe_text(line) for line in raw.splitlines()]


def check_staged(repo=ROOT, fresh=False):
    # These checks inspect the index, not unstaged editor contents. A fresh run
    # remains available; only a successful cached run populates local metadata.
    commands = [
        ['scripts/technical_catalog.py', 'check', '--staged', '--enforce-changes'],
        ['scripts/security_guard.py', '--staged'] + ([] if fresh else ['--cache-staged']),
    ]
    for command in commands:
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', *command], cwd=repo)
        if result.returncode:
            return result.returncode
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    status_parser = commands.add_parser('status', help='Current Git/tag state; never a live-runtime acceptance')
    status_parser.add_argument('--json', action='store_true')
    status_parser.add_argument('--backup-index', type=Path, help='Local private backup index; overrides repo-local comfyui.backupIndex')
    history_parser = commands.add_parser('history', help='Only the maintenance first-parent history')
    history_parser.add_argument('--limit', type=int, default=10)
    check_parser = commands.add_parser('check-staged', help='Check staged bytes and documentation, using the local cache')
    check_parser.add_argument('--fresh', action='store_true', help='Run without reading or writing the staged cache')
    commands.add_parser('backup-policy', help='Show rules only; does not make or delete a backup')
    args = parser.parse_args()
    try:
        if args.command == 'check-staged':
            return check_staged(fresh=args.fresh)
        if args.command == 'history':
            print('\n'.join(history(limit=args.limit)))
        elif args.command == 'backup-policy':
            print(json.dumps(policy(ROOT), ensure_ascii=False, indent=2))
        else:
            report = collect_status(backup_index=args.backup_index)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                tag = report['local_release']
                print('主仓：' + report['repository'])
                print('当前：' + report['branch'] + ' / ' + report['head'][:12])
                print('本地维护标签：' + (tag['tag'].removeprefix('refs/tags/') if tag['annotated'] else '尚无对应 annotated 标签'))
                print('未提交变更：' + str(len(report['changes'])))
                for item in report['changes']:
                    print('  ' + item['status'] + ' ' + item['path'])
                print('提交保护：' + ('已配置' if report['hooks_configured'] else '未配置，请按 MAINTENANCE 启用'))
                print('运行状态：未实测；Git 标签不等于当前部署版本。')
                for line in backup_status.lines(report['backup']):
                    print(line)
        return 0
    except Exception as exc:
        # Metadata and Git errors may contain paths or private values.
        print(json.dumps({'pass': False, 'error': type(exc).__name__, 'rule': 'maintenance_query_failed'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
