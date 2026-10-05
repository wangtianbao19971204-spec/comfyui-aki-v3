"""Offline scene/object context corrections and explicit core recall."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('core_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_core_recall/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
SUPPORT={**previous.SUPPORT,
 '绘画与插画':r'\b(?:painting|illustration|illustrated|painterly|drawing|digital art)\b|绘画|插画',
}
BAD={
 '职业与身份':[r'\b(?:the )?wizard of oz\b'],
 '建筑与设施':[r'\bpalace solemnity\b'],
 '绘画与插画':[r'\bpeeling paint\b',r'\bdrawing (?:the )?viewer\b'],
 '拥抱与日常互动':[r'\b(?:hugging|embracing) (?:her|his|their|own) knees\b'],
}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    if re.search(r'\bfigure skater\b',positive):result.pop('移动与运动',None)
    if re.search(r'\b(?:airline stewardess|travel attendant)\b',positive):result.pop('职业与身份',None)
    for parent in parents:
        remaining=positive;cues=[]
        for pattern in BAD.get(parent,[]):
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            result[parent]={'false_cues':cues,'reason':'Work title, atmosphere, paint surface or self-directed gesture; no independent parent evidence.'}
    scene=refinements._scene_text(body)
    if scene!=body:
        remaining='; '.join(refinements._positive_parts(scene))
        for parent in ('城市与街道','植物与花园'):
            if parent in parents and not re.search(SUPPORT[parent],remaining,re.I):
                result[parent]={'false_cues':['depicted scene'],'reason':'Scene occurs only on printed material or an advertising backdrop.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=refinements._positive_parts(body)
    positive='; '.join(parts)
    for parent,pattern in [
        ('上衣与外套',r'\b(?:(?:long|short)[- ]sleeved? (?:[a-z-]+ ){0,2}top|halter top|shrug \(clothing\)?)\b'),
        ('室内空间',r'\bindoor (?:scenes?|settings?)\b'),
        ('种族与幻想生物',r'\b(?:demon boy|monster boy|giant monster)\b'),
        ('身体改造与伤痕',r'\bcompass rose tattoo\b'),
        ('动漫与卡通',r'\banime illustration\b'),
        ('体型与肤色',r'\b(?:muscular (?:old )?man|gigantic muscles)\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    if '动物主体' not in parents and '动物主体' not in result and 'no humans' in parts and re.search(r'\bhamster\b',positive):result.append('动物主体')
    if '持物与道具互动' not in parents and '持物与道具互动' not in result:
        for part in parts:
            for m in re.finditer(r'\b(?:holds?|holding|grips?|gripping|clutches|clutching)\s+(?:up\s+)?(?:[a-z-]+\s+){0,6}(?:mug|bowl|spoon|fan|clutch)\b',part):
                before=part[:m.start()]
                if not before.strip() or re.search(r'\b(?:she|he|woman|man|girl|boy|character|figure|hands?|fingers?)\b[^.;!?]{0,70}$',before):
                    result.append('持物与道具互动');return result
            if re.search(r'\b(?:smartphone|phone|mug|bowl|spoon|fan|clutch|book|cup)\s+(?:is\s+)?held in (?:her|his|their) (?:left |right )?hands?\b',part):
                result.append('持物与道具互动');return result
    return result
