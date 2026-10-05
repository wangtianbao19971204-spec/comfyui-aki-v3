import json
from pathlib import Path
from collections import Counter

ROOT = Path(r'G:\ComfyUI-aki-v3')
OUT = Path(__file__).parent
WF = ROOT / 'ComfyUI/user/default/workflows'
paths = [WF / 'UAP统一生产工作台_v2.json', *sorted(WF.glob('生产套件_0[123]*v2.json'))]
reports = []
for path in paths:
    data = json.loads(path.read_text('utf8'))
    nodes = {n['id']: n for n in data['nodes']}
    links = {e[0]: e for e in data['links']}
    def upstream(node_id, visited=None):
        visited = set() if visited is None else visited
        if node_id in visited:
            return []
        visited.add(node_id)
        n = nodes[node_id]
        result = [{'id': n['id'], 'type': n['type'], 'title': n.get('title'), 'mode': n.get('mode', 0),
                   'widgets': n.get('widgets_values'), 'inputs': [
                       {'name': i['name'], 'link': links.get(i.get('link'))} for i in n.get('inputs', [])]}]
        for i in n.get('inputs', []):
            edge = links.get(i.get('link'))
            if edge:
                result += upstream(edge[1], visited)
        return result
    branches = data.get('extra', {}).get('uap_workbench', {}).get('branches') or [
        {'id': path.stem, 'label': path.stem, 'nodeIds': list(nodes)}]
    report = {'file': str(path), 'nodes': len(nodes), 'links': len(links),
              'sw00b_nodes': [n['id'] for n in nodes.values() if 'SW-00B' in n.get('title', '')], 'branches': []}
    for b in branches:
        ns = [nodes[i] for i in b['nodeIds']]
        samplers = [n for n in ns if n['type'] in ['KSampler', 'KSamplerAdvanced']]
        row = {'id': b['id'], 'label': b['label'], 'saved_modes': dict(Counter(n.get('mode', 0) for n in ns)),
               'activation_modes': b.get('modes'), 'samplers': [],
               'outputs': [{'id': n['id'], 'type': n['type']} for n in ns if n['type'] in ['SaveImage', 'PreviewImage', 'Image Save'] or 'Save' in n['type']],
               'node_types': dict(Counter(n['type'] for n in ns))}
        for n in samplers:
            entry = {'id': n['id'], 'title': n.get('title'), 'widgets': n.get('widgets_values'), 'inputs': {}}
            for i in n.get('inputs', []):
                if i['name'] in ['positive', 'negative', 'model']:
                    e = links.get(i.get('link'))
                    entry['inputs'][i['name']] = {'edge': e, 'upstream': upstream(e[1]) if e else []}
            row['samplers'].append(entry)
        report['branches'].append(row)
    reports.append(report)
(OUT / 'workflow_paths.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf8')
for r in reports:
    print(Path(r['file']).name, 'SW00B', r['sw00b_nodes'])
    for b in r['branches']:
        print(' ', b['id'], b['label'], 'saved', b['saved_modes'], 'samplers', [n['id'] for n in b['samplers']])
        if not b['samplers']:
            print('  nodes', b['node_types'])
        for s in b['samplers']:
            for name, x in s['inputs'].items():
                print(' ', name, ' '.join(f"{n['id']}:{n['type']}" for n in x['upstream']))
