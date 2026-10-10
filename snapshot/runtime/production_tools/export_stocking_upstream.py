"""Export a reviewed ComfyUI adapter payload without any maintenance-repo history.

Develop here, export to a fresh directory, then overlay this allowlist onto a
clean public upstream checkout for tests and publication. Never exports input
images, weights, user settings, private workflows, or the maintenance Git data.
"""
import argparse
import hashlib
import json
from pathlib import Path

from build_stocking_workflow import build

PLUGIN = Path(__file__).resolve().parents[1] / 'ComfyUI/custom_nodes/ComfyUI-Stocking-Texture'
README = Path(__file__).with_name('stocking_upstream_README.md')
FILES = (
    '__init__.py', 'nodes.py', 'engine.py', 'rendering.py', 'studio.py', 'studio_api.py',
    'studio_assets.py', 'studio_store.py', 'studio_models.py', 'studio_nodes.py',
    'requirements.txt', 'MODEL_SOURCES.json', 'UPSTREAM.json',
    'web/stocking_texture.js', 'web/editor_model.js', 'web/stocking_texture.css', 'web/stocking_studio.js',
    'tests/test_nodes.py', 'tests/test_studio.py', 'tests/test_editor.cjs', 'tests/test_studio_editor.cjs',
    'tests/compare_upstream.py', 'tests/studio_compare.py', 'tests/model_acceptance.py',
    'tests/feature_acceptance.py', 'tests/bend_acceptance.py', 'tests/parity_matrix.py', 'tests/api_parity.py',
    'tests/image_acceptance.py', 'tests/isolated_acceptance.py',
    'vendor/i18n.py',
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
BRIDGE = '''"""Reuse upstream modules under a host-local namespace, without copying them.

Only i18n is overridden here: standalone settings must not be shared by ComfyUI
users. Keeping a separate module namespace avoids patching stocking globals.
"""
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "stocking"
__path__.append(str(SOURCE_ROOT))
'''


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Adapter export anchor changed: ' + before)
    return text.replace(before, after, 1)


def export(upstream, out):
    upstream, out = Path(upstream).resolve(), Path(out).resolve()
    provenance = json.loads((PLUGIN/'UPSTREAM.json').read_text(encoding='utf-8'))
    for row in provenance['files']:
        path = upstream/'stocking'/row['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Upstream changed; rebase and revalidate: ' + row['file'])
    if (upstream/'__init__.py').exists() or (upstream/'integrations/comfyui').exists():
        raise ValueError('Upstream already has an integration; inspect instead of overwriting')
    data = {'__init__.py': ROOT_ENTRY, 'integrations/__init__.py': '"""Optional host integrations."""\n',
            'integrations/comfyui/vendor/__init__.py': BRIDGE,
            'integrations/comfyui/README.md': README.read_text(encoding='utf-8')}
    for name in FILES:
        text = (PLUGIN/name).read_text(encoding='utf-8')
        if name == 'studio_assets.py':
            text = replace_once(text, 'Path(__file__).parent / "vendor/static"',
                                'Path(__file__).resolve().parents[2] / "stocking/static"')
        elif name == 'vendor/i18n.py':
            text = replace_once(text, 'Path(__file__).parent / "static/i18n/en.json"',
                                'Path(__file__).resolve().parents[3] / "stocking/static/i18n/en.json"')
        elif name == 'tests/test_nodes.py':
            text = replace_once(text, '(ROOT / "vendor" / item["file"])',
                                '(ROOT.parents[1] / "stocking" / item["file"])')
        elif name == 'studio.py':
            # An upstream proposal must start in the original rendering mode.
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
    data['README.md'] = (upstream/'README.md').read_text(encoding='utf-8') + '\n## ComfyUI 实验性接入\n\n可选的 AI 编写接入与独立丝袜修复工作流见 [ComfyUI 说明](integrations/comfyui/README.md)。原桌面启动方式保持不变。\n'
    data['README.en.md'] = (upstream/'README.en.md').read_text(encoding='utf-8') + '\n## Experimental ComfyUI integration\n\nSee the [AI-written optional integration and independent repair workflow](integrations/comfyui/README.md). The standalone launcher is unchanged.\n'
    out.mkdir(parents=True, exist_ok=False)
    for name, content in data.items():
        dest=out/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(content,encoding='utf-8',newline='\n')
    return {'upstream_commit':provenance['commit'],'files':[
        {'path':name,'sha256':hashlib.sha256((out/name).read_bytes()).hexdigest()} for name in sorted(data)],
        'duplicated_upstream_core_or_ui':False,'private_history_exported':False,
        'upstream_dark_adaptation_default':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--receipt',type=Path,required=True)
    a=p.parse_args()
    if a.receipt.exists():
        raise SystemExit('Receipt exists; preserve it and choose another path')
    report=export(a.upstream,a.out)
    with a.receipt.open('x',encoding='utf-8') as file:
        json.dump(report,file,ensure_ascii=False,indent=2)
    print(json.dumps({'files':len(report['files']),'upstream_commit':report['upstream_commit'],'out':str(a.out)}))
