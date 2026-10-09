"""Import only new downloaded LoRAs; weights and private receipts stay outside Git.

Default: preview the plan. --apply explicitly moves verified new downloads,
registers each card without a library rescan, and updates the public catalogue.
No restart, generation, model download, or replacement of existing models.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import model_sources as catalogue
from model_naming_rules import build_standardization, LORA_CATEGORIES
from standardize_models import display_metadata

REPO = Path(__file__).resolve().parents[1]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def regular(path):
    """Reject links and Windows junctions before using a local path."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('linked_path')
    return path


def fingerprint(path):
    stat = regular(path).stat()
    return [stat.st_size, stat.st_mtime_ns, stat.st_ino]


def inspect_weight(path):
    before = fingerprint(path)
    if time.time() - path.stat().st_mtime < 30:
        raise ValueError('download_still_recent')
    with path.open('rb') as stream:
        count = struct.unpack('<Q', stream.read(8))[0]
        if not 2 <= count <= min(before[0] - 8, 16 * 1024 * 1024):
            raise ValueError('invalid_safetensors_header')
        header = json.loads(stream.read(count))
        tensors = [v for k, v in header.items() if k != '__metadata__']
        if not tensors or any(not isinstance(v, dict) or not isinstance(v.get('data_offsets'), list)
                              or len(v['data_offsets']) != 2
                              or not 0 <= v['data_offsets'][0] <= v['data_offsets'][1] <= before[0] - count - 8
                              for v in tensors):
            raise ValueError('incomplete_safetensors')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if before != fingerprint(path):
        raise ValueError('download_changed')
    return {'original_name': path.name, 'bytes': before[0], 'sha256': digest, 'stat': before}


def request(url, data=None):
    payload = None if data is None else json.dumps(data, ensure_ascii=False).encode('utf-8')
    req = Request(url, data=payload, headers={'User-Agent': 'ComfyUI-LoRA-import',
                                            'Content-Type': 'application/json'})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def selected_version(version, sha):
    """Bind a public version to its exact file, never to its title alone."""
    if version.get('model', {}).get('type', '').upper() != 'LORA':
        raise ValueError('source_is_not_lora')
    selected = [f for f in version.get('files', [])
                if (f.get('hashes', {}).get('SHA256') or '').lower() == sha]
    if len(selected) != 1:
        raise ValueError('exact_source_file_not_found')
    file = selected[0]
    if any(type(v) is not int or v <= 0 for v in (version.get('id'), version.get('modelId'), file.get('id'))):
        raise ValueError('invalid_source_identity')
    return file


def category_for(title):
    text = title.casefold()
    if any(word in text for word in ('outfit', 'uniform', 'swimsuit', '服装', '制服')):
        return '服装与配饰'
    if any(word in text for word in ('style', 'artist', '画风', '画師', '画师')):
        return '画风与画师'
    return '其他与待核'


def public_asset(row, version, category):
    if category not in LORA_CATEGORIES:
        raise ValueError('unknown_category')
    file = selected_version(version, row['sha256'])
    source = {'provider': 'civitai',
              'page_url': f"https://civitai.com/models/{version['modelId']}?modelVersionId={version['id']}",
              'download_url': f"https://civitai.com/api/download/models/{version['id']}",
              'model_id': version['modelId'], 'version_id': version['id'], 'file_id': file['id'],
              'filename': file['name'], 'declared_sha256': row['sha256'], 'revision': None,
              'evidence': [{'kind': 'anonymous_public_version_metadata_and_measured_full_local_sha256',
                            'reference': 'docs/technical/runtime/lora-quick-import.md'}],
              'availability': 'public_version_metadata_and_local_sha256_match_download_not_tested'}
    asset = {'path': 'ComfyUI/models/loras/' + row['original_name'], 'bytes': row['bytes'],
             'kind': 'lora', 'captured_in_inventory': False, 'observed_present': True,
             'local_sha256': row['sha256'], 'source_status': 'version_metadata', 'family': None,
             'sources': [source], 'companions': [], 'workflows': [], 'derivation': None,
             'notes': ['Downloaded file verified by full SHA-256 against the exact public version; weights stay outside Git.']}
    standard = build_standardization(asset, {'civitai': version, 'organization': {'category': category}})
    asset.update(current_path=standard['target_path'], standardization=standard, family=standard['family_slug'])
    if standard['family_slug'] == 'other':
        raise ValueError('source_family_needs_review')
    asset['companions'] = [str(Path(asset['current_path']).with_suffix('.metadata.json')).replace('\\', '/')]
    return asset


