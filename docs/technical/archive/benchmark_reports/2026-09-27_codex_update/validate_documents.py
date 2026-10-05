from update_common import *

rows=read(HERE/'document_comparison.json');gaps=read(HERE/'document_gap_review.json')
web={source_key(m,e):e for m,e in sources()}
index={(x['source_file'],x['source_entry']):x for x in rows}
review=[]
for g in gaps:
    row=index[(g['source_file'],g['source_entry'])];body=norm(row['tags'])
    result={'file':g['source_file'],'entry':g['source_entry'],'disposition':g['disposition']}
    if g['disposition']=='body_is_contained_in_complete_web_entry':
        assert any(body in norm(content(web[k])) for k in g['web_ids'])
        result['web_ids']=g['web_ids']
    elif g['disposition']=='inspect_difference':
        c=g['candidate'];key=c['dataset']+':'+c['id'];entry=web[key]
        negatives=[norm(cp['negative']) for cp in entry.get('characterPrompts',[]) if cp.get('negative')]
        if any('uc:' in x.get('doc','').replace(' ','') or '1uc' in x.get('doc','') for x in g['differences']):
            assert negatives and all(n.strip(' ,;') in body for n in negatives)
            result['disposition']='character_labels_and_negative_fields_separated'
            result['negative_fields_verified']=len(negatives)
        elif key=='suozhang_r18:codex_6e699406-0901':
            result['disposition']='publisher_character_label_typo_correction'
        elif key=='suozhang_r18:codex_6e699406-5081':
            result['disposition']='equivalent_character_labels'
        elif key=='suozhang_nai5_r18:suozhang_nai5_r18-0447':
            assert all(d['op']=='insert' for d in g['differences'])
            result['disposition']='web_contains_additional_complete_panels'
        else:raise AssertionError(key)
        result['web_ids']=[key]
    else:
        candidates=[]
        for n in ('0074','0075','0076'):
            key='suozhang_nai5:suozhang_nai5-'+n;e=web[key]
            if g['title']=='负面' and body==norm(e.get('negative','')):candidates.append(key)
            elif g['title'].startswith('Steps:'):
                compact=lambda s:re.sub(r'\s+','',s).lower()
                note=compact(e.get('note',''))
                if compact(g['title']) in note and compact(row['tags']) in note:candidates.append(key)
        assert len(candidates)==1,(g['source_entry'],candidates)
        result.update(disposition='negative_or_parameters_attached_to_style',web_ids=candidates)
    review.append(result)
counts=Counter(x['status'] for x in rows)
assert len(rows)==18506 and counts['web_exact']==18371 and counts['local_exact']==46 and len(review)==89
save(HERE/'document_coverage_receipt.json',{'passed':True,'documents':8,'entries':len(rows),'web_exact':counts['web_exact'],'already_local_exact':counts['local_exact'],'remaining_adjudicated':len(review),'unresolved':0,'coverage_means':'All parsed document rows accounted for; exclusions in source registry still apply. Parser fragments were not inserted as separate prompts.','review':review})
print('DOCUMENT_COVERAGE',len(rows),'UNRESOLVED',0,dict(Counter(x['disposition'] for x in review)))
