"""Batch 37 rules: exposure-verb recall, butterfly-decoration guard and bodily-fluid streaks from round 123."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('weapon_token',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_weapon_token/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '裸露与遮盖':r"\b(?:nude|naked|topless|bottomless|exposed|exposing|bare skin|nsfw|see-through|transparent|sheer)\b",
    '射精与体液':r"\b(?:cum|semen|ejaculat\w*|love juices?|pussy juice\w*|squirt\w*|saliva|drool\w*|sweat|fluid)\b",
}

EXPOSURE_VERB=r"\bexpos(?:e|es|ed|ing)\b[^.;!?]{0,25}\b(?:areolae?|nipples?|breasts?)\b"
FLUID_STREAK=r"\b(?:fluid|love juices?|pussy juice\w*)\b[^.;!?]{0,20}\b(?:streaks?|trails?|drips?|trickles?|running)\w*\b"
FLUID_BODY=r"\b(?:pussy|thigh|thighs|slit|arousal|fingering|self-fingering|crotch|groin|breasts?|belly|nude|naked)\b"
BUTTERFLY_DECOR=r"\b(?:butterfl(?:y|ies))\s+(?:pasties|hair ?ornament|ornament|print|pattern|motif|tattoo|earrings?|ring|clip|pin|brooch|decorations?)\b|\b(?:pasties|hair ?ornament|ornament|print|pattern|motif|tattoo|earrings?|ring|clip|pin|brooch)\b[^.;!?]{0,20}\b(?:butterfl(?:y|ies))\b"

REMOVALS=[
    ('动物主体',[BUTTERFLY_DECOR],SUPPORT['动物主体'],'Butterfly decoration, not an independent animal.'),
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
    want('裸露与遮盖',EXPOSURE_VERB)
    fluid_allowed=False
    for match in re.finditer(FLUID_STREAK,positive,re.I):
        window=positive[max(0,match.start()-60):match.end()+60]
        if re.search(FLUID_BODY,window,re.I):fluid_allowed=True;break
    want('射精与体液',FLUID_STREAK,allowed=fluid_allowed)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
