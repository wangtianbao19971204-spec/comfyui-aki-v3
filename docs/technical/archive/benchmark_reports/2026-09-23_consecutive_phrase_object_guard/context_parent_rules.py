"""Batch 45 rules: garment-hug base form, `holding back` and inanimate-motion guards from round 133."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('depiction_guard',Path(__file__).resolve().parent.parent/'2026-09-23_consecutive_depiction_guard/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT}

# 衣物贴合的基础形（sleeves hug her shoulders / the dress hugs her waist）不是人物拥抱。
GARMENT_HUG_BASE=r"\b(?:fabric|cloth|garment|material|silk|satin|chiffon|leather|denim|bodysuit|leggings|stockings|tights|hosiery|dress|skirt|shirt|top|jacket|coat|blouse|sleeves?)\b[^.;!?]{0,25}\bhug(?:s|ging)?\s+(?:(?:the|her|his|their)\s+)?(?:(?:arm|leg|hip|thigh|shoulder|torso|upper|lower|waist)s?\s+)?(?:contours?|curves?|body|waist|figure|silhouette|outline|shape|form|hips|thighs?)"
HUG_SUPPORT=r"\b(?:hugging|hug|hugs|embraces?|embracing|cuddling)\b[^.;!?]{0,25}\b(?:another|each other|mutual|the (?:girl|woman|boy|man|child)|viewer|someone|his|her|him|their)\b"

# holding back / held back 是短语动词，不是持物。
HOLD_BACK=r"\bhold(?:ing|s|eld)?\s+back\b"
OBJECT_SUPPORT=(r"\b(?:holding|holds?|carrying|carries|grasp\w*|grip\w*|clutch\w*|grabb?\w*|lift(?:ing|s)?|rais(?:e|es|ing))\b[^.;!?]{0,45}"
    r"\b(?:book|books|cup|teacup|glass|phone|smartphone|sword|gun|spear|knife|bag|handbag|basket|ball|bottle|flower|bouquet|lantern|umbrella|parasol|fan|dildo|vibrator|weapon|camera|brush|pen|lipstick|envelope|letter|lollipop|plate|tray|towel|blanket|doll|plush|food|fruit)\b")

# 眼镜（eyewear）不是家具与生活用品。
EYEWEAR_GLASSES=(r"\b(?:[a-z]+-framed|rimless|framed)\s+eyewear\b|\bglasses\b[^.;!?]{0,15}\b(?:eyewear|eyesight|vision)\b"
    r"|\b(?:eyewear|eyesight|vision)\b[^.;!?]{0,15}\bglasses\b")
FURNITURE_OTHER=r"\b(?:beds?|chairs?|stools?|benches?|sofas?|couches?|tables?|desks?|shelves?|shelf|books?|cups?|teacups?|mugs?|bottles?|mirrors?|phones?|smartphones?|clocks?|pillows?|towels?|carpets?|rugs?|blankets?|sinks?|faucets?|baskets?|easels?|canvases?|instruments?|guitars?|pianos?|violins?|biwa|koto|shamisen|lutes?|harps?|flutes?|drums?|seats?|toys?|lanterns?|mailboxes?|curtains?|radiators?|cabinets?|drawers?|vending machines?|boxes?|holders?|candlesticks?|holders?)\b"

# 图案/刺绣装饰里的植物词不作为“新补挂”植物与花园的依据（既有父类仍按轮次账本处理）。
DECOR_CUE=(r"\b(?:blossoms?|foliage|leaves|flowers?|petals?)\b[^.;!?]{0,30}\b(?:decorat\w+|printed|embroider\w+)\b"
    r"|\b(?:decorat\w+|printed|embroider\w+)\b[^.;!?]{0,30}\b(?:blossoms?|foliage|leaves|flowers?|petals?)\b")
DECOR_CONTEXT=r"\b(?:backdrops?|curtains?|wallpapers?|printed|pattern\w*|motifs?|embroider\w+|decorat\w+|floral)\b"
PLANT_WORD=r"\b(?:flowers?|roses?|petals?|blossoms?|foliage|leaves|leaf|trees?|bouquet|vase|garden|forest|bamboo|mushrooms?|plants?|ivy|ferns?|grass|moss|thicket|bush)\b"

REMOVALS=[
    ('拥抱与日常互动',[GARMENT_HUG_BASE],HUG_SUPPORT,'Garment or fabric clinging is not a hug.'),
    ('持物与道具互动',[HOLD_BACK],OBJECT_SUPPORT,'Phrasal verb `holding back`, not an object.'),
    ('家具与生活用品',[EYEWEAR_GLASSES],FURNITURE_OTHER,'Eyewear, not a household item.'),
]


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body)).replace('; ', ', ')


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
    if '植物与花园' in found:
        positive=_positive(body,refinements)
        decor=[match.group() for match in re.finditer(DECOR_CUE,positive,re.I)]
        if decor:
            stripped=re.sub(DECOR_CUE,' ',positive,flags=re.I)
            real=[]
            for match in re.finditer(PLANT_WORD,stripped,re.I):
                window=stripped[max(0,match.start()-120):match.end()+120]
                if re.search(DECOR_CONTEXT,window,re.I):continue
                real.append(match.group())
            if not real:
                found.remove('植物与花园')
    rejected=candidates(body,list(parents)+list(found),refinements)
    return [parent for parent in found if parent not in rejected]
