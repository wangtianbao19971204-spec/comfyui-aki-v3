"""Offline metadata contract for private state kept outside the public checkout.

No credentials are parsed into a report. Materialization creates a new overlay;
it never edits production, overlays existing code, or copies model/media trees.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import time
import unicodedata
from pathlib import Path

from snapshot import REPO, digest, manifest_path_failures, portable_parts, private_config
from security_guard import patterns

SCHEMA = 1
CATEGORIES = {'private_config', 'mutable_db', 'mutable_cache', 'external_asset'}
ACTIONS = {'copy', 'sqlite_backup', 'reference'}
PRIVATE_EXTENSIONS = {'.json', '.jsonl', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.env', '.txt'}
SQLITE_EXTENSIONS = {'.db', '.sqlite', '.sqlite3'}
MAX_CONFIG_BYTES = 8 * 1024 * 1024
MAX_COPY_BYTES = 64 * 1024 * 1024
MAX_DB_BYTES = 2 * 1024 * 1024 * 1024
RECEIPT = 'EXTERNAL_STATE_RECEIPT.json'
ENTRY_KEYS = {'id', 'root', 'source', 'target', 'category', 'action'}
IDENTIFIER = re.compile(r'[a-z][a-z0-9_-]{0,63}')
REFERENCE_ONLY_PRIVATE_CONFIG_PATHS = frozenset({
    'qwen21_lab/extra_model_paths.yaml',
    'qwen21_lab/runtime.json',
    'qwen21_lab/server.json',
})


class ContractError(ValueError):
    """Only fixed machine-readable codes, never content from a private file."""


def canonical_json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()


def no_links(path):
    path = Path(path).absolute()
    for candidate in [*reversed(path.parents), path]:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ContractError('linked_or_reparse_path')
    return path


def absolute_path(value, repo, must_exist=False):
    if not isinstance(value, str) or not value or '\x00' in value or re.search(r'[\r\n]', value):
        raise ContractError('invalid_absolute_path')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or str(path).startswith(('\\\\', '//')):
        raise ContractError('local_absolute_path_required')
    if len(path.parts) > 1:
        relative_path('/'.join(path.parts[1:]))
    no_links(path)
    resolved = path.resolve(strict=must_exist)
    if resolved == repo.resolve() or resolved.is_relative_to(repo.resolve()):
        raise ContractError('external_state_inside_public_checkout')
    if resolved == Path(resolved.anchor):
        raise ContractError('broad_filesystem_root_forbidden')
    return resolved


def relative_path(value):
    try:
        parts = portable_parts(value)
    except (TypeError, ValueError):
        raise ContractError('invalid_portable_relative_path') from None
    if any(unicodedata.normalize('NFKC', part) != part for part in parts):
        raise ContractError('ambiguous_unicode_path')
    if any(part.casefold() == '.git' for part in parts) or patterns(value.encode('utf-8')):
        raise ContractError('unsafe_or_credential_bearing_path')
    return '/'.join(parts)


def source_file(root, relative):
    target = root.joinpath(*relative_path(relative).split('/'))
    no_links(target)
    resolved = target.resolve(strict=True)
    if not resolved.is_relative_to(root) or resolved == root:
        raise ContractError('source_escaped_root')
    info = resolved.stat()
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ContractError('source_not_regular_file_or_directory')
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise ContractError('hardlinked_source_ambiguous')
    return resolved


def source_fingerprint(path, category):
    no_links(path)
    if path.is_dir():
        return {'type': 'directory', 'bytes': None, 'sha256': None, 'verification': 'directory_reference_only'}
    before = path.stat()
    # Never read terabytes of model/media data just to build a placement manifest.
    hashed = category != 'external_asset' and (category != 'mutable_cache' or before.st_size <= MAX_CONFIG_BYTES)
    value = digest(path) if hashed else None
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ContractError('source_changed_while_hashing')
    result = {'type': 'file', 'bytes': after.st_size, 'sha256': value,
              'verification': 'sha256' if hashed else 'path_size_only'}
    if category == 'mutable_db':
        with path.open('rb') as stream:
            if stream.read(16) != b'SQLite format 3\x00':
                raise ContractError('mutable_db_is_not_sqlite')
        wal = Path(str(path) + '-wal')
        no_links(wal)
        if wal.exists() and (not wal.is_file() or wal.stat().st_nlink > 1):
            raise ContractError('unsafe_database_wal')
        result['wal'] = source_fingerprint(wal, 'private_config') if wal.exists() else None
    return result


def public_ownership(repo):
    file = repo / 'snapshot/manifest.json'
    no_links(file)
    manifest = json.loads(file.read_bytes())
    if manifest_path_failures(manifest):
        raise ContractError('public_manifest_invalid')
    claims = {entry['source'].casefold(): entry['kind'] for entry in manifest['files']}
    return digest(file), claims


def validate_plan(plan, repo=REPO):
    repo = Path(repo).resolve()
    if not isinstance(plan, dict) or set(plan) != {'schema', 'roots', 'entries'} or type(plan['schema']) is not int or plan['schema'] != SCHEMA:
        raise ContractError('invalid_plan_schema')
    if not isinstance(plan['roots'], dict) or not plan['roots'] or not isinstance(plan['entries'], list):
        raise ContractError('invalid_plan_collections')
    if len(plan['entries']) > 10000:
        raise ContractError('plan_entry_limit')
    roots = {}
    for name, value in plan['roots'].items():
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
            raise ContractError('invalid_root_id')
        root = absolute_path(value, repo, must_exist=True)
        if not root.is_dir() or str(root).casefold() in {str(p).casefold() for p in roots.values()}:
            raise ContractError('ambiguous_source_root')
        roots[name] = root
    manifest_hash, claims = public_ownership(repo)
    entries = []
    ids, sources, targets = set(), set(), {}
    copy_bytes = 0
    for raw in plan['entries']:
        if not isinstance(raw, dict) or set(raw) != ENTRY_KEYS:
            raise ContractError('unexpected_entry_fields')
        entry = dict(raw)
        if not isinstance(entry['id'], str) or not IDENTIFIER.fullmatch(entry['id']) or entry['id'] in ids:
            raise ContractError('duplicate_or_invalid_entry_id')
        ids.add(entry['id'])
        if any(not isinstance(entry[key], str) for key in ENTRY_KEYS):
            raise ContractError('entry_values_must_be_strings')
        if entry['root'] not in roots or entry['category'] not in CATEGORIES or entry['action'] not in ACTIONS:
            raise ContractError('invalid_entry_role')
        entry['source'] = relative_path(entry['source'])
        entry['target'] = relative_path(entry['target'])
        target = entry['target'].casefold()
        if target == RECEIPT.casefold() or target.startswith(RECEIPT.casefold() + '/'):
            raise ContractError('reserved_receipt_target')
        if target in targets or any(target.startswith(old + '/') or old.startswith(target + '/') for old in targets):
            raise ContractError('duplicate_or_overlapping_target')
        path = source_file(roots[entry['root']], entry['source'])
        identity = str(path).casefold()
        if identity in sources:
            raise ContractError('duplicate_physical_source')
        sources.add(identity)
        is_dir = path.is_dir()
        if is_dir and entry['action'] != 'reference':
            raise ContractError('directory_payload_copy_forbidden')
        if entry['category'] == 'external_asset' and entry['action'] != 'reference':
            raise ContractError('asset_payload_copy_forbidden')
        if entry['category'] == 'mutable_db':
            if is_dir or Path(entry['target']).suffix.lower() not in SQLITE_EXTENSIONS or entry['action'] == 'copy':
                raise ContractError('database_requires_reference_or_backup_api')
        elif entry['action'] == 'sqlite_backup':
            raise ContractError('backup_action_requires_mutable_db')
        if entry['target'].casefold() in REFERENCE_ONLY_PRIVATE_CONFIG_PATHS and (
                entry['target'] not in REFERENCE_ONLY_PRIVATE_CONFIG_PATHS or
                entry['category'] != 'private_config' or entry['action'] != 'reference'):
            raise ContractError('private_config_reference_only')
        if entry['category'] == 'private_config':
            if is_dir or not (private_config(entry['target']) or entry['target'] in {
                'ComfyUI/extra_model_paths.yaml', 'ComfyUI/user/default/comfy.settings.json',
                'ComfyUI/user/anima_lora_config.json'
            } or entry['target'] in REFERENCE_ONLY_PRIVATE_CONFIG_PATHS):
                raise ContractError('private_config_target_not_recognized')
        if entry['action'] == 'copy':
            if Path(entry['target']).suffix.lower() not in PRIVATE_EXTENSIONS and Path(entry['target']).name != '.env':
                raise ContractError('executable_or_unknown_overlay_payload')
            if path.stat().st_size > MAX_CONFIG_BYTES:
                raise ContractError('private_copy_size_limit')
            copy_bytes += path.stat().st_size
        if entry['action'] == 'sqlite_backup' and path.stat().st_size > MAX_DB_BYTES:
            raise ContractError('database_backup_size_limit')
        if copy_bytes > MAX_COPY_BYTES:
            raise ContractError('total_private_copy_size_limit')
        for claim, kind in claims.items():
            if target == claim:
                if not (entry['category'] == 'mutable_db' and kind == 'sqlite_sql'):
                    raise ContractError('overlay_would_shadow_public_payload')
            elif target.startswith(claim + '/') or claim.startswith(target + '/'):
                raise ContractError('overlay_would_shadow_public_hierarchy')
        targets[target] = entry['id']
        entries.append((entry, path))
    return roots, entries, manifest_hash


def inventory(plan, repo=REPO):
    roots, entries, manifest_hash = validate_plan(plan, repo)
    records = []
    for entry, path in entries:
        record = dict(entry)
        record['state'] = source_fingerprint(path, entry['category'])
        records.append(record)
    # One final guard after all files have been read, including DB main+WAL.
    for record, (_, path) in zip(records, entries):
        if source_fingerprint(path, record['category']) != record['state']:
            raise ContractError('source_changed_during_inventory')
    return {'schema': SCHEMA, 'kind': 'comfyui-external-state', 'public_manifest_sha256': manifest_hash,
            'roots': {key: str(value) for key, value in roots.items()}, 'entries': records,
            'contains_secret_values': False, 'assets_copied': False, 'production_modified': False}


def load_manifest(value):
    required = {'schema', 'kind', 'public_manifest_sha256', 'roots', 'entries', 'contains_secret_values', 'assets_copied', 'production_modified'}
    if not isinstance(value, dict) or set(value) != required or value.get('kind') != 'comfyui-external-state':
        raise ContractError('invalid_external_manifest')
    if value.get('contains_secret_values') is not False or value.get('assets_copied') is not False or value.get('production_modified') is not False:
        raise ContractError('unexpected_manifest_assertions')
    if not isinstance(value['entries'], list) or not isinstance(value['public_manifest_sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', value['public_manifest_sha256']):
        raise ContractError('invalid_manifest_collections_or_hash')
    entries = []
    for record in value['entries']:
        if not isinstance(record, dict) or set(record) != ENTRY_KEYS | {'state'}:
            raise ContractError('unexpected_manifest_entry_fields')
        entries.append({key: record[key] for key in ENTRY_KEYS})
    return {'schema': value['schema'], 'roots': value['roots'], 'entries': entries}


def validate_destination(destination, roots, repo):
    destination = absolute_path(str(destination), Path(repo), must_exist=False)
    if destination.exists():
        raise ContractError('destination_must_not_exist')
    if any(destination == root or destination.is_relative_to(root) or root.is_relative_to(destination) for root in roots.values()):
        raise ContractError('destination_overlaps_source_root')
    return destination


def verify_dry_run(manifest, destination=None, repo=REPO):
    plan = load_manifest(manifest)
    roots, entries, public_hash = validate_plan(plan, repo)
    if public_hash != manifest['public_manifest_sha256']:
        raise ContractError('public_manifest_changed_reinventory_required')
    current = inventory(plan, repo)
    if current != manifest:
        raise ContractError('external_state_changed_reinventory_required')
    if destination is not None:
        validate_destination(destination, roots, repo)
    references = [entry['id'] for entry, path in entries if entry['action'] == 'reference']
    return {'pass': True, 'mode': 'VERIFY_DRY_RUN', 'entries': len(entries),
            'manifest_sha256': hashlib.sha256(canonical_json(manifest)).hexdigest(),
            'reference_entries': references, 'unresolved_external_references': len(references),
            'destination_checked': destination is not None, 'production_modified': False,
            'complete_runtime_restored': False}


def sqlite_copy(source, target):
    before = source_fingerprint(source, 'mutable_db')
    deadline = time.monotonic() + 60
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise ContractError('database_backup_timeout')
    with target.open('xb'):
        pass
    with contextlib.closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=1)) as src, contextlib.closing(sqlite3.connect(target)) as dst:
        src.execute('PRAGMA query_only=ON')
        src.backup(dst, pages=256, progress=progress, sleep=0.01)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ContractError('database_backup_integrity_failed')
    if source_fingerprint(source, 'mutable_db') != before:
        raise ContractError('database_changed_during_backup')
    return digest(target)


def materialize(manifest, destination, repo=REPO):
    verified = verify_dry_run(manifest, destination, repo)
    roots, entries, public_hash = validate_plan(load_manifest(manifest), repo)
    destination = validate_destination(destination, roots, repo)
    destination.parent.mkdir(parents=True, exist_ok=True)
    no_links(destination.parent)
    destination.mkdir(mode=0o700, exist_ok=False)
    written = []
    try:
        for record, (entry, source) in zip(manifest['entries'], entries):
            if entry['action'] == 'reference':
                continue
            no_links(destination)
            target = destination.joinpath(*entry['target'].split('/'))
            no_links(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            no_links(target.parent)
            if target.exists():
                raise ContractError('overlay_target_already_exists')
            if source_fingerprint(source, entry['category']) != record['state']:
                raise ContractError('source_changed_before_copy')
            if entry['action'] == 'sqlite_backup':
                output_hash = sqlite_copy(source, target)
            else:
                with source.open('rb') as src, os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                output_hash = digest(target)
                if output_hash != record['state']['sha256']:
                    raise ContractError('copied_private_file_hash_mismatch')
            if source_fingerprint(source, entry['category']) != record['state']:
                raise ContractError('source_changed_after_copy')
            written.append({'path': entry['target'], 'bytes': target.stat().st_size, 'sha256': output_hash})
        final = inventory(load_manifest(manifest), repo)
        if final != manifest:
            raise ContractError('source_changed_during_materialization')
        receipt = {**verified, 'mode': 'OVERLAY_MATERIALIZED', 'pass': True, 'written': written,
                   'service_started': False, 'public_source_overwritten': False}
        with (destination / RECEIPT).open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2)
            stream.write('\n')
        return receipt
    except BaseException:
        # Keep the partial private tree for inspection/recovery; never remove data.
        raise ContractError('materialization_failed_partial_destination_retained') from None


def read_external_json(file, repo=REPO):
    path = absolute_path(str(file), Path(repo), must_exist=True)
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ContractError('external_manifest_file_invalid')
    if path.stat().st_nlink > 1:
        raise ContractError('hardlinked_external_manifest')
    return json.loads(path.read_bytes())


def write_external_json(file, value, repo=REPO):
    path = absolute_path(str(file), Path(repo), must_exist=False)
    if path.exists():
        raise ContractError('report_destination_exists')
    path.parent.mkdir(parents=True, exist_ok=True)
    no_links(path.parent)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    capture = commands.add_parser('inventory')
    capture.add_argument('--plan', type=Path, required=True)
    capture.add_argument('--out', type=Path, required=True)
    for command in ['verify-dry-run', 'materialize']:
        sub = commands.add_parser(command)
        sub.add_argument('--manifest', type=Path, required=True)
        sub.add_argument('--dest', type=Path, required=command == 'materialize')
    args = parser.parse_args()
    try:
        if args.command == 'inventory':
            result = inventory(read_external_json(args.plan))
            write_external_json(args.out, result)
            summary = {'pass': True, 'mode': 'INVENTORY', 'entries': len(result['entries']),
                       'contains_secret_values': False, 'production_modified': False}
        else:
            manifest = read_external_json(args.manifest)
            summary = verify_dry_run(manifest, args.dest) if args.command == 'verify-dry-run' else materialize(manifest, args.dest)
        print(json.dumps(summary, ensure_ascii=True, indent=2))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, ContractError) else type(exc).__name__
        print(json.dumps({'pass': False, 'rule': code, 'values_not_logged': True}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
