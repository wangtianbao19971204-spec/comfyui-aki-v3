"""Import one downloaded base model (checkpoint or diffusion weight) into the runtime.

Mirrors the LoRA entry contract for a single explicitly named download: verify the
full SHA-256 against the exact Civitai version file, place the weight under the
family/purpose root, write the sidecar, register the manager card, fetch one public
thumbnail, and record the asset in the catalogue.  Weights and private receipts stay
outside Git; the runtime is never restarted and nothing is downloaded.

Default: preview the plan.  ``--apply`` explicitly copies, registers and records.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import model_sources as catalogue
from model_naming_rules import build_standardization
from standardize_models import display_metadata

REPO = Path(__file__).resolve().parents[1]
ROOTS = {'checkpoint': 'checkpoints', 'diffusion_model': 'diffusion_models'}
LOADERS = {'checkpoint': ('CheckpointLoaderSimple', 'ckpt_name'),
           'diffusion_model': ('UNETLoader', 'unet_name')}
FULL_CHECKPOINT_PREFIXES = ('first_stage_model.', 'cond_stage_model.')


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
    """Validate the safetensors container, classify the loader root and hash it."""
    before = fingerprint(path)
    if time.time() - path.stat().st_mtime < 30:
        raise ValueError('download_still_recent')
    with path.open('rb') as stream:
        count = struct.unpack('<Q', stream.read(8))[0]
        if not 2 <= count <= min(before[0] - 8, 16 * 1024 * 1024):
            raise ValueError('invalid_safetensors_header')
        header = json.loads(stream.read(count))
    tensors = [value for key, value in header.items() if key != '__metadata__']
    if not tensors or any(not isinstance(value, dict) or not isinstance(value.get('data_offsets'), list)
                          or len(value['data_offsets']) != 2
                          or not 0 <= value['data_offsets'][0] <= value['data_offsets'][1] <= before[0] - count - 8
                          for value in tensors):
        raise ValueError('incomplete_safetensors')
    keys = [key for key in header if key != '__metadata__']
    kind = 'diffusion_model' if keys else 'checkpoint'
    if any(key.startswith(FULL_CHECKPOINT_PREFIXES) for key in keys):
        kind = 'checkpoint'
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if before != fingerprint(path):
        raise ValueError('download_changed')
    return {'original_name': path.name, 'bytes': before[0], 'sha256': digest, 'stat': before, 'kind': kind}


def request(url, data=None):
    payload = None if data is None else json.dumps(data, ensure_ascii=False).encode('utf-8')
    req = Request(url, data=payload, headers={'User-Agent': 'ComfyUI-model-import',
                                             'Content-Type': 'application/json'})
    with urlopen(req, timeout=60) as response:
        return json.load(response)


def selected_file(version, sha):
    """Bind the public version to its exact file, never to the title alone."""
    if (version.get('model', {}).get('type') or '').upper() != 'CHECKPOINT':
        raise ValueError('source_is_not_checkpoint')
    selected = [f for f in version.get('files', [])
                if (f.get('hashes', {}).get('SHA256') or '').lower() == sha]
    if len(selected) != 1:
        raise ValueError('exact_source_file_not_found')
    file = selected[0]
    if any(type(value) is not int or value <= 0 for value in (version.get('id'), version.get('modelId'), file.get('id'))):
        raise ValueError('invalid_source_identity')
    return file


def build_asset(row, version, kind):
    file = selected_file(version, row['sha256'])
    root = ROOTS[kind]
    source = {'provider': 'civitai',
              'page_url': 'https://civitai.com/models/%d?modelVersionId=%d' % (version['modelId'], version['id']),
              'download_url': 'https://civitai.com/api/download/models/%d' % version['id'],
              'model_id': version['modelId'], 'version_id': version['id'], 'file_id': file['id'],
              'filename': file['name'], 'declared_sha256': row['sha256'], 'revision': None,
              'evidence': [{'kind': 'anonymous_public_version_metadata_and_measured_full_local_sha256',
                            'reference': 'docs/technical/runtime/models.md'}],
              'availability': 'public_version_metadata_and_local_sha256_match_download_not_tested'}
    asset = {'path': 'ComfyUI/models/%s/%s' % (root, row['original_name']), 'bytes': row['bytes'],
             'kind': kind, 'captured_in_inventory': False, 'observed_present': True,
             'local_sha256': row['sha256'], 'source_status': 'version_metadata', 'family': None,
             'sources': [source], 'companions': [], 'workflows': [], 'derivation': None,
             'notes': ['Downloaded file verified by full SHA-256 against the exact public version; '
                       'weights stay outside Git.']}
    standard = build_standardization(asset, {'civitai': version, 'organization': {'category': '图像生成'}})
    if standard['family_slug'] == 'other':
        raise ValueError('source_family_needs_review')
    asset.update(current_path=standard['target_path'], standardization=standard,
                 family=standard['family_label'])
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
        while block := src.read(8 * 1024 * 1024):
            digest.update(block); dst.write(block)
        dst.flush(); os.fsync(dst.fileno())
    if digest.hexdigest() != row['sha256'] or fingerprint(source) != row['stat']:
        raise ValueError('copied_weight_differs_original_retained')
    with target.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256']:
            raise ValueError('destination_hash_mismatch_original_retained')


def metadata_for(row, asset, version, target):
    label, organization = display_metadata(asset['standardization'])
    file = selected_file(version, row['sha256'])
    organization.update({'kind': '底模', 'sha256': row['sha256'],
                         'civitai_model_id': version['modelId'], 'civitai_version_id': version['id'],
                         'civitai_url': asset['sources'][0]['page_url'],
                         'binding_status': 'hash_verified', 'local_training': False,
                         'source_type': version['model']['type']})
    clean = {key: version[key] for key in ('id', 'modelId', 'name', 'baseModel', 'trainedWords') if key in version}
    clean['model'] = {key: version['model'][key] for key in ('name', 'type') if key in version['model']}
    clean['files'] = [{key: file[key] for key in ('id', 'name', 'metadata', 'hashes') if key in file}]
    return {'file_name': target.stem, 'file_path': target.as_posix(), 'folder': None, 'size': row['bytes'],
            'sha256': row['sha256'], 'hash_status': 'completed', 'base_model': version['baseModel'],
            'model_name': label, 'from_civitai': True, 'modified': target.stat().st_mtime,
            'autov3': file.get('hashes', {}).get('AutoV3', ''), 'preview_url': '',
            'trained_words': version.get('trainedWords', []), 'organization': organization,
            'civitai': clean, 'tags': [], 'favorite': False, 'exclude': False,
            'skip_metadata_refresh': False, 'metadata_source': 'civitai_api',
            'source_platform': 'civitai', 'source_url': asset['sources'][0]['page_url']}


def loader_path(target, kind, runtime):
    return target.relative_to(runtime / 'ComfyUI/models' / ROOTS[kind]).as_posix()


def verify_card(db_path, target, row, label):
    with closing(sqlite3.connect(regular(db_path).as_uri() + '?mode=ro', uri=True)) as con:
        rows = con.execute("select file_path, model_name, sha256 from models where model_type='checkpoint'").fetchall()
    matches = [item for item in rows
               if item[0].replace('\\', '/').casefold() == target.as_posix().casefold()]
    if len(matches) != 1 or matches[0][2].lower() != row['sha256'] or matches[0][1] != label:
        raise ValueError('card_verification_failed_original_retained')
    return True


def current_branch():
    try:
        return subprocess.check_output(['git', 'branch', '--show-current'], cwd=REPO, text=True).strip()
    except OSError:
        head = (REPO / '.git' / 'HEAD').read_text(encoding='utf-8').strip()
        prefix = 'ref: refs/heads/'
        return head[len(prefix):] if head.startswith(prefix) else ''


def apply_row(row, downloads, runtime, api, evidence, previews=True, keep_originals=False):
    queue = request(api + '/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('queue_is_not_empty')
    node, field_name = LOADERS[row['kind']]
    node_info = request(api + '/object_info/' + node)
    if node not in node_info:
        raise ValueError('unexpected_runtime_service')
    source = regular(downloads / row['original_name'])
    target = regular(runtime / row['asset']['current_path'])
    target.relative_to(regular(runtime / 'ComfyUI/models' / ROOTS[row['kind']]))
    if target.exists() or target.with_suffix('.metadata.json').exists():
        raise ValueError('target_exists_no_overwrite')
    with (evidence / 'journal.jsonl').open('a', encoding='utf-8') as journal:
        journal.write(json.dumps({'phase': 'copy_started', 'source': str(source), 'target': str(target),
                                  'sha256': row['sha256']}, ensure_ascii=False) + '\n')
    copy_verified(source, target, row)
    metadata = metadata_for(row, row['asset'], row['version'], target)
    with target.with_suffix('.metadata.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
    response = request(api + '/api/lm/checkpoints/save-metadata',
                       {key: metadata[key] for key in ('file_path', 'model_name', 'organization')})
    if not response.get('success'):
        raise ValueError('registration_failed_original_retained')
    if previews:
        images = [image for image in row['version'].get('images', [])
                  if image.get('type') == 'image' and urlsplit(image.get('url', '')).scheme == 'https'
                  and urlsplit(image.get('url', '')).hostname == 'image.civitai.com']
        if images:
            image = min(images, key=lambda item: item.get('nsfwLevel', 0))
            preview = request(api + '/api/lm/checkpoints/set-preview-from-url',
                              {'model_path': target.as_posix(), 'image_url': image['url'],
                               'nsfw_level': image.get('nsfwLevel', 0)})
            if preview.get('success'):
                sidecar = json.loads(target.with_suffix('.metadata.json').read_text(encoding='utf-8'))
                preview_file = regular(Path(sidecar['preview_url']))
                preview_file.relative_to(target.parent)
                if preview_file.is_file():
                    row['asset']['companions'].append(preview_file.relative_to(runtime).as_posix())
            else:
                print(json.dumps({'preview_pending': row['original_name']}, ensure_ascii=False), flush=True)
    verify_card(row['cache_db'], target, row, metadata['model_name'])
    names = request(api + '/object_info/' + node)[node]['input']['required'][field_name][0]
    relative = loader_path(target, row['kind'], runtime)
    if relative not in [name.replace('\\', '/') for name in names]:
        raise ValueError('loader_verification_failed_original_retained')
    if fingerprint(source) != row['stat']:
        raise ValueError('source_changed_original_retained')
    if not keep_originals:
        source.unlink()
    print(json.dumps({'imported': relative}, ensure_ascii=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True, help='Exact file name inside --downloads')
    parser.add_argument('--kind', choices=sorted(ROOTS), help='Override the container-based loader root')
    parser.add_argument('--downloads', type=Path, default=Path.home() / 'Downloads')
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--api', default='http://127.0.0.1:8188')
    parser.add_argument('--evidence-root', type=Path,
                        default=Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ComfyUI-Model-Imports')
    parser.add_argument('--cache-db', type=Path,
                        default=Path(os.environ.get('LOCALAPPDATA', str(Path.home())))
                        / 'ComfyUI-LoRA-Manager/cache/model/comfyui.sqlite')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--keep-originals', action='store_true')
    parser.add_argument('--no-preview', action='store_true')
    args = parser.parse_args(argv)
    url = urlsplit(args.api)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.username \
            or url.password or url.query or url.fragment or url.path:
        raise ValueError('api_must_be_local_origin')
    cat, _, _ = catalogue.checked_catalogue(REPO)
    manifest_path = REPO / 'snapshot/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    runtime = regular(args.runtime or Path(manifest['source_root']))
    downloads = regular(args.downloads)
    source = regular(downloads / args.name)
    if not source.is_file():
        raise ValueError('download_not_found')
    evidence = regular(args.evidence_root) / ('import-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    evidence.mkdir(parents=True, exist_ok=False)
    row = inspect_weight(source)
    if args.kind:
        row['kind'] = args.kind
    known = {asset['local_sha256'].lower(): asset for asset in cat['assets']
             if asset['observed_present'] and asset.get('local_sha256')}
    if row['sha256'] in known:
        raise ValueError('digest_already_recorded_in_catalogue')
    row['version'] = request('https://civitai.com/api/v1/model-versions/by-hash/' + row['sha256'])
    row['asset'] = build_asset(row, row['version'], row['kind'])
    target = regular(runtime / row['asset']['current_path'])
    row['cache_db'] = args.cache_db
    plan = {'original_name': row['original_name'], 'bytes': row['bytes'], 'sha256': row['sha256'],
            'kind': row['kind'], 'current_path': row['asset']['current_path'],
            'civitai': {'model_id': row['version']['modelId'], 'version_id': row['version']['id'],
                        'file_id': row['asset']['sources'][0]['file_id'],
                        'version_name': row['version']['name'],
                        'base_model': row['version']['baseModel']},
            'standardization': row['asset']['standardization']}
    save(evidence / 'plan.json', plan)
    print(json.dumps(plan, ensure_ascii=False), flush=True)
    if not args.apply:
        return
    branch = current_branch()
    if not branch or branch == 'main':
        raise ValueError('apply_requires_development_branch')
    if target.exists() or target.with_suffix('.metadata.json').exists():
        raise ValueError('target_exists_no_overwrite')
    original = catalogue.digest(REPO / catalogue.CATALOGUE)
    proposed = json.loads(json.dumps(cat))
    proposed['assets'].append(row['asset'])
    proposed['summary'] = catalogue.compute_summary(proposed)
    inventory, invsha = catalogue.read_json(REPO / catalogue.INVENTORY)
    catalogue.validate_catalogue(proposed, inventory, invsha, catalogue.digest(REPO / catalogue.WORKFLOW_SOURCE))
    with closing(sqlite3.connect(regular(args.cache_db).as_uri() + '?mode=ro', uri=True)) as src, \
            closing(sqlite3.connect(evidence / 'cache-before.sqlite')) as dst:
        src.backup(dst)
    apply_row(row, downloads, runtime, args.api, evidence, previews=not args.no_preview,
              keep_originals=args.keep_originals)
    if original != catalogue.digest(REPO / catalogue.CATALOGUE):
        raise ValueError('catalogue_changed_during_import')
    cat['assets'].append(row['asset'])
    cat['summary'] = catalogue.compute_summary(cat)
    inventory, invsha = catalogue.read_json(REPO / catalogue.INVENTORY)
    catalogue.validate_catalogue(cat, inventory, invsha, catalogue.digest(REPO / catalogue.WORKFLOW_SOURCE))
    save(REPO / catalogue.CATALOGUE, cat)
    catalogue.render(REPO)
    for item in manifest['metadata_files']:
        if item['path'] == 'inventory/model_sources.json':
            item.update(sha256=catalogue.digest(REPO / catalogue.CATALOGUE),
                        bytes=(REPO / catalogue.CATALOGUE).stat().st_size)
    save(manifest_path, manifest)
    save(evidence / 'completed-asset.json', row['asset'])
    save(evidence / 'result.json', {'imported': 1, 'kind': row['kind'],
                                    'source_original_moved': not args.keep_originals,
                                    'card_registered': True, 'loader_verified': True,
                                    'restarted': False, 'gpu_tested': False})


if __name__ == '__main__':
    main()
