"""Exact current 2.9B part subgraphs + USDU, driven by a clothed neutral input."""
import copy
from repair import Graph, ROOT, RUN, EXT, WF, read, save, set_widget

ext=read(RUN/'candidate'/EXT.name)
main=read(RUN/'candidate'/WF.name)
g=Graph(ext)
for n in ext['nodes']:
    if n.get('properties',{}).get('uap_refinement'):
        n['mode']=4 if n['properties']['uap_refinement'].startswith('region') else 0
    if n['type']=='CLIPTextEncode':
        set_widget(n,'text','An adult woman wearing a blue raincoat and yellow boots, standing beside a bicycle, daylight, illustration' if n['id']%2==0 else 'text, watermark, blurry')
    if n['type']=='SaveImage':
        set_widget(n,'filename_prefix','_codex_qa/repair_audit/a29_parts')
for idx,s in enumerate(ext['definitions']['subgraphs']):
    if s.get('extra',{}).get('uap_refinement') not in {'hand','foot','face','eye'}:
        continue
    sg=Graph(s,sub=True)
    detector=next(n for n in s['nodes'] if n['type']=='ImpactSimpleDetectorSEGS')
    name=s['extra']['uap_refinement']
    nid=160000+idx*10
    records=[
        dict(id=nid,type='SegsToCombinedMask',inputs=[dict(name='segs',type='SEGS',link=None)],outputs=[dict(name='MASK',type='MASK',links=[])]),
        dict(id=nid+1,type='MaskToImage',inputs=[dict(name='mask',type='MASK',link=None)],outputs=[dict(name='IMAGE',type='IMAGE',links=[])]),
        dict(id=nid+2,type='SaveImage',inputs=[dict(name='images',type='IMAGE',link=None),dict(name='filename_prefix',type='STRING',widget=dict(name='filename_prefix'),link=None)],outputs=[],widgets_values=[f'_codex_qa/repair_audit/mask_{name}']),
    ]
    for i,n in enumerate(records):
        n.update(pos=[400+i*340,700],size=[300,100],flags={},mode=0,order=i,title=f'QA only: {name} mask',properties={})
        s['nodes'].append(n);sg.nodes[n['id']]=n
    sg.connect(detector['id'],0,nid,'segs','SEGS')
    sg.connect(nid,0,nid+1,'mask','MASK')
    sg.connect(nid+1,0,nid+2,'images','IMAGE')
    sg.finish()
for src,newid in [(1111,200),(1112,201)]:
    n=copy.deepcopy(next(n for n in main['nodes'] if n['id']==src))
    n.update(id=newid,mode=0,pos=[4090,140+(newid-200)*160])
    n['properties'].pop('uap_layout_group',None)
    ext['nodes'].append(n);g.nodes[newid]=n
for name,src,kind in [('image',105,'IMAGE'),('model',5,'MODEL'),('positive',20,'CONDITIONING'),('negative',21,'CONDITIONING'),('vae',4,'VAE'),('upscale_model',200,'UPSCALE_MODEL')]:
    g.connect(src,0,201,name,kind)
g.connect(201,0,50,'images','IMAGE')
g.connect(201,0,51,'images','IMAGE')
set_widget(g.nodes[50],'filename_prefix','_codex_qa/repair_audit/a29_parts_usdu')
ext['extra']['uap_repair_fixture']=True
ext['id']='0aa5a8f3-e52b-41e8-bb65-ecb6f224465c'
g.finish()
save(ROOT/'ComfyUI/user/default/workflows/_codex_qa/UAP_repair_inference.json',ext)
print('Prepared neutral hand/foot/face/eye + USDU fixture; regional presets bypassed.')
