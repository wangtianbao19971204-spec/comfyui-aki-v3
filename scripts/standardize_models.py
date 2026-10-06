"""Reviewed local model naming migration; no downloads or inference.

Plan binds every weight, companion and deployment source to its actual bytes.
Apply uses the installed LoRA Manager's local rename/move APIs so shared
collection identities and recipe references remain under their normal owner.
Private sidecars/data backups and the journal stay outside the Git checkout.
"""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from model_naming_rules import build_standardization

REPO = Path(__file__).resolve().parents[1]
KINDS = {'lora', 'diffusion_model', 'checkpoint'}
ALLOWED_METADATA_CHANGES = {'file_name', 'file_path', 'model_name', 'preview_url',
                            'original_file_name', 'sub_type', 'organization'}
ALLOWED_ORGANIZATION_CHANGES = {'family', 'purpose', 'official_name', 'version', 'precision', 'naming_policy'}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def safe(root, relative):
    from model_sources import relative_path
    relative_path(relative)
    root = Path(root).absolute()
    path = root / relative
    candidate = path
    while True:
        if candidate.exists():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked migration path refused')
        if candidate == root:
            break
        if root not in candidate.parents:
            raise ValueError('Migration path escaped root')
        candidate = candidate.parent
    return path


def api(route, body=None):
    # Fixed loopback endpoint, never follow remote redirects or use proxy env.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('Local service redirect refused')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request('http://127.0.0.1:8188' + route,
        data=None if body is None else json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with opener.open(request, timeout=120) as response:
        result = json.load(response)
    if isinstance(result, dict) and (result.get('success') is False or result.get('partial_success')):
        raise ValueError('Local model operation requires reference recovery')
    return result


