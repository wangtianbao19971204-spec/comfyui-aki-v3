"""Batch 31 rules: weapon recall for kunai plus title/garment/container context guards from round 117."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('reveal_verb',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_reveal_verb/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

# Keep the inherited support table available to later batches and to the
# removal checks below.
SUPPORT={**previous.SUPPORT,
    '武器与装备':r"\b(?:swords?|knives?|knife|katanas?|daggers?|kunai|shurikens?|spears?|lances?|halberds?|axes?|bows?|guns?|pistols?|rifles?|weapons?|scythes?|gauntlets?|dual blades?|armou?red dress)\b",
    '文字与图形':r"\b(?:lettering|writing on|signage|neon sign|signboard|logo|symbols?|banner|poster|graffiti wall|graffiti on|spray can|kanji|text on|subtitle|caption|speech bubble)\b",
}

WEAPON_CUE=r"\b(?:kunai|苦无)\b"
# 饰品化写法与专名（如 `kunai nakasato` 这类人名标签）都不证明武器；
# `kunai in hand` 之类的真实持械表述仍保留。
WEAPON_GUARD=r"\b(?:kunai|苦无)\b[^.;!?]{0,15}\b(?:hair|ornament|clip|pin)\b|\bkunai\s+(?!in\b|on\b|with\b|and\b|to\b|held\b|is\b|near\b|beside\b|at\b)[a-z]{2,}\b"

# A false cue only removes a parent when no independent evidence remains.
REMOVALS=[
    ('交通与机械',[r"\bmecha[ -](?:goggles|visor|mask|helmet|headgear|earpiece|hairband)\b"],SUPPORT['交通与机械'],'Mecha-styled accessory, not a machine subject.'),
    ('自然地貌与水域',[r"\b(?:glass|cup|mug|bottle|jar)\b[^.;!?]{0,30}\b(?:filled with|of)\s+(?:clear |clean |fresh |cold )?water\b"],SUPPORT['自然地貌与水域'],'Water inside a container, not a water landscape.'),
    ('文字与图形',[r"\byume graffiti\b"],SUPPORT['文字与图形'],'Work title, not an in-image graphic element.'),
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
    want('武器与装备',WEAPON_CUE,allowed=not re.search(WEAPON_GUARD,positive,re.I))
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
