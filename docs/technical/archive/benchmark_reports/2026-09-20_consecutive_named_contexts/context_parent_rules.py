"""Reviewed contextual repairs; lack of a child match is never removal evidence."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('motion_parent_contexts',Path(__file__).resolve().parent.parent/'2026-09-20_consecutive_motion_recall/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
BAD={
 '头饰与发饰':[r'\bguilty crown\b'],
 '城市与街道':[r'\burban (?:life(?:style)?|moment|nightlife|fashion|style|vibe|feel|aesthetic|chic)\b',r'\bstreet photography\b'],
 '视角与透视':[r'\b(?:natural )?light\s+(?:shines|streams)\s+from an?\s+(?:upward|downward) angle\b'],
 '绘画与插画':[r'\bpencil skirt\b',r'\b(?:draw(?:ing|s)?|drew)\s+(?:the\s+)?(?:eye|eyes|attention|focus|viewer|gaze)\b'],
}
SUPPORT={**previous.SUPPORT,
 '头饰与发饰':previous.SUPPORT['头饰与发饰']+r'|\b(?:hairclip|hairpin|hairpins)\b',
 '城市与街道':previous.SUPPORT['城市与街道']+r'|\b(?:subway|metro|tram|asphalt|park|distant building silhouettes)\b',
}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent in parents:
        remaining=positive;cues=[]
        for pattern in BAD.get(parent,[]):
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            result[parent]={'false_cues':cues,'reason':'Named title, mood or lighting context; no independent visual evidence for this parent.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent,pattern in [
        ('上衣与外套',r'\b(?:long[ -]sleeved?|short[ -]sleeved?|sleeveless) (?:turtleneck |high-neck |knit )?top\b'),
        ('上衣与外套',r'\bblazer\b'),
        ('裙装与礼服',r'\bshirt[ -]?dress\b'),
        ('泳装与内衣',r'\bbralette\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    return result
