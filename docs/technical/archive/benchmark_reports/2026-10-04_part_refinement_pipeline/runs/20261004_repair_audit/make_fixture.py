"""Neutral, isolated browser fixture. Never submit the user's positive prompts."""
import copy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from repair import ROOT,RUN,WF,NEUTRAL,read,save

wf=read(RUN/'candidate'/WF.name)
for graph in [wf]+wf['definitions']['subgraphs']:
    for n in graph['nodes']:
        if n['type'] in {'WeiLinPromptUI','CLIPTextEncode','CR Prompt Text'}:
            values=n.get('widgets_values',[])
            if isinstance(values,list):
                n['widgets_values']=[NEUTRAL if isinstance(v,str) else v for v in values]
            if isinstance(n.get('widgets_values_named'),dict):
                n['widgets_values_named']={k:NEUTRAL if isinstance(v,str) else v for k,v in n['widgets_values_named'].items()}
        if n['type']=='SaveImage':
            n['widgets_values']=['_codex_qa/repair_audit/neutral']
            n['widgets_values_named']={'filename_prefix':'_codex_qa/repair_audit/neutral'}
wf['id']='07556fce-8b19-4555-b1ec-782e767f8472'
wf['extra']['uap_repair_fixture']=True
save(ROOT/'ComfyUI/user/default/workflows/_codex_qa/UAP_repair_neutral.json',wf)
print('Neutral isolated browser fixture prepared.')
