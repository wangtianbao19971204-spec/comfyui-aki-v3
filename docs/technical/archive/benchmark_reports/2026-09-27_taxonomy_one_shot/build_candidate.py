from common import *
import re, ast, shutil

cases=read(HERE/'review_cases.json')
keep_parent={1:'Independent suspenders are wearable accessories.',5:'Bunny-costume wrist cuffs and detached collar are worn accessories.',8:'Headphones/headset are independent personal accessories.',9:'Belly chain is independent jewelry.',12:'Nipple rings explicitly support this parent under the published batch-25 standard.',13:'A separate necktie is a wearable accessory; no leaf is required for parent retention.',15:'Headphones/headset are independent personal accessories.',17:'Worn collar and chain independently support the broad accessory parent.',25:'Independent suspenders support the broad accessory parent.',27:'Worn collar and chain independently support the broad accessory parent.'}
keep_leather={42:'A suede jacket is a leather garment; the handbag and car-seat mentions do not negate it.',50:'The beret has a black leather brim, independently of the handbag.',55:'Visible leather stiletto pumps support footwear material; the chair does not negate that evidence.',64:'Brown leather blazer is an explicit garment.',71:'Black leather corsage is explicit clothing.'}
for n in (8,15):
    keep_parent.pop(n)
judgments=[]
for x in cases[:76]:
    flag=x['flags'][0];n=x['n'];kind=flag['kind'];target=flag['target']
    if kind=='false_positive_parent':
        retain=n in keep_parent; reason=keep_parent.get(n,'Full text has only an eye-bag or waste/plastic bag cue, with no independent jewelry or personal accessory. Clothing ribbons and hair decorations do not establish this parent.')
        if n in (8,15):reason='Headphones/headset belong to the existing household-device parent under 分类标准.md:212, already present. They do not support jewelry/personal accessory membership; eye bags are figurative.'
    elif flag['cue']=='fabric_leather_furniture_guard':
        retain=n in keep_leather;reason=keep_leather.get(n,'All leather mentions describe furniture, a vehicle interior, an object on a table, or anaphoric surface/texture; no garment leather evidence in full text.')
    elif n==40:retain=True;reason='Light and shadow from the upper left explicitly highlight the silhouette; this is a lighting description.'
    elif n==60:retain=True;reason='The scanner matches eyes that hold a hint of mystery. Pulling worn dress fabric does not establish a held prop; no missing prop leaf is proven.'
    else:retain=False;reason={'hair.very_long':'Explicit very long white hair; color modifier blocks the current literal phrase.', 'hair.white':'Explicit long white hair with a numeric length annotation; nested color must survive.', 'hair.multicolor':'Positive multicolored hair follows no text|; the negative scope must stop at that separator.', 'plant.tree':'Tree pattern and tree girl are a decorative/anthropomorphic concept, not a separate actual tree.', 'light_effect.soft':'Explicit soft/even scene illumination; unrelated soft material/blur elsewhere must not veto it.', 'light_effect.silhouette':'Hourglass silhouette is a body shape modified by a belt, not a lighting effect.', 'cover.nude':'Both occurrences of nude modify stockings or pointed-toe stilettos; no nude body is described.'}[target]
    want=(target in (x['parents'] if 'parent' in kind else x['leaves'])) if retain else kind.startswith('missing')
    judgments.append({'n':n,'id':x['id'],'prompt_sha256':x['prompt_sha256'],'flag':flag,'decision':'retain_current' if retain else 'repair','expected_present':want,'reason':reason,'full_text_read':True})
save(HERE/'review_decisions.json',judgments)

# Stored-parent changes are bound to both the body and the entire old record.
data=read(HERE/'backup/data.json'); edits=[];byid={j['id']:j for j in judgments if j['flag']['kind']=='false_positive_parent' and j['decision']=='repair'}
for c in data['categories']:
    for p in c.get('prompts',[]):
        j=byid.get(p['id'])
        if not j:continue
        assert hashlib.sha256(p['prompt'].encode()).hexdigest()==j['prompt_sha256']
        before=json.loads(json.dumps(p));parent=j['flag']['target']
        assert parent in p['_classification']['subcategories']
        p['_classification']['subcategories'].remove(parent)
        edits.append({'id':p['id'],'category_id':c['id'],'prompt_sha256':j['prompt_sha256'],'before_classification':before['_classification'],'after_classification':p['_classification'],'reason':j['reason']})
