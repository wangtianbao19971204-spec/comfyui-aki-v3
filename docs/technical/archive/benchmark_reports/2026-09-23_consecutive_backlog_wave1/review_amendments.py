import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
AMENDMENTS={}
for name in ('pool_scope_amendment.json','worn_belt_amendment.json','mixed_pose_amendment.json'):
    item=json.loads((HERE/name).read_bytes());AMENDMENTS[item['id']]=item
for item in json.loads((HERE.parent/'2026-09-21_round93_100_audit/audit_amendments.json').read_bytes())['reviews']:
    AMENDMENTS[item['id']]=item
for item in json.loads((HERE/'round109_retain_amendment.json').read_bytes())['reviews']:
    AMENDMENTS[item['id']]=item
for item in json.loads((HERE/'round110_retain_amendment.json').read_bytes())['reviews']:
    AMENDMENTS[item['id']]=item
for item in json.loads((HERE/'round130_grab_amendment.json').read_bytes())['reviews']:
    AMENDMENTS[item['id']]=item
for item in json.loads((HERE/'round113_hug_amendment.json').read_bytes())['reviews']:
    AMENDMENTS[item['id']]=item
for item in json.loads((HERE/'round131_silhouette_amendment.json').read_bytes())['reviews']:
    AMENDMENTS[item['id']]=item
for item in json.loads((HERE/'round134_stage_screen_amendment.json').read_bytes())['reviews']:
    AMENDMENTS[item['id']]=item

def amend_review(review):
    updated=AMENDMENTS.get(review.get('id'))
    if updated is None:return review
    assert review['prompt_sha256']==updated['prompt_sha256']
    return updated.copy()
