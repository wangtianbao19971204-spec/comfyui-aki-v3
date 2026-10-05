"""Offline, exact-assignment migration of legacy remote-LLM BAT configuration.

Dry-run is the default. --write creates a new private directory containing the
JSON and byte-identical BAT backups; it never edits or executes a runtime file.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path

from external_state import ContractError, absolute_path, no_links, write_external_json
from snapshot import REPO, digest

MODULE = REPO / 'snapshot/runtime/remote_llm_guard/launcher.py'
SPEC = importlib.util.spec_from_file_location('remote_llm_launcher_contract', MODULE)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
FILES = ['启动_绘世_自动唤醒远端LLM.bat', '测试_远端LLM心跳.bat']
PATH_NAMES = {'ROOT', 'PY', 'PYW', 'LAUNCHER'}
ALLOWED = launcher.ENVIRONMENT_KEYS | PATH_NAMES
ASSIGNMENT = re.compile(r'set "([A-Z][A-Z0-9_]*)=(.*)"', re.I)
EXPANSION = re.compile(r'%([A-Z][A-Z0-9_]*)%', re.I)


def parse_assignments(raw):
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ContractError('legacy_batch_not_utf8') from None
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not re.match(r'(?i)^set\s', line):
            continue
        match = ASSIGNMENT.fullmatch(line)
        if not match or match[1].upper() not in ALLOWED or match[1].upper() in result:
            raise ContractError('legacy_batch_unrecognized_or_duplicate_assignment')
        name, value = match[1].upper(), match[2]
        if '\x00' in value or '"' in value or '!' in value:
            raise ContractError('legacy_batch_ambiguous_assignment')
        result[name] = value
    return result


def resolve_assignments(values, runtime):
    result = {}
    for name, raw in values.items():
        value = raw.replace('%~dp0', str(runtime) + os.sep)
        for _ in range(len(values) + 1):
            unresolved = EXPANSION.findall(value)
            if not unresolved:
                break
            if any(key.upper() not in values for key in unresolved):
                raise ContractError('legacy_batch_unknown_environment_expansion')
            value = EXPANSION.sub(lambda match: values[match[1].upper()], value)
        if '%' in value:
            raise ContractError('legacy_batch_unresolved_environment_expansion')
        result[name] = value
    root = result.get('ROOT')
    if not root or Path(root).resolve() != runtime:
        raise ContractError('legacy_batch_runtime_root_mismatch')
    return result


def capture_config(runtime, repo=REPO):
    runtime = absolute_path(str(runtime), Path(repo), must_exist=True)
    originals, combined, receipts = {}, {}, []
    for name in FILES:
        file = runtime / name
        no_links(file)
        if not file.is_file() or file.stat().st_nlink != 1 or file.stat().st_size > 1024 * 1024:
            raise ContractError('legacy_batch_not_safe_regular_file')
        raw = file.read_bytes()
        originals[name] = raw
        values = resolve_assignments(parse_assignments(raw), runtime)
        for key, value in values.items():
            if key in combined and combined[key] != value:
                raise ContractError('legacy_batch_shared_values_disagree')
            combined[key] = value
        receipts.append({'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    paths = {}
    for name, field in [('PY', 'python'), ('PYW', 'pythonw'), ('LAUNCHER', 'launcher')]:
        if name not in combined:
            raise ContractError('legacy_batch_missing_runtime_executable')
        path = Path(combined[name])
        no_links(path)
        if not path.is_absolute() or not path.resolve().is_relative_to(runtime) or not path.is_file():
            raise ContractError('legacy_executable_not_inside_runtime')
        paths[field] = path.relative_to(runtime).as_posix()
        launcher.relative_executable(runtime, paths[field])
    config = {'schema': 1, 'paths': paths,
              'environment': {key: value for key, value in combined.items() if key in launcher.ENVIRONMENT_KEYS}}
    for item in receipts:
        if digest(runtime / item['path']) != item['sha256']:
            raise ContractError('legacy_batch_changed_during_capture')
    return runtime, config, originals, receipts


def extract(runtime, external, write=False, repo=REPO):
    runtime, config, originals, source_receipts = capture_config(runtime, repo)
    external = absolute_path(str(external), Path(repo), must_exist=False)
    if external == runtime or external.is_relative_to(runtime):
        raise ContractError('private_destination_inside_runtime')
    destination = external / 'private-config/remote-llm'
    no_links(destination)
    if destination.exists():
        raise ContractError('private_remote_llm_destination_already_exists')
    receipt = {'pass': True, 'mode': 'PRIVATE_CAPTURE' if write else 'DRY_RUN',
               'files': source_receipts, 'configuration_fields': len(config['environment']),
               'configuration_values_logged': False, 'production_modified': False,
               'network_called': False, 'scripts_executed': False}
    if not write:
        return receipt
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    backups = destination / 'originals'; backups.mkdir(mode=0o700)
    try:
        # Keep exact originals before writing the transformed config.
        for name, raw in originals.items():
            with os.fdopen(os.open(backups / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
                stream.write(raw)
        write_external_json(destination / 'config.json', config, repo)
        launcher.load_config(runtime, {'COMFYUI_EXTERNAL_ROOT': str(external)})
        for item in source_receipts:
            if digest(runtime / item['path']) != item['sha256'] or digest(backups / item['path']) != item['sha256']:
                raise ContractError('legacy_batch_or_backup_changed')
        receipt['configuration_sha256'] = digest(destination / 'config.json')
        write_external_json(destination / 'MIGRATION_RECEIPT.json', receipt, repo)
        return receipt
    except BaseException:
        raise ContractError('private_capture_failed_partial_destination_retained') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--external-root', type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    external = args.external_root
    if external is None and os.environ.get('COMFYUI_EXTERNAL_ROOT'):
        external = Path(os.environ['COMFYUI_EXTERNAL_ROOT'])
    if external is None:
        external = args.runtime_root.resolve().parent / 'ComfyUI-local'
    try:
        print(json.dumps(extract(args.runtime_root, external, args.write), ensure_ascii=True, indent=2))
        return 0
    except Exception as exc:
        rule = str(exc) if isinstance(exc, (ContractError, launcher.ConfigurationError)) else type(exc).__name__
        print(json.dumps({'pass': False, 'rule': rule, 'values_not_logged': True}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
