"""捕获、验证和离线还原主仓管理的源码与资料。

capture 只读运行区并写入新候选；materialize 只向新目录还原，不部署或启动服务。
详见 docs/SNAPSHOT.md 与 docs/RESTORE.md。
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from security_guard import blocked_path
from library_sql import ITERDUMP, GALLERY_FTS5, FORMATS, iter_sql, table_counts, restore_sql, summary as sql_summary

REPO = Path(__file__).resolve().parents[1]
WB = 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'
LIBRARY = WB + '/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data'
LIBRARY_DATABASES = ('userdatas_zh_CN_danbooru.db', 'userdatas_zh_CN_history.db', 'userdatas_zh_CN_tags.db')
GALLERY_DATABASE = WB + '/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/py/shared/data/tags_cache.db'
RANDOM_TEMPLATES = tuple(WB + '/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/random_tag/' + name
                         for name in ('20260606_203538.json', '20260606_205040.json'))
LEGACY_SELECTOR_FILES = ('ComfyUI/custom_nodes/nsfwprompt/PromptSelector_user_logic_history_extra_sorted.json',
                         'ComfyUI/custom_nodes/nsfwprompt/promptselector_edit_log.jsonl')
WEIGHTS = {'.safetensors', '.ckpt', '.pt', '.pth', '.onnx', '.gguf', '.bin', '.engine'}
TEXT = {'.py', '.pyi', '.mako', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts', '.patch', '.vue', '.svelte', '.css', '.scss', '.sass', '.less', '.html', '.json', '.jsonl', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.md', '.rst', '.txt', '.csv', '.tsv', '.sql', '.xml', '.sh', '.ps1', '.psm1', '.bat', '.cmd', '.example', '.lock', '.map', '.in', '.c', '.cc', '.cpp', '.h', '.hpp', '.cu', '.cuh', '.glsl', '.frag', '.vert'}
ASSETS = {'.png', '.jpg', '.jpeg', '.webp', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.mp3', '.webmanifest', '.gz'}
SKIP_DIRS = {'.git', '.hg', '.svn', '__pycache__', 'node_modules', '.cache', '.pytest_cache', '.hypothesis', '.agents', '.benchmarks', '.omo', '.specs', '.venv', 'venv', 'logs', 'temp', 'output', 'input', 'preview', 'preview_thumbnails', 'user_data', 'lora_userdatas', 'loras_userdatas', 'translate_userdatas', 'prompt_selector_data_backups', 'random_tag'}
PRIVATE_NAME = re.compile(r'^(?:\.env(?:\..*)?|(?:.*[_-])?(?:credentials|secrets|cookies|accounts|auth|tokens|providers|settings)(?:\.(?:json|yaml|yml|ini|toml))|config\.(?:json|yaml|yml|ini))$', re.I)
PRIVATE_PATHS = {
    WB + '/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/init.json',
    'ComfyUI/custom_nodes/TB_Multi_API_Caption_ConfigPage_V17_ProviderAdapters/models_cache.json',
}
PUBLIC_CONFIG_PATHS = {
    'ComfyUI/.github/ISSUE_TEMPLATE/config.yml',
    'ComfyUI/comfy/text_encoders/byt5_tokenizer/added_tokens.json',
    'qwen21_lab/ComfyUI/comfy/text_encoders/byt5_tokenizer/added_tokens.json',
    'ComfyUI/custom_nodes/comfyui_controlnet_aux/src/custom_mesh_graphormer/modeling/bert/bert-base-uncased/config.json',
    'anima_lora_forge/vendor/sd-trainer/SD-Trainer/vendor/sd-scripts/configs/qwen3_06b/config.json',
    'anima_lora_forge/vendor/sd-trainer/SD-Trainer/vendor/sd-scripts/configs/t5_old/config.json',
    *('ComfyUI/custom_nodes/comfyui-easy-use/locales/' + language + '/settings.json' for language in ('en', 'fr', 'ja', 'ko', 'ru', 'zh')),
}
# Shipped defaults and executable web support are source dependencies, not
# arbitrary .default/.wasm payloads. Path approval never waives content scanning.
REVIEWED_SUPPORT_FILES = frozenset({
    'ComfyUI/custom_nodes/rgthree-comfy/rgthree_config.json.default',
    *('ComfyUI/custom_nodes/rgthree-comfy/' + tree + '/lib/' + filename
      for tree in ('src_web', 'web')
      for filename in ('tree-sitter.wasm', 'tree-sitter-python.wasm')),
    *('anima_lora_forge/vendor/sd-trainer/SD-Trainer/scripts/' + relative
      for relative in ('dev/COMMIT_ID', 'stable/COMMIT_ID', 'portable/UPDATER_VERSION')),
})
SOURCE_SPECIAL_NAMES = frozenset({
    'LICENSE', 'COPYING', 'NOTICE', 'Dockerfile', '.gitignore', '.gitattributes',
    '.gitattributes.upstream', 'CODEOWNERS', 'put_blueprints_here', 'VERSION',
    'PORTABLE_BUILD', 'requirements.txt.filtered',
})
TOKENIZER_SOURCE_FILES = frozenset({
    'ComfyUI/comfy/text_encoders/t5_pile_tokenizer/tokenizer.model',
    'qwen21_lab/ComfyUI/comfy/text_encoders/t5_pile_tokenizer/tokenizer.model',
})


def source_license_name(name):
    """Recognize extensionless upstream notices without admitting executables."""
    return bool(re.fullmatch(r'(?:LICENSE|COPYING|NOTICE)(?:[-_][A-Za-z0-9][A-Za-z0-9_-]*)?|THIRD_PARTY_NOTICES', name))


def supported_source_payload(relative):
    """Shared capture/seal type policy; private paths and byte gates stay separate."""
    path = Path(relative)
    return (path.suffix.lower() in TEXT | ASSETS or path.name in SOURCE_SPECIAL_NAMES
            or source_license_name(path.name) or relative in REVIEWED_SUPPORT_FILES
            or relative in TOKENIZER_SOURCE_FILES or relative in reviewed_plugin_sources())


def reviewed_plugin_sources():
    """Exact audited support paths; never approve whole cache/config directories."""
    contract = REPO / 'governance/plugin-support-20261007.json'
    if not contract.is_file():
        return frozenset()
    stat = contract.stat()
    return _reviewed_plugin_sources(contract, stat.st_mtime_ns, stat.st_size)


@functools.lru_cache(maxsize=4)
def _reviewed_plugin_sources(contract, modified, size):
    spec = json.loads(contract.read_text(encoding='utf-8'))
    paths = spec['public_sources']
    for relative in paths:
        portable_parts(relative)
        if not relative.startswith('ComfyUI/custom_nodes/'):
            raise ValueError('Reviewed plugin source is outside its owner tree')
    if len(paths) != len(set(paths)):
        raise ValueError('Duplicate reviewed plugin sources')
    return frozenset(paths)

# Reviewed synthetic URL/redaction fixtures. Any edit requires another review.
REVIEWED_SECURITY_FIXTURES = {
    'runtime/' + WB + '/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/tests/test_v53_legacy_security.py': '06d5f2680138c9fa4919fc13afd362fe3c969fe58c1c54d635380fe80181e7a1',
    'runtime/' + WB + '/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/tests/test_v53_ssrf.py': '32a06d3f7d31f43c8d558f6f6223d9b8accf37c832b20181b2f8c5c1ef00c812',
}
TOKEN_PATTERNS = [re.compile(r'sk-(?:proj-)?[A-Za-z0-9_-]{30,}'), re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}'), re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'), re.compile(r'(?i)https?://[^\s/:@]+:[^\s/@]{6,}@')]
ASSIGNMENT = re.compile(r'''(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret|authorization|cookie)["']?\s*[:=]\s*(["'])([^"'\r\n]{16,})\1''')
PLACEHOLDER = re.compile(r'(?i)(?:example|dummy|test|placeholder|your[_ -]|replace|redacted|changeme|xxx|\{\{|\$\{|<.*>)')
CHUNK = 8 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(file):
    result = hashlib.sha256()
    with Path(file).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def database_state(file):
    wal = Path(str(file) + '-wal')
    return {'source_main_sha256': digest(file), 'source_wal_sha256': digest(wal) if wal.exists() else None}


def is_link(path):
    return (path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())
            or (path.exists() and bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)))


def unlinked_source(root, relative):
    """Check the original spelling before resolve can erase linked ancestors."""
    path = root
    for part in portable_parts(relative):
        path = path / part
        if is_link(path):
            raise ValueError('Linked runtime source is not captured: ' + relative)
    return safe_path(root, relative)


def private_config(relative):
    return relative in PRIVATE_PATHS or (relative not in PUBLIC_CONFIG_PATHS and relative not in reviewed_plugin_sources()
                                        and bool(PRIVATE_NAME.fullmatch(Path(relative).name)))


def payload_relative(source):
    # Nested attributes would override byte-preserving rules on add/clone.
    return 'runtime/' + source + ('.upstream' if Path(source).name == '.gitattributes' else '')


def save(file, data):
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def safe_path(root, relative):
    parts = portable_parts(relative)
    candidate = root.joinpath(*parts).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate == root.resolve():
        raise ValueError('Path escaped target')
    return candidate


def portable_parts(relative):
    """One spelling on Windows and POSIX; reject drive/ADS and alias tricks."""
    if not isinstance(relative, str) or not relative or re.search(r'[\\:*?"<>|\x00-\x1f]', relative):
        raise ValueError('Unsafe portable relative path')
    parts = relative.split('/')
    devices = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
    if any(part in {'', '.', '..'} or part.rstrip(' .') != part or part.split('.')[0].casefold() in devices for part in parts):
        raise ValueError('Unsafe portable relative path')
    return parts


def manifest_path_failures(manifest):
    """Validate ownership before hashing/copying so every target is unique."""
    failures = []
    sources, payloads = {}, {}
    source_parents, payload_parents = set(), set()

    def claim(relative, claims, parents, owner, directory=False, scope='payload'):
        try:
            parts = portable_parts(relative)
        except ValueError:
            failures.append({'path': '<' + owner + '>', 'reason': 'invalid_' + scope + '_path'})
            return False
        key = '/'.join(parts).casefold()
        ancestors = ['/'.join(parts[:index]).casefold() for index in range(1, len(parts))]
        if key in claims:
            failures.append({'path': relative, 'reason': 'duplicate_' + scope + '_path'})
            return False
        if key in parents or any(parent in claims and (not claims[parent][0] or claims[parent][1] != owner) for parent in ancestors):
            failures.append({'path': relative, 'reason': scope + '_path_conflict'})
            return False
        claims[key] = (directory, owner)
        parents.update(ancestors)
        return True

    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list) or not isinstance(manifest.get('metadata_files', []), list):
        return [{'path': 'manifest.json', 'reason': 'invalid_manifest_structure'}]
    claim('manifest.json', payloads, payload_parents, 'reserved-manifest')
    claim('verification.json', payloads, payload_parents, 'reserved-verification')
    claim('RESTORE_RECEIPT.json', sources, source_parents, 'reserved-restore-receipt', scope='source')
    for index, entry in enumerate(manifest['files']):
        owner = 'files[' + str(index) + ']'
        if not isinstance(entry, dict) or not isinstance(entry.get('kind'), str) or entry['kind'] not in {'file', 'chunks', 'sqlite_sql'}:
            failures.append({'path': '<' + owner + '>', 'reason': 'invalid_entry_kind'})
            continue
        kind = entry['kind']
        hash_field = 'sql_sha256' if kind == 'sqlite_sql' else 'sha256'
        if not isinstance(entry.get(hash_field), str) or not re.fullmatch('[0-9a-f]{64}', entry[hash_field]):
            failures.append({'path': '<' + owner + '>', 'reason': 'invalid_entry_hash'})
        source_ok = claim(entry.get('source'), sources, source_parents, owner, scope='source')
        path_ok = claim(entry.get('path'), payloads, payload_parents, owner, directory=kind != 'file')
        if kind == 'sqlite_sql':
            sql_format = entry.get('sql_format', ITERDUMP)
            if not isinstance(sql_format, str) or sql_format not in FORMATS or (sql_format == GALLERY_FTS5 and entry.get('source') != GALLERY_DATABASE):
                failures.append({'path': '<' + owner + '>', 'reason': 'unreviewed_sql_format'})
            if source_ok:
                claim(entry['source'] + '.restore.sql', sources, source_parents, owner + '-sql-sidecar', scope='source')
            if not isinstance(entry.get('tables'), dict) or any(not isinstance(table, str) or not isinstance(count, int) or count < 0 for table, count in entry.get('tables', {}).items()):
                failures.append({'path': '<' + owner + '>', 'reason': 'invalid_sql_table_counts'})
        if kind == 'file':
            continue
        if not isinstance(entry.get('parts'), list):
            failures.append({'path': '<' + owner + '>', 'reason': 'invalid_parts_list'})
            continue
        for part_index, part in enumerate(entry['parts']):
            if not isinstance(part, dict) or not isinstance(part.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', part['sha256']):
                failures.append({'path': '<' + owner + '.parts[' + str(part_index) + ']>', 'reason': 'invalid_part_entry'})
                continue
            try:
                portable_parts(part.get('path'))
            except ValueError:
                failures.append({'path': '<' + owner + '.parts[' + str(part_index) + ']>', 'reason': 'invalid_part_path'})
                continue
            if path_ok:
                claim(entry['path'] + '/' + part['path'], payloads, payload_parents, owner)
    for index, entry in enumerate(manifest.get('metadata_files', [])):
        owner = 'metadata_files[' + str(index) + ']'
        if not isinstance(entry, dict) or not isinstance(entry.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', entry['sha256']):
            failures.append({'path': '<' + owner + '>', 'reason': 'invalid_metadata_entry'})
            continue
        claim(entry.get('path'), payloads, payload_parents, owner)
    return failures


def walk(root, skip=SKIP_DIRS, skip_top=()):
    for folder, dirs, files in os.walk(root, followlinks=False):
        excluded = skip | set(skip_top) if Path(folder) == root else skip
        dirs[:] = sorted(d for d in dirs if d not in excluded and not is_link(Path(folder, d)))
        for name in sorted(files):
            file = Path(folder, name)
            if not is_link(file):
                yield file


def git(path, *args):
    result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    return result.stdout.strip() if result.returncode == 0 else None


def upstream(path, root):
    own_git = (path / '.git').exists()
    url = git(path, 'remote', 'get-url', 'origin') if own_git else None
    if url:
        url = re.sub(r'(https?://)[^/@]+@', r'\1', url).split('?')[0].split('#')[0]
    result = {'path': path.relative_to(root).as_posix(), 'own_git': own_git,
            'head': git(path, 'rev-parse', 'HEAD') if own_git else None,
            'upstream': url, 'tracked_dirty': bool(git(path, 'status', '--porcelain', '--untracked-files=no')) if own_git else None}
    registry = REPO / 'governance/retired-git.json'
    if not own_git and registry.is_file():
        for entry in json.loads(registry.read_text(encoding='utf-8'))['repositories']:
            if entry['runtime_path'] == result['path']:
                result.update(git_metadata_retired=True, recorded_original_head=entry.get('original_head'),
                              history_provenance='governance/retired-git.json')
                break
    return result


def health():
    def get(route):
        with urllib.request.urlopen('http://127.0.0.1:8188' + route, timeout=10) as response:
            return json.load(response)
    queue = get('/queue')
    if queue['queue_running'] or queue['queue_pending']:
        raise RuntimeError('Queue busy; capture was not started/completed')
    status = get('/unified-workbench/status')
    if status.get('degraded') or not all(m['ready'] for m in status['modules']):
        raise RuntimeError('Workbench not ready')
    import psutil
    listeners = sorted({c.pid for c in psutil.net_connections(kind='tcp') if c.status == psutil.CONN_LISTEN and c.laddr.port == 8188})
    return {'queue': {'running': 0, 'pending': 0}, 'listeners': [{'pid': pid, 'created': psutil.Process(pid).create_time()} for pid in listeners], 'modules': status['modules']}


def selected_sources(root, registered_manifest=None):
    selected = {}
    omitted = []
    def offer(file):
        rel = file.relative_to(root).as_posix()
        if rel in LEGACY_SELECTOR_FILES:
            return  # Reviewed mutable text has one owner: reversible library exports.
        name = file.name.lower()
        if private_config(rel) or blocked_path('snapshot/runtime/' + rel):
            omitted.append({'path': rel, 'reason': 'private_or_machine_config'}); return
        if any(word in name for word in ['.backup', '.before-', '.before_', '.bak', '.disabled']) or file.suffix.lower() in WEIGHTS:
            return
        if not supported_source_payload(rel):
            return
        if file.stat().st_size > 48 * 1024 * 1024:
            omitted.append({'path': rel, 'reason': 'large_optional_source_asset', 'bytes': file.stat().st_size}); return
        selected[rel] = file
    core = root / 'ComfyUI'
    for file in walk(core, SKIP_DIRS - {'input', 'output', 'temp'}, {'custom_nodes', 'models', 'user', 'web', 'input', 'output', 'temp'}):
        offer(file)
    # Frontend extensions here are distinct from the Python-package frontend distribution.
    for file in walk(core / 'web'):
        offer(file)
    profiles = json.loads((root / 'production_tools/profiles.json').read_text(encoding='utf-8-sig'))
    plugins = sorted(set(profiles['production']))
    for name in plugins:
        plugin = core / 'custom_nodes' / name
        if not plugin.is_dir():
            raise FileNotFoundError(plugin)
        for file in walk(plugin):
            offer(file)
    # Previously omitted shipped support for installed non-production plugins
    # and the top-level websocket node uses exact reviewed paths, not a blanket
    # import of every plugin cache or private configuration.
    for relative in sorted(reviewed_plugin_sources()):
        file = unlinked_source(root, relative)
        if file.is_file():
            offer(file)
    # Small runtime-owned selector dictionaries may live outside user_data.
    for folder in ['production_tools', 'benchmark_reports/source_update_flow']:
        for file in walk(root / folder, SKIP_DIRS | {'state', 'templates'}):
            offer(file)
    for pattern in ['启动_ComfyUI_*.cmd', '停止_ComfyUI_*.cmd']:
        for file in root.glob(pattern):
            offer(file)
    for file in (root / 'production_tools/templates').glob('*.json'):
        selected[file.relative_to(root).as_posix()] = file
    for file in (root / 'ComfyUI/user/default/workflows').glob('*.json'):
        selected[file.relative_to(root).as_posix()] = file
    for name in ['promptselector_user_overrides.json', 'promptselector_builder_config.json', 'promptselector_local_sort_review_builder.py', 'NSFWPromptSelector_LocalMerged.py', 'suozhang_html_unfiltered_importer.py']:
        file = root / LIBRARY / name
        if file.exists():
            offer(file)
    # Source additions accepted into the single main checkout remain in scope
    # on later accepted-deployment captures, even outside the production profile.
    registered_manifest = registered_manifest or REPO / 'snapshot/manifest.json'
    if registered_manifest.is_file():
        registered = json.loads(registered_manifest.read_text(encoding='utf-8'))
        if manifest_path_failures(registered):
            raise ValueError('Registered main source manifest is invalid')
        for entry in registered['files']:
            if entry['kind'] != 'file':
                continue
            file = unlinked_source(root, entry['source'])
            if file.is_file():
                offer(file)
    return selected, omitted, plugins


def suspects(text):
    found = []
    for pattern in TOKEN_PATTERNS:
        if any(not PLACEHOLDER.search(m.group()) for m in pattern.finditer(text)):
            found.append('credential_pattern')
    for match in ASSIGNMENT.finditer(text):
        value = match.group(2)
        if not PLACEHOLDER.search(value) and not re.search(r'[{}<>\s]', value) and re.search('[a-zA-Z]', value) and re.search('[0-9]', value):
            found.append('literal_credential_assignment')
    return sorted(set(found))


def scan(file):
    if Path(file).suffix.lower() not in TEXT | {'.part', '.svg'} and Path(file).name not in {'LICENSE', 'COPYING', 'NOTICE'}:
        return []
    found = set()
    with Path(file).open('r', encoding='utf-8-sig', errors='replace') as stream:
        tail = ''
        while block := stream.read(1024 * 1024):
            found.update(suspects(tail + block))
            tail = block[-4096:]
    return sorted(found)


def split_file(source, out):
    out.mkdir(parents=True, exist_ok=False)
    parts = []
    with Path(source).open('rb') as stream:
        number = 0
        while block := stream.read(CHUNK):
            # Split at a nearby newline where possible without changing a single byte.
            block += stream.readline(1024 * 1024)
            file = out / f'{number:05d}.part'
            file.write_bytes(block)
            parts.append({'path': file.name, 'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
            number += 1
    return parts


def capture(root, out, offline=False):
    root, out = root.resolve(), out.resolve()
    if out.exists():
        raise FileExistsError('Destination must be new; existing snapshots are never overwritten')
    if root == out or out.is_relative_to(root / 'ComfyUI'):
        raise ValueError('Capture must not target the running ComfyUI tree')
    selected, omitted, plugins = selected_sources(root)
    runtime_before = None if offline else health()
    out.mkdir(parents=True)
    entries = []
    print('Capturing runtime source and workflows...', flush=True)
    for rel, file in sorted(selected.items()):
        target = safe_path(out, payload_relative(rel))
        target.parent.mkdir(parents=True, exist_ok=True)
        before = digest(file)
        shutil.copyfile(file, target)
        if digest(target) != before or digest(file) != before:
            raise RuntimeError('Source changed during capture: ' + rel)
        entries.append({'source': rel, 'path': target.relative_to(out).as_posix(), 'sha256': before, 'bytes': target.stat().st_size, 'kind': 'file'})
    print('Capturing authoritative library bytes in reversible chunks...', flush=True)
    library = root / LIBRARY
    text_exports = [(library / 'prompt_selector' / name, 'library/json/' + name)
                    for name in ['data.json', 'default.json', 'semantic_projection.json', 'shared_pairs.json', 'shared_sync_log.json', 'STORE_OWNER.txt']]
    text_exports.extend((root / relative, 'library/random_templates/' + Path(relative).name) for relative in RANDOM_TEMPLATES)
    text_exports.extend((root / relative, 'library/legacy_selector/' + Path(relative).name) for relative in LEGACY_SELECTOR_FILES)
    unreviewed_templates = {file.relative_to(root).as_posix() for file in (library.parent / 'random_tag').glob('*.json')} - set(RANDOM_TEMPLATES)
    if unreviewed_templates:
        raise ValueError('Review new random templates before capture: ' + ', '.join(sorted(unreviewed_templates)))
    for source, payload_path in text_exports:
        source = unlinked_source(root, source.relative_to(root).as_posix())
        if not source.exists():
            raise FileNotFoundError(source)
        before = digest(source)
        destination = out / payload_path
        parts = split_file(source, destination)
        if digest(source) != before:
            raise RuntimeError('Library changed during capture: ' + source.name)
        entries.append({'source': source.relative_to(root).as_posix(), 'path': destination.relative_to(out).as_posix(), 'kind': 'chunks', 'sha256': before, 'bytes': source.stat().st_size, 'parts': parts})
    print('Online-consistent SQLite backups and SQL exports...', flush=True)
    for source in sorted(library.glob('*.db')):
        if source.name not in LIBRARY_DATABASES:
            omitted.append({'path': source.relative_to(root).as_posix(), 'reason': 'database_not_in_reviewed_contract'})
    database_exports = [(library / name, 'library/sql/' + name, ITERDUMP) for name in LIBRARY_DATABASES]
    database_exports.append((root / GALLERY_DATABASE, 'library/sql/gallery_tags_cache.db', GALLERY_FTS5))
    for source, payload_path, sql_format in database_exports:
        source = unlinked_source(root, source.relative_to(root).as_posix())
        if not source.is_file():
            raise FileNotFoundError(source)
        before = database_state(source)
        with tempfile.TemporaryDirectory(prefix='comfyui-sql-') as temp:
            backup = Path(temp) / source.name
            src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
            target = sqlite3.connect(backup)
            try:
                src.backup(target, pages=1024)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('SQLite integrity check failed: ' + source.name)
                dump = Path(temp) / 'dump.sql'
                with dump.open('w', encoding='utf-8', newline='\n') as stream:
                    for line in iter_sql(target, sql_format, allow_stale_fts=sql_format == GALLERY_FTS5):
                        stream.write(line + '\n')
                tables = table_counts(target, sql_format, allow_stale_fts=sql_format == GALLERY_FTS5)
                fts_state = ({key: value for key, value in sql_summary(target, sql_format, allow_stale_fts=True).items()
                              if key.startswith('fts_')} if sql_format == GALLERY_FTS5 else {})
            finally:
                target.close(); src.close()
            destination = out / payload_path
            parts = split_file(dump, destination)
            entries.append({'source': source.relative_to(root).as_posix(), 'path': destination.relative_to(out).as_posix(), 'kind': 'sqlite_sql', 'sql_format': sql_format, **fts_state, **before, 'sql_sha256': digest(dump), 'sql_bytes': dump.stat().st_size, 'tables': tables, 'parts': parts})
        if database_state(source) != before:
            raise RuntimeError('Database main/WAL changed during capture; retry a quiet interval')
    print('Recording models and external library media (no weight/media copying)...', flush=True)
    inventory = out / 'inventory'; inventory.mkdir()
    model_files = []
    for source in walk(root / 'ComfyUI/models', {'.git', '__pycache__', '.cache'}):
        if source.suffix.lower() in WEIGHTS:
            stat = source.stat()
            model_files.append({'path': source.relative_to(root).as_posix(), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sha256': None, 'verification': 'path_size_mtime_only'})
    for name in plugins:
        for source in walk(root / 'ComfyUI/custom_nodes' / name):
            if source.suffix.lower() in WEIGHTS:
                stat = source.stat()
                model_files.append({'path': source.relative_to(root).as_posix(), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sha256': None, 'verification': 'path_size_mtime_only'})
    save(inventory / 'models.json', {'files': model_files, 'count': len(model_files), 'bytes': sum(f['bytes'] for f in model_files), 'weights_in_git': False, 'full_weight_hashes_computed': False})
    media_count = media_bytes = 0
    with (inventory / 'library_media.jsonl').open('w', encoding='utf-8', newline='\n') as stream:
        for folder in ['preview', 'preview_thumbnails']:
            for source in walk(library / 'prompt_selector' / folder, set()):
                stat = source.stat()
                stream.write(json.dumps({'path': source.relative_to(root).as_posix(), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}, ensure_ascii=False) + '\n')
                media_count += 1; media_bytes += stat.st_size
    save(inventory / 'library_media_summary.json', {'files': media_count, 'bytes': media_bytes, 'media_in_git': False, 'hashes_computed': False})
    all_plugins = [p for p in (root / 'ComfyUI/custom_nodes').iterdir() if p.is_dir() and not p.name.startswith('.') and p.name != '__pycache__']
    save(inventory / 'upstreams.json', {'core': upstream(root / 'ComfyUI', root), 'plugins': [{**upstream(p, root), 'production_profile': p.name in plugins, 'source_captured': any(relative.startswith(p.relative_to(root).as_posix() + '/') for relative in selected)} for p in sorted(all_plugins)]})
    save(inventory / 'excluded_private_configs.json', omitted)
    save(inventory / 'environment.json', {'python': sys.version, 'platform': platform.platform(), 'packages': sorted([{'name':d.metadata.get('Name','unknown'), 'version':d.version} for d in importlib.metadata.distributions()], key=lambda x:x['name'].lower()), 'python_runtime_in_git':False})
    references = []
    for rel, file in sorted(selected.items()):
        if not rel.startswith(('ComfyUI/user/default/workflows/', 'production_tools/templates/')) or file.suffix != '.json':
            continue
        data = json.loads(file.read_text(encoding='utf-8-sig'))
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for item in value: yield from strings(item)
            elif isinstance(value, dict):
                for item in value.values(): yield from strings(item)
        for value in sorted(set(v for v in strings(data) if len(v) < 500 and Path(v).suffix.lower() in WEIGHTS)):
            normalized = value.replace('\\','/').lower()
            matches = [m['path'] for m in model_files if m['path'].lower().endswith('/'+normalized) or Path(m['path']).name.lower()==Path(normalized).name]
            references.append({'workflow':rel,'reference':value,'candidates':matches,'status':'resolved' if len(matches)==1 else 'missing' if not matches else 'ambiguous'})
    save(inventory / 'workflow_models.json', references)
    evidence = out / 'evidence'; evidence.mkdir()
    scope = root / 'benchmark_reports/2026-10-04_part_refinement_pipeline'
    state = json.loads((scope / 'STATE.json').read_text(encoding='utf-8-sig'))
    for key in ['latest_receipt','latest_release_receipt','latest_workflow_release_receipt','latest_inference_receipt']:
        receipt = Path(state[key])
        dest = evidence / receipt.parent.name
        for name in ['FINAL_DELIVERY.json','REPORT.txt']:
            source = receipt.parent / name
            if source.exists():
                dest.mkdir(exist_ok=True); shutil.copyfile(source, dest / name)
    shutil.copyfile(scope / 'STATE.json', evidence / 'production_STATE.json')
    if not offline:
        runtime_after = health()
        if runtime_after != runtime_before:
            raise RuntimeError('Runtime identity/readiness changed during capture')
    else:
        runtime_after = None
    # Guard every captured source again after library export, not only at copy time.
    for entry in entries:
        source = root / entry['source']
        if entry['kind'] == 'sqlite_sql':
            matches = database_state(source) == {key: entry[key] for key in ('source_main_sha256', 'source_wal_sha256')}
        else:
            matches = digest(source) == entry['sha256']
        if not matches:
            raise RuntimeError('Runtime source drifted: ' + entry['source'])
    metadata = [{'path': file.relative_to(out).as_posix(), 'sha256': digest(file), 'bytes': file.stat().st_size} for folder in [inventory, evidence] for file in walk(folder, set())]
    save(out / 'manifest.json', {'schema':1,'created_at':now(),'source_root':str(root),'files':entries,'metadata_files':metadata,'production_plugins':plugins,'runtime_before':runtime_before,'runtime_after':runtime_after,'scope':'Core + production and registered installed plugin sources/support + workflows + six authoritative prompt files + two reviewed random templates + three WeiLin logical SQL databases and Gallery FTS5 dictionary/history; external weights/user media are inventories, not payloads'})
    result = verify(out)
    save(out / 'verification.json', result)
    if not result['pass']:
        raise RuntimeError('Capture verification failed; inspect verification.json')
    print(json.dumps({'captured':str(out), 'files':len(entries), 'plugins':len(plugins), 'models':len(model_files), 'media':media_count, 'pass':True}),flush=True)


def verify(snapshot):
    snapshot = snapshot.resolve()
    manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
    failures = manifest_path_failures(manifest)
    if failures:
        return {'time':now(),'pass':False,'entry_count':len(manifest.get('files', [])) if isinstance(manifest, dict) and isinstance(manifest.get('files'), list) else 0,'failures':failures,'reviewed_security_fixtures':[]}
    expected_paths = {'manifest.json', 'verification.json'}
    reviewed_fixtures = []
    for entry in manifest.get('metadata_files', []):
        expected_paths.add(entry['path'])
        target = safe_path(snapshot, entry['path'])
        if not target.is_file() or digest(target) != entry['sha256']:
            failures.append({'path':entry['path'],'reason':'metadata_hash_mismatch'})
    for entry in manifest['files']:
        target = safe_path(snapshot, entry['path'])
        if entry['kind'] == 'file':
            expected_paths.add(entry['path'])
            if not target.is_file() or digest(target) != entry['sha256']:
                failures.append({'path':entry['path'],'reason':'hash_mismatch'})
        else:
            total = hashlib.sha256()
            for part in entry['parts']:
                file = safe_path(target, part['path'])
                expected_paths.add(file.relative_to(snapshot).as_posix())
                if not file.is_file() or digest(file) != part['sha256']:
                    failures.append({'path':file.relative_to(snapshot).as_posix(),'reason':'part_hash_mismatch'});continue
                total.update(file.read_bytes())
            if total.hexdigest() != entry.get('sha256', entry.get('sql_sha256')):
                failures.append({'path':entry['path'],'reason':'joined_hash_mismatch'})
    for folder, directories, files in os.walk(snapshot, followlinks=False):
        for name in directories + files:
            path = Path(folder, name)
            if is_link(path):
                failures.append({'path': path.relative_to(snapshot).as_posix(), 'reason': 'linked_payload'})
        directories[:] = [name for name in directories if not is_link(Path(folder, name))]
    for file in walk(snapshot, set()):
        relative = file.relative_to(snapshot).as_posix()
        if relative not in expected_paths:
            failures.append({'path': relative, 'reason': 'unlisted_payload'})
        if file.stat().st_size > 50 * 1024 * 1024:
            failures.append({'path':file.relative_to(snapshot).as_posix(),'reason':'git_blob_too_large'})
        if file.suffix.lower() in WEIGHTS | {'.db','.sqlite','.sqlite3','.pem','.key'}:
            failures.append({'path':file.relative_to(snapshot).as_posix(),'reason':'forbidden_payload'})
        if private_config(relative.removeprefix('runtime/')):
            failures.append({'path': relative, 'reason': 'private_config_payload'})
        for reason in blocked_path('snapshot/' + relative):
            failures.append({'path': relative, 'reason': reason})
        if relative in REVIEWED_SECURITY_FIXTURES and REVIEWED_SECURITY_FIXTURES[relative] == digest(file):
            reviewed_fixtures.append({'path': relative, 'sha256': digest(file), 'reason': 'reviewed_synthetic_security_test'})
            continue
        for reason in scan(file):
            failures.append({'path':file.relative_to(snapshot).as_posix(),'reason':reason})
    result={'time':now(),'pass':not failures,'entry_count':len(manifest['files']),'failures':failures,'reviewed_security_fixtures':reviewed_fixtures}
    return result


def materialize(snapshot, destination):
    snapshot, destination = snapshot.resolve(), destination.resolve()
    manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    if destination.exists():
        raise FileExistsError('Restore destination must not exist')
    source_root=Path(manifest['source_root']).resolve()
    if destination == source_root or destination.is_relative_to(source_root / 'ComfyUI') or destination.is_relative_to(snapshot):
        raise ValueError('Refusing live runtime destination')
    result=verify(snapshot)
    if not result['pass']:
        raise RuntimeError('Snapshot failed verification')
    destination.mkdir(parents=True)
    checks=[]
    for entry in manifest['files']:
        target=safe_path(destination,entry['source']);target.parent.mkdir(parents=True,exist_ok=True)
        payload=safe_path(snapshot,entry['path'])
        if entry['kind']=='file':
            with payload.open('rb') as source, target.open('xb') as stream:
                shutil.copyfileobj(source,stream)
        else:
            joined=target if entry['kind']=='chunks' else target.with_suffix(target.suffix+'.restore.sql')
            with joined.open('xb') as stream:
                for part in entry['parts']:
                    with safe_path(payload,part['path']).open('rb') as source:
                        shutil.copyfileobj(source,stream)
            if entry['kind']=='sqlite_sql':
                with target.open('xb'):
                    pass
                with contextlib.closing(sqlite3.connect(target)) as conn, joined.open(encoding='utf-8', newline='') as sql:
                    if entry.get('sql_format', ITERDUMP) == GALLERY_FTS5:
                        restored = restore_sql(conn, sql, GALLERY_FTS5)
                        if restored['tables'] != entry['tables'] or restored['sql_sha256'] != entry['sql_sha256']:
                            raise RuntimeError('Restored Gallery logical content mismatch')
                        checks.append({'path': entry['source'], 'logical_sql_match': True, 'sql_format': GALLERY_FTS5,
                                       'rows': restored['tables'], 'fts_integrity_match': True})
                        continue
                    restored = restore_sql(conn, sql, ITERDUMP)
                    rows = restored['tables']
                    if rows != entry['tables']:
                        raise RuntimeError('Database row count mismatch')
                    if restored['sql_sha256'] != entry['sql_sha256']:
                        raise RuntimeError('Restored logical SQL content mismatch')
                checks.append({'path':entry['source'],'logical_sql_match':True,'rows':rows});continue
        if digest(target)!=entry['sha256']:
            raise RuntimeError('Restored file hash mismatch')
        checks.append({'path':entry['source'],'sha256_match':True})
    receipt={'time':now(),'pass':True,'snapshot_manifest_sha256':digest(snapshot/'manifest.json'),'snapshot_verification':result,'checks':checks,'external_assets_restored':False,'service_started':False}
    save(destination/'RESTORE_RECEIPT.json',receipt)
    print(json.dumps({'materialized':str(destination),'checks':len(checks),'pass':True}),flush=True)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    cap=commands.add_parser('capture');cap.add_argument('--runtime',type=Path,required=True);cap.add_argument('--out',type=Path,required=True);cap.add_argument('--offline',action='store_true')
    ver=commands.add_parser('verify');ver.add_argument('--snapshot',type=Path,default=REPO/'snapshot')
    restore=commands.add_parser('materialize');restore.add_argument('--snapshot',type=Path,default=REPO/'snapshot');restore.add_argument('--dest',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='capture':capture(args.runtime,args.out,args.offline)
    elif args.command=='verify':
        result=verify(args.snapshot);print(json.dumps({'pass':result['pass'],'entries':result['entry_count'],'failures':result['failures']}));sys.exit(0 if result['pass'] else 1)
    else:materialize(args.snapshot,args.dest)


if __name__=='__main__':
    main()
