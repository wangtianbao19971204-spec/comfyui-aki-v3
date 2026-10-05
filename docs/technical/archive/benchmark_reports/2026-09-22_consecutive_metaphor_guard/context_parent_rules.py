"""Batch 43 rules: garment-hug and abstract-carry retractions from round 130."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('palette_fabric',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_palette_fabric/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT}

# 衣物/面料的贴合（X hugging body/waist/curves/contours）不是人物拥抱。
GARMENT=r"\b(?:fabric|cloth|garment|material|silk|satin|chiffon|leather|denim|bodysuit|leggings|stockings|tights|hosiery|dress|skirt|shirt|top|jacket|coat|blouse)\b"
GARMENT_HUG=GARMENT+r"[^.;!?]{0,25}\bhugging\s+(?:(?:the|her|his|their)\s+)?(?:(?:arm|leg|hip|thigh|shoulder|torso|upper|lower)s?\s+)?(?:contours?|curves?|body|waist|figure|silhouette|outline|shape|form|hips|thighs?)"
HUG_SUPPORT=r"\b(?:hugging|hug|hugs|embraces?|embracing|cuddling)\b[^.;!?]{0,25}\b(?:another|each other|mutual|the (?:girl|woman|boy|man|child)|viewer|someone|his|her|him|their)\b"

# carrying + 抽象名词（carrying the realism）不是持物。
ABSTRACT_CARRY=r"\bcarrying\s+(?:the|his|her|their|its)\s+(?:realism|authenticity|spirit|essence|mood|atmosphere|weight|air|feel|soul|tradition|heritage|emotion|tension|elegance|charm|sensuality|beauty|story|narrative|legacy|intensity|warmth|sophistication|simplicity|dignity|grace|mystery|nostalgia|message|meaning)\b"
OBJECT_SUPPORT=(r"\b(?:holding|holds?|carrying|carries|grasp\w*|grip\w*|clutch\w*|grabb?\w*|lift(?:ing|s)?|rais(?:e|es|ing))\b[^.;!?]{0,45}"
    r"\b(?:book|books|cup|teacup|phone|smartphone|sword|gun|spear|knife|bag|handbag|basket|ball|bottle|glass|flower|bouquet|lantern|umbrella|parasol|fan|dildo|vibrator|weapon|camera|brush|pen|lipstick|envelope|letter|lollipop|plate|tray|towel|blanket|doll|plush)\b")

# 角色专名 `sakamoto miko` 里的 miko 不是巫女职业证据（第 130 轮逐条证据撤回）。
MIKO_NAME=r"\bsakamoto miko\b"
OTHER_ROLE_SUPPORT=re.sub(r'miko\|','',previous.SUPPORT.get('职业与身份',''))
MIKO_SUPPORT=(r"\bmiko (?:outfit|dress|clothes|uniform|costume|attire)\b|\bshrine maiden\b|巫女|神社|\bshrine\b|"+OTHER_ROLE_SUPPORT)

REMOVALS=[
    ('拥抱与日常互动',[GARMENT_HUG],HUG_SUPPORT,'Garment or fabric clinging is not a hug.'),
    ('持物与道具互动',[ABSTRACT_CARRY],OBJECT_SUPPORT,'Carrying an abstract quality is not holding an object.'),
    ('职业与身份',[MIKO_NAME],MIKO_SUPPORT,'Character-name token, not an occupation cue.'),
]


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))


def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    # `_positive_parts` splits on commas; keep the garment and its `hugging`
    # verb inside one window so `fabric, hugging the arm contours` stays visible.
    positive=_positive(body,refinements).replace('; ', ', ')
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
    # Upstream recall must not resurrect a parent this batch withdraws.
    found=previous.additions(body,parents,refinements)
    rejected=candidates(body,list(parents)+list(found),refinements)
    return [parent for parent in found if parent not in rejected]