assert len(edits)==len(byid)
writer=load_script(OLD/'parent_correction_stage.py','parent_stage_helpers').deployed_writer()
(HERE/'stage/data.json').write_bytes(writer(data))
projection=read(HERE/'backup/semantic_projection.json')
# The projection stores inherited decisions; regenerate through the existing
# deterministic writer. Explicit per-record decisions live in data.json.
old_projection=load_script(OLD/'parent_correction_stage.py','projection_stage_helpers')
from collections import Counter
projection_bytes=writer(projection)
assert dict(Counter(d.get('disposition') for d in projection['decisions'].values())) == projection['counts']
assert projection_bytes == (HERE/'backup/semantic_projection.json').read_bytes()
(HERE/'stage/semantic_projection.json').write_bytes(projection_bytes)
save(HERE/'parent_edits.json',edits)
del data

source=(HERE/'backup/semantic_refinements.py').read_text(encoding='utf-8')
source=source.replace("REFINEMENT_VERSION = '2026-09-25.25'","REFINEMENT_VERSION = '2026-09-27.01'",1)
source=source.replace("text = strip_nonpositive_nai_weights(text)\n", "text = strip_nonpositive_nai_weights(text)\n    text = re.sub(r'\\bno\\s+text\\s*\\|', 'no text,', text)\n",1)
anchor="    if parent == '植物与花园' and re.match(r'\\s+(?:flowers?\\s+)?(?:necklace|hairpin|hair ornament)\\b', after):"
assert source.count(anchor)==1
source=source.replace(anchor,"    if parent == '植物与花园' and phrase in {'tree', 'trees'} and re.match(r'\\s+(?:girl|boy|woman|man)\\b', after):\n        return False\n"+anchor)
anchor="    if parent == '光影效果' and phrase == 'silhouette' and re.search(r'\\b(?:s-curve|s\\s+curve|body|figure)\\s*$', before):"
assert source.count(anchor)==1
source=source.replace(anchor,anchor.replace('body|figure','body|figure|hourglass'))
anchor="r'\\s+(?:stockings?|thighhighs?|pantyhose|tights|leggings|pants|trousers|shorts|heels?|pumps?|'"
assert source.count(anchor)==1
source=source.replace(anchor,"r'\\s+(?:(?:pointed[- ]toe|square[- ]toe|open[- ]toe|high[- ]heeled)\\s+)?(?:stockings?|thighhighs?|pantyhose|tights|leggings|pants|trousers|shorts|heels?|pumps?|'",1)
anchor="            elif (len(_out_key.split()) >= 2 and _in_key"
assert source.count(anchor)==1
source=source.replace(anchor,"            elif (re.fullmatch(r'\\d+(?:\\.\\d+)?x\\s+length', _in_key)\n                  and re.fullmatch(r'(?:long |very long )?(?:white |black |blonde |brown |silver )?hair', _out_key)):\n                part = outside\n"+anchor)
anchor="    if '视线方向' in parents and any(_B86_GAZE.search(_part) for _part in parts):"
assert source.count(anchor)==1
source=source.replace(anchor,"    if '头发与发型' in parents and any(re.search(r'\\b(?:very|extremely) long (?:(?:white|black|blonde|brown|silver|straight|wavy) ){0,2}hair\\b', re.sub(r'\\b(?:no|not|without)\\s+[^,;.!?]+', '', part)) for part in parts):\n        found.add('hair.very_long')\n"+anchor)
old="""            if (_B90_SOFT_DIRECT.search(_joined)
                    and not _B86_SOFT_MATERIAL.search(_joined)
                    and not _B86_SOFT_FOCUS.search(_joined)
                    and not _B86_SOFT_DEVICE.search(_joined)):
                found.add('light_effect.soft')"""
