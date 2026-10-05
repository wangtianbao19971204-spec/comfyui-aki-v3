from audit_remaining import *

# These labels correct the meaning of a lexical hit. They never approve a record.
NON_AGE = {
    'artist_name_child_isoliya': re.compile(r'\bchild\s*\(isoliya\)', re.I),
    'artist_name_loli_king': re.compile(r'\bajishio\s*\(loli king\)', re.I),
    'feeding_bottle_object': re.compile(r'\bbaby[\s_-]+bottles?\b', re.I),
    'lingerie_garment_name': re.compile(r'\bbaby[\s_-]+doll\b', re.I),
    'injury_severity': re.compile(r'\bminor[\s_-]+(?:wounds?|injur(?:y|ies))\b', re.I),
    'drawing_style': re.compile(r"\bchild['’]s[\s_-]+drawing\b", re.I),
    'papercraft_style': re.compile(r'\bpaper[\s_-]+child\b', re.I),
    'childbearing_body_descriptor': re.compile(r'\bchild[\s_-]+bearing\b', re.I),
}

def evidence(text):
    exclusions = [(m.start(),m.end(),kind) for kind,pattern in NON_AGE.items() for m in pattern.finditer(text)]
    result = []
    for hit in YOUTH.finditer(text):
        ignored = next((kind for start,end,kind in exclusions if start<=hit.start() and hit.end()<=end),None)
        result.append({'start':hit.start(),'end':hit.end(),'cue':hit.group(0),'is_age_evidence':ignored is None,'non_age_reason':ignored})
    return result

def main():
    raw={r['source']:r for r in load_rows()}
    inventory=read(HERE/'inventory.json'); corrections=[]; candidates=[]
    for item in inventory:
        src=raw[item['source']];rec=src['record']
        text=rec['positive_prompt']+' '+rec['title']+' '+' / '.join(rec['source_path'])
        found=evidence(text)
        if not any(not hit['is_age_evidence'] for hit in found):continue
        row={'source':item['source'],'id':item['id'],'source_sha256':src['source_sha256'],'review_text_sha256':digest(text),'age_cues':found,'retained_age_evidence':sum(x['is_age_evidence'] for x in found),'record_disposition':'unchanged_pending_context_review','no_automatic_approval':True}
        corrections.append(row)
        if row['retained_age_evidence']==0 and not item['already_direct_source_review'] and not item['already_direct_local_review']:
            candidates.append(row)
    save(HERE/'corrected_cue_evidence.json',corrections)
    save(HERE/'new_lexical_candidates.json',candidates)
    print(json.dumps({'records_with_non_age_hits':len(corrections),'records_whose_lexical_age_hits_are_all_non_age':sum(not x['retained_age_evidence'] for x in corrections),'new_full_context_candidates':len(candidates),'reasons':dict(Counter(h['non_age_reason'] for r in corrections for h in r['age_cues'] if not h['is_age_evidence'])),'candidates':[r['source'] for r in candidates]},ensure_ascii=False))

if __name__=='__main__':main()
