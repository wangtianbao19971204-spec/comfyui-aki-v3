import copy,json,shutil
from manage import FILES,OUT,sha,save

metrics=json.loads((OUT/'measurement.json').read_text('utf8'))
assert metrics['identical_pixels'] and len(metrics['verified_warm_jobs'])>=3
release=json.loads((OUT/'release.json').read_text('utf8'))
changes=[]
for name,p in FILES.items():
 if not (name.startswith('UAP') or name.startswith('生产套件_01_')):continue
 assert sha(p)==release['sources'][name],name
 before=json.loads(p.read_text('utf8'));after=copy.deepcopy(before)
 if name.startswith('UAP'):
  branch=next(b for b in before['extra']['uap_workbench']['branches'] if b['id']=='a1');ids=set(branch['nodeIds'])
 else:ids={n['id'] for n in before['nodes']}
 chosen=[n for n in after['nodes'] if n['id'] in ids and n['type']=='VRAMCleanup']
 assert len(chosen)==1
 for n in chosen:
  assert n['widgets_values']==[True,True]
  n['widgets_values']=[False,False]
  changes.append({'file':name,'node':n['id'],'before':[True,True],'after':[False,False]})
 restored=copy.deepcopy(after)
 for n in restored['nodes']:
  if n['id'] in {x['id'] for x in chosen}:n['widgets_values']=[True,True]
 assert restored==before,'Only cleanup booleans may change'
 staged=OUT/'staged'/name;staged.write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf8')
 shutil.copyfile(staged,p);release['sources'][name]=sha(p)
save('release.json',release)
save('default_policy.json',{'changes':changes,'other_workflows_unchanged':True,'basis':'Only the currently measured AnimaYume production branch changes default. Anima 2.9B and Krea2 retain their previous default and expose the selector.'})
print(json.dumps(changes,ensure_ascii=False))