def copy_verified(source, target, row):
    """Exclusive cross-volume copy; keep the original until registration verifies."""
    regular(source); regular(target)
    if fingerprint(source) != row['stat']:
        raise ValueError('source_changed_since_plan')
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with source.open('rb') as src, target.open('xb') as dst:
        while block := src.read(4 * 1024 * 1024):
            digest.update(block); dst.write(block)
        dst.flush(); os.fsync(dst.fileno())
    if digest.hexdigest() != row['sha256'] or fingerprint(source) != row['stat']:
        raise ValueError('copied_weight_differs_original_retained')
    with target.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256']:
            raise ValueError('destination_hash_mismatch_original_retained')


def metadata_for(row, asset, version, target):
    label, organization = display_metadata(asset['standardization'])
    file = selected_version(version, row['sha256'])
    # Select public identity fields only; raw training headers/private sidecars are not copied.
    clean = {k: version[k] for k in ('id', 'modelId', 'name', 'baseModel', 'trainedWords') if k in version}
    clean['model'] = {k: version['model'][k] for k in ('name', 'type') if k in version['model']}
    clean['files'] = [{k: file[k] for k in ('id', 'name', 'metadata', 'hashes') if k in file}]
    return {'file_name': target.stem, 'file_path': target.as_posix(), 'size': row['bytes'],
            'folder': target.parent.relative_to(target.parents[2] if asset['standardization']['family_slug'] != 'other' else target.parent).as_posix(),
            'autov3': file.get('hashes', {}).get('AutoV3', ''), 'from_civitai': True,
            'modified': target.stat().st_mtime, 'sha256': row['sha256'], 'hash_status': 'completed',
            'base_model': version['baseModel'], 'model_name': label, 'civitai': clean,
            'trained_words': version.get('trainedWords', []), 'organization': organization,
            'tags': [], 'favorite': False, 'exclude': False, 'skip_metadata_refresh': False,
            'preview_url': ''}


