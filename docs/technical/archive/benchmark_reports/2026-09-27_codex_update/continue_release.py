"""Resume the verified transaction after closing SQLite fingerprint handles."""
from update_common import *
from db_fingerprint import fingerprint

prior=read(HERE/'release_receipt.json');assert prior['phase'] in ('rollback_required','compatibility_check_corrected_ready')
if not (HERE/'file_lock_attempt_receipt.json').exists():save(HERE/'file_lock_attempt_receipt.json',prior)
code=(HERE/'release.py').read_text(encoding='utf-8').split('\npre=read(')[0]
ns={'__file__':str(HERE/'release.py'),'__name__':'update_release_continuation'};exec(compile(code,str(HERE/'release.py'),'exec'),ns)
pre=read(HERE/'preflight.json');ns['pre']=pre;ns['receipt']=prior
assert ns['listeners']()==[]
for relative,digest in pre['bound_files'].items():
    if Path(relative).name in ('db_fingerprint.py','live_acceptance.py'):continue
    assert sha(ROOT/relative)==digest,relative
assert fingerprint(DB)==pre['db_before'],'The failed rename must not have changed user data'
for name,dst in ns['targets'].items():
    if name!='tags.db':assert sha(dst)==sha(BACKUP/name),name
for name,src in ns['staged'].items():assert sha(src)==pre['stage_sha256'][name],name
for relative,digest in pre['frozen_hashes'].items():assert sha(ROOT/relative)==digest
save(HERE/'continuation_preflight.json',{'passed':True,'created_at':now(),'parent_preflight_sha256':sha(HERE/'preflight.json'),'closing_fix_sha256':sha(HERE/'db_fingerprint.py'),'live_check_sha256':sha(HERE/'live_acceptance.py'),'continuation_sha256':sha(Path(__file__)),'stage_sha256':pre['stage_sha256'],'all_user_data_at_baseline':True,'listener_absent':True,'reason':'Explicitly close SQLite fingerprint connections before file replacement. Compare legacy served parents through the deployed selector_subcategories, including its existing broad fallback; full index equality remains mandatory.'})
checkpoint=ns['checkpoint'];replace=ns['replace'];child=None
try:
    checkpoint('resuming_verified_transaction',applied=True)
    for name,dst in ns['targets'].items():replace(ns['staged'][name],dst)
    child=ns['start']('production');checkpoint('live_acceptance')
    ns['run']('live_acceptance');ns['run']('live_contract')
    for name,dst in ns['targets'].items():
        if name!='tags.db':assert sha(dst)==pre['stage_sha256'][name],name
    assert fingerprint(DB)==pre['db_after']
    for relative,digest in pre['frozen_hashes'].items():assert sha(ROOT/relative)==digest
    ns['queue_empty']();assert ns['listeners']()==[child.pid]
    prior['sole_listener_ok']=True;checkpoint('accepted',passed=True,completed_at=now(),file_lock_resolved=True)
except BaseException as exc:
    checkpoint('continuation_rollback_required',failure=repr(exc))
    if child is None and prior.get('production') and ns['psutil'].pid_exists(prior['production']['pid']):child=ns['psutil'].Process(prior['production']['pid'])
    if child is not None and child.is_running():ns['stop'](child,prior['production']['create_time'])
    assert not ns['listeners']()
    for name,dst in ns['targets'].items():replace(BACKUP/name,dst)
    prior['applied']=False;recovered=ns['start']('recovery')
    assert ns['get']('/prompt_selector/library/index')==read(HERE/'baseline_index.json')
    assert fingerprint(DB)==pre['db_before'];ns['queue_empty']()
    checkpoint('rolled_back',rollback_verified=True);raise
