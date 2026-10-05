import collections
import hashlib
import json
import pathlib
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(r'G:\ComfyUI-aki-v3')
OUT = pathlib.Path(__file__).parent

def get(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)

CONTROL_TYPES = {'KSampler', 'KSamplerAdvanced', 'UNETLoader', 'CLIPLoader', 'VAELoader', 'CheckpointLoaderSimple', 'UpscaleModelLoader', 'UnetLoaderGGUF', 'AnimaLLLiteApply_sdscripts', 'ModelSamplingAuraFlow', 'VRAMCleanup', 'PrimitiveBoolean', 'PrimitiveFloat', 'PrimitiveInt', 'EmptyLatentImage', 'EmptySD3LatentImage', 'ImpactConditionalBranch', 'DazzleSwitch', 'easy seed'}

def redact_text(value):
    if isinstance(value, str):
        return {'text_omitted': True, 'characters': len(value), 'sha256': hashlib.sha256(value.encode('utf8')).hexdigest()}
    if isinstance(value, list):
        return [redact_text(v) for v in value]
    if isinstance(value, dict):
        return {k:redact_text(v) for k,v in value.items()}
    return value

live = {}
for endpoint in ['system_stats', 'queue', 'object_info', 'extensions']:
    try:
        live[endpoint] = get('http://127.0.0.1:8188/' + endpoint)
    except Exception as e:
        live[endpoint] = {'error': str(e)}
(OUT / 'live_snapshot.json').write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding='utf-8')
obj = live.get('object_info', {})
rows = []
for path in sorted((ROOT / 'ComfyUI/user/default/workflows').glob('*.json')):
    raw = path.read_bytes()
    wf = json.loads(raw)
    if not isinstance(wf.get('nodes'), list):
        continue
    graphs = [('root', wf)]
    graphs.extend((g.get('id', str(i)), g) for i, g in enumerate(wf.get('definitions', {}).get('subgraphs', [])))
    subids = {g[0] for g in graphs[1:]}
    nodes = []
    for graph_id, graph in graphs:
        for n in graph.get('nodes', []):
            widgets=n.get('widgets_values')
            if n['type'] not in CONTROL_TYPES:
                widgets=redact_text(widgets)
            nodes.append({'graph':graph_id, 'id':n['id'], 'type':n['type'], 'title':n.get('title'), 'mode':n.get('mode',0), 'widgets':widgets, 'inputs':n.get('inputs',[]), 'outputs':n.get('outputs',[])})
    types = collections.Counter(n['type'] for n in nodes)
    missing = {t:c for t,c in types.items() if t not in obj and t not in subids and t not in ['Note','MarkdownNote','Reroute'] and not t.startswith(('Primitive','GetNode','SetNode'))}
    row = {'file':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'root_nodes':len(wf.get('nodes',[])), 'subgraphs':len(graphs)-1, 'total_nodes':len(nodes),'modes':dict(collections.Counter(str(n['mode']) for n in nodes)), 'types':dict(types),'missing_or_frontend':missing,'nodes':nodes,'graphs':[{'id':k,'links':g.get('links',[]),'inputs':g.get('inputs',[]),'outputs':g.get('outputs',[])} for k,g in graphs]}
    rows.append(row)
(OUT / 'workflow_inventory.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'observed_at_utc':datetime.now(timezone.utc).isoformat(),'system':live['system_stats'],'queue':live['queue'],'registered_nodes':len(obj),'extensions':len(live['extensions']),'workflows':[{k:v for k,v in r.items() if k not in ['nodes','graphs','types']} for r in rows]}, ensure_ascii=False, indent=2))
alltypes = collections.Counter(n['type'] for r in rows for n in r['nodes'])
print('NODE_TYPES', json.dumps(alltypes,ensure_ascii=False))
