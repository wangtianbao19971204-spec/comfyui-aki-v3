from common import *

path=STAGE/'semantic_refinements.py';source=path.read_text(encoding='utf-8')
source=source.replace("_LEATHER_CLOTHES = r'(?:jacket|blazer|coat|pants|trousers|skirt|shorts|", "_LEATHER_CLOTHES = r'(?:jacket|blazer|coat|waistcoat|suit|ensemble|loafers?|stockings?|thighhighs|pants|trousers|miniskirt|skirt|shorts|")
source=source.replace('textured|cropped)\\s+){0,3}', 'textured|cropped|mini|moto|maid|spaghetti-strap|restraint|high-heel|high|trench|biker|motorcycle|quilted|pleated|soft)\\s+){0,3}')
source=source.replace("r'\\b(?:leather|suede)\\s+' + _LEATHER_MODIFIERS", "r'\\b(?:leather|suede)(?:-like)?\\s+' + _LEATHER_MODIFIERS")
old="    return bool(re.search(r'\\b(?:sofa|couch|armchair|chair|seats?|bench|stool|headboard|headrest|backrest|armrest|car interior|cabin|booth)\\b[^.;!?]{0,100}\\bleather\\b|\\bleather\\b[^.;!?]{0,65}\\b(?:sofa|couch|armchair|chair|seats?|bench|stool|headboard|headrest|backrest|armrest|car interior|booth)\\b', text))"
new="""    furniture = r'(?:sofa|couch|armchair|chair|seats?|bench|stool|headboard|headrest|backrest|armrest|car interior|cabin|booth)'
    return bool(re.search(
        r'\\bleather\\s+(?:(?:black|brown|white|red|dark|light|tan|café|cafe|office|reclining|business-class|car|passenger|driver|captain)\\s+){0,3}' + furniture + r'\\b'
        r'|\\b' + furniture + r"(?:'s)?\\s+(?:(?:is|are|made|of|from|in|a|with|rich|matte|gray|dark|black|brown|white|orange-brown|soft|shiny|glossy)\\s+){0,6}leather\\b"
        r'|\\bleather (?:textures?|surface) (?:on|of) (?:the )?(?:seat|sofa|chair)\\b'
        r'|\\bleather textures\\s+classic sports car interior\\b', text))"""
assert old in source;source=source.replace(old,new)
anchor="                _window = _joined[max(0, _match.start()-12):_match.end()+55]"
source=source.replace(anchor,"""                if ('glow' in _match.group() and
                        (_B86_SOFT_MATERIAL.search(_joined) or _B86_SOFT_FOCUS.search(_joined) or _B86_SOFT_DEVICE.search(_joined))):
                    continue
"""+anchor)
# The older soft-light fallback also ran on negated clauses.
old='        for _part in parts:\n            if (_B86_SOFT.search(_part)'
new="        for _part in parts:\n            _part = re.sub(r'\\b(?:no|not|without|never)\\s+[^,;.!?]+', '', _part)\n            if (_B86_SOFT.search(_part)"
assert old in source;source=source.replace(old,new)
compile(source,str(path),'exec');path.write_text(source,encoding='utf-8')
candidate=read(HERE/'candidate_build.json');candidate.update(source_sha256=sha(path),narrowing='Require direct furniture/material relation; preserve garment variants; remove negative clauses from legacy soft fallback.')
save(HERE/'candidate_build.json',candidate)
print(candidate['source_sha256'])
