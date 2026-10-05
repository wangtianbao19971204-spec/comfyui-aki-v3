import json
import hashlib
import shutil
from pathlib import Path

ROOT=Path(r'G:\ComfyUI-aki-v3')
OUT=Path(__file__).parent
WF=ROOT/'ComfyUI/user/default/workflows'
(OUT/'fixtures').mkdir(exist_ok=True)
rows=[]
for i,p in enumerate([WF/'UAP统一生产工作台_v2.json',*sorted(WF.glob('生产套件_0[123]*v2.json'))]):
    d=json.loads(p.read_text('utf8')); changes=[]
    def sanitize(graph):
        for n in graph.get('nodes',[]):
            t=n.get('type');w=n.get('widgets_values',[])
            if t in ['WeiLinPromptUI','CLIPTextEncode','CR Prompt Text','Krea2EditGroundedEncode'] and isinstance(w,list) and w:
                w[0]=f"quiet forest, neutral source {n['id']}, (soft daylight:1.1)"
                changes.append({'id':n['id'],'type':t,'widget_index':0})
                if t=='WeiLinPromptUI':
                    w[1]=False
                    for j in range(2,len(w)):
                        if isinstance(w[j],str):w[j]=''
                if t=='Krea2EditGroundedEncode' and len(w)>2:w[2]=''
            if t=='MarkdownNote':n['widgets_values']=['M2 neutral disposable fixture']
        for g in graph.get('definitions',{}).get('subgraphs',[]):sanitize(g)
    sanitize(d)
    f=OUT/'fixtures'/f'workflow_{i}.json'
    f.write_text(json.dumps(d,ensure_ascii=False),encoding='utf8')
    shutil.copy2(p,OUT/'before'/p.name)
    rows.append({'original':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'fixture':str(f),'neutralized':changes,
                 'scope':'text fields only; original modes, node IDs, links and widget object schemas retained'})
(OUT/'fixtures_manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'workflows':len(rows),'neutral_text_fields':sum(len(r['neutralized']) for r in rows)}))
