"""Offline contextual removals and explicit clothing recall."""
import importlib.util
from pathlib import Path
import re

spec=importlib.util.spec_from_file_location('object_parent_contexts',Path(__file__).resolve().parent.parent/'2026-09-20_consecutive_object_contexts/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
BAD={
 '移动与运动':[r'\b(?:juices?|liquids?|fluids?|droplets?|tears?|blood|water|sweat)\s+(?:\w+ly\s+)?(?:runs|running)\b',r'\b(?:hair|sleeves|fabric|strands|tassels)\s+(?:\w+ly\s+)?(?:flutter(?:ing|s)?|float(?:ing|s)?|drift(?:ing|s)?|fall(?:ing|s)?)\b'],
 '视角与透视':[r'\b(?:footjob|handjob|fellatio|groping|grabbing|hugging|sex) from behind\b'],
 '动漫与卡通':[r'\bcartoon (?:phone )?(?:case|pattern|print|toy|sticker|keychain)\b',r'\banime (?:poster|enthusiast|fan)\b'],
 '职业与身份':[r'\bmaid (?:apron|skirt|headdress|dress|outfit|uniform)\b'],
 '卧姿与趴姿':[r'\b(?:blazer|jacket|coat|shirt|clothes|dress)\s+lying\b'],
 '家具与生活用品':[r'\btextured canvas\b',r'\b(?:side|right|left|center|edge) of (?:the )?canvas\b'],
}
SUPPORT={**previous.SUPPORT,
 '移动与运动':previous.SUPPORT['移动与运动']+r'|\bsprint(?:ing|s)?\b',
 '动漫与卡通':previous.previous.SUPPORT['动漫与卡通'],
 '职业与身份':previous.previous.SUPPORT['职业与身份'],
 '卧姿与趴姿':r'\b(?:lying|reclining|reclined|prone|supine|on back|on side|on stomach|bent over|bending over)\b|卧|趴|躺',
 '家具与生活用品':r'\b(?:bed|chair|stool|bench|sofa|couch|table|desk|shelf|shelves|book|books|cup|bottle|glass|glasses|mirror|phone|clock|rope|chain|door|window|curtain|umbrella|canvas|easel|pillow|towel|carpet|rug|blanket|sink|faucet|basket)\b|家具|桌|椅|窗|门|伞',
}

def candidates(body,parents,refinements):
    results=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent in parents:
        remaining=positive;cues=[]
        for pattern in BAD.get(parent,[]):
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            results[parent]={'false_cues':cues,'reason':'Identified non-subject meaning with no independent supporting cue.'}
    return results

def additions(body,parents,refinements):
    result=[]
    positive='; '.join(refinements._positive_parts(body))
    if '上衣与外套' not in parents:
        # Require an actual clothing phrase, not a top-of-frame position.
        nodes=refinements.extract_refinements(body,['上衣与外套'])
        if nodes or re.search(r'\b(?:short[ -]sleeved?|long[ -]sleeved?|sun-protective|knit|cropped|crop|tank|sleeveless) top\b',positive):
            result.append('上衣与外套')
    if '多格与连续画面' not in parents and re.search(r'\b(?:four[ -]panel|4koma|four panels)\b|四格漫画|4格漫画',positive):
        result.append('多格与连续画面')
    return result
