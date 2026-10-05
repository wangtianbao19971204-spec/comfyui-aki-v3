import collections
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

from guard import ROOT, OUT, PLAN, get, read, sha, write

CUSTOM = ROOT / 'ComfyUI/custom_nodes'
WB = CUSTOM / 'ComfyUI-Unified-Prompt-Workbench'
profiles = read(ROOT / 'production_tools/profiles.json')
base = read(OUT / 'baseline.json')
cmd = base['live']['owners'][0]['cmdline']
start = cmd.index('--whitelist-custom-nodes') + 1
allowlist = []
for value in cmd[start:]:
    if value.startswith('--'):
        break
    allowlist.append(value)
assert allowlist == profiles['production']
info = json.loads(get('/object_info'))
extensions = json.loads(get('/extensions'))
modules = read(WB / 'modules.json')['modules']
write(OUT / 'registered_nodes.json', {k: {x: v.get(x) for x in ['python_module', 'category', 'output_node']} for k, v in info.items()})
write(OUT / 'extensions.json', extensions)


def owner(t):
    module = info.get(t, {}).get('python_module', '')
    return module.removeprefix('custom_nodes.') if module.startswith('custom_nodes.') else 'ComfyUI core' if t in info else None


workflows = []
used = collections.defaultdict(set)
main_used = collections.defaultdict(set)
virtual = set()
missing = set()
for path in sorted((ROOT / 'ComfyUI/user/default/workflows').glob('*.json')):
    data = read(path)
    if 'nodes' not in data:
        continue
    definitions = {s['id']: s for s in data.get('definitions', {}).get('subgraphs', [])}
    nodes = {n['id']: n for n in data['nodes']}

    def expand(ns, stack=()):
        result = []
        for node in ns:
            t = node['type']
            row = dict(id=node['id'], type=t, mode=node.get('mode', 0), subgraph_path=list(stack))
            if t in definitions:
                assert t not in stack
                row['kind'] = 'subgraph'
                result.append(row)
                result.extend(expand(definitions[t]['nodes'], (*stack, t)))
            elif t in info:
                result.append(dict(row, kind='backend', plugin=owner(t)))
            else:
                virtual.add(t)
                result.append(dict(row, kind='frontend_or_missing'))
        return result

    branches = data.get('extra', {}).get('uap_workbench', {}).get('branches') or [dict(id=path.stem, label=path.stem, nodeIds=list(nodes))]
    rows = []
    for branch in branches:
        expanded = expand([nodes[i] for i in branch['nodeIds']])
        deps = collections.Counter(n['plugin'] for n in expanded if n['kind'] == 'backend')
        row = dict(id=branch['id'], label=branch['label'], node_count=len(expanded), plugins=dict(sorted(deps.items())), nodes=expanded)
        rows.append(row)
    all_nodes = expand(data['nodes'])
    primary = path.name == 'UAP统一生产工作台_v2.json' or path.name.startswith(('生产套件_01_', '生产套件_02_', '生产套件_03_'))
    for n in all_nodes:
        if n['kind'] == 'backend':
            used[n['plugin']].add(path.name)
            if primary:
                main_used[n['plugin']].add(path.name)
    workflows.append(dict(file=str(path), sha256=sha(path), primary=primary, branches=rows, all_nodes=all_nodes))
write(OUT / 'workflow_dependencies.json', workflows)

plugin_rows = []
for directory in sorted(CUSTOM.iterdir()):
    if not directory.is_dir() or directory.name.startswith(('.', '__')):
        continue
    name = directory.name
    registered = sorted(t for t in info if owner(t) == name)
    ext = [e for e in extensions if unquote(e).startswith('/extensions/' + name + '/')]
    bundled = next((m for m in modules if m['directory'] == name), None)
    module_path = WB / 'modules' / name if bundled else directory
    git = None
    if (module_path / '.git').exists():
        result = subprocess.run(['git', '-C', str(module_path), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10)
        git = result.stdout.strip() if result.returncode == 0 else None
    identity = {str(p.relative_to(module_path)): sha(p) for p in [module_path / '__init__.py', module_path / 'pyproject.toml', module_path / 'package.json', module_path / 'requirements.txt'] if p.is_file()}
    version = None
    pyproject = module_path / 'pyproject.toml'
    if pyproject.is_file():
        import tomllib
        try:
            version = tomllib.loads(pyproject.read_text('utf8')).get('project', {}).get('version')
        except (ValueError, UnicodeError):
            pass
    if name.endswith('.disabled'):
        category = '停用回滚包'
    elif bundled:
        category = '统一工作台内置模块；同名顶层目录不加载'
    elif name in main_used:
        category = '生产工作流必需'
    elif name in allowlist:
        category = '按场景使用；生产保留'
    elif name == 'ComfyUI-Manager' or name == 'comfyui-dev-utils':
        category = '独立维护或诊断'
    else:
        category = '历史兼容；生产不加载'
    plugin_rows.append(dict(plugin=name, production=name in allowlist, diagnostic=name in profiles['diagnostic'], category=category, registered_nodes=registered, extension_count=len(ext), workflows=sorted(used.get(name, [])), primary_workflows=sorted(main_used.get(name, [])), bundled_module_key=bundled['key'] if bundled else None, effective_path=str(module_path), git_commit=git, declared_version=version, identity_hashes=identity))
write(OUT / 'plugin_inventory.json', dict(allowlist=allowlist, matches_saved_profile=True, registered_count=len(info), modules=modules, plugins=plugin_rows))

# Only read the log opened by the verified current service; historical import failures are not current failures.
log = ROOT / 'benchmark_reports/2026-10-03_runtime_phase2/production.log'
import psutil
assert str(log) in {x.path for x in psutil.Process(base['live']['owners'][0]['pid']).open_files()}
text = log.read_text('utf8', errors='replace')
lines = text.splitlines()
startup_end = next(i for i, s in enumerate(lines) if 'To see the GUI go to:' in s)
startup = lines[:startup_end + 1]
issues = [dict(line=i + 1, text=s) for i, s in enumerate(lines) if re.search(r'\[ERROR\]|Traceback|IMPORT FAILED|Cannot import|\[WARNING\]', s)]
write(OUT / 'runtime_log_review.json', dict(path=str(log), sha256=sha(log), reviewed_lines=len(lines), startup_end_line=startup_end + 1, startup_import_errors=[x for x in issues if x['line'] <= startup_end + 1], issues=issues, inactive_legacy=['ComfyUI-LTXVideo', 'llama-cpp_vllm'], limits='No service restart or new inference. Current boot log and live registration evidence.'))
summary = dict(workflow_count=len(workflows), primary_count=sum(x['primary'] for x in workflows), uap_branch_count=len(next(x for x in workflows if Path(x['file']).name == 'UAP统一生产工作台_v2.json')['branches']), registered_count=len(info), allowlist_count=len(allowlist), plugin_directories=len(plugin_rows), frontend_or_missing=sorted(virtual), required_plugins=sorted(main_used), startup_import_errors=len([x for x in issues if x['line'] <= startup_end + 1]), runtime_log_issues=issues)
write(OUT / 'inventory_summary.json', summary)
print(json.dumps(summary, ensure_ascii=False, indent=2))
