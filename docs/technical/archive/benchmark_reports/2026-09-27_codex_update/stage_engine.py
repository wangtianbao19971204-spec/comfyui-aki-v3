from update_common import *
import shutil
out=STAGE/'prompt_selector';out.mkdir(exist_ok=True)
for f in (PROD/'prompt_selector').glob('*.py'):shutil.copy2(f,out/f.name)
source=PROD/'prompt_selector/semantic_refinements.py'
shutil.copy2(source,BACKUP/'semantic_refinements.py')
text=source.read_text(encoding='utf-8')
assert "REFINEMENT_VERSION = '2026-09-27.01'" in text
text=text.replace("REFINEMENT_VERSION = '2026-09-27.01'","REFINEMENT_VERSION = '2026-09-27.02'",1)
anchor='very long silver white hair|very long straight black hair'
assert text.count(anchor)==1
text=text.replace(anchor,'very long silver white hair|very long snow white hair|very long straight black hair',1)
(out/'semantic_refinements.py').write_text(text,encoding='utf-8',newline='')
compile(text,str(out/'semantic_refinements.py'),'exec')
hits=[]
for c in read(BACKUP/'data.json')['categories']:
    for p in c['prompts']:
        if re.search(r'very[ _]long[ _]snow[ _]white[ _]hair',p['prompt'],re.I):
            hits.append({'id':p['id'],'prompt_sha256':hashlib.sha256(p['prompt'].encode()).hexdigest(),'text':p['prompt']})
save(HERE/'engine_phrase_radius.json',{'phrase':'very long snow white hair','baseline_hits':hits,'source_sha256':sha(out/'semantic_refinements.py')})
print('ENGINE_STAGED','BASELINE_LITERAL_HITS',len(hits))
