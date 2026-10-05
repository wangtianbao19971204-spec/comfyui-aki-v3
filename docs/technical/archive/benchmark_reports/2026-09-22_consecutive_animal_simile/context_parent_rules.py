"""Batch 32 rules: independent-animal recall and armor-simile guards from round 118."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('weapon_title_water',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_weapon_title_water/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '武器与装备':previous.SUPPORT['武器与装备']+r"|armou?r|pauldrons?",
    '动物主体':r"\b(?:cats?|dogs?|birds?|mice|mouse|rats?|rabbits?|hamsters?|foxes?|fox|squirrels?|snakes?|spiders?|fish|horses?|wolves|wolf|bears?|pandas?|pupp(?:y|ies)|kittens?|moths?|butterfl(?:y|ies)|parrots?|owls?|animals?)\b",
    '奇幻与角色服饰':r"\b(?:armou?r|cosplay|fantasy|witch|maid|kimono|hanfu|plate mail|pauldrons?)\b",
}

ANIMAL_ON_BODY=r"\banimal on (?:the )?(?:shoulder|shoulders|lap|head|arm|hand|back|chest)\b"
QUALIFIED_ANIMAL=r"\b(?:cats?|dogs?|mouse|mice|rats?|rabbits?|hamsters?|bird|birds|fox|foxes|squirrels?|snakes?|spiders?|fish|pupp(?:y|ies)|kittens?|moths?|parrots?|owls?)\s*\((?:animal|real)\)"
ANIMAL_FAKE=r"\b(?:plush|stuffed|toy|fake|drawn|print|pattern|motif|costume|cushion|pillow|keychain|charm|statue|figure|food|logo|symbol)\b"
ANIMAL_CUE=ANIMAL_ON_BODY+'|'+QUALIFIED_ANIMAL
ARMOR_SIMILE=r"(?<![-'\w])(?:like|as if|as though|resembling|akin to)\b[^.;!?]{0,20}\barmou?r\b"

REMOVALS=[
    ('武器与装备',[ARMOR_SIMILE],SUPPORT['武器与装备'],'Armor appears only in a simile, not as a depicted item.'),
    ('奇幻与角色服饰',[ARMOR_SIMILE],SUPPORT['奇幻与角色服饰'],'Armor appears only in a simile, not as depicted clothing.'),
]


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))


def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive=_positive(body,refinements)
    node_parents={node['parent'] for node in refinements.REFINEMENT_NODES.values()}
    for parent,patterns,support,reason in REMOVALS:
        if parent not in parents:continue
        remaining=positive;cues=[]
        for pattern in patterns:
            cues.extend(match.group() for match in re.finditer(pattern,remaining,re.I))
            remaining=re.sub(pattern,' ',remaining,flags=re.I)
        if not cues:continue
        if re.search(support,remaining,re.I):continue
        if parent in node_parents and refinements.extract_refinements(remaining,[parent]):continue
        result[parent]={'false_cues':cues,'reason':reason}
    return result


def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    def want(parent,pattern,allowed=True):
        if parent in parents or parent in found or not allowed:return
        if re.search(pattern,positive,re.I):found.append(parent)
    animal_allowed=True
    for match in re.finditer(ANIMAL_CUE,positive,re.I):
        window=positive[max(0,match.start()-40):match.end()+40]
        if re.search(ANIMAL_FAKE,window,re.I):continue
        animal_allowed=True;break
    else:
        animal_allowed=False
    want('动物主体',ANIMAL_CUE,allowed=animal_allowed)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
