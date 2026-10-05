from update_common import *
import importlib.util

def verify(gate,projection,refinements,taxonomy,entry,staged_replay):
    oldpath=gate.DATA;oldprojection=gate.PROJECTION
    updates={o['id']:o for o in read(HERE/'operations.json') if 'upstream_body_update' in o['action']}
    allowed={'codex-codex_8489ac52-5486','codex-codex_6e699406-5026'}
    assert set(staged_replay['binding_failures'])==allowed
    assert staged_replay['failures']==2 and all(x['kind']=='ledger_body_hash_mismatch' for x in staged_replay['failure_sample'])
    assert allowed<=set(updates)
    gate.DATA=BACKUP/'data.json';gate.PROJECTION=BACKUP/'semantic_projection.json'
    try:baseline=gate.run_replay(projection,refinements,taxonomy,152,entry)
    finally:gate.DATA=oldpath;gate.PROJECTION=oldprojection
    assert baseline['failures']==0,baseline
    before={p['id']:(c,p) for c in read(BACKUP/'data.json')['categories'] for p in c['prompts']}
    after={p['id']:(c,p) for c in read(STAGE/'data.json')['categories'] for p in c['prompts']}
    amendments=gate.strict_replay.load_amendments(ROOT,ROOT/'benchmark_reports/2026-09-25_full_coverage/replay_amendments.json')
    doc=projection.read_projection(STAGE/'semantic_projection.json');checks=[]
    for number,name,row in gate.ledger_rows():
        if row['id'] not in allowed:continue
        bc,bp=before[row['id']];c,p=after[row['id']]
        oldhash=hashlib.sha256(bp['prompt'].encode()).hexdigest();newhash=hashlib.sha256(p['prompt'].encode()).hexdigest()
        assert oldhash==row['prompt_sha256'] and oldhash!=newhash
        expected,_=gate.strict_replay.apply_amendment(number,row,bp['prompt'],amendments)
        semantic=entry(doc,c,p)['_semantic'];parents=set(semantic['subcategories']);leaves=set(semantic['refinements'])
        operations=[]
        for field,values in expected.items():
            for value in sorted(values):
                assert (value in (leaves if field.endswith('nodes') else parents))==(not field.startswith('remove')),(row['id'],field,value)
                operations.append({'operation':field,'target':value,'passed':True})
        checks.append({'round':number,'id':row['id'],'old_body_sha256':oldhash,'new_body_sha256':newhash,'publisher_source':updates[row['id']]['source'],'checks':operations})
    assert len(checks)==2
    result={'passed':True,'data_sha256':sha(STAGE/'data.json'),'engine_sha256':sha(STAGE/'prompt_selector/semantic_refinements.py'),'immutable_baseline_replay':baseline,'staged_replay_before_revision_adjudication':staged_replay,'approved_source_revisions':checks,'unexplained_failures':0,'frozen_samples_changed':False,'method':'Replay every frozen assertion on immutable original bodies with the candidate engine; separately replay every original semantic assertion on the two explicitly hash-bound publisher revisions. No assertion or historical file is weakened or replaced.'}
    save(HERE/'historical_compatibility.json',result);return result

if __name__=='__main__':
    path=ROOT/'benchmark_reports/2026-09-25_full_coverage/release_gate.py';spec=importlib.util.spec_from_file_location('update_history_gate',path);gate=importlib.util.module_from_spec(spec);sys.modules[spec.name]=gate;spec.loader.exec_module(gate)
    gate.SOURCES=STAGE/'prompt_selector';gate.DATA=STAGE/'data.json';gate.PROJECTION=STAGE/'semantic_projection.json'
    projection,refinements,taxonomy=gate.load_runtime();entry=gate.load_caller(projection,taxonomy,refinements)
    result=verify(gate,projection,refinements,taxonomy,entry,read(HERE/'historical_replay.json'))
    print('HISTORICAL_COMPATIBILITY_PASS',result['immutable_baseline_replay']['checks'])
