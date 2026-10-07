"""One-way, new-path-only import of explicitly selected Comfy maintenance sources.

This is not capture/adopt: existing main-repository files are never overwritten.
No runtime script is executed, and no service, database or original Git is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from snapshot import (REPO, REVIEWED_SUPPORT_FILES, EXACT_SOURCE_SUPPORT_FILES, exact_support_source,
                      digest, is_link, now, payload_relative,
                      portable_parts, private_config, safe_path, source_license_name, reviewed_plugin_sources)
from security_guard import StreamScanner, blocked_path
import security_guard


MAX_SOURCE = 50 * 1024 * 1024
SOURCE_SUFFIXES = {'.py', '.pyi', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts', '.patch', '.vue', '.svelte',
                   '.css', '.scss', '.sass', '.less', '.html', '.sql', '.sh', '.ps1', '.psm1',
                   '.bat', '.cmd', '.toml', '.ini', '.cfg', '.md', '.rst', '.c', '.cc', '.cpp',
                   '.h', '.hpp', '.cu', '.cuh', '.glsl', '.frag', '.vert', '.svg',
                   '.mako', '.xml', '.example', '.in'}
SPECIAL = {'.gitignore', '.gitattributes', 'LICENSE', 'COPYING', 'NOTICE', 'Dockerfile',
           'VERSION', 'PORTABLE_BUILD', 'requirements.txt.filtered', 'CODEOWNERS',
           'put_blueprints_here', 'manager_requirements.txt'}
PUBLIC_JSON_NAMES = {'package.json', 'package-lock.json', 'tsconfig.json', 'jsconfig.json'}
PUBLIC_JSON_PATHS = {
    'anima_lora_forge/templates/new_character.profile.json',
    'character_lora_forge/templates/anima_current_api.json',
    'qwen21_lab/workflows_api/background.json',
    'qwen21_lab/workflows_api/coat_mask.json',
    'qwen21_lab/workflows_api/hands.json',
}
PRUNE = {'.git', '.hg', '.svn', '.venv', 'venv', 'python', 'site-packages', 'site_packages',
         'node_modules', '__pycache__', '.cache', '.pytest_cache', '.mypy_cache', '.ai', '.agents',
         'logs', 'temp', 'tmp', 'output', 'outputs', 'input', 'preview', 'preview_thumbnails',
         'user_data', 'userdatas', 'lora_userdatas', 'loras_userdatas', 'translate_userdatas',
         'prompt_selector_data_backups', 'random_tag', 'autosave', 'sd-models'}
TRAINER = 'anima_lora_forge/vendor/sd-trainer/SD-Trainer'
TRAINER_PORTABLE_FILES = (
    'Download-Anima-Model.bat',
    'Fix-Portable-Bats.bat',
    'install_xformers.bat',
    'README.txt',
    'run_gui_portable.bat',
    'run_gui.bat',
    'Update-SD-Trainer-Release.bat',
    'Update-SD-Trainer.bat',
    'update/update_dependencies.bat',
    'update/update_from_release.bat',
    'update/update_sd_trainer.bat',
)
LAB_CORE = 'qwen21_lab/ComfyUI'
CODE_DIRECTORY_EXCEPTIONS = {LAB_CORE + '/comfy_api/input'}
PUBLIC_JSON_PREFIXES = (
    LAB_CORE + '/comfy/', LAB_CORE + '/blueprints/',
    TRAINER + '/vendor/sd-scripts/configs/',
    TRAINER + '/mikazuki/hook/', TRAINER + '/mikazuki/dataset-tag-editor/javascript/',
    'ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite/video_formats/',
    'ComfyUI/custom_nodes/ComfyUI_Custom_Nodes_AlekPet/web_alekpet_nodes/assets/painternode/brushes/',
    'ComfyUI/custom_nodes/ComfyUI_Custom_Nodes_AlekPet/web_alekpet_nodes/assets/painternode/json/',
    'ComfyUI/custom_nodes/ComfyUI-LTXVideo/gemma_configs/',
    'ComfyUI/custom_nodes/ComfyUI-LTXVideo/presets/',
    'ComfyUI/custom_nodes/ComfyUI-WanVideoWrapper/configs/',
)
PUBLIC_JSON_PATHS.update({
    'ComfyUI/custom_nodes/ComfyUI_Custom_Nodes_AlekPet/DeepTranslatorNode/detect_languages_list.json',
    *(TRAINER + suffix for suffix in ('/scripts/dev/finetune/blip/med_config.json',
                                      '/scripts/stable/finetune/blip/med_config.json',
                                      '/vendor/sd-scripts/finetune/blip/med_config.json')),
    *('ComfyUI/custom_nodes/ComfyUI-Manager/' + filename
      for filename in ('alter-list.json', 'custom-node-list.json', 'extension-node-map.json',
                       'model-list.json', 'extras.json')),
})
TOKENIZER_TEXT_PREFIXES = (LAB_CORE + '/comfy/', TRAINER + '/vendor/sd-scripts/configs/')
FORGE_TREES = {
    'anima_lora_forge': {'anima_lora_forge', 'tests', 'tools', 'templates'},
    'character_lora_forge': {'character_forge', 'tests', 'tools', 'templates'},
}
PRIVATE_FILES = {'runtime.json', 'server.json', 'extra_model_paths.yaml', 'run.lock',
                 'STATE.json', 'EXECUTION_STATE.json', 'CONTINUATION.txt'}
ROOT_SOURCE_NAMES = {'_img1.py', '_t3.py', 'qwen_direct_test.py'}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def linked(path):
    try:
        return is_link(path) or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except OSError:
        return True


def safe_unlinked(root, relative):
    path = root
    for part in portable_parts(relative):
        path = path / part
        if linked(path) and (path.exists() or path.is_symlink()):
            raise ValueError('Linked source or destination is not imported')
    return safe_path(root, relative)


def selected_roots(runtime):
    """Explicit owner trees; no before/backup/runs/character-data broad imports."""
    roots = []
    # Never recurse over production models or trainer configuration data.
    # The shared exact paths are discoverable before any manifest registration.
    for relative in sorted(EXACT_SOURCE_SUPPORT_FILES):
        file = exact_support_source(runtime, relative)
        if file is not None:
            roots.append((file, False))
    for prefix, children in FORGE_TREES.items():
        base = runtime / prefix
        if not base.is_dir():
            continue
        roots.extend((file, False) for file in base.iterdir() if file.is_file() or file.is_symlink())
        roots.extend((base / name, True) for name in sorted(children) if (base / name).exists())
    # remote_llm_guard and its root launchers have a separate credential-aware
    # migration owner. They are deliberately not raw-byte import candidates.
    for prefix in ('scripts',):
        if (runtime / prefix).exists():
            roots.append((runtime / prefix, True))
    for prefix in ('tools', 'tools/llama.cpp', 'qwen21_lab'):
        base = runtime / prefix
        if base.is_dir():
            roots.extend((file, False) for file in base.iterdir() if file.is_file() or file.is_symlink())
    for prefix in ('qwen21_lab/workflows_api', TRAINER, LAB_CORE):
        if (runtime / prefix).exists():
            roots.append((runtime / prefix, True))
    # Reviewed portable wrappers live outside the inner trainer source tree.
    # Select files, never recurse over the package root, update/ or environments.
    portable = (runtime / TRAINER).parent
    for name in TRAINER_PORTABLE_FILES:
        file = portable / name
        if file.is_file() or file.is_symlink():
            roots.append((file, False))
    plugins = runtime / 'ComfyUI/custom_nodes'
    if plugins.is_dir():
        roots.extend((runtime / relative, False) for relative in sorted(reviewed_plugin_sources())
                     if (runtime / relative).is_file() and Path(relative).parent.as_posix() == 'ComfyUI/custom_nodes')
        for plugin in plugins.iterdir():
            if plugin.is_dir() and not plugin.name.startswith('.') and '.disabled' not in plugin.name.casefold() and 'backup' not in plugin.name.casefold() and plugin.name != '__pycache__':
                roots.append((plugin, True))
    roots.extend((runtime / name, False) for name in sorted(ROOT_SOURCE_NAMES) if (runtime / name).exists())
    return roots


def paths(runtime):
    yielded = set()
    for root, recurse in selected_roots(runtime):
        relative = root.relative_to(runtime).as_posix()
        if relative in yielded:
            continue
        if linked(root):
            yielded.add(relative)
            yield root, 'linked_path_not_followed'
            continue
        if not recurse:
            yielded.add(relative)
            yield root, None
            continue
        for directory, folders, files in os.walk(root, followlinks=False):
            retained = []
            for name in sorted(folders):
                path = Path(directory, name)
                rel = path.relative_to(runtime).as_posix()
                if linked(path):
                    yield path, 'linked_path_not_followed'
                elif (name in PRUNE and rel not in CODE_DIRECTORY_EXCEPTIONS) or name.startswith('.disabled') or any(term in name.casefold() for term in ('.backup', '.before-', '.before_', '.disabled')):
                    yield path, 'generated_private_or_backup_directory'
                elif Path(directory) == runtime / TRAINER / 'config' and name not in {'presets', 'anima_fast_environment'}:
                    yield path, 'trainer_runtime_configuration_directory'
                else:
                    retained.append(name)
            folders[:] = retained
            for name in sorted(files):
                path = Path(directory, name)
                rel = path.relative_to(runtime).as_posix()
                if rel not in yielded:
                    yielded.add(rel)
                    yield path, 'linked_path_not_followed' if linked(path) else None


def rejection(relative):
    try:
        portable_parts(relative)
    except ValueError:
        return 'unsafe_portable_relative_path'
    path = Path(relative)
    if private_config(relative) or blocked_path('snapshot/' + payload_relative(relative)) or path.name in PRIVATE_FILES:
        return 'private_configuration_or_external_payload'
    lower = path.name.casefold()
    if any(marker in lower for marker in ('.backup', '.before-', '.before_', '.bak', '.disabled')):
        return 'historical_backup_file'
    if relative in EXACT_SOURCE_SUPPORT_FILES or relative in REVIEWED_SUPPORT_FILES or relative in reviewed_plugin_sources() or source_license_name(path.name):
        return None
    if path.suffix.lower() == '.json':
        if relative in PUBLIC_JSON_PATHS or path.name in PUBLIC_JSON_NAMES or relative.startswith(PUBLIC_JSON_PREFIXES):
            return None
        # Translation dictionaries are data, but shipped UI source rather than
        # provider configuration; they still receive the full credential scan.
        if '/locales/' in relative and path.name in {'nodeDefs.json', 'settings.json', 'main.json'}:
            return None
        if relative.startswith('ComfyUI/custom_nodes/ComfyUI-Manager/node_db/') and path.name in {'alter-list.json', 'custom-node-list.json', 'extension-node-map.json', 'model-list.json'}:
            return None
        return 'json_requires_explicit_public_source_review'
    if path.suffix.lower() in {'.yaml', '.yml'}:
        return None if '/.github/' in relative or relative == LAB_CORE + '/openapi.yaml' else 'yaml_requires_explicit_public_source_review'
    if path.suffix.lower() == '.txt':
        if relative.startswith(TOKENIZER_TEXT_PREFIXES) and path.name in {'merges.txt', 'vocab.txt'}:
            return None
        return None if path.name in SPECIAL or re.match(r'(?i)(?:readme|license|copying|notice|requirements|constraints|version)(?:[._-]|$)', path.name) else 'text_data_not_source_allowlist'
    if relative == LAB_CORE + '/comfy/text_encoders/t5_pile_tokenizer/tokenizer.model':
        return None
    if path.suffix.lower() in SOURCE_SUFFIXES or path.name in SPECIAL:
        return None
    return 'not_a_source_allowlist_extension'


def content_rules(file):
    scanner = StreamScanner()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            scanner.feed(block)
    return sorted(scanner.findings)


def content_review(file, relative, sha256):
    rules = content_rules(file)
    if not rules:
        return rules, None
    full = 'snapshot/' + payload_relative(relative)
    # Reuse the shared gate's exact, reviewed content identities. A directory
    # name or broad "test" classification never exempts new content.
    fixture_reason = security_guard.REVIEWED_FIXTURES.get(sha256)
    fixture_suffix = security_guard.FIXTURE_ENDS.get(sha256)
    if fixture_reason and fixture_suffix and full.endswith(fixture_suffix):
        return [], {'sha256': sha256, 'reason': fixture_reason, 'matched_rules': rules}
    return rules, None


def plan(runtime, repo=REPO):
    runtime, repo = runtime.resolve(), repo.resolve()
    if runtime == repo or runtime.is_relative_to(repo):
        raise ValueError('Runtime must be outside the main checkout')
    records = []
    for file, path_reason in paths(runtime):
        relative = file.relative_to(runtime).as_posix()
        row = {'source': relative, 'destination': 'snapshot/' + payload_relative(relative)}
        reason = path_reason or rejection(relative)
        if reason:
            row.update({'status': 'excluded', 'reason': reason})
            records.append(row)
            continue
        safe_unlinked(runtime, relative)
        size = file.stat().st_size
        row['bytes'] = size
        if size > MAX_SOURCE:
            row.update({'status': 'excluded', 'reason': 'source_over_50_mib'})
            records.append(row)
            continue
        row['source_sha256'] = digest(file)
        target = safe_unlinked(repo, row['destination'])
        if target.exists():
            row['target_sha256'] = digest(target) if target.is_file() else None
            row['status'] = 'existing_identical_skip' if row['target_sha256'] == row['source_sha256'] else 'existing_different_skip'
        else:
            rules, reviewed = content_review(file, relative, row['source_sha256'])
            if reviewed:
                row['reviewed_content'] = reviewed
            if rules:
                row.update({'status': 'security_quarantine', 'rules': rules})
            else:
                row['status'] = 'new_source'
        if digest(file) != row['source_sha256']:
            raise RuntimeError('Runtime source changed during plan: ' + relative)
        records.append(row)
    records.sort(key=lambda item: item['source'])
    summary = {}
    for row in records:
        group = row['source'].split('/')[0]
        if row['source'].startswith('ComfyUI/custom_nodes/'):
            group = '/'.join(row['source'].split('/')[:3])
        counts = summary.setdefault(group, {})
        counts[row['status']] = counts.get(row['status'], 0) + 1
        if row['status'] == 'new_source':
            counts['new_bytes'] = counts.get('new_bytes', 0) + row['bytes']
    result = {'schema': 1, 'time': now(), 'mode': 'NEW_PATHS_ONLY_SOURCE_IMPORT',
              'runtime_root': str(runtime), 'repo_root': str(repo), 'summary': summary, 'records': records,
              'new_files': sum(row['status'] == 'new_source' for row in records),
              'new_bytes': sum(row.get('bytes', 0) for row in records if row['status'] == 'new_source'),
              'production_modified': False, 'existing_main_files_modified': False}
    result['review_sha256'] = canonical_hash(result)
    return result


def apply_plan(review, expected_review, repo=REPO):
    bound = dict(review)
    recorded_hash = bound.pop('review_sha256', None)
    if expected_review != recorded_hash or canonical_hash(bound) != expected_review:
        raise ValueError('Plan review hash is missing, stale or modified')
    repo = repo.resolve()
    runtime = Path(review['runtime_root']).resolve()
    if review['repo_root'] != str(repo) or runtime == repo or runtime.is_relative_to(repo):
        raise ValueError('Plan belongs to another repository or unsafe runtime')
    pending = [row for row in review['records'] if row['status'] == 'new_source']
    allowed = {file.relative_to(runtime).as_posix() for file, reason in paths(runtime) if not reason}
    names = set()
    # Preflight every source and target before creating any file.
    for row in pending:
        source = safe_unlinked(runtime, row['source'])
        if row['source'] not in allowed or rejection(row['source']) or row['destination'] != 'snapshot/' + payload_relative(row['source']):
            raise ValueError('Plan contains an unapproved source mapping')
        key = row['destination'].casefold()
        if key in names:
            raise ValueError('Duplicate import target')
        names.add(key)
        target = safe_unlinked(repo, row['destination'])
        if target.exists():
            raise FileExistsError('Main source appeared after review; import never overwrites: ' + row['source'])
        if source.stat().st_size > MAX_SOURCE or digest(source) != row['source_sha256'] or content_review(source, row['source'], row['source_sha256'])[0]:
            raise RuntimeError('Source drift or credential gate failed: ' + row['source'])
    copied = []
    for row in pending:
        source = safe_unlinked(runtime, row['source'])
        target = safe_unlinked(repo, row['destination'])
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['source_sha256']:
            raise RuntimeError('Source changed after import preflight: ' + row['source'])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
        if digest(target) != row['source_sha256'] or digest(source) != row['source_sha256']:
            raise RuntimeError('Import verification failed: ' + row['source'])
        copied.append({'source': row['source'], 'path': row['destination'], 'sha256': row['source_sha256'], 'bytes': len(data)})
    return {'schema': 1, 'time': now(), 'review_sha256': expected_review, 'copied': copied,
            'files': len(copied), 'bytes': sum(row['bytes'] for row in copied), 'production_modified': False,
            'existing_main_files_modified': False, 'sealed': False, 'committed': False, 'deployed': False}


def report_path(name, repo=REPO):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*\.json', name):
        raise ValueError('Report name must be a simple JSON filename')
    return safe_unlinked(repo, 'local/workspace-consolidation/' + name)


def save_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def public_summary(review, receipts):
    """Publish source identities, never machine paths, private state or secrets."""
    files = []
    for receipt in receipts:
        files.extend({key: item[key] for key in ('source', 'path', 'sha256', 'bytes')}
                     for item in receipt['copied'])
    if len({item['path'].casefold() for item in files}) != len(files):
        raise ValueError('Public import summary has duplicate source identities')
    excluded = {}
    for row in review['records']:
        if row['status'] in {'excluded', 'security_quarantine'}:
            reason = row.get('reason', 'credential_gate_quarantine')
            excluded[reason] = excluded.get(reason, 0) + 1
    return {
        'schema': 1, 'purpose': 'Current installed source consolidation into the sole maintenance Git',
        'mode': 'NEW_PATHS_ONLY_SOURCE_IMPORT',
        'review_sha256': sorted({item['review_sha256'] for item in receipts}),
        'files': sorted(files, key=lambda item: item['path']),
        'file_count': len(files), 'bytes': sum(item['bytes'] for item in files),
        'ownership': {
            'authority': 'snapshot/runtime/<source relative path>',
            'installed_plugins': 'Captured does not mean enabled; production plugin whitelist is unchanged.',
            'workbench_modules': 'Unified workbench modules remain authoritative; outer shims are not a second development copy.',
            'anima_lora_forge': 'Forge and current on-disk trainer source, without restoring upstream deletions.',
            'character_lora_forge': 'Dataset maintenance code only; character projects, review outputs and media stay external.',
            'qwen21_lab': 'Independent lab launcher, actual current core and API graphs; not the production service.',
            'remote_llm_guard': 'Handled by separate credential-aware migration; raw launchers not copied by this importer.',
        },
        'excluded_reason_counts': dict(sorted(excluded.items())),
        'external_boundary': [
            'Model weights, training datasets, previews and generated media',
            'Python/CUDA environments, node_modules, compiled service binaries and caches',
            'Credential-bearing files, runtime state, user databases and unreviewed live configuration',
            'Historical benchmark/backups, old Git metadata and raw private archives',
            'Unreviewed JSON/YAML/text fixtures, example graphs and non-source binary assets remain in the private exclusion inventory',
        ],
        'existing_main_files_modified': False, 'production_modified': False,
        'sealed_by_importer': False, 'committed_by_importer': False, 'deployed': False,
        'acceptance_boundary': 'Byte identity and isolated import-tool tests only; no cold start, training or GPU inference acceptance.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    planner = commands.add_parser('plan')
    planner.add_argument('--runtime', type=Path, required=True)
    planner.add_argument('--report', default='source-import-plan.json')
    apply = commands.add_parser('apply')
    apply.add_argument('--plan', default='source-import-plan.json')
    apply.add_argument('--review-sha256', required=True)
    apply.add_argument('--report', default='source-import-receipt.json')
    public = commands.add_parser('public-summary')
    public.add_argument('--plan', required=True)
    public.add_argument('--receipt', action='append', required=True)
    public.add_argument('--output', default='workspace-source-import.json')
    args = parser.parse_args()
    if args.command == 'plan':
        result = plan(args.runtime)
        save_new(report_path(args.report), result)
        print(json.dumps({key: result[key] for key in ('new_files', 'new_bytes', 'summary', 'review_sha256')}, ensure_ascii=False, indent=2))
    elif args.command == 'apply':
        receipt_path = report_path(args.report)
        if receipt_path.exists():
            raise FileExistsError('Receipt already exists')
        result = apply_plan(json.loads(report_path(args.plan).read_text(encoding='utf-8')), args.review_sha256)
        save_new(receipt_path, result)
        print(json.dumps({key: result[key] for key in ('files', 'bytes', 'production_modified', 'existing_main_files_modified', 'sealed', 'deployed')}))
    else:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*\.json', args.output):
            raise ValueError('Public report name must be a simple JSON filename')
        review = json.loads(report_path(args.plan).read_text(encoding='utf-8'))
        receipts = [json.loads(report_path(name).read_text(encoding='utf-8')) for name in args.receipt]
        result = public_summary(review, receipts)
        save_new(safe_unlinked(REPO, 'governance/' + args.output), result)
        print(json.dumps({key: result[key] for key in ('file_count', 'bytes', 'deployed')}))


if __name__ == '__main__':
    main()
