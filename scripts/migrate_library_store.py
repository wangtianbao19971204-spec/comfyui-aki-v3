"""Migrate the prompt library from data.json into the SQLite authority DB.

One-shot maintenance tool for the round-3 storage change.  It reads the old
``data.json`` document (read-only, never modified), writes every row into
``library.sqlite3`` in a single transaction, deep-verifies the database against
the source document, and only then replaces an existing database (keeping the
previous file as ``library.sqlite3.bak.<stamp>``).  A receipt with the source
SHA256 and row counts is stored inside the database and printed as JSON.

Default is a dry run; ``--apply`` performs the migration.  Re-running on the
same source is idempotent: the stored receipt matches, so the database is left
untouched.  ``--export-json`` writes the authoritative document back out in the
original compact data.json form (and compares it with the source when one is
given).

Examples (run from the maintenance repo root, ``$comfyPython`` = runtime python)::

    & $comfyPython -X utf8 -B scripts/migrate_library_store.py --dry-run
    & $comfyPython -X utf8 -B scripts/migrate_library_store.py --apply
    & $comfyPython -X utf8 -B scripts/migrate_library_store.py --export-json <path>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_REL = (Path('snapshot') / 'runtime' / 'ComfyUI' / 'custom_nodes'
              / 'ComfyUI-Unified-Prompt-Workbench' / 'modules'
              / 'WeiLin-Comfyui-Tools-V52-FullPromptSelector' / 'prompt_selector')
DEFAULT_STORE = (REPO_ROOT / PLUGIN_REL / 'user_data' / 'prompt_selector')


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_library_store(plugin_dir):
    module_path = Path(plugin_dir) / 'library_store.py'
    if not module_path.is_file():
        raise SystemExit('library_store.py not found under %s' % plugin_dir)
    spec = importlib.util.spec_from_file_location('weilin_library_store', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counts_of(document):
    categories = document.get('categories') or []
    return {'categories': len(categories),
            'prompts': sum(len(category.get('prompts') or []) for category in categories)}


def remove_database_files(path):
    for suffix in ('', '-wal', '-shm'):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def json_receipt(**fields):
    return json.dumps(fields, ensure_ascii=False, indent=2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data-json', type=Path, default=DEFAULT_STORE / 'data.json',
                        help='source data.json (read-only; default: repo snapshot runtime path)')
    parser.add_argument('--db', type=Path, default=None,
                        help='target library.sqlite3 (default: next to data.json)')
    parser.add_argument('--plugin-dir', type=Path, default=None,
                        help='prompt_selector package dir holding library_store.py '
                             '(default: repo snapshot runtime path)')
    parser.add_argument('--apply', action='store_true', help='perform the migration')
    parser.add_argument('--dry-run', action='store_true',
                        help='explicit dry run (the default); cannot be combined with --apply')
    parser.add_argument('--force', action='store_true',
                        help='rebuild the database even when the receipt already matches')
    parser.add_argument('--export-json', type=Path, default=None,
                        help='write the authoritative document as compact data.json and compare')
    parser.add_argument('--receipt', type=Path, default=None, help='also write the JSON receipt here')
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error('--apply and --dry-run are mutually exclusive')

    plugin_dir = args.plugin_dir or (REPO_ROOT / PLUGIN_REL)
    store_module = load_library_store(plugin_dir)
    data_json = Path(args.data_json)
    db_path = Path(args.db) if args.db else (data_json.parent / 'library.sqlite3')
    receipt = {
        'schema': 1,
        'tool': 'migrate_library_store',
        'mode': 'apply' if args.apply else 'dry-run',
        'data_json': str(data_json),
        'db': str(db_path),
        'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }

    def finish(code, **fields):
        receipt.update(fields)
        text = json_receipt(**receipt)
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(text + '\n', encoding='utf-8')
        print(text)
        return code

    if not data_json.is_file():
        return finish(2, ok=False, error='source data.json not found')
    if not args.apply and not args.export_json:
        # A dry run still has to prove the source parses and report what would happen.
        pass

    started = time.perf_counter()
    source_sha = sha256_file(data_json)
    source_bytes = data_json.stat().st_size
    source = store_module.read_json_document(data_json)
    source_counts = counts_of(source)
    receipt.update(source_sha256=source_sha, source_bytes=source_bytes,
                   source_counts=source_counts,
                   source_parse_seconds=round(time.perf_counter() - started, 3))
    print('source: %s (%d bytes, %d categories, %d prompts)'
          % (data_json, source_bytes, source_counts['categories'], source_counts['prompts']),
          file=sys.stderr)

    existing_receipt = None
    if db_path.is_file():
        try:
            existing = store_module.open_store(db_path)
            try:
                existing_receipt = existing.meta_value('__migration_receipt__')
                receipt['existing_db'] = {**existing.stat(),
                                          'tables': existing.table_counts(),
                                          'counts': existing.verify_document_equals(source, max_diffs=0)['counts']}
            finally:
                existing.close()
        except Exception as error:  # noqa: BLE001 - report, do not delete anything
            receipt['existing_db_error'] = '%s: %s' % (type(error).__name__, error)
    receipt['existing_receipt'] = existing_receipt
    receipt_matches = bool(existing_receipt
                           and existing_receipt.get('source_sha256') == source_sha
                           and not args.force)

    if not args.apply:
        actions = []
        if args.export_json and db_path.is_file():
            actions.append('export-json')
        elif db_path.is_file() and receipt_matches:
            actions.append('database already migrated from this source (idempotent no-op)')
        elif db_path.is_file():
            actions.append('replace existing database (previous kept as .bak)')
        else:
            actions.append('create database')
        receipt['plan'] = actions
        if args.export_json and db_path.is_file():
            store = store_module.open_store(db_path)
            try:
                info = store.export_json(args.export_json)
            finally:
                store.close()
            exported = store_module.read_json_document(args.export_json)
            receipt['export'] = {**info, 'counts': counts_of(exported),
                                 'digest_matches_source': store_module.document_digest(exported)
                                 == store_module.document_digest(source)}
            return finish(0, ok=bool(receipt['export']['digest_matches_source']))
        return finish(0, ok=True, would_write=not receipt_matches)

    if receipt_matches and db_path.is_file():
        if args.export_json:
            store = store_module.open_store(db_path)
            try:
                info = store.export_json(args.export_json)
            finally:
                store.close()
            exported = store_module.read_json_document(args.export_json)
            receipt['export'] = {**info, 'digest_matches_source': store_module.document_digest(exported)
                                 == store_module.document_digest(source)}
        return finish(0, ok=True, migrated=False, reason='receipt matches source SHA256')

    temp_db = db_path.with_name(db_path.name + '.migrate-' + uuid.uuid4().hex + '.tmp')
    remove_database_files(temp_db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migration_started = time.perf_counter()
    store = store_module.open_store(temp_db, create=True)
    try:
        migration_receipt = {
            'schema': 1,
            'source_sha256': source_sha,
            'source_bytes': source_bytes,
            'source_counts': source_counts,
            'migrated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        written = store.initialize_from_document(source, receipt=migration_receipt)
        migration_seconds = time.perf_counter() - migration_started
        integrity = store.integrity_check()
        verify_started = time.perf_counter()
        verification = store.verify_document_equals(source)
        receipt.update(migrated=True, written=written, integrity=integrity,
                       migration_seconds=round(migration_seconds, 3),
                       verify_seconds=round(time.perf_counter() - verify_started, 3),
                       verify=verification)
        if integrity != ['ok']:
            raise RuntimeError('integrity_check failed: %r' % (integrity,))
        if not verification['equal']:
            raise RuntimeError('database does not match the source document: %r'
                               % verification['diffs'][:5])
    except Exception:
        store.close()
        remove_database_files(temp_db)
        raise
    else:
        store.close()

    previous_backup = None
    if db_path.is_file():
        stamp = time.strftime('%Y%m%d_%H%M%S')
        previous_backup = db_path.with_name(db_path.name + '.bak.' + stamp)
        os.replace(db_path, previous_backup)
        for suffix in ('-wal', '-shm'):
            stale = Path(str(db_path) + suffix)
            if stale.exists():
                stale.unlink()
    os.replace(temp_db, db_path)
    for suffix in ('-wal', '-shm'):
        stale = Path(str(temp_db) + suffix)
        if stale.exists():
            stale.unlink()
    receipt['previous_db_backup'] = str(previous_backup) if previous_backup else None

    reopened = store_module.open_store(db_path)
    try:
        receipt['db_after_migration'] = {**reopened.stat(), 'tables': reopened.table_counts()}
        receipt['stored_receipt'] = reopened.meta_value('__migration_receipt__')
        final_verify = reopened.verify_document_equals(source)
        receipt['final_verify'] = final_verify
        if not final_verify['equal']:
            raise RuntimeError('reopened database does not match the source document')
        if args.export_json:
            info = reopened.export_json(args.export_json)
            exported = store_module.read_json_document(args.export_json)
            receipt['export'] = {**info, 'digest_matches_source':
                                 store_module.document_digest(exported)
                                 == store_module.document_digest(source)}
            if not receipt['export']['digest_matches_source']:
                raise RuntimeError('exported data.json does not match the source document')
    finally:
        reopened.close()
    receipt['total_seconds'] = round(time.perf_counter() - started, 3)
    return finish(0, ok=True)


if __name__ == '__main__':
    sys.exit(main())