def apply_rows(rows, downloads, runtime, api, evidence, previews=True):
    queue = request(api + '/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('queue_is_not_empty')
    loader = request(api + '/object_info/LoraLoader')
    if 'LoraLoader' not in loader:
        raise ValueError('unexpected_runtime_service')
    completed = []
    for row in rows:
        source = regular(downloads / row['original_name'])
        asset = row['asset']; target = regular(runtime / asset['current_path'])
        target.relative_to(regular(runtime / 'ComfyUI/models/loras'))
        if target.exists() or target.with_suffix('.metadata.json').exists():
            raise ValueError('target_exists_no_overwrite')
        queue = request(api + '/queue')
        if queue.get('queue_running') or queue.get('queue_pending'):
            raise ValueError('queue_is_not_empty')
        with (evidence / 'journal.jsonl').open('a', encoding='utf-8') as journal:
            journal.write(json.dumps({'phase': 'copy_started', 'source': str(source), 'target': str(target),
                                      'sha256': row['sha256']}, ensure_ascii=False) + '\n')
        copy_verified(source, target, row)
        metadata = metadata_for(row, asset, row['version'], target)
        with target.with_suffix('.metadata.json').open('x', encoding='utf-8', newline='\n') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        response = request(api + '/api/lm/loras/save-metadata',
                           {k: metadata[k] for k in ('file_path', 'model_name', 'organization')})
        if not response.get('success'):
            raise ValueError('registration_failed_original_retained')
        if previews:
            add_preview(row, target, runtime, api)
        query = urlencode({'hashes': json.dumps([row['sha256']]), 'page_size': 100, 'group_by_model': 'false'})
        cards = request(api + '/api/lm/loras/list?' + query)
        matches = [i for i in cards.get('items', []) if i.get('file_path', '').replace('\\', '/').casefold() == target.as_posix().casefold()
                   and i.get('sha256', '').lower() == row['sha256'] and i.get('model_name') == metadata['model_name']]
        names = request(api + '/object_info/LoraLoader')['LoraLoader']['input']['required']['lora_name'][0]
        relative = target.relative_to(runtime / 'ComfyUI/models/loras').as_posix()
        if len(matches) != 1 or relative not in [n.replace('\\', '/') for n in names]:
            raise ValueError('card_or_loader_verification_failed_original_retained')
        if fingerprint(source) != row['stat']:
            raise ValueError('source_changed_original_retained')
        source.unlink()
        completed.append(asset)
        save(evidence / 'completed-assets.json', completed)
        print(json.dumps({'imported': relative}, ensure_ascii=False), flush=True)
    return completed


def add_preview(row, target, runtime, api):
    """Use the deployed manager for one public static thumbnail, never raw prompts."""
    images = [i for i in row['version'].get('images', []) if i.get('type') == 'image'
              and urlsplit(i.get('url', '')).scheme == 'https'
              and urlsplit(i.get('url', '')).hostname == 'image.civitai.com']
    if not images:
        return
    image = min(images, key=lambda i: i.get('nsfwLevel', 0))
    try:
        response = request(api + '/api/lm/loras/set-preview-from-url',
                           {'model_path': target.as_posix(), 'image_url': image['url'],
                            'nsfw_level': image.get('nsfwLevel', 0)})
        if not response.get('success'):
            raise ValueError('preview_fetch_failed')
        sidecar = json.loads(target.with_suffix('.metadata.json').read_text(encoding='utf-8'))
        preview = regular(Path(sidecar['preview_url']))
        preview.relative_to(target.parent)
        if not preview.is_file():
            raise ValueError('preview_file_not_found')
        row['asset']['companions'].append(preview.relative_to(runtime).as_posix())
    except Exception as error:
        print(json.dumps({'preview_pending': row['original_name'], 'reason': type(error).__name__}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--downloads', type=Path, default=Path.home() / 'Downloads')
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--api', default='http://127.0.0.1:8188')
    parser.add_argument('--evidence-root', type=Path, default=Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ComfyUI-LoRA-Imports')
    parser.add_argument('--cache-db', type=Path, default=Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ComfyUI-LoRA-Manager/cache/model/comfyui.sqlite')
    parser.add_argument('--categories', type=Path, help='Reviewed JSON mapping of full SHA256 to category')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--no-preview', action='store_true', help='Skip public static preview thumbnails')
    args = parser.parse_args(argv)
    url = urlsplit(args.api)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.username or url.password or url.query or url.fragment or url.path:
        raise ValueError('api_must_be_local_origin')
    cat, _, _ = catalogue.checked_catalogue(REPO)
    manifest_path = REPO / 'snapshot/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    runtime = regular(args.runtime or Path(manifest['source_root']))
    downloads = regular(args.downloads)
    evidence = regular(args.evidence_root) / ('import-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    evidence.relative_to(regular(args.evidence_root))
    if evidence.is_relative_to(REPO) or downloads.is_relative_to(REPO) or runtime.is_relative_to(REPO):
        raise ValueError('private_inputs_must_stay_outside_git')
    evidence.mkdir(parents=True, exist_ok=False)
    known = {a['local_sha256']: a for a in cat['assets'] if a['observed_present'] and a['local_sha256']}
    categories = json.loads(args.categories.read_text(encoding='utf-8')) if args.categories else {}
    rows = []; duplicates = []; skipped = []
    paths = sorted(downloads.glob('*.safetensors'))
    def prepare(path):
        try:
            row = inspect_weight(path)
            if row['sha256'] in known:
                asset = known[row['sha256']]; target = regular(runtime / catalogue.current_path(asset))
                with target.open('rb') as f:
                    if hashlib.file_digest(f, 'sha256').hexdigest() != row['sha256']:
                        raise ValueError('existing_weight_mismatch')
                return 'duplicate', {'original_name': row['original_name'], 'sha256': row['sha256']}
            version = request('https://civitai.com/api/v1/model-versions/by-hash/' + row['sha256'])
            category = categories.get(row['sha256'], category_for(version['model']['name']))
            row['asset'] = public_asset(row, version, category); row['version'] = version
            return 'new', row
        except Exception as error:
            return 'skipped', {'original_name': path.name, 'reason': type(error).__name__ if not isinstance(error, ValueError) else str(error)}
    for kind, value in ThreadPoolExecutor(max_workers=3).map(prepare, paths):
        {'new': rows, 'duplicate': duplicates, 'skipped': skipped}[kind].append(value)
    # In-batch duplicate downloads must not acquire the same target twice.
    seen = set(); unique = []
    for row in rows:
        if row['sha256'] in seen:
            duplicates.append({'original_name': row['original_name'], 'sha256': row['sha256']})
        else:
            seen.add(row['sha256']); unique.append(row)
    rows = unique
    save(evidence / 'plan.json', {'rows': rows, 'duplicates': duplicates, 'skipped': skipped})
    print(json.dumps({'new': len(rows), 'duplicates': len(duplicates), 'skipped': skipped,
                      'bytes': sum(r['bytes'] for r in rows), 'receipt': str(evidence)}, ensure_ascii=False), flush=True)
    if not args.apply or not rows:
        return
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=REPO, text=True).strip()
    if not branch or branch == 'main':
        raise ValueError('apply_requires_development_branch')
    original = catalogue.digest(REPO / catalogue.CATALOGUE)
    proposed = json.loads(json.dumps(cat))
    proposed['assets'].extend(r['asset'] for r in rows)
    proposed['summary'] = catalogue.compute_summary(proposed)
    inventory, invsha = catalogue.read_json(REPO / catalogue.INVENTORY)
    catalogue.validate_catalogue(proposed, inventory, invsha, catalogue.digest(REPO / catalogue.WORKFLOW_SOURCE))
    db = regular(args.cache_db)
    with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(evidence / 'cache-before.sqlite')) as dst:
        src.backup(dst)
    assets = apply_rows(rows, downloads, runtime, args.api, evidence, previews=not args.no_preview)
    if original != catalogue.digest(REPO / catalogue.CATALOGUE):
        raise ValueError('catalogue_changed_completed_assets_in_receipt')
    cat['assets'].extend(assets); cat['summary'] = catalogue.compute_summary(cat)
    inventory, invsha = catalogue.read_json(REPO / catalogue.INVENTORY)
    catalogue.validate_catalogue(cat, inventory, invsha, catalogue.digest(REPO / catalogue.WORKFLOW_SOURCE))
    save(REPO / catalogue.CATALOGUE, cat)
    catalogue.render(REPO)
    for item in manifest['metadata_files']:
        if item['path'] == 'inventory/model_sources.json':
            item.update(sha256=catalogue.digest(REPO / catalogue.CATALOGUE), bytes=(REPO / catalogue.CATALOGUE).stat().st_size)
    save(manifest_path, manifest)
    save(evidence / 'result.json', {'imported': len(assets), 'duplicates': len(duplicates), 'skipped': skipped,
                                   'source_originals_moved': True, 'single_card_registration': True,
                                   'full_library_rescan': False, 'restarted': False, 'gpu_tested': False})


if __name__ == '__main__':
    main()
