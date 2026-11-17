"""Register LoRA weights that already exist in the runtime but not in the catalogue.

The 2026-11-14 MOSS library deploy and several later manager imports placed and
renamed weights without recording them in the Git catalogue.  This tool reads the
deployed sidecars, re-measures each weight's full SHA-256, and appends catalogue
records for exactly those files.  It never moves, renames, downloads, deletes, or
writes to the runtime, and it refuses to touch anything already recorded.

Default: plan only.  ``--apply`` rewrites the catalogue, its manifest entry and the
rendered public document only after the full catalogue contract passes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import model_sources as catalogue
from model_naming_rules import FAMILY_LABELS

REPO = Path(__file__).resolve().parents[1]
LORA_ROOT = 'ComfyUI/models/loras'
EVIDENCE_KIND = 'deployed_sidecar_and_measured_full_local_sha256'
EVIDENCE_REFERENCE = 'docs/technical/runtime/lora-quick-import.md'
SUFFIX = '.safetensors'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8', newline='\n')


def measure(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plain(path):
    """Reject links and junctions, then return the regular file."""
    resolved = path.absolute()
    for part in [*reversed(resolved.parents), resolved]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked_path')
    if not resolved.is_file():
        raise ValueError('not_a_regular_file')
    return resolved


def readable_name(value):
    """Keep an upstream filename only when the catalogue accepts the literal form."""
    if not isinstance(value, str) or not value:
        return None
    try:
        catalogue.relative_path(value)
    except catalogue.CatalogueError:
        return None
    return value


def display_name(meta):
    organization = meta.get('organization') or {}
    name = (organization.get('official_name') or '').strip()
    if not name:
        raw = (meta.get('model_name') or '').strip()
        name = re.sub(r'^【[^】]*】', '', raw).split(' · ', 1)[0].strip()
    return name or Path(meta.get('file_name') or Path(meta.get('file_path', 'unnamed')).stem).stem


def build_asset(relative, sidecar_relative, digest, size, meta, preview_relative):
    parts = relative.split('/')
    if len(parts) < 6 or parts[:3] != ['ComfyUI', 'models', 'loras']:
        raise ValueError('unexpected_loras_layout')
    family_slug, category = parts[3], parts[4]
    if family_slug not in FAMILY_LABELS or not category or family_slug == 'other':
        raise ValueError('unreviewed_family_or_purpose')
    civitai = meta.get('civitai') or {}
    organization = meta.get('organization') or {}
    files = civitai.get('files') or []
    selected = files[0] if files and isinstance(files[0], dict) else {}
    model_id, version_id, file_id = civitai.get('modelId'), civitai.get('id'), selected.get('id')
    resolved = all(type(value) is int and value > 0 for value in (model_id, version_id, file_id))
    sources = []
    if resolved:
        sources.append({
            'provider': 'civitai',
            'page_url': 'https://civitai.com/models/%d?modelVersionId=%d' % (model_id, version_id),
            'download_url': 'https://civitai.com/api/download/models/%d' % version_id,
            'model_id': model_id, 'version_id': version_id, 'file_id': file_id,
            'filename': readable_name(selected.get('name')),
            'declared_sha256': ((selected.get('hashes') or {}).get('SHA256') or '').lower() or None,
            'revision': None,
            'evidence': [{'kind': EVIDENCE_KIND, 'reference': EVIDENCE_REFERENCE}],
            'availability': 'public_version_metadata_and_local_sha256_match_download_not_tested',
        })
    standardization = {
        'family_slug': family_slug,
        'family_label': FAMILY_LABELS[family_slug],
        'category': category,
        'display_name': display_name(meta),
        'version': organization.get('version') or None,
        'precision': organization.get('precision') or None,
        'source_identity': ('civitai:model=%d,version=%d,file=%d' % (model_id, version_id, file_id)
                            if resolved else 'unresolved:sha256=' + digest),
        'target_path': relative,
        'evidence': ['snapshot/inventory/model_sources.json', sidecar_relative],
    }
    companions = [sidecar_relative] + ([preview_relative] if preview_relative else [])
    return {
        'path': relative, 'bytes': size, 'kind': 'lora', 'captured_in_inventory': False,
        'observed_present': True, 'local_sha256': digest,
        'source_status': 'version_metadata' if resolved else 'unresolved',
        'family': FAMILY_LABELS[family_slug], 'sources': sources, 'companions': companions,
        'workflows': [], 'derivation': None,
        'notes': ['Registered from the already deployed and renamed runtime weight; the captured '
                  'path is the deployment path and the upstream original name stays in sources.',
                  'Placed before this capture by the 2026-11-14 MOSS library deploy or a later '
                  'LoRA Manager import; weights stay outside Git.'],
        'current_path': relative, 'standardization': standardization,
    }


def collect(runtime, existing_paths, existing_current, existing_sha):
    root = runtime / LORA_ROOT
    added, skipped = [], []
    for path in sorted(root.rglob('*' + SUFFIX)):
        relative = path.relative_to(runtime).as_posix()
        if relative.casefold() in existing_paths or relative.casefold() in existing_current:
            continue
        sidecar = path.with_suffix('.metadata.json')
        if not sidecar.is_file():
            skipped.append({'path': relative, 'reason': 'sidecar_missing'})
            continue
        try:
            file = plain(path)
            digest = measure(file)
            if digest in existing_sha:
                skipped.append({'path': relative, 'reason': 'digest_already_recorded'})
                continue
            meta = json.loads(sidecar.read_text(encoding='utf-8'))
            if (meta.get('sha256') or '').lower() != digest:
                skipped.append({'path': relative, 'reason': 'sidecar_sha256_mismatch'})
                continue
            preview_relative = None
            preview = meta.get('preview_url') or ''
            if preview:
                candidate = (runtime / preview.replace('\\', '/')).absolute()
                if candidate.is_file() and candidate.parent == path.parent:
                    preview_relative = candidate.relative_to(runtime).as_posix()
            asset = build_asset(relative, sidecar.relative_to(runtime).as_posix(), digest,
                                file.stat().st_size, meta, preview_relative)
            try:
                catalogue.relative_path(asset['path'])
                for companion in asset['companions']:
                    catalogue.relative_path(companion)
            except catalogue.CatalogueError:
                skipped.append({'path': relative, 'reason': 'invalid_catalogue_path'})
                continue
            added.append(asset)
        except Exception as error:
            reason = str(error) if isinstance(error, ValueError) else type(error).__name__
            skipped.append({'path': relative, 'reason': reason})
    return added, skipped


def current_branch():
    """Read the branch name; a Git binary is optional on this host."""
    try:
        return subprocess.check_output(['git', 'branch', '--show-current'], cwd=REPO, text=True).strip()
    except OSError:
        head = (REPO / '.git' / 'HEAD').read_text(encoding='utf-8').strip()
        prefix = 'ref: refs/heads/'
        return head[len(prefix):] if head.startswith(prefix) else ''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--evidence-root', type=Path,
                        default=Path(os.environ.get('LOCALAPPDATA', str(Path.home())))
                        / 'ComfyUI-LoRA-Imports')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    manifest_path = REPO / 'snapshot/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    runtime = Path(args.runtime or manifest['source_root']).absolute()
    evidence = args.evidence_root.absolute() / ('register-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    if evidence.is_relative_to(REPO) or runtime.is_relative_to(REPO):
        raise ValueError('private_inputs_must_stay_outside_git')
    evidence.mkdir(parents=True, exist_ok=False)
    cat, _, _ = catalogue.checked_catalogue(REPO)
    existing_paths = {item['path'].casefold() for item in cat['assets']}
    existing_current = {catalogue.current_path(item).casefold() for item in cat['assets']}
    existing_sha = {item['local_sha256'].lower() for item in cat['assets']
                    if item.get('observed_present') and item.get('local_sha256')}
    added, skipped = collect(runtime, existing_paths, existing_current, existing_sha)
    save(evidence / 'plan.json', {'added': added, 'skipped': skipped})
    print(json.dumps({'added': len(added), 'skipped': skipped,
                      'bytes': sum(item['bytes'] for item in added),
                      'receipt': str(evidence)}, ensure_ascii=False), flush=True)
    if not args.apply or not added:
        return
    branch = current_branch()
    if not branch or branch == 'main':
        raise ValueError('apply_requires_development_branch')
    proposed = json.loads(json.dumps(cat))
    proposed['assets'].extend(added)
    proposed['summary'] = catalogue.compute_summary(proposed)
    inventory, invsha = catalogue.read_json(REPO / catalogue.INVENTORY)
    catalogue.validate_catalogue(proposed, inventory, invsha,
                                 catalogue.digest(REPO / catalogue.WORKFLOW_SOURCE))
    save(REPO / catalogue.CATALOGUE, proposed)
    catalogue.render(REPO)
    for item in manifest['metadata_files']:
        if item['path'] == 'inventory/model_sources.json':
            item.update(sha256=catalogue.digest(REPO / catalogue.CATALOGUE),
                        bytes=(REPO / catalogue.CATALOGUE).stat().st_size)
    save(manifest_path, manifest)
    save(evidence / 'result.json', {'registered': len(added), 'skipped': skipped,
                                    'runtime_untouched': True, 'manager_rescan': False,
                                    'gpu_tested': False})


if __name__ == '__main__':
    main()