def quiet():
    queue = api('/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('Wait for the generation queue to finish before migration')


def display_metadata(standard):
    organization = {'family': standard['family_label'], 'purpose': standard['category'],
                    'official_name': standard['display_name'], 'version': standard['version'],
                    'precision': standard['precision'], 'naming_policy': '2026-10-07-v1'}
    label = '【' + standard['family_label'] + '｜' + standard['category'] + '】' + standard['display_name']
    if standard['version']:
        label += ' · ' + standard['version']
    if standard['precision']:
        label += ' · ' + standard['precision']
    return label, organization


def save_display_metadata(row, runtime):
    target = safe(runtime, row['new_path'])
    sidecar = target.with_suffix('.metadata.json')
    prior = load(sidecar) if sidecar.exists() else {}
    label, fields = display_metadata(row['standardization'])
    organization = dict(prior.get('organization') or {})
    organization.update(fields)
    prefix = 'loras' if row['kind'] == 'lora' else 'checkpoints'
    api('/api/lm/' + prefix + '/save-metadata',
        {'file_path': str(target), 'model_name': label, 'organization': organization})


def verify_model_caches(plan):
    """Check every migrated identity in the regular and excluded views."""
    runtime = Path(plan['runtime'])
    counts = {}
    for prefix, kinds in (('loras', {'lora'}), ('checkpoints', {'diffusion_model', 'checkpoint'})):
        views = {}
        for view in ('list', 'excluded'):
            paths = set()
            page = 1
            expected_total = None
            expected_pages = None
            while True:
                result = api(f'/api/lm/{prefix}/{view}?page={page}&page_size=100')
                total = result.get('total')
                pages = result.get('total_pages')
                if (not isinstance(total, int) or total < 0 or not isinstance(pages, int)
                        or pages < 0 or result.get('page') != page
                        or (expected_total is not None and total != expected_total)
                        or (expected_pages is not None and pages != expected_pages)):
                    raise ValueError('Model cache pagination changed during verification')
                expected_total = total
                expected_pages = pages
                for item in result.get('items', []):
                    file_path = item.get('file_path')
                    if not isinstance(file_path, str) or not file_path:
                        raise ValueError('Model cache identity is missing')
                    key = os.path.normcase(os.path.normpath(file_path))
                    if key in paths:
                        raise ValueError('Duplicate model cache identity')
                    paths.add(key)
                if page >= pages:
                    break
                page += 1
                if page > 10000:
                    raise ValueError('Model cache pagination is unbounded')
            if len(paths) != expected_total:
                raise ValueError('Model cache pagination omitted identities')
            views[view] = paths
        if views['list'] & views['excluded']:
            raise ValueError('Model appears in both regular and excluded caches')
        for row in plan['rows']:
            if row['kind'] not in kinds:
                continue
            target = safe(runtime, row['new_path'])
            metadata_file = target.with_suffix('.metadata.json')
            metadata = load(metadata_file) if metadata_file.exists() else {}
            if 'standardization' in row:
                label, fields = display_metadata(row['standardization'])
                organization = metadata.get('organization') or {}
                if (metadata.get('model_name') != label
                        or any(organization.get(k) != v for k, v in fields.items())):
                    raise ValueError('Standard model display metadata is missing')
            excluded = bool(metadata.get('exclude', False))
            if 'baseline_excluded' in row and excluded != row['baseline_excluded']:
                raise ValueError('Baseline exclusion setting changed')
            expected_view = 'excluded' if excluded else 'list'
            key = os.path.normcase(os.path.normpath(str(target)))
            if key not in views[expected_view]:
                raise ValueError('Migrated model missing from its expected cache view')
            old_key = os.path.normcase(os.path.normpath(str(safe(runtime, row['old_path']))))
            if old_key != key and old_key in views['list'] | views['excluded']:
                raise ValueError('Old model identity remains in cache')
        counts[prefix] = {'regular': len(views['list']), 'excluded': len(views['excluded'])}
    return counts


def protected(metadata):
    value = {k: v for k, v in metadata.items() if k not in ALLOWED_METADATA_CHANGES}
    organization = metadata.get('organization')
    if isinstance(organization, dict):
        retained = {k: v for k, v in organization.items() if k not in ALLOWED_ORGANIZATION_CHANGES}
        if retained:
            value['organization'] = retained
    return value


def update_shared_info(path, old_relative, new_relative, target):
    """Repair the legacy panel's local paths without changing source metadata."""
    value = load(path)
    if 'file' in value:
        value['file'] = new_relative
    if 'path' in value:
        value['path'] = str(target)
    for image in value.get('images', []):
        if not isinstance(image, dict) or not isinstance(image.get('url'), str):
            continue
        parsed = urlsplit(image['url'])
        if not parsed.scheme and not parsed.netloc and parsed.path == '/weilin/prompt_ui/api/lorainfo/api/loras/img':
            query = [(key, new_relative if key == 'file' and val.replace('\\', '/') == old_relative else val)
                     for key, val in parse_qsl(parsed.query, keep_blank_values=True)]
            image['url'] = urlunsplit(('', '', parsed.path, urlencode(query), parsed.fragment))
    save(path, value)


def aliases(rows):
    result = {}
    ambiguous = set()
    for row in rows:
        old, new = row['old_path'], row['new_path']
        for a, b in [(old, new), ('../' + old, '../' + new),
                     (old.removeprefix('ComfyUI/models/'), new.removeprefix('ComfyUI/models/')),
                     ('/'.join(old.split('/')[3:]), '/'.join(new.split('/')[3:])),
                     (Path(old).name, '/'.join(new.split('/')[3:]))]:
            for av, bv in [(a, b), (a.replace('/', '\\'), b.replace('/', '\\'))]:
                if av in result and result[av].replace('\\', '/') != bv.replace('\\', '/'):
                    ambiguous.add(av)
                if '/' not in av and '\\' not in av:
                    bv = bv.replace('\\', '/')
                result[av] = bv
    for key in ambiguous:
        result.pop(key, None)
    return {k: v for k, v in result.items() if k != v}


def rewrite(value, mapping):
    if isinstance(value, dict):
        # Downloader declarations retain the upstream filename and URL; only
        # actual runtime selectors (including map keys) acquire local names.
        if isinstance(value.get('url'), str) and '://' in value['url'] and 'name' in value:
            return value
        rewritten = {}
        for key, item in value.items():
            new_key = mapping.get(key, key)
            if new_key in rewritten:
                raise ValueError('Model reference dictionary key collision')
            rewritten[new_key] = rewrite(item, mapping)
        return rewritten
    if isinstance(value, list):
        return [rewrite(v, mapping) for v in value]
    if not isinstance(value, str) or '://' in value:
        return value
    if value in mapping:
        return mapping[value]
    # Some graph nodes serialize model selectors as JSON in a string widget.
    if value.startswith(('[', '{')):
        try:
            inner = json.loads(value)
        except ValueError:
            return value
        changed = rewrite(inner, mapping)
        if changed != inner:
            return json.dumps(changed, ensure_ascii=False)
    return value


def deployment_candidates():
    tracked = subprocess.check_output(['git', 'ls-files', '-z', 'snapshot/runtime'], cwd=REPO).decode('utf-8').split('\0')
    for relative in tracked:
        path = REPO / relative
        if path.suffix not in {'.json', '.py', '.js', '.yaml', '.yml', '.toml', '.cmd', '.bat'}:
            continue
        # Runtime originals only; archived evaluation scripts are historical.
        if '/tests' in relative or '/test_' in relative or '/node_modules/' in relative:
            continue
        yield path


def source_edits(rows, runtime, evidence):
    mapping = aliases(rows)
    old_names = [Path(row['old_path']).name for row in rows if row['old_path'] != row['new_path']]
    for row in rows:
        if row['old_path'] != row['new_path']:
            for old, new in [(str(runtime / row['old_path']), str(runtime / row['new_path'])),
                             ((runtime / row['old_path']).as_posix(), (runtime / row['new_path']).as_posix())]:
                mapping[old] = new
    edits = []
    for path in deployment_candidates():
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeError:
            continue
        if not any(name in text for name in old_names):
            continue
        if path.suffix == '.json':
            original = json.loads(text)
            updated = rewrite(original, mapping)
            if original == updated:
                continue
            replacement = (json.dumps(updated, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        else:
            # Only quoted, exact selector values; do not rewrite download URLs,
            # comments, arbitrary prose, or model-name substrings in prompts.
            updated = text
            for old, new in sorted(mapping.items(), key=lambda x: -len(x[0])):
                if '/' not in old and '\\' not in old:
                    continue
                for quote in ['"', "'"]:
                    for a, b in [(old, new), (old.replace('\\', '\\\\'), new.replace('\\', '\\\\'))]:
                        updated = updated.replace(quote + a + quote, quote + b + quote)
            if updated == text:
                continue
            replacement = updated.encode('utf-8')
        relative = path.relative_to(REPO / 'snapshot/runtime').as_posix()
        live = safe(runtime, relative)
        if not live.is_file() or sha(live) != sha(path):
            raise ValueError('Runtime source drift before migration: ' + relative)
        staged = evidence / 'candidate-sources' / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(replacement)
        edits.append({'path': relative, 'before_sha256': sha(path), 'after_sha256': sha(staged),
                      'bytes': len(replacement)})
    return edits


def prepare(runtime, evidence):
    quiet()
    if evidence.exists():
        raise ValueError('Use a new evidence directory')
    if REPO in evidence.parents or runtime in evidence.parents:
        raise ValueError('Evidence must stay outside runtime and repository')
    evidence.mkdir(parents=True)
    cat = load(REPO / 'snapshot/inventory/model_sources.json')
    rows = []
    selected = sorted([x for x in cat['assets'] if x['observed_present'] and x['kind'] in KINDS],
                      key=lambda x: (x['kind'] != 'lora', x['path']))
    # Validate all naming targets before reading hundreds of GiB of weights.
    standards = {}
    for asset in selected:
        path = safe(runtime, asset.get('current_path', asset['path']))
        sidecar = path.with_suffix('.metadata.json')
        standard = build_standardization(asset, load(sidecar) if sidecar.exists() else {})
        safe(runtime, standard['target_path'])
        standards[asset['path']] = standard
    for i, asset in enumerate(selected, 1):
        old = asset.get('current_path', asset['path'])
        path = safe(runtime, old)
        if not path.is_file() or path.stat().st_size != asset['bytes']:
            raise ValueError('Model inventory drift before migration')
        metadata_file = path.with_suffix('.metadata.json')
        metadata = load(metadata_file) if metadata_file.exists() else {}
        standard = standards[asset['path']]
        target = safe(runtime, standard['target_path'])
        if target != path and target.exists():
            raise ValueError('Model target already exists')
        companions = []
        for companion in path.parent.iterdir():
            if not companion.name.startswith(path.stem + '.'):
                continue
            if companion == path or not companion.is_file():
                continue
            safe(runtime, companion.relative_to(runtime).as_posix())
            suffix = companion.name[len(path.stem):]
            new = target.with_name(target.stem + suffix)
            if new != companion and new.exists():
                raise ValueError('Companion target already exists')
            # Raw companion backups contain private metadata and remain private.
            backup = evidence / 'before-companions' / companion.relative_to(runtime)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(companion, backup)
            companions.append({'old_path': companion.relative_to(runtime).as_posix(),
                               'new_path': new.relative_to(runtime).as_posix(), 'sha256': sha(companion)})
        info = path.stat()
        rows.append({'catalogue_path': asset['path'], 'old_path': old, 'new_path': standard['target_path'],
                     'kind': asset['kind'], 'standardization': standard, 'bytes': info.st_size,
                     'baseline_excluded': bool(metadata.get('exclude', False)),
                     'inode': info.st_ino, 'sha256': sha(path), 'companions': companions,
                     'metadata_protected_sha256': hashlib.sha256(json.dumps(protected(metadata), sort_keys=True, ensure_ascii=False).encode()).hexdigest()})
        if i % 10 == 0 or i == len(selected):
            print(json.dumps({'phase': 'hash_and_plan', 'done': i, 'total': len(selected)}), flush=True)
    keys = [r['new_path'].casefold() for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate standardized paths')
    edits = source_edits(rows, runtime, evidence)
    for edit in edits:
        src = safe(runtime, edit['path'])
        backup = evidence / 'before-sources' / edit['path']
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, backup)
    # Consistent online SQLite backups; never overwrite the application files.
    user_data = runtime / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-ComfyUI-prompt-all-in-one/user_data'
    if not user_data.exists():
        matches = list((runtime / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules').glob('*/user_data/prompt_selector'))
        if len(matches) != 1:
            raise ValueError('Shared data owner is ambiguous')
        user_data = matches[0].parent
    for data in user_data.rglob('*'):
        if not data.is_file() or data.suffix.lower() not in {'.json', '.db'}:
            continue
        if any(part in {'preview', 'preview_thumbnails', 'cache'} for part in data.relative_to(user_data).parts):
            continue
        backup = evidence / 'before-shared-data' / data.relative_to(user_data)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if data.suffix == '.db':
            source = sqlite3.connect(data.resolve().as_uri() + '?mode=ro', uri=True)
            destination = sqlite3.connect(backup)
            try:
                source.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Database backup integrity failed')
            finally:
                destination.close()
                source.close()
        else:
            shutil.copy2(data, backup)
    plan = {'schema': 1, 'created_at': now(), 'runtime': str(runtime),
            'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO).decode().strip(),
            'catalogue_sha256': sha(REPO / 'snapshot/inventory/model_sources.json'),
            'rows': rows, 'source_edits': edits, 'service_restarted': False,
            'scope': 'All current LoRAs and image bases in the registered main model roots; SAM tool separately classified.'}
    save(evidence / 'plan.json', plan)
    print(json.dumps({'phase': 'prepared', 'models': len(rows), 'source_files': len(edits),
                      'plan_sha256': sha(evidence / 'plan.json')}), flush=True)


def record(evidence, value):
    with (evidence / 'apply.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'at': now(), **value}, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def review_plan(evidence, expected_sha256):
    """Refine reference/companion enumeration before any apply; reuse hashes.

    This does not promote sidecar hashes into weight hashes. The full baseline
    hashes remain unchanged and apply rechecks them immediately before moving.
    """
    if sha(evidence / 'plan.json') != expected_sha256 or (evidence / 'apply.jsonl').exists():
        raise ValueError('Only a bound, unapplied plan can be reviewed')
    plan = load(evidence / 'plan.json')
    runtime = Path(plan['runtime'])
    cat = load(REPO / 'snapshot/inventory/model_sources.json')
    if sha(REPO / 'snapshot/inventory/model_sources.json') != plan['catalogue_sha256']:
        raise ValueError('Catalogue changed after baseline')
    assets = {x['path']: x for x in cat['assets']}
    for row in plan['rows']:
        old = safe(runtime, row['old_path'])
        info = old.stat()
        if info.st_size != row['bytes'] or info.st_ino != row['inode']:
            raise ValueError('Weight identity changed before plan review')
        sidecar = old.with_suffix('.metadata.json')
        metadata = load(sidecar) if sidecar.exists() else {}
        standard = build_standardization(assets[row['catalogue_path']], metadata)
        target = safe(runtime, standard['target_path'])
        if target != old and target.exists():
            raise ValueError('Revised target already exists')
        row['new_path'], row['standardization'] = standard['target_path'], standard
        row['metadata_protected_sha256'] = hashlib.sha256(json.dumps(protected(metadata), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        companions = []
        for file in old.parent.iterdir():
            if file == old or not file.name.startswith(old.stem + '.') or not file.is_file():
                continue
            safe(runtime, file.relative_to(runtime).as_posix())
            new = target.with_name(target.stem + file.name[len(old.stem):])
            if new != file and new.exists():
                raise ValueError('Revised companion target already exists')
            backup = evidence / 'before-companions' / file.relative_to(runtime)
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists() and sha(backup) != sha(file):
                raise ValueError('Companion changed since baseline backup')
            if not backup.exists():
                shutil.copy2(file, backup)
            companions.append({'old_path': file.relative_to(runtime).as_posix(),
                               'new_path': new.relative_to(runtime).as_posix(), 'sha256': sha(file)})
        row['companions'] = companions
    if len({r['new_path'].casefold() for r in plan['rows']}) != len(plan['rows']):
        raise ValueError('Revised standardized path collision')
    plan['source_edits'] = source_edits(plan['rows'], runtime, evidence)
    mapping = aliases(plan['rows'])
    for row in plan['rows']:
        for old, new in [(str(runtime / row['old_path']), str(runtime / row['new_path'])),
                         ((runtime / row['old_path']).as_posix(), (runtime / row['new_path']).as_posix())]:
            mapping[old] = new
    external_edits = []
    tracked = {edit['path'] for edit in plan['source_edits']}
    for folder in ['anima_lora_forge/profiles', 'qwen21_lab/workflows_api', 'qwen21_lab/user/default/workflows']:
        for file in (runtime / folder).glob('*.json'):
            relative = file.relative_to(runtime).as_posix()
            if relative in tracked:
                continue
            safe(runtime, relative)
            original = load(file)
            updated = rewrite(original, mapping)
            if updated == original:
                continue
            staged = evidence / 'candidate-configs' / relative
            save(staged, updated)
            backup = evidence / 'before-configs' / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, backup)
            external_edits.append({'path': relative, 'before_sha256': sha(file), 'after_sha256': sha(staged)})
    plan['external_edits'] = external_edits
    for edit in plan['source_edits']:
        backup = evidence / 'before-sources' / edit['path']
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(safe(runtime, edit['path']), backup)
    if not (evidence / 'plan-initial.json').exists():
        save(evidence / 'plan-initial.json', load(evidence / 'plan.json'))
    plan['reviewed_at'] = now()
    plan['helper_sha256'] = sha(Path(__file__))
    plan['naming_rules_sha256'] = sha(REPO / 'scripts/model_naming_rules.py')
    save(evidence / 'plan.json', plan)
    print(json.dumps({'phase': 'reviewed', 'models': len(plan['rows']),
                      'companions': sum(len(r['companions']) for r in plan['rows']),
                      'source_files': len(plan['source_edits']), 'external_configs': len(external_edits),
                      'plan_sha256': sha(evidence / 'plan.json')}), flush=True)


def stage(evidence, expected_sha256):
    if sha(evidence / 'plan.json') != expected_sha256:
        raise ValueError('Plan binding changed')
    plan = load(evidence / 'plan.json')
    for edit in plan['source_edits']:
        staged = safe(evidence / 'candidate-sources', edit['path'])
        repository = safe(REPO / 'snapshot/runtime', edit['path'])
        if sha(staged) != edit['after_sha256'] or sha(repository) != edit['before_sha256']:
            raise ValueError('Reviewed source binding changed before staging')
        repository.write_bytes(staged.read_bytes())
    print(json.dumps({'phase': 'staged_in_main_git', 'source_files': len(plan['source_edits']), 'runtime_modified': False}), flush=True)


def normalize_family_directory_case(runtime, rows, evidence):
    """Use the canonical on-disk case required by filename enum validation.

    Windows accepts a lower-case path to an existing upper-case directory,
    but ComfyUI's filename choices still expose that directory's stored case.
    A same-volume two-step directory rename repairs this without copying or
    changing any model. Linux paths already created with canonical case need
    no change. Only the exact reviewed family folders are eligible.
    """
    quiet()
    wanted = sorted({tuple(row['new_path'].split('/')[:4]) for row in rows})
    for parts in wanted:
        root = safe(runtime, '/'.join(parts[:3]))
        expected = parts[3]
        actual = [p for p in root.iterdir() if p.name.casefold() == expected.casefold()]
        if len(actual) != 1 or not actual[0].is_dir():
            raise ValueError('Canonical model family directory is absent or ambiguous')
        old = safe(runtime, actual[0].relative_to(runtime).as_posix())
        new = safe(runtime, '/'.join(parts))
        if old.name == expected:
            continue
        temporary = root / ('.naming-case-' + expected)
        safe(runtime, temporary.relative_to(runtime).as_posix())
        if temporary.exists():
            raise ValueError('Case-normalization temporary folder already exists')
        # Verified absolute old/new/temp roots all remain in this loader root.
        old.rename(temporary)
        try:
            temporary.rename(new)
        except BaseException:
            temporary.rename(old)
            raise
        record(evidence, {'event': 'family_case_normalized', 'old_path': old.relative_to(runtime).as_posix(),
                          'new_path': new.relative_to(runtime).as_posix()})


def apply(evidence, expected_sha256, limit=None):
    if sha(evidence / 'plan.json') != expected_sha256:
        raise ValueError('Plan binding changed')
    plan = load(evidence / 'plan.json')
    runtime = Path(plan['runtime'])
    quiet()
    if sha(REPO / 'snapshot/inventory/model_sources.json') != plan['catalogue_sha256']:
        raise ValueError('Source catalogue changed after plan review')
    for edit in plan['source_edits']:
        if sha(safe(runtime, edit['path'])) not in {edit['before_sha256'], edit['after_sha256']}:
            raise ValueError('Runtime source changed before migration')
    for edit in plan.get('external_edits', []):
        if sha(safe(runtime, edit['path'])) != edit['before_sha256']:
            raise ValueError('Private config changed before migration')
    if not (evidence / 'apply.jsonl').exists():
        for row in plan['rows']:
            if row['new_path'] != row['old_path'] and safe(runtime, row['new_path']).exists():
                raise ValueError('Model target occupied before migration')
            for companion in row['companions']:
                if companion['new_path'] != companion['old_path'] and safe(runtime, companion['new_path']).exists():
                    raise ValueError('Companion target occupied before migration')
    # No overwrite of a previously mutated file; an interrupted operation must
    # be diagnosed from its journal and disk rather than blindly run again.
    if (evidence / 'apply.jsonl').exists():
        completed = [json.loads(line) for line in (evidence / 'apply.jsonl').read_text('utf-8').splitlines() if line]
        done = {x['catalogue_path'] for x in completed if x.get('event') == 'model_complete'}
        started = {x['catalogue_path'] for x in completed if x.get('event') == 'model_begin'}
        if started != done:
            raise ValueError('Interrupted model operation requires journal recovery')
    else:
        done = set()
    pending = [r for r in plan['rows'] if r['catalogue_path'] not in done]
    for edit in plan['source_edits']:
        if sha(safe(REPO / 'snapshot/runtime', edit['path'])) != edit['after_sha256']:
            raise ValueError('Stage and validate source changes in the main Git before applying')
    for i, row in enumerate(pending[:limit] if limit else pending, 1):
        quiet()
        old, target = safe(runtime, row['old_path']), safe(runtime, row['new_path'])
        if sha(old) != row['sha256'] or old.stat().st_ino != row['inode']:
            raise ValueError('Model changed after plan')
        for companion in row['companions']:
            if sha(safe(runtime, companion['old_path'])) != companion['sha256']:
                raise ValueError('Companion changed after plan')
        record(evidence, {'event': 'model_begin', 'catalogue_path': row['catalogue_path']})
        prefix = 'loras' if row['kind'] == 'lora' else 'checkpoints'
        current = old
        # A GGUF not registered in LM is moved directly on this same volume;
        # it has no LM/shared identity or sidecar. Its graph references are
        # migrated by the reviewed source changes below.
        if old.suffix.lower() == '.gguf' and not old.with_suffix('.metadata.json').exists():
            if row['companions']:
                raise ValueError('Unregistered GGUF companions require owner review')
            target.parent.mkdir(parents=True, exist_ok=True)
            if target != old:
                old.rename(target)
        else:
            # Move first: scanner's existing companion enumeration covers
            # additional .json and shared-info suffixes beyond preview images.
            if current.parent != target.parent:
                result = api('/api/lm/' + prefix + '/move_model', {'file_path': str(current), 'target_path': str(target.parent), 'use_default_paths': False})
                current = Path(result['new_file_path'])
                record(evidence, {'event': 'moved', 'catalogue_path': row['catalogue_path'], 'path': str(current), 'reference_sync': result.get('reference_sync')})
            if old.stem != target.stem:
                result = api('/api/lm/' + prefix + '/rename', {'file_path': str(current), 'new_file_name': target.stem})
                current = Path(result['new_file_path'])
                record(evidence, {'event': 'renamed', 'catalogue_path': row['catalogue_path'], 'path': str(current), 'reference_sync': result.get('reference_sync')})
            if current != target:
                raise ValueError('Unexpected model target selected by service')
            for companion in row['companions']:
                new = safe(runtime, companion['new_path'])
                if new.exists():
                    continue
                # Lifecycle rename handles standard metadata and previews.
                # Other exact companions retain their byte identity, and are
                # moved explicitly from the intermediate old stem.
                suffix = Path(companion['old_path']).name[len(old.stem):]
                intermediate = target.parent / (old.stem + suffix)
                if not intermediate.exists():
                    intermediate = safe(runtime, companion['old_path'])
                if not intermediate.is_file() or sha(intermediate) != companion['sha256']:
                    raise ValueError('Additional companion is absent or changed')
                intermediate.rename(new)
            for companion in row['companions']:
                if companion['new_path'].endswith('.weilin-info.json'):
                    update_shared_info(safe(runtime, companion['new_path']),
                        '/'.join(row['old_path'].split('/')[3:]),
                        '/'.join(row['new_path'].split('/')[3:]), target)
            save_display_metadata(row, runtime)
        if not target.is_file() or target.stat().st_ino != row['inode'] or target.stat().st_size != row['bytes']:
            raise ValueError('Weight identity changed during naming migration')
        metadata_file = target.with_suffix('.metadata.json')
        metadata = load(metadata_file) if metadata_file.exists() else {}
        actual = hashlib.sha256(json.dumps(protected(metadata), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if actual != row['metadata_protected_sha256']:
            raise ValueError('Protected metadata changed during naming migration')
        for companion in row['companions']:
            new = safe(runtime, companion['new_path'])
            if not new.is_file():
                raise ValueError('Companion did not follow its model')
            if not new.name.endswith(('.metadata.json', '.metadata.json.bak', '.weilin-info.json')) and sha(new) != companion['sha256']:
                raise ValueError('Preview content changed during naming migration')
        record(evidence, {'event': 'model_complete', 'catalogue_path': row['catalogue_path']})
        print(json.dumps({'phase': 'apply_models', 'done': len(done) + i, 'total': len(plan['rows'])}), flush=True)
    if limit and limit < len(pending):
        return
    normalize_family_directory_case(runtime, plan['rows'], evidence)
    for edit in plan['source_edits']:
        staged = safe(evidence / 'candidate-sources', edit['path'])
        repository = safe(REPO / 'snapshot/runtime', edit['path'])
        live = safe(runtime, edit['path'])
        if sha(staged) != edit['after_sha256']:
            raise ValueError('Candidate source changed')
        for path in [live]:
            if sha(path) == edit['after_sha256']:
                continue
            if sha(path) != edit['before_sha256']:
                raise ValueError('Deployment source changed during migration')
            temporary = path.with_name(path.name + '.naming-tmp')
            temporary.write_bytes(staged.read_bytes())
            os.replace(temporary, path)
        record(evidence, {'event': 'source_complete', 'path': edit['path']})
    for edit in plan.get('external_edits', []):
        live = safe(runtime, edit['path'])
        staged = safe(evidence / 'candidate-configs', edit['path'])
        if sha(staged) != edit['after_sha256'] or sha(live) != edit['before_sha256']:
            raise ValueError('Private config changed during migration')
        temporary = live.with_name(live.name + '.naming-tmp')
        temporary.write_bytes(staged.read_bytes())
        os.replace(temporary, live)
        record(evidence, {'event': 'config_complete', 'path': edit['path']})
    # Incremental reconcile can reinsert renamed excluded entries in raw_data.
    # Rebuild both views from current sidecars without fetching remote metadata.
    api('/api/lm/loras/scan?full_rebuild=true')
    api('/api/lm/checkpoints/scan?full_rebuild=true')
    for row in plan['rows']:
        if Path(row['new_path']).suffix.lower() == '.gguf':
            # Previously unregistered GGUFs acquire local default sidecars only
            # during the scan; set their display fields after registration.
            save_display_metadata(row, runtime)
    if any(Path(row['new_path']).suffix.lower() == '.gguf' for row in plan['rows']):
        # The scanner may append an additional cache row when first assigning
        # metadata to a GGUF. Rebuild from the one physical file before proving
        # uniqueness; never remove either row by deleting the weight.
        api('/api/lm/checkpoints/scan?full_rebuild=true')
    cache_counts = verify_model_caches(plan)
    record(evidence, {'event': 'model_caches_verified', 'counts': cache_counts})
    print(json.dumps({'phase': 'applied', 'models': len(plan['rows']), 'source_files': len(plan['source_edits'])}), flush=True)


def verify(evidence):
    plan = load(evidence / 'plan.json')
    runtime = Path(plan['runtime'])
    results = []
    for i, row in enumerate(plan['rows'], 1):
        target = safe(runtime, row['new_path'])
        actual = sha(target)
        if actual != row['sha256']:
            raise ValueError('Post-migration weight SHA mismatch')
        if row['new_path'] != row['old_path'] and safe(runtime, row['old_path']).exists():
            raise ValueError('Old model path still exists')
        results.append({'path': row['new_path'], 'sha256': actual})
        if i % 10 == 0 or i == len(plan['rows']):
            print(json.dumps({'phase': 'post_hash', 'done': i, 'total': len(plan['rows'])}), flush=True)
    for edit in plan['source_edits']:
        if sha(safe(runtime, edit['path'])) != edit['after_sha256'] or sha(safe(REPO / 'snapshot/runtime', edit['path'])) != edit['after_sha256']:
            raise ValueError('Deployed source mismatch')
    for edit in plan.get('external_edits', []):
        if sha(safe(runtime, edit['path'])) != edit['after_sha256']:
            raise ValueError('Private config reference mismatch')
    quiet()
    cache_counts = verify_model_caches(plan)
    receipt = {'schema': 1, 'pass': True, 'verified_at': now(), 'model_count': len(results),
               'plan_sha256': sha(evidence / 'plan.json'), 'weight_hashes': results,
               'source_files': len(plan['source_edits']), 'queue_running': 0, 'queue_pending': 0,
               'model_cache_counts': cache_counts,
               'service_restarted': False, 'models_downloaded': False}
    save(evidence / 'post-verification.json', receipt)
    print(json.dumps({'phase': 'verified', 'pass': True, 'models': len(results), 'source_files': len(plan['source_edits'])}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('plan')
    prep.add_argument('--runtime', type=Path, required=True)
    prep.add_argument('--evidence', type=Path, required=True)
    apply_parser = sub.add_parser('apply')
    apply_parser.add_argument('--evidence', type=Path, required=True)
    apply_parser.add_argument('--plan-sha256', required=True)
    apply_parser.add_argument('--limit', type=int)
    stage_parser = sub.add_parser('stage')
    stage_parser.add_argument('--evidence', type=Path, required=True)
    stage_parser.add_argument('--plan-sha256', required=True)
    review = sub.add_parser('review-plan')
    review.add_argument('--evidence', type=Path, required=True)
    review.add_argument('--plan-sha256', required=True)
    ver = sub.add_parser('verify')
    ver.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'plan':
        prepare(args.runtime.absolute(), args.evidence.absolute())
    elif args.command == 'review-plan':
        review_plan(args.evidence.absolute(), args.plan_sha256)
    elif args.command == 'stage':
        stage(args.evidence.absolute(), args.plan_sha256)
    elif args.command == 'apply':
        evidence = args.evidence.absolute()
        lock = evidence / 'apply.lock'
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(descriptor, json.dumps({'pid': os.getpid(), 'at': now()}).encode())
            os.close(descriptor)
            apply(evidence, args.plan_sha256, args.limit)
        finally:
            lock.unlink()
    else:
        verify(args.evidence.absolute())


if __name__ == '__main__':
    main()
