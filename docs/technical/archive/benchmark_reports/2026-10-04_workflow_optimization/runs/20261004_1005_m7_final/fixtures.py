import copy
from pathlib import Path
from manage import OUT, PLAN, NAMES, read, write

safe = read(PLAN / 'runs/20261004_0705_m4_controls/neutral_uap.json')
safe_nodes = safe['nodes'] + [n for s in safe.get('definitions', {}).get('subgraphs', []) for n in s['nodes']]
text_types = {'MarkdownNote', 'Note', 'ShowText|pysssss', 'DanbooruGalleryNode', 'CR Prompt Text', 'WeiLinPromptUI', 'OlmJoyCaption', 'TB_Anima_Prompt_Judge_API_V16', 'VNCCS_PoseStudio', 'TB_Multi_API_Caption_SmartRunner_V16', 'Krea2EditGroundedEncode', 'CLIPTextEncode'}
folder = OUT / 'fixtures'
folder.mkdir(exist_ok=True)
manifest = []
for index, name in enumerate(NAMES):
    data = read(OUT / 'candidate' / name)
    nodes = data['nodes'] + [n for s in data.get('definitions', {}).get('subgraphs', []) for n in s['nodes']]
    changed = []
    for node in nodes:
        if node['type'] in text_types:
            candidates = [n for n in safe_nodes if n['type'] == node['type']]
            assert candidates, node['type']
            neutral = next((n for n in candidates if n['id'] == node['id']), candidates[0])
            for key in ['widgets_values', 'widgets_values_named']:
                if key in neutral:
                    node[key] = copy.deepcopy(neutral[key])
                else:
                    node.pop(key, None)
            changed.append(node['id'])
    data['id'] = f'00000000-0000-4000-8000-00000000{index+700:04d}'
    write(folder / name, data)
    manifest.append(dict(file=name, neutralized_nodes=changed, source='M4 accepted neutral fixture payloads for text-bearing node types', scope='Browser import, controls and prompt export only. No inference or formal save. Structural assertions separately use exact candidate.'))
write(OUT / 'fixture_manifest.json', manifest)
print({'fixtures': len(manifest), 'source': 'accepted M4 neutral fixture'})
