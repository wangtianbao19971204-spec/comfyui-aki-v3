"""Offline referent guards; specific omissions remain reviewed data patches."""
import importlib.util
from pathlib import Path
import re

spec=importlib.util.spec_from_file_location('object_boundaries',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_object_boundaries/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
RECALL=previous.RECALL
FALSE_CUES={
 '动物主体':r'\bbird (?:ears?|legs?|tail|charms?)\b|\b(?:butterfly|rabbit) charms?\b|\bpickle pee pump-a-rum crow\b',
 '植物与花园':r'\bflower (?:necklace|hairpin|ornaments?)\b',
 '人工光与发光':r'\bskin glowing\b|\bglowing shelves\b',
 '自然地貌与水域':r'\bsea (?:wind|breeze)\b',
 '天空与天气':r'\bnight wear\b',
 '拥抱与日常互动':r'\b(?:leggings|pants|sleeves) hug\b',
 '体型与肤色':r'\bheel is slender\b|\bslender heels?\b|\bslender jade-like fingers\b|\brendering across skin\b',
 '服装材质与剪裁':r'\bsilk chaise lounge\b|\bwhite gauze curtains\b',
 '奇幻与角色服饰':r'\band costume\b(?=;|,)',
}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent,pattern in FALSE_CUES.items():
        if parent not in parents:continue
        if parent == '人工光与发光' and not re.search(r'\b(?:sunlight|sun|daylight|natural light|afternoon rays)\b', positive):continue
        remaining=re.sub(pattern,' ',positive)
        if remaining==positive:continue
        independent_foliage = parent == '植物与花园' and bool(re.search(r'\btropical foliage fills\b|\bbackground\b[^.!?]{0,180}\bgreenery\b', refinements._scene_text(remaining)))
        if independent_foliage or refinements.extract_refinements(remaining,[parent]) or parent in previous.additions(remaining,[p for p in parents if p!=parent],refinements):
            result.pop(parent,None)
        else:result[parent]={'reason':'The cue describes a body part, ornament, garment fit, local material or rendering subject, with no independent parent evidence.'}
    protections={
        '人工光与发光':r'\b(?:streetlights|warm interior lighting|light from the shop|glowing eyes)\b',
        '传统与民族服饰':r'\bancient chinese (?:woman|man) wears\b[^.!?;]{0,80}\brobe\b|\bchinese traditional outfit\b',
        '服装材质与剪裁':r'\b(?:high collar|three-quarter sleeves|side slits)\b',
        '体型与肤色':r'\bpale complexion\b',
        '自然地貌与水域':r'\b(?:seaside rocky path|distant coastline)\b',
    }
    for parent,pattern in protections.items():
        if parent in result and re.search(pattern,positive):result.pop(parent)
    return result

def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    rejected=candidates(body,parents+found,refinements)
    return [p for p in found if p not in rejected]