new="""            for _match in _B90_SOFT_DIRECT.finditer(_joined):
                # Qualify the actual illumination phrase, not unrelated soft
                # clothing, hair or blur elsewhere in the prompt.
                _window = _joined[max(0, _match.start()-12):_match.end()+55]
                if re.search(r'\\b(?:no|not|without)\\s*$', _joined[max(0,_match.start()-12):_match.start()]):
                    continue
                if _soft_light_is_artwork_only_occurrence(_joined, _match.start(), _match.end()):
                    continue
                if re.search(r'\\b(?:glow|light)\\s+(?:of|from)\\s+(?:the |a )?(?:phone|screen|monitor|device|sign)\\b', _window):
                    continue
                found.add('light_effect.soft')
                break"""
assert source.count(old)==1
source=source.replace(old,new)
helper="""

_LEATHER_CLOTHES = r'(?:jacket|blazer|coat|pants|trousers|skirt|shorts|boots?|gloves?|dress|corset|corsage|bustier|harness|leotard|bodysuit|bra|lingerie|belt|heels?|shoes?|sandals?|pumps?|stilettos?|footwear|cap|hat|brim|choker|vest|catsuit)'
_LEATHER_MODIFIERS = r'(?:(?:black|brown|white|red|dark|light|tan|pointed[- ]toe|square[- ]toe|high[- ]heeled|ankle|knee[- ]high|thigh[- ]high|long|short|fitted|tight|shiny|glossy|textured|cropped)\\s+){0,3}'
_GARMENT_LEATHER = re.compile(r'\\b(?:leather|suede)\\s+' + _LEATHER_MODIFIERS + _LEATHER_CLOTHES + r'\\b|\\b' + _LEATHER_CLOTHES + r"(?:'s)?\\s+(?:(?:is|are|made|of|from|in|black|brown|white|soft|shiny|glossy)\\s+){0,6}(?:leather|suede)\\b", re.I)
_FOOTWEAR_LEATHER = re.compile(r'\\b(?:boots?|shoes?|pumps?|stilettos?|heels?)\\b[^.;!?]{0,110}\\btheir\\s+(?:shiny |glossy |black )?leather\\b', re.I)

def _furniture_leather_without_garment(parts):
    text=' '.join(re.sub(r'\\b(?:no|not|without|never)\\s+[^,;.!?]+', '', part) for part in parts)
    if not re.search(r'\\bleather\\b', text):
        return False
    if _GARMENT_LEATHER.search(text) or _FOOTWEAR_LEATHER.search(text):
        return False
    return bool(re.search(r'\\b(?:sofa|couch|armchair|chair|seats?|bench|stool|headboard|headrest|backrest|armrest|car interior|cabin|booth)\\b[^.;!?]{0,100}\\bleather\\b|\\bleather\\b[^.;!?]{0,65}\\b(?:sofa|couch|armchair|chair|seats?|bench|stool|headboard|headrest|backrest|armrest|car interior|booth)\\b', text))
"""
anchor='\ndef extract_refinements(body, subcategories, *, enable_soft_modifier_cues=False):'
assert source.count(anchor)==1;source=source.replace(anchor,helper+anchor)
anchor='    return sorted(found)'
assert source.count(anchor)==1
source=source.replace(anchor,"    if 'fabric.leather' in found and _furniture_leather_without_garment(parts):\n        found.discard('fabric.leather')\n"+anchor)
compile(source,str(STAGE/'semantic_refinements.py'),'exec')
(STAGE/'semantic_refinements.py').write_text(source,encoding='utf-8')
save(HERE/'candidate_build.json',{'created_at':now(),'version':'2026-09-27.01','source_sha256':sha(STAGE/'semantic_refinements.py'),'data_sha256':sha(HERE/'stage/data.json'),'projection_sha256':sha(HERE/'stage/semantic_projection.json'),'parent_edit_count':len(edits),'retained_flags':sum(j['decision']=='retain_current' for j in judgments),'production_mutated':False})
print(read(HERE/'candidate_build.json'))
