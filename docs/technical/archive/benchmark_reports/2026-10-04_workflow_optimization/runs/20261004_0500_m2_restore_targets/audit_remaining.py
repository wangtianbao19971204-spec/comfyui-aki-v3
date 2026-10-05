import hashlib
import json
from pathlib import Path

OUT=Path(__file__).parent
PREVIOUS=OUT.parent/'20261004_0400_m2_graph_audit'
ROOT=Path(r'G:\ComfyUI-aki-v3')
def read(p):return json.loads(p.read_text('utf8'))
def save(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
old_baseline=read(PREVIOUS/'baseline.json')['files']
paths=read(PREVIOUS/'workflow_paths.json')
reused=[]
for r in paths:
    p=Path(r['file']);h=hashlib.sha256(p.read_bytes()).hexdigest()
    assert h==old_baseline[str(p)]
    reused.append({'file':str(p),'sha256':h,'unchanged':True,'sampler_paths':str(PREVIOUS/'browser_graph_audit.json')})
audit=read(PREVIOUS/'browser_graph_audit.json')['reports']
entries=[]
for row in audit:
    api=row['api']
    for sampler in row['samplers']:
        for direction in ['positive','negative']:
            r=sampler['report'][direction]
            edges=[];value=api[sampler['id']]['inputs'][direction];seen=set();leaf=None
            while isinstance(value,list) and len(value)==2 and str(value[0]) not in seen:
                ident=str(value[0]);seen.add(ident);n=api[ident];t=n['class_type'];i=n['inputs']
                edges.append({'id':ident,'class_type':t,'slot':value[1]})
                if t=='CLIPTextEncode':
                    value=i['text']
                    if isinstance(value,str):leaf={'id':ident,'field':'text'}
                elif t in ['WeiLinPromptUI','CR Prompt Text','Krea2EditGroundedEncode']:
                    field='positive' if t=='WeiLinPromptUI' else 'prompt'
                    leaf={'id':ident,'field':field};break
                else:break
            entries.append({'branch':row['branch'],'sampler':sampler['id'],'direction':direction,'edges':edges,
                            'leaf':leaf,'static_text_confirmed':'text' in r,'runtime_reason':r.get('reason'),
                            'multi_source_merge_confirmed':False,
                            'scope':'Saved default graph only; no provenance is inferred for manually combined text inside a field.'})
assert len(entries)==18
assert all(e['leaf'] for e in entries)
save('duplicate_source_audit.json',{'status':'verified_no_change','paths':entries,
    'static_text_paths':sum(e['static_text_confirmed'] for e in entries),'runtime_paths':sum(not e['static_text_confirmed'] for e in entries),
    'decision':'No confirmed duplicate concatenation from multiple graph sources on these default conditioning paths. Do not add an alert or automatically deduplicate text. Within-field repetition has no source/subject provenance; neutral browser fixtures verify exact preservation.',
    'limits':'Runtime expansions, user-edited graphs and optional disabled branches are not claimed free of duplicates. No semantic conflict judgement is made for multi-character/weighted/segmented text.'})
save('reused_evidence.json',{'workflow_paths':reused,'previous_display_fix':str(PREVIOUS/'FINAL_DELIVERY.json'),
    'current_source_sha256':hashlib.sha256((ROOT/'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/prompt_inspector.js').read_bytes()).hexdigest(),
    'scope':'Reuse standalone suite API paths and M2a display regression; nine console target paths have new browser coverage this run.'})
browser=[read(p) for p in sorted(OUT.glob('branch_*.json'))]
assert len(browser)==9 and all(r['passed'] for r in browser)
save('target_matrix.json',{'passed':True,'branches':browser,'checks':sum(len(r['checks']) for r in browser),
    'method':'Real production UI mounted in a text-neutralized copy of UAP; branch selection via UI, source identity via getPromptInput, input events drive production handlers, exact API text checked and restored; no generation.'})
print(json.dumps({'branches':len(browser),'checks':sum(len(r['checks']) for r in browser),'paths':len(entries),'runtime_paths':sum(not e['static_text_confirmed'] for e in entries)}))
