import hashlib
import re
import urllib.request
from pathlib import Path

from guard import ROOT, OUT, get, read, sha, write, live

WB = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'
inventory = read(OUT / 'plugin_inventory.json')
workflows = read(OUT / 'workflow_dependencies.json')
browser = read(OUT / 'browser_registration.json')['result']['value']
primary = read(OUT / 'browser_primary_nodes.json')['result']['value']
assert primary['requiredFrontendTypeCount'] == 74 and not primary['missing']
assert not primary['duplicateExtensionNames'] and primary['pixai'] and not primary['wd14']
assert read(OUT / 'browser_cleanup.json')['remainingTabs'] == []

frontend = {t for t, exists in browser['registry'].items() if exists}
missing = []
for row in workflows:
    for branch in row['branches']:
        for node in branch['nodes']:
            if node['kind'] == 'frontend_or_missing':
                node['kind'] = 'frontend' if node['type'] in frontend else 'missing'
    for node in row['all_nodes']:
        if node['kind'] == 'frontend_or_missing':
            node['kind'] = 'frontend' if node['type'] in frontend else 'missing'
        if node['kind'] == 'missing':
            missing.append(dict(file=row['file'], type=node['type'], id=node['id'], primary=row['primary']))
assert not any(x['primary'] for x in missing)
assert {Path(x['file']).name for x in missing} == {'▶▷Krea2-高清生图优化流(整合).json'}
assert {x['type'] for x in missing} == {'GetImageSize+', 'SimpleMathDual+', 'LoaderGGUF'}
write(OUT / 'workflow_dependencies.json', workflows)

protected_paths = [Path('C:/Users/Administrator/AppData/Local/ComfyUI-LoRA-Manager/settings.json')]
protected_paths += list(Path('C:/Users/Administrator/AppData/Local/ComfyUI-LoRA-Manager/stats').glob('*.json'))
protected_paths += list((ROOT / 'ComfyUI').glob('extra_model_paths*.yaml'))
protected = {str(p): sha(p) for p in protected_paths}
write(OUT / 'additional_config_before.json', protected)
api = []
for route in ['/unified-workbench/status', '/api/lm/version-info', '/api/lm/init-status', '/api/lm/downloads/queue', '/api/lm/downloads/history?limit=1&offset=0', '/api/lm/backup/status']:
    with urllib.request.urlopen('http://127.0.0.1:8188' + route, timeout=30) as response:
        import json
        data = json.load(response)
        assert response.status == 200 and data.get('success', True) is not False
        record = dict(route=route, status=response.status, success=data.get('success'), response_keys=list(data))
        if route.endswith('version-info'):
            assert data['version'] == '1.2.4-stable'
            record['version'] = data['version']
        if route.endswith('init-status'):
            assert data['status'] == 'complete' and data['progress'] == 100
            record.update(initialization=data['status'], progress=data['progress'])
        api.append(record)
write(OUT / 'api_acceptance.json', api)

extensions = read(OUT / 'extensions.json')
served = []
targets = [(WB / 'modules/comfyui-lora-manager/web/comfyui', 'comfyui-lora-manager', n) for n in ['workflow_registry.js', 'loras_widget.js', 'autocomplete.js']]
targets += [(ROOT / 'ComfyUI/custom_nodes/ComfyUI-PixAI-Tagger/web', 'ComfyUI-PixAI-Tagger', 'pixai_tagger.js')]
for folder, plugin, name in targets:
    path = folder / name
    routes = [r for r in extensions if r.startswith('/extensions/' + plugin + '/') and r.endswith('/' + name)]
    assert len(routes) == 1
    disk = sha(path)
    remote = hashlib.sha256(get(routes[0])).hexdigest()
    assert disk == remote
    served.append(dict(path=str(path), route=routes[0], disk=disk, served=remote))
write(OUT / 'compatibility_assets.json', served)

residuals = []
template_parity = []


def diff_paths(a, b, prefix=''):
    if type(a) is not type(b):
        return [prefix]
    if isinstance(a, dict):
        return [p for k in a.keys() | b.keys() for p in (diff_paths(a[k], b[k], prefix + '/' + str(k)) if k in a and k in b else [prefix + '/' + str(k)])]
    if isinstance(a, list):
        return [prefix + '/length'] if len(a) != len(b) else [p for i, (x, y) in enumerate(zip(a, b)) for p in diff_paths(x, y, prefix + '/' + str(i))]
    return [] if a == b else [prefix]


