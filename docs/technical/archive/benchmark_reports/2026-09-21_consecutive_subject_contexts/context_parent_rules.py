"""Contextual parent candidates for named works and non-subject actions."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('named_parent_contexts',Path(__file__).resolve().parent.parent/'2026-09-20_consecutive_named_contexts/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
BAD={
 '非人特征':[r'\bfairy tail\b'],
 '种族与幻想生物':[r'\bfairy tail\b'],
 '移动与运动':[r'\b(?:mist|fog|smoke)\s+(?:\w+ly\s+)?crawling\b',r'\bsaliva strings? stretching\b',r'\b(?:real and|emotionally|deeply) moving\b'],
 '持物与道具互动':[r"\bholding another's wrists?\b",r'\b(?:arm|head|wrist) grab\b'],
}
SUPPORT={**previous.SUPPORT,
 '非人特征':r'\b(?:tail|wings?|horns?|antlers|tentacles?|scales|claws|fangs|(?:cat|dog|wolf|fox|rabbit|animal|pointy|pointed|elf) ears|animal feet|bird legs|extra arms|extra ears|antennae)\b|兽耳|尾巴|翅膀|触手|鳞片|兽爪',
}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent in parents:
        remaining=positive;cues=[]
        for pattern in BAD.get(parent,[]):
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            result[parent]={'false_cues':cues,'reason':'Known title, body contact or non-subject movement; no independent supporting cue.'}
    return result

def additions(body,parents,refinements):
    return previous.additions(body,parents,refinements)
