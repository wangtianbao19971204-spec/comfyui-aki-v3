"""Reconcile catalogue presence with the runtime filesystem.

Deleted weights stay in the catalogue as history: the record keeps its captured
path, bytes, sources and notes, while presence, local SHA-256 and the placement
contract are cleared, exactly like earlier reviewed deletions.  The tool never
touches the runtime, never re-downloads, and never restores a deleted weight.

Default: report only.  ``--apply`` rewrites the catalogue, its manifest entry and
the rendered document after the full catalogue contract passes, and writes a
receipt outside Git listing every record it changed.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path

import model_sources as catalogue

REPO = Path(__file__).resolve().parents[1]
AUTHORIZED_PURGE = ('ComfyUI/models/loras/anima/', 'ComfyUI/models/loras/anima-2.9b/',
                    'ComfyUI/models/diffusion_models/anima/', 'ComfyUI/models/diffusion_models/anima-2.9b/',
                    'ComfyUI/models/diffusion_models/qwen-image-2.1/',
                    'ComfyUI/models/checkpoints/anima/',
                    'ComfyUI/models/controlnet/anima-lllite-',
                    'ComfyUI/models/text_encoders/anima_baseV10_txt',
                    'ComfyUI/models/text_encoders/qwen3vl_8b_bf16',
                    'ComfyUI/models/vae/qwen_image')
PURGE_NOTE = ('2026-11-18 presence check: this path no longer exists in the runtime. It was removed by '
              'the user-authorized 2026-10-24 Anima/Qwen series purge; the private deletion receipt '
              'anima-assets-deletion-20261024 and the pre-deletion manifest are the only records kept.')
OTHER_NOTE = ('2026-11-18 presence check: this path no longer exists in the runtime. It was deleted through '
              'the deployed LoRA Manager after the 2026-10-24 purge; the pre-deletion path, size and digest '
              'stay in this record and in the reconciliation receipt.')


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def reason_for(path):
    return PURGE_NOTE if path.startswith(AUTHORIZED_PURGE) else OTHER_NOTE


def missing(asset, runtime):
    if not asset['observed_present']:
        return False
    target = Path(runtime) / (asset.get('current_path') or asset['path'])
    return not target.is_file()


def mark_missing(asset):
    """Clear only the fields the contract forbids on a missing record."""
    updated = dict(asset)
    updated['observed_present'] = False
    updated['local_sha256'] = None
    updated.pop('current_path', None)
    updated.pop('standardization', None)
    note = reason_for(asset['path'])
    if note not in updated['notes']:
        updated['notes'] = [*updated['notes'], note]
    return updated


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
    evidence = args.evidence_root.absolute() / ('presence-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    if evidence.is_relative_to(REPO) or runtime.is_relative_to(REPO):
        raise ValueError('private_inputs_must_stay_outside_git')
    evidence.mkdir(parents=True, exist_ok=False)
    cat, _, _ = catalogue.checked_catalogue(REPO)
    changed = []
    for asset in cat['assets']:
        if missing(asset, runtime):
            changed.append({'path': asset['path'], 'kind': asset['kind'], 'bytes': asset['bytes'],
                            'family': asset['family'], 'local_sha256': asset['local_sha256'],
                            'previous_current_path': asset.get('current_path'),
                            'reason': 'authorized_purge' if reason_for(asset['path']) == PURGE_NOTE else 'manager_delete'})
    save(evidence / 'missing.json', changed)
    print(json.dumps({'missing': len(changed), 'bytes': sum(item['bytes'] for item in changed),
                      'by_kind': {kind: sum(1 for item in changed if item['kind'] == kind)
                                  for kind in sorted({item['kind'] for item in changed})},
                      'receipt': str(evidence)}, ensure_ascii=False), flush=True)
    if not args.apply or not changed:
        return
    proposed = json.loads(json.dumps(cat))
    targets = {item['path'] for item in changed}
    proposed['assets'] = [mark_missing(asset) if asset['path'] in targets else asset
                          for asset in proposed['assets']]
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
    save(evidence / 'result.json', {'reconciled': len(changed), 'runtime_untouched': True,
                                    'weights_restored': 0, 'gpu_tested': False})


if __name__ == '__main__':
    main()
