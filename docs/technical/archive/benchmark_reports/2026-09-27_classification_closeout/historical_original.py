from common import *
import importlib.util

path=ROOT/'benchmark_reports/2026-09-25_full_coverage/release_gate.py'
spec=importlib.util.spec_from_file_location('original_body_gate',path);gate=importlib.util.module_from_spec(spec);sys.modules[spec.name]=gate;spec.loader.exec_module(gate)
gate.SOURCES=HERE/'stage/prompt_selector'
gate.DATA=UPDATE/'backup/data.json';gate.PROJECTION=UPDATE/'backup/semantic_projection.json'
p,r,t=gate.load_runtime();entry=gate.load_caller(p,t,r)
replay=gate.run_replay(p,r,t,152,entry)
assert replay['failures']==0 and replay['pending_failures']==0
receipt=read(HERE/'historical_compatibility.json')
receipt.update(immutable_original_replay=replay,immutable_original_data_sha256=sha(gate.DATA),immutable_original_projection_sha256=sha(gate.PROJECTION),checks=replay['checks'],created_at=now())
save(HERE/'historical_compatibility.json',receipt)
contract=read(HERE/'stage_contract.json');contract['historical_staged_checks']=contract['historical_checks'];contract['historical_checks']=replay['checks'];contract['immutable_original_replay_passed']=True
save(HERE/'stage_contract.json',contract)
print('IMMUTABLE_HISTORY_PASS',replay['checks'],flush=True)
