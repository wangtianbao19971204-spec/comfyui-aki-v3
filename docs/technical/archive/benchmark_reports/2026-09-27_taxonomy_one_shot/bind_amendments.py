from common import *

strict=load_script(OLD/'strict_replay.py','strict')
gate=load_script(OLD/'release_gate.py','registry_gate')
rows={(n,r['id']):(name,r) for n,name,r in gate.ledger_rows()}
entries=[]
def add(number,review,evidence,changes):
    name,original=rows[number,review['id']]
    assert original['prompt_sha256']==review['prompt_sha256']
    entries.append({'round':number,'id':review['id'],'prompt_sha256':review['prompt_sha256'],
                    'evidence':{'path':str(evidence.relative_to(ROOT)),'sha256':sha(evidence)},
                    'ledger':{'path':str((gate.FROZEN/name).relative_to(ROOT)),'sha256':sha(gate.FROZEN/name)},'changes':changes})

legacy=read(OLD/'release_gate_batch91_final_001.json')['replay']['amendment_evidence']
for n,paths in legacy.items():
    n=int(n);unique={}
    for p in paths:
        if 'transaction_fault' not in p:unique.setdefault(sha(ROOT/p),ROOT/p)
    assert len(unique)==1,(n,unique)
    path=next(iter(unique.values()));doc=read(path)
    for r in doc.get('reviews',[doc]):
        if n==57:
            changes=[{'field':f,'target':r['node'],'old':o,'new':not o} for f,o in [('remove_nodes',True),('retain_nodes',False)]]
        elif n==114:
            r=doc['binding'];assert sha(ROOT/r['ledger_path'])==r['ledger_sha256']
            changes=[{'field':f,'target':'作品角色','old':o,'new':not o} for f,o in [('retain_parents',True),('remove',False)]]
        else:
            _,old=rows[n,r['id']];changes=[]
            for field in strict.FIELDS:
                before=set(old.get(field) or []);after=set(r.get(field) or [])
                for target in sorted(before^after):changes.append({'field':field,'target':target,'old':target in before,'new':target in after})
        if changes:add(n,r,path,changes)

cases=read(HERE/'review_cases.json')[-3:]
evidence=HERE/'furniture_material_amendment.json'
save(evidence,{'schema':'precise-material-adjudication/v1','created_at':now(),'basis':'分类标准.md:206: material of hand-held accessories is not garment fabric. Furniture leather is also not garment material. Full originals reread. Frozen ledgers unchanged.',
    'reviews':[{'round':114 if c['n']<79 else 121,'id':c['id'],'prompt_sha256':c['prompt_sha256'],'full_original_read':True,
                'retain_nodes_removed':['fabric.leather'],'remove_nodes_added':['fabric.leather'],
                'reason':{77:'Leather armchair and dangling held strap only; neither is garment material.',78:'Green leather sofa only; white top/shorts and black jacket have no leather material evidence.',79:'Brown/orange-brown leather belongs to the sofa. Leopard textile top, skirt, stockings and matte shoes contain no leather evidence.'}[c['n']]} for c in cases]})
for r in read(evidence)['reviews']:
    add(r['round'],r,evidence,[{'field':f,'target':'fabric.leather','old':o,'new':not o} for f,o in [('retain_nodes',True),('remove_nodes',False)]])
save(OLD/'replay_amendments.json',{'schema':'precise-replay-amendments/v1','created_at':now(),'entries':entries})
strict.load_amendments(ROOT,OLD/'replay_amendments.json')
gatepath=OLD/'release_gate.py';source=gatepath.read_text(encoding='utf-8')
start=source.index('def run_replay(');end=source.index('\ndef run_contract(',start)
source=source[:start]+'''def run_replay(pmod, rmod, tmod, max_round=134, caller=None):
    return strict_replay.run_replay(sys.modules[__name__], pmod, rmod, tmod, max_round, caller)

'''+source[end:]
if 'import strict_replay\n' not in source:
    source=source.replace("HERE = Path(__file__).resolve().parent", "HERE = Path(__file__).resolve().parent\nsys.path.insert(0, str(HERE))\nimport strict_replay")
compile(source,str(gatepath),'exec');gatepath.write_text(source,encoding='utf-8')
print(json.dumps({'entries':len(entries),'assertion_changes':sum(len(e['changes']) for e in entries),'gate_sha':sha(gatepath)}))
