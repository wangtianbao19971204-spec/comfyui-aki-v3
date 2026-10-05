"""Apply explicitly bound historical assertion changes, never whole-round waivers."""
import hashlib
import json
from pathlib import Path

FIELDS=('add','add_nodes','remove','remove_nodes','retain_nodes','retain_parents')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_amendments(root, registry):
    document=json.loads(Path(registry).read_text(encoding='utf-8'))
    if document.get('schema')!='precise-replay-amendments/v1':
        raise ValueError('Unknown replay amendment schema')
    result={}
    for entry in document['entries']:
        key=(entry['round'],entry['id'])
        for label in ('evidence','ledger'):
            path=(root/entry[label]['path']).resolve()
            if not path.is_relative_to(root.resolve()) or digest(path)!=entry[label]['sha256']:
                raise ValueError(f'{label} hash mismatch for {key}')
        target=result.setdefault(key, {'prompt_sha256':entry['prompt_sha256'],'changes':[],'evidence':[]})
        if target['prompt_sha256']!=entry['prompt_sha256']:
            raise ValueError(f'Conflicting prompt bindings: {key}')
        for change in entry['changes']:
            if change['field'] not in FIELDS or type(change['old']) is not bool or type(change['new']) is not bool or change['old']==change['new']:
                raise ValueError(f'Invalid assertion change: {key}')
            if any(x['field']==change['field'] and x['target']==change['target'] for x in target['changes']):
                raise ValueError(f'Duplicate assertion change: {key}')
            target['changes'].append(change)
        target['evidence'].append(entry['evidence'])
    return result

def apply_amendment(number,row,body,amendments):
    expectations={field:set(row.get(field) or []) for field in FIELDS}
    amendment=amendments.get((number,row['id']))
    if amendment is None:
        return expectations,0
    if hashlib.sha256(body.encode('utf-8')).hexdigest()!=amendment['prompt_sha256']:
        raise ValueError(f'Prompt hash mismatch for {(number,row["id"])}')
    for change in amendment['changes']:
        values=expectations[change['field']]
        if (change['target'] in values)!=change['old']:
            raise ValueError(f'Ledger assertion changed for {(number,row["id"])}')
        if change['new']:values.add(change['target'])
        else:values.remove(change['target'])
    return expectations,len(amendment['changes'])

def run_replay(gate,pmod,rmod,tmod,max_round,caller):
    root=gate.ROOT
    amendments=load_amendments(root,root/'benchmark_reports/2026-09-25_full_coverage/replay_amendments.json')
    data=json.loads(gate.DATA.read_bytes())
    records={p.get('id'):(c,p) for c in data['categories'] for p in c.get('prompts',[])}
    doc=pmod.read_projection(gate.PROJECTION)
    checks=0;pending_checks=0;pending_failures=0;changes=0;failures=[];rounds=set();missing=[];bindings=[];seen=set()
    rows=gate.ledger_rows()
    for number,name,row in rows:
        seen.add((number,row['id']))
        pair=records.get(row['id'])
        if pair is None:
            missing.append(row['id']);failures.append({'round':number,'id':row['id'],'kind':'missing_record'});continue
        category,prompt=pair;body=prompt.get('prompt') or ''
        expected_hash=row.get('prompt_sha256')
        if expected_hash and hashlib.sha256(body.encode()).hexdigest()!=expected_hash:
            bindings.append(row['id']);failures.append({'round':number,'id':row['id'],'kind':'ledger_body_hash_mismatch'});continue
        expected,applied=apply_amendment(number,row,body,amendments) if number<=max_round else ({f:set(row.get(f) or []) for f in FIELDS},0)
        changes+=applied
        if caller is not None:semantic=caller(doc,category,prompt)['_semantic'];parents=set(semantic['subcategories']);leaves=set(semantic['refinements'])
        else:
            decision=pmod.decision_for(doc,category,prompt)
            parents=set(pmod.selector_subcategories(decision,prompt));leaves=set(rmod.extract_refinements(body,sorted(parents)))
        for field,values in expected.items():
            collection=leaves if field.endswith('nodes') else parents
            for target in sorted(values):
                checks+=1;ok=(target in collection)==(not field.startswith('remove'))
                if number>max_round:
                    pending_checks+=1;pending_failures+=not ok;continue
                rounds.add(number)
                if not ok:failures.append({'round':number,'id':row['id'],'kind':field,'value':target,'ledger':name})
    unused=[list(k) for k in amendments if k not in seen]
    if unused:raise ValueError(f'Amendment ledger record not found: {unused}')
    return {'checks':checks,'failures':len(failures),'failure_sample':failures[:50],'failure_ids':[f"{f['round']}|{f['id']}|{f['kind']}|{f.get('value','')}" for f in failures],
            'rounds':len(rounds),'ledger_rows':len(rows),'closed_ledger_rows':sum(n<=max_round for n,_,_ in rows),'max_round':max_round,'pending_rows':sum(n>max_round for n,_,_ in rows),'pending_checks':pending_checks,'pending_failures':pending_failures,
            'records_without_body':len(missing),'binding_failures':bindings,'amended_suppressed':0,'precise_assertion_changes':changes,'amendment_records':len(amendments),'amendment_registry_sha256':digest(root/'benchmark_reports/2026-09-25_full_coverage/replay_amendments.json'),'round_wide_waivers':False}
