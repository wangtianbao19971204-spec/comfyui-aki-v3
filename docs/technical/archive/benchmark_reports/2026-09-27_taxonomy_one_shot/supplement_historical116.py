from common import *

rid='krea2-9f3cb65b5ea2b6744a2c6f6c'
data=read(HERE/'stage/data.json');row=next(v for c in data['categories'] for v in c.get('prompts',[]) if v['id']==rid)
body_sha=hashlib.sha256(row['prompt'].encode()).hexdigest()
matches=[v['id'] for c in data['categories'] for v in c.get('prompts',[]) if hashlib.sha256(v.get('prompt','').encode()).hexdigest()==body_sha]
assert matches==[rid],matches
del data
evidence=HERE/'historical116_material_amendment.json'
save(evidence,{'schema':'precise-material-adjudication/v1','round':116,'id':rid,'prompt_sha256':body_sha,'full_original_read':True,
              'reason':'Both leather mentions describe the light-green tote bag, including the later anaphoric smooth leather. The sheer gray dress and matching floral pointed heels have no leather material evidence. Under 分类标准.md:206 bag material is not garment fabric. The broad furniture draft happened to suppress it through the adjacent chair; use the reviewed complete-text binding instead of that false furniture relation.',
              'retain_nodes_removed':['fabric.leather'],'remove_nodes_added':['fabric.leather']})
ledger=ROOT/'benchmark_reports/2026-09-20_consecutive_extension/round_116_ledger.jsonl'
original=next(json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines() if json.loads(line)['id']==rid)
assert original['prompt_sha256']==body_sha and 'fabric.leather' in original['retain_nodes']
registry=read(OLD/'replay_amendments.json');assert not any(x['round']==116 for x in registry['entries'])
registry['entries'].append({'round':116,'id':rid,'prompt_sha256':body_sha,'evidence':{'path':str(evidence.relative_to(ROOT)),'sha256':sha(evidence)},'ledger':{'path':str(ledger.relative_to(ROOT)),'sha256':sha(ledger)},'changes':[{'field':f,'target':'fabric.leather','old':o,'new':not o} for f,o in [('retain_nodes',True),('remove_nodes',False)]]})
save(OLD/'replay_amendments.json',registry)
source=(STAGE/'semantic_refinements.py').read_text(encoding='utf-8')
anchor="    if 'fabric.leather' in found and _furniture_leather_without_garment(parts):"
assert source.count(anchor)==1
source=source.replace(anchor,"    # Reviewed round-116 prose: repeated leather describes the tote bag only.\n    if _round137_sha == '"+body_sha+"':\n        found.discard('fabric.leather')\n"+anchor)
compile(source,str(STAGE/'semantic_refinements.py'),'exec')
(STAGE/'semantic_refinements.py').write_text(source,encoding='utf-8')
candidate=read(HERE/'candidate_build.json');candidate.update(source_sha256=sha(STAGE/'semantic_refinements.py'),supplemental_material_record=rid)
save(HERE/'candidate_build.json',candidate)
print(candidate['source_sha256'])