for folder in ['ComfyUI/user/default/workflows', 'production_tools/templates']:
    for path in (ROOT / folder).glob('*.json'):
        if 'wd14' in path.read_text('utf8').lower():
            residuals.append(str(path))
assert not residuals
for wf in workflows:
    if wf['primary']:
        template = ROOT / 'production_tools/templates' / Path(wf['file']).name
        current_data = read(Path(wf['file']))
        template_data = read(template)
        definitions = template_data.get('definitions', {}).get('subgraphs', [])
        available = set(read(OUT / 'registered_nodes.json')) | frontend | {s['id'] for s in definitions}
        template_nodes = template_data['nodes'] + [n for s in definitions for n in s['nodes']]
        unresolved = sorted({n['type'] for n in template_nodes} - available)
        assert not unresolved
        current_ids = {n['id'] for n in current_data['nodes']}
        extra_nodes = [dict(id=n['id'], type=n['type']) for n in template_data['nodes'] if n['id'] not in current_ids]
        template_parity.append(dict(workflow=wf['file'], template=str(template), equal=sha(template) == wf['sha256'], different_fields=diff_paths(current_data, template_data), missing_types=unresolved, template_only_nodes=extra_nodes))
write(OUT / 'template_parity.json', template_parity)

# Record the exact currently served scripts that import deprecated core APIs.
deprecated = []
resources = browser['resourceScripts']
for resource in resources:
    route = resource.removeprefix('http://127.0.0.1:8188')
    source = get(route).decode('utf8', errors='replace')
    imports = [s for s in ['scripts/ui.js', 'extensions/core/clipspace.js', 'scripts/ui/components/button.js'] if s in source]
    if imports:
        deprecated.append(dict(route=route, imports=imports, served_sha256=hashlib.sha256(source.encode('utf8')).hexdigest()))
write(OUT / 'deprecated_api_consumers.json', deprecated)

for module in inventory['modules']:
    stub = ROOT / 'ComfyUI/custom_nodes' / module['directory'] / '__init__.py'
    content = stub.read_text('utf8')
    assert 'NODE_CLASS_MAPPINGS = {}' in content and 'Implementation is owned by ComfyUI-Unified-Prompt-Workbench' in content
    module['top_level_compatibility_stub_sha256'] = sha(stub)

after = {str(p): sha(p) for p in protected_paths}
assert protected == after
write(OUT / 'additional_config_after.json', after)
current = live()
assert current['owners'] == read(OUT / 'baseline.json')['live']['owners']
assert not current['queue']['queue_running'] and not current['queue']['queue_pending']
write(OUT / 'acceptance_summary.json', dict(status='LIVE_RUNTIME_AND_BROWSER_ACCEPTANCE_PASS', registered_count=inventory['registered_count'], production_allowlist_count=len(inventory['allowlist']), production_backend_plugins=sum(bool(r['primary_workflows']) for r in inventory['plugins']), optional_production_plugins=[r['plugin'] for r in inventory['plugins'] if r['production'] and not r['primary_workflows']], primary_frontend_types=74, missing_primary=[], legacy_missing=missing, template_parity=template_parity, wd14_residuals=residuals, modules=inventory['modules'], api_count=len(api), compatibility_assets=len(served), deprecation_consumer_count=len(deprecated), additional_configs_unchanged=len(after), no_runtime_change=True, no_restart=True, no_generation=True, no_model_unload=True, limits=['Current registration, GET API, served resources and existing boot log only; no new isolated startup or inference.', 'Five builtin modules share the Unified Workbench backend owner; their old top-level directories are empty compatibility stubs.', 'Legacy Krea2 reference remains missing three types; previously documented and outside maintained production scope.', 'Three deprecated core API paths remain supported; consumers are recorded for future compatibility maintenance, not evidence of current failure.', 'No user workflow was loaded, edited, saved or queued by this run; no application storage was explicitly modified.']))
print({'status': 'pass', 'api': len(api), 'served': len(served), 'deprecated_consumers': len(deprecated), 'additional_configs': len(after)})
