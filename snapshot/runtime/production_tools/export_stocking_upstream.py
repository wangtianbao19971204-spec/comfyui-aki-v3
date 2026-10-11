"""Export a standalone ComfyUI plugin with a fixed, unmodified upstream copy.

Develop here and export this allowlist to a fresh directory for installation and
publication, without overlaying the upstream repository. Only the exact reviewed
showcase panels in the pinned manifest may be copied from outside the repository.
Never exports input collections, weights, settings, private workflows or Git data.
"""
import argparse
import hashlib
import json
from pathlib import Path

from build_stocking_workflow import build

PLUGIN = Path(__file__).resolve().parents[1] / 'ComfyUI/custom_nodes/ComfyUI-Stocking-Texture'
README = Path(__file__).with_name('stocking_upstream_README.md')
ROOT_README = Path(__file__).with_name('stocking_independent_README.md')
SHOWCASE = Path(__file__).with_name('stocking_showcase.json')
SHOWCASE_README = Path(__file__).with_name('stocking_showcase.md')
FILES = (
    '__init__.py', 'nodes.py', 'engine.py', 'rendering.py', 'studio.py', 'studio_api.py',
    'studio_assets.py', 'studio_store.py', 'studio_models.py', 'studio_nodes.py',
    'requirements.txt', 'MODEL_SOURCES.json', 'UPSTREAM.json', 'sync_upstream.py',
    'web/stocking_texture.js', 'web/editor_model.js', 'web/stocking_texture.css', 'web/stocking_studio.js',
    'tests/test_nodes.py', 'tests/test_studio.py', 'tests/test_studio_models.py', 'tests/test_issue3.py', 'tests/test_request_contract.py', 'tests/test_retention.py', 'tests/test_editor.cjs', 'tests/test_studio_editor.cjs',
    'tests/compare_upstream.py', 'tests/studio_compare.py', 'tests/model_acceptance.py',
    'tests/feature_acceptance.py', 'tests/bend_acceptance.py', 'tests/parity_matrix.py', 'tests/api_parity.py',
    'tests/image_acceptance.py', 'tests/isolated_acceptance.py',
    'vendor/__init__.py', 'vendor/i18n.py',
)
ROOT_ENTRY = '''"""Optional ComfyUI entry point; standalone imports start no host services."""
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
try:
    import folder_paths as _folder_paths
    from server import PromptServer as _PromptServer
except ModuleNotFoundError as exc:
    if exc.name not in ("folder_paths", "server"):
        raise
else:
    from .integrations.comfyui import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./integrations/comfyui/web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
'''


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Adapter export anchor changed: ' + before)
    return text.replace(before, after, 1)


def reviewed_showcase(directory):
    """Read only the explicitly reviewed, hash-pinned publication assets."""
    directory = Path(directory).resolve(strict=True)
    manifest = json.loads(SHOWCASE.read_text(encoding='utf-8'))
    data = {}
    for row in manifest['files']:
        name = row['name']
        if Path(name).name != name or '/' in name or '\\' in name or not name.endswith('.png'):
            raise ValueError('Invalid showcase filename')
        source = directory / name
        if source.is_symlink() or source.resolve() != source:
            raise ValueError('Showcase links are not allowed: ' + name)
        content = source.read_bytes()
        if len(content) != row['bytes'] or hashlib.sha256(content).hexdigest() != row['sha256']:
            raise ValueError('Showcase changed; review before publication: ' + name)
        data['integrations/comfyui/docs/images/' + name] = content
    data['integrations/comfyui/SHOWCASE.json'] = SHOWCASE.read_bytes()
    data['integrations/comfyui/SHOWCASE.md'] = SHOWCASE_README.read_text(encoding='utf-8')
    return data


