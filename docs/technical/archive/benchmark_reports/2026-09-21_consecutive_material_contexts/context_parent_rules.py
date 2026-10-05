"""Offline repairs for material nouns, printed words and named costumes."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('subject_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_subject_contexts/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
BAD={
 '植物与花园':[r'\bbamboo chopsticks?\b'],
 '制服与职业装':[r'\bzero suit\b'],
 '色彩与调色':[r'\bsketchbook full colors\b'],
 '城市与街道':[r'\bstreet vibes?\b',r'\burban nightlife\b'],
 '移动与运动':[r'\bmotion blur\b',r'\bhair flying\b'],
 '卧姿与趴姿':[r'\b(?:ribbon|paper|book|bag|towel)s? lying\b'],
 '持物与道具互动':[r'\b(?:price tags?|street signs?|signs?|labels?)\s+reading\b'],
 '动漫与卡通':[r'\bcartoon graffiti\b',r'\bcabinet with (?:a )?(?:hand-drawn )?cartoon girl\b',r'\binteraction with (?:the )?cartoon\b'],
}
SUPPORT={**previous.SUPPORT,
 '植物与花园':r'\b(?:bamboo|plant|plants|tree|trees|forest|garden|flower|flowers|bush|bushes|grass|leaves|foliage|petals|rose|roses)\b|植物|竹林|花园|树林',
 '色彩与调色':r'\b(?:colors?|colours?|palette|saturation|monochrome|grayscale|sepia|grain|noise|pastel|vibrant|muted|vivid|chromatic)\b|色彩|调色|颗粒|单色',
}
def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent in parents:
        remaining=positive;cues=[]
        for pattern in BAD.get(parent,[]):
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            result[parent]={'false_cues':cues,'reason':'Material, printed words, named costume or non-subject action; independent support absent.'}
    return result
def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent,pattern in [
        ('奇幻与角色服饰',r'\bzero suit\b'),
        ('上衣与外套',r'\b(?:v-neck|pleated|off-shoulder|off-the-shoulder) (?:[a-z-]+ ){0,2}top\b'),
    ]:
        evidence=positive
        if parent=='上衣与外套':
            evidence=re.sub(r'\bdress\b[^.;]{0,45}[—–]\s*the\s+v-neck top\b',' ',evidence)
        if parent not in parents and parent not in result and re.search(pattern,evidence):result.append(parent)
    return result
