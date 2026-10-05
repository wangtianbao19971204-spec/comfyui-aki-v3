from pathlib import Path
import sys, re, json
HERE = Path(__file__).resolve().parent
PREV = HERE.with_name('2026-09-27_llama_verified_writeback')
sys.path.insert(0, str(PREV))
from common import read, load_rows, digest
from update_common import YOUTH

def save(name, value):
    (HERE/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

raw = {r['source']:r for r in load_rows()}
items = read(HERE/'inventory.json')
proper_artist = re.compile(r'\bchild\s*\(isoliya\)', re.I)
review = []
for item in items:
    row = raw[item['source']]; r = row['record']
    combined = r['positive_prompt']+' '+r['title']+' '+' / '.join(r['source_path'])
    remaining_age = list(YOUTH.finditer(proper_artist.sub('', combined)))
    known_young_character = bool(re.search(r'\b(?:hoto cocoa|kafuu chino)\b', combined, re.I))
    source_no_explicit = not row['flags']['explicit_positive'] and not row['flags']['explicit_title']
    if (not remaining_age and not known_young_character) or (source_no_explicit and item['next_action'] == 'direct_review_candidate'):
        review.append({'source':item['source'], 'id':item['id'], 'prior_hold':item['prior_hold'], 'source_flags':row['flags'], 'artist_name_age_collision':bool(proper_artist.search(combined)), 'other_age_cues':len(remaining_age), 'source_sha256':row['source_sha256'], 'positive_body_sha256':digest(r['positive_prompt'])})
save('source_context_review.json', review)
print(json.dumps({'source_context_candidates':len(review), 'artist_only_age_collisions':sum(r['artist_name_age_collision'] and not r['other_age_cues'] for r in review), 'metadata_only_local_candidates':sum(not r['source_flags']['explicit_positive'] and not r['source_flags']['explicit_title'] for r in review)},ensure_ascii=False))