def export(upstream, out, showcase):
    upstream, out = Path(upstream).resolve(), Path(out).resolve()
    provenance = json.loads((PLUGIN/'UPSTREAM.json').read_text(encoding='utf-8'))
    dependency = {}
    for row in provenance['files']:
        path = upstream/'stocking'/row['file']
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row['sha256']:
            raise ValueError('Upstream changed; rebase and revalidate: ' + row['file'])
        dependency['integrations/comfyui/upstream/stocking/' + row['file']] = content
    license_bytes = (upstream/'LICENSE').read_bytes()
    if hashlib.sha256(license_bytes).hexdigest() != provenance['license_sha256']:
        raise ValueError('Upstream license changed; review before publication')
    data = reviewed_showcase(showcase)
    data.update(dependency)
    data.update({'__init__.py': ROOT_ENTRY, 'integrations/__init__.py': '"""Optional host integrations."""\n',
            'LICENSE': (PLUGIN/'LICENSE').read_bytes(),
            'integrations/comfyui/upstream/LICENSE': license_bytes,
            '.gitignore': '__pycache__/\n.pytest_cache/\n*.pyc\n',
            '.gitattributes': '# Fixed upstream blobs must survive Windows core.autocrlf=true.\n* text=auto eol=lf\n*.png binary\n*.ico binary\n',
            'README.md': ROOT_README.read_text(encoding='utf-8').replace('{{UPSTREAM_COMMIT}}', provenance['commit']),
            'integrations/comfyui/README.md': README.read_text(encoding='utf-8').replace('{{UPSTREAM_COMMIT}}', provenance['commit'])})
    for name in FILES:
        text = (PLUGIN/name).read_text(encoding='utf-8')
        if name == 'studio.py':
            # The standalone distribution starts in the original rendering mode.
            text = replace_once(text, 'self.project.get("dark_adapt", True)',
                                'self.project.get("dark_adapt", False)')
        data['integrations/comfyui/'+name] = text
    workflow = build()
    workflow['extra'].pop('uap_workbench')
    for node in workflow['nodes']:
        node['properties'].pop('uap_layout_group', None)
    workflow['nodes'][-1]['widgets_values'] = [
        'Open the full editor and import PNG/JPG/PSD (or connect one IMAGE and run once).\n'
        'Select the fabric, correct the mask, draw course guides, choose a style.\n'
        'Apply to node, close the editor, then queue this independent workflow.\n'
        'SaveImage writes the finished RGB image and a separate RGBA fabric layer.\n'
        'Export guide PSD from the editor. No diffusion model, upscaler or workbench extension is required.\n'
        'For matching standalone output, keep Dark adaptation OFF.']
    data['integrations/comfyui/examples/stocking-repair.json'] = json.dumps(workflow,ensure_ascii=False,indent=2)+'\n'
    out.mkdir(parents=True, exist_ok=False)
    for name, content in data.items():
        dest=out/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        if isinstance(content, bytes):
            dest.write_bytes(content)
        else:
            dest.write_text(content,encoding='utf-8',newline='\n')
    return {'upstream_commit':provenance['commit'],'files':[
        {'path':name,'sha256':hashlib.sha256((out/name).read_bytes()).hexdigest()} for name in sorted(data)],
        'dependency_mode':'fixed-raw-blob-copy','private_history_exported':False,
        'upstream_files_modified':False,
        'upstream_dark_adaptation_default':False,
        'reviewed_showcase_files': [r['name'] for r in json.loads(SHOWCASE.read_text(encoding='utf-8'))['files']]}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--showcase-dir',type=Path,required=True,
                   help='External directory containing the exact hash-pinned showcase panels')
    p.add_argument('--receipt',type=Path,required=True)
    a=p.parse_args()
    if a.receipt.exists():
        raise SystemExit('Receipt exists; preserve it and choose another path')
    report=export(a.upstream,a.out,a.showcase_dir)
    with a.receipt.open('x',encoding='utf-8') as file:
        json.dump(report,file,ensure_ascii=False,indent=2)
    print(json.dumps({'files':len(report['files']),'upstream_commit':report['upstream_commit'],'out':str(a.out)}))
