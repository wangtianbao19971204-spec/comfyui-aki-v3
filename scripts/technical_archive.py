"""Archive explicitly reviewed technical text, never deploy or execute it.

Selection: {"schema": 1, "entries": [{"source": "benchmark_reports/...",
"role": "implementation"}]}. Optional required_external_data / missing_fixture
lists contain {source, reason}; these are private references, NOT copied backups.
Plans and receipts must remain outside the runtime and public checkout. A failed
write may leave verified new files without provenance; keep them for inspection
and retry the same approved plan, never claim a failed apply completed.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
import uuid

import security_guard
from security_guard import StreamScanner, archive_magic, blocked_path, patterns, strong_name_rules
from snapshot import REPO, portable_parts, private_config

ARCHIVE = 'docs/technical/archive'
PROVENANCE = 'governance/technical-archive.json'
README = ARCHIVE + '/README.md'
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_ENTRIES = 5000
ROLES = {'implementation', 'test', 'evidence', 'documentation', 'license', 'standard', 'configuration'}
SUFFIXES = {'.md', '.rst', '.txt', '.py', '.pyi', '.js', '.mjs', '.cjs', '.ts', '.tsx',
            '.ps1', '.psm1', '.cmd', '.bat', '.sh', '.sql', '.json', '.jsonl', '.toml',
            '.yaml', '.yml', '.ini', '.cfg', '.css', '.scss', '.html', '.vue'}
SPECIAL = {'LICENSE', 'COPYING', 'NOTICE'}
HISTORICAL_COPY = re.compile(r'(?i)(?:^|[._-])(?:before|backup|backups|rollback|candidate|stage|staged|sandbox|vendor)(?:$|[._-])')
SKIP_PARTS = {'.git', '.hg', '.svn', '.cache', '.venv', 'venv', 'node_modules',
              '__pycache__', 'site-packages', 'site_packages'}
HEX = re.compile(r'[0-9a-f]{64}')
README_BYTES = ("# 历史技术参考归档\n\n"
                "这里保存经过显式清单、内容哈希和凭据门禁审核的技术原件副本。\n"
                "它们不是当前部署源，也不因归档而获得执行授权；旧脚本可能包含固定路径、日期、PID、发布或回滚操作。\n"
                "需要复用时先在唯一主 Git 中审查与适配，再按现行维护流程验证。\n\n"
                "归档文件的原相对路径、SHA-256 和角色见 `../../../governance/technical-archive.json`。\n"
                "仓外原件不移动、不删除；private reference、缺失 fixture、模型、缓存和媒体没有被此工具备份。\n"
                "归档完整不表示依赖闭合、冷启动或实际功能验收通过。\n").encode('utf-8')


class ArchiveError(ValueError):
    """Fixed codes only: never put credential values or untrusted names in errors."""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def no_links(path):
    path = Path(path).absolute()
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ArchiveError('linked_or_reparse_path')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ArchiveError('hardlinked_path')
    return path


def root_path(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or str(path).startswith(('\\\\', '//')):
        raise ArchiveError('local_absolute_root_required')
    no_links(path)
    path = path.resolve(strict=True)
    if not path.is_dir() or path == Path(path.anchor):
        raise ArchiveError('invalid_or_broad_root')
    return path


def relative(value):
    try:
        parts = portable_parts(value)
    except (TypeError, ValueError):
        raise ArchiveError('invalid_relative_path') from None
    if any(unicodedata.normalize('NFKC', part) != part for part in parts):
        raise ArchiveError('ambiguous_unicode_path')
    if strong_name_rules(value) or patterns(value.encode('utf-8')):
        raise ArchiveError('credential_bearing_name')
    return '/'.join(parts)


def location(root, name):
    path = root.joinpath(*relative(name).split('/'))
    no_links(path)
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ArchiveError('path_outside_root')
    return path


def roots(runtime, repo):
    runtime, repo = root_path(runtime), root_path(repo)
    if runtime == repo or runtime.is_relative_to(repo):
        raise ArchiveError('runtime_inside_public_checkout')
    return runtime, repo


def source_path(runtime, repo, name):
    path = location(runtime, name)
    if path.resolve().is_relative_to(repo):
        raise ArchiveError('source_inside_public_checkout')
    return path


def source_policy(name):
    parts = relative(name).split('/')
    if any(p.casefold() in SKIP_PARTS or HISTORICAL_COPY.search(p) for p in parts[:-1]):
        return 'duplicate_private_tree_reference_only'
    if any(marker in parts[-1].casefold() for marker in ('.before', '.backup', '.bak', '.disabled')):
        return 'historical_copy_reference_only'
    if parts[-1].casefold() in {'agents.md', 'claude.md', '.gitattributes', '.gitignore'}:
        return 'active_control_file_not_archived'
    if private_config(name) or blocked_path('snapshot/runtime/' + name):
        return 'private_or_external_payload'
    if Path(name).suffix.casefold() not in SUFFIXES and parts[-1] not in SPECIAL:
        return 'not_technical_text_extension'
    if ARCHIVE + '/' + name == README:
        return 'reserved_archive_readme'
    return None


def read_regular(path, limit=MAX_FILE):
    no_links(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ArchiveError('not_regular_single_link_file')
    if before.st_size > limit:
        raise ArchiveError('file_over_limit')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(limit + 1)
    no_links(path)
    after = path.stat()
    states = {(x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns) for x in (before, opened, after)}
    if len(states) != 1 or len(data) != after.st_size or len(data) > limit:
        raise ArchiveError('file_changed_during_read')
    return data


def inspect_source(path, target=None, training_reviews=None, *, return_review=False):
    data = read_regular(path)
    if archive_magic(data[:512]) or data.startswith((b'MZ', b'\x7fELF', b'SQLite format 3\0')):
        raise ArchiveError('binary_or_compressed_payload')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ArchiveError('not_utf8_text') from None
    if any(ord(char) < 32 and char not in '\r\n\t\f' for char in text):
        raise ArchiveError('binary_control_character')
    scanner = StreamScanner()
    for start in range(0, len(data), 1024 * 1024):
        scanner.feed(data[start:start + 1024 * 1024])
    rules, removed = set(scanner.findings), set()
    if target is not None:
        registry = training_reviews if training_reviews is not None else security_guard.load_training_trigger_reviews()
        rules, removed = security_guard.apply_training_trigger_review(sha(data), [target], rules, registry)
    result = (data, sorted(rules))
    return (*result, sorted(removed)) if return_review else result


def validate_selection(selection):
    optional = {'required_external_data', 'missing_fixture'}
    annotations = {'created_at', 'scope', 'archive_base', 'execution_status', 'notes'}
    if not isinstance(selection, dict) or set(selection) - ({'schema', 'entries'} | optional | annotations):
        raise ArchiveError('invalid_selection_schema')
    if type(selection.get('schema')) is not int or selection['schema'] != 1 or not isinstance(selection.get('entries'), list):
        raise ArchiveError('invalid_selection_schema')
    result = {'schema': 1, 'entries': []}
    for key in sorted(annotations & set(selection)):
        value = selection[key]
        values = value if key == 'notes' and isinstance(value, list) else [value]
        if not values or len(values) > 200 or any(not isinstance(x, str) or len(x) > 4000 for x in values):
            raise ArchiveError('invalid_selection_annotation')
        if key == 'archive_base' and value != ARCHIVE:
            raise ArchiveError('unapproved_archive_base')
        result[key] = value
    scanner = StreamScanner()
    scanner.feed(json_bytes(selection))
    if scanner.findings:
        raise ArchiveError('credential_bearing_selection_metadata')
    claims = set()
    for row in selection['entries']:
        if not isinstance(row, dict) or set(row) != {'source', 'role'} or not isinstance(row['role'], str) or row['role'] not in ROLES:
            raise ArchiveError('invalid_selected_entry')
        name = relative(row['source'])
        if name.casefold() in claims:
            raise ArchiveError('duplicate_selected_source')
        claims.add(name.casefold())
        result['entries'].append({'source': name, 'role': row['role']})
    for category in sorted(optional):
        records = selection.get(category, [])
        if not isinstance(records, list):
            raise ArchiveError('invalid_reference_list')
        result[category] = []
        for row in records:
            if not isinstance(row, dict) or set(row) != {'source', 'reason'}:
                raise ArchiveError('invalid_reference_entry')
            name, reason = relative(row['source']), row['reason']
            if name.casefold() in claims:
                raise ArchiveError('duplicate_selected_source')
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000 or patterns(reason.encode()):
                raise ArchiveError('invalid_reference_reason')
            claims.add(name.casefold())
            result[category].append({'source': name, 'reason': reason})
    if len(claims) > MAX_ENTRIES:
        raise ArchiveError('selection_entry_limit')
    for key in ('entries', *sorted(optional)):
        result[key].sort(key=lambda row: row['source'])
    return result


def empty_provenance():
    return {'schema': 1, 'role': 'historical_reference_not_deployable', 'files': []}


def read_provenance(repo):
    path = location(repo, PROVENANCE)
    if not path.exists():
        return empty_provenance(), None
    data = read_regular(path, MAX_TOTAL)
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise ArchiveError('invalid_public_provenance') from None
    if not isinstance(value, dict) or set(value) != {'schema', 'role', 'files'} or type(value['schema']) is not int or value['schema'] != 1 or value['role'] != empty_provenance()['role'] or not isinstance(value['files'], list):
        raise ArchiveError('invalid_public_provenance')
    claims = set()
    for row in value['files']:
        if not isinstance(row, dict) or set(row) != {'source', 'path', 'sha256', 'role'}:
            raise ArchiveError('invalid_public_provenance_entry')
        name = relative(row['source'])
        if source_policy(name) or row['path'] != ARCHIVE + '/' + name or not isinstance(row['role'], str) or row['role'] not in ROLES or not isinstance(row['sha256'], str) or not HEX.fullmatch(row['sha256']):
            raise ArchiveError('invalid_public_provenance_entry')
        if row['path'].casefold() in claims:
            raise ArchiveError('duplicate_public_provenance')
        claims.add(row['path'].casefold())
        target = location(repo, row['path'])
        if not target.is_file() or sha(read_regular(target)) != row['sha256']:
            raise ArchiveError('previous_archive_content_drift')
    return value, sha(data)


def merged_provenance(previous, records):
    result = empty_provenance()
    rows = {row['path'].casefold(): row for row in previous['files']}
    for row in records:
        item = {'source': row['source'], 'path': row['destination'], 'sha256': row['sha256'], 'role': row['role']}
        prior = rows.get(item['path'].casefold())
        if prior is not None and prior != item:
            raise ArchiveError('conflicting_public_provenance')
        rows[item['path'].casefold()] = item
    result['files'] = sorted(rows.values(), key=lambda row: row['path'])
    return result


def reference_states(selection, runtime, repo):
    rows = []
    for category in ('required_external_data', 'missing_fixture'):
        for entry in selection[category]:
            try:
                path = source_path(runtime, repo, entry['source'])
            except ArchiveError as exc:
                if str(exc) not in {'linked_or_reparse_path', 'hardlinked_path'}:
                    raise
                # Private dependency notes may name an environment junction.
                # Keep only its literal reference: never resolve or enumerate it.
                rows.append({**entry, 'category': category, 'exists': None,
                             'type': str(exc) + '_not_followed',
                             'copied': False, 'content_verified': False})
                continue
            exists = path.exists()
            # "Missing fixture" means unavailable in the public replay tree;
            # an old comparison original may still exist in private storage.
            rows.append({**entry, 'category': category, 'exists': exists,
                         'type': 'directory' if path.is_dir() else 'file' if path.is_file() else 'missing',
                         'copied': False, 'content_verified': False})
    return rows


def plan(selection, runtime, repo=REPO):
    runtime, repo = roots(runtime, repo)
    selection = validate_selection(selection)
    training_reviews = security_guard.load_training_trigger_reviews(repo / security_guard.TRAINING_REVIEW_FILE)
    previous, previous_sha = read_provenance(repo)
    readme = location(repo, README)
    if readme.exists() and read_regular(readme) != README_BYTES:
        raise ArchiveError('archive_readme_conflict')
    records = []
    for entry in selection['entries']:
        row = {**entry, 'destination': ARCHIVE + '/' + entry['source']}
        reason = source_policy(entry['source'])
        if reason:
            row.update(status='rejected', reason=reason)
            records.append(row)
            continue
        try:
            source = source_path(runtime, repo, entry['source'])
            data, rules, reviewed_rules = inspect_source(source, row['destination'], training_reviews, return_review=True)
            row.update(bytes=len(data), sha256=sha(data), reviewed_rules=reviewed_rules)
            if rules:
                row.update(status='rejected', reason='credential_gate', rules=rules)
            else:
                target = location(repo, row['destination'])
                if target.exists():
                    if read_regular(target) != data:
                        raise ArchiveError('existing_target_differs')
                    row['status'] = 'identical_existing'
                else:
                    row['status'] = 'new_archive'
        except (ArchiveError, OSError) as exc:
            row.update(status='rejected', reason=str(exc) if isinstance(exc, ArchiveError) else 'source_or_target_io_error')
        records.append(row)
    if sum(row.get('bytes', 0) for row in records) > MAX_TOTAL:
        raise ArchiveError('selection_total_over_limit')
    result = {'schema': 1, 'mode': 'HISTORICAL_TECHNICAL_ARCHIVE', 'runtime_root': str(runtime),
              'repo_root': str(repo), 'selection': selection, 'records': records,
              'references': reference_states(selection, runtime, repo),
              'provenance_before': previous, 'provenance_before_sha256': previous_sha,
              'training_trigger_registry_sha256': training_reviews['sha256'],
              'source_modified': False, 'snapshot_manifest_modified': False, 'deployed': False}
    if security_guard.load_training_trigger_reviews(repo / security_guard.TRAINING_REVIEW_FILE)['sha256'] != training_reviews['sha256']:
        raise ArchiveError('training_review_registry_changed_during_plan')
    result['review_sha256'] = canonical_hash(result)
    return result


def save_new(path, data):
    no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    no_links(path)
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    no_links(path)
    if read_regular(path, MAX_TOTAL) != data:
        raise ArchiveError('new_file_verification_failed')


@contextlib.contextmanager
def apply_lock(repo):
    path = location(repo, 'local/technical-archive.apply.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    no_links(path)
    try:
        handle = path.open('xb')
    except FileExistsError:
        raise ArchiveError('archive_apply_busy') from None
    try:
        owned = os.fstat(handle.fileno())
        handle.close()
        yield
    finally:
        no_links(path)
        current = path.stat()
        if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
            path.unlink()
        else:
            raise ArchiveError('apply_lock_identity_changed')


def apply_plan(review, expected_review, repo=REPO):
    bound = dict(review)
    recorded = bound.pop('review_sha256', None)
    if not isinstance(expected_review, str) or not HEX.fullmatch(expected_review) or recorded != expected_review or canonical_hash(bound) != expected_review:
        raise ArchiveError('review_hash_mismatch')
    if review.get('schema') != 1 or review.get('mode') != 'HISTORICAL_TECHNICAL_ARCHIVE':
        raise ArchiveError('invalid_review_schema')
    runtime, repo = roots(review['runtime_root'], repo)
    if review['repo_root'] != str(repo):
        raise ArchiveError('review_repository_mismatch')
    training_reviews = security_guard.load_training_trigger_reviews(repo / security_guard.TRAINING_REVIEW_FILE)
    if 'training_trigger_registry_sha256' not in review or review['training_trigger_registry_sha256'] != training_reviews['sha256']:
        raise ArchiveError('training_review_registry_changed_since_plan')
    selection = validate_selection(review['selection'])
    if selection != review['selection'] or len(selection['entries']) != len(review['records']):
        raise ArchiveError('review_selection_mismatch')
    approved = {}
    for entry, row in zip(selection['entries'], review['records']):
        if row.get('source') != entry['source'] or row.get('role') != entry['role'] or row.get('destination') != ARCHIVE + '/' + entry['source']:
            raise ArchiveError('review_mapping_mismatch')
        if row.get('status') not in {'new_archive', 'identical_existing'} or source_policy(row['source']):
            raise ArchiveError('rejected_entry_in_review')
        if type(row.get('bytes')) is not int or not isinstance(row.get('sha256'), str) or not HEX.fullmatch(row['sha256']):
            raise ArchiveError('invalid_review_identity')
        data, rules, reviewed_rules = inspect_source(source_path(runtime, repo, row['source']), row['destination'], training_reviews, return_review=True)
        if rules or len(data) != row['bytes'] or sha(data) != row['sha256'] or reviewed_rules != row.get('reviewed_rules'):
            raise ArchiveError('source_drift_or_credential_gate')
        target = location(repo, row['destination'])
        if target.exists() and read_regular(target) != data:
            raise ArchiveError('existing_target_differs')
        approved[row['source']] = data
    if sum(map(len, approved.values())) > MAX_TOTAL:
        raise ArchiveError('selection_total_over_limit')
    if reference_states(selection, runtime, repo) != review['references']:
        raise ArchiveError('reference_state_changed')
    wanted = merged_provenance(review['provenance_before'], review['records'])
    wanted_bytes = json_bytes(wanted)

    def public_preflight():
        if security_guard.load_training_trigger_reviews(repo / security_guard.TRAINING_REVIEW_FILE)['sha256'] != training_reviews['sha256']:
            raise ArchiveError('training_review_registry_changed_since_plan')
        current, current_sha = read_provenance(repo)
        if current_sha != review['provenance_before_sha256'] and current != wanted:
            raise ArchiveError('public_provenance_changed_since_review')
        if current_sha == review['provenance_before_sha256'] and current != review['provenance_before']:
            raise ArchiveError('review_provenance_baseline_mismatch')
        readme = location(repo, README)
        if readme.exists() and read_regular(readme) != README_BYTES:
            raise ArchiveError('archive_readme_conflict')
        return current_sha

    public_preflight()
    copied, retained = [], []
    if approved:
        with apply_lock(repo):
            previous_sha = public_preflight()
            for row in review['records']:
                source = source_path(runtime, repo, row['source'])
                data, rules = inspect_source(source, row['destination'], training_reviews)
                if rules or data != approved[row['source']]:
                    raise ArchiveError('source_changed_after_preflight')
                target = location(repo, row['destination'])
                if target.exists():
                    if read_regular(target) != data:
                        raise ArchiveError('existing_target_differs')
                    retained.append(row['source'])
                else:
                    save_new(target, data)
                    copied.append(row['source'])
                if read_regular(source) != data:
                    raise ArchiveError('source_changed_during_copy')
            for row in review['records']:
                if sha(read_regular(source_path(runtime, repo, row['source']))) != row['sha256'] or sha(read_regular(location(repo, row['destination']))) != row['sha256']:
                    raise ArchiveError('final_archive_verification_failed')
            if security_guard.load_training_trigger_reviews(repo / security_guard.TRAINING_REVIEW_FILE)['sha256'] != training_reviews['sha256']:
                raise ArchiveError('training_review_registry_changed_during_apply')
            readme = location(repo, README)
            if not readme.exists():
                save_new(readme, README_BYTES)
            if read_regular(readme) != README_BYTES:
                raise ArchiveError('archive_readme_conflict')
            provenance = location(repo, PROVENANCE)
            if not provenance.exists():
                save_new(provenance, wanted_bytes)
            elif read_regular(provenance, MAX_TOTAL) != wanted_bytes:
                staged = location(repo, 'governance/.technical-archive-' + uuid.uuid4().hex + '.tmp')
                try:
                    save_new(staged, wanted_bytes)
                    if sha(read_regular(provenance, MAX_TOTAL)) != previous_sha:
                        raise ArchiveError('concurrent_public_provenance_change')
                    no_links(provenance)
                    os.replace(staged, provenance)
                finally:
                    if staged.exists():
                        no_links(staged)
                        staged.unlink()
            current, _ = read_provenance(repo)
            if current != wanted:
                raise ArchiveError('public_provenance_verification_failed')
    return {'schema': 1, 'review_sha256': expected_review, 'copied': copied, 'retained_identical': retained,
            'training_trigger_registry_sha256': training_reviews['sha256'],
            'references': review['references'], 'source_modified': False, 'snapshot_manifest_modified': False,
            'complete_runtime_restored': False, 'deployed': False, 'committed': False, 'complete': True}


def private_path(value, private_root, runtime, repo):
    private_root = root_path(private_root)
    for other in (runtime, repo):
        if private_root == other or private_root.is_relative_to(other) or other.is_relative_to(private_root):
            raise ArchiveError('private_root_overlaps_public_or_runtime')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ArchiveError('private_report_absolute_path_required')
    no_links(path)
    if not path.resolve().is_relative_to(private_root) or path.resolve() == private_root:
        raise ArchiveError('private_report_outside_private_root')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=REPO)
    sub = parser.add_subparsers(dest='command', required=True)
    planner = sub.add_parser('plan')
    planner.add_argument('--runtime', type=Path, required=True)
    planner.add_argument('--selection', type=Path, required=True)
    executor = sub.add_parser('apply')
    executor.add_argument('--plan', type=Path, required=True)
    executor.add_argument('--review-sha256', required=True)
    for command in (planner, executor):
        command.add_argument('--private-root', type=Path, required=True)
        command.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        repo = root_path(args.repo)
        if args.command == 'plan':
            runtime, repo = roots(args.runtime, repo)
            selection_path = private_path(args.selection, args.private_root, runtime, repo)
            selection = json.loads(read_regular(selection_path, MAX_TOTAL))
        else:
            # The plan path is first bounded outside the public checkout; its
            # runtime is then checked before any apply or report creation.
            private_root = root_path(args.private_root)
            candidate = location(private_root, args.plan.relative_to(private_root).as_posix())
            if candidate.resolve().is_relative_to(repo):
                raise ArchiveError('plan_inside_public_checkout')
            review = json.loads(read_regular(candidate, MAX_TOTAL))
            runtime, repo = roots(review['runtime_root'], repo)
            private_path(args.plan, private_root, runtime, repo)
        report = private_path(args.report, args.private_root, runtime, repo)
        if report.exists():
            raise ArchiveError('private_report_already_exists')
        result = plan(selection, runtime, repo) if args.command == 'plan' else apply_plan(review, args.review_sha256, repo)
        save_new(report, json_bytes(result))
        summary = {'pass': True, 'mode': args.command, 'source_modified': False, 'deployed': False}
        if args.command == 'plan':
            summary.update(review_sha256=result['review_sha256'], selected=len(result['records']),
                           rejected=sum(row['status'] == 'rejected' for row in result['records']),
                           private_references=len(result['references']))
        else:
            summary.update(copied=len(result['copied']), retained_identical=len(result['retained_identical']))
        print(json.dumps(summary))
        return 0
    except (ArchiveError, OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'pass': False, 'rule': 'technical_archive_failed_closed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
